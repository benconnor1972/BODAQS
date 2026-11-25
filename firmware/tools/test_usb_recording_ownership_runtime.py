"""Exercise upload/card handoff with actual recording and USB lifecycle policies."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    upload = (root/'src/UploadModeManager.cpp').read_text(encoding='utf-8')
    upload = re.sub(r'^#include.*\n', '', upload, flags=re.M)
    storage = (root/'src/StorageManager.cpp').read_text(encoding='utf-8')
    logging = (root/'src/LoggingManager.cpp').read_text(encoding='utf-8')
    restart = (root/'src/DeviceRestart.cpp').read_text(encoding='utf-8')
    fixture = r'''
#include <cassert>
#include <cstring>
#include <cstdio>
#include <memory>
#include "RecordingLifecycle.h"
#include "StorageOwnership.h"
#include "UsbUploadSession.h"
#include "UploadModeManager.h"
#define ESP32 1
RecordingLifecycle s_lifecycle;
bool handoff=false,ioPending=false,loggingActive=false,s_sdMounted=true;
bool StorageManager_recordingIoPending(){return ioPending;}
namespace CanMasterManager {bool recordingHandoffActive(){return handoff;}}
namespace LoggingManager {
bool isRunning(){return s_lifecycle.state()==RecordingLifecycle::State::Recording;}
// LOCK
}
namespace StorageFilesystem {
StorageOwnership value;
StorageOwnership& ownership(){return value;}
}
// REQUEST
bool StorageManager_cancelExternalAccess(){return StorageFilesystem::ownership().cancelExternal();}
namespace UI {
constexpr int TARGET_BOTH=0,LVL_WARN=1,LVL_INFO=0;
template<class... T> void println(T...){}
void status(const char*){}
template<class... T> void toast(T...){}
template<class... T> void toastModal(T...){}
}
namespace DisplayManager {void present(){}}
struct SerialPort {void println(const char*){}void flush(){}} Serial;
unsigned restarts=0,invalidations=0;
void RTCManager_invalidateInternalTime(){++invalidations;}
void esp_restart(){++restarts;}
namespace DeviceRestart {void restart();}
namespace WiFiManager {void refreshDiscovery(){}}
uint32_t nowMs=100;
struct CardBackend final:UsbUploadSession::Backend {
 bool localReady()const override{return StorageFilesystem::ownership().localAvailable();}
 bool requestStorage()override{return StorageManager_requestExternalAccess();}
 bool storageGranted()const override{return StorageFilesystem::ownership().state()==StorageOwnership::State::External;}
 void cancelStorage()override{StorageManager_cancelExternalAccess();}
 UsbUploadSession::ExposeResult expose()override{return UsbUploadSession::ExposeResult::Ready;}
 bool withdraw(bool)override{return true;}
 bool reclaim()override{
  auto& card=StorageFilesystem::ownership();
  if(card.localAvailable())return true;
  if(!card.beginReclaim())return false;
  card.reclaimComplete(true);return true;
 }
} backend;
UsbUploadSession usb(backend);
namespace UsbDriveManager {
bool enabled(){return true;}void begin(){}
void loop(){usb.poll({true,true,false,false,false,0,1},nowMs);}
bool active(){return usb.active();}bool enter(bool busy){return usb.enter(busy);}
void requestExit(){usb.requestExit(nowMs);}bool cancelExit(){return usb.cancelExit();}
bool exitPending(){return usb.exitPending();}void retry(){usb.retry();}
uint8_t phase(){return uint8_t(usb.state());}
const char* stateKey(){return usb.stateKey();}const char* label(){return usb.label();}
const char* shortLabel(){return usb.shortLabel();}
}
// UPLOAD
// RESTART
int main(){
 UploadModeManager::begin([]{return s_lifecycle.state()==RecordingLifecycle::State::Recording;});
 for(auto phase:{RecordingLifecycle::State::Preparing,RecordingLifecycle::State::Recording,
                 RecordingLifecycle::State::Stopping,RecordingLifecycle::State::Finalizing,
                 RecordingLifecycle::State::Uncertain}){
  s_lifecycle.publish(phase);
  assert(!UploadModeManager::canEnter());assert(!UploadModeManager::enter());
  assert(!StorageManager_requestExternalAccess());
 }
 s_lifecycle.publish(RecordingLifecycle::State::Completed);
 ioPending=true;assert(!UploadModeManager::enter());
 assert(!StorageManager_requestExternalAccess());
 ioPending=false;handoff=true;assert(!UploadModeManager::enter());
 handoff=false;assert(UploadModeManager::canEnter());
 {
  auto transfer=StorageFilesystem::ownership().acquireLocal();assert(transfer);
  assert(UploadModeManager::enter());UploadModeManager::loop();
  assert(usb.state()==UsbUploadSession::State::Waiting);
  DeviceRestart::restart();assert(!restarts && !invalidations);
  assert(!StorageFilesystem::ownership().acquireLocal());
  assert(!StorageFilesystem::ownership().beginExternal());
 }
 assert(StorageFilesystem::ownership().beginExternal());
 StorageFilesystem::ownership().externalReady();UploadModeManager::loop();
 assert(usb.state()==UsbUploadSession::State::Shared);
 DeviceRestart::restart();assert(!restarts && !invalidations);
 UploadModeManager::exit();nowMs+=2999;UploadModeManager::loop();
 assert(UploadModeManager::isActive() && UploadModeManager::exitPending());
 nowMs++;UploadModeManager::loop();
 assert(!UploadModeManager::isActive() && StorageFilesystem::ownership().localAvailable());
 DeviceRestart::restart();assert(restarts==1 && invalidations==1);
 assert(UploadModeManager::canEnter());
 puts("USB/recording ownership: preparation, retirement, I/O, handoff, open transfer and reclaim passed");
}
'''
    fixture = fixture.replace('// LOCK',definition(logging,'bool LoggingManager::configurationLocked(').replace('bool LoggingManager::','bool '))
    fixture = fixture.replace('// REQUEST',definition(storage,'bool StorageManager_requestExternalAccess('))
    fixture = fixture.replace('// UPLOAD',upload)
    fixture = fixture.replace('// RESTART',definition(restart,'void DeviceRestart::restart('))
    with tempfile.TemporaryDirectory(prefix='bodaqs-usb-ownership-') as tmp:
        cpp,exe=Path(tmp)/'ownership.cpp',Path(tmp)/'ownership.exe'
        cpp.write_text(fixture,encoding='utf-8')
        subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Werror',
            '-I',str(root/'test/stubs'),'-I',str(root/'src'),str(cpp),
            str(root/'src/UsbUploadSession.cpp'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True,timeout=15)


if __name__=='__main__':
    main()
