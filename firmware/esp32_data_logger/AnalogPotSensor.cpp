#include "AnalogPotSensor.h"
#include <Arduino.h>
#include <math.h>
#include <string.h>

#include "SensorRegistry.h"
#include "Calibration.h"
#include "ConfigManager.h"
//#include "OutputTransforms.h"

// ---------- Ctors ----------
AnalogPotSensor::AnalogPotSensor(const Params& p)
: AnalogPotSensor(p.name ? p.name : "pot", p) {}

AnalogPotSensor::AnalogPotSensor(const char* nm, const Params& p) {
  if (nm && nm[0]) {
    strncpy(m_name, nm, sizeof(m_name)-1);
    m_name[sizeof(m_name)-1] = '\0';
  }
  applyParams(p);
}

void AnalogPotSensor::begin() {
  pinMode(m_pin, INPUT);
  m_emaInit = false;
}

// Satisfy vtable: we don't apply anything from LoggerConfig yet for this sensor
void AnalogPotSensor::applyConfig(const LoggerConfig&) {
  // no-op for now
}

// Convert user Params -> internal state
void AnalogPotSensor::applyParams(const Params& p) {
  if (p.name && p.name[0]) {
    strncpy(m_name, p.name, sizeof(m_name)-1);
    m_name[sizeof(m_name)-1] = '\0';
  }

  // wiring / polarity
  m_pin    = p.pin;
  m_invert = p.invert;

  // smoothing
  m_alpha    = fmaxf(0.0f, fminf(1.0f, float(p.emaAlphaPermille) / 1000.0f));
  m_deadband = p.deadbandCounts;
  m_emaInit  = false;

  // geometry
  m_zero   = p.sensorZeroCount;
  m_full   = p.sensorFullCount;
  m_fullMm = p.sensorFullTravelMm;
  installed_zero_count_ = p.installedZeroCount;

  long spanCounts = long(m_full) - long(m_zero);
  long spanAbs    = abs(spanCounts);
  if (m_fullMm > 0.0f && spanCounts != 0) {
    spanCounts = m_full - m_zero;
    spanAbs = abs(spanCounts);
    counts_per_mm_ = double(spanAbs) / double(m_fullMm);   // counts per 1 mm along sensor axis
  } else {
    counts_per_mm_ = 0.0;  // invalid; sampling will output a safe 0
  }
 
  // output policy
  m_includeRaw = p.includeRawColumn;

  // units label (legacy LINEAR label for CSV header; transform label comes from base Sensor)
  if (p.unitsLabel[0]) {
    strncpy(m_unitsLabel, p.unitsLabel, sizeof(m_unitsLabel)-1);
    m_unitsLabel[sizeof(m_unitsLabel)-1] = '\0';
  } else {
    m_unitsLabel[0] = '\0';
  }
}

// ---------- RAW helpers ----------
int AnalogPotSensor::readOnce() const {
  int raw = analogRead(m_pin);
  return raw;
}

int AnalogPotSensor::updateEma(int raw) {
  if (!m_emaInit) {
    m_ema = float(raw);
    m_emaInit = true;
    return int(lroundf(m_ema));
  }
  if (fabsf(m_ema - float(raw)) < float(m_deadband)) {
    return int(lroundf(m_ema));
  }
  m_ema = m_alpha * float(raw) + (1.0f - m_alpha) * m_ema;
  return int(lroundf(m_ema));
}

// ---------- Sampling ----------
static inline float lin_from_counts(int x, int zero, float invSpan, float fullMm) {
  if (invSpan == 0.0f) return 0.0f;
  const float norm = (float(x) - float(zero)) * invSpan; // 0..1 range across [zero..full]
  const float scale = (fullMm > 0.0f) ? fullMm : 1.0f;   // 1.0 => normalized; >1 => real units
  return norm * scale;
}

void AnalogPotSensor::sample(float& selectedOut, int& smoothedRawOut) {
  if (m_muted) { selectedOut = 0.0f; smoothedRawOut = 0; return; }

  // 1) read & smooth (as you already do)
  const int raw      = readOnce();
  const int smoothed = updateEma(raw);
  smoothedRawOut     = smoothed;

  // 2) RAW path
  if (m_mode == OutputMode::RAW) {
    selectedOut = float(smoothed);
    return;
  }

  // 3) Non-RAW: counts -> mm on sensor axis
  const double k = counts_per_mm_;                 // precomputed in applyParams
  if (k <= 0.0) {                                 // invalid bench scale -> safe zero
    selectedOut = 0.0f;
    return;
  }
  double x_mm_sensor = (double(smoothed) - double(installed_zero_count_)) / k;
  // Apply polarity in real-units space. This preserves raw ADC counts.
  if (m_invert) x_mm_sensor = -x_mm_sensor;

  // 4) Output by mode
  switch (m_mode) {
    case OutputMode::LINEAR:
      // linear = just the sensor-axis mm (no transform)
      selectedOut = float(x_mm_sensor);
      break;

    case OutputMode::POLY:
    case OutputMode::LUT:
      // transforms now expect real mm input; no pre-clamp
      selectedOut = applyTransform(float(x_mm_sensor));  // already in transform.meta.outUnits
      break;

    default:
      // should not happen; fall back to linear
      selectedOut = float(x_mm_sensor);
      break;
  }
}


// ---------- Output policy ----------
OutputConfig AnalogPotSensor::outputConfig() const {
  OutputConfig oc;
  oc.primary    = m_mode;       // RAW or LINEAR
  oc.includeRaw = m_includeRaw;
  return oc;
}

void AnalogPotSensor::setOutputConfig(const OutputConfig& cfg) {
  setOutputMode(cfg.primary);
  m_includeRaw = cfg.includeRaw;
}

OutputMode AnalogPotSensor::outputMode() const {
  return m_mode;
}

void AnalogPotSensor::setOutputMode(OutputMode m) {
  // Treat anything that isn't RAW as "non-RAW" (i.e., use the transform path).
  m_mode = m;
}


// ---------- Smoothing ----------
SmoothingConfig AnalogPotSensor::smoothing() const {
  SmoothingConfig sc;
  sc.emaAlpha     = m_alpha;
  sc.deadband     = float(m_deadband);
  sc.emaWarmStart = true;
  return sc;
}

void AnalogPotSensor::setSmoothing(const SmoothingConfig& s) {
  float a = s.emaAlpha;
  if (a < 0.0f) a = 0.0f;
  if (a > 1.0f) a = 1.0f;
  m_alpha    = a;
  m_deadband = (s.deadband < 0.0f) ? 0u : uint16_t(lroundf(s.deadband));
  if (m_alpha >= 0.9999f) m_emaInit = false; // next sample seeds EMA
}

// ---------- Calibration ----------
bool AnalogPotSensor::setCalibration(const CalibrationState& state) {
  (void)state;   // unused, satisfies interface
  return false;  // or true if you prefer "accepted but ignored"
}


bool AnalogPotSensor::beginCalibration(CalMode mode) {
  if (mode == CalMode::NONE) return false;

  cal_ = CalState{}; // reset everything
  cal_.mode  = mode;
  cal_.phase = CalPhase::ACTIVE;
  cal_.started_ms = millis();
  return true;
}

bool AnalogPotSensor::updateCalibration(int32_t latestCounts) {
  if (cal_.phase != CalPhase::ACTIVE) return false;

  ++cal_.samples;

  if (cal_.mode == CalMode::RANGE) {
    // RANGE is a 2-point capture with LABELLED endpoints:
    //  - 1st sample: zero-travel endpoint
    //  - 2nd sample: full-travel endpoint
    if (cal_.samples == 1) {
      cal_.min_counts = latestCounts;   // labelled "zero travel"
    } else if (cal_.samples == 2) {
      cal_.max_counts = latestCounts;   // labelled "full travel"
    } else {
      // Ignore any extra samples in RANGE mode to preserve labels.
      // (If you later want "sweep" calibration, do it explicitly and store both labels separately.)
    }
  }

  return true;
}

bool AnalogPotSensor::finishCalibration(bool persist) {
  if (cal_.phase != CalPhase::ACTIVE) return false;

  if (cal_.mode == CalMode::ZERO) {
    const int32_t now = currentRawCounts();
    installed_zero_count_ = now;

    if (persist) {
      const char* sname = this->name();
      ConfigManager::saveSensorParamByName(sname, "installed_zero_count", String(installed_zero_count_));
    }
  } else if (cal_.mode == CalMode::RANGE) {
    const bool haveMin = (cal_.min_counts != INT32_MAX);
    const bool haveMax = (cal_.max_counts != INT32_MIN);
    if (!haveMin || !haveMax || cal_.max_counts == cal_.min_counts) {
      cal_.phase = CalPhase::COMPLETE;
      cal_.mode  = CalMode::NONE;
      return false;
    }
    sensor_zero_count_ = cal_.min_counts;
    sensor_full_count_ = cal_.max_counts;

    // Default invert comes from labelled endpoints:
    // zero-travel captured first (sensor_zero_count_), full-travel captured second (sensor_full_count_).
    // If full < zero, counts decrease with increasing travel => invert mapping.
    const bool autoInvert = (sensor_full_count_ < sensor_zero_count_);
    m_invert = autoInvert;   // apply immediately at runtime

    // keep legacy mirrors in sync
    m_zero   = sensor_zero_count_;
    m_full   = sensor_full_count_;
    // m_fullMm already mirrors sensor_full_travel_mm_ in applyParams (verify if needed)

    long spanCounts = long(m_full) - long(m_zero);
    long spanAbs    = abs(spanCounts);
    if (m_fullMm > 0.0f && spanCounts != 0) {
      spanCounts = m_full - m_zero;
      spanAbs = abs(spanCounts);
      counts_per_mm_ = double(spanAbs) / double(m_fullMm);   // counts per 1 mm along sensor axis
    } else {
      counts_per_mm_ = 0.0;  // invalid; sampling will output a safe 0
    }

    if (persist) {
      const char* sname = this->name();
      ConfigManager::saveSensorParamByName(sname, "sensor_zero_count", String(sensor_zero_count_));
      ConfigManager::saveSensorParamByName(sname, "sensor_full_count", String(sensor_full_count_));
      ConfigManager::saveSensorParamByName(sname, "invert", autoInvert ? "true" : "false");

    }
  }

  // Recompute linear scale if you still call this, or update counts_per_mm_ inline
  // applyLinearScalePrecompute();  // (or replace with your new derivation)

  cal_.phase = CalPhase::COMPLETE;
  cal_.mode  = CalMode::NONE;
  return true;
}


// Present linear mapping via legacy fields
CalibrationState AnalogPotSensor::calibration() const {
  CalibrationState cs;
  cs.mode = m_mode; // RAW or LINEAR

  if (m_mode == OutputMode::LINEAR && m_invSpan != 0.0f) {
    // counts -> units: y = scale*(x - zero)
    const float scale = (m_fullMm > 0.0f) ? (m_fullMm * m_invSpan) : (1.0f * m_invSpan);
    cs.offset = -float(m_zero) * scale;
    cs.scale  = scale;
  } else {
    cs.offset = 0.0f;
    cs.scale  = 1.0f;
  }
  return cs;
}

uint8_t AnalogPotSensor::columnCount() const {
  // Primary output + optional raw counts column
  return m_includeRaw ? 2 : 1;
}

void AnalogPotSensor::getColumnName(uint8_t col, char* out, size_t cap) const {
  if (!out || cap < 2) return;
  out[0] = '\0';

  if (col == 0) {
    // Primary column per mode
    switch (m_mode) {
      case OutputMode::RAW: {
        String s = String(name()) + " [counts]";
        s.toCharArray(out, cap);
        return;
      }
      case OutputMode::LINEAR: {
        String s = String(name()) + " [mm]";             // sensor-axis mm
        s.toCharArray(out, cap);
        return;
      }
      case OutputMode::POLY:
      case OutputMode::LUT: {
        // If you can access the selected transform’s outUnits, use them; else default to [mm]
        const char* outUnits = "mm";
        // (Optional) replace outUnits with transform.meta.outUnits if you have it here.
        String s = String(name()) + " [" + outUnits + "]";
        s.toCharArray(out, cap);
        return;
      }
      default: break;
    }
  }

  // Optional second column: raw counts if you support include_raw
  if (col == 1 && m_includeRaw) {
    String s = String(name()) + "_raw [counts]";
    s.toCharArray(out, cap);
    return;
  }
}



void AnalogPotSensor::sampleValues(float* out, uint8_t max) {
  if (!out || max == 0 || m_muted) return;

  float selected = 0.0f;
  int   counts   = 0;
  sample(selected, counts);                 // <-- uses the pipeline above

  uint8_t w = 0;
  out[w++] = selected;                      // primary column (counts if RAW, units if LINEAR/transform)
  if (m_includeRaw && w < max) out[w++] = float(counts);
}



// ---------- Schema & factory ----------
const ParamDef* AnalogPotSensor::paramDefs(size_t& count) {
  static const ParamDef defs[] = {
    // Wiring
    {"ain",            ParamType::Int,   "-1",   "-1",  "7",   nullptr, "Analog input ordinal (AIN0..). -1=use pin"},
    {"invert",         ParamType::Bool,  "false",nullptr,nullptr,nullptr,"Invert readings (set automatically during range calibration - override not recommended)"},

    // RAW smoothing
    {"ema_alpha",      ParamType::Float, "0.2",  "0",   "1",    nullptr, "EMA alpha [0..1]"},
    {"deadband",       ParamType::Int,   "0",    "0",   "4095", nullptr, "Deadband (counts)"},

    // Anchors / geometry
    {"sensor_zero_count",     ParamType::Int,   "0",    nullptr,nullptr,nullptr,"Counts at sensor 0 position"},
    {"sensor_full_count",     ParamType::Int,   "4095", nullptr,nullptr,nullptr,"Counts at sensor full scale position"},
    {"sensor_full_travel_mm", ParamType::Float, "0",    "0",   nullptr,nullptr, "If 1 => normalized; >1 => mm"},
    {"installed_zero_count", ParamType::Int, "", nullptr, nullptr, nullptr, "Installed zero point (counts)"},

    // Output policy
    {"output_mode", ParamType::Enum,"RAW,LINEAR,POLY,LUT", nullptr,nullptr,nullptr, "Output method: RAW, scaled (LINEAR) or transformed (POLY/LUT)."},
    {"include_raw",    ParamType::Bool,  "false",nullptr,nullptr,nullptr,"Append RAW column after primary"},
    {"units_label",    ParamType::String,"",     nullptr,nullptr,nullptr,"Units suffix for non RAW output (e.g., mm, deg, N, norm)"},

  };

  count = sizeof(defs)/sizeof(defs[0]);
  return defs;
}

Sensor* AnalogPotSensor::create(const char* instanceName, const ParamPack& params, bool mutedDefault) {
  Params p;
  p.name = instanceName ? instanceName : "pot";

  long li; bool b; double d; String s;

  // Wiring / polarity
  if (params.getBool("invert", b))        p.invert = b;
  if (params.getInt("pin", li))           p.pin = (int8_t)li;


  // Smoothing
  if (params.getFloat("ema_alpha", d))   p.emaAlphaPermille = (uint16_t)lround(d * 1000.0);
  if (params.getInt("deadband", li))     p.deadbandCounts   = (uint16_t)li;

  // Anchors / geometry
  if (params.getInt("sensor_zero_count", li))   p.sensorZeroCount        = (int32_t)li;
  if (params.getInt("sensor_full_count", li))   p.sensorFullCount        = (int32_t)li;
  if (params.getFloat("sensor_full_travel_mm", d)) p.sensorFullTravelMm  = (float)d;
  if (params.getInt("installed_zero_count", li)) p.installedZeroCount    = (int32_t)li;


  // Output policy
  if (params.getBool("include_raw", b))  p.includeRawColumn = b;

  // Units label
  if (params.get("units_label", s))      s.toCharArray(p.unitsLabel, sizeof(p.unitsLabel));

  auto* obj = new AnalogPotSensor(p);
  obj->setMuted(mutedDefault);
  return obj;
}

// ---- Auto-register this type ----
static bool _reg_pot =
  SensorRegistry::registerType(
    SensorType::AnalogPot,
    "analog_pot",
    "Analog Potentiometer",
    &AnalogPotSensor::paramDefs,
    &AnalogPotSensor::create,
    /*supportedCalMask*/ (CalModeMask)(CAL_ZERO | CAL_RANGE)
  );

int32_t AnalogPotSensor::currentRawCounts() const {
  return static_cast<int32_t>(readOnce());
}

void AnalogPotSensor::applyLinearScalePrecompute() {
  // Keep legacy geometry fields in sync with the new calibration params.
  m_zero   = sensor_zero_count_;
  m_full   = sensor_full_count_;
  m_fullMm = sensor_full_travel_mm_;

  const int32_t span = (m_full - m_zero);
  if (span != 0) {
    m_invSpan = 1.0f / static_cast<float>(span);
  } else {
    m_invSpan = 0.0f; // avoid divide-by-zero
  }
}

// Normalizes raw counts to 0..1 using precomputed zero/span.
// Assumes m_invSpan == 1.0f / (full_count - m_zero); if you fold invert into m_invSpan,
// this works for both normal and inverted setups. Then we clamp to [0,1].
float AnalogPotSensor::normalize_(int counts) const {
  float x = float(counts - m_zero) * m_invSpan;
  if (m_invert) x = 1.0f - x;
  if (x < 0.0f) x = 0.0f;
  if (x > 1.0f) x = 1.0f;
  return x;
}

// Uses the base-class hook you already have; identity if no transform is attached.
float AnalogPotSensor::applyTransform_(float xNorm) const {
  return applyTransform(xNorm);
}

void AnalogPotSensor::setIncludeRaw(bool b) {
  m_includeRaw = b;
}

void AnalogPotSensor::setOutputUnitsLabel(const char* u) {
  if (!u) u = "";
  // Keep the sensor’s explicit units label for LINEAR/non-RAW
  strncpy(m_unitsLabel, u, sizeof(m_unitsLabel) - 1);
  m_unitsLabel[sizeof(m_unitsLabel) - 1] = 0;

  // Also mirror into the column header label that your CSV/UI uses
  strncpy(m_outputUnitsLabel, u, sizeof(m_outputUnitsLabel) - 1);
  m_outputUnitsLabel[sizeof(m_outputUnitsLabel) - 1] = 0;
}
