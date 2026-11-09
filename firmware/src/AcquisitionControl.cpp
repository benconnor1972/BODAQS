#include "AcquisitionControl.h"
#include "ImuFlowDiagnostics.h"
#include "../can-fd/common/protocol/bodaqs_control_acquisition.h"
#include "CanMasterManager.h"
#include "../can-fd/common/protocol/bodaqs_control_snapshot.h"
#include <Arduino.h>
#include <string.h>
#include <initializer_list>

#if defined(ARDUINO_ARCH_ESP32)
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/portmacro.h>
#endif

namespace AcquisitionControl {
namespace {
using CanMasterManager::MeasurementInbox;
struct Exchange {
  BodaqsControlWrapped request = {};
  uint32_t object = 0, started = 0;
  bool pending = false;
};
enum class Phase : uint8_t {
  Idle = 0, Begin = 1, PreparePages = 2, InitialProof = 3,
  Commit = 4, SnapshotPages = 5, ReleaseSnapshot = 6
};
struct Peer {
  Request intent;
  Exchange ordinary, protectedLane;
  BodaqsControlWrapped stopRequest={};
  bool stopRequestValid=false;
  uint32_t mutation = 0, renewal = 0, nextRenewal = 0, began = 0;
  uint32_t pendingMutation = 0, nextPoll = 0, waitStarted = 0;
  uint32_t leaseDeadline = 0, proposedDeadline = 0;
  uint32_t proposedWireDeadline = 0;
  uint64_t transfer = 0, recording = 0;
  uint8_t prepare[112] = {}, snapshot[128] = {}, page = 0;
  Phase phase = Phase::Idle;
  bool leased = false;
  bool excluded = false;
  bool observing = false;
  bool monitoring = false;
  bool fenceConfirmed = false;
};
struct Mailbox { Request request; bool pending = false; };
static Peer peers[4];
static Mailbox mailboxes[4];
static Outcome outcomes[4];
static CanMasterManager::MeasurementTransport transport;
static uint64_t recordingId, contextId, session, masterBoot, nextTransfer;
static uint32_t nextRead;
static bool owned = false, enterPending = false, exitPending = false, servicing = false;
static bool cleanupRequested=false;
static uint8_t cursor;
static bool physicalFenceVerified=false;
static uint32_t nextFenceInspection=0;
static FenceDiagnostics fenceSnapshot;
static uint32_t nextFenceSnapshot=0, fenceInspections=0, fenceObservations=0;
static DataConsumer dataConsumer=nullptr;
static uint8_t dataMask=0,dataCursor=0,serviceCursor=0;
static uint32_t nextHealthObservation=0;
static uint8_t healthCursor=0;
#if defined(ARDUINO_ARCH_ESP32)
static TaskHandle_t task = nullptr;
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
struct Lock { Lock() { portENTER_CRITICAL(&mux); } ~Lock() { portEXIT_CRITICAL(&mux); } };
static bool isOwner() { return task && xTaskGetCurrentTaskHandle()==task; }
#else
struct Lock { Lock() {} ~Lock() {} };
static bool isOwner() { return servicing; }
#endif
static bool due(uint32_t now,uint32_t deadline) { return static_cast<int32_t>(now-deadline)>=0; }
static void publishFenceDiagnostics(uint32_t now) {
  if(!due(now,nextFenceSnapshot)) return;
  nextFenceSnapshot=now+100;
  FenceDiagnostics snapshot;
  snapshot.observedMs=now;snapshot.inspections=fenceInspections;snapshot.observations=fenceObservations;
  snapshot.modeFlags=CanMasterManager::diagnostics().measurement.flags;
  snapshot.verified=physicalFenceVerified;snapshot.recovering=transport.recovering;snapshot.failed=transport.failed;
  snapshot.allFenced=true;
  for(uint8_t n=0;n<4;++n) {
    const auto& p=peers[n];
    if(p.recording) {snapshot.recordingMask|=1u<<n;snapshot.allFenced &= p.fenceConfirmed;}
    if(p.fenceConfirmed) snapshot.confirmedMask|=1u<<n;
    if(p.ordinary.pending) snapshot.ordinaryMask|=1u<<n;
    if(p.protectedLane.pending) snapshot.protectedMask|=1u<<n;
    if(p.pendingMutation) snapshot.mutationMask|=1u<<n;
    for(uint8_t lane=0;lane<3;++lane) {
      if(lane==2 && n) continue;
      const auto& in=transport.inboxes[lane==2?4:lane][n];
      auto& out=snapshot.data[lane][n];out.object=in.state.object;out.ackObject=in.pendingAck.object;
      out.flags=(in.state.complete?1u:0u)|(in.admitted?2u:0u)|(in.ackPending?4u:0u);
    }
  }
  Lock lock;
  for(uint8_t n=0;n<4;++n) if(mailboxes[n].pending) snapshot.mailboxMask|=1u<<n;
  snapshot.allFenced &= snapshot.recordingMask && !snapshot.ordinaryMask && !snapshot.protectedMask && !snapshot.mutationMask && !snapshot.mailboxMask;
  fenceSnapshot=snapshot;
}
static uint32_t allocate(uint32_t& value) {
  if (!value || value==UINT32_MAX) {value=0;return 0;}
  return value++;
}
static void publish(uint8_t n,Result result,uint8_t reason=0,const BodaqsControlRecord* reply=nullptr) {
  (void)reply; // Node-wide generic results contain no endpoint revision/epoch.
  if(result==Result::Succeeded && peers[n].intent.action==Action::Fence) peers[n].fenceConfirmed=true;
  if(result==Result::Succeeded && peers[n].intent.action==Action::Start) peers[n].monitoring=true;
  if(peers[n].observing && (result==Result::Pending || result==Result::Succeeded)) {
    if(result==Result::Succeeded) peers[n].observing=false;
    return;
  }
  Lock lock;
  auto& out=outcomes[n];
  ++out.serial;out.action=peers[n].intent.action;out.result=result;out.reason=reason;
  out.leaseAcknowledged=peers[n].leased;
}
static BodaqsControlWrapped request(uint8_t n,uint8_t opcode,uint32_t operation,uint64_t transferId=0) {
  BodaqsControlWrapped q={};q.master_boot_id=masterBoot;q.node_address=n;
  q.record.opcode=opcode;q.record.endpoint=255;q.record.operation=operation;
  q.record.node_boot_id=CanMasterManager::diagnostics().authority.nodes[n].boot;
  q.record.session=session;q.record.transfer=transferId;
  return q;
}
static bool send(uint8_t n,Exchange& exchange,BodaqsControlWrapped q,bool protectedLane) {
  const uint32_t id=CanMasterManager::nextMeasurementObjectId(protectedLane?4:3,n);
  if(!id || !CanMasterManager::queueMeasurementControl(transport,q,id,protectedLane)) return false;
  exchange.request=q;exchange.object=id;exchange.started=millis();exchange.pending=true;
  return true;
}
static void fail(uint8_t n,Result result,uint8_t reason) {

  auto& p=peers[n];p.phase=Phase::Idle;p.ordinary.pending=false;p.pendingMutation=0;
  if(p.observing && (reason==7 || reason==10)) {
    p.observing=false;return; // Busy/aged optional diagnostics are not a node fault.
  }
  if(p.recording && !p.observing) {
    p.excluded=true;p.leased=false;p.protectedLane.pending=false;
    transport.terminalNodes|=1u<<n;
    Lock lock;outcomes[n].excluded=true;outcomes[n].terminal=true;
  }
  publish(n,result,reason);
}
static void exclude(uint8_t n,uint8_t reason) {
  auto& p=peers[n];
  p.excluded=true;p.leased=false;p.observing=false;p.protectedLane.pending=false;
  transport.terminalNodes|=1u<<n;
  {Lock lock;outcomes[n].excluded=true;outcomes[n].terminal=true;}
  fail(n,Result::Unavailable,reason);
}
static bool uncertainStop(uint8_t n,uint8_t reason) {
  auto& p=peers[n];
  if(p.excluded || p.intent.action!=Action::Stop) return false;
  p.leased=false;p.monitoring=false;p.observing=false;
  p.protectedLane.pending=false;p.ordinary.pending=false;p.pendingMutation=0;p.phase=Phase::Idle;
  transport.terminalNodes|=1u<<n;
  {Lock lock;outcomes[n].terminal=true;}
  publish(n,Result::Uncertain,reason);
  return true;
}
static bool retryRenewal(uint8_t n) {
  auto& p=peers[n];const auto& q=p.protectedLane.request.record;
  if(!p.leased || p.excluded || due(millis(),p.leaseDeadline) ||
     !(q.opcode==0x27 || (q.opcode==0x26 && q.data[12]==1))) return false;
  p.protectedLane.pending=false;
  p.nextRenewal=millis()+BODAQS_ACQ_RENEW_MS;
  // Only a matched confirmation changes leaseDeadline. A node may have
  // accepted a proof whose reply was lost; the next fresh attempt is safe.
  return true;
}
static void challenge(uint8_t n,bool initial) {
  auto& p=peers[n];
  if(p.renewal==UINT32_MAX) {exclude(n,22);return;}
  auto q=request(n,0x26,allocate(nextRead),initial?p.transfer:0);
  if(!q.record.operation) {exclude(n,22);return;}
  q.record.data_length=16;
  bodaqs_control_put_u64(q.record.data,p.recording);
  bodaqs_control_put_u32(q.record.data+8,++p.renewal);
  q.record.data[12]=initial?0:1;q.record.data[13]=1;
  if(!send(n,p.protectedLane,q,true)) {
    if(!initial && p.leased && !due(millis(),p.leaseDeadline))
      p.nextRenewal=millis()+BODAQS_ACQ_RENEW_MS;
    else exclude(n,26);
  }
}
static void beginRequest(uint8_t n,const Request& intent,bool observing=false) {
  auto& p=peers[n];p.intent=intent;p.began=millis();p.observing=observing;
  if(!observing) {Lock lock;outcomes[n].snapshotValid=false;}
  if(intent.action==Action::Fence) {
    if(transport.failed || p.excluded) cleanupRequested=true;
    // A fence cancels old scope; it never asserts RAM acceptance. Preserve
    // unaccepted/partial objects until fresh physical retirement is observed.
    Lock lock;outcomes[n].localFenceComplete=false;
  }
  if(intent.action==Action::Stop) {
    // Terminal locally before dispatch. A delayed challenge can never renew.
    p.leased=false;p.monitoring=false;p.protectedLane.pending=false;p.ordinary.pending=false;p.phase=Phase::Idle;p.pendingMutation=0;
    transport.terminalNodes|=1u<<n;
    {Lock lock;outcomes[n].terminal=true;}
    auto& retired=transport.inboxes[3][n];
    if(!retired.state.complete) retired=MeasurementInbox{};
  }
  const uint8_t opcodes[]={0x20,0x24,0x25,0x28,0x2a,0x29};
  if(intent.action==Action::Stop && p.stopRequestValid &&
     p.stopRequest.record.node_boot_id==CanMasterManager::diagnostics().authority.nodes[n].boot &&
     p.stopRequest.record.session==session && bodaqs_control_get_u64(p.stopRequest.record.data)==intent.recording) {
    if(!send(n,p.protectedLane,p.stopRequest,true)) uncertainStop(n,7);
    else publish(n,Result::Pending);
    return;
  }
  uint32_t operation=intent.action==Action::Snapshot?allocate(nextRead):allocate(p.mutation);
  if(!operation) {fail(n,Result::Unavailable,22);return;}
  if(intent.action==Action::Prepare) p.recording=intent.recording;
  auto q=request(n,opcodes[static_cast<unsigned>(intent.action)],operation);
  q.record.data_length=24;bodaqs_control_put_u64(q.record.data,intent.recording);
  if(intent.action==Action::Prepare) {
    if(nextTransfer==UINT64_MAX) {fail(n,Result::Unavailable,22);return;}
    p.transfer=++nextTransfer;p.phase=Phase::Begin;p.page=0;p.renewal=0;
    memset(p.prepare,0,sizeof p.prepare);p.prepare[0]=4;p.prepare[2]=1;p.prepare[4]=112;p.prepare[6]=1;
    bodaqs_control_put_u64(p.prepare+8,intent.recording);
    bodaqs_control_put_u64(p.prepare+16,intent.revision);
    bodaqs_control_put_u64(p.prepare+64,intent.epoch);
    memcpy(q.record.data,p.prepare,16);q.record.transfer=p.transfer;
  } else if(intent.action==Action::Start) {
    bodaqs_control_put_u64(q.record.data+8,intent.epoch);
    bodaqs_control_put_u64(q.record.data+16,intent.revision);
  } else if(intent.action==Action::Stop) q.record.data[8]=intent.reason;
  if(intent.action==Action::Snapshot) q.record.data_length=8;
  if(intent.action==Action::Stop) {p.stopRequest=q;p.stopRequestValid=true;}
  if(!send(n,intent.action==Action::Stop?p.protectedLane:p.ordinary,q,intent.action==Action::Stop)) {
    if(intent.action==Action::Stop && uncertainStop(n,7)) return;
    fail(n,Result::Unavailable,7);return;
  }
  publish(n,Result::Pending);
}
static bool correlated(const Exchange& exchange,const BodaqsControlWrapped& reply) {
  const auto& q=exchange.request;const auto& r=reply.record;
  return exchange.pending && reply.master_boot_id==q.master_boot_id &&
      reply.node_address==q.node_address && r.node_boot_id==q.record.node_boot_id &&
      r.session==q.record.session && r.operation==q.record.operation &&
      r.endpoint==255 && r.page==q.record.page &&
      (r.opcode==q.record.opcode || r.opcode==BODAQS_CONTROL_ERROR) &&
      (q.record.opcode==0x28 || r.transfer==q.record.transfer);
}
static void accept(uint8_t n,bool protectedLane,const BodaqsControlWrapped& wrapped) {
  auto& p=peers[n];auto& x=protectedLane?p.protectedLane:p.ordinary;
  if(!correlated(x,wrapped)) return;
  const auto q=x.request;const auto& r=wrapped.record;x.pending=false;
  if(r.data_length==4) {
    // A master transport receipt is not a node's 24-byte proof/result.
    if(r.data[3]!=q.record.opcode || r.data[0]<BODAQS_CONTROL_BUSY || r.data[0]>BODAQS_CONTROL_UNCERTAIN) {
      exclude(n,1);return;
    }
    if(r.data[0]!=BODAQS_CONTROL_REJECTED && (r.data[1]==7 || r.data[1]==10 || r.data[1]==26)) {
      if(uncertainStop(n,r.data[1]) || (protectedLane && retryRenewal(n))) return;
    }
    fail(n,r.data[0]==BODAQS_CONTROL_UNCERTAIN?Result::Uncertain:Result::Rejected,r.data[1]);return;
  }
  if(r.opcode==BODAQS_CONTROL_ERROR || (r.data_length==24 && r.data[0]==1 &&
      q.record.opcode!=0x26 && q.record.opcode!=0x27 && q.record.opcode!=0x28 && q.record.opcode!=7)) {
    if((r.data[1]==7 || r.data[1]==10 || r.data[1]==26) && uncertainStop(n,r.data[1])) return;
    if(protectedLane && (r.data[1]==7 || r.data[1]==10 || r.data[1]==20 || r.data[1]==26) && retryRenewal(n)) return;
    if(p.recording && (r.data[1]==4 || r.data[1]==27 || r.data[1]==29 || protectedLane)) {
      exclude(n,r.data[1]);return;
    }
    if(protectedLane) p.leased=false;
    if((q.record.opcode==0x20 && p.phase==Phase::Begin) || q.record.opcode==0x24 ||
       q.record.opcode==0x25 || q.record.opcode==0x29 || q.record.opcode==0x2a) {
      if(p.mutation==q.record.operation+1) p.mutation=q.record.operation;
    }
    fail(n,Result::Rejected,r.data[1]);return;
  }
  if(q.record.opcode==0x26) {
    const bool initial=p.phase==Phase::InitialProof;
    if((!initial && !p.leased) || r.data_length!=24 ||
       bodaqs_control_get_u32(r.data+20)!=p.renewal || !bodaqs_control_get_u64(r.data) ||
       static_cast<uint32_t>(bodaqs_control_get_u32(r.data+12)-bodaqs_control_get_u32(r.data+8))!=BODAQS_ACQ_RESPONSE_MS*1000U ||
       static_cast<uint32_t>(bodaqs_control_get_u32(r.data+16)-bodaqs_control_get_u32(r.data+8))!=BODAQS_ACQ_LEASE_MS*1000U) {
      exclude(n,1);return;
    }
    // Node ticks are not logger ticks. Bound transit by local request age.
    if(static_cast<uint32_t>(millis()-x.started)>=BODAQS_ACQ_RESPONSE_MS) {
      if(!retryRenewal(n)) exclude(n,26);
      return;
    }
    p.proposedDeadline=x.started+BODAQS_ACQ_LEASE_MS;
    p.proposedWireDeadline=bodaqs_control_get_u32(r.data+16);
    auto proof=request(n,initial?0x22:0x27,initial?p.ordinary.request.record.operation:q.record.operation,initial?p.transfer:0);
    proof.record.data_length=24;bodaqs_control_put_u64(proof.record.data,p.recording);
    memcpy(proof.record.data+8,r.data,8);bodaqs_control_put_u32(proof.record.data+16,p.renewal);
    if(initial) p.phase=Phase::Commit;
    if(!send(n,initial?p.ordinary:p.protectedLane,proof,!initial) &&
       (initial || !retryRenewal(n))) {p.leased=false;fail(n,Result::Uncertain,26);}
    return;
  }
  if(q.record.opcode==0x27) {
    if(r.data_length==24 && bodaqs_control_get_u64(r.data)==p.recording &&
       bodaqs_control_get_u32(r.data+12)==p.renewal &&
       bodaqs_control_get_u32(r.data+8)==p.proposedWireDeadline) {
      p.leaseDeadline=p.proposedDeadline;
      Lock lock;outcomes[n].leaseAcknowledged=p.leased;
    } else exclude(n,1);
    return;
  }
  if(p.phase==Phase::Begin || p.phase==Phase::PreparePages) {
    p.phase=Phase::PreparePages;
    if(p.page==5) {p.phase=Phase::InitialProof;challenge(n,true);return;}
    auto page=q;page.record.opcode=0x21;page.record.page=p.page;
    page.record.data_length=p.page==4?16:24;memset(page.record.data,0,24);
    memcpy(page.record.data,p.prepare+24*p.page,page.record.data_length);++p.page;
    if(!send(n,p.ordinary,page,false)) fail(n,Result::Uncertain,26);
    return;
  }
  if(q.record.opcode==0x28) {
    if(r.data_length!=24 || r.data[0]!=5 || r.data[2]!=1 || r.data[4]!=128 || r.data[5] || !r.transfer) {
      fail(n,Result::Rejected,1);return;
    }
    p.transfer=r.transfer;p.page=0;p.phase=Phase::SnapshotPages;
  }
  if(p.phase==Phase::SnapshotPages) {
    if(q.record.opcode==7) {
      const uint8_t length=p.page==5?8:24;
      if(r.data_length!=length) {fail(n,Result::Rejected,1);return;}
      memcpy(p.snapshot+24*p.page,r.data,length);++p.page;
    }
    auto page=request(n,p.page==6?8:7,q.record.operation,p.transfer);
    page.record.page=p.page==6?0:p.page;
    if(p.page==6) p.phase=Phase::ReleaseSnapshot;
    if(!page.record.operation || !send(n,p.ordinary,page,false)) fail(n,Result::Uncertain,26);
    return;
  }
  if(p.phase==Phase::ReleaseSnapshot) {
    if(!bodaqs_control_descriptor_valid(p.snapshot,128,5,255) ||
       bodaqs_control_get_u32(p.snapshot+24)!=r.node_boot_id ||
       (p.intent.recording && bodaqs_control_get_u64(p.snapshot+8)!=p.intent.recording)) {
      fail(n,Result::Rejected,1);return;
    }
    {Lock lock;memcpy(outcomes[n].snapshot,p.snapshot,128);outcomes[n].snapshotValid=true;
      outcomes[n].revision=bodaqs_control_get_u64(p.snapshot+72);
      outcomes[n].epoch=bodaqs_control_get_u64(p.snapshot+64);}
    // A current node-issued snapshot is observational: it cannot grant a lease
    // or rejoin a participant excluded by boot, bus-off or lease expiry.
    if(p.leased && (bodaqs_control_get_u64(p.snapshot+16)!=session ||
       !(bodaqs_control_get_u32(p.snapshot+28)&1u) || p.snapshot[60])) {
      exclude(n,p.snapshot[60]?p.snapshot[60]:29);return;
    }
    p.phase=Phase::Idle;publish(n,Result::Succeeded);return;
  }
  if(q.record.opcode==0x22 && (r.data[0]==2 || r.data[0]==3)) {
    p.leased=true;p.leaseDeadline=p.proposedDeadline;p.nextRenewal=millis()+BODAQS_ACQ_RENEW_MS;p.phase=Phase::Idle;
  }
  if(r.data_length!=24) {fail(n,Result::Uncertain,1);return;}
  if(r.data[0]==2) {
    if(!p.pendingMutation) {
      p.pendingMutation=q.record.opcode==0x14?bodaqs_control_get_u32(q.record.data):q.record.operation;
      p.waitStarted=millis();
    }
    p.nextPoll=millis()+100;
  } else p.pendingMutation=0;
  publish(n,r.data[0]==3?Result::Succeeded:r.data[0]==2?Result::Pending:Result::Uncertain,r.data[1],&r);
}
#if defined(ARDUINO_ARCH_ESP32)
static void run(void*) {
  for(;;) {
    // Bounded catch-up group; each service transfers one CS-bounded slot and
    // releases shared SPI before the >=25us rearm/ADC opportunity. The group
    // removes the lease-only one-slot-per-RTOS-tick throughput cap.
    for(unsigned i=0;i<8 && active();++i) service();
    vTaskDelay(1);
  }
}
#endif
} // namespace

bool begin(uint64_t recording,uint64_t context) {
  if(!recording || !context) return false;
  {Lock lock;if(owned) return false;}
#if defined(ARDUINO_ARCH_ESP32)
  if(!task && xTaskCreate(run,"AcquisitionCtl",4096,nullptr,2,&task)!=pdPASS) return false;
#endif
  if(!CanMasterManager::claimMeasurementControl(isOwner)) return false;
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  ImuFlowDiagnostics::reset(context,millis());
#endif
  const auto& d=CanMasterManager::diagnostics();session=d.authority.session;masterBoot=d.control.master_boot_id;
  nextRead=d.authority.next_read;nextTransfer=d.apply.next_transfer;
  for(uint8_t n=0;n<4;++n) {peers[n]=Peer{};peers[n].mutation=d.authority.nodes[n].next_mutation;mailboxes[n]=Mailbox{};outcomes[n]=Outcome{};}
  memset(&transport,0,sizeof transport);recordingId=recording;contextId=context;cursor=0;
  nextHealthObservation=millis()+2000;healthCursor=0;physicalFenceVerified=false;nextFenceInspection=0;
  fenceInspections=fenceObservations=0;nextFenceSnapshot=millis();
  {Lock lock;fenceSnapshot={};}
  {Lock lock;owned=true;enterPending=true;exitPending=false;cleanupRequested=false;}
  return true;
}
size_t reservedBytes() {
 return sizeof(peers)+sizeof(mailboxes)+sizeof(outcomes)+sizeof(transport)+sizeof(fenceSnapshot)+3*sizeof(uint32_t)+
        sizeof(recordingId)+sizeof(contextId)+sizeof(session)+sizeof(masterBoot)+sizeof(nextTransfer)+
        sizeof(nextRead)+sizeof(cursor)+sizeof(dataConsumer)+sizeof(dataMask)+sizeof(dataCursor)+sizeof(serviceCursor)+
        4096 // configured control task stack; watermark qualification remains deferred
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
        +ImuFlowDiagnostics::reservedBytes()
#endif
        ;
}
bool active() {Lock lock;return owned;}
bool setDataConsumer(DataConsumer consumer,uint8_t mask) {
  Lock lock;if(owned || (mask&~15u)) return false;
  dataConsumer=consumer;dataMask=mask;dataCursor=serviceCursor=0;return true;
}
bool enqueue(const Request& request) {
  if(request.node>3 || static_cast<unsigned>(request.action)>static_cast<unsigned>(Action::Release)) return false;
  Lock lock;
  if((outcomes[request.node].excluded || outcomes[request.node].terminal) && (request.action==Action::Prepare || request.action==Action::Start)) return false;
  if(!owned || (exitPending && request.action!=Action::Stop && request.action!=Action::Fence && request.action!=Action::Release && request.action!=Action::Snapshot) || (mailboxes[request.node].pending && request.action!=Action::Stop)) return false;
  mailboxes[request.node].request=request;mailboxes[request.node].pending=true;return true;
}
void fenceDiagnostics(FenceDiagnostics& out) {Lock lock;out=fenceSnapshot;}
bool outcome(uint8_t n,Outcome& out) {if(n>3) return false;Lock lock;out=outcomes[n];return true;}
bool requestExit() {Lock lock;if(!owned || exitPending) return false;exitPending=true;return true;}
void service() {
#if defined(ARDUINO_ARCH_ESP32)
  if(!isOwner()) return;
#endif
  bool enter=false,exit=false;
  {Lock lock;if(!owned) return;enter=enterPending;enterPending=false;exit=exitPending;}
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  ImuFlowDiagnostics::service();
#endif
  servicing=true;
  if(transport.failed) for(uint8_t n=0;n<4;++n) {
    Request terminal;bool queued=false;
    {Lock lock;if(mailboxes[n].pending) {
      terminal=mailboxes[n].request;mailboxes[n].pending=false;queued=true;
    }}
    if(queued && terminal.action==Action::Fence) cleanupRequested=true;
    // The unavailable measurement context cannot carry another command. STOP
    // has already stopped renewal; the node's original lease must expire.
  }
  bool liveRemote=false;for(const auto& peer:peers) liveRemote|=peer.leased;
  if(cleanupRequested && !liveRemote) {
    if(CanMasterManager::cleanupUnavailableMeasurement()) {
      // Retire all old assemblers, deduplication and ACK state only after the
      // node/master physical fences and explicit administrative release.
      memset(&transport,0,sizeof transport);
      for(uint8_t n=0;n<4;++n) {
        peers[n].ordinary.pending=peers[n].protectedLane.pending=false;
        peers[n].phase=Phase::Idle;peers[n].pendingMutation=0;
        {Lock lock;mailboxes[n].pending=false;outcomes[n].localFenceComplete=true;}
      }
      nextFenceSnapshot=millis();publishFenceDiagnostics(millis());
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
      ImuFlowDiagnostics::finish(millis(),micros());
#endif
      CanMasterManager::releaseMeasurementControl();
      {Lock lock;owned=false;exitPending=false;cleanupRequested=false;}
      servicing=false;return;
    }
    publishFenceDiagnostics(millis());servicing=false;return;
  }
  if(enter && !CanMasterManager::enterMeasurementMode(recordingId,contextId)) {
    // Entry can fail after the master changed mode but before confirmation.
    // No trustworthy transport exists for PREPARE or normal Fence commands.
    // Route the eventual fence through explicit unavailable-context cleanup;
    // retain ownership until it verifies node and master retirement/release.
    transport.failed=true;
    for(uint8_t n=0;n<4;++n) publish(n,Result::Unavailable,26);
  }
  if(exit) {
    bool live=false;for(const auto& p:peers) live|=p.leased || p.ordinary.pending || p.protectedLane.pending || p.phase!=Phase::Idle || p.pendingMutation;
    if(!live && CanMasterManager::exitMeasurementMode()) {
      uint32_t mutations[4];for(uint8_t n=0;n<4;++n) mutations[n]=peers[n].mutation;
      CanMasterManager::retainMeasurementAllocators(nextRead,mutations,nextTransfer);
      nextFenceSnapshot=millis();publishFenceDiagnostics(millis());
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
      ImuFlowDiagnostics::finish(millis(),micros());
#endif
      CanMasterManager::releaseMeasurementControl();
      {Lock lock;owned=false;exitPending=false;}
      servicing=false;return;
    }
  }
  if(!CanMasterManager::measurementReady()) {publishFenceDiagnostics(millis());servicing=false;return;}
  const uint32_t now=millis();
  for(uint8_t n=0;n<4;++n) {
    auto& p=peers[n];Request intent;bool have=false;
    if(p.leased && due(now,p.leaseDeadline)) exclude(n,29);
    {Lock lock;if(mailboxes[n].pending && (mailboxes[n].request.action==Action::Stop || (!p.ordinary.pending && p.phase==Phase::Idle && !p.pendingMutation && !transport.controls[0][n].state.complete))) {
      intent=mailboxes[n].request;mailboxes[n].pending=false;have=true;
    }}
    if(have) beginRequest(n,intent);
    for(Exchange* x:{&p.ordinary,&p.protectedLane}) {
      const uint32_t deadline=x==&p.protectedLane?BODAQS_ACQ_RESPONSE_MS:3500;
      // A request may have been queued after the service-level 'now' snapshot.
      if(x->pending && static_cast<uint32_t>(millis()-x->started)>=deadline) {
        x->pending=false;
        if(uncertainStop(n,26)) continue;
        if(x==&p.protectedLane) {if(!retryRenewal(n)) exclude(n,26);continue;}
        if(x==&p.ordinary && p.observing) {p.observing=false;p.phase=Phase::Idle;continue;}
        fail(n,Result::Uncertain,26);
        if(p.leased) {
          Request stop;stop.node=n;stop.action=Action::Stop;stop.recording=p.recording;stop.reason=26;
          beginRequest(n,stop);
        }
      }
    }
    if(p.pendingMutation && !p.ordinary.pending && p.phase==Phase::Idle && !transport.controls[0][n].state.complete && due(now,p.nextPoll)) {
      if(static_cast<uint32_t>(now-p.waitStarted)>=10000) {
        p.pendingMutation=0;publish(n,Result::Uncertain,26);
        if(p.leased) {
          Request stop;stop.node=n;stop.action=Action::Stop;stop.recording=p.recording;stop.reason=26;
          beginRequest(n,stop);
        }
      } else {
        auto query=request(n,0x14,allocate(nextRead));query.record.data_length=4;
        bodaqs_control_put_u32(query.record.data,p.pendingMutation);
        if(!query.record.operation || !send(n,p.ordinary,query,false)) fail(n,Result::Uncertain,26);
      }
    }
    if(p.leased && due(now,p.nextRenewal)) {
      p.nextRenewal=now+BODAQS_ACQ_RENEW_MS; // no accumulated catch-up requests
      if(!p.protectedLane.pending) challenge(n,false);
    }
  }
  // One eight-request immutable acquisition snapshot per two seconds globally
  // costs at most four ordinary requests/s before bounded transport retries.
  // Protected renewals remain the fast fault detector; this fair, optional
  // observation supplements them without spending 32 requests/s on four nodes.
  if(due(now,nextHealthObservation)) for(unsigned i=0;i<4;++i) {
    const uint8_t peer=(healthCursor+i)%4;auto& p=peers[peer];
    if(!p.monitoring || !p.leased || p.excluded || p.ordinary.pending || p.phase!=Phase::Idle || p.pendingMutation) continue;
    bool pending;{Lock lock;pending=mailboxes[peer].pending;}
    if(pending || transport.controls[0][peer].state.complete) continue;
    nextHealthObservation=now+2000;healthCursor=(peer+1)%4;
    Request observation;observation.node=peer;observation.action=Action::Snapshot;observation.recording=p.recording;
    beginRequest(peer,observation,true);break;
  }
  bool allFenced=true,anyRecording=false;
  for(uint8_t node=0;node<4;++node) {
    const auto& p=peers[node];
    if(p.recording) {anyRecording=true;allFenced &= p.fenceConfirmed;}
    allFenced &= !p.ordinary.pending && !p.protectedLane.pending && !p.pendingMutation;
    Lock lock;allFenced &= !mailboxes[node].pending;
  }
  if(anyRecording && allFenced && !physicalFenceVerified && due(now,nextFenceInspection)) {
    nextFenceInspection=now+20;
    if(fenceInspections!=UINT32_MAX) ++fenceInspections;
    const bool observed=CanMasterManager::inspectMeasurementMode();
    if(observed && fenceObservations!=UINT32_MAX) ++fenceObservations;
    if(observed && CanMasterManager::measurementReady() &&
       (CanMasterManager::diagnostics().measurement.flags&BODAQS_MODE_FLAG_FENCED)) {
      // Fully bound fresh status follows adapter FIFO/DMA retirement. Cancel
      // local data state administratively, without a RAM-accepted ACK.
      physicalFenceVerified=true;nextFenceSnapshot=now;
      for(uint8_t node=0;node<4;++node) for(uint8_t cls:{1,2,5}) {
        if(cls==5 && node) continue;
        auto& data=transport.inboxes[cls-1][node];
        if(data.state.object && !data.admitted) {
          Lock lock;auto& out=outcomes[node];out.tailDiscarded=true;
          if(out.tailObjectsDiscarded!=UINT32_MAX) ++out.tailObjectsDiscarded;
          if(cls==1) out.sampleTailDiscarded=true;
        }
        data={};
      }
      transport.bridgePending=transport.bridgeReady=transport.bridgeExpired=false;
      transport.lossReady=false;
    }
  }
  MeasurementInbox* inbox=nullptr;
  // Repeat each idle control selection before rotating, so alternating lost
  // SPI requests cannot permanently skip a node's only response poll.
  uint8_t n=(cursor/2)%4,cls=(cursor/8)%2?3:4;
  bool urgent=false;
  uint32_t oldest=0;
  for(uint8_t candidate=0;candidate<4;++candidate) {
    const auto& exchange=peers[candidate].protectedLane;
    const uint32_t age=now-exchange.started;
    if(exchange.pending && (!urgent || age>oldest)) {urgent=true;oldest=age;n=candidate;cls=4;}
  }
  // Protected and ordinary lanes retain independent service. Data takes three
  // slots out of four when registered; lifecycle still advances at each turn.
  if(!urgent && !physicalFenceVerified && dataConsumer && dataMask && (++serviceCursor%4)!=0) {
    for(unsigned i=0;i<4;++i) {
      n=dataCursor++%4;if(dataMask&(1u<<n)) break;
    }
    cls=(serviceCursor%4)==1?2:1;
  } else if(!urgent) cursor=(cursor+1)%16;
  transport.timingEnabled=!physicalFenceVerified && dataConsumer && dataMask;
  if(!urgent && transport.timingEnabled && (serviceCursor%20)==0) {cls=5;n=255;}
  const int result=CanMasterManager::serviceMeasurementTransport(transport,cls,n,inbox);
  if(result==-14) for(uint8_t peer=0;peer<4;++peer)
    if(peers[peer].recording && !peers[peer].excluded) exclude(peer,26);
  if(result==1 && inbox && (inbox->state.cls==3 || inbox->state.cls==4)) {
    BodaqsControlWrapped reply={};
    if(bodaqs_control_decode_wrapped(inbox->bytes,64,&reply) && reply.node_address<4)
      accept(reply.node_address,inbox->state.cls==4,reply);
    CanMasterManager::releaseMeasurementObject(*inbox);
  }
  if(dataConsumer) for(uint8_t node=0;node<4;++node) for(uint8_t dataClass:{2,1}) {
    auto& data=transport.inboxes[dataClass-1][node];
    if(peers[node].excluded && data.state.complete && !data.admitted) {
      // Exclusion is not admission; retain until administrative retirement.
      Lock lock;outcomes[node].tailDiscarded=true;outcomes[node].sampleTailDiscarded|=dataClass==1;
      continue;
    }
    if(CanMasterManager::measurementObjectReady(data) &&
       dataConsumer(dataClass,node,data.state.object,data.bytes,data.state.total))
      CanMasterManager::releaseMeasurementObject(data);
  }
  if(dataConsumer) {
    if(transport.lossReady && dataConsumer(7,transport.lossDiagnostic.node,
       transport.lossDiagnostic.object,transport.lossDiagnostic.body,8)) transport.lossReady=false;
    auto& shared=transport.inboxes[4][0];
    if(CanMasterManager::measurementObjectReady(shared) &&
       dataConsumer(5,255,shared.state.object,shared.bytes,shared.state.total))
      CanMasterManager::releaseMeasurementObject(shared);
    if(transport.bridgeReady) {
      uint8_t b[32]={};
      bodaqs_measurement_put(b,transport.bridgeToken,4);bodaqs_measurement_put(b+4,transport.bridgeTick,4);
      bodaqs_measurement_put(b+8,transport.bridgeEpoch,4);b[12]=transport.bridgeExpired?2:1;
      bodaqs_measurement_put(b+16,transport.bridgeLower,8);bodaqs_measurement_put(b+24,transport.bridgeUpper,8);
      if(dataConsumer(6,255,transport.bridgeToken,b,sizeof b)) transport.bridgeReady=false;
    }
  }
  for(uint8_t node=0;node<4;++node) {
    if(peers[node].intent.action!=Action::Fence) continue;
    bool retired=peers[node].fenceConfirmed;
    for(uint8_t cls:{1,2,5}) {
      const auto& retained=transport.inboxes[cls-1][cls==5?0:node];
      retired &= !retained.state.object || (retained.admitted && !retained.ackPending);
    }
    Lock lock;outcomes[node].localFenceComplete=retired;
  }
  publishFenceDiagnostics(millis());
  servicing=false;
}
} // namespace AcquisitionControl
