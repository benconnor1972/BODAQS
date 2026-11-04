#include "Arduino.h"
#include "WebServer.h"
#include <ArduinoJson.h>
void convertFromJson(JsonVariantConst value, String& out) { out = value.as<const char*>(); }
bool canConvertFromJson(JsonVariantConst value, const String&) { return value.is<const char*>(); }
#include "ConfigManager.h"
#include "SensorRegistry.h"
#include "SensorAssignment.h"
#include "SensorConfigEdit.h"
#include "Rates.h"
#include "Lsm6dso32xConfig.h"
#include "CanMasterManager.h"
#include "ImuOrientation.h"
#include "BoardSelect.h"
#include <cassert>
#include <memory>
#include <new>
#include <cmath>
using LogLevel = uint8_t;
bool Log_parseLevel(const char*, LogLevel&) { return false; }
const char* Log_levelName(LogLevel) { return "info"; }
LoggerConfig g_cfg;
namespace board { const BoardProfile* gBoard = nullptr; }
String disk;
bool saveOk = true, recording = false, upload = false;
int rebuilds = 0;
bool StorageManager_loadTextFile(const char*, String& out) { out = disk; return true; }
bool StorageManager_saveTextFile(const char*, const String& text) { if (!saveOk) return false; disk = text; return true; }
namespace SensorRegistry {
const ParamDef defs[] = {
  {"pin", ParamType::Int, "1", "0", "255", nullptr, nullptr},
  {"mode", ParamType::Enum, "a", nullptr, nullptr, "a,b", nullptr},
  {"optional_count", ParamType::Int, "", nullptr, nullptr, nullptr, nullptr}};
const ParamDef* params(size_t& n) { n = 3; return defs; }
const SensorTypeInfo info = {SensorType::AnalogPot, "analog_pot", "Analog", params, nullptr};
const SensorTypeInfo lsm = {SensorType::LSM6DSO32XImu, "lsm6dso32x_imu", "LSM", Lsm6dso32xConfig::paramDefs, nullptr};
const SensorTypeInfo bmi = {SensorType::BMI270ImuI2C, "bmi270_imu_i2c", "BMI", params, nullptr};
const SensorTypeInfo* lookup(SensorType t) { return t == SensorType::LSM6DSO32XImu ? &lsm : t == SensorType::BMI270ImuI2C ? &bmi : t == SensorType::AnalogPot ? &info : nullptr; }
const char* typeKey(SensorType t) { return t == SensorType::LSM6DSO32XImu ? "lsm6dso32x_imu" : t == SensorType::BMI270ImuI2C ? "bmi270_imu_i2c" : "analog_pot"; }
const char* typeLabel(SensorType) { return "Analog"; }
CalModeMask supportedCalMask(SensorType) { return CAL_NONE; }
}
namespace CanMasterManager {
Diagnostics controlDiagnostics;
const Diagnostics& diagnostics() { return controlDiagnostics; }
bool configurationReconciled(uint8_t) { return false; }
void scheduleConfigurationReconciliation() {}
}
namespace LoggingManager { bool isRunning() { return recording; } void refreshConfigurationStatus() {} }
namespace UploadModeManager { bool isActive() { return upload; } }
struct Sensor {
  bool mute = true;
  const char* name() const { return "front"; }
  bool muted() const { return mute; }
  void setMuted(bool value) { mute = value; }
} live;
namespace SensorManager {
uint8_t count() { return 1; }
Sensor* get(uint8_t index) { return index == 0 ? &live : nullptr; }
bool rebuildOk = true;
bool rebuildFromConfig(const LoggerConfig& cfg, char*, size_t) { ++rebuilds; live.mute = cfg.sensors[0].mutedDefault; return rebuildOk; }
}
namespace AnalogInputManager { uint16_t configureFromConfig(const LoggerConfig&, uint16_t hz) { return hz; } }
void StorageManager_setSampleRate(uint16_t) {}
class BMI270ImuSensor { public: static bool validateSpec(const SensorSpec&, char*, size_t) { return true; } };
// PRODUCTION_CONFIG
// PRODUCTION_EDIT
void sendJson_(WebServer& srv, int status, JsonDocument& doc) {
  std::string body; serializeJson(doc, body); srv.send(status, "application/json", body.c_str());
}
void sendError_(WebServer& srv, int status, const char* error, const char* message) {
  JsonDocument doc; doc["error"] = error; doc["message"] = message; sendJson_(srv, status, doc);
}
void addEnvelope_(JsonDocument& doc, const char* schema) { doc["schema"] = schema; }
bool readJsonBody_(WebServer& srv, JsonDocument& doc) { return !deserializeJson(doc, srv.arg("plain").c_str()); }
// PRODUCTION_API
#define WEB_LOGW(...) do {} while(0)
enum class OutputMode { RAW, LINEAR };
namespace HtmlUtil {
bool isHtmxRequest(WebServer&) { return false; }
String htmlEscape(const String& text) { return text; }
}
using namespace HtmlUtil;
namespace HttpFileSender {
void sendText(WebServer& srv, int status, const char* type, const String& text, const char*) { srv.send(status, type, text); }
}
namespace WebServerManager { bool canStart() { return !recording; } }
void noteHttpActivity_() {}
String configurationNotice_(bool) { return ""; }
// PRODUCTION_WEB

int main() {
  ConfigManager::begin("loggercfg");
  {
    WebServer srv;
    mockSetArg("plain", R"({"type":"lsm6dso32x_imu","name":"remote","params":{"provider":"can2","endpoint":"imu","profile":"imu6_3333_32g_2000dps_v1","calibration_ref":"host-cal","mount_point":"fork","orient_valid":true,"orient_qw":1,"orient_qx":0,"orient_qy":0,"orient_qz":0}})");
    handleSensorPost_(srv); assert(mockLastStatus==201);
    JsonDocument remote; assert(!deserializeJson(remote,mockLastBody.c_str()));
    assert(remote["sensor"]["remote_control"]["desired_profile"]=="imu6_3333_32g_2000dps_v1");
    assert(remote["sensor"]["remote_control"]["acquisition_ready"]==false);
    static_assert(uint8_t(SensorType::BMI270ImuI2C)==7 && uint8_t(SensorType::LSM6DSO32XImu)==8);
    assert(disk.indexOf("lsm6dso32x_imu")>=0 && disk.indexOf("host-cal")>=0);
    const String saved=disk;
    mockSetArg("id","0"); mockSetArg("plain",R"({"params":{"profile":"orientation_200"}})");
    handleSensorPut_(srv); assert(mockLastStatus==400 && disk==saved);
    mockSetArg("plain",R"({"params":{"provider":"local"}})");
    handleSensorPut_(srv); assert(mockLastStatus==400 && disk==saved);
    mockSetArg("plain",R"({"params":{"orient_qw":0}})");
    handleSensorPut_(srv); assert(mockLastStatus==400 && disk==saved);
    saveOk=false; mockSetArg("plain",R"({"name":"failed"})");
    handleSensorPut_(srv); assert(mockLastStatus==500 && disk==saved); saveOk=true;
    assert(ConfigManager::reload()); SensorSpec sp; assert(ConfigManager::getSensorSpec(0,sp));
    assert(sp.type==SensorType::LSM6DSO32XImu); String metadata; sp.params.get("calibration_ref",metadata); assert(metadata=="host-cal");
    assert(ConfigManager::deleteSensorByIndex(0)); assert(ConfigManager::save(ConfigManager::get()));
    rebuilds=0; live.mute=true;
  }
  {
    // Legacy saved input stays byte-for-byte unchanged on reload and inspection.
    assert(ConfigManager::appendSensor(SensorType::BMI270ImuI2C, "legacy"));
    SensorSpec legacy; assert(ConfigManager::getSensorSpec(0, legacy));
    assert(legacy.params.set("provider", "can1"));
    assert(legacy.params.set("endpoint", "imu"));
    assert(legacy.params.set("profile", "orientation_200"));
    assert(legacy.params.set("calibration_ref", "cal-legacy"));
    assert(legacy.params.set("mount_point", "fork"));
    assert(legacy.params.set("orient_valid", "true"));
    assert(legacy.params.set("orient_qw", "1"));
    assert(legacy.params.set("orient_qx", "0"));
    assert(legacy.params.set("orient_qy", "0"));
    assert(legacy.params.set("orient_qz", "0"));
    assert(ConfigManager::save(ConfigManager::get()));
    Calibration calibration; calibration.capture_n = 41;
    assert(ConfigManager::saveCalibrationByIndex(0, calibration));
    const String before = disk;
    assert(ConfigManager::reload() && disk == before);
    WebServer srv; mockSetArg("id", "0"); handleSensorGet_(srv);
    JsonDocument response; assert(!deserializeJson(response, mockLastBody.c_str()));
    assert(response["sensor"]["assignment_state"] == "unresolved_legacy_remote_imu");
    assert(response["sensor"]["migration"]["type"] == "lsm6dso32x_imu");
    assert(response["sensor"]["migration"]["url"] == "/api/v1/sensor?id=0");
    assert(response["sensor"]["migration"]["profile"] == "imu6_3333_32g_2000dps_v1");
    assert(response["sensor"]["recording_eligible"] == false && disk == before);
    for (const char* request : {
        R"({"type":"lsm6dso32x_imu"})",
        R"({"migration":{"type":"lsm6dso32x_imu","profile":"orientation_200"}})",
        R"({"migration":{"type":"lsm6dso32x_imu"}})",
        R"({"migration":null})",
        R"({"migration":{"type":"lsm6dso32x_imu","profile":"imu6_3333_32g_2000dps_v1"},"name":"ignored"})"}) {
      mockSetArg("plain", request); handleSensorPut_(srv);
      assert(mockLastStatus == 400 && disk == before);
      assert(ConfigManager::getSensorSpec(0, legacy) && legacy.type == SensorType::BMI270ImuI2C);
      String profile; assert(legacy.params.get("profile", profile) && profile == "orientation_200");
    }
    mockSetArg("plain", R"({"migration":{"type":"lsm6dso32x_imu","profile":"imu6_3333_32g_2000dps_v1"}})");
    // Invalid retained mounting data is rejected rather than discarded.
    legacy.params.set("orient_qw", "0");
    assert(ConfigManager::save(ConfigManager::get())); const String invalidMount = disk;
    handleSensorPut_(srv); assert(mockLastStatus == 400 && disk == invalidMount);
    assert(ConfigManager::getSensorSpec(0, legacy) && legacy.type == SensorType::BMI270ImuI2C);
    disk = before; assert(ConfigManager::reload());
    saveOk = false; handleSensorPut_(srv); saveOk = true;
    assert(mockLastStatus == 500 && disk == before);
    assert(ConfigManager::getSensorSpec(0, legacy) && legacy.type == SensorType::BMI270ImuI2C);
    String oldProfile; assert(legacy.params.get("profile", oldProfile) && oldProfile == "orientation_200");
    Calibration retained; assert(ConfigManager::loadCalibrationByIndex(0, retained) && retained.capture_n == 41);
    recording = true; handleSensorPut_(srv); recording = false;
    assert(mockLastStatus == 423 && disk == before);
    mockSetArg("plain", R"({"migration":{"type":"lsm6dso32x_imu","profile":"imu6_3333_32g_2000dps_v1"}})");
    handleSensorPut_(srv); assert(mockLastStatus == 200);
    assert(ConfigManager::getSensorSpec(0, legacy) && legacy.type == SensorType::LSM6DSO32XImu);
    String value;
    assert(String(legacy.name) == "legacy");
    assert(legacy.params.get("provider", value) && value == "can1");
    assert(legacy.params.get("endpoint", value) && value == "imu");
    assert(legacy.params.get("calibration_ref", value) && value == "cal-legacy");
    assert(legacy.params.get("mount_point", value) && value == "fork");
    assert(legacy.params.get("orient_qw", value) && value == "1");
    assert(legacy.params.get("profile", value) && value == "imu6_3333_32g_2000dps_v1");
    assert(ConfigManager::reload());
    assert(ConfigManager::getSensorSpec(0, legacy) && legacy.type == SensorType::LSM6DSO32XImu);
    assert(ConfigManager::loadCalibrationByIndex(0, retained) && retained.capture_n == 41);
    // The web action selects the same canonical desired profile through commit.
    disk = before; assert(ConfigManager::reload()); mockReset();
    mockSetArg("s0.type", "lsm6dso32x_imu");
    web::post(srv); assert(mockLastStatus == 400 && disk == before);
    mockReset();
    mockSetArg("migrate_legacy_idx", "0");
    mockSetArg("s0.migration_type", "lsm6dso32x_imu");
    web::post(srv); assert(mockLastStatus == 400 && disk == before);
    mockSetArg("s0.migration_profile", "orientation_200");
    web::post(srv); assert(mockLastStatus == 400 && disk == before);
    mockSetArg("s0.migration_profile", "imu6_3333_32g_2000dps_v1");
    saveOk = false; web::post(srv); saveOk = true;
    assert(mockLastStatus == 500 && disk == before);
    recording = true; web::post(srv); recording = false;
    assert(mockLastStatus == 423 && disk == before);
    web::post(srv); assert(mockLastStatus == 303);
    assert(ConfigManager::getSensorSpec(0, legacy) && legacy.type == SensorType::LSM6DSO32XImu);
    assert(String(legacy.name) == "legacy");
    assert(legacy.params.get("calibration_ref", value) && value == "cal-legacy");
    assert(legacy.params.get("orient_qw", value) && value == "1");
    assert(ConfigManager::loadCalibrationByIndex(0, retained) && retained.capture_n == 41);
    // Local BMI configuration remains local and cannot use remote migration.
    disk = before; assert(ConfigManager::reload()); mockReset();
    assert(ConfigManager::getSensorSpec(0, legacy)); legacy.params.set("provider", "local");
    assert(ConfigManager::save(ConfigManager::get())); const String local = disk;
    mockSetArg("id", "0"); handleSensorGet_(srv);
    assert(!deserializeJson(response, mockLastBody.c_str()));
    assert(response["sensor"]["migration"].isNull());
    mockSetArg("plain", R"({"migration":{"type":"lsm6dso32x_imu","profile":"imu6_3333_32g_2000dps_v1"}})");
    handleSensorPut_(srv); assert(mockLastStatus == 400 && disk == local);
    assert(ConfigManager::getSensorSpec(0, legacy) && legacy.type == SensorType::BMI270ImuI2C);
    assert(legacy.params.get("profile", value) && value == "orientation_200");
    assert(ConfigManager::deleteSensorByIndex(0)); assert(ConfigManager::save(ConfigManager::get()));
    mockReset(); rebuilds = 0; live.mute = true;
  }
  assert(ConfigManager::appendSensor(SensorType::AnalogPot, "front"));
  assert(ConfigManager::save(ConfigManager::get()));
  {
    SensorConfigEdit edit;
    assert(edit.ready());
    SensorSpec sp; ConfigManager::getSensorSpec(0, sp);
    sp.params.setInt("pin", 2);
    char error[160] = {};
    assert(edit.commit(ConfigManager::get(), error, sizeof(error)) == SensorConfigEdit::Result::Applied);
  }
  assert(rebuilds == 1);
  assert(live.muted());
  assert(disk.indexOf("sensor0.pin=2") >= 0);
  WebServer srv;
  mockSetArg("id", "0");
  live.mute = false;
  mockSetArg("plain", R"({"muted":true})");
  handleSensorPut_(srv);
  assert(mockLastStatus == 200 && live.muted());
  mockSetArg("plain", R"({"muted":false})");
  handleSensorPut_(srv);
  assert(mockLastStatus == 200 && !live.muted());
  mockSetArg("plain", R"({"params":{"pin":3,"provider":"can:2","endpoint":"ain:0","custom_field":"retained"}})");
  handleSensorPut_(srv);
  assert(mockLastStatus == 200);
  JsonDocument response; assert(!deserializeJson(response, mockLastBody.c_str()));
  assert(response["saved"] == true && response["runtime_rebuilt"] == true);
  assert(response["restart_recommended"] == false);
  assert(response["sensor"]["params"]["provider"] == "can:2");
  assert(response["sensor"]["params"]["endpoint"] == "ain:0");
  assert(response["sensor"]["params"]["custom_field"] == "retained");
  handleSensorGet_(srv);
  assert(!deserializeJson(response, mockLastBody.c_str()));
  assert(response["sensor"]["provider"] == "can:2");
  assert(response["sensor"]["endpoint"] == "ain:0");
  mockSetArg("plain", R"({"params":{"mode":"invalid"}})");
  handleSensorPut_(srv);
  assert(mockLastStatus == 400);
  mockSetArg("plain", R"({"params":{"custom_field":"bad\nvalue"}})");
  handleSensorPut_(srv);
  assert(mockLastStatus == 400);
  mockSetArg("plain", R"({"muted":"invalid"})");
  handleSensorPut_(srv);
  assert(mockLastStatus == 400);
  const String previous = disk;
  const int previousRebuilds = rebuilds;
  mockSetArg("plain", R"({"name":"damaged","params":{"pin":"garbage"}})");
  handleSensorPut_(srv);
  assert(mockLastStatus == 400);
  assert(disk == previous && rebuilds == previousRebuilds);
  SensorSpec current; ConfigManager::getSensorSpec(0, current);
  assert(String(current.name) == "front");
  long pin; assert(current.params.getInt("pin", pin) && pin == 3);
  saveOk = false;
  mockSetArg("plain", R"({"name":"damaged","params":{"pin":4}})");
  handleSensorPut_(srv);
  assert(mockLastStatus == 500);
  assert(disk == previous && rebuilds == previousRebuilds);
  ConfigManager::getSensorSpec(0, current);
  assert(String(current.name) == "front");
  assert(current.params.getInt("pin", pin) && pin == 3);
  handleSensorDelete_(srv);
  assert(mockLastStatus == 500 && ConfigManager::sensorCount() == 1);
  handleSensorPost_(srv);
  assert(mockLastStatus == 500 && ConfigManager::sensorCount() == 1);
  saveOk = true;
  recording = true;
  handleSensorPut_(srv);
  assert(mockLastStatus == 423 && disk == previous && rebuilds == previousRebuilds);
  handleSensorPost_(srv);
  assert(mockLastStatus == 423 && ConfigManager::sensorCount() == 1);
  handleSensorDelete_(srv);
  assert(mockLastStatus == 423 && ConfigManager::sensorCount() == 1);
  recording = false;
  mockReset();
  mockSetArg("s0.pin", "5");
  web::post(srv);
  assert(mockLastStatus == 303 && disk.indexOf("sensor0.pin=5") >= 0);
  const String webSaved = disk;
  const int webRebuilds = rebuilds;
  mockSetArg("s0.pin", "not a number");
  web::post(srv);
  assert(mockLastStatus == 400 && disk == webSaved && rebuilds == webRebuilds);
  saveOk = false;
  mockSetArg("s0.pin", "6");
  web::post(srv);
  assert(mockLastStatus == 500 && disk == webSaved && rebuilds == webRebuilds);
  saveOk = true; recording = true;
  web::post(srv);
  assert(mockLastStatus == 423 && disk == webSaved && rebuilds == webRebuilds);
  recording = false;
  mockReset();
  mockSetArg("plain", R"({"name":"rear","params":{"provider":"can:1","endpoint":"ain:1"}})");
  handleSensorPost_(srv);
  assert(mockLastStatus == 201 && ConfigManager::sensorCount() == 2);
  SensorSpec added; ConfigManager::getSensorSpec(1, added);
  String assigned; assert(added.params.get("endpoint", assigned) && assigned == "ain:1");
  Calibration rearCalibration;
  rearCalibration.capture_n = 37;
  assert(ConfigManager::saveCalibrationByIndex(1, rearCalibration));
  saveOk = false;
  mockSetArg("id", "0");
  handleSensorDelete_(srv);
  assert(mockLastStatus == 500 && ConfigManager::sensorCount() == 2);
  Calibration restored;
  assert(ConfigManager::loadCalibrationByIndex(1, restored) && restored.capture_n == 37);
  ConfigManager::getSensorSpec(1, added);
  assert(String(added.name) == "rear");
  saveOk = true;
  mockSetArg("id", "1");
  handleSensorDelete_(srv);
  assert(mockLastStatus == 200 && ConfigManager::sensorCount() == 1);
  mockSetArg("id", "0");
  mockSetArg("plain", R"({"name":"front_edited"})");
  SensorManager::rebuildOk = false;
  handleSensorPut_(srv);
  assert(mockLastStatus == 500);
  assert(!deserializeJson(response, mockLastBody.c_str()));
  assert(response["saved"] == true && response["runtime_rebuilt"] == false);
  assert(disk.indexOf("sensor0.name=front_edited") >= 0);
  SensorManager::rebuildOk = true;
  puts("web and JSON success, assignment readback, invalid input, save failure, mute preservation and recording guards pass");
}
