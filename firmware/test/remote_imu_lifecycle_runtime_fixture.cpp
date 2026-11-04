#include "RemoteImuRecording.h"
static bool retirePhysicalMaster=true;

static void recordingSteps(unsigned duration) {
  const uint32_t until=clockMs+duration;
  while(int32_t(clockMs-until)<0) {
    ++clockMs;
    for(uint8_t n=0;n<4;++n) bodaqs_control_acquisition_tick(&acquisitions[n],clockMs);
    // Simulate the master's physical driver retiring DMA/preloaded data only
    // after the production service asks for that fence.
    if(retirePhysicalMaster && master.acquisition_retirement_pending)
      bodaqs_master_service_measurement_fence(&master,true,true);
    AcquisitionControl::service();
    const bool wasFailed=RemoteImuRecording::failed();
    RemoteImuRecording::service();
    if(!wasFailed && RemoteImuRecording::failed()) {
      AcquisitionControl::Outcome o;AcquisitionControl::outcome(0,o);
      std::fprintf(stderr,"first failure at%lu: result=%u reason=%u action=%u nodePhase=%u endpointEpoch=%llu\n",(unsigned long)clockMs,unsigned(o.result),o.reason,unsigned(o.action),acquisitions[0].phase,(unsigned long long)node.view.endpoint_epoch[0]);
    }
  }
}

int main(int argc,char**) {
  ImuAdmission::Profile costs;costs.qualified=true;costs.sampleSlotUs=64;costs.auxiliarySlotUs=64;costs.sampleDrainSlotsPerSecond=14000;
  assert(RemoteImuRecording::setAdmissionProfile(costs));
  saved.type=SensorType::LSM6DSO32XImu;std::strcpy(saved.name,"remote_imu");
  assert(savedParams.set("provider","can:0"));
  assert(savedParams.set("endpoint","imu"));
  assert(savedParams.set("profile","imu6_3333_32g_2000dps_v1"));
  saved.params.bind(&savedParams);
  fixtureSensorCount=argc>1?4:1;
  for(unsigned n=1;n<fixtureSensorCount;++n) {
    extra[n-1]=saved;extraParams[n-1]=savedParams;
    char provider[8];std::snprintf(provider,sizeof provider,"can:%u",n);
    assert(extraParams[n-1].set("provider",provider));extra[n-1].params.bind(&extraParams[n-1]);
  }
  reset();lifecycleEnabled=true;fastMeasurementClock=true;
  BodaqsMasterDiscoveryRecord records[4]={};
  for(uint8_t n=0;n<4;++n) {
    auto& f=peerFixture(n);f.view.active_session=0;f.authority={};f.view.flags=0;
    f.authority.next_challenge=1;
    bodaqs_control_acquisition_init(&acquisitions[n],&f.authority,&f.view,f.apply.effective,backendEvent,reinterpret_cast<void*>(static_cast<uintptr_t>(n)));
    acquisitionSnapshots[n]={};
    acquisitionSnapshots[n].capture=bodaqs_control_apply_capture;
    acquisitionSnapshots[n].capture_context=&f.apply;
    acquisitionSnapshots[n].capture_acquisition=bodaqs_control_acquisition_capture;
    acquisitionSnapshots[n].acquisition_context=&acquisitions[n];
    records[n].node_address=n;records[n].flags=n<fixtureSensorCount?1:0;records[n].boot_id=f.view.boot_id;
    records[n].capabilities=BODAQS_CAN_LINK_CAP_ACQUISITION;records[n].endpoint_mask=1;records[n].hardware_uid=123+n;
  }
  bodaqs_master_service_set_inventory(&master,2,records,4);
  assert(CanMasterManager::probeNow());
  for(unsigned wait=0;wait<300000;++wait) {
    advance(1);bool ready=true;
    for(unsigned n=0;n<fixtureSensorCount;++n) ready=ready && CanMasterManager::configurationReconciled(n);
    if(ready) break;
  }
  for(unsigned n=0;n<fixtureSensorCount;++n) if(!CanMasterManager::configurationReconciled(n)) {
    const auto& d=CanMasterManager::diagnostics();std::fprintf(stderr,"unreconciled %u desired=%d generation=%llu current=%d session=%llu active=%llu phase=%u\n",n,d.desiredEnabled[n],(unsigned long long)d.desiredGeneration[n],d.control.nodes[n].endpoints[0].current,(unsigned long long)d.authority.session,(unsigned long long)peerFixture(n).view.active_session,peerFixture(n).apply.phase);
    assert(false);
  }
  // Handoff must drain the observer's page/release chain. Abandoning its
  // pinned effective snapshot makes the next acquisition snapshot reject BUSY.
  CanMasterManager::beginRecordingHandoff();advance(4000);
  assert(CanMasterManager::recordingHandoffReady());
  assert(RemoteImuRecording::configure(config));
  assert(RemoteImuRecording::configured());
  assert(!RemoteImuRecording::prepared());
  recordingSteps(100);
  for(unsigned n=0;n<fixtureSensorCount;++n) assert(!acquisitions[n].recording && !acquisitions[n].phase);
  assert(!AcquisitionControl::active()); // no PREPARE before storage allocation
  assert(RemoteImuRecording::resourcesReady());
  recordingSteps(8000);
  if(RemoteImuRecording::failed()) {
    AcquisitionControl::Outcome o;AcquisitionControl::outcome(0,o);
    std::fprintf(stderr,"prepare failed: configured=%d prepared=%d result=%u reason=%u action=%u phase=%u lease=%d\n",RemoteImuRecording::configured(),RemoteImuRecording::prepared(),unsigned(o.result),o.reason,unsigned(o.action),acquisitions[0].phase,acquisitions[0].lease_valid);
  }
  assert(RemoteImuRecording::prepared());
  assert(!RemoteImuRecording::failed());
  assert(acquisitions[0].phase==2 && acquisitions[0].lease_valid);
  assert(!RemoteImuRecording::recording()); // Preparation cannot start samples.
  BdqV2StreamDescriptor descriptors[8];
  assert(RemoteImuRecording::describe(descriptors,8,2)==2*fixtureSensorCount);
  assert(!strcmp(descriptors[0].payloadSchema,"bodaqs.can_imu6.v1"));
  assert(!strcmp(descriptors[1].payloadSchema,"bodaqs.can_timing_evidence.v1"));
  RemoteImuRecording::start();recordingSteps(2000);
  assert(RemoteImuRecording::recording());
  for(unsigned n=0;n<fixtureSensorCount;++n) assert(acquisitions[n].phase==3 && acquisitions[n].lease_valid);
  const uint32_t stoppedAt=clockMs;
  RemoteImuRecording::stop();
  clockMs+=37; // Main-loop scheduling delay must not extend the operator tail.
  RemoteImuRecording::service();
  recordingSteps(800);
  assert(acquisitions[0].terminal && acquisitions[0].stopped && !acquisitions[0].lease_valid);
  assert(!RemoteImuRecording::failed());
  assert(!RemoteImuRecording::tailDrained());
  // No storage calls participate in this deadline. A repeated STOP cannot
  // restart the five-second normal tail interval.
  clockMs=stoppedAt+4999;
  RemoteImuRecording::stop();RemoteImuRecording::service();
  assert(!RemoteImuRecording::tailDrained());
  clockMs=stoppedAt+5000;RemoteImuRecording::service();
  assert(RemoteImuRecording::tailDrained());
  retirePhysicalMaster=false;
  recordingSteps(3000);
  // Node RELEASE can win the race against physical DMA retirement. A rejected
  // premature exit must not destroy the confirmed measurement context.
  assert(!acquisitions[0].recording);
  assert(AcquisitionControl::active());
  assert(CanMasterManager::measurementReady());
  assert(master.acquisition_retirement_pending);
  retirePhysicalMaster=true;
  recordingSteps(3000);
  assert(!master.acquisition_retirement_pending);
  assert(!acquisitions[0].recording);
  if(AcquisitionControl::active()) {
    AcquisitionControl::Outcome o;AcquisitionControl::outcome(0,o);
    std::fprintf(stderr,"exit pending: result=%u reason=%u action=%u localFence=%d masterPhase=%u masterReason=%u retired=%d fenced=%u quiescent=%d modefenced=%d\n",unsigned(o.result),o.reason,unsigned(o.action),o.localFenceComplete,master.measurement.mode.phase,master.measurement.mode.reason,master.acquisition_retirement_pending,master.acquisition_fenced,master.measurement.quiescent,master.measurement.fenced);
  }
  assert(!AcquisitionControl::active());
  assert(RemoteImuRecording::stopped());
  assert(!RemoteImuRecording::failed());
  RemoteImuRecording::release();
  assert(!RemoteImuRecording::configured());
  CanMasterManager::endRecordingHandoff();
  // A configured but unavailable remote sensor must not silently become ready.
  reset();spiAvailable=false;
  assert(RemoteImuRecording::configure(config));
  assert(RemoteImuRecording::failed());
  assert(!RemoteImuRecording::configured());
  assert(RemoteImuRecording::prepared()); // Local start gate remains usable.
  RemoteImuRecording::start();assert(RemoteImuRecording::recording());
  assert(saved.type==SensorType::LSM6DSO32XImu && !saved.mutedDefault);
  RemoteImuRecording::release();
  puts("production remote coordinator prepare/snapshot/START/STOP/tail/fence/release/exit passed");
}
