#pragma once
#include "RecordingTimelineDiagnostics.h"
#include <algorithm>
#include <new>
#include <type_traits>
#if defined(ARDUINO_ARCH_ESP32)
#include <esp_heap_caps.h>
#endif
#ifndef BODAQS_CONTROL_POLL_DIAGNOSTICS
#define BODAQS_CONTROL_POLL_DIAGNOSTICS 0
#endif
#if BODAQS_CONTROL_POLL_DIAGNOSTICS != 0 && BODAQS_CONTROL_POLL_DIAGNOSTICS != 1
#error "Control polling diagnostics must be0or1"
#endif
#ifndef BODAQS_ACQUISITION_PROFILE
#define BODAQS_ACQUISITION_PROFILE 0
#endif
#if BODAQS_ACQUISITION_PROFILE != 0 && BODAQS_ACQUISITION_PROFILE != 1
#error "Acquisition profile must be0or1"
#endif
#if BODAQS_ACQUISITION_PROFILE && !BODAQS_CONTROL_POLL_DIAGNOSTICS
#error "Acquisition profiling requires control diagnostics"
#endif
#if BODAQS_CONTROL_POLL_DIAGNOSTICS
#if !BODAQS_STORAGE_TIMELINE || BODAQS_ORDINARY_FETCH_INTERVAL_MS != 20
#error "Control polling diagnostics require the unchanged timeline/ordinary20 profile"
#endif
// Diagnostic-only banks. Acquisition owns peers/events/requests; storage owns
// memory samples. Read together only after matching producer retirement.
namespace ControlPollingDiagnostics {
constexpr uint32_t capacity=RecordingTimelineDiagnostics::capacity;
enum Reason {Outgoing,Partial,Unadmitted,PendingFirst,PendingDue,PendingNotDue,AckOnly,Idle,ReasonCount};
struct Peer {uint32_t startedMs=0,operation=0;uint8_t opcode=0,page=0;bool pending=false;};
#if BODAQS_ACQUISITION_PROFILE
enum Stage {Service,Selection,Transport,Consumers,Encode,SpiWait,SpiPrepare,SpiTransfer,SpiFinish,Decode,Burst,Sleep,StageCount};
struct Profile {
  uint64_t totalUs[StageCount]={};uint32_t maxUs[StageCount]={},calls[StageCount]={};
  uint32_t cores[3]={}; // core0, core1, host/unknown
  uint32_t reclaimed[3]={},legacyBlockedWindowOpen=0; // sample,evidence,none
};
#endif
struct Bin {
  uint32_t targets[8]={},reasons[ReasonCount]={};
  uint32_t fetches[4]={},pendingFetches[4]={},ageMaxMs[4]={};
  uint64_t ageSumMs[4]={};
  uint32_t firstOperation[4]={},lastOperation[4]={};
  uint32_t begins[4]={},matched[4]={},timeouts[4]={},matchedAgeMaxMs[4]={};
  uint8_t lastOpcode[4]={},lastPage[4]={};
#if BODAQS_ACQUISITION_PROFILE
  Profile profile;
#endif
};
struct MemoryBin {
  uint32_t samples=0,elapsedUs=0,internalFree=0,internalLargest=0,psramFree=0,psramLargest=0;
};
struct Acquisition {
  Bin bins[capacity];Peer peers[4];uint64_t context=0;
  uint32_t originUs=0,used=0,overflow=0;
};
struct Memory {
  MemoryBin bins[capacity];uint32_t originUs=0,used=0,overflow=0;
  bool initialized=false,frozen=false;
};
struct Banks {Acquisition acq;Memory mem;};
// Persistent allocation, once before acquisition. Each owner retains only its
// own bank; the pointer publication follows complete bank construction.
inline Acquisition* acquisition=nullptr;
inline Memory* memory=nullptr;
inline std::atomic<Acquisition*> published{nullptr};
#if BODAQS_ACQUISITION_PROFILE
// Single acquisition-task writer, ordinary internal RAM. Flush only when the
// time bin changes; retired serialization reads the current hot bin directly.
inline Profile hotProfile;
inline uint32_t hotIndex=capacity;
inline const Profile& profileAt(uint32_t i){return i==hotIndex?hotProfile:acquisition->bins[i].profile;}
inline Profile& profileWrite(uint32_t i){
  // A parent interval may finish after a child entered the next bin. Its
  // start-bin update goes to the already flushed bank without rewinding it.
  if(hotIndex<capacity && i<hotIndex)return acquisition->bins[i].profile;
  if(i!=hotIndex){
    if(hotIndex<capacity)acquisition->bins[hotIndex].profile=hotProfile;
    hotProfile={};hotIndex=i;
  }
  return hotProfile;
}
#endif
static_assert(std::atomic<Acquisition*>::is_always_lock_free,"Diagnostic publication must not lock");
static_assert(std::is_trivially_copyable<Acquisition>::value && std::is_trivially_copyable<Memory>::value,"Zeroable scalar banks");
static_assert(sizeof(Banks)+sizeof(acquisition)+sizeof(memory)+sizeof(published)<=(BODAQS_ACQUISITION_PROFILE?18000:10100),"Bounded control diagnostic bank RAM");
inline size_t reservedBytes(){return sizeof(Banks)+sizeof(acquisition)+sizeof(memory)+sizeof(published)
#if BODAQS_ACQUISITION_PROFILE
  +sizeof(hotProfile)+sizeof(hotIndex)
#endif
  ;}
inline Banks* allocateBanks(){
#if defined(ARDUINO_ARCH_ESP32)
  void* bytes=heap_caps_malloc(sizeof(Banks),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  return bytes?new(bytes) Banks:nullptr;
#else
  return new(std::nothrow) Banks;
#endif
}
inline void resetStorage(uint32_t origin){
  if(!memory){
    Banks* banks=allocateBanks();
    if(!banks){published.store(nullptr,std::memory_order_release);return;}
    memory=&banks->mem;published.store(&banks->acq,std::memory_order_release);
  }
  // Banks contain only unsigned integers, byte enums and bools; avoid a large
  // reset temporary on either owner's stack.
  std::fill_n(reinterpret_cast<uint8_t*>(memory),sizeof(*memory),uint8_t(0));
  memory->originUs=origin;memory->initialized=true;
}
inline void resetAcquisition(uint64_t context){
#if BODAQS_ACQUISITION_PROFILE
  hotProfile={};hotIndex=capacity;
#endif
  acquisition=published.load(std::memory_order_acquire);if(!acquisition)return;
  std::fill_n(reinterpret_cast<uint8_t*>(acquisition),sizeof(*acquisition),uint8_t(0));
  acquisition->context=context;
  acquisition->originUs=RecordingTimelineDiagnostics::acquisition.originUs;
}
inline void peer(unsigned node,bool pending,uint32_t started,uint32_t operation,uint8_t opcode,uint8_t page){
  if(acquisition && node<4)acquisition->peers[node]={started,operation,opcode,page,pending};
}
inline void event(unsigned node,uint8_t kind,uint32_t ageMs,uint32_t nowUs){
  if(node>=4 || !acquisition || !acquisition->context)return;
  const auto i=RecordingTimelineDiagnostics::index(*acquisition,nowUs);if(i==capacity)return;
  auto& b=acquisition->bins[i];
  if(kind==0)++b.begins[node];
  else if(kind==1){++b.matched[node];RecordingTimelineDiagnostics::maximum(b.matchedAgeMaxMs[node],ageMs);}
  else if(kind==2)++b.timeouts[node];
}
inline void request(uint8_t target,uint8_t node,bool outgoing,bool partial,bool unadmitted,bool ack,
                    bool seen,uint32_t lastFetchMs,uint32_t nowMs,uint32_t nowUs){
  if(!acquisition || !acquisition->context)return;
  const auto i=RecordingTimelineDiagnostics::index(*acquisition,nowUs);if(i==capacity)return;
  auto& b=acquisition->bins[i];++b.targets[target<8?target:7];
  if(target!=3 || node>=4)return;
  const auto& p=acquisition->peers[node];
  const Reason reason=outgoing?Outgoing:partial?Partial:unadmitted?Unadmitted:
      p.pending?(!seen?PendingFirst:uint32_t(nowMs-lastFetchMs)>=20?PendingDue:PendingNotDue):ack?AckOnly:Idle;
  ++b.reasons[reason];
  if(++b.fetches[node]==1)b.firstOperation[node]=p.operation;
  b.lastOperation[node]=p.operation;b.lastOpcode[node]=p.opcode;b.lastPage[node]=p.page;
  if(p.pending){
    const uint32_t age=nowMs-p.startedMs;++b.pendingFetches[node];b.ageSumMs[node]+=age;
    RecordingTimelineDiagnostics::maximum(b.ageMaxMs[node],age);
  }
}
#if BODAQS_ACQUISITION_PROFILE
inline void reclaimed(uint32_t nowUs,uint8_t cls,bool selected,bool legacyMismatch){
  if(!acquisition || !acquisition->context)return;
  const auto i=RecordingTimelineDiagnostics::index(*acquisition,nowUs);if(i==capacity)return;
  auto& p=profileWrite(i);++p.reclaimed[selected?(cls==1?0:1):2];
  if(legacyMismatch)++p.legacyBlockedWindowOpen;
}
// Intervals are charged to their start bin. Nested stages must not be summed.
inline void profile(Stage stage,uint32_t start,uint32_t duration,unsigned core=2){
  if(!acquisition || !acquisition->context)return;
  const auto i=RecordingTimelineDiagnostics::index(*acquisition,start);if(i==capacity)return;
  auto& p=profileWrite(i);++p.calls[stage];p.totalUs[stage]+=duration;
  RecordingTimelineDiagnostics::maximum(p.maxUs[stage],duration);
  if(stage==Service)++p.cores[core<2?core:2];
}
#endif
inline bool memoryDue(uint32_t nowUs){
  if(!memory || !memory->initialized || memory->frozen)return false;
  const auto i=RecordingTimelineDiagnostics::index(*memory,nowUs);
  return i<capacity && !memory->bins[i].samples;
}
inline void sampleMemory(uint32_t nowUs,uint32_t internalFree,uint32_t internalLargest,
                         uint32_t psramFree,uint32_t psramLargest){
  if(!memoryDue(nowUs))return;
  const auto i=uint32_t(nowUs-memory->originUs)/RecordingTimelineDiagnostics::binUs;
  memory->bins[i]={1,uint32_t(nowUs-memory->originUs),internalFree,internalLargest,psramFree,psramLargest};
}
}
#endif
