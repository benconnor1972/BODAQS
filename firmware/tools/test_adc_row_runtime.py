"""Actual row deadline planner and timer/worker gate startup seam."""
from pathlib import Path
import subprocess,tempfile
from runtime_test_helpers import definition
r=Path(__file__).resolve().parents[1];s=(r/'src/AnalogInputManager.cpp').read_text()
fixture=r"""
#define AIN_LOGE(...) ((void)0)
#include <atomic>
#include <cassert>
#include "AdcRowSchedule.h"
using SemaphoreHandle_t=bool*;
bool gates[2]={};SemaphoreHandle_t rowGates[2]={&gates[0],&gates[1]};
void* rowTimer=(void*)1;std::atomic<bool> rowActive{false};int64_t rowOrigin=0;
namespace board {constexpr unsigned BOARD_MAX_EXTERNAL_ADCS=2;}
int s_effectiveHz=500;struct Ads{int activeChannels=0;void* asyncTask=nullptr;};
struct Devices {Ads values[board::BOARD_MAX_EXTERNAL_ADCS];Ads& operator[](unsigned i){assert(i<board::BOARD_MAX_EXTERNAL_ADCS);return values[i];}}s_ads;
int64_t now=1000000;int period=0,timerResult=0;constexpr int ESP_OK=0;
int64_t esp_timer_get_time(){return now;}
void xSemaphoreGive(SemaphoreHandle_t gate){*gate=true;}
int esp_timer_start_periodic(void*,int p){period=p;return timerResult;}
// FUNCTIONS
int main(){
 int64_t previous=-1;auto d=AdcRowSchedule::claim(999,1000,previous);assert(!d.acquire && !d.observed && previous==-1);
 d=AdcRowSchedule::claim(1000,1000,previous);assert(d.acquire && d.observed && !d.startLagUs && d.deadline==2800 && !d.missed);
 assert(!AdcRowSchedule::claim(1100,1000,previous).acquire);
 d=AdcRowSchedule::claim(3400,1000,previous);
#if BODAQS_ADC_ROW_MAX_START_LAG_US == 500
 assert(d.acquire && d.observed && d.startLagUs==400 && d.missed==0 && d.deadline==4800);
#else
 assert(!d.acquire && d.observed && d.startLagUs==400 && d.missed==1);
#endif
 d=AdcRowSchedule::claim(7100,1000,previous);assert(d.acquire && d.missed==1 && d.deadline==8800);
 previous=-1;assert(AdcRowSchedule::claim(1000,1000,previous).acquire);
 previous=-1;d=AdcRowSchedule::claim(1300,1000,previous);assert(d.acquire && d.deadline==2800);
 previous=-1;d=AdcRowSchedule::claim(1301,1000,previous);
#if BODAQS_ADC_ROW_MAX_START_LAG_US == 500
 assert(d.acquire);
#else
 assert(!d.acquire && d.missed==1);
#endif
 previous=-1;d=AdcRowSchedule::claim(1500,1000,previous);
#if BODAQS_ADC_ROW_MAX_START_LAG_US == 500
 assert(d.acquire && d.deadline==2800);
#else
 assert(!d.acquire && d.missed==1);
#endif
 previous=-1;d=AdcRowSchedule::claim(1501,1000,previous);assert(!d.acquire && d.missed==1);
 s_ads[0]={1,(void*)1};s_ads[1]={1,(void*)2};assert(beginRowPacing()==1001800 && period==2000);
 assert(rowActive && gates[0] && gates[1]);
 rowActive=false;for(auto& g:gates)g=false;rowTick(nullptr);for(auto g:gates)assert(!g);
 s_effectiveHz=200;assert(!beginRowPacing());s_effectiveHz=500;
 s_ads[1].activeChannels=2;assert(!beginRowPacing());s_ads[1].activeChannels=1;
 s_ads[1].asyncTask=nullptr;assert(!beginRowPacing());s_ads[1].asyncTask=(void*)2;
 timerResult=-1;assert(!beginRowPacing() && !rowActive);
}
"""
fixture=fixture.replace('// FUNCTIONS',definition(s,'void rowTick(void*)')+'\n'+definition(s,'int64_t beginRowPacing()'))
with tempfile.TemporaryDirectory() as temp:
 cpp=Path(temp)/'row.cpp';exe=Path(temp)/'row.exe';cpp.write_text(fixture)
 for cutoff in (None,500):
  flags=[] if cutoff is None else ['-DBODAQS_ADC_ROW_MAX_START_LAG_US=500']
  subprocess.run(['C:/msys64/ucrt64/bin/g++.exe','-std=c++17','-Wall','-Wextra','-Werror',*flags,'-I',str(r/'src'),str(cpp),'-o',str(exe)],check=True)
  subprocess.run([str(exe)],check=True)

print('Actual row planner: default300/selected500 cutoff boundaries, unchanged1800 completion, early/duplicate/late/skipped epochs, restart, exact scope, timer failure and inactive callback PASS')
