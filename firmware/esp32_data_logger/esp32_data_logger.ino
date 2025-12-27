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
#include "esp_system.h"
#include "esp_heap_caps.h"

#define PROBE(msg) do { LOGI(msg); delay(2); } while(0)

static uint32_t lastHeapReport = 0;

// --- Small utils ------------------------------------------------------------
static const char* resetReasonStr(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON:   return "POWERON";
    case ESP_RST_EXT:       return "EXT";
    case ESP_RST_SW:        return "SW";
    case ESP_RST_PANIC:     return "PANIC";
    case ESP_RST_INT_WDT:   return "INT_WDT";
    case ESP_RST_TASK_WDT:  return "TASK_WDT";
    case ESP_RST_WDT:       return "WDT";
    case ESP_RST_BROWNOUT:  return "BROWNOUT";
    default:                return "OTHER";
  }
}

static void printBootDiag() {
  esp_reset_reason_t r = esp_reset_reason();
  Serial.printf("[BOOT] reset_reason=%d (%s)\n", (int)r, resetReasonStr(r));
  Serial.printf("[BOOT] freeHeap=%u minFreeHeap=%u largest8bit=%u\n",
                (unsigned)ESP.getFreeHeap(),
                (unsigned)ESP.getMinFreeHeap(),
                (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
}

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


using namespace board;

void setup() {
  
  Serial.printf("[WS] start of setup: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

    SelectBoard(BoardID::ThingPlus_A);
    DumpActiveBoardButtons();

  // Optional sanity check
  if (!gBoard) {
    Serial.println("FATAL: Board not selected");
    while (true) delay(1000);
  }
  
  Serial.begin(115200);

  //Buffer debug
  static uint32_t g_sampleCounter = 0;


  RTCManager_setHumanReadable(true); // false = fast integer, true = readable

  Serial.printf("[WS] before storage_begin: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

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

  Serial.printf("[WS] before configmanager::begin: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

  ConfigManager::begin(StorageManager_getSd(), "/config/loggercfg.txt");
  //ConfigManager::debugDumpConfigFile();

  if (!ConfigManager::load(g_cfg)) {
    Serial.println("[CFG] Load failed — using defaults");
  } else {
    Serial.printf("[CFG] Loaded");
  }

  Serial.println("SETUP: A ButtonBindingTable::initFromConfig");
  ButtonBindingTable::initFromConfig(ConfigManager::get());
  Serial.println("SETUP: A done");

  Serial.printf("[WS] before sensormanager::begin: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

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

  Serial.printf("[WS] after sensormanager::finalisebegin: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

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

  Serial.printf("[WS] after webservermanager::attachconfig: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

  Serial.println("SETUP: F storagemanager_getSD");

  WebServerManager::begin(StorageManager_getSd());
    Serial.println("SETUP: F done");

  Serial.printf("[WS] after storagemanager_getsd: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));


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
  
  Serial.printf("[WS] after RTCmanager: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

    Serial.println("SETUP: G wifimanager::begin");

  WiFiManager::begin();

  Serial.println("SETUP: G Done");

  Serial.printf("[WS] after WiFimanager::begin: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

    Serial.println("SETUP: H maybeconnectforRTC");

  WiFiManager::maybeConnectForRTC();   
  Serial.println("SETUP: H Done");


  // 3) Init logging *after* sensors exist
  LoggingManager::begin(&g_cfg);

  Serial.println("SETUP: I Done");

  Serial.printf("[WS] after Loggingmanager: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

  // Start OLED if present
  DisplayManager::begin(cfg, gBoard->display, gBoard->i2c);

  Serial.println("SETUP: J Done");
  Serial.printf("[WS] after Displaymanager: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

  // Configure routing (Serial/OLED/Both + levels)
  UI::begin(g_cfg);
    Serial.println("SETUP: K Done");

  Serial.printf("[WS] after UI::begin: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

  // Show initial status
  UI::status("Ready");
  UI::println("Device ready.", "", UI::TARGET_SERIAL, UI::LVL_INFO, 1200);

  ButtonActions::begin();
    Serial.println("SETUP: L Done");

  Serial.printf("[WS] after buttonactions: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

  //ConfigManager::printAllCalibrations();

  // Start the menu system
  MenuSystem::begin(&g_cfg);
    Serial.println("SETUP: M Done");

  MenuSystem::setIdleCloseMs(120000);
  Serial.println("SETUP: N Done");

    Serial.println("SETUP: ALL DONE");

  Serial.printf("[WS] after menusystem: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

}

void loop() {
  WebServerManager::loop();
  WiFiManager::loop();
  RTCManager_loop();
  ButtonManager_loop();
  StorageManager_loop();       // consumer: formats & flushes to SD
  UI::loop();
  MenuSystem::loop();

  uint32_t dt = millis() - lastHeapReport;
  if (dt > 2000) {
    Serial.printf("[Main loop]: heap free=%lu largest=%lu\n",
    (unsigned long)ESP.getFreeHeap(),
    (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
    lastHeapReport = millis();
  }
}



