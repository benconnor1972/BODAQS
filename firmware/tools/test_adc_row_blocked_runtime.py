"""Actual blocked row-wait helper: deadlines, notification races and failures."""
from pathlib import Path
import subprocess,tempfile
from runtime_test_helpers import definition
r=Path(__file__).resolve().parents[1];s=(r/'src/LoggingManager.cpp').read_text()
body='\n'.join(definition(s,n) for n in ('static void rowSampleTick_(void* argument)','static bool sampleWaitAppointment_(int64_t deadline,bool* blocked=nullptr)'))
fixture=r"""
#include <cassert>
#include <cstdint>
#define LOGGING_LOGE(...) ((void)0)
#define pdMS_TO_TICKS(x) (x)
constexpr int pdTRUE=1,ESP_OK=0;
using TaskHandle_t=void*;using esp_timer_handle_t=void*;
struct esp_timer_create_args_t{void(*callback)(void*)=nullptr;void* arg=nullptr;const char* name=nullptr;};
static esp_timer_handle_t s_rowSampleTimer=nullptr;static bool s_running=true,active=false;
static int64_t now=1000,due=0;static int notified=0,arms=0,blocks=0,stops=0;
static bool failCreate=false,failArm=false,stopAtClear=false,stopAtArm=false;static int mode=0;
static esp_timer_create_args_t saved;static void* task=(void*)1;
int64_t esp_timer_get_time(){return now;}
TaskHandle_t xTaskGetCurrentTaskHandle(){return task;}
void xTaskNotifyGive(TaskHandle_t t){assert(t==task);++notified;}
int esp_timer_create(esp_timer_create_args_t* args,esp_timer_handle_t* h){if(failCreate)return -1;saved=*args;*h=(void*)2;return ESP_OK;}
int esp_timer_stop(esp_timer_handle_t){++stops;active=false;return ESP_OK;}
int esp_timer_start_once(esp_timer_handle_t,uint64_t delay){++arms;if(failArm)return -1;active=true;due=now+delay;if(stopAtArm){s_running=false;xTaskNotifyGive(task);}return ESP_OK;}
uint32_t ulTaskNotifyTake(int,int ticks){
 if(!ticks){int n=notified;notified=0;if(stopAtClear){s_running=false;xTaskNotifyGive(task);}return n;}
 ++blocks;if(notified){notified=0;return 1;}
 if(mode==1){mode=0;now+=10;return 1;} // early pulse
 if(mode==2){now+=11000;return 0;} // missing timer callback
 assert(active);now=due;saved.callback(saved.arg);assert(notified);notified=0;return 1;
}
// ACTUAL
void reset(){s_running=true;active=false;now=1000;notified=arms=blocks=stops=0;failCreate=failArm=stopAtClear=stopAtArm=false;mode=0;}
int main(){
 reset();bool blocked=false;assert(sampleWaitAppointment_(2800,&blocked) && blocked);assert(now==2800 && arms==1 && blocks==1 && !active);
 auto handle=s_rowSampleTimer;reset();notified=3;assert(sampleWaitAppointment_(2800));assert(s_rowSampleTimer==handle && now==2800 && blocks==1);
 reset();mode=1;assert(sampleWaitAppointment_(2800));assert(now==2800 && arms==2 && blocks==2 && !active);
 reset();now=2800;blocked=true;assert(sampleWaitAppointment_(2800,&blocked) && !blocked && arms==0 && blocks==0);
 reset();s_running=false;assert(sampleWaitAppointment_(2800) && arms==0);
 reset();stopAtClear=true;assert(sampleWaitAppointment_(2800) && arms==0 && !active);
 reset();stopAtArm=true;assert(sampleWaitAppointment_(2800) && arms==1 && blocks==1 && !active);
 reset();failArm=true;assert(!sampleWaitAppointment_(2800) && !active && blocks==0);
 reset();s_rowSampleTimer=nullptr;failCreate=true;assert(!sampleWaitAppointment_(2800) && arms==0);
 reset();mode=2;assert(!sampleWaitAppointment_(2800) && !active);
 int before=arms;rowSampleTick_(task);assert(arms==before); // late callback never rearms
 reset();assert(sampleWaitAppointment_(2800) && !active); // restart
}
"""
with tempfile.TemporaryDirectory() as d:
 cpp=Path(d)/'wait.cpp';exe=Path(d)/'wait.exe';cpp.write_text(fixture.replace('// ACTUAL',body))
 subprocess.run(['C:/msys64/ucrt64/bin/g++.exe','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
assert 'if(blockedForRow)lastBlockUs=esp_timer_get_time();' in s
assert 'const bool appointmentReady=sampleWaitAppointment_(next_us,&blockedForRow);' in s
stop=s[s.index('void LoggingManager::stop(StopReason'):]
assert stop.index('s_running = false;')<stop.index('if(s_sampleTask)xTaskNotifyGive(s_sampleTask);')<stop.index('while (s_sampleInProgress.load())')
assert s.index('if(!s_running)continue;',s.index('const bool appointmentReady'))<s.index('// Wait for the next scheduled slot.')
print('Actual blocked row wait: due/expired deadline, stale/early notifications, STOP during clear/arm/wait, create/arm/timeout failures, persistent callback, restart and stop/wait wiring PASS; not a FreeRTOS timing simulation')
