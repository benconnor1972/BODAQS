#include "BdqLogWriter.h"

#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <new>
#include "BoardProfile.h"
#include "FirmwareInfo.h"
#include "SensorManager.h"
#include "DebugLog.h"
#include "LoggerLimits.h"

#define BDQ_LOGE(...) LOGE_TAG("BDQ", __VA_ARGS__)
#define BDQ_LOGW(...) LOGW_TAG("BDQ", __VA_ARGS__)
#define BDQ_LOGI(...) LOGI_TAG("BDQ", __VA_ARGS__)

namespace {

static_assert(sizeof(float) == 4, "BDQ v1 requires 32-bit float storage");

constexpr uint8_t kFileMagic[8] = { 'B', 'D', 'Q', 'L', 'O', 'G', 0x00, 0x01 };
constexpr uint16_t kFormatMajor = 1;
constexpr uint16_t kFormatMinor = 0;
constexpr uint32_t kFileHeaderLen = 32;
constexpr uint8_t kChunkMagic[4] = { 'B', 'D', 'Q', 'C' };
constexpr uint16_t kChunkHeaderVersion = 1;
constexpr uint16_t kMaxColumns = LoggerLimits::kMaxDynamicColumns;
constexpr uint16_t kMaxFramesPerChunk = 512;
constexpr uint16_t kDataPayloadHeaderLen = 20;

enum class ChunkType : uint16_t {
  Metadata = 1,
  ChannelSchema = 2,
  Data = 3,
  Event = 4,
  FinalSummary = 5,
};

enum class StorageType : uint8_t {
  UInt16 = 1,
  Int32 = 2,
  Float32 = 3,
};

enum SampleFlags : uint16_t {
  SAMPLE_FLAG_NONE       = 0,
  SAMPLE_FLAG_MARK       = 1 << 0,
  SAMPLE_FLAG_SD_BUSY    = 1 << 1,
  SAMPLE_FLAG_OVERRUN    = 1 << 2,
  SAMPLE_FLAG_SENSOR_ERR = 1 << 3,
};

struct ColumnLayout {
  char field[64] = {0};
  char csvHeader[96] = {0};
  char sensorName[16] = {0};
  char end[16] = {0};
  char domain[24] = {0};
  char quantity[24] = {0};
  char unit[24] = {0};
  char source[24] = {0};
  char kind[8] = {0};
  char processingRole[24] = {0};
  char columnClass[16] = {0};
  StorageType storage = StorageType::Float32;
  uint16_t valueIndex = 0;
  uint16_t byteOffset = 0;
  bool raw = false;
  bool semanticSelectionExcluded = false;
};

File* s_file = nullptr;
bool s_active = false;
uint32_t s_sequence = 0;
uint16_t s_columnCount = 0;
ColumnLayout s_columns[kMaxColumns];
uint16_t s_frameSize = 0;
uint8_t* s_chunkPayload = nullptr;
uint32_t s_chunkPayloadCapacity = 0;
uint16_t s_framesPerChunk = 0;
uint16_t s_pendingFrames = 0;
uint32_t s_firstPendingSampleId = 0;
uint64_t s_pendingChunkStartUnixUs = 0;
uint32_t s_samplesWritten = 0;
uint32_t s_dataChunksWritten = 0;
uint32_t s_samplePeriodUs = 0;
uint16_t s_sampleRateHz = 0;
String s_sessionId;
String s_logPath;
String s_timezone;
String s_startedAtUtc;
String s_startedAtLocal;

void copyField_(char* dst, size_t cap, const char* src) {
  if (!dst || cap == 0) return;
  if (!src) src = "";
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

uint32_t crc32Update_(uint32_t crc, const uint8_t* data, size_t len) {
  crc = ~crc;
  for (size_t i = 0; i < len; ++i) {
    crc ^= data[i];
    for (int k = 0; k < 8; ++k) {
      crc = (crc >> 1) ^ (0xEDB88320u & (-(int32_t)(crc & 1u)));
    }
  }
  return ~crc;
}

void putU16_(uint8_t* out, uint16_t v) {
  out[0] = (uint8_t)(v & 0xFF);
  out[1] = (uint8_t)((v >> 8) & 0xFF);
}

void putU32_(uint8_t* out, uint32_t v) {
  out[0] = (uint8_t)(v & 0xFF);
  out[1] = (uint8_t)((v >> 8) & 0xFF);
  out[2] = (uint8_t)((v >> 16) & 0xFF);
  out[3] = (uint8_t)((v >> 24) & 0xFF);
}

void putU64_(uint8_t* out, uint64_t v) {
  for (uint8_t i = 0; i < 8; ++i) {
    out[i] = (uint8_t)((v >> (8 * i)) & 0xFF);
  }
}

bool writeBytes_(const void* data, size_t len) {
  if (!s_file || !*s_file) return false;
  if (len == 0) return true;
  return s_file->write((const uint8_t*)data, len) == len;
}

bool writeU16_(uint16_t v) {
  uint8_t b[2];
  putU16_(b, v);
  return writeBytes_(b, sizeof(b));
}

bool writeU32_(uint32_t v) {
  uint8_t b[4];
  putU32_(b, v);
  return writeBytes_(b, sizeof(b));
}

bool writeU64_(uint64_t v) {
  uint8_t b[8];
  putU64_(b, v);
  return writeBytes_(b, sizeof(b));
}

void appendJsonEscaped_(String& out, const char* text) {
  out += '"';
  const char* p = text ? text : "";
  while (*p) {
    const char c = *p++;
    switch (c) {
      case '"': out += F("\\\""); break;
      case '\\': out += F("\\\\"); break;
      case '\b': out += F("\\b"); break;
      case '\f': out += F("\\f"); break;
      case '\n': out += F("\\n"); break;
      case '\r': out += F("\\r"); break;
      case '\t': out += F("\\t"); break;
      default:
        if ((uint8_t)c < 0x20) {
          char buf[7];
          snprintf(buf, sizeof(buf), "\\u%04x", (unsigned)(uint8_t)c);
          out += buf;
        } else {
          out += c;
        }
        break;
    }
  }
  out += '"';
}

void appendKey_(String& out, uint8_t depth, const char* key) {
  for (uint8_t i = 0; i < depth; ++i) out += F("  ");
  appendJsonEscaped_(out, key);
  out += F(": ");
}

void appendKeyString_(String& out, uint8_t depth, const char* key, const char* value, bool comma = true) {
  appendKey_(out, depth, key);
  appendJsonEscaped_(out, value);
  out += comma ? F(",\n") : F("\n");
}

void appendKeyUInt_(String& out, uint8_t depth, const char* key, uint64_t value, bool comma = true) {
  appendKey_(out, depth, key);
  char buf[24];
  snprintf(buf, sizeof(buf), "%llu", (unsigned long long)value);
  out += buf;
  out += comma ? F(",\n") : F("\n");
}

void appendKeyInt_(String& out, uint8_t depth, const char* key, int32_t value, bool comma = true) {
  appendKey_(out, depth, key);
  out += String(value);
  out += comma ? F(",\n") : F("\n");
}

void appendKeyHex8_(String& out, uint8_t depth, const char* key, uint8_t value, bool comma = true) {
  appendKey_(out, depth, key);
  char buf[7];
  snprintf(buf, sizeof(buf), "\"0x%02X\"", (unsigned)value);
  out += buf;
  out += comma ? F(",\n") : F("\n");
}

void appendKeyHex16_(String& out, uint8_t depth, const char* key, uint16_t value, bool comma = true) {
  appendKey_(out, depth, key);
  char buf[9];
  snprintf(buf, sizeof(buf), "\"0x%04X\"", (unsigned)value);
  out += buf;
  out += comma ? F(",\n") : F("\n");
}

void appendKeyBool_(String& out, uint8_t depth, const char* key, bool value, bool comma = true) {
  appendKey_(out, depth, key);
  out += value ? F("true") : F("false");
  out += comma ? F(",\n") : F("\n");
}

const TimingSummary& emptyTimingSummary_() {
  static const TimingSummary empty;
  return empty;
}

const StorageTimingStats& emptyStorageTiming_() {
  static const StorageTimingStats empty;
  return empty;
}

const ExternalAdcTimingStats& emptyExternalAdcTiming_() {
  static const ExternalAdcTimingStats empty;
  return empty;
}

const SensorTimingStats& emptySensorTiming_() {
  static const SensorTimingStats empty;
  return empty;
}

const I2CBusSchedulerTimingStats& emptyI2CSchedulerTiming_() {
  static const I2CBusSchedulerTimingStats empty;
  return empty;
}

void appendKeyFloat_(String& out, uint8_t depth, const char* key, float value, bool comma = true) {
  appendKey_(out, depth, key);
  out += String(value, 6);
  out += comma ? F(",\n") : F("\n");
}

void appendIndent_(String& out, uint8_t depth) {
  for (uint8_t i = 0; i < depth; ++i) out += F("  ");
}

void appendTimingSummary_(String& out, uint8_t depth, const char* key, const TimingSummary& s, bool comma = true) {
  appendKey_(out, depth, key);
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "count", s.count);
  appendKeyUInt_(out, depth + 1, "min_us", s.minUs);
  appendKeyFloat_(out, depth + 1, "avg_us", TimingStats_avgUs(s));
  appendKeyUInt_(out, depth + 1, "max_us", s.maxUs);
  appendKeyUInt_(out, depth + 1, "total_us", s.totalUs);
  appendKey_(out, depth + 1, "buckets_us");
  out += F("{\n");
  appendKeyUInt_(out, depth + 2, "lt_250", s.bucketLt250);
  appendKeyUInt_(out, depth + 2, "250_500", s.bucket250To500);
  appendKeyUInt_(out, depth + 2, "500_1000", s.bucket500To1000);
  appendKeyUInt_(out, depth + 2, "1000_1500", s.bucket1000To1500);
  appendKeyUInt_(out, depth + 2, "1500_2000", s.bucket1500To2000);
  appendKeyUInt_(out, depth + 2, "ge_2000", s.bucketGe2000, false);
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendAdcTiming_(String& out, uint8_t depth, const ExternalAdcTimingStats& stats, bool comma = true) {
  appendKey_(out, depth, "external_adc_timing");
  out += F("{\n");
  bool wroteAny = false;
  for (uint8_t adc = 0; adc < ExternalAdcTimingStats::kMaxAdcs; ++adc) {
    const auto& a = stats.adc[adc];
    if (!a.present && a.activeChannels == 0 && a.scanUs.count == 0) continue;
    if (wroteAny) out += F(",\n");
    wroteAny = true;

    char key[8];
    snprintf(key, sizeof(key), "adc%u", (unsigned)adc);
    appendKey_(out, depth + 1, key);
    out += F("{\n");
    appendKeyBool_(out, depth + 2, "present", a.present);
    appendKeyBool_(out, depth + 2, "async_running", a.asyncRunning);
    appendKeyUInt_(out, depth + 2, "active_channels", a.activeChannels);
    appendKeyUInt_(out, depth + 2, "configured_sps", a.configuredSps);
    appendKeyUInt_(out, depth + 2, "wait_timeouts", a.waitTimeouts);
    appendKeyUInt_(out, depth + 2, "drdy_already_ready", a.drdyAlreadyReady);
    appendTimingSummary_(out, depth + 2, "scan_us", a.scanUs);
    appendTimingSummary_(out, depth + 2, "async_loop_us", a.asyncLoopUs);
    appendTimingSummary_(out, depth + 2, "config_us", a.configUs);
    appendTimingSummary_(out, depth + 2, "start_us", a.startUs);
    appendTimingSummary_(out, depth + 2, "wait_us", a.waitUs);
    appendTimingSummary_(out, depth + 2, "read_us", a.readUs);
    appendKey_(out, depth + 2, "channels");
    out += F("{\n");
    bool wroteChannel = false;
    for (uint8_t ch = 0; ch < ExternalAdcTimingStats::kMaxChannels; ++ch) {
      const auto& c = a.channel[ch];
      if (c.totalUs.count == 0 && c.waitUs.count == 0 && c.rowUses == 0) continue;
      if (wroteChannel) out += F(",\n");
      wroteChannel = true;
      char chKey[8];
      snprintf(chKey, sizeof(chKey), "ch%u", (unsigned)ch);
      appendKey_(out, depth + 3, chKey);
      out += F("{\n");
      appendTimingSummary_(out, depth + 4, "total_us", c.totalUs);
      appendTimingSummary_(out, depth + 4, "wait_us", c.waitUs);
      appendTimingSummary_(out, depth + 4, "row_age_us", c.rowAgeUs);
      appendKeyUInt_(out, depth + 4, "acquire_ok", c.acquireOk);
      appendKeyUInt_(out, depth + 4, "acquire_fail", c.acquireFail);
      appendKeyUInt_(out, depth + 4, "row_uses", c.rowUses);
      appendKeyUInt_(out, depth + 4, "row_fresh", c.rowFresh);
      appendKeyUInt_(out, depth + 4, "row_reused", c.rowReused);
      appendKeyUInt_(out, depth + 4, "row_no_sample", c.rowNoSample, false);
      appendIndent_(out, depth + 3);
      out += F("}");
    }
    if (wroteChannel) out += '\n';
    appendIndent_(out, depth + 2);
    out += F("}\n");
    appendIndent_(out, depth + 1);
    out += F("}");
  }
  if (wroteAny) out += '\n';
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendSensorTiming_(String& out, uint8_t depth, const SensorTimingStats& stats, bool comma = true) {
  appendKey_(out, depth, "sensor_timing");
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "sensor_count", stats.sensorCount);
  appendKey_(out, depth + 1, "sensors");
  out += F("{\n");

  bool wroteAny = false;
  for (uint8_t i = 0; i < SensorTimingStats::kMaxSensors; ++i) {
    const auto& s = stats.sensor[i];
    if (!s.present && s.sampleUs.count == 0) continue;
    if (wroteAny) out += F(",\n");
    wroteAny = true;

    char key[12];
    snprintf(key, sizeof(key), "sensor%u", (unsigned)i);
    appendKey_(out, depth + 2, key);
    out += F("{\n");
    appendKeyBool_(out, depth + 3, "present", s.present);
    appendKeyBool_(out, depth + 3, "muted", s.muted);
    appendKeyBool_(out, depth + 3, "synchronous", s.synchronous);
    appendKeyString_(out, depth + 3, "name", s.name);
    appendKeyString_(out, depth + 3, "label", s.label);
    appendKeyUInt_(out, depth + 3, "column_count", s.columnCount);
    appendTimingSummary_(out, depth + 3, "sample_us", s.sampleUs, false);
    appendIndent_(out, depth + 2);
    out += F("}");
  }
  if (wroteAny) out += '\n';
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendI2CSchedulerTiming_(String& out,
                               uint8_t depth,
                               const I2CBusSchedulerTimingStats& stats,
                               bool comma = true) {
  appendKey_(out, depth, "i2c_scheduler_timing");
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "client_count", stats.clientCount);

  appendKey_(out, depth + 1, "buses");
  out += F("{\n");
  bool wroteBus = false;
  for (uint8_t bus = 0; bus < I2CBusSchedulerTimingStats::kMaxBuses; ++bus) {
    const auto& b = stats.bus[bus];
    if (!b.present && !b.running && b.clientCount == 0 && b.acquireLoopUs.count == 0) continue;
    if (wroteBus) out += F(",\n");
    wroteBus = true;
    char key[8];
    snprintf(key, sizeof(key), "bus%u", (unsigned)bus);
    appendKey_(out, depth + 2, key);
    out += F("{\n");
    appendKeyBool_(out, depth + 3, "present", b.present);
    appendKeyBool_(out, depth + 3, "running", b.running);
    appendKeyUInt_(out, depth + 3, "client_count", b.clientCount);
    appendKeyUInt_(out, depth + 3, "hz", b.hz);
    appendTimingSummary_(out, depth + 3, "acquire_loop_us", b.acquireLoopUs, false);
    appendIndent_(out, depth + 2);
    out += F("}");
  }
  if (wroteBus) out += '\n';
  appendIndent_(out, depth + 1);
  out += F("},\n");

  appendKey_(out, depth + 1, "clients");
  out += F("{\n");
  bool wroteClient = false;
  for (uint8_t i = 0; i < I2CBusSchedulerTimingStats::kMaxClients; ++i) {
    const auto& c = stats.client[i];
    if (!c.present && c.acquireUs.count == 0 && c.rowUses == 0) continue;
    if (wroteClient) out += F(",\n");
    wroteClient = true;
    char key[12];
    snprintf(key, sizeof(key), "client%u", (unsigned)i);
    appendKey_(out, depth + 2, key);
    out += F("{\n");
    appendKeyBool_(out, depth + 3, "present", c.present);
    appendKeyBool_(out, depth + 3, "active", c.active);
    appendKeyString_(out, depth + 3, "name", c.name);
    appendKeyString_(out, depth + 3, "kind", c.kind);
    appendKeyUInt_(out, depth + 3, "bus", c.busIndex);
    appendKeyUInt_(out, depth + 3, "address", c.address);
    appendKeyUInt_(out, depth + 3, "target_rate_hz", c.targetRateHz);
    appendKeyUInt_(out, depth + 3, "period_us", c.periodUs);
    appendKeyUInt_(out, depth + 3, "acquire_ok", c.acquireOk);
    appendKeyUInt_(out, depth + 3, "acquire_fail", c.acquireFail);
    appendKeyUInt_(out, depth + 3, "row_uses", c.rowUses);
    appendKeyUInt_(out, depth + 3, "row_fresh", c.rowFresh);
    appendKeyUInt_(out, depth + 3, "row_reused", c.rowReused);
    appendKeyUInt_(out, depth + 3, "row_no_sample", c.rowNoSample);
    appendTimingSummary_(out, depth + 3, "acquire_us", c.acquireUs);
    appendTimingSummary_(out, depth + 3, "row_age_us", c.rowAgeUs, false);
    appendIndent_(out, depth + 2);
    out += F("}");
  }
  if (wroteClient) out += '\n';
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendI2CBusDiagnostics_(String& out,
                              uint8_t depth,
                              const board::BoardProfile* bp,
                              bool comma = true) {
  appendKey_(out, depth, "i2c_buses");
  out += F("{\n");
  appendKeyString_(out, depth + 1, "board", bp ? bp->name : "");
  appendKeyUInt_(out, depth + 1, "count", bp ? bp->i2c_count : 0);
  appendKey_(out, depth + 1, "buses");
  out += F("{\n");

  bool wroteAny = false;
  if (bp) {
    const uint8_t count = (bp->i2c_count < board::BOARD_MAX_I2C_BUSES)
      ? bp->i2c_count
      : board::BOARD_MAX_I2C_BUSES;
    for (uint8_t i = 0; i < count; ++i) {
      const auto& bus = bp->i2c[i];
      if (wroteAny) out += F(",\n");
      wroteAny = true;

      char key[8];
      snprintf(key, sizeof(key), "bus%u", (unsigned)i);
      appendKey_(out, depth + 2, key);
      out += F("{\n");
      appendKeyBool_(out, depth + 3, "present", bus.present);
      appendKeyInt_(out, depth + 3, "sda", bus.sda);
      appendKeyInt_(out, depth + 3, "scl", bus.scl);
      appendKeyUInt_(out, depth + 3, "hz", bus.hz, false);
      appendIndent_(out, depth + 2);
      out += F("}");
    }
  }
  if (wroteAny) out += '\n';
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

const char* storageTypeName_(StorageType t) {
  switch (t) {
    case StorageType::UInt16: return "uint16";
    case StorageType::Int32: return "int32";
    case StorageType::Float32:
    default: return "float32";
  }
}

uint16_t storageTypeSize_(StorageType t) {
  switch (t) {
    case StorageType::UInt16: return 2;
    case StorageType::Int32: return 4;
    case StorageType::Float32:
    default: return 4;
  }
}

bool isUnwrappedRaw_(const SensorColumnDescriptor& desc) {
  return strcasecmp(desc.source, "unwrapped_raw_counts") == 0 ||
         strcasecmp(desc.source, "unwrapped_raw") == 0 ||
         strstr(desc.columnId, "unwrapped") != nullptr ||
         strstr(desc.csvHeader, "unwrapped") != nullptr;
}

StorageType storageTypeFor_(const SensorColumnDescriptor& desc) {
  if (!desc.raw) return StorageType::Float32;
  return isUnwrappedRaw_(desc) ? StorageType::Int32 : StorageType::UInt16;
}

void appendDeviceConfigObject_(String& out,
                               const SensorDeviceConfigDescriptor& cfg,
                               uint8_t depth,
                               bool comma) {
  out += F("{\n");
  appendKeyString_(out, depth + 1, "kind", cfg.kind);
  appendKeyString_(out, depth + 1, "policy", cfg.policy[0] ? cfg.policy : "read_only");
  appendKeyString_(out, depth + 1, "status", cfg.status);
  if (cfg.requestedSlowFilter[0]) appendKeyString_(out, depth + 1, "requested_slow_filter", cfg.requestedSlowFilter);
  if (cfg.writeStatus[0]) appendKeyString_(out, depth + 1, "write_status", cfg.writeStatus);
  appendKeyBool_(out, depth + 1, "read_ok", cfg.readOk);

  appendKey_(out, depth + 1, "registers");
  out += F("{\n");
  appendKeyUInt_(out, depth + 2, "zpos", cfg.zpos);
  appendKeyUInt_(out, depth + 2, "mpos", cfg.mpos);
  appendKeyUInt_(out, depth + 2, "mang", cfg.mang);
  appendKeyUInt_(out, depth + 2, "conf", cfg.conf);
  appendKeyHex16_(out, depth + 2, "conf_hex", cfg.conf);
  appendKeyUInt_(out, depth + 2, "raw_angle", cfg.rawAngle);
  appendKeyUInt_(out, depth + 2, "angle", cfg.angle);
  appendKeyUInt_(out, depth + 2, "status", cfg.statusReg);
  appendKeyHex8_(out, depth + 2, "status_hex", cfg.statusReg);
  appendKeyUInt_(out, depth + 2, "agc", cfg.agc);
  appendKeyUInt_(out, depth + 2, "magnitude", cfg.magnitude, false);
  for (uint8_t i = 0; i < depth + 1; ++i) out += F("  ");
  out += F("},\n");

  appendKey_(out, depth + 1, "decoded");
  out += F("{\n");
  appendKeyString_(out, depth + 2, "power_mode", cfg.readOk ? cfg.confPowerMode : "");
  appendKeyString_(out, depth + 2, "hysteresis", cfg.readOk ? cfg.confHysteresis : "");
  appendKeyString_(out, depth + 2, "output_stage", cfg.readOk ? cfg.confOutputStage : "");
  appendKeyString_(out, depth + 2, "pwm_frequency", cfg.readOk ? cfg.confPwmFrequency : "");
  appendKeyString_(out, depth + 2, "slow_filter", cfg.readOk ? cfg.confSlowFilter : "");
  appendKeyString_(out, depth + 2, "fast_filter_threshold", cfg.readOk ? cfg.confFastFilterThreshold : "");
  appendKeyBool_(out, depth + 2, "watchdog", cfg.readOk && cfg.confWatchdog, false);
  for (uint8_t i = 0; i < depth + 1; ++i) out += F("  ");
  out += F("}\n");

  for (uint8_t i = 0; i < depth; ++i) out += F("  ");
  out += comma ? F("},\n") : F("}\n");
}

bool appendDeviceConfigs_(String& out) {
  const uint16_t sensorCount = SensorManager::describeSensors(nullptr, 0);
  SensorMetadataDescriptor* sensors = sensorCount ? new (std::nothrow) SensorMetadataDescriptor[sensorCount] : nullptr;
  if (sensorCount && !sensors) return false;

  const uint16_t sensorsWritten = SensorManager::describeSensors(sensors, sensorCount);
  uint16_t configCount = 0;
  for (uint16_t i = 0; i < sensorsWritten; ++i) {
    if (sensors[i].hasDeviceConfig) ++configCount;
  }

  if (configCount == 0) {
    delete[] sensors;
    return false;
  }

  appendKey_(out, 1, "device_configs");
  out += F("{\n");
  uint16_t written = 0;
  for (uint16_t i = 0; i < sensorsWritten; ++i) {
    const SensorMetadataDescriptor& sensor = sensors[i];
    if (!sensor.hasDeviceConfig) continue;

    out += F("    ");
    appendJsonEscaped_(out, sensor.sensorId[0] ? sensor.sensorId : sensor.name);
    out += F(": ");
    appendDeviceConfigObject_(out, sensor.deviceConfig, 2, ++written < configCount);
  }
  out += F("  },\n");

  delete[] sensors;
  return true;
}

bool buildColumnLayout_() {
  s_columnCount = 0;
  s_frameSize = 4; // sample_id

  const uint16_t total = SensorManager::describeSensorColumns(nullptr, 0);
  const uint16_t n = (total > kMaxColumns) ? kMaxColumns : total;

  if (total > kMaxColumns) {
    BDQ_LOGW("schema truncated: columns=%u max=%u\n", (unsigned)total, (unsigned)kMaxColumns);
  }

  for (uint16_t i = 0; i < n; ++i) {
    SensorColumnDescriptor desc;
    if (!SensorManager::describeSensorColumnAt(i, desc)) continue;

    ColumnLayout& col = s_columns[s_columnCount];
    col = ColumnLayout{};
    col.storage = storageTypeFor_(desc);
    col.valueIndex = i;
    col.byteOffset = s_frameSize;
    col.raw = desc.raw;
    copyField_(col.csvHeader, sizeof(col.csvHeader), desc.csvHeader);
    copyField_(col.sensorName, sizeof(col.sensorName), desc.sensorName);
    copyField_(col.end, sizeof(col.end), desc.end);
    copyField_(col.domain, sizeof(col.domain), desc.domain);
    copyField_(col.quantity, sizeof(col.quantity), desc.quantity);
    copyField_(col.unit, sizeof(col.unit), desc.unit);
    copyField_(col.source, sizeof(col.source), desc.source);
    copyField_(col.kind, sizeof(col.kind), desc.kind);
    copyField_(col.processingRole, sizeof(col.processingRole), desc.processingRole);
    copyField_(col.columnClass, sizeof(col.columnClass), desc.diagnostic ? "diagnostic" : "signal");
    col.semanticSelectionExcluded = desc.semanticSelectionExcluded;
    const char* field = desc.columnId[0] ? desc.columnId : desc.csvHeader;
    copyField_(col.field, sizeof(col.field), field);

    s_frameSize += storageTypeSize_(col.storage);
    ++s_columnCount;
  }

  // trailing flags
  s_frameSize += 2;
  return s_frameSize > 6;
}

String buildMetadataJson_(const BdqLogSessionInfo& info) {
  const LoggerConfig* cfg = info.config;
  const String loggerIdText = cfg ? ConfigManager::loggerId(*cfg) : String("unknown");
  const char* loggerId = loggerIdText.c_str();

  String out;
  out.reserve(1536);
  out += F("{\n");
  appendKeyString_(out, 1, "format", "bdq.v1");
  appendKeyString_(out, 1, "format_name", "BDQLOG v1");
  appendKeyString_(out, 1, "device_id", loggerId && *loggerId ? loggerId : "unknown");
  appendKeyString_(out, 1, "firmware_name", FirmwareInfo::name());
  appendKeyString_(out, 1, "firmware_version", FirmwareInfo::version());
  appendKeyString_(out, 1, "firmware_build", FirmwareInfo::buildDateTime());
  appendKeyString_(out, 1, "hardware_version", FirmwareInfo::boardName());
  appendKeyString_(out, 1, "recording_id", info.sessionId && *info.sessionId ? info.sessionId : "unknown");
  appendKeyString_(out, 1, "path", info.logPath);
  appendKeyUInt_(out, 1, "created_unix_us", info.createdUnixUs);
  appendKeyUInt_(out, 1, "sample_rate_hz", info.sampleRateHz);
  appendKeyUInt_(out, 1, "sample_period_us", info.samplePeriodUs);
  appendKeyString_(out, 1, "timezone", info.timezone && *info.timezone ? info.timezone : "unknown");
  appendKeyString_(out, 1, "started_at_utc", info.startedAtUtc);
  appendKeyString_(out, 1, "started_at_local", info.startedAtLocal);
  appendDeviceConfigs_(out);
  appendKeyString_(out, 1, "log_format", cfg ? ConfigManager::logFormatKey(cfg->logFormat) : "bodaqs_compact_binary", false);
  out += F("}\n");
  return out;
}

void appendChannelJson_(String& out,
                        const char* field,
                        const char* quantity,
                        const char* unit,
                        const char* storageType,
                        uint16_t byteOffset,
                        const char* sensorName,
                        const char* end,
                        const char* domain,
                        const char* source,
                        const char* kind,
                        const char* processingRole,
                        const char* columnClass,
                        bool raw,
                        bool semanticSelectionExcluded,
                        bool comma) {
  out += F("    {\n");
  appendKeyString_(out, 3, "field", field);
  if (columnClass && *columnClass) appendKeyString_(out, 3, "class", columnClass);
  appendKeyString_(out, 3, "quantity", quantity);
  appendKeyString_(out, 3, "unit", unit);
  appendKeyString_(out, 3, "storage_type", storageType);
  appendKeyUInt_(out, 3, "byte_offset", byteOffset);
  if (sensorName && *sensorName) appendKeyString_(out, 3, "sensor", sensorName);
  if (end && *end) appendKeyString_(out, 3, "end", end);
  if (domain && *domain) appendKeyString_(out, 3, "domain", domain);
  if (source && *source) appendKeyString_(out, 3, "source", source);
  if ((kind && *kind) || raw) appendKeyString_(out, 3, "kind", kind && *kind ? kind : "raw");
  if (processingRole && *processingRole) appendKeyString_(out, 3, "processing_role", processingRole);
  if (semanticSelectionExcluded) appendKeyBool_(out, 3, "semantic_selection_excluded", true);
  appendKeyBool_(out, 3, "raw", raw, false);
  out += comma ? F("    },\n") : F("    }\n");
}

String buildSchemaJson_() {
  String out;
  out.reserve(1024 + (s_columnCount * 320));
  out += F("{\n");
  appendKeyString_(out, 1, "schema_format", "bdq.channel_schema.v1");
  appendKeyString_(out, 1, "frame_layout", "fixed_mixed_v1");
  appendKeyString_(out, 1, "endianness", "little");
  appendKeyUInt_(out, 1, "frame_size_bytes", s_frameSize);

  appendKey_(out, 1, "timebase");
  out += F("{\n");
  appendKeyString_(out, 2, "type", "fixed_rate");
  appendKeyUInt_(out, 2, "sample_rate_hz", s_sampleRateHz);
  appendKeyUInt_(out, 2, "sample_period_us", s_samplePeriodUs);
  appendKeyBool_(out, 2, "timestamp_per_sample", false);
  appendKeyString_(out, 2, "timestamp_reconstruction", "session_start_unix_us + sample_id * sample_period_us", false);
  out += F("  },\n");

  appendKey_(out, 1, "channels");
  out += F("[\n");
  appendChannelJson_(out, "sample_id", "sample_index", "sample", "uint32", 0, "", "", "", "frame", "", "", "index", false, false, true);

  for (uint16_t i = 0; i < s_columnCount; ++i) {
    const ColumnLayout& col = s_columns[i];
    const bool comma = true;
    const char* quantity = col.quantity[0] ? col.quantity : (col.raw ? "raw" : "value");
    const char* unit = col.unit[0] ? col.unit : (col.raw ? "counts" : "");
    appendChannelJson_(out,
                       col.field[0] ? col.field : col.csvHeader,
                       quantity,
                       unit,
                       storageTypeName_(col.storage),
                       col.byteOffset,
                       col.sensorName,
                       col.end,
                       col.domain,
                       col.source,
                       col.kind,
                       col.processingRole,
                       col.columnClass,
                       col.raw,
                       col.semanticSelectionExcluded,
                       comma);
  }

  appendChannelJson_(out, "flags", "flags", "bitfield", "uint16", (uint16_t)(s_frameSize - 2), "", "", "", "frame", "qc", "qc_metric", "qc_flag", false, true, false);
  out += F("  ],\n");

  appendKey_(out, 1, "sample_flags");
  out += F("{\n");
  appendKeyUInt_(out, 2, "mark", SAMPLE_FLAG_MARK);
  appendKeyUInt_(out, 2, "sd_busy", SAMPLE_FLAG_SD_BUSY);
  appendKeyUInt_(out, 2, "overrun", SAMPLE_FLAG_OVERRUN);
  appendKeyUInt_(out, 2, "sensor_err", SAMPLE_FLAG_SENSOR_ERR, false);
  out += F("  }\n");

  out += F("}\n");
  return out;
}

bool writeFileHeader_(uint64_t createdUnixUs) {
  return writeBytes_(kFileMagic, sizeof(kFileMagic)) &&
         writeU16_(kFormatMajor) &&
         writeU16_(kFormatMinor) &&
         writeU32_(kFileHeaderLen) &&
         writeU64_(createdUnixUs) &&
         writeU32_(0) &&
         writeU32_(0);
}

bool writeChunk_(ChunkType type, const uint8_t* payload, uint32_t payloadLen) {
  const uint32_t crc = payloadLen ? crc32Update_(0, payload, payloadLen) : 0;
  const uint32_t seq = s_sequence++;

  const bool ok = writeBytes_(kChunkMagic, sizeof(kChunkMagic)) &&
                  writeU16_(kChunkHeaderVersion) &&
                  writeU16_((uint16_t)type) &&
                  writeU32_(seq) &&
                  writeU32_(payloadLen) &&
                  writeU32_(crc) &&
                  writeBytes_(payload, payloadLen);

  if (!ok) {
    BDQ_LOGW("chunk write failed type=%u seq=%lu len=%lu\n",
             (unsigned)type,
             (unsigned long)seq,
             (unsigned long)payloadLen);
  }
  return ok;
}

bool writeJsonChunk_(ChunkType type, const String& json) {
  return writeChunk_(type, (const uint8_t*)json.c_str(), (uint32_t)json.length());
}

void resetChunkState_() {
  s_pendingFrames = 0;
  s_firstPendingSampleId = 0;
  s_pendingChunkStartUnixUs = 0;
}

bool allocChunkBuffer_(uint32_t targetBytes) {
  free(s_chunkPayload);
  s_chunkPayload = nullptr;
  s_chunkPayloadCapacity = 0;
  s_framesPerChunk = 0;

  if (targetBytes < 1024) targetBytes = 1024;
  if (targetBytes > 65535) targetBytes = 65535;

  uint32_t frames = (targetBytes > kDataPayloadHeaderLen)
                      ? ((targetBytes - kDataPayloadHeaderLen) / s_frameSize)
                      : 1;
  if (frames < 1) frames = 1;
  if (frames > kMaxFramesPerChunk) frames = kMaxFramesPerChunk;

  const uint32_t payloadCapacity = kDataPayloadHeaderLen + frames * s_frameSize;
  s_chunkPayload = static_cast<uint8_t*>(malloc(payloadCapacity));
  if (!s_chunkPayload) {
    BDQ_LOGE("chunk buffer allocation failed bytes=%lu\n", (unsigned long)payloadCapacity);
    return false;
  }

  s_chunkPayloadCapacity = payloadCapacity;
  s_framesPerChunk = (uint16_t)frames;
  resetChunkState_();
  return true;
}

uint16_t flagsFromValueError_(uint16_t flags, float value) {
  if (!isfinite(value)) return (uint16_t)(flags | SAMPLE_FLAG_SENSOR_ERR);
  return flags;
}

uint16_t floatToU16_(float value, uint16_t& flags) {
  flags = flagsFromValueError_(flags, value);
  if (!isfinite(value)) return 0;
  long v = lroundf(value);
  if (v < 0) {
    flags = (uint16_t)(flags | SAMPLE_FLAG_SENSOR_ERR);
    return 0;
  }
  if (v > 65535L) {
    flags = (uint16_t)(flags | SAMPLE_FLAG_SENSOR_ERR);
    return 65535;
  }
  return (uint16_t)v;
}

int32_t floatToI32_(float value, uint16_t& flags) {
  flags = flagsFromValueError_(flags, value);
  if (!isfinite(value)) return 0;
  double rounded = round((double)value);
  if (rounded < -2147483648.0) {
    flags = (uint16_t)(flags | SAMPLE_FLAG_SENSOR_ERR);
    return INT32_MIN;
  }
  if (rounded > 2147483647.0) {
    flags = (uint16_t)(flags | SAMPLE_FLAG_SENSOR_ERR);
    return INT32_MAX;
  }
  return (int32_t)rounded;
}

void putFloat32_(uint8_t* out, float value, uint16_t& flags) {
  flags = flagsFromValueError_(flags, value);
  if (!isfinite(value)) value = NAN;
  uint32_t raw = 0;
  memcpy(&raw, &value, sizeof(raw));
  putU32_(out, raw);
}

bool appendFrame_(uint32_t sampleId, uint64_t tsMs, const float* values, uint16_t nValues, bool mark) {
  if (!s_chunkPayload || s_pendingFrames >= s_framesPerChunk) return false;

  if (s_pendingFrames == 0) {
    s_firstPendingSampleId = sampleId;
    s_pendingChunkStartUnixUs = tsMs ? (tsMs * 1000ULL) : 0;
  }

  uint8_t* frame = s_chunkPayload + kDataPayloadHeaderLen + ((uint32_t)s_pendingFrames * s_frameSize);
  memset(frame, 0, s_frameSize);
  putU32_(frame, sampleId);

  uint16_t flags = mark ? SAMPLE_FLAG_MARK : SAMPLE_FLAG_NONE;
  if (nValues < s_columnCount) {
    flags = (uint16_t)(flags | SAMPLE_FLAG_SENSOR_ERR);
  }

  for (uint16_t i = 0; i < s_columnCount; ++i) {
    const ColumnLayout& col = s_columns[i];
    const float value = (values && col.valueIndex < nValues) ? values[col.valueIndex] : NAN;
    uint8_t* dst = frame + col.byteOffset;

    switch (col.storage) {
      case StorageType::UInt16:
        putU16_(dst, floatToU16_(value, flags));
        break;
      case StorageType::Int32:
        putU32_(dst, (uint32_t)floatToI32_(value, flags));
        break;
      case StorageType::Float32:
      default:
        putFloat32_(dst, value, flags);
        break;
    }
  }

  putU16_(frame + s_frameSize - 2, flags);
  ++s_pendingFrames;
  ++s_samplesWritten;
  return true;
}

String buildFinalSummaryJson_(const BdqLogEndInfo& info) {
  String out;
  out.reserve(512);
  out += F("{\n");
  appendKeyString_(out, 1, "summary_format", "bdq.final_summary.v1");
  appendKeyString_(out, 1, "session_id", s_sessionId.c_str());
  appendKeyString_(out, 1, "path", s_logPath.c_str());
  appendKeyUInt_(out, 1, "samples_written", s_samplesWritten);
  appendKeyUInt_(out, 1, "data_chunks_written", s_dataChunksWritten);
  appendKeyUInt_(out, 1, "samples_dropped", info.samplesDropped);
  appendKeyUInt_(out, 1, "queue_max", info.queueMax);
  appendKeyUInt_(out, 1, "queue_depth", info.queueDepth);
  appendKeyUInt_(out, 1, "flush_count", info.flushCount);
  appendKeyUInt_(out, 1, "flush_max_ms", info.flushMaxMs);
#if BODAQS_TIMING_INSTRUMENTATION
  appendKeyUInt_(out, 1, "flush_total_ms", info.flushTotalMs);
#else
  appendKeyUInt_(out, 1, "flush_total_ms", info.flushTotalMs, false);
#endif
#if BODAQS_TIMING_INSTRUMENTATION
  appendKeyUInt_(out, 1, "sampler_late_ticks", info.samplerLateTicks);
  appendKeyUInt_(out, 1, "sampler_late_max_lag_ms", info.samplerLateMaxLagMs);
  appendKeyUInt_(out, 1, "missed_sample_slots", info.missedSampleSlots);
  const StorageTimingStats& storageTiming = info.storageTiming ? *info.storageTiming : emptyStorageTiming_();
  appendTimingSummary_(out, 1, "sample_once_us", info.sampleOnceUs ? *info.sampleOnceUs : emptyTimingSummary_());
  appendTimingSummary_(out, 1, "sensor_sample_us", info.sensorSampleUs ? *info.sensorSampleUs : emptyTimingSummary_());
  appendTimingSummary_(out, 1, "enqueue_us", info.enqueueUs ? *info.enqueueUs : emptyTimingSummary_());
  appendTimingSummary_(out, 1, "storage_row_write_us", storageTiming.rowWriteUs);
  appendTimingSummary_(out, 1, "storage_drain_loop_us", storageTiming.drainLoopUs);
  appendKeyUInt_(out, 1, "storage_drain_loops", storageTiming.drainLoops);
  appendKeyUInt_(out, 1, "storage_drain_rows", storageTiming.drainRows);
  appendAdcTiming_(out, 1, info.externalAdcTiming ? *info.externalAdcTiming : emptyExternalAdcTiming_());
  appendSensorTiming_(out, 1, info.sensorTiming ? *info.sensorTiming : emptySensorTiming_());
  appendI2CSchedulerTiming_(out, 1, info.i2cSchedulerTiming ? *info.i2cSchedulerTiming : emptyI2CSchedulerTiming_());
  appendI2CBusDiagnostics_(out, 1, info.boardProfile, false);
#endif
  out += F("}\n");
  return out;
}

} // namespace

namespace BdqLogWriter {

bool begin(File& file, const BdqLogSessionInfo& info) {
  reset();
  if (!file) return false;

  s_file = &file;
  s_sequence = 0;
  s_samplePeriodUs = info.samplePeriodUs;
  s_sampleRateHz = info.sampleRateHz;
  s_sessionId = info.sessionId ? info.sessionId : "";
  s_logPath = info.logPath ? info.logPath : "";
  s_timezone = info.timezone ? info.timezone : "";
  s_startedAtUtc = info.startedAtUtc ? info.startedAtUtc : "";
  s_startedAtLocal = info.startedAtLocal ? info.startedAtLocal : "";

  if (!buildColumnLayout_()) {
    reset();
    return false;
  }
  if (!allocChunkBuffer_(info.targetChunkBytes)) {
    reset();
    return false;
  }

  if (!writeFileHeader_(info.createdUnixUs)) {
    reset();
    return false;
  }

  const String metadata = buildMetadataJson_(info);
  const String schema = buildSchemaJson_();

  if (!writeJsonChunk_(ChunkType::Metadata, metadata) ||
      !writeJsonChunk_(ChunkType::ChannelSchema, schema)) {
    reset();
    return false;
  }

  s_active = true;
  BDQ_LOGI("begin frame=%u cols=%u framesPerChunk=%u\n",
           (unsigned)s_frameSize,
           (unsigned)s_columnCount,
           (unsigned)s_framesPerChunk);
  return true;
}

bool writeSample(uint32_t sampleId, uint64_t tsMs, const float* values, uint16_t nValues, bool mark) {
  if (!s_active) return false;

  if (s_pendingFrames >= s_framesPerChunk) {
    if (!flushDataChunk()) return false;
  }

  return appendFrame_(sampleId, tsMs, values, nValues, mark);
}

bool flushDataChunk() {
  if (!s_active || s_pendingFrames == 0 || !s_chunkPayload) return false;

  putU32_(s_chunkPayload + 0, s_firstPendingSampleId);
  putU32_(s_chunkPayload + 4, s_pendingFrames);
  putU64_(s_chunkPayload + 8, s_pendingChunkStartUnixUs);
  putU16_(s_chunkPayload + 16, s_frameSize);
  putU16_(s_chunkPayload + 18, 0);

  const uint32_t payloadLen = kDataPayloadHeaderLen + ((uint32_t)s_pendingFrames * s_frameSize);
  const bool ok = writeChunk_(ChunkType::Data, s_chunkPayload, payloadLen);
  if (ok) {
    ++s_dataChunksWritten;
    resetChunkState_();
  }
  return ok;
}

void flushFile() {
  if (s_file && *s_file) {
    s_file->flush();
  }
}

bool end(const BdqLogEndInfo& info) {
  if (!s_active) {
    reset();
    return true;
  }

  const bool dataOk = (s_pendingFrames == 0) ? true : flushDataChunk();
  const String summary = buildFinalSummaryJson_(info);
  const bool summaryOk = writeJsonChunk_(ChunkType::FinalSummary, summary);
  flushFile();
  reset();
  return dataOk && summaryOk;
}

void reset() {
  free(s_chunkPayload);
  s_chunkPayload = nullptr;
  s_chunkPayloadCapacity = 0;
  s_file = nullptr;
  s_active = false;
  s_sequence = 0;
  s_columnCount = 0;
  s_frameSize = 0;
  s_framesPerChunk = 0;
  resetChunkState_();
  s_samplesWritten = 0;
  s_dataChunksWritten = 0;
  s_samplePeriodUs = 0;
  s_sampleRateHz = 0;
  s_sessionId = "";
  s_logPath = "";
  s_timezone = "";
  s_startedAtUtc = "";
  s_startedAtLocal = "";
}

bool isActive() {
  return s_active;
}

uint16_t frameSizeBytes() {
  return s_frameSize;
}

uint16_t pendingFrameCount() {
  return s_pendingFrames;
}

uint32_t samplesWritten() {
  return s_samplesWritten;
}

uint32_t dataChunksWritten() {
  return s_dataChunksWritten;
}

} // namespace BdqLogWriter
