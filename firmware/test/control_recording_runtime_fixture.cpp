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
static bool spiAvailable=true, recording=false, muted=false, dropCommit=false, dropInspection=false, corruptReplies=false;
static unsigned commitAttempts=0;
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
struct SPISettings { SPISettings(uint32_t,int,int) {} };
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
static uint64_t rng(void*) { return 0x12345678; }
namespace SharedSpiBus {
bool begin(const board::SPIProfile&) { return spiAvailable; }
bool transfer(int8_t,const SPISettings&,const uint8_t*tx,uint8_t*rx,size_t length,uint32_t) {
 if(!spiAvailable) return false;
 assert(length==84);
 CanMasterProtocol::Frame request;
 assert(CanMasterProtocol::decodeSlot(tx,84,request)==CanMasterProtocol::DecodeResult::Ok);
 if(request.type==CanMasterProtocol::MessageType::ControlSubmitRequest) {
  BodaqsControlWrapped w;assert(bodaqs_control_decode_wrapped(request.payload,64,&w));
  submitted.push_back(w.record.opcode);
 }
 assert(bodaqs_master_service_process_slot(&master,tx,rx)==BODAQS_MASTER_SLOT_PROCESSED);
 uint8_t address,bytes[64];uint16_t transaction,decoded;BodaqsControlRecord q,r;
 if(bodaqs_control_exchange_transmit(&master.control,clockMs,&address,&transaction,bytes)) {
  assert(address==0 && bodaqs_control_decode_can(bytes,64,false,&decoded,&q));
  assert(bodaqs_control_authority_process(&node.authority,&node.view,&q,clockMs,rng,nullptr,&r) ||
   bodaqs_control_apply_process(&node.apply,&q,clockMs,&r) ||
   bodaqs_control_snapshot_process(&snapshot,&node.view,&q,clockMs,&r) ||
   bodaqs_control_node_process(&node.view,&q,&r));
  assert(bodaqs_control_encode_can(&r,true,transaction,bytes));
  assert(bodaqs_control_decode_can(bytes,64,true,&decoded,&r));
  if(q.opcode==BODAQS_CONTROL_COMMIT_APPLY) ++commitAttempts;
  const bool drop=(dropCommit && q.opcode==BODAQS_CONTROL_COMMIT_APPLY) ||
      (dropInspection && q.opcode==BODAQS_CONTROL_GET_OPERATION);
  if(corruptReplies) r.operation+=10000;
  if(!drop) { const bool received=bodaqs_control_exchange_receive(&master.control,address,decoded,&r); assert(received || corruptReplies); }
 }
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
 BodaqsMasterIdentity identity={};identity.capabilities=7;identity.hardware_uid=20;
 identity.minimum_protocol_version=identity.maximum_protocol_version=1;
 bodaqs_master_service_init(&master,&identity);bodaqs_control_exchange_init(&master.control,99);
 snapshot={};snapshot.capture=bodaqs_control_apply_capture;snapshot.capture_context=&node.apply;
 inventory();profile={};profile.can_fd_master.supported=true;
 profile.can_fd_master.cs_pin=5;profile.can_fd_master.spi_bus_index=0;
 config.canMasterMode=CanMasterMode::Auto;
 CanMasterManager::begin(profile,config);
}
static void atPhase(uint8_t phase,bool pending) {
 for(unsigned t=0;t<40000;++t) {
  const auto& d=CanMasterManager::diagnostics();
  if(d.apply.phase==phase && d.apply.pending==pending) return;
  advance(1);
 }
 fprintf(stderr,"missing phase %u pending%d actual%u/%d\n",phase,pending,CanMasterManager::diagnostics().apply.phase,CanMasterManager::diagnostics().apply.pending);
 assert(false);
}
static void fence(uint8_t phase,bool pending,bool outage) {
 reset();atPhase(phase,pending);
 const bool committed=CanMasterManager::diagnostics().apply.commit_sent;
 const auto operation=CanMasterManager::diagnostics().apply.nodes[0].operation;
 const auto count=submitted.size();
 starting=true;CanMasterManager::beginRecordingHandoff();
 const auto began=clockMs;
 if(outage)spiAvailable=false;
 while(!CanMasterManager::recordingHandoffReady()) {
  advance(1);
  CanMasterManager::beginRecordingHandoff(); // repeated request never extends deadline
  assert(clockMs-began<=5500);
 }
 assert(clockMs-began<=5500);
 if(outage)assert(clockMs-began>=5500);
 for(size_t i=count;i<submitted.size();++i) assert(committed && submitted[i]==0x14);
 assert(!CanMasterManager::diagnostics().apply.phase);
 assert(CanMasterManager::diagnostics().authority.nodes[0].next_mutation>operation);
 const auto after=submitted.size();recording=true;starting=false;spiAvailable=true;advance(7000);
 assert(submitted.size()==after); // no bind/config/rejoin or delayed commit during recording
 assert(!CanMasterManager::diagnostics().apply.phase);
 recording=false;CanMasterManager::endRecordingHandoff();
}
int main() {
 for(uint8_t phase=1;phase<=5;++phase) {
  if(phase>1)fence(phase,false,false);
  fence(phase,true,false);
 }
 fence(1,true,true);fence(4,true,true);fence(5,true,true);
 reset();spiAvailable=false;starting=true;CanMasterManager::beginRecordingHandoff();
 // An absent remote cannot delay a local-only start when there is no owned work.
 assert(CanMasterManager::recordingHandoffReady());
 puts("production manager recording handoff phase/outage/deadline guards passed");
}
