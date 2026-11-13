#include "RemoteImuStream.h"
#include <cassert>
#include <cstring>
static void put(uint8_t* p,uint32_t v) { BdqV2Format::putU32(p,v); }
static void origin(RemoteImuStream& s,unsigned sequence,unsigned id) {
  uint8_t m[64]={1,0x24,1,0,0,0,56,0,7};
  m[13]=1;m[14]=1;m[20]=1;m[24]=1;m[40]=1;m[42]=1;
  put(m+16,id);put(m+28,sequence);put(m+32,1000+sequence*300);
  put(m+36,300);put(m+44,500);put(m+52,150000);
  assert(s.accept(0x90,m,64,0,0,2000000)==RemoteImuStream::Accepted);
  uint8_t a[32]={1,0x22,1,0,0,0,20,0,0,1,1};
  put(a+12,sequence);put(a+16,1000+sequence*300);put(a+20,300);a[24]=1;
  assert(s.accept(0x90,a,32,0,0,2000000)==RemoteImuStream::Accepted);
}
int main() {
  RemoteImuStream s;RemoteImuBinding binding;binding.boot=7;
  assert(s.configure(binding,2,3));
  uint8_t b[64]={1,0x25,1,0,0,0,56,0,7};b[13]=1;b[14]=2;b[54]=0x60;
  assert(s.accept(0x90,b,64,0,0,2000000)==RemoteImuStream::Accepted);
  uint8_t p[64]={0,0,1,5};
  for(unsigned seq=0;seq<8195;seq+=5) {
    if(seq%100==0) {
      origin(s,seq,seq/100+1);
      // Persist definitions while samples remain queued through many model
      // retirements; only expanded bytes/evidence serials keep references.
      auto source=s.evidenceSource();uint8_t definition[224];
      while(source.pendingRecords(source.context)) assert(source.popRecord(source.context,definition,sizeof definition));
      source.chunkWritten(source.context);
    }
    BdqV2Format::putU16(p,seq);
    // The last complete batch is dropped; the immutable 8190 old rows remain.
    assert(s.accept(0x100,p,64,0,0,2000000)==RemoteImuStream::Accepted);
  }
  assert(!s.failed());
  auto ev=s.evidenceSource(),data=s.sampleSource();uint8_t record[224];bool loss=false;
  while(ev.pendingRecords(ev.context)) {
    assert(ev.popRecord(ev.context,record,sizeof record));
    if(record[12]==7) {
      assert(record[168]==8 && BdqV2Format::getU32(record+148)==5);
      assert(BdqV2Format::getU32(record+160)==8190 && BdqV2Format::getU32(record+164)==8194);
      assert(record[184]==0);loss=true;
    }
  }
  ev.chunkWritten(ev.context);
  assert(loss);
  for(unsigned seq=0;seq<5;++seq) {
    assert(data.popRecord(data.context,record,sizeof record));
    assert(BdqV2Format::getU32(record)==seq);
    assert(BdqV2Format::getU32(record+4)==1000+300*seq);
  }
  origin(s,8195,83);BdqV2Format::putU16(p,8195);
  assert(s.accept(0x100,p,64,0,0,2100000)==RemoteImuStream::Accepted);
  while(ev.pendingRecords(ev.context)) assert(ev.popRecord(ev.context,record,sizeof record));
  ev.chunkWritten(ev.context);
  for(unsigned seq=5;seq<8190;++seq) {
    assert(data.popRecord(data.context,record,sizeof record));
    assert(BdqV2Format::getU32(record)==seq);
  }
  assert(data.popRecord(data.context,record,sizeof record));
  assert(BdqV2Format::getU32(record)==8195 && (record[8]&3)==3);
  assert(s.acceptManagementLoss(1,9,6,15,2500000)==RemoteImuStream::Accepted);
  assert(s.acceptManagementLoss(1,9,6,15,2500001)==RemoteImuStream::Accepted);
  assert(s.acceptManagementLoss(1,9,6,20,2600000)==RemoteImuStream::Accepted);
  auto losses=s.evidenceSource();unsigned managementEvents=0;uint32_t managementTotal=0;
  while(losses.pendingRecords(losses.context)) {
    uint8_t row[224];assert(losses.popRecord(losses.context,row,sizeof row));
    if(row[168]==6) {
      ++managementEvents;managementTotal+=BdqV2Format::getU32(row+148);
      assert(row[184]==0 && BdqV2Format::getU32(row+76)==0 && BdqV2Format::getU32(row+80)==0);
    }
  }
  assert(managementEvents==2 && managementTotal==20);
  losses.chunkWritten(losses.context);
  // Periodic evidence cannot occupy the slots reserved for interpretation.
  s.release();assert(s.configure(binding,2,3));
  for(unsigned i=0;i<524;++i) assert(s.acceptSharedSync(i,1000*i,1,3000000)==RemoteImuStream::Accepted);
  assert(!s.failed());
  assert(s.finish(3200000));
  ev=s.evidenceSource();unsigned evidenceLost=0;
  while(ev.pendingRecords(ev.context)) {
    assert(ev.popRecord(ev.context,record,sizeof record));
    if(record[168]==9) {
      evidenceLost+=BdqV2Format::getU32(record+152);
      assert(!(BdqV2Format::getU32(record+16)&(1u<<16)));
    }
  }
  assert(evidenceLost==20);
  ev.chunkWritten(ev.context);
  assert(s.accept(0x90,b,64,0,0,3300000)==RemoteImuStream::Accepted);
  b[14]=3;unsigned retained=1;
  while(s.accept(0x90,b,64,0,0,3300000)==RemoteImuStream::Accepted) ++retained;
  assert(s.failed() && retained==512);
  assert(s.failureSite()!=0);
  const auto firstSite=s.failureSite();
  assert(s.acceptManagementLoss(1,14,6,0,3400000)==RemoteImuStream::Invalid);
  assert(s.failureSite()==firstSite);
  assert(ev.pendingRecords(ev.context)==512); // essential exhaustion preserves every old record
  s.release();assert(s.configure(binding,2,3));
  assert(!s.failed() && s.failureSite()==0);
  assert(s.acceptManagementLoss(1,14,6,0,3500000)==RemoteImuStream::Accepted);
  assert(s.failed() && s.failureSite()!=0 && s.failureSite()!=firstSite);
  // A fatal notification carries no cumulative counter. Replaying it between
  // unchanged loss reports must not count the same missing readings twice.
  s.release();assert(s.configure(binding,2,3));
  assert(s.acceptManagementLoss(1,9,6,58934,3600000)==RemoteImuStream::Accepted);
  assert(s.acceptManagementLoss(1,14,6,0,3600001)==RemoteImuStream::Accepted);
  assert(s.acceptManagementLoss(1,9,6,58934,3600002)==RemoteImuStream::Accepted);
  assert(s.acceptManagementLoss(1,9,6,58939,3600003)==RemoteImuStream::Accepted);
  losses=s.evidenceSource();managementTotal=0;
  while(losses.pendingRecords(losses.context)) {
    uint8_t row[224];assert(losses.popRecord(losses.context,row,sizeof row));
    managementTotal+=BdqV2Format::getU32(row+148);
  }
  assert(managementTotal==58939 && s.failed());
}
