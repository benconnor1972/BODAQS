#include "RemoteImuRecording.h"
#include "RemoteImuStream.h"
#include "AcquisitionControl.h"
#include "CanMasterManager.h"
#include "SensorAssignment.h"
#include "BoardSelect.h"
#include "SensorManager.h"
#include "ConfigManager.h"
#include <Arduino.h>
#include <esp_timer.h>
#include <cstring>

namespace RemoteImuRecording {
namespace {
RemoteImuStream stream;
enum Phase { Idle, Prepare, PreparedSnapshot, Ready, Starting, Recording, Stop,
             Tail, Fence, Release, Exit, Done };
Phase phase=Idle;
uint8_t node=0;
uint64_t record=0,revision=0,epoch=0;
uint64_t allocatedSession=0,nextRecording=1;
uint32_t serial=0,began=0,tailBegan=0;
std::atomic<bool> fault{false};
bool stopIntent=false,startIntent=false;
uint32_t nextCleanupAttempt=0;
bool cleanupQueued=false;
// Bit0 closes admission, bit1 marks an active producer callback. The main
// owner closes without waiting; storage finalization starts only after bit1
// retires. A late object is ACKed as discarded, never queued into a closing file.
std::atomic<uint8_t> dataGate{1};
std::atomic<uint32_t> tailDiscards{0};
uint32_t objectProgress[2]={};
uint16_t recordProgress[2]={};
bool consume(uint8_t cls,uint8_t address,uint32_t identity,const uint8_t* p,uint16_t total) {
  uint8_t open=0;
  if(!dataGate.compare_exchange_strong(open,2,std::memory_order_acq_rel)) {
    if(tailDiscards.load()!=UINT32_MAX) tailDiscards.fetch_add(1);
    return true;
  }
  struct Retire {~Retire(){dataGate.fetch_and(1,std::memory_order_release);}} retire;
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
}
bool configure(const LoggerConfig& cfg) {
  if(phase!=Idle) return false;
  fault=false;
  SensorSpec chosen;unsigned count=0;
  for(uint8_t i=0;i<cfg.sensorCount();++i) {
    SensorSpec spec;bool muted=false;
    if(!cfg.getSensorSpec(i,spec) || spec.type!=SensorType::LSM6DSO32XImu) continue;
    if(!SensorManager::getMuted(i,muted)) muted=spec.mutedDefault;
    if(muted) continue;
    chosen=spec;++count;
  }
  if(!count) return true;
  // Four-node scheduling/resource admission is a separate implementation slice;
  // never silently record only the first of several requested remote IMUs.
  if(count!=1) {fault=true;return true;}
  const auto assignment=sensorAssignment(chosen,board::gBoard);node=assignment.provider.index;
  if(assignment.kind!=SensorAssignment::Kind::NodeImu || node>3 || !CanMasterManager::configurationReconciled(node)) {fault=true;return true;}
  const auto& d=CanMasterManager::diagnostics();const auto& endpoint=d.control.nodes[node].endpoints[0];
  RemoteImuBinding b;b.node=node;b.boot=endpoint.effective_boot;b.uid=endpoint.effective_uid;b.masterBoot=d.control.master_boot_id;b.masterUid=d.hardwareUid;
  b.session=d.authority.session;
  if(allocatedSession!=b.session) {allocatedSession=b.session;nextRecording=1;}
  if(!nextRecording || nextRecording==UINT64_MAX) {fault=true;return true;}
  record=nextRecording++;
  b.recording=record;b.context=record;std::memcpy(b.effective,endpoint.effective,192);
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
  if(!stream.configure(b,34,35) || !AcquisitionControl::setDataConsumer(consume,1u<<node) ||
     !AcquisitionControl::begin(record,record)) {stream.release();fault=true;return true;}
  fault=false;stopIntent=startIntent=false;cleanupQueued=false;phase=Prepare;began=millis();serial=0;
  std::memset(objectProgress,0,sizeof objectProgress);std::memset(recordProgress,0,sizeof recordProgress);
  tailDiscards.store(0);dataGate.store(0,std::memory_order_release);
  if(!send(AcquisitionControl::Action::Prepare)) {fault=true;stop();}
  return true;
}
bool configured() {return phase!=Idle;}
bool prepared() {return phase==Idle || phase==Ready || (phase>=Stop && fault.load());}
bool recording() {return phase==Idle || phase==Recording || (phase>=Stop && fault.load());}
bool failed() {return fault || stream.failed();}
void start() {startIntent=true;}
void stop() {if(!stopIntent) tailBegan=millis();stopIntent=true;}
bool stopped() {return phase==Idle || phase==Done;}
bool tailDrained() {return stopped() || phase>=Fence;}
uint32_t discardedTailObjects() {return tailDiscards.load();}
void release() {if(!stopped()) return;stream.release();phase=Idle;fault=false;AcquisitionControl::setDataConsumer(nullptr,0);}
uint16_t describe(BdqV2StreamDescriptor* out,uint16_t capacity,uint16_t) {
  if(!configured() || (phase>=Stop && fault.load())) return 0;
  if(out && capacity>=2) {out[0]=stream.descriptor(false);out[1]=stream.descriptor(true);}
  return 2;
}
void service() {
  if(phase==Idle || phase==Done) return;
  const uint32_t now=millis();
  AcquisitionControl::Outcome out;AcquisitionControl::outcome(node,out);
  const bool fresh=out.serial!=serial;
  const bool success=fresh && out.result==AcquisitionControl::Result::Succeeded;
  if((phase<=Starting && uint32_t(now-began)>=10000) || stream.failed()) {fault=true;stop();}
  if(fault.load() && phase<Stop) stop();
  if(fresh && (out.result==AcquisitionControl::Result::Rejected || out.result==AcquisitionControl::Result::Uncertain || out.result==AcquisitionControl::Result::Unavailable)) {
    fault=true;if(phase<Stop) stop();
  }
  if(stopIntent && phase<Stop) {phase=Stop;if(fault.load()) dataGate.fetch_or(1);cleanupQueued=send(AcquisitionControl::Action::Stop);nextCleanupAttempt=now+300;return;}
  switch(phase) {
    case Prepare: if(success && out.action==AcquisitionControl::Action::Prepare) {phase=PreparedSnapshot;send(AcquisitionControl::Action::Snapshot);} break;
    case PreparedSnapshot:
      if(success && out.action==AcquisitionControl::Action::Snapshot && out.snapshotValid) {revision=out.revision;epoch=out.epoch;phase=Ready;} break;
    case Ready: if(startIntent) {phase=Starting;send(AcquisitionControl::Action::Start);} break;
    case Starting: if(success && out.action==AcquisitionControl::Action::Start) phase=Recording;break;
    case Stop:
      if((success && out.action==AcquisitionControl::Action::Stop) || uint32_t(now-tailBegan)>=1000) phase=Tail;
      else if(!cleanupQueued && int32_t(now-nextCleanupAttempt)>=0) {cleanupQueued=send(AcquisitionControl::Action::Stop);nextCleanupAttempt=now+300;}
      break;
    case Tail:
      // Keep transport/producer queues alive for the complete normal tail
      // interval. The independent storage worker continues writing throughout.
      if(uint32_t(now-tailBegan)>=5000) {
        dataGate.fetch_or(1,std::memory_order_acq_rel);
        if(!(dataGate.load(std::memory_order_acquire)&2u) &&
           (stream.failed() || stream.finish(static_cast<uint32_t>(esp_timer_get_time())))) {
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
      if(success && out.action==AcquisitionControl::Action::Release) {phase=Exit;cleanupQueued=AcquisitionControl::requestExit();}
      else if(int32_t(now-nextCleanupAttempt)>=0 && (!cleanupQueued || out.result!=AcquisitionControl::Result::Pending)) {
        cleanupQueued=send(AcquisitionControl::Action::Release);nextCleanupAttempt=now+3500;
      }
      break;
    case Exit: if(!AcquisitionControl::active()) phase=Done;break;
    default:break;
  }
}
}
