#include "DANF10NGpsSensor.h"

#include <Arduino.h>
#include <HardwareSerial.h>
#include <SparkFun_u-blox_GNSS_v3.h>
#include <math.h>
#include <string.h>

#include "BoardSelect.h"
#include "ConfigManager.h"
#include "DebugLog.h"
#include "SensorRegistry.h"

#define GPS_LOGI(...) LOGI_TAG("GPS", __VA_ARGS__)
#define GPS_LOGW(...) LOGW_TAG("GPS", __VA_ARGS__)

namespace {

static constexpr uint8_t kDanf10nMaxUpdateHz = 10;
static constexpr uint32_t kTaskRetryMs = 1000;
static constexpr uint32_t kTaskIdleMs = 5;

void copyField_(char* dst, size_t cap, const char* src) {
  if (!dst || cap == 0) return;
  if (!src) src = "";
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

void writeColumnLabel_(const char* name, const char* suffix, const char* units, char* out, size_t cap) {
  if (!out || cap < 2) return;
  out[0] = '\0';
  String s = name ? String(name) : String("gps");
  if (suffix && suffix[0]) {
    s += "_";
    s += suffix;
  }
  if (units && units[0]) {
    s += " [";
    s += units;
    s += "]";
  }
  s.toCharArray(out, cap);
}

DANF10NGpsSensor::QualityColumns parseQualityColumns_(const String& value) {
  String s = value;
  s.trim();
  s.toLowerCase();
  if (s == "full" || s == "2") return DANF10NGpsSensor::QualityColumns::Full;
  if (s == "none" || s == "off" || s == "0") return DANF10NGpsSensor::QualityColumns::None;
  return DANF10NGpsSensor::QualityColumns::Minimal;
}

DANF10NGpsSensor::ValidityPolicy parseValidityPolicy_(const String& value) {
  String s = value;
  s.trim();
  s.toLowerCase();
  s.replace("-", "_");
  if (s == "latest" || s == "latest_with_status" || s == "status" || s == "1") {
    return DANF10NGpsSensor::ValidityPolicy::LatestWithStatus;
  }
  if (s == "fresh" || s == "fresh_only" || s == "2") {
    return DANF10NGpsSensor::ValidityPolicy::FreshOnly;
  }
  return DANF10NGpsSensor::ValidityPolicy::ValidOnly;
}

uint8_t clampUpdateRate_(long value) {
  if (value <= 1) return 1;
  if (value <= 2) return 2;
  if (value <= 5) return 5;
  return kDanf10nMaxUpdateHz;
}

void loadParamsFromPack_(DANF10NGpsSensor::Params& p,
                         const char* instanceName,
                         const ParamPack& params) {
  p.name = instanceName ? instanceName : "gps";

  long li = 0;
  bool b = false;
  String s;

  if (params.getInt("uart_port", li)) p.uartPort = (li < 0) ? 0u : (uint8_t)li;
  if (params.getInt("baud", li)) p.baud = (li <= 0) ? 38400UL : (uint32_t)li;
  if (params.getInt("update_rate_hz", li)) p.updateRateHz = clampUpdateRate_(li);
  if (params.getInt("stale_after_ms", li)) p.staleAfterMs = (li < 0) ? 0UL : (uint32_t)li;
  if (params.getInt("begin_max_wait_ms", li)) p.beginMaxWaitMs = (li < 0) ? 0u : (uint16_t)li;
  if (params.getInt("config_max_wait_ms", li)) p.configMaxWaitMs = (li < 0) ? 0u : (uint16_t)li;
  if (params.getInt("rx_buffer_bytes", li)) p.rxBufferBytes = (li < 256) ? 256u : (uint16_t)li;
  if (params.get("quality_columns", s)) p.qualityColumns = parseQualityColumns_(s);
  if (params.get("validity_policy", s)) p.validityPolicy = parseValidityPolicy_(s);
  if (params.getBool("emit_position", b)) p.emitPosition = b;
  if (params.getBool("emit_altitude", b)) p.emitAltitude = b;
  if (params.getBool("emit_motion", b)) p.emitMotion = b;
}

const char* suffixForColumn_(DANF10NGpsSensor::ColumnKind kind) {
  using K = DANF10NGpsSensor::ColumnKind;
  switch (kind) {
    case K::LatDeg: return "lat";
    case K::LonDeg: return "lon";
    case K::AltM: return "alt";
    case K::SpeedMps: return "speed";
    case K::HeadingDeg: return "heading";
    case K::Valid: return "valid";
    case K::AgeMs: return "age";
    case K::Seq: return "seq";
    case K::Fresh: return "fresh";
    case K::FixType: return "fix_type";
    case K::Satellites: return "sats";
    case K::HAccM: return "hacc";
    case K::VAccM: return "vacc";
    default: return "value";
  }
}

const char* unitForColumn_(DANF10NGpsSensor::ColumnKind kind) {
  using K = DANF10NGpsSensor::ColumnKind;
  switch (kind) {
    case K::LatDeg:
    case K::LonDeg:
    case K::HeadingDeg: return "deg";
    case K::AltM:
    case K::HAccM:
    case K::VAccM: return "m";
    case K::SpeedMps: return "m/s";
    case K::AgeMs: return "ms";
    case K::Seq: return "count";
    case K::Valid:
    case K::Fresh:
    case K::FixType:
    case K::Satellites:
    default: return "";
  }
}

const char* quantityForColumn_(DANF10NGpsSensor::ColumnKind kind) {
  using K = DANF10NGpsSensor::ColumnKind;
  switch (kind) {
    case K::LatDeg: return "position_latitude";
    case K::LonDeg: return "position_longitude";
    case K::AltM: return "altitude";
    case K::SpeedMps: return "speed";
    case K::HeadingDeg: return "heading";
    case K::Valid: return "valid";
    case K::AgeMs: return "age";
    case K::Seq: return "seq";
    case K::Fresh: return "fresh";
    case K::FixType: return "fix_type";
    case K::Satellites: return "satellites";
    case K::HAccM: return "horizontal_accuracy";
    case K::VAccM: return "vertical_accuracy";
    default: return "value";
  }
}

bool isQcColumn_(DANF10NGpsSensor::ColumnKind kind) {
  using K = DANF10NGpsSensor::ColumnKind;
  switch (kind) {
    case K::Valid:
    case K::AgeMs:
    case K::Seq:
    case K::Fresh:
    case K::FixType:
    case K::Satellites:
    case K::HAccM:
    case K::VAccM:
      return true;
    case K::LatDeg:
    case K::LonDeg:
    case K::AltM:
    case K::SpeedMps:
    case K::HeadingDeg:
    default:
      return false;
  }
}

} // namespace

DANF10NGpsSensor::DANF10NGpsSensor(const Params& p) {
  applyParams(p);
}

void DANF10NGpsSensor::applyParams(const Params& p) {
  if (p.name && p.name[0]) {
    strncpy(m_name, p.name, sizeof(m_name) - 1);
    m_name[sizeof(m_name) - 1] = '\0';
  }
  m_uartPort = p.uartPort;
  m_baud = p.baud ? p.baud : 38400UL;
  m_updateRateHz = clampUpdateRate_(p.updateRateHz);
  m_staleAfterMs = p.staleAfterMs;
  m_beginMaxWaitMs = p.beginMaxWaitMs;
  m_configMaxWaitMs = p.configMaxWaitMs;
  m_rxBufferBytes = p.rxBufferBytes;
  m_qualityColumns = p.qualityColumns;
  m_validityPolicy = p.validityPolicy;
  m_emitPosition = p.emitPosition;
  m_emitAltitude = p.emitAltitude;
  m_emitMotion = p.emitMotion;
}

void DANF10NGpsSensor::begin() {
#if defined(ESP32)
  if (!m_mutex) {
    m_mutex = xSemaphoreCreateMutex();
  }
#endif

  m_initialized = false;
  m_warnedNoUart = false;
  m_warnedInit = false;
  m_snapshot = Snapshot{};
  m_nextSeq = 0;
  m_lastLoggedSeq = 0;

  if (m_muted) return;
  if (!startSerial_()) return;
  (void)startTask_();
}

bool DANF10NGpsSensor::reconfigureFromSpec(const SensorSpec& spec) {
  if (spec.type != SensorType::DANF10NGps) return false;
  Params p;
  loadParamsFromPack_(p, spec.name, spec.params);
  applyParams(p);
  begin();
  return true;
}

HardwareSerial* DANF10NGpsSensor::serialForPort_(uint8_t port) {
  switch (port) {
    case 0: return &Serial1;
    case 1: return &Serial2;
    default: return nullptr;
  }
}

bool DANF10NGpsSensor::startSerial_() {
  if (!board::gBoard) {
    GPS_LOGW("sensor '%s': no board profile available for UART\n", name());
    return false;
  }
  if (m_uartPort >= board::gBoard->uart_count || m_uartPort >= board::BOARD_MAX_UART_PORTS ||
      !board::gBoard->uart[m_uartPort].present) {
    if (!m_warnedNoUart) {
      GPS_LOGW("sensor '%s': UART%u not present in board profile\n",
               name(), (unsigned)m_uartPort);
      m_warnedNoUart = true;
    }
    return false;
  }

  const auto& uart = board::gBoard->uart[m_uartPort];
  if (uart.rx < 0 || uart.tx < 0) {
    GPS_LOGW("sensor '%s': UART%u invalid pins TX=%d RX=%d\n",
             name(), (unsigned)m_uartPort, (int)uart.tx, (int)uart.rx);
    return false;
  }

  m_serial = serialForPort_(m_uartPort);
  if (!m_serial) {
    GPS_LOGW("sensor '%s': no HardwareSerial instance for UART%u\n",
             name(), (unsigned)m_uartPort);
    return false;
  }

#if defined(ESP32)
  if (m_rxBufferBytes >= 256) {
    m_serial->setRxBufferSize(m_rxBufferBytes);
  }
#endif
  m_serial->begin(m_baud, SERIAL_8N1, uart.rx, uart.tx);
  GPS_LOGI("sensor '%s': UART%u TX=%d RX=%d baud=%lu update=%uHz stale=%lu ms\n",
           name(),
           (unsigned)m_uartPort,
           (int)uart.tx,
           (int)uart.rx,
           (unsigned long)m_baud,
           (unsigned)m_updateRateHz,
           (unsigned long)m_staleAfterMs);
  return true;
}

bool DANF10NGpsSensor::startTask_() {
#if defined(ESP32)
  if (m_task) return true;
  m_taskRun = true;
  const BaseType_t ok = xTaskCreatePinnedToCore(
    &DANF10NGpsSensor::taskThunk_,
    "GpsTask",
    6144,
    this,
    1,
    &m_task,
    1);
  if (ok != pdPASS) {
    GPS_LOGW("sensor '%s': failed to start GPS task\n", name());
    m_task = nullptr;
    m_taskRun = false;
    return false;
  }
  return true;
#else
  return false;
#endif
}

void DANF10NGpsSensor::taskThunk_(void* arg) {
  DANF10NGpsSensor* self = static_cast<DANF10NGpsSensor*>(arg);
  if (self) self->taskLoop_();
#if defined(ESP32)
  vTaskDelete(nullptr);
#endif
}

void DANF10NGpsSensor::taskLoop_() {
#if defined(ESP32)
  while (m_taskRun) {
    if (!m_initialized) {
      if (!initializeGnss_()) {
        vTaskDelay(pdMS_TO_TICKS(kTaskRetryMs));
        continue;
      }
    }

    if (m_gnss && m_gnss->getPVT(0)) {
      updateSnapshotFromGnss_();
    } else {
      vTaskDelay(pdMS_TO_TICKS(kTaskIdleMs));
    }
  }
#endif
}

bool DANF10NGpsSensor::initializeGnss_() {
  if (!m_serial) return false;
  if (!m_gnss) {
    m_gnss = new SFE_UBLOX_GNSS_SERIAL();
    if (!m_gnss) {
      GPS_LOGW("sensor '%s': GNSS object allocation failed\n", name());
      return false;
    }
  }

  if (!m_gnss->begin(*m_serial, m_beginMaxWaitMs)) {
    if (!m_warnedInit) {
      GPS_LOGW("sensor '%s': DAN-F10N not detected on UART%u; retrying in background\n",
               name(), (unsigned)m_uartPort);
      m_warnedInit = true;
    }
    return false;
  }

  const bool outputOk = m_gnss->setUART1Output(COM_TYPE_UBX, VAL_LAYER_RAM, m_configMaxWaitMs);
  const bool rateOk = m_gnss->setNavigationFrequency(m_updateRateHz, VAL_LAYER_RAM, m_configMaxWaitMs);
  const bool autoOk = m_gnss->setAutoPVT(true, VAL_LAYER_RAM, m_configMaxWaitMs);
  if (!outputOk || !rateOk || !autoOk) {
    GPS_LOGW("sensor '%s': GNSS config partial failure output=%u rate=%u autoPVT=%u\n",
             name(),
             outputOk ? 1u : 0u,
             rateOk ? 1u : 0u,
             autoOk ? 1u : 0u);
  }

  m_initialized = true;
  m_warnedInit = false;
  GPS_LOGI("sensor '%s': DAN-F10N ready UART%u update=%uHz\n",
           name(), (unsigned)m_uartPort, (unsigned)m_updateRateHz);
  return true;
}

void DANF10NGpsSensor::updateSnapshotFromGnss_() {
  if (!m_gnss) return;

  Snapshot s;
  s.have = true;
  s.fixOk = m_gnss->getGnssFixOk(0);
  s.invalidLlh = m_gnss->getInvalidLlh(0);
  s.fixType = m_gnss->getFixType(0);
  s.satellites = m_gnss->getSIV(0);
  s.latE7 = m_gnss->getLatitude(0);
  s.lonE7 = m_gnss->getLongitude(0);
  s.altMslMm = m_gnss->getAltitudeMSL(0);
  s.groundSpeedMmS = m_gnss->getGroundSpeed(0);
  s.headingDegE5 = m_gnss->getHeading(0);
  s.hAccMm = m_gnss->getHorizontalAccEst(0);
  s.vAccMm = m_gnss->getVerticalAccEst(0);
  s.speedAccMmS = m_gnss->getSpeedAccEst(0);
  s.headingAccDegE5 = m_gnss->getHeadingAccEst(0);
  s.gpsTowMs = m_gnss->getTimeOfWeek(0);
  s.gpsUnixSeconds = m_gnss->getUnixEpoch(0);
  s.receivedMs = millis();
  s.valid = s.fixOk && !s.invalidLlh && s.fixType >= 2;
  s.seq = ++m_nextSeq;

#if defined(ESP32)
  if (m_mutex && xSemaphoreTake(m_mutex, portMAX_DELAY) == pdTRUE) {
    m_snapshot = s;
    xSemaphoreGive(m_mutex);
  }
#else
  m_snapshot = s;
#endif
}

bool DANF10NGpsSensor::copySnapshot_(Snapshot& out) const {
#if defined(ESP32)
  if (m_mutex) {
    if (xSemaphoreTake(m_mutex, 0) != pdTRUE) return false;
    out = m_snapshot;
    xSemaphoreGive(m_mutex);
    return out.have;
  }
#endif
  out = m_snapshot;
  return out.have;
}

uint32_t DANF10NGpsSensor::snapshotAgeMs_(const Snapshot& s, uint32_t nowMs) const {
  if (!s.have) return UINT32_MAX;
  return nowMs - s.receivedMs;
}

bool DANF10NGpsSensor::outputValueValid_(const Snapshot& s, uint32_t ageMs, bool fresh) const {
  if (!s.have) return false;
  const bool stale = (m_staleAfterMs != 0 && ageMs > m_staleAfterMs);
  switch (m_validityPolicy) {
    case ValidityPolicy::LatestWithStatus:
      return true;
    case ValidityPolicy::FreshOnly:
      return fresh && !stale && s.valid;
    case ValidityPolicy::ValidOnly:
    default:
      return !stale && s.valid;
  }
}

uint8_t DANF10NGpsSensor::collectColumns_(ColumnKind* out, uint8_t max) const {
  uint8_t n = 0;
  auto add = [&](ColumnKind k) {
    if (out && n < max) out[n] = k;
    ++n;
  };

  if (m_emitPosition) {
    add(ColumnKind::LatDeg);
    add(ColumnKind::LonDeg);
  }
  if (m_emitAltitude) {
    add(ColumnKind::AltM);
  }
  if (m_emitMotion) {
    add(ColumnKind::SpeedMps);
    add(ColumnKind::HeadingDeg);
  }

  if (m_qualityColumns != QualityColumns::None) {
    add(ColumnKind::Valid);
    add(ColumnKind::AgeMs);
  }
  if (m_qualityColumns == QualityColumns::Full) {
    add(ColumnKind::Seq);
    add(ColumnKind::Fresh);
    add(ColumnKind::FixType);
    add(ColumnKind::Satellites);
    add(ColumnKind::HAccM);
    add(ColumnKind::VAccM);
  }

  return n;
}

uint8_t DANF10NGpsSensor::columnCount() const {
  return collectColumns_(nullptr, 0);
}

void DANF10NGpsSensor::getColumnName(uint8_t idx, char* out, size_t cap) const {
  ColumnKind cols[16];
  const uint8_t n = collectColumns_(cols, sizeof(cols) / sizeof(cols[0]));
  if (idx >= n) {
    if (out && cap) out[0] = '\0';
    return;
  }
  writeColumnLabel_(name(), suffixForColumn_(cols[idx]), unitForColumn_(cols[idx]), out, cap);
}

float DANF10NGpsSensor::valueForColumn_(ColumnKind kind,
                                        const Snapshot& s,
                                        uint32_t ageMs,
                                        bool fresh,
                                        bool emitValue) const {
  using K = ColumnKind;
  switch (kind) {
    case K::Valid:
      return (s.have && s.valid && (m_staleAfterMs == 0 || ageMs <= m_staleAfterMs)) ? 1.0f : 0.0f;
    case K::AgeMs:
      return s.have ? float(ageMs) : NAN;
    case K::Seq:
      return s.have ? float(s.seq) : NAN;
    case K::Fresh:
      return fresh ? 1.0f : 0.0f;
    case K::FixType:
      return s.have ? float(s.fixType) : NAN;
    case K::Satellites:
      return s.have ? float(s.satellites) : NAN;
    case K::HAccM:
      return s.have ? float(s.hAccMm) * 0.001f : NAN;
    case K::VAccM:
      return s.have ? float(s.vAccMm) * 0.001f : NAN;
    default:
      break;
  }

  if (!emitValue) return NAN;

  switch (kind) {
    case K::LatDeg: return float(s.latE7) * 1.0e-7f;
    case K::LonDeg: return float(s.lonE7) * 1.0e-7f;
    case K::AltM: return float(s.altMslMm) * 0.001f;
    case K::SpeedMps: return float(s.groundSpeedMmS) * 0.001f;
    case K::HeadingDeg: return float(s.headingDegE5) * 1.0e-5f;
    default: return NAN;
  }
}

void DANF10NGpsSensor::sampleValues(float* out, uint8_t max) {
  if (!out || max == 0 || m_muted) return;

  ColumnKind cols[16];
  const uint8_t n = collectColumns_(cols, sizeof(cols) / sizeof(cols[0]));

  Snapshot s;
  const bool have = copySnapshot_(s);
  if (!have) s = Snapshot{};

  const uint32_t now = millis();
  const uint32_t ageMs = snapshotAgeMs_(s, now);
  const bool fresh = s.have && s.seq != m_lastLoggedSeq;
  const bool emitValue = outputValueValid_(s, ageMs, fresh);
  if (s.have) m_lastLoggedSeq = s.seq;

  const uint8_t limit = (n < max) ? n : max;
  for (uint8_t i = 0; i < limit; ++i) {
    out[i] = valueForColumn_(cols[i], s, ageMs, fresh, emitValue);
  }
}

void DANF10NGpsSensor::onLoggingStart() {
  Snapshot s;
  if (copySnapshot_(s)) {
    m_lastLoggedSeq = s.seq;
  } else {
    m_lastLoggedSeq = 0;
  }
}

bool DANF10NGpsSensor::describeColumn(uint8_t idx, SensorColumnDescriptor& out) const {
  if (idx >= columnCount()) return false;
  if (!Sensor::describeColumn(idx, out)) return false;

  ColumnKind cols[16];
  const uint8_t n = collectColumns_(cols, sizeof(cols) / sizeof(cols[0]));
  if (idx >= n) return false;
  const ColumnKind kind = cols[idx];
  const bool qc = isQcColumn_(kind);

  copyField_(out.sensorName, sizeof(out.sensorName), name());
  copyField_(out.domain, sizeof(out.domain), "world");
  copyField_(out.quantity, sizeof(out.quantity), quantityForColumn_(kind));
  copyField_(out.unit, sizeof(out.unit), unitForColumn_(kind));
  copyField_(out.source, sizeof(out.source), "async_snapshot");
  snprintf(out.columnId, sizeof(out.columnId), "%s_%s", name(), out.quantity);
  if (qc) {
    copyField_(out.kind, sizeof(out.kind), "qc");
    copyField_(out.processingRole, sizeof(out.processingRole), "qc_metric");
    out.semanticSelectionExcluded = true;
  }
  out.outputMode = OutputMode::RAW;
  out.required = false;
  out.primary = !qc && (idx == 0);
  out.raw = false;
  out.calibrated = false;
  out.transformed = false;
  copyField_(out.notes, sizeof(out.notes), "DAN-F10N async GPS snapshot");
  return true;
}

bool DANF10NGpsSensor::describeSensorMetadata(SensorMetadataDescriptor& out) const {
  out = SensorMetadataDescriptor{};
  copyField_(out.sensorId, sizeof(out.sensorId), name());
  copyField_(out.name, sizeof(out.name), name());
  copyField_(out.type, sizeof(out.type), "dan_f10n_gps_uart");
  copyField_(out.domain, sizeof(out.domain), "world");
  copyField_(out.rawUnit, sizeof(out.rawUnit), "");
  out.hasCalibration = false;
  out.hasTracking = false;
  return true;
}

bool DANF10NGpsSensor::gpsStatus(SensorGpsStatus& out) const {
  out = SensorGpsStatus{};

  if (m_muted || m_warnedNoUart || !m_serial) {
    out.state = SensorGpsState::Error;
    return true;
  }

#if defined(ESP32)
  if (!m_task) {
    out.state = SensorGpsState::Error;
    return true;
  }
#endif

  if (!m_initialized) {
    out.state = m_warnedInit ? SensorGpsState::Error : SensorGpsState::Acquiring;
    return true;
  }

  Snapshot s;
  if (!copySnapshot_(s)) {
    out.state = SensorGpsState::Acquiring;
    return true;
  }

  const uint32_t ageMs = snapshotAgeMs_(s, millis());
  const bool stale = (m_staleAfterMs != 0 && ageMs > m_staleAfterMs);
  out.valid = s.valid && !stale;
  out.satellites = s.satellites;
  out.fixType = s.fixType;
  out.ageMs = ageMs;
  out.state = out.valid ? SensorGpsState::Fixed : SensorGpsState::Acquiring;
  return true;
}

const ParamDef* DANF10NGpsSensor::paramDefs(size_t& count) {
  static const ParamDef defs[] = {
    {"uart_port",          ParamType::Enum,   "0",     nullptr, nullptr, "0,1", "Board UART port index"},
    {"baud",               ParamType::Int,    "38400", "9600",  "921600", nullptr, "UART baud rate; DAN-F10N default is 38400"},
    {"update_rate_hz",     ParamType::Enum,   "1",     nullptr, nullptr, "1,2,5,10", "GNSS navigation update rate"},
    {"stale_after_ms",     ParamType::Int,    "1500",  "0",     "10000", nullptr, "Snapshot age after which position/motion values become NaN; 0 disables stale filtering"},
    {"validity_policy",    ParamType::Enum,   "valid_only", nullptr, nullptr, "valid_only,latest_with_status,fresh_only", "Controls when position/motion values are emitted"},
    {"quality_columns",    ParamType::Enum,   "minimal", nullptr, nullptr, "none,minimal,full", "GPS status columns to append"},
    {"emit_position",      ParamType::Bool,   "true",  nullptr, nullptr, nullptr, "Emit latitude and longitude columns"},
    {"emit_altitude",      ParamType::Bool,   "true",  nullptr, nullptr, nullptr, "Emit altitude column"},
    {"emit_motion",        ParamType::Bool,   "true",  nullptr, nullptr, nullptr, "Emit speed and heading columns"},
    {"rx_buffer_bytes",    ParamType::Int,    "4096",  "256",   "8192", nullptr, "UART RX buffer size"},
    {"begin_max_wait_ms",  ParamType::Int,    "1000",  "0",     "5000", nullptr, "GNSS begin wait per background retry"},
    {"config_max_wait_ms", ParamType::Int,    "500",   "0",     "5000", nullptr, "GNSS configuration wait"},
  };
  count = sizeof(defs) / sizeof(defs[0]);
  return defs;
}

Sensor* DANF10NGpsSensor::create(const char* instanceName, const ParamPack& params, bool mutedDefault) {
  Params p;
  loadParamsFromPack_(p, instanceName, params);
  auto* obj = new DANF10NGpsSensor(p);
  obj->setMuted(mutedDefault);
  return obj;
}

static bool _reg_dan_f10n_gps =
  SensorRegistry::registerType(
    SensorType::DANF10NGps,
    "dan_f10n_gps_uart",
    "DAN-F10N GPS (UART)",
    &DANF10NGpsSensor::paramDefs,
    &DANF10NGpsSensor::create,
    CAL_NONE
  );
