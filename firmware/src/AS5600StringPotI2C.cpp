#include "AS5600StringPotI2C.h"

#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <string.h>

#include "ConfigManager.h"
#include "I2CManager.h"
#include "PowerManager.h"
#include "SensorRegistry.h"
#include "DebugLog.h"
#include "esp_timer.h"

#define AS5600I2C_LOGI(...) LOGI_TAG("AS5600", __VA_ARGS__)
#define AS5600I2C_LOGW(...) LOGW_TAG("AS5600", __VA_ARGS__)

namespace {

static constexpr uint8_t kZposMsbReg = 0x01;
static constexpr uint8_t kMposMsbReg = 0x03;
static constexpr uint8_t kMangMsbReg = 0x05;
static constexpr uint8_t kConfMsbReg = 0x07;
static constexpr uint8_t kStatusReg = 0x0B;
static constexpr uint8_t kRawAngleMsbReg = 0x0C;
static constexpr uint8_t kAngleMsbReg = 0x0E;
static constexpr uint8_t kAgcReg = 0x1A;
static constexpr uint8_t kMagnitudeMsbReg = 0x1B;
static constexpr uint32_t kDefaultDiagnosticIntervalMs = 250;
static constexpr uint32_t kDeviceConfigRetryMs = 2000;
static constexpr uint8_t kDiagnosticColumnCount = 7;
static constexpr uint16_t kConfSlowFilterMask = 0x0300;
static constexpr uint8_t kConfSlowFilterShift = 8;
static constexpr uint16_t kMaxAsyncRateHz = 1000;
static constexpr uint32_t kDeferredRecoveryFailureStreak = 3;

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

uint16_t decode12_(uint8_t msb, uint8_t lsb) {
  return (uint16_t(msb & 0x0Fu) << 8) | lsb;
}

uint16_t decode16_(uint8_t msb, uint8_t lsb) {
  return (uint16_t(msb) << 8) | lsb;
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

void loadParamsFromPack_(AS5600StringPotI2C::Params& p,
                         const char* instanceName,
                         const ParamPack& params) {
  p.name = instanceName ? instanceName : "as5600_i2c";

  long li = 0;
  bool b = false;
  double d = 0.0;
  String s;

  if (params.getInt("i2c_bus", li))                  p.busIndex = (li < 0) ? 0u : (uint8_t)li;
  if (params.getInt("i2c_addr", li))                 p.i2cAddr = (li <= 0) ? 0x36u : (uint8_t)li;
  if (params.get("slow_filter", s))                  p.slowFilterCode = parseSlowFilterCode_(s);
  if (params.getInt("async_rate_hz", li))            p.asyncRateHz = (li < 0) ? 0u : (uint16_t)li;
  if (params.getBool("include_angle", b))            p.includeAngleColumn = b;
  if (params.getBool("include_diag", b))             p.includeDiagColumns = b;
  if (params.getInt("diag_interval_ms", li))         p.diagnosticIntervalMs = (li < 0) ? 0UL : (uint32_t)li;
  if (params.getInt("counts_per_turn", li))          p.countsPerTurn = (uint16_t)li;
  if (params.getInt("wrap_threshold_counts", li))    p.wrapThresholdCounts = (uint16_t)li;
  if (params.getInt("sensor_zero_count", li))        p.sensorZeroCount = (int32_t)li;
  if (params.getInt("sensor_full_count", li))        p.sensorFullCount = (int32_t)li;
  if (params.getFloat("sensor_full_travel_mm", d))   p.sensorFullTravelMm = (float)d;
  if (params.getFloat("installed_range", d))         p.installedRange = (float)d;
  if (params.getInt("installed_zero_count", li))     p.installedZeroCount = (int32_t)li;
  if (params.getBool("assume_turn0_at_start", b))    p.assumeTurn0AtStart = b;
  if (params.getBool("include_raw", b))              p.includeRawColumn = b;
  if (params.get("end", s))                          s.toCharArray(p.semanticEnd, sizeof(p.semanticEnd));
  if (params.get("primary_domain", s))               s.toCharArray(p.primaryDomain, sizeof(p.primaryDomain));
  if (params.get("primary_quantity", s))             s.toCharArray(p.primaryQuantity, sizeof(p.primaryQuantity));
}

} // namespace

AS5600StringPotI2C::AS5600StringPotI2C(const Params& p)
  : AS5600StringPotSensorBase(p),
    m_busIndex(p.busIndex),
    m_i2cAddr(p.i2cAddr ? p.i2cAddr : 0x36),
    m_slowFilterCode((p.slowFilterCode >= 0 && p.slowFilterCode <= 3) ? p.slowFilterCode : -1),
    m_asyncRateHz(p.asyncRateHz) {
  if (m_asyncRateHz > kMaxAsyncRateHz) m_asyncRateHz = kMaxAsyncRateHz;
  m_includeAngleColumn = p.includeAngleColumn;
  m_includeDiagColumns = p.includeDiagColumns;
  m_diagnosticIntervalMs = p.diagnosticIntervalMs;
}

void AS5600StringPotI2C::setRuntimeFailure_(SensorRuntimeFailureStage stage,
                                            int16_t resultCode,
                                            uint8_t expectedBytes,
                                            uint8_t receivedBytes) const {
  m_lastRuntimeFailure.stage = stage;
  m_lastRuntimeFailure.resultCode = resultCode;
  m_lastRuntimeFailure.expectedBytes = expectedBytes;
  m_lastRuntimeFailure.receivedBytes = receivedBytes;
}

void AS5600StringPotI2C::resetRuntimeDiagnostics_() {
  const uint32_t beginCount = m_runtimeDiagnostics.beginCount + 1;
  m_runtimeDiagnostics = SensorRuntimeDiagnostics{};
  m_runtimeDiagnostics.present = true;
  copyField_(m_runtimeDiagnostics.sensorName, sizeof(m_runtimeDiagnostics.sensorName), name());
  copyField_(m_runtimeDiagnostics.kind, sizeof(m_runtimeDiagnostics.kind), asyncClientKind());
  m_runtimeDiagnostics.busIndex = m_busIndex;
  m_runtimeDiagnostics.address = m_i2cAddr;
  m_runtimeDiagnostics.beginCount = beginCount;
  m_runtimeDiagnostics.lastBeginUptimeMs = millis();
  m_lastRuntimeFailure = SensorRuntimeFailure{};
  m_lastRawRuntimeFailure = SensorRuntimeFailure{};
  m_runtimeSessionReadFailureBase = 0;
  m_runtimeSessionDiagnosticFailureBase = 0;
  m_runtimeReadFailureStreak = 0;
  m_runtimeReadFailureActive = false;
  m_runtimeConfigFailureActive = false;
}

void AS5600StringPotI2C::resetSessionRuntimeDiagnostics_() const {
  m_runtimeDiagnostics.eventCount = 0;
  m_runtimeDiagnostics.eventsTotal = 0;
  m_runtimeDiagnostics.eventsDropped = 0;
  m_runtimeDiagnostics.readFailureStreakMax = 0;
  m_runtimeDiagnostics.readRecoveries = 0;
  m_runtimeSessionReadFailureBase = m_readFailures;
  m_runtimeSessionDiagnosticFailureBase = m_diagnosticReadFailures;
  m_runtimeReadFailureStreak = 0;
  m_runtimeReadFailureActive = false;
  m_runtimeConfigFailureActive = false;
}

void AS5600StringPotI2C::recordRuntimeEvent_(SensorRuntimeEventType type) const {
  ++m_runtimeDiagnostics.eventsTotal;
  if (m_runtimeDiagnostics.eventCount >= SensorRuntimeDiagnostics::kMaxEvents) {
    ++m_runtimeDiagnostics.eventsDropped;
    return;
  }

  SensorRuntimeEvent& event = m_runtimeDiagnostics.events[m_runtimeDiagnostics.eventCount++];
  event = SensorRuntimeEvent{};
  event.uptimeMs = millis();
  event.acquisitionSeq = m_asyncNextSeq;
  event.rawReadFailures = m_readFailures - m_runtimeSessionReadFailureBase;
  event.raw = m_haveLastGoodWrapped ? (uint16_t)m_lastGoodWrapped : 0;
  event.conf = m_deviceConfigReadOk ? m_configConf : m_runtimeDiagnostics.configAfter;
  event.type = type;
  switch (type) {
    case SensorRuntimeEventType::ReadFailureStarted:
    case SensorRuntimeEventType::ReadRecovered:
      event.failure = m_lastRawRuntimeFailure;
      break;
    case SensorRuntimeEventType::ConfigWriteFailed:
    case SensorRuntimeEventType::ConfigWriteRecovered:
      event.failure = m_lastRuntimeFailure;
      break;
    default:
      event.failure = m_lastReadOk ? SensorRuntimeFailure{} : m_lastRawRuntimeFailure;
      break;
  }
  event.haveSample = m_haveLastGoodWrapped;
  event.readOk = m_lastReadOk;
  event.reused = m_lastReadReused;
  event.analogRailEnabled = PowerManager::analogRailEnabled();
  event.analogRailFault = PowerManager::analogRailFaultActive();
}

void AS5600StringPotI2C::updateReadTransition_(bool readOk) const {
  if (!readOk) {
    ++m_runtimeReadFailureStreak;
    if (m_runtimeReadFailureStreak > m_runtimeDiagnostics.readFailureStreakMax) {
      m_runtimeDiagnostics.readFailureStreakMax = m_runtimeReadFailureStreak;
    }
    if (!m_runtimeReadFailureActive) {
      m_runtimeReadFailureActive = true;
      recordRuntimeEvent_(SensorRuntimeEventType::ReadFailureStarted);
    }
    return;
  }

  if (m_runtimeReadFailureActive) {
    ++m_runtimeDiagnostics.readRecoveries;
    recordRuntimeEvent_(SensorRuntimeEventType::ReadRecovered);
  }
  m_runtimeReadFailureActive = false;
  m_runtimeReadFailureStreak = 0;
}

void AS5600StringPotI2C::begin() {
  m_deferredRecoveryPending = false;
  resetRuntimeDiagnostics_();
  m_wire = I2CManager::bus(m_busIndex);
  m_warnedNoBus = false;
  m_warnedRead = false;
  m_warnedDiagnostics = false;
  m_warnedDiagnosticRead = false;
  m_warnedFailureProbe = false;
  m_haveLastGoodWrapped = false;
  m_lastGoodWrapped = 0;
  m_haveDiagnostics = false;
  m_lastStatus = 0;
  m_lastAgc = 0;
  m_lastMagnitude = 0;
  m_lastReadOk = false;
  m_lastReadReused = false;
  m_readFailures = 0;
  m_diagnosticReadFailures = 0;
  m_nextReadAttemptMs = 0;
  m_nextDiagnosticReadMs = 0;
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
  m_asyncLoggingActive = false;
  m_asyncNextSeq = 0;
  m_asyncLastLoggedSeq = 0;
  resetAsyncSnapshot_();
  I2CBusScheduler::registerClient(this);

  if (!m_wire) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusUnavailable);
    m_runtimeDiagnostics.initializationFailure = m_lastRuntimeFailure;
    AS5600I2C_LOGW("sensor '%s': I2C bus %u unavailable\n",
                   name(), (unsigned)m_busIndex);
  } else if (!probe_()) {
    m_runtimeDiagnostics.initializationFailure = m_lastRuntimeFailure;
    AS5600I2C_LOGW("sensor '%s': no AS5600 response at 0x%02X on bus %u\n",
                   name(), (unsigned)m_i2cAddr, (unsigned)m_busIndex);
  } else {
    m_runtimeDiagnostics.initialProbeOk = true;
    maybeApplyVolatileConfig_();
    int wrapped = 0;
    if (!readWrappedCountsDirectOnce_(wrapped)) {
      m_runtimeDiagnostics.initializationFailure = m_lastRawRuntimeFailure;
    }
    refreshDiagnostics_(true);
    readDeviceConfig_();
  }

  m_runtimeDiagnostics.configWriteAttempted = m_configWriteAttempted;
  m_runtimeDiagnostics.configWriteOk = m_configWriteOk;
  m_runtimeDiagnostics.configReadAttempted = m_deviceConfigReadAttempted;
  m_runtimeDiagnostics.configReadOk = m_deviceConfigReadOk;
  if (m_deviceConfigReadOk) m_runtimeDiagnostics.configAfter = m_configConf;

  AS5600StringPotSensorBase::onLoggingStart();
}

bool AS5600StringPotI2C::reconfigureFromSpec(const SensorSpec& spec) {
  if (spec.type != SensorType::AS5600StringPotI2C) return false;

  Params p;
  loadParamsFromPack_(p, spec.name, spec.params);
  applyBaseParams(p);
  m_busIndex = p.busIndex;
  m_i2cAddr = p.i2cAddr ? p.i2cAddr : 0x36;
  m_slowFilterCode = (p.slowFilterCode >= 0 && p.slowFilterCode <= 3) ? p.slowFilterCode : -1;
  m_asyncRateHz = p.asyncRateHz;
  if (m_asyncRateHz > kMaxAsyncRateHz) m_asyncRateHz = kMaxAsyncRateHz;
  m_includeAngleColumn = p.includeAngleColumn;
  m_includeDiagColumns = p.includeDiagColumns;
  m_diagnosticIntervalMs = p.diagnosticIntervalMs;
  begin();
  return true;
}

void AS5600StringPotI2C::onLoggingStart() {
  resetSessionRuntimeDiagnostics_();
  AS5600StringPotSensorBase::onLoggingStart();
  m_asyncLoggingActive = true;
  m_asyncNextSeq = 0;
  m_asyncLastLoggedSeq = 0;
  resetAsyncSnapshot_();
  recordRuntimeEvent_(SensorRuntimeEventType::LoggingStart);
  (void)acquireAsyncSample_();
}

void AS5600StringPotI2C::onLoggingStop() {
  recordRuntimeEvent_(SensorRuntimeEventType::LoggingStop);
  m_asyncLoggingActive = false;
  AS5600StringPotSensorBase::onLoggingStop();
  const bool sustainedReadFailure =
    m_runtimeReadFailureActive &&
    m_runtimeReadFailureStreak >= kDeferredRecoveryFailureStreak;
  const bool configFailure =
    (m_configWriteAttempted && !m_configWriteOk) ||
    (m_deviceConfigReadAttempted && !m_deviceConfigReadOk);
  if (sustainedReadFailure || configFailure) {
    m_deferredRecoveryPending = true;
    AS5600I2C_LOGW("sensor '%s': recovery deferred until log finalization read_streak=%lu config_failure=%d\n",
                   name(),
                   (unsigned long)m_runtimeReadFailureStreak,
                   configFailure ? 1 : 0);
  }
}

void AS5600StringPotI2C::onLoggingFinalized() {
  if (!m_deferredRecoveryPending) return;

  m_deferredRecoveryPending = false;
  AS5600I2C_LOGI("sensor '%s': attempting deferred post-session recovery\n", name());
  begin();

  const bool sampleRecovered = m_runtimeDiagnostics.initialProbeOk && m_lastReadOk;
  const bool configRecovered =
    (!m_configWriteAttempted || m_configWriteOk) && m_deviceConfigReadOk;
  if (sampleRecovered && configRecovered) {
    AS5600I2C_LOGI("sensor '%s': deferred post-session recovery complete\n", name());
    return;
  }

  m_deferredRecoveryPending = true;
  AS5600I2C_LOGW("sensor '%s': deferred recovery incomplete probe=%d read=%d config_write=%d config_read=%d\n",
                 name(),
                 m_runtimeDiagnostics.initialProbeOk ? 1 : 0,
                 m_lastReadOk ? 1 : 0,
                 (!m_configWriteAttempted || m_configWriteOk) ? 1 : 0,
                 m_deviceConfigReadOk ? 1 : 0);
}

uint16_t AS5600StringPotI2C::asyncTargetRateHz() const {
  if (m_asyncRateHz != 0) return m_asyncRateHz;
  const LoggerConfig& cfg = ConfigManager::get();
  uint16_t hz = cfg.sampleRateHz;
  if (hz == 0) hz = 100;
  if (hz > kMaxAsyncRateHz) hz = kMaxAsyncRateHz;
  return hz;
}

bool AS5600StringPotI2C::asyncAcquire() {
  return acquireAsyncSample_();
}

void AS5600StringPotI2C::asyncSchedulerStarting() {
  recordRuntimeEvent_(SensorRuntimeEventType::SchedulerStart);
}

void AS5600StringPotI2C::asyncSchedulerStopped() {
  recordRuntimeEvent_(SensorRuntimeEventType::SchedulerStop);
}

bool AS5600StringPotI2C::probe_() const {
  if (!m_wire) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusUnavailable);
    return false;
  }
  if (!I2CManager::lock(m_wire)) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusLock);
    return false;
  }
  m_wire->beginTransmission(m_i2cAddr);
  const uint8_t result = (uint8_t)m_wire->endTransmission(true);
  I2CManager::unlock(m_wire);
  if (result != 0) {
    setRuntimeFailure_(SensorRuntimeFailureStage::Probe, result);
    return false;
  }
  return true;
}

bool AS5600StringPotI2C::readRegBytesLocked_(uint8_t reg, uint8_t* out, uint8_t len) const {
  if (!m_wire) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusUnavailable);
    return false;
  }
  if (!out || len == 0) {
    setRuntimeFailure_(SensorRuntimeFailureStage::RequestBytes, -1, len, 0);
    return false;
  }

  m_wire->beginTransmission(m_i2cAddr);
  m_wire->write(reg);
  const uint8_t txResult = (uint8_t)m_wire->endTransmission(false);
  if (txResult != 0) {
    setRuntimeFailure_(SensorRuntimeFailureStage::RegisterAddress, txResult);
    return false;
  }

  const size_t got = m_wire->requestFrom((int)m_i2cAddr, (int)len);
  if (got != len) {
    while (m_wire->available() > 0) (void)m_wire->read();
    setRuntimeFailure_(SensorRuntimeFailureStage::RequestBytes,
                       0,
                       len,
                       (got > 255u) ? 255u : (uint8_t)got);
    return false;
  }

  for (uint8_t i = 0; i < len; ++i) {
    const int v = m_wire->read();
    if (v < 0) {
      setRuntimeFailure_(SensorRuntimeFailureStage::ReadByte, v, len, i);
      return false;
    }
    out[i] = (uint8_t)v;
  }
  return true;
}

bool AS5600StringPotI2C::writeRegBytesLocked_(uint8_t reg,
                                              const uint8_t* data,
                                              uint8_t len) const {
  if (!m_wire) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusUnavailable);
    return false;
  }
  if (!data || len == 0) {
    setRuntimeFailure_(SensorRuntimeFailureStage::WriteRegister, -1, len, 0);
    return false;
  }

  m_wire->beginTransmission(m_i2cAddr);
  m_wire->write(reg);
  for (uint8_t i = 0; i < len; ++i) m_wire->write(data[i]);
  const uint8_t result = (uint8_t)m_wire->endTransmission(true);
  if (result != 0) {
    setRuntimeFailure_(SensorRuntimeFailureStage::WriteRegister, result);
    return false;
  }
  return true;
}

bool AS5600StringPotI2C::readReg16_(uint8_t reg, uint16_t& value) const {
  value = 0;
  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusUnavailable);
    return false;
  }
  if (!I2CManager::lock(m_wire)) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusLock);
    return false;
  }

  uint8_t bytes[2] = {0, 0};
  const bool ok = readRegBytesLocked_(reg, bytes, sizeof(bytes));
  I2CManager::unlock(m_wire);
  if (!ok) return false;
  value = decode12_(bytes[0], bytes[1]);
  return true;
}

bool AS5600StringPotI2C::readAngleRegister_(uint16_t& value) const {
  return readReg16_(kAngleMsbReg, value);
}

bool AS5600StringPotI2C::readWrappedCounts_(int& wrapped) const {
  wrapped = 0;
  uint16_t raw = 0;
  if (!readReg16_(kRawAngleMsbReg, raw)) return false;
  wrapped = int(raw);
  return true;
}

bool AS5600StringPotI2C::readDiagnostics_(OutputSample& out) const {
  out = OutputSample{};
  if (!m_wire) m_wire = I2CManager::bus(m_busIndex);
  if (!m_wire) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusUnavailable);
    return false;
  }
  if (!I2CManager::lock(m_wire)) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusLock);
    return false;
  }

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

bool AS5600StringPotI2C::refreshDiagnostics_(bool force) const {
  const uint32_t now = millis();
  if (!force && m_diagnosticIntervalMs > 0 &&
      m_nextDiagnosticReadMs != 0 &&
      (int32_t)(now - m_nextDiagnosticReadMs) < 0) {
    return m_haveDiagnostics;
  }

  OutputSample sample;
  if (!readDiagnostics_(sample)) {
    ++m_diagnosticReadFailures;
    if (!m_warnedDiagnosticRead) {
      AS5600I2C_LOGW("sensor '%s': diagnostic read failed at 0x%02X on bus %u\n",
                     name(), (unsigned)m_i2cAddr, (unsigned)m_busIndex);
      m_warnedDiagnosticRead = true;
    }
    m_nextDiagnosticReadMs = now +
      (m_diagnosticIntervalMs ? m_diagnosticIntervalMs : kDefaultDiagnosticIntervalMs);
    return false;
  }

  m_lastStatus = sample.status;
  m_lastAgc = sample.agc;
  m_lastMagnitude = sample.magnitude;
  m_haveDiagnostics = true;
  m_warnedDiagnosticRead = false;
  m_nextDiagnosticReadMs = now + m_diagnosticIntervalMs;
  maybeWarnDiagnostics_();
  return true;
}

void AS5600StringPotI2C::maybeWarnDiagnostics_() const {
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

  AS5600I2C_LOGW("sensor '%s': status=0x%02X agc=%u mag=%u flags:%s%s%s%s\n",
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

bool AS5600StringPotI2C::applyVolatileConfig_() const {
  m_configWriteAttempted = true;
  m_configWriteOk = false;
  m_runtimeDiagnostics.configWriteAttempted = true;
  m_runtimeDiagnostics.configWriteOk = false;

  if (m_slowFilterCode < 0) {
    m_configWriteOk = true;
    m_runtimeDiagnostics.configWriteOk = true;
    return true;
  }

  if (!m_wire) m_wire = I2CManager::bus(m_busIndex);
  if (!m_wire) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusUnavailable);
    m_nextConfigWriteMs = millis() + kDeviceConfigRetryMs;
    if (m_asyncLoggingActive && !m_runtimeConfigFailureActive) {
      m_runtimeConfigFailureActive = true;
      recordRuntimeEvent_(SensorRuntimeEventType::ConfigWriteFailed);
    }
    return false;
  }
  if (!I2CManager::lock(m_wire)) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusLock);
    m_nextConfigWriteMs = millis() + kDeviceConfigRetryMs;
    if (m_asyncLoggingActive && !m_runtimeConfigFailureActive) {
      m_runtimeConfigFailureActive = true;
      recordRuntimeEvent_(SensorRuntimeEventType::ConfigWriteFailed);
    }
    return false;
  }

  uint8_t confBytes[2] = {0, 0};
  bool ok = readRegBytesLocked_(kConfMsbReg, confBytes, sizeof(confBytes));
  const uint16_t oldConf = ok ? decode16_(confBytes[0], confBytes[1]) : 0;
  uint16_t newConf = oldConf;
  if (ok) m_runtimeDiagnostics.configBefore = oldConf;
  if (ok) {
    newConf = (uint16_t)((oldConf & ~kConfSlowFilterMask) |
                         ((uint16_t(m_slowFilterCode) << kConfSlowFilterShift) & kConfSlowFilterMask));
    if (newConf != oldConf) {
      const uint8_t outBytes[2] = {
        (uint8_t)((newConf >> 8) & 0xFFu),
        (uint8_t)(newConf & 0xFFu),
      };
      ok = writeRegBytesLocked_(kConfMsbReg, outBytes, sizeof(outBytes));
    }
  }
  I2CManager::unlock(m_wire);

  if (!ok) {
    m_nextConfigWriteMs = millis() + kDeviceConfigRetryMs;
    m_runtimeDiagnostics.initializationFailure = m_lastRuntimeFailure;
    if (m_asyncLoggingActive && !m_runtimeConfigFailureActive) {
      m_runtimeConfigFailureActive = true;
      recordRuntimeEvent_(SensorRuntimeEventType::ConfigWriteFailed);
    }
    AS5600I2C_LOGW("sensor '%s': slow_filter=%s volatile config write failed at 0x%02X on bus %u\n",
                   name(),
                   as5600SlowFilterName_((uint8_t)m_slowFilterCode),
                   (unsigned)m_i2cAddr,
                   (unsigned)m_busIndex);
    return false;
  }

  m_configWriteOk = true;
  m_runtimeDiagnostics.configWriteOk = true;
  m_runtimeDiagnostics.configAfter = newConf;
  if (m_asyncLoggingActive && m_runtimeConfigFailureActive) {
    m_runtimeConfigFailureActive = false;
    recordRuntimeEvent_(SensorRuntimeEventType::ConfigWriteRecovered);
  }
  m_nextConfigWriteMs = 0;
  m_deviceConfigReadOk = false;
  m_nextDeviceConfigReadMs = 0;
  AS5600I2C_LOGI("sensor '%s': slow_filter=%s volatile config conf 0x%04X -> 0x%04X\n",
                 name(),
                 as5600SlowFilterName_((uint8_t)m_slowFilterCode),
                 (unsigned)oldConf,
                 (unsigned)newConf);
  return true;
}

bool AS5600StringPotI2C::maybeApplyVolatileConfig_() const {
  if (m_slowFilterCode < 0 || m_configWriteOk) return true;
  if (m_asyncLoggingActive) return false;

  const uint32_t now = millis();
  if (m_nextConfigWriteMs != 0 &&
      (int32_t)(now - m_nextConfigWriteMs) < 0) return false;
  return applyVolatileConfig_();
}

bool AS5600StringPotI2C::readDeviceConfig_() const {
  m_deviceConfigReadAttempted = true;
  m_deviceConfigReadOk = false;
  m_runtimeDiagnostics.configReadAttempted = true;
  m_runtimeDiagnostics.configReadOk = false;

  if (!m_wire) m_wire = I2CManager::bus(m_busIndex);
  if (!m_wire) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusUnavailable);
    m_nextDeviceConfigReadMs = millis() + kDeviceConfigRetryMs;
    if (!m_asyncLoggingActive) m_runtimeDiagnostics.initializationFailure = m_lastRuntimeFailure;
    return false;
  }
  if (!I2CManager::lock(m_wire)) {
    setRuntimeFailure_(SensorRuntimeFailureStage::BusLock);
    m_nextDeviceConfigReadMs = millis() + kDeviceConfigRetryMs;
    if (!m_asyncLoggingActive) m_runtimeDiagnostics.initializationFailure = m_lastRuntimeFailure;
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
    if (!m_asyncLoggingActive) m_runtimeDiagnostics.initializationFailure = m_lastRuntimeFailure;
    AS5600I2C_LOGW("sensor '%s': read-only config snapshot failed at 0x%02X on bus %u\n",
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
  m_runtimeDiagnostics.configReadOk = true;
  m_runtimeDiagnostics.configAfter = m_configConf;
  m_nextDeviceConfigReadMs = 0;
  return true;
}

bool AS5600StringPotI2C::maybeRefreshDeviceConfig_() const {
  if (m_deviceConfigReadOk) return true;
  const uint32_t now = millis();
  if (m_nextDeviceConfigReadMs != 0 &&
      (int32_t)(now - m_nextDeviceConfigReadMs) < 0) return false;
  return readDeviceConfig_();
}

void AS5600StringPotI2C::logFailureProbe_() const {
  if (m_warnedFailureProbe) return;
  m_warnedFailureProbe = true;

  if (!m_wire) m_wire = I2CManager::bus(m_busIndex);
  if (!m_wire) return;
  if (!I2CManager::lock(m_wire, 20)) {
    AS5600I2C_LOGW("sensor '%s': failure probe could not lock I2C bus %u\n",
                   name(), (unsigned)m_busIndex);
    return;
  }

  m_wire->beginTransmission(m_i2cAddr);
  const uint8_t pingConfigured = (uint8_t)m_wire->endTransmission(true);
  m_wire->beginTransmission(0x36);
  const uint8_t pingDefault = (uint8_t)m_wire->endTransmission(true);

  uint8_t bytes[2] = {0, 0};
  const bool readOk = readRegBytesLocked_(kRawAngleMsbReg, bytes, sizeof(bytes));
  I2CManager::unlock(m_wire);

  AS5600I2C_LOGW("sensor '%s': failure probe bus%u addr=0x%02X ping_configured=%u ping_0x36=%u raw2{ok=%d bytes=%02X %02X raw=%u}\n",
                 name(),
                 (unsigned)m_busIndex,
                 (unsigned)m_i2cAddr,
                 (unsigned)pingConfigured,
                 (unsigned)pingDefault,
                 readOk ? 1 : 0,
                 (unsigned)bytes[0],
                 (unsigned)bytes[1],
                 (unsigned)decode12_(bytes[0], bytes[1]));
}

int AS5600StringPotI2C::readWrappedCountsOnce() const {
  if (m_asyncLoggingActive) {
    AsyncSnapshot snapshot;
    const bool have = copyAsyncSnapshot_(snapshot);
    const uint64_t nowUs = (uint64_t)esp_timer_get_time();
    const uint32_t ageUs = (have && nowUs >= snapshot.acquiredUs)
      ? (uint32_t)(nowUs - snapshot.acquiredUs)
      : 0;
    const bool fresh = have && snapshot.seq != m_asyncLastLoggedSeq;
    if (have) m_asyncLastLoggedSeq = snapshot.seq;
    I2CBusScheduler::recordRowUse((I2CAsyncClient*)this, ageUs, fresh, have);

    if (have) return snapshot.wrapped;
    return m_haveLastGoodWrapped ? m_lastGoodWrapped : 0;
  }

  int wrapped = 0;
  (void)readWrappedCountsDirectOnce_(wrapped);
  return wrapped;
}

bool AS5600StringPotI2C::readWrappedCountsDirectOnce_(int& wrapped) const {
  wrapped = m_haveLastGoodWrapped ? m_lastGoodWrapped : 0;

  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) {
    if (!m_warnedNoBus) {
      AS5600I2C_LOGW("sensor '%s': skipping read, I2C bus %u unavailable\n",
                     name(), (unsigned)m_busIndex);
      m_warnedNoBus = true;
    }
    m_lastReadOk = false;
    m_lastReadReused = m_haveLastGoodWrapped;
    setRuntimeFailure_(SensorRuntimeFailureStage::BusUnavailable);
    m_lastRawRuntimeFailure = m_lastRuntimeFailure;
    ++m_readFailures;
    return false;
  }

  const uint32_t now = millis();
  maybeApplyVolatileConfig_();
  if (m_nextReadAttemptMs != 0 &&
      (int32_t)(now - m_nextReadAttemptMs) < 0) {
    m_lastReadOk = false;
    m_lastReadReused = m_haveLastGoodWrapped;
    return false;
  }

  for (uint8_t attempt = 0; attempt < 3; ++attempt) {
    if (readWrappedCounts_(wrapped)) {
      m_warnedRead = false;
      m_lastGoodWrapped = wrapped;
      m_haveLastGoodWrapped = true;
      m_lastReadOk = true;
      m_lastReadReused = false;
      m_nextReadAttemptMs = 0;
      refreshDiagnostics_(false);
      maybeRefreshDeviceConfig_();
      return true;
    }
    delayMicroseconds(150);
  }

  m_lastRawRuntimeFailure = m_lastRuntimeFailure;

  if (!m_warnedRead) {
    AS5600I2C_LOGW("sensor '%s': read failed at 0x%02X on bus %u; reusing last good sample\n",
                   name(), (unsigned)m_i2cAddr, (unsigned)m_busIndex);
    m_warnedRead = true;
    logFailureProbe_();
  }
  m_lastReadOk = false;
  m_lastReadReused = m_haveLastGoodWrapped;
  ++m_readFailures;
  m_nextReadAttemptMs = now + (m_haveLastGoodWrapped ? 250UL : 1000UL);
  wrapped = m_haveLastGoodWrapped ? m_lastGoodWrapped : 0;
  return false;
}

void AS5600StringPotI2C::resetAsyncSnapshot_() const {
  AsyncSnapshot empty;
#if defined(ESP32)
  portENTER_CRITICAL(&m_asyncMux);
  m_asyncSnapshot = empty;
  portEXIT_CRITICAL(&m_asyncMux);
#else
  m_asyncSnapshot = empty;
#endif
}

void AS5600StringPotI2C::publishAsyncSnapshot_(const AsyncSnapshot& snapshot) const {
#if defined(ESP32)
  portENTER_CRITICAL(&m_asyncMux);
  m_asyncSnapshot = snapshot;
  portEXIT_CRITICAL(&m_asyncMux);
#else
  m_asyncSnapshot = snapshot;
#endif
}

bool AS5600StringPotI2C::copyAsyncSnapshot_(AsyncSnapshot& snapshot) const {
#if defined(ESP32)
  portENTER_CRITICAL(&m_asyncMux);
  snapshot = m_asyncSnapshot;
  portEXIT_CRITICAL(&m_asyncMux);
#else
  snapshot = m_asyncSnapshot;
#endif
  return snapshot.have;
}

bool AS5600StringPotI2C::acquireAsyncSample_() const {
  int wrapped = 0;
  const bool readOk = readWrappedCountsDirectOnce_(wrapped);

  AsyncSnapshot snapshot;
  snapshot.have = readOk || m_haveLastGoodWrapped;
  snapshot.readOk = m_lastReadOk;
  snapshot.reused = m_lastReadReused;
  snapshot.wrapped = snapshot.have ? wrapped : 0;
  snapshot.haveDiagnostics = m_haveDiagnostics;
  snapshot.status = m_lastStatus;
  snapshot.agc = m_lastAgc;
  snapshot.magnitude = m_lastMagnitude;
  snapshot.readFailures = m_readFailures;
  snapshot.diagnosticReadFailures = m_diagnosticReadFailures;
  snapshot.seq = ++m_asyncNextSeq;
  snapshot.acquiredUs = (uint64_t)esp_timer_get_time();
  updateReadTransition_(snapshot.readOk);

  if (m_includeAngleColumn) {
    uint16_t angle = 0;
    snapshot.haveAngle = readAngleRegister_(angle);
    snapshot.angle = angle;
  } else {
    snapshot.haveAngle = false;
    snapshot.angle = (uint16_t)snapshot.wrapped;
  }

  publishAsyncSnapshot_(snapshot);
  return snapshot.readOk;
}

uint8_t AS5600StringPotI2C::columnCount() const {
  uint8_t count = AS5600StringPotSensorBase::columnCount();
  if (m_includeAngleColumn) ++count;
  if (m_includeDiagColumns) count += kDiagnosticColumnCount;
  return count;
}

void AS5600StringPotI2C::getColumnName(uint8_t idx, char* out, size_t cap) const {
  const uint8_t baseCount = AS5600StringPotSensorBase::columnCount();
  if (idx < baseCount) {
    AS5600StringPotSensorBase::getColumnName(idx, out, cap);
    return;
  }
  if (!out || cap < 2) return;
  out[0] = '\0';

  uint8_t next = baseCount;
  if (m_includeAngleColumn) {
    if (idx == next) {
      String s = String(name()) + "_angle [counts]";
      s.toCharArray(out, cap);
      return;
    }
    ++next;
  }

  if (m_includeDiagColumns && idx >= next && idx < next + kDiagnosticColumnCount) {
    String s = String(name());
    switch (idx - next) {
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

void AS5600StringPotI2C::sampleValues(float* out, uint8_t max) {
  if (!out || max == 0 || muted()) return;

  const uint8_t baseCount = AS5600StringPotSensorBase::columnCount();
  AS5600StringPotSensorBase::sampleValues(out, max);
  uint8_t w = baseCount;

  AsyncSnapshot snapshot;
  const bool haveAsync = m_asyncLoggingActive && copyAsyncSnapshot_(snapshot);
  if (m_includeAngleColumn && w < max) {
    if (m_asyncLoggingActive) {
      out[w++] = (haveAsync && snapshot.haveAngle) ? float(snapshot.angle) : NAN;
    } else {
      uint16_t angle = 0;
      out[w++] = readAngleRegister_(angle) ? float(angle) : NAN;
    }
  }

  if (!m_includeDiagColumns) return;
  if (!m_asyncLoggingActive) refreshDiagnostics_(false);
  const bool haveDiagnostics = m_asyncLoggingActive
    ? (haveAsync && snapshot.haveDiagnostics)
    : m_haveDiagnostics;
  const uint8_t agc = m_asyncLoggingActive ? snapshot.agc : m_lastAgc;
  const uint8_t status = m_asyncLoggingActive ? snapshot.status : m_lastStatus;
  const uint16_t magnitude = m_asyncLoggingActive ? snapshot.magnitude : m_lastMagnitude;
  const bool readOk = m_asyncLoggingActive ? (haveAsync && snapshot.readOk) : m_lastReadOk;
  const bool reused = m_asyncLoggingActive ? (haveAsync && snapshot.reused) : m_lastReadReused;
  const uint32_t readFailures = haveAsync ? snapshot.readFailures : m_readFailures;
  const uint32_t diagnosticFailures = haveAsync
    ? snapshot.diagnosticReadFailures
    : m_diagnosticReadFailures;

  if (w < max) out[w++] = haveDiagnostics ? float(agc) : NAN;
  if (w < max) out[w++] = haveDiagnostics ? float(status) : NAN;
  if (w < max) out[w++] = haveDiagnostics ? float(magnitude) : NAN;
  if (w < max) out[w++] = readOk ? 1.0f : 0.0f;
  if (w < max) out[w++] = reused ? 1.0f : 0.0f;
  if (w < max) out[w++] = float(readFailures);
  if (w < max) out[w++] = float(diagnosticFailures);
}

bool AS5600StringPotI2C::describeColumn(uint8_t idx, SensorColumnDescriptor& out) const {
  const uint8_t baseCount = AS5600StringPotSensorBase::columnCount();
  if (idx < baseCount) return AS5600StringPotSensorBase::describeColumn(idx, out);
  if (idx >= columnCount() || !Sensor::describeColumn(idx, out)) return false;

  uint8_t next = baseCount;
  if (m_includeAngleColumn) {
    if (idx == next) {
      copyField_(out.sensorName, sizeof(out.sensorName), name());
      out.outputMode = OutputMode::RAW;
      out.required = false;
      out.primary = false;
      out.raw = true;
      out.diagnostic = true;
      out.calibrated = false;
      out.end[0] = '\0';
      out.domain[0] = '\0';
      copyField_(out.source, sizeof(out.source), "as5600_angle_register");
      copyField_(out.quantity, sizeof(out.quantity), "angle");
      copyField_(out.unit, sizeof(out.unit), "counts");
      snprintf(out.columnId, sizeof(out.columnId), "%s_angle", name());
      copyField_(out.notes, sizeof(out.notes), "AS5600 ANGLE register readout");
      return true;
    }
    ++next;
  }

  if (!m_includeDiagColumns || idx < next || idx >= next + kDiagnosticColumnCount) return false;
  copyField_(out.sensorName, sizeof(out.sensorName), name());
  out.outputMode = OutputMode::RAW;
  out.required = false;
  out.primary = false;
  out.raw = true;
  out.diagnostic = true;
  out.calibrated = false;
  out.end[0] = '\0';
  out.domain[0] = '\0';
  copyField_(out.source, sizeof(out.source), "as5600_diagnostic");

  switch (idx - next) {
    case 0: copyField_(out.quantity, sizeof(out.quantity), "agc"); copyField_(out.unit, sizeof(out.unit), "counts"); break;
    case 1: copyField_(out.quantity, sizeof(out.quantity), "status"); copyField_(out.unit, sizeof(out.unit), "flags"); break;
    case 2: copyField_(out.quantity, sizeof(out.quantity), "mag"); copyField_(out.unit, sizeof(out.unit), "counts"); break;
    case 3: copyField_(out.quantity, sizeof(out.quantity), "read_ok"); copyField_(out.unit, sizeof(out.unit), "flags"); break;
    case 4: copyField_(out.quantity, sizeof(out.quantity), "reused"); copyField_(out.unit, sizeof(out.unit), "flags"); break;
    case 5: copyField_(out.quantity, sizeof(out.quantity), "read_failures"); copyField_(out.unit, sizeof(out.unit), "count"); break;
    case 6: copyField_(out.quantity, sizeof(out.quantity), "diag_failures"); copyField_(out.unit, sizeof(out.unit), "count"); break;
    default: return false;
  }
  snprintf(out.columnId, sizeof(out.columnId), "%s_%s", name(), out.quantity);
  copyField_(out.notes, sizeof(out.notes), "AS5600 diagnostic readout");
  return true;
}

bool AS5600StringPotI2C::describeSensorMetadata(SensorMetadataDescriptor& out) const {
  if (!AS5600StringPotSensorBase::describeSensorMetadata(out)) return false;
  copyField_(out.type, sizeof(out.type), "as5600_string_pot_i2c");
  out.hasDeviceConfig = true;
  copyField_(out.deviceConfig.kind, sizeof(out.deviceConfig.kind), "as5600_registers");
  copyField_(out.deviceConfig.policy, sizeof(out.deviceConfig.policy),
             (m_slowFilterCode >= 0) ? "volatile_write_then_read" : "read_only");
  copyField_(out.deviceConfig.status, sizeof(out.deviceConfig.status),
             m_deviceConfigReadOk ? "read_ok" : (m_deviceConfigReadAttempted ? "read_failed" : "not_read"));
  if (m_slowFilterCode >= 0) {
    copyField_(out.deviceConfig.requestedSlowFilter,
               sizeof(out.deviceConfig.requestedSlowFilter),
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
  copyField_(out.deviceConfig.confFastFilterThreshold,
             sizeof(out.deviceConfig.confFastFilterThreshold),
             as5600FastFilterThresholdName_((uint8_t)((m_configConf >> 10) & 0x07u)));
  out.deviceConfig.confWatchdog = ((m_configConf >> 13) & 0x01u) != 0;
  return true;
}

bool AS5600StringPotI2C::describeRuntimeDiagnostics(SensorRuntimeDiagnostics& out) const {
  out = m_runtimeDiagnostics;
  out.present = true;
  copyField_(out.sensorName, sizeof(out.sensorName), name());
  copyField_(out.kind, sizeof(out.kind), asyncClientKind());
  out.busIndex = m_busIndex;
  out.address = m_i2cAddr;
  out.configWriteAttempted = m_configWriteAttempted;
  out.configWriteOk = m_configWriteOk;
  out.configReadAttempted = m_deviceConfigReadAttempted;
  out.configReadOk = m_deviceConfigReadOk;
  out.rawReadFailures = m_readFailures - m_runtimeSessionReadFailureBase;
  out.diagnosticReadFailures =
    m_diagnosticReadFailures - m_runtimeSessionDiagnosticFailureBase;
  out.haveLastGoodRaw = m_haveLastGoodWrapped;
  out.lastReadOk = m_lastReadOk;
  out.lastReadReused = m_lastReadReused;
  out.lastGoodRaw = m_haveLastGoodWrapped ? (uint16_t)m_lastGoodWrapped : 0;
  out.lastConf = m_deviceConfigReadOk ? m_configConf : out.configAfter;
  out.lastFailure =
    (out.rawReadFailures > 0 || !m_lastReadOk)
      ? m_lastRawRuntimeFailure
      : SensorRuntimeFailure{};
  return true;
}

const ParamDef* AS5600StringPotI2C::paramDefs(size_t& count) {
  static const ParamDef defs[] = {
    {"i2c_bus",              ParamType::Enum,  "0",     nullptr, nullptr, "0,1",  "I2C bus index"},
    {"i2c_addr",             ParamType::Int,   "54",    "1",    "127",  nullptr, "I2C address in decimal (default 54 = 0x36)"},
    {"slow_filter",          ParamType::Enum,  "2x",    nullptr, nullptr, "unchanged,16x,8x,4x,2x", "Volatile AS5600 slow filter setting; not burned to OTP"},
    {"async_rate_hz",        ParamType::Int,   "0",     "0",    "1000", nullptr, "Async I2C acquisition rate; 0 follows logger sample rate"},
    {"include_angle",        ParamType::Bool,  "false", nullptr, nullptr, nullptr, "Append AS5600 ANGLE register counts for diagnostics"},
    {"include_diag",         ParamType::Bool,  "false", nullptr, nullptr, nullptr, "Append AS5600 magnetic diagnostics, read state, and failure counters"},
    {"diag_interval_ms",     ParamType::Int,   "250",   "0",    "5000", nullptr, "Minimum interval between AS5600 diagnostic reads"},
    {"counts_per_turn",      ParamType::Int,   "4096",  "2",    "32767", nullptr, "Wrapped counts per AS5600 turn"},
    {"wrap_threshold_counts",ParamType::Int,   "2048",  "1",    "32767", nullptr, "Delta threshold used to detect wrap crossings"},
    {"sensor_zero_count",    ParamType::Int,   "0",     nullptr, nullptr, nullptr, "Unwrapped counts at zero travel"},
    {"sensor_full_count",    ParamType::Int,   "4095",  nullptr, nullptr, nullptr, "Unwrapped counts at full travel"},
    {"sensor_full_travel_mm",ParamType::Float, "0",     "0",    nullptr, nullptr, "Full sensor travel in mm for RANGE scaling"},
    {"installed_range",      ParamType::Float, "0",     "0",    nullptr, nullptr, "Installed range in linear output units for sag percentage"},
    {"installed_zero_count", ParamType::Int,   "0",     nullptr, nullptr, nullptr, "Installed zero point in unwrapped counts"},
    {"assume_turn0_at_start",ParamType::Bool,  "true",  nullptr, nullptr, nullptr, "Reset unwrap state to turn 0 at each logging start"},
    {"output_mode",          ParamType::Enum,  "1",     nullptr, nullptr, "RAW,LINEAR", "Output method: wrapped RAW counts or linear mm"},
    {"include_raw",          ParamType::Bool,  "true",  nullptr, nullptr, nullptr, "Append wrapped and unwrapped RAW columns"},
    {"end",                  ParamType::Enum,  "",      nullptr, nullptr, "front,rear", "Optional semantic end for log metadata"},
    {"primary_domain",       ParamType::Enum,  "",      nullptr, nullptr, "wheel,suspension,brake,drivetrain,frame,steering", "Optional semantic domain for primary output"},
    {"primary_quantity",     ParamType::Enum,  "",      nullptr, nullptr, "disp,ang_disp,force,pressure,temp,voltage,norm", "Optional semantic quantity for primary output"},
  };

  count = sizeof(defs) / sizeof(defs[0]);
  return defs;
}

Sensor* AS5600StringPotI2C::create(const char* instanceName, const ParamPack& params, bool mutedDefault) {
  Params p;
  loadParamsFromPack_(p, instanceName, params);

  auto* obj = new AS5600StringPotI2C(p);
  obj->setMuted(mutedDefault);
  return obj;
}

static bool _reg_as5600_i2c =
  SensorRegistry::registerType(
    SensorType::AS5600StringPotI2C,
    "as5600_string_pot_i2c",
    "AS5600 String Pot (I2C)",
    &AS5600StringPotI2C::paramDefs,
    &AS5600StringPotI2C::create,
    (CalModeMask)(CAL_ZERO | CAL_RANGE)
  );
