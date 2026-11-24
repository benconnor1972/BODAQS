// Included inside CpuOccupancy: pre-board, opt-in controlled workloads.
// Workers are deleted while parked, after both observer interrupts are retired.
struct CalibrationJob {
 TaskHandle_t controller=nullptr,worker=nullptr;
 unsigned mode=0;
 uint64_t elapsedUs=0,busyUs=0;
 uint32_t checksum=0;
};
struct CalibrationBarrier {unsigned core=2,priority=~0u;};
static void calibrationBarrier(void* argument){
 auto& result=*static_cast<CalibrationBarrier*>(argument);
 result.core=xPortGetCoreID();result.priority=uxTaskPriorityGet(nullptr);
}
static bool calibrationParked(unsigned count){
 // Installed SDK runs IPC at the caller's priority. A priority-1 IPC
 // callback cannot run on a core while its pinned priority-2 worker is
 // ready. After completion that worker's only blocking point is the next
 // notification wait. No new work is notified until this barrier returns.
 static_assert(CONFIG_ESP_IPC_USES_CALLERS_PRIORITY==1,"Calibration parking needs caller-priority IPC");
 if(uxTaskPriorityGet(nullptr)!=1)return false;
 for(unsigned cpu=0;cpu<count;++cpu){
  CalibrationBarrier result;
  if(esp_ipc_call_blocking(cpu,calibrationBarrier,&result)!=ESP_OK || result.core!=cpu || result.priority!=1)return false;
 }
 return true;
}
static void calibrationHalt(){
 Serial.println("[CPU] calibration retirement failed; restart required");Serial.flush();
 for(;;)delay(1000);
}
static void calibrationWorker(void* argument){
 auto& job=*static_cast<CalibrationJob*>(argument);
 for(;;){
  ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
  const auto start=esp_timer_get_time();uint32_t value=0x17c9e32bu;
  job.busyUs=0;
  if(job.mode==0){
   Scope marker(Preparing);
   // Fixed instruction work: elapsed time includes the complete interrupt
   // entry/exit and scheduling effect, unlike the ISR's lower-bound counter.
   for(unsigned i=0;i<10000000;++i){
    value^=value<<13;value^=value>>17;value^=value<<5;
    asm volatile("" : "+r"(value));
   }
  }else if(job.mode==1){
   Scope marker(Sleep);vTaskDelay(pdMS_TO_TICKS(300));
  }else if(job.mode==3){
   Scope marker(Preparing);
   while(esp_timer_get_time()-start<300000)asm volatile("");
  }else{
   while(esp_timer_get_time()-start<500000){
    const auto busyStart=esp_timer_get_time();
    {Scope marker(Preparing);while(esp_timer_get_time()-busyStart<100)asm volatile("");}
    job.busyUs+=esp_timer_get_time()-busyStart;
    {Scope marker(Sleep);vTaskDelay(1);}
   }
  }
  job.checksum=value;job.elapsedUs=esp_timer_get_time()-start;
  xTaskNotifyGive(job.controller);
 }
}
static bool calibrate(){
 if(uxTaskPriorityGet(nullptr)!=1){Serial.println("[CPU] calibration requires priority-1 controller");return false;}
 CalibrationJob jobs[2];bool passed=true;unsigned created=0;
 const bool originalSelection=state->selected;
 const auto controller=xTaskGetCurrentTaskHandle();
 for(unsigned cpu=0;cpu<2;++cpu){
  jobs[cpu].controller=controller;
  if(xTaskCreatePinnedToCore(calibrationWorker,"CPUcal",2048,&jobs[cpu],2,&jobs[cpu].worker,cpu)!=pdPASS){passed=false;break;}
  ++created;
 }
 if(created!=2){
  if(!calibrationParked(created))calibrationHalt();
  for(unsigned i=0;i<created;++i)vTaskDelete(jobs[i].worker);
  Serial.println("{\"schema\":\"bodaqs.cpu-calibration.v1\",\"type\":\"finished\",\"passed\":false,\"error\":\"task_allocation\"}");
  return false;
 }
 bindTask(Acquisition,reinterpret_cast<uintptr_t>(jobs[0].worker));
 bindTask(Sampler,reinterpret_cast<uintptr_t>(jobs[1].worker));
 uint64_t fixedUs[4][2]={};
 Serial.printf("{\"schema\":\"bodaqs.cpu-calibration.v1\",\"type\":\"begin\",\"recipe\":\"%s\",\"mhz\":%u}\n",FirmwareInfo::buildRecipe(),getCpuFrequencyMhz());Serial.flush();
 for(unsigned trial=0;trial<8;++trial){
  // Fixed work OFF/ON/ON/OFF; idle; single busy core; periodic tick-shaped
  // bursts twice, with distinct timer seeds and natural initial offsets.
  state->selected=trial!=0 && trial!=3;
  jobs[0].mode=jobs[1].mode=trial<4?0:trial==4?1:trial==5?3:2;
  if(trial==5)jobs[1].mode=1;
  const uint64_t context=0xc9200000u+trial;
  if(!begin(context)){
   passed=false;
   // begin may have failed before publishing this context, or while
   // unwinding a partial start. Confirm both physical stops regardless.
   const bool stopped0=operate(0,false),stopped1=operate(1,false);
   if(!stopped0 || !stopped1 || !calibrationParked(2))calibrationHalt();
   break;
  }
  ulTaskNotifyTake(pdTRUE,0);
  xTaskNotifyGive(jobs[0].worker);xTaskNotifyGive(jobs[1].worker);
  unsigned done=0;
  while(done<2 && ulTaskNotifyTake(pdFALSE,pdMS_TO_TICKS(3000)))++done;
  const bool stopped=retire(context);
  if(done!=2 || !stopped || !calibrationParked(2)){
   // No stack-backed job or task handle may outlive this function.
   // A failing/unresponsive worker therefore stops qualification here.
   calibrationHalt();
  }
  const auto* capture=snapshot(context);
  bool trialPassed=capture && capture->valid && capture->mhzStart==240 && capture->mhzEnd==240;
  for(unsigned cpu=0;cpu<2;++cpu){
   const auto& c=capture->cores[cpu];uint32_t counts[TaskCount]={},here[PhaseCount]={},absent[PhaseCount]={},samples=0;
   for(const auto& b:c.bins){
    samples+=b.samples;for(unsigned k=0;k<TaskCount;++k)counts[k]+=b.tasks[k];
    for(unsigned k=0;k<PhaseCount;++k){here[k]+=b.ownerHere[k];absent[k]+=b.ownerAbsent[k];}
   }
   const unsigned identity=cpu==0?Acquisition:Sampler;
   const unsigned workerUnused=uxTaskGetStackHighWaterMark(jobs[cpu].worker);
   if(workerUnused<256 || c.ipcStackUnusedMin<128)trialPassed=false;
   if(trial<4)fixedUs[trial][cpu]=jobs[cpu].elapsedUs;
   if(state->selected){
    if(samples<150)trialPassed=false;
    const uint64_t span=c.stoppedUs-c.startedUs;
    if(c.intervalMin<400 || c.intervalMax>3000 || uint64_t(samples)*1200<span || uint64_t(samples)*800>span)trialPassed=false;
    if(uint64_t(c.intervalHist[0]+c.intervalHist[1])*100>samples*2u || uint64_t(c.intervalHist[6]+c.intervalHist[7])*100>samples*5u)trialPassed=false;
    for(unsigned k=2;k<=5;++k)if(uint64_t(c.intervalHist[k])*100<samples*12u || uint64_t(c.intervalHist[k])*100>samples*38u)trialPassed=false;
    const uint64_t fraction=samples?uint64_t(counts[identity])*10000/samples:0;
    if((jobs[cpu].mode==0 || jobs[cpu].mode==3) && fraction<9000)trialPassed=false;
    if(jobs[cpu].mode==1 && (fraction>1000 || uint64_t(counts[Idle])*100<samples*85u))trialPassed=false;
    if(jobs[cpu].mode==2){
     const uint64_t expected=jobs[cpu].elapsedUs?jobs[cpu].busyUs*10000/jobs[cpu].elapsedUs:0;
     if(fraction>expected+600 || fraction+600<expected)trialPassed=false;
     // Reject a grossly phase-locked observer, rather than assuming jitter
     // means its samples actually covered the tick phase on this device.
     for(auto n:c.phaseHist)if(uint64_t(n)*100<samples*3u || uint64_t(n)*100>samples*20u)trialPassed=false;
    }
    if(cpu==0){
     if(jobs[cpu].mode!=1 && uint64_t(here[Preparing])*100<uint64_t(counts[Acquisition])*70)trialPassed=false;
     if(jobs[cpu].mode==1 && uint64_t(absent[Sleep])*100<uint64_t(samples)*85)trialPassed=false;
     if(jobs[cpu].mode==2 && uint64_t(absent[Sleep])*100<uint64_t(samples-counts[Acquisition])*80)trialPassed=false;
    }
   }
   Serial.printf("{\"schema\":\"bodaqs.cpu-calibration.v1\",\"type\":\"core\",\"trial\":%u,\"enabled\":%s,\"core\":%u,\"mode\":%u,\"elapsed_us\":%llu,\"busy_us\":%llu,\"checksum\":%u,\"samples\":%u,\"unknown_us\":%llu,\"callback_cycles_lower_bound\":%llu,\"max_callback_cycles_lower_bound\":%u,\"tasks\":[",trial,state->selected?"true":"false",cpu,jobs[cpu].mode,jobs[cpu].elapsedUs,jobs[cpu].busyUs,jobs[cpu].checksum,samples,c.unknownUs,c.overheadCycles,c.maxOverheadCycles);
   for(unsigned k=0;k<TaskCount;++k)Serial.printf("%s%u",k?",":"",counts[k]);
   Serial.print("],\"millisecond_phase_hist\":[");for(unsigned k=0;k<10;++k)Serial.printf("%s%u",k?",":"",c.phaseHist[k]);
   Serial.printf("],\"interval_min_us\":%u,\"interval_max_us\":%u,\"interval_hist_250us_capped7\":[",c.intervalMin,c.intervalMax);
   for(unsigned k=0;k<8;++k)Serial.printf("%s%u",k?",":"",c.intervalHist[k]);
   Serial.print("],\"owner_here\":[");for(unsigned k=0;k<PhaseCount;++k)Serial.printf("%s%u",k?",":"",here[k]);
   Serial.print("],\"owner_absent\":[");for(unsigned k=0;k<PhaseCount;++k)Serial.printf("%s%u",k?",":"",absent[k]);Serial.println("]}");
   Serial.printf("{\"schema\":\"bodaqs.cpu-calibration.v1\",\"type\":\"stack\",\"trial\":%u,\"core\":%u,\"worker_unused_min_bytes\":%u,\"ipc_unused_min_bytes\":%u}\n",trial,cpu,workerUnused,c.ipcStackUnusedMin);
  }
  passed &=trialPassed;
  Serial.printf("{\"schema\":\"bodaqs.cpu-calibration.v1\",\"type\":\"trial\",\"trial\":%u,\"passed\":%s}\n",trial,trialPassed?"true":"false");Serial.flush();
 }
 for(unsigned cpu=0;cpu<2;++cpu){
  const uint64_t off=fixedUs[0][cpu]+fixedUs[3][cpu],on=fixedUs[1][cpu]+fixedUs[2][cpu];
  // Paired fixed-work totals, with a deliberately coarse 5% observer budget.
  const bool overheadPassed=off && on && on*100<=off*105 && on*100>=off*90;
  passed &=overheadPassed;
  Serial.printf("{\"schema\":\"bodaqs.cpu-calibration.v1\",\"type\":\"overhead\",\"core\":%u,\"off_us\":%llu,\"on_us\":%llu,\"passed\":%s}\n",cpu,off,on,overheadPassed?"true":"false");
 }
 for(auto& job:jobs)vTaskDelete(job.worker);
 bindTask(Acquisition,0);bindTask(Sampler,0);state->selected=originalSelection;
 Serial.printf("{\"schema\":\"bodaqs.cpu-calibration.v1\",\"type\":\"finished\",\"passed\":%s}\n",passed?"true":"false");Serial.flush();
 return passed;
}
