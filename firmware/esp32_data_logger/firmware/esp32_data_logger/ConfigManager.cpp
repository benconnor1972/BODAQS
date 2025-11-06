#include "ConfigManager.h"
#include "SensorParams.h"
#include "SensorTypes.h"
#include "Rates.h"
#include "Calibration.h"
#include "SensorRegistry.h"
#include <ctype.h>
#include <string.h>



// ---- private per-sensor key/value storage (backing ParamPack) ----
namespace {

  //constexpr uint8_t MAX_SENSORS = 8;     // single definition

  static SdFat*     g_sd = nullptr;
  static char       g_cfgName[32] = "loggercfg";
  static SensorSpec g_specs[MAX_SENSORS];
  static ParamStore g_stores[MAX_SENSORS];
  static uint8_t    g_specCount = 0;
  static uint8_t    g_expectedCount = 0;
  static LoggerConfig s_cfg;
  static Calibration g_cals[MAX_SENSORS];   // NEW: per-sensor calibration cache
  constexpr uint8_t kCalSlots = uint8_t(sizeof(g_cals) / sizeof(g_cals[0]));
  static CalModeMask g_calAllowed[MAX_SENSORS];  // 0xFF = inherit type defaults
  static String calMaskToStr(CalModeMask m) {
    String out;
    if (m & CAL_ZERO)  { if (out.length()) out += ","; out += "ZERO"; }
    if (m & CAL_RANGE) { if (out.length()) out += ","; out += "RANGE"; }
    if (!out.length()) out = "NONE";
    return out;
  }



  // small helpers

  static inline bool keyEquals(const char* a, const char* b) { return a && b && strcasecmp(a,b)==0; }
  // Small helper for human-readable mode text
  static const char* calModeToStr(CalMode m) {
    switch (m) {
      case CalMode::ZERO:  return "ZERO";
      case CalMode::RANGE: return "RANGE";
      default:             return "NONE";
    }
  }

  static inline bool validIdx(long idx) { return idx >= 0 && idx < MAX_SENSORS; }   // helper to clamp index

  
  static void copyStrBounded(const char* src, char* dst, size_t cap) {
    if (!dst || cap == 0) return;
    if (!src) { dst[0] = '\0'; return; }
    strncpy(dst, src, cap - 1); dst[cap - 1] = '\0';
  }

  static SensorType strToSensorType(const char* v) {
    if (!v) return SensorType::AnalogPot;
    if (!strcasecmp(v, "analog_pot") || !strcasecmp(v, "pot")) return SensorType::AnalogPot;
    return SensorType::AnalogPot;
  }

  // simple line reader for SdFat
  static bool readLine(FsFile& f, char* buf, size_t cap) {
    size_t n = 0; int c;
    while (n < cap - 1 && (c = f.read()) >= 0) {
      if (c == '\r') continue;
      if (c == '\n') break;
      buf[n++] = (char)c;
    }
    if (n == 0 && c < 0) return false;
    buf[n] = '\0';
    return true;
  }

  // Convert a SensorType to a config-safe key like "analog_pot"
  static String typeKeyForSave(SensorType t) {
    const char* lbl = SensorRegistry::typeLabel(t);  // e.g. "Analog Pot"
    String s = lbl ? String(lbl) : String("unknown");
    s.toLowerCase();
    // replace non-alnum with underscores to match keys like "analog_pot"
    for (size_t i = 0; i < s.length(); ++i) {
      char c = s[i];
      if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'))) s.setCharAt(i, '_');
    }
    // collapse multiple underscores (optional)
    String out; out.reserve(s.length());
    bool prevUnd = false;
    for (size_t i = 0; i < s.length(); ++i) {
      char c = s[i];
      if (c == '_') { if (!prevUnd) { out += c; prevUnd = true; } }
      else { out += c; prevUnd = false; }
    }
    return out;
  }


  // ensure a spec slot exists, default it, and bind its ParamPack to its own store
  static SensorSpec* ensureSpec(uint8_t idx) {
    if (idx >= MAX_SENSORS) return nullptr;
    if (idx >= g_specCount) {
      SensorSpec& s = g_specs[idx];
      memset(&s, 0, sizeof(s));
      s.type = SensorType::AnalogPot;
      s.mutedDefault = false;
      copyStrBounded("pot", s.name, sizeof(s.name));
      g_stores[idx].clear();
      s.params.bind(&g_stores[idx]);
      g_specCount = idx + 1;
    }
    return &g_specs[idx];
  }

  // route a K/V into the correct sensor's store
  static void storeKV(uint8_t idx, const char* key, const char* val) {
    if (idx < MAX_SENSORS) g_stores[idx].set(key, val);
  }

  static CalModeMask parseCalAllowedCSV(const char* csv) {
    if (!csv || !*csv) return 0xFF; // inherit
    CalModeMask m = CAL_NONE;
    const char* p = csv;
    while (*p) {
      while (*p == ' ' || *p == '\t' || *p == ',') ++p;
      const char* start = p;
      while (*p && *p != ',') ++p;
      String tok = String(start).substring(0, p - start);
      tok.trim(); tok.toUpperCase();
      if (tok == "ZERO")  m |= CAL_ZERO;
      else if (tok == "RANGE") m |= CAL_RANGE;
      // ignore unknown tokens to stay forward-compatible
    }
    // If user wrote an empty/unknown list, treat as explicit “none”
    return (m == CAL_NONE) ? CAL_NONE : m;
  }

  static CalModeMask typeSupportedMask(SensorType t) {
    switch (t) {
      case SensorType::AnalogPot:
        return CAL_ZERO | CAL_RANGE;
      default:
        return CAL_NONE;
    }
  }

  // Parse "HH:HH:HH:HH:HH:HH" into 6 bytes; returns true on success
  static bool parseMac(const char* s, uint8_t out[6]) {
    if (!s) return false;
    int bytes[6];
    if (sscanf(s, "%x:%x:%x:%x:%x:%x", &bytes[0],&bytes[1],&bytes[2],&bytes[3],&bytes[4],&bytes[5]) != 6) return false;
    for (int i = 0; i < 6; ++i) { if (bytes[i] < 0 || bytes[i] > 255) return false; out[i] = (uint8_t)bytes[i]; }
    return true;
  }
  static inline bool validRssi(int v) { return v >= -100 && v <= -10; }

} // namespace

const LoggerConfig& ConfigManager::get() {
    return s_cfg;
}


static bool startsWith(const String& s, const char* prefix) {
  int n = s.length(), m = strlen(prefix);
  if (n < m) return false;
  for (int i = 0; i < m; ++i) if (s[i] != prefix[i]) return false;
  return true;
}

// --- helpers (file-scope static or just above the block is fine) ---
static bool parseBoolC_(const char* v) {
  if (!v) return false;
  // trim (leading)
  while (*v && (*v==' '||*v=='\t')) ++v;
  if (!*v) return false;
  // lowercase compare
  if (!strcasecmp(v, "1") || !strcasecmp(v, "true") ||
      !strcasecmp(v, "yes") || !strcasecmp(v, "on")) return true;
  return false;
}

static bool parseBssidC_(const char* v, uint8_t out[6]) {
  if (!v) return false;
  int n = 0, hi = -1;
  for (const char* p = v; *p && n < 6; ++p) {
    int d = -1;
    const char c = *p;
    if (c >= '0' && c <= '9') d = c - '0';
    else if (c >= 'a' && c <= 'f') d = 10 + (c - 'a');
    else if (c >= 'A' && c <= 'F') d = 10 + (c - 'A');
    if (d >= 0) {
      if (hi < 0) hi = d;
      else { out[n++] = uint8_t((hi << 4) | d); hi = -1; }
    }
  }
  return (n == 6 && hi < 0);
}

static void copyStrBoundedC_(const char* src, char* dst, size_t dstsz) {
  if (!dst || dstsz == 0) return;
  if (!src) { dst[0] = '\0'; return; }
  strncpy(dst, src, dstsz - 1);
  dst[dstsz - 1] = '\0';
}

void ConfigManager::begin(SdFat* sdRef, const char* filename) {
  g_sd = sdRef;
  if (filename && *filename) copyStrBounded(filename, g_cfgName, sizeof(g_cfgName));
  g_specCount = 0;
  g_expectedCount = 0;
  for (uint8_t i = 0; i < MAX_SENSORS; ++i) {
    g_stores[i].clear();
    g_specs[i].params.bind(&g_stores[i]);
    g_cals[i] = Calibration{};             // NEW: reset cal cache
    g_calAllowed[i] = 0xFF;           // inherit by default
  }
}

void ConfigManager::trimInPlace(char* s) {
  if (!s) return;
  // leading
  char* p = s;
  while (*p && isspace((unsigned char)*p)) ++p;
  if (p != s) memmove(s, p, strlen(p) + 1);
  // trailing
  size_t n = strlen(s);
  while (n && isspace((unsigned char)s[n - 1])) s[--n] = '\0';
}

bool ConfigManager::parseBool(const String& s, bool& out) {
  String t = s; t.trim(); t.toLowerCase();
  if (t == "1" || t == "true"  || t == "on"  || t == "yes") { out = true;  return true; }
  if (t == "0" || t == "false" || t == "off" || t == "no")  { out = false; return true; }
  return false;
}

uint8_t ConfigManager::sensorCount() {
   return get().sensorCount(); 
}

bool ConfigManager::getSensorSpec(uint8_t i, SensorSpec& out) {
  return get().getSensorSpec(i, out);
}

int8_t ConfigManager::findSensorByName(const char* name) {
  return get().findSensorByName(name);
}

void ConfigManager::setSampleRateHz(uint16_t hz, bool persist) {
  // snap to allowed list (or closest)
  int idx = Rates::indexOf(hz);
  if (idx < 0) {
    // choose nearest
    uint16_t best = Rates::kList[0];
    uint32_t bestErr = ~0u;
    for (size_t i = 0; i < Rates::kCount; ++i) {
      uint32_t e = (hz > Rates::kList[i]) ? (hz - Rates::kList[i]) : (Rates::kList[i] - hz);
      if (e < bestErr) { bestErr = e; best = Rates::kList[i]; }
    }
    hz = best;
  }

  LoggerConfig cfg = ConfigManager::get();     // ← copy existing
  if (cfg.sampleRateHz == hz) return;          // nothing to change
  cfg.sampleRateHz = hz;

  if (persist) {
    ConfigManager::save(cfg);                  // ← matches your header signature
  } else {
    // If you have an in-memory setter to update “current” config, call it here.
    // e.g., ConfigManager::setCurrent(cfg);
  }
}

bool ConfigManager::parseLine(char* line, LoggerConfig& cfg) {
  // strip comments (# ...)
  char* hash = strchr(line, '#');
  if (hash) *hash = '\0';
  trimInPlace(line);
  if (!*line) return true; // blank/comment

  // split key=value
  char* eq = strchr(line, '=');
  if (!eq) return true;
  *eq = '\0';
  char* key = line;
  char* val = eq + 1;
  trimInPlace(key);
  trimInPlace(val);

  // 1) Global Wi-Fi flags
  if (!strcasecmp(key, "wifi_enabled_default")) {
    cfg.wifiEnabledDefault = parseBoolC_(val);
    return true;
  }
  if (!strcasecmp(key, "wifi_auto_time_on_rtc_invalid")) {
    cfg.wifiAutoTimeOnRtcInvalid = parseBoolC_(val);
    return true;
  }

  // 2) wifiN.* (N=0..4)
  if (strncmp(key, "wifi", 4) == 0 && isdigit((unsigned char)key[4])) {
    int i = key[4] - '0';
    if (i >= 0 && i <= 4) {
      const char* dot = strchr(key + 5, '.');
      if (!dot) return false;           // malformed; let others try
      const char* sub = dot + 1;

      if (!strcasecmp(sub, "ssid")) {
        copyStrBoundedC_(val, cfg.wifi[i].ssid, sizeof(cfg.wifi[i].ssid));
        return true;
      }
      if (!strcasecmp(sub, "password")) {
        copyStrBoundedC_(val, cfg.wifi[i].password, sizeof(cfg.wifi[i].password));
        return true;
      }
      if (!strcasecmp(sub, "min_rssi")) {
        // “0/blank” means ignore
        if (!val || !*val) { cfg.wifi[i].minRssi = -127; return true; }
        char* endp = nullptr;
        long vi = strtol(val, &endp, 10);
        if (endp == val) { cfg.wifi[i].minRssi = -127; return true; } // not a number
        if (vi == 0)      { cfg.wifi[i].minRssi = -127; return true; }
        if (vi >= -100 && vi <= -10) cfg.wifi[i].minRssi = (int16_t)vi;
        else                         cfg.wifi[i].minRssi = -127;
        return true;
      }
      if (!strcasecmp(sub, "bssid")) {
        uint8_t b[6] = {0};
        if (val && *val && parseBssidC_(val, b)) {
          memcpy(cfg.wifi[i].bssid, b, 6);
          cfg.wifi[i].bssidSet = true;
        } else {
          memset(cfg.wifi[i].bssid, 0, 6);
          cfg.wifi[i].bssidSet = false;
        }
        return true;
      }
      if (!strcasecmp(sub, "hidden")) {
        cfg.wifi[i].hidden = parseBoolC_(val);
        return true;
      }
    }
  }

  // sensor_count (hint only)
  if (keyEquals(key, "sensor_count")) {
    long v = strtol(val, nullptr, 10);
    if (v < 0) v = 0; if (v > MAX_SENSORS) v = MAX_SENSORS;
    g_expectedCount = (uint8_t)v;
    return true;
  }

  // sensorN.something
  if (!strncasecmp(key, "sensor", 6)) {
    const char* p = key + 6;
    char* endp = nullptr;
    long idx = strtol(p, &endp, 10);
    if (idx < 0 || idx >= MAX_SENSORS || !endp || *endp != '.') return true;
    const char* sub = endp + 1;

    SensorSpec* sp = ensureSpec((uint8_t)idx);
    if (!sp) return true;

    if (!strcasecmp(sub, "type"))  { sp->type = strToSensorType(val); return true; }
    if (!strcasecmp(sub, "name"))  {
      Serial.print(F("[CFG] set name for sensor")); Serial.print(idx);
      Serial.print(F(" = '")); Serial.print(val); Serial.println(F("'"));
      copyStrBounded(val, sp->name, sizeof(sp->name)); 
      return true; 
    }
    
    if (!strcasecmp(sub, "muted")) { bool b; if (parseBool(String(val), b)) sp->mutedDefault = b; return true; }
    // --- Calibration keys (per sensor) ---
    if (!strcasecmp(sub, "cal_enabled")) {
      bool b; if (parseBool(String(val), b)) g_cals[idx].enabled = b;
      return true;
    }
    if (!strcasecmp(sub, "cal_allowed")) {
      g_calAllowed[idx] = parseCalAllowedCSV(val);
      return true;
    }
    //if (!strcasecmp(sub, "cal_mode")) {
    //  long v = strtol(val, nullptr, 10);
    //  g_cals[idx].mode = (v == 2) ? CalMode::RANGE : (v == 1 ? CalMode::ZERO : CalMode::NONE);
    //  return true;
    //}
    if (!strcasecmp(sub, "r0_raw"))         { g_cals[idx].r0_raw = (float)strtod(val,nullptr); return true; }
    if (!strcasecmp(sub, "r1_raw"))         { g_cals[idx].r1_raw = (float)strtod(val,nullptr); return true; }
    if (!strcasecmp(sub, "capture_avg_ms")) { long v=strtol(val,nullptr,10); if (v>=0 && v<=65535) g_cals[idx].capture_avg_ms=(uint16_t)v; return true; }
    if (!strcasecmp(sub, "capture_n"))      { long v=strtol(val,nullptr,10); if (v>=0 && v<=65535) g_cals[idx].capture_n=(uint16_t)v;     return true; }
    if (!strcasecmp(sub, "ts_epoch_ms"))    { g_cals[idx].ts_epoch_ms = (uint64_t)strtoull(val,nullptr,10); return true; }




    // everything else goes to ParamPack backing store
    storeKV((uint8_t)idx, sub, val);
    return true;
  }

  // ---- globals ----
  if (keyEquals(key, "sample_rate_hz")) { long v=strtol(val,nullptr,10); if (v>=1 && v<=2000) cfg.sampleRateHz=(uint16_t)v; return true; }
  if (keyEquals(key, "timestamp_mode")) { if (!strcasecmp(val,"human")) cfg.timestampHuman=true; else if (!strcasecmp(val,"fast")) cfg.timestampHuman=false; return true; }
  if (keyEquals(key, "tz"))             { copyStrBounded(val, cfg.tz, sizeof(cfg.tz)); return true; }
  if (keyEquals(key, "debounce_ms"))    { long v=strtol(val,nullptr,10); if (v>=0 && v<=1000) cfg.debounceMs=(uint16_t)v; return true; }
  if (keyEquals(key, "web_button_pin")) { long v=strtol(val,nullptr,10); if (v>=0 && v<=39) cfg.webBtnPin=(uint8_t)v; return true; }
  if (keyEquals(key, "log_button_pin")) { long v=strtol(val,nullptr,10); if (v>=0 && v<=39) cfg.logBtnPin=(uint8_t)v; return true; }
  if (keyEquals(key, "mark_button_pin")){ long v=strtol(val,nullptr,10); if (v>=0 && v<=39) cfg.markBtnPin=(uint8_t)v; return true; }

  if (keyEquals(key, "nav_up_pin"))     { long v=strtol(val,nullptr,10); if (v>=0 && v<=39) cfg.navUpPin=(uint8_t)v; return true; }
  if (keyEquals(key, "nav_down_pin"))   { long v=strtol(val,nullptr,10); if (v>=0 && v<=39) cfg.navDownPin=(uint8_t)v; return true; }
  if (keyEquals(key, "nav_left_pin"))   { long v=strtol(val,nullptr,10); if (v>=0 && v<=39) cfg.navLeftPin=(uint8_t)v; return true; }
  if (keyEquals(key, "nav_right_pin"))  { long v=strtol(val,nullptr,10); if (v>=0 && v<=39) cfg.navRightPin=(uint8_t)v; return true; }
  if (keyEquals(key, "nav_enter_pin"))  { long v=strtol(val,nullptr,10); if (v>=0 && v<=39) cfg.navEnterPin=(uint8_t)v; return true; }


  if (keyEquals(key, "use_external_rtc")){ bool b; if (parseBool(String(val), b)) cfg.useExternalRTC=b; return true; }
  if (keyEquals(key, "wifi_ssid"))      { copyStrBounded(val, cfg.wifiSSID, sizeof(cfg.wifiSSID)); return true; }
  if (keyEquals(key, "wifi_password"))  { copyStrBounded(val, cfg.wifiPassword, sizeof(cfg.wifiPassword)); return true; }

    // ---- new-style WiFi globals ----
  if (keyEquals(key, "wifi_enabled_default")) {bool b; if (ConfigManager::parseBool(String(val), b)) cfg.wifiEnabledDefault = b; return true;  }
  if (keyEquals(key, "wifi_auto_time_on_rtc_invalid")) {bool b; if (ConfigManager::parseBool(String(val), b)) cfg.wifiAutoTimeOnRtcInvalid = b; return true;  }
  // advisory only; we'll recompute after load()
  if (keyEquals(key, "wifi_network_count")) {
    long v = strtol(val, nullptr, 10);
    if (v < 0) v = 0; if (v > 5) v = 5;
    cfg.wifiNetworkCount = (uint8_t)v;
    return true;
  }

  // ---- new-style WiFi per-slot: wifiN.* ----
  if (!strncasecmp(key, "wifi", 4) && isdigit((unsigned char)key[4])) {
    const char* p = key + 4; char* endp = nullptr;
    long idx = strtol(p, &endp, 10);
    if (idx < 0 || idx > 4 || !endp || *endp != '.') return true;
    const char* sub = endp + 1;

    // convenience
    auto& w = cfg.wifi[(int)idx];

    if (!strcasecmp(sub, "ssid"))     { copyStrBounded(val, w.ssid, sizeof(w.ssid)); return true; }
    if (!strcasecmp(sub, "password")) { copyStrBounded(val, w.password, sizeof(w.password)); return true; }

    if (!strcasecmp(sub, "min_rssi")) {
      long v = strtol(val, nullptr, 10);
      w.minRssi = validRssi((int)v) ? (int16_t)v : (int16_t)-127; // -127 = unset
      return true;
    }
    if (!strcasecmp(sub, "bssid")) {
      uint8_t mac[6];
      if (parseMac(val, mac)) { memcpy(w.bssid, mac, 6); w.bssidSet = true; }
      else { w.bssidSet = false; memset(w.bssid, 0, 6); }
      return true;
    }
    if (!strcasecmp(sub, "hidden")) {
      bool b; if (ConfigManager::parseBool(String(val), b)) w.hidden = b;
      return true;
    }
    return true;
  }


  if (keyEquals(key, "ntp_servers"))    { copyStrBounded(val, cfg.ntpServers, sizeof(cfg.ntpServers)); return true; }
  if (keyEquals(key, "time_check_url")) { copyStrBounded(val, cfg.timeCheckUrl, sizeof(cfg.timeCheckUrl)); return true; }
  if (keyEquals(key, "ui_target")) {
    long v=strtol(val,nullptr,10);
    if (v>=1 && v<=3) cfg.uiTarget=(uint8_t)v;
    else {
      if (!strcasecmp(val,"serial")) cfg.uiTarget=1;
      else if (!strcasecmp(val,"oled")) cfg.uiTarget=2;
      else if (!strcasecmp(val,"both")) cfg.uiTarget=3;
    }
    return true;
  }
  if (keyEquals(key, "ui_serial_level")){ long v=strtol(val,nullptr,10); if (v<1) v=1; if (v>4) v=4; cfg.uiSerialLevel=(uint8_t)v; return true; }
  if (keyEquals(key, "ui_oled_level"))  { long v=strtol(val,nullptr,10); if (v<1) v=1; if (v>4) v=4; cfg.uiOledLevel=(uint8_t)v; return true; }
  if (keyEquals(key, "oled_brightness")){ long v=strtol(val,nullptr,10); if (v<0) v=0; if (v>255) v=255; cfg.oledBrightness=(uint8_t)v; return true; }
  if (keyEquals(key, "oled_idle_dim_ms")){long v=strtol(val,nullptr,10); if (v<0) v=0; if (v>65535) v=65535; cfg.oledIdleDimMs=(uint16_t)v; return true; }

  //

  return true;
}

bool ConfigManager::load(LoggerConfig& cfg) {
  if (!g_sd) return false;

  FsFile f;
  if (!f.open(g_cfgName, O_RDONLY)) return false;

  // Reset parser scratch state
  g_specCount     = 0;
  g_expectedCount = 0;

  // Reset the destination (config-scoped) list for this load
  cfg.sensorN = 0;

  // Reset scratch ParamStores and make each scratch spec's ParamPack point at its store
  for (uint8_t i = 0; i < MAX_SENSORS; ++i) {
    g_stores[i].clear();
    g_specs[i].params.bind(&g_stores[i]);
  }

  // Parse the file line-by-line into scratch buffers (names, params, etc.)
  char line[256];
  while (readLine(f, line, sizeof(line))) {
    // parseLine fills g_specs/g_stores, updates g_specCount/g_expectedCount, etc.
    parseLine(line, cfg);
  }
  f.close();

  // If the file implied more sensors (e.g., late name-only lines), materialize them
  const uint8_t need = (g_expectedCount > g_specCount) ? g_expectedCount : g_specCount;
  for (uint8_t i = 0; i < need; ++i) {
    ensureSpec(i);
  }

  // Safety: rebind the scratch ParamPacks to their stores (in case ensureSpec touched them)
  for (uint8_t i = 0; i < g_specCount; ++i) {
    g_specs[i].params.bind(&g_stores[i]);
  }

  // ------------------------------
  // Populate the LoggerConfig copy
  // ------------------------------
  // Cap to MAX_SENSORS to avoid overflow; log if truncated (optional).
  cfg.sensorN = (g_specCount <= MAX_SENSORS) ? g_specCount : MAX_SENSORS;
  for (uint8_t i = 0; i < cfg.sensorN; ++i) {
    cfg.sensors[i] = g_specs[i];
    // NOTE: We do NOT bind cfg.sensors[i].params here.
    // Accessors should bind on output so returned copies point at the active store:
    //   bool LoggerConfig::getSensorSpec(i, out) const {
    //     out = sensors[i];
    //     out.params.bind(&g_stores[i]);
    //     return true;
    //   }
  }

  // Rebind ParamPacks just to be safe
  for (uint8_t i=0;i<g_specCount;++i) g_specs[i].params.bind(&g_stores[i]);
  
  // ---- Normalize new-style WiFi block ----
  // Recompute network count and clean invalids
  uint8_t count = 0;
  bool seen[5] = {false,false,false,false,false};
  for (int i = 0; i < 5; ++i) {
    // trim SSID
    if (cfg.wifi[i].ssid[0]) {
      // collapse whitespace-only SSIDs to empty
      String s = String(cfg.wifi[i].ssid); s.trim();
      if (s.length() == 0) { cfg.wifi[i].ssid[0] = '\0'; }
      else {
        // write back trimmed
        copyStrBounded(s.c_str(), cfg.wifi[i].ssid, sizeof(cfg.wifi[i].ssid));
      }
    }

    // accept only entries with a non-empty SSID
    if (cfg.wifi[i].ssid[0]) {
      // minRssi range check
      if (!validRssi(cfg.wifi[i].minRssi)) cfg.wifi[i].minRssi = -127;
      // bssidSet guard (all-zero means unset)
      bool allZero = true; for (int b=0;b<6;++b) if (cfg.wifi[i].bssid[b]) { allZero=false; break; }
      if (allZero) cfg.wifi[i].bssidSet = false;
      // track duplicates (keep first)
      if (!seen[i]) {
        // naive duplicate collapse by SSID across later slots
        for (int j = 0; j < i; ++j) {
          if (cfg.wifi[j].ssid[0] && !strcasecmp(cfg.wifi[j].ssid, cfg.wifi[i].ssid)) {
            cfg.wifi[i].ssid[0] = '\0'; // drop duplicate
            break;
          }
        }
      }
    }
    if (cfg.wifi[i].ssid[0]) ++count;
  }
  cfg.wifiNetworkCount = count;

  // If no new-style networks but legacy SSID present, synthesize one (back-compat)
  if (cfg.wifiNetworkCount == 0 && cfg.wifiSSID[0]) {
    copyStrBounded(cfg.wifiSSID,   cfg.wifi[0].ssid,     sizeof(cfg.wifi[0].ssid));
    copyStrBounded(cfg.wifiPassword, cfg.wifi[0].password, sizeof(cfg.wifi[0].password));
    cfg.wifi[0].minRssi = -127;
    cfg.wifi[0].bssidSet = false; memset(cfg.wifi[0].bssid, 0, 6);
    cfg.wifi[0].hidden = false;
    cfg.wifiNetworkCount = 1;
  }

  // Make this the active global config (preserves existing callers of ConfigManager::get()).
  s_cfg = cfg;

  return true;
}


bool ConfigManager::save(const LoggerConfig& cfg) {
  if (!g_sd) return false;

  FsFile f;
  if (!f.open(g_cfgName, O_WRONLY | O_CREAT | O_TRUNC)) return false;

  // ---- globals ----
  f.printf("# global\n");
  f.printf("sample_rate_hz=%u\n", (unsigned)cfg.sampleRateHz);
  f.printf("timestamp_mode=%s\n", cfg.timestampHuman ? "human" : "fast");
  f.printf("tz=%s\n", cfg.tz);
  f.printf("debounce_ms=%u\n", (unsigned)cfg.debounceMs);
  f.printf("web_button_pin=%u\n", (unsigned)cfg.webBtnPin);
  f.printf("log_button_pin=%u\n", (unsigned)cfg.logBtnPin);
  f.printf("mark_button_pin=%u\n", (unsigned)cfg.markBtnPin);

  f.printf("nav_up_pin=%u\n",   (unsigned)cfg.navUpPin);
  f.printf("nav_down_pin=%u\n", (unsigned)cfg.navDownPin);
  f.printf("nav_left_pin=%u\n", (unsigned)cfg.navLeftPin);
  f.printf("nav_right_pin=%u\n",(unsigned)cfg.navRightPin);
  f.printf("nav_enter_pin=%u\n",(unsigned)cfg.navEnterPin);

  f.printf("use_external_rtc=%s\n", cfg.useExternalRTC ? "true" : "false");
  f.printf("\n");
  
  // new-style WiFi (multi-network)
  f.printf("wifi_enabled_default=%s\n", cfg.wifiEnabledDefault ? "true" : "false");
  f.printf("wifi_auto_time_on_rtc_invalid=%s\n", cfg.wifiAutoTimeOnRtcInvalid ? "true" : "false");
  f.printf("wifi_network_count=%u\n", (unsigned)cfg.wifiNetworkCount);

  for (uint8_t i = 0; i < 5; ++i) {
    const auto& w = cfg.wifi[i];
    f.printf("wifi%u.ssid=%s\n", i, w.ssid);
    f.printf("wifi%u.password=%s\n", i, w.password);
    if (w.minRssi != -127) f.printf("wifi%u.min_rssi=%d\n", i, (int)w.minRssi);
    if (w.bssidSet) {
      f.printf("wifi%u.bssid=%02X:%02X:%02X:%02X:%02X:%02X\n", i,
               w.bssid[0], w.bssid[1], w.bssid[2], w.bssid[3], w.bssid[4], w.bssid[5]);
    }
    f.printf("wifi%u.hidden=%s\n", i, w.hidden ? "true" : "false");
  }
  f.printf("\n");

  
  //f.printf("wifi_ssid=%s\n", cfg.wifiSSID);
  //f.printf("wifi_password=%s\n", cfg.wifiPassword);
  f.printf("ntp_servers=%s\n", cfg.ntpServers);
  f.printf("time_check_url=%s\n", cfg.timeCheckUrl);
  f.printf("wifi_ssid=%s\n",     cfg.wifiSSID);
  f.printf("wifi_password=%s\n", cfg.wifiPassword);
  f.printf("ntp_servers=%s\n",   cfg.ntpServers);
  f.printf("time_check_url=%s\n",cfg.timeCheckUrl);
  f.printf("\n");
  f.printf("ui_target=%u\n",        (unsigned)cfg.uiTarget);
  f.printf("ui_serial_level=%u\n",  (unsigned)cfg.uiSerialLevel);
  f.printf("ui_oled_level=%u\n",    (unsigned)cfg.uiOledLevel);
  f.printf("oled_brightness=%u\n",  (unsigned)cfg.oledBrightness);
  f.printf("oled_idle_dim_ms=%u\n", (unsigned)cfg.oledIdleDimMs);
  f.printf("\n");

  // ---- sensors ----
  f.printf("# sensors\n");
  f.printf("sensor_count=%u\n\n", (unsigned)cfg.sensorCount());

  const uint8_t n = cfg.sensorCount();
  for (uint8_t i = 0; i < n; ++i) {
    const SensorSpec& sp = cfg.sensors[i];               // configured spec (POD copy)
    String typeKey = typeKeyForSave(sp.type);
    f.printf("sensor%u.type=%s\n", i, typeKey.c_str());
    f.printf("sensor%u.name=%s\n",  i, sp.name);
    f.printf("sensor%u.muted=%s\n", i, sp.mutedDefault ? "true" : "false");

    // Params: enumerate from the active ParamStore slot i
    const ParamStore* st = &g_stores[i];
    const uint8_t cnt = st->size();
    for (uint8_t k = 0; k < cnt; ++k) {
      f.printf("sensor%u.%s=%s\n", i, st->keys[k], st->vals[k]);
    }
    f.printf("\n");
  }

  f.close();

  // Keep the in-memory active copy synced
  s_cfg = cfg;
  return true;
}

void ConfigManager::print(const LoggerConfig& cfg) {
  Serial.println(F("[CFG] --- current config ---"));
  Serial.print(F("sampleRateHz="));   Serial.println(cfg.sampleRateHz);
  Serial.print(F("timestampHuman=")); Serial.println(cfg.timestampHuman ? "true":"false");
  Serial.print(F("tz="));             Serial.println(cfg.tz);
  Serial.print(F("debounceMs="));     Serial.println(cfg.debounceMs);
  Serial.print(F("webBtnPin="));      Serial.println(cfg.webBtnPin);
  Serial.print(F("logBtnPin="));      Serial.println(cfg.logBtnPin);
  Serial.print(F("markBtnPin="));     Serial.println(cfg.markBtnPin);

  Serial.print(F("navUpPin="));       Serial.println(cfg.navUpPin);
  Serial.print(F("navDownPin="));     Serial.println(cfg.navDownPin);
  Serial.print(F("navLeftPin="));     Serial.println(cfg.navLeftPin);
  Serial.print(F("navRightPin="));    Serial.println(cfg.navRightPin);
  Serial.print(F("navEnterPin="));    Serial.println(cfg.navEnterPin);

  Serial.print(F("useExternalRTC=")); Serial.println(cfg.useExternalRTC ? "true":"false");
  
    Serial.print(F("wifiEnabledDefault="));       Serial.println(cfg.wifiEnabledDefault ? "true":"false");
    Serial.print(F("wifiAutoTimeOnRtcInvalid=")); Serial.println(cfg.wifiAutoTimeOnRtcInvalid ? "true":"false");
    Serial.print(F("wifiNetworkCount="));         Serial.println(cfg.wifiNetworkCount);
    for (uint8_t i = 0; i < 5; ++i) {
      const auto& w = cfg.wifi[i];
      if (!w.ssid[0]) continue;
      Serial.print(F("  wifi")); Serial.print(i); Serial.print(F(": ssid='")); Serial.print(w.ssid);
      Serial.print(F("' hidden=")); Serial.print(w.hidden ? "1":"0");
      Serial.print(F(" minRssi=")); Serial.print((int)w.minRssi);
      Serial.print(F(" bssidSet=")); Serial.print(w.bssidSet ? "1":"0");
      if (w.bssidSet) {
        Serial.printf(" (%02X:%02X:%02X:%02X:%02X:%02X)",
          w.bssid[0],w.bssid[1],w.bssid[2],w.bssid[3],w.bssid[4],w.bssid[5]);
      }
      Serial.print(F(" pwd=")); Serial.println("********");
    }

  
  Serial.print(F("wifiSSID="));       Serial.println(cfg.wifiSSID);
  Serial.print(F("wifiPassword="));   Serial.println("********");
  Serial.print(F("ntpServers="));     Serial.println(cfg.ntpServers);
  Serial.print(F("timeCheckUrl="));   Serial.println(cfg.timeCheckUrl);
  Serial.print(F("uiTarget="));       Serial.println(cfg.uiTarget);
  Serial.print(F("uiSerialLevel="));  Serial.println(cfg.uiSerialLevel);
  Serial.print(F("uiOledLevel="));    Serial.println(cfg.uiOledLevel);
  Serial.print(F("oledBrightness=")); Serial.println(cfg.oledBrightness);
  Serial.print(F("oledIdleDimMs="));  Serial.println(cfg.oledIdleDimMs);

  const uint8_t n = cfg.sensorCount();
  Serial.print(F("sensors=")); Serial.println(n);

  for (uint8_t i = 0; i < n; ++i) {
    const SensorSpec& sp = cfg.sensors[i];
    Serial.print(F("  [")); Serial.print(i);
    Serial.print(F("] type=")); Serial.print(SensorRegistry::typeLabel(sp.type));
    Serial.print(F(" name="));  Serial.print(sp.name);
    Serial.print(F(" muted=")); Serial.println(sp.mutedDefault ? "true" : "false");

    // Print params from the active ParamStore slot i
    const ParamStore* st = &g_stores[i];
    for (uint8_t k = 0; k < st->size(); ++k) {
      Serial.print(F("     ")); Serial.print(st->keys[k]); Serial.print('=');
      Serial.println(st->vals[k]);
    }
  }
}


// ---- Safe accessors used by SensorManager ----
static const char* lookupKV_(uint8_t idx, const char* key) {
  if (idx >= g_specCount || !key || !*key) return nullptr;
  const ParamStore& st = g_stores[idx];
  if (st.count == 0) return nullptr;
  for (uint8_t i = 0; i < st.count; ++i) {
    const char* k = st.keys[i];
    if (k && strcasecmp(k, key) == 0) {
      return st.vals[i];
    }
  }
  return nullptr;
}

bool ConfigManager::getParam(uint8_t index, const char* key, String& out) {
  const char* v = lookupKV_(index, key);
  if (!v) return false;
  out = v;
  return true;
}

bool ConfigManager::getIntParam(uint8_t index, const char* key, long& out) {
  const char* v = lookupKV_(index, key);
  if (!v) return false;
  char* endp = nullptr;
  long tmp = strtol(v, &endp, 10);
  if (endp == v) return false;
  out = tmp;
  return true;
}

bool ConfigManager::getFloatParam(uint8_t index, const char* key, double& out) {
  const char* v = lookupKV_(index, key);
  if (!v) return false;
  char* endp = nullptr;
  double tmp = strtod(v, &endp);
  if (endp == v) return false;
  out = tmp;
  return true;
}

bool ConfigManager::getBoolParam(uint8_t index, const char* key, bool& out) {
  String s;
  if (!getParam(index, key, s)) return false;
  return ConfigManager::parseBool(s, out);
}

// ===== Calibration access =====

bool ConfigManager::loadCalibration(const char* sensorName, Calibration& out) {
  if (!sensorName || !*sensorName) return false;
  int8_t idx = ConfigManager::findSensorByName(sensorName);
  if (idx < 0) return false;
  out = g_cals[(uint8_t)idx];
  return true;
}

// Utility: upsert a "key=value\n" line in a whole-file String (flat format)
static void upsertKVLineFlat(String& content, const String& key, const String& value) {
  const String newline = key + "=" + value + "\n";

  // Find an occurrence of key at the start of a line (beginning of file or after '\n')
  int pos = -1;
  int searchFrom = 0;
  while (true) {
    int cand = content.indexOf(key + "=", searchFrom);
    if (cand < 0) break;
    if (cand == 0 || content[cand - 1] == '\n') { pos = cand; break; }
    searchFrom = cand + 1; // keep searching
  }

  if (pos >= 0) {
    // Replace the whole line "key=...<newline>" with our new line
    int lineEnd = content.indexOf('\n', pos);
    if (lineEnd < 0) lineEnd = content.length();
    // Remove the existing line
    content.remove(pos, lineEnd - pos);
    // Insert the new line by rebuilding around 'pos'
    content = content.substring(0, pos) + newline + content.substring(pos);
  } else {
    // Append new line; ensure the file ends with a newline first
    if (content.length() && content[content.length() - 1] != '\n') content += '\n';
    content += newline;
  }
}

bool ConfigManager::saveSensorParamByName(const char* sensorName, const char* key, const String& value) {
  if (!g_sd || !sensorName || !*sensorName || !key || !*key) return false;
  int8_t idx = ConfigManager::findSensorByName(sensorName);
  if (idx < 0) return false;
  return ConfigManager::saveSensorParamByIndex((uint8_t)idx, key, value);
}

bool ConfigManager::saveSensorParamByIndex(uint8_t index, const char* key, const String& value) {
  if (!g_sd || !key || !*key) return false;
  if (index >= g_specCount) return false;

  // Build "sensorN.key"
  const String prefix  = String("sensor") + String((int)index) + ".";
  const String fullKey = prefix + key;

  // Load entire file
  FsFile f;
  String content;
  if (f.open(g_cfgName, O_RDONLY)) {
    char line[256];
    while (readLine(f, line, sizeof(line))) { content += line; content += '\n'; }
    f.close();
  }

  // Upsert the line (same helper used by saveCalibration)
  upsertKVLineFlat(content, fullKey, value);

  // Write back atomically (truncate)
  if (!f.open(g_cfgName, O_WRONLY | O_CREAT | O_TRUNC)) return false;
  f.print(content);
  f.close();

  // Keep in-memory ParamStore in sync
  storeKV(index, key, value.c_str());
  return true;
}


bool ConfigManager::saveCalibration(const char* sensorName, const Calibration& cal) {
  if (!g_sd || !sensorName || !*sensorName) return false;

  // Locate index by name so we can write keys as "sensorN.xxx"
  int8_t idx = ConfigManager::findSensorByName(sensorName);
  if (idx < 0) return false;
  const String prefix = String("sensor") + String((int)idx) + ".";

  // Load entire file
  FsFile f;
  String content;
  if (f.open(g_cfgName, O_RDONLY)) {
    char line[256];
    while (readLine(f, line, sizeof(line))) { content += line; content += '\n'; }
    f.close();
  }

  // Upsert all calibration keys in flat style
  upsertKVLineFlat(content, prefix + "cal_enabled",    cal.enabled ? "1" : "0");
  upsertKVLineFlat(content, prefix + "cal_mode",       String((int)(cal.mode == CalMode::RANGE ? 2 : (cal.mode == CalMode::ZERO ? 1 : 0))));
  upsertKVLineFlat(content, prefix + "r0_raw",         String(cal.r0_raw, 6));
  upsertKVLineFlat(content, prefix + "r1_raw",         String(cal.r1_raw, 6));
  upsertKVLineFlat(content, prefix + "capture_avg_ms", String(cal.capture_avg_ms));
  upsertKVLineFlat(content, prefix + "capture_n",      String(cal.capture_n));
  upsertKVLineFlat(content, prefix + "ts_epoch_ms",    String((unsigned long long)cal.ts_epoch_ms));

  // Write back atomically (truncate)
  if (!f.open(g_cfgName, O_WRONLY | O_CREAT | O_TRUNC)) return false;
  f.print(content);
  f.close();

  // Update in-memory cache
  g_cals[(uint8_t)idx] = cal;
  return true;
}

bool ConfigManager::recomputeCalibrationFromUnits(const char* sensorName,
                                                  float u0_units, float u1_units) {
  Calibration cal;
  if (!loadCalibration(sensorName, cal)) return false;
  if (!cal.enabled || cal.mode == CalMode::NONE) return true; // nothing active
  if (!cal.recompute(u0_units, u1_units)) return false;
  return saveCalibration(sensorName, cal);
}

void ConfigManager::printCalibration(const char* sensorName) {
  if (!sensorName || !*sensorName) {
    Serial.println(F("printCalibration: invalid sensor name"));
    return;
  }
  int8_t idx = ConfigManager::findSensorByName(sensorName);
  if (idx < 0) {
    Serial.print(F("printCalibration: sensor not found: "));
    Serial.println(sensorName);
    return;
  }
  printCalibration(idx);
}

void ConfigManager::printCalibration(int8_t sensorIndex) {
  if (sensorIndex < 0 || uint8_t(sensorIndex) >= kCalSlots) {
    Serial.println(F("printCalibration: invalid sensor index"));
    return;
  }

  const uint8_t idx = (uint8_t)sensorIndex;

  // Directly use the TU-local cache; no externs here
  const Calibration& c = g_cals[idx];

  Serial.print(F("sensor"));
  Serial.print(idx);
  Serial.println(F(".calibration {"));

  Serial.print(F("  enabled        = ")); Serial.println(c.enabled ? F("1") : F("0"));
  Serial.print(F("  mode           = ")); Serial.print((int)(c.mode == CalMode::RANGE ? 2 : (c.mode == CalMode::ZERO ? 1 : 0)));
  Serial.print(F(" (")); Serial.print(calModeToStr(c.mode)); Serial.println(F(")"));

  Serial.print(F("  r0_raw         = ")); Serial.println(c.r0_raw, 6);
  Serial.print(F("  r1_raw         = ")); Serial.println(c.r1_raw, 6);
  Serial.print(F("  capture_avg_ms = ")); Serial.println(c.capture_avg_ms);
  Serial.print(F("  capture_n      = ")); Serial.println(c.capture_n);
  Serial.print(F("  ts_epoch_ms    = ")); Serial.println((unsigned long long)c.ts_epoch_ms);

  // Derived terms (k_gain/k_offset) are meaningful only after recompute(u0,u1).
  Serial.print(F("  k_gain         = ")); Serial.println(c.k_gain, 9);
  Serial.print(F("  k_offset       = ")); Serial.println(c.k_offset, 9);

  // Convenience: span in RAW
  Serial.print(F("  delta_r        = ")); Serial.println(c.r1_raw - c.r0_raw, 6);

  // --- Mode visibility ---
  CalModeMask typeMask  = typeSupportedMask(g_specs[idx].type);
  CalModeMask allowMask = g_calAllowed[idx];
  if (allowMask == 0xFF) allowMask = typeMask;
  CalModeMask resolvedMask = (typeMask & allowMask);

  Serial.print(F("  supportedModes = ")); Serial.println(calMaskToStr(typeMask));
  Serial.print(F("  allowedMask    = ")); Serial.println(calMaskToStr(allowMask));
  Serial.print(F("  menuMask       = ")); Serial.println(calMaskToStr(resolvedMask));


  Serial.println(F("}"));
}


void ConfigManager::printAllCalibrations() {
  Serial.println(F("=== Calibration Summary ==="));
  for (int8_t i = 0; i < kCalSlots; ++i) {
    printCalibration(i);
  }
  Serial.println(F("==========================="));
}

CalModeMask ConfigManager::calAllowedMaskByIndex(uint8_t index) {
  if (index >= MAX_SENSORS) return 0xFF;  // inherit
  return g_calAllowed[index];
}

CalModeMask ConfigManager::calAllowedMaskByName(const char* sensorName) {
  if (!sensorName || !*sensorName) return 0xFF;  // inherit
  int8_t idx = ConfigManager::findSensorByName(sensorName);
  if (idx < 0) return 0xFF;                      // inherit
  return g_calAllowed[(uint8_t)idx];
}

bool ConfigManager::loadCalibrationByIndex(uint8_t index, Calibration& out) {
  if (index >= g_specCount) return false;
  out = g_cals[index];
  return true;
}
bool ConfigManager::saveCalibrationByIndex(uint8_t index, const Calibration& cal) {
  if (index >= g_specCount) return false;
  // save using name-based writer so the flat file gets sensorN.* keys consistently
  return ConfigManager::saveCalibration(g_specs[index].name, cal);
}
CalMode ConfigManager::loadCalModeByIndex(uint8_t index) {
  if (index >= g_specCount) return CalMode::NONE;
  return g_cals[index].mode;
}
void ConfigManager::setCalAllowedByIndex(uint8_t index, CalModeMask m) {
  if (index >= MAX_SENSORS) return;
  g_calAllowed[index] = m;
  // Optionally write-through to file here by upserting sensorN.cal_allowed line
  // using the same String-file "upsert" helper you already have.
}

bool ConfigManager::setSensorHeaderByIndex(uint8_t index, const SensorSpec& sp) {
  if (index >= g_specCount) return false;
  g_specs[index].type = sp.type;
  // copy name safely
  copyStrBounded(sp.name, g_specs[index].name, sizeof(g_specs[index].name));
  g_specs[index].mutedDefault = sp.mutedDefault;
  return true;
}

bool ConfigManager::hasConfiguredNetworks() {
  return s_cfg.wifiNetworkCount > 0;
}

const LoggerConfig::WiFiEntry* ConfigManager::wifiNetworks(size_t& count) {
  count = s_cfg.wifiNetworkCount;
  return s_cfg.wifi;  // pointer to the first element of the fixed array
}


void ConfigManager::debugDumpConfigFile() {
  if (!g_sd) { Serial.println(F("[CFG] No SD mounted")); return; }
  FsFile f;
  Serial.print(F("[CFG] Opening file: ")); Serial.println(g_cfgName);
  if (!f.open(g_cfgName, O_RDONLY)) { Serial.println(F("[CFG] open FAIL")); return; }
  Serial.println(F("[CFG] --- file contents ---"));
  char line[256];
  while (true) {
    size_t n = 0; int c;
    while (n < sizeof(line)-1 && (c = f.read()) >= 0) {
      if (c == '\r') continue;
      if (c == '\n') break;
      line[n++] = (char)c;
    }
    if (n == 0 && c < 0) break;
    line[n] = '\0';
    Serial.println(line);
    if (c < 0) break;
  }
  f.close();
  Serial.println(F("[CFG] --- end file ---"));
}


//LoggerConfig methods
uint8_t LoggerConfig::sensorCount() const {
   return sensorN; 
}

bool LoggerConfig::getSensorSpec(uint8_t i, SensorSpec& out) const {
  if (i >= sensorN) return false;
  out = sensors[i];
  out.params.bind(&g_stores[i]);   // make the copy's ParamPack view the correct store
  return true;
}

int8_t LoggerConfig::findSensorByName(const char* name) const {
  if (!name || !*name) return -1;
  for (uint8_t i = 0; i < sensorN; ++i) {
    if (!strcasecmp(sensors[i].name, name)) return (int8_t)i;
  }
  return -1;
}
