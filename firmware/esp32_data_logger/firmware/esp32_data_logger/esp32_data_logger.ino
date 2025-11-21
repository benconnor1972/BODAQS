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

//static void buildSensorsFromConfig();
void onToggleLogging(ButtonEvent event);
void onMarkEvent(ButtonEvent event);
void onWebServerToggle(ButtonEvent event);


LoggerConfig g_cfg;   // holds everything we load from loggercfg
TransformRegistry gTransforms;
SdFs* gSd = nullptr;   // SdFat typedefs to SdFs



static bool isLoggingPredicate() { return LoggingManager::isRunning(); }

void setup() {
  Serial.begin(115200);

  RTCManager_setHumanReadable(true); // false = fast integer, true = readable
  StorageManager_begin(5);           // CS pin depends on your SD breakout
  gSd = StorageManager_getSd();      // <-- add this line

  // Debug settings
  Log_setEnabled(true);
  Log_setLevel(LOG_DEBUG);

  StorageManager_setSampleRate(100);   // 100 Hz logging
  StorageManager_setBufferSize(32768);  // 1 KB buffer

  // UI / OLED defaults (fallbacks)
  g_cfg.uiTarget       = 1;     // serial
  g_cfg.uiSerialLevel  = 3;     // info
  g_cfg.uiOledLevel    = 3;     // info
  g_cfg.oledBrightness = 200;   // nominal contrast
  g_cfg.oledIdleDimMs  = 30000; // 30s
  g_cfg.sampleRateHz   = 100;   // fallback

  ConfigManager::begin(StorageManager_getSd(), "/config/loggercfg.txt");
  //ConfigManager::debugDumpConfigFile();

  if (!ConfigManager::load(g_cfg)) {
    Serial.println("[CFG] Load failed — using defaults");
  } else {
    Serial.printf("[CFG] Loaded: sampleRate=%u Hz, enter=%u up=%u down=%u left=%u right=%u web=%u log=%u mark=%u\n",
      g_cfg.sampleRateHz, g_cfg.navEnterPin, g_cfg.navUpPin, g_cfg.navDownPin, g_cfg.navLeftPin, g_cfg.navRightPin,
      g_cfg.webBtnPin, g_cfg.logBtnPin, g_cfg.markBtnPin);
  }

  ButtonBindingTable::initFromConfig(ConfigManager::get());


  // 1) Sensor framework
  SensorManager::begin(&g_cfg);
  SensorManager::buildSensorsFromConfig(g_cfg);
  SensorManager::finalizeBegin();
  //PROBE("[SENS] debugDump");
  //SensorManager::debugDump("after-register");
  UI::status("Sensors ready");

  StorageManager_setSampleRate(g_cfg.sampleRateHz);


  //ConfigManager::print(g_cfg);
  //Serial.println("[BOOT] after ConfigManager::print");
  //Serial.flush();

  WebServerManager::attachConfig(&g_cfg);
  WebServerManager::begin(StorageManager_getSd(), isLoggingPredicate);

  const auto& cfg = ConfigManager::get();

  // Bring Wi-Fi up on boot only if the user asked for it by default
  if (ConfigManager::hasConfiguredNetworks() && cfg.wifiEnabledDefault) {
    WiFiManager::enable();
    WiFiManager::connectNow();   // one pass: scan → select → connect
  }

 
  // Choose RTC
  RTCManager_begin(RTC_INTERNAL);
  // RTCManager_begin(RTC_EXTERNAL);

  // Timezone + NTP list
  String n1, n2, n3;
  splitCsv3(g_cfg.ntpServers, n1, n2, n3);
  configTzTime(g_cfg.tz, n1.length()? n1.c_str(): nullptr, n2.length()? n2.c_str(): nullptr, n3.length()? n3.c_str(): nullptr);
  
  WiFiManager::begin();
  WiFiManager::maybeConnectForRTC();   

  // 3) Init logging *after* sensors exist
  LoggingManager::begin(&g_cfg);

  // Start OLED if present
  DisplayManager::begin(g_cfg);

  // Configure routing (Serial/OLED/Both + levels)
  UI::begin(g_cfg);

  // Show initial status
  UI::status("Ready");
  UI::println("Device ready.", "", UI::TARGET_SERIAL, UI::LVL_INFO, 1200);

  ButtonActions::begin();

  ConfigManager::printAllCalibrations();

  // Start the menu system
  MenuSystem::begin(&g_cfg);
  MenuSystem::setIdleCloseMs(120000);
}

void loop() {
  WiFiManager::loop();
  RTCManager_loop();
  ButtonManager_loop();
  StorageManager_loop();
  WebServerManager::loop();
  UI::loop();
  MenuSystem::loop();
  LoggingManager::loop();
}



