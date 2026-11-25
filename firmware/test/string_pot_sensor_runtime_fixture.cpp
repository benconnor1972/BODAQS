#include "AS5600StringPotSensorBase.h"
#include "BdqV2Catalog.h"
#include <cassert>
#include <fstream>
#include <vector>
#include <cmath>

struct LoggerConfig {};
uint32_t micros() {return 1000;}
int64_t esp_timer_get_time() {return 2000;}
static bool configMutable=true,calibrationSaveOk=true;
static unsigned calibrationWrites=0;
class ConfigManager {
public:
  static bool configurationMutable(){return configMutable;}
  static bool saveSensorParamsByName(const char*,const char* const*,const String*,size_t count){
    if(!calibrationSaveOk)return false;
    calibrationWrites+=count;
    return true;
  }
  static bool saveSensorParamByName(const char*,const char*,const String&) {return true;}
};
// ACTUAL_SENSOR
// ACTUAL_BASE_FUNCTIONS

class TestSensor:public AS5600StringPotSensorBase {
public:
  TestSensor(const BaseParams& params,bool analog):AS5600StringPotSensorBase(params),analog_(analog) {}
  void begin() override {onLoggingStart();}
  mutable unsigned reads=0;
protected:
  int readWrappedCountsOnce() const override {++reads;return 42;}
  bool hasAnalogWrapSettling() const override {return analog_;}
private:
  bool analog_;
};

class TestI2C final:public TestSensor {
public:
  explicit TestI2C(const BaseParams& params):TestSensor(params,false) {}
  bool acquireAsyncSample_() const;
  void asyncMissedServiceSlots(uint64_t);
  void sampleValues(float*,uint8_t) override;
  // ACTUAL_I2C_SNAPSHOT
  mutable bool m_haveLastGoodWrapped=false,m_lastReadOk=true,m_lastReadReused=false;
  bool valid=true,m_includeAngleColumn=true,m_haveDiagnostics=true,m_includeDiagColumns=true,m_asyncLoggingActive=true;
  uint8_t m_lastStatus=32,m_lastAgc=3;
  uint16_t m_lastMagnitude=999;
  mutable uint32_t m_readFailures=0,m_diagnosticReadFailures=0,m_asyncNextSeq=0;
  mutable uint64_t m_lastRawAcquiredUs=0;
  mutable AsyncSnapshot published;
  bool readWrappedCountsDirectOnce_(int& count) const {
    ++reads;count=42;m_lastReadOk=valid;
    if(valid) {m_haveLastGoodWrapped=true;m_lastRawAcquiredUs=1000;} else ++m_readFailures;
    return valid;
  }
  bool readAngleRegister_(uint16_t& angle) const {++reads;angle=1000;return true;}
  void updateReadTransition_(bool) const {}
  void publishAsyncSnapshot_(const AsyncSnapshot& snapshot) const {published=snapshot;}
  bool copyAsyncSnapshot_(AsyncSnapshot& snapshot) const {snapshot=published;return published.have;}
  bool refreshDiagnostics_(bool) const {assert(false);return false;}
protected:
  bool hasCountAuxiliary() const override {return true;}
};
// ACTUAL_I2C_ACQUISITION
// ACTUAL_I2C_SAMPLING
// ACTUAL_I2C_MISSED_SLOTS

int main(int argc,char** argv) {
  assert(argc==2);
  AS5600StringPotSensorBase::BaseParams params;
  params.name="travel";params.assumeTurn0AtStart=false;params.sensorFullCount=4096;params.sensorFullTravelMm=100;
  TestSensor observed(params,true), control(params,true);
  LoggerConfig config;char error[120]={};
  assert(observed.prepareLoggingStart(config,500,error,sizeof error));
  assert(control.prepareLoggingStart(config,500,error,sizeof error));
  assert(observed.startLoggingSession(error,sizeof error) && control.startLoggingSession(error,sizeof error));
  const int counts[]={4090,2000,1000,3};
  for(unsigned i=0;i<4;++i) {
    observed.publishAcquisitionCounts(counts[i],1000+i*2000,0,i);
    control.publishAcquisitionCounts(counts[i],1000+i*2000,0,i);
    for(unsigned preview=0;preview<100;++preview) {
      char unit[16];float value=0, values[3]={};
      assert(observed.readPreviewValue(OutputMode::RAW,value,unit,sizeof unit));
      (void)observed.readPreviewValue(OutputMode::LINEAR,value,unit,sizeof unit);
      (void)observed.currentRawCounts();observed.sampleValues(values,3);
    }
  }
  assert(!observed.reads && !control.reads);
  observed.loop();assert(!observed.reads); // Control/UI loop cannot acquire while recording.
  assert(observed.currentRawCounts()==4099);
  observed.onLoggingStop();control.onLoggingStop();
  BdqV2StreamDescriptor descriptor;
  assert(observed.describeBdqV2Stream(2,descriptor) && descriptor.source.recordSizeBytes==24);
  const auto bytes=BdqV2Catalog::measure("host",&descriptor,1);
  std::vector<char> json(bytes+1);size_t written=0;
  assert(BdqV2Catalog::write("host",&descriptor,1,json.data(),json.size(),written));
  std::ofstream(std::string(argv[1])+".catalog.json",std::ios::binary).write(json.data(),written);
  auto a=descriptor.source;
  BdqV2StreamDescriptor second;assert(control.describeBdqV2Stream(3,second));auto b=second.source;
  std::ofstream records(std::string(argv[1])+".records",std::ios::binary);
  uint8_t left[24],right[24];unsigned rows=0;
  while(a.popRecord(a.context,left,sizeof left)) {
    assert(b.popRecord(b.context,right,sizeof right) && !memcmp(left,right,sizeof left));
    records.write(reinterpret_cast<const char*>(left),sizeof left);++rows;
  }
  assert(rows==4 && !b.pendingRecords(b.context));records.close();
  assert(observed.pendingLoggingRows()==0);
  SensorRuntimeDiagnostics diagnostics;
  assert(observed.describeRuntimeDiagnostics(diagnostics) && diagnostics.hasBdqV2Stream);
  assert(diagnostics.bdqV2RecordsEnqueued==4 && diagnostics.bdqV2RecordsDequeued==4 && !diagnostics.bdqV2RecordsDropped);
  observed.onLoggingFinalized();observed.loop();assert(observed.reads==1);
  assert(observed.startLoggingSession(error,sizeof error));
  observed.publishAcquisitionCounts(100,10000,0,0);
  assert(a.popRecord(a.context,left,sizeof left) && BdqV2Format::getU32(left+20)==2);
  assert(BdqV2Format::getU16(left+14)&StringPotCountStream::Reset);
  observed.onLoggingStop();observed.onLoggingFinalized();
  TestI2C i2c(params);
  assert(i2c.prepareLoggingStart(config,500,error,sizeof error) && i2c.startLoggingSession(error,sizeof error));
  assert(i2c.acquireAsyncSample_());
  assert(i2c.describeBdqV2Stream(4,descriptor));
  assert(descriptor.source.recordSizeBytes==40);
  uint8_t auxiliary[40]={};auto digital=descriptor.source;
  assert(digital.popRecord(digital.context,auxiliary,sizeof auxiliary));
  assert(BdqV2Format::getU32(auxiliary)==0 && BdqV2Format::getU16(auxiliary+12)==42);
  assert(BdqV2Format::getU16(auxiliary+24)==1000 && auxiliary[26]==32 && auxiliary[27]==3);
  assert(BdqV2Format::getU16(auxiliary+28)==999 && BdqV2Format::getU16(auxiliary+30)==7);
  const auto digitalReads=i2c.reads;
  float preview=0;char units[12];
  for(unsigned i=0;i<100;++i) {
    assert(i2c.readPreviewValue(OutputMode::RAW,preview,units,sizeof units));
    float extras[11]={};i2c.sampleValues(extras,11);
  }
  assert(i2c.reads==digitalReads);
  i2c.valid=false;assert(!i2c.acquireAsyncSample_());
  assert(digital.popRecord(digital.context,auxiliary,sizeof auxiliary));
  assert(BdqV2Format::getU32(auxiliary)==1 && BdqV2Format::getU32(auxiliary+4)==2000);
  assert(BdqV2Format::getU16(auxiliary+8)&32);
  assert(BdqV2Format::getU16(auxiliary+30)==6 && BdqV2Format::getU32(auxiliary+32)==1);
  i2c.onLoggingStop();i2c.onLoggingFinalized();i2c.m_asyncLoggingActive=false;
  const auto stoppedReads=i2c.reads;float idle[11]={};i2c.sampleValues(idle,11);
  assert(i2c.reads==stoppedReads);
  TestI2C skipped(params);
  assert(skipped.prepareLoggingStart(config,500,error,sizeof error) && skipped.startLoggingSession(error,sizeof error));
  assert(skipped.acquireAsyncSample_());
  skipped.asyncMissedServiceSlots(1);
  assert(skipped.acquireAsyncSample_());
  assert(skipped.describeBdqV2Stream(5,descriptor));auto missed=descriptor.source;
  assert(missed.popRecord(missed.context,auxiliary,sizeof auxiliary));
  assert(missed.popRecord(missed.context,auxiliary,sizeof auxiliary));
  assert(BdqV2Format::getU32(auxiliary)==2);
  assert((BdqV2Format::getU16(auxiliary+14)&12)==12); // Gap and retained uncertainty, without a read failure.
  assert((BdqV2Format::getU16(auxiliary+8)&9)==9);
  skipped.onLoggingStop();skipped.onLoggingFinalized();
  TestSensor calibrating(params,false);
  calibrating.setOutputMode(OutputMode::LINEAR);
  const auto originalCalibration=calibrating.calibration();
  assert(calibrating.beginCalibration(CalMode::RANGE));
  assert(calibrating.updateCalibration(100) && calibrating.updateCalibration(200));
  configMutable=false;
  assert(!calibrating.finishCalibration(true) && !calibrating.beginCalibration(CalMode::ZERO));
  configMutable=true;calibrationSaveOk=false;
  assert(!calibrating.finishCalibration(true));
  assert(calibrating.calibration().scale==originalCalibration.scale && calibrationWrites==0);
  calibrationSaveOk=true;
  assert(calibrating.finishCalibration(true) && calibrationWrites==2);
  assert(fabs(calibrating.calibration().scale-1.0f)<1e-6f);

}
