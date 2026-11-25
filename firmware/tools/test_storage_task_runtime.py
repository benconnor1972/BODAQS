"""Exercise production storage task creation/reuse/failure; no scheduler simulation."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/StorageManager.cpp").read_text(encoding="utf-8")
    default = re.search(r"#ifndef BODAQS_STORAGE_TASK_PRIORITY\n.*?\n#endif", source, re.S).group()
    start = source.index("bool StorageManager_startLog() {")
    end = source.index("\nstatic void StorageManager_logSampleRow_", start)
    fixture = r'''
#include <cassert>
#include <cstring>
#define ESP32 1
constexpr int configMAX_PRIORITIES=25, pdPASS=1;
void* s_storageTask=nullptr;
void storageTaskFn_(void*) {}
unsigned creates=0, requests=0;
#define STOR_LOGE(...) do {} while (0)
bool failCreate=true, acceptStart=true;
const char* status="";
void setStatus_(const char* text) { status=text; }
int xTaskCreatePinnedToCore(void (*fn)(void*), const char* name, unsigned stack,
                           void* arg, int priority, void** handle, int core) {
  ++creates;
  assert(fn==storageTaskFn_ && std::strcmp(name,"StorageTask")==0);
  assert(stack==12288 && arg==nullptr && core==1);
  assert(priority==EXPECTED_PRIORITY);
  if(failCreate) return 0;
  *handle=reinterpret_cast<void*>(1); return pdPASS;
}
struct Worker { bool requestStart() { ++requests; return acceptStart; } };
Worker& storageWorker_() { static Worker worker; return worker; }
// PRODUCTION
int main() {
  assert(!StorageManager_startLog());
  assert(creates==1 && requests==0 && !s_storageTask);
  assert(std::strcmp(status,"storage task unavailable")==0);
  failCreate=false;
  assert(StorageManager_startLog());
  assert(creates==2 && requests==1 && s_storageTask);
  assert(StorageManager_startLog());
  assert(creates==2 && requests==2);
  acceptStart=false;
  assert(!StorageManager_startLog());
  assert(creates==2 && requests==3);
}
'''.replace("// PRODUCTION", default + "\n" + definition(source, "bool StorageManager_prepareTask() {") + "\n" + source[start:end])
    with tempfile.TemporaryDirectory(prefix="bodaqs-storage-task-") as directory:
        cpp = Path(directory)/"task.cpp"
        cpp.write_text(fixture, encoding="utf-8")
        for priority in (1, 2):
            exe = Path(directory)/f"task-{priority}.exe"
            subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            f"-DEXPECTED_PRIORITY={priority}",
                            *(["-DBODAQS_STORAGE_TASK_PRIORITY=2"] if priority==2 else []),
                            str(cpp), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
    print("Production storage task priority/default, core, create failure, reuse and start refusal: PASS")


if __name__ == "__main__":
    main()
