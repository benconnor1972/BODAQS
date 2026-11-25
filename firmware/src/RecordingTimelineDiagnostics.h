#pragma once
#include <atomic>
#include <stddef.h>
#include <stdint.h>

#ifndef BODAQS_STORAGE_TIMELINE
#define BODAQS_STORAGE_TIMELINE 0
#endif
#if BODAQS_STORAGE_TIMELINE != 0 && BODAQS_STORAGE_TIMELINE != 1
#error "Storage timeline must be0or1"
#endif
#if BODAQS_STORAGE_TIMELINE
#if !BODAQS_RECORDING_PRESSURE_DIAGNOSTICS || !BODAQS_IMU_FLOW_DIAGNOSTICS
#error "Storage timeline requires recording pressure and retired FLOW snapshots"
#endif

// Each owner writes only its own bank. Publish the common clock origin once,
// before acquisition starts. Serialize only after matching producer retirement.
// Fixed20s bins cover12minutes, with explicit overflow (no silent ring overwrite).
// Entire operations belong to their start bin; service gaps to their end bin.
namespace RecordingTimelineDiagnostics {
constexpr uint32_t binUs=20000000,capacity=36,slowWriteUs=100000;
struct StorageBin {
  uint32_t writes=0,bytes=0,writeUs=0,writeMaxUs=0,slowWrites=0;
  uint32_t flushes=0,flushUs=0,flushMaxUs=0;
  uint32_t serviceCalls=0,serviceUs=0,nonIoServiceUs=0,serviceMaxUs=0;
  uint32_t primaryPeak=0,serviceGapMaxUs=0,serviceTimeInvalid=0;
};
struct AcquisitionBin {
  uint32_t services=0,serviceGapMaxUs=0,gapsOver10ms=0;
  uint32_t sampleCalls=0,sampleWaits=0,evidenceCalls=0,evidenceWaits=0;
  uint16_t samplePeak[4]={},evidencePeak[4]={};
  uint32_t sourceLossReports[4]={},evidenceLossReports[4]={};
};
struct StorageState {
  StorageBin bins[capacity];
  uint64_t ioUs=0;
  uint32_t originUs=0,used=0,overflow=0,lastEndUs=0,lastEventUs=0;
  bool initialized=false,frozen=false,haveService=false;
};
struct AcquisitionState {
  AcquisitionBin bins[capacity];
  uint64_t context=0;
  uint32_t originUs=0,used=0,overflow=0,lastServiceUs=0;
  bool haveService=false;
};
inline StorageState storage;
inline AcquisitionState acquisition;
inline std::atomic<uint32_t> publishedOriginUs{0};
static_assert(std::atomic<uint32_t>::is_always_lock_free,"Timeline clock publication must not lock");
static_assert(sizeof(storage)+sizeof(acquisition)+sizeof(publishedOriginUs)<=6000,"Bounded timeline RAM");
inline size_t reservedBytes(){return sizeof(storage)+sizeof(acquisition)+sizeof(publishedOriginUs);}
inline void resetStorage(uint32_t nowUs) {
  storage={};storage.originUs=storage.lastEventUs=nowUs;storage.initialized=true;
  publishedOriginUs.store(nowUs,std::memory_order_release);
}
inline void resetAcquisition(uint64_t context,uint32_t nowUs) {
  acquisition={};acquisition.context=context;
  acquisition.originUs=publishedOriginUs.load(std::memory_order_acquire);
  acquisition.lastServiceUs=nowUs;
}
template<class State> inline uint32_t index(State& state,uint32_t tick) {
  const uint32_t i=uint32_t(tick-state.originUs)/binUs;
  if(state.overflow || i>=capacity){if(state.overflow!=UINT32_MAX)++state.overflow;return capacity;}
  if(i+1>state.used)state.used=i+1;
  return i;
}
inline void maximum(uint32_t& field,uint32_t value){if(value>field)field=value;}
inline void storageOperation(uint8_t operation,uint32_t start,uint32_t duration,uint32_t bytes,uint16_t primary) {
  if(!storage.initialized || storage.frozen)return;
  storage.ioUs+=duration;
  storage.lastEventUs=start+duration;
  const auto i=index(storage,start);if(i==capacity)return;auto& b=storage.bins[i];
  maximum(b.primaryPeak,primary);
  if(operation==3){++b.writes;b.bytes+=bytes;b.writeUs+=duration;maximum(b.writeMaxUs,duration);if(duration>=slowWriteUs)++b.slowWrites;}
  else if(operation==4){++b.flushes;b.flushUs+=duration;maximum(b.flushMaxUs,duration);}
}
inline void storageService(uint32_t start,uint32_t duration,uint64_t ioBefore,uint16_t primary) {
  if(!storage.initialized || storage.frozen)return;
  const auto i=index(storage,start);if(i==capacity)return;auto& b=storage.bins[i];
  ++b.serviceCalls;b.serviceUs+=duration;maximum(b.serviceMaxUs,duration);maximum(b.primaryPeak,primary);
  const uint64_t nestedIo=storage.ioUs-ioBefore;
  if(nestedIo<=duration)b.nonIoServiceUs+=duration-uint32_t(nestedIo);
  else ++b.serviceTimeInvalid;
  if(storage.haveService)maximum(b.serviceGapMaxUs,uint32_t(start-storage.lastEndUs));
  storage.lastEndUs=start+duration;storage.haveService=true;
  storage.lastEventUs=storage.lastEndUs;
}
inline void service(uint32_t now) {
  const auto i=index(acquisition,now);if(i==capacity)return;auto& b=acquisition.bins[i];++b.services;
  if(acquisition.haveService){const uint32_t gap=now-acquisition.lastServiceUs;maximum(b.serviceGapMaxUs,gap);if(gap>=10000)++b.gapsOver10ms;}
  acquisition.lastServiceUs=now;acquisition.haveService=true;
}
inline void consumer(uint8_t node,uint8_t cls,bool accepted,uint16_t samples,uint16_t evidence,uint32_t now) {
  if(node>=4)return;
  const auto i=index(acquisition,now);if(i==capacity)return;auto& b=acquisition.bins[i];
  if(samples>b.samplePeak[node])b.samplePeak[node]=samples;
  if(evidence>b.evidencePeak[node])b.evidencePeak[node]=evidence;
  if(cls==1){++b.sampleCalls;if(!accepted)++b.sampleWaits;}
  else if(cls==2){++b.evidenceCalls;if(!accepted)++b.evidenceWaits;}
}
inline void loss(uint8_t node,uint8_t cls,uint32_t now) {
  if(node>=4 || cls<1 || cls>2)return;
  const auto i=index(acquisition,now);if(i==capacity)return;auto& b=acquisition.bins[i];
  if(cls==1)++b.sourceLossReports[node];else ++b.evidenceLossReports[node];
}
}
#endif
