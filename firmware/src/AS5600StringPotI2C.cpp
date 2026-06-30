#include "AS5600StringPotI2C.h"

#include <Arduino.h>
#include <Wire.h>
#include <math.h>

#include "ConfigManager.h"
#include "I2CManager.h"
#include "SensorRegistry.h"
#include "DebugLog.h"
#include "esp_timer.h"

#define AS5600I2C_LOGW(...) LOGW_TAG("AS5600", __VA_ARGS__)

namespace {

static constexpr uint8_t kAs5600RawAngleReg = 0x0C;
static constexpr uint16_t kMaxAsyncRateHz = 1000;

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
  if (params.getInt("async_rate_hz", li))            p.asyncRateHz = (li < 0) ? 0u : (uint16_t)li;
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
    m_asyncRateHz(p.asyncRateHz) {
  if (m_asyncRateHz > kMaxAsyncRateHz) m_asyncRateHz = kMaxAsyncRateHz;
}

void AS5600StringPotI2C::begin() {
  m_wire = I2CManager::bus(m_busIndex);
  m_warnedNoBus = false;
  m_warnedRead = false;
  m_haveLastGoodWrapped = false;
  m_lastGoodWrapped = 0;
  m_lastReadOk = false;
  m_lastReadReused = false;
  m_readFailures = 0;
  m_nextReadAttemptMs = 0;
  m_asyncLoggingActive = false;
  m_asyncNextSeq = 0;
  m_asyncLastLoggedSeq = 0;
  resetAsyncSnapshot_();
  I2CBusScheduler::registerClient(this);

  if (!m_wire) {
    AS5600I2C_LOGW("sensor '%s': I2C bus %u unavailable\n",
                   name(), (unsigned)m_busIndex);
  } else if (!probe_()) {
    AS5600I2C_LOGW("sensor '%s': no AS5600 response at 0x%02X on bus %u\n",
                   name(), (unsigned)m_i2cAddr, (unsigned)m_busIndex);
  }

  AS5600StringPotSensorBase::onLoggingStart();
}

bool AS5600StringPotI2C::reconfigureFromSpec(const SensorSpec& spec) {
  if (spec.type != SensorType::AS5600StringPotI2C) return false;

  Params p;
  loadParamsFromPack_(p, spec.name, spec.params);
  applyBaseParams(p);
  m_busIndex = p.busIndex;
  m_i2cAddr = p.i2cAddr ? p.i2cAddr : 0x36;
  m_asyncRateHz = p.asyncRateHz;
  if (m_asyncRateHz > kMaxAsyncRateHz) m_asyncRateHz = kMaxAsyncRateHz;
  begin();
  return true;
}

void AS5600StringPotI2C::onLoggingStart() {
  AS5600StringPotSensorBase::onLoggingStart();
  m_asyncLoggingActive = true;
  m_asyncNextSeq = 0;
  m_asyncLastLoggedSeq = 0;
  resetAsyncSnapshot_();
  (void)acquireAsyncSample_();
}

void AS5600StringPotI2C::onLoggingStop() {
  m_asyncLoggingActive = false;
  AS5600StringPotSensorBase::onLoggingStop();
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

bool AS5600StringPotI2C::probe_() const {
  if (!m_wire) return false;
  if (!I2CManager::lock(m_wire)) return false;
  m_wire->beginTransmission(m_i2cAddr);
  const bool ok = (m_wire->endTransmission(true) == 0);
  I2CManager::unlock(m_wire);
  return ok;
}

bool AS5600StringPotI2C::readReg16_(uint8_t reg, uint16_t& value) const {
  value = 0;
  if (!m_wire) {
    m_wire = I2CManager::bus(m_busIndex);
  }
  if (!m_wire) return false;
  if (!I2CManager::lock(m_wire)) return false;

  m_wire->beginTransmission(m_i2cAddr);
  m_wire->write(reg);
  if (m_wire->endTransmission(false) != 0) {
    I2CManager::unlock(m_wire);
    return false;
  }

  if (m_wire->requestFrom((int)m_i2cAddr, 2) != 2) {
    I2CManager::unlock(m_wire);
    return false;
  }

  const uint8_t msb = m_wire->read();
  const uint8_t lsb = m_wire->read();
  I2CManager::unlock(m_wire);
  value = (uint16_t(msb) << 8) | lsb;
  return true;
}

bool AS5600StringPotI2C::readWrappedCounts_(int& wrapped) const {
  wrapped = 0;
  uint16_t raw = 0;
  if (!readReg16_(kAs5600RawAngleReg, raw)) return false;
  wrapped = int(raw & 0x0FFFu);
  return true;
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
    ++m_readFailures;
    return false;
  }

  const uint32_t now = millis();
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
      return true;
    }
    delayMicroseconds(150);
  }

  if (!m_warnedRead) {
    AS5600I2C_LOGW("sensor '%s': read failed at 0x%02X on bus %u; reusing last good sample\n",
                   name(), (unsigned)m_i2cAddr, (unsigned)m_busIndex);
    m_warnedRead = true;
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
  snapshot.readFailures = m_readFailures;
  snapshot.seq = ++m_asyncNextSeq;
  snapshot.acquiredUs = (uint64_t)esp_timer_get_time();

  publishAsyncSnapshot_(snapshot);
  return snapshot.readOk;
}

const ParamDef* AS5600StringPotI2C::paramDefs(size_t& count) {
  static const ParamDef defs[] = {
    {"i2c_bus",              ParamType::Enum,  "0",     nullptr, nullptr, "0,1",  "I2C bus index"},
    {"i2c_addr",             ParamType::Int,   "54",    "1",    "127",  nullptr, "I2C address in decimal (default 54 = 0x36)"},
    {"async_rate_hz",        ParamType::Int,   "0",     "0",    "1000", nullptr, "Async I2C acquisition rate; 0 follows logger sample rate"},
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
