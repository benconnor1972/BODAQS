#pragma once
#include <stdint.h>
#include <stddef.h>
#ifndef BODAQS_CPU_OCCUPANCY
#define BODAQS_CPU_OCCUPANCY 0
#endif
namespace CpuOccupancy {
enum Task : unsigned {Acquisition,Adc,Sampler,Storage,Main,Idle,Other,Calibration,TaskCount};
enum Phase : unsigned {Inactive,Preparing,BusWait,Transfer,Decode,Consumers,Sleep,PhaseCount};
constexpr unsigned binCount=10;
constexpr uint32_t binUs=20000000;
struct Bin {
 uint32_t tasks[TaskCount]={},ownerHere[PhaseCount]={},ownerAbsent[PhaseCount]={};
 uint32_t samples=0,ownerRemote=0,unstable=0,gaps=0;
};
struct Core {
 Bin bins[binCount];uint32_t seed=0,requestedUs=0,used=0,overflow=0;
 uint64_t lastUs=0,startedUs=0,stoppedUs=0,unknownUs=0,tailUs=0,overheadCycles=0;
 uint32_t maxOverheadCycles=0,intervalMin=UINT32_MAX,intervalMax=0,phaseHist[10]={},intervalHist[8]={};
 uint32_t ipcStackUnusedMin=UINT32_MAX;
};
struct Snapshot {
 uint64_t context=0,originUs=0;Core cores[2];
 bool enabled=false,retired=false,valid=false;uint32_t mhzStart=0,mhzEnd=0,error=0;
};
inline uint32_t nextInterval(uint32_t& seed){
 if(!seed)seed=0x91ab3271u;
 seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return 500+seed%1001;
}
// Pure counter update: gaps are reported as unknown, never credited as CPU time.
inline void record(Core& c,uint64_t relativeUs,unsigned task,unsigned phase,unsigned location,bool stable){
 const auto index=relativeUs/binUs;if(index>=binCount){++c.overflow;return;}
 if(index+1>c.used)c.used=index+1;
 auto& b=c.bins[index];
 const uint64_t elapsed=relativeUs-c.lastUs;c.lastUs=relativeUs;
 if(elapsed>3000){++b.gaps;c.unknownUs+=elapsed;return;}
 const auto dt=static_cast<uint32_t>(elapsed);if(dt<c.intervalMin)c.intervalMin=dt;
 if(dt>c.intervalMax)c.intervalMax=dt;
 ++c.phaseHist[(relativeUs%1000)/100];
 ++c.intervalHist[dt/250<7?dt/250:7];
 ++b.samples;++b.tasks[task<TaskCount?task:Other];
 if(!stable || phase>=PhaseCount){++b.unstable;return;}
 if(location==0)++b.ownerHere[phase];else if(location==1)++b.ownerRemote;else ++b.ownerAbsent[phase];
}
#if BODAQS_CPU_OCCUPANCY
void bindTask(Task,uintptr_t);
void bootGate();bool begin(uint64_t);bool retire(uint64_t);
const Snapshot* snapshot(uint64_t);
Phase exchangePhase(Phase);void restorePhase(Phase);
class Scope {
 Phase previous;
public: explicit Scope(Phase phase):previous(exchangePhase(phase)){} ~Scope(){restorePhase(previous);}
 Scope(const Scope&)=delete;Scope& operator=(const Scope&)=delete;
};
#else
inline void bindTask(Task,uintptr_t){} inline void bootGate(){}
inline bool begin(uint64_t){return true;} inline bool retire(uint64_t){return true;}
inline const Snapshot* snapshot(uint64_t){return nullptr;}
class Scope {public:explicit Scope(Phase){}};
#endif
}
