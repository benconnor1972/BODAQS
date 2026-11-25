"""Actual sampler wait seam: peer opportunity and fresh deadline observation."""
from pathlib import Path
import subprocess,tempfile
from runtime_test_helpers import definition
r=Path(__file__).resolve().parents[1];s=(r/'src/LoggingManager.cpp').read_text()
body=definition(s,'static int64_t sampleWaitNow_(int64_t deadline)')
fixture=r"""
#include <stdint.h>
#include <cassert>
static int64_t now=1000;static int calls=0;static int64_t advance=150;
int64_t esp_timer_get_time(){return now;}
void taskYIELD(){++calls;now+=advance;}
// ACTUAL
int main(){
 auto t=sampleWaitNow_(2800);
#if BODAQS_ADC_ROW_COOPERATIVE_WAIT
 assert(t==1150 && calls==1);
 advance=2000;t=sampleWaitNow_(2800);assert(t==3150 && calls==2);
 t=sampleWaitNow_(2800);assert(t==3150 && calls==2);
#else
 assert(t==1000 && calls==0);
#endif
 now=2800;calls=0;assert(sampleWaitNow_(2800)==2800 && calls==0);
}
"""
with tempfile.TemporaryDirectory() as d:
 cpp=Path(d)/'wait.cpp';exe=Path(d)/'wait.exe';cpp.write_text(fixture.replace('// ACTUAL',body))
 for enabled in (0,1):
  subprocess.run(['C:/msys64/ucrt64/bin/g++.exe','-std=c++17','-Wall','-Wextra','-Werror',f'-DBODAQS_ADC_ROW_COOPERATIVE_WAIT={enabled}',str(cpp),'-o',str(exe)],check=True)
  subprocess.run([str(exe)],check=True)
 assert 'int64_t now_us = sampleWaitNow_(next_us);' in s
print('Actual sampler wait: default unchanged, enabled peer yield, post-yield clock, expired/due deadline PASS; not a FreeRTOS timing simulation')
