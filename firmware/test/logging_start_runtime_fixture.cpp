#include "Arduino.h"
#include "SensorAssignment.h"
#include "LoggingStartStatus.h"
#include "HomeRestartGesture.h"
#include "HtmlUtil.h"
#include "BMI270Profile.h"
#include "ImuOrientation.h"
#include <cstdarg>
#include <vector>
#include <string>
#include <algorithm>
#include <cassert>

#define TRACE(...) do {} while (0)
#define LOGGING_LOGI(...) do {} while (0)
#define LOGGING_LOGW(...) do {} while (0)
#define RTC_LOGW(...) do {} while (0)

enum class LogFormat { BodaqsStandard, BodaqsCompactBinary, BodaqsMultiStreamBinary };
struct LoggerConfig {
  SensorSpec sensors[MAX_SENSORS];
  ParamStore stores[MAX_SENSORS];
  uint8_t sensorN = 0;
  uint16_t sampleRateHz = 500;
  LogFormat logFormat = LogFormat::BodaqsStandard;
  uint8_t sensorCount() const { return sensorN; }
  bool getSensorSpec(uint8_t i, SensorSpec& spec) const {
    if (i >= sensorN) return false;
    spec = sensors[i]; spec.params.bind(&stores[i]); return true;
  }
};
LoggerConfig g_cfg, savedConfig;
board::BoardProfile profile;
namespace board { const BoardProfile* gBoard = &profile; }
struct Sensor {
  std::string instance;
  bool mute = false, stale = false;
  const char* name() const { return instance.c_str(); }
  bool muted() const { return mute; }
  bool loggingRestartRequired(const SensorSpec&, char* error, size_t cap) const {
    if (stale) snprintf(error, cap, "%s profile changed", name());
    return stale;
  }
};
namespace SensorRegistry { bool lookup(SensorType type) { return type != SensorType::Unknown; } }
enum class BMI270GyroBiasMode { Off, InUseOffsetCorrection };
class BMI270ImuSensor {
public:
  // PRODUCTION_BMI_PARAMS
  Params params_;
  static bool validateSpec(const SensorSpec&, char*, size_t) { return true; }
  static bool loadParams_(Params&, const char*, const ParamPack&);
  bool loggingRestartRequired(const SensorSpec&, char*, size_t) const;
};
bool fail_(char* error, size_t cap, const char* format, ...) {
  va_list args; va_start(args, format);
  if (error && cap) vsnprintf(error, cap, format, args);
  va_end(args); return false;
}
// PRODUCTION_BMI
std::vector<std::string> events;
bool saveOk = true, upload = false, powerOk = true, storageOk = true, openOk = true;
bool validateOk = true, sensorsStartOk = true;
int prepares = 0;
LogFormat preparedFormat, fileFormat;

namespace SensorManager {
  Sensor* s_list[MAX_SENSORS] = {};
  SensorAssignment s_liveAssignment[MAX_SENSORS];
  SensorType s_liveType[MAX_SENSORS] = {};
  bool s_liveMutedDefault[MAX_SENSORS] = {};
  // PRODUCTION_PREFLIGHT
  uint16_t synchronousMaxSampleRateHz() { return 0; }
  bool validateLoggingStart(const LoggerConfig& cfg, uint16_t, char*, size_t) {
    ++prepares; events.push_back("prepare"); preparedFormat = cfg.logFormat; return validateOk;
  }
  bool onLoggingStart(char*, size_t) { events.push_back("sensors"); return sensorsStartOk; }
  void onLoggingStop() { events.push_back("sensor_stop"); }
  void onLoggingFinalized() { events.push_back("finalize"); }
  uint8_t activeCount() { return 2; }
}

class ConfigManager {
public:
  static LoggerConfig s_cfg;
  static const LoggerConfig& get() { return g_cfg; }
  static bool save(const LoggerConfig& cfg) {
    events.push_back("save");
    if (!saveOk) return false;
    savedConfig = cfg; g_cfg = cfg; return true;
  }
  static bool setLogFormat(LogFormat, bool persist = true);
};
LoggerConfig ConfigManager::s_cfg;
// PRODUCTION_FORMAT

namespace UI {
  bool modal = false;
  bool isModal() { return modal; }
  void toast(const char*, int, int) { events.push_back("toast"); }
  void status(const String&) {}
  void loop() { events.push_back("paint"); }
  constexpr int TARGET_SERIAL = 0, LVL_INFO = 0;
  void println(const char*, const char*, int, int) {}
}
namespace UploadModeManager { bool isActive() { return upload; } }
namespace PowerManager { bool canStartLogging() { return powerOk; } }
bool StorageManager_readyForLogging() { return storageOk; }
const char* StorageManager_lastStatus() { return "test"; }
uint32_t StorageManager_getSampleIntervalUs() { return 2000; }
void StorageManager_setSampleRate(uint16_t) {}
unsigned StorageManager_getSampleRateHz() { return 500; }
bool StorageManager_startLog() { events.push_back("file"); fileFormat = g_cfg.logFormat; return openOk; }
void StorageManager_stopLog() { events.push_back("close"); }
namespace AnalogInputManager {
  uint16_t configureFromConfig(const LoggerConfig&, uint16_t rate) { return rate; }
  void onLoggingStart() {}
  void onLoggingStop() {}
}
namespace I2CManager { void resetRecoveryStats() {} }
namespace WebServerManager { bool isRunning() { return false; } void stop() {} }
namespace WiFiManager { void suspendForLogging() {} void resumeAfterLogging() { events.push_back("wifi_resume"); } }
bool RTCManager_hasValidTime() { return true; }
uint64_t RTCManager_getEpochMs() { return 100000; }
namespace DisplayManager { void prepareLoggingScreen(uint16_t, uint8_t) { events.push_back("screen"); } }
namespace IndicatorManager { void ledOn() {} }

namespace LoggingManager {
  enum class StartFailureHint { None, RestartNow, ConfigConflict };
  enum class StopReason { StartFailure };
  struct StopContext {};
  void refreshConfigurationStatus();
  LoggingConfigIssue configurationIssue();
  const char* configurationDetail();
  bool start();
}
const LoggerConfig* s_cfg = &g_cfg;
bool s_running = false;
LoggingManager::StartFailureHint s_startFailureHint;
LoggingManager::StopContext s_stopContext;
LoggingConfigIssue s_configurationIssue = LoggingConfigIssue::None;
char s_configurationDetail[160] = {};
uint32_t s_intervalUs;
uint64_t s_t0UnixUs, s_sampleCount;
void captureStopContext_(LoggingManager::StopReason, const char*) {}
// PRODUCTION_START

enum ButtonEvent { BUTTON_PRESSED, BUTTON_RELEASED, BUTTON_HELD, BUTTON_CLICK };
bool menuActive = false, revealRestartOnPress = false;
int restartCount = 0, boundActions = 0;
namespace MenuSystem { bool isActive() { return menuActive; } }
namespace DeviceRestart { void restart() { ++restartCount; } }
namespace LoggingManager { bool isRunning() { return s_running; } }
// PRODUCTION_NOTICE
namespace ButtonActions {
  void invoke(int, ButtonEvent) {
    ++boundActions;
    if (revealRestartOnPress) {
      SensorManager::s_list[0]->stale = true;
      LoggingManager::refreshConfigurationStatus();
    }
  }
}
HomeRestartGesture s_homeRestart;
struct Binding { uint8_t buttonIndex; ButtonEvent event; int action; };
Binding s_bindings[] = {{0, BUTTON_PRESSED, 1}, {0, BUTTON_RELEASED, 1}};
uint8_t s_bindingCount = 2;
// PRODUCTION_BUTTON

int checks = 0;
void check(bool ok) { ++checks; if (!ok) { fprintf(stderr, "Failed check %d\n", checks); abort(); } }
Sensor live[MAX_SENSORS];
void reset() {
  g_cfg = LoggerConfig{}; savedConfig = LoggerConfig{}; profile = board::BoardProfile{};
  events.clear(); s_running = false; s_configurationIssue = LoggingConfigIssue::None; s_configurationDetail[0] = 0;
  saveOk = powerOk = storageOk = openOk = validateOk = sensorsStartOk = true; upload = false; prepares = 0;
  for (int i = 0; i < MAX_SENSORS; ++i) { SensorManager::s_list[i] = nullptr; live[i] = Sensor{}; }
  profile.analog.count = 3;
  profile.analog.inputs[0].source = board::AnalogSourceType::InternalGpio;
  profile.analog.inputs[0].pin = 10;
  for (int i = 1; i <= 2; ++i) {
    profile.analog.inputs[i].source = board::AnalogSourceType::ExternalAdc;
    profile.analog.inputs[i].external_adc_index = 0;
    profile.analog.inputs[i].external_channel = i;
  }
}
void add(SensorType type, const char* name, int bus, int input, bool present = true) {
  int i = g_cfg.sensorN++;
  g_cfg.sensors[i].type = type;
  snprintf(g_cfg.sensors[i].name, sizeof(g_cfg.sensors[i].name), "%s", name);
  SensorSpec spec; g_cfg.getSensorSpec(i, spec);
  if (type == SensorType::AnalogPot || type == SensorType::AS5600StringPotAnalog) spec.params.setInt("ain", input);
  else { spec.params.setInt("i2c_bus", bus); spec.params.setInt("i2c_addr", input); }
  if (present) {
    live[i].instance = name; SensorManager::s_list[i] = &live[i];
    SensorManager::noteLiveConfiguration(&live[i], spec);
  }
}
LoggingConfigIssue issue() { char e[160]; return SensorManager::configurationIssue(g_cfg, e, sizeof(e)); }
void set(int i, const char* key, const char* value) { g_cfg.stores[i].set(key, value); }
bool has(const char* event) { return std::find(events.begin(), events.end(), event) != events.end(); }
int index(const char* event) { return std::find(events.begin(), events.end(), event) - events.begin(); }
int main() {
  using T = SensorType; using I = LoggingConfigIssue;
  reset(); check(issue() == I::None);
  add(T::BMI270ImuI2C, "imu0", 1, 104); add(T::BMI270ImuI2C, "imu1", 1, 105);
  check(issue() == I::None); check(SensorManager::requiresBdqV2(g_cfg));
  check(LoggingManager::start()); check(s_running); check(savedConfig.logFormat == LogFormat::BodaqsMultiStreamBinary);
  check(preparedFormat == LogFormat::BodaqsMultiStreamBinary); check(fileFormat == preparedFormat);
  check(index("save") < index("prepare")); check(index("prepare") < index("file")); check(index("file") < index("sensors")); check(has("paint"));
  reset(); add(T::BMI270ImuI2C,"a",1,104); add(T::BMI270ImuI2C,"b",1,104,false);
  check(issue() == I::Conflict); check(!LoggingManager::start()); check(s_startFailureHint == LoggingManager::StartFailureHint::ConfigConflict);
  check(!has("save") && !has("file") && prepares == 0);
  g_cfg.sensors[1].mutedDefault = true; check(issue() == I::None); check(!SensorManager::requiresBdqV2(g_cfg));
  reset(); add(T::BMI270ImuI2C,"a",1,104); add(T::BMI270ImuI2C,"b",1,105);
  live[1].stale = true; check(issue() == I::RestartRequired); check(!LoggingManager::start());
  check(s_startFailureHint == LoggingManager::StartFailureHint::RestartNow); check(!has("save") && !has("file"));
  live[1].stale = false; check(issue() == I::None);
  saveOk = false; check(!LoggingManager::start()); check(g_cfg.logFormat == LogFormat::BodaqsStandard); check(!has("file") && prepares == 0);
  reset(); add(T::BMI270ImuI2C,"a",1,104);
  check(!SensorManager::requiresBdqV2(g_cfg)); check(LoggingManager::start()); check(!has("save")); check(fileFormat == LogFormat::BodaqsStandard);
  reset(); add(T::BMI270ImuI2C,"a",1,104); set(0,"profile","accel_800_gyro_200");
  check(SensorManager::requiresBdqV2(g_cfg)); g_cfg.logFormat = LogFormat::BodaqsCompactBinary;
  check(LoggingManager::start()); check(fileFormat == LogFormat::BodaqsMultiStreamBinary);
  reset(); add(T::AS5600AngleI2C,"angle",1,54); add(T::AS5600StringPotI2C,"pot",1,54); check(issue() == I::Conflict);
  set(1,"i2c_bus","0"); check(issue() == I::RestartRequired);
  SensorSpec spec; g_cfg.getSensorSpec(1,spec); SensorManager::noteLiveConfiguration(&live[1],spec); check(issue() == I::None);
  profile.fuel.type = board::FuelGaugeType::MAX17048; profile.fuel.bus_index = 0; check(issue() == I::Conflict);
  profile.fuel.type = board::FuelGaugeType::None; set(1,"i2c_bus","1"); live[1].mute = true; check(issue() == I::None);
  live[1].mute = false; check(issue() == I::Conflict);
  reset(); add(T::AnalogPot,"pot",0,0); add(T::AS5600StringPotAnalog,"angle",0,-1); set(1,"pin","10"); check(issue() == I::Conflict);
  reset(); add(T::AnalogPot,"pot",0,1); add(T::AnalogPot,"pot2",0,2); check(issue() == I::None);
  profile.analog.inputs[2].differential = true; profile.analog.inputs[2].negative_channel = 1; check(issue() == I::Conflict);
  reset(); add(T::BMI270ImuI2C,"a",0,104); add(T::BMI270ImuI2C,"b",1,104); check(issue() == I::None);
  set(0,"imu_id","same"); set(1,"imu_id","SAME"); check(issue() == I::Conflict);
  set(1,"imu_id","different"); snprintf(g_cfg.sensors[1].name,16,"A"); check(issue() == I::Conflict);
  reset(); add(T::BMI270ImuI2C,"a",1,104,false); check(issue() == I::RestartRequired);
  reset(); add(T::BMI270ImuI2C,"a",1,104); g_cfg.sensorN = 0; check(issue() == I::RestartRequired);
  live[0].mute = true; check(issue() == I::None);
  reset(); add(T::AS5600AngleI2C,"angle",1,54); set(0,"i2c_addr","55"); check(issue() == I::RestartRequired);
  set(0,"i2c_addr","54"); check(issue() == I::None);
  g_cfg.sensors[0].type = T::AS5048BAngleI2C; check(issue() == I::RestartRequired);
  g_cfg.sensors[0].type = T::Unknown; check(issue() == I::InvalidConfig);
  reset(); add(T::AnalogPot,"pot",0,9); check(issue() == I::InvalidConfig);
  reset(); add(T::BMI270ImuI2C,"a",1,104); g_cfg.sensors[0].mutedDefault = true; check(issue() == I::RestartRequired);
  live[0].mute = true; g_cfg.getSensorSpec(0,spec); SensorManager::noteLiveConfiguration(&live[0],spec); check(issue() == I::None);
  live[0].mute = false; check(issue() == I::None); // menu unmute overrides saved default
  HomeRestartGesture gesture;
  check(!gesture.update(false,true,false)); check(!gesture.update(true,false,true)); // failed start release
  check(!gesture.update(true,true,false)); check(gesture.update(true,false,true)); check(!gesture.update(true,false,true));
  check(!gesture.update(true,true,false)); check(!gesture.update(false,false,false)); check(!gesture.update(true,false,true)); // menu closes
  check(!gesture.update(true,true,false)); check(!gesture.update(false,false,true)); // prompt resolved
  reset(); add(T::BMI270ImuI2C,"a",1,104); add(T::BMI270ImuI2C,"b",1,105);
  upload = true; check(!LoggingManager::start() && !has("save"));
  upload = false; powerOk = false; check(!LoggingManager::start() && !has("save"));
  powerOk = true; storageOk = false; check(!LoggingManager::start() && !has("save"));
  storageOk = true; openOk = false; check(!LoggingManager::start()); check(has("wifi_resume") && !s_running);
  reset(); add(T::BMI270ImuI2C,"a",1,104); sensorsStartOk = false;
  check(!LoggingManager::start()); check(has("close") && has("finalize") && has("sensor_stop") && !s_running);
  reset(); add(T::BMI270ImuI2C,"a",1,104);
  profile.buttons.count = 1; strcpy(profile.buttons.btn[0].id,"nav_enter");
  revealRestartOnPress = true;
  handleButtonBinding_(0,BUTTON_PRESSED); // start action exposes restart warning
  check(boundActions == 1 && restartCount == 0);
  handleButtonBinding_(0,BUTTON_RELEASED);
  check(boundActions == 1 && restartCount == 0);
  revealRestartOnPress = false;
  handleButtonBinding_(0,BUTTON_PRESSED); handleButtonBinding_(0,BUTTON_RELEASED);
  check(restartCount == 1 && boundActions == 1);
  handleButtonBinding_(0,BUTTON_CLICK); check(restartCount == 1 && boundActions == 1);
  menuActive = true; handleButtonBinding_(0,BUTTON_PRESSED);
  menuActive = false; handleButtonBinding_(0,BUTTON_RELEASED); check(restartCount == 1);
  handleButtonBinding_(0,BUTTON_PRESSED); live[0].stale = false;
  handleButtonBinding_(0,BUTTON_RELEASED); check(restartCount == 1); // reverted edit cancels acknowledgment
  live[0].stale = true; UI::modal = true;
  handleButtonBinding_(0,BUTTON_PRESSED); check(restartCount == 1);
  UI::modal = false; handleButtonBinding_(0,BUTTON_RELEASED); check(restartCount == 1);
  handleButtonBinding_(0,BUTTON_PRESSED); handleButtonBinding_(0,BUTTON_RELEASED); check(restartCount == 2);
  reset(); add(T::BMI270ImuI2C,"a",1,104); g_cfg.getSensorSpec(0,spec);
  BMI270ImuSensor bmi; bmi.loadParams_(bmi.params_, spec.name, spec.params);
  char error[128]; check(!bmi.loggingRestartRequired(spec,error,sizeof(error)));
  const char* edits[][2] = {{"profile","orientation_400"}, {"fifo_poll_rate_hz","25"},
    {"startup_bias_capture_s","10"}, {"max_output_rate_hz","100"}, {"gyro_bias_mode","ioc"},
    {"ioc_diagnostics","true"}, {"calibration_ref","other"}, {"orient_plane","xy"},
    {"orient_normal_sign","-1"}, {"domain","steering"}, {"end","front"}, {"imu_id","other"},
    {"mount_point","fork"}};
  for (const auto& edit : edits) {
    set(0,edit[0],edit[1]); check(bmi.loggingRestartRequired(spec,error,sizeof(error)));
    g_cfg.stores[0].remove(edit[0]); check(!bmi.loggingRestartRequired(spec,error,sizeof(error)));
  }
  set(0,"profile","orientation_400"); bmi.loadParams_(bmi.params_,spec.name,spec.params);
  check(!bmi.loggingRestartRequired(spec,error,sizeof(error))); // successful live apply clears mismatch
  check(configurationNotice_().indexOf("alert-warn") < 0);
  live[0].stale = true;
  check(configurationNotice_().indexOf("Restart required") >= 0);
  add(T::BMI270ImuI2C,"<script>",1,104);
  const String conflictHtml = configurationNotice_(true);
  check(conflictHtml.indexOf("Config conflict") >= 0);
  check(conflictHtml.indexOf("hx-swap-oob='outerHTML'") >= 0);
  check(conflictHtml.indexOf("&lt;script&gt;") >= 0 && conflictHtml.indexOf("<script>") < 0);
  live[0].stale = false; live[1].mute = true;
  const String clearedHtml = configurationNotice_(true);
  check(clearedHtml.indexOf("logging-config-notice") >= 0 && clearedHtml.indexOf("alert-warn") < 0);
  printf("Logging start runtime: %d checks passed\n", checks);
}
