#include "RemoteImuStream.h"
#include <cassert>
#include <cstring>
int main() {
  RemoteImuStream stream;
  RemoteImuBinding binding;
  binding.node=1; binding.boot=7;
  binding.effective[12]=16; // Sensitivities known/current, independent rational constants.
  binding.effective[72]=122;
  binding.effective[76]=0x48;binding.effective[77]=0xe8;binding.effective[78]=1; //125000
  binding.effective[80]=7;binding.effective[84]=100;
  assert(stream.configure(binding,2,3));
  uint8_t boundary[64]={1,0x25,1,0,0,0,56,0,7};
  boundary[13]=1;boundary[14]=2;boundary[16]=1;boundary[20]=1;boundary[24]=1;
  boundary[54]=0x61;boundary[55]=1;
  assert(stream.accept(0x91,boundary,64,50,1,100)==RemoteImuStream::Accepted);
  uint8_t anchor[32]={1,0x22,1,0,0,0,20,0,0,1,1};
  anchor[16]=0xe8;anchor[17]=3;anchor[20]=0x2c;anchor[21]=1;anchor[24]=1;
  // This head must be retained in RAM and acknowledged, so a later model can arrive.
  assert(stream.accept(0x91,anchor,32,51,2,101)==RemoteImuStream::Accepted);
  uint8_t model[64]={1,0x24,1,0,0,0,56,0,7};
  model[13]=1;model[14]=1;model[16]=1;model[20]=1;model[24]=1;
  model[32]=0xe8;model[33]=3;model[36]=0x2c;model[37]=1;model[40]=1;model[42]=1;
  model[44]=0xf4;model[45]=1;model[52]=0xf0;model[53]=0x49;model[54]=2;
  assert(stream.accept(0x91,model,64,52,3,102)==RemoteImuStream::Accepted);
  assert(stream.accept(0x91,model,64,52,4,102)==RemoteImuStream::Accepted); // canonical duplicate
  uint8_t compact[16]={0,0,1,0x21,0xff,0xff,2,0,3,0,4,0,5,0,6,0};
  assert(stream.accept(0x108,compact,16,53,5,103)==RemoteImuStream::Accepted);
  auto evidence=stream.evidenceSource();auto sample=stream.sampleSource();uint8_t record[224];
  assert(sample.pendingRecords(sample.context)==0);
  while(evidence.pendingRecords(evidence.context)) assert(evidence.popRecord(evidence.context,record,sizeof record));
  evidence.chunkWritten(evidence.context);
  assert(sample.popRecord(sample.context,record,sizeof record));
  assert(record[8]==27); // Estimated+degraded+discontinuity+CAN queue loss; not source recovery.
  const char* provenance=stream.descriptor(false).acquisitionDetailsJson;
  assert(std::strstr(provenance,"\"accel_ug_per_count\":976"));
  assert(std::strstr(provenance,"\"gyro_udps_per_count\":70000"));
  assert(std::strstr(provenance,"stopped_configuration_at_admission"));
  assert(!std::strstr(provenance,"\"verification_phase\":3"));
  // A conflicting definition cannot silently replace an already used origin.
  model[32]^=1;
  assert(stream.accept(0x91,model,64,54,6,104)==RemoteImuStream::Invalid);
}
