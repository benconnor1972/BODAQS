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
  uint8_t capture[24]={1,0x21,1,0,5,0,16,0,5,0,0,0,0x20,0x4e,0,0,7,0,0,0,1,0,0,0};
  assert(stream.accept(0x91,capture,24,30000,0x100000007ULL,200)==RemoteImuStream::Accepted);
  assert(evidence.popRecord(evidence.context,record,sizeof record));
  assert(record[12]==3 && record[14]==1 && BdqV2Format::getU32(record+68)==20000);
  assert(BdqV2Format::getU32(record+40)==1 && record[184]==0x21 && record[186]==24);
  assert(BdqV2Format::getU32(record+188)==1 && record[140]==1);
  assert(stream.acceptSharedSync(5,123456,9,201)==RemoteImuStream::Accepted);
  assert(evidence.popRecord(evidence.context,record,sizeof record));
  assert(record[12]==4 && BdqV2Format::getU32(record+40)==9);
  assert(BdqV2Format::getU32(record+16)==((1u<<3)|(1u<<8)|(1u<<22)));
  assert(BdqV2Format::getU32(record+64)==5 && BdqV2Format::getU32(record+72)==123456);
  assert(stream.acceptBridge(11,654321,9,0x100000002ULL,0x100000063ULL,202)==RemoteImuStream::Accepted);
  assert(evidence.popRecord(evidence.context,record,sizeof record));
  assert(record[12]==5 && BdqV2Format::getU32(record+144)==11);
  assert(BdqV2Format::getU64(record+120)==0x100000002ULL && BdqV2Format::getU64(record+128)==0x100000063ULL);
  assert(BdqV2Format::getU32(record+16)==((1u<<3)|(1u<<14)|(1u<<15)|(1u<<22)));
  assert(BdqV2Format::getU32(record+180)==0); // No invented physical uncertainty.
  assert(stream.acceptMissingBridge(12,203)==RemoteImuStream::Accepted);
  assert(evidence.popRecord(evidence.context,record,sizeof record));
  assert(record[12]==5 && BdqV2Format::getU32(record+144)==12 && record[140]==2);
  assert(BdqV2Format::getU32(record+16)==((1u<<15)|(1u<<22)));
  assert(BdqV2Format::getU32(record+40)==0 && BdqV2Format::getU64(record+120)==0);
  // A reception-clock fault degrades that observation; node sample timing survives.
  assert(stream.accept(0x91,capture,24,99999,0x100000008ULL,204,1)==RemoteImuStream::Accepted);
  assert(evidence.popRecord(evidence.context,record,sizeof record));
  assert(!(BdqV2Format::getU32(record+16)&(1u<<9)) && (BdqV2Format::getU32(record+16)&(1u<<10)));
  assert(BdqV2Format::getU32(record+76)==0 && BdqV2Format::getU32(record+180)==1);
  RemoteImuStream fullCatalog;
  RemoteImuBinding fullBinding=binding;
  fullBinding.uid=fullBinding.masterUid=fullBinding.masterBoot=fullBinding.session=fullBinding.recording=fullBinding.context=UINT64_MAX;
  fullBinding.orientationValid=true;
  fullBinding.mountingQuaternion[0]=0.316227766016838;
  fullBinding.mountingQuaternion[1]=0.447213595499958;
  fullBinding.mountingQuaternion[2]=0.547722557505166;
  fullBinding.mountingQuaternion[3]=0.632455532033676;
  assert(fullCatalog.configure(fullBinding,2,3));
  assert(std::strstr(fullCatalog.descriptor(false).acquisitionDetailsJson,"saved_mount_quaternion"));
  // A conflicting definition cannot silently replace an already used origin.
  model[32]^=1;
  assert(stream.accept(0x91,model,64,54,6,104)==RemoteImuStream::Invalid);
}
