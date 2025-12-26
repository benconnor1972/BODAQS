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
#include "esp_heap_caps.h"
#include "LoggingManager.h"
#include "HtmlUtil.h"
using namespace HtmlUtil;


// gTransforms is defined in esp32_data_logger.ino (non-static there)
extern TransformRegistry gTransforms;
static SdFs*g_sd = nullptr;                     // defined in esp32_data_logger.ino: SdFs* gSd = nullptr;

// --- Module state ---
WebServer g_server(80);   
static bool g_running = false;
static bool g_routesSetup = false;
SdFs* WebServerManager::sd() { return g_sd; }

// Pointer to the live config struct
static LoggerConfig* g_cfgPtr = nullptr;

// -------------------- fwd decls --------------------
static bool ensureSd();
static uint32_t lastHC = 0;

// --- helpers: send small chunks without building big Strings ---

static inline void sendP(const __FlashStringHelper* s) {
  g_server.sendContent_P(reinterpret_cast<const char*>(s));
}

static inline void sendC(const char* s) {
  g_server.sendContent(s);
}

// Stream HTML-escape of an Arduino String without creating another String.
static void sendHtmlEscaped(const String& in) {
  // Small stack buffer to batch sends (reduces overhead).
  char buf[96];
  size_t n = 0;

  auto flush = [&]() {
    if (n) {
      buf[n] = '\0';
      g_server.sendContent(buf);
      n = 0;
    }
  };

  for (size_t i = 0; i < in.length(); ++i) {
    const char c = in[i];
    const char* repl = nullptr;

    switch (c) {
      case '&':  repl = "&amp;";  break;
      case '<':  repl = "&lt;";   break;
      case '>':  repl = "&gt;";   break;
      case '"':  repl = "&quot;"; break;
      case '\'': repl = "&#39;";  break;
      default:   repl = nullptr;  break;
    }

    if (repl) {
      flush();
      g_server.sendContent(repl);
    } else {
      // Copy char into buffer; flush if near full.
      if (n + 2 >= sizeof(buf)) flush();
      buf[n++] = c;
    }
  }

  flush();
}

// Minimal header/footer that stream directly.
// If you already have standard header/footer content, move it here.
static void sendHtmlHeaderStream(const __FlashStringHelper* title) {
  sendP(F("<!doctype html><html><head><meta charset='utf-8'>"
          "<meta name='viewport' content='width=device-width,initial-scale=1'>"
          "<title>"));
  sendP(title);
  sendP(F("</title></head><body>"));
}

static void sendHtmlFooterStream() {
  sendP(F("</body></html>"));
}


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
    Serial.println(F("[WS] ensureSd: no SdFs* provided (call begin(StorageManager_getSd(), ...) first)"));
    return false;
  }
  return true; // StorageManager owns begin()
}

// -------------------- public API --------------------
void WebServerManager::begin(SdFs* sdRef) {
  g_sd        = sdRef;
}

void WebServerManager::attachConfig(LoggerConfig* cfg) {
  g_cfgPtr = cfg;
}

static inline bool isLoggingNow_() {
  return LoggingManager::isRunning();
}

bool WebServerManager::canStart() {
  return !isLoggingNow_();
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
  //Serial.printf("[WS] start: WiFi.status()=%d (need %d=WL_CONNECTED)\n", (int)wl, (int)WL_CONNECTED);
  if (wl != WL_CONNECTED) {
    Serial.println(F("[WS] start: WiFi not connected; will retry from loop()"));
    Serial.printf("[WS] heap free=%lu largest=%lu\n",
    (unsigned long)ESP.getFreeHeap(),
    (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
    return false;
  }

  IPAddress ip = WiFi.localIP();
  //Serial.printf("[WS] start: starting on http://%s/\n", ip.toString().c_str());

  Serial.printf("[WS] before set up routes: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

   if(!g_routesSetup) {
    setupRoutes();  // registers all handlers
    g_routesSetup = true;
   }
  
  Serial.printf("[WS] after set up routes: heap free=%lu largest=%lu\n",
  (unsigned long)ESP.getFreeHeap(),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

//  Serial.printf("[WS] begin() g_server=%p\n", (void*)g_server);
  g_server.begin();
  Serial.printf("[WS] begin() done\n");
  g_running = true;

 // Serial.printf("[WS] start: listening http://%s/\n", WiFi.localIP().toString().c_str());
  return true;
}



void WebServerManager::stop() {
  if (!g_running) return;
  g_server.stop();
  g_running = false;
  Serial.println(F("[WS] stopped"));
}

bool WebServerManager::isRunning() { return g_running; }

void WebServerManager::loop() {
  ++g_ws_loop_ticks;

//  if (!g_running) (void)WebServerManager::start();

  static uint32_t lastLoopMs = 0;
  static uint32_t lastHCEndMs = 0;

  uint32_t loopNow = millis();
  uint32_t loopDt  = loopNow - lastLoopMs;
  lastLoopMs = loopNow;

 // if (loopDt > 50) {
  //  Serial.printf("[WS] loop gap=%lu ms (something blocked loop)\n", (unsigned long)loopDt);
  //}

/*
  if (g_server) {
    uint32_t t0 = millis();
    g_server.handleClient();
    //  Serial.printf("[WS] Hitting handleclient\n");
    uint32_t t1 = millis();

    uint32_t hcDur = t1 - t0;
    if (hcDur > 50) {
      Serial.printf("[WS] handleClient duration=%lu ms (handleClient blocked)\n", (unsigned long)hcDur);
    }

    // If you *also* want time between completed calls:
    uint32_t sinceLastEnd = t1 - lastHCEndMs;
    lastHCEndMs = t1;
    if (sinceLastEnd > 50) {
      Serial.printf("[WS] time since last handleClient end=%lu ms\n", (unsigned long)sinceLastEnd);
    }
  }
*/
  
  uint32_t t0 = millis();
  g_server.handleClient();
  uint32_t dt = millis() - t0;
  /* if (dt > 100) {
    Serial.printf("[WS] handleClient SLOW dt=%lu free=%lu largest=%lu\n",
      (unsigned long)dt,
      (unsigned long)ESP.getFreeHeap(),
      (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
  }
*/
  // keep Wi-Fi happy
  delay(0);
  yield();
}


void WebServerManager::setupRoutes() {

  if (g_routesSetup) return;
  g_routesSetup = true;

  // Root can stay here (or move into a Routes_Status later)
  g_server.on("/", HTTP_GET, handleRoot);

  // Delegate
  registerFileRoutes();
  registerConfigRoutes();
  registerTransformRoutes();


  // --- debug canary: always available ---
 /* g_server.on("/ping", HTTP_GET, [](){
    g_server.sendHeader("Connection", "close");
    WiFiClient c = g_server.client();
    g_server.send(200, F("text/plain"), F("OK"));
    c.stop();
    Serial.printf("[WS] /ping after send: client=%d\n", (int)g_server.client().connected());

  });*/

  g_server.on("/ping", HTTP_GET, [](){
  WiFiClient c = g_server.client();
  c.print(
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: text/plain\r\n"
    "Connection: close\r\n"
    "Content-Length: 2\r\n"
    "\r\n"
    "OK"
  );
  c.stop();
});

  // --- debug health: JSON snapshot ---
  g_server.on("/__health", HTTP_GET, [](){
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
    g_server.send(200, "application/json", out);
  });

  // --- log *every* unhandled request (method + URI + args) ---
  g_server.onNotFound([](){
    String uri = g_server.uri();
    Serial.printf("[WS] 404 %s %s\n",
                  (g_server.method() == HTTP_GET ? "GET" :
                  g_server.method() == HTTP_POST ? "POST" :
                  g_server.method() == HTTP_PUT ? "PUT" :
                  g_server.method() == HTTP_DELETE ? "DEL" : "?"),
                  uri.c_str());
    const int ac = g_server.args();
    for (int i = 0; i < ac; ++i) {
      Serial.printf("      arg[%d] %s = %s\n", i,
                    g_server.argName(i).c_str(),
                    g_server.arg(i).c_str());
    }
    g_server.send(404, "text/plain", "Not found");
  });

  // 404
  g_server.onNotFound(WebServerManager::handleNotFound);

}

void WebServerManager::handleRoot() {
  WiFiManager::noteUserActivity();

  Serial.printf("[WS] heap free=%lu largest=%lu\n",
                (unsigned long)ESP.getFreeHeap(),
                (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

  // Stream response (chunked)
  g_server.setContentLength(CONTENT_LENGTH_UNKNOWN);

  // Optional but often helps browsers not hold the socket open on embedded servers:
  g_server.sendHeader(F("Connection"), F("close"));

  g_server.send(200, F("text/html"), "");   // headers only; body follows via sendContent*

  // Header (streamed from PROGMEM via HtmlUtil)
  HtmlUtil::sendHtmlHeader(g_server, F("ESP32 Logger"));

  g_server.sendContent_P(PSTR("<h1>ESP32 Data Logger</h1>"));

  // Status
  g_server.sendContent_P(PSTR("<p>Status: "));
  if (g_loggingActive)      g_server.sendContent_P(PSTR("<b>LOGGING</b>"));
  else if (g_running)       g_server.sendContent_P(PSTR("<b>SERVER RUNNING</b>"));
  else                      g_server.sendContent_P(PSTR("<b>IDLE</b>"));
  g_server.sendContent_P(PSTR("</p>"));

  // WiFi IP (no String allocation)
  g_server.sendContent_P(PSTR("<p>WiFi: "));
  {
    IPAddress ip = WiFi.localIP();
    char ipbuf[16]; // "255.255.255.255" + '\0'
    snprintf(ipbuf, sizeof(ipbuf), "%u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]);
    g_server.sendContent(ipbuf);
  }
  g_server.sendContent_P(PSTR("</p>"));

  // Links
  g_server.sendContent_P(PSTR("<h2>Links</h2><ul>"));
  g_server.sendContent_P(PSTR("<li><a href=\"/files\">Browse SD Card</a></li>"));
  g_server.sendContent_P(PSTR("<li><a href=\"/config\">Config (General)</a></li>"));
  g_server.sendContent_P(PSTR("<li><a href=\"/config/sensors\">Config (Sensors)</a></li>"));
  g_server.sendContent_P(PSTR("<li><a href=\"/config/buttons\">Config (Buttons)</a></li>"));
  g_server.sendContent_P(PSTR("</ul>"));

  // Footer
  HtmlUtil::sendHtmlFooter(g_server);

  // Final chunk
  g_server.sendContent("");

  Serial.printf("[WS] heap free=%lu largest=%lu\n",
                (unsigned long)ESP.getFreeHeap(),
                (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
}



void WebServerManager::handleNotFound() {
  WiFiManager::noteUserActivity();

  g_server.setContentLength(CONTENT_LENGTH_UNKNOWN);
  g_server.send(404, F("text/html"), "");   // headers only; body via sendContent*

  sendHtmlHeaderStream(F("404 Not Found"));

  sendP(F("<h2>Not found</h2><p>The requested URL <code>"));
  sendHtmlEscaped(g_server.uri());
  sendP(F("</code> was not found.</p>"));

  sendP(F("<p><a href='/'>Home</a> &nbsp; <a href='/config'>Config</a> &nbsp; "
          "<a href='/files'>Files</a></p>"));

  sendHtmlFooterStream();

  g_server.sendContent(""); // some cores like a final chunk
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
