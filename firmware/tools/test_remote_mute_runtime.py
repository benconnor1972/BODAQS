"""Production configured-slot runtime mute: remote overlay and local behavior."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=(root/"src/SensorManager.cpp").read_text()
    fixture=r'''#include "ConfigManager.h"
#include "SensorAssignment.h"
#include <cassert>
#include <cstring>
static LoggerConfig cfg;
static SensorSpec specs[MAX_SENSORS];
static uint8_t n;
uint8_t LoggerConfig::sensorCount() const {return n;}
bool LoggerConfig::getSensorSpec(uint8_t i,SensorSpec& out) const {if(i>=n)return false;out=specs[i];return true;}
const LoggerConfig& ConfigManager::get(){return cfg;}
namespace board { const BoardProfile* gBoard=nullptr; }
static bool locked=false;
static unsigned reconcile=0;
namespace LoggingManager { bool configurationLocked(){return locked;} }
namespace CanMasterManager { void scheduleConfigurationReconciliation(){++reconcile;} }
struct Sensor { bool mute=false; bool muted()const{return mute;} void setMuted(bool v){mute=v;} } local;
static Sensor* s_list[MAX_SENSORS]={};
// OVERLAY
namespace SensorManager {
// METHODS
}
int main(){
 ParamStore remote, localParams;
 remote.set("provider","can:1");remote.set("endpoint","imu");
 specs[0].type=SensorType::LSM6DSO32XImu;strcpy(specs[0].name,"remote");specs[0].params.bind(&remote);
 specs[1].type=SensorType::AnalogPot;strcpy(specs[1].name,"local");specs[1].params.bind(&localParams);n=2;s_list[1]=&local;
 bool muted=true;assert(SensorManager::getMuted(0,muted)&&!muted);
 assert(SensorManager::setMuted(0,true));assert(reconcile==1);
 assert(SensorManager::getMuted(0,muted)&&muted);assert(!specs[0].mutedDefault);
 locked=true;assert(!SensorManager::setMuted(0,false));assert(reconcile==1);
 assert(SensorManager::getMuted(0,muted)&&muted);
 assert(SensorManager::setMuted(1,true)&&local.muted());assert(reconcile==1);
 locked=false;assert(SensorManager::setMuted(0,false));assert(reconcile==2);
 // Unrelated metadata does not lose the runtime override. Assignment/default edits do.
 assert(SensorManager::setMuted(0,true));remote.set("mount_point","fork");
 assert(SensorManager::getMuted(0,muted)&&muted);
 remote.set("provider","can:2");assert(SensorManager::getMuted(0,muted)&&!muted);
 assert(SensorManager::setMuted(0,true));specs[0].mutedDefault=true;
 assert(SensorManager::getMuted(0,muted)&&muted);specs[0].mutedDefault=false;
 assert(SensorManager::getMuted(0,muted)&&!muted);
 assert(!SensorManager::setMuted(9,true));
 puts("production remote/local runtime mute passed");
}
'''
    overlay=source[source.index("  struct RemoteMuteOverride"):source.index("  int firstFree()")] if "  struct RemoteMuteOverride" in source else ""
    fixture=fixture.replace("// OVERLAY",overlay)
    fixture=fixture.replace("// METHODS",definition(source,"bool getMuted(")+"\n"+definition(source,"bool setMuted("))
    with tempfile.TemporaryDirectory(prefix="bodaqs-mute-") as temp:
        cpp,exe=Path(temp)/"runtime.cpp",Path(temp)/"runtime.exe"
        cpp.write_text(fixture)
        subprocess.run([args.compiler,"-std=gnu++2a","-I",str(root/"test/stubs"),"-I",str(root/"src"),str(cpp),str(root/"src/SensorAssignment.cpp"),str(root/"src/SensorParams.cpp"),"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
if __name__=="__main__":main()

