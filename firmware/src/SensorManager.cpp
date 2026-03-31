#include "SensorManager.h"
#include "Sensor.h"
#include "AnalogPotSensor.h"
#include "ConfigManager.h"
#include "SensorRegistry.h"
#include "TransformRegistry.h"
#include "StorageManager.h"
#include "SensorTypes.h"
#include "UI.h"
#include "BoardSelect.h" 
#include <cstring>
#include "BoardSelect.h"
#include "DebugLog.h"

#define SENS_LOGE(...) LOGE_TAG("SENS", __VA_ARGS__)
#define SENS_LOGW(...) LOGW_TAG("SENS", __VA_ARGS__)
#define SENS_LOGI(...) LOGI_TAG("SENS", __VA_ARGS__)
#define SENS_LOGD(...) LOGD_TAG("SENS", __VA_ARGS__)
#define XFORM_LOGW(...) LOGW_TAG("XFORM", __VA_ARGS__)
#define XFORM_LOGI(...) LOGI_TAG("XFORM", __VA_ARGS__)
#define XFORM_LOGD(...) LOGD_TAG("XFORM", __VA_ARGS__)
#define SM_LOGI(...) LOGI_TAG("SM", __VA_ARGS__)

//Debug
static uint32_t s_sampleID = 0;

namespace {
  //constexpr uint8_t MAX_SENSORS = 16;
  Sensor*             s_list[MAX_SENSORS] = { nullptr };
  const LoggerConfig* s_cfg               = nullptr;
  AnalogPotSensor*    s_primaryPot        = nullptr;

  int firstFree() {
    for (int i = 0; i < (int)MAX_SENSORS; ++i) if (!s_list[i]) return i;
    return -1;
  }

  void appendCsv(char* out, size_t cap, const char* token) {
    if (!out || cap == 0 || !token || !*token) return;
    size_t len = strnlen(out, cap);
    if (len >= cap - 1) return;

    if (len > 0) {
      if (len + 1 >= cap) return;
      out[len++] = ',';
      out[len] = '\0';
    }
    size_t i = 0;
    while (token[i] && (len + i) < cap - 1) {
      out[len + i] = token[i];
      ++i;
    }
    out[len + i] = '\0';
  }

  static uint16_t countColumns() {
    uint16_t total = 0;
    for (auto* s : s_list) {
      if (!s || s->muted()) continue;
      total += s->columnCount();
    }
    return total;
  }

  bool sensorNeedsAnalogPin_(SensorType t) {
    switch (t) {
      case SensorType::AnalogPot:
      case SensorType::AS5600StringPotAnalog:
        return true;
      case SensorType::AS5600StringPotI2C:
      case SensorType::Unknown:
      default:
        return false;
    }
  }
}

static CalMask parseCalMaskCSV(const char* csv) {
  if (!csv || !*csv) return CAL_NONE;
  CalMask m = CAL_NONE;

  auto matches = [](const char* a, const char* b) -> bool {
    while (*a && *b) {
      char ca = (*a >= 'a' && *a <= 'z') ? char(*a - 32) : *a;
      char cb = (*b >= 'a' && *b <= 'z') ? char(*b - 32) : *b;
      if (ca != cb) return false;
      ++a; ++b;
    }
    return (*a == '\0' && *b == '\0');
  };

  const char* p = csv;
  while (*p) {
    while (*p == ',' || *p == ' ' || *p == '\t') ++p;
    if (!*p) break;

    const char* start = p;
    while (*p && *p != ',') ++p;
    size_t len = size_t(p - start);
    if (len > 0) {
      char buf[16];
      if (len >= sizeof(buf)) len = sizeof(buf)-1;
      memcpy(buf, start, len);
      buf[len] = '\0';

      if (matches(buf, "ZERO"))  m |= CAL_ZERO;
      if (matches(buf, "RANGE")) m |= CAL_RANGE;
    }
  }
  return m;
}

namespace SensorManager {

void begin(const LoggerConfig* cfg) {
  s_cfg = cfg;
  for (auto& p : s_list) p = nullptr;
  s_primaryPot = nullptr;
}

void registerSensor(Sensor* s) {
  if (!s) return;
  for (auto* p : s_list) if (p == s) return;
  int idx = firstFree();
  if (idx < 0) return;
  s_list[idx] = s;
}

void buildSensorsFromConfig(const LoggerConfig& cfg) {
  SENS_LOGI("Starting buildSensorsFromConfig\n");
  const uint8_t n = cfg.sensorCount();
  if (n == 0) {
    UI::status("No sensors");
    return;
  }

  for (uint8_t i = 0; i < n; ++i) {
    SensorSpec sp;
    if (!cfg.getSensorSpec(i, sp)) { ///need tp make this non-global
      SENS_LOGW("spec %u read failed\n", i);
      continue;
    }

    // --- Resolve analog input ordinal (ain) to a physical GPIO pin via BoardProfile ---
    if (sensorNeedsAnalogPin_(sp.type)) {
      long ain = -1;
      if (sp.params.getInt("ain", ain)) {
        if (!board::gBoard) {
          SENS_LOGW("sensor '%s' has ain=%ld but gBoard is null\n", sp.name, ain);
        } else {
          const auto& bp = *board::gBoard;

          if (ain < 0 || ain >= (long)bp.analog.count) {
            SENS_LOGW("sensor '%s': ain=%ld out of range (board analog.count=%u)\n",
                      sp.name, ain, (unsigned)bp.analog.count);
          } else {
            const int pin = bp.analog.pins[(uint8_t)ain];
            if (pin < 0) {
              SENS_LOGW("sensor '%s': AIN%ld not available on this board (pin<0)\n",
                        sp.name, ain);
            } else {
              sp.params.set("pin", String(pin));
              SENS_LOGI("sensor '%s': ain=%ld -> pin=%d\n", sp.name, ain, pin);
            }
          }
        }
      }
    }

    const SensorTypeInfo* ti = SensorRegistry::lookup(sp.type);
    if (!ti) {
      SENS_LOGW("type %u not registered (sensor '%s')\n",
                (unsigned)sp.type, sp.name);
      continue;
    }

    if (sensorNeedsAnalogPin_(sp.type)) {
      long pinCheck;
      if (!sp.params.getInt("pin", pinCheck) || pinCheck < 0) {
        SENS_LOGW("'%s': no valid analog input assigned (missing or invalid ain)\n",
                  sp.name);
        continue;
      }
    }

    // Create via registry factory — IMPORTANT: respect muted default from config
    Sensor* s = ti->create(sp.name, sp.params, sp.mutedDefault);
    if (!s) {
      SENS_LOGE("create failed for '%s' (type %u)\n",
                sp.name, (unsigned)sp.type);
      continue;
    }

    XFORM_LOGI("about to load transforms for '%s'\n", sp.name);
    XFORM_LOGD("gSd ptr=%p\n", (void*)gSd);

    // Preload any transforms on disk for this sensor
    if (SD_MMC.cardType() != CARD_NONE) {
      gTransforms.loadForSensor(sp.name, SD_MMC);   // fs::FS&
    } else if (gSd) {
      gTransforms.loadForSensor(sp.name, *gSd);     // SdFs& (SPI backend)
    } else {
      XFORM_LOGW("no SD backend available -> skipping transform load\n");
    }

    {
      auto metas = gTransforms.list(sp.name);
      XFORM_LOGI("loaded %u transforms for sensor='%s':\n",
                 (unsigned)metas.size(), sp.name);
      for (const auto& m : metas) {
        LOGI("  id='%s' label='%s'\n", m.id, m.label);
      }
    }

    // Selected transform (shape) from config; identity if absent
    {
    String outId;
    bool haveId = sp.params.get("output_id", outId) && outId.length();
    if (!haveId) {
      // If exactly one non-identity transform is available, auto-select it
      auto metas = gTransforms.list(sp.name);
      String onlyId;
      for (const auto& m : metas) {
        if (m.id == "identity") continue;
        if (onlyId.length()) { onlyId = ""; break; } // >1, bail
        onlyId = m.id;
      }
      if (onlyId.length()) {
        outId = onlyId;
        sp.params.set("output_id", outId);  // persist in-memory (optional file save later)
      }
    }

    // NEW: strip filename extension (".lut", ".poly", etc)
    int dot = outId.lastIndexOf('.');
    if (dot > 0) outId = outId.substring(0, dot);

    // sanitize and apply if present
    if (outId.length()) {
      outId.trim();
      // strip trailing separators/spaces
      while (outId.length()) {
        char c = outId[outId.length()-1];
        if (c == ',' || c == ';' || c <= ' ') outId.remove(outId.length()-1);
        else break;
      }


      // Persist normalized id so future saves keep the clean value
      ConfigManager::saveSensorParamByName(sp.name, "output_id", outId);
      s->setSelectedTransformId(outId);
    }
    s->attachTransform(gTransforms);  // identity fallback if none selected

    }

    // -------- Apply runtime config from sp to the live sensor (boot defaults) --------

    // 1) Muted state (so columnCount() later can omit muted sensors)
    s->setMuted(sp.mutedDefault);

    // 2) Output mode (RAW/LINEAR/POLY/LUT)
    {
      long omInt = -1; String omStr;
      OutputMode mode = OutputMode::RAW;
      if (sp.params.getInt("output_mode", omInt)) {
        if      (omInt == (long)OutputMode::RAW)    mode = OutputMode::RAW;
        else if (omInt == (long)OutputMode::LINEAR) mode = OutputMode::LINEAR;
        else if (omInt == (long)OutputMode::POLY)   mode = OutputMode::POLY;
        else if (omInt == (long)OutputMode::LUT)    mode = OutputMode::LUT;
      } else if (sp.params.get("output_mode", omStr)) {
        omStr.trim(); omStr.toUpperCase();
        if      (omStr == "RAW"    || omStr == "0") mode = OutputMode::RAW;
        else if (omStr == "LINEAR" || omStr == "1") mode = OutputMode::LINEAR;
        else if (omStr == "POLY"   || omStr == "2") mode = OutputMode::POLY;
        else if (omStr == "LUT"    || omStr == "3") mode = OutputMode::LUT;
      }
      s->setOutputMode(mode);
      if (mode == OutputMode::RAW) {
        s->setSelectedTransformId("identity");
      }


      // 3) Include raw column
      bool inc = false;
      sp.params.getBool("include_raw", inc);
      s->setIncludeRaw(inc);

      // ----- Units label policy -----
      // RAW    => "counts"
      // LINEAR => use user-specified units_label (if any)
      // POLY/LUT => always use transform's label
      {
        auto getLabelFromSelected = [&](const char* sensorName, const char* selId) -> String {
          if (!selId || !*selId) return String();
          for (const auto& m : gTransforms.list(sensorName)) {
            if (m.id == selId) {
              return String(m.label);   // <-- use transform's label
            }
          }
          return String();
        };

        switch (mode) {
          case OutputMode::RAW: {
            s->setOutputUnitsLabel("counts");
            break;
          }
          case OutputMode::LINEAR: {
            String ulabel;
            sp.params.get("units_label", ulabel);  // blank if unset
            s->setOutputUnitsLabel(ulabel.c_str());
            break;
          }
          case OutputMode::POLY:
          case OutputMode::LUT: {
            const String sel = s->selectedTransformId();
            const String lab = getLabelFromSelected(sp.name, sel.c_str());
            s->setOutputUnitsLabel(lab.c_str());   // empty if none
            break;
          }
        }
      }

    }

    // 5) Smoothing (EMA alpha + deadband), if present
    {
      SmoothingConfig sm = s->smoothing();

      // ema_alpha expects a double& from ParamPack
      double fa = 0.0;
      if (sp.params.getFloat("ema_alpha", fa)) {
        sm.emaAlpha = (float)fa;
      }

      // deadband: try float first, then fall back to int
      double dbf = 0.0;
      if (sp.params.getFloat("deadband", dbf)) {
        sm.deadband = (float)dbf;
      } else {
        long dbi = 0;
        if (sp.params.getInt("deadband", dbi)) {
          sm.deadband = (float)dbi;
        }
      }

      s->setSmoothing(sm);
    }


    // Register with SensorManager (takes ownership, per your contract)
    SensorManager::registerSensor(s);

    // ---- Calibration mask: supported (per type) ∧ allowed (per instance CSV) ----
    // 1) Supported per type
    CalMask supported = SensorRegistry::supportedCalMask(sp.type);

    // 2) Allowed per instance (CSV "ZERO,RANGE")
    String calCsvStr; const char* calCsv = nullptr;
    if (sp.params.get("cal_modes", calCsvStr)) {
      calCsv = calCsvStr.c_str();
    }

    // 3) Final = supported ∧ allowed (default to supported if CSV missing)
    CalMask allowed   = (calCsv && *calCsv) ? parseCalMaskCSV(calCsv) : supported;
    CalMask finalMask = (CalMask)(supported & allowed);

    // 4) Apply to the sensor
    s->setAllowedCalMask(finalMask);

    #ifdef SERIAL_DEBUG
    SENS_LOGD("[CalMask] %s supported=%X allowed=%X final=%X\n",
              sp.name, (int)supported, (int)allowed, (int)finalMask);
    #endif
  }
}

void finalizeBegin() {
  if (s_cfg) {
    for (auto* s : s_list) if (s) s->applyConfig(*s_cfg);
  }
  for (auto* s : s_list) if (s) s->begin();
}

void applyConfig(const LoggerConfig& cfg) {
  s_cfg = &cfg;
  for (auto* s : s_list) if (s) s->applyConfig(cfg);
}

void loop() {
  for (auto* s : s_list) if (s) s->loop();
}

void onLoggingStart() {
  for (auto* s : s_list) if (s) s->onLoggingStart();
}

void onLoggingStop() {
  for (auto* s : s_list) if (s) s->onLoggingStop();
}

uint8_t count() {
  uint8_t n = 0;
  for (auto* s : s_list) if (s) ++n;
  return n;
}

Sensor* get(uint8_t i) {
  uint8_t seen = 0;
  for (auto* s : s_list) {
    if (!s) continue;
    if (seen == i) return s;
    ++seen;
  }
  return nullptr;
}

Sensor* at(uint8_t i) { return get(i); }

bool getMuted(uint8_t index, bool& outMuted) {
  if (index >= MAX_SENSORS || !s_list[index]) return false;
  outMuted = s_list[index]->muted();
  return true;
}

bool setMuted(uint8_t index, bool muted) {
  if (index >= MAX_SENSORS || !s_list[index]) return false;
  s_list[index]->setMuted(muted);
  return true;
}

uint8_t activeCount() {
  uint8_t n = ConfigManager::sensorCount();
  uint8_t active = 0;
  for (uint8_t i = 0; i < n; ++i) {
    bool muted = false;
    if (getMuted(i, muted) && !muted) {
      ++active;
    }
  }
  return active;
}

uint16_t dynamicColumnCount() {
  return countColumns();
}

void buildHeader(char* out, size_t n, bool humanTs) {
  if (!out || n == 0) return;
  out[0] = '\0';

  appendCsv(out, n, humanTs ? "timestamp" : "timestamp_ms");

  for (auto* s : s_list) {
    if (!s || s->muted()) continue;
    const uint8_t cols = s->columnCount();
    for (uint8_t i = 0; i < cols; ++i) {
      char nameBuf[96] = {0};
      s->getColumnName(i, nameBuf, sizeof(nameBuf));

      if (!nameBuf[0]) {
        char fb[32];
        snprintf(fb, sizeof(fb), "col%u", (unsigned)i);
        appendCsv(out, n, fb);
      } else {
        appendCsv(out, n, nameBuf);
      }
    }
  }

  appendCsv(out, n, "mark");
}

void sampleValues(float* out, uint16_t cap, uint16_t& written) {
    written = 0;
    if (!out || cap == 0) return;
    //
    // 2. Write all sensor columns as before
    //
    for (auto* s : s_list) {
        if (!s || s->muted()) continue;

        const uint8_t need = s->columnCount();
        if (!need) continue;

        const uint16_t room = (written < cap) ? (cap - written) : 0;
        if (!room) break;

        const uint8_t toWrite = (need <= room) ? need : (uint8_t)room;
        s->sampleValues(out + written, toWrite);
        written += toWrite;

        if (toWrite < need) break;
    }
}


void debugDump(const char* tag) {
  const uint8_t kSlots = MAX_SENSORS;
  uint8_t n = 0;
  for (uint8_t i = 0; i < kSlots; ++i) if (s_list[i]) ++n;

  SM_LOGI("%s: sensors=%u\n", tag, (unsigned)n);

  for (uint8_t i = 0; i < kSlots; ++i) {
    Sensor* s = s_list[i];
    if (!s) continue;
    const uint8_t cols = s->columnCount();
    char firstCol[24] = {0};
    if (cols) s->getColumnName(0, firstCol, sizeof(firstCol));
    LOGI("  slot=%u muted=%d cols=%u firstCol='%s'\n",
         (unsigned)i, (int)s->muted(), (unsigned)cols, firstCol);
  }
}

} // namespace SensorManager


