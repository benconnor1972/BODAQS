#include "AcquisitionControl.h"
#include "bodaqs_control_acquisition.h"
static bool lifecycleEnabled=false;
static Fixture otherNodes[3];
static BodaqsControlAcquisition acquisitions[4];
static BodaqsControlSnapshot acquisitionSnapshots[4];
static uint8_t pendingCommand[4];
static bool delayNodeZero=false;
static bool holdCommit=false, commitHeld=false;
static BodaqsControlRecord heldCommit;
static bool loseRenewalChallenges=false, loseRenewalResults=false;
static unsigned lostRenewals=0;
static uint8_t renewalError=0;
static bool renewalErrorOnProof=false;
static BodaqsControlRecord heldRenewal;
static bool holdControl(uint8_t address,const BodaqsControlRecord& request) {
 if(address) return false;
 if(holdCommit && request.opcode==0x22) {heldCommit=request;commitHeld=true;return true;}
 if(loseRenewalChallenges && request.opcode==0x26 && request.data[12]==1) {++lostRenewals;return true;}
 if(loseRenewalResults && request.opcode==0x27) {
  heldRenewal=request;BodaqsControlRecord ignored;
  assert(dispatchControl(0,request,ignored));++lostRenewals;return true;
 }
 return false;
}
static Fixture& peerFixture(uint8_t n) {return n?otherNodes[n-1]:node;}
static uint64_t fixtureRandom(void*) {return 123456;}
static void backendEvent(void* context,uint8_t command,uint32_t generation,uint64_t,uint32_t,BodaqsAcquisitionEvent* event) {
 const uint8_t n=static_cast<uint8_t>(reinterpret_cast<uintptr_t>(context));
 if(command) {pendingCommand[n]=command;return;}
 const uint8_t pending=pendingCommand[n];
 if(!pending || (n==0 && delayNodeZero)) return;
 event->generation=generation;event->register_proof_current=true;
 event->node_clock_epoch=event->sensor_clock_epoch=1;
 event->kind=pending==BODAQS_ACQ_PREPARE?BODAQS_ACQ_READY:pending==BODAQS_ACQ_START?BODAQS_ACQ_FIRST:pending==BODAQS_ACQ_STOP?BODAQS_ACQ_STOPPED:BODAQS_ACQ_FENCED;
 event->known_empty=true;event->boundary[8]=1;event->boundary[9]=7;
 pendingCommand[n]=0;
}
static bool dispatchControl(uint8_t n,const BodaqsControlRecord& request,BodaqsControlRecord& reply) {
 if(!lifecycleEnabled) return bodaqs_control_node_process(&node.view,&request,&reply);
 if(!n && renewalError && (renewalErrorOnProof ? request.opcode==0x27 : (request.opcode==0x26 && request.data[12]==1))) {
  reply=request;reply.opcode=BODAQS_CONTROL_ERROR;reply.data_length=24;
  std::memset(reply.data,0,24);reply.data[0]=1;reply.data[1]=renewalError;
  reply.data[2]=renewalError==20?17:1;reply.data[3]=request.opcode;
  bodaqs_control_put_u32(reply.data+4,request.operation);++lostRenewals;return true;
 }
 auto& f=peerFixture(n);auto& a=acquisitions[n];
 bodaqs_control_acquisition_tick(&a,clockMs);
 bool handled=bodaqs_control_authority_process(&f.authority,&f.view,&request,clockMs,fixtureRandom,nullptr,&reply) ||
   bodaqs_control_snapshot_process(&acquisitionSnapshots[n],&f.view,&request,clockMs,&reply) ||
   bodaqs_control_acquisition_process(&a,&request,clockMs,&reply) ||
   bodaqs_control_apply_process(&f.apply,&request,clockMs,&reply) ||
   bodaqs_control_node_process(&f.view,&request,&reply);
 return handled;
}
static void controlSteps(unsigned duration) {
 for(unsigned i=0;i<duration;++i) {
  ++clockMs;
  for(uint8_t n=0;n<4;++n) bodaqs_control_acquisition_tick(&acquisitions[n],clockMs);
  AcquisitionControl::service();
 }
}
int main(int argc,char** argv) {
 fastMeasurementClock=true;
 reset();
 CanMasterManager::beginRecordingHandoff();
 for(unsigned wait=0;wait<5500 && !CanMasterManager::recordingHandoffReady();++wait) advance(1);
 assert(CanMasterManager::recordingHandoffReady());
 assert(AcquisitionControl::begin(123,456));
 // The main task cannot mutate transport mode while ownership is handed off.
 assert(!CanMasterManager::enterMeasurementMode(999,888));
 AcquisitionControl::service();
 assert(CanMasterManager::measurementReady());
 AcquisitionControl::Request request;
 request.node=0;request.recording=123;request.action=AcquisitionControl::Action::Snapshot;
 assert(AcquisitionControl::enqueue(request));
 assert(!AcquisitionControl::enqueue(request)); // bounded per-node mailbox
 for(unsigned i=0;i<100;++i) AcquisitionControl::service();
 AcquisitionControl::Outcome result;
 assert(AcquisitionControl::outcome(0,result));
 assert(result.result==AcquisitionControl::Result::Rejected);
 assert(!result.leaseAcknowledged && !result.snapshotValid);
 assert(AcquisitionControl::requestExit());
 AcquisitionControl::service();
 assert(!AcquisitionControl::active());
 assert(!CanMasterManager::measurementReady());
 // Real authority and acquisition dispatch, four independent hardware fixtures.
 if(argc>1 && !std::strcmp(argv[1],"renewal-wrap")) clockMs=UINT32_MAX-5000U;
 reset();lifecycleEnabled=true;
 dropBindReplyUntil=clockMs; // Disabled injection must also be past at wrap.
 BodaqsMasterDiscoveryRecord records[4]={};
 for(uint8_t n=0;n<4;++n) {
  auto& f=peerFixture(n);f.view.active_session=0;f.authority={};f.view.flags=0;
  f.authority.next_challenge=1;
  f.apply.effective[4]=2;bodaqs_control_put_u32(f.apply.effective+20,3);
  bodaqs_control_put_u64(f.apply.effective+32,1);
  bodaqs_control_acquisition_init(&acquisitions[n],&f.authority,&f.view,f.apply.effective,backendEvent,reinterpret_cast<void*>(static_cast<uintptr_t>(n)));
  acquisitionSnapshots[n]={};acquisitionSnapshots[n].capture_acquisition=bodaqs_control_acquisition_capture;
  acquisitionSnapshots[n].acquisition_context=&acquisitions[n];
  records[n].node_address=n;records[n].flags=1;records[n].boot_id=f.view.boot_id;
  records[n].endpoint_mask=1;records[n].hardware_uid=123+n;
 }
 bodaqs_master_service_set_inventory(&master,2,records,4);
 assert(CanMasterManager::probeNow());advance(4000);
 for(uint8_t n=0;n<4;++n) {
  const auto& auth=CanMasterManager::diagnostics().authority.nodes[n];
  assert(auth.bound);
 }
 CanMasterManager::beginRecordingHandoff();
 advance(1000);
 for(unsigned wait=0;wait<5500 && !CanMasterManager::recordingHandoffReady();++wait) advance(1);
 assert(CanMasterManager::recordingHandoffReady());
 assert(AcquisitionControl::begin(123,457));AcquisitionControl::service();
 for(uint8_t n=0;n<4;++n) {
  request={};request.node=n;request.recording=123;request.action=AcquisitionControl::Action::Prepare;
  request.revision=1;request.epoch=peerFixture(n).view.endpoint_epoch[0];
  assert(AcquisitionControl::enqueue(request));
 }
 controlSteps(2200);
 for(uint8_t n=0;n<4;++n) {
  assert(AcquisitionControl::outcome(n,result));
  assert(result.result==AcquisitionControl::Result::Succeeded && result.leaseAcknowledged);
  assert(acquisitions[n].phase==2 && acquisitions[n].renewal_sequence>=2 && acquisitions[n].renewal_sequence<=3);
 }
 if(argc>1) {
  if(!std::strncmp(argv[1],"retryable-error-",16) || !std::strcmp(argv[1],"expired-proof-error")) {
   renewalErrorOnProof=!std::strcmp(argv[1],"expired-proof-error");
   renewalError=renewalErrorOnProof?20:static_cast<uint8_t>(std::atoi(argv[1]+16));
   controlSteps(1600);assert(lostRenewals);
   assert(AcquisitionControl::outcome(0,result) && !result.excluded && result.leaseAcknowledged);
   renewalError=0;controlSteps(1600);
   assert(AcquisitionControl::outcome(0,result) && !result.excluded && result.leaseAcknowledged);
   puts("matched retryable node error preserves confirmed authority: PASS");return 0;
  }
  if(!std::strcmp(argv[1],"late-renewal-wire") || !std::strcmp(argv[1],"split-renewal-stop") || !std::strcmp(argv[1],"late-renewal-retry")) {
   const uint32_t confirmedUpper=acquisitions[0].lease_deadline;
   delayRenewalWire=true;
   controlSteps(1400);assert(renewalWire.size()==2);
   if(!std::strcmp(argv[1],"late-renewal-retry")) {
    delayRenewalWire=false;loseRenewalChallenges=true;controlSteps(800);
    replayRenewalWire=true;
    while(int32_t(clockMs-(confirmedUpper+1))<0) controlSteps(1);
    assert(renewalWire.empty());
    assert(AcquisitionControl::outcome(0,result) && result.excluded && !result.leaseAcknowledged);
    puts("old successful reply cannot confirm a newer pending retry: PASS");return 0;
   }
   request.node=0;request.action=AcquisitionControl::Action::Stop;request.recording=123;
   assert(AcquisitionControl::enqueue(request));controlSteps(500);
   assert(acquisitions[0].terminal && !acquisitions[0].lease_valid);
   if(!std::strcmp(argv[1],"split-renewal-stop")) renewalWire.erase(renewalWire.begin());
   delayRenewalWire=false;replayRenewalWire=true;controlSteps(1000);
   assert(renewalWire.empty());
   assert(AcquisitionControl::outcome(0,result) && !result.leaseAcknowledged);
   assert(acquisitions[0].terminal && !acquisitions[0].lease_valid);
   puts("late successful renewal wire fragments cannot revive STOP: PASS");return 0;
  }
  if(!std::strcmp(argv[1],"renewal-wrap")) {
   controlSteps(7000);
   assert(AcquisitionControl::outcome(0,result) && !result.excluded && result.leaseAcknowledged);
   assert(acquisitions[0].lease_valid && acquisitions[0].renewal_sequence>=8);
   puts("confirmed leases survive millisecond and native tick wrap: PASS");return 0;
  }
  const bool resultLoss=!std::strcmp(argv[1],"lost-renewal-result");
  const bool stopRetry=!std::strcmp(argv[1],"stop-renewal-retry");
  const bool exhaustion=!std::strcmp(argv[1],"renewal-expiry");
  const uint32_t oldRemoteDeadline=acquisitions[0].lease_deadline;
  loseRenewalChallenges=!(resultLoss || stopRetry);loseRenewalResults=resultLoss || stopRetry;
  controlSteps(exhaustion?6000:1600);
  assert(lostRenewals);
  assert(AcquisitionControl::outcome(0,result));
  if(exhaustion) {
   assert(result.excluded && !result.leaseAcknowledged && acquisitions[0].terminal);
   loseRenewalChallenges=false;controlSteps(1600);
   assert(AcquisitionControl::outcome(0,result) && result.excluded);
   puts("unconfirmed retries cannot extend authority or rejoin: PASS");return 0;
  }
  assert(!result.excluded && result.leaseAcknowledged);
  if(stopRetry) {
   request.node=0;request.action=AcquisitionControl::Action::Stop;request.recording=123;
   assert(AcquisitionControl::enqueue(request));controlSteps(500);
   assert(acquisitions[0].terminal && !acquisitions[0].lease_valid);
   BodaqsControlRecord stale;
   assert(dispatchControl(0,heldRenewal,stale));assert(stale.data[0]==1 && stale.data[1]==30);
   loseRenewalResults=false;controlSteps(1600);
   assert(AcquisitionControl::outcome(0,result) && !result.leaseAcknowledged);
   assert(!acquisitions[0].lease_valid);
   puts("STOP overtakes a retry and late renewal cannot revive it: PASS");return 0;
  }
  if(resultLoss) assert(int32_t(acquisitions[0].lease_deadline-oldRemoteDeadline)>0);
  loseRenewalChallenges=loseRenewalResults=false;controlSteps(1600);
  assert(AcquisitionControl::outcome(0,result) && !result.excluded && result.leaseAcknowledged);
  assert(int32_t(acquisitions[0].lease_deadline-oldRemoteDeadline)>0);
  puts("bounded renewal retry recovers within confirmed authority: PASS");return 0;
 }
 // A pending ordinary START on one node does not suppress its own renewals or
 // other nodes' one-second lease attempts. STOP then supersedes that operation.
 request={};request.action=AcquisitionControl::Action::Start;request.recording=123;
 request.revision=1;request.epoch=node.view.endpoint_epoch[0];delayNodeZero=true;
 assert(AcquisitionControl::enqueue(request));controlSteps(1500);
 for(uint8_t n=0;n<4;++n) assert(acquisitions[n].lease_valid && acquisitions[n].renewal_sequence>=3 && acquisitions[n].renewal_sequence<=5);
 request.action=AcquisitionControl::Action::Stop;assert(AcquisitionControl::enqueue(request));
 delayNodeZero=false;controlSteps(500);
 assert(acquisitions[0].terminal && !acquisitions[0].lease_valid && acquisitions[0].stopped);
 assert(AcquisitionControl::outcome(0,result));
 assert(result.result==AcquisitionControl::Result::Succeeded);
 request.action=AcquisitionControl::Action::Snapshot;assert(AcquisitionControl::enqueue(request));controlSteps(1000);
 assert(AcquisitionControl::outcome(0,result));
 assert(result.snapshotValid && result.snapshot[6]==5 && bodaqs_control_get_u64(result.snapshot+8)==123);
 for(uint8_t n=1;n<4;++n) {
  request.node=n;request.action=AcquisitionControl::Action::Stop;
  assert(AcquisitionControl::enqueue(request));
 }
 controlSteps(1000);
 for(uint8_t n=0;n<4;++n) {
  assert(acquisitions[n].stopped && !acquisitions[n].lease_valid);
  request.node=n;request.action=AcquisitionControl::Action::Fence;
  assert(AcquisitionControl::enqueue(request));
 }
 controlSteps(1200);
 for(uint8_t n=0;n<4;++n) {
  assert(AcquisitionControl::outcome(n,result));
  assert(result.result==AcquisitionControl::Result::Succeeded && result.localFenceComplete);
  request.node=n;request.action=AcquisitionControl::Action::Release;
  assert(AcquisitionControl::enqueue(request));
 }
 controlSteps(1200);
 for(uint8_t n=0;n<4;++n) assert(!acquisitions[n].recording);
 // The physical master driver independently confirms its old DMA/preloaded
 // boundary has retired. A node ACK alone must not authorize mode exit.
 assert(master.acquisition_retirement_pending);
 bodaqs_master_service_measurement_fence(&master,true,true);
 assert(AcquisitionControl::requestExit());controlSteps(20);
 assert(!AcquisitionControl::active());
 assert(!CanMasterManager::measurementReady());
 // A physically delayed COMMIT must not acquire after a protected STOP.
 assert(AcquisitionControl::begin(124,458));AcquisitionControl::service();
 request={};request.node=0;request.recording=124;request.action=AcquisitionControl::Action::Prepare;
 request.revision=1;request.epoch=node.view.endpoint_epoch[0];holdCommit=true;
 assert(AcquisitionControl::enqueue(request));controlSteps(700);
 assert(commitHeld && acquisitions[0].staging && !acquisitions[0].recording);
 request.action=AcquisitionControl::Action::Stop;assert(AcquisitionControl::enqueue(request));
 controlSteps(200);
 assert(AcquisitionControl::outcome(0,result));
 assert(result.result==AcquisitionControl::Result::Succeeded);
 holdCommit=false;BodaqsControlRecord lateReply;
 assert(dispatchControl(0,heldCommit,lateReply));
 assert(lateReply.data[0]==6 && lateReply.data[1]==13);
 assert(!acquisitions[0].recording && !acquisitions[0].lease_valid && acquisitions[0].phase!=1);
 controlSteps(700); // retire the physically delayed ordinary result as well
 request.action=AcquisitionControl::Action::Fence;assert(AcquisitionControl::enqueue(request));controlSteps(200);
 assert(AcquisitionControl::outcome(0,result));
 assert(result.result==AcquisitionControl::Result::Succeeded && result.localFenceComplete);
 request.action=AcquisitionControl::Action::Release;assert(AcquisitionControl::enqueue(request));controlSteps(200);
 assert(AcquisitionControl::outcome(0,result));
 assert(result.result==AcquisitionControl::Result::Succeeded);
 bodaqs_master_service_measurement_fence(&master,true,true);
 assert(AcquisitionControl::requestExit());controlSteps(20);assert(!AcquisitionControl::active());
 puts("logger ownership, four-node preparation/renewal, pending START, STOP and immutable snapshot passed");
}
