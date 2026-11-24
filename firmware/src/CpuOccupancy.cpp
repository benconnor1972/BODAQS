#include "CpuOccupancy.h"
#if BODAQS_CPU_OCCUPANCY
#include <Arduino.h>
#include <atomic>
#include <cstring>
#include <new>
#include "driver/periph_ctrl.h"
#include "soc/interrupts.h"
#include "esp_ipc.h"
#include "esp_timer.h"
#include "esp_cpu.h"
#include "esp_heap_caps.h"
#include "esp_intr_alloc.h"
#include "esp_attr.h"
#include "hal/timer_ll.h"
#include "FirmwareInfo.h"
namespace CpuOccupancy {
struct State {
 Snapshot snapshot;
 std::atomic<uintptr_t> handles[TaskCount]{};
 std::atomic<unsigned> phase{Inactive};
 bool selected=false,initialized[2]={},registered[2]={};
 intr_handle_t interrupts[2]={};
 uintptr_t idleHandles[2]={};
};
// Only this pointer uses RTC slow SRAM; the live counters and atomics are
// explicitly allocated from ordinary internal RAM. Boot always replaces it.
static RTC_SLOW_ATTR State* state;
static_assert(std::atomic<uintptr_t>::is_always_lock_free,"ISR handle reads must not lock");
static_assert(std::atomic<unsigned>::is_always_lock_free,"ISR marker reads must not lock");
static void sample(void* argument){
 const unsigned cpu=static_cast<unsigned>(reinterpret_cast<uintptr_t>(argument));
 const uint32_t before=esp_cpu_get_ccount();
 auto& core=state->snapshot.cores[cpu];const auto timer=TIMER_0;
 auto* hw=TIMER_LL_GET_HW(cpu);hw->int_clr_timers.val=1u<<timer;
 const unsigned marker=state->phase.load(std::memory_order_relaxed);
 const auto task=reinterpret_cast<uintptr_t>(xTaskGetCurrentTaskHandleForCPU(cpu));
 const auto remote=reinterpret_cast<uintptr_t>(xTaskGetCurrentTaskHandleForCPU(1-cpu));
 unsigned kind=task==state->idleHandles[cpu]?Idle:Other;
 for(unsigned i=0;i<TaskCount;++i)if(i!=Idle && i!=Other && task && task==state->handles[i].load(std::memory_order_relaxed)){kind=i;break;}
 const auto owner=state->handles[Acquisition].load(std::memory_order_relaxed);
 const unsigned location=owner && task==owner?0:owner && remote==owner?1:2;
 if(state->snapshot.enabled)record(core,uint64_t(esp_timer_get_time())-state->snapshot.originUs,kind,marker,location,marker==state->phase.load(std::memory_order_relaxed));
 const uint32_t next=nextInterval(core.seed);core.requestedUs=next;
 uint64_t tick=0;timer_ll_get_counter_value(hw,timer,&tick);
 timer_ll_set_alarm_value(hw,timer,tick+next);
 timer_ll_set_alarm_enable(hw,timer,true);
 const auto cycles=uint32_t(esp_cpu_get_ccount()-before);core.overheadCycles+=cycles;
 if(cycles>core.maxOverheadCycles)core.maxOverheadCycles=cycles;
}
struct Operation {unsigned core;bool start;esp_err_t result=ESP_OK;};
struct IpcStackSample {
 Core& core;
 ~IpcStackSample(){const auto unused=uxTaskGetStackHighWaterMark(nullptr);if(unused<core.ipcStackUnusedMin)core.ipcStackUnusedMin=unused;}
};
static void timerOperation(void* argument){
 auto& op=*static_cast<Operation*>(argument);const unsigned cpu=op.core;
 IpcStackSample stack{state->snapshot.cores[cpu]};
 const auto timer=TIMER_0;
 auto* hw=TIMER_LL_GET_HW(cpu);
 if(state->initialized[cpu]){
  timer_ll_set_counter_enable(hw,timer,false);
  timer_ll_set_alarm_enable(hw,timer,false);
  hw->int_clr_timers.val=1u<<timer;
 }
 if(!op.start){
  if(state->registered[cpu]){
   op.result=esp_intr_disable(state->interrupts[cpu]);if(op.result!=ESP_OK)return;
   op.result=esp_intr_free(state->interrupts[cpu]);if(op.result!=ESP_OK)return;
   state->interrupts[cpu]=nullptr;state->registered[cpu]=false;
  }
  auto& c=state->snapshot.cores[cpu];
  if(state->snapshot.enabled && c.startedUs && !c.stoppedUs){
   c.stoppedUs=esp_timer_get_time();const auto relative=c.stoppedUs-state->snapshot.originUs;
   if(relative>=c.lastUs){c.tailUs=relative-c.lastUs;c.unknownUs+=c.tailUs;}
  }
  return;
 }
 if(!state->initialized[cpu]){
  // T0 in each group is reserved by this diagnostic only. Do not reset the
  // group or modify watchdog registers. Enable T0's mask once at boot;
  // later stop uses its counter and interrupt allocation, avoiding a shared
  // interrupt-enable-register RMW while other firmware is running.
  if(timer_ll_get_counter_enable(hw,timer)){op.result=ESP_ERR_INVALID_STATE;return;}
  periph_module_enable(cpu==0?PERIPH_TIMG0_MODULE:PERIPH_TIMG1_MODULE);
  timer_ll_set_counter_enable(hw,timer,false);
  timer_ll_set_alarm_enable(hw,timer,false);
  timer_ll_set_use_xtal(hw,timer,false);
  timer_ll_set_divider(hw,timer,80);
  timer_ll_set_counter_increase(hw,timer,true);
  timer_ll_set_auto_reload(hw,timer,false);
  hw->int_clr_timers.val=1u<<timer;
  timer_ll_intr_enable(hw,timer);
  state->initialized[cpu]=true;
 }
 if(!state->registered[cpu]){
  op.result=esp_intr_alloc(cpu==0?ETS_TG0_T0_LEVEL_INTR_SOURCE:ETS_TG1_T0_LEVEL_INTR_SOURCE,ESP_INTR_FLAG_INTRDISABLED,sample,reinterpret_cast<void*>(uintptr_t(cpu)),&state->interrupts[cpu]);
  if(op.result!=ESP_OK)return;
  state->registered[cpu]=true;
 }
 if(!state->snapshot.enabled)return; // OFF reserves the same callback/driver resources.
 timer_ll_set_counter_value(hw,timer,0);
 hw->int_clr_timers.val=1u<<timer;
 auto& core=state->snapshot.cores[cpu];core.seed=(0x91ab3271u+cpu*0x372819u+uint32_t(state->snapshot.context))^uint32_t(state->snapshot.originUs);
 state->idleHandles[cpu]=reinterpret_cast<uintptr_t>(xTaskGetIdleTaskHandleForCPU(cpu));
 timer_ll_set_alarm_value(hw,timer,nextInterval(core.seed));
 timer_ll_set_alarm_enable(hw,timer,true);
 core.startedUs=esp_timer_get_time();core.lastUs=core.startedUs-state->snapshot.originUs;
 op.result=esp_intr_enable(state->interrupts[cpu]);if(op.result!=ESP_OK)return;
 timer_ll_set_counter_enable(hw,timer,true);
}
static bool operate(unsigned cpu,bool start){
 Operation op={cpu,start};const auto r=esp_ipc_call_blocking(cpu,timerOperation,&op);
 if(r!=ESP_OK || op.result!=ESP_OK){state->snapshot.error=static_cast<uint32_t>(r!=ESP_OK?r:op.result);state->snapshot.valid=false;return false;}
 return true;
}
void bindTask(Task kind,uintptr_t handle){if(kind<TaskCount)state->handles[kind].store(handle,std::memory_order_relaxed);}
bool retire(uint64_t context){
 if(!state || context!=state->snapshot.context || !context)return false;
 // OFF sessions own no callbacks. A previous ON/partial session must still
 // retire on both owning cores; selection alone is not retirement proof.
 bool stopped=true;
 if(state->snapshot.enabled || state->registered[0] || state->registered[1]){
  const bool a=operate(0,false),b=operate(1,false);stopped=a&&b;
 }
 state->snapshot.retired=stopped;
 if(!state->snapshot.retired){state->snapshot.valid=false;return false;}
 state->snapshot.mhzEnd=getCpuFrequencyMhz();state->snapshot.valid &= state->snapshot.retired && state->snapshot.mhzEnd==state->snapshot.mhzStart;
 if(state->snapshot.enabled)for(const auto& c:state->snapshot.cores){
  uint32_t count=0;for(const auto& b:c.bins)count+=b.samples;
  state->snapshot.valid &= !c.overflow && count && c.stoppedUs>c.startedUs &&
      c.unknownUs<(c.stoppedUs-c.startedUs)/10;
 }
 return state->snapshot.retired;
}
bool begin(uint64_t context){
 if(!context || !state)return false;
 // Both callbacks are stopped on their own cores before reset/publication.
 if(state->selected || state->registered[0] || state->registered[1]){
  const bool stopped0=operate(0,false),stopped1=operate(1,false);
  if(!stopped0 || !stopped1)return false;
 }
 state->snapshot.~Snapshot();new(&state->snapshot) Snapshot();
 state->snapshot.context=context;state->snapshot.originUs=esp_timer_get_time();state->snapshot.enabled=state->selected;
 state->snapshot.valid=true;state->snapshot.mhzStart=getCpuFrequencyMhz();state->phase.store(Inactive);
 // Boot has already reserved/stopped these diagnostic timers. With sampling
 // OFF there is no reason to reallocate interrupts through the small SDK IPC
 // stacks at recording START. Keep the disabled snapshot/context lifecycle.
 if(state->selected && (!operate(0,true) || !operate(1,true))){retire(context);return false;}
 return true;
}
const Snapshot* snapshot(uint64_t context){return state && state->snapshot.context==context && state->snapshot.retired?&state->snapshot:nullptr;}
Phase exchangePhase(Phase next){
 if(!state->selected || reinterpret_cast<uintptr_t>(xTaskGetCurrentTaskHandle())!=state->handles[Acquisition].load(std::memory_order_relaxed))return Inactive;
 return static_cast<Phase>(state->phase.exchange(next,std::memory_order_relaxed));
}
void restorePhase(Phase previous){(void)exchangePhase(previous);}
#include "CpuOccupancyCalibration.h"
void bootGate(){
 state=nullptr;
 void* allocation=heap_caps_malloc(sizeof(State),MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
 if(!allocation){Serial.println("[CPU] internal counter reservation failed; diagnostic cannot start");for(;;)delay(1000);}
 state=new(allocation) State();
 bindTask(Main,reinterpret_cast<uintptr_t>(xTaskGetCurrentTaskHandle()));
 state->snapshot.originUs=esp_timer_get_time();
 // Reserve identical driver objects/interrupt slots in OFF and ON modes.
 const bool reserved0=operate(0,true),reserved1=operate(1,true);
 const bool stopped0=operate(0,false),stopped1=operate(1,false);
 if(!reserved0 || !reserved1 || !stopped0 || !stopped1){Serial.println("[CPU] timer reservation failed");for(;;)delay(1000);}
#if defined(BODAQS_BENCH_AUTO_BOOT) && BODAQS_BENCH_AUTO_BOOT
 state->selected=false;
 Serial.printf("{\"schema\":\"bodaqs.cpu-occupancy-gate.v1\",\"type\":\"selected\",\"recipe\":\"%s\",\"enabled\":false,\"automatic\":true}\n",FirmwareInfo::buildRecipe());
 return;
#endif
 char line[20]={};unsigned used=0;bool overflow=false;uint32_t announcement=0;
 for(;;){
  if(!announcement || millis()-announcement>2000){announcement=millis();Serial.printf("{\"schema\":\"bodaqs.cpu-occupancy-gate.v1\",\"type\":\"ready\",\"recipe\":\"%s\",\"commands\":\"cpu test,cpu off,cpu on\"}\n",FirmwareInfo::buildRecipe());}
  while(Serial.available()){
   const char ch=Serial.read();if(ch=='\r')continue;
   if(ch=='\n'){
    line[used]=0;
    if(!overflow && !strcmp(line,"cpu test")){(void)calibrate();used=0;overflow=false;announcement=0;continue;}
    if(!overflow && (!strcmp(line,"cpu on") || !strcmp(line,"cpu off"))){state->selected=!strcmp(line,"cpu on");Serial.printf("{\"schema\":\"bodaqs.cpu-occupancy-gate.v1\",\"type\":\"selected\",\"recipe\":\"%s\",\"enabled\":%s}\n",FirmwareInfo::buildRecipe(),state->selected?"true":"false");Serial.flush();return;}
    used=0;overflow=false;
   }else if(used<sizeof(line)-1)line[used++]=ch;else overflow=true;
  }
  delay(10);
 }
}
}
#endif
