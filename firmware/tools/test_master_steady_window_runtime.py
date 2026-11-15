"""Compile the real steady-window state machine against boundary-time vectors."""
import argparse
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--cc',required=True)
p.add_argument('--warmup-us',type=int,required=True)
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
source=(root/'can-fd/master/src/main.c').read_text()
start=source.index('#if defined(BODAQS_MASTER_PHASE_TIMING)',source.index('/* Active drain diagnostic state. */'))
end=source.index('/* Main-loop writer only;',start)
real=source[start:end]
fixture=r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#define BODAQS_MASTER_PHASE_TIMING 1
#define BODAQS_MASTER_PROGRESS_DIAGNOSTICS 1
#define BODAQS_MASTER_CRC_RAM 1
#define BODAQS_SPI_BULK_BYTES 0
static unsigned resets;
static void bodaqs_progress_reset(uint64_t c,uint64_t r){assert(c&&r);++resets;}
REAL
int main(void) {
 const uint32_t origin=0xffff0000U,warmup=WARMUP;
 steady_observe(9,1,true,origin,1);
 assert(gMasterSteadyInfo.state==1&&resets==1);
 steady_observe(9,1,true,origin+warmup-1U,1);
 assert(gMasterSteadyInfo.state==1&&gMasterSteadyInfo.elapsed_us==0);
 steady_observe(9,1,true,origin+warmup,1);
 assert(gMasterSteadyInfo.state==2&&gMasterSteadyInfo.started_tick==origin+warmup);
 steady_observe(9,1,true,origin+warmup+29999999U,1);
 assert(gMasterSteadyInfo.state==2);
 steady_observe(9,1,true,origin+warmup+30000000U,1);
 assert(gMasterSteadyInfo.state==3&&gMasterSteadyInfo.finish_reason==1);
 assert(gMasterSteadyInfo.elapsed_us==30000000U&&resets==1);
 steady_observe(9,1,false,origin+warmup+40000000U,1);
 assert(gMasterSteadyInfo.finish_reason==1&&gMasterSteadyInfo.elapsed_us==30000000U);
 steady_observe(9,2,true,100,1);
 assert(gMasterSteadyInfo.state==1&&gMasterSteadyInfo.recording==2&&resets==2);
 steady_observe(9,2,false,101,1);
 assert(gMasterSteadyInfo.state==3&&gMasterSteadyInfo.finish_reason==2);
 steady_observe(9,3,true,200,1);
 steady_observe(9,3,true,201,2);
 assert(gMasterSteadyInfo.state==3&&gMasterSteadyInfo.finish_reason==4&&gMasterSteadyInfo.timing_invalid);
 steady_observe(9,4,true,300,1);
 steady_observe(10,4,true,301,1);
 assert(gMasterSteadyInfo.state==3&&gMasterSteadyInfo.finish_reason==3);
 return 0;
}
'''
fixture=fixture.replace('REAL',real).replace('WARMUP',str(a.warmup_us)+'U')
with tempfile.TemporaryDirectory() as temp:
    src=Path(temp)/'window.c';exe=Path(temp)/'window.exe'
    src.write_text(fixture)
    subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('Production steady window: threshold, full duration, wrap, STOP, restart, epoch and identity PASS')
