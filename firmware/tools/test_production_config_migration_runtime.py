"""Execute production migration/configuration persistence against independent files."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    fixture = (root / 'test/sensor_config_runtime_fixture.cpp').read_text(encoding='utf-8')
    fixture = fixture[:fixture.index('int main()')]
    # Only ConfigManager is under test; route/edit methods are separate suites.
    fixture = fixture[:fixture.index('// PRODUCTION_EDIT')]
    fixture = fixture.replace('String disk;', '''#include <map>
#include "ProductionConfigMigration.h"
std::map<std::string,String> files;
String disk;
bool failConfig=false;
struct FileSystem { bool exists(const char* path) { return files.count(path); } } SD_MMC;''')
    start = fixture.index('bool StorageManager_loadTextFile(')
    end = fixture.index('namespace SensorRegistry', start)
    fixture = fixture[:start] + '''bool StorageManager_loadTextFile(const char* path,String& out) {
  auto found=files.find(path); if(found==files.end()) return false; out=found->second;return true;
}
bool StorageManager_saveTextFile(const char* path,const String& text) {
  if(!saveOk || (failConfig && std::string(path)=="loggercfg")) return false; files[path]=text;return true;
}
''' + fixture[end:]
    source = '\n'.join(line for line in (root/'src/ConfigManager.cpp').read_text(encoding='utf-8').splitlines()
                       if not line.startswith('#include'))
    fixture = fixture.replace('// PRODUCTION_CONFIG', source)
    web = (root/'src/Routes_Config.cpp').read_text(encoding='utf-8')
    api = (root/'src/Routes_Api.cpp').read_text(encoding='utf-8')
    html = (root/'src/HtmlUtil.cpp').read_text(encoding='utf-8')
    fixture += "namespace HtmlUtil {" + definition(html,'  String htmlEscape(') + "}"
    fixture += """
void sendJson_(WebServer& srv,int status,JsonDocument& doc) { std::string json;serializeJson(doc,json);srv.send(status,"application/json",json.c_str()); }
void sendError_(WebServer& srv,int status,const char* code,const char* message) {JsonDocument doc;doc["error"]=code;doc["message"]=message;sendJson_(srv,status,doc);}
bool readJsonBody_(WebServer& srv,JsonDocument& doc) {return !deserializeJson(doc,srv.arg("plain").c_str());}
"""
    fixture += definition(web,'static String productionMigrationHtml_(')
    fixture += definition(web,'static void handleProductionMigrationWeb_(')
    fixture += definition(api,'static void handleProductionMigrationApi_(')
    fixture += """
namespace UI { String toast;void toastModal(const String& value,int,int){toast=value;} }
void deferUiFor(int) {}
void drawSettings_() {}
enum class State { Settings };
State s_state=State::Settings;
String s_migrationReview,s_migrationRevision;
uint16_t s_migrationPage=0;
unsigned s_logFormatIdx=0;
constexpr LogFormat kLogFormatOptions[]={LogFormat::BodaqsMultiStreamBinary};
"""
    menu=(root/'src/MenuSystem.cpp').read_text(encoding='utf-8')
    fixture += definition(menu,'  static void applyLogFormat_() {')

    fixture += '''
int main() {
  const String old="log_format=csv\\r\\nsensor_count=1\\r\\nsensor0.type=analog_pot\\r\\nsensor0.name=fork\\r\\nsensor0.output_mode=LINEAR\\r\\nsensor0.cal_enabled=true\\r\\nsensor0.cal_mode=2\\r\\nsensor0.r0_raw=12.5\\r\\nsensor0.r1_raw=4000.25\\r\\nsensor0.sensor_zero_count=50\\r\\nsensor0.sensor_full_count=4050\\r\\n";
  files["loggercfg"]=old;
  ConfigManager::begin("loggercfg"); LoggerConfig cfg;
  assert(ConfigManager::load(cfg));
  assert(ConfigManager::migrationPending());
  assert(files.size()==1 && files["loggercfg"]==old);
  const String html=productionMigrationHtml_();
  assert(html.indexOf("csv -&gt; bodaqs_multi_stream_binary")>=0);
  assert(html.indexOf(ConfigManager::migrationRevision())>=0);
  assert(files.size()==1);
  WebServer request;
  mockSetArg("plain","{}"); handleProductionMigrationApi_(request);
  assert(mockLastStatus==400 && files.size()==1);
  starting=true;
  mockSetArg("acknowledge","yes");mockSetArg("revision",ConfigManager::migrationRevision());
  handleProductionMigrationWeb_(request);
  assert(mockLastStatus==409 && files.size()==1);
  starting=false;
  s_migrationReview=ConfigManager::migrationChanges();s_migrationRevision=ConfigManager::migrationRevision();
  applyLogFormat_();
  assert(UI::toast=="Review all changes" && files.size()==1);
  assert(!ConfigManager::save(cfg));
  char error[128]{};
  const String revision=ConfigManager::migrationRevision();
  assert(!ConfigManager::acceptMigration("stale",error,sizeof(error)));
  saveOk=false;
  assert(!ConfigManager::acceptMigration(revision.c_str(),error,sizeof(error)));
  assert(files["loggercfg"]==old && ConfigManager::migrationPending());
  saveOk=true; failConfig=true;
  assert(!ConfigManager::acceptMigration(revision.c_str(),error,sizeof(error)));
  assert(files["loggercfg"]==old && ConfigManager::migrationPending());
  failConfig=false;
  handleProductionMigrationWeb_(request);
  assert(mockLastStatus==303);
  assert(!ConfigManager::migrationPending());
  assert(!ConfigManager::setLogFormat(LogFormat::BodaqsStandard));
  assert(!ConfigManager::get().recordingBestEffort);
  assert(files.size()==2 && ConfigManager::get().logFormat==LogFormat::BodaqsMultiStreamBinary);
  bool foundOriginal=false; for(const auto& file:files) if(file.first!="loggercfg") {assert(file.second==old);foundOriginal=true;}
  assert(foundOriginal);
  assert(ConfigManager::reload() && !ConfigManager::migrationPending());
  const char* keys[]={"sensor_zero_count","sensor_full_count"};
  const String values[]={"100","4000"};
  saveOk=false;
  assert(!ConfigManager::saveSensorParamsByName("fork",keys,values,2));
  String value; assert(ConfigManager::getParam(0,"sensor_zero_count",value) && value=="50");
  saveOk=true;starting=true;
  assert(!ConfigManager::saveSensorParamsByName("fork",keys,values,2));
  starting=false;upload=true;assert(!ConfigManager::configurationMutable());upload=false;
  assert(ConfigManager::saveSensorParamsByName("fork",keys,values,2));
  assert(ConfigManager::getParam(0,"sensor_full_count",value) && value=="4000");
  assert(ConfigManager::reload() && !ConfigManager::migrationPending());
  Calibration captured; assert(ConfigManager::loadCalibration("fork",captured));
  assert(captured.enabled && captured.mode==CalMode::RANGE && captured.r0_raw==12.5f && captured.r1_raw==4000.25f);
  // Unknown sensor tokens and parameters survive migration and ordinary save.
  files["loggercfg"]="log_format=csv\\nrecording_best_effort=true\\nsensor_count=1\\nsensor0.type=future_special_sensor\\nsensor0.name=unsupported\\nsensor0.custom_anchor=99\\n";
  ConfigManager::begin("loggercfg"); assert(ConfigManager::load(cfg));
  assert(ConfigManager::sensorTypeKey(0)=="future_special_sensor");
  const String apiBody=String("{\\"acknowledge\\":true,\\"revision\\":\\"")+ConfigManager::migrationRevision()+"\\"}";
  mockReset();mockSetArg("plain",apiBody);handleProductionMigrationApi_(request);
  assert(mockLastStatus==200);
  assert(ConfigManager::get().recordingBestEffort);
  assert(ConfigManager::configurationBlocker().indexOf("future_special_sensor")>=0);
  assert(ConfigManager::save(ConfigManager::get()));
  assert(std::string(files["loggercfg"].c_str()).find("sensor0.type=future_special_sensor")!=std::string::npos);
  assert(ConfigManager::getParam(0,"custom_anchor",value) && value=="99");
  files["loggercfg"]=old;ConfigManager::begin("loggercfg");assert(ConfigManager::load(cfg));
  s_migrationReview=ConfigManager::migrationChanges();s_migrationRevision=ConfigManager::migrationRevision();
  s_migrationPage=uint16_t((s_migrationReview.length()-1)/63);
  applyLogFormat_();
  assert(!ConfigManager::migrationPending() && UI::toast=="Migration accepted");
  files["loggercfg"]="log_format=bdq_v2\\nrecording_best_effort=false\\nsensor_count=2\\nsensor0.type=analog_pot\\nsensor0.name=first\\nsensor1.type=future_other_sensor\\nsensor1.name=second\\n";
  assert(ConfigManager::reload());
  assert(ConfigManager::acceptMigration(ConfigManager::migrationRevision().c_str(),error,sizeof(error)));
  assert(ConfigManager::deleteSensorByIndex(0) && ConfigManager::save(ConfigManager::get()));
  assert(ConfigManager::sensorTypeKey(0)=="future_other_sensor");
  assert(std::string(files["loggercfg"].c_str()).find("sensor0.type=future_other_sensor")!=std::string::npos);
}
'''
    with tempfile.TemporaryDirectory(prefix='bodaqs-migration-') as temp:
        cpp, exe = Path(temp)/'test.cpp', Path(temp)/'test.exe'
        cpp.write_text(fixture, encoding='utf-8')
        includes = root/'.pio/libdeps/bodaqs_a8_production/ArduinoJson/src'
        subprocess.run([args.compiler,'-std=gnu++2a','-DBODAQS_PRODUCTION_RECORDING=1',
                        '-Wno-unused','-I',str(includes),'-I',str(root/'test/stubs'),
                        '-I',str(root/'src'),str(cpp),str(root/'src/SensorParams.cpp'),
                        '-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__=='__main__':
    main()


