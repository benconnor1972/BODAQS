#pragma once
#include "RecordingTimelineDiagnostics.h"
#ifndef BODAQS_CONTROL_POLL_DIAGNOSTICS
#define BODAQS_CONTROL_POLL_DIAGNOSTICS 0
#endif
#if BODAQS_CONTROL_POLL_DIAGNOSTICS != 0 && BODAQS_CONTROL_POLL_DIAGNOSTICS != 1
#error "Control polling diagnostics must be0or1"
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
struct Bin {
  uint32_t targets[8]={},reasons[ReasonCount]={};
  uint32_t fetches[4]={},pendingFetches[4]={},ageMaxMs[4]={};
  uint64_t ageSumMs[4]={};
  uint32_t firstOperation[4]={},lastOperation[4]={};
  uint32_t begins[4]={},matched[4]={},timeouts[4]={},matchedAgeMaxMs[4]={};
  uint8_t lastOpcode[4]={},lastPage[4]={};
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
inline Acquisition acquisition;
inline Memory memory;
static_assert(sizeof(acquisition)+sizeof(memory)<=10000,"Bounded control diagnostic RAM");
inline size_t reservedBytes(){return sizeof(acquisition)+sizeof(memory);}
inline void resetStorage(uint32_t origin){memory={};memory.originUs=origin;memory.initialized=true;}
inline void resetAcquisition(uint64_t context){
  acquisition={};acquisition.context=context;
  acquisition.originUs=RecordingTimelineDiagnostics::acquisition.originUs;
}
inline void peer(unsigned node,bool pending,uint32_t started,uint32_t operation,uint8_t opcode,uint8_t page){
  if(node<4)acquisition.peers[node]={started,operation,opcode,page,pending};
}
inline void event(unsigned node,uint8_t kind,uint32_t ageMs,uint32_t nowUs){
  if(node>=4 || !acquisition.context)return;
  const auto i=RecordingTimelineDiagnostics::index(acquisition,nowUs);if(i==capacity)return;
  auto& b=acquisition.bins[i];
  if(kind==0)++b.begins[node];
  else if(kind==1){++b.matched[node];RecordingTimelineDiagnostics::maximum(b.matchedAgeMaxMs[node],ageMs);}
  else if(kind==2)++b.timeouts[node];
}
inline void request(uint8_t target,uint8_t node,bool outgoing,bool partial,bool unadmitted,bool ack,
                    bool seen,uint32_t lastFetchMs,uint32_t nowMs,uint32_t nowUs){
  if(!acquisition.context)return;
  const auto i=RecordingTimelineDiagnostics::index(acquisition,nowUs);if(i==capacity)return;
  auto& b=acquisition.bins[i];++b.targets[target<8?target:7];
  if(target!=3 || node>=4)return;
  const auto& p=acquisition.peers[node];
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
inline bool memoryDue(uint32_t nowUs){
  if(!memory.initialized || memory.frozen)return false;
  const auto i=RecordingTimelineDiagnostics::index(memory,nowUs);
  return i<capacity && !memory.bins[i].samples;
}
inline void sampleMemory(uint32_t nowUs,uint32_t internalFree,uint32_t internalLargest,
                         uint32_t psramFree,uint32_t psramLargest){
  if(!memoryDue(nowUs))return;
  const auto i=uint32_t(nowUs-memory.originUs)/RecordingTimelineDiagnostics::binUs;
  memory.bins[i]={1,uint32_t(nowUs-memory.originUs),internalFree,internalLargest,psramFree,psramLargest};
}
}
#endif
