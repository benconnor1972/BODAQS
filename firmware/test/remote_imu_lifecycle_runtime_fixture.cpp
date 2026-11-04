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

int main(int argc,char** argv) {
  saved.type=SensorType::LSM6DSO32XImu;std::strcpy(saved.name,"remote_imu");
  assert(savedParams.set("provider","can:0"));
  assert(savedParams.set("endpoint","imu"));
  assert(savedParams.set("profile","imu6_3333_32g_2000dps_v1"));
  saved.params.bind(&savedParams);
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
    records[n].node_address=n;records[n].flags=n==0?1:0;records[n].boot_id=f.view.boot_id;
    records[n].endpoint_mask=1;records[n].hardware_uid=123+n;
  }
  bodaqs_master_service_set_inventory(&master,2,records,4);
  assert(CanMasterManager::probeNow());
  advance(12000);
  assert(CanMasterManager::configurationReconciled(0));
  // Handoff must drain the observer's page/release chain. Abandoning its
  // pinned effective snapshot makes the next acquisition snapshot reject BUSY.
  CanMasterManager::beginRecordingHandoff();advance(4000);
  assert(CanMasterManager::recordingHandoffReady());
  assert(RemoteImuRecording::configure(config));
  assert(RemoteImuRecording::configured());
  assert(!RemoteImuRecording::prepared());
  recordingSteps(3000);
  if(RemoteImuRecording::failed()) {
    AcquisitionControl::Outcome o;AcquisitionControl::outcome(0,o);
    std::fprintf(stderr,"prepare failed: configured=%d prepared=%d result=%u reason=%u action=%u phase=%u lease=%d\n",RemoteImuRecording::configured(),RemoteImuRecording::prepared(),unsigned(o.result),o.reason,unsigned(o.action),acquisitions[0].phase,acquisitions[0].lease_valid);
  }
  assert(RemoteImuRecording::prepared());
  assert(!RemoteImuRecording::failed());
  assert(acquisitions[0].phase==2 && acquisitions[0].lease_valid);
  assert(!RemoteImuRecording::recording()); // Preparation cannot start samples.
  BdqV2StreamDescriptor descriptors[2];
  assert(RemoteImuRecording::describe(descriptors,2,2)==2);
  assert(!strcmp(descriptors[0].payloadSchema,"bodaqs.can_imu6.v1"));
  assert(!strcmp(descriptors[1].payloadSchema,"bodaqs.can_timing_evidence.v1"));
  RemoteImuRecording::start();recordingSteps(500);
  assert(RemoteImuRecording::recording());
  assert(acquisitions[0].phase==3 && acquisitions[0].lease_valid);
  if(argc>1) {
    recording=true;
    if(!std::strcmp(argv[1],"node-reboot")) {
      ++node.view.boot_id;node.view.active_session=0;node.view.flags=0;node.authority={};
      bodaqs_control_acquisition_init(&acquisitions[0],&node.authority,&node.view,node.apply.effective,backendEvent,nullptr);
      master.discovery[0].boot_id=node.view.boot_id;
    } else if(!std::strcmp(argv[1],"master-reboot")) {
      const auto identity=master.identity;
      bodaqs_master_service_init(&master,&identity);bodaqs_control_exchange_init(&master.control,100);
      inventory();allowMalformedMeasurement=true;
    } else if(!std::strcmp(argv[1],"bus-off")) {
      bodaqs_control_acquisition_exclude(&acquisitions[0],27);
    } else {
      assert(!std::strcmp(argv[1],"lease-expiry"));
      clockMs=acquisitions[0].lease_deadline;
    }
    recordingSteps(1800);
    AcquisitionControl::Outcome result;AcquisitionControl::outcome(0,result);
    assert(result.excluded && !result.leaseAcknowledged && RemoteImuRecording::failed());
    assert(recording); // Remote fault cannot stop healthy local sampling.
    AcquisitionControl::Request rejoin;rejoin.node=0;rejoin.action=AcquisitionControl::Action::Prepare;rejoin.recording=1;
    assert(!AcquisitionControl::enqueue(rejoin));
    recordingSteps(6000);assert(RemoteImuRecording::tailDrained());
    recording=false;
    for(unsigned i=0;i<20000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
    assert(!acquisitions[0].recording && acquisitions[0].fenced);
    puts("production remote fault exclusion and quiescent explicit cleanup passed");return 0;
  }
  // Actual management ERROR diagnostics cross the pipelined SPI manager and
  // control owner into a companion without fabricating a CAN reception.
  bodaqs_master_service_loss_counts(&master,0,5,1,0,6,7,0,false,1234,9);
  recordingSteps(500);
  assert(!RemoteImuRecording::failed());
  unsigned observedLoss=0,lossReports=0;uint8_t lossRow[224];
  auto& lossSource=descriptors[1].source;
  while(lossSource.pendingRecords(lossSource.context)) {
    assert(lossSource.popRecord(lossSource.context,lossRow,sizeof lossRow));
    if(lossRow[168]==5) {
      observedLoss+=BdqV2Format::getU32(lossRow+148);++lossReports;
      assert(lossRow[184]==0 && BdqV2Format::getU32(lossRow+76)==0);
    }
  }
  lossSource.chunkWritten(lossSource.context);
  assert(observedLoss==7 && lossReports==1); // repeated cumulative errors deduplicate
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
  // Restart the logger while a previous measurement context survives. A node
  // reboot leaves no membership, but old master retention still needs an
  // explicit current-boot hardware fence before context retirement.
  assert(CanMasterManager::enterMeasurementMode(999,1000));
  master.acquisition_record[0]=999;master.acquisition_boot[0]=node.view.boot_id;
  master.acquisition_fenced&=~1u;
  master.measurement.quiescent=false;master.measurement.fenced=false;
  ++node.view.boot_id;node.view.active_session=0;node.view.flags=0;node.authority={};
  bodaqs_control_acquisition_init(&acquisitions[0],&node.authority,&node.view,node.apply.effective,backendEvent,nullptr);
  master.discovery[0].boot_id=node.view.boot_id;
  const uint64_t abandonedSession=master.measurement.mode.session;
  dropBindReplyUntil=clockMs+5000; // Lost success must retry the identical BIND, even after local timeout.
  CanMasterManager::begin(profile,config);
  assert(CanMasterManager::diagnostics().measurement.phase==2);
  assert(!CanMasterManager::measurementReady()); // Observational restart discovery never rejoins.
  for(unsigned i=0;i<20000 && master.measurement.mode.phase;++i) {
    advance(1);bodaqs_control_acquisition_tick(&acquisitions[0],clockMs);
    if(master.acquisition_retirement_pending) bodaqs_master_service_measurement_fence(&master,true,true);
  }
  assert(master.measurement.mode.phase==0);
  assert(!acquisitions[0].recording && acquisitions[0].fenced);
  BodaqsControlRecord replay={},rejected={};
  replay.opcode=0x25;replay.endpoint=255;replay.node_boot_id=node.view.boot_id-1;
  replay.session=abandonedSession;replay.operation=2;replay.data_length=24;replay.data[0]=1;
  assert(dispatchControl(0,replay,rejected) && rejected.opcode==127 && rejected.data[1]==4);
  replay.node_boot_id=node.view.boot_id;
  assert(dispatchControl(0,replay,rejected) && rejected.opcode==127 && rejected.data[1]==5);
  advance(12000);
  CanMasterManager::beginRecordingHandoff();advance(4000);
  assert(RemoteImuRecording::configure(config));recordingSteps(3000);
  assert(!RemoteImuRecording::failed());
  RemoteImuRecording::start();recordingSteps(500);recording=true;
  loseMeasurementReplies=true;recordingSteps(330);loseMeasurementReplies=false;
  AcquisitionControl::Outcome excluded;AcquisitionControl::outcome(0,excluded);
  assert(excluded.excluded && !excluded.leaseAcknowledged);
  assert(RemoteImuRecording::failed() && recording); // Healthy locals remain running.
  const uint32_t oldRenewal=acquisitions[0].renewal_sequence;
  recordingSteps(6000);
  assert(acquisitions[0].renewal_sequence==oldRenewal);
  assert(RemoteImuRecording::tailDrained());
  assert(!RemoteImuRecording::stopped()); // Tail cutoff is distinct from administrative cleanup.
  recording=false;
  for(unsigned i=0;i<20000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
  assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
  assert(!acquisitions[0].recording && acquisitions[0].fenced);
  RemoteImuRecording::release();CanMasterManager::endRecordingHandoff();
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
