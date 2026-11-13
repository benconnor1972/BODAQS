#include "RemoteImuRecording.h"
#include "RemoteImuStream.h"
#include "ImuFlowDiagnostics.h"
#include "AcquisitionControl.h"
#include "../can-fd/common/protocol/bodaqs_control_acquisition.h"
#include "CanMasterManager.h"
#include "SensorAssignment.h"
#include "BoardSelect.h"
#include "SensorManager.h"
#include "ConfigManager.h"
#include <Arduino.h>
#include <esp_timer.h>
#include <esp_system.h>
#include <cstring>
#include "ImuAdmission.h"
#include "AnalogInputManager.h"
#include "DebugLog.h"
#include <new>

namespace RemoteImuRecording {
namespace {
enum Phase { Idle, Allocated, Prepare, PreparedSnapshot, Ready, Starting, Recording, Stop, Tail, Fence, Release, Exit, Done };
struct Participant {
RemoteImuStream stream;

std::atomic<Phase> phase{Idle};
uint8_t node=0;
uint64_t record=0,recordContext=0,revision=0,epoch=0;

uint32_t serial=0,began=0,tailBegan=0;
uint32_t stopRequestedMs=0,stopConfirmedMs=0;
bool stopConfirmed=false;
Completion frozenCompletion;
std::atomic<bool> completionFrozen{false};
std::atomic<bool> fault{false};
bool stopIntent=false,startIntent=false;
uint32_t nextCleanupAttempt=0;
bool cleanupQueued=false;
Failure firstFailure;
// Bit0 closes admission, bit1 marks an active producer callback. The main
// owner closes without waiting; storage finalization starts only after bit1
// retires. Unaccepted tail objects remain retained until administrative fence.
std::atomic<uint8_t> dataGate{1};
uint32_t objectProgress[2]={};
uint16_t recordProgress[2]={};
bool consume(uint8_t cls,uint8_t address,uint32_t identity,const uint8_t* p,uint16_t total) {
  uint8_t open=0;
  if(!dataGate.compare_exchange_strong(open,2,std::memory_order_acq_rel)) {
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
    if(ImuFlowDiagnostics::active) ++ImuFlowDiagnostics::live.gateWait;
#endif
    return false; // No RAM acceptance after the file admission gate closes.
  }

  struct Retire {std::atomic<uint8_t>& gate;~Retire(){gate.fetch_and(1,std::memory_order_release);}} retire{dataGate};
  if(cls==7 && address==node && total==8) {
    const auto accepted=stream.acceptManagementLoss(p[0],p[1],BdqV2Format::getU16(p+2),
      BdqV2Format::getU32(p+4),static_cast<uint32_t>(esp_timer_get_time()));
    if(accepted==RemoteImuStream::Invalid) fault=true;
    return accepted!=RemoteImuStream::Blocked;
  }

  if(address==255 && cls==6) {
    if(total!=32) {fault=true;return true;}
    if(p[12]==2) return stream.acceptMissingBridge(BdqV2Format::getU32(p),
      static_cast<uint32_t>(esp_timer_get_time()))!=RemoteImuStream::Blocked;
    auto accepted=stream.acceptBridge(BdqV2Format::getU32(p),BdqV2Format::getU32(p+4),
      BdqV2Format::getU32(p+8),BdqV2Format::getU64(p+16),BdqV2Format::getU64(p+24),
      static_cast<uint32_t>(esp_timer_get_time()));
    return accepted!=RemoteImuStream::Blocked;
  }
  if(address==255 && cls==5) {
    if(total<12 || p[0]!=1 || p[1] || p[3] || p[6] || p[7]) {fault=true;return true;}
    const uint16_t count=BdqV2Format::getU16(p+4);
    if(p[2]!=1 || total!=12+16*count || count!=1 || p[8]!=1 || p[9] || p[10] || p[11]) {fault=true;return true;}
    return stream.acceptSharedSync(BdqV2Format::getU32(p+12),BdqV2Format::getU32(p+16),
      BdqV2Format::getU32(p+20),static_cast<uint32_t>(esp_timer_get_time()))!=RemoteImuStream::Blocked;
  }
#if BODAQS_MEASUREMENT_VERSION >= 3
  if(cls==1 && address==node) {
    const auto result=stream.acceptSampleUnit(recordContext,identity,p,total,
        static_cast<uint32_t>(esp_timer_get_time()));
    if(result==RemoteImuStream::Invalid) {
      fault=true;
#if BODAQS_MEASUREMENT_VERSION >= 4
      return false; // invalid/faulted source has no RAM custody; fence its tail
#endif
    }
    return result!=RemoteImuStream::Blocked;
  }
#endif
  if(address!=node || cls<1 || cls>2 || total<20 || p[0]!=1 || p[1] || p[2]!=cls || p[3]!=node ||
     BdqV2Format::getU32(p+4)!=CanMasterManager::diagnostics().authority.nodes[node].boot ||
     BdqV2Format::getU16(p+14)) {fault=true;return true;}
  const uint16_t count=BdqV2Format::getU16(p+12);
  if(!count || count>13 || total!=20+76*count) {fault=true;return true;}
  // Immutable transport object identifies the retained head, preserving partial
  // downstream progress when its bounded queue temporarily fills.
  const unsigned lane=cls-1;
  if(objectProgress[lane]!=identity) {objectProgress[lane]=identity;recordProgress[lane]=0;}
  for(uint16_t& i=recordProgress[lane];i<count;++i) {
    const uint8_t* r=p+16+76*i;
    if(r[2]>64) {fault=true;return true;}
    const uint64_t order=(uint64_t(BdqV2Format::getU32(p+8))<<32)|BdqV2Format::getU32(r+8);
    const auto accepted=stream.accept(BdqV2Format::getU16(r),r+12,r[2],
      BdqV2Format::getU32(r+4),order,static_cast<uint32_t>(esp_timer_get_time()),r[3]);
    if(accepted==RemoteImuStream::Blocked) return false;
    if(accepted==RemoteImuStream::Invalid) {fault=true;return true;}
  }
  return true;
}
bool send(AcquisitionControl::Action action) {
  AcquisitionControl::Request q;q.node=node;q.action=action;q.recording=record;q.revision=revision;q.epoch=epoch;
  AcquisitionControl::Outcome out;AcquisitionControl::outcome(node,out);serial=out.serial;
  return AcquisitionControl::enqueue(q);
}
bool configure(const SensorSpec& chosen,uint64_t sharedRecord,uint64_t sharedContext) {
  if(phase!=Idle) return false;
  fault=false;
  const auto assignment=sensorAssignment(chosen,board::gBoard);node=assignment.provider.index;
  if(assignment.kind!=SensorAssignment::Kind::NodeImu || node>3 || !CanMasterManager::configurationReconciled(node)) {fault=true;return true;}
  const auto& d=CanMasterManager::diagnostics();const auto& endpoint=d.control.nodes[node].endpoints[0];
  RemoteImuBinding b;b.node=node;b.boot=endpoint.effective_boot;b.uid=endpoint.effective_uid;b.masterBoot=d.control.master_boot_id;b.masterUid=d.hardwareUid;
  b.compactPackets=ImuAdmission::singleNodeSmokeBuild();
#if BODAQS_MEASUREMENT_VERSION >= 3
  b.compactPackets=true;b.sampleUnits=true;
#endif
  b.session=d.authority.session;
  record=sharedRecord;recordContext=sharedContext;
  b.recording=record;b.context=sharedContext;std::memcpy(b.effective,endpoint.effective,192);
  String text=chosen.name;chosen.params.get("imu_id",text);std::snprintf(b.sensorId,sizeof b.sensorId,"%s",text.c_str());
  text="";chosen.params.get("mount_point",text);std::snprintf(b.mountPoint,sizeof b.mountPoint,"%s",text.c_str());
  text="";chosen.params.get("calibration_ref",text);std::snprintf(b.calibrationRef,sizeof b.calibrationRef,"%s",text.c_str());
  text="frame";chosen.params.get("domain",text);std::snprintf(b.domain,sizeof b.domain,"%s",text.c_str());
  text="none";chosen.params.get("end",text);std::snprintf(b.end,sizeof b.end,"%s",text.c_str());
  chosen.params.getBool("orient_valid",b.orientationValid);
  const char* quaternionKeys[]={"orient_qw","orient_qx","orient_qy","orient_qz"};
  if(b.orientationValid) for(unsigned i=0;i<4;++i)
    if(!chosen.params.getFloat(quaternionKeys[i],b.mountingQuaternion[i])) {fault=true;return true;}
  revision=BdqV2Format::getU64(endpoint.effective+32);epoch=d.control.nodes[node].endpoint_epoch[0];
  // IDs are finalized before catalog generation; sources do not yet contain data.
  if(!stream.configure(b,uint16_t(34+2*node),uint16_t(35+2*node)) ) {stream.release();fault=true;return true;}
  fault=false;stopIntent=startIntent=false;cleanupQueued=false;phase=Allocated;began=millis();serial=0;
  firstFailure={};
  stopRequestedMs=stopConfirmedMs=0;stopConfirmed=false;completionFrozen=false;
  std::memset(objectProgress,0,sizeof objectProgress);std::memset(recordProgress,0,sizeof recordProgress);
  dataGate.store(0,std::memory_order_release);
  return true;
}
bool configured() {return phase!=Idle;}
bool prepared() {return phase==Idle || phase==Ready || (phase>=Stop && fault.load());}
bool recording() {return phase==Idle || phase==Recording || (phase>=Stop && fault.load());}
bool failed() {return fault || stream.failed();}
void start() {startIntent=true;}
void stop() {
  if(phase==Allocated) {dataGate.store(1);phase=Done;}
  if(!stopIntent) {stopRequestedMs=millis();tailBegan=stopRequestedMs;}
  stopIntent=true;
}
bool stopped() {return phase==Idle || phase==Done;}
bool tailDrained() {return stopped() || phase>=Fence;}
void release() {if(!stopped()) return;stream.release();phase=Idle;fault=false;}
uint16_t describe(BdqV2StreamDescriptor* out,uint16_t capacity,uint16_t) {
  if(!configured() || (phase>=Stop && fault.load())) return 0;
  if(out && capacity>=2) {out[0]=stream.descriptor(false);out[1]=stream.descriptor(true);}
  return 2;
}
void service() {
  if(phase==Idle || phase==Allocated || phase==Done) return;
  const uint32_t now=millis();
  if(phase>=Fence && !AcquisitionControl::active()) {phase=Done;return;}
  AcquisitionControl::Outcome out;AcquisitionControl::outcome(node,out);
  const bool fresh=out.serial!=serial;
  const bool success=fresh && out.result==AcquisitionControl::Result::Succeeded;
  const bool startupTimeout=(phase==Prepare || phase==PreparedSnapshot || phase==Starting) && uint32_t(now-began)>=10000;
  const bool retryableStop=stopIntent && phase==Stop && out.action==AcquisitionControl::Action::Stop &&
      !out.excluded && (out.result==AcquisitionControl::Result::Uncertain || out.result==AcquisitionControl::Result::Unavailable) &&
      (out.reason==7 || out.reason==10 || out.reason==26);
  const bool controlFailed=fresh && !retryableStop && (out.result==AcquisitionControl::Result::Rejected || out.result==AcquisitionControl::Result::Uncertain || out.result==AcquisitionControl::Result::Unavailable);
  if(!firstFailure.cause && (fault.load() || startupTimeout || stream.failed() || controlFailed)) {
    const auto& d=CanMasterManager::diagnostics();
    firstFailure.observedMs=now;firstFailure.phase=phase;
    firstFailure.action=static_cast<uint8_t>(out.action);firstFailure.result=static_cast<uint8_t>(out.result);firstFailure.reason=out.reason;
    firstFailure.cause=controlFailed?1:startupTimeout?2:stream.failed()?3:4;
    firstFailure.measurementPhase=d.measurement.phase;firstFailure.measurementReason=d.measurement.reason;
    firstFailure.measurementUnavailable=d.measurementUnavailable;
    firstFailure.objectsReceived=d.measurementObjectsReceived;firstFailure.transferErrors=d.measurementTransferErrors;
    firstFailure.transferErrorMask=d.measurementTransferErrorMask;
    firstFailure.streamFailureSite=stream.failureSite();
    firstFailure.timingAvailable=d.measurementTimingContext==recordContext;
    if(firstFailure.timingAvailable) firstFailure.timing=d.measurementTiming;
    LOGW_TAG("REMOTEIMU","first failure node=%u phase=%u cause=%u action=%u result=%u reason=%u mode=%u modeReason=%u unavailable=%u objects=%lu errors=%lu\n",
      node,firstFailure.phase,firstFailure.cause,firstFailure.action,firstFailure.result,firstFailure.reason,
      firstFailure.measurementPhase,firstFailure.measurementReason,firstFailure.measurementUnavailable,
      static_cast<unsigned long>(firstFailure.objectsReceived),static_cast<unsigned long>(firstFailure.transferErrors));
    [[maybe_unused]] const auto& t=firstFailure.timing;
    LOGW_TAG("DRAIN","window_us=%lu slots=%lu failed=%lu empty=%lu exchange_us=%llu max_exchange_us=%lu max_idle_us=%lu\n",
      (unsigned long)t.elapsedUs,(unsigned long)t.slots,(unsigned long)t.failedSlots,(unsigned long)t.emptySlots,
      (unsigned long long)t.exchangeUs,(unsigned long)t.maxExchangeUs,(unsigned long)t.maxIdleUs);
    LOGW_TAG("DRAIN","stage=first_failure timing_available=%u transfer_failed=%lu decode_failed=%lu\n",
      firstFailure.timingAvailable,(unsigned long)t.transferFailedSlots,(unsigned long)t.decodeFailedSlots);
    LOGW_TAG("DRAIN","polls sample=%lu evidence=%lu control=%lu protected=%lu shared=%lu fragments=%lu,%lu,%lu,%lu,%lu deferred=%lu,%lu\n",
      (unsigned long)t.polls[0],(unsigned long)t.polls[1],(unsigned long)t.polls[2],(unsigned long)t.polls[3],(unsigned long)t.polls[4],
      (unsigned long)t.fragments[0],(unsigned long)t.fragments[1],(unsigned long)t.fragments[2],(unsigned long)t.fragments[3],(unsigned long)t.fragments[4],
      (unsigned long)t.deferrals[0],(unsigned long)t.deferrals[1]);
  }
  if(startupTimeout || stream.failed()) {fault=true;stop();}
  if(fault.load() && phase<Stop) stop();
  if(controlFailed) {
    fault=true;if(phase<Stop) stop();
  }
  if(stopIntent && phase<Stop) {phase=Stop;if(fault.load()) dataGate.fetch_or(1);cleanupQueued=send(AcquisitionControl::Action::Stop);nextCleanupAttempt=now+300;return;}
  switch(phase) {
    case Prepare: if(success && out.action==AcquisitionControl::Action::Prepare) {phase=PreparedSnapshot;send(AcquisitionControl::Action::Snapshot);} break;
    case PreparedSnapshot:
      if(success && out.action==AcquisitionControl::Action::Snapshot && out.snapshotValid) {revision=out.revision;epoch=out.epoch;phase=Ready;} break;
    case Ready: if(startIntent) {phase=Starting;began=now;send(AcquisitionControl::Action::Start);} break;
    case Starting: if(success && out.action==AcquisitionControl::Action::Start) phase=Recording;break;
    case Stop:
      if(fresh && retryableStop) cleanupQueued=false;
      if(success && out.action==AcquisitionControl::Action::Stop) {
        stopConfirmed=true;stopConfirmedMs=now;tailBegan=now;phase=Tail;
      } else if(uint32_t(now-stopRequestedMs)>=BODAQS_ACQ_LEASE_MS+5000U) {
        // Bounded file-prefix closure, explicitly not proof of remote expiry.
        fault=true;phase=Tail;
      }
      else if(!cleanupQueued && int32_t(now-nextCleanupAttempt)>=0) {
        cleanupQueued=send(AcquisitionControl::Action::Stop);nextCleanupAttempt=now+1000;
      }
      break;
    case Tail:
      // Keep transport/producer queues alive for the complete normal tail
      // interval. The independent storage worker continues writing throughout.
      if(!stopConfirmed || uint32_t(now-tailBegan)>=5000) {
        dataGate.fetch_or(1,std::memory_order_acq_rel);
        if(!(dataGate.load(std::memory_order_acquire)&2u) &&
           (stream.failed() || stream.finish(static_cast<uint32_t>(esp_timer_get_time())))) {
          frozenCompletion={};frozenCompletion.stopRequestedMs=stopRequestedMs;
          frozenCompletion.stopConfirmedMs=stopConfirmedMs;frozenCompletion.drainClosedMs=now;
          frozenCompletion.stopConfirmed=stopConfirmed;frozenCompletion.uncertain=!stopConfirmed;
          frozenCompletion.sourceFinalObserved=stream.terminalBoundary(frozenCompletion.finalSequence,frozenCompletion.streamEpoch);
          completionFrozen.store(true,std::memory_order_release);
          phase=Fence;cleanupQueued=send(AcquisitionControl::Action::Fence);nextCleanupAttempt=now+3500;
        }
      }
      break;
    case Fence:
      if(out.action==AcquisitionControl::Action::Fence && out.result==AcquisitionControl::Result::Succeeded && out.localFenceComplete) {phase=Release;cleanupQueued=send(AcquisitionControl::Action::Release);nextCleanupAttempt=now+3500;}
      else if(int32_t(now-nextCleanupAttempt)>=0 && (!cleanupQueued || out.result!=AcquisitionControl::Result::Pending)) {
        cleanupQueued=send(AcquisitionControl::Action::Fence);nextCleanupAttempt=now+3500;
      }
      break;
    case Release:
      if(success && out.action==AcquisitionControl::Action::Release) {phase=Exit;cleanupQueued=true;}
      else if(int32_t(now-nextCleanupAttempt)>=0 && (!cleanupQueued || out.result!=AcquisitionControl::Result::Pending)) {
        cleanupQueued=send(AcquisitionControl::Action::Release);nextCleanupAttempt=now+3500;
      }
      break;
    case Exit: if(!AcquisitionControl::active()) phase=Done;break;
    default:break;
  }
}
};
Participant peers[4];
uint8_t selected=0;
uint64_t allocatedSession=0,nextRecording=1,context=0;
ImuAdmission::Profile profile;
ImuAdmission::Report report;
struct SharedProgress {uint32_t object=0;uint8_t pending=0;};
// Sync and bridge may both retry while one participant is blocked. Each class
// must retain its own fanout progress to avoid re-copying into healthy peers.
SharedProgress sharedProgress[2];
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
void observeConsumer(uint8_t cls,Participant& peer,bool accepted,const uint8_t* p,uint16_t total) {
 const auto queues=peer.stream.queueState();
 ImuFlowDiagnostics::consumer(cls,accepted,queues.samples,queues.evidence,queues.sampleCapacity,queues.evidenceCapacity);
 ImuFlowDiagnostics::nodeConsumer(peer.node,accepted,queues.packetsAccepted,queues.samplesAccepted,
   queues.samples,queues.evidence,queues.sampleCapacity,queues.evidenceCapacity);
 if(cls==7 && total==8 && p[0]==1 && p[1]==9)
   ImuFlowDiagnostics::loss(BdqV2Format::getU32(p+4),millis(),micros());
}
void logFlowSnapshot(const char* stage,[[maybe_unused]] const ImuFlowDiagnostics::Snapshot& s) {
 LOGW_TAG("FLOW","stage=%s context=%llu began_ms=%lu observed_ms=%lu services=%lu loss_counter=%lu\n",
  stage,(unsigned long long)s.context,(unsigned long)s.beganMs,(unsigned long)s.observedMs,(unsigned long)s.services,
  (unsigned long)s.lossCounter);
 LOGW_TAG("FLOW","stage=%s poll=%lu ackfetch=%lu outgoing=%lu other=%lu empty=%lu wire_failed=%lu deferred=%lu,%lu\n",
  stage,
  (unsigned long)s.requests[0],(unsigned long)s.requests[1],(unsigned long)s.requests[2],(unsigned long)s.requests[3],
  (unsigned long)s.empty,(unsigned long)s.wireFailures,(unsigned long)s.deferred[0],(unsigned long)s.deferred[1]);
 if(s.measurementFailuresAvailable)
  LOGW_TAG("FLOW","stage=%s measurement_transfer_failed=%lu measurement_decode_failed=%lu\n",
    stage,(unsigned long)s.measurementTransferFailures,(unsigned long)s.measurementDecodeFailures);
 LOGW_TAG("FLOW","stage=%s queue_packet_peak=%lu/%lu queue_evidence_peak=%lu/%lu gate_wait=%lu bridge_wait=%lu management_wait=%lu\n",
  stage,(unsigned long)s.sampleQueuePeak,(unsigned long)s.sampleCapacity,(unsigned long)s.evidenceQueuePeak,(unsigned long)s.evidenceCapacity,
  (unsigned long)s.gateWait,(unsigned long)s.consumerWait[5],(unsigned long)s.consumerWait[6]);
 for(unsigned i=0;i<5;++i) {
  LOGW_TAG("FLOW","stage=%s class=%u new_frag=%lu replay_frag=%lu admitted=%lu consumer_calls=%lu consumer_wait=%lu polls=%lu fetch_target=%lu\n",
   stage,i+1,(unsigned long)s.newFragments[i],(unsigned long)s.repeatFragments[i],(unsigned long)s.admitted[i],
   (unsigned long)s.consumerCalls[i],(unsigned long)s.consumerWait[i],(unsigned long)s.polls[i],(unsigned long)s.fetchTargets[i]);
  LOGW_TAG("FLOW","stage=%s class=%u proof_n=%lu proof_total_us=%llu proof_max_us=%lu proof_pending=%lu proof_oldest_us=%lu\n",
   stage,i+1,
   (unsigned long)s.proofMatches[i],(unsigned long long)s.proofWaitTotalUs[i],(unsigned long)s.proofWaitMaxUs[i],
   (unsigned long)s.proofPending[i],(unsigned long)s.proofOldestUs[i]);
 }
 (void)stage;
 for(unsigned n=0;n<4;++n) if(selected&(1u<<n)) {
  [[maybe_unused]] const auto& d=s.nodes[n];
  LOGW_TAG("FLOW","stage=%s node=%u packets_accepted=%lu samples_accepted=%llu packet_sampled_peak=%lu/%lu evidence_sampled_peak=%lu/%lu consumer_wait=%lu\n",
   stage,n,(unsigned long)d.packetsAccepted,(unsigned long long)d.samplesAccepted,
   (unsigned long)d.sampleQueuePeak,(unsigned long)d.sampleCapacity,
   (unsigned long)d.evidenceQueuePeak,(unsigned long)d.evidenceCapacity,(unsigned long)d.consumerWait);
 }
}
#endif
bool consume(uint8_t cls,uint8_t address,uint32_t identity,const uint8_t* p,uint16_t total) {
 if(address<4) {
  if(!(selected&(1u<<address))) return true;
  const bool accepted=peers[address].consume(cls,address,identity,p,total);
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  observeConsumer(cls,peers[address],accepted,p,total);
#endif
  return accepted;
 }
 if(address!=255 || cls<5 || cls>6) return false;
 auto& progress=sharedProgress[cls-5];
 if(progress.object!=identity) {progress.object=identity;progress.pending=selected;}
 for(uint8_t n=0;n<4;++n) if(progress.pending&(1u<<n)) {
  const bool accepted=peers[n].consume(cls,address,identity,p,total);
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  observeConsumer(cls,peers[n],accepted,p,total);
#endif
  if(!accepted) return false;
  progress.pending&=uint8_t(~(1u<<n));
 }
 return true;
}
void discardAllocated() {for(auto& peer:peers) {peer.stream.release();peer.phase=Idle;peer.fault=false;}selected=0;}
}
const ImuAdmission::Report& admission() {return report;}
bool failure(uint8_t node,Failure& out) {
 if(node>=4 || !(selected&(1u<<node)) || !peers[node].firstFailure.cause) return false;
 out=peers[node].firstFailure;return true;
}
void logDiagnostics() {
 [[maybe_unused]] const auto& d=CanMasterManager::diagnostics();
 LOGW_TAG("REMOTEIMU","cleanup active=%u selected=0x%x mode=%u modeReason=%u unavailable=%u objects=%lu errors=%lu\n",
   AcquisitionControl::active(),selected,d.measurement.phase,d.measurement.reason,d.measurementUnavailable,
   static_cast<unsigned long>(d.measurementObjectsReceived),static_cast<unsigned long>(d.measurementTransferErrors));
 for(uint8_t n=0;n<4;++n) if(selected&(1u<<n)) {
   AcquisitionControl::Outcome out;AcquisitionControl::outcome(n,out);
   LOGW_TAG("REMOTEIMU","node=%u cleanupPhase=%u action=%u result=%u reason=%u excluded=%u localFence=%u\n",
     n,static_cast<unsigned>(peers[n].phase.load()),static_cast<unsigned>(out.action),static_cast<unsigned>(out.result),out.reason,out.excluded,out.localFenceComplete);
 }
 AcquisitionControl::FenceDiagnostics f;AcquisitionControl::fenceDiagnostics(f);
 LOGW_TAG("REMOTEIMU","fence observed_ms=%lu attempts=%lu observations=%lu flags=0x%x all=%u verified=%u recording=0x%x confirmed=0x%x ordinary=0x%x protected=0x%x mutation=0x%x mailbox=0x%x recovering=%u failed=%u\n",
   (unsigned long)f.observedMs,(unsigned long)f.inspections,(unsigned long)f.observations,f.modeFlags,f.allFenced,f.verified,
   f.recordingMask,f.confirmedMask,f.ordinaryMask,f.protectedMask,f.mutationMask,f.mailboxMask,f.recovering,f.failed);
 for(uint8_t node=0;node<4;++node) if(selected&(1u<<node)) for(uint8_t lane=0;lane<3;++lane) {
   [[maybe_unused]] const auto& in=f.data[lane][lane==2?0:node];
   LOGW_TAG("REMOTEIMU","retained class=%u node=%u object=%lu ack_object=%lu flags=0x%x\n",
     lane==2?5:lane+1,lane==2?255:node,(unsigned long)in.object,(unsigned long)in.ackObject,in.flags);
 }

}
bool setAdmissionProfile(const ImuAdmission::Profile& p) {
 if(selected || AcquisitionControl::active()) return false;
 profile=p;return true;
}
bool configure(const LoggerConfig& cfg) {
 if(selected) return false;
 report={};report.benchOnly=ImuAdmission::singleNodeSmokeBuild();SensorSpec chosen[4];uint8_t mask=0;
 bool otherActiveSensors=false;uint8_t benchAdcMask=0;
 for(uint8_t i=0;i<cfg.sensorCount();++i) {
  SensorSpec spec;bool muted=false;
  if(!cfg.getSensorSpec(i,spec)) continue;
  if(!SensorManager::getMuted(i,muted)) muted=spec.mutedDefault;
  if(muted) continue;
  if(spec.type!=SensorType::LSM6DSO32XImu) {
   const auto a=sensorAssignment(spec,board::gBoard);
   long ain=-1,mode=1;bool includeRaw=false;
   spec.params.getInt("ain",ain);spec.params.getInt("output_mode",mode);
   spec.params.getBool("include_raw",includeRaw);
   const bool channelBench=ImuAdmission::channelRateBenchBuild();
   const uint8_t bit=channelBench?(ain>=0 && ain<8?uint8_t(1u<<ain):0):(ain==0?1:ain==4?2:0);
   const bool mapped=channelBench?(ain>=0 && a.input==ain%4 && a.bus==ain/4)
                                :(a.input==0 && a.bus==(ain==4?1:0));
   if(ImuAdmission::singleNodeAdcSmokeBuild() && spec.type==SensorType::AnalogPot &&
      a.kind==SensorAssignment::Kind::ExternalAdc && mapped &&
      bit && !(benchAdcMask&bit) && !includeRaw && (mode==0 || mode==1))
    benchAdcMask|=bit;
   else otherActiveSensors=true;
   continue;
  }
  report.attempted=true;
  auto assignment=sensorAssignment(spec,board::gBoard);uint8_t n=assignment.provider.index;
  if(assignment.kind!=SensorAssignment::Kind::NodeImu || n>3 || (mask&(1u<<n)) || !CanMasterManager::configurationReconciled(n)) {
   report.reason=ImuAdmission::Reason::Eligibility;return true;
  }
  if(!CanMasterManager::acquisitionLinkCompatible(n)) {report.reason=ImuAdmission::Reason::Link;return true;}
  chosen[n]=spec;mask|=1u<<n;
 }
 ImuAdmission::Demand demand;
 demand.loggerRateHz=cfg.sampleRateHz;
 for(uint8_t n=0;n<4;++n) if(mask&(1u<<n)) ++demand.nodes;
 for(uint8_t a=0;a<2;++a) if(board::gBoard && a<board::gBoard->external_adc_count && AnalogInputManager::activeChannelCount(a))
  demand.adc[a]={AnalogInputManager::configuredDataRateSps(a),board::gBoard->external_adcs[a].spi_hz,
                AnalogInputManager::activeChannelCount(a)};
 const bool benchMaskAllowed=ImuAdmission::channelRateBenchBuild()?((ImuAdmission::multiNodeBenchBuild() && benchAdcMask==0) || benchAdcMask==0x03 || benchAdcMask==0x11 ||
      (ImuAdmission::scalingBenchBuild() && benchAdcMask==0x33)):benchAdcMask==3;
 report=ImuAdmission::sampleUnitBenchBuild()
     ? ImuAdmission::evaluateSampleUnitBench(demand,otherActiveSensors)
     : ImuAdmission::multiNodeBenchBuild()
     ? ImuAdmission::evaluateMultiNodeBench(demand,otherActiveSensors || !benchMaskAllowed)
     : ImuAdmission::singleNodeAdcSmokeBuild()
     ? ImuAdmission::evaluateSingleNodeAdcSmoke(demand,otherActiveSensors || !benchMaskAllowed)
     : ImuAdmission::singleNodeSmokeBuild()
     ? ImuAdmission::evaluateSingleNodeSmoke(demand,otherActiveSensors)
     : ImuAdmission::evaluate(demand,profile);
 if(report.reason!=ImuAdmission::Reason::None || !mask) return true;
 uint64_t session=CanMasterManager::diagnostics().authority.session;
 if(allocatedSession!=session) {allocatedSession=session;nextRecording=1;}
 if(!nextRecording || nextRecording==UINT64_MAX) {report.reason=ImuAdmission::Reason::Eligibility;return true;}
 uint64_t record=nextRecording++;
 const uint64_t previous=context;
 context=(uint64_t(esp_random())<<32)|esp_random();
 context^=session^(record*UINT64_C(0x9e3779b97f4a7c15));
 if(!context || context==previous) {report.reason=ImuAdmission::Reason::Eligibility;return true;}
 // Allocate every queue and definition buffer before any authorization.
 for(uint8_t n=0;n<4;++n) if(mask&(1u<<n)) {
  // Participant configure performs no PREPARE until the complete allocation pass.
  if(!peers[n].configure(chosen[n],record,context) || peers[n].fault.load()) {
   discardAllocated();report.reason=ImuAdmission::Reason::Allocation;return true;
  }
 }
 report.loggerBytes=sizeof(peers)+demand.nodes*RemoteImuStream::allocatedBufferBytes(ImuAdmission::singleNodeSmokeBuild())+
    AcquisitionControl::reservedBytes()+sizeof(CanMasterManager::Diagnostics);
 selected=mask;for(auto& progress:sharedProgress) progress={};
 return true;
}
bool resourcesReady(size_t storageReservedBytes) {
 if(!selected) return true;
 bool allocated=false;uint64_t record=0;
 for(uint8_t n=0;n<4;++n) if(selected&(1u<<n)) {allocated|=peers[n].phase==Allocated;record=peers[n].record;}
 if(!allocated) return true;
 report.loggerBytes+=storageReservedBytes;
 if(!AcquisitionControl::setDataConsumer(consume,selected) || !AcquisitionControl::begin(record,context)) {
  discardAllocated();report.reason=ImuAdmission::Reason::Eligibility;return false;
 }
 for(uint8_t n=0;n<4;++n) if(selected&(1u<<n)) {
  peers[n].phase=Prepare;peers[n].began=millis();
  if(!peers[n].send(AcquisitionControl::Action::Prepare)) {peers[n].fault=true;peers[n].stop();}
 }
 return true;
}
bool configured() {return selected!=0;}
const char* failureReason() {return report.reason==ImuAdmission::Reason::None?"Remote IMU excluded":ImuAdmission::reasonText(report.reason);}
bool failed() {if(report.reason!=ImuAdmission::Reason::None) return true;for(uint8_t n=0;n<4;++n) if((selected&(1u<<n)) && peers[n].failed()) return true;return false;}
bool prepared() {for(uint8_t n=0;n<4;++n) if((selected&(1u<<n)) && !peers[n].prepared()) return false;return true;}
bool recording() {for(uint8_t n=0;n<4;++n) if((selected&(1u<<n)) && !peers[n].recording()) return false;return true;}
void start() {for(uint8_t n=0;n<4;++n) if(selected&(1u<<n)) peers[n].start();}
void stop() {for(uint8_t n=0;n<4;++n) if(selected&(1u<<n)) peers[n].stop();}
bool stopped() {for(uint8_t n=0;n<4;++n) if((selected&(1u<<n)) && !peers[n].stopped()) return false;return true;}
bool finalMeasurementFailures(uint32_t& transfer,uint32_t& decode) {
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
 if(!selected || !stopped() || !ImuFlowDiagnostics::haveFinished ||
    ImuFlowDiagnostics::finished.context!=context || !ImuFlowDiagnostics::finished.measurementFailuresAvailable) return false;
 transfer=ImuFlowDiagnostics::finished.measurementTransferFailures;
 decode=ImuFlowDiagnostics::finished.measurementDecodeFailures;return true;
#else
 (void)transfer;(void)decode;return false;
#endif
}
bool completion(uint8_t node,Completion& out) {
 if(node>3 || !(selected&(1u<<node)) || !peers[node].completionFrozen.load(std::memory_order_acquire)) return false;
 out=peers[node].frozenCompletion;return true;
}
bool finalNodeDiagnostics(uint8_t node,ImuFlowDiagnostics::NodeStats& out) {
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
 if(node>3 || !(selected&(1u<<node)) || !stopped() || !ImuFlowDiagnostics::haveFinished ||
    ImuFlowDiagnostics::finished.context!=context) return false;
 out=ImuFlowDiagnostics::finished.nodes[node];return true;
#else
 (void)node;(void)out;return false;
#endif
}
const MeasurementReplyCapture* finalRejectedMeasurementReplies() {
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
 uint32_t transfer=0,decode=0;
 if(finalMeasurementFailures(transfer,decode)) return &ImuFlowDiagnostics::finishedReplies;
#endif
 return nullptr;
}
const uint32_t* finalMeasurementDecodeReasons() {
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
 uint32_t transfer=0,decode=0;
 if(finalMeasurementFailures(transfer,decode)) return ImuFlowDiagnostics::finished.measurementDecodeReasons;
#endif
 return nullptr;
}
bool readyForFileFinalization() {
 for(uint8_t n=0;n<4;++n) if(selected&(1u<<n)) {
  Completion c;
  if(!peers[n].stopped() && (!completion(n,c) || c.stopConfirmed)) return false;
 }
 return true;
}
bool tailDrained() {for(uint8_t n=0;n<4;++n) if((selected&(1u<<n)) && !peers[n].tailDrained()) return false;return true;}
uint32_t discardedTailObjects() {uint32_t total=0;for(uint8_t node=0;node<4;++node) {AcquisitionControl::Outcome out;AcquisitionControl::outcome(node,out);uint32_t n=out.tailObjectsDiscarded;if(UINT32_MAX-total<n) return UINT32_MAX;total+=n;}return total;}
void release() {
 if(!stopped()) return;
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
 // stopped() acquires inactive owner state before reading owner-written snapshots.
 if(selected && ImuFlowDiagnostics::haveFinished && ImuFlowDiagnostics::finished.context==context) {
  if(ImuFlowDiagnostics::haveFirstLoss && ImuFlowDiagnostics::firstLoss.context==context)
    logFlowSnapshot("first_loss",ImuFlowDiagnostics::firstLoss);
  logFlowSnapshot("finished",ImuFlowDiagnostics::finished);
#if BODAQS_PIPELINE_TRACE
  MeasurementPipelineTrace::dump([](const char* line) {Log_taggedPrintln(LOG_WARN,"PIPE",line);});
#endif
 }
#endif
 for(auto& p:peers) p.release();
 selected=0;report={};AcquisitionControl::setDataConsumer(nullptr,0);
}
uint16_t describe(BdqV2StreamDescriptor* out,uint16_t capacity,uint16_t firstId) {
 uint16_t count=0;for(uint8_t n=0;n<4;++n) if(selected&(1u<<n)) {
  uint16_t remaining=capacity>count?uint16_t(capacity-count):0;
  count+=peers[n].describe(out && remaining>=2?out+count:nullptr,remaining,firstId+count);
 }return count;
}
void service() {
 bool exit=true;
 for(uint8_t n=0;n<4;++n) if(selected&(1u<<n)) {peers[n].service();if(peers[n].phase!=Exit && peers[n].phase!=Done) exit=false;}
 if(selected && exit && AcquisitionControl::active()) AcquisitionControl::requestExit();
}
}
