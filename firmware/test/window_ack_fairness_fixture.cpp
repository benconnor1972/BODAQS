// Composed after the real logger/master fixture. Only SPI/time are stubbed.
int main(int argc,char** argv) {
  assert(argc==3);
  const unsigned lag=unsigned(std::strtoul(argv[1],nullptr,10));
  const unsigned loseEvery=unsigned(std::strtoul(argv[2],nullptr,10));
  assert(lag>=1 && lag<=4);
  reset();assert(CanMasterManager::enterMeasurementMode(123,456));
  fixedMeasurementClock=true;
  static CanMasterManager::MeasurementTransport bank;
  bank.sampleNodes=3;
  CanMasterManager::MeasurementInbox* initial=nullptr;
  for(unsigned i=0;i<2;++i) CanMasterManager::serviceMeasurementTransport(bank,1,255,initial);
  for(unsigned n=0;n<2;++n) {
    master.discovery[n].flags=1;master.discovery[n].boot_id=node.view.boot_id;
    master.acquisition_record[n]=123;master.acquisition_boot[n]=node.view.boot_id;
    master.anchor_boot[n]=node.view.boot_id;master.anchor_epoch[n]=1;
  }
  delayStatusResponses=lag>1;delayedResponseDepth=lag-1;
  fairnessLoseEvery=loseEvery;
  unsigned offered[2]={},accepted[2]={},evidence[2]={};
  for(unsigned ms=0;ms<10000;++ms) {
    ++clockMs;
    // Independently specified equal3333.3 readings/s sources, not a measure
    // of hardware speed. Keep ingress active while proofs remain in flight.
    if(ms%3==0) for(unsigned n=0;n<2;++n) for(unsigned packet=0;packet<2;++packet) {
      uint8_t bytes[64]={0,0,1,5};bodaqs_measurement_put(bytes,offered[n],2);offered[n]+=5;
      (void)bodaqs_master_service_receive_can(&master,n,1,0x100+8*n,bytes,64,0,clockMs*1000,clockMs);
    }
    if(ms%25==0) for(unsigned n=0;n<2;++n) {
      uint8_t anchor[32]={1,0x22,1,0,0,0,20,0,0,1,1};
      bodaqs_measurement_put(anchor+12,offered[n],4);
      bodaqs_measurement_put(anchor+16,clockMs*1000,4);
      bodaqs_measurement_put(anchor+20,300,4);anchor[24]=1;
      assert(bodaqs_master_service_receive_can(&master,n,2,0x90+n,anchor,32,0,clockMs*1000,clockMs));
    }
    CanMasterManager::MeasurementInbox* completed=nullptr;
    // Repeat evidence probes on adjacent turns. A permanently erased poll is
    // outside ACK selection's control; this keeps alternating loss from hiding
    // a source's evidence head before it can even earn a custody ACK.
    const bool evidenceTurn=ms%8==1 || ms%8==2;
    const int result=CanMasterManager::serviceMeasurementTransport(bank,evidenceTurn?2:1,evidenceTurn?ms/8%2:255,completed);
    assert(result!=-14); // individual stale replies cannot revoke this valid context
    if(completed && completed->state.cls==2) {
      evidence[completed->state.node]+=unsigned(bodaqs_measurement_get(completed->bytes+12,2));
      CanMasterManager::releaseMeasurementObject(*completed);
    }
    for(unsigned n=0;n<2;++n) {
      auto& inbox=CanMasterManager::nextSampleInbox(bank,n);
      if(inbox.state.object==bank.sampleNext[n] && CanMasterManager::measurementObjectReady(inbox)) {
        accepted[n]+=unsigned(bodaqs_measurement_get(inbox.bytes+12,2))*5;
        CanMasterManager::releaseMeasurementObject(inbox);++bank.sampleNext[n];
      }
    }
  }
  std::printf("ACK fairness lag%u loseEvery%u: offered%u/%u admitted%u/%u anchors%u/%u\n",
    lag,loseEvery,offered[0],offered[1],accepted[0],accepted[1],evidence[0],evidence[1]);
  std::fflush(stdout);
  // Ten seconds offers33340 readings/source. Allow only the final unfinished
  // units, not sustained starvation behind replayed retirement proofs.
  assert(offered[0]==33340 && offered[1]==33340);
  if(loseEvery==2) {
    // Half of MOSI is erased: there is no lossless service claim. Both sources
    // must still get substantial equal custody while all anchors progress.
    assert(accepted[0]>=20000 && accepted[1]>=20000);
    assert(accepted[0]<=accepted[1]+100 && accepted[1]<=accepted[0]+100);
  } else assert(accepted[0]>=33000 && accepted[1]>=33000);
  assert(evidence[0]>=395 && evidence[1]>=395);
}
