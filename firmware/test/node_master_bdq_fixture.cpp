#include "RemoteImuStream.h"
#include "BdqV2StreamQueue.h"
#include "BdqV2Writer.h"
#include "bodaqs_master_service.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>
static BodaqsMasterService master;
static RemoteImuStream stream;
static bool duplicatePacket=false;
static BodaqsMeasurementSlot exchange(const BodaqsMeasurementSlot& request,unsigned now) {
  uint8_t wire[64],response[84];BodaqsMeasurementSlot reply={};
  assert(bodaqs_measurement_encode(&request,wire,64));
  assert(bodaqs_master_service_process_transfer(&master,wire,64,now,response)==0);
  assert(bodaqs_measurement_decode(response,64,&reply));return reply;
}
static bool drain(unsigned cls,unsigned now) {
  BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=9;poll.node=0;poll.body[0]=cls;
  auto first=exchange(poll,now);if(first.kind==0) return false;
  assert(first.kind==(cls==1?2:3));
  uint8_t bytes[1024]={};BodaqsFragmentState assembly={};BodaqsMeasurementSlot ack={};
  for(unsigned i=0;i<(first.total+39u)/40u;++i) {
    poll.object=first.object;poll.index=i;
    const auto fragment=exchange(poll,now);
    const int result=bodaqs_fragment_accept(&assembly,bytes,sizeof bytes,&fragment,1,&ack);
    assert(result==(i+1==(first.total+39u)/40u?1:0));
  }
  const unsigned count=BdqV2Format::getU16(bytes+12);
  for(unsigned i=0;i<count;++i) {
    const uint8_t* r=bytes+16+76*i;
    const uint64_t order=(uint64_t(BdqV2Format::getU32(bytes+8))<<32)|BdqV2Format::getU32(r+8);
    assert(stream.accept(BdqV2Format::getU16(r),r+12,r[2],BdqV2Format::getU32(r+4),order,5000+now)
      ==RemoteImuStream::Accepted);
    if(duplicatePacket && BdqV2Format::getU16(r)==0x100) {
      // Replay at the public recording seam, after actual master reassembly.
      // This tests persistence/decode deduplication, not transport RAM-ACK logic.
      assert(stream.accept(0x100,r+12,r[2],BdqV2Format::getU32(r+4),order,5000+now)==RemoteImuStream::Accepted);
      duplicatePacket=false;
    }
  }
  (void)exchange(ack,now);return true;
}
class FileSink final:public BdqV2ByteSink {
  FILE* file;
public:
  explicit FileSink(const char* path):file(std::fopen(path,"wb")) {assert(file);}
  ~FileSink(){std::fclose(file);}
  bool write(const uint8_t* p,size_t n) override{return std::fwrite(p,1,n,file)==n;}
  bool flush() override{return std::fflush(file)==0;}
};
int main(int argc,char** argv) {
  assert(argc>=3 && argc<=5);
  duplicatePacket=argc==5;
  BodaqsMasterIdentity identity={};bodaqs_master_service_init(&master,&identity);
  bodaqs_control_exchange_init(&master.control,99);
  master.measurement.mode.phase=2;master.measurement.mode.context=9;master.measurement.mode.recording=77;
  master.discovery[0].flags=1;master.discovery[0].boot_id=17;
  master.acquisition_record[0]=77;master.acquisition_boot[0]=17;
  RemoteImuBinding binding;binding.boot=17;binding.masterBoot=99;binding.session=1;binding.recording=77;binding.context=9;
  binding.compactPackets=argc>=4;
  assert(stream.configure(binding,2,3));
  std::ifstream input(argv[1]);assert(input);
  unsigned id,length,now=0;std::string hex;
  while(input>>id>>length>>hex) {
    assert(length<=64 && hex.size()==length*2);uint8_t payload[64]={};
    for(unsigned i=0;i<length;++i) payload[i]=std::stoul(hex.substr(i*2,2),nullptr,16);
    assert(bodaqs_master_service_receive_can(&master,0,id==0x100?1:2,id,payload,length,0,1000+50*now,now));
    while(drain(2,now)||drain(1,now)) {}
    ++now;
  }
  while(drain(2,now+20)||drain(1,now+20)) {}
  BdqV2StreamQueue<16,4,2> primary(1,uint64_t{1}<<32);
  const uint8_t row[16]={0,0,0,0,90,0,0,0,0,0,0,0,20,0,0,0};assert(primary.enqueueRecord(row,16));
  const BdqV2CatalogChannel channels[]={
    {"sequence","sequence","count","uint32",0,"diagnostic"},
    {"native_tick","time","us","uint32",4,"time"},
    {"status_flags","status","bitfield","uint16",8,"diagnostic"},
    {"value","raw","count","int16",12,"signal"}};
  const BdqV2CatalogStatusFlag flags[]={{"discontinuity_before",1}};
  BdqV2StreamDescriptor descriptors[3]={stream.descriptor(false),stream.descriptor(true),{}};
  auto& pd=descriptors[2];pd.source=primary.source();pd.channels=channels;pd.channelCount=4;
  std::strcpy(pd.streamKey,"primary");std::strcpy(pd.transport,"local");std::strcpy(pd.clockId,"logger_monotonic");
  std::strcpy(pd.clockRelation,"logger_monotonic");pd.nominalSampleRateNumeratorHz=200;pd.statusFlags=flags;pd.statusFlagCount=1;
  const size_t size=BdqV2Catalog::measure("adapter_fixture",descriptors,3);assert(size);
  std::vector<char> catalog(size+1);size_t lengthOut=0;
  assert(BdqV2Catalog::write("adapter_fixture",descriptors,3,catalog.data(),catalog.size(),lengthOut));
  const char metadata[]=R"({"format":"bdq.v2","format_name":"BDQLOG v2","recording_id":"adapter_fixture","device_id":"adapter_fixture","firmware_name":"BODAQS","firmware_version":"169-host","hardware_version":"host","created_unix_us":0,"timezone":"Australia/Perth","log_format":"bodaqs_multi_stream_binary","native_stream_contract":"bodaqs.native_stream.v1","stream_count":3,"logger_monotonic_clock":{"clock_id":"logger_monotonic","unit":"us","nondecreasing":true}})";
  FileSink sink(argv[2]);uint8_t workspace[2048];BdqV2Writer writer;
  for(const auto& d:descriptors) assert(writer.addStream(d.source));
  assert(writer.begin(sink,workspace,sizeof workspace,0,metadata,sizeof metadata-1,catalog.data(),lengthOut));
  assert(writer.end("{}",2));assert(!writer.failed() && stream.empty());
}
