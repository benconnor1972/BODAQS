#include <cassert>
#include <cmath>
#include <fstream>
#include <vector>
#include "Arduino.h"
// The hardware harness delivers PVT messages at the existing acquisition seam.
// Private access injects the external receiver; assertions use public outputs only.
#define private public
#include "DANF10NGpsSensor.h"
#undef private
#include "BdqV2Catalog.h"
#if !defined(ESP32)
using BaseType_t=int;
#endif
struct LoggerConfig {};
namespace board {
constexpr unsigned BOARD_MAX_UART_PORTS=2;
struct Uart {bool present=true;int rx=1,tx=2;};
struct Board {unsigned uart_count=2;Uart uart[2];};
Board profile;Board* gBoard=&profile;
}
class HardwareSerial {public:void end(){} void begin(uint32_t,int,int,int){} void setRxBufferSize(size_t){} int available(){return 0;} int read(){return -1;}};
HardwareSerial Serial1,Serial2;
constexpr int SERIAL_8N1=0,COM_TYPE_UBX=1,VAL_LAYER_RAM=1;
uint32_t micros(){return uint32_t(millis())*1000;}
class SFE_UBLOX_GNSS_SERIAL {
public:
 bool fix=true,date=true,time=true;
 bool begin(HardwareSerial&,uint16_t){return true;}
 bool getPVT(int){return false;}
 bool setUART1Output(int,int,uint16_t){return true;}
 bool setNavigationFrequency(int,int,uint16_t){return true;}
 bool setAutoPVT(bool,int,uint16_t){return true;}
 bool getGnssFixOk(int){return fix;} bool getInvalidLlh(int){return false;}
 uint8_t getFixType(int){return fix?3:0;} uint8_t getSIV(int){return 12;}
 int32_t getLatitude(int){return -319512345;} int32_t getLongitude(int){return 1158612345;}
 int32_t getAltitudeMSL(int){return -1234;} int32_t getGroundSpeed(int){return 12345;}
 int32_t getHeading(int){return 35912345;}
 uint32_t getHorizontalAccEst(int){return 123;} uint32_t getVerticalAccEst(int){return 456;}
 uint32_t getSpeedAccEst(int){return 789;} uint32_t getHeadingAccEst(int){return 12345;}
 uint32_t getTimeOfWeek(int){return 604799999;} uint32_t getUnixEpoch(int){return 1795478400;}
 bool getDateValid(int){return date;} bool getTimeValid(int){return time;}
};
class SensorRegistry {public:template<class... T> static bool registerType(T...){return true;}};
class WebServerManager {public:static bool isRunning(){return false;}};
class UploadModeManager {public:static bool isActive(){return false;}};
// ACTUAL_SENSOR
// ACTUAL_BASE_FUNCTIONS

static void startupFailureChecks() {
#if defined(ESP32) && BODAQS_PRODUCTION_RECORDING
  const auto allocated=GpsRuntime::liveAllocations;
  {
    DANF10NGpsSensor::Params params;params.name="gps_failure";
    DANF10NGpsSensor sensor(params);char error[120]{};
    GpsRuntime::failTask=true;
    sensor.begin();
    assert(!sensor.startLoggingSession(error,sizeof error));
    assert(error[0] && sensor.pendingLoggingRows()==0);
    // A failed attempted session still belongs to lifecycle cleanup.
    assert(!sensor.startLoggingSession(error,sizeof error));
    sensor.onLoggingStop();sensor.onLoggingFinalized();
    GpsRuntime::failTask=false;
    assert(sensor.startLoggingSession(error,sizeof error));
    sensor.onLoggingStop();sensor.onLoggingFinalized();assert(sensor.shutdown());
  }
  assert(GpsRuntime::liveAllocations==allocated);
  {
    DANF10NGpsSensor::Params params;params.name="gps_uart_failure";
    DANF10NGpsSensor sensor(params);char error[120]{};
    board::profile.uart[0].present=false;sensor.begin();
    assert(!sensor.startLoggingSession(error,sizeof error));
    assert(error[0] && sensor.pendingLoggingRows()==0);
    sensor.onLoggingStop();sensor.onLoggingFinalized();
    board::profile.uart[0].present=true;
    assert(sensor.startLoggingSession(error,sizeof error));
    sensor.onLoggingStop();sensor.onLoggingFinalized();assert(sensor.shutdown());
  }
  assert(GpsRuntime::liveAllocations==allocated);
  for(auto mode:{DANF10NGpsSensor::DiagnosticMode::Disabled,DANF10NGpsSensor::DiagnosticMode::SerialOnly,
                DANF10NGpsSensor::DiagnosticMode::SleepTask,DANF10NGpsSensor::DiagnosticMode::DrainTask}) {
    DANF10NGpsSensor::Params params;params.name="gps_diagnostic";params.diagnosticMode=mode;
    DANF10NGpsSensor sensor(params);char error[120]{};sensor.begin();
    assert(!sensor.startLoggingSession(error,sizeof error));
    assert(error[0] && sensor.pendingLoggingRows()==0);
    sensor.onLoggingStop();sensor.onLoggingFinalized();assert(sensor.shutdown());
  }
  assert(GpsRuntime::liveAllocations==allocated);
#endif
}

int main(int argc,char** argv) {
  assert(argc==2);
#if !BODAQS_PRODUCTION_RECORDING
  for(auto mode:{DANF10NGpsSensor::DiagnosticMode::Normal,DANF10NGpsSensor::DiagnosticMode::Disabled,
                DANF10NGpsSensor::DiagnosticMode::SerialOnly,DANF10NGpsSensor::DiagnosticMode::SleepTask,
                DANF10NGpsSensor::DiagnosticMode::DrainTask}) {
    DANF10NGpsSensor::Params params;params.diagnosticMode=mode;
    DANF10NGpsSensor sensor(params);char error[120]{};
    GpsRuntime::failTask=true;sensor.begin();
    assert(!sensor.usesBdqV2NativeStream());
    assert(sensor.startLoggingSession(error,sizeof error));
    sensor.onLoggingStop();sensor.onLoggingFinalized();assert(sensor.shutdown());
  }
  GpsRuntime::failTask=false;
  return 0;
#else
  startupFailureChecks();
  DANF10NGpsSensor::Params params;params.name="gps";params.qualityColumns=DANF10NGpsSensor::QualityColumns::Full;
  DANF10NGpsSensor sensor(params);sensor.begin();
  assert(sensor.initializeGnss_());
  LoggerConfig config;char error[120]{};
  assert(sensor.prepareLoggingStart(config,1000,error,sizeof error));
  assert(sensor.startLoggingSession(error,sizeof error));
  BdqV2StreamDescriptor descriptor;assert(sensor.describeBdqV2Stream(2,descriptor));
  sensor.updateSnapshotFromGnss_(sensor.m_sessionGeneration.load()-1);
  assert(sensor.pendingLoggingRows()==0); // missing receiver cannot fabricate a row
  float values[16]{};sensor.sampleValues(values,16);assert(std::isnan(values[0]));
  sensor.updateSnapshotFromGnss_(sensor.m_sessionGeneration.load());
  assert(sensor.pendingLoggingRows()==1);
  for(unsigned i=0;i<100;++i) sensor.sampleValues(values,16);
  assert(sensor.pendingLoggingRows()==1);assert(std::isfinite(values[0]));
  SensorSpec spec;spec.type=SensorType::DANF10NGps;
  assert(!sensor.reconfigureFromSpec(spec));sensor.setMuted(true);assert(!sensor.muted());
  sensor.m_gnss->fix=false;sensor.m_gnss->date=false;sensor.m_gnss->time=false;
  sensor.updateSnapshotFromGnss_(sensor.m_sessionGeneration.load());sensor.sampleValues(values,16);assert(std::isnan(values[0]));
  sensor.m_gnss->fix=true;sensor.updateSnapshotFromGnss_(sensor.m_sessionGeneration.load());
  for(unsigned i=0;i<1600;++i) sensor.sampleValues(values,16);
  assert(std::isnan(values[0])); // stale published data does not become fresh via observation
  sensor.onLoggingStop();sensor.updateSnapshotFromGnss_(sensor.m_sessionGeneration.load());assert(sensor.pendingLoggingRows()==3);
  std::vector<uint8_t> records;uint8_t row[64];
  while(descriptor.source.popRecord(descriptor.source.context,row,64)) records.insert(records.end(),row,row+64);
  assert(records.size()==192);
  assert(BdqV2Format::getU16(records.data()+60)==27);
  assert(BdqV2Format::getU16(records.data()+64+60)==1);
  assert(BdqV2Format::getU32(records.data()+64+52)==0); // unknown UTC
  SensorRuntimeDiagnostics diagnostics;assert(sensor.describeRuntimeDiagnostics(diagnostics));
  assert(diagnostics.bdqV2RecordsEnqueued==3 && diagnostics.bdqV2RecordsDequeued==3);
  size_t size=BdqV2Catalog::measure("fixture",&descriptor,1),length=0;
  std::vector<char> catalog(size+1);assert(BdqV2Catalog::write("fixture",&descriptor,1,catalog.data(),catalog.size(),length));
  std::ofstream(std::string(argv[1])+".catalog.json")<<catalog.data();
  std::ofstream output(std::string(argv[1])+".records",std::ios::binary);output.write(reinterpret_cast<const char*>(records.data()),records.size());
  assert(!sensor.startLoggingSession(error,sizeof error));
  sensor.onLoggingFinalized();assert(sensor.startLoggingSession(error,sizeof error));
  assert(sensor.pendingLoggingRows()==0);sensor.sampleValues(values,16);assert(std::isnan(values[0]));
  sensor.updateSnapshotFromGnss_(sensor.m_sessionGeneration.load());assert(sensor.pendingLoggingRows()==1);
  sensor.onLoggingStop();sensor.onLoggingFinalized();assert(sensor.pendingLoggingRows()==0);
  assert(sensor.shutdown());
#endif
}
