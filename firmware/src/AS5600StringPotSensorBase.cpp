#include "AS5600StringPotSensorBase.h"

#include <Arduino.h>
#include <math.h>
#include <string.h>

#include "ConfigManager.h"

AS5600StringPotSensorBase::AS5600StringPotSensorBase(const BaseParams& p) {
  applyBaseParams(p);
}

void AS5600StringPotSensorBase::applyBaseParams(const BaseParams& p) {
  if (p.name && p.name[0]) {
    strncpy(m_name, p.name, sizeof(m_name) - 1);
    m_name[sizeof(m_name) - 1] = '\0';
  }

  m_invert = p.invert;
  m_alpha = fmaxf(0.0f, fminf(1.0f, float(p.emaAlphaPermille) / 1000.0f));
  m_deadband = p.deadbandCounts;
  m_countsPerTurn = (p.countsPerTurn >= 2) ? p.countsPerTurn : 4096;

  uint16_t defaultThreshold = uint16_t(m_countsPerTurn / 2);
  if (defaultThreshold == 0) defaultThreshold = 1;
  m_wrapThreshold = p.wrapThresholdCounts ? p.wrapThresholdCounts : defaultThreshold;
  if (m_wrapThreshold >= m_countsPerTurn) m_wrapThreshold = defaultThreshold;

  sensor_zero_count_ = p.sensorZeroCount;
  sensor_full_count_ = p.sensorFullCount;
  installed_zero_count_ = p.installedZeroCount;
  sensor_full_travel_mm_ = p.sensorFullTravelMm;
  m_assumeTurn0AtStart = p.assumeTurn0AtStart;
  m_includeRaw = p.includeRawColumn;

  if (p.unitsLabel[0]) {
    strncpy(m_unitsLabel, p.unitsLabel, sizeof(m_unitsLabel) - 1);
    m_unitsLabel[sizeof(m_unitsLabel) - 1] = '\0';
  } else {
    strcpy(m_unitsLabel, "mm");
  }
  setOutputUnitsLabel(m_unitsLabel);
  recomputeScale();
  resetTrackingState(m_assumeTurn0AtStart);
}

void AS5600StringPotSensorBase::resetTrackingState(bool assumeTurnZero) {
  m_trackingInit = false;
  m_lastWrappedRaw = 0;
  m_turnIndex = assumeTurnZero ? 0 : 0;
  m_lastUnwrappedRaw = 0;
  m_emaInit = false;
  m_ema = 0.0f;
}

void AS5600StringPotSensorBase::recomputeScale() {
  const int32_t span = sensor_full_count_ - sensor_zero_count_;
  const int32_t spanAbs = (span >= 0) ? span : -span;
  if (sensor_full_travel_mm_ > 0.0f && spanAbs != 0) {
    counts_per_mm_ = double(spanAbs) / double(sensor_full_travel_mm_);
  } else {
    counts_per_mm_ = 0.0;
  }
}

void AS5600StringPotSensorBase::onLoggingStart() {
  resetTrackingState(m_assumeTurn0AtStart);
}

void AS5600StringPotSensorBase::onLoggingStop() {
}

int AS5600StringPotSensorBase::normalizeWrapped_(int wrapped) const {
  const int turn = (m_countsPerTurn > 0) ? int(m_countsPerTurn) : 1;
  int out = wrapped % turn;
  if (out < 0) out += turn;
  return out;
}

int32_t AS5600StringPotSensorBase::initialUnwrappedFromWrapped_(int wrapped) const {
  wrapped = normalizeWrapped_(wrapped);

  if (!m_assumeTurn0AtStart) {
    return int32_t(wrapped);
  }

  const int32_t turn = (m_countsPerTurn > 0) ? int32_t(m_countsPerTurn) : 1;
  const int32_t zeroPhase = int32_t(normalizeWrapped_(int(installed_zero_count_)));
  int32_t relative = int32_t(wrapped) - zeroPhase;
  if (relative < 0) relative += turn;

  const int32_t zeroBase = installed_zero_count_ - zeroPhase;
  return zeroBase + relative;
}

int32_t AS5600StringPotSensorBase::updateUnwrappedFromWrapped_(int wrapped) const {
  wrapped = normalizeWrapped_(wrapped);
  if (!m_trackingInit) {
    m_trackingInit = true;
    m_lastWrappedRaw = wrapped;
    m_lastUnwrappedRaw = initialUnwrappedFromWrapped_(wrapped);
    const int32_t turn = (m_countsPerTurn > 0) ? int32_t(m_countsPerTurn) : 1;
    m_turnIndex = (m_lastUnwrappedRaw - int32_t(wrapped)) / turn;
    return m_lastUnwrappedRaw;
  }

  const int delta = wrapped - m_lastWrappedRaw;
  if (delta <= -int(m_wrapThreshold)) {
    ++m_turnIndex;
  } else if (delta >= int(m_wrapThreshold)) {
    --m_turnIndex;
  }

  m_lastWrappedRaw = wrapped;
  m_lastUnwrappedRaw = (m_turnIndex * int32_t(m_countsPerTurn)) + int32_t(wrapped);
  return m_lastUnwrappedRaw;
}

int32_t AS5600StringPotSensorBase::updateUnwrappedEma_(int32_t raw) const {
  if (!m_emaInit) {
    m_ema = float(raw);
    m_emaInit = true;
    return raw;
  }

  if (fabsf(m_ema - float(raw)) < float(m_deadband)) {
    return int32_t(lroundf(m_ema));
  }

  m_ema = m_alpha * float(raw) + (1.0f - m_alpha) * m_ema;
  return int32_t(lroundf(m_ema));
}

AS5600StringPotSensorBase::SampleState AS5600StringPotSensorBase::captureSample_() const {
  SampleState s;
  s.wrappedRaw = normalizeWrapped_(readWrappedCountsOnce());
  s.unwrappedRaw = updateUnwrappedFromWrapped_(s.wrappedRaw);
  s.unwrappedSmoothed = updateUnwrappedEma_(s.unwrappedRaw);
  return s;
}

float AS5600StringPotSensorBase::countsToMm_(int32_t counts) const {
  if (counts_per_mm_ <= 0.0) return 0.0f;
  double mm = (double(counts) - double(installed_zero_count_)) / counts_per_mm_;
  if (m_invert) mm = -mm;
  return float(mm);
}

bool AS5600StringPotSensorBase::rawColumnEnabled_() const {
  return (m_mode == OutputMode::RAW) ? true : m_includeRaw;
}

uint8_t AS5600StringPotSensorBase::columnCount() const {
  return rawColumnEnabled_() ? 2 : 1;
}

void AS5600StringPotSensorBase::getColumnName(uint8_t idx, char* out, size_t cap) const {
  if (!out || cap < 2) return;
  out[0] = '\0';

  if (m_mode == OutputMode::RAW) {
    if (idx == 0) {
      String s = String(name()) + "_raw [counts]";
      s.toCharArray(out, cap);
    } else if (idx == 1) {
      String s = String(name()) + " [mm]";
      s.toCharArray(out, cap);
    }
    return;
  }

  if (idx == 0) {
    const char* units = (m_outputUnitsLabel[0] ? m_outputUnitsLabel : "mm");
    String s = String(name()) + " [" + units + "]";
    s.toCharArray(out, cap);
    return;
  }

  if (idx == 1 && m_includeRaw) {
    String s = String(name()) + "_raw [counts]";
    s.toCharArray(out, cap);
  }
}

void AS5600StringPotSensorBase::sampleValues(float* out, uint8_t max) {
  if (!out || max == 0 || m_muted) return;

  const SampleState sample = captureSample_();
  const float linearMm = countsToMm_(sample.unwrappedSmoothed);
  float primary = 0.0f;

  switch (m_mode) {
    case OutputMode::RAW:
      primary = float(sample.wrappedRaw);
      break;
    case OutputMode::LINEAR:
      primary = linearMm;
      break;
    case OutputMode::POLY:
    case OutputMode::LUT:
      primary = applyTransform(linearMm);
      break;
    default:
      primary = linearMm;
      break;
  }

  uint8_t w = 0;
  out[w++] = primary;
  if (w < max && rawColumnEnabled_()) {
    const float secondary = (m_mode == OutputMode::RAW) ? linearMm : float(sample.wrappedRaw);
    out[w++] = secondary;
  }
}

OutputConfig AS5600StringPotSensorBase::outputConfig() const {
  return OutputConfig{m_mode, m_includeRaw};
}

void AS5600StringPotSensorBase::setOutputConfig(const OutputConfig& cfg) {
  setOutputMode(cfg.primary);
  setIncludeRaw(cfg.includeRaw);
}

OutputMode AS5600StringPotSensorBase::outputMode() const {
  return m_mode;
}

void AS5600StringPotSensorBase::setOutputMode(OutputMode m) {
  m_mode = m;
}

bool AS5600StringPotSensorBase::beginCalibration(CalMode mode) {
  if (mode == CalMode::NONE) return false;
  cal_ = CalState{};
  cal_.mode = mode;
  cal_.phase = CalPhase::ACTIVE;
  cal_.started_ms = millis();
  resetTrackingState(m_assumeTurn0AtStart);
  return true;
}

bool AS5600StringPotSensorBase::updateCalibration(int32_t latestCounts) {
  if (cal_.phase != CalPhase::ACTIVE) return false;
  ++cal_.samples;

  if (cal_.mode == CalMode::ZERO) {
    cal_.first_counts = latestCounts;
  } else if (cal_.mode == CalMode::RANGE) {
    if (cal_.samples == 1) {
      cal_.first_counts = latestCounts;
    } else if (cal_.samples == 2) {
      cal_.second_counts = latestCounts;
    }
  }
  return true;
}

bool AS5600StringPotSensorBase::finishCalibration(bool persist) {
  if (cal_.phase != CalPhase::ACTIVE) return false;

  if (cal_.mode == CalMode::ZERO) {
    const bool haveZero = (cal_.first_counts != INT32_MAX);
    installed_zero_count_ = haveZero ? cal_.first_counts : currentRawCounts();
    if (persist) {
      const char* sname = name();
      ConfigManager::saveSensorParamByName(sname, "installed_zero_count", String(installed_zero_count_));
    }
  } else if (cal_.mode == CalMode::RANGE) {
    const bool haveFirst = (cal_.first_counts != INT32_MAX);
    const bool haveSecond = (cal_.second_counts != INT32_MIN);
    if (!haveFirst || !haveSecond || cal_.first_counts == cal_.second_counts) {
      cal_.phase = CalPhase::COMPLETE;
      cal_.mode = CalMode::NONE;
      return false;
    }

    sensor_zero_count_ = cal_.first_counts;
    sensor_full_count_ = cal_.second_counts;
    m_invert = (sensor_full_count_ < sensor_zero_count_);
    recomputeScale();

    if (persist) {
      const char* sname = name();
      ConfigManager::saveSensorParamByName(sname, "sensor_zero_count", String(sensor_zero_count_));
      ConfigManager::saveSensorParamByName(sname, "sensor_full_count", String(sensor_full_count_));
      ConfigManager::saveSensorParamByName(sname, "invert", m_invert ? "true" : "false");
    }
  }

  cal_.phase = CalPhase::COMPLETE;
  cal_.mode = CalMode::NONE;
  return true;
}

int32_t AS5600StringPotSensorBase::currentRawCounts() const {
  return captureSample_().unwrappedRaw;
}

CalibrationState AS5600StringPotSensorBase::calibration() const {
  CalibrationState cs;
  cs.mode = m_mode;
  if (m_mode == OutputMode::LINEAR && counts_per_mm_ > 0.0) {
    const float gain = (m_invert ? -1.0f : 1.0f) / float(counts_per_mm_);
    cs.scale = gain;
    cs.offset = -float(installed_zero_count_) * gain;
  }
  return cs;
}

bool AS5600StringPotSensorBase::setCalibration(const CalibrationState& s) {
  (void)s;
  return false;
}

SmoothingConfig AS5600StringPotSensorBase::smoothing() const {
  SmoothingConfig sc;
  sc.emaAlpha = m_alpha;
  sc.deadband = float(m_deadband);
  sc.emaWarmStart = true;
  return sc;
}

void AS5600StringPotSensorBase::setSmoothing(const SmoothingConfig& s) {
  float a = s.emaAlpha;
  if (a < 0.0f) a = 0.0f;
  if (a > 1.0f) a = 1.0f;
  m_alpha = a;
  m_deadband = (s.deadband < 0.0f) ? 0u : uint16_t(lroundf(s.deadband));
  if (m_alpha >= 0.9999f) m_emaInit = false;
}

void AS5600StringPotSensorBase::setIncludeRaw(bool b) {
  m_includeRaw = b;
}

void AS5600StringPotSensorBase::setOutputUnitsLabel(const char* u) {
  if (!u) u = "";
  strncpy(m_unitsLabel, u, sizeof(m_unitsLabel) - 1);
  m_unitsLabel[sizeof(m_unitsLabel) - 1] = '\0';
  strncpy(m_outputUnitsLabel, u, sizeof(m_outputUnitsLabel) - 1);
  m_outputUnitsLabel[sizeof(m_outputUnitsLabel) - 1] = '\0';
}
