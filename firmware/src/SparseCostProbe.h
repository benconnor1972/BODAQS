#pragma once
#ifndef BODAQS_SPARSE_COST_PROBE
#define BODAQS_SPARSE_COST_PROBE 0
#endif
#if BODAQS_SPARSE_COST_PROBE != 0 && BODAQS_SPARSE_COST_PROBE != 1
#error "Sparse cost probe must be0or1"
#endif
#if BODAQS_SPARSE_COST_PROBE
#if !BODAQS_ACQUISITION_PROFILE || !BODAQS_PACKED_EXCHANGE
#error "Sparse cost probe requires the selected live acquisition/packed profile"
#endif
#include "RecordingTimelineDiagnostics.h"
#include "../can-fd/common/protocol/packed_receiver.h"
#include <algorithm>
#include <type_traits>
namespace SparseCostProbe {
constexpr uint32_t capacity=RecordingTimelineDiagnostics::capacity,block=64;
enum Stage {Service,Consumers,ControlAccept,StageCount};
enum PacketKind {Empty,NewSmall,NewFull,Replay,Mixed,Metadata,Invalid,Legacy,Recovering,PacketKindCount};
enum PacketPart {Envelope,Codec,Receiver,Rest,PacketPartCount};
//20s bins and sparse selection keep normal totals far below32-bit capacity.
// Saturate/mark invalid on overflow rather than wrap or grow scarce static RAM.
struct Metric {uint32_t totalUs=0,calls=0,maxUs=0;};
struct Bin {
 Metric stages[StageCount],packets[PacketKindCount][PacketPartCount],consumers[7][2],observers[7];
 uint32_t eligible=0,selected=0,coresIn[3]={},coresOut[3]={},migrations=0,clockChanges=0;
 uint32_t minMHz=0,maxMHz=0,invalidIntervals=0;
};
struct State {Bin bins[capacity];uint64_t context=0;uint32_t originUs=0,used=0,overflow=0;bool enabled=false;};
inline State* state=nullptr;inline Bin hot;inline uint32_t hotIndex=capacity,serial=0;
inline bool enabled=false,active=false;
// Immutable binding for this acquisition owner. The export bank may be in
// PSRAM; selection and nested guards must not fetch it on every live call.
inline uint64_t boundContext=0;
inline uint32_t boundOriginUs=0;
inline bool boundEnabled=false;
uint32_t nowUs();unsigned coreId();unsigned frequencyMHz();void bootModeGate();
static_assert(std::is_trivially_copyable<State>::value,"Single-writer scalar diagnostics");
static_assert(sizeof(Bin)<=1100,"Bounded internal hot bank");
template<class T> inline void clear(T& v){std::fill_n(reinterpret_cast<uint8_t*>(&v),sizeof(v),uint8_t(0));}
inline size_t hotReservedBytes(){return sizeof(hot)+sizeof(state)+sizeof(hotIndex)+sizeof(serial)+sizeof(enabled)+sizeof(active)+sizeof(boundContext)+sizeof(boundOriginUs)+sizeof(boundEnabled);}
// Called by the acquisition owner after existing storage-bank publication and
// its in-place clear of the complete acquisition bank, including State.
// Boot selection is immutable after tasks start. No live/retired bank aliasing.
inline void bind(State* bank,uint64_t context,uint32_t origin){
 active=false;state=bank;clear(hot);hotIndex=capacity;serial=0;
 boundContext=bank?context:0;boundOriginUs=origin;boundEnabled=bank && context && enabled;
 if(state){state->context=context;state->originUs=origin;state->enabled=enabled;}
}
inline const Bin& at(uint32_t i){return i==hotIndex?hot:state->bins[i];}
inline void metric(Metric& m,uint32_t us){
 if(m.calls==UINT32_MAX || us>UINT32_MAX-m.totalUs){m.totalUs=UINT32_MAX;++hot.invalidIntervals;return;}
 ++m.calls;m.totalUs+=us;if(us>m.maxUs)m.maxUs=us;
}
inline bool elapsed(uint32_t start,uint32_t end,uint32_t& us){
 us=end-start;if(us>=0x80000000u){++hot.invalidIntervals;return false;}return true;
}
class ServiceScope {
 bool chosen=false;uint64_t context=0;uint32_t start=0;unsigned entryCore=2,entryMHz=0;
public:
 ServiceScope(uint32_t tick,unsigned core):start(tick),entryCore(core){
  if(!boundEnabled)return;
  if(active){++hot.invalidIntervals;return;}
  const auto i=uint32_t(tick-boundOriginUs)/RecordingTimelineDiagnostics::binUs;
  if(i>=capacity){if(state->overflow!=UINT32_MAX)++state->overflow;return;}
  if(i!=hotIndex){
   if(hotIndex<capacity)state->bins[hotIndex]=hot;clear(hot);hotIndex=i;
   if(i+1>state->used)state->used=i+1;
  }
  ++hot.eligible;const auto n=serial++;
  chosen=(n%block)==(((n/block)*17)%block);
  if(!chosen)return;
  context=boundContext;active=true;++hot.selected;++hot.coresIn[core<2?core:2];entryMHz=frequencyMHz();
 }
 void finish(){
  if(!chosen)return;chosen=false;
  if(!active || !state || boundContext!=context)return;
  const auto end=nowUs();const auto core=coreId(),mhz=frequencyMHz();
  uint32_t us;if(elapsed(start,end,us))metric(hot.stages[Service],us);
  ++hot.coresOut[core<2?core:2];if(core!=entryCore)++hot.migrations;
  if(mhz!=entryMHz)++hot.clockChanges;
  if(!hot.minMHz || entryMHz<hot.minMHz)hot.minMHz=entryMHz;
  if(mhz<hot.minMHz)hot.minMHz=mhz;
  hot.maxMHz=std::max(hot.maxMHz,std::max(mhz,entryMHz));active=false;
 }
 ~ServiceScope(){finish();}
 ServiceScope(const ServiceScope&)=delete;ServiceScope& operator=(const ServiceScope&)=delete;
};
class Span {
 Metric* output=nullptr;uint32_t start=0;uint64_t context=0;
public:
 explicit Span(Stage s){if(active){output=&hot.stages[s];context=boundContext;start=nowUs();}}
 Span(Stage s,uint32_t tick){if(active){output=&hot.stages[s];context=boundContext;start=tick;}}
 Span(unsigned cls,bool observer){if(active && cls>=1 && cls<=7 && observer){output=&hot.observers[cls-1];context=boundContext;start=nowUs();}}
 ~Span(){if(output && active && state && boundContext==context){uint32_t us;if(elapsed(start,nowUs(),us))metric(*output,us);}}
 Span(const Span&)=delete;Span& operator=(const Span&)=delete;
};
template<class F> inline bool consumer(unsigned cls,F&& fn){
 if(!active || cls<1 || cls>7)return fn();
 const auto context=boundContext;const auto start=nowUs();const bool accepted=fn();const auto end=nowUs();
 uint32_t us;if(active && state && boundContext==context && elapsed(start,end,us))metric(hot.consumers[cls-1][accepted?1:0],us);return accepted;
}
// Reply shape/node/count have already passed the real packet decoder.
inline PacketKind classify(const BpReply& reply,const BpReceiver* receiver){
 if(!reply.count)return Empty;
 unsigned samples=0,known=0;bool full=false;
 for(unsigned i=0;i<reply.count;++i){const auto& item=reply.items[i];
  if(bodaqs_fragment_class(item.kind)!=1)continue;
  ++samples;full|=item.length==468;
  if(receiver){const auto& cell=receiver->cells[4*item.node+(item.object-1)%4];
   known+=item.object<receiver->base[item.node] || (cell.state.object==item.object && cell.state.complete);}
 }
 if(!samples)return Metadata;if(samples!=reply.count)return Mixed;
 if(known==samples)return Replay;if(known)return Mixed;return full?NewFull:NewSmall;
}
class Frame {
 bool chosen=false,haveCodec=false,haveReceiver=false;uint32_t start=0,codec=0,receiver=0;uint64_t context=0;PacketKind kind=Legacy;
public:
 explicit Frame(uint32_t tick):chosen(active),start(tick),context(active?boundContext:0){}
 template<class F> bool decode(F&& fn){
  if(!chosen)return fn();const auto t=nowUs();const bool result=fn();
  const auto end=nowUs();if(active && state && boundContext==context)haveCodec=elapsed(t,end,codec);return result;
 }
 void decoded(bool valid,const BpReply& reply,const BpReceiver* r,bool recovering){
  if(chosen)kind=!valid?Invalid:recovering?Recovering:classify(reply,r);
 }
 template<class F> bool receive(F&& fn){
  if(!chosen)return fn();const auto t=nowUs();const bool result=fn();
  const auto end=nowUs();if(active && state && boundContext==context)haveReceiver=elapsed(t,end,receiver);return result;
 }
 void finish(uint32_t end){
  if(!chosen || !active || !state || boundContext!=context)return;uint32_t us;if(!elapsed(start,end,us))return;
  auto& p=hot.packets[kind];metric(p[Envelope],us);
  if(haveCodec)metric(p[Codec],codec);if(haveReceiver)metric(p[Receiver],receiver);
  if(uint64_t(codec)+receiver<=us)metric(p[Rest],us-codec-receiver);else ++hot.invalidIntervals;
  chosen=false;
 }
};
}
#endif
