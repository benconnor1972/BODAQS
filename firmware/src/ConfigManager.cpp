#include "ConfigManager.h"
#include "SensorParams.h"
#include "SensorTypes.h"
#include "Rates.h"
#include "Calibration.h"
#include "SensorRegistry.h"
#include "StorageManager.h"
#include "DebugLog.h"
#include <ctype.h>
#include <string.h>

extern LoggerConfig g_cfg;

#define CFG_LOGE(...) LOGE_TAG("CFG", __VA_ARGS__)
#define CFG_LOGW(...) LOGW_TAG("CFG", __VA_ARGS__)
#define CFG_LOGI(...) LOGI_TAG("CFG", __VA_ARGS__)
#define CFG_LOGD(...) LOGD_TAG("CFG", __VA_ARGS__)


// ---- private per-sensor key/value storage (backing ParamPack) ----
namespace {

  //constexpr uint8_t MAX_SENSORS = 8;     // single definition

  static SdFs*     g_sd = nullptr;
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

  // --- Bindings parsed from file (scratch until load() completes) ---

  ButtonBindingDef g_bindingDefs[MAX_BUTTON_BINDINGS];
  uint8_t          g_bindingDefCount       = 0;

  // Small helper: bounded string copy for button fields
  static void copyStrBoundedButton_(const char* src, char* dst, size_t cap) {
    if (!dst || cap == 0) return;
    if (!src) { dst[0] = '\0'; return; }
    strncpy(dst, src, cap - 1);
    dst[cap - 1] = '\0';
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

  static bool shouldPersistSensorKey_(uint8_t idx, const char* key) {
    if (!key || !*key || idx >= g_specCount) return false;

    // `pin` is a legacy fallback for analog sensors. When `ain` is present,
    // the physical GPIO is board-derived and `pin` becomes redundant noise.
    if (strcasecmp(key, "pin") == 0) {
      const ParamStore& st = g_stores[idx];
      for (uint8_t i = 0; i < st.count; ++i) {
        const char* k = st.keys[i];
        if (k && strcasecmp(k, "ain") == 0) return false;
      }
    }

    return true;
  }

  static SensorType strToSensorType(const char* v) {
    if (!v) return SensorType::AnalogPot;
    if (!strcasecmp(v, "analog_pot") || !strcasecmp(v, "pot")) return SensorType::AnalogPot;
    if (!strcasecmp(v, "as5600_string_pot_analog") || !strcasecmp(v, "as5600_pot_analog")) {
      return SensorType::AS5600StringPotAnalog;
    }
    if (!strcasecmp(v, "as5600_string_pot_i2c") || !strcasecmp(v, "as5600_pot_i2c")) {
      return SensorType::AS5600StringPotI2C;
    }
    return SensorType::AnalogPot;
  }

  // simple line reader for SdFat
//  static bool readLine(FsFile& f, char* buf, size_t cap) {
//    size_t n = 0; int c;
//    while (n < cap - 1 && (c = f.read()) >= 0) {
//      if (c == '\r') continue;
//      if (c == '\n') break;
//      buf[n++] = (char)c;
//    }
//    if (n == 0 && c < 0) return false;
//    buf[n] = '\0';
//    return true;
//  }

  // Convert a SensorType to a config-safe key like "analog_pot"
  static String typeKeyForSave(SensorType t) {
    const char* key = SensorRegistry::typeKey(t);
    return (key && key[0]) ? String(key) : String("unknown");
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
    return SensorRegistry::supportedCalMask(t);
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

void ConfigManager::begin(SdFs* sdRef, const char* filename) {
  // IMPORTANT: ConfigManager must not retain a SdFat pointer in SDMMC mode.
  // StorageManager_getSd() returns nullptr when SDIO_SDMMC is active.
  g_sd = sdRef;
  if (filename && *filename) copyStrBounded(filename, g_cfgName, sizeof(g_cfgName));

  g_specCount = 0;
  g_expectedCount = 0;

  for (uint8_t i = 0; i < MAX_SENSORS; ++i) {
    g_stores[i].clear();
    g_specs[i].params.bind(&g_stores[i]);
    g_cals[i] = Calibration{};
    g_calAllowed[i] = 0xFF;
  }

  g_bindingDefCount  = 0;

  for (uint8_t i = 0; i < MAX_BUTTON_BINDINGS; ++i) g_bindingDefs[i] = ButtonBindingDef{};
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

static bool parseIPv4(const String& s, uint8_t out[4]) {
  int a,b,c,d;
  if (sscanf(s.c_str(), "%d.%d.%d.%d", &a,&b,&c,&d) != 4) return false;
  if ((unsigned)a>255 || (unsigned)b>255 || (unsigned)c>255 || (unsigned)d>255) return false;
  out[0]=(uint8_t)a; out[1]=(uint8_t)b; out[2]=(uint8_t)c; out[3]=(uint8_t)d;
  return true;
}

static void setIPv4OrZero_(const char* val, uint8_t out[4]) {
  if (!val || !*val) { out[0]=out[1]=out[2]=out[3]=0; return; }
  uint8_t tmp[4];
  if (parseIPv4(val, tmp)) memcpy(out, tmp, 4);
  else { out[0]=out[1]=out[2]=out[3]=0; } // or "ignore"; your call
}

static String fmtIPv4(const uint8_t ip[4]) {
  char buf[16];
  snprintf(buf, sizeof(buf), "%u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]);
  return String(buf);
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
      CFG_LOGD("set name for sensor%ld = '%s'\n", idx, val);
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
  if (keyEquals(key, "auto_sleep_idle_ms")) { cfg.autoSleepIdleMs = (uint32_t)strtoul(val, nullptr, 10); return true; }
  if (keyEquals(key, "wifi_idle_timeout_ms")) { cfg.wifiIdleTimeoutMs = (uint32_t)strtoul(val, nullptr, 10); return true; }
  if (keyEquals(key, "log_level")) {
    if (!val[0] || !strcasecmp(val, "default")) {
      cfg.logLevelOverride = 0xFF;
      return true;
    }

    LogLevel level;
    if (Log_parseLevel(val, level)) {
      cfg.logLevelOverride = (uint8_t)level;
    }
    return true;
  }

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


   if (!strcasecmp(sub, "static_ip")) {
      bool b;
      if (ConfigManager::parseBool(String(val), b)) w.staticIp = b;
      return true;
    }
    if (!strcasecmp(sub, "ip"))      { setIPv4OrZero_(val, w.ip);      return true; }
    if (!strcasecmp(sub, "gateway")) { setIPv4OrZero_(val, w.gateway); return true; }
    if (!strcasecmp(sub, "subnet"))  { setIPv4OrZero_(val, w.subnet);  return true; }
    if (!strcasecmp(sub, "dns1"))    { setIPv4OrZero_(val, w.dns1);    return true; }
    if (!strcasecmp(sub, "dns2"))    { setIPv4OrZero_(val, w.dns2);    return true; }
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

  // --- buttonN.* : DEPRECATED (hardware buttons are defined by BoardProfile) ---
  if (!strncasecmp(key, "button", 6) && isdigit((unsigned char)key[6])) {
    // Ignore old hardware button definitions in config to avoid split source-of-truth.
    // Optional: print a one-time warning if you want visibility.
    static bool warned = false;
    if (!warned) {
      CFG_LOGW("Note: buttonN.* entries are ignored; hardware buttons now come from BoardProfile.\n");
      warned = true;
    }
    return true;
  }

  // Optional: ignore button_count too (if present in old configs)
  if (keyEquals(key, "button_count")) {
    static bool warnedCount = false;
    if (!warnedCount) {
      CFG_LOGW("Note: button_count is ignored; hardware buttons now come from BoardProfile.\n");
      warnedCount = true;
    }
    return true;
  }


  // --- bindingN.* : button-event → action mappings ---
  if (!strncasecmp(key, "binding", 7) && isdigit((unsigned char)key[7])) {
    const char* p   = key + 7;
    char*       end = nullptr;
    long        idx = strtol(p, &end, 10);
    if (idx < 0 || idx >= MAX_BUTTON_BINDINGS || !end || *end != '.') {
      return true;
    }

    const char*      sub = end + 1;
    ButtonBindingDef &bd = g_bindingDefs[(uint8_t)idx];

    if ((uint8_t)(idx + 1) > g_bindingDefCount) {
      g_bindingDefCount = (uint8_t)(idx + 1);
    }

    if (!strcasecmp(sub, "button")) {
      copyStrBoundedButton_(val, bd.buttonId, sizeof(bd.buttonId));
      return true;
    }
    if (!strcasecmp(sub, "event")) {
      copyStrBoundedButton_(val, bd.event, sizeof(bd.event));
      return true;
    }
    if (!strcasecmp(sub, "action")) {
      copyStrBoundedButton_(val, bd.action, sizeof(bd.action));
      return true;
    }

    return true;
  }

  //

  return true;
}

bool ConfigManager::load(LoggerConfig& cfg) {
  CFG_LOGI("Load: starting\n");

  // ---- Read whole config file into memory via StorageManager ----
  String content;
  if (!StorageManager_loadTextFile(g_cfgName, content)) {
    CFG_LOGW("Load: failed to open/read '%s', using defaults\n", g_cfgName);
    return false;
  }

  // ---- Reset parser scratch state ----
  g_specCount     = 0;
  g_expectedCount = 0;

  // Reset the destination (config-scoped) list for this load
  cfg.sensorN = 0;

  // Reset scratch ParamStores and make each scratch spec's ParamPack point at its store
  for (uint8_t i = 0; i < MAX_SENSORS; ++i) {
    g_stores[i].clear();
    g_specs[i].params.bind(&g_stores[i]);
  }

  // ---- Parse the file line-by-line from the String ----
  char line[256];
  int  pos = 0;
  const int lenContent = content.length();

  while (pos < lenContent) {
    int next = content.indexOf('\n', pos);
    if (next < 0) next = lenContent;
    int lineLen = next - pos;
    if (lineLen >= (int)sizeof(line)) lineLen = sizeof(line) - 1;

    // Copy substring into line buffer
    content.substring(pos, pos + lineLen).toCharArray(line, sizeof(line));
    line[lineLen] = '\0';

    // Strip trailing '\r' if present (handles CRLF files)
    size_t n = strlen(line);
    if (n && line[n - 1] == '\r') line[n - 1] = '\0';

    // parseLine fills g_specs/g_stores, updates g_specCount/g_expectedCount, etc.
    parseLine(line, cfg);

    pos = next + 1;
  }

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
  cfg.sensorN = (g_specCount <= MAX_SENSORS) ? g_specCount : MAX_SENSORS;
  for (uint8_t i = 0; i < cfg.sensorN; ++i) {
    cfg.sensors[i] = g_specs[i];
    // NOTE: We do NOT bind cfg.sensors[i].params here.
    // Accessors bind on output so returned copies point at the active store:
    //   bool LoggerConfig::getSensorSpec(i, out) const {
    //     out = sensors[i];
    //     out.params.bind(&g_stores[i]);
    //     return true;
    //   }
  }

  // Rebind ParamPacks just to be safe
  for (uint8_t i = 0; i < g_specCount; ++i) {
    g_specs[i].params.bind(&g_stores[i]);
  }

  // ---- Normalize new-style WiFi block ----
  uint8_t count = 0;
  bool seen[5] = {false,false,false,false,false};
  for (int i = 0; i < 5; ++i) {
    // trim SSID
    if (cfg.wifi[i].ssid[0]) {
      String s = String(cfg.wifi[i].ssid); s.trim();
      if (s.length() == 0) { cfg.wifi[i].ssid[0] = '\0'; }
      else {
        copyStrBounded(s.c_str(), cfg.wifi[i].ssid, sizeof(cfg.wifi[i].ssid));
      }
    }

    if (cfg.wifi[i].ssid[0]) {
      if (!validRssi(cfg.wifi[i].minRssi)) cfg.wifi[i].minRssi = -127;

      bool allZero = true;
      for (int b = 0; b < 6; ++b) {
        if (cfg.wifi[i].bssid[b]) { allZero = false; break; }
      }
      if (allZero) cfg.wifi[i].bssidSet = false;

      if (!seen[i]) {
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
    copyStrBounded(cfg.wifiSSID,     cfg.wifi[0].ssid,     sizeof(cfg.wifi[0].ssid));
    copyStrBounded(cfg.wifiPassword, cfg.wifi[0].password, sizeof(cfg.wifi[0].password));
    cfg.wifi[0].minRssi  = -127;
    cfg.wifi[0].bssidSet = false;
    memset(cfg.wifi[0].bssid, 0, 6);
    cfg.wifi[0].hidden = false;
    cfg.wifiNetworkCount = 1;
  }

  cfg.buttonBindingCount = (g_bindingDefCount <= MAX_BUTTON_BINDINGS)
                             ? g_bindingDefCount
                             : MAX_BUTTON_BINDINGS;
  for (uint8_t i = 0; i < cfg.buttonBindingCount; ++i) {
    cfg.buttonBindings[i] = g_bindingDefs[i];
  }

  // Now commit cfg as usual:
  s_cfg = cfg;

  CFG_LOGI("Load OK\n");
  return true;
}

bool ConfigManager::save(const LoggerConfig& cfg) {
  CFG_LOGI("save: starting\n");

  String out;
  out.reserve(4096);

  auto NZ = [](const char* s) -> const char* { return s ? s : ""; };

  auto line = [&](const char* s) {
    out += s;
    out += '\n';
  };

  auto kv = [&](const char* key, const char* val) {
    out += key;
    out += '=';
    out += NZ(val);
    out += '\n';
  };

  auto kv_bool = [&](const char* key, bool v) {
    out += key;
    out += '=';
    out += (v ? "true" : "false");
    out += '\n';
  };

  auto kv_u = [&](const char* key, unsigned v) {
    out += key;
    out += '=';
    out += String(v);
    out += '\n';
  };

  auto kv_i = [&](const char* key, int v) {
    out += key;
    out += '=';
    out += String(v);
    out += '\n';
  };

  // Helper for "wifiN.xxx" / "sensorN.xxx"
  auto kv_indexed = [&](const char* prefix, unsigned idx, const char* key, const char* val) {
    out += prefix;
    out += String(idx);
    out += '.';
    out += key;
    out += '=';
    out += NZ(val);
    out += '\n';
  };

  auto kv_indexed_bool = [&](const char* prefix, unsigned idx, const char* key, bool v) {
    out += prefix;
    out += String(idx);
    out += '.';
    out += key;
    out += '=';
    out += (v ? "true" : "false");
    out += '\n';
  };

auto kv_indexed_u = [&](const char* prefix, unsigned idx, const char* key, unsigned v) {
  out += prefix;
  out += String(idx);
  out += '.';
  out += key;
  out += '=';
  out += String(v);
  out += '\n';
};

auto kv_indexed_i = [&](const char* prefix, unsigned idx, const char* key, int v) {
  out += prefix;
  out += String(idx);
  out += '.';
  out += key;
  out += '=';
  out += String(v);
  out += '\n';
};

  // ---------------- Global ----------------
  line("# global");
  kv_u("sample_rate_hz", (unsigned)cfg.sampleRateHz);
  kv("timestamp_mode", cfg.timestampHuman ? "human" : "fast");
  kv("tz", cfg.tz);
  kv("ntp_servers", cfg.ntpServers);
  kv("time_check_url", cfg.timeCheckUrl);
  kv_u("debounce_ms", (unsigned)cfg.debounceMs);
  kv_u("auto_sleep_idle_ms", (unsigned)cfg.autoSleepIdleMs);
  kv_u("wifi_idle_timeout_ms", (unsigned)cfg.wifiIdleTimeoutMs);
  kv("log_level", (cfg.logLevelOverride == 0xFF) ? "default" : Log_levelName((LogLevel)cfg.logLevelOverride));
  line("");

  CFG_LOGD("save: globals ok\n");

  // ---------------- Button bindings ----------------
  line("# bindings");
  kv_u("binding_count", (unsigned)cfg.buttonBindingCount);

  for (uint8_t i = 0; i < cfg.buttonBindingCount && i < MAX_BUTTON_BINDINGS; ++i) {
    const ButtonBindingDef& bd = cfg.buttonBindings[i];
    kv_indexed("binding", i, "button", NZ(bd.buttonId));
    kv_indexed("binding", i, "event",  NZ(bd.event));
    kv_indexed("binding", i, "action", NZ(bd.action));
  }
  line("");


  // ---------------- WiFi ----------------
  kv_bool("wifi_enabled_default", cfg.wifiEnabledDefault);
  kv_bool("wifi_auto_time_on_rtc_invalid", cfg.wifiAutoTimeOnRtcInvalid);
  kv_u("wifi_network_count", (unsigned)cfg.wifiNetworkCount);

  for (uint8_t i = 0; i < cfg.wifiNetworkCount; i++) {
    const auto& w = cfg.wifi[i];

    kv_indexed("wifi", i, "ssid",     w.ssid);
    kv_indexed("wifi", i, "password", w.password);
    kv_indexed_i("wifi", i, "min_rssi", (int)w.minRssi);
    kv_indexed_bool("wifi", i, "hidden", w.hidden);

    // BSSID pinning
    if (w.bssidSet) {
      char bssidStr[18];
      snprintf(bssidStr, sizeof(bssidStr),
              "%02X:%02X:%02X:%02X:%02X:%02X",
              w.bssid[0], w.bssid[1], w.bssid[2],
              w.bssid[3], w.bssid[4], w.bssid[5]);
      kv_indexed("wifi", i, "bssid", bssidStr);
    } else {
      kv_indexed("wifi", i, "bssid", "");
    }

    // ---------- Static IP (per network) ----------
    kv_indexed_bool("wifi", i, "static_ip", w.staticIp);

    auto fmtIPv4 = [](const uint8_t a[4], char out[16]) {
      snprintf(out, 16, "%u.%u.%u.%u", a[0], a[1], a[2], a[3]);
    };

    char ipStr[16], gwStr[16], snStr[16], d1Str[16], d2Str[16];
    fmtIPv4(w.ip,      ipStr);
    fmtIPv4(w.gateway, gwStr);
    fmtIPv4(w.subnet,  snStr);
    fmtIPv4(w.dns1,    d1Str);
    fmtIPv4(w.dns2,    d2Str);

    kv_indexed("wifi", i, "ip",      ipStr);
    kv_indexed("wifi", i, "gateway", gwStr);
    kv_indexed("wifi", i, "subnet",  snStr);
    kv_indexed("wifi", i, "dns1",    d1Str);
    kv_indexed("wifi", i, "dns2",    d2Str);
  }


  line("");

  CFG_LOGD("save: wifi ok\n");

  // ---------------- UI ----------------
  kv_u("ui_target", (unsigned)cfg.uiTarget);
  kv_u("ui_serial_level", (unsigned)cfg.uiSerialLevel);
  kv_u("ui_oled_level", (unsigned)cfg.uiOledLevel);
  kv_u("oled_brightness", (unsigned)cfg.oledBrightness);
  kv_u("oled_idle_dim_ms", (unsigned)cfg.oledIdleDimMs);
  line("");


  // ---------------- Sensors ----------------
  line("# sensors");
  kv_u("sensor_count", (unsigned)cfg.sensorCount());
  line("");

  const uint8_t n = cfg.sensorCount();
  for (uint8_t i = 0; i < n; ++i) {
    const SensorSpec& sp = cfg.sensors[i];

    String typeKey = typeKeyForSave(sp.type);
    kv_indexed("sensor", i, "type", typeKey.c_str());
    kv_indexed("sensor", i, "name",  NZ(sp.name));
    kv_indexed_bool("sensor", i, "muted", sp.mutedDefault);

    const ParamStore& st = g_stores[i];
    for (uint8_t k = 0; k < st.size(); ++k) {
      if (!shouldPersistSensorKey_(i, st.keys[k])) continue;
      // Keys/vals are char*; make them null-safe
      out += "sensor"; out += String(i); out += ".";
      out += NZ(st.keys[k]);
      out += "=";
      out += NZ(st.vals[k]);
      out += "\n";
    }
    line("");
  }

  CFG_LOGD("save: sensors ok\n");

  // ---------------- Persist ----------------
  const bool ok = StorageManager_saveTextFile(g_cfgName, out);
  if (!ok) {
    CFG_LOGE("save: StorageManager_saveTextFile failed\n");
    return false;
  }

  s_cfg = cfg;
  g_cfg = s_cfg;
  return true;
}



void ConfigManager::print(const LoggerConfig& cfg) {
  LOGI("[CFG] --- current config ---\n");
  LOGI("sampleRateHz=%u\n", cfg.sampleRateHz);
  LOGI("timestampHuman=%s\n", cfg.timestampHuman ? "true" : "false");
  LOGI("tz=%s\n", cfg.tz);
  LOGI("debounceMs=%u\n", cfg.debounceMs);
  LOGI("autoSleepIdleMs=%lu\n", (unsigned long)cfg.autoSleepIdleMs);
  LOGI("wifiIdleTimeoutMs=%lu\n", (unsigned long)cfg.wifiIdleTimeoutMs);
  LOGI("logLevel=%s\n", (cfg.logLevelOverride == 0xFF) ? "default" : Log_levelName((LogLevel)cfg.logLevelOverride));

  LOGI("wifiEnabledDefault=%s\n", cfg.wifiEnabledDefault ? "true" : "false");
  LOGI("wifiAutoTimeOnRtcInvalid=%s\n", cfg.wifiAutoTimeOnRtcInvalid ? "true" : "false");
  LOGI("wifiNetworkCount=%u\n", cfg.wifiNetworkCount);
  for (uint8_t i = 0; i < 5; ++i) {
    const auto& w = cfg.wifi[i];
    if (!w.ssid[0]) continue;
    LOGI("  wifi%u: ssid='%s' hidden=%s minRssi=%d bssidSet=%s",
         i, w.ssid, w.hidden ? "1" : "0", (int)w.minRssi, w.bssidSet ? "1" : "0");
    if (w.bssidSet) {
      LOGI(" (%02X:%02X:%02X:%02X:%02X:%02X)",
           w.bssid[0], w.bssid[1], w.bssid[2], w.bssid[3], w.bssid[4], w.bssid[5]);
    }
    LOGI(" pwd=********\n");
  }


  LOGI("wifiSSID=%s\n", cfg.wifiSSID);
  LOGI("wifiPassword=********\n");
  LOGI("ntpServers=%s\n", cfg.ntpServers);
  LOGI("timeCheckUrl=%s\n", cfg.timeCheckUrl);
  LOGI("uiTarget=%u\n", cfg.uiTarget);
  LOGI("uiSerialLevel=%u\n", cfg.uiSerialLevel);
  LOGI("uiOledLevel=%u\n", cfg.uiOledLevel);
  LOGI("oledBrightness=%u\n", cfg.oledBrightness);
  LOGI("oledIdleDimMs=%u\n", cfg.oledIdleDimMs);

  const uint8_t n = cfg.sensorCount();
  LOGI("sensors=%u\n", n);

  for (uint8_t i = 0; i < n; ++i) {
    const SensorSpec& sp = cfg.sensors[i];
    LOGI("  [%u] type=%s name=%s muted=%s\n",
         i,
         SensorRegistry::typeLabel(sp.type),
         sp.name,
         sp.mutedDefault ? "true" : "false");

    // Print params from the active ParamStore slot i
    const ParamStore* st = &g_stores[i];
    for (uint8_t k = 0; k < st->size(); ++k) {
      LOGI("     %s=%s\n", st->keys[k], st->vals[k]);
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
  if (!sensorName || !*sensorName || !key || !*key) return false;
  int8_t idx = ConfigManager::findSensorByName(sensorName);
  if (idx < 0) return false;
  return ConfigManager::saveSensorParamByIndex((uint8_t)idx, key, value);
}


bool ConfigManager::saveSensorParamByIndex(uint8_t index, const char* key, const String& value) {
  if (!key || !*key) return false;
  if (index >= g_specCount) return false;

  // Build "sensorN.key"
  const String prefix  = String("sensor") + String((int)index) + ".";
  const String fullKey = prefix + key;

  // Load entire file (backend-agnostic)
  String content;
  (void)StorageManager_loadTextFile(g_cfgName, content); // if missing, content stays empty

  // Ensure newline termination so upsert behaves nicely
  if (content.length() && content[content.length() - 1] != '\n') content += '\n';

  // Upsert the line (flat style)
  upsertKVLineFlat(content, fullKey, value);

  // Persist back (backend-agnostic)
  if (!StorageManager_saveTextFile(g_cfgName, content)) return false;

  // Keep in-memory ParamStore in sync
  storeKV(index, key, value.c_str());
  return true;
}



bool ConfigManager::saveCalibration(const char* sensorName, const Calibration& cal) {
  if (!sensorName || !*sensorName) return false;

  // Locate index by name so we can write keys as "sensorN.xxx"
  int8_t idx = ConfigManager::findSensorByName(sensorName);
  if (idx < 0) return false;

  const String prefix = String("sensor") + String((int)idx) + ".";

  // Load entire file (backend-agnostic)
  String content;
  (void)StorageManager_loadTextFile(g_cfgName, content);

  if (content.length() && content[content.length() - 1] != '\n') content += '\n';

  // Upsert all calibration keys in flat style
  upsertKVLineFlat(content, prefix + "cal_enabled",    cal.enabled ? "1" : "0");

  int modeInt = 0;
  if (cal.mode == CalMode::ZERO)  modeInt = 1;
  if (cal.mode == CalMode::RANGE) modeInt = 2;
  upsertKVLineFlat(content, prefix + "cal_mode",       String(modeInt));

  upsertKVLineFlat(content, prefix + "r0_raw",         String(cal.r0_raw, 6));
  upsertKVLineFlat(content, prefix + "r1_raw",         String(cal.r1_raw, 6));
  upsertKVLineFlat(content, prefix + "capture_avg_ms", String(cal.capture_avg_ms));
  upsertKVLineFlat(content, prefix + "capture_n",      String(cal.capture_n));
  upsertKVLineFlat(content, prefix + "ts_epoch_ms",    String((unsigned long long)cal.ts_epoch_ms));

  // Persist back (backend-agnostic)
  if (!StorageManager_saveTextFile(g_cfgName, content)) return false;

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
    LOGW("printCalibration: invalid sensor name\n");
    return;
  }
  int8_t idx = ConfigManager::findSensorByName(sensorName);
  if (idx < 0) {
    LOGW("printCalibration: sensor not found: %s\n", sensorName);
    return;
  }
  printCalibration(idx);
}

void ConfigManager::printCalibration(int8_t sensorIndex) {
  if (sensorIndex < 0 || uint8_t(sensorIndex) >= kCalSlots) {
    LOGW("printCalibration: invalid sensor index\n");
    return;
  }

  const uint8_t idx = (uint8_t)sensorIndex;

  // Directly use the TU-local cache; no externs here
  const Calibration& c = g_cals[idx];

  LOGI("sensor%u.calibration {\n", idx);
  LOGI("  enabled        = %s\n", c.enabled ? "1" : "0");
  LOGI("  mode           = %d (%s)\n",
       (int)(c.mode == CalMode::RANGE ? 2 : (c.mode == CalMode::ZERO ? 1 : 0)),
       calModeToStr(c.mode));
  LOGI("  r0_raw         = %.6f\n", c.r0_raw);
  LOGI("  r1_raw         = %.6f\n", c.r1_raw);
  LOGI("  capture_avg_ms = %u\n", c.capture_avg_ms);
  LOGI("  capture_n      = %u\n", c.capture_n);
  LOGI("  ts_epoch_ms    = %llu\n", (unsigned long long)c.ts_epoch_ms);

  // Derived terms (k_gain/k_offset) are meaningful only after recompute(u0,u1).
  LOGI("  k_gain         = %.9f\n", c.k_gain);
  LOGI("  k_offset       = %.9f\n", c.k_offset);

  // Convenience: span in RAW
  LOGI("  delta_r        = %.6f\n", c.r1_raw - c.r0_raw);

  // --- Mode visibility ---
  CalModeMask typeMask  = typeSupportedMask(g_specs[idx].type);
  CalModeMask allowMask = g_calAllowed[idx];
  if (allowMask == 0xFF) allowMask = typeMask;
  CalModeMask resolvedMask = (typeMask & allowMask);

  const String typeMaskText = calMaskToStr(typeMask);
  const String allowMaskText = calMaskToStr(allowMask);
  const String resolvedMaskText = calMaskToStr(resolvedMask);
  LOGI("  supportedModes = %s\n", typeMaskText.c_str());
  LOGI("  allowedMask    = %s\n", allowMaskText.c_str());
  LOGI("  menuMask       = %s\n", resolvedMaskText.c_str());


  LOGI("}\n");
}


void ConfigManager::printAllCalibrations() {
  LOGI("=== Calibration Summary ===\n");
  for (int8_t i = 0; i < kCalSlots; ++i) {
    printCalibration(i);
  }
  LOGI("===========================\n");
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
  String content;
  CFG_LOGI("Opening file: %s\n", g_cfgName);

  if (!StorageManager_loadTextFile(g_cfgName, content)) {
    CFG_LOGW("open FAIL\n");
    return;
  }

  CFG_LOGI("--- file contents ---\n");

  // Print line-by-line to avoid one huge buffered log and match old behaviour.
  int start = 0;
  while (start < (int)content.length()) {
    int end = content.indexOf('\n', start);
    if (end < 0) end = content.length();
    String line = content.substring(start, end);
    if (line.endsWith("\r")) line.remove(line.length() - 1);
    LOGI("%s\n", line.c_str());
    start = end + 1;
  }

  CFG_LOGI("--- end file ---\n");
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
