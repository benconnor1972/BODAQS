#include "AS5600AngleSensor.h"

#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <string.h>

#include "ConfigManager.h"
#include "I2CManager.h"
#include "SensorRegistry.h"
#include "DebugLog.h"

#define AS5600A_LOGI(...) LOGI_TAG("AS5600", __VA_ARGS__)
#define AS5600A_LOGW(...) LOGW_TAG("AS5600", __VA_ARGS__)

namespace {

static constexpr uint8_t kDefaultAddress = 0x36;
static constexpr uint8_t kZposMsbReg = 0x01;
static constexpr uint8_t kMposMsbReg = 0x03;
static constexpr uint8_t kMangMsbReg = 0x05;
static constexpr uint8_t kConfMsbReg = 0x07;
static constexpr uint8_t kStatusReg = 0x0B;
static constexpr uint8_t kRawAngleMsbReg = 0x0C;
static constexpr uint8_t kAngleMsbReg = 0x0E;
static constexpr uint8_t kAgcReg = 0x1A;
static constexpr uint8_t kMagnitudeMsbReg = 0x1B;
static constexpr uint16_t kCountsPerTurn = 4096;
static constexpr uint16_t kHalfTurn = kCountsPerTurn / 2;
static constexpr float kDegreesPerCount = 360.0f / float(kCountsPerTurn);
static constexpr uint32_t kDefaultDiagnosticIntervalMs = 250;
static constexpr uint32_t kDeviceConfigRetryMs = 2000;
static constexpr int32_t kDirectionMinDeltaCounts = int32_t(kCountsPerTurn / 720); // about 0.5 deg
static constexpr uint8_t kDiagnosticColumnCount = 7;
static constexpr uint16_t kConfSlowFilterMask = 0x0300;
static constexpr uint8_t kConfSlowFilterShift = 8;

static constexpr uint8_t kStatusMagnetTooStrong = 0x08;
static constexpr uint8_t kStatusMagnetTooWeak = 0x10;
static constexpr uint8_t kStatusMagnetDetected = 0x20;

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

AS5600AngleSensor::I2CReadMode parseReadMode_(const String& value) {
  String s = value;
  s.trim();
  s.toLowerCase();
  s.replace("-", "_");

  if (s == "stop" || s == "stop_then_read" || s == "stop_read" || s == "0") {
    return AS5600AngleSensor::I2CReadMode::StopThenRead;
  }
  return AS5600AngleSensor::I2CReadMode::RepeatedStart;
}

int8_t parseDirectionSign_(const String& value) {
  String s = value;
  s.trim();
  s.toLowerCase();
  s.replace("-", "_");

  if (s == "counts_decrease_positive" || s == "decrease_positive" ||
      s == "inverted" || s == "invert" || s == "reverse" || s == "-1" || s == "-") {
    return -1;
  }
  return 1;
}

const char* directionName_(int8_t sign) {
  return (sign < 0) ? "counts_decrease_positive" : "counts_increase_positive";
}

int8_t parseSlowFilterCode_(const String& value) {
  String s = value;
  s.trim();
  s.toLowerCase();
  s.replace("-", "_");
  s.replace(" ", "");

  if (!s.length() || s == "unchanged" || s == "default" || s == "none" || s == "-1") return -1;
  if (s == "16x" || s == "16" || s == "0") return 0;
  if (s == "8x" || s == "8" || s == "1") return 1;
  if (s == "4x" || s == "4" || s == "2") return 2;
  if (s == "2x" || s == "3") return 3;
  return -1;
}

uint32_t busHz_(uint8_t busIndex) {
  const board::I2CProfile* profile = I2CManager::profile(busIndex);
  return (profile && profile->hz) ? profile->hz : 100000UL;
}

void loadParamsFromPack_(AS5600AngleSensor::Params& p,
                         const char* instanceName,
                         const ParamPack& params) {
  p.name = instanceName ? instanceName : "as5600";

  long li = 0;
  bool b = false;
  double d = 0.0;
  String s;

  if (params.getInt("i2c_bus", li))       p.busIndex = (li < 0) ? 0u : (uint8_t)li;
  if (params.getInt("i2c_addr", li))      p.i2cAddr = (li <= 0) ? kDefaultAddress : (uint8_t)li;
  if (params.get("i2c_read_mode", s))     p.readMode = parseReadMode_(s);
  if (params.getInt("zero_count", li))    p.zeroCount = (int32_t)li;
  if (params.get("direction", s))          p.directionSign = parseDirectionSign_(s);
  if (params.getFloat("installed_range", d)) p.installedRange = (float)d;
  if (params.get("slow_filter", s))        p.slowFilterCode = parseSlowFilterCode_(s);
  if (params.getBool("include_raw", b))   p.includeRawColumn = b;
  if (params.getBool("include_angle", b)) p.includeAngleColumn = b;
  if (params.getBool("include_diag", b))  p.includeDiagColumns = b;
  if (params.getInt("diag_interval_ms", li)) p.diagnosticIntervalMs = (li < 0) ? 0UL : (uint32_t)li;
  if (params.get("end", s))               s.toCharArray(p.semanticEnd, sizeof(p.semanticEnd));
  if (params.get("primary_domain", s))    s.toCharArray(p.primaryDomain, sizeof(p.primaryDomain));
  if (params.get("primary_quantity", s))  s.toCharArray(p.primaryQuantity, sizeof(p.primaryQuantity));
}

uint16_t decode12_(uint8_t msb, uint8_t lsb) {
  return (uint16_t(msb & 0x0Fu) << 8) | lsb;
}

uint16_t decode16_(uint8_t msb, uint8_t lsb) {
  return (uint16_t(msb) << 8) | lsb;
}

const char* as5600PowerModeName_(uint8_t v) {
  switch (v & 0x03u) {
    case 0: return "nom";
    case 1: return "lpm1";
    case 2: return "lpm2";
    case 3: return "lpm3";
    default: return "";
  }
}

const char* as5600HysteresisName_(uint8_t v) {
  switch (v & 0x03u) {
    case 0: return "off";
    case 1: return "1_lsb";
    case 2: return "2_lsb";
    case 3: return "3_lsb";
    default: return "";
  }
}

const char* as5600OutputStageName_(uint8_t v) {
  switch (v & 0x03u) {
    case 0: return "analog_full";
    case 1: return "analog_reduced";
    case 2: return "pwm";
    default: return "reserved";
  }
}

const char* as5600PwmFrequencyName_(uint8_t v) {
  switch (v & 0x03u) {
    case 0: return "115hz";
    case 1: return "230hz";
    case 2: return "460hz";
    case 3: return "920hz";
    default: return "";
  }
}

const char* as5600SlowFilterName_(uint8_t v) {
  switch (v & 0x03u) {
    case 0: return "16x";
    case 1: return "8x";
    case 2: return "4x";
    case 3: return "2x";
    default: return "";
  }
}

const char* as5600FastFilterThresholdName_(uint8_t v) {
  switch (v & 0x07u) {
    case 0: return "slow_only";
    case 1: return "6_lsb";
    case 2: return "7_lsb";
    case 3: return "9_lsb";
    case 4: return "18_lsb";
    case 5: return "21_lsb";
    case 6: return "24_lsb";
    case 7: return "10_lsb";
    default: return "";
  }
}

} // namespace

AS5600AngleSensor::AS5600AngleSensor(const Params& p) {
  applyParams(p);
}

void AS5600AngleSensor::applyParams(const Params& p) {
  if (p.name && p.name[0]) {
    strncpy(m_name, p.name, sizeof(m_name) - 1);
    m_name[sizeof(m_name) - 1] = '\0';
  }

  m_busIndex = p.busIndex;
  m_i2cAddr = p.i2cAddr ? p.i2cAddr : kDefaultAddress;
  m_readMode = p.readMode;
  m_zeroCount = normalizeCount_(p.zeroCount);
  m_directionSign = (p.directionSign < 0) ? -1 : 1;
  m_installedRange = p.installedRange;
  m_slowFilterCode = (p.slowFilterCode >= 0 && p.slowFilterCode <= 3) ? p.slowFilterCode : -1;
  m_includeRaw = p.includeRawColumn;
  m_includeAngleColumn = p.includeAngleColumn;
  m_includeDiagColumns = p.includeDiagColumns;
  m_diagnosticIntervalMs = p.diagnosticIntervalMs;

  copyField_(m_unitsLabel, sizeof(m_unitsLabel), "deg");
  Sensor::setOutputUnitsLabel(m_unitsLabel);
  copyField_(m_semanticEnd, sizeof(m_semanticEnd), p.semanticEnd);
  copyField_(m_primaryDomain, sizeof(m_primaryDomain), p.primaryDomain);
  copyField_(m_primaryQuantity, sizeof(m_primaryQuantity), p.primaryQuantity);
  copyField_(m_rawDomain, sizeof(m_rawDomain), p.primaryDomain);
}

void AS5600AngleSensor::begin() {
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
  m_lastStatus = 0;
  m_lastAgc = 0;
  m_lastMagnitude = 0;
  m_lastReadOk = false;
  m_lastReadReused = false;
  m_rawReadFailures = 0;
  m_diagnosticReadFailures = 0;
  m_configWriteAttempted = false;
  m_configWriteOk = false;
  m_nextConfigWriteMs = 0;
  m_deviceConfigReadAttempted = false;
  m_deviceConfigReadOk = false;
  m_nextDeviceConfigReadMs = 0;
  m_configRawAngle = 0;
  m_configAngle = 0;
  m_configZpos = 0;
  m_configMpos = 0;
  m_configMang = 0;
  m_configConf = 0;
  m_configStatus = 0;
  m_configAgc = 0;
  m_configMagnitude = 0;
  m_calUnwrapInit = false;
  m_calLastUnwrapped = 0;

  if (!m_wire) {
    AS5600A_LOGW("sensor '%s': I2C bus %u unavailable\n",
                 name(), (unsigned)m_busIndex);
    return;
  }

  if (!probe_()) {
    AS5600A_LOGW("sensor '%s': no AS5600 response at 0x%02X on bus %u\n",
                 name(), (unsigned)m_i2cAddr, (unsigned)m_busIndex);
    return;
  }

  maybeApplyVolatileConfig_();

  uint16_t raw = 0;
  if (readRawAngle_(raw)) {
    refreshDiagnostics_(true);
    readDeviceConfig_();
    AS5600A_LOGI("sensor '%s': ready at 0x%02X bus%u raw=%u status=0x%02X agc=%u mag=%u zero=%ld direction=%s bus_hz=%lu read_mode=%s\n",
                 name(),
                 (unsigned)m_i2cAddr,
                 (unsigned)m_busIndex,
                 (unsigned)raw,
                 (unsigned)m_lastStatus,
                 (unsigned)m_lastAgc,
                 (unsigned)m_lastMagnitude,
                 (long)m_zeroCount,
                 directionName_(m_directionSign),
                 (unsigned long)busHz_(m_busIndex),
                 (m_readMode == I2CReadMode::RepeatedStart) ? "repeated" : "stop");
  } else {
    readDeviceConfig_();
  }
}

bool AS5600AngleSensor::reconfigureFromSpec(const SensorSpec& spec) {
  if (spec.type != SensorType::AS5600AngleI2C) return false;

  Params p;
  loadParamsFromPack_(p, spec.name, spec.params);
  applyParams(p);
  begin();
  return true;
}

bool AS5600AngleSensor::probe_() const {
  if (!m_wire) return false;
  if (!I2CManager::lock(m_wire)) return false;
  m_wire->beginTransmission(m_i2cAddr);
  const bool ok = (m_wire->endTransmission(true) == 0);
  I2CManager::unlock(m_wire);
  return ok;
}

bool AS5600AngleSensor::readRegBytesLocked_(uint8_t reg, uint8_t* out, uint8_t len) const {
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

bool AS5600AngleSensor::writeRegBytesLocked_(uint8_t reg, const uint8_t* data, uint8_t len) const {
  if (!m_wire || !data || len == 0) return false;

  m_wire->beginTransmission(m_i2cAddr);
  m_wire->write(reg);
  for (uint8_t i = 0; i < len; ++i) {
    m_wire->write(data[i]);
  }
  return m_wire->endTransmission(true) == 0;
}

bool AS5600AngleSensor::readOutputBlock_(OutputSample& out) const {
  out = OutputSample{};
  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) return false;
  if (!I2CManager::lock(m_wire)) return false;

  uint8_t bytes[2] = {0, 0};
  const bool ok = readRegBytesLocked_(kRawAngleMsbReg, bytes, sizeof(bytes));
  I2CManager::unlock(m_wire);
  if (!ok) return false;

  out.angle = decode12_(bytes[0], bytes[1]);
  return true;
}

bool AS5600AngleSensor::readAngleRegister_(uint16_t& out) const {
  out = 0;
  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) return false;
  if (!I2CManager::lock(m_wire)) return false;

  uint8_t bytes[2] = {0, 0};
  const bool ok = readRegBytesLocked_(kAngleMsbReg, bytes, sizeof(bytes));
  I2CManager::unlock(m_wire);
  if (!ok) return false;

  out = decode12_(bytes[0], bytes[1]);
  return true;
}

bool AS5600AngleSensor::readDiagnostics_(OutputSample& out) const {
  out.agc = 0;
  out.status = 0;
  out.magnitude = 0;

  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) return false;
  if (!I2CManager::lock(m_wire)) return false;

  uint8_t status = 0;
  uint8_t agc = 0;
  uint8_t magnitudeBytes[2] = {0, 0};
  const bool ok =
    readRegBytesLocked_(kStatusReg, &status, 1) &&
    readRegBytesLocked_(kAgcReg, &agc, 1) &&
    readRegBytesLocked_(kMagnitudeMsbReg, magnitudeBytes, sizeof(magnitudeBytes));
  I2CManager::unlock(m_wire);
  if (!ok) return false;

  out.status = status;
  out.agc = agc;
  out.magnitude = decode12_(magnitudeBytes[0], magnitudeBytes[1]);
  return true;
}

bool AS5600AngleSensor::applyVolatileConfig_() const {
  m_configWriteAttempted = true;
  m_configWriteOk = false;

  if (m_slowFilterCode < 0) {
    m_configWriteOk = true;
    return true;
  }

  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) {
    m_nextConfigWriteMs = millis() + kDeviceConfigRetryMs;
    return false;
  }
  if (!I2CManager::lock(m_wire)) {
    m_nextConfigWriteMs = millis() + kDeviceConfigRetryMs;
    return false;
  }

  uint8_t confBytes[2] = {0, 0};
  bool ok = readRegBytesLocked_(kConfMsbReg, confBytes, sizeof(confBytes));
  uint16_t oldConf = ok ? decode16_(confBytes[0], confBytes[1]) : 0;
  uint16_t newConf = oldConf;
  if (ok) {
    newConf = (uint16_t)((oldConf & ~kConfSlowFilterMask) |
                         ((uint16_t(m_slowFilterCode) << kConfSlowFilterShift) & kConfSlowFilterMask));
    if (newConf != oldConf) {
      uint8_t outBytes[2] = {
        (uint8_t)((newConf >> 8) & 0xFFu),
        (uint8_t)(newConf & 0xFFu),
      };
      ok = writeRegBytesLocked_(kConfMsbReg, outBytes, sizeof(outBytes));
    }
  }

  I2CManager::unlock(m_wire);

  if (!ok) {
    m_nextConfigWriteMs = millis() + kDeviceConfigRetryMs;
    AS5600A_LOGW("sensor '%s': slow_filter=%s volatile config write failed at 0x%02X on bus %u\n",
                 name(),
                 as5600SlowFilterName_((uint8_t)m_slowFilterCode),
                 (unsigned)m_i2cAddr,
                 (unsigned)m_busIndex);
    return false;
  }

  m_configWriteOk = true;
  m_nextConfigWriteMs = 0;
  m_deviceConfigReadOk = false;
  m_nextDeviceConfigReadMs = 0;
  AS5600A_LOGI("sensor '%s': slow_filter=%s volatile config conf 0x%04X -> 0x%04X\n",
               name(),
               as5600SlowFilterName_((uint8_t)m_slowFilterCode),
               (unsigned)oldConf,
               (unsigned)newConf);
  return true;
}

bool AS5600AngleSensor::maybeApplyVolatileConfig_() const {
  if (m_slowFilterCode < 0) return true;
  if (m_configWriteOk) return true;

  const uint32_t now = millis();
  if (m_nextConfigWriteMs != 0 &&
      (int32_t)(now - m_nextConfigWriteMs) < 0) {
    return false;
  }

  return applyVolatileConfig_();
}

bool AS5600AngleSensor::readDeviceConfig_() const {
  m_deviceConfigReadAttempted = true;
  m_deviceConfigReadOk = false;

  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) {
    m_nextDeviceConfigReadMs = millis() + kDeviceConfigRetryMs;
    return false;
  }
  if (!I2CManager::lock(m_wire)) {
    m_nextDeviceConfigReadMs = millis() + kDeviceConfigRetryMs;
    return false;
  }

  uint8_t zposBytes[2] = {0, 0};
  uint8_t mposBytes[2] = {0, 0};
  uint8_t mangBytes[2] = {0, 0};
  uint8_t confBytes[2] = {0, 0};
  uint8_t rawBytes[2] = {0, 0};
  uint8_t angleBytes[2] = {0, 0};
  uint8_t status = 0;
  uint8_t agc = 0;
  uint8_t magnitudeBytes[2] = {0, 0};

  const bool ok =
    readRegBytesLocked_(kZposMsbReg, zposBytes, sizeof(zposBytes)) &&
    readRegBytesLocked_(kMposMsbReg, mposBytes, sizeof(mposBytes)) &&
    readRegBytesLocked_(kMangMsbReg, mangBytes, sizeof(mangBytes)) &&
    readRegBytesLocked_(kConfMsbReg, confBytes, sizeof(confBytes)) &&
    readRegBytesLocked_(kRawAngleMsbReg, rawBytes, sizeof(rawBytes)) &&
    readRegBytesLocked_(kAngleMsbReg, angleBytes, sizeof(angleBytes)) &&
    readRegBytesLocked_(kStatusReg, &status, 1) &&
    readRegBytesLocked_(kAgcReg, &agc, 1) &&
    readRegBytesLocked_(kMagnitudeMsbReg, magnitudeBytes, sizeof(magnitudeBytes));

  I2CManager::unlock(m_wire);
  if (!ok) {
    m_nextDeviceConfigReadMs = millis() + kDeviceConfigRetryMs;
    AS5600A_LOGW("sensor '%s': read-only config snapshot failed at 0x%02X on bus %u\n",
                 name(), (unsigned)m_i2cAddr, (unsigned)m_busIndex);
    return false;
  }

  m_configZpos = decode12_(zposBytes[0], zposBytes[1]);
  m_configMpos = decode12_(mposBytes[0], mposBytes[1]);
  m_configMang = decode12_(mangBytes[0], mangBytes[1]);
  m_configConf = decode16_(confBytes[0], confBytes[1]);
  m_configRawAngle = decode12_(rawBytes[0], rawBytes[1]);
  m_configAngle = decode12_(angleBytes[0], angleBytes[1]);
  m_configStatus = status;
  m_configAgc = agc;
  m_configMagnitude = decode12_(magnitudeBytes[0], magnitudeBytes[1]);
  m_deviceConfigReadOk = true;
  m_nextDeviceConfigReadMs = 0;

  AS5600A_LOGI("sensor '%s': config snapshot zpos=%u mpos=%u mang=%u conf=0x%04X raw=%u angle=%u status=0x%02X agc=%u mag=%u\n",
               name(),
               (unsigned)m_configZpos,
               (unsigned)m_configMpos,
               (unsigned)m_configMang,
               (unsigned)m_configConf,
               (unsigned)m_configRawAngle,
               (unsigned)m_configAngle,
               (unsigned)m_configStatus,
               (unsigned)m_configAgc,
               (unsigned)m_configMagnitude);
  return true;
}

bool AS5600AngleSensor::maybeRefreshDeviceConfig_() const {
  if (m_deviceConfigReadOk) return true;

  const uint32_t now = millis();
  if (m_nextDeviceConfigReadMs != 0 &&
      (int32_t)(now - m_nextDeviceConfigReadMs) < 0) {
    return false;
  }

  return readDeviceConfig_();
}

bool AS5600AngleSensor::refreshDiagnostics_(bool force) const {
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
      AS5600A_LOGW("sensor '%s': diagnostic read failed at 0x%02X on bus %u\n",
                   name(), (unsigned)m_i2cAddr, (unsigned)m_busIndex);
      m_warnedDiagnosticRead = true;
    }
    m_nextDiagnosticReadMs = now + (m_diagnosticIntervalMs ? m_diagnosticIntervalMs : kDefaultDiagnosticIntervalMs);
    return false;
  }

  m_lastStatus = diagnosticSample.status;
  m_lastAgc = diagnosticSample.agc;
  m_lastMagnitude = diagnosticSample.magnitude;
  m_haveDiagnostics = true;
  m_warnedDiagnosticRead = false;
  m_nextDiagnosticReadMs = now + m_diagnosticIntervalMs;
  maybeWarnDiagnostics_();
  return true;
}

void AS5600AngleSensor::maybeWarnDiagnostics_() const {
  if (!m_haveDiagnostics) return;

  const bool magnetDetected = (m_lastStatus & kStatusMagnetDetected) != 0;
  const bool magneticHigh = (m_lastStatus & kStatusMagnetTooStrong) != 0;
  const bool magneticLow = (m_lastStatus & kStatusMagnetTooWeak) != 0;
  const bool agcSaturated = (m_lastAgc == 0u || m_lastAgc == 255u);
  const bool bad = !magnetDetected || magneticHigh || magneticLow || agcSaturated;

  if (!bad) {
    m_warnedDiagnostics = false;
    return;
  }
  if (m_warnedDiagnostics) return;

  AS5600A_LOGW("sensor '%s': status=0x%02X agc=%u mag=%u flags:%s%s%s%s\n",
               name(),
               (unsigned)m_lastStatus,
               (unsigned)m_lastAgc,
               (unsigned)m_lastMagnitude,
               magnetDetected ? "" : " MAG_NOT_DETECTED",
               magneticHigh ? " MAG_HIGH" : "",
               magneticLow ? " MAG_LOW" : "",
               agcSaturated ? " AGC_SAT" : "");
  m_warnedDiagnostics = true;
}

void AS5600AngleSensor::logFailureProbe_() const {
  if (m_warnedFailureProbe) return;
  m_warnedFailureProbe = true;

  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) return;

  if (!I2CManager::lock(m_wire, 20)) {
    AS5600A_LOGW("sensor '%s': failure probe could not lock I2C bus %u\n",
                 name(), (unsigned)m_busIndex);
    return;
  }

  m_wire->beginTransmission(m_i2cAddr);
  const uint8_t pingConfigured = (uint8_t)m_wire->endTransmission(true);

  m_wire->beginTransmission(kDefaultAddress);
  const uint8_t pingDefault = (uint8_t)m_wire->endTransmission(true);

  uint8_t tx = 255;
  uint8_t got = 0;
  uint8_t b0 = 0;
  uint8_t b1 = 0;
  m_wire->beginTransmission(m_i2cAddr);
  m_wire->write(kRawAngleMsbReg);
  tx = (uint8_t)m_wire->endTransmission(m_readMode == I2CReadMode::StopThenRead);
  if (tx == 0) {
    if (m_readMode == I2CReadMode::StopThenRead) delayMicroseconds(5);
    got = (uint8_t)m_wire->requestFrom((int)m_i2cAddr, 2);
    if (m_wire->available() > 0) b0 = (uint8_t)m_wire->read();
    if (m_wire->available() > 0) b1 = (uint8_t)m_wire->read();
    while (m_wire->available() > 0) {
      (void)m_wire->read();
    }
  }

  I2CManager::unlock(m_wire);

  const uint16_t raw = decode12_(b0, b1);
  AS5600A_LOGW("sensor '%s': failure probe bus%u addr=0x%02X bus_hz=%lu mode=%s "
               "ping_configured=%u ping_0x36=%u raw2{tx=%u got=%u bytes=%02X %02X raw=%u}\n",
               name(),
               (unsigned)m_busIndex,
               (unsigned)m_i2cAddr,
               (unsigned long)busHz_(m_busIndex),
               (m_readMode == I2CReadMode::RepeatedStart) ? "repeated" : "stop",
               (unsigned)pingConfigured,
               (unsigned)pingDefault,
               (unsigned)tx,
               (unsigned)got,
               (unsigned)b0,
               (unsigned)b1,
               (unsigned)raw);
}

bool AS5600AngleSensor::readRawAngle_(uint16_t& out) const {
  OutputSample sample;
  if (!readOutputBlock_(sample)) return false;

  out = sample.angle;
  m_lastGoodRaw = int(sample.angle);
  m_haveLastGoodRaw = true;
  m_lastReadOk = true;
  m_lastReadReused = false;
  m_warnedRead = false;
  m_nextReadAttemptMs = 0;
  refreshDiagnostics_(false);
  return true;
}

int AS5600AngleSensor::readRawAngleOnce_() const {
  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) {
    if (!m_warnedNoBus) {
      AS5600A_LOGW("sensor '%s': skipping read, I2C bus %u unavailable\n",
                   name(), (unsigned)m_busIndex);
      m_warnedNoBus = true;
    }
    m_lastReadOk = false;
    m_lastReadReused = m_haveLastGoodRaw;
    ++m_rawReadFailures;
    return m_haveLastGoodRaw ? m_lastGoodRaw : 0;
  }

  const uint32_t now = millis();
  maybeApplyVolatileConfig_();

  if (m_nextReadAttemptMs != 0 &&
      (int32_t)(now - m_nextReadAttemptMs) < 0) {
    m_lastReadOk = false;
    m_lastReadReused = m_haveLastGoodRaw;
    return m_haveLastGoodRaw ? m_lastGoodRaw : 0;
  }

  uint16_t raw = 0;
  for (uint8_t attempt = 0; attempt < 3; ++attempt) {
    if (readRawAngle_(raw)) {
      maybeRefreshDeviceConfig_();
      return int(raw);
    }
    delayMicroseconds(150);
  }

  if (!m_warnedRead) {
    AS5600A_LOGW("sensor '%s': read failed at 0x%02X on bus %u bus_hz=%lu mode=%s; reusing last good sample\n",
                 name(),
                 (unsigned)m_i2cAddr,
                 (unsigned)m_busIndex,
                 (unsigned long)busHz_(m_busIndex),
                 (m_readMode == I2CReadMode::RepeatedStart) ? "repeated" : "stop");
    m_warnedRead = true;
    logFailureProbe_();
  }
  ++m_rawReadFailures;
  m_lastReadOk = false;
  m_lastReadReused = m_haveLastGoodRaw;
  m_nextReadAttemptMs = now + (m_haveLastGoodRaw ? 250UL : 1000UL);
  return m_haveLastGoodRaw ? m_lastGoodRaw : 0;
}

int32_t AS5600AngleSensor::normalizeCount_(int32_t count) {
  count %= (int32_t)kCountsPerTurn;
  if (count < 0) count += kCountsPerTurn;
  return count;
}

int32_t AS5600AngleSensor::signedDeltaCounts_(int32_t raw, int32_t zero) {
  int32_t delta = normalizeCount_(raw) - normalizeCount_(zero);
  delta = normalizeCount_(delta + kHalfTurn) - kHalfTurn;
  return delta;
}

int32_t AS5600AngleSensor::calibrationCountsFromRaw_(int raw) const {
  raw = (int)normalizeCount_(raw);
  if (!m_calUnwrapInit) {
    m_calUnwrapInit = true;
    m_calLastUnwrapped = raw;
    return m_calLastUnwrapped;
  }

  m_calLastUnwrapped += signedDeltaCounts_(raw, normalizeCount_(m_calLastUnwrapped));
  return m_calLastUnwrapped;
}

float AS5600AngleSensor::degreesFromRaw_(int raw) const {
  return float(m_directionSign) * float(signedDeltaCounts_(raw, m_zeroCount)) * kDegreesPerCount;
}

void AS5600AngleSensor::sample(float& primaryOut, int& rawOut) const {
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

uint8_t AS5600AngleSensor::columnCount() const {
  uint8_t count = (m_includeRaw && m_mode != OutputMode::RAW) ? 2 : 1;
  if (m_includeAngleColumn) ++count;
  if (m_includeDiagColumns) count += kDiagnosticColumnCount;
  return count;
}

void AS5600AngleSensor::getColumnName(uint8_t idx, char* out, size_t cap) const {
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

  const uint8_t angleIdx = (m_includeRaw && m_mode != OutputMode::RAW) ? 2 : 1;
  if (m_includeAngleColumn && idx == angleIdx) {
    String s = String(name()) + "_angle [counts]";
    s.toCharArray(out, cap);
    return;
  }

  const uint8_t diagStart = angleIdx + (m_includeAngleColumn ? 1 : 0);
  if (m_includeDiagColumns && idx >= diagStart && idx < diagStart + kDiagnosticColumnCount) {
    String s = String(name());
    switch (idx - diagStart) {
      case 0: s += "_agc [counts]"; break;
      case 1: s += "_status [flags]"; break;
      case 2: s += "_mag [counts]"; break;
      case 3: s += "_read_ok [flags]"; break;
      case 4: s += "_reused [flags]"; break;
      case 5: s += "_read_failures [count]"; break;
      case 6: s += "_diag_failures [count]"; break;
      default: break;
    }
    s.toCharArray(out, cap);
  }
}

void AS5600AngleSensor::sampleValues(float* out, uint8_t max) {
  if (!out || max == 0 || m_muted) return;

  float primary = 0.0f;
  int raw = 0;
  sample(primary, raw);

  uint8_t w = 0;
  out[w++] = primary;
  if (m_includeRaw && m_mode != OutputMode::RAW && w < max) {
    out[w++] = float(raw);
  }
  if (m_includeAngleColumn && w < max) {
    uint16_t angle = 0;
    out[w++] = readAngleRegister_(angle) ? float(angle) : NAN;
  }
  if (m_includeDiagColumns && w < max) {
    refreshDiagnostics_(false);
    out[w++] = m_haveDiagnostics ? float(m_lastAgc) : NAN;
  }
  if (m_includeDiagColumns && w < max) {
    out[w++] = m_haveDiagnostics ? float(m_lastStatus) : NAN;
  }
  if (m_includeDiagColumns && w < max) {
    out[w++] = m_haveDiagnostics ? float(m_lastMagnitude) : NAN;
  }
  if (m_includeDiagColumns && w < max) {
    out[w++] = m_lastReadOk ? 1.0f : 0.0f;
  }
  if (m_includeDiagColumns && w < max) {
    out[w++] = m_lastReadReused ? 1.0f : 0.0f;
  }
  if (m_includeDiagColumns && w < max) {
    out[w++] = float(m_rawReadFailures);
  }
  if (m_includeDiagColumns && w < max) {
    out[w++] = float(m_diagnosticReadFailures);
  }
}

bool AS5600AngleSensor::describeColumn(uint8_t idx, SensorColumnDescriptor& out) const {
  if (idx >= columnCount()) return false;
  if (!Sensor::describeColumn(idx, out)) return false;

  const bool hasRawColumn = (m_includeRaw && m_mode != OutputMode::RAW);
  const uint8_t angleIdx = hasRawColumn ? 2 : 1;
  if (m_includeAngleColumn && idx == angleIdx) {
    copyField_(out.sensorName, sizeof(out.sensorName), name());
    out.outputMode = OutputMode::RAW;
    out.required = false;
    out.primary = false;
    out.raw = true;
    out.diagnostic = true;
    out.calibrated = false;
    out.transformed = false;
    out.end[0] = '\0';
    out.domain[0] = '\0';
    copyField_(out.source, sizeof(out.source), "as5600_angle_register");
    copyField_(out.quantity, sizeof(out.quantity), "angle");
    copyField_(out.unit, sizeof(out.unit), "counts");
    snprintf(out.columnId, sizeof(out.columnId), "%s_angle", name());
    copyField_(out.notes, sizeof(out.notes), "AS5600 ANGLE register readout");
    return true;
  }

  const uint8_t diagStart = angleIdx + (m_includeAngleColumn ? 1 : 0);
  const bool diagColumn = m_includeDiagColumns && idx >= diagStart && idx < diagStart + kDiagnosticColumnCount;
  if (diagColumn) {
    copyField_(out.sensorName, sizeof(out.sensorName), name());
    out.outputMode = OutputMode::RAW;
    out.required = false;
    out.primary = false;
    out.raw = true;
    out.diagnostic = true;
    out.calibrated = false;
    out.transformed = false;
    out.end[0] = '\0';
    out.domain[0] = '\0';
    copyField_(out.source, sizeof(out.source), "as5600_diagnostic");

    switch (idx - diagStart) {
      case 0:
        copyField_(out.quantity, sizeof(out.quantity), "agc");
        copyField_(out.unit, sizeof(out.unit), "counts");
        break;
      case 1:
        copyField_(out.quantity, sizeof(out.quantity), "status");
        copyField_(out.unit, sizeof(out.unit), "flags");
        break;
      case 2:
        copyField_(out.quantity, sizeof(out.quantity), "mag");
        copyField_(out.unit, sizeof(out.unit), "counts");
        break;
      case 3:
        copyField_(out.quantity, sizeof(out.quantity), "read_ok");
        copyField_(out.unit, sizeof(out.unit), "flags");
        break;
      case 4:
        copyField_(out.quantity, sizeof(out.quantity), "reused");
        copyField_(out.unit, sizeof(out.unit), "flags");
        break;
      case 5:
        copyField_(out.quantity, sizeof(out.quantity), "read_failures");
        copyField_(out.unit, sizeof(out.unit), "count");
        break;
      case 6:
        copyField_(out.quantity, sizeof(out.quantity), "diag_failures");
        copyField_(out.unit, sizeof(out.unit), "count");
        break;
      default:
        break;
    }

    snprintf(out.columnId, sizeof(out.columnId), "%s_%s", name(), out.quantity);
    copyField_(out.notes, sizeof(out.notes), "AS5600 diagnostic readout");
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

bool AS5600AngleSensor::describeSensorMetadata(SensorMetadataDescriptor& out) const {
  out = SensorMetadataDescriptor{};
  copyField_(out.sensorId, sizeof(out.sensorId), name());
  copyField_(out.name, sizeof(out.name), name());
  copyField_(out.type, sizeof(out.type), "as5600_angle_i2c");
  copyField_(out.domain, sizeof(out.domain), m_primaryDomain);
  copyField_(out.rawUnit, sizeof(out.rawUnit), "counts");
  copyField_(out.calibrationType, sizeof(out.calibrationType), "zero_offset");
  copyField_(out.calibrationInputUnit, sizeof(out.calibrationInputUnit), "counts");
  copyField_(out.calibrationOutputUnit, sizeof(out.calibrationOutputUnit), m_outputUnitsLabel);
  out.installedZeroCount = m_zeroCount;
  out.sensorZeroCount = 0;
  out.sensorFullCount = kCountsPerTurn - 1;
  out.sensorFullTravel = 360.0f;
  copyField_(out.direction, sizeof(out.direction), directionName_(m_directionSign));
  out.invert = (m_directionSign < 0);
  out.hasCalibration = true;
  out.hasTracking = false;
  out.countsPerTurn = kCountsPerTurn;
  out.wrapThresholdCounts = kHalfTurn;
  out.assumeTurn0AtStart = false;
  out.hasDeviceConfig = true;
  copyField_(out.deviceConfig.kind, sizeof(out.deviceConfig.kind), "as5600_registers");
  copyField_(out.deviceConfig.policy, sizeof(out.deviceConfig.policy),
             (m_slowFilterCode >= 0) ? "volatile_write_then_read" : "read_only");
  copyField_(out.deviceConfig.status, sizeof(out.deviceConfig.status),
             m_deviceConfigReadOk ? "read_ok" : (m_deviceConfigReadAttempted ? "read_failed" : "not_read"));
  if (m_slowFilterCode >= 0) {
    copyField_(out.deviceConfig.requestedSlowFilter, sizeof(out.deviceConfig.requestedSlowFilter),
               as5600SlowFilterName_((uint8_t)m_slowFilterCode));
    copyField_(out.deviceConfig.writeStatus, sizeof(out.deviceConfig.writeStatus),
               m_configWriteOk ? "write_ok" : (m_configWriteAttempted ? "write_failed" : "not_attempted"));
  }
  out.deviceConfig.readOk = m_deviceConfigReadOk;
  out.deviceConfig.rawAngle = m_configRawAngle;
  out.deviceConfig.angle = m_configAngle;
  out.deviceConfig.zpos = m_configZpos;
  out.deviceConfig.mpos = m_configMpos;
  out.deviceConfig.mang = m_configMang;
  out.deviceConfig.conf = m_configConf;
  out.deviceConfig.statusReg = m_configStatus;
  out.deviceConfig.agc = m_configAgc;
  out.deviceConfig.magnitude = m_configMagnitude;
  copyField_(out.deviceConfig.confPowerMode, sizeof(out.deviceConfig.confPowerMode),
             as5600PowerModeName_((uint8_t)(m_configConf & 0x03u)));
  copyField_(out.deviceConfig.confHysteresis, sizeof(out.deviceConfig.confHysteresis),
             as5600HysteresisName_((uint8_t)((m_configConf >> 2) & 0x03u)));
  copyField_(out.deviceConfig.confOutputStage, sizeof(out.deviceConfig.confOutputStage),
             as5600OutputStageName_((uint8_t)((m_configConf >> 4) & 0x03u)));
  copyField_(out.deviceConfig.confPwmFrequency, sizeof(out.deviceConfig.confPwmFrequency),
             as5600PwmFrequencyName_((uint8_t)((m_configConf >> 6) & 0x03u)));
  copyField_(out.deviceConfig.confSlowFilter, sizeof(out.deviceConfig.confSlowFilter),
             as5600SlowFilterName_((uint8_t)((m_configConf >> 8) & 0x03u)));
  copyField_(out.deviceConfig.confFastFilterThreshold, sizeof(out.deviceConfig.confFastFilterThreshold),
             as5600FastFilterThresholdName_((uint8_t)((m_configConf >> 10) & 0x07u)));
  out.deviceConfig.confWatchdog = ((m_configConf >> 13) & 0x01u) != 0;
  return true;
}

OutputConfig AS5600AngleSensor::outputConfig() const {
  return OutputConfig{m_mode, m_includeRaw};
}

void AS5600AngleSensor::setOutputConfig(const OutputConfig& cfg) {
  setOutputMode(cfg.primary);
  setIncludeRaw(cfg.includeRaw);
}

bool AS5600AngleSensor::beginCalibration(CalMode mode) {
  if (mode != CalMode::ZERO) return false;
  cal_ = CalState{};
  cal_.mode = mode;
  cal_.phase = CalPhase::ACTIVE;
  cal_.started_ms = millis();
  m_calUnwrapInit = false;
  m_calLastUnwrapped = 0;
  return true;
}

bool AS5600AngleSensor::updateCalibration(int32_t latestCounts) {
  if (cal_.phase != CalPhase::ACTIVE || cal_.mode != CalMode::ZERO) return false;
  ++cal_.samples;
  if (cal_.samples == 1) {
    cal_.first_counts = latestCounts;
  } else if (cal_.samples == 2) {
    cal_.second_counts = latestCounts;
  }
  return true;
}

bool AS5600AngleSensor::finishCalibration(bool persist) {
  if (cal_.phase != CalPhase::ACTIVE) return false;

  if (cal_.mode == CalMode::ZERO) {
    const bool haveZero = (cal_.first_counts != INT32_MAX);
    const bool haveDirection = (cal_.second_counts != INT32_MIN);
    const int32_t zero = haveZero ? cal_.first_counts : currentRawCounts();
    m_zeroCount = normalizeCount_(zero);

    if (haveDirection) {
      const int32_t delta = cal_.second_counts - zero;
      const int32_t absDelta = (delta < 0) ? -delta : delta;
      if (absDelta < kDirectionMinDeltaCounts) {
        cal_.phase = CalPhase::COMPLETE;
        cal_.mode = CalMode::NONE;
        return false;
      }
      m_directionSign = (delta < 0) ? -1 : 1;
    }

    if (persist) {
      ConfigManager::saveSensorParamByName(name(), "zero_count", String(m_zeroCount));
      ConfigManager::saveSensorParamByName(name(), "direction", String(directionName_(m_directionSign)));
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

int32_t AS5600AngleSensor::currentRawCounts() const {
  const int raw = readRawAngleOnce_();
  if (cal_.phase == CalPhase::ACTIVE && cal_.mode == CalMode::ZERO) {
    return calibrationCountsFromRaw_(raw);
  }
  return raw;
}

bool AS5600AngleSensor::readPreviewValue(OutputMode mode, float& value, char* unit, size_t unitCap) {
  if (mode == OutputMode::RAW) return Sensor::readPreviewValue(mode, value, unit, unitCap);
  if (mode != OutputMode::LINEAR || m_mode != OutputMode::LINEAR || m_muted) return false;

  float primary = 0.0f;
  int raw = 0;
  sample(primary, raw);
  (void)raw;
  value = primary;
  copyField_(unit, unitCap, m_outputUnitsLabel[0] ? m_outputUnitsLabel : "deg");
  return true;
}

CalibrationState AS5600AngleSensor::calibration() const {
  CalibrationState cs;
  cs.mode = m_mode;
  if (m_mode != OutputMode::RAW) {
    cs.scale = float(m_directionSign) * kDegreesPerCount;
    cs.offset = -float(m_zeroCount) * cs.scale;
  }
  return cs;
}

bool AS5600AngleSensor::setCalibration(const CalibrationState& s) {
  (void)s;
  return false;
}

void AS5600AngleSensor::setIncludeRaw(bool b) {
  m_includeRaw = b;
}

void AS5600AngleSensor::setOutputUnitsLabel(const char* u) {
  Sensor::setOutputUnitsLabel((u && u[0]) ? u : "deg");
}

const ParamDef* AS5600AngleSensor::paramDefs(size_t& count) {
  static const ParamDef defs[] = {
    {"i2c_bus",          ParamType::Enum,   "0",   nullptr, nullptr, "0,1", "I2C bus index"},
    {"i2c_addr",         ParamType::Int,    "54",  "1",     "127",   nullptr, "I2C address in decimal (default 54 = 0x36)"},
    {"i2c_read_mode",    ParamType::Enum,   "repeated", nullptr, nullptr, "repeated,stop", "I2C register read transaction style"},
    {"zero_count",       ParamType::Int,    "0",   "0",     "4095", nullptr, "Firmware zero point in raw AS5600 counts"},
    {"direction",        ParamType::Enum,   "counts_increase_positive", nullptr, nullptr, "counts_increase_positive,counts_decrease_positive", "Raw-count direction for positive angular movement"},
    {"installed_range",  ParamType::Float,  "0",   "0",     nullptr, nullptr, "Installed range in linear output units for sag percentage"},
    {"slow_filter",      ParamType::Enum,   "unchanged", nullptr, nullptr, "unchanged,16x,8x,4x,2x", "Volatile AS5600 slow filter setting; not burned to OTP"},
    {"output_mode",      ParamType::Enum,   "1",   nullptr, nullptr, nullptr, "Output method: RAW counts, LINEAR degrees, or transformed degrees"},
    {"include_raw",      ParamType::Bool,   "true", nullptr, nullptr, nullptr, "Append raw absolute angle counts after primary"},
    {"include_angle",    ParamType::Bool,   "false", nullptr, nullptr, nullptr, "Append AS5600 ANGLE register counts for diagnostics"},
    {"include_diag",     ParamType::Bool,   "false", nullptr, nullptr, nullptr, "Append AS5600 AGC, status, magnitude, read-state, and failure-counter columns"},
    {"diag_interval_ms", ParamType::Int,    "250", "0",     "5000", nullptr, "Minimum interval between AS5600 diagnostic reads"},
    {"end",              ParamType::Enum,   "",    nullptr, nullptr, "front,rear", "Optional semantic end for log metadata"},
    {"primary_domain",   ParamType::Enum,   "",    nullptr, nullptr, "wheel,suspension,brake,drivetrain,frame,steering", "Optional semantic domain for primary output"},
    {"primary_quantity", ParamType::Enum,   "ang_disp", nullptr, nullptr, "disp,ang_disp,force,pressure,temp,voltage,norm", "Optional semantic quantity for primary output"},
  };

  count = sizeof(defs) / sizeof(defs[0]);
  return defs;
}

Sensor* AS5600AngleSensor::create(const char* instanceName, const ParamPack& params, bool mutedDefault) {
  Params p;
  loadParamsFromPack_(p, instanceName, params);

  auto* obj = new AS5600AngleSensor(p);
  obj->setMuted(mutedDefault);
  return obj;
}

static bool _reg_as5600_angle_i2c =
  SensorRegistry::registerType(
    SensorType::AS5600AngleI2C,
    "as5600_angle_i2c",
    "AS5600 Angle (I2C)",
    &AS5600AngleSensor::paramDefs,
    &AS5600AngleSensor::create,
    CAL_ZERO
  );
