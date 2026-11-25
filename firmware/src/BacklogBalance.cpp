#include "RecordingFeatures.h"
#include "BacklogBalance.h"
#if BODAQS_ADAPTIVE_DRAIN_OWNER
#include <Arduino.h>
#include <cstring>
#include "FirmwareInfo.h"
#include "LoggingManager.h"
#include "StorageManager.h"
#include "RemoteImuRecording.h"
#include "CpuOccupancy.h"
#include "ControlPollingDiagnostics.h"
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
namespace BacklogBalance {
namespace {
#if BODAQS_PRODUCTION_RECORDING
bool adaptive = true;
#else
bool adaptive = false;
#endif
Pressure pressure(){
 Pressure q;q.running=LoggingManager::isRunning();if(!q.running)return q;
 const auto cap=StorageManager_primaryCapacityForBalance();
 q.valid=cap!=0;
 if(cap){const auto pending=StorageManager_primaryPendingForBalance();q.primary=pending>=cap?1000:unsigned(1000*pending/cap);}
 bool remote=false;RemoteImuRecording::queuePressureForBalance(q.samples,q.evidence,remote);
 q.valid &= remote;return q;
}
struct Counters {
 uint64_t context=0;uint32_t services=0,bursts=0,boosted=0,recovery=0,switches=0;
 unsigned primaryPeak=0,samplePeak=0,evidencePeak=0;
 void observe(const Pressure& q){
  if(q.primary>primaryPeak)primaryPeak=q.primary;
  if(q.samples>samplePeak)samplePeak=q.samples;
  if(q.evidence>evidencePeak)evidencePeak=q.evidence;
 }
 void print(){
#if !BODAQS_PRODUCTION_RECORDING
 Serial.printf("{\"schema\":\"bodaqs.backlog-balance.v1\",\"type\":\"retired\",\"context\":\"%llu\",\"adaptive\":%s,\"services\":%lu,\"bursts\":%lu,\"boosted_bursts\":%lu,\"recovery_bursts\":%lu,\"priority_switches\":%lu,\"primary_peak_permille\":%u,\"sample_peak_permille\":%u,\"evidence_peak_permille\":%u}\n",
  (unsigned long long)context,adaptive?"true":"false",(unsigned long)services,(unsigned long)bursts,
  (unsigned long)boosted,(unsigned long)recovery,(unsigned long)switches,primaryPeak,samplePeak,evidencePeak);
#endif
 }
};
}
#if !BODAQS_PRODUCTION_RECORDING
void bootGate(){
 char line[32]={};unsigned used=0;bool overflow=false;uint32_t announced=0;
 for(;;){
  if(!announced || millis()-announced>=2000){announced=millis();Serial.println("[BALANCE] select drain control or drain adaptive before startup");}
  while(Serial.available()){
   const char c=char(Serial.read());if(c=='\r')continue;
   if(c=='\n'){
    line[used]=0;
    if(!overflow && (!strcmp(line,"drain control") || !strcmp(line,"drain adaptive"))){
     adaptive=!strcmp(line,"drain adaptive");
     Serial.printf("{\"schema\":\"bodaqs.backlog-balance.v1\",\"type\":\"selected\",\"adaptive\":%s,\"recipe\":\"%s\"}\n",adaptive?"true":"false",FirmwareInfo::buildRecipe());Serial.flush();return;
    }
    used=0;overflow=false;
   }else if(used<sizeof(line)-1)line[used++]=c;else overflow=true;
  }
  delay(10);
 }
}
#endif
void runOwner(bool (*isActive)(),uint64_t (*context)(),void (*service)()) {
 Policy policy;Counters stats,pending;bool have=false,havePending=false;unsigned priority=2;
 auto setPriority=[&](unsigned next){if(next!=priority){priority=next;++stats.switches;vTaskPrioritySet(nullptr,next);}};
 for(;;){
  if(!isActive()){
   setPriority(2);if(havePending){pending.print();havePending=false;}
   if(have){stats.print();have=false;stats={};policy=Policy{};}
   vTaskDelay(1);continue;
  }
  if(have && stats.context!=context()){setPriority(2);pending=stats;havePending=true;stats={};policy=Policy{};have=false;}
  if(!have){stats={};stats.context=context();have=true;}
  auto q=pressure();stats.observe(q);auto d=policy.decide(adaptive,q);setPriority(d.priority);
  ++stats.bursts;if(d.priority==3)++stats.boosted;else if(adaptive&&q.running)++stats.recovery;
  const uint32_t start=micros();
  for(unsigned i=0;i<d.calls && isActive();++i){
   {CpuOccupancy::Scope phase(CpuOccupancy::Preparing);service();}++stats.services;
   if(!isActive()) {d={2,8,0,1};setPriority(2);break;}
   q=pressure();stats.observe(q);
   const auto next=policy.decide(adaptive,q);
   if(next.priority!=d.priority){d=next;setPriority(next.priority);break;}
   if(d.budgetUs && uint32_t(micros()-start)>=d.budgetUs)break;
  }
#if BODAQS_ACQUISITION_PROFILE
  const uint32_t sleepStart=micros();
  if(isActive() && context()==stats.context)ControlPollingDiagnostics::profile(ControlPollingDiagnostics::Burst,start,sleepStart-start);
#endif
  // Real blocked state gives lower priorities a scheduling opportunity.
  // START/STOP lifecycle never retains the boosted priority.
  if(!isActive() || !LoggingManager::isRunning()){setPriority(2);d.sleepTicks=1;}
  {CpuOccupancy::Scope phase(CpuOccupancy::Sleep);vTaskDelay(d.sleepTicks);}
#if BODAQS_ACQUISITION_PROFILE
  if(isActive() && context()==stats.context)ControlPollingDiagnostics::profile(ControlPollingDiagnostics::Sleep,sleepStart,micros()-sleepStart);
#endif
 }
}
}
#endif
