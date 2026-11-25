#pragma once
#include <stdint.h>
#include "RecordingFeatures.h"
namespace BacklogBalance {
struct Pressure {unsigned primary=0,samples=0,evidence=0;bool valid=false,running=false;};
struct Decision {unsigned priority,calls,budgetUs,sleepTicks;};
class Policy {
 bool recovery=false;
public:
 Decision decide(bool adaptive,const Pressure& q) {
  if(!adaptive || !q.running){recovery=false;return {2,8,0,1};}
  if(!q.valid || q.primary>=125 || q.samples>=250 || q.evidence>=250)recovery=true;
  else if(q.primary<=62 && q.samples<=125 && q.evidence<=125)recovery=false;
  return recovery?Decision{2,1,0,1}:Decision{3,8,6000,1};
 }
};
#if BODAQS_ADAPTIVE_DRAIN_OWNER
#if BODAQS_PRODUCTION_RECORDING
inline void bootGate(){}
#else
void bootGate();
#endif
void runOwner(bool (*isActive)(),uint64_t (*context)(),void (*service)());
#else
inline void bootGate(){}
#endif
}
