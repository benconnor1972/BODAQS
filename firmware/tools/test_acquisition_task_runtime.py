"""Exercise the actual task-creation seam: API, affinity, priority and errors."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=(root/'src/AcquisitionControl.cpp').read_text()
    start=source.index('#ifndef BODAQS_ACQUISITION_TASK_CORE')
    guards=source[start:source.index('#ifndef BODAQS_ACQ_HEALTH_INTERVAL_MS')]
    helper=definition(source,'static BaseType_t createTask_()')
    begin=definition(source,'bool begin(uint64_t recording,uint64_t context)')
    assert 'if(!task && createTask_()!=pdPASS) return false;' in begin
    assert begin.index('createTask_()') < begin.index('claimMeasurementControl')
    fixture=r'''
#include <cassert>
#include <cstring>
using BaseType_t=int;
using TaskHandle_t=void*;
constexpr BaseType_t pdPASS=1;
static TaskHandle_t task=nullptr;
constexpr unsigned controlStackBytes=6144;
static void run(void*) {}
static int unpinned=0,pinned=0,observedCore=-2;
static BaseType_t result=pdPASS;
static void check(void(*fn)(void*),const char* name,unsigned stack,void* arg,unsigned priority,TaskHandle_t* out) {
  assert(fn==run && !std::strcmp(name,"AcquisitionCtl") && stack==6144);
  assert(arg==nullptr && priority==2 && out==&task);
  if(result==pdPASS)*out=reinterpret_cast<void*>(1);
}
static BaseType_t xTaskCreate(void(*fn)(void*),const char* name,unsigned stack,void* arg,unsigned priority,TaskHandle_t* out) {
  ++unpinned;check(fn,name,stack,arg,priority,out);return result;
}
static BaseType_t xTaskCreatePinnedToCore(void(*fn)(void*),const char* name,unsigned stack,void* arg,unsigned priority,TaskHandle_t* out,int core) {
  ++pinned;observedCore=core;check(fn,name,stack,arg,priority,out);return result;
}
// ACTUAL_HELPER
int main() {
  assert(createTask_()==pdPASS && task);
  task=nullptr;result=-1;
  assert(createTask_()==-1 && !task);
  if(BODAQS_ACQUISITION_TASK_CORE==-1)assert(unpinned==2 && pinned==0);
  else assert(pinned==2 && unpinned==0 && observedCore==BODAQS_ACQUISITION_TASK_CORE);
}
'''
    with tempfile.TemporaryDirectory(prefix='bodaqs-acq-affinity-') as d:
        temp=Path(d);cpp=temp/'task.cpp';exe=temp/'task.exe'
        cpp.write_text(guards+fixture.replace('// ACTUAL_HELPER',helper))
        for core,processors,valid in [(None,2,True),(-1,2,True),(0,2,True),(1,2,True),(-2,2,False),(2,2,False),(1,1,False)]:
            flags=[] if core is None else [f'-DBODAQS_ACQUISITION_TASK_CORE={core}']
            p=subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Werror','-Wno-unused-function',
                f'-DportNUM_PROCESSORS={processors}',*flags,str(cpp),'-o',str(exe)],capture_output=True,text=True)
            assert (p.returncode==0)==valid,(core,processors,p.stderr)
            if valid:subprocess.run([str(exe)],check=True)
            else:assert 'Acquisition task core' in p.stderr,p.stderr
            print('Affinity',core,'cores',processors,'creation/error checks' if valid else 'compile rejection','PASS')


if __name__=='__main__':main()
