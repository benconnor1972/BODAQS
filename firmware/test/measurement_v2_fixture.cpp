#include "bodaqs_master_service.h"
#include <cassert>
#include <cstdio>
#include <cstring>
static BodaqsMasterService service;
static BodaqsMeasurementSlot transfer(const BodaqsMeasurementSlot& request,unsigned now=100) {
  uint8_t tx[256],rx[256];BodaqsMeasurementSlot reply={};
  assert(bodaqs_measurement_encode(&request,tx,sizeof tx));
  assert(bodaqs_master_service_process_transfer(&service,tx,256,now,rx)==BODAQS_MASTER_SLOT_PROCESSED);
  assert(bodaqs_measurement_decode(rx,256,&reply));return reply;
}
int main(int argc,char** argv) {
  assert(argc==2);
  BodaqsMeasurementMode mode={};mode.boot=99;mode.session=1;mode.recording=77;mode.context=9;mode.caller=1;
  mode.version=2;mode.maximum=1024;mode.physical=256;mode.hz=16000000;mode.gap=25;
  assert(bodaqs_measurement_limits(&mode));
  auto incompatible=mode;incompatible.version=1;assert(!bodaqs_measurement_limits(&incompatible));
  BodaqsMasterIdentity identity={};bodaqs_master_service_init(&service,&identity);
  bodaqs_control_exchange_init(&service.control,99);service.measurement.mode.boot=99;
  assert(!bodaqs_measurement_stage(&service.measurement,&mode,7,1,false));
  BodaqsMeasurementSlot confirm={};confirm.kind=8;confirm.node=255;confirm.context=9;confirm.object=7;
  bodaqs_measurement_confirm_body(&mode,confirm.body);
  assert(transfer(confirm).body[32]==2);
  service.discovery[0].flags=1;service.discovery[0].boot_id=17;
  service.acquisition_record[0]=77;service.acquisition_boot[0]=17;
  uint8_t anchor[32]={1,0x22,1,0,0,0,20,0,0,1,1};anchor[20]=0x2c;anchor[21]=1;anchor[24]=1;
  assert(bodaqs_master_service_receive_can(&service,0,2,0x90,anchor,32,0,10,1));
  BodaqsMeasurementSlot poll={};poll.kind=1;poll.node=0;poll.context=9;poll.body[0]=2;
  const auto evidence=transfer(poll);assert(evidence.total==96);
  uint8_t bytes[1024]={};BodaqsFragmentState assembled={};BodaqsMeasurementSlot ack={};
  assert(bodaqs_fragment_accept(&assembled,bytes,sizeof bytes,&evidence,1,&ack)==1);
  transfer(ack);
  for(unsigned i=0;i<13;++i) {
    uint8_t packet[64]={};packet[0]=static_cast<uint8_t>(i*5);packet[2]=1;packet[3]=5;
    packet[4]=0;packet[5]=0x80;packet[6]=0xff;packet[7]=0x7f;
    assert(bodaqs_master_service_receive_can(&service,0,1,0x100,packet,64,0,20+i,2+i));
  }
  poll.body[0]=1;
  auto first=transfer(poll);assert(first.total==1008);
  assembled={};
  for(unsigned i=0;i<5;++i) {
    poll.object=first.object;poll.index=i;
    auto fragment=transfer(poll);
    assert(bodaqs_fragment_accept(&assembled,bytes,sizeof bytes,&fragment,1,&ack)==(i==4?1:0));
  }
  assert(bytes[16+12+4]==0 && bytes[16+12+5]==0x80);
  // Next real batch is shorter than the immutable accepted head.
  uint8_t packet[16]={65,0,1,1};
  assert(bodaqs_master_service_receive_can(&service,0,1,0x100,packet,16,0,100,20));
  BodaqsMeasurementSlot fetch=ack;fetch.kind=14;fetch.body[2]=1;fetch.body[3]=0;
  const uint32_t acknowledged=service.objects_acked;
  for(unsigned fault=0;fault<6;++fault) {
    auto wrong=fetch;
    if(fault==0) ++wrong.context;
    if(fault==1) wrong.body[0]=2;
    if(fault==2) wrong.node=1;
    if(fault==3) ++wrong.object;
    if(fault==4) --wrong.total;
    if(fault==5) wrong.body[1]=3;
    assert(!transfer(wrong).retired);
    assert(service.objects_acked==acknowledged && service.receptions[0].object.complete);
  }
  for(unsigned fault=0;fault<4;++fault) {
    auto wrong=fetch;
    if(fault==0) wrong.body[2]=0;
    if(fault==1) wrong.index=1;
    if(fault==2) {wrong.retired=true;wrong.retiredClass=1;wrong.retiredObject=first.object;wrong.retiredTotal=1008;wrong.retiredChecksum=assembled.checksum;}
    if(fault==3) {wrong.body[2]=5;wrong.body[3]=0;}
    uint8_t tx[256],rx[256];assert(bodaqs_measurement_encode(&wrong,tx,256));
    assert(bodaqs_master_service_process_transfer(&service,tx,256,100,rx)==BODAQS_MASTER_SLOT_MALFORMED);
    assert(service.objects_acked==acknowledged && service.receptions[0].object.complete);
  }
  fetch.body[4]^=1;
  auto bad=transfer(fetch);assert(!bad.retired && service.receptions[0].object.complete);
  fetch.body[4]^=1;
  auto next=transfer(fetch);
  assert(next.retired && next.retiredClass==1 && next.retiredNode==0 && next.retiredObject==first.object);
  assert(next.retiredTotal==1008 && next.retiredChecksum==assembled.checksum);
  assert(next.kind==2 && next.total==96 && next.object!=first.object);
  auto repeated=transfer(fetch);assert(repeated.retired && repeated.object==next.object && repeated.total==96);
  assembled={};assert(bodaqs_fragment_accept(&assembled,bytes,sizeof bytes,&next,1,&ack)==1);
  fetch=ack;fetch.kind=14;fetch.body[2]=1;fetch.body[3]=0;
  auto empty=transfer(fetch);assert(empty.kind==0 && empty.retired && empty.retiredObject==next.object);
  auto replay=transfer(fetch);assert(replay.kind==0 && replay.retired && replay.retiredObject==next.object);
  service.receptions[0].next_id[0]=UINT32_MAX-1;
  for(unsigned i=0;i<13;++i) {
    uint8_t p[64]={};p[0]=66+i*5;p[2]=1;p[3]=5;
    assert(bodaqs_master_service_receive_can(&service,0,1,0x100,p,64,0,200+i,200+i));
  }
  poll.object=0;poll.index=0;
  auto last=transfer(poll,300);assert(last.object==UINT32_MAX);
  assembled={};
  for(unsigned i=0;i<5;++i) {
    poll.object=last.object;poll.index=i;
    const auto part=transfer(poll,300);
    assert(bodaqs_fragment_accept(&assembled,bytes,sizeof bytes,&part,1,&ack)==(i==4?1:0));
  }
  packet[0]=131;
  assert(bodaqs_master_service_receive_can(&service,0,1,0x100,packet,16,0,300,300));
  fetch=ack;fetch.kind=14;fetch.body[2]=1;
  auto exhausted=transfer(fetch,400);
  assert(exhausted.retired && exhausted.retiredObject==UINT32_MAX && exhausted.kind==7 && exhausted.body[1]==14);
  auto repeatedLast=transfer(fetch,400);
  assert(repeatedLast.retired && repeatedLast.retiredObject==UINT32_MAX);
  assert(service.receptions[0].next_id[0]==UINT32_MAX && service.receptions[0].count==1);
  uint8_t wire[256];assert(bodaqs_measurement_encode(&next,wire,sizeof wire));
  FILE* out=std::fopen(argv[1],"wb");assert(out);assert(std::fwrite(wire,1,256,out)==256);std::fclose(out);
  wire[235]^=1;BodaqsMeasurementSlot decoded={};assert(!bodaqs_measurement_decode(wire,256,&decoded));
  assert(!bodaqs_measurement_decode(wire,64,&decoded));
  assert(bodaqs_measurement_encode(&next,wire,sizeof wire));wire[239]=1;
  bodaqs_measurement_put(wire+252,bodaqs_measurement_crc(wire,252),4);
  assert(!bodaqs_measurement_decode(wire,256,&decoded));
  // A source START boundary supplies identity without a timing-model anchor.
  // A long low16 jump remains raw data for offline bounds, not a guessed high word.
  bodaqs_master_service_init(&service,&identity);bodaqs_control_exchange_init(&service.control,99);
  service.measurement.mode.phase=2;service.measurement.mode.context=9;service.measurement.mode.recording=77;
  service.discovery[0].flags=1;service.discovery[0].boot_id=17;
  service.acquisition_record[0]=77;service.acquisition_boot[0]=17;
  uint8_t start[64]={1,0x25,1,0,0,0,56,0,17};start[13]=1;start[14]=2;start[54]=1;start[55]=1;
  assert(bodaqs_master_service_receive_can(&service,0,2,0x90,start,64,0,10,1));
  uint8_t raw[16]={0xff,0xff,1,1};
  assert(bodaqs_master_service_receive_can(&service,0,1,0x100,raw,16,0,20,2));
  puts("versioned real 256-byte variable/empty ACK-fetch retirement passed");
}
