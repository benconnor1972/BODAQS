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
// Synthetic clock option for sustained acquisition/control fixtures. This is
// an injected service-cost example, never a physical timing qualification.
static bool fastMeasurementClock=false;
static uint32_t measurementSlots=0;
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
static bool allowMalformedMeasurement=false;
static uint32_t dropBindReplyUntil=0;
namespace SharedSpiBus {
bool begin(const board::SPIProfile&) { return spiAvailable; }
bool transfer(int8_t,const SPISettings& settings,const uint8_t*tx,uint8_t*rx,size_t length,uint32_t) {
 if(!spiAvailable) return false;
 if(length!=64 || !fastMeasurementClock || ++measurementSlots%10==0) ++clockMs;
 assert(length==64 || length==84);
 if(length==64) assert(settings.hz==8000000);
 memcpy(rx,preloaded,length);
 uint8_t next[84];
 const auto slotResult=bodaqs_master_service_process_transfer(&master,tx,length,clockMs,next);
 assert(slotResult==BODAQS_MASTER_SLOT_PROCESSED ||
   (allowMalformedMeasurement && length==64 && slotResult==BODAQS_MASTER_SLOT_MALFORMED));
 memcpy(preloaded,next,84);
 uint8_t address,payload[64]; uint16_t transaction;
 if(bodaqs_master_service_control_transmit(&master,clockMs,&address,&transaction,payload)) {
  BodaqsControlRecord request,reply;uint16_t decoded;
  assert(bodaqs_control_decode_can(payload,64,false,&decoded,&request));
  assert(bodaqs_control_node_process(&node.view,&request,&reply));
  assert(bodaqs_master_service_control_receive(&master,address,transaction,&reply));
 }
 if(length==64 && loseMeasurementReplies) memset(rx,0,length);
 if(length==84 && int32_t(clockMs-dropBindReplyUntil)<0) {
  BodaqsMasterFrame legacy={};BodaqsControlWrapped reply={};
  if(bodaqs_master_decode_slot(rx,length,&legacy)==BODAQS_MASTER_DECODE_OK &&
     static_cast<unsigned>(legacy.type)==0x87 &&
     bodaqs_control_decode_wrapped(legacy.payload,legacy.payload_length,&reply) && reply.record.opcode==2)
   memset(rx,0,length);
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
 BodaqsMasterIdentity identity={};identity.capabilities=15;identity.hardware_uid=20;
 identity.minimum_protocol_version=identity.maximum_protocol_version=1;
 bodaqs_master_service_init(&master,&identity);bodaqs_control_exchange_init(&master.control,99);
 snapshot={};snapshot.capture=bodaqs_control_apply_capture;snapshot.capture_context=&node.apply;
 inventory();profile={};profile.can_fd_master.supported=true;
 profile.can_fd_master.cs_pin=5;profile.can_fd_master.spi_bus_index=0;
 config.canMasterMode=CanMasterMode::Auto;
 CanMasterManager::begin(profile,config);
}
static unsigned bridgeObservations;
static uint32_t bridgeClock(void*,uint32_t* epoch) {++bridgeObservations;*epoch=7;return 987654;}
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
 BodaqsControlWrapped observed={};
 assert(CanMasterManager::queryMeasurementNodeState(0,node.view.boot_id,77,observed));
 assert(observed.record.opcode==BODAQS_CONTROL_GET_NODE_STATE && observed.record.data_length==24);
 assert(CanMasterManager::diagnostics().measurementObjectsReceived==1);
 // Every SPI exchange receives the previous request's response. Rotate four
 // nodes and protected control so a same-request assumption cannot pass.
 for(uint8_t n=0;n<4;++n) {
  master.discovery[n].flags=1;master.discovery[n].boot_id=node.view.boot_id;
  master.acquisition_record[n]=master.measurement.mode.recording;master.acquisition_boot[n]=node.view.boot_id;master.acquisition_fenced &= ~(1u<<n);
  const uint8_t event[8]={1,4,1,0,0,0,0,0};
  assert(bodaqs_master_service_receive_can(&master,n,2,0x060+n,event,8,0,12345+n,clockMs));
 }
 static CanMasterManager::MeasurementTransport transport;
 BodaqsControlWrapped protectedRequest={};protectedRequest.master_boot_id=99;
 protectedRequest.node_address=0;protectedRequest.record.opcode=0x26;
 protectedRequest.record.endpoint=255;protectedRequest.record.node_boot_id=node.view.boot_id;
 protectedRequest.record.operation=901;
 protectedRequest.record.session=CanMasterManager::diagnostics().measurement.session;
 protectedRequest.record.transfer=9;protectedRequest.record.data_length=16;
 bodaqs_control_put_u64(protectedRequest.record.data,123);
 bodaqs_control_put_u32(protectedRequest.record.data+8,1);
 protectedRequest.record.data[13]=1;
 assert(CanMasterManager::queueMeasurementControl(transport,protectedRequest,
     CanMasterManager::nextMeasurementObjectId(4,0),true));
 uint8_t delivered=0;bool authorizationDelivered=false;
 for(unsigned i=0;i<200 && (delivered!=15 || !authorizationDelivered);++i) {
  CanMasterManager::MeasurementInbox* completed=nullptr;
  const uint8_t n=i%5;
  int result=CanMasterManager::serviceMeasurementTransport(transport,n==4?4:2,n==4?0:n,completed);
  assert(result>=0);
  if(result==1) {
   assert(completed);
   if(completed->state.cls==4) {
    BodaqsControlWrapped reply={};
    assert(bodaqs_control_decode_wrapped(completed->bytes,64,&reply));
    assert(reply.record.operation==901);authorizationDelivered=true;
    CanMasterManager::releaseMeasurementObject(*completed);continue;
   }
   assert(completed->state.cls==2 && completed->state.total==96);
   assert(!(delivered&(1U<<completed->state.node)));
   assert(bodaqs_measurement_get(completed->bytes+20,4)==12345U+completed->state.node);
   delivered|=1U<<completed->state.node;
   CanMasterManager::releaseMeasurementObject(*completed);
  }
 }
 assert(delivered==15 && authorizationDelivered);
 // Drain RAM ACKs, including retained duplicates received while sending ACKs.
 for(unsigned i=0;i<12;++i) {
  CanMasterManager::MeasurementInbox* completed=nullptr;
  assert(CanMasterManager::serviceMeasurementTransport(transport,4,0,completed)>=0);
 }
 // Fresh bridge request owns one immutable L0 and M across pipelined retries.
 master.native_clock=bridgeClock;transport.timingEnabled=true;
 loseMeasurementReplies=true;
 CanMasterManager::MeasurementInbox* bridgeInbox=nullptr;
 for(unsigned i=0;i<5;++i) CanMasterManager::serviceMeasurementTransport(transport,5,255,bridgeInbox);
 const uint64_t originalLower=transport.bridgeLower;
 const uint32_t originalToken=transport.bridgeToken;
 assert(transport.bridgePending && !transport.bridgeReady && bridgeObservations==1);
 clockMs+=50;
 loseMeasurementReplies=false;
 for(unsigned i=0;i<5 && !transport.bridgeReady;++i)
   CanMasterManager::serviceMeasurementTransport(transport,5,255,bridgeInbox);
 assert(transport.bridgeReady && transport.bridgeToken==originalToken);
 assert(transport.bridgeLower==originalLower && transport.bridgeUpper>=originalLower+50000);
 assert(transport.bridgeTick==987654 && transport.bridgeEpoch==7 && bridgeObservations==1);
 transport.bridgeReady=false;transport.bridgeNext=clockMs;
 loseMeasurementReplies=true;
 CanMasterManager::serviceMeasurementTransport(transport,5,255,bridgeInbox);
 const uint32_t expiringToken=transport.bridgeToken;
 clockMs+=300;
 CanMasterManager::serviceMeasurementTransport(transport,5,255,bridgeInbox);
 assert(!transport.bridgePending && transport.bridgeReady && transport.bridgeExpired && transport.bridgeToken==expiringToken);
 loseMeasurementReplies=false;transport.timingEnabled=false;
 const auto slots=master.slots_received;
 advance(1000);
 assert(master.slots_received==slots); // active mode suppresses legacy background polling
 // A lost link must establish a fresh, fully bound status before returning
 // data. A short same-boot outage preserves the immutable caller bank.
 loseMeasurementReplies=true;
 CanMasterManager::MeasurementInbox* resumed=nullptr;
 assert(CanMasterManager::serviceMeasurementTransport(transport,1,0,resumed)==0);
 clockMs+=40;loseMeasurementReplies=false;
 for(unsigned i=0;i<6;++i)
  assert(CanMasterManager::serviceMeasurementTransport(transport,1,0,resumed)>=0);
 assert(!transport.recovering && !transport.failed);
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
 reset();assert(CanMasterManager::enterMeasurementMode(555,666));
 static CanMasterManager::MeasurementTransport deadlineBank;
 loseMeasurementReplies=true;
 assert(CanMasterManager::serviceMeasurementTransport(deadlineBank,1,0,resumed)==0);
 const uint32_t outage=clockMs;
 clockMs=outage+299;
 assert(CanMasterManager::serviceMeasurementTransport(deadlineBank,1,0,resumed)==0);
 clockMs=outage+300;loseMeasurementReplies=false;
 assert(CanMasterManager::serviceMeasurementTransport(deadlineBank,1,0,resumed)==-14);
 assert(CanMasterManager::serviceMeasurementTransport(deadlineBank,1,0,resumed)==-14);
 reset();assert(CanMasterManager::enterMeasurementMode(777,888));
 static CanMasterManager::MeasurementTransport rebootBank;
 loseMeasurementReplies=true;
 assert(CanMasterManager::serviceMeasurementTransport(rebootBank,1,0,resumed)==0);
 loseMeasurementReplies=false;
 bodaqs_control_exchange_init(&master.control,100); // actual confirmed boot change
 bool excluded=false;
 for(unsigned i=0;i<5;++i)
  excluded|=CanMasterManager::serviceMeasurementTransport(rebootBank,1,0,resumed)==-14;
 assert(excluded);
 puts("production logger/master pipelined mode, exit, read-only status and lost-reply tests passed");
}
