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
static unsigned millisReadsToAdvance;
static bool spiAvailable=true, recording=false, muted=false;
static bool starting=false;
// Synthetic clock option for sustained acquisition/control fixtures. This is
// an injected service-cost example, never a physical timing qualification.
static bool fastMeasurementClock=false;
static bool fixedMeasurementClock=false;
static uint32_t measurementSlots=0;
static std::vector<uint8_t> submitted;
uint32_t millis() {
 if(millisReadsToAdvance && --millisReadsToAdvance==0) ++clockMs;
 return clockMs;
}
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
#if BODAQS_MEASUREMENT_VERSION >= 4
static BodaqsMasterWindowStorage fixtureWindow;
#endif
static BodaqsControlSnapshot snapshot;
uint8_t LoggerConfig::sensorCount() const { return 1; }
bool LoggerConfig::getSensorSpec(uint8_t i,SensorSpec& spec) const { if(i) return false; spec=saved; return true; }
const LoggerConfig& ConfigManager::get() { return config; }
// Integrated recording scenarios use an already accepted configuration. The
// real migration owner and its storage failures have a separate runtime seam.
bool ConfigManager::migrationPending() {return false;}
String ConfigManager::configurationBlocker() {return String();}
namespace LoggingManager { bool isRunning() { return recording; } bool configurationLocked() { return recording || starting; } }
namespace SensorManager {
enum class DiscoveryReason:uint8_t {TransportUpdate};
bool getMuted(uint8_t,bool& value) { value=muted; return true; }
void clearRemoteDiscoveryObservations() {}
void discoverHardware(DiscoveryReason) {}
bool setRemoteProviderObservation(const SensorProviderObservation&) { return true; }
bool setRemoteEndpointObservation(const SensorEndpointObservation&) { return true; }
}
static uint8_t preloaded[BODAQS_MASTER_TRANSFER_BYTES];
// Model saturation of the real one-slot RX queue: every other physical slot
// arrives before the main-loop owner has freed its previous queue entry.
static bool alternateRxLoss=false;
static unsigned physicalSlots;
static bool dropOrdinaryControlAck=false;
static unsigned droppedControlAcks;
static bool loseExitStageRequest=false,loseExitStageReply=false,loseExitConfirmReply=false;
static unsigned lostExitStages=0,lostExitReplies=0,lostExitConfirms=0;
static bool loseExitConfirmRequest=false;
static unsigned expiredExitReservations=0;
static bool delayStatusResponses=false;
static bool deferFenceStatus=false,haveDeferredFenceStatus=false;
static unsigned deferredFenceStatuses=0,ordinaryFenceStatuses=0;
static uint8_t deferredFenceStatus[BODAQS_MEASUREMENT_BYTES];
static unsigned delayedResponseDepth=8;
struct DelayedSpiSlot {uint8_t bytes[BODAQS_MASTER_TRANSFER_BYTES];};
static std::vector<DelayedSpiSlot> delayedSpiSlots;
static bool loseMeasurementReplies=false;
static bool dropDataFragmentOnce=false;
static unsigned droppedDataFragments;
static uint8_t droppedFragmentIndex=1;
static bool loseBridgeReplies=false;
static bool strandOrdinaryReply=false;
static bool delayRenewalWire=false,replayRenewalWire=false;
static uint32_t delayedRenewalObject=0;
static std::vector<DelayedSpiSlot> renewalWire;
static bool allowMalformedMeasurement=false;
static uint32_t dropBindReplyUntil=0;
namespace SharedSpiBus {
bool begin(const board::SPIProfile&) { return spiAvailable; }
bool transfer(int8_t,const SPISettings& settings,const uint8_t*tx,uint8_t*rx,size_t length,uint32_t,uint32_t startSpacingUs=0,uint32_t csSetupUs=0,SpiTransactionContext* context=nullptr) {
 if(context) { *context={};context->valid=true;context->cs=4;context->previousCs=10;context->previousValid=true; }
#if defined(BODAQS_MEASUREMENT_CS_SETUP_US)
 assert(csSetupUs==(length==BODAQS_MEASUREMENT_BYTES?BODAQS_MEASUREMENT_CS_SETUP_US:0));
#else
 assert(csSetupUs==0);
#endif
#if defined(BODAQS_MEASUREMENT_START_SPACING_US)
 assert(startSpacingUs==(length==BODAQS_MEASUREMENT_BYTES?BODAQS_MEASUREMENT_START_SPACING_US:0));
#else
 assert(startSpacingUs==0);
#endif
 if(!spiAvailable) return false;
 if(!fixedMeasurementClock && (length!=BODAQS_MEASUREMENT_BYTES || !fastMeasurementClock || ++measurementSlots%10==0)) ++clockMs;
 assert(length==BODAQS_MEASUREMENT_BYTES || length==84);
 if(length==BODAQS_MEASUREMENT_BYTES) assert(settings.hz==BODAQS_MEASUREMENT_HZ);
 memcpy(rx,preloaded,length);
 uint8_t lostAckReplacement[BODAQS_MEASUREMENT_BYTES];BodaqsMeasurementSlot ackSlot={};
 if(length==BODAQS_MEASUREMENT_BYTES && dropOrdinaryControlAck && bodaqs_measurement_decode(tx,BODAQS_MEASUREMENT_BYTES,&ackSlot) &&
    (ackSlot.kind==5 || ackSlot.kind==14) && ackSlot.node==0 && ackSlot.body[0]==3) {
  dropOrdinaryControlAck=false;++droppedControlAcks;
  ackSlot={};ackSlot.node=255;ackSlot.context=master.measurement.mode.context;
  assert(bodaqs_measurement_encode(&ackSlot,lostAckReplacement,BODAQS_MEASUREMENT_BYTES));
  tx=lostAckReplacement;
  // Another lane's empty response can occupy MISO when this ACK is lost.
  // Do not hand the host an immediate duplicate that would repair the ACK.
  memcpy(rx,lostAckReplacement,BODAQS_MEASUREMENT_BYTES);
 }
 if(length==84 && loseExitStageRequest) {
  BodaqsMasterFrame stage={};
  if(bodaqs_master_decode_slot(tx,length,&stage)==BODAQS_MASTER_DECODE_OK && static_cast<unsigned>(stage.type)==9) {
   ++lostExitStages;return true;
  }
 }
 if(length==BODAQS_MEASUREMENT_BYTES && loseExitConfirmRequest) {
  BodaqsMeasurementSlot confirm={};
  if(bodaqs_measurement_decode(tx,length,&confirm) && confirm.kind==9) {++lostExitConfirms;return true;}
 }
 if(alternateRxLoss && (++physicalSlots%2)==0) return true;
 uint8_t next[BODAQS_MASTER_TRANSFER_BYTES];
 const auto slotResult=bodaqs_master_service_process_transfer(&master,tx,length,clockMs,next);
 if(master.measurement.mode.phase==4 && master.measurement.mode.reason==12) ++expiredExitReservations;
 if(slotResult!=BODAQS_MASTER_SLOT_PROCESSED && !allowMalformedMeasurement)
  std::fprintf(stderr,"malformed at%u length%u kind%u phase%u context%llu\n",clockMs,unsigned(length),tx[3],master.measurement.mode.phase,(unsigned long long)master.measurement.mode.context);
 assert(slotResult==BODAQS_MASTER_SLOT_PROCESSED ||
   (allowMalformedMeasurement && length==BODAQS_MEASUREMENT_BYTES && slotResult==BODAQS_MASTER_SLOT_MALFORMED));
 if(delayStatusResponses && length==BODAQS_MEASUREMENT_BYTES) {
  DelayedSpiSlot queued={};memcpy(queued.bytes,next,BODAQS_MASTER_TRANSFER_BYTES);delayedSpiSlots.push_back(queued);
  if(delayedSpiSlots.size()>delayedResponseDepth) {
   memcpy(preloaded,delayedSpiSlots.front().bytes,BODAQS_MASTER_TRANSFER_BYTES);delayedSpiSlots.erase(delayedSpiSlots.begin());
  }
 } else memcpy(preloaded,next,BODAQS_MASTER_TRANSFER_BYTES);
 uint8_t address,payload[64]; uint16_t transaction;
 if(bodaqs_master_service_control_transmit(&master,clockMs,&address,&transaction,payload)) {
  BodaqsControlRecord request,reply;uint16_t decoded;
  assert(bodaqs_control_decode_can(payload,64,false,&decoded,&request));
  assert(bodaqs_control_node_process(&node.view,&request,&reply));
  assert(bodaqs_master_service_control_receive(&master,address,transaction,&reply));
 }
 if(length==84 && loseExitStageReply) {
  BodaqsMasterFrame reply={};
  if(bodaqs_master_decode_slot(rx,length,&reply)==BODAQS_MASTER_DECODE_OK && static_cast<unsigned>(reply.type)==0x89) {
   memset(rx,0,length);++lostExitReplies;
  }
 }
 if(length==BODAQS_MEASUREMENT_BYTES && loseExitConfirmReply) {
  BodaqsMeasurementSlot reply={};
  if(bodaqs_measurement_decode(rx,length,&reply) && reply.kind==6 && reply.body[32]==0) {
   memset(rx,0,length);++lostExitConfirms;
  }
 }
 if(length==BODAQS_MEASUREMENT_BYTES && loseMeasurementReplies) memset(rx,0,length);
 if(length==BODAQS_MEASUREMENT_BYTES && dropDataFragmentOnce) {
  BodaqsMeasurementSlot fragment={};
  if(bodaqs_measurement_decode(rx,BODAQS_MEASUREMENT_BYTES,&fragment) && fragment.kind==2 && fragment.index==droppedFragmentIndex) {
   dropDataFragmentOnce=false;++droppedDataFragments;
   const uint64_t context=fragment.context;fragment={};fragment.context=context;fragment.node=255;
   assert(bodaqs_measurement_encode(&fragment,rx,BODAQS_MEASUREMENT_BYTES));
  }
 }
 if(length==BODAQS_MEASUREMENT_BYTES && loseBridgeReplies) {
  BodaqsMeasurementSlot bridge={};
  if(bodaqs_measurement_decode(rx,BODAQS_MEASUREMENT_BYTES,&bridge) && bridge.kind==11) {
    bridge={};bridge.node=255;bridge.context=master.measurement.mode.context;
    assert(bodaqs_measurement_encode(&bridge,rx,BODAQS_MEASUREMENT_BYTES));
  }
 }
 if(length==BODAQS_MEASUREMENT_BYTES && (strandOrdinaryReply || delayRenewalWire || replayRenewalWire)) {
  BodaqsMeasurementSlot slot={};
  if(bodaqs_measurement_decode(rx,BODAQS_MEASUREMENT_BYTES,&slot)) {
   bool suppress=strandOrdinaryReply && slot.kind==4 && slot.node==0 && slot.index==1;
   if(delayRenewalWire && slot.kind==12 && slot.node==0) {
    if(slot.index==0 && slot.body[12]==0x27) delayedRenewalObject=slot.object;
    if(delayedRenewalObject && slot.object==delayedRenewalObject) {
     DelayedSpiSlot savedSlot={};memcpy(savedSlot.bytes,rx,BODAQS_MEASUREMENT_BYTES);
     constexpr unsigned renewalFragments=(68+BODAQS_MEASUREMENT_BODY_BYTES-1)/BODAQS_MEASUREMENT_BODY_BYTES;
     if(renewalWire.size()<renewalFragments && slot.index==renewalWire.size()) renewalWire.push_back(savedSlot);
     suppress=renewalFragments==1 || slot.index!=0;
    }
   }
   if(suppress) {BodaqsMeasurementSlot empty={};empty.node=255;empty.context=master.measurement.mode.context;assert(bodaqs_measurement_encode(&empty,rx,BODAQS_MEASUREMENT_BYTES));}
  }
  if(replayRenewalWire && !renewalWire.empty()) {
   memcpy(rx,renewalWire.front().bytes,BODAQS_MEASUREMENT_BYTES);renewalWire.erase(renewalWire.begin());
  }
 }
 if(length==84 && int32_t(clockMs-dropBindReplyUntil)<0) {
  BodaqsMasterFrame legacy={};BodaqsControlWrapped reply={};
  if(bodaqs_master_decode_slot(rx,length,&legacy)==BODAQS_MASTER_DECODE_OK &&
     static_cast<unsigned>(legacy.type)==0x87 &&
     bodaqs_control_decode_wrapped(legacy.payload,legacy.payload_length,&reply) && reply.record.opcode==2)
   memset(rx,0,length);
 }
 if(deferFenceStatus && length==BODAQS_MEASUREMENT_BYTES && master.acquisition_fenced && master.measurement.fenced) {
  BodaqsMeasurementSlot request={},reply={};
  assert(bodaqs_measurement_decode(tx,length,&request));
  if(request.kind==6 && bodaqs_measurement_decode(rx,length,&reply) && reply.kind==6) {
   // Actual status response becomes visible only on a later ordinary SPI slot.
   // The selected physical response window is asynchronous to the inspector.
   memcpy(deferredFenceStatus,rx,length);haveDeferredFenceStatus=true;++deferredFenceStatuses;
   reply={};reply.node=255;reply.context=master.measurement.mode.context;
   assert(bodaqs_measurement_encode(&reply,rx,length));
  } else if(request.kind!=6 && haveDeferredFenceStatus) {
   memcpy(rx,deferredFenceStatus,length);haveDeferredFenceStatus=false;++ordinaryFenceStatuses;
  }
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
#if BODAQS_MEASUREMENT_VERSION >= 4
 assert(bodaqs_master_service_bind_window(&master,&fixtureWindow));
#endif
 snapshot={};snapshot.capture=bodaqs_control_apply_capture;snapshot.capture_context=&node.apply;
 inventory();profile={};profile.can_fd_master.supported=true;
 profile.can_fd_master.cs_pin=5;profile.can_fd_master.spi_bus_index=0;
 config.canMasterMode=CanMasterMode::Auto;
 CanMasterManager::begin(profile,config);
}
static unsigned bridgeObservations;
static uint32_t bridgeClock(void*,uint32_t* epoch) {++bridgeObservations;*epoch=7;return 987654;}
static void mixedReceptionDrain(unsigned turns,bool loseFragment=false,unsigned evidenceBurst=1,unsigned responseLag=1,uint8_t lostIndex=1) {
 // Controlled host schedule, not a physical throughput qualification: bounded SPI
 // turns/ms, 2 five-sample CAN packets/3ms and an evidence event/100ms.
 // Probe evidence first so a shared empty-probe timer starves the sample head.
 reset();assert(CanMasterManager::enterMeasurementMode(123,456));
 master.acquisition_record[0]=123;master.acquisition_boot[0]=node.view.boot_id;
 master.acquisition_fenced=0;master.anchor_boot[0]=node.view.boot_id;master.anchor_epoch[0]=1;
 static CanMasterManager::MeasurementTransport drain;
 drain={};
 CanMasterManager::MeasurementInbox* initial=nullptr;
 for(unsigned i=0;i<2;++i) (void)CanMasterManager::serviceMeasurementTransport(drain,4,0,initial);
 const uint32_t initialFailedSlots=CanMasterManager::diagnostics().measurementTiming.failedSlots;
 master.anchor_boot[0]=node.view.boot_id;master.anchor_epoch[0]=1;
 fixedMeasurementClock=true;
 assert(responseLag>=1 && responseLag<=8);
 delayStatusResponses=responseLag>1;delayedResponseDepth=responseLag-1;delayedSpiSlots.clear();
 dropDataFragmentOnce=loseFragment;droppedDataFragments=0;droppedFragmentIndex=lostIndex;
 unsigned sequence=0,received=0,produced=0;
 auto drainTurn=[&](unsigned slot) {
  CanMasterManager::MeasurementInbox* completed=nullptr;
  (void)CanMasterManager::serviceMeasurementTransport(drain,slot%4==0?2:slot%4==3?4:1,0,completed);
  if(completed && completed->state.cls<=2) {
   received+=bodaqs_measurement_get(completed->bytes+12,2);
   CanMasterManager::releaseMeasurementObject(*completed);
  }
 };
 for(unsigned ms=0;ms<(evidenceBurst>1?10000:1000);++ms) {
  ++clockMs;
  if(ms%3==0) for(unsigned i=0;i<2;++i) {
   uint8_t sample[64]={};bodaqs_measurement_put(sample,sequence,2);sample[2]=1;sample[3]=5;sequence+=5;
   (void)bodaqs_master_service_receive_can(&master,0,1,0x100,sample,64,0,clockMs*1000,clockMs);
   ++produced;
  }
  if(ms%100==0) for(unsigned eventIndex=0;eventIndex<evidenceBurst;++eventIndex) {
   const uint8_t event[8]={1,4,1,0,0,0,0,0};
   (void)bodaqs_master_service_receive_can(&master,0,2,0x60,event,8,0,clockMs*1000,clockMs);
   ++produced;
  }
  for(unsigned turn=0;turn<turns;++turn) {
   drainTurn(ms*turns+turn);
  }
 }
 std::fprintf(stderr,"mixed drain (%u turns/ms, evidence burst %u, response lag %u): received=%u retained=%u high_water=%u dropped=%lu\n",turns,evidenceBurst,responseLag,received,master.ingress[0].count,master.ingress[0].high_water,(unsigned long)master.ingress[0].dropped);
 assert(master.ingress[0].dropped==0 && !master.loss[0].failed);
 assert(received>600);
 const auto& timing=CanMasterManager::diagnostics().measurementTiming;
 std::fprintf(stderr,"drain budget: slots=%lu duplicates=%lu deferred=%lu,%lu lost_fragment=%u\n",
  (unsigned long)timing.slots,(unsigned long)CanMasterManager::diagnostics().measurementDuplicates,
  (unsigned long)timing.deferrals[0],(unsigned long)timing.deferrals[1],droppedDataFragments);
 assert(timing.slots>600 && timing.elapsedUs>=1000000);
 assert(timing.polls[0] && timing.polls[1] && timing.fragments[0] && timing.fragments[1]);
 assert(timing.failedSlots==initialFailedSlots);
 assert(droppedDataFragments==unsigned(loseFragment));
 // Finish every retained record, then prove idle probes return to 50Hz/class.
 for(unsigned ms=0;ms<300;++ms) {
  ++clockMs;for(unsigned turn=0;turn<turns;++turn) drainTurn(ms*turns+turn);
 }
 assert(received==produced && !master.ingress[0].count && !master.receptions[0].object.complete);
 const uint32_t idlePolls[2]={timing.polls[0],timing.polls[1]};
 for(unsigned ms=0;ms<200;++ms) {
  ++clockMs;for(unsigned turn=0;turn<turns;++turn) drainTurn(ms*turns+turn);
 }
 for(unsigned cls=0;cls<2;++cls) assert(timing.polls[cls]-idlePolls[cls]<=11);
 fixedMeasurementClock=false;
 delayStatusResponses=false;delayedResponseDepth=8;delayedSpiSlots.clear();
}
static void measurementFailureSplit() {
 reset();assert(CanMasterManager::enterMeasurementMode(123,456));
 BodaqsMeasurementSlot request={},response={};request.node=255;request.context=456;
 const auto before=CanMasterManager::diagnostics().measurementTiming;
 spiAvailable=false;
 assert(!CanMasterManager::exchangeMeasurementSlot(request,response));
 auto after=CanMasterManager::diagnostics().measurementTiming;
 assert(after.transferFailedSlots==before.transferFailedSlots+1 && after.decodeFailedSlots==before.decodeFailedSlots);
 spiAvailable=true;preloaded[0]^=0x80; // Valid MOSI; corrupt returned measurement magic.
 assert(!CanMasterManager::exchangeMeasurementSlot(request,response));
 after=CanMasterManager::diagnostics().measurementTiming;
 assert(after.transferFailedSlots==before.transferFailedSlots+1 && after.decodeFailedSlots==before.decodeFailedSlots+1);
 assert(after.failedSlots==after.transferFailedSlots+after.decodeFailedSlots);
 assert(after.decodeReasons[BODAQS_MEASUREMENT_DECODE_MAGIC]==before.decodeReasons[BODAQS_MEASUREMENT_DECODE_MAGIC]+1);
 assert(CanMasterManager::exchangeMeasurementSlot(request,response));
 after=CanMasterManager::diagnostics().measurementTiming;
 assert(after.slots==before.slots+3 && after.failedSlots==before.failedSlots+2);
 puts("actual measurement adapter separates failed bus transfer from invalid reply: PASS");
}
int main() {
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
 reset();ImuFlowDiagnostics::reset(456,clockMs);
 assert(CanMasterManager::enterMeasurementMode(123,456));
 BodaqsMeasurementSlot captureRequest={},captureResponse={};
 captureRequest.node=255;captureRequest.context=456;captureRequest.kind=1;captureRequest.body[0]=1;
 uint8_t rejected[6][256]={};
 for(unsigned i=0;i<6;++i) {
  assert(bodaqs_measurement_encode(&captureResponse,rejected[i],256));
  if(i==0) rejected[i][0]='X';
  else if(i==1) rejected[i][252]^=1;
  else {rejected[i][i==2?239:60]=uint8_t(i+1);
   bodaqs_measurement_put(rejected[i]+252,bodaqs_measurement_crc(rejected[i],252),4);}
  assert(!bodaqs_measurement_decode(rejected[i],256,&captureResponse));
 }
 auto initialSlots=CanMasterManager::diagnostics().measurementTiming.slots;
 const auto initialMagic=CanMasterManager::diagnostics().measurementTiming.decodeReasons[BODAQS_MEASUREMENT_DECODE_MAGIC];
 spiAvailable=false;assert(!CanMasterManager::exchangeMeasurementSlot(captureRequest,captureResponse));spiAvailable=true;
 assert(ImuFlowDiagnostics::liveReplies.count==0);
 for(unsigned i=0;i<6;++i) {
  memcpy(preloaded,rejected[i],256);
  assert(!CanMasterManager::exchangeMeasurementSlot(captureRequest,captureResponse));
 }
 assert(ImuFlowDiagnostics::liveReplies.count==4);
 assert(CanMasterManager::diagnostics().measurementTiming.decodeReasons[BODAQS_MEASUREMENT_DECODE_MAGIC]==initialMagic+1);
 assert(CanMasterManager::diagnostics().measurementTiming.decodeReasons[BODAQS_MEASUREMENT_DECODE_CRC]>=1);
 for(unsigned i=0;i<4;++i) {
  const auto& entry=ImuFlowDiagnostics::liveReplies.entries[i];
  assert(entry.slot==initialSlots+2+i && entry.requestKind==1);
  assert(!memcmp(entry.reply,rejected[i],256));
  assert(entry.bus.valid && entry.bus.cs==4 && entry.bus.previousCs==10);
 }
 assert(CanMasterManager::exchangeMeasurementSlot(captureRequest,captureResponse));
 assert(ImuFlowDiagnostics::liveReplies.count==4);
 const auto reasons=CanMasterManager::diagnostics().measurementTiming;
 ImuFlowDiagnostics::finish(clockMs,micros(),1,6,true,reasons.decodeReasons);
 assert(ImuFlowDiagnostics::finished.measurementDecodeReasons[BODAQS_MEASUREMENT_DECODE_MAGIC]==initialMagic+1);
 memset(ImuFlowDiagnostics::liveReplies.entries[0].reply,0,256);
 assert(!memcmp(ImuFlowDiagnostics::finishedReplies.entries[0].reply,rejected[0],256));
 ImuFlowDiagnostics::reset(789,clockMs);
 assert(!ImuFlowDiagnostics::liveReplies.count && !ImuFlowDiagnostics::finishedReplies.count);
 memcpy(preloaded,rejected[0],256);
 assert(!CanMasterManager::exchangeMeasurementSlot(captureRequest,captureResponse));
 assert(ImuFlowDiagnostics::liveReplies.count==0);
 puts("actual rejected-reply capture: transfer failure exclusion, exact bytes, cap, freeze and reset PASS");
 return 0;
#endif
 measurementFailureSplit();
 mixedReceptionDrain(8);
 mixedReceptionDrain(4);
 mixedReceptionDrain(4,true);
 mixedReceptionDrain(4,false,4);
 mixedReceptionDrain(4,true,4);
 mixedReceptionDrain(4,false,4,2);
 mixedReceptionDrain(4,true,4,2);
 mixedReceptionDrain(4,true,4,2,25); // Lost final fragment of a maximum-sized batch.
 reset();
 assert(CanMasterManager::inspectMeasurementMode());
 assert(CanMasterManager::diagnostics().measurement.phase==0);
 assert(!CanMasterManager::measurementReady());
 assert(CanMasterManager::enterMeasurementMode(123,456));
 assert(CanMasterManager::measurementReady());
 assert(CanMasterManager::diagnostics().measurementTiming.slots<10); // New context resets old counts.
 assert(master.measurement.mode.phase==2 && master.measurement.mode.context==456);
 assert(CanMasterManager::inspectMeasurementMode());
 assert(CanMasterManager::measurementReady());
 // A fenced master may reply after the inspector's four-slot call budget.
 // Repeated calls must eventually accept that fresh correlated observation.
 assert(master.measurement.quiescent && master.measurement.fenced);
 delayStatusResponses=true;
 assert(!CanMasterManager::inspectMeasurementMode()); // Preloaded status is not fresh proof.
 clockMs+=301;
 assert(!CanMasterManager::inspectMeasurementMode()); // Expired token must be replaced.
 bool inspected=false;
 for(unsigned attempt=0;attempt<8 && !inspected;++attempt)
  inspected=CanMasterManager::inspectMeasurementMode();
 assert(inspected && CanMasterManager::measurementReady());
 delayStatusResponses=false;delayedSpiSlots.clear();
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
 loseBridgeReplies=true;
 CanMasterManager::serviceMeasurementTransport(transport,5,255,bridgeInbox);
 const uint32_t expiringToken=transport.bridgeToken;
 clockMs+=300;
 CanMasterManager::serviceMeasurementTransport(transport,5,255,bridgeInbox);
 assert(!transport.bridgePending && transport.bridgeReady && transport.bridgeExpired && transport.bridgeToken==expiringToken);
 loseBridgeReplies=false;transport.timingEnabled=false;
 const auto slots=master.slots_received;
 advance(1000);
 assert(master.slots_received==slots); // active mode suppresses legacy background polling
 // A lost link must establish a fresh, fully bound status before returning
 // data. A short same-boot outage preserves the immutable caller bank.
 loseMeasurementReplies=true;
 CanMasterManager::MeasurementInbox* resumed=nullptr;
 transport.inboxes[0][0].requestedFragments=0x3ffffff;
 transport.inboxes[1][3].requestedFragments=0x3ffffff;
 const uint32_t retainedMask=transport.inboxes[1][3].state.mask;
 assert(CanMasterManager::serviceMeasurementTransport(transport,1,0,resumed)==0);
 clockMs+=40;loseMeasurementReplies=false;
 assert(CanMasterManager::serviceMeasurementTransport(transport,1,0,resumed)>=0);
 assert(!transport.inboxes[0][0].requestedFragments && !transport.inboxes[1][3].requestedFragments);
 assert(transport.inboxes[1][3].state.mask==retainedMask);
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
 // A permanently missing predecessor on node0 must not pin every poll after
 // its successor times out. Node1 data and ordinary replies still progress.
 reset();assert(CanMasterManager::enterMeasurementMode(123,456));
 static CanMasterManager::MeasurementTransport stranded;
 BodaqsControlWrapped query={};query.master_boot_id=99;query.node_address=0;
 query.record.opcode=BODAQS_CONTROL_GET_NODE_STATE;query.record.endpoint=255;
 query.record.node_boot_id=node.view.boot_id;query.record.operation=902;
 query.record.session=CanMasterManager::diagnostics().measurement.session;
 strandOrdinaryReply=true;
 assert(CanMasterManager::queueMeasurementControl(stranded,query,CanMasterManager::nextMeasurementObjectId(3,0)));
 for(unsigned i=0;i<100;++i) {++clockMs;CanMasterManager::serviceMeasurementTransport(stranded,3,0,resumed);}
 query.record.operation=903;
 assert(CanMasterManager::queueMeasurementControl(stranded,query,CanMasterManager::nextMeasurementObjectId(3,0)));
 master.discovery[1].flags=1;master.discovery[1].boot_id=node.view.boot_id;
 master.acquisition_record[1]=123;master.acquisition_boot[1]=node.view.boot_id;master.acquisition_fenced &= ~2u;
 const uint8_t event[8]={1,4,1,0,0,0,0,0};
 assert(bodaqs_master_service_receive_can(&master,1,2,0x061,event,8,0,12345,clockMs));
 query.node_address=1;query.record.operation=904;
 assert(CanMasterManager::queueMeasurementControl(stranded,query,CanMasterManager::nextMeasurementObjectId(3,1)));
 bool healthyData=false,healthyControl=false;
 for(unsigned i=0;i<1000 && !(healthyData && healthyControl);++i) {
  ++clockMs;
  int r=CanMasterManager::serviceMeasurementTransport(stranded,i%2?2:3,1,resumed);
  if(r==1) {
   healthyData|=resumed->state.cls==2 && resumed->state.node==1;
   healthyControl|=resumed->state.cls==3 && resumed->state.node==1;
   CanMasterManager::releaseMeasurementObject(*resumed);
  }
 }
 assert(healthyData && healthyControl);
 strandOrdinaryReply=false;
 puts("production logger/master pipelined mode, exit, read-only status and lost-reply tests passed");
}
