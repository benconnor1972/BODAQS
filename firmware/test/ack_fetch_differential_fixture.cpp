#include "bodaqs_master_service.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <initializer_list>

static BodaqsMasterService seed, current;
static unsigned cases;
static void execute(FILE* trace,const BodaqsMeasurementSlot& request,unsigned now) {
  uint8_t tx[256],rx[256];
  assert(bodaqs_measurement_encode(&request,tx,256));
  const auto result=bodaqs_master_service_process_transfer(&current,tx,256,now,rx);
  assert(std::fwrite(&result,sizeof result,1,trace)==1);
  assert(std::fwrite(rx,1,sizeof rx,trace)==sizeof rx);
  assert(std::fwrite(&current,1,sizeof current,trace)==sizeof current);
  ++cases;
}
static void initialize(unsigned cls,unsigned node,bool exhausted) {
  bodaqs_master_service_init(&seed,nullptr);
  bodaqs_control_exchange_init(&seed.control,99);
  seed.measurement.mode.boot=99;seed.measurement.mode.session=1;
  seed.measurement.mode.recording=77;seed.measurement.mode.context=9;seed.measurement.mode.phase=2;
  BodaqsMeasurementSlot query={};query.context=9;query.node=255;
  uint8_t tx[256],rx[256];assert(bodaqs_measurement_encode(&query,tx,256));
  assert(bodaqs_master_service_process_transfer(&seed,tx,256,100,rx)==BODAQS_MASTER_SLOT_PROCESSED);
  const uint32_t object=exhausted?UINT32_MAX:41;
  uint8_t* bytes;BodaqsFragmentState* state;
  if(cls<=2) {
    auto& batch=seed.receptions[node];batch.cls=cls;batch.count=1;
    batch.started_ms=10;batch.next_id[cls-1]=object;
    bytes=batch.bytes;state=&batch.object;
    bytes[0]=1;bytes[2]=cls;bytes[3]=node;bytes[12]=1;
    // A successor queued behind the immutable head exercises advancement and sealing.
    auto& queue=seed.ingress[node];queue.count=1;
    auto& record=queue.records[0];record.cls=cls;record.boot=17;record.received_ms=20;
    record.bytes[0]=0;record.bytes[1]=1;record.bytes[12]=1;record.bytes[15]=5;
  } else if(cls<=4) {
    auto& lane=seed.lanes[cls-3][node];bytes=lane.outgoing;state=&lane.tx;
    lane.next_id=object;
  } else {bytes=seed.master_evidence_bytes;state=&seed.master_evidence;seed.master_evidence_next_id=object;}
  assert(bodaqs_fragment_seal(state,bytes,cls<=2?1024:cls<=4?68:1024,9,object,node,cls,1,cls<=2?92:cls<=4?64:24));
}
static BodaqsMeasurementSlot request(unsigned cls,unsigned node) {
  BodaqsMeasurementSlot ack={};
  const auto& state=cls<=2?seed.receptions[node].object:cls<=4?seed.lanes[cls-3][node].tx:seed.master_evidence;
  bodaqs_fragment_ack(&state,1,&ack);ack.kind=14;ack.body[2]=cls;ack.body[3]=node;
  return ack;
}
int main(int argc,char** argv) {
  assert(argc==2);FILE* trace=std::fopen(argv[1],"wb");assert(trace);
  for(unsigned cls=1;cls<=5;++cls) for(unsigned lane=0;lane<(cls==5?1:4);++lane)
    for(unsigned exhausted=0;exhausted<2;++exhausted) {
      const unsigned node=cls==5?255:lane;
      initialize(cls,node,exhausted);const auto good=request(cls,node);
      // Single-byte mutations cover the complete decoded request, including reserved tails.
      for(unsigned offset=0;offset<236;++offset) for(unsigned value:{1u,255u}) {
        uint8_t wire[256];assert(bodaqs_measurement_encode(&good,wire,256));wire[offset]^=value;
        bodaqs_measurement_put(wire+252,bodaqs_measurement_crc(wire,252),4);
        BodaqsMeasurementSlot decoded={};
        if(!bodaqs_measurement_decode(wire,256,&decoded)) continue;
        current=seed;execute(trace,decoded,100);
      }
      for(unsigned fetchClass=1;fetchClass<=5;++fetchClass) for(unsigned index=0;index<5;++index)
        for(unsigned disposition:{1u,2u,3u}) {
          auto r=good;r.body[1]=disposition;r.body[2]=fetchClass;r.body[3]=fetchClass==5?255:lane;
          r.body[12]=index;bodaqs_measurement_put(r.body+8,index?41:0,4);
          current=seed;execute(trace,r,100);execute(trace,r,101);execute(trace,r,200);
        }
      current=seed;
      execute(trace,good,100);execute(trace,good,101); // exact ACK replay after actual retirement
      auto late=good;late.object=40;execute(trace,late,102);
      auto plain=good;plain.kind=5;plain.body[2]=plain.body[3]=0;execute(trace,plain,103);
    }
  assert(std::fclose(trace)==0);
  std::printf("ACK-fetch differential corpus: %u requests, state bytes=%zu\n",cases,sizeof current);
}
