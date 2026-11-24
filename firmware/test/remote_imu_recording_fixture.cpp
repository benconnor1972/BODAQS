#include "RemoteImuStream.h"
#include "BdqV2StreamQueue.h"
#include "BdqV2Writer.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>

static void feed(RemoteImuStream& stream) {
  // Independently specified begin-source boundary, model and matching anchor.
  uint8_t boundary[64]={1,0x25,1,0,0,0,56,0,7};
  boundary[13]=1; boundary[14]=2; boundary[16]=1;
  boundary[20]=1; boundary[24]=1; boundary[54]=0x61; boundary[55]=1;
  assert(stream.accept(0x90,boundary,64,50,1,100)==RemoteImuStream::Accepted);
  uint8_t model[64]={1,0x24,1,0,0,0,56,0,7};
  model[13]=1; model[14]=1; model[16]=1; model[20]=1; model[24]=1;
  model[32]=0xe8; model[33]=3; // anchor1000
  model[36]=0x2c; model[37]=1; model[40]=1; model[42]=1;
  model[44]=0xf4; model[45]=1; model[52]=0xf0; model[53]=0x49; model[54]=2;
  assert(stream.accept(0x90,model,64,51,2,101)==RemoteImuStream::Accepted);
  uint8_t anchor[32]={1,0x22,1,0,0,0,20,0,0,1,1};
  anchor[16]=0xe8;anchor[17]=3;anchor[20]=0x2c;anchor[21]=1;anchor[24]=1;
  assert(stream.accept(0x90,anchor,32,52,3,102)==RemoteImuStream::Accepted);
  uint8_t compact[16]={0,0,1,1,0xff,0xff,2,0,3,0,4,0,5,0,6,0};
  assert(stream.accept(0x100,compact,16,53,4,103)==RemoteImuStream::Accepted);
}

class FileSink final : public BdqV2ByteSink {
public:
  explicit FileSink(const char* path) : file_(std::fopen(path,"wb")) { assert(file_); }
  ~FileSink() { std::fclose(file_); }
  bool write(const uint8_t* bytes,size_t size) override { return std::fwrite(bytes,1,size,file_)==size; }
  bool flush() override { return std::fflush(file_)==0; }
private:
  std::FILE* file_;
};

int main(int argc,char** argv) {
  RemoteImuStream stream;
  RemoteImuBinding binding;
  binding.node=0; binding.boot=7; binding.uid=123;
  binding.masterBoot=456;binding.session=789;binding.recording=100;binding.context=999;
  std::strcpy(binding.sensorId,"remote_imu");
  std::strcpy(binding.mountPoint,"frame");std::strcpy(binding.calibrationRef,"fixture");
  assert(stream.configure(binding,2,3));
  feed(stream);
  auto sample=stream.sampleSource(); auto evidence=stream.evidenceSource();
  assert(sample.pendingRecords(sample.context)==0); // evidence pending on SD
  uint8_t bytes[224];
  while(evidence.pendingRecords(evidence.context)) assert(evidence.popRecord(evidence.context,bytes,sizeof bytes));
  assert(sample.pendingRecords(sample.context)==0); // popping is not persistence
  evidence.chunkWritten(evidence.context);
  assert(sample.pendingRecords(sample.context)==1);
  assert(sample.popRecord(sample.context,bytes,sizeof bytes));
  const uint8_t expected[28]={0,0,0,0,0xe8,3,0,0,25,0,0,0,1,0,0,0,0xff,0xff,2,0,3,0,4,0,5,0,6,0};
  assert(std::memcmp(bytes,expected,28)==0);
  // Same wire sequence cannot silently be reused in one source segment.
  uint8_t compact[16]={0,0,1,1,0xff,0xff,2,0,3,0,4,0,5,0,6,0};
  assert(stream.accept(0x100,compact,16,54,5,104)==RemoteImuStream::Invalid);
  if(argc<2) return 0;

  // A separate run goes through the actual catalog and writer, not queue-pop
  // simulation. Register samples first to exercise the persistence gate.
  assert(stream.configure(binding,2,3));
  feed(stream);
  uint8_t snapshot[64]={1,0x23,1,0,0,0,56,0,7};
  snapshot[13]=1;snapshot[14]=0x11;snapshot[15]=1;snapshot[16]=9;
  snapshot[24]=1;snapshot[28]=1;snapshot[32]=25;
  snapshot[36]=0xe8;snapshot[37]=3;snapshot[40]=40;
  snapshot[44]=2;snapshot[48]=0x84;snapshot[49]=3;snapshot[52]=1;
  snapshot[56]=1;snapshot[57]=2;snapshot[58]=3;snapshot[59]=0xff;snapshot[60]=1;
  assert(stream.accept(0x90,snapshot,64,54,0x100000005ULL,104)==RemoteImuStream::Accepted);
  uint8_t capture[24]={1,0x21,1,0,2,0,16,0,2,0,0,0,0x84,3,0,0,7,0,0,0,1,0,0,0};
  assert(stream.accept(0x90,capture,24,55,0x100000006ULL,105)==RemoteImuStream::Accepted);
  assert(stream.acceptSharedSync(2,50000,1,106)==RemoteImuStream::Accepted);
  assert(stream.acceptBridge(42,50100,1,0x100000010ULL,0x100000042ULL,107)==RemoteImuStream::Accepted);
  assert(stream.acceptMissingBridge(43,108)==RemoteImuStream::Accepted);
  BdqV2StreamQueue<16,4,2> primary(1,uint64_t{1}<<32);
  const uint8_t primaryRecord[16]={0,0,0,0,90,0,0,0,0,0,0,0,20,0,0,0};
  assert(primary.enqueueRecord(primaryRecord,sizeof primaryRecord));
  const BdqV2CatalogChannel primaryChannels[]={
    {"sequence","sequence","count","uint32",0,"diagnostic"},
    {"native_tick","time","us","uint32",4,"time"},
    {"status_flags","status","bitfield","uint16",8,"diagnostic"},
    {"suspension_raw","raw","count","int16",12,"signal"}
  };
  const BdqV2CatalogStatusFlag primaryFlags[]={{"discontinuity_before",1}};
  BdqV2StreamDescriptor descriptors[3]={stream.descriptor(false),stream.descriptor(true),{}};
  auto& pd=descriptors[2];pd.source=primary.source();pd.channels=primaryChannels;pd.channelCount=4;
  std::strcpy(pd.streamKey,"primary");std::strcpy(pd.transport,"local");
  std::strcpy(pd.clockId,"logger_monotonic");std::strcpy(pd.clockRelation,"logger_monotonic");
  pd.nominalSampleRateNumeratorHz=200;
  pd.statusFlags=primaryFlags;pd.statusFlagCount=1;
  const size_t catalogSize=BdqV2Catalog::measure("fixture_logger",descriptors,3);
  assert(catalogSize);
  std::vector<char> catalog(catalogSize+1);size_t catalogLength=0;
  assert(BdqV2Catalog::write("fixture_logger",descriptors,3,catalog.data(),catalog.size(),catalogLength));
  const char metadata[]=R"({"format":"bdq.v2","format_name":"BDQLOG v2","recording_id":"fixture","device_id":"fixture_logger","firmware_name":"BODAQS","firmware_version":"169-host-fixture","hardware_version":"host","created_unix_us":0,"timezone":"Australia/Perth","log_format":"bodaqs_multi_stream_binary","native_stream_contract":"bodaqs.native_stream.v1","stream_count":3,"logger_monotonic_clock":{"clock_id":"logger_monotonic","unit":"us","nondecreasing":true}})";
  FileSink sink(argv[1]);uint8_t workspace[2048];BdqV2Writer writer;
  for(const auto& descriptor:descriptors) assert(writer.addStream(descriptor.source));
  assert(writer.begin(sink,workspace,sizeof workspace,0,metadata,sizeof metadata-1,catalog.data(),catalogLength));
  assert(writer.end("{}",2));
  assert(!writer.failed());assert(stream.empty());
}
