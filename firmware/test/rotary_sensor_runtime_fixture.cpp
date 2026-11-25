// Actual rotary acquisition/lifecycle/preview methods are inserted by the runner.
#include <algorithm>
#include <cassert>
#include <cmath>
#include <fstream>
#include <vector>
#include "Arduino.h"
#include "Sensor.h"
#include "RotaryRecordingDescriptor.h"
using std::isfinite;
uint64_t modelTimeUs=1000000;
int64_t esp_timer_get_time(){return modelTimeUs;}
void delayMicroseconds(unsigned){}
struct PreviewBase {
  OutputMode m_mode=OutputMode::RAW;bool m_includeRaw=true;
  char m_outputUnitsLabel[48]="deg";
  float applyTransform(float x) const {return x;}
};
enum class LogFormat {BodaqsMultiStreamBinary};
struct LoggerConfig {uint16_t sampleRateHz=200;LogFormat logFormat=LogFormat::BodaqsMultiStreamBinary;};
class ConfigManager {public:static const LoggerConfig& get(){static LoggerConfig config;return config;}};
class PowerManager {public:static bool analogRailEnabled(){return true;}static bool analogRailFaultActive(){return false;}};
struct I2CTransferPriorityScope {};
class TwoWire {
public:
  uint16_t raw=0,angle=1234;
  uint8_t status=32,agc=7;
  uint16_t magnitude=456;
  bool fail=false;
  unsigned transactions=0;
  uint8_t reg=0;std::vector<uint8_t> reply;size_t next=0;
  void beginTransmission(uint8_t){++transactions;}
  void write(uint8_t r){reg=r;}
  uint8_t endTransmission(bool){return fail?2:0;}
  size_t requestFrom(int,int count){
    ++transactions;reply.clear();next=0;if(fail) return 0;
#if TEST_AS5600
    uint16_t value=(reg==0x0c?raw:reg==0x0e?angle:reg==0x1b?magnitude:0);
    if(count==2) {reply.push_back(value>>8);reply.push_back(value&255);}
    else reply.push_back(reg==0x0b?status:agc);
#else
    uint16_t value=reg==0xfe?raw:magnitude;
    if(count==2) {reply.push_back(value>>6);reply.push_back(value&63);}
    else reply.push_back(reg==0xfb?status:agc);
#endif
    return reply.size();
  }
  int available(){return int(reply.size()-next);}
  int read(){return available()?reply[next++]:-1;}
};
TwoWire wire;
class I2CManager {public:static TwoWire* bus(uint8_t){return &wire;}static bool lock(TwoWire*){return true;}static void unlock(TwoWire*){}};
#define AS5600A_LOGI(...) do{}while(0)
#define AS5600A_LOGW(...) do{}while(0)
#define AS5048_LOGI(...) do{}while(0)
#define AS5048_LOGW(...) do{}while(0)
// ACTUAL_CLASS
// ACTUAL_HELPERS
// ACTUAL_METHODS

int main(int argc,char** argv) {
  assert(argc==2);
  wire.raw=kCountsPerTurn-2;
#if !TEST_AS5600
  wire.status=1;
#endif
  TestRotary::Params params;
  params.name="steering";params.asyncRateHz=200;
#if TEST_AS5600
  params.includeAngleColumn=true;
#endif
  TestRotary sensor(params);char error[120]{};
  assert(sensor.startLoggingSession(error,sizeof error));
  assert(sensor.pendingLoggingRows()==0);
  BdqV2StreamDescriptor descriptor;assert(sensor.describeBdqV2Stream(2,descriptor));
  sensor.asyncSchedulerStarting();
  modelTimeUs+=5000;assert(sensor.asyncAcquire());
  assert(sensor.pendingLoggingRows()==1);
  const auto reads=wire.transactions;
  float out[16]{};float preview=0;char unit[16]{};
  for(unsigned i=0;i<100;++i) {
    sensor.sampleValues(out,16);assert(out[0]==kCountsPerTurn-2);
    assert(sensor.currentRawCounts()==kCountsPerTurn-2);
    assert(sensor.readPreviewValue(OutputMode::RAW,preview,unit,sizeof unit));
    assert(preview==kCountsPerTurn-2);
  }
  assert(wire.transactions==reads && sensor.pendingLoggingRows()==1);
#if TEST_AS5600
  assert(out[1]==1234);
#endif
  // Starting a new calibration cannot reuse a snapshot from its previous wrap epoch.
  sensor.cal_.phase=CalPhase::ACTIVE;sensor.cal_.mode=CalMode::ZERO;
  ++sensor.m_calibrationEpoch;
  assert(sensor.currentRawCounts()==INT32_MIN && wire.transactions==reads);
  // Calibration wrap advances on acquisition only; observing repeatedly cannot change it.
  sensor.cal_.phase=CalPhase::ACTIVE;sensor.cal_.mode=CalMode::ZERO;
  wire.raw=3;modelTimeUs+=5000;assert(sensor.asyncAcquire());
  for(unsigned i=0;i<100;++i) assert(sensor.currentRawCounts()==kCountsPerTurn+3);
  assert(sensor.pendingLoggingRows()==2);
  modelTimeUs+=200000;assert(sensor.currentRawCounts()==INT32_MIN);
  assert(!sensor.readPreviewValue(OutputMode::RAW,preview,unit,sizeof unit));
  sensor.sampleValues(out,16);assert(std::isnan(out[0]));
  wire.fail=true;modelTimeUs+=5000;assert(!sensor.asyncAcquire());
  assert(sensor.currentRawCounts()==INT32_MIN);
  assert(sensor.pendingLoggingRows()==3);
  sensor.asyncMissedServiceSlots(2);
  sensor.asyncSchedulerStopped();sensor.onLoggingStop();
  assert(!sensor.startLoggingSession(error,sizeof error));
  std::vector<uint8_t> bytes;uint8_t row[32];
  while(descriptor.source.popRecord(descriptor.source.context,row,32)) bytes.insert(bytes.end(),row,row+32);
  assert(bytes.size()==96);
  assert(BdqV2Format::getU32(bytes.data())==0);
  assert(BdqV2Format::getU16(bytes.data()+12)==kCountsPerTurn-2);
  assert(BdqV2Format::getU16(bytes.data()+32+12)==3);
  assert(BdqV2Format::getU16(bytes.data()+64+8)&32);
  assert(bytes[64+19]&8);
#if TEST_AS5600
  assert(BdqV2Format::getU16(bytes.data()+14)==1234);
  assert(bytes[19]&2);
#endif
  SensorRuntimeDiagnostics diagnostics;assert(sensor.describeRuntimeDiagnostics(diagnostics));
  assert(diagnostics.bdqV2RecordsEnqueued==3 && diagnostics.bdqV2RecordsDequeued==3);
  size_t size=BdqV2Catalog::measure("fixture",&descriptor,1),length=0;
  std::vector<char> json(size+1);assert(BdqV2Catalog::write("fixture",&descriptor,1,json.data(),json.size(),length));
  std::ofstream(std::string(argv[1])+".catalog.json")<<json.data();
  std::ofstream records(std::string(argv[1])+".records",std::ios::binary);records.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());records.close();
  sensor.onLoggingFinalized();wire.fail=false;wire.raw=7;modelTimeUs+=1000000;
  assert(sensor.startLoggingSession(error,sizeof error));assert(sensor.pendingLoggingRows()==0);
  modelTimeUs+=5000;assert(sensor.asyncAcquire());assert(sensor.pendingLoggingRows()==1);
  assert(descriptor.source.popRecord(descriptor.source.context,row,32));
  assert(BdqV2Format::getU32(row)==0 && BdqV2Format::getU16(row+12)==7);
  sensor.onLoggingStop();sensor.onLoggingFinalized();assert(sensor.pendingLoggingRows()==0);
}
