#include <WiFi.h>
#include <WebServer.h>
#include <Arduino.h>
#include <ArduinoJson.h>
#include <SdFat.h>
#include "WebServerManager.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "SensorTypes.h"
#include "Sensor.h"
#include "TransformRegistry.h"
#include "OutputTransform.h"
#include "WiFiManager.h"
#include "PowerManager.h"
#include "Routes_Files.h"
#include "Routes_Config.h"
#include "Routes_Transforms.h"
#include "HtmlUtil.h"
#include "DebugLog.h"
using namespace HtmlUtil;

#define WS_LOGE(...) LOGE_TAG("WS", __VA_ARGS__)
#define WS_LOGW(...) LOGW_TAG("WS", __VA_ARGS__)
#define WS_LOGI(...) LOGI_TAG("WS", __VA_ARGS__)
#define WS_LOGD(...) LOGD_TAG("WS", __VA_ARGS__)


// gTransforms is defined in esp32_data_logger.ino (non-static there)
extern TransformRegistry gTransforms;
static SdFs*g_sd = nullptr;                     // defined in esp32_data_logger.ino: SdFs* gSd = nullptr;

// --- Module state ---
static WebServer* g_server = nullptr;
static WebServerManager::IsLoggingFn g_isLogging = nullptr;
static bool g_running = false;
SdFs* WebServerManager::sd() { return g_sd; }

// Pointer to the live config struct
static LoggerConfig* g_cfgPtr = nullptr;

// -------------------- fwd decls --------------------
static bool ensureSd();

static CalModeMask parseCalAllowedCSV_(const String& csv);


// Diagnostics
// --- Diagnostics ---
static volatile uint32_t g_ws_loop_ticks = 0;
static volatile uint32_t g_ws_req_total  = 0;
static volatile uint32_t g_ws_req_2xx    = 0;
static volatile uint32_t g_ws_req_4xx    = 0;
static volatile uint32_t g_ws_req_5xx    = 0;
static volatile uint32_t g_ws_inflight   = 0;
static uint32_t          g_ws_last_req_ms   = 0;
static uint32_t          g_ws_last_2xx_ms   = 0;
static uint32_t          g_ws_last_err_ms   = 0;
static uint32_t          g_ws_last_beat_ms  = 0;

static void ws_diag_on_request() {
  ++g_ws_req_total;
  ++g_ws_inflight;
  g_ws_last_req_ms = millis();
}
static void ws_diag_on_response(int code) {
  if (code >= 200 && code < 300) { ++g_ws_req_2xx; g_ws_last_2xx_ms = millis(); }
  else if (code >= 400 && code < 500) { ++g_ws_req_4xx; g_ws_last_err_ms = millis(); }
  else if (code >= 500) { ++g_ws_req_5xx; g_ws_last_err_ms = millis(); }
  if (g_ws_inflight) --g_ws_inflight;
}

static void noteHttpActivity_() {
  WiFiManager::noteUserActivity();
  PowerManager::noteActivity();
}


// -------------------- helpers --------------------
static bool ensureSd() {
  if (!g_sd) {
    WS_LOGW("ensureSd: no SdFs* provided (call begin(StorageManager_getSd(), ...) first)\n");
    return false;
  }
  return true; // StorageManager owns begin()
}

// -------------------- public API --------------------
void WebServerManager::begin(SdFs* sdRef, IsLoggingFn isLogging) {
  g_sd        = sdRef;
  g_isLogging = isLogging;
}

void WebServerManager::attachConfig(LoggerConfig* cfg) {
  g_cfgPtr = cfg;
}

void WebServerManager::setStaConfig(const String& ssid, const String& password) {
} //no-op. legacy

bool WebServerManager::canStart() {
  // Only block while logging; do NOT require SdFs here.
  if (g_isLogging && g_isLogging()) {
    return false;
  }
  return true;
}


bool WebServerManager::start() {
  if (g_running) {
    WS_LOGD("start: already running\n");
    return true;
  }

  if (!canStart()) {
    WS_LOGD("start: canStart() = false (probably logging active)\n");
    return false;
  }

  wl_status_t wl = WiFi.status();
  WS_LOGD("start: WiFi.status()=%d (need %d=WL_CONNECTED)\n", (int)wl, (int)WL_CONNECTED);
  if (wl != WL_CONNECTED) {
    WS_LOGI("start: WiFi not connected; will retry from loop()\n");
    return false;
  }

  IPAddress ip = WiFi.localIP();
  WS_LOGI("start: starting on http://%s/\n", ip.toString().c_str());

  // Allocate server and wire routes if first time
  if (!g_server) {
    g_server = new WebServer(80);
    setupRoutes();  // registers all handlers
  }

  g_server->begin();
  g_running = true;

  WS_LOGI("start: listening http://%s/\n", WiFi.localIP().toString().c_str());
  return true;
}



void WebServerManager::stop() {
  if (!g_running) return;

  if (g_server) {
    g_server->stop();     // if available in your core; safe to call if it exists
  }
  g_running = false;
}

bool WebServerManager::isRunning() { return g_running; }

/*
void WebServerManager::loop() {
  if (g_isLogging && g_isLogging()) return;
  if (g_server) g_server->handleClient(); 
  if (!g_running) {
    if (canStart() && WiFi.status() == WL_CONNECTED) {
      // Try to start (safe if called repeatedly)
      start();
    }
  }

  if (g_server) {
    g_server->handleClient();
  }

  // Always yield to keep Wi-Fi stack happy
  delay(0);
  yield();
}
*/

void WebServerManager::loop() {
  if (g_isLogging && g_isLogging()) {
    if (g_running) stop();
    return;
  }

  bool wifiUp = (WiFi.status() == WL_CONNECTED);

  if (wifiUp) {
    if (!g_running) start();  // will call begin(); should be idempotent
    if (g_server) g_server->handleClient();
  } else {
    if (g_running) stop();
  }
}


void WebServerManager::setupRoutes() {
  // Root can stay here (or move into a Routes_Status later)
  g_server->on("/", HTTP_GET, handleRoot);

  // Delegate
  registerFileRoutes(*g_server);
  registerConfigRoutes(*g_server);
  registerTransformRoutes(*g_server);


  // --- debug canary: always available ---
  g_server->on("/__ping", HTTP_GET, [](){
    noteHttpActivity_();
    g_server->send(200, "text/plain", "pong");
  });

  // --- debug health: JSON snapshot ---
  g_server->on("/__health", HTTP_GET, [](){
    noteHttpActivity_();
    String out;
    out.reserve(256);
    out += F("{\"wifi\":");
    out += String((int)WiFi.status());
    out += F(",\"ip\":\""); out += WiFi.localIP().toString(); out += F("\"");
    out += F(",\"running\":"); out += g_running ? F("true") : F("false");
    out += F(",\"canStart\":"); out += canStart() ? F("true") : F("false");
    out += F(",\"sd\":"); out += (g_sd ? F("true") : F("false"));
  #ifdef ESP32
    out += F(",\"heap\":"); out += String((int)ESP.getFreeHeap());
  #endif
    out += F(",\"loopTicks\":"); out += String(g_ws_loop_ticks);
    out += F(",\"reqTotal\":");  out += String(g_ws_req_total);
    out += F(",\"req2xx\":");    out += String(g_ws_req_2xx);
    out += F(",\"req4xx\":");    out += String(g_ws_req_4xx);
    out += F(",\"req5xx\":");    out += String(g_ws_req_5xx);
    out += F(",\"inflight\":");  out += String(g_ws_inflight);
    out += F(",\"lastReqMsAgo\":"); out += String((uint32_t)(millis() - g_ws_last_req_ms));
    out += F(",\"last2xxMsAgo\":"); out += String((uint32_t)(millis() - g_ws_last_2xx_ms));
    out += F(",\"lastErrMsAgo\":"); out += String((uint32_t)(millis() - g_ws_last_err_ms));
    out += F("}");
    g_server->send(200, "application/json", out);
  });

  // --- log *every* unhandled request (method + URI + args) ---
  g_server->onNotFound([](){
    noteHttpActivity_();
    String uri = g_server->uri();
    WS_LOGD("404 %s %s\n",
            (g_server->method() == HTTP_GET ? "GET" :
            g_server->method() == HTTP_POST ? "POST" :
            g_server->method() == HTTP_PUT ? "PUT" :
            g_server->method() == HTTP_DELETE ? "DEL" : "?"),
            uri.c_str());
    const int ac = g_server->args();
    for (int i = 0; i < ac; ++i) {
      LOGD("      arg[%d] %s = %s\n", i,
           g_server->argName(i).c_str(),
           g_server->arg(i).c_str());
    }
    g_server->send(404, "text/plain", "Not found");
  });
}

void WebServerManager::handleRoot() {
  noteHttpActivity_();
  String html = htmlHeader("ESP32 Logger");

  html += F("<h1>ESP32 Data Logger</h1>");

  // Status
  html += F("<p>Status: ");
  if (g_isLogging && g_isLogging())       html += F("<b>LOGGING</b>");
  else if (g_running)                     html += F("<b>SERVER RUNNING</b>");
  else                                    html += F("<b>IDLE</b>");
  html += F("</p>");

  // WiFi / IP
  html += F("<p>WiFi: ");
  html += WiFi.localIP().toString();
  html += F("</p>");

  // Quick links
  html += F("<h2>Links</h2>");
  html += F("<ul>");
  html += F("<li><a href=\"/files\">Browse SD Card</a></li>");
  html += F("<li><a href=\"/config\">Config (General)</a></li>");
  html += F("<li><a href=\"/config/sensors\">Config (Sensors)</a></li>");
  html += F("<li><a href=\"/config/buttons\">Config (Buttons)</a></li>");
  html += F("</ul>");

  html += htmlFooter();
  g_server->send(200, "text/html", html);
}

void WebServerManager::handleNotFound() {
  if (!g_server) return;
  noteHttpActivity_();
  String html = htmlHeader("404 Not Found");
  html += F("<h2>Not found</h2><p>The requested URL <code>");
  html += htmlEscape(g_server->uri());
  html += F("</code> was not found.</p>");
  html += F("<p><a href='/'>Home</a> &nbsp; <a href='/config'>Config</a> &nbsp; <a href='/files'>Files</a></p>");
  html += htmlFooter();

  g_server->send(404, "text/html", html);
}

static bool strToBool(const String& s) {
  String t = s; t.trim(); t.toLowerCase();
  return (t == "1" || t == "true" || t == "yes" || t == "on");
}

// --- cal_allowed CSV <-> mask ---
static CalModeMask parseCalAllowedCSV_(const String& csv) {
  String s = csv; s.trim(); if (!s.length()) return 0xFF; // inherit
  CalModeMask m = 0;
  int start = 0;
  while (start < s.length()) {
    int comma = s.indexOf(',', start);
    String tok = (comma < 0) ? s.substring(start) : s.substring(start, comma);
    tok.trim(); tok.toUpperCase();
    if (tok == "ZERO")  m |= CAL_ZERO;
    else if (tok == "RANGE") m |= CAL_RANGE;
    start = (comma < 0) ? s.length() : comma + 1;
  }
  return (m == 0) ? 0 : m;
}

static String calAllowedCSV_(CalModeMask m) {
  if (m == 0xFF) return String(""); // inherit
  String out;
  if (m & CAL_ZERO)  { if (out.length()) out += ","; out += "ZERO"; }
  if (m & CAL_RANGE) { if (out.length()) out += ","; out += "RANGE"; }
  if (!out.length()) out = "NONE";
  return out;
}
