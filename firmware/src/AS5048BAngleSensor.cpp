#include "AS5048BAngleSensor.h"

#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <string.h>

#include "ConfigManager.h"
#include "I2CManager.h"
#include "SensorRegistry.h"
#include "DebugLog.h"

#define AS5048_LOGI(...) LOGI_TAG("AS5048", __VA_ARGS__)
#define AS5048_LOGW(...) LOGW_TAG("AS5048", __VA_ARGS__)

namespace {

static constexpr uint8_t kDefaultAddress = 0x40;
static constexpr uint8_t kAgcReg = 0xFA;
static constexpr uint8_t kDiagnosticReg = 0xFB;
static constexpr uint8_t kMagnitudeMsbReg = 0xFC;
static constexpr uint8_t kAngleMsbReg = 0xFE;
static constexpr uint16_t kCountsPerTurn = 16384;
static constexpr uint16_t kHalfTurn = kCountsPerTurn / 2;
static constexpr float kDegreesPerCount = 360.0f / float(kCountsPerTurn);
static constexpr uint32_t kDefaultDiagnosticIntervalMs = 250;

void copyField_(char* dst, size_t cap, const char* src) {
  if (!dst || cap == 0) return;
  if (!src) src = "";
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

void writeColumnLabel_(const char* name, const char* units, char* out, size_t cap) {
  if (!out || cap < 2) return;
  out[0] = '\0';

  String s = name ? String(name) : String();
  if (units && units[0]) {
    s += " [";
    s += units;
    s += "]";
  }
  s.toCharArray(out, cap);
}

uint16_t decode14_(uint8_t msb, uint8_t lsb) {
  return (uint16_t(msb) << 6) | (lsb & 0x3Fu);
}

uint16_t decode14Swapped_(uint8_t lsb, uint8_t msb) {
  return (uint16_t(msb) << 6) | (lsb & 0x3Fu);
}

// Datasheet-style random reads use repeated-start and return MSB,LSB.
// Keep STOP-then-read as a fallback, but decode the observed byte order.
uint16_t decode14ForReadMode_(AS5048BAngleSensor::I2CReadMode mode,
                              uint8_t first,
                              uint8_t second) {
  return (mode == AS5048BAngleSensor::I2CReadMode::StopThenRead)
    ? decode14Swapped_(first, second)
    : decode14_(first, second);
}

AS5048BAngleSensor::I2CReadMode parseReadMode_(const String& value) {
  String s = value;
  s.trim();
  s.toLowerCase();
  s.replace("-", "_");

  if (s == "repeated" || s == "repeated_start" || s == "restart" || s == "rs" || s == "1") {
    return AS5048BAngleSensor::I2CReadMode::RepeatedStart;
  }
  return AS5048BAngleSensor::I2CReadMode::StopThenRead;
}

uint32_t busHz_(uint8_t busIndex) {
  const board::I2CProfile* profile = I2CManager::profile(busIndex);
  return (profile && profile->hz) ? profile->hz : 100000UL;
}

void loadParamsFromPack_(AS5048BAngleSensor::Params& p,
                         const char* instanceName,
                         const ParamPack& params) {
  p.name = instanceName ? instanceName : "as5048b";

  long li = 0;
  bool b = false;
  String s;

  if (params.getInt("i2c_bus", li))       p.busIndex = (li < 0) ? 0u : (uint8_t)li;
  if (params.getInt("i2c_addr", li))      p.i2cAddr = (li <= 0) ? kDefaultAddress : (uint8_t)li;
  if (params.get("i2c_read_mode", s))     p.readMode = parseReadMode_(s);
  if (params.getInt("zero_count", li))    p.zeroCount = (int32_t)li;
  if (params.getBool("include_raw", b))   p.includeRawColumn = b;
  if (params.getBool("include_diag", b))  p.includeDiagColumns = b;
  if (params.getInt("diag_interval_ms", li)) p.diagnosticIntervalMs = (li < 0) ? 0UL : (uint32_t)li;
  if (params.get("units_label", s))       s.toCharArray(p.unitsLabel, sizeof(p.unitsLabel));
  if (params.get("end", s))               s.toCharArray(p.semanticEnd, sizeof(p.semanticEnd));
  if (params.get("primary_domain", s))    s.toCharArray(p.primaryDomain, sizeof(p.primaryDomain));
  if (params.get("primary_quantity", s))  s.toCharArray(p.primaryQuantity, sizeof(p.primaryQuantity));
}

} // namespace

AS5048BAngleSensor::AS5048BAngleSensor(const Params& p) {
  applyParams(p);
}

void AS5048BAngleSensor::applyParams(const Params& p) {
  if (p.name && p.name[0]) {
    strncpy(m_name, p.name, sizeof(m_name) - 1);
    m_name[sizeof(m_name) - 1] = '\0';
  }

  m_busIndex = p.busIndex;
  m_i2cAddr = p.i2cAddr ? p.i2cAddr : kDefaultAddress;
  m_readMode = p.readMode;
  m_zeroCount = normalizeCount_(p.zeroCount);
  m_includeRaw = p.includeRawColumn;
  m_includeDiagColumns = p.includeDiagColumns;
  m_diagnosticIntervalMs = p.diagnosticIntervalMs;

  copyField_(m_unitsLabel, sizeof(m_unitsLabel), p.unitsLabel[0] ? p.unitsLabel : "deg");
  Sensor::setOutputUnitsLabel(m_unitsLabel);
  copyField_(m_semanticEnd, sizeof(m_semanticEnd), p.semanticEnd);
  copyField_(m_primaryDomain, sizeof(m_primaryDomain), p.primaryDomain);
  copyField_(m_primaryQuantity, sizeof(m_primaryQuantity), p.primaryQuantity);
  copyField_(m_rawDomain, sizeof(m_rawDomain), p.primaryDomain);
}

void AS5048BAngleSensor::begin() {
  m_wire = I2CManager::bus(m_busIndex);
  m_warnedNoBus = false;
  m_warnedRead = false;
  m_warnedDiagnostics = false;
  m_warnedDiagnosticRead = false;
  m_warnedFailureProbe = false;
  m_nextReadAttemptMs = 0;
  m_nextDiagnosticReadMs = 0;
  m_haveLastGoodRaw = false;
  m_haveDiagnostics = false;
  m_lastGoodRaw = 0;
  m_lastDiagnostic = 0;
  m_lastAgc = 0;
  m_lastMagnitude = 0;
  m_diagnosticReadFailures = 0;
  m_calUnwrapInit = false;
  m_calLastUnwrapped = 0;

  if (!m_wire) {
    AS5048_LOGW("sensor '%s': I2C bus %u unavailable\n",
                name(), (unsigned)m_busIndex);
    return;
  }

  if (!probe_()) {
    AS5048_LOGW("sensor '%s': no AS5048B response at 0x%02X on bus %u\n",
                name(), (unsigned)m_i2cAddr, (unsigned)m_busIndex);
    return;
  }

  uint16_t raw = 0;
  if (readRawAngle_(raw)) {
    refreshDiagnostics_(true);
    AS5048_LOGI("sensor '%s': ready at 0x%02X bus%u raw=%u diag=0x%02X agc=%u mag=%u zero=%ld bus_hz=%lu read_mode=%s\n",
                name(),
                (unsigned)m_i2cAddr,
                (unsigned)m_busIndex,
                (unsigned)raw,
                (unsigned)m_lastDiagnostic,
                (unsigned)m_lastAgc,
                (unsigned)m_lastMagnitude,
                (long)m_zeroCount,
                (unsigned long)busHz_(m_busIndex),
                (m_readMode == I2CReadMode::RepeatedStart) ? "repeated" : "stop");
  }
}

bool AS5048BAngleSensor::reconfigureFromSpec(const SensorSpec& spec) {
  if (spec.type != SensorType::AS5048BAngleI2C) return false;

  Params p;
  loadParamsFromPack_(p, spec.name, spec.params);
  applyParams(p);
  begin();
  return true;
}

bool AS5048BAngleSensor::probe_() const {
  if (!m_wire) return false;
  if (!I2CManager::lock(m_wire)) return false;
  m_wire->beginTransmission(m_i2cAddr);
  const bool ok = (m_wire->endTransmission(true) == 0);
  I2CManager::unlock(m_wire);
  return ok;
}

bool AS5048BAngleSensor::readRegBytesLocked_(uint8_t reg, uint8_t* out, uint8_t len) const {
  if (!m_wire || !out || len == 0) return false;

  m_wire->beginTransmission(m_i2cAddr);
  m_wire->write(reg);
  const bool stopAfterRegister = (m_readMode == I2CReadMode::StopThenRead);
  if (m_wire->endTransmission(stopAfterRegister) != 0) {
    return false;
  }
  if (stopAfterRegister) delayMicroseconds(5);

  const size_t got = m_wire->requestFrom((int)m_i2cAddr, (int)len);
  if (got != len) {
    while (m_wire->available() > 0) {
      (void)m_wire->read();
    }
    return false;
  }

  for (uint8_t i = 0; i < len; ++i) {
    const int v = m_wire->read();
    if (v < 0) return false;
    out[i] = (uint8_t)v;
  }
  return true;
}

bool AS5048BAngleSensor::readOutputBlock_(OutputSample& out) const {
  out = OutputSample{};
  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) return false;
  if (!I2CManager::lock(m_wire)) return false;
  uint8_t bytes[2] = {0, 0};
  const bool ok = readRegBytesLocked_(kAngleMsbReg, bytes, sizeof(bytes));
  I2CManager::unlock(m_wire);
  if (!ok) return false;

  const uint8_t angleMsb = bytes[0];
  const uint8_t angleLsb = bytes[1];
  out.angle = decode14ForReadMode_(m_readMode, angleMsb, angleLsb);
  return true;
}

bool AS5048BAngleSensor::readDiagnostics_(OutputSample& out) const {
  out.agc = 0;
  out.diagnostic = 0;
  out.magnitude = 0;

  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) return false;
  if (!I2CManager::lock(m_wire)) return false;

  uint8_t agc = 0;
  uint8_t diagnostic = 0;
  uint8_t magnitudeBytes[2] = {0, 0};
  const bool ok =
    readRegBytesLocked_(kAgcReg, &agc, 1) &&
    readRegBytesLocked_(kDiagnosticReg, &diagnostic, 1) &&
    readRegBytesLocked_(kMagnitudeMsbReg, magnitudeBytes, sizeof(magnitudeBytes));
  I2CManager::unlock(m_wire);
  if (!ok) return false;

  out.agc = agc;
  out.diagnostic = diagnostic;
  out.magnitude = decode14ForReadMode_(m_readMode, magnitudeBytes[0], magnitudeBytes[1]);
  return true;
}

bool AS5048BAngleSensor::refreshDiagnostics_(bool force) const {
  const uint32_t now = millis();
  if (!force && m_diagnosticIntervalMs > 0 &&
      m_nextDiagnosticReadMs != 0 &&
      (int32_t)(now - m_nextDiagnosticReadMs) < 0) {
    return m_haveDiagnostics;
  }

  OutputSample diagnosticSample;
  if (!readDiagnostics_(diagnosticSample)) {
    ++m_diagnosticReadFailures;
    if (!m_warnedDiagnosticRead) {
      AS5048_LOGW("sensor '%s': diagnostic read failed at 0x%02X on bus %u\n",
                  name(), (unsigned)m_i2cAddr, (unsigned)m_busIndex);
      m_warnedDiagnosticRead = true;
    }
    m_nextDiagnosticReadMs = now + (m_diagnosticIntervalMs ? m_diagnosticIntervalMs : kDefaultDiagnosticIntervalMs);
    return false;
  }

  m_lastAgc = diagnosticSample.agc;
  m_lastDiagnostic = diagnosticSample.diagnostic;
  m_lastMagnitude = diagnosticSample.magnitude;
  m_haveDiagnostics = true;
  m_warnedDiagnosticRead = false;
  m_nextDiagnosticReadMs = now + m_diagnosticIntervalMs;
  maybeWarnDiagnostics_();
  return true;
}

void AS5048BAngleSensor::maybeWarnDiagnostics_() const {
  if (!m_haveDiagnostics) return;

  const bool ocfReady = (m_lastDiagnostic & 0x01u) != 0;
  const bool cordicOverflow = (m_lastDiagnostic & 0x02u) != 0;
  const bool magneticHigh = (m_lastDiagnostic & 0x04u) != 0;
  const bool magneticLow = (m_lastDiagnostic & 0x08u) != 0;
  const bool agcSaturated = (m_lastAgc == 0u || m_lastAgc == 255u);
  const bool bad = !ocfReady || cordicOverflow || magneticHigh || magneticLow || agcSaturated;

  if (!bad) {
    m_warnedDiagnostics = false;
    return;
  }
  if (m_warnedDiagnostics) return;

  AS5048_LOGW("sensor '%s': diag=0x%02X agc=%u mag=%u flags:%s%s%s%s%s\n",
              name(),
              (unsigned)m_lastDiagnostic,
              (unsigned)m_lastAgc,
              (unsigned)m_lastMagnitude,
              ocfReady ? "" : " OCF_NOT_READY",
              cordicOverflow ? " COF" : "",
              magneticHigh ? " MAG_HIGH" : "",
              magneticLow ? " MAG_LOW" : "",
              agcSaturated ? " AGC_SAT" : "");
  m_warnedDiagnostics = true;
}

void AS5048BAngleSensor::logFailureProbe_() const {
  if (m_warnedFailureProbe) return;
  m_warnedFailureProbe = true;

  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) return;

  if (!I2CManager::lock(m_wire, 20)) {
    AS5048_LOGW("sensor '%s': failure probe could not lock I2C bus %u\n",
                name(), (unsigned)m_busIndex);
    return;
  }

  uint8_t ping[4] = {255, 255, 255, 255};
  for (uint8_t i = 0; i < 4; ++i) {
    const uint8_t addr = uint8_t(0x40u + i);
    m_wire->beginTransmission(addr);
    ping[i] = (uint8_t)m_wire->endTransmission(true);
  }

  uint8_t tx = 255;
  uint8_t got = 0;
  uint8_t b0 = 0;
  uint8_t b1 = 0;
  m_wire->beginTransmission(m_i2cAddr);
  m_wire->write(kAngleMsbReg);
  tx = (uint8_t)m_wire->endTransmission(true);
  if (tx == 0) {
    delayMicroseconds(5);
    got = (uint8_t)m_wire->requestFrom((int)m_i2cAddr, 2);
    if (m_wire->available() > 0) b0 = (uint8_t)m_wire->read();
    if (m_wire->available() > 0) b1 = (uint8_t)m_wire->read();
    while (m_wire->available() > 0) {
      (void)m_wire->read();
    }
  }

  I2CManager::unlock(m_wire);

  const uint16_t raw = decode14ForReadMode_(m_readMode, b0, b1);
  AS5048_LOGW("sensor '%s': failure probe bus%u addr=0x%02X bus_hz=%lu mode=%s "
              "candidates 0x40=%u 0x41=%u 0x42=%u 0x43=%u "
              "stop2{tx=%u got=%u bytes=%02X %02X raw=%u}\n",
              name(),
              (unsigned)m_busIndex,
              (unsigned)m_i2cAddr,
              (unsigned long)busHz_(m_busIndex),
              (m_readMode == I2CReadMode::RepeatedStart) ? "repeated" : "stop",
              (unsigned)ping[0],
              (unsigned)ping[1],
              (unsigned)ping[2],
              (unsigned)ping[3],
              (unsigned)tx,
              (unsigned)got,
              (unsigned)b0,
              (unsigned)b1,
              (unsigned)raw);
}

bool AS5048BAngleSensor::readRawAngle_(uint16_t& out) const {
  OutputSample sample;
  if (!readOutputBlock_(sample)) return false;

  out = sample.angle;
  m_lastGoodRaw = int(sample.angle);
  m_haveLastGoodRaw = true;
  m_warnedRead = false;
  m_nextReadAttemptMs = 0;
  refreshDiagnostics_(false);
  return true;
}

int AS5048BAngleSensor::readRawAngleOnce_() const {
  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) {
    if (!m_warnedNoBus) {
      AS5048_LOGW("sensor '%s': skipping read, I2C bus %u unavailable\n",
                  name(), (unsigned)m_busIndex);
      m_warnedNoBus = true;
    }
    return m_haveLastGoodRaw ? m_lastGoodRaw : 0;
  }

  const uint32_t now = millis();
  if (m_nextReadAttemptMs != 0 &&
      (int32_t)(now - m_nextReadAttemptMs) < 0) {
    return m_haveLastGoodRaw ? m_lastGoodRaw : 0;
  }

  uint16_t raw = 0;
  if (readRawAngle_(raw)) return int(raw);

  if (!m_warnedRead) {
    AS5048_LOGW("sensor '%s': read failed at 0x%02X on bus %u bus_hz=%lu mode=%s; reusing last good sample\n",
                name(),
                (unsigned)m_i2cAddr,
                (unsigned)m_busIndex,
                (unsigned long)busHz_(m_busIndex),
                (m_readMode == I2CReadMode::RepeatedStart) ? "repeated" : "stop");
    m_warnedRead = true;
    logFailureProbe_();
  }
  m_nextReadAttemptMs = now + (m_haveLastGoodRaw ? 250UL : 1000UL);
  return m_haveLastGoodRaw ? m_lastGoodRaw : 0;
}

int32_t AS5048BAngleSensor::normalizeCount_(int32_t count) {
  count %= (int32_t)kCountsPerTurn;
  if (count < 0) count += kCountsPerTurn;
  return count;
}

int32_t AS5048BAngleSensor::signedDeltaCounts_(int32_t raw, int32_t zero) {
  int32_t delta = normalizeCount_(raw) - normalizeCount_(zero);
  delta = normalizeCount_(delta + kHalfTurn) - kHalfTurn;
  return delta;
}

int32_t AS5048BAngleSensor::calibrationCountsFromRaw_(int raw) const {
  raw = (int)normalizeCount_(raw);
  if (!m_calUnwrapInit) {
    m_calUnwrapInit = true;
    m_calLastUnwrapped = raw;
    return m_calLastUnwrapped;
  }

  m_calLastUnwrapped += signedDeltaCounts_(raw, normalizeCount_(m_calLastUnwrapped));
  return m_calLastUnwrapped;
}

float AS5048BAngleSensor::degreesFromRaw_(int raw) const {
  return float(signedDeltaCounts_(raw, m_zeroCount)) * kDegreesPerCount;
}

void AS5048BAngleSensor::sample(float& primaryOut, int& rawOut) const {
  rawOut = readRawAngleOnce_();
  const float deg = degreesFromRaw_(rawOut);

  switch (m_mode) {
    case OutputMode::RAW:
      primaryOut = float(rawOut);
      break;
    case OutputMode::POLY:
    case OutputMode::LUT:
      primaryOut = applyTransform(deg);
      break;
    case OutputMode::LINEAR:
    default:
      primaryOut = deg;
      break;
  }
}

uint8_t AS5048BAngleSensor::columnCount() const {
  uint8_t count = (m_includeRaw && m_mode != OutputMode::RAW) ? 2 : 1;
  if (m_includeDiagColumns) count += 3;
  return count;
}

void AS5048BAngleSensor::getColumnName(uint8_t idx, char* out, size_t cap) const {
  if (!out || cap < 2) return;
  out[0] = '\0';

  if (idx == 0) {
    if (m_mode == OutputMode::RAW) {
      String s = String(name()) + " [counts]";
      s.toCharArray(out, cap);
    } else {
      writeColumnLabel_(name(), m_outputUnitsLabel, out, cap);
    }
    return;
  }

  if (idx == 1 && m_includeRaw && m_mode != OutputMode::RAW) {
    String s = String(name()) + "_raw [counts]";
    s.toCharArray(out, cap);
    return;
  }

  const uint8_t diagStart = (m_includeRaw && m_mode != OutputMode::RAW) ? 2 : 1;
  if (m_includeDiagColumns && idx >= diagStart && idx < diagStart + 3) {
    String s = String(name());
    switch (idx - diagStart) {
      case 0: s += "_agc [counts]"; break;
      case 1: s += "_diag [flags]"; break;
      case 2: s += "_mag [counts]"; break;
      default: break;
    }
    s.toCharArray(out, cap);
  }
}

void AS5048BAngleSensor::sampleValues(float* out, uint8_t max) {
  if (!out || max == 0 || m_muted) return;

  float primary = 0.0f;
  int raw = 0;
  sample(primary, raw);

  uint8_t w = 0;
  out[w++] = primary;
  if (m_includeRaw && m_mode != OutputMode::RAW && w < max) {
    out[w++] = float(raw);
  }
  if (m_includeDiagColumns && w < max) {
    refreshDiagnostics_(false);
    out[w++] = m_haveDiagnostics ? float(m_lastAgc) : NAN;
  }
  if (m_includeDiagColumns && w < max) {
    out[w++] = m_haveDiagnostics ? float(m_lastDiagnostic) : NAN;
  }
  if (m_includeDiagColumns && w < max) {
    out[w++] = m_haveDiagnostics ? float(m_lastMagnitude) : NAN;
  }
}

bool AS5048BAngleSensor::describeColumn(uint8_t idx, SensorColumnDescriptor& out) const {
  if (idx >= columnCount()) return false;
  if (!Sensor::describeColumn(idx, out)) return false;

  const bool hasRawColumn = (m_includeRaw && m_mode != OutputMode::RAW);
  const uint8_t diagStart = hasRawColumn ? 2 : 1;
  const bool diagColumn = m_includeDiagColumns && idx >= diagStart && idx < diagStart + 3;
  if (diagColumn) {
    copyField_(out.sensorName, sizeof(out.sensorName), name());
    out.outputMode = OutputMode::RAW;
    out.required = false;
    out.primary = false;
    out.raw = true;
    out.calibrated = false;
    out.transformed = false;
    copyField_(out.end, sizeof(out.end), m_semanticEnd);
    copyField_(out.domain, sizeof(out.domain), m_primaryDomain);
    copyField_(out.source, sizeof(out.source), "as5048_diagnostic");

    switch (idx - diagStart) {
      case 0:
        copyField_(out.quantity, sizeof(out.quantity), "agc");
        copyField_(out.unit, sizeof(out.unit), "counts");
        break;
      case 1:
        copyField_(out.quantity, sizeof(out.quantity), "diag");
        copyField_(out.unit, sizeof(out.unit), "flags");
        break;
      case 2:
        copyField_(out.quantity, sizeof(out.quantity), "mag");
        copyField_(out.unit, sizeof(out.unit), "counts");
        break;
      default:
        break;
    }

    snprintf(out.columnId, sizeof(out.columnId), "%s_%s", name(), out.quantity);
    copyField_(out.notes, sizeof(out.notes), "AS5048B diagnostic readout");
    return true;
  }

  const bool rawColumn = (m_mode == OutputMode::RAW && idx == 0) ||
                         (hasRawColumn && idx == 1);

  copyField_(out.sensorName, sizeof(out.sensorName), name());
  out.outputMode = m_mode;
  out.required = true;
  out.primary = (idx == 0);
  out.raw = rawColumn;
  out.calibrated = !rawColumn;
  out.transformed = (idx == 0 && (m_mode == OutputMode::POLY || m_mode == OutputMode::LUT));

  copyField_(out.end, sizeof(out.end), m_semanticEnd);
  copyField_(out.domain, sizeof(out.domain), rawColumn ? m_rawDomain : m_primaryDomain);
  if (!out.domain[0]) copyField_(out.domain, sizeof(out.domain), m_primaryDomain);

  if (rawColumn) {
    copyField_(out.quantity, sizeof(out.quantity), "raw");
    copyField_(out.unit, sizeof(out.unit), "counts");
    copyField_(out.source, sizeof(out.source), "absolute_angle_counts");
    out.calibrated = false;
  } else {
    copyField_(out.quantity, sizeof(out.quantity), m_primaryQuantity);
    copyField_(out.unit, sizeof(out.unit), m_outputUnitsLabel);
    copyField_(out.source, sizeof(out.source), out.transformed ? "transformed" : "zeroed_angle");
    copyField_(out.calibrationId, sizeof(out.calibrationId), "zero_offset");
  }

  if (out.transformed && selectedTransformId().length()) {
    selectedTransformId().toCharArray(out.transformChain, sizeof(out.transformChain));
  }

  if (out.end[0] && out.domain[0] && out.quantity[0]) {
    snprintf(out.columnId, sizeof(out.columnId), "%s_%s_%s",
             out.end, out.domain, out.quantity);
  } else if (out.quantity[0]) {
    snprintf(out.columnId, sizeof(out.columnId), "%s_%s", name(), out.quantity);
  }

  if (!out.quantity[0]) {
    copyField_(out.notes, sizeof(out.notes), "missing semantic quantity");
  } else if (!out.end[0] || !out.domain[0]) {
    copyField_(out.notes, sizeof(out.notes), "partial semantic metadata");
  } else {
    out.notes[0] = '\0';
  }

  return true;
}

bool AS5048BAngleSensor::describeSensorMetadata(SensorMetadataDescriptor& out) const {
  out = SensorMetadataDescriptor{};
  copyField_(out.sensorId, sizeof(out.sensorId), name());
  copyField_(out.name, sizeof(out.name), name());
  copyField_(out.type, sizeof(out.type), "as5048b_angle_i2c");
  copyField_(out.domain, sizeof(out.domain), m_primaryDomain);
  copyField_(out.rawUnit, sizeof(out.rawUnit), "counts");
  copyField_(out.calibrationType, sizeof(out.calibrationType), "zero_offset");
  copyField_(out.calibrationInputUnit, sizeof(out.calibrationInputUnit), "counts");
  copyField_(out.calibrationOutputUnit, sizeof(out.calibrationOutputUnit), m_outputUnitsLabel);
  out.installedZeroCount = m_zeroCount;
  out.sensorZeroCount = 0;
  out.sensorFullCount = kCountsPerTurn - 1;
  out.sensorFullTravel = 360.0f;
  out.invert = false;
  out.hasCalibration = true;
  out.hasTracking = false;
  out.countsPerTurn = kCountsPerTurn;
  out.wrapThresholdCounts = kHalfTurn;
  out.assumeTurn0AtStart = false;
  return true;
}

OutputConfig AS5048BAngleSensor::outputConfig() const {
  return OutputConfig{m_mode, m_includeRaw};
}

void AS5048BAngleSensor::setOutputConfig(const OutputConfig& cfg) {
  setOutputMode(cfg.primary);
  setIncludeRaw(cfg.includeRaw);
}

bool AS5048BAngleSensor::beginCalibration(CalMode mode) {
  if (mode != CalMode::ZERO) return false;
  cal_ = CalState{};
  cal_.mode = mode;
  cal_.phase = CalPhase::ACTIVE;
  cal_.started_ms = millis();
  m_calUnwrapInit = false;
  m_calLastUnwrapped = 0;
  return true;
}

bool AS5048BAngleSensor::updateCalibration(int32_t latestCounts) {
  if (cal_.phase != CalPhase::ACTIVE || cal_.mode != CalMode::ZERO) return false;
  ++cal_.samples;
  cal_.first_counts = normalizeCount_(latestCounts);
  return true;
}

bool AS5048BAngleSensor::finishCalibration(bool persist) {
  if (cal_.phase != CalPhase::ACTIVE) return false;

  if (cal_.mode == CalMode::ZERO) {
    const bool haveZero = (cal_.first_counts != INT32_MAX);
    m_zeroCount = normalizeCount_(haveZero ? cal_.first_counts : currentRawCounts());
    if (persist) {
      ConfigManager::saveSensorParamByName(name(), "zero_count", String(m_zeroCount));
    }
  } else {
    cal_.phase = CalPhase::COMPLETE;
    cal_.mode = CalMode::NONE;
    return false;
  }

  cal_.phase = CalPhase::COMPLETE;
  cal_.mode = CalMode::NONE;
  return true;
}

int32_t AS5048BAngleSensor::currentRawCounts() const {
  const int raw = readRawAngleOnce_();
  if (cal_.phase == CalPhase::ACTIVE && cal_.mode == CalMode::ZERO) {
    return calibrationCountsFromRaw_(raw);
  }
  return raw;
}

CalibrationState AS5048BAngleSensor::calibration() const {
  CalibrationState cs;
  cs.mode = m_mode;
  if (m_mode != OutputMode::RAW) {
    cs.scale = kDegreesPerCount;
    cs.offset = -float(m_zeroCount) * kDegreesPerCount;
  }
  return cs;
}

bool AS5048BAngleSensor::setCalibration(const CalibrationState& s) {
  (void)s;
  return false;
}

void AS5048BAngleSensor::setIncludeRaw(bool b) {
  m_includeRaw = b;
}

void AS5048BAngleSensor::setOutputUnitsLabel(const char* u) {
  Sensor::setOutputUnitsLabel((u && u[0]) ? u : "deg");
}

const ParamDef* AS5048BAngleSensor::paramDefs(size_t& count) {
  static const ParamDef defs[] = {
    {"i2c_bus",          ParamType::Enum,   "0",   nullptr, nullptr, "0,1", "I2C bus index"},
    {"i2c_addr",         ParamType::Int,    "64",  "1",     "127",   nullptr, "I2C address in decimal (default 64 = 0x40)"},
    {"i2c_read_mode",    ParamType::Enum,   "repeated", nullptr, nullptr, "repeated,stop", "I2C register read transaction style; repeated is the AS5048B datasheet path"},
    {"zero_count",       ParamType::Int,    "0",   "0",     "16383", nullptr, "Firmware zero point in raw AS5048B counts"},
    {"output_mode",      ParamType::Enum,   "1",   nullptr, nullptr, nullptr, "Output method: RAW counts, LINEAR degrees, or transformed degrees"},
    {"include_raw",      ParamType::Bool,   "true", nullptr, nullptr, nullptr, "Append raw absolute angle counts after primary"},
    {"include_diag",     ParamType::Bool,   "false", nullptr, nullptr, nullptr, "Append AS5048B AGC, diagnostic flags, and magnitude columns"},
    {"diag_interval_ms", ParamType::Int,    "250", "0",     "5000", nullptr, "Minimum interval between AS5048B diagnostic reads"},
    {"units_label",      ParamType::String, "deg", nullptr, nullptr, nullptr, "Units suffix for angular output"},
    {"end",              ParamType::Enum,   "",    nullptr, nullptr, "front,rear", "Optional semantic end for log metadata"},
    {"primary_domain",   ParamType::Enum,   "",    nullptr, nullptr, "wheel,suspension,brake,drivetrain,frame,steering", "Optional semantic domain for primary output"},
    {"primary_quantity", ParamType::Enum,   "ang_disp", nullptr, nullptr, "disp,ang_disp,force,pressure,temp,voltage,norm", "Optional semantic quantity for primary output"},
  };

  count = sizeof(defs) / sizeof(defs[0]);
  return defs;
}

Sensor* AS5048BAngleSensor::create(const char* instanceName, const ParamPack& params, bool mutedDefault) {
  Params p;
  loadParamsFromPack_(p, instanceName, params);

  auto* obj = new AS5048BAngleSensor(p);
  obj->setMuted(mutedDefault);
  return obj;
}

static bool _reg_as5048b_angle_i2c =
  SensorRegistry::registerType(
    SensorType::AS5048BAngleI2C,
    "as5048b_angle_i2c",
    "AS5048B Angle (I2C)",
    &AS5048BAngleSensor::paramDefs,
    &AS5048BAngleSensor::create,
    CAL_ZERO
  );
