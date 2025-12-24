#include "Routes_Transforms.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <SdFat.h>
#include "SD_MMC.h"   // for SD_MMC backend

#include "HtmlUtil.h"
#include "WebServerManager.h"
#include "ConfigManager.h"
#include "SensorManager.h"

using namespace HtmlUtil;

// --- tiny SD helper ---
static bool ensureSd_(SdFat*& out) {
  out = WebServerManager::sd();
  if (!out) { Serial.println(F("[XFORM] SdFat* is null")); return false; }
  return true;
}

// Normalize ID and label helpers
static String stemOf_(const char* name) {
  String s(name);
  int dot = s.lastIndexOf('.');
  if (dot > 0) s = s.substring(0, dot);
  return s;
}
static const __FlashStringHelper* typeForSuffix_(const char* name) {
  String s(name); s.toLowerCase();
  if (s.endsWith(".lut") || s.endsWith(".csv"))  return F("LUT");
  if (s.endsWith(".poly")|| s.endsWith(".cfg"))  return F("POLY");
  if (s.endsWith(".json"))                       return F("JSON");
  return F("custom");
}

// Get the last path segment (strip leading directories)
static String baseName_(const String& path) {
  int slash = path.lastIndexOf('/');
  if (slash >= 0 && slash + 1 < (int)path.length()) {
    return path.substring(slash + 1);
  }
  return path;
}

static void addTransformsFromDir_(SdFat* sd, const char* dirPath, JsonArray outArr) {
  if (!sd) return;
  SdFile dir;
  if (!dir.open(dirPath)) return;

  dir.rewind();
  SdFile entry;
  char name[128];
  while (entry.openNext(&dir, O_READ)) {
    if (entry.isHidden() || entry.isSubDir()) { entry.close(); continue; }
    entry.getName(name, sizeof(name));
    // Skip obviously non-transform files
    String lower(name); lower.toLowerCase();
    if (!(lower.endsWith(".lut") || lower.endsWith(".csv") || lower.endsWith(".poly")
          || lower.endsWith(".cfg") || lower.endsWith(".json"))) {
      entry.close(); continue;
    }
    JsonObject o = outArr.createNestedObject();
    o["id"]    = stemOf_(name);
    o["label"] = stemOf_(name);
    o["type"]  = typeForSuffix_(name);
    entry.close();
    delay(0);
  }
  dir.close();
}

// SD_MMC backend: same logic as addTransformsFromDir_ but using SD_MMC FS
static void addTransformsFromDirMMC_(const char* dirPath, JsonArray outArr) {
  File dir = SD_MMC.open(dirPath);
  if (!dir || !dir.isDirectory()) {
    if (dir) dir.close();
    return;
  }

  File entry = dir.openNextFile();
  while (entry) {
    if (entry.isDirectory()) {
      entry.close();
      entry = dir.openNextFile();
      continue;
    }

    String fullName = entry.name();
    String base = baseName_(fullName);  // re-use same helper pattern as in Routes_Files, or inline

    String lower = base;
    lower.toLowerCase();
    if (!(lower.endsWith(".lut") || lower.endsWith(".csv") || lower.endsWith(".poly")
          || lower.endsWith(".cfg") || lower.endsWith(".json"))) {
      entry.close();
      entry = dir.openNextFile();
      continue;
    }

    JsonObject o = outArr.createNestedObject();
    o["id"]    = stemOf_(base.c_str());
    o["label"] = stemOf_(base.c_str());
    o["type"]  = typeForSuffix_(base.c_str());

    entry.close();
    delay(0);
    entry = dir.openNextFile();
  }

  dir.close();
}

static void addTransformsFromDirAny_(const char* dirPath, JsonArray outArr) {
  if (SdFat* sd = WebServerManager::sd()) {
    addTransformsFromDir_(sd, dirPath, outArr);      // SPI/SdFat
  } else {
    addTransformsFromDirMMC_(dirPath, outArr);       // SD_MMC
  }
}


void registerTransformRoutes(WebServer& srv) {
  WebServer* S = &srv;

  // -------- GET /api/transforms/list?sensor=... [&mode=...]
  S->on("/api/transforms/list", HTTP_GET, [S](){
    auto& srv = *S;
    // NOTE: 'mode' is accepted for future filtering (RAW/LINEAR/POLY/LUT).
    // We still include every discovered file here; your UI chooses visibility.
    if (!srv.hasArg("sensor")) {
      StaticJsonDocument<64> err; err["error"] = "missing sensor";
      String out; serializeJson(err, out);
      srv.send(400, F("application/json"), out);
      return;
    }
    const String sensor = srv.arg("sensor");
    String mode = srv.hasArg("mode") ? srv.arg("mode") : "";

    SdFat* sd = WebServerManager::sd();
    const bool useSpi = (sd != nullptr);

    // Build result
    StaticJsonDocument<4096> doc;
    JsonArray items = doc.to<JsonArray>();


    // Always include identity
    {
      JsonObject id = items.createNestedObject();
      id["id"]    = "identity";
      id["label"] = "Identity (no transform)";
      id["type"]  = "RAW";
    }

    // Per-sensor directory: /cal/<sensor>/
    {
      String dir = F("/cal/");
      dir += sensor;
      dir += '/';
    addTransformsFromDirAny_(dir.c_str(), items);

    }

    // Generic directory: /cal/
    addTransformsFromDirAny_("/cal/", items);


    // Optional: filter by mode if provided (only hides non-matching)
    if (mode.length()) {
      String m = mode; m.toUpperCase();
      // Create filtered copy
      StaticJsonDocument<4096> filtered;
      JsonArray f = filtered.to<JsonArray>();
      for (JsonObject o : items) {
        String t = o["type"].as<const char*>();
        if (!t.length()) t = "";
        t.toUpperCase();
        if (m == "RAW" || m == "ANY") { f.add(o); continue; }
        if ((m == "POLY" && t == "POLY") || (m == "LUT" && (t == "LUT" || t == "CSV"))) f.add(o);
        else if (m == t) f.add(o);
      }

      String out; serializeJson(f, out);
      srv.sendHeader("Cache-Control", "no-store");
      srv.send(200, F("application/json"), out);
      return;
    }

    String out; serializeJson(items, out);
    srv.sendHeader("Cache-Control", "no-store");
    srv.send(200, F("application/json"), out);
  });

  // -------- POST /api/transforms/select (sensor=...&id=...)
  S->on("/api/transforms/select", HTTP_POST, [S](){
    auto& srv = *S;

    if (!srv.hasArg("sensor") || !srv.hasArg("id")) {
      srv.send(400, F("application/json"), F("{\"error\":\"sensor and id required\"}"));
      return;
    }
    const String sensor = srv.arg("sensor");
    String id = srv.arg("id"); id.trim();

    // Persist to config (by index)
    LoggerConfig cfg = ConfigManager::get();   // snapshot
    const uint8_t n  = cfg.sensorCount();
    bool saved = false;
    for (uint8_t i = 0; i < n; ++i) {
      SensorSpec sp;
      if (!cfg.getSensorSpec(i, sp)) continue;
      if (String(sp.name) == sensor) {
        // Update config param and persist just this param
        ConfigManager::saveSensorParamByIndex(i, "output_id", id);
        saved = true;
        break;
      }
    }

    // Best-effort: update the live sensor immediately (if present)
    Sensor* live = nullptr;
    for (uint8_t j = 0; j < SensorManager::count(); ++j) {
      Sensor* s = SensorManager::get(j);
      if (s && String(s->name()) == sensor) { live = s; break; }
    }
    if (live) {
      // Hook here if you expose a runtime apply method, e.g.:
      // live->selectTransformById(id.c_str());
    }

    if (!saved) {
      srv.send(404, F("application/json"), F("{\"error\":\"sensor not found\"}"));
      return;
    }

    srv.sendHeader("Cache-Control", "no-store");
    srv.send(200, F("application/json"), F("{\"ok\":true}"));
  });

  // -------- POST /api/transforms/reload (sensor=...)
  S->on("/api/transforms/reload", HTTP_POST, [S](){
    auto& srv = *S;
    // Placeholder no-op: integrate a TransformRegistry here if/when available.
    srv.sendHeader("Cache-Control", "no-store");
    srv.send(200, F("application/json"), F("{\"ok\":true}"));
  });
}
