// Production transport/master service with a controlled delayed publication.
// DMA/RTOS/SD timing is simulated; this is a scheduling invariant, not capacity.
static void runCase(uint8_t address,unsigned ordinaryTurns) {
  reset();fixedMeasurementClock=true;
  assert(CanMasterManager::enterMeasurementMode(123,456));
  master.discovery[address]=master.discovery[0];master.discovery[address].node_address=address;
  master.acquisition_record[address]=123;master.acquisition_boot[address]=node.view.boot_id;
  master.acquisition_fenced=0;master.anchor_boot[address]=node.view.boot_id;master.anchor_epoch[address]=1;
  static CanMasterManager::MeasurementTransport transport;transport={};
  CanMasterManager::MeasurementInbox* completed=nullptr;
  for(unsigned i=0;i<2;++i) assert(CanMasterManager::serviceMeasurementTransport(transport,4,address,completed)>=0);
  master.anchor_boot[address]=node.view.boot_id;master.anchor_epoch[address]=1;
  for(unsigned packet=0;packet<13;++packet) {
    uint8_t bytes[64]={};bytes[0]=uint8_t(packet*5);bytes[2]=1;bytes[3]=5;
    assert(bodaqs_master_service_receive_can(&master,address,1,uint16_t(0x100+8*address),bytes,64,0,1234+packet,clockMs));
  }
  auto& sample=transport.inboxes[0][address];
  for(unsigned i=0;i<10 && !sample.state.object;++i) {
    clockMs+=21;
    assert(CanMasterManager::serviceMeasurementTransport(transport,1,address,completed)>=0);
  }
  assert(sample.state.total==1008 && sample.state.mask==1 && !sample.state.complete);
  // Genuine retained shared object, validated into owned RAM before releasing.
  master.measurement.fenced=false;master.measurement.quiescent=false;
  uint8_t sync[24]={1,0,1};sync[4]=1;sync[8]=1;
  assert(bodaqs_master_service_publish_evidence(&master,sync,sizeof sync));
  BodaqsMeasurementSlot fragment={},ack={};
  assert(bodaqs_fragment_emit(&master.master_evidence,master.master_evidence_bytes,0,&fragment));
  auto& shared=transport.inboxes[4][0];
  assert(bodaqs_fragment_accept(&shared.state,shared.bytes,sizeof shared.bytes,&fragment,1,&ack)==1);

  // No data response or retirement proof arrives during these five exchanges.
  BodaqsMeasurementSlot empty={};empty.context=456;empty.node=255;
  assert(bodaqs_measurement_encode(&empty,preloaded,sizeof preloaded));
  delayStatusResponses=true;delayedResponseDepth=8;delayedSpiSlots.clear();
  for(unsigned i=0;i<ordinaryTurns;++i) assert(CanMasterManager::serviceMeasurementTransport(transport,1,address,completed)>=0);
  CanMasterManager::releaseMeasurementObject(shared);assert(shared.ackPending);
  observedRequests.clear();
  for(unsigned i=0;i<5;++i) {
    assert(CanMasterManager::serviceMeasurementTransport(transport,1,address,completed)>=0);
    assert(!completed && sample.state.mask==1 && !sample.admitted && !sample.ackPending);
    assert(shared.ackPending); // Scheduling does not manufacture retirement.
  }
  assert(observedRequests.size()==5);
  for(unsigned i=0;i<5;++i) {
    const auto& request=observedRequests[i];
    assert(request.kind==14 && request.body[0]==5 && request.node==255);
    assert(request.body[2]==1 && request.body[3]==address);
    assert(bodaqs_measurement_get(request.body+8,4)==sample.state.object);
    std::printf("%u%s",unsigned(request.body[12]),i==4?"\n":",");
    const unsigned expected=BODAQS_ACK_FETCH_FRAGMENT_SWEEP?1+(i+ordinaryTurns)%4:1;
    assert(request.body[12]==expected);
  }
  delayStatusResponses=false;delayedSpiSlots.clear();
  // A hinted-but-lost fragment must still be fetched and checksum-validated.
  dropDataFragmentOnce=true;droppedDataFragments=0;droppedFragmentIndex=2;
  bool accepted=false;
  for(unsigned i=0;i<120 && !accepted;++i) {
    ++clockMs;
    const int result=CanMasterManager::serviceMeasurementTransport(transport,1,address,completed);
    assert(result>=0);
    if(result==1) {assert(completed==&sample && sample.state.complete);accepted=true;}
  }
  assert(accepted && droppedDataFragments==1 && !sample.admitted && !sample.ackPending);
  const uint32_t before=master.objects_acked;
  CanMasterManager::releaseMeasurementObject(sample);
  for(unsigned i=0;i<60 && sample.ackPending;++i) {
    ++clockMs;CanMasterManager::serviceMeasurementTransport(transport,1,address,completed);
  }
  assert(!sample.ackPending && master.objects_acked==before+1);
  std::puts("ACK-fetch delayed publication: exact sweep, loss retry, RAM acceptance and retirement PASS");
}

int main() {
  runCase(0,0);runCase(1,0);runCase(0,2);runCase(1,2);
}
