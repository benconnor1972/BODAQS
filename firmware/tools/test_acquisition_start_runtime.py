"""Exercise actual I2C worker reservation against independent task failures."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/I2CBusScheduler.cpp").read_text(encoding="utf-8")
    fixture = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#define ESP32 1
#define I2CSCHED_LOGW(...) ((void)0)
using BaseType_t=int;
using TaskHandle_t=void*;
constexpr int pdPASS=1;
constexpr unsigned kMaxBuses=2,kTaskStackBytes=4096,kTaskPriority=1,kTaskCore=1;
TaskHandle_t s_tasks[2]{};
std::atomic<bool> s_run[2],s_retired[2];
uint64_t s_sessionStartUs=0,s_sessionEndUs=0;
bool active[2]{},allocationOk[2]{true,true};
unsigned attempts[2]{};
bool schedulerTasksActive_(){return s_tasks[0] || s_tasks[1];}
bool busHasActiveClients_(unsigned bus){return active[bus];}
int64_t esp_timer_get_time(){return 1234;}
void taskFn_(void*){}
int xTaskCreatePinnedToCore(void(*)(void*),const char*,unsigned,void* argument,
                           unsigned,void** task,unsigned){
  const unsigned bus=uintptr_t(argument);++attempts[bus];
  if(!allocationOk[bus])return 0;
  *task=reinterpret_cast<void*>(bus+1);return pdPASS;
}
namespace I2CBusScheduler {
// START
}
int main(){
  assert(I2CBusScheduler::start()); // no clients require no workers
  assert(!attempts[0] && !attempts[1]);
  active[0]=active[1]=true;allocationOk[1]=false;
  assert(!I2CBusScheduler::start());
  assert(s_tasks[0] && s_run[0] && !s_retired[0]);
  assert(!s_tasks[1] && !s_run[1] && s_retired[1]);
  allocationOk[1]=true;
  assert(I2CBusScheduler::start()); // safe retry does not duplicate the first owner
  assert(attempts[0]==1 && attempts[1]==2);
  s_run[0]=false;
  assert(!I2CBusScheduler::start()); // retained retiring task is not ready
  assert(attempts[0]==1 && attempts[1]==2);
  puts("I2C acquisition: empty plan, partial allocation failure, retry and retiring owner passed");
}
'''.replace("// START", definition(source, "bool start()"))
    with tempfile.TemporaryDirectory(prefix="bodaqs-acquisition-start-") as tmp:
        cpp, exe = Path(tmp) / "start.cpp", Path(tmp) / "start.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=15)


if __name__ == "__main__":
    main()
