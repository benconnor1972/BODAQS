#define millis stubArduinoMillis
#include "CanMasterManager.h"
#include "SensorInventory.h"
#include "SensorRegistry.h"
#undef millis
#include <cassert>
#include <cstdio>
#include <cstring>
#define main commonApplyRegressionMain
#include "test_apply.cpp"
#undef main
static uint32_t clockMs=100, randomWord=100;
static bool zeroEntropy=false;
static bool spiAvailable=true, recording=false, muted=false, dropCommit=false, dropInspection=false, corruptReplies=false;
static unsigned commitAttempts=0, sensorAttempts=0;
uint32_t millis() { return clockMs; }
uint32_t micros() { return clockMs*1000; }
uint32_t esp_random() { return zeroEntropy ? 0 : ++randomWord; }
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
static Fixture node, secondNode;
static bool secondFitted=false, secondSilent=false;
static uint64_t nodeUid=0x1234;
static BodaqsMasterService master;
static BodaqsControlSnapshot snapshot, secondSnapshot;
uint8_t LoggerConfig::sensorCount() const { return 1; }
bool LoggerConfig::getSensorSpec(uint8_t i,SensorSpec& spec) const { if(i) return false; spec=saved; return true; }
const LoggerConfig& ConfigManager::get() { return config; }
namespace LoggingManager { bool isRunning() { return recording; } bool configurationLocked() { return recording; } }
namespace SensorManager {
enum class DiscoveryReason:uint8_t {TransportUpdate};
bool getMuted(uint8_t,bool& value) { value=muted; return true; }
void clearRemoteDiscoveryObservations() {}
void discoverHardware(DiscoveryReason) {}
bool setRemoteProviderObservation(const SensorProviderObservation&) { return true; }
bool setRemoteEndpointObservation(const SensorEndpointObservation&) { return true; }
}
static int sensorIo(void* context,bool write,uint8_t address,uint8_t* value,uint32_t deadline) { ++sensorAttempts; return Registers::io(context,write,address,value,deadline); }
static uint64_t rng(void*) { return 0x12345678; }
namespace SharedSpiBus {
bool begin(const board::SPIProfile&) { return spiAvailable; }
bool transfer(int8_t,const SPISettings&,const uint8_t*tx,uint8_t*rx,size_t length,uint32_t) {
 if(!spiAvailable) return false;
 assert(length==84);
 assert(bodaqs_master_service_process_slot(&master,tx,rx)==BODAQS_MASTER_SLOT_PROCESSED);
 uint8_t address,bytes[64];uint16_t transaction,decoded;BodaqsControlRecord q,r;
 if(bodaqs_control_exchange_transmit(&master.control,clockMs,&address,&transaction,bytes)) {
  assert(address<2 && bodaqs_control_decode_can(bytes,64,false,&decoded,&q));
  if(address==1 && secondSilent) return true;
  auto& peer=address ? secondNode : node;
  auto& peerSnapshot=address ? secondSnapshot : snapshot;
  assert(bodaqs_control_authority_process(&peer.authority,&peer.view,&q,clockMs,rng,nullptr,&r) ||
   bodaqs_control_apply_process(&peer.apply,&q,clockMs,&r) ||
   bodaqs_control_snapshot_process(&peerSnapshot,&peer.view,&q,clockMs,&r) ||
   bodaqs_control_node_process(&peer.view,&q,&r));
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
 records[0].endpoint_mask=1;records[0].hardware_uid=nodeUid;
 if(secondFitted) { records[1].flags=1;records[1].boot_id=secondNode.view.boot_id;
 records[1].endpoint_mask=1;records[1].hardware_uid=0x5678; }
 bodaqs_master_service_set_inventory(&master,1,records,4);
}
static void advance(unsigned ms) {
 for(unsigned t=0;t<ms;++t) { ++clockMs; node.now=clockMs;
  bodaqs_control_apply_tick(&node.apply,clockMs);
  bodaqs_control_apply_tick(&secondNode.apply,clockMs);
  bodaqs_control_exchange_tick(&master.control,clockMs);
  CanMasterManager::loop();
 }
}
static void reconcile() {
 for(unsigned t=0;t<40000 && !CanMasterManager::configurationReconciled(0);t+=100) advance(100);
 if(!CanMasterManager::configurationReconciled(0)) {
  const auto& d=CanMasterManager::diagnostics(); const auto& n=d.control.nodes[0];
  fprintf(stderr,"time%u session%llu nodeactive%llu bound%d phase%u authreason%u next%u apply%u kind%u reason%u current%d state%u gen%llu accepted%llu\n",clockMs,(unsigned long long)d.authority.session,(unsigned long long)n.active_session,d.authority.nodes[0].bound,d.authority.nodes[0].phase,d.authority.nodes[0].reason,d.authority.nodes[0].next_mutation,d.apply.phase,d.apply.nodes[0].kind,d.apply.nodes[0].reason,n.endpoints[0].current,n.endpoints[0].effective[4],(unsigned long long)d.desiredGeneration[0],(unsigned long long)bodaqs_control_get_u64(n.endpoints[0].effective+24));
 }
 assert(CanMasterManager::configurationReconciled(0));
}
static void captureWithUid(void* context,const BodaqsControlNode* view,uint8_t endpoint,bool effective,uint8_t* bytes) {
 bodaqs_control_apply_capture(context,view,endpoint,effective,bytes);
 if(!effective) bodaqs_control_put_u64(bytes+40,context==&node.apply ? nodeUid : 0x5678);
}
static void rebootNode(uint32_t boot) {
 node.view={};node.view.boot_id=boot;node.view.endpoint_mask=1;node.view.endpoint_epoch[0]=1;
 node.authority={};node.regs.reset();
 bodaqs_imu_disabled_init(&node.backend,sensorIo,nullptr,&node.regs);
 bodaqs_control_apply_init(&node.apply,&node.authority,&node.view,&node.backend);
 snapshot={};snapshot.capture=captureWithUid;snapshot.capture_context=&node.apply;
 inventory();assert(CanMasterManager::probeNow());
}
int main(int argc,char**) {
 if(argc>1) clockMs=0xffff0000u;
 saved.type=SensorType::LSM6DSO32XImu;
 assert(savedParams.set("provider","can:0") && savedParams.set("endpoint","imu") &&
   savedParams.set("profile","imu6_3333_32g_2000dps_v1") && savedParams.set("mount_point","rear"));
 saved.params.bind(&savedParams);
 node.view.active_session=0;node.view.flags=0;node.authority={};
 BodaqsMasterIdentity identity={};identity.capabilities=7;identity.hardware_uid=20;
 identity.minimum_protocol_version=identity.maximum_protocol_version=1;
 bodaqs_master_service_init(&master,&identity);bodaqs_control_exchange_init(&master.control,99);
 snapshot.capture=captureWithUid;snapshot.capture_context=&node.apply;
 inventory();
 board::BoardProfile profile={};profile.can_fd_master.supported=true;
 profile.can_fd_master.cs_pin=5;profile.can_fd_master.spi_bus_index=0;
 config.canMasterMode=CanMasterMode::Auto;
 CanMasterManager::begin(profile,config);reconcile();
 auto session=CanMasterManager::diagnostics().authority.session;
 auto operation=CanMasterManager::diagnostics().authority.nodes[0].next_mutation;
 auto resets=node.regs.resets;
 spiAvailable=false;assert(!CanMasterManager::probeNow());
 assert(!CanMasterManager::configurationReconciled(0));
 assert(CanMasterManager::diagnostics().control.nodes[0].endpoints[0].effective_valid);
 spiAvailable=true;assert(CanMasterManager::probeNow());reconcile();
 assert(CanMasterManager::diagnostics().authority.session==session);
 assert(CanMasterManager::diagnostics().authority.nodes[0].next_mutation>=operation);
 assert(node.regs.resets==resets);
 bodaqs_control_exchange_init(&master.control,100);
 assert(CanMasterManager::probeNow());
 assert(CanMasterManager::diagnostics().authority.session!=session);
 reconcile();
 auto fresh=CanMasterManager::diagnostics().authority.session;
 assert(bodaqs_control_get_u64(CanMasterManager::diagnostics().control.nodes[0].endpoints[0].effective+144)==fresh);
 assert(node.regs.resets==resets);
 assert(CanMasterManager::probeNow());assert(CanMasterManager::diagnostics().authority.session==fresh);
 // Same-boot stale inventory preserves scope and permits a DIFFERENT desired payload.
 inventory(false);assert(CanMasterManager::probeNow());
 assert(!CanMasterManager::configurationReconciled(0));
 inventory();assert(CanMasterManager::probeNow());reconcile();
 operation=CanMasterManager::diagnostics().authority.nodes[0].next_mutation;
 muted=true;CanMasterManager::scheduleConfigurationReconciliation();
 advance(100);reconcile();
 assert(CanMasterManager::diagnostics().authority.nodes[0].next_mutation>operation);
 assert(node.authority.high_water>=operation);
 // Node reboot invalidates old proof, retaining its original provenance until recaptured.
 const auto oldBoot=CanMasterManager::diagnostics().control.nodes[0].endpoints[0].effective_boot;
 rebootNode(8);
 assert(!CanMasterManager::configurationReconciled(0));
 assert(CanMasterManager::diagnostics().control.nodes[0].endpoints[0].effective_boot==oldBoot);
 reconcile();assert(CanMasterManager::diagnostics().control.nodes[0].endpoints[0].effective_boot==8);
 assert(!strcmp(savedParams.get("mount_point"),"rear"));
 // Hardware succeeds despite ALL three COMMIT replies being lost; inspection can also fail.
 const auto beforeLostResets=node.regs.resets;
 commitAttempts=0;dropCommit=dropInspection=true;
 muted=false;CanMasterManager::scheduleConfigurationReconciliation();advance(18000);
 assert(commitAttempts==3);
 dropCommit=dropInspection=false;reconcile();
 assert(node.regs.resets==beforeLostResets+1);
 // Repeated failed SPI slots and malformed peer replies cannot freeze ownership.
 spiAvailable=false;advance(8000);spiAvailable=true;advance(8000);reconcile();
 corruptReplies=true;advance(8000);corruptReplies=false;advance(8000);reconcile();
 // Persistent sensor failure retains historical evidence and has a bounded retry interval.
 node.regs.spi_failure=true;muted=true;
 CanMasterManager::scheduleConfigurationReconciliation();advance(15000);
 auto faultAttempts=sensorAttempts;advance(10000);assert(sensorAttempts==faultAttempts);
 const auto& fault=CanMasterManager::diagnostics().control.nodes[0].endpoints[0];
 assert(fault.effective[4]==3 && bodaqs_control_get_u32(fault.effective+16)!=0);
 assert(!CanMasterManager::configurationReconciled(0));
 node.regs.spi_failure=false;advance(31000);reconcile();
 // Confirmed replacement requires a new master powered interval; saved metadata remains owned here.
 const auto oldUid=CanMasterManager::diagnostics().control.nodes[0].endpoints[0].effective_uid;
 nodeUid=0x9999;
 bodaqs_control_exchange_init(&master.control,101);rebootNode(9);
 assert(CanMasterManager::diagnostics().control.nodes[0].endpoints[0].effective_uid==oldUid);
 reconcile();assert(CanMasterManager::diagnostics().control.nodes[0].endpoints[0].effective_uid==0x9999);
 assert(!strcmp(savedParams.get("mount_point"),"rear"));
 // Node reset during staging/commit never adopts old replies or strands the arbiter.
 for(unsigned phase: {2u,4u}) {
  muted=!muted;CanMasterManager::scheduleConfigurationReconciliation();
  unsigned elapsed=0;
  while(CanMasterManager::diagnostics().apply.phase!=phase && elapsed<60000) { advance(100);elapsed+=100; }
  assert(elapsed<60000);
  rebootNode(node.view.boot_id+1);reconcile();
 }
 // A silent, independently fitted node must not suppress healthy endpoint recovery.
 secondNode.view.active_session=0;secondNode.view.flags=0;secondNode.authority={};
 secondNode.view.boot_id=17;
 secondSnapshot.capture=captureWithUid;secondSnapshot.capture_context=&secondNode.apply;
 secondFitted=secondSilent=true;inventory();assert(CanMasterManager::probeNow());
 muted=!muted;CanMasterManager::scheduleConfigurationReconciliation();advance(100);reconcile();
 secondSilent=false;
 for(unsigned t=0;t<60000 && !CanMasterManager::configurationReconciled(1);t+=100) advance(100);
 assert(CanMasterManager::configurationReconciled(1));
 // Entropy failure on a confirmed new master excludes control with stable diagnostics.
 zeroEntropy=true;bodaqs_control_exchange_init(&master.control,102);
 assert(CanMasterManager::probeNow());advance(10000);
 assert(!CanMasterManager::diagnostics().authority.session);
 assert(!CanMasterManager::configurationReconciled(0));
 assert(!strcmp(CanMasterManager::controlShortStatus(),"C:!"));
 puts("production manager outage/restart/lost-result/sensor/independent-peer recovery passed");
}
