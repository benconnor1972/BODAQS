#include "bodaqs_fragment_transport.h"
#include "bodaqs_master_service.h"
#include <cassert>
#include <cstdio>
int main() {
 uint8_t data[1024]={}; BodaqsFragmentState tx={},rx={}; uint8_t accepted[1024]={};
 for(unsigned i=0;i<64;++i) data[i]=(uint8_t)i;
 assert(bodaqs_fragment_seal(&tx,data,sizeof data,9,1,0,3,1,64));
 assert(tx.total==68);
 assert(tx.checksum==0xf80a184bU); // Independent struct.pack + Python zlib vector.
 assert(data[64]==0x4b && data[65]==0x18 && data[66]==0x0a && data[67]==0xf8);
 BodaqsMeasurementSlot a={},b={},ack={};
 assert(bodaqs_fragment_emit(&tx,data,1,&b));
 assert(bodaqs_fragment_accept(&rx,accepted,sizeof accepted,&b,1,&ack)==0);
 assert(bodaqs_fragment_emit(&tx,data,0,&a));
 assert(bodaqs_fragment_accept(&rx,accepted,sizeof accepted,&a,1,&ack)==1);
 assert(ack.kind==5 && ack.body[1]==1 && rx.accepted==1);
 assert(bodaqs_fragment_accept(&rx,accepted,sizeof accepted,&a,1,&ack)==2);
 assert(ack.body[1]==2 && rx.accepted==1);
 a.body[0]^=1;
 assert(bodaqs_fragment_accept(&rx,accepted,sizeof accepted,&a,1,&ack)==-5);
 assert(!bodaqs_fragment_seal(&tx,data,sizeof data,9,0,0,3,1,64));
 BodaqsMasterService service={}; BodaqsMasterIdentity identity={};
 bodaqs_master_service_init(&service,&identity); bodaqs_control_exchange_init(&service.control,99);
 service.measurement.mode.phase=2;service.measurement.mode.context=9;
 for(unsigned n=0;n<4;++n) {service.discovery[n].flags=1;service.discovery[n].boot_id=5;}
 uint8_t payload[64]={1,2,3},wire[64],response[84];
 for(unsigned n=0;n<4;++n) assert(bodaqs_master_service_receive_can(&service,n,2,0x060+n,payload,64,0,1234,100));
 BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=9;poll.node=255;poll.body[0]=2;
 bodaqs_measurement_encode(&poll,wire,64);
 assert(bodaqs_master_service_process_transfer(&service,wire,64,119,response)==0);
 BodaqsMeasurementSlot got={};bodaqs_measurement_decode(response,64,&got); assert(got.kind==0);
 for(unsigned n=0;n<4;++n) {
  assert(bodaqs_master_service_process_transfer(&service,wire,64,120,response)==0);
  bodaqs_measurement_decode(response,64,&got);assert(got.kind==3 && got.node==n && got.total==96);
  assert(got.body[0]==1 && got.body[12]==1); // schema and reception count
 }
 assert(!bodaqs_master_service_receive_can(&service,0,2,0x060,payload,64,0,1235,121));
 assert(service.backpressure_frames==1);
 // Invalid logical CRC never publishes, and unknown context cannot change a partial assembly.
 BodaqsFragmentState damaged={}, mixed={};uint8_t damagedBytes[68]={},mixedBytes[68]={};
 a.body[0]^=1; // restore the literal vector
 auto bad=b;bad.body[24]^=1;
 assert(bodaqs_fragment_accept(&damaged,damagedBytes,68,&a,1,&ack)==0);
 assert(bodaqs_fragment_accept(&damaged,damagedBytes,68,&bad,1,&ack)==-3);
 assert(!damaged.complete && damaged.accepted==0);
 assert(bodaqs_fragment_accept(&mixed,mixedBytes,68,&a,1,&ack)==0);
 auto alien=b;alien.context=10;
 assert(bodaqs_fragment_accept(&mixed,mixedBytes,68,&alien,1,&ack)==-4);
 alien=b;alien.total=69;
 assert(bodaqs_fragment_accept(&mixed,mixedBytes,68,&alien,1,&ack)<0);
 assert(bodaqs_fragment_accept(&mixed,mixedBytes,68,&b,1,&ack)==1);
 // Lost ACKs retain the selected immutable master head across polls and incoming traffic.
 poll.node=0;bodaqs_measurement_encode(&poll,wire,64);
 bodaqs_master_service_process_transfer(&service,wire,64,200,response);
 BodaqsMeasurementSlot pinned={};bodaqs_measurement_decode(response,64,&pinned);
 assert(pinned.object==1 && pinned.total==96);
 assert(!bodaqs_master_service_receive_can(&service,0,2,0x060,payload,64,0,9999,201));
 bodaqs_master_service_process_transfer(&service,wire,64,220,response);
 bodaqs_measurement_decode(response,64,&got);
 assert(!memcmp(&pinned,&got,sizeof got));
 // Master-local evidence has separate storage and ACK state while node data remains pinned.
 uint8_t event[24]={1,0,1,0,1,0,0,0,1,0,0,0,1,0,0,0,42,0,0,0,1,0,0,0};
 assert(bodaqs_master_service_publish_evidence(&service,event,24));
 assert(!bodaqs_master_service_publish_evidence(&service,event,24));
 poll.node=255;poll.body[0]=5;bodaqs_measurement_encode(&poll,wire,64);
 bodaqs_master_service_process_transfer(&service,wire,64,221,response);
 bodaqs_measurement_decode(response,64,&got);assert(got.kind==13 && got.node==255 && got.total==28);
 // Stale IDs never insert again; higher IDs remain ordered by canonical class/direction.
 auto stale=a;stale.object=0;
 assert(bodaqs_fragment_accept(&mixed,mixedBytes,68,&stale,1,&ack)<0);
 // Ordinary and authorization classes cannot pin one another; STOP preempts renewal.
 auto submit=[&](uint8_t cls,uint32_t id,uint8_t opcode,uint32_t operation) {
  BodaqsControlWrapped request={};request.master_boot_id=99;request.node_address=0;
  request.record.opcode=opcode;request.record.endpoint=255;request.record.node_boot_id=5;
  request.record.operation=operation;request.record.session=1;
  uint8_t bytes[68]={};BodaqsFragmentState object={};
  assert(bodaqs_control_encode_wrapped(&request,bytes));
  assert(bodaqs_fragment_seal(&object,bytes,68,9,id,0,cls,0,64));
  for(uint8_t index=0;index<2;++index) {
   BodaqsMeasurementSlot fragment={};assert(bodaqs_fragment_emit(&object,bytes,index,&fragment));
   bodaqs_measurement_encode(&fragment,wire,64);
   assert(bodaqs_master_service_process_transfer(&service,wire,64,300,response)==0);
  }
  bodaqs_measurement_decode(response,64,&got);assert(got.kind==5);
 };
 submit(3,1,4,70);submit(4,1,0x26,80);
 assert(service.control.slots[0].state==1 && service.authorization.slots[0].state==1);
 submit(4,2,0x25,81);
 assert(service.authorization.slots[0].request.opcode==0x25);
 uint8_t address=255,can[64];uint16_t transaction;
 for(uint32_t now=400;now<=600;now+=100) {
  assert(bodaqs_master_service_control_transmit(&service,now,&address,&transaction,can));
  BodaqsControlRecord request={};uint16_t decoded;
  assert(bodaqs_control_decode_can(can,64,false,&decoded,&request));assert(request.opcode==0x25);
 }
 (void)bodaqs_master_service_control_transmit(&service,700,&address,&transaction,can);
 assert(service.authorization.slots[0].state==3); // bounded uncertain STOP
 assert(service.control.slots[0].request.opcode==4); // ordinary identity preserved
 // 1KiB and 26-slot physical bounds are checked independently of queue storage.
 BodaqsFragmentState tooLarge={};assert(!bodaqs_fragment_seal(&tooLarge,data,1024,9,2,0,3,0,1021));
 // Complete RAM ACK releases one selected batch; duplicate ACK is idempotent.
 BodaqsFragmentState reception={};uint8_t bytes[1024]={};
 poll.node=0;poll.body[0]=2;
 for(uint8_t index=0;index<3;++index) {
  poll.index=index;bodaqs_measurement_encode(&poll,wire,64);
  bodaqs_master_service_process_transfer(&service,wire,64,710,response);
  bodaqs_measurement_decode(response,64,&got);
  assert(bodaqs_fragment_accept(&reception,bytes,1024,&got,1,&ack)==(index==2?1:0));
 }
 assert(bytes[16]==0x60 && bytes[18]==64);
 assert(bodaqs_measurement_get(bytes+20,4)==1234 && bodaqs_measurement_get(bytes+24,4)==1);
 bodaqs_measurement_encode(&ack,wire,64);
 bodaqs_master_service_process_transfer(&service,wire,64,711,response);
 const auto acked=service.objects_acked;
 bodaqs_master_service_process_transfer(&service,wire,64,712,response);
 assert(service.objects_acked==acked);
 for(unsigned i=0;i<13;++i) assert(bodaqs_master_service_receive_can(&service,0,2,0x060,payload,64,0,2000+i,720));
 assert(!bodaqs_master_service_receive_can(&service,0,2,0x060,payload,64,0,3000,720));
 poll.index=25;bodaqs_measurement_encode(&poll,wire,64);
 bodaqs_master_service_process_transfer(&service,wire,64,721,response);
 bodaqs_measurement_decode(response,64,&got);
 assert(got.total==1008 && got.index==25 && bodaqs_measurement_zero(got.body+8,32));
 // Duplicate address is excluded even when it has a valid boot and prior anchor.
 service.discovery[1].flags=5;
 assert(!bodaqs_master_service_receive_can(&service,1,2,0x061,payload,64,0,3000,720));
 puts("fragment complete RAM acceptance and duplicate/conflict checks passed");
}
