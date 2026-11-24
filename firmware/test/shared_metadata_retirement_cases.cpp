// Included inside the integrated runner's main; physical node backend failures
// are injected, while coordinator/control/custody/storage code remains real.
if(scenario=="shared-startup-failure" || scenario=="shared-runtime-failure") {
  assert(fixtureSensorCount==4);
#if BODAQS_MEASUREMENT_VERSION >= 4
  // These cases isolate participant failure; the ordinary scenarios exercise
  // selective window loss with all sources present.
  holdWindowUnit=false;dropWindowProof=false;
#endif
  const bool startup=scenario=="shared-startup-failure";
  fixtureRejectPrepareMask=startup?6:0; // Same two CLOCK_UNTRUSTED refusals seen in r11.
  assert(LoggingManager::requestStart()==LoggingManager::StartResult::Pending);
  for(unsigned i=0;i<20000 && !s_running;++i)step(1);
  assert(s_running && worker.recording());
  RemoteImuRecording::Failure failure;
  if(startup) {
    for(unsigned n: {1u,2u}) {
      assert(RemoteImuRecording::failure(n,failure) && failure.reason==35);
      assert(!acquisitions[n].lease_valid);
    }
    assert(acquisitions[0].lease_valid && acquisitions[3].lease_valid);
  }
  // A shared object must continue to both healthy participants even though
  // configured participant1 can no longer accept any file records.
  uint8_t sync[24]={1,0,1,0,1,0,0,0,1};
  auto publish=[&](uint32_t sequence) {
    BdqV2Format::putU32(sync+12,sequence);BdqV2Format::putU32(sync+16,clockMs*1000);BdqV2Format::putU32(sync+20,1);
    assert(bodaqs_master_service_publish_evidence(&master,sync,sizeof sync));
    step(200);
    if(master.master_evidence.complete) std::fprintf(stderr,"shared SYNC %u still retained at %u ms\n",sequence,clockMs);
    assert(!master.master_evidence.complete); // Fails on the r11 closed-peer gate.
  };
  if(!startup) {
    publish(7000); // Every participant accepts this before a fatal source loss.
    bodaqs_master_service_loss_counts(&master,0,2,1,0,0,0,1,true,clockMs*1000,1);
    for(unsigned i=0;i<10000 && !RemoteImuRecording::failure(0,failure);++i) step(1);
    assert(RemoteImuRecording::failure(0,failure));
    step(200);
  }
  publish(7001);
  publish(7002); // New shared identity must not inherit the previous fan-out mask.
  feedWire(argv[1],40,startup?9:14); // Actual CAN data still reaches healthy sources.
  LoggingManager::stop(LoggingManager::StopReason::UserRequest,"operator");
  awaitFinalized();
  assert(storage.cleanClosed && !AcquisitionControl::active());
  assert(std::fclose(inputLedger)==0 && std::fclose(controlLedger)==0);
  puts("Shared metadata retires with failed participants; live source data and normal STOP remain active: PASS");
  return 0;
}
