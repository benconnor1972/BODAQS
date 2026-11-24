#include "RemoteImuStream.h"
#include "../can-fd/common/protocol/bodaqs_fragment_transport.h"
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>

static void start(RemoteImuStream& stream,unsigned node) {
  RemoteImuBinding b;b.node=node;b.boot=7+node;b.context=9;
  b.compactPackets=b.sampleUnits=true;
  assert(stream.configure(b,2*node+1,2*node+2));
  uint8_t boundary[64]={1,0x25,1,0,0,0,56};
  bodaqs_measurement_put(boundary+8,b.boot,4);
  boundary[13]=1;boundary[14]=2;boundary[16]=1;boundary[20]=1;boundary[24]=1;
  boundary[54]=0x61;boundary[55]=1;
  assert(stream.accept(0x90+node,boundary,64,50,1,100)==RemoteImuStream::Accepted);
}
static void unit(unsigned node,unsigned object,uint8_t* body) {
  std::memset(body,0,468);
  bodaqs_measurement_put(body,2,2);body[2]=1;body[3]=node;
  bodaqs_measurement_put(body+4,7+node,4);bodaqs_measurement_put(body+12,7,2);
  for(unsigned packet=0;packet<7;++packet) {
    auto* p=body+16+64*packet;
    bodaqs_measurement_put(p,(object-1)*35+packet*5,2);p[2]=1;p[3]=5;
    for(unsigned j=0;j<5;++j) bodaqs_measurement_put(p+4+12*j,node*1000+object,2);
  }
  BodaqsFragmentState state={};
  assert(bodaqs_fragment_seal(&state,body,468,9,object,node,1,1,464));
}
static void check(const uint8_t* record,unsigned node,unsigned object) {
  assert(BdqV2Format::getU32(record)==object-1);
  assert(BdqV2Format::getU32(record+32)==object&&record[36]==node);
  assert(BdqV2Format::getU16(record+40)==468);
  uint8_t expected[468];unit(node,object,expected);
  assert(!std::memcmp(record+44,expected,sizeof expected));
}
int main(int argc,char** argv) {
  assert(argc==2);const unsigned capacity=std::strtoul(argv[1],nullptr,10);
  RemoteImuStream streams[4];
  for(unsigned node=0;node<4;++node) {
    start(streams[node],node);
    assert(streams[node].queueState().sampleCapacity==capacity);
    assert(streams[node].queueState().evidenceCapacity==512);
    for(unsigned i=1;i<=capacity;++i) {
      uint8_t body[468];unit(node,i,body);
      assert(streams[node].acceptSampleUnit(9,i,body,sizeof body,200+i)==RemoteImuStream::Accepted);
    }
    uint8_t body[468];unit(node,capacity,body);
    assert(streams[node].acceptSampleUnit(9,capacity,body,sizeof body,1000)==RemoteImuStream::Accepted);
    unit(node,capacity+1,body);
    assert(streams[node].acceptSampleUnit(9,capacity+1,body,sizeof body,1001)==RemoteImuStream::Blocked);
    assert(streams[node].queueState().samples==capacity);
    assert(streams[node].queueState().samplesAccepted==35*capacity);
  }
  for(unsigned node=0;node<4;++node) {
    auto sample=streams[node].sampleSource();uint8_t record[516];
    const unsigned drained=capacity/2+1;
    for(unsigned i=1;i<=drained;++i) {
      assert(sample.popRecord(sample.context,record,sizeof record));check(record,node,i);
    }
    for(unsigned i=capacity+1;i<=capacity+drained;++i) {
      uint8_t body[468];unit(node,i,body);
      assert(streams[node].acceptSampleUnit(9,i,body,sizeof body,2000+i)==RemoteImuStream::Accepted);
    }
    assert(streams[node].queueState().samples==capacity);
    for(unsigned i=drained+1;i<=capacity+drained;++i) {
      assert(sample.popRecord(sample.context,record,sizeof record));check(record,node,i);
    }
    assert(!sample.popRecord(sample.context,record,sizeof record));
    streams[node].release();
  }
  assert(DynamicSpscQueueDetail::liveAllocations==0);
  for(int fail=0;fail<5;++fail) {
    DynamicSpscQueueDetail::allocationsBeforeFailure=fail;
    RemoteImuBinding b;b.boot=7;b.context=9;b.compactPackets=b.sampleUnits=true;
    RemoteImuStream stream;assert(!stream.configure(b,1,2));
    assert(DynamicSpscQueueDetail::liveAllocations==0);
  }
  DynamicSpscQueueDetail::allocationsBeforeFailure=-1;
  start(streams[0],0);assert(streams[0].queueState().samples==0);streams[0].release();
  assert(DynamicSpscQueueDetail::liveAllocations==0);
  std::printf("capacity=%u bytes_per_node=%zu\n",capacity,RemoteImuStream::allocatedBufferBytes(true,true));
}
