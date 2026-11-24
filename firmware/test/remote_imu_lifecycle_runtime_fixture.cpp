#include "RemoteImuRecording.h"
static bool retirePhysicalMaster=true;
static std::vector<BdqV2StreamSource> simulatedStorage;

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
    // A healthy independently scheduled storage owner drains old companions.
    // Retain recent rows for the exact diagnostic assertions below.
    for(auto& source:simulatedStorage) if(source.pendingRecords(source.context)>64) {
      uint8_t row[224];
      while(source.pendingRecords(source.context)>32) assert(source.popRecord(source.context,row,sizeof row));
      source.chunkWritten(source.context);
    }
    const bool wasFailed=RemoteImuRecording::failed();
    RemoteImuRecording::service();
    if(!wasFailed && RemoteImuRecording::failed()) {
      AcquisitionControl::Outcome o;AcquisitionControl::outcome(0,o);
      std::fprintf(stderr,"first failure at%lu: result=%u reason=%u action=%u nodePhase=%u endpointEpoch=%llu\n",(unsigned long)clockMs,unsigned(o.result),o.reason,unsigned(o.action),acquisitions[0].phase,(unsigned long long)node.view.endpoint_epoch[0]);
    }
  }
}

int main(int argc,char** argv) {
  ImuAdmission::Profile costs;costs.maximumSourceSamplesPerSecond=3333;costs.qualified=true;costs.adcAttemptsPerConversion=1;costs.canBurstFrames=20;costs.spiBurstSlots=32;costs.sampleSlotUs=64;costs.auxiliarySlotUs=64;costs.sampleDrainSlotsPerSecond=14000;
  if(!ImuAdmission::singleNodeSmokeBuild()) assert(RemoteImuRecording::setAdmissionProfile(costs));
  saved.type=SensorType::LSM6DSO32XImu;std::strcpy(saved.name,"remote_imu");
  assert(savedParams.set("provider","can:0"));
  assert(savedParams.set("endpoint","imu"));
  assert(savedParams.set("profile","imu6_3333_32g_2000dps_v1"));
  saved.params.bind(&savedParams);
  const bool failingReadiness=argc>1 && !std::strcmp(argv[1],"readiness-failing");
  const bool readinessCase=failingReadiness || (argc>1 && !std::strcmp(argv[1],"readiness"));
  fixtureSensorCount=argc>1 && (readinessCase || !std::strcmp(argv[1],"four") || !std::strcmp(argv[1],"four-bus-off"))?4:1;
  const bool multiCase=argc>1 && !std::strncmp(argv[1],"multi-",6);
  if(multiCase) {assert(ImuAdmission::multiNodeBenchBuild());fixtureSensorCount=unsigned(argv[1][6]-'0');}
  const bool mixedRejected=argc>1 && !std::strncmp(argv[1],"mixed-reject-",13);
  const bool scopeRejected=mixedRejected || (argc>1 && (!std::strcmp(argv[1],"scope-two") || !std::strcmp(argv[1],"scope-other") || !std::strcmp(argv[1],"scope-adc")));
  if(scopeRejected && !mixedRejected && std::strcmp(argv[1],"scope-adc")) fixtureSensorCount=2;
  for(unsigned n=1;n<fixtureSensorCount;++n) {
    extra[n-1]=saved;extraParams[n-1]=savedParams;
    char provider[8];std::snprintf(provider,sizeof provider,"can:%u",n);
    assert(extraParams[n-1].set("provider",provider));extra[n-1].params.bind(&extraParams[n-1]);
  }
  reset();lifecycleEnabled=true;fastMeasurementClock=true;
  const bool wideMasterBoot=argc>1 && !std::strcmp(argv[1],"wide-master-boot");
  if(wideMasterBoot) bodaqs_control_exchange_init(&master.control,UINT64_C(0x5f1afad1c7ff51d2));
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
  const uint32_t preparationBegan=clockMs;
  loseIdleNodeZero=failingReadiness;
  for(unsigned wait=0;wait<300000;++wait) {
    advance(1);bool ready=true;
    for(unsigned n=failingReadiness?1:0;n<fixtureSensorCount;++n) ready=ready && CanMasterManager::configurationReconciled(n);
    if(ready) break;
  }
  if(readinessCase) {
    std::printf("Modeled preparation (%s): %lu ms\n",failingReadiness?"one nonresponding peer":"four healthy peers",static_cast<unsigned long>(clockMs-preparationBegan));
    // Failure progress includes unchanged protocol timeouts/retry semantics;
    // this is a finite-progress regression guard, not a product latency SLA.
    assert(clockMs-preparationBegan<(failingReadiness?60000u:10000u));
    if(failingReadiness) {
      assert(!CanMasterManager::configurationReconciled(0));
      for(unsigned n=1;n<4;++n) assert(CanMasterManager::configurationReconciled(n));
      return 0;
    }
    for(unsigned n=0;n<4;++n) assert(CanMasterManager::configurationReconciled(n));
    // Steady state uses fresh state checks without downloading unchanged pages.
    advance(1500);
    for(unsigned n=0;n<4;++n) assert(CanMasterManager::configurationReconciled(n));
    assert(extraParams[0].set("profile","imu6_1667_32g_2000dps_v1"));
    CanMasterManager::scheduleConfigurationReconciliation();
    assert(!CanMasterManager::configurationReconciled(1));
    const uint32_t changedAt=clockMs;
    for(unsigned wait=0;wait<10000 && !CanMasterManager::configurationReconciled(1);++wait) advance(1);
    assert(CanMasterManager::configurationReconciled(1));
    assert(peerFixture(1).regs.bytes[0][16]==0x84);
    std::printf("Changed profile modeled preparation: %lu ms\n",static_cast<unsigned long>(clockMs-changedAt));
    // A late/absent configured node does not monopolize ready peers.
    records[0].flags=0;
    bodaqs_master_service_set_inventory(&master,3,records,4);
    assert(CanMasterManager::probeNow());
    advance(1500);
    assert(!CanMasterManager::configurationReconciled(0));
    for(unsigned n=1;n<4;++n) assert(CanMasterManager::configurationReconciled(n));
    records[0].flags=1;
    bodaqs_master_service_set_inventory(&master,4,records,4);
    for(unsigned wait=0;wait<10000 && !CanMasterManager::configurationReconciled(0);++wait) advance(1);
    assert(CanMasterManager::configurationReconciled(0));
    return 0;
  }
  for(unsigned n=0;n<fixtureSensorCount;++n) if(!CanMasterManager::configurationReconciled(n)) {
    const auto& d=CanMasterManager::diagnostics();std::fprintf(stderr,"unreconciled %u desired=%d generation=%llu current=%d session=%llu active=%llu phase=%u\n",n,d.desiredEnabled[n],(unsigned long long)d.desiredGeneration[n],d.control.nodes[n].endpoints[0].current,(unsigned long long)d.authority.session,(unsigned long long)peerFixture(n).view.active_session,peerFixture(n).apply.phase);
    assert(false);
  }
  // Handoff must drain the observer's page/release chain. Abandoning its
  // pinned effective snapshot makes the next acquisition snapshot reject BUSY.
  CanMasterManager::beginRecordingHandoff();advance(4000);
  assert(CanMasterManager::recordingHandoffReady());
  const unsigned remoteNodes=fixtureSensorCount;
  config.sampleRateHz=500;
  if(ImuAdmission::singleNodeAdcSmokeBuild() && !(multiCase && (!std::strcmp(argv[1]+8,"none") || !std::strcmp(argv[1]+8,"fault")))) {
    config.sampleRateHz=500;
    profile.external_adc_count=2;profile.analog.count=8;
    for(unsigned a=0;a<2;++a) {
      profile.external_adcs[a].spi_hz=1000000;
      auto& input=profile.analog.inputs[a*4];
      input.source=board::AnalogSourceType::ExternalAdc;
      input.external_adc_index=a;input.external_channel=0;
      const unsigned index=fixtureSensorCount++-1;
      extra[index]={};extra[index].type=SensorType::AnalogPot;
      assert(extraParams[index].set("ain",a?"4":"0"));
      extra[index].params.bind(&extraParams[index]);
    }
    fixtureAdcChannels=1;fixtureAdcSps=1000;
    if(argc>1 && !std::strncmp(argv[1],"channel-rate-",13)) {
      assert(ImuAdmission::channelRateBenchBuild());
      fixtureConcentrated=true;
      profile.analog.inputs[1]=profile.analog.inputs[0];
      profile.analog.inputs[1].external_channel=1;
      assert(extraParams[1].set("ain","1"));
      config.sampleRateHz=uint16_t(std::atoi(argv[1]+13));
    }
    if(argc>1 && (!std::strncmp(argv[1],"scaling-",8) || !std::strncmp(argv[1],"mixed-reject-scaling-",21))) {
      assert(ImuAdmission::scalingBenchBuild());
      const char* ains[]={"0","1","4","5"};
      fixtureSensorCount=5;fixtureAdcChannels=2;
      config.sampleRateHz=!std::strcmp(argv[1],"scaling-500")?500:200;
      fixtureAdcSps=config.sampleRateHz==200?600:2000;
      for(unsigned i=0;i<4;++i) {
        extra[i]={};extra[i].type=SensorType::AnalogPot;
        assert(extraParams[i].set("ain",ains[i]));extra[i].params.bind(&extraParams[i]);
        const unsigned ain=unsigned(std::atoi(ains[i]));
        auto& input=profile.analog.inputs[ain];input.source=board::AnalogSourceType::ExternalAdc;
        input.external_adc_index=ain/4;input.external_channel=ain%4;
      }
      if(!std::strcmp(argv[1],"mixed-reject-scaling-rate")) config.sampleRateHz=700;
      if(!std::strcmp(argv[1],"mixed-reject-scaling-duplicate")) assert(extraParams[3].set("ain","4"));
      if(!std::strcmp(argv[1],"mixed-reject-scaling-map")) profile.analog.inputs[5].external_channel=0;
      if(!std::strcmp(argv[1],"mixed-reject-scaling-raw")) assert(extraParams[3].set("include_raw","true"));
    }
    if(multiCase) {
      const char* ains[]={"0","1","4","5"};
      fixtureSensorCount=remoteNodes+4;fixtureAdcChannels=2;
      config.sampleRateHz=uint16_t(std::atoi(argv[1]+8));fixtureAdcSps=config.sampleRateHz==200?600:2000;
      for(unsigned i=0;i<4;++i) {
        const unsigned index=remoteNodes-1+i;extra[index]={};extra[index].type=SensorType::AnalogPot;
        assert(extraParams[index].set("ain",ains[i]));extra[index].params.bind(&extraParams[index]);
        const unsigned ain=unsigned(std::atoi(ains[i]));auto& input=profile.analog.inputs[ain];
        input.source=board::AnalogSourceType::ExternalAdc;input.external_adc_index=ain/4;input.external_channel=ain%4;
      }
    }
    if(argc>1 && !std::strcmp(argv[1],"mixed-control")) {
      saved.mutedDefault=true;
      assert(RemoteImuRecording::configure(config));
      assert(!RemoteImuRecording::configured() && !RemoteImuRecording::failed());
      assert(!AcquisitionControl::active() && DynamicSpscQueueDetail::liveAllocations==0);
      puts("same-image ADC-only control creates no remote authorization: PASS");return 0;
    }
    if(mixedRejected) {
      if(!std::strcmp(argv[1],"mixed-reject-ain")) assert(extraParams[0].set("ain","1"));
      if(!std::strcmp(argv[1],"mixed-reject-rate")) config.sampleRateHz=200;
      if(!std::strcmp(argv[1],"mixed-reject-channels")) fixtureAdcChannels=2;
      if(!std::strcmp(argv[1],"mixed-reject-duplicate")) assert(extraParams[1].set("ain","0"));
      if(!std::strcmp(argv[1],"mixed-reject-transform")) assert(extraParams[0].set("output_mode","2"));
    }
  }
  if(scopeRejected) {
    assert(ImuAdmission::singleNodeSmokeBuild());
    if(!std::strcmp(argv[1],"scope-other")) extra[0].type=SensorType::BMI270ImuI2C;
    if(!std::strcmp(argv[1],"scope-adc")) {
      profile.external_adc_count=1;profile.external_adcs[0].spi_hz=1000000;
      fixtureAdcChannels=1;
    }
    assert(RemoteImuRecording::configure(config));
    assert(!RemoteImuRecording::configured());
    assert(RemoteImuRecording::admission().reason==(ImuAdmission::singleNodeAdcSmokeBuild()
        ? (ImuAdmission::multiNodeBenchBuild()?ImuAdmission::Reason::MultiNodeBenchScope:ImuAdmission::Reason::MixedSmokeScope):ImuAdmission::Reason::SmokeScope));
    assert(RemoteImuRecording::admission().benchOnly && !RemoteImuRecording::admission().qualified);
    assert(!AcquisitionControl::active() && DynamicSpscQueueDetail::liveAllocations==0);
    puts("restricted workload rejected before authorization: PASS");return 0;
  }
  if(argc>1 && !std::strcmp(argv[1],"legacy-rx-overrun")) {
    alternateRxLoss=true;physicalSlots=1; // First command is lost, fetches continue.
    bool observed=false;
    for(unsigned attempt=0;attempt<8 && !observed;++attempt)
      observed=CanMasterManager::inspectMeasurementMode();
    assert(observed && CanMasterManager::diagnostics().measurement.phase==0);
    puts("legacy polling escapes alternating physical RX loss: PASS");return 0;
  }
  // Fail a real queue/model allocation, before any control owner is entered.
  DynamicSpscQueueDetail::allocationsBeforeFailure=remoteNodes==4?7:2;
  assert(RemoteImuRecording::configure(config));
  assert(!RemoteImuRecording::configured() && RemoteImuRecording::failed());
  assert(RemoteImuRecording::admission().reason==ImuAdmission::Reason::Allocation);
  assert(!AcquisitionControl::active() && DynamicSpscQueueDetail::liveAllocations==0);
  DynamicSpscQueueDetail::allocationsBeforeFailure=-1;
  assert(RemoteImuRecording::configure(config));
  assert(RemoteImuRecording::configured());
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  if(argc>1 && !std::strcmp(argv[1],"flow-cancel-scope")) {
    // Simulate a prior completed observation, then cancel this new allocation
    // before resourcesReady begins a new acquisition-owned diagnostic scope.
    ImuFlowDiagnostics::reset(9999,clockMs);ImuFlowDiagnostics::finish(clockMs,micros());
    assert(!AcquisitionControl::active());
    RemoteImuRecording::stop();assert(RemoteImuRecording::stopped());
    uint32_t transfer=0,decode=0;
    ImuFlowDiagnostics::NodeStats stats;assert(!RemoteImuRecording::finalNodeDiagnostics(0,stats));
    assert(!RemoteImuRecording::finalMeasurementFailures(transfer,decode)); // Stale completed context is not this allocation.
    assert(!RemoteImuRecording::finalRejectedMeasurementReplies());
    flowLogCalls=0;RemoteImuRecording::release();
    assert(flowLogCalls==0); // Never attribute prior-context FLOW to this cancellation.
    assert(ImuFlowDiagnostics::finished.context==9999);
    puts("allocated cancellation excludes prior-context FLOW snapshot: PASS");return 0;
  }
#endif
  if(ImuAdmission::singleNodeSmokeBuild()) {
    assert(RemoteImuRecording::admission().benchOnly);
    assert(!RemoteImuRecording::admission().qualified);
  }
  if(argc>1 && !std::strcmp(argv[1],"shared-integrity")) {
    assert(!RemoteImuRecording::sharedIntegrityFault());
    const uint8_t malformed[12]={};
    assert(RemoteImuRecording::consume(5,255,1,malformed,sizeof malformed));
    assert(RemoteImuRecording::sharedIntegrityFault());
    RemoteImuRecording::stop();RemoteImuRecording::release();
    puts("malformed shared clock evidence requests session STOP: PASS");return 0;
  }
  assert(!RemoteImuRecording::prepared());
  recordingSteps(100);
  for(unsigned n=0;n<remoteNodes;++n) assert(!acquisitions[n].recording && !acquisitions[n].phase);
  assert(!AcquisitionControl::active()); // no PREPARE before storage allocation
  assert(RemoteImuRecording::resourcesReady());
  if(argc>1 && !std::strcmp(argv[1],"start-clock-boundary")) {
    recordingSteps(8000);
    assert(!RemoteImuRecording::failed() && RemoteImuRecording::prepared());
    RemoteImuRecording::start();RemoteImuRecording::service();
    // The owner samples now, then the clock advances while START is queued.
    millisReadsToAdvance=2;AcquisitionControl::service();
    AcquisitionControl::Outcome outcome;AcquisitionControl::outcome(0,outcome);
    assert(outcome.action==AcquisitionControl::Action::Start);
    assert(outcome.result==AcquisitionControl::Result::Pending);
    recordingSteps(1000);
    assert(!RemoteImuRecording::failed() && RemoteImuRecording::recording());
    RemoteImuRecording::stop();
    for(unsigned i=0;i<30000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
    puts("START queued across a millisecond boundary does not time out: PASS");return 0;
  }
  if(argc>1 && !std::strcmp(argv[1],"lost-control-ack")) {
    dropOrdinaryControlAck=true;
    recordingSteps(8000);
    assert(droppedControlAcks==1);
    if(BODAQS_MEASUREMENT_VERSION==1)
      assert(CanMasterManager::diagnostics().measurementTransferErrorMask&(1U<<8));
    assert(!RemoteImuRecording::failed() && RemoteImuRecording::prepared());
    RemoteImuRecording::stop();
    for(unsigned i=0;i<30000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
    puts("lost ordinary control RAM ACK: PREPARE and cleanup passed");return 0;
  }
  if(argc>1 && !std::strcmp(argv[1],"delayed-cleanup-status")) {
    recordingSteps(8000);
    assert(!RemoteImuRecording::failed() && RemoteImuRecording::prepared());
    loseMeasurementReplies=true;recordingSteps(330);loseMeasurementReplies=false;
    assert(RemoteImuRecording::failed());
    RemoteImuRecording::stop();
    bool observedReleasedFence=false;
    for(unsigned i=0;i<30000 && !RemoteImuRecording::stopped();++i) {
      const auto& slot=master.control.slots[0];
      if(slot.request.opcode==0x29 && slot.state==2 && master.measurement.quiescent && master.measurement.fenced) {
        observedReleasedFence=true;delayStatusResponses=true;
      }
      recordingSteps(1);
    }
    assert(observedReleasedFence && RemoteImuRecording::stopped() && !AcquisitionControl::active());
    assert(master.measurement.mode.phase==0);
    simulatedStorage.clear();RemoteImuRecording::release();CanMasterManager::endRecordingHandoff();
    puts("completed RELEASE and physical fence exit despite delayed mode status: PASS");return 0;
  }
  if(argc>1 && (!std::strcmp(argv[1],"rx-overrun") || !std::strcmp(argv[1],"rx-overrun-odd"))) {
    // The second phase targets measurement polling, after legacy mode entry.
    // Entry loss/failure has its own cleanup regressions below.
    if(!std::strcmp(argv[1],"rx-overrun-odd")) {
      AcquisitionControl::service();assert(CanMasterManager::measurementReady());
    }
    alternateRxLoss=true;physicalSlots=!std::strcmp(argv[1],"rx-overrun-odd")?1:0;
    recordingSteps(8000);
    assert(!RemoteImuRecording::failed() && RemoteImuRecording::prepared());
    RemoteImuRecording::stop();
    for(unsigned i=0;i<30000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
    simulatedStorage.clear();RemoteImuRecording::release();CanMasterManager::endRecordingHandoff();
    puts("alternating physical RX loss: PREPARE and verified cleanup passed");return 0;
  }
  const bool entryOffline=argc>1 && !std::strcmp(argv[1],"entry-offline");
  const bool entryPrecheck=argc>1 && !std::strcmp(argv[1],"entry-precheck");
  if(entryOffline || entryPrecheck || (argc>1 && !std::strcmp(argv[1],"entry-timeout"))) {
    // The master may have accepted the mode change while every confirming
    // reply was lost. No PREPARE has run, and no remote lease exists.
    if(entryPrecheck) {
      auto& diagnostic=const_cast<CanMasterManager::Diagnostics&>(CanMasterManager::diagnostics());
      diagnostic.measurementTimingContext=9999;diagnostic.measurementTiming.transferFailedSlots=7;
      diagnostic.measurementTiming.decodeFailedSlots=11;diagnostic.measurementUnavailable=true;
    }
    loseMeasurementReplies=!entryOffline && !entryPrecheck;spiAvailable=!entryOffline;
    recordingSteps(1300);
    loseMeasurementReplies=false;spiAvailable=true;
    assert(RemoteImuRecording::failed());
    assert(CanMasterManager::diagnostics().measurementUnavailable);
    assert(!acquisitions[0].recording && !acquisitions[0].lease_valid);
    RemoteImuRecording::stop();
    for(unsigned i=0;i<30000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
    assert(!master.measurement.mode.phase);
    if(entryPrecheck) {
      uint32_t transfer=99,decode=88;
      assert(!RemoteImuRecording::finalMeasurementFailures(transfer,decode));
      assert(!RemoteImuRecording::finalRejectedMeasurementReplies());
      assert(transfer==99 && decode==88); // Prior scope is unavailable, not current 7/11.
      RemoteImuRecording::Failure firstFailure;
      assert(RemoteImuRecording::failure(0,firstFailure) && !firstFailure.timingAvailable);
      assert(!firstFailure.timing.transferFailedSlots && !firstFailure.timing.decodeFailedSlots);
      puts("entry precheck failure cannot relabel prior measurement counters: PASS");
    }
    simulatedStorage.clear();RemoteImuRecording::release();CanMasterManager::endRecordingHandoff();
    puts("failed measurement entry reaches verified cleanup without a remote lease: PASS");
    return 0;
  }
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
  assert(RemoteImuRecording::describe(descriptors,8,2)==2*remoteNodes);
  for(unsigned n=0;n<remoteNodes;++n) simulatedStorage.push_back(descriptors[n*2+1].source);
  assert(!strcmp(descriptors[0].payloadSchema,ImuAdmission::singleNodeSmokeBuild()?"bodaqs.can_imu_packets.v1":"bodaqs.can_imu6.v1"));
  assert(!strcmp(descriptors[1].payloadSchema,"bodaqs.can_timing_evidence.v1"));
  RemoteImuRecording::start();recordingSteps(2000);
  assert(RemoteImuRecording::recording());
  assert(!RemoteImuRecording::failed());
  if(wideMasterBoot) {
    assert(!RemoteImuRecording::sharedIntegrityFault());
    // A change confined to the upper half must still invalidate shared scope.
    const auto identity=master.identity;
    bodaqs_master_service_init(&master,&identity);
    bodaqs_control_exchange_init(&master.control,UINT64_C(0x5f1afad2c7ff51d2));
    inventory();allowMalformedMeasurement=true;
    recordingSteps(1800);
    assert(RemoteImuRecording::sharedIntegrityFault());
    puts("full-width master boot identity remains valid; upper-half reboot detected: PASS");
    return 0;
  }
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
  assert(!RemoteImuRecording::finalRejectedMeasurementReplies()); // Owner is still live.
  uint8_t capturedWire[256];memcpy(capturedWire,preloaded,256);capturedWire[0]='X';
  memcpy(preloaded,capturedWire,256);
  for(unsigned i=0;i<10 && !ImuFlowDiagnostics::liveReplies.count;++i) recordingSteps(1);
  assert(ImuFlowDiagnostics::liveReplies.count==1);
#endif
  if(argc>1 && (!std::strcmp(argv[1],"lost-exit-request") || !std::strcmp(argv[1],"lost-exit-stage") || !std::strcmp(argv[1],"lost-exit-confirm") || !std::strcmp(argv[1],"expired-exit-stage"))) {
    loseExitStageRequest=!std::strcmp(argv[1],"lost-exit-request");
    const bool expired=!std::strcmp(argv[1],"expired-exit-stage");
    loseExitStageReply=expired || !std::strcmp(argv[1],"lost-exit-stage");
    loseExitConfirmRequest=expired;
    loseExitConfirmReply=!std::strcmp(argv[1],"lost-exit-confirm");
    bool uncertain=false,failedReservation=false;uint32_t uncertainAt=0,firstStage=0;RemoteImuRecording::stop();
    for(unsigned i=0;i<30000 && !RemoteImuRecording::stopped();++i) {
      recordingSteps(1);
      const auto& mode=CanMasterManager::diagnostics();
      if(mode.measurementUnavailable && mode.measurement.phase==3) {
        uncertain=true;if(!uncertainAt) {uncertainAt=clockMs;firstStage=master.measurement.sequence;}
      }
      failedReservation |= master.measurement.mode.phase==4;
      if(uncertain && (!expired || uint32_t(clockMs-uncertainAt)>=1300))
        loseExitStageRequest=loseExitStageReply=loseExitConfirmReply=loseExitConfirmRequest=false;
    }
    if(expired) assert(failedReservation || expiredExitReservations);
    assert(uncertain && (lostExitStages || lostExitReplies || lostExitConfirms));
    if(!RemoteImuRecording::stopped()) {
      AcquisitionControl::Outcome o;AcquisitionControl::outcome(0,o);
      std::fprintf(stderr,"exit stall: local_phase=%u unavailable=%d master_phase=%u release_result=%u local_fence=%d\n",
        CanMasterManager::diagnostics().measurement.phase,CanMasterManager::diagnostics().measurementUnavailable,
        master.measurement.mode.phase,unsigned(o.result),o.localFenceComplete);
    }
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
    assert(!master.measurement.mode.phase);
    if(!std::strcmp(argv[1],"lost-exit-stage") || !std::strcmp(argv[1],"lost-exit-confirm"))
      assert(master.measurement.sequence==firstStage);
    if(expired) assert(master.measurement.sequence>firstStage);
    assert(!acquisitions[0].lease_valid && !acquisitions[0].recording);
    const uint64_t oldContext=master.measurement.mode.context,oldRecording=master.measurement.mode.recording;
    simulatedStorage.clear();RemoteImuRecording::release();CanMasterManager::endRecordingHandoff();
    advance(12000);CanMasterManager::beginRecordingHandoff();advance(4000);
    assert(RemoteImuRecording::configure(config) && RemoteImuRecording::resourcesReady());
    recordingSteps(8000);assert(RemoteImuRecording::prepared() && !RemoteImuRecording::failed());
    RemoteImuRecording::start();recordingSteps(1000);
    assert(RemoteImuRecording::recording() && !RemoteImuRecording::failed());
    assert(master.measurement.mode.context!=oldContext && master.measurement.mode.recording!=oldRecording);
    RemoteImuRecording::stop();
    for(unsigned i=0;i<20000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
    puts("uncertain exit resumes after bounded loss and permits a fresh explicit recording: PASS");return 0;
  }
  if(argc>1 && (!std::strcmp(argv[1],"tail-pressure") || !std::strcmp(argv[1],"tail-pressure-deferred-status"))) {
    deferFenceStatus=!std::strcmp(argv[1],"tail-pressure-deferred-status");
    assert(ImuAdmission::singleNodeSmokeBuild() && BODAQS_MEASUREMENT_VERSION==2);
    uint8_t boundary[64]={};boundary[0]=1;boundary[1]=0x25;boundary[2]=1;boundary[6]=56;
    bodaqs_control_put_u32(boundary+8,node.view.boot_id);boundary[13]=1;boundary[14]=2;
    bodaqs_control_put_u32(boundary+16,1);bodaqs_control_put_u32(boundary+20,1);
    bodaqs_control_put_u32(boundary+24,1);boundary[54]=0x61;boundary[55]=1;
    assert(bodaqs_master_service_receive_can(&master,0,2,0x90,boundary,64,0,clockMs*1000,clockMs));
    recordingSteps(100);
    for(unsigned i=0;i<2065;++i) {
      uint8_t packet[64]={};packet[0]=uint8_t(i*5);packet[1]=uint8_t((i*5)>>8);packet[2]=1;packet[3]=5;
      for(unsigned j=4;j<64;j+=2) {packet[j]=0x34;packet[j+1]=0x12;}
      assert(bodaqs_master_service_receive_can(&master,0,1,0x100,packet,64,0,clockMs*1000,clockMs));
      recordingSteps(10);
    }
    auto& source=descriptors[0].source;
    assert(source.pendingRecords(source.context)==2048);
    recordingSteps(200);assert(source.pendingRecords(source.context)==2048);
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
    assert(ImuFlowDiagnostics::live.sampleQueuePeak==2048);
    assert(ImuFlowDiagnostics::live.consumerWait[0]>0);
    assert(ImuFlowDiagnostics::live.proofMatches[0]>0);
    // A real master loss report traverses the wire/management consumer while
    // the native packet queue stays full. Capture is diagnostic, not admission.
    const uint8_t lost[16]={0,0,1,1};
    bodaqs_master_service_loss(&master,0,6,1,lost,16,clockMs*1000,100000);
    recordingSteps(500);
    assert(ImuFlowDiagnostics::haveFirstLoss);
    assert(ImuFlowDiagnostics::firstLoss.sampleQueuePeak==2048);
    assert(ImuFlowDiagnostics::firstLoss.lossCounter==1);
#endif
    retirePhysicalMaster=false;RemoteImuRecording::stop();
    recordingSteps(8000);
    AcquisitionControl::Outcome pendingFence;AcquisitionControl::outcome(0,pendingFence);
    assert(!pendingFence.localFenceComplete && AcquisitionControl::active());
    assert(master.acquisition_retirement_pending && !master.measurement.fenced);
    AcquisitionControl::FenceDiagnostics diagnostic;
    AcquisitionControl::fenceDiagnostics(diagnostic);
    assert(diagnostic.confirmedMask==1 && !diagnostic.verified);
    assert(diagnostic.inspections && diagnostic.observations);
    assert(!(diagnostic.modeFlags&2));
    assert(diagnostic.data[0][0].object && !(diagnostic.data[0][0].flags&2));
    bodaqs_master_service_measurement_fence(&master,true,true);
    assert(master.measurement.fenced && master.measurement.mode.phase==2 && !master.master_evidence.complete);
    uint8_t timing[24]={};timing[0]=1;timing[2]=1;timing[4]=1;timing[8]=1;
    assert(!bodaqs_master_service_publish_evidence(&master,timing,sizeof timing));
    retirePhysicalMaster=true;
    for(unsigned i=0;i<30000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
    if(deferFenceStatus && !RemoteImuRecording::stopped()) {
      AcquisitionControl::fenceDiagnostics(diagnostic);
      std::fprintf(stderr,"fence stall: master_fenced=%d node_mask=%u deferred=%u ordinary_deliveries=%u attempts=%lu observations=%lu all=%d verified=%d\n",
        master.measurement.fenced,master.acquisition_fenced,deferredFenceStatuses,ordinaryFenceStatuses,
        (unsigned long)diagnostic.inspections,(unsigned long)diagnostic.observations,diagnostic.allFenced,diagnostic.verified);
    }
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
    assert(ImuFlowDiagnostics::haveFinished && !ImuFlowDiagnostics::active);
    assert(ImuFlowDiagnostics::finished.consumerWait[0]>0);
    assert(ImuFlowDiagnostics::firstLoss.lossCounter==1);
#endif
    if(deferFenceStatus) assert(deferredFenceStatuses && ordinaryFenceStatuses);
    uint8_t row[100];unsigned count=0;
    while(source.pendingRecords(source.context)) {
      assert(source.popRecord(source.context,row,sizeof row));
      assert(BdqV2Format::getU32(row)==count++);
      assert(BdqV2Format::getU16(row+40)==0x1234);
    }
    assert(count==2048);
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
    ImuFlowDiagnostics::NodeStats stats;assert(RemoteImuRecording::finalNodeDiagnostics(0,stats));
    assert(stats.packetsAccepted==2048 && stats.samplesAccepted==10240 && stats.consumerWait>0);
#endif
    AcquisitionControl::fenceDiagnostics(diagnostic);
    assert(diagnostic.verified && (diagnostic.modeFlags&2));
    assert(!diagnostic.data[0][0].object);
    assert(!RemoteImuRecording::failed());
    AcquisitionControl::Outcome outcome;AcquisitionControl::outcome(0,outcome);
    assert(outcome.tailDiscarded && outcome.sampleTailDiscarded);
    assert(RemoteImuRecording::discardedTailObjects()==outcome.tailObjectsDiscarded);
    puts("full compact queue retains partial progress and administratively fences unaccepted tail: PASS");return 0;
  }
  if(argc>1 && (!std::strcmp(argv[1],"lost-stop-result") || !std::strcmp(argv[1],"uncertain-stop"))) {
    const bool uncertain=!std::strcmp(argv[1],"uncertain-stop");
    loseStopResults=true;const uint32_t requested=clockMs;RemoteImuRecording::stop();
    recordingSteps(1600);
    assert(lostStopResults && !RemoteImuRecording::tailDrained());
    assert(!RemoteImuRecording::failed());
    AcquisitionControl::Request rejoin;rejoin.node=0;rejoin.action=AcquisitionControl::Action::Prepare;rejoin.recording=1;
    assert(!AcquisitionControl::enqueue(rejoin));
    if(!uncertain) loseStopResults=false;
    for(unsigned i=0;i<12000 && !RemoteImuRecording::tailDrained();++i) recordingSteps(1);
    RemoteImuRecording::Completion c;assert(RemoteImuRecording::completion(0,c));
    assert(c.stopConfirmed!=uncertain && c.uncertain==uncertain);
    if(uncertain) assert(uint32_t(c.drainClosedMs-requested)>=10000);
    else assert(uint32_t(c.drainClosedMs-c.stopConfirmedMs)>=5000 && !RemoteImuRecording::failed());
    loseStopResults=false;
    for(unsigned i=0;i<30000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
    puts("STOP retry and explicit confirmed/uncertain tail basis: PASS");return 0;
  }

  for(unsigned n=0;n<remoteNodes;++n) assert(acquisitions[n].phase==3 && acquisitions[n].lease_valid);

  assert(acquisitions[0].phase==3 && acquisitions[0].lease_valid);
  if(argc>1 && std::strcmp(argv[1],"four") && std::strncmp(argv[1],"channel-rate-",13) && std::strncmp(argv[1],"scaling-",8) && !multiCase) {
    recording=true;
    if(!std::strcmp(argv[1],"node-reboot")) {
      ++node.view.boot_id;node.view.active_session=0;node.view.flags=0;node.authority={};
      bodaqs_control_acquisition_init(&acquisitions[0],&node.authority,&node.view,node.apply.effective,backendEvent,nullptr);
      master.discovery[0].boot_id=node.view.boot_id;
    } else if(!std::strcmp(argv[1],"master-reboot")) {
      const auto identity=master.identity;
      bodaqs_master_service_init(&master,&identity);bodaqs_control_exchange_init(&master.control,100);
      inventory();allowMalformedMeasurement=true;
    } else if((!std::strcmp(argv[1],"bus-off") || !std::strcmp(argv[1],"four-bus-off"))) {
      bodaqs_control_acquisition_exclude(&acquisitions[0],27);
    } else {
      assert(!std::strcmp(argv[1],"lease-expiry"));
      clockMs=acquisitions[0].lease_deadline;
    }
    recordingSteps(1800);
    AcquisitionControl::Outcome result;AcquisitionControl::outcome(0,result);
    assert(result.excluded && !result.leaseAcknowledged && RemoteImuRecording::failed());
    assert(recording); // The control owner decides session STOP from the shared fault signal.
    if(!std::strcmp(argv[1],"master-reboot")) assert(RemoteImuRecording::sharedIntegrityFault());
    if(!std::strcmp(argv[1],"node-reboot") || !std::strcmp(argv[1],"four-bus-off"))
      assert(!RemoteImuRecording::sharedIntegrityFault()); // Healthy independent participants continue.
    AcquisitionControl::Request rejoin;rejoin.node=0;rejoin.action=AcquisitionControl::Action::Prepare;rejoin.recording=1;
    assert(!AcquisitionControl::enqueue(rejoin));
    recordingSteps(11000);
    if(remoteNodes==4) {
      assert(!RemoteImuRecording::tailDrained() && AcquisitionControl::active());
      for(unsigned n=1;n<4;++n) {
        AcquisitionControl::Outcome check;AcquisitionControl::outcome(n,check);
        if(acquisitions[n].phase!=3 || !acquisitions[n].lease_valid) std::fprintf(stderr,"healthy peer%u phase%u leased%d excluded%d result%u reason%u action%u\n",n,acquisitions[n].phase,acquisitions[n].lease_valid,check.excluded,unsigned(check.result),check.reason,unsigned(check.action));
        assert(acquisitions[n].phase==3 && acquisitions[n].lease_valid);
      }
      RemoteImuRecording::stop();recordingSteps(12000);
    }
    assert(RemoteImuRecording::tailDrained());
    recording=false;
    for(unsigned i=0;i<20000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
    assert(!acquisitions[0].recording && acquisitions[0].fenced);
    puts("production remote fault exclusion and quiescent explicit cleanup passed");return 0;
  }
#if defined(BODAQS_MULTI_NODE_BENCH) && BODAQS_MULTI_NODE_BENCH
  if(multiCase) {
    // Real per-node master ingress and packet consumer, distinct native values.
    for(unsigned n=0;n<remoteNodes;++n) {
      uint8_t boundary[64]={};boundary[0]=1;boundary[1]=0x25;boundary[2]=1;boundary[6]=56;
      bodaqs_control_put_u32(boundary+8,peerFixture(n).view.boot_id);boundary[13]=1;boundary[14]=2;
      bodaqs_control_put_u32(boundary+16,1);bodaqs_control_put_u32(boundary+20,1);
      bodaqs_control_put_u32(boundary+24,1);boundary[54]=0x61;boundary[55]=1;
      assert(bodaqs_master_service_receive_can(&master,n,2,uint16_t(0x90+n),boundary,64,0,clockMs*1000,clockMs));
      recordingSteps(50);
      uint8_t packet[64]={};packet[2]=1;packet[3]=5;packet[4]=uint8_t(10+n);
      assert(bodaqs_master_service_receive_can(&master,n,1,uint16_t(0x100+8*n),packet,64,0,clockMs*1000,clockMs));
    }
    recordingSteps(1000);
    for(unsigned n=0;n<remoteNodes;++n) {
      auto& source=descriptors[2*n].source;uint8_t row[100];
      assert(source.pendingRecords(source.context)==1);
      assert(source.popRecord(source.context,row,sizeof row));
      assert(BdqV2Format::getU16(row+40)==10+n);
      assert(ImuFlowDiagnostics::live.nodes[n].packetsAccepted==1);
      assert(ImuFlowDiagnostics::live.nodes[n].samplesAccepted==5);
      ImuFlowDiagnostics::NodeStats unavailable;
      assert(!RemoteImuRecording::finalNodeDiagnostics(n,unavailable));
    }
    if(remoteNodes>1) {
      // Model ownership interleavings at the existing coordinator seam. A live
      // callback blocks; closing its gate must still wait for that callback.
      auto& peer=RemoteImuRecording::peers[1];auto& gate=peer.dataGate;gate.store(2);
      uint8_t sync[28]={1,0,1};sync[4]=1;sync[8]=1;sync[12]=7;sync[20]=1;
      uint8_t bridge[32]={};bridge[0]=17;bridge[12]=2;
      assert(!RemoteImuRecording::consume(5,255,900001,sync,sizeof sync));
      assert(!RemoteImuRecording::consume(6,255,900002,bridge,sizeof bridge));
      const auto healthy=RemoteImuRecording::peers[0].stream.queueState().evidence;
      const auto later=RemoteImuRecording::peers[remoteNodes-1].stream.queueState().evidence;
      gate.store(3);
      uint8_t loss[8]={2,14,5,0,0,0,0,0};
      assert(!RemoteImuRecording::consume(7,1,0,loss,sizeof loss));
      for(unsigned retry=0;retry<3;++retry) {
        assert(!RemoteImuRecording::consume(5,255,900001,sync,sizeof sync));
        assert(!RemoteImuRecording::consume(6,255,900002,bridge,sizeof bridge));
        assert(RemoteImuRecording::peers[0].stream.queueState().evidence==healthy);
      }
      gate.store(1); // Callback has retired; optional fan-out may now retire.
      assert(RemoteImuRecording::consume(7,1,0,loss,sizeof loss));
      assert(peer.managementRetirements.load()==1);
      loss[1]=8;assert(!RemoteImuRecording::consume(7,1,0,loss,sizeof loss));loss[1]=14;
      peer.managementRetirements.store(UINT32_MAX);
      assert(RemoteImuRecording::consume(7,1,0,loss,sizeof loss));
      assert(peer.managementRetirements.load()==UINT32_MAX);

      assert(!RemoteImuRecording::consume(1,1,1,loss,sizeof loss));
      assert(RemoteImuRecording::consume(5,255,900001,sync,sizeof sync));
      assert(RemoteImuRecording::consume(6,255,900002,bridge,sizeof bridge));
      assert(RemoteImuRecording::peers[0].stream.queueState().evidence==healthy);
      assert(RemoteImuRecording::peers[remoteNodes-1].stream.queueState().evidence==later);
      assert(peer.sharedRetirements[0].load()==1 && peer.sharedRetirements[1].load()==1);
      assert(RemoteImuRecording::consume(5,255,900001,sync,sizeof sync));
      assert(peer.sharedRetirements[0].load()==1);
      // Every destination retired, and one counter at its numeric limit.
      peer.sharedRetirements[0].store(UINT32_MAX);
      for(unsigned n=0;n<remoteNodes;++n) RemoteImuRecording::peers[n].dataGate.store(1);
      assert(RemoteImuRecording::consume(5,255,900003,sync,sizeof sync));
      assert(RemoteImuRecording::consume(6,255,900004,bridge,sizeof bridge));
      assert(peer.sharedRetirements[0].load()==UINT32_MAX && peer.sharedRetirements[1].load()==2);
      // Restore only this synthetic interleaving fixture for its normal STOP.
      for(unsigned n=0;n<remoteNodes;++n) RemoteImuRecording::peers[n].dataGate.store(0);
    }
    if(!std::strcmp(argv[1]+8,"fault")) {
      bodaqs_control_acquisition_exclude(&acquisitions[0],27);recordingSteps(1800);
      assert(RemoteImuRecording::failed());
    }
    RemoteImuRecording::stop();
    for(unsigned i=0;i<30000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
    assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
    for(unsigned n=0;n<remoteNodes;++n) {
      ImuFlowDiagnostics::NodeStats stats;
      assert(RemoteImuRecording::finalNodeDiagnostics(n,stats));
      assert(stats.packetsAccepted==1 && stats.samplesAccepted==5 && stats.sampleCapacity==2048);
      assert(!acquisitions[n].recording && !acquisitions[n].lease_valid);
    }
    simulatedStorage.clear();RemoteImuRecording::release();CanMasterManager::endRecordingHandoff();
    ImuFlowDiagnostics::NodeStats unavailable;assert(!RemoteImuRecording::finalNodeDiagnostics(0,unavailable));
    assert(DynamicSpscQueueDetail::liveAllocations==0);
    if(remoteNodes>1 && std::strcmp(argv[1]+8,"fault")) {
      advance(12000);
      for(unsigned wait=0;wait<300000;++wait) {
        bool ready=true;for(unsigned n=0;n<remoteNodes;++n) ready&=CanMasterManager::configurationReconciled(n);
        if(ready) break;
        advance(1);
      }
      assert(RemoteImuRecording::configure(config) && RemoteImuRecording::configured());
      for(unsigned n=0;n<remoteNodes;++n) {
        assert(!RemoteImuRecording::peers[n].sharedRetirements[0].load());
        assert(!RemoteImuRecording::peers[n].sharedRetirements[1].load());
        assert(!RemoteImuRecording::peers[n].managementRetirements.load());
      }
      for(const auto& progress:RemoteImuRecording::sharedProgress) assert(!progress.object && !progress.pending);
      RemoteImuRecording::stop();
      for(unsigned i=0;i<30000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
      assert(RemoteImuRecording::stopped());RemoteImuRecording::release();
      assert(DynamicSpscQueueDetail::liveAllocations==0);
    }
    puts("compact multi-node isolation, exact RAM admissions and retired cleanup: PASS");return 0;
  }
#endif
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
  uint32_t confirmedAt=0;
  for(unsigned i=0;i<1600 && !confirmedAt;++i) {
    recordingSteps(1);AcquisitionControl::Outcome stopResult;AcquisitionControl::outcome(0,stopResult);
    if(stopResult.action==AcquisitionControl::Action::Stop && stopResult.result==AcquisitionControl::Result::Succeeded)
      confirmedAt=clockMs;
  }
  assert(confirmedAt && int32_t(confirmedAt-stoppedAt)>0);
  assert(acquisitions[0].terminal && acquisitions[0].stopped && !acquisitions[0].lease_valid);
  assert(!RemoteImuRecording::failed());
  assert(!RemoteImuRecording::tailDrained());
  // Keep control/transport service running while testing the normal tail.
  // Jumping wall time with an in-flight STOP result fabricates a transport
  // timeout unrelated to the coordinator's five-second tail deadline.
  while(int32_t(clockMs-(confirmedAt+4999))<0) recordingSteps(1);
  // No storage calls participate in this deadline. A repeated STOP cannot
  // restart the five-second normal tail interval.
  RemoteImuRecording::stop();RemoteImuRecording::service();
  assert(!RemoteImuRecording::tailDrained());
  clockMs=confirmedAt+5000;RemoteImuRecording::service();
  if(remoteNodes==1) assert(RemoteImuRecording::tailDrained());
  // Each participant's interval begins at its own confirmed STOP result.
  retirePhysicalMaster=false;
  for(unsigned i=0;i<1600 && !RemoteImuRecording::tailDrained();++i) recordingSteps(1);
  assert(RemoteImuRecording::tailDrained());
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
  uint32_t finalTransfer=0,finalDecode=0;
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
  const auto* captured=RemoteImuRecording::finalRejectedMeasurementReplies();
  assert(captured && captured==&ImuFlowDiagnostics::finishedReplies);
  assert(captured->count>=1 && captured->count<=4);
  assert(!memcmp(captured->entries[0].reply,capturedWire,256));
#else
  assert(!RemoteImuRecording::finalRejectedMeasurementReplies());
#endif
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  assert(RemoteImuRecording::finalMeasurementFailures(finalTransfer,finalDecode));
  assert(finalTransfer==CanMasterManager::diagnostics().measurementTiming.transferFailedSlots);
  assert(finalDecode==CanMasterManager::diagnostics().measurementTiming.decodeFailedSlots);
#else
  assert(!RemoteImuRecording::finalMeasurementFailures(finalTransfer,finalDecode));
#endif
  simulatedStorage.clear();RemoteImuRecording::release();
  assert(!RemoteImuRecording::configured());
  assert(!RemoteImuRecording::finalRejectedMeasurementReplies());
  assert(!RemoteImuRecording::finalMeasurementFailures(finalTransfer,finalDecode));
  CanMasterManager::endRecordingHandoff();
  if(remoteNodes==4) {puts("production four-node resource/lifecycle isolation passed");return 0;}
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
  assert(RemoteImuRecording::configure(config));assert(RemoteImuRecording::resourcesReady());recordingSteps(3000);
  assert(!RemoteImuRecording::failed());
  RemoteImuRecording::start();recordingSteps(500);recording=true;
  loseMeasurementReplies=true;recordingSteps(330);loseMeasurementReplies=false;
  AcquisitionControl::Outcome excluded;AcquisitionControl::outcome(0,excluded);
  assert(excluded.excluded && !excluded.leaseAcknowledged);
  assert(!CanMasterManager::measurementReady());
  assert(RemoteImuRecording::failed() && recording); // Healthy locals remain running.
  RemoteImuRecording::Failure originalFailure;
  assert(RemoteImuRecording::failure(0,originalFailure));
  assert(originalFailure.result==unsigned(AcquisitionControl::Result::Unavailable));
  assert(originalFailure.reason==26);
  const uint32_t oldRenewal=acquisitions[0].renewal_sequence;
  recordingSteps(11000);
  assert(acquisitions[0].renewal_sequence==oldRenewal);
  assert(RemoteImuRecording::tailDrained());
  RemoteImuRecording::Completion incomplete;
  assert(RemoteImuRecording::completion(0,incomplete) && !incomplete.stopConfirmed && incomplete.uncertain);
  assert(!RemoteImuRecording::stopped()); // Tail cutoff is distinct from administrative cleanup.
  recording=false;
  for(unsigned i=0;i<20000 && !RemoteImuRecording::stopped();++i) recordingSteps(1);
  assert(RemoteImuRecording::stopped() && !AcquisitionControl::active());
  RemoteImuRecording::Failure retainedFailure;
  assert(RemoteImuRecording::failure(0,retainedFailure));
  assert(retainedFailure.observedMs==originalFailure.observedMs &&
         retainedFailure.action==originalFailure.action &&
         retainedFailure.reason==originalFailure.reason);
  assert(originalFailure.timing.slots && originalFailure.timing.failedSlots);
  assert(originalFailure.timingAvailable);
  assert(retainedFailure.timing.slots==originalFailure.timing.slots &&
         retainedFailure.timing.exchangeUs==originalFailure.timing.exchangeUs);
  uint32_t transfer=0,decode=0;
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  assert(RemoteImuRecording::finalMeasurementFailures(transfer,decode));
  assert(transfer==CanMasterManager::diagnostics().measurementTiming.transferFailedSlots);
  assert(decode==CanMasterManager::diagnostics().measurementTiming.decodeFailedSlots);
#else
  assert(!RemoteImuRecording::finalMeasurementFailures(transfer,decode));
#endif
  assert(!acquisitions[0].recording && acquisitions[0].fenced);
  simulatedStorage.clear();RemoteImuRecording::release();CanMasterManager::endRecordingHandoff();
  // A configured but unavailable remote sensor must not silently become ready.
  reset();spiAvailable=false;
  assert(RemoteImuRecording::configure(config));
  assert(RemoteImuRecording::failed());
  assert(!RemoteImuRecording::configured());
  assert(RemoteImuRecording::prepared()); // Local start gate remains usable.
  RemoteImuRecording::start();assert(RemoteImuRecording::recording());
  assert(saved.type==SensorType::LSM6DSO32XImu && !saved.mutedDefault);
  simulatedStorage.clear();RemoteImuRecording::release();
  puts("production remote coordinator prepare/snapshot/START/STOP/tail/fence/release/exit passed");
}
