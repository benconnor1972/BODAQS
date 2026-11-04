#define millis stubArduinoMillis
#include "CanMasterManager.h"
#include "SensorInventory.h"
#include "SensorRegistry.h"
#undef millis
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include <new>
#define main commonApplyRegressionMain
#include "test_apply.cpp"
#undef main
static uint32_t clockMs=100, randomWord=100;
static bool spiAvailable=true, recording=false, muted=false;
static bool starting=false;
static std::vector<uint8_t> submitted;
uint32_t millis() { return clockMs; }
uint32_t micros() { return clockMs*1000; }
uint32_t esp_random() { return ++randomWord; }
void delayMicroseconds(uint32_t) {}
void pinMode(uint8_t,int) {}
void digitalWrite(uint8_t,int) {}
int digitalRead(uint8_t) { return 1; }
enum {OUTPUT,INPUT_PULLUP,INPUT,HIGH=1,LOW=0,MSBFIRST=0,SPI_MODE0=0,SPI_MODE1=1,SPI_MODE2=2,SPI_MODE3=3};
struct SPISettings { uint32_t hz; SPISettings(uint32_t h,int,int):hz(h) {} };
namespace SensorRegistry { bool registerType(SensorType,const char*,const char*,ParamDefsFn,CreateFn,CalModeMask) {return true;} }
static LoggerConfig config;
static SensorSpec saved;
static ParamStore savedParams;
static Fixture node;
static BodaqsMasterService master;
static BodaqsControlSnapshot snapshot;
uint8_t LoggerConfig::sensorCount() const { return 1; }
bool LoggerConfig::getSensorSpec(uint8_t i,SensorSpec& spec) const { if(i) return false; spec=saved; return true; }
const LoggerConfig& ConfigManager::get() { return config; }
namespace LoggingManager { bool isRunning() { return recording; } bool configurationLocked() { return recording || starting; } }
namespace SensorManager {
enum class DiscoveryReason:uint8_t {TransportUpdate};
bool getMuted(uint8_t,bool& value) { value=muted; return true; }
void clearRemoteDiscoveryObservations() {}
void discoverHardware(DiscoveryReason) {}
bool setRemoteProviderObservation(const SensorProviderObservation&) { return true; }
bool setRemoteEndpointObservation(const SensorEndpointObservation&) { return true; }
}
static uint8_t preloaded[84];
static bool loseMeasurementReplies=false;
namespace SharedSpiBus {
bool begin(const board::SPIProfile&) { return spiAvailable; }
bool transfer(int8_t,const SPISettings& settings,const uint8_t*tx,uint8_t*rx,size_t length,uint32_t) {
 if(!spiAvailable) return false;
 ++clockMs;
 assert(length==64 || length==84);
 if(length==64) assert(settings.hz==8000000);
 memcpy(rx,preloaded,length);
 uint8_t next[84];
 assert(bodaqs_master_service_process_transfer(&master,tx,length,clockMs,next)==BODAQS_MASTER_SLOT_PROCESSED);
 memcpy(preloaded,next,84);
 if(length==64 && loseMeasurementReplies) memset(rx,0,length);
 return true;
}
}
// PRODUCTION_MANAGER
static void inventory(bool available=true) {
 BodaqsMasterDiscoveryRecord records[4]={};
 for(uint8_t i=0;i<4;++i) records[i].node_address=i;
 records[0].flags=available?1:3;records[0].boot_id=node.view.boot_id;
 records[0].endpoint_mask=1;records[0].hardware_uid=0x1234;
 bodaqs_master_service_set_inventory(&master,1,records,4);
}
static void advance(unsigned ms) {
 for(unsigned t=0;t<ms;++t) { ++clockMs; node.now=clockMs;
  bodaqs_control_apply_tick(&node.apply,clockMs);
  bodaqs_control_exchange_tick(&master.control,clockMs);
  CanMasterManager::loop();
 }
}

static board::BoardProfile profile;
static void reset() {
 CanMasterManager::endRecordingHandoff();
 node.~Fixture(); new (&node) Fixture;
 node.view.active_session=0;node.view.flags=0;node.authority={};
 recording=starting=false;spiAvailable=true;submitted.clear();
 BodaqsMasterIdentity identity={};identity.capabilities=15;identity.hardware_uid=20;
 identity.minimum_protocol_version=identity.maximum_protocol_version=1;
 bodaqs_master_service_init(&master,&identity);bodaqs_control_exchange_init(&master.control,99);
 snapshot={};snapshot.capture=bodaqs_control_apply_capture;snapshot.capture_context=&node.apply;
 inventory();profile={};profile.can_fd_master.supported=true;
 profile.can_fd_master.cs_pin=5;profile.can_fd_master.spi_bus_index=0;
 config.canMasterMode=CanMasterMode::Auto;
 CanMasterManager::begin(profile,config);
}
int main() {
 reset();
 assert(CanMasterManager::inspectMeasurementMode());
 assert(CanMasterManager::diagnostics().measurement.phase==0);
 assert(!CanMasterManager::measurementReady());
 assert(CanMasterManager::enterMeasurementMode(123,456));
 assert(CanMasterManager::measurementReady());
 assert(master.measurement.mode.phase==2 && master.measurement.mode.context==456);
 assert(CanMasterManager::inspectMeasurementMode());
 assert(CanMasterManager::measurementReady());
 const auto slots=master.slots_received;
 advance(1000);
 assert(master.slots_received==slots); // active mode suppresses legacy background polling
 assert(CanMasterManager::exitMeasurementMode());
 assert(!CanMasterManager::measurementReady() && master.measurement.mode.phase==0);
 assert(CanMasterManager::inspectMeasurementMode());
 reset(); loseMeasurementReplies=true;
 const auto began=clockMs;
 assert(!CanMasterManager::enterMeasurementMode(789,987));
 assert(clockMs-began>=1000 && clockMs-began<1010);
 assert(master.measurement.mode.phase==2); // reply loss cannot authorize the logger
 assert(!CanMasterManager::measurementReady());
 loseMeasurementReplies=false;
 assert(CanMasterManager::inspectMeasurementMode());
 assert(!CanMasterManager::measurementReady()); // inspection never grants acquisition
 // Observing a foreign context or reboot revokes previous confirmation.
 reset();
 assert(CanMasterManager::enterMeasurementMode(111,222));
 assert(CanMasterManager::measurementReady());
 master.measurement.mode.context=333;
 assert(CanMasterManager::inspectMeasurementMode());
 assert(!CanMasterManager::measurementReady());
 puts("production logger/master pipelined mode, exit, read-only status and lost-reply tests passed");
}
