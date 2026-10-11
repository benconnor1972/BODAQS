#include "SensorManager.h"
#include "Sensor.h"
#include "AnalogPotSensor.h"
#include "ConfigManager.h"
#include "SensorRegistry.h"
#include "StorageManager.h"
#include "SensorTypes.h"
#include "UI.h"
#include "BoardSelect.h" 
#include "AnalogInputManager.h"
#include "I2CBusScheduler.h"
#include "BMI270ImuSensor.h"
#include "BMI270Profile.h"
#include "BdqV2Catalog.h"
#include "LoggerLimits.h"
#include "SensorAssignment.h"
#include <cstring>
#include "BoardSelect.h"
#include "DebugLog.h"

#define SENS_LOGE(...) LOGE_TAG("SENS", __VA_ARGS__)
#define SENS_LOGW(...) LOGW_TAG("SENS", __VA_ARGS__)
#define SENS_LOGI(...) LOGI_TAG("SENS", __VA_ARGS__)
#define SENS_LOGD(...) LOGD_TAG("SENS", __VA_ARGS__)
#define SM_LOGI(...) LOGI_TAG("SM", __VA_ARGS__)

//Debug
static uint32_t s_sampleID = 0;

namespace {
  //constexpr uint8_t MAX_SENSORS = 16;
  Sensor*             s_list[MAX_SENSORS] = { nullptr };
  SensorAssignment    s_liveAssignment[MAX_SENSORS];
  SensorType          s_liveType[MAX_SENSORS] = {};
  bool                s_liveMutedDefault[MAX_SENSORS] = {};
  bool                s_loggingStarted[MAX_SENSORS] = {};
  bool                s_loggingStopped[MAX_SENSORS] = {};
  const LoggerConfig* s_cfg               = nullptr;
  AnalogPotSensor*    s_primaryPot        = nullptr;
  SensorTimingStats   s_timingStats;

  int firstFree() {
    for (int i = 0; i < (int)MAX_SENSORS; ++i) if (!s_list[i]) return i;
    return -1;
  }

  int liveIndex_(const SensorSpec& spec) {
    for (int i = 0; i < MAX_SENSORS; ++i) {
      if (s_list[i] && s_liveType[i] == spec.type &&
          strcasecmp(s_list[i]->name(), spec.name) == 0) return i;
    }
    return -1;
  }

  bool configuredActive_(const SensorSpec& spec) {
    const int i = liveIndex_(spec);
    // Menu muting is a runtime override. A newly saved mute change wins until
    // applied; unchanged saved defaults must not undo the menu override.
    if (i >= 0 && spec.mutedDefault == s_liveMutedDefault[i]) return !s_list[i]->muted();
    return !spec.mutedDefault;
  }

  void copyTimingText_(char* dst, size_t cap, const char* src) {
    if (!dst || cap == 0) return;
    if (!src) src = "";
    size_t n = strlen(src);
    if (n >= cap) n = cap - 1;
    memcpy(dst, src, n);
    dst[n] = '\0';
  }

  void refreshTimingSlot_(uint8_t idx, Sensor* s) {
    if (idx >= SensorTimingStats::kMaxSensors) return;
    auto& slot = s_timingStats.sensor[idx];
    slot = SensorTimingStats::SensorStats{};
    if (!s) return;

    slot.present = true;
    slot.muted = s->muted();
    slot.synchronous = (s->sampleMode() == SensorSampleMode::Synchronous);
    slot.columnCount = s->columnCount();
    copyTimingText_(slot.name, sizeof(slot.name), s->name());
    copyTimingText_(slot.label, sizeof(slot.label), s->label());
  }

  void resetTimingStats_() {
#if BODAQS_TIMING_INSTRUMENTATION
    s_timingStats = SensorTimingStats{};
    for (uint8_t i = 0; i < MAX_SENSORS && i < SensorTimingStats::kMaxSensors; ++i) {
      if (s_list[i]) ++s_timingStats.sensorCount;
      refreshTimingSlot_(i, s_list[i]);
    }
#endif
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

  void appendCsv(String& out, const char* token) {
    if (!token || !*token) return;
    if (out.length()) out += ',';
    out += token;
  }

  static uint16_t countColumns(bool excludeBdqV2NativeStreams = false) {
    uint16_t total = 0;
    for (auto* s : s_list) {
      if (!s || s->muted()) continue;
      if (excludeBdqV2NativeStreams && s->usesBdqV2NativeStream()) continue;
      total += s->columnCount();
    }
    return total;
  }

  bool sensorNeedsAnalogInput_(SensorType t) {
    switch (t) {
      case SensorType::AnalogPot:
      case SensorType::AS5600StringPotAnalog:
        return true;
      case SensorType::AS5600StringPotI2C:
      case SensorType::AS5600AngleI2C:
      case SensorType::AS5048BAngleI2C:
      case SensorType::DANF10NGps:
      case SensorType::Unknown:
      default:
        return false;
    }
  }

  bool sensorHasValidAnalogInput_(const SensorSpec& sp) {
    long ain = -1;
    if (sp.params.getInt("ain", ain)) {
      if (ain >= 0) {
        return ain < (long)board::BOARD_MAX_ANALOG_INPUTS &&
               AnalogInputManager::available((uint8_t)ain);
      }
    }

    long pin = -1;
    return sp.params.getInt("pin", pin) && pin >= 0;
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
  for (uint8_t i = 0; i < MAX_SENSORS; ++i) {
    s_list[i] = nullptr;
    s_loggingStarted[i] = false;
    s_loggingStopped[i] = false;
  }
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

    // --- Resolve analog input ordinal (ain) through the active board profile ---
    if (sensorNeedsAnalogInput_(sp.type)) {
      long ain = -1;
      if (sp.params.getInt("ain", ain) && ain >= 0) {
        if (!board::gBoard) {
          SENS_LOGW("sensor '%s' has ain=%ld but gBoard is null\n", sp.name, ain);
        } else {
          const auto& bp = *board::gBoard;

          if (ain < 0 || ain >= (long)bp.analog.count) {
            SENS_LOGW("sensor '%s': ain=%ld out of range (board analog.count=%u)\n",
                      sp.name, ain, (unsigned)bp.analog.count);
          } else {
            if (!AnalogInputManager::available((uint8_t)ain)) {
              SENS_LOGW("sensor '%s': AIN%ld not available on this board\n",
                        sp.name, ain);
            } else {
              const int pin = AnalogInputManager::pinForAin((uint8_t)ain);
              if (pin >= 0) {
                sp.params.set("pin", String(pin));
                SENS_LOGI("sensor '%s': ain=%ld -> GPIO%d\n", sp.name, ain, pin);
              } else if (AnalogInputManager::inputIsExternal((uint8_t)ain)) {
                SENS_LOGI("sensor '%s': ain=%ld -> external ADC\n", sp.name, ain);
              }
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

    if (sensorNeedsAnalogInput_(sp.type)) {
      if (!sensorHasValidAnalogInput_(sp)) {
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

    // Complex on-device transforms are retired. Keep legacy output_id fields
    // loadable, but force runtime transform selection to identity.
    s->setSelectedTransformId("identity");

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
        else if (omInt == (long)OutputMode::POLY)   mode = OutputMode::LINEAR;
        else if (omInt == (long)OutputMode::LUT)    mode = OutputMode::LINEAR;
      } else if (sp.params.get("output_mode", omStr)) {
        omStr.trim(); omStr.toUpperCase();
        if      (omStr == "RAW"    || omStr == "0") mode = OutputMode::RAW;
        else if (omStr == "LINEAR" || omStr == "1") mode = OutputMode::LINEAR;
        else if (omStr == "POLY"   || omStr == "2") mode = OutputMode::LINEAR;
        else if (omStr == "LUT"    || omStr == "3") mode = OutputMode::LINEAR;
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
      // LINEAR => sensor class default. Units are no longer config-overridable.
      // Legacy POLY/LUT values are normalized to LINEAR above; downstream tools
      // now own complex transform application.
      {
        switch (mode) {
          case OutputMode::RAW: {
            s->setOutputUnitsLabel("counts");
            break;
          }
          case OutputMode::LINEAR: {
            break;
          }
          case OutputMode::POLY:
          case OutputMode::LUT: {
            break;
          }
        }
      }

    }

    // Register with SensorManager (takes ownership, per your contract)
    SensorManager::registerSensor(s);
    SensorManager::noteLiveConfiguration(s, sp);

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

void noteLiveConfiguration(Sensor* sensor, const SensorSpec& spec) {
  for (int i = 0; i < MAX_SENSORS; ++i) {
    if (s_list[i] != sensor) continue;
    s_liveType[i] = spec.type;
    s_liveAssignment[i] = sensorAssignment(spec, board::gBoard);
    s_liveMutedDefault[i] = spec.mutedDefault;
    return;
  }
}

LoggingConfigIssue configurationIssue(const LoggerConfig& cfg, char* error, size_t cap) {
  if (error && cap) error[0] = '\0';
  auto issue = [&](LoggingConfigIssue kind, const char* format, const char* a, const char* b = "") {
    if (error && cap) snprintf(error, cap, format, a, b);
    return kind;
  };
  // Conflicts take priority: rebooting cannot repair duplicate assignments.
  for (uint8_t i = 0; i < cfg.sensorCount(); ++i) {
    SensorSpec current;
    if (!cfg.getSensorSpec(i, current)) continue;
    const auto assignment = sensorAssignment(current, board::gBoard);
    const bool active = configuredActive_(current);
    if (active) {
      if (const char* owner = assignmentOwner(assignment, board::gBoard)) {
        return issue(LoggingConfigIssue::Conflict, "%s shares an I2C address with the %s", current.name, owner);
      }
    }
    String currentId;
    current.params.get("imu_id", currentId);
    if (!currentId.length()) currentId = String(current.name) + "_001";
    for (uint8_t j = 0; j < i; ++j) {
      SensorSpec previous;
      if (!cfg.getSensorSpec(j, previous)) continue;
      if (current.name[0] && strcasecmp(current.name, previous.name) == 0)
        return issue(LoggingConfigIssue::Conflict, "Duplicate sensor name '%s'", current.name);
      if (!active || !configuredActive_(previous)) continue;
      if (assignmentsConflict(assignment, sensorAssignment(previous, board::gBoard))) {
        if (error && cap) {
          if (assignment.kind == SensorAssignment::Kind::I2C)
            snprintf(error, cap, "%s and %s share I2C bus %d address 0x%02X", previous.name, current.name, assignment.bus, assignment.input);
          else snprintf(error, cap, "%s and %s share an input assignment", previous.name, current.name);
        }
        return LoggingConfigIssue::Conflict;
      }
      if (current.type == SensorType::BMI270ImuI2C && previous.type == current.type) {
        String previousId;
        previous.params.get("imu_id", previousId);
        if (!previousId.length()) previousId = String(previous.name) + "_001";
        if (currentId.equalsIgnoreCase(previousId))
          return issue(LoggingConfigIssue::Conflict, "Duplicate imu_id '%s'", currentId.c_str());
      }
    }
  }
  for (uint8_t i = 0; i < cfg.sensorCount(); ++i) {
    SensorSpec current;
    if (!cfg.getSensorSpec(i, current)) continue;
    if (!SensorRegistry::lookup(current.type))
      return issue(LoggingConfigIssue::InvalidConfig, "%s has an unknown sensor type", current.name);
    if (!configuredActive_(current)) continue;
    const auto assignment = sensorAssignment(current, board::gBoard);
    if (assignment.kind == SensorAssignment::Kind::None)
      return issue(LoggingConfigIssue::InvalidConfig, "%s has no valid input assignment", current.name);
    if (current.type == SensorType::BMI270ImuI2C && !BMI270ImuSensor::validateSpec(current, error, cap))
      return LoggingConfigIssue::InvalidConfig;
  }
  for (uint8_t i = 0; i < cfg.sensorCount(); ++i) {
    SensorSpec current;
    if (!cfg.getSensorSpec(i, current) || !configuredActive_(current)) continue;
    const int live = liveIndex_(current);
    if (live < 0 || s_list[live]->muted() ||
        !(s_liveAssignment[live] == sensorAssignment(current, board::gBoard)))
      return issue(LoggingConfigIssue::RestartRequired, "%s differs from the running sensor; restart required", current.name);
    if (s_list[live]->loggingRestartRequired(current, error, cap)) return LoggingConfigIssue::RestartRequired;
  }
  // Removed/type-changed/muted entries can leave a previously active object.
  for (int i = 0; i < MAX_SENSORS; ++i) {
    if (!s_list[i] || s_list[i]->muted()) continue;
    bool retained = false;
    for (uint8_t j = 0; j < cfg.sensorCount(); ++j) {
      SensorSpec current;
      if (cfg.getSensorSpec(j, current) && liveIndex_(current) == i && configuredActive_(current)) { retained = true; break; }
    }
    if (!retained) return issue(LoggingConfigIssue::RestartRequired, "%s is still active; restart required", s_list[i]->name());
  }
  return LoggingConfigIssue::None;
}

bool requiresBdqV2(const LoggerConfig& cfg) {
  uint8_t count = 0;
  for (uint8_t i = 0; i < cfg.sensorCount(); ++i) {
    SensorSpec spec;
    if (!cfg.getSensorSpec(i, spec) || spec.type != SensorType::BMI270ImuI2C || !configuredActive_(spec)) continue;
    if (++count > 1) return true;
    String name = "orientation_200";
    spec.params.get("profile", name);
    const auto* profile = BMI270Profile::find(name.c_str());
    if (profile && profile->accelOdrHz != profile->gyroOdrHz) return true;
  }
  return false;
}

bool validateLoggingStart(
    const LoggerConfig& cfg,
    uint16_t effectiveRateHz,
    char* error,
    size_t errorCapacity) {
  if (error && errorCapacity) error[0] = '\0';
  if (configurationIssue(cfg, error, errorCapacity) != LoggingConfigIssue::None) return false;
  if (requiresBdqV2(cfg) && cfg.logFormat != LogFormat::BodaqsMultiStreamBinary) {
    if (error && errorCapacity) snprintf(error, errorCapacity, "IMU configuration requires BDQ v2 logging");
    return false;
  }

  for (auto* sensor : s_list) {
    if (!sensor || sensor->muted()) continue;
    if (!sensor->prepareLoggingStart(cfg, effectiveRateHz, error, errorCapacity)) return false;
    if (!sensor->validateLoggingStart(cfg, effectiveRateHz, error, errorCapacity)) return false;
  }
  const bool excludeNativeStreams =
      cfg.logFormat == LogFormat::BodaqsMultiStreamBinary;
  const uint16_t columnCount = dynamicColumnCount(excludeNativeStreams);
  if (columnCount > LoggerLimits::kMaxDynamicColumns) {
    if (error && errorCapacity) {
      snprintf(error, errorCapacity,
               "configured sensor columns %u exceed maximum %u",
               (unsigned)columnCount,
               (unsigned)LoggerLimits::kMaxDynamicColumns);
    }
    return false;
  }
  return true;
}

bool onLoggingStart(char* error, size_t errorCapacity) {
#if BODAQS_TIMING_INSTRUMENTATION
  resetTimingStats_();
#endif
  // Live scheduler load also drives the OLED logging policy, so reset it even
  // when the optional detailed timing summaries are compiled out.
  I2CBusScheduler::resetTimingStats();
  if (error && errorCapacity) error[0] = '\0';
  for (uint8_t i = 0; i < MAX_SENSORS; ++i) {
    s_loggingStarted[i] = false;
    s_loggingStopped[i] = false;
  }
  for (uint8_t i = 0; i < MAX_SENSORS; ++i) {
    Sensor* s = s_list[i];
    if (!s || s->muted()) continue;
    // Remember the attempted start so a partially started sensor is stopped
    // on failure. Muted sensors must not probe or acquire at log start.
    s_loggingStarted[i] = true;
    if (!s->startLoggingSession(error, errorCapacity)) {
      onLoggingStop();
      return false;
    }
  }
  I2CBusScheduler::start();
  return true;
}

void onLoggingStop() {
  I2CBusScheduler::stop();
  for (uint8_t i = 0; i < MAX_SENSORS; ++i) {
    if (!s_loggingStarted[i] || s_loggingStopped[i]) continue;
    if (s_list[i]) s_list[i]->onLoggingStop();
    s_loggingStopped[i] = true;
  }
}

void onLoggingFinalized() {
  for (uint8_t i = 0; i < MAX_SENSORS; ++i) {
    if (s_loggingStarted[i] && s_list[i]) s_list[i]->onLoggingFinalized();
    s_loggingStarted[i] = false;
    s_loggingStopped[i] = false;
  }
}

size_t pendingLoggingRows() {
  size_t pending = 0;
  for (auto* sensor : s_list) {
    if (!sensor || sensor->muted()) continue;
    const size_t sensorPending = sensor->pendingLoggingRows();
    if (sensorPending > pending) pending = sensorPending;
  }
  return pending;
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

bool gpsStatus(SensorGpsStatus& out) {
  out = SensorGpsStatus{};
  bool found = false;
  SensorGpsStatus best;
  best.state = SensorGpsState::Error;

  for (auto* s : s_list) {
    if (!s) continue;

    SensorGpsStatus candidate;
    if (!s->gpsStatus(candidate)) continue;

    found = true;
    if (candidate.state == SensorGpsState::Fixed) {
      out = candidate;
      return true;
    }
    if (candidate.state == SensorGpsState::Acquiring && best.state != SensorGpsState::Acquiring) {
      best = candidate;
    } else if (best.state == SensorGpsState::Error) {
      best = candidate;
    }
  }

  if (found) out = best;
  return found;
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

uint16_t dynamicColumnCount(bool excludeBdqV2NativeStreams) {
  return countColumns(excludeBdqV2NativeStreams);
}

uint16_t synchronousMaxSampleRateHz() {
  uint16_t cap = 0;
  for (auto* s : s_list) {
    if (!s || s->muted()) continue;
    if (s->sampleMode() != SensorSampleMode::Synchronous) continue;

    const uint16_t sensorCap = s->maxSampleRateHz();
    if (sensorCap == 0) continue;
    if (cap == 0 || sensorCap < cap) cap = sensorCap;
  }
  return cap;
}

void buildHeader(char* out, size_t n, bool humanTs) {
  if (!out || n == 0) return;
  buildHeaderString(humanTs).toCharArray(out, n);
}

String buildHeaderString(bool humanTs) {
  String out;
  out.reserve(128 + (countColumns() * 32));

  appendCsv(out, humanTs ? "timestamp" : "timestamp_ms");

  for (auto* s : s_list) {
    if (!s || s->muted()) continue;
    const uint8_t cols = s->columnCount();
    for (uint8_t i = 0; i < cols; ++i) {
      char nameBuf[96] = {0};
      s->getColumnName(i, nameBuf, sizeof(nameBuf));

      if (!nameBuf[0]) {
        char fb[32];
        snprintf(fb, sizeof(fb), "col%u", (unsigned)i);
        appendCsv(out, fb);
      } else {
        appendCsv(out, nameBuf);
      }
    }
  }

  appendCsv(out, "mark");
  return out;
}

void sampleValues(
    float* out,
    uint16_t cap,
    uint16_t& written,
    bool excludeBdqV2NativeStreams) {
    written = 0;
    if (!out || cap == 0) return;
    AnalogInputManager::beginSample();
    //
    // 2. Write all sensor columns as before
    //
    for (uint8_t sensorIndex = 0; sensorIndex < MAX_SENSORS; ++sensorIndex) {
        auto* s = s_list[sensorIndex];
        if (!s || s->muted()) continue;
        if (excludeBdqV2NativeStreams && s->usesBdqV2NativeStream()) continue;

        const uint8_t need = s->columnCount();
        if (!need) continue;

        const uint16_t room = (written < cap) ? (cap - written) : 0;
        if (!room) break;

        const uint8_t toWrite = (need <= room) ? need : (uint8_t)room;
#if BODAQS_TIMING_INSTRUMENTATION
        if (sensorIndex < SensorTimingStats::kMaxSensors) {
          auto& slot = s_timingStats.sensor[sensorIndex];
          if (!slot.present) refreshTimingSlot_(sensorIndex, s);
          slot.muted = s->muted();
          slot.columnCount = need;
        }
        const uint32_t sensorT0 = micros();
#endif
        s->sampleValues(out + written, toWrite);
#if BODAQS_TIMING_INSTRUMENTATION
        if (sensorIndex < SensorTimingStats::kMaxSensors) {
          TimingStats_record(s_timingStats.sensor[sensorIndex].sampleUs,
                             (uint32_t)(micros() - sensorT0));
        }
#endif
        written += toWrite;

        if (toWrite < need) break;
    }
    AnalogInputManager::endSample();
}

void resetTimingStats() {
  resetTimingStats_();
}

const SensorTimingStats& timingStats() {
  return s_timingStats;
}

uint16_t readSuspensionPreview(PreviewMode mode, PreviewValue* out, uint16_t maxOut) {
  uint16_t total = 0;
  uint16_t written = 0;

  AnalogInputManager::beginSample();

  for (auto* s : s_list) {
    if (!s || s->muted()) continue;

    SensorColumnDescriptor desc;
    if (!s->describeColumn(0, desc)) continue;
    if (strcasecmp(desc.domain, "suspension") != 0) continue;

    float value = 0.0f;
    char unit[24] = {0};
    if (mode == PreviewMode::Raw) {
      if (!s->readPreviewValue(OutputMode::RAW, value, unit, sizeof(unit))) continue;
    } else if (mode == PreviewMode::Linear) {
      if (!s->readPreviewValue(OutputMode::LINEAR, value, unit, sizeof(unit))) continue;
    } else if (mode == PreviewMode::SagPercent) {
      const float range = s->installedRange();
      if (!(range > 0.0f)) continue;
      if (!s->readPreviewValue(OutputMode::LINEAR, value, unit, sizeof(unit))) continue;
      value = (value / range) * 100.0f;
      snprintf(unit, sizeof(unit), "%%");
    } else {
      continue;
    }

    if (out && written < maxOut) {
      PreviewValue& row = out[written];
      row = PreviewValue{};
      const char* name = desc.sensorName[0] ? desc.sensorName : s->name();
      snprintf(row.sensorName, sizeof(row.sensorName), "%s", name ? name : "");
      snprintf(row.unit, sizeof(row.unit), "%s", unit);
      row.value = value;
      ++written;
    }

    ++total;
  }

  AnalogInputManager::endSample();
  return total;
}

uint16_t describeSensorColumns(
    SensorColumnDescriptor* out,
    uint16_t maxOut,
    bool excludeBdqV2NativeStreams) {
  uint16_t total = 0;
  uint16_t written = 0;

  for (auto* s : s_list) {
    if (!s || s->muted()) continue;
    if (excludeBdqV2NativeStreams && s->usesBdqV2NativeStream()) continue;

    const uint8_t cols = s->columnCount();
    for (uint8_t i = 0; i < cols; ++i) {
      SensorColumnDescriptor desc;
      if (!s->describeColumn(i, desc)) continue;

      if (out && written < maxOut) {
        out[written] = desc;
        ++written;
      }
      ++total;
    }
  }

  return total;
}

bool describeSensorColumnAt(
    uint16_t columnIndex,
    SensorColumnDescriptor& out,
    bool excludeBdqV2NativeStreams) {
  uint16_t logicalIndex = 0;

  for (auto* s : s_list) {
    if (!s || s->muted()) continue;
    if (excludeBdqV2NativeStreams && s->usesBdqV2NativeStream()) continue;

    const uint8_t cols = s->columnCount();
    for (uint8_t i = 0; i < cols; ++i) {
      SensorColumnDescriptor desc;
      if (!s->describeColumn(i, desc)) continue;

      if (logicalIndex == columnIndex) {
        out = desc;
        return true;
      }
      ++logicalIndex;
    }
  }

  return false;
}

uint16_t describeSensors(SensorMetadataDescriptor* out, uint16_t maxOut) {
  uint16_t total = 0;
  uint16_t written = 0;

  for (auto* s : s_list) {
    if (!s || s->muted()) continue;

    SensorMetadataDescriptor desc;
    if (!s->describeSensorMetadata(desc)) continue;

    if (out && written < maxOut) {
      out[written] = desc;
      ++written;
    }
    ++total;
  }

  return total;
}

bool describeSensorAt(uint16_t sensorIndex, SensorMetadataDescriptor& out) {
  uint16_t logicalIndex = 0;

  for (auto* s : s_list) {
    if (!s || s->muted()) continue;

    SensorMetadataDescriptor desc;
    if (!s->describeSensorMetadata(desc)) continue;
    if (logicalIndex == sensorIndex) {
      out = desc;
      return true;
    }
    ++logicalIndex;
  }

  return false;
}

bool describeRuntimeDiagnosticsAt(uint8_t sensorIndex, SensorRuntimeDiagnostics& out) {
  out = SensorRuntimeDiagnostics{};
  Sensor* sensor = get(sensorIndex);
  return sensor && sensor->describeRuntimeDiagnostics(out);
}

uint16_t describeBdqV2Streams(
    BdqV2StreamDescriptor* out,
    uint16_t maxOut,
    uint16_t firstStreamId) {
  if (firstStreamId == 0) return 0;
  uint16_t total = 0;
  uint16_t written = 0;
  uint32_t nextStreamId = firstStreamId;

  for (auto* sensor : s_list) {
    if (!sensor || sensor->muted() || nextStreamId > UINT16_MAX) continue;
    BdqV2StreamDescriptor descriptor;
    if (!sensor->describeBdqV2Stream(
            static_cast<uint16_t>(nextStreamId), descriptor)) {
      continue;
    }
    if (out && written < maxOut) out[written++] = descriptor;
    ++total;
    ++nextStreamId;
  }
  return total;
}

uint16_t describeSensorColumnRawFlags(bool* out, uint16_t maxOut) {
  uint16_t total = 0;
  uint16_t written = 0;

  for (auto* s : s_list) {
    if (!s || s->muted()) continue;

    const uint8_t cols = s->columnCount();
    for (uint8_t i = 0; i < cols; ++i) {
      SensorColumnDescriptor desc;
      if (!s->describeColumn(i, desc)) continue;

      if (out && written < maxOut) {
        out[written] = desc.raw;
        ++written;
      }
      ++total;
    }
  }

  return total;
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

void debugDumpColumnMetadata(const char* tag) {
  SM_LOGI("%s: sensor column metadata\n", tag ? tag : "metadata");

  uint16_t logicalIndex = 0;
  for (auto* s : s_list) {
    if (!s || s->muted()) continue;

    const uint8_t cols = s->columnCount();
    for (uint8_t i = 0; i < cols; ++i) {
      SensorColumnDescriptor d;
      if (!s->describeColumn(i, d)) continue;

      LOGI("  col=%u sensor='%s' header='%s' id='%s' end='%s' domain='%s' quantity='%s' unit='%s' source='%s' transform='%s' notes='%s'\n",
           (unsigned)logicalIndex,
           d.sensorName,
           d.csvHeader,
           d.columnId,
           d.end,
           d.domain,
           d.quantity,
           d.unit,
           d.source,
           d.transformChain,
           d.notes);
      ++logicalIndex;
    }
  }
}

} // namespace SensorManager


