// Actual logger/master transport; fake clock and physical publication delay.
// The ledger verifies original CAN sequence/axes, independent of object packing.
int main(int argc,char** argv) {
  assert(argc==3);
  const unsigned lag=unsigned(std::strtoul(argv[1],nullptr,10));
  const unsigned loseEvery=unsigned(std::strtoul(argv[2],nullptr,10));
  reset();assert(CanMasterManager::enterMeasurementMode(123,456));
  fixedMeasurementClock=true;
  static CanMasterManager::MeasurementTransport bank;bank.sampleNodes=15;
  CanMasterManager::MeasurementInbox* initial=nullptr;
  for(unsigned i=0;i<2;++i)CanMasterManager::serviceMeasurementTransport(bank,1,255,initial);
  for(unsigned n=0;n<4;++n) {
    master.discovery[n].flags=1;master.discovery[n].boot_id=node.view.boot_id;
    master.acquisition_record[n]=123;master.acquisition_boot[n]=node.view.boot_id;
    master.anchor_boot[n]=node.view.boot_id;master.anchor_epoch[n]=1;
  }
  delayStatusResponses=lag>1;delayedResponseDepth=lag-1;fairnessLoseEvery=loseEvery;
  const unsigned beginning=clockMs;
  unsigned offered[4]={},accepted[4]={},evidence[4]={},last[4]={};
  bool seen[4]={};unsigned previousMs=~0u,units=0;
  for(unsigned turn=0;turn<16667;++turn) {
    const unsigned ms=turn*600/1000;clockMs=beginning+ms;
    if(ms!=previousMs) {
      previousMs=ms;
      if(ms%3==0) for(unsigned n=0;n<4;++n)for(unsigned packet=0;packet<2;++packet) {
        uint8_t bytes[64]={0,0,1,5};bodaqs_measurement_put(bytes,offered[n],2);
        for(unsigned k=0;k<5;++k)bodaqs_measurement_put(bytes+4+12*k,1000+n,2);
        offered[n]+=5;
        (void)bodaqs_master_service_receive_can(&master,n,1,0x100+8*n,bytes,64,0,clockMs*1000,clockMs);
      }
      if(ms%25==0)for(unsigned n=0;n<4;++n) {
        uint8_t anchor[32]={1,0x22,1,0,0,0,20,0,0,1,1};
        bodaqs_measurement_put(anchor+12,offered[n],4);
        bodaqs_measurement_put(anchor+16,clockMs*1000,4);
        bodaqs_measurement_put(anchor+20,300,4);anchor[24]=1;
        assert(bodaqs_master_service_receive_can(&master,n,2,0x90+n,anchor,32,0,clockMs*1000,clockMs));
      }
    }
    CanMasterManager::MeasurementInbox* completed=nullptr;
    const bool ev=turn%8==1 || turn%8==2;
    assert(CanMasterManager::serviceMeasurementTransport(bank,ev?2:1,ev?turn/8%4:255,completed)!=-14);
    if(completed && completed->state.cls==2) {
      evidence[completed->state.node]+=unsigned(bodaqs_measurement_get(completed->bytes+12,2));
      CanMasterManager::releaseMeasurementObject(*completed);
    }
    for(unsigned n=0;n<4;++n) {
      auto& inbox=CanMasterManager::nextSampleInbox(bank,n);
      if(inbox.state.object!=bank.sampleNext[n] || !CanMasterManager::measurementObjectReady(inbox))continue;
      ++units;
      for(unsigned p=0;p<bodaqs_measurement_get(inbox.bytes+12,2);++p) {
        const uint8_t* can=inbox.bytes+16+64*p;
        const unsigned sequence=unsigned(bodaqs_measurement_get(can,2));
        assert(!seen[n] || sequence>last[n]);seen[n]=true;last[n]=sequence;
        assert(sequence+5<=offered[n]);
        for(unsigned k=0;k<5;++k)assert(bodaqs_measurement_get(can+4+12*k,2)==1000+n);
        accepted[n]+=5;
      }
      CanMasterManager::releaseMeasurementObject(inbox);++bank.sampleNext[n];
    }
  }
  std::printf("geometry=%u lag=%u loseEvery=%u requests=%u units=%u retained=%u,%u,%u,%u anchors=%u,%u,%u,%u ingress_loss=%u,%u,%u,%u\n",
    BODAQS_MEASUREMENT_BYTES,lag,loseEvery,fairnessWireTurns,units,accepted[0],accepted[1],accepted[2],accepted[3],
    evidence[0],evidence[1],evidence[2],evidence[3],master.ingress[0].dropped,master.ingress[1].dropped,master.ingress[2].dropped,master.ingress[3].dropped);
  std::fflush(stdout);
  for(unsigned n=0;n<4;++n) {
    assert(offered[n]==33340);
    assert(accepted[n]>10000 && evidence[n]>300);
    for(unsigned other=0;other<4;++other) assert(accepted[n]<accepted[other]+2500);
  }
}
