static void asynchronousInspectionProofs() {
  for(unsigned variant=0;variant<9;++variant) {
    reset();fixedMeasurementClock=true;
    assert(CanMasterManager::enterMeasurementMode(123,456));
    master.acquisition_fenced=1;master.measurement.fenced=true;
    deferFenceStatus=true;haveDeferredFenceStatus=false;
    assert(!CanMasterManager::inspectMeasurementMode());
    assert(haveDeferredFenceStatus);
    BodaqsMeasurementSlot proof={};
    assert(bodaqs_measurement_decode(deferredFenceStatus,BODAQS_MEASUREMENT_BYTES,&proof));
    assert(proof.kind==6 && (proof.body[36]&2));
    deferFenceStatus=false;
    if(variant==1) ++proof.object;
    if(variant==2) ++proof.context;
    if(variant>=3 && variant<=6) ++proof.body[(variant-3)*8]; // boot, session, record, body context
    if(variant==7) clockMs+=301;
    assert(bodaqs_measurement_encode(&proof,preloaded,BODAQS_MEASUREMENT_BYTES));
    BodaqsMeasurementSlot poll={},received={};poll.kind=1;poll.node=255;poll.context=456;poll.body[0]=5;
    assert(CanMasterManager::exchangeMeasurementSlot(poll,received));
    const uint32_t before=master.slots_received;
    if(variant>=3 && variant<=6) {
      assert(!CanMasterManager::measurementReady()); // matched identity change fails closed
      continue;
    }
    assert(CanMasterManager::inspectMeasurementMode());
    if(variant==0 || variant==8) {
      assert(master.slots_received==before); // proof arrived on an ordinary poll, no extra wire exchange
      if(variant==8) {
        assert(bodaqs_measurement_encode(&proof,preloaded,BODAQS_MEASUREMENT_BYTES));
        assert(CanMasterManager::exchangeMeasurementSlot(poll,received));
        const uint32_t replayBefore=master.slots_received;
        assert(CanMasterManager::inspectMeasurementMode());
        assert(master.slots_received>replayBefore); // consumed nonce cannot satisfy another inspection
      }
    } else assert(master.slots_received>before); // wrong/expired proof requires a fresh successful query
  }
  deferFenceStatus=false;haveDeferredFenceStatus=false;
  puts("asynchronous mode proofs preserve nonce, binding, freshness and one-time consumption: PASS");
}
static void uncertainExitBindingGates() {
  for(unsigned variant=0;variant<8;++variant) {
    reset();fixedMeasurementClock=false;fastMeasurementClock=true;
    assert(CanMasterManager::enterMeasurementMode(123,456));
    loseExitStageRequest=true;
    assert(!CanMasterManager::exitMeasurementMode());
    assert(CanMasterManager::diagnostics().measurement.phase==3);
    loseExitStageRequest=false;
    const uint32_t sequence=master.measurement.sequence;
    if(variant==0) ++master.control.master_boot_id;
    if(variant==1) ++master.measurement.mode.session;
    if(variant==2) ++master.measurement.mode.recording;
    if(variant==3) ++master.measurement.mode.context;
    if(variant==4) master.measurement.fenced=false;
    if(variant==5) master.measurement.quiescent=false;
    if(variant==6) master.measurement.mode.phase=1;
    if(variant==7) {master.measurement.mode.phase=4;master.measurement.mode.reason=13;}
    const unsigned expectedPhase=variant==6?1:variant==7?4:2;
    for(unsigned i=0;i<10;++i) {
      assert(!CanMasterManager::exitMeasurementMode());
      assert(!CanMasterManager::enterMeasurementMode(321,654));
    }
    assert(master.measurement.mode.phase==expectedPhase && master.measurement.sequence==sequence);
  }
  reset();fixedMeasurementClock=false;fastMeasurementClock=true;
  assert(CanMasterManager::enterMeasurementMode(123,456));
  loseExitStageRequest=true;assert(!CanMasterManager::exitMeasurementMode());loseExitStageRequest=false;
  const uint32_t savedAllocator=s_nextSequence,oldStage=master.measurement.sequence;
  s_nextSequence=UINT32_MAX-1;
  assert(!CanMasterManager::exitMeasurementMode());
  assert(s_nextSequence==UINT32_MAX);
  for(unsigned i=0;i<4;++i) {
    assert(!CanMasterManager::exitMeasurementMode());
    assert(!CanMasterManager::enterMeasurementMode(321,654));
    assert(s_nextSequence==UINT32_MAX && master.measurement.sequence==oldStage);
    assert(CanMasterManager::diagnostics().measurementUnavailable);
  }
  s_nextSequence=savedAllocator; // Test-only exhausted allocator injection ends with this fixture reset.
  puts("uncertain exit refuses changed binding or absent physical fence/quiescence: PASS");
}
int main() {
  asynchronousInspectionProofs();
  uncertainExitBindingGates();
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
      full=true;
    }
  }
  assert(full);auto& inbox=transport.inboxes[0][0];
  const uint32_t pinned=inbox.state.object,acceptedBefore=master.objects_acked;
  const std::vector<uint8_t> pinnedBytes(inbox.bytes,inbox.bytes+inbox.state.total);
  for(unsigned i=0;i<100;++i) {
    ++clockMs;CanMasterManager::serviceMeasurementTransport(transport,1,0,completed);
  }
  assert(master.objects_acked==acceptedBefore && master.receptions[0].object.object==pinned);
  assert(!inbox.admitted && !inbox.ackPending);
  assert(std::equal(pinnedBytes.begin(),pinnedBytes.end(),inbox.bytes));
  retainedRam.push_back(pinnedBytes);CanMasterManager::releaseMeasurementObject(inbox);
  const uint32_t oldObject=inbox.pendingAck.object;
  clockMs+=30;
  CanMasterManager::serviceMeasurementTransport(transport,1,0,completed); // ACK/fetch dispatched
  BodaqsMeasurementSlot poll={},lost={};poll.kind=1;poll.context=456;poll.node=0;poll.body[0]=1;
  assert(CanMasterManager::exchangeMeasurementSlot(poll,lost));
  assert(lost.retired && lost.retiredObject==oldObject); // whole confirmation lost to caller
  for(unsigned fault=0;fault<5;++fault) {
    auto wrong=lost;
    if(fault==0) wrong.retiredClass=2;
    if(fault==1) wrong.retiredNode=1;
    if(fault==2) ++wrong.retiredObject;
    if(fault==3) --wrong.retiredTotal;
    if(fault==4) wrong.retiredChecksum^=1;
    assert(bodaqs_measurement_encode(&wrong,preloaded,sizeof preloaded));
    const int ignored=CanMasterManager::serviceMeasurementTransport(transport,1,0,completed);
    assert(ignored>=0 && ignored!=1);
    assert(inbox.ackPending && inbox.pendingAck.object==oldObject);
    assert(!CanMasterManager::measurementObjectReady(inbox));
  }
  assert(CanMasterManager::exchangeMeasurementSlot(poll,lost)); // discard the real confirmation once more
  int response=CanMasterManager::serviceMeasurementTransport(transport,1,0,completed);
  assert(response!=1 && inbox.state.complete && inbox.state.total==96);
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
