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
#include "IndicatorManager.h"

#define PROBE(msg) do { LOGI(msg); delay(2); } while(0)


// --- Small utils ------------------------------------------------------------

static void splitCsv3(const char* csv, String& s1, String& s2, String& s3) {
  s1 = s2 = s3 = String();
  if (!csv || !*csv) return;
  String all(csv); all.trim();
  int p1 = all.indexOf(',');
  if (p1 < 0) { s1 = all; return; }
  s1 = all.substring(0, p1); s1.trim();
  int p2 = all.indexOf(',', p1 + 1);
  if (p2 < 0) { s2 = all.substring(p1 + 1); s2.trim(); return; }
  s2 = all.substring(p1 + 1, p2); s2.trim();
  s3 = all.substring(p2 + 1); s3.trim();
}

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


LoggerConfig g_cfg;  
TransformRegistry gTransforms;
SdFs* gSd = nullptr; 


using namespace board;

static bool isLoggingPredicate() { return LoggingManager::isRunning(); }

void setup() {
  
    Serial.begin(115200);
    SelectBoard(BoardID::ThingPlusS3_BODAQS_4_D);
    DumpActiveBoardButtons();

  if (!gBoard) {
    Serial.println("FATAL: Board not selected");
    while (true) delay(1000);
  }
  
  //Buffer debug
  static uint32_t g_sampleCounter = 0;

  RTCManager_setHumanReadable(true); // false = fast integer, true = readable
  StorageManager_begin(*gBoard);           
  gSd = StorageManager_getSd();      

  // Debug settings
  Log_setEnabled(true);
  Log_setLevel(LOG_DEBUG);

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
    Serial.println("[CFG] Load failed — using defaults");
  } else {
    Serial.printf("[CFG] Loaded");
  }

  Serial.println("SETUP: A ButtonBindingTable::initFromConfig");
  ButtonBindingTable::initFromConfig(ConfigManager::get());
  Serial.println("SETUP: A done");


  // 1) Sensor framework
  Serial.println("SETUP: B Sensormanager::begin");

  SensorManager::begin(&g_cfg);
    Serial.println("SETUP: B done");

  Serial.println("SETUP: C buildsensorsfromFromConfig");

  SensorManager::buildSensorsFromConfig(g_cfg);
  Serial.println("SETUP: C done");

  Serial.println("SETUP: D finalize begin");

  SensorManager::finalizeBegin();
    Serial.println("SETUP: D done");

  //PROBE("[SENS] debugDump");
  //SensorManager::debugDump("after-register");
  UI::status("Sensors ready");

  StorageManager_setSampleRate(g_cfg.sampleRateHz);


  //ConfigManager::print(g_cfg);
  //Serial.println("[BOOT] after ConfigManager::print");
  //Serial.flush();

  Serial.println("SETUP: E webservermanager::attachconfig");
  WebServerManager::attachConfig(&g_cfg);
      Serial.println("SETUP: E done");

  Serial.println("SETUP: F storagemanager_getSD");

  WebServerManager::begin(StorageManager_getSd(), isLoggingPredicate);
    Serial.println("SETUP: F done");

  const auto& cfg = ConfigManager::get();

  // Choose RTC
  RTCManager_begin(RTC_INTERNAL);
  // RTCManager_begin(RTC_EXTERNAL);

  //Initialise wifi manager
  Serial.println("SETUP: G wifimanager::begin");
  WiFiManager::begin(isLoggingPredicate);
  Serial.println("SETUP: G Done");

  // Bring Wi-Fi up on boot only if the user asked for it by default
  if (ConfigManager::hasConfiguredNetworks() && cfg.wifiEnabledDefault) {
    WiFiManager::enable();
    WiFiManager::connectNow();   // one pass: scan → select → connect
    WiFiManager::maybeConnectForRTC();   

  } else {
    WiFiManager::disable();  // ensures clean OFF
    WiFiManager::maybeConnectForRTC();  // if your signature takes cfg; otherwise keep your existing call
  }

 


  // Timezone + NTP list
  String n1, n2, n3;
  splitCsv3(g_cfg.ntpServers, n1, n2, n3);
  configTzTime(g_cfg.tz, n1.length()? n1.c_str(): nullptr, n2.length()? n2.c_str(): nullptr, n3.length()? n3.c_str(): nullptr);

  // 3) Init logging *after* sensors exist
  LoggingManager::begin(&g_cfg);

  Serial.println("SETUP: I Done");

  // Start OLED if present
  DisplayManager::begin(cfg, gBoard->display, gBoard->i2c);

  Serial.println("SETUP: J Done");

  // Configure routing (Serial/OLED/Both + levels)
  UI::begin(g_cfg);
    Serial.println("SETUP: K Done");


  // Show initial status
  UI::status("Ready");
  UI::println("Device ready.", "", UI::TARGET_SERIAL, UI::LVL_INFO, 1200);

  ButtonActions::begin();
    Serial.println("SETUP: L Done");


  //ConfigManager::printAllCalibrations();

  // Start the menu system
  MenuSystem::begin(&g_cfg);
    Serial.println("SETUP: M Done");

  MenuSystem::setIdleCloseMs(300000);
  Serial.println("SETUP: N Done");

    Serial.println("SETUP: ALL DONE");

}

void loop() {
  WiFiManager::loop();
  RTCManager_loop();
  ButtonManager_loop();
  StorageManager_loop();       
  WebServerManager::loop();
  UI::loop();
  MenuSystem::loop();
}



