#include "Routes_Transforms.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <SdFat.h>
#include "SD_MMC.h"   // for SD_MMC backend

#include "HtmlUtil.h"
#include "WebServerManager.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "TransformRegistry.h"

using namespace HtmlUtil;

// --- tiny SD helper ---
static bool ensureSd_(SdFs*& out) {
  out = WebServerManager::sd();
  if (!out) { Serial.println(F("[XFORM] SdFs* is null")); return false; }
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

static void addTransformsFromDir_(SdFs* sd, const char* dirPath, JsonArray outArr) {
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
  if (SdFs* sd = WebServerManager::sd()) {
    addTransformsFromDir_(sd, dirPath, outArr);      // SPI/SdFat
  } else {
    addTransformsFromDirMMC_(dirPath, outArr);       // SD_MMC
  }
}


void registerTransformRoutes(WebServer& srv) {
  WebServer* S = &srv;

// -------- GET /api/transforms/list?sensor=...
S->on("/api/transforms/list", HTTP_GET, [S](){
  auto& srv = *S;

  if (!srv.hasArg("sensor")) {
    srv.send(400, F("application/json"), F("{\"error\":\"sensor required\"}"));
    return;
  }

  const String sensor = srv.arg("sensor");

  // Ensure registry is loaded for this sensor (prefer SdFat if available)
  SdFs* sd = WebServerManager::sd();
  if (sd) {
    gTransforms.loadForSensor(sensor, *sd);
  } else {
    // fallback: FS-style backend (SD_MMC)
    gTransforms.loadForSensor(sensor, SD_MMC);
  }

  DynamicJsonDocument doc(8192);
  JsonArray items = doc.createNestedArray("items");

  // Always include identity
  {
    JsonObject o = items.createNestedObject();
    o["id"]        = "identity";
    o["label"]     = "identity";
    o["type"]      = "identity";
    o["in_units"]  = "";
    o["out_units"] = "";
  }

  // Registry-backed transforms
  auto metas = gTransforms.list(sensor);
  for (const auto& m : metas) {
    // If your identity transform also appears in list(), skip duplicates:
    if (m.id == "identity") continue;

    JsonObject o = items.createNestedObject();
    o["id"]        = m.id;
    o["label"]     = m.label;
    o["type"]      = m.type;
    o["in_units"]  = m.inUnits;
    o["out_units"] = m.outUnits;
  }

  String out;
  serializeJson(doc, out);

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
    String id = srv.arg("id");
    id.trim();

    // --- Find sensor index in config (match your existing convention) ---
    LoggerConfig cfg = ConfigManager::get();     // snapshot ok for lookup
    const uint8_t n  = cfg.sensorCount();
    int foundIdx = -1;

    for (uint8_t i = 0; i < n; ++i) {
      SensorSpec sp;
      if (!cfg.getSensorSpec(i, sp)) continue;
      if (String(sp.name) == sensor) {  // or sp.id if you have one
        foundIdx = (int)i;
        break;
      }
    }

    if (foundIdx < 0) {
      srv.send(404, F("application/json"), F("{\"error\":\"sensor not found\"}"));
      return;
    }

    // --- Best-effort: update live sensor immediately (and APPLY) ---
    for (uint8_t j = 0; j < SensorManager::count(); ++j) {
      Sensor* s = SensorManager::get(j);
      if (!s) continue;
      if (String(s->name()) == sensor) {
        s->setSelectedTransformId(id);   // updates selectedTransformId()
        s->attachTransform(gTransforms); // updates m_transform (and usually units)
        break;
      }
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
