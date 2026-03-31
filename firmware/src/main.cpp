#include <Arduino.h>
#include "ButtonManager.h"

#include "Calibration.h"
#include "RTCManager.h"
#include "StorageManager.h"
#include "WebServerManager.h"
#include "WiFi.h"
#include "ConfigManager.h"
#include "DisplayManager.h"
#include "UI.h"
#include "LoggingManager.h"
#include "ButtonActions.h"
#include "ButtonBindingTable.h"
#include "Sensor.h"
#include "SensorManager.h"
#include "AnalogPotSensor.h"
#include "DebugLog.h"
#include "MenuSystem.h"
#include "SensorRegistry.h"
#include "TransformRegistry.h"
#include "OutputTransform.h"
#include "WiFiManager.h"
#include "BoardSelect.h"
#include "I2CManager.h"
#include "IndicatorManager.h"
#include "PowerManager.h"
#include "BoardProfile.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_heap_caps.h"

#include "FS.h"
#include "SD_MMC.h"
#include <SdFat.h>

#define PROBE(msg) do { LOGI(msg); delay(2); } while(0)
#define BOOT_LOGW(...) LOGW_TAG("BOOT", __VA_ARGS__)
#define BOOT_LOGE(...) LOGE_TAG("BOOT", __VA_ARGS__)
#define BOOT_LOGI(...) LOGI_TAG("BOOT", __VA_ARGS__)
#define HB_LOGD(...)   LOGD_TAG("HB", __VA_ARGS__)
#define ADC_LOGD(...)  LOGD_TAG("ADC", __VA_ARGS__)


//Debug
static void dbgHeartbeat_()
{
  static uint32_t last = 0;
  uint32_t now = millis();
  if (now - last < 5000) return;
  last = now;

  HB_LOGD("ms=%lu core=%d heap=%u largest=%u\n",
          (unsigned long)now,
          xPortGetCoreID(),
          ESP.getFreeHeap(),
          heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

  // Optional: stack watermark for loop task (call from the task you care about)
  HB_LOGD("stack watermark=%u\n", (unsigned)uxTaskGetStackHighWaterMark(nullptr));
}


// --- Small utils ------------------------------------------------------------

// Parse "ZERO,RANGE" → CalMask (case-insensitive). Unknown tokens are ignored.
static CalMask parseCalMaskCSV(const char* csv) {
  if (!csv || !*csv) return CAL_NONE;
  CalMask m = CAL_NONE;

  auto ieq = [](char a, char b) {
    if (a >= 'a' && a <= 'z') a = char(a - 32);
    if (b >= 'a' && b <= 'z') b = char(b - 32);
    return a == b;
  };
  auto tokenEq = [&](const char* tok, const char* lit) {
    while (*tok && *tok != ' ' && *tok != '\t') {
      if (!*lit || !ieq(*tok, *lit)) return false;
      ++tok; ++lit;
    }
    return *lit == '\0';
  };

  const char* p = csv;
  while (*p) {
    while (*p == ',' || *p == ' ' || *p == '\t') ++p;
    if (!*p) break;
    const char* start = p;
    while (*p && *p != ',') ++p;

    // trim end spaces
    const char* end = p;
    while (end > start && (end[-1] == ' ' || end[-1] == '\t')) --end;

    char buf[24];
    size_t len = size_t(end - start);
    if (len >= sizeof(buf)) len = sizeof(buf) - 1;
    memcpy(buf, start, len);
    buf[len] = '\0';

    // normalize leading/trailing spaces already handled
    if (tokenEq(buf, "ZERO"))  m = (CalMask)(m | CAL_ZERO);
    if (tokenEq(buf, "RANGE")) m = (CalMask)(m | CAL_RANGE);
  }
  return m;
}

// ----------------------------------------------------------------------------

static void buildSensorsFromConfig();
static bool s_rtcConnectIntent = false;
void onToggleLogging(ButtonEvent event);
void onMarkEvent(ButtonEvent event);
void onWebServerToggle(ButtonEvent event);

static void applyLogSettings_(const LoggerConfig& cfg) {
  Log_setEnabled(true);
  Log_resetLevel();
  if (cfg.logLevelOverride <= LOG_TRACE) {
    Log_setLevel((LogLevel)cfg.logLevelOverride);
  }
}


LoggerConfig g_cfg;  
TransformRegistry gTransforms;
SdFs*  gSd = nullptr;     // stays for SPI SdFat backend
fs::FS* gFs = nullptr;    // NEW: active filesystem for SDMMC (and could be used for SPI too if you want)

using namespace board;

static bool isLoggingPredicate() { return LoggingManager::isRunning(); }

void setup() {
  
    Serial.begin(115200);
    SelectBoard(BoardID::ThingPlusS3_BODAQS_4_D);
    DumpActiveBoardButtons();

    //Debug
    auto dumpAdc = [](const char* tag){
      ADC_LOGD("\n%s\n", tag);
      int pins[] = {15,17,18,10};
      for (int p : pins) {
        int v = analogRead(p);
        LOGD("  GPIO%02d = %d\n", p, v);
      }
    };

    dumpAdc("before WiFi");


  if (!gBoard) {
    BOOT_LOGE("FATAL: Board not selected\n");
    while (true) delay(1000);
  }
  
  //Buffer debug
  static uint32_t g_sampleCounter = 0;

  RTCManager_setHumanReadable(true); // false = fast integer, true = readable
  StorageManager_begin(*gBoard);           
  gSd = StorageManager_getSd();      

  applyLogSettings_(g_cfg);

  StorageManager_setSampleRate(100);   // 100 Hz logging

  // UI / OLED defaults (fallbacks)
  g_cfg.uiTarget       = 1;     // serial
  g_cfg.uiSerialLevel  = 3;     // info
  g_cfg.uiOledLevel    = 3;     // info
  g_cfg.oledBrightness = 200;   // nominal contrast
  g_cfg.oledIdleDimMs  = 30000; // 30s
  g_cfg.sampleRateHz   = 100;   // fallback

  IndicatorManager::begin(*board::gBoard);

  ConfigManager::begin(StorageManager_getSd(), "/config/loggercfg.txt");


  if (!ConfigManager::load(g_cfg)) {
    LOGW_TAG("CFG", "Load failed, using defaults\n");
  } else {
    LOGI_TAG("CFG", "Loaded");
  }

  applyLogSettings_(g_cfg);
  BOOT_LOGI("SETUP: A ButtonBindingTable::initFromConfig\n");
  ButtonBindingTable::initFromConfig(ConfigManager::get());
  BOOT_LOGI("SETUP: A done\n");
  RTCManager_setTimezone(g_cfg.tz);
  const auto& cfg = ConfigManager::get();
  I2CManager::begin(*gBoard);


  // 1) Sensor framework
  BOOT_LOGI("SETUP: B Sensormanager::begin\n");

  SensorManager::begin(&g_cfg);
    BOOT_LOGI("SETUP: B done\n");

  BOOT_LOGI("SETUP: C buildsensorsfromFromConfig\n");

  SensorManager::buildSensorsFromConfig(g_cfg);
  BOOT_LOGI("SETUP: C done\n");

  BOOT_LOGI("SETUP: D finalize begin\n");

  SensorManager::finalizeBegin();
    BOOT_LOGI("SETUP: D done\n");

  //PROBE("[SENS] debugDump");
  //SensorManager::debugDump("after-register");
  UI::status("Sensors ready");

  StorageManager_setSampleRate(g_cfg.sampleRateHz);


  //ConfigManager::print(g_cfg);
  // Boot probe after ConfigManager::print.
  //Serial.flush();

  BOOT_LOGI("SETUP: E webservermanager::attachconfig\n");
  WebServerManager::attachConfig(&g_cfg);
      BOOT_LOGI("SETUP: E done\n");

  BOOT_LOGI("SETUP: F storagemanager_getSD\n");

  WebServerManager::begin(StorageManager_getSd(), isLoggingPredicate);
    BOOT_LOGI("SETUP: F done\n");

  // Choose RTC
  RTCManager_begin(RTC_INTERNAL);
  // RTCManager_begin(RTC_EXTERNAL, I2CManager::bus(0));

  //Initialise wifi manager
  BOOT_LOGI("SETUP: G wifimanager::begin\n");
  WiFiManager::begin(isLoggingPredicate);
  BOOT_LOGI("SETUP: G Done\n");

  // Bring Wi-Fi up on boot only if the user asked for it by default
  if (ConfigManager::hasConfiguredNetworks() && cfg.wifiEnabledDefault) {
    WiFiManager::enable();
    WiFiManager::connectNow();   // one pass: scan → select → connect
    WiFiManager::maybeConnectForRTC();   

  } else {
    WiFiManager::disable();  // ensures clean OFF
    WiFiManager::maybeConnectForRTC();  // if your signature takes cfg; otherwise keep your existing call
  }

 
  // 3) Init logging *after* sensors exist
  LoggingManager::begin(&g_cfg);

  BOOT_LOGI("SETUP: I Done\n");

  if (gBoard && gBoard->fuel.type != FuelGaugeType::None) {
    PowerManager::fuelGaugeBegin(gBoard->fuel.i2c_addr,
                                 I2CManager::bus(gBoard->fuel.bus_index));
  }
  // Start OLED if present
  DisplayManager::begin(cfg,
                        gBoard->display,
                        I2CManager::bus(gBoard->display.bus_index));

  BOOT_LOGI("SETUP: J Done\n");

  // Configure routing (Serial/OLED/Both + levels)
  UI::begin(g_cfg);
    BOOT_LOGI("SETUP: K Done\n");


  // Show initial status
  UI::status("Ready");
  UI::println("Device ready.", "", UI::TARGET_SERIAL, UI::LVL_INFO, 1200);

  ButtonActions::begin();
    BOOT_LOGI("SETUP: L Done\n");


  //ConfigManager::printAllCalibrations();

  // Start the menu system
  MenuSystem::begin(&g_cfg);
    BOOT_LOGI("SETUP: M Done\n");

  MenuSystem::setIdleCloseMs(300000);
  BOOT_LOGI("SETUP: N Done\n");

    BOOT_LOGI("SETUP: ALL DONE\n");

}

void loop() {
  WiFiManager::loop();
  RTCManager_loop();
  ButtonManager_loop();
  StorageManager_loop();       
  WebServerManager::loop();
  UI::loop();
  MenuSystem::loop();
  PowerManager::fuelGaugeLoop();
  //dbgHeartbeat_();
}



