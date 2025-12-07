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
#include "Routes_Files.h"
#include "Routes_Config.h"
#include "Routes_Transforms.h"
#include "HtmlUtil.h"
using namespace HtmlUtil;


// gTransforms is defined in esp32_data_logger.ino (non-static there)
extern TransformRegistry gTransforms;
static SdFs*g_sd = nullptr;                     // defined in esp32_data_logger.ino: SdFs* gSd = nullptr;

// --- Module state ---
static WebServer* g_server = nullptr;
static WebServerManager::IsLoggingFn g_isLogging = nullptr;
static bool g_running = false;
SdFat* WebServerManager::sd() { return g_sd; }

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


// -------------------- helpers --------------------
static bool ensureSd() {
  if (!g_sd) {
    Serial.println(F("[WS] ensureSd: no SdFat* provided (call begin(StorageManager_getSd(), ...) first)"));
    return false;
  }
  return true; // StorageManager owns begin()
}

// -------------------- public API --------------------
void WebServerManager::begin(SdFat* sdRef, IsLoggingFn isLogging) {
  g_sd        = sdRef;
  g_isLogging = isLogging;
}

void WebServerManager::attachConfig(LoggerConfig* cfg) {
  g_cfgPtr = cfg;
}

void WebServerManager::setStaConfig(const String& ssid, const String& password) {
} //no-op. legacy

bool WebServerManager::canStart() {
  // Only block while logging; do NOT require SdFat here.
  if (g_isLogging && g_isLogging()) {
    return false;
  }
  return true;
}


bool WebServerManager::start() {
  if (g_running) {
    Serial.println(F("[WS] start: already running"));
    return true;
  }

  if (!canStart()) {
    Serial.println(F("[WS] start: canStart() = false (probably logging active)"));
    return false;
  }

  wl_status_t wl = WiFi.status();
  Serial.printf("[WS] start: WiFi.status()=%d (need %d=WL_CONNECTED)\n", (int)wl, (int)WL_CONNECTED);
  if (wl != WL_CONNECTED) {
    Serial.println(F("[WS] start: WiFi not connected; will retry from loop()"));
    return false;
  }

  IPAddress ip = WiFi.localIP();
  Serial.printf("[WS] start: starting on http://%s/\n", ip.toString().c_str());

  // Allocate server and wire routes if first time
  if (!g_server) {
    g_server = new WebServer(80);
    setupRoutes();  // registers all handlers
  }

  g_server->begin();
  g_running = true;

  Serial.printf("[WS] start: listening http://%s/\n", WiFi.localIP().toString().c_str());
  return true;
}



void WebServerManager::stop() {
  if (!g_running) return;
  if (g_server) { g_server->stop(); delete g_server; g_server = nullptr; }
  g_running = false;
  Serial.println(F("[WS] stopped"));
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
  ++g_ws_loop_ticks;

  // If you intentionally pause servicing while logging, keep that guard here.
  // Otherwise, remove this block.
  if (g_isLogging && g_isLogging()) {
    // Uncomment next line if you want to *throttle* instead of fully pause.
    // if ((g_ws_loop_ticks & 0xFF) == 0) Serial.println(F("[WS] loop: paused (logging)"));
    return;
  }

  if (g_server) {
    g_server->handleClient();
  }

  // Heartbeat every ~2s so we know loop() runs regularly
  uint32_t now = millis();
  if (now - g_ws_last_beat_ms > 2000) {
    g_ws_last_beat_ms = now;
    //Serial.printf("[WS] hb: ticks=%lu total=%lu inflight=%lu 2xx=%lu 4xx=%lu 5xx=%lu\n",
    //              (unsigned long)g_ws_loop_ticks,
    //              (unsigned long)g_ws_req_total,
    //              (unsigned long)g_ws_inflight,
    //              (unsigned long)g_ws_req_2xx,
    //              (unsigned long)g_ws_req_4xx,
    //              (unsigned long)g_ws_req_5xx);
  }

  // keep Wi-Fi happy
  delay(0);
  yield();
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
    ws_diag_on_request();
    g_server->send(200, "text/plain", "pong");
    ws_diag_on_response(200);
  });

  // --- debug health: JSON snapshot ---
  g_server->on("/__health", HTTP_GET, [](){
    ws_diag_on_request();
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
    ws_diag_on_response(200);
  });

  // --- log *every* unhandled request (method + URI + args) ---
  g_server->onNotFound([](){
    ws_diag_on_request();
    String uri = g_server->uri();
    Serial.printf("[WS] 404 %s %s\n",
                  (g_server->method() == HTTP_GET ? "GET" :
                  g_server->method() == HTTP_POST ? "POST" :
                  g_server->method() == HTTP_PUT ? "PUT" :
                  g_server->method() == HTTP_DELETE ? "DEL" : "?"),
                  uri.c_str());
    const int ac = g_server->args();
    for (int i = 0; i < ac; ++i) {
      Serial.printf("      arg[%d] %s = %s\n", i,
                    g_server->argName(i).c_str(),
                    g_server->arg(i).c_str());
    }
    g_server->send(404, "text/plain", "Not found");
    ws_diag_on_response(404);
  });

  // 404
  //g_server->onNotFound(WebServerManager::handleNotFound);
}

void WebServerManager::handleRoot() {
  ws_diag_on_request();

  WiFiManager::noteUserActivity();
  String html = htmlHeader("ESP32 Logger");

  html += F("<h1>ESP32 Data Logger</h1><p>Status: ");
  if (g_isLogging && g_isLogging())       html += F("<b>LOGGING</b>");
  else if (g_running)                     html += F("<b>SERVER RUNNING</b>");
  else                                    html += F("<b>IDLE</b>");
  html += F("</p><p>WiFi: ");
  html += WiFi.localIP().toString();
  html += F("<p><a href=\"/files\">Browse SD Card</a> &nbsp; "
            "<a href=\"/config\">Config</a></p>");

  html += htmlFooter();
  g_server->send(200, "text/html", html);
  ws_diag_on_response(200);

}

void WebServerManager::handleNotFound() {
  if (!g_server) return;
  WiFiManager::noteUserActivity();
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
