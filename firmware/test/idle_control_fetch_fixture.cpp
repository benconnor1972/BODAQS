static bool consumeSchedulingTest(uint8_t,uint8_t,uint32_t,const uint8_t*,uint16_t) {return false;}
static void seedAccepted(CanMasterManager::MeasurementInbox& inbox,uint8_t cls,uint8_t n) {
  uint8_t payload[64]={};inbox={};
  assert(bodaqs_fragment_seal(&inbox.state,inbox.bytes,sizeof inbox.bytes,456,71,n,cls,0,sizeof payload));
  inbox.admitted=true;inbox.ackPending=true;
  bodaqs_fragment_ack(&inbox.state,1,&inbox.pendingAck);
}
int main(int argc,char** argv) {
  assert(argc==2);const char* scenario=argv[1];
  reset();fixedMeasurementClock=true;
  CanMasterManager::beginRecordingHandoff();
  for(unsigned i=0;i<5500 && !CanMasterManager::recordingHandoffReady();++i) advance(1);
  assert(CanMasterManager::recordingHandoffReady());
  assert(AcquisitionControl::setDataConsumer(consumeSchedulingTest,3));
  assert(AcquisitionControl::begin(123,456));
  for(unsigned i=0;i<100 && !CanMasterManager::measurementReady();++i) AcquisitionControl::service();
  assert(CanMasterManager::measurementReady());
  using namespace AcquisitionControl;
  transport.bridgeNext=clockMs+10000;nextHealthObservation=clockMs+10000;
  serviceCursor=3;cursor=0;dataCursor=0;
  if(!std::strcmp(scenario,"ack")) seedAccepted(transport.inboxes[0][1],1,1);
  if(!std::strcmp(scenario,"ordinary") || !std::strcmp(scenario,"fair")) {
    peers[2].ordinary.pending=true;peers[2].ordinary.started=clockMs;
  }
  if(!std::strcmp(scenario,"fair")) {peers[0].ordinary.pending=true;peers[0].ordinary.started=clockMs;}
  if(!std::strcmp(scenario,"urgent")) {peers[1].protectedLane.pending=true;peers[1].protectedLane.started=clockMs;}
  if(!std::strcmp(scenario,"partial")) {
    auto& s=transport.inboxes[2][3].state;s.context=456;s.object=71;s.cls=3;s.node=3;s.total=64;s.mask=1;
  }
  if(!std::strcmp(scenario,"control-ack")) seedAccepted(transport.inboxes[2][3],3,3);
  if(!std::strcmp(scenario,"retired-cache")) {
    seedAccepted(transport.inboxes[3][0],4,0);transport.inboxes[3][0].ackPending=false;
  }
  if(!std::strcmp(scenario,"blocked")) for(unsigned n=0;n<2;++n) for(unsigned c=0;c<2;++c) {
    seedAccepted(transport.inboxes[c][n],c+1,n);transport.inboxes[c][n].admitted=false;transport.inboxes[c][n].ackPending=false;
  }
  if(!std::strcmp(scenario,"no-data")) dataConsumer=nullptr;
  capturedSchedule.clear();AcquisitionControl::service();assert(capturedSchedule.size()==1);
  auto request=capturedSchedule.back();
  auto targetClass=[](const BodaqsMeasurementSlot& r) {return r.kind==14?r.body[2]:r.body[0];};
  auto targetNode=[](const BodaqsMeasurementSlot& r) {return r.kind==14?r.body[3]:r.node;};
  const unsigned cls=targetClass(request),n=targetNode(request);
  if(!std::strcmp(scenario,"idle") || !std::strcmp(scenario,"retired-cache")) {
    assert(request.kind==1 && cls==1 && n==0 && "idle control selection must become a data fetch");
  } else if(!std::strcmp(scenario,"ack")) {
    const auto& expected=transport.inboxes[0][1].pendingAck;
    assert(request.kind==14 && cls==1 && n==0);
    assert(request.node==expected.node && request.object==expected.object && request.total==expected.total && request.context==expected.context);
    assert(request.body[0]==expected.body[0] && request.body[1]==expected.body[1] && !std::memcmp(request.body+4,expected.body+4,4));
    assert(transport.inboxes[0][1].ackPending); // Sending never fabricates retirement.
  } else if(!std::strcmp(scenario,"ordinary")) {
    assert(request.kind==1 && cls==3 && n==2); // Unselected node still has real work.
  } else if(!std::strcmp(scenario,"urgent")) {
    assert(request.kind==1 && cls==4 && n==1);
  } else if(!std::strcmp(scenario,"partial")) {
    assert(request.kind==1 && cls==3 && n==3 && request.object==71 && request.index==1);
  } else if(!std::strcmp(scenario,"control-ack")) {
    assert(request.kind==14 && request.body[0]==3 && request.node==3 && cls==3 && n==3);
    assert(transport.inboxes[2][3].ackPending);
  } else if(!std::strcmp(scenario,"blocked") || !std::strcmp(scenario,"no-data")) {
    assert(request.kind==1 && cls==4 && n==0); // Preserve drain opportunity when nothing eligible.
  } else if(!std::strcmp(scenario,"fair")) {
    unsigned counts[4]={};++counts[n];
    for(unsigned i=1;i<16;++i) {serviceCursor=3;AcquisitionControl::service();assert(targetClass(capturedSchedule.back())==3);++counts[targetNode(capturedSchedule.back())];}
    assert(counts[0]>=2 && counts[2]>=2 && !counts[1] && !counts[3]);
  } else assert(false);
  printf("Actual acquisition selector / encoded wire preserves %s: PASS\n",scenario);
}
