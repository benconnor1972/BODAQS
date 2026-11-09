int main() {
  reset();fixedMeasurementClock=true;
  assert(CanMasterManager::enterMeasurementMode(123,456));
  master.acquisition_record[0]=123;master.acquisition_boot[0]=node.view.boot_id;
  master.acquisition_fenced &= ~1u;
  uint8_t anchor[32]={1,0x22,1,0,0,0,20,0,0,1,1};anchor[20]=0x2c;anchor[21]=1;anchor[24]=1;
  assert(bodaqs_master_service_receive_can(&master,0,2,0x90,anchor,32,0,10,clockMs));
  static CanMasterManager::MeasurementTransport transport;
  CanMasterManager::MeasurementInbox* completed=nullptr;
  bool origin=false;
  for(unsigned i=0;i<100 && !origin;++i) {
    ++clockMs;
    if(CanMasterManager::serviceMeasurementTransport(transport,2,0,completed)==1) {
      assert(completed->state.total==96);origin=true;CanMasterManager::releaseMeasurementObject(*completed);
    }
  }
  assert(origin);
  for(unsigned i=0;i<10;++i) {++clockMs;CanMasterManager::serviceMeasurementTransport(transport,2,0,completed);}
  assert(!transport.inboxes[1][0].ackPending);
  for(unsigned i=0;i<14;++i) {
    uint8_t packet[64]={};packet[0]=i*5;packet[2]=1;packet[3]=i==13?1:5;
    packet[4]=0;packet[5]=0x80;packet[6]=0xff;packet[7]=0x7f;
    assert(bodaqs_master_service_receive_can(&master,0,1,0x100,packet,i==13?16:64,0,20+i,clockMs));
  }
  bool full=false;
  std::vector<std::vector<uint8_t>> retainedRam;
  for(unsigned i=0;i<100 && !full;++i) {
    ++clockMs;
    if(CanMasterManager::serviceMeasurementTransport(transport,1,0,completed)==1) {
      assert(completed->state.total==1008);
      retainedRam.emplace_back(completed->bytes,completed->bytes+completed->state.total);
      CanMasterManager::releaseMeasurementObject(*completed);full=true;
    }
  }
  assert(full);auto& inbox=transport.inboxes[0][0];
  const uint32_t oldObject=inbox.pendingAck.object;
  clockMs+=30;
  CanMasterManager::serviceMeasurementTransport(transport,1,0,completed); // ACK/fetch dispatched
  BodaqsMeasurementSlot poll={},lost={};poll.kind=1;poll.context=456;poll.node=0;poll.body[0]=1;
  assert(CanMasterManager::exchangeMeasurementSlot(poll,lost));
  assert(lost.retired && lost.retiredObject==oldObject); // whole confirmation lost to caller
  int response=CanMasterManager::serviceMeasurementTransport(transport,1,0,completed);
  assert(response==0 && inbox.state.complete && inbox.state.total==96);
  assert(inbox.ackPending && inbox.pendingAck.object==oldObject);
  assert(!CanMasterManager::measurementObjectReady(inbox));
  response=CanMasterManager::serviceMeasurementTransport(transport,1,0,completed);
  assert(response==1 && completed==&inbox && !inbox.ackPending);
  retainedRam.emplace_back(inbox.bytes,inbox.bytes+inbox.state.total);
  CanMasterManager::releaseMeasurementObject(inbox);
  const uint32_t newerAck=inbox.pendingAck.object;
  CanMasterManager::serviceMeasurementTransport(transport,1,0,completed);
  assert(inbox.ackPending && inbox.pendingAck.object==newerAck); // late old proof cannot clear new ACK
  for(unsigned i=0;i<10 && inbox.ackPending;++i) {
    ++clockMs;CanMasterManager::serviceMeasurementTransport(transport,1,0,completed);
  }
  assert(!inbox.ackPending && retainedRam.size()==2);
  assert(BdqV2Format::getU16(retainedRam[0].data()+12)==13);
  assert(BdqV2Format::getU16(retainedRam[1].data()+12)==1);
  assert(retainedRam[1][28]==65 && retainedRam[1][32]==0 && retainedRam[1][33]==0x80);
  const uint32_t slots=master.slots_received;
  for(unsigned i=0;i<1000;++i) {++clockMs;CanMasterManager::serviceMeasurementTransport(transport,1,0,completed);}
  assert(master.slots_received-slots<=55); // idle head probing remains bounded
  puts("real logger RAM acceptance waits for explicit matching retirement after lost reply: PASS");
}
