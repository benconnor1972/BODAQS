#pragma once
#include <stdint.h>
#include <stddef.h>
#include <cstdio>
#include "../can-fd/common/protocol/bodaqs_measurement.h"

#ifndef BODAQS_PIPELINE_TRACE
#define BODAQS_PIPELINE_TRACE 0
#endif
#if BODAQS_PIPELINE_TRACE != 0 && BODAQS_PIPELINE_TRACE != 1
#error "Pipeline trace must be 0 or 1"
#endif
#if BODAQS_PIPELINE_TRACE && (!defined(BODAQS_IMU_FLOW_DIAGNOSTICS) || !BODAQS_IMU_FLOW_DIAGNOSTICS || BODAQS_MEASUREMENT_VERSION != 2)
#error "Pipeline trace requires FLOW and v2"
#endif

namespace MeasurementPipelineTrace {
// Diagnostic only. Acquisition owner writes; reset before ownership publication,
// freeze/finish before release; dump only after acquiring inactive owner state.
// No wire bytes, receive/ACK masks, timers or admission decisions use this data.
struct Entry {
  uint32_t slot,startedUs,durationUs,targetObject,responseObject,ackObject;
  uint16_t available;
  uint8_t targetMask,requestedAfter;
  uint8_t requestKind,targetClass,targetNode,targetIndex;
  uint8_t responseKind,responseNode,responseIndex,flags;
  uint8_t ackClass,ackNode,responseMaskBefore,reserved;
};
static_assert(sizeof(Entry)==40,"Trace layout changed");
enum : uint8_t { Valid=1,KnownFragment=2,OlderFragment=4,DownstreamBlocked=8,
                 Retirement=16,TargetAckPending=32,ContextMismatch=64,IdleControl=128 };
#if BODAQS_PIPELINE_TRACE
struct Window {
  Entry rows[128]={};
  uint32_t overwritten=0;
  uint16_t head=0,count=0;
  uint8_t reason=0; // 0 live, 1 first loss, 2 terminal set, 3 finish, 4 fatal loss
  void append(const Entry& row) {
    if(reason) return;
    rows[head]=row;head=(head+1)%128;
    if(count<128) ++count;else if(overwritten!=UINT32_MAX) ++overwritten;
  }
};
inline Window firstLoss,stop;
inline uint64_t context=0;
inline uint32_t slots=0,empty=0,emptyWithAvailable=0,invalid=0,idleControl=0;
inline uint8_t participants=0,terminalMask=0,ordinaryPending=0,protectedPending=0;
inline bool active=false,stopArmed=false,exhausted=false;
inline void reset(uint64_t value,uint32_t) {
  firstLoss={};stop={};context=value;slots=empty=emptyWithAvailable=invalid=idleControl=0;
  participants=terminalMask=ordinaryPending=protectedPending=0;
  active=true;stopArmed=exhausted=false;
}
inline size_t reservedBytes() {return sizeof(firstLoss)+sizeof(stop)+64;}
inline void setParticipants(uint8_t mask) {if(active) participants=mask;}
inline void pending(uint8_t ordinary,uint8_t protectedMask) {
  if(active) {ordinaryPending=ordinary;protectedPending=protectedMask;}
}
inline void loss() {if(active && !firstLoss.reason) firstLoss.reason=1;}
inline void terminal(uint8_t node) {
  if(!active || node>3) return;
  terminalMask|=uint8_t(1u<<node);
  if(stopArmed && !stop.reason && participants && (terminalMask&participants)==participants) stop.reason=2;
}
inline void finish() {
  if(!active) return;
  if(!firstLoss.reason) firstLoss.reason=3;
  if(!stop.reason) stop.reason=3;
  active=false;
}
inline void record(const BodaqsMeasurementSlot& request,const BodaqsMeasurementSlot* reply,
                   uint32_t began,uint32_t duration,uint8_t targetMask,uint8_t requested,
                   uint8_t responseMask,uint8_t flags) {
  if(!active || exhausted) return;
  if(slots==UINT32_MAX) {exhausted=true;return;}
  Entry row={};row.slot=++slots;row.startedUs=began;row.durationUs=duration;
  row.requestKind=request.kind;row.targetNode=255;row.ackNode=255;
  if(request.kind==1) {
    row.targetClass=request.body[0];row.targetNode=request.node;
    row.targetObject=request.object;row.targetIndex=request.index;
  } else if(request.kind==14) {
    row.targetClass=request.body[2];row.targetNode=request.body[3];
    row.targetObject=(uint32_t)bodaqs_measurement_get(request.body+8,4);row.targetIndex=request.body[12];
    row.ackClass=request.body[0];row.ackNode=request.node;row.ackObject=request.object;
  }
  if(row.targetClass==3 || row.targetClass==4) {
    const uint8_t mask=row.targetClass==3?ordinaryPending:protectedPending;
    if(row.targetNode<4 && !(mask&(1u<<row.targetNode))) {flags|=IdleControl;++idleControl;}
  }
  if(request.kind==12 && request.index==0 && request.body[12]==0x25) stopArmed=true;
  row.targetMask=targetMask;row.requestedAfter=requested;row.responseMaskBefore=responseMask;row.flags=flags;
  if(reply) {
    row.flags|=Valid;row.responseKind=reply->kind;row.responseNode=reply->node;
    row.responseObject=reply->object;row.responseIndex=reply->index;row.available=reply->available;
    if(reply->retired) row.flags|=Retirement;
    if(!reply->kind) {++empty;if(reply->available) ++emptyWithAvailable;}
  } else {row.responseNode=255;++invalid;}
  firstLoss.append(row);
  if(stopArmed) stop.append(row);
  if(stopArmed && reply && reply->kind==7 && reply->body[1]==14 && !stop.reason) stop.reason=4;
}
template<class Writer> bool dump(Writer write) {
  if(active) return false; // Caller also needs the existing inactive-owner acquire.
  char line[768];
  std::snprintf(line,sizeof line,
    "{\"schema\":\"bodaqs.spi-pipeline.v1\",\"type\":\"summary\",\"context\":\"%llu\",\"slots\":%lu,\"empty\":%lu,\"empty_available\":%lu,\"invalid\":%lu,\"idle_control_targets\":%lu,\"participants\":%u,\"terminal_mask\":%u,\"stop_armed\":%s,\"exhausted\":%s}\n",
    (unsigned long long)context,(unsigned long)slots,(unsigned long)empty,(unsigned long)emptyWithAvailable,
    (unsigned long)invalid,(unsigned long)idleControl,participants,terminalMask,stopArmed?"true":"false",exhausted?"true":"false");
  write(line);
  for(unsigned window=0;window<2;++window) {
    const auto& capture=window?stop:firstLoss;
    std::snprintf(line,sizeof line,
      "{\"schema\":\"bodaqs.spi-pipeline.v1\",\"type\":\"window\",\"window\":%u,\"count\":%u,\"overwritten\":%lu,\"reason\":%u,\"columns\":[\"slot\",\"start_us\",\"duration_us\",\"target_object\",\"response_object\",\"ack_object\",\"available\",\"target_mask\",\"requested_after_selection\",\"request_kind\",\"target_class\",\"target_node\",\"target_index\",\"response_kind\",\"response_node\",\"response_index\",\"flags\",\"ack_class\",\"ack_node\",\"response_mask_before\"]}\n",
      window,capture.count,(unsigned long)capture.overwritten,capture.reason);
    write(line);
    for(unsigned i=0;i<capture.count;++i) {
      const auto& e=capture.rows[(capture.head+128-capture.count+i)%128];
      std::snprintf(line,sizeof line,
        "{\"type\":\"frame\",\"window\":%u,\"v\":[%lu,%lu,%lu,%lu,%lu,%lu,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u]}\n",
        window,(unsigned long)e.slot,(unsigned long)e.startedUs,(unsigned long)e.durationUs,
        (unsigned long)e.targetObject,(unsigned long)e.responseObject,(unsigned long)e.ackObject,
        e.available,e.targetMask,e.requestedAfter,e.requestKind,e.targetClass,e.targetNode,e.targetIndex,
        e.responseKind,e.responseNode,e.responseIndex,e.flags,e.ackClass,e.ackNode,e.responseMaskBefore);
      write(line);
    }
  }
  write("{\"schema\":\"bodaqs.spi-pipeline.v1\",\"type\":\"end\"}\n");return true;
}
#else
inline void reset(uint64_t,uint32_t) {}
inline size_t reservedBytes() {return 0;}
inline void setParticipants(uint8_t) {}
inline void pending(uint8_t,uint8_t) {}
inline void loss() {}
inline void terminal(uint8_t) {}
inline void finish() {}
template<class Writer> bool dump(Writer) {return false;}
#endif
}
