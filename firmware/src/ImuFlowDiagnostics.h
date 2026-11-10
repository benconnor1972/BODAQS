#pragma once
#include <stdint.h>
#include <stddef.h>
#include "MeasurementReplyCapture.h"

#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
#if !defined(BODAQS_IMU_FLOW_DIAGNOSTICS) || !BODAQS_IMU_FLOW_DIAGNOSTICS || !defined(BODAQS_SPI_MEASUREMENT_V2) || !BODAQS_SPI_MEASUREMENT_V2
#error "Rejected reply capture requires FLOW diagnostics and measurement v2"
#endif
#endif

#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
// One acquisition-owner writer. Reset before ownership publication; finish
// before ownership release. Read/print only after acquiring inactive ownership.
namespace ImuFlowDiagnostics {
struct Snapshot {
  uint64_t context=0;
  uint32_t beganMs=0,observedMs=0,services=0;
  uint32_t requests[4]={}; // polls, ACK_FETCH, outgoing fragments, other
  uint32_t polls[5]={},fetchTargets[5]={},deferred[2]={},empty=0,wireFailures=0;
  uint32_t newFragments[5]={},repeatFragments[5]={};
  uint32_t admitted[5]={},consumerCalls[7]={},consumerWait[7]={},gateWait=0;
  uint32_t proofMatches[5]={},proofWaitMaxUs[5]={};
  uint64_t proofWaitTotalUs[5]={};
  uint32_t proofPending[5]={},proofOldestUs[5]={};
  uint32_t sampleQueuePeak=0,evidenceQueuePeak=0,sampleCapacity=0,evidenceCapacity=0;
  uint32_t lossCounter=0;
  uint32_t measurementTransferFailures=0,measurementDecodeFailures=0;
  bool measurementFailuresAvailable=false;
};
struct Wait {uint32_t object=0,startedUs=0;};
inline Snapshot live,firstLoss,finished;
inline Wait waits[5][4];
inline bool active=false,haveFirstLoss=false,haveFinished=false;
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
inline MeasurementReplyCapture liveReplies,finishedReplies;
// Acquisition owner only. No allocation, serialization or logging in this path.
inline void rejectedReply(uint64_t context,uint32_t slot,uint8_t kind,const uint8_t* bytes) {
  if(!active || live.context!=context || liveReplies.count==MeasurementReplyCapture::capacity) return;
  auto& entry=liveReplies.entries[liveReplies.count++];
  entry.slot=slot;entry.requestKind=kind;
  for(unsigned i=0;i<MeasurementReplyCapture::replyBytes;++i) entry.reply[i]=bytes[i];
}
#endif
inline size_t reservedBytes() {
  size_t bytes=sizeof(live)+sizeof(firstLoss)+sizeof(finished)+sizeof(waits)+3*sizeof(bool);
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
  bytes+=sizeof(liveReplies)+sizeof(finishedReplies);
#endif
  return bytes;
}
inline void reset(uint64_t context,uint32_t now) {
  live={};firstLoss={};finished={};
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
  liveReplies={};finishedReplies={};
#endif
  for(auto& row:waits) for(auto& wait:row) wait={};
  live.context=context;live.beganMs=now;active=true;haveFirstLoss=haveFinished=false;
}
inline void service() {if(active) ++live.services;}
inline void request(uint8_t kind,uint8_t cls,uint8_t node,uint32_t object,uint32_t nowUs,uint8_t fetchClass=0) {
  if(!active) return;
  ++live.requests[kind==1?0:kind==14?1:(kind==4 || kind==12)?2:3];
  if(kind==1 && cls>=1 && cls<=5) ++live.polls[cls-1];
  if(kind==14 && cls>=1 && cls<=5 && (node<4 || (cls==5 && node==255))) {
    if(fetchClass>=1 && fetchClass<=5) ++live.fetchTargets[fetchClass-1];
    auto& wait=waits[cls-1][cls==5?0:node];
    if(wait.object!=object) {wait.object=object;wait.startedUs=nowUs;}
  }
}
inline void proof(uint8_t cls,uint8_t node,uint32_t object,uint32_t nowUs) {
  if(!active || cls<1 || cls>5 || (node>3 && !(cls==5 && node==255))) return;
  auto& wait=waits[cls-1][cls==5?0:node];
  if(wait.object!=object || !object) return;
  const uint32_t elapsed=nowUs-wait.startedUs;
  ++live.proofMatches[cls-1];live.proofWaitTotalUs[cls-1]+=elapsed;
  if(elapsed>live.proofWaitMaxUs[cls-1]) live.proofWaitMaxUs[cls-1]=elapsed;
  wait={};
}
inline void fragment(uint8_t cls,bool fresh) {
  if(active && cls>=1 && cls<=5) ++(fresh?live.newFragments[cls-1]:live.repeatFragments[cls-1]);
}
inline void admitted(uint8_t cls) {if(active && cls>=1 && cls<=5) ++live.admitted[cls-1];}
inline void consumer(uint8_t cls,bool accepted,size_t sampleDepth,size_t evidenceDepth,
                     size_t sampleCapacity,size_t evidenceCapacity) {
  if(!active || cls<1 || cls>7) return;
  ++live.consumerCalls[cls-1];if(!accepted) ++live.consumerWait[cls-1];
  if(sampleDepth>live.sampleQueuePeak) live.sampleQueuePeak=sampleDepth;
  if(evidenceDepth>live.evidenceQueuePeak) live.evidenceQueuePeak=evidenceDepth;
  live.sampleCapacity=sampleCapacity;live.evidenceCapacity=evidenceCapacity;
}
inline Snapshot capture(uint32_t now,uint32_t nowUs) {
  Snapshot result=live;result.observedMs=now;
  for(unsigned cls=0;cls<5;++cls) for(const auto& wait:waits[cls]) if(wait.object) {
    ++result.proofPending[cls];
    const uint32_t elapsed=nowUs-wait.startedUs;
    if(elapsed>result.proofOldestUs[cls]) result.proofOldestUs[cls]=elapsed;
  }
  return result;
}
inline void loss(uint32_t counter,uint32_t now,uint32_t nowUs) {
  if(!active || haveFirstLoss || !counter) return;
  live.lossCounter=counter;firstLoss=capture(now,nowUs);haveFirstLoss=true;
}
inline void finish(uint32_t now,uint32_t nowUs,uint32_t transferFailures=0,uint32_t decodeFailures=0,bool measurementAvailable=true) {
  if(!active) return;
  live.measurementTransferFailures=transferFailures;live.measurementDecodeFailures=decodeFailures;
  live.measurementFailuresAvailable=measurementAvailable;
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
  if(measurementAvailable) finishedReplies=liveReplies;
  else finishedReplies={};
#endif
  finished=capture(now,nowUs);haveFinished=true;active=false;
}
} // namespace ImuFlowDiagnostics
#endif
