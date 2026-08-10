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
  Int16 = 4,
  UInt32 = 5,
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
  char mountPoint[32] = {0};
  char quantity[24] = {0};
  char component[8] = {0};
  char coordinateFrame[24] = {0};
  char vectorGroup[32] = {0};
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
  bool allowNaN = false;
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

const char* imuStartupStateName_(uint8_t state) {
  switch (state) {
    case 0: return "disabled";
    case 1: return "collecting";
    case 2: return "accepted";
    case 3: return "rejected";
    default: return "unknown";
  }
}

const char* imuStartupRejectionName_(uint8_t state, uint16_t mask) {
  if (state == 0) return "disabled";
  if (state == 1) return "window_incomplete";
  if (mask == 0) return "none";
  if (mask & 0x0001) return "insufficient_samples";
  if (mask & 0x0002) return "quality_incident";
  if (mask & 0x0004) return "accel_mean_outside_gravity_band";
  if (mask & 0x0008) return "accel_magnitude_unstable";
  if (mask & 0x0010) return "gyro_x_unstable";
  if (mask & 0x0020) return "gyro_y_unstable";
  if (mask & 0x0040) return "gyro_z_unstable";
  if (mask & 0x0080) return "gyro_motion_detected";
  return "unknown";
}

void appendImuQualityDiagnostics_(
    String& out,
    uint8_t depth,
    const SensorRuntimeDiagnostics& diagnostics) {
  appendKey_(out, depth, "near_rail_counts");
  out += F("{\n");
  appendKey_(out, depth + 1, "accel");
  out += F("{\n");
  appendKeyUInt_(out, depth + 2, "x", diagnostics.imuAccelNearRail[0]);
  appendKeyUInt_(out, depth + 2, "y", diagnostics.imuAccelNearRail[1]);
  appendKeyUInt_(out, depth + 2, "z", diagnostics.imuAccelNearRail[2], false);
  appendIndent_(out, depth + 1);
  out += F("},\n");
  appendKey_(out, depth + 1, "gyro");
  out += F("{\n");
  appendKeyUInt_(out, depth + 2, "x", diagnostics.imuGyroNearRail[0]);
  appendKeyUInt_(out, depth + 2, "y", diagnostics.imuGyroNearRail[1]);
  appendKeyUInt_(out, depth + 2, "z", diagnostics.imuGyroNearRail[2], false);
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += F("},\n");

  appendKeyUInt_(out, depth, "timing_degraded_samples", diagnostics.imuTimingDegradedSamples);
  appendKeyUInt_(out, depth, "sequence_discontinuity_events", diagnostics.imuSequenceDiscontinuityEvents);
  appendKeyUInt_(out, depth, "native_time_discontinuity_events", diagnostics.imuNativeTimeDiscontinuityEvents);

  appendKey_(out, depth, "acquisition_age_us");
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "count", diagnostics.imuAgeSamples);
  appendKeyUInt_(out, depth + 1, "unavailable", diagnostics.imuAgeUnavailable);
  appendKeyUInt_(out, depth + 1, "histogram_clipped", diagnostics.imuAgeClipped);
  appendKeyUInt_(out, depth + 1, "histogram_resolution_us", diagnostics.imuAgeResolutionUs);
  appendKeyUInt_(out, depth + 1, "minimum", diagnostics.imuAgeMinimumUs);
  appendKeyUInt_(out, depth + 1, "median", diagnostics.imuAgeMedianUs);
  appendKeyUInt_(out, depth + 1, "p95", diagnostics.imuAgeP95Us);
  appendKeyUInt_(out, depth + 1, "p99", diagnostics.imuAgeP99Us);
  appendKeyUInt_(out, depth + 1, "maximum", diagnostics.imuAgeMaximumUs, false);
  appendIndent_(out, depth);
  out += F("},\n");

  appendKey_(out, depth, "temperature_deg_c");
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "samples", diagnostics.imuTemperatureSamples);
  appendKeyFloat_(out, depth + 1, "minimum", diagnostics.imuTemperatureMinimumC);
  appendKeyFloat_(out, depth + 1, "maximum", diagnostics.imuTemperatureMaximumC, false);
  appendIndent_(out, depth);
  out += F("},\n");

  appendKey_(out, depth, "startup_stationary_observation");
  out += F("{\n");
  appendKeyString_(out, depth + 1, "schema", "bodaqs.imu_startup_observation.v1");
  appendKeyString_(out, depth + 1, "state", imuStartupStateName_(diagnostics.imuStartupObservationState));
  appendKeyBool_(out, depth + 1, "accepted", diagnostics.imuStartupObservationState == 2);
  appendKeyString_(out, depth + 1, "rejection_reason",
                   imuStartupRejectionName_(diagnostics.imuStartupObservationState,
                                            diagnostics.imuStartupRejectionMask));
  appendKeyHex16_(out, depth + 1, "rejection_mask", diagnostics.imuStartupRejectionMask);
  appendKeyUInt_(out, depth + 1, "configured_window_s", diagnostics.imuStartupConfiguredSeconds);
  appendKeyUInt_(out, depth + 1, "target_sample_slots", diagnostics.imuStartupTargetSampleSlots);
  appendKeyUInt_(out, depth + 1, "minimum_valid_samples", 800);
  appendKeyUInt_(out, depth + 1, "valid_samples", diagnostics.imuStartupValidSamples);
  appendKey_(out, depth + 1, "thresholds");
  out += F("{\n");
  appendKeyFloat_(out, depth + 2, "accel_mean_tolerance_g", 0.15f);
  appendKeyFloat_(out, depth + 2, "accel_magnitude_std_max_g", 0.03f);
  appendKeyFloat_(out, depth + 2, "gyro_axis_std_max_dps", 0.5f);
  appendKeyFloat_(out, depth + 2, "gyro_magnitude_max_dps", 5.0f, false);
  appendIndent_(out, depth + 1);
  out += F("},\n");
  appendKey_(out, depth + 1, "gyro_mean_raw");
  out += F("{\n");
  appendKeyFloat_(out, depth + 2, "x", diagnostics.imuStartupGyroMeanRaw[0]);
  appendKeyFloat_(out, depth + 2, "y", diagnostics.imuStartupGyroMeanRaw[1]);
  appendKeyFloat_(out, depth + 2, "z", diagnostics.imuStartupGyroMeanRaw[2], false);
  appendIndent_(out, depth + 1);
  out += F("},\n");
  appendKey_(out, depth + 1, "gyro_std_raw");
  out += F("{\n");
  appendKeyFloat_(out, depth + 2, "x", diagnostics.imuStartupGyroStdRaw[0]);
  appendKeyFloat_(out, depth + 2, "y", diagnostics.imuStartupGyroStdRaw[1]);
  appendKeyFloat_(out, depth + 2, "z", diagnostics.imuStartupGyroStdRaw[2], false);
  appendIndent_(out, depth + 1);
  out += F("},\n");
  appendKeyFloat_(out, depth + 1, "accel_magnitude_mean_g", diagnostics.imuStartupAccelMagnitudeMeanG);
  appendKeyFloat_(out, depth + 1, "accel_magnitude_std_g", diagnostics.imuStartupAccelMagnitudeStdG);
  appendKeyFloat_(out, depth + 1, "maximum_gyro_magnitude_dps", diagnostics.imuStartupMaximumGyroMagnitudeDps);
  appendKey_(out, depth + 1, "temperature_deg_c");
  out += F("{\n");
  appendKeyUInt_(out, depth + 2, "samples", diagnostics.imuStartupTemperatureSamples);
  appendKeyFloat_(out, depth + 2, "mean", diagnostics.imuStartupTemperatureMeanC);
  appendKeyFloat_(out, depth + 2, "minimum", diagnostics.imuStartupTemperatureMinimumC);
  appendKeyFloat_(out, depth + 2, "maximum", diagnostics.imuStartupTemperatureMaximumC, false);
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += F("},\n");
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
    appendKeyUInt_(out, depth + 3, "acquire_fail_streak_max", c.acquireFailStreakMax);
    appendKeyUInt_(out, depth + 3, "row_reuse_streak_max", c.rowReuseStreakMax);
    appendKeyUInt_(out, depth + 3, "row_no_sample_streak_max", c.rowNoSampleStreakMax);
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

const char* runtimeEventName_(SensorRuntimeEventType type) {
  switch (type) {
    case SensorRuntimeEventType::LoggingStart: return "logging_start";
    case SensorRuntimeEventType::SchedulerStart: return "scheduler_start";
    case SensorRuntimeEventType::ReadFailureStarted: return "read_failure_started";
    case SensorRuntimeEventType::ReadRecovered: return "read_recovered";
    case SensorRuntimeEventType::ConfigWriteFailed: return "config_write_failed";
    case SensorRuntimeEventType::ConfigWriteRecovered: return "config_write_recovered";
    case SensorRuntimeEventType::SchedulerStop: return "scheduler_stop";
    case SensorRuntimeEventType::LoggingStop: return "logging_stop";
    default: return "unknown";
  }
}

const char* runtimeFailureStageName_(SensorRuntimeFailureStage stage) {
  switch (stage) {
    case SensorRuntimeFailureStage::None: return "none";
    case SensorRuntimeFailureStage::BusUnavailable: return "bus_unavailable";
    case SensorRuntimeFailureStage::BusLock: return "bus_lock";
    case SensorRuntimeFailureStage::Probe: return "probe";
    case SensorRuntimeFailureStage::RegisterAddress: return "register_address";
    case SensorRuntimeFailureStage::RequestBytes: return "request_bytes";
    case SensorRuntimeFailureStage::ReadByte: return "read_byte";
    case SensorRuntimeFailureStage::WriteRegister: return "write_register";
    case SensorRuntimeFailureStage::InvalidArgument: return "invalid_argument";
    case SensorRuntimeFailureStage::WritePayload: return "write_payload";
    case SensorRuntimeFailureStage::EndTransmission: return "end_transmission";
    default: return "unknown";
  }
}

void appendRuntimeFailure_(String& out,
                           uint8_t depth,
                           const char* key,
                           const SensorRuntimeFailure& failure,
                           bool comma = true) {
  appendKey_(out, depth, key);
  out += F("{\n");
  appendKeyString_(out, depth + 1, "stage", runtimeFailureStageName_(failure.stage));
  appendKeyInt_(out, depth + 1, "result_code", failure.resultCode);
  appendKeyUInt_(out, depth + 1, "register_address", failure.registerAddress);
  appendKeyUInt_(out, depth + 1, "expected_bytes", failure.expectedBytes);
  appendKeyUInt_(out, depth + 1, "received_bytes", failure.receivedBytes, false);
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendRuntimeDiagnostics_(String& out, uint8_t depth, bool comma = true) {
  uint8_t sensorCount = 0;
  const uint8_t registered = SensorManager::count();
  SensorRuntimeDiagnostics diagnostics;
  for (uint8_t i = 0; i < registered; ++i) {
    if (SensorManager::describeRuntimeDiagnosticsAt(i, diagnostics) && diagnostics.present) {
      ++sensorCount;
    }
  }

  appendKey_(out, depth, "sensor_runtime_diagnostics");
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "sensor_count", sensorCount);
  appendKey_(out, depth + 1, "sensors");
  out += F("{\n");

  bool wroteSensor = false;
  for (uint8_t i = 0; i < registered; ++i) {
    if (!SensorManager::describeRuntimeDiagnosticsAt(i, diagnostics) || !diagnostics.present) {
      continue;
    }
    if (wroteSensor) out += F(",\n");
    wroteSensor = true;

    appendKey_(out, depth + 2, diagnostics.sensorName);
    out += F("{\n");
    appendKeyString_(out, depth + 3, "kind", diagnostics.kind);
    appendKeyUInt_(out, depth + 3, "bus", diagnostics.busIndex);
    appendKeyUInt_(out, depth + 3, "address", diagnostics.address);

    appendKey_(out, depth + 3, "initialization");
    out += F("{\n");
    appendKeyUInt_(out, depth + 4, "begin_count", diagnostics.beginCount);
    appendKeyUInt_(out, depth + 4, "last_begin_uptime_ms", diagnostics.lastBeginUptimeMs);
    appendKeyBool_(out, depth + 4, "probe_ok", diagnostics.initialProbeOk);
    appendKeyBool_(out, depth + 4, "config_write_attempted", diagnostics.configWriteAttempted);
    appendKeyBool_(out, depth + 4, "config_write_ok", diagnostics.configWriteOk);
    appendKeyBool_(out, depth + 4, "config_read_attempted", diagnostics.configReadAttempted);
    appendKeyBool_(out, depth + 4, "config_read_ok", diagnostics.configReadOk);
    appendKeyHex16_(out, depth + 4, "conf_before", diagnostics.configBefore);
    appendKeyHex16_(out, depth + 4, "conf_after", diagnostics.configAfter);
    appendRuntimeFailure_(out,
                          depth + 4,
                          "failure",
                          diagnostics.initializationFailure,
                          false);
    appendIndent_(out, depth + 3);
    out += F("},\n");

    appendKey_(out, depth + 3, "session");
    out += F("{\n");
    appendKeyUInt_(out, depth + 4, "raw_read_failures", diagnostics.rawReadFailures);
    appendKeyUInt_(out, depth + 4, "diagnostic_read_failures", diagnostics.diagnosticReadFailures);
    appendKeyUInt_(out, depth + 4, "read_failure_streak_max", diagnostics.readFailureStreakMax);
    appendKeyUInt_(out, depth + 4, "read_recoveries", diagnostics.readRecoveries);
    appendKeyBool_(out, depth + 4, "have_last_good_raw", diagnostics.haveLastGoodRaw);
    appendKeyBool_(out, depth + 4, "last_read_ok", diagnostics.lastReadOk);
    appendKeyBool_(out, depth + 4, "last_read_reused", diagnostics.lastReadReused);
    appendKeyUInt_(out, depth + 4, "last_good_raw", diagnostics.lastGoodRaw);
    appendKeyHex16_(out, depth + 4, "last_conf", diagnostics.lastConf);
    appendKeyUInt_(out, depth + 4, "events_recorded", diagnostics.eventCount);
    appendKeyUInt_(out, depth + 4, "events_total", diagnostics.eventsTotal);
    appendKeyUInt_(out, depth + 4, "events_dropped", diagnostics.eventsDropped);
    appendRuntimeFailure_(out, depth + 4, "last_failure", diagnostics.lastFailure, false);
    appendIndent_(out, depth + 3);
    out += F("},\n");

    if (diagnostics.hasImuSession) {
      appendKey_(out, depth + 3, "imu_session");
      out += F("{\n");
      appendKeyUInt_(out, depth + 4, "drain_calls", diagnostics.imuDrainCalls);
      appendKeyUInt_(out, depth + 4, "drain_passes", diagnostics.imuDrainPasses);
      appendKeyUInt_(out, depth + 4, "empty_passes", diagnostics.imuEmptyPasses);
      appendKeyUInt_(out, depth + 4, "drain_pass_limit_hits", diagnostics.imuDrainPassLimitHits);
      appendKeyUInt_(out, depth + 4, "fifo_bytes_read", diagnostics.imuFifoBytesRead);
      appendKeyUInt_(out, depth + 4, "fifo_frames_parsed", diagnostics.imuFifoFramesParsed);
      appendKeyUInt_(out, depth + 4, "sensor_time_frames", diagnostics.imuSensorTimeFrames);
      appendKeyUInt_(out, depth + 4, "missing_sensor_time_batches", diagnostics.imuMissingSensorTimeBatches);
      appendKeyUInt_(out, depth + 4, "fifo_skip_control_frames", diagnostics.imuSkipControlFrames);
      appendKeyUInt_(out, depth + 4, "fifo_overflow_events", diagnostics.imuFifoOverflowEvents);
      appendKeyUInt_(out, depth + 4, "fifo_full_observations", diagnostics.imuFifoFullObservations);
      appendKeyUInt_(out, depth + 4, "hardware_skipped_frames", diagnostics.imuHardwareSkippedFrames);
      appendKeyUInt_(out, depth + 4, "unpaired_frames", diagnostics.imuUnpairedFrames);
      appendKeyUInt_(out, depth + 4, "input_config_frames", diagnostics.imuInputConfigFrames);
      appendKeyUInt_(out, depth + 4, "invalid_headers", diagnostics.imuInvalidHeaders);
      appendKeyUInt_(out, depth + 4, "partial_frames", diagnostics.imuPartialFrames);
      appendKeyUInt_(out, depth + 4, "overread_frames", diagnostics.imuOverreadFrames);
      appendKeyUInt_(out, depth + 4, "parser_output_drops", diagnostics.imuParserOutputDrops);
      appendKeyUInt_(out, depth + 4, "samples_enqueued", diagnostics.imuSamplesEnqueued);
      appendKeyUInt_(out, depth + 4, "samples_emitted", diagnostics.imuSamplesEmitted);
      appendKeyUInt_(out, depth + 4, "queue_drops", diagnostics.imuQueueDrops);
      appendKeyUInt_(out, depth + 4, "queue_capacity", diagnostics.imuQueueCapacity);
      appendKeyUInt_(out, depth + 4, "queue_high_water", diagnostics.imuQueueHighWater);
      appendKeyUInt_(out, depth + 4, "final_queue_depth", diagnostics.imuFinalQueueDepth);
      appendKeyUInt_(out, depth + 4, "pre_session_queue_discards", diagnostics.imuPreSessionQueueDiscards);
      appendKeyUInt_(out, depth + 4, "explicit_queue_discards", diagnostics.imuExplicitQueueDiscards);
      appendKeyUInt_(out, depth + 4, "temperature_reads", diagnostics.imuTemperatureReads);
      appendKeyUInt_(out, depth + 4, "temperature_read_failures", diagnostics.imuTemperatureReadFailures);
      appendKeyUInt_(out, depth + 4, "operational_validation_attempts", diagnostics.imuOperationalValidationAttempts);
      appendKeyUInt_(out, depth + 4, "operational_validation_failures", diagnostics.imuOperationalValidationFailures);
      appendKeyUInt_(out, depth + 4, "session_start_validation_attempts", diagnostics.imuSessionStartValidationAttempts);
      appendKeyUInt_(out, depth + 4, "session_start_validation_failures", diagnostics.imuSessionStartValidationFailures);
      appendKeyUInt_(out, depth + 4, "no_progress_timeout_us", diagnostics.imuNoProgressTimeoutUs);
      appendKeyUInt_(out, depth + 4, "no_progress_events", diagnostics.imuNoProgressEvents);
      appendKeyUInt_(out, depth + 4, "maximum_no_progress_us", diagnostics.imuMaximumNoProgressUs);
      appendKeyUInt_(out, depth + 4, "last_validation_issues", diagnostics.imuLastValidationIssues);
      appendKeyInt_(out, depth + 4, "last_validation_api_result", diagnostics.imuLastValidationApiResult);
      appendKeyUInt_(out, depth + 4, "last_validation_chip_id", diagnostics.imuLastValidationChipId);
      appendKeyUInt_(out, depth + 4, "last_validation_internal_status", diagnostics.imuLastValidationInternalStatus);
      appendKeyUInt_(out, depth + 4, "last_validation_power_control", diagnostics.imuLastValidationPowerControl);
      appendKeyUInt_(out, depth + 4, "last_validation_fifo_config", diagnostics.imuLastValidationFifoConfig);
      appendKeyUInt_(out, depth + 4, "last_validation_fifo_watermark", diagnostics.imuLastValidationFifoWatermark);
      appendKeyUInt_(out, depth + 4, "last_validation_accel_downsample", diagnostics.imuLastValidationAccelDownsample);
      appendKeyUInt_(out, depth + 4, "last_validation_gyro_downsample", diagnostics.imuLastValidationGyroDownsample);
      appendKeyUInt_(out, depth + 4, "last_validation_accel_filtered", diagnostics.imuLastValidationAccelFiltered);
      appendKeyUInt_(out, depth + 4, "last_validation_gyro_filtered", diagnostics.imuLastValidationGyroFiltered);
      appendKeyUInt_(out, depth + 4, "fifo_flushes", diagnostics.imuFifoFlushes);
      appendKeyUInt_(out, depth + 4, "fifo_flush_failures", diagnostics.imuFifoFlushFailures);
      appendKeyUInt_(out, depth + 4, "stop_drain_attempts", diagnostics.imuStopDrainAttempts);
      appendKeyUInt_(out, depth + 4, "stop_drain_failures", diagnostics.imuStopDrainFailures);
      appendKeyUInt_(out, depth + 4, "maximum_fifo_bytes_observed", diagnostics.imuMaximumFifoBytesObserved);
      appendKeyUInt_(out, depth + 4, "maximum_drain_duration_us", diagnostics.imuMaximumDrainDurationUs);
      appendKeyUInt_(out, depth + 4, "maximum_drain_failure_streak", diagnostics.imuMaximumDrainFailureStreak);
      appendKeyUInt_(out, depth + 4, "i2c_operations", diagnostics.imuI2cOperations);
      appendKeyUInt_(out, depth + 4, "i2c_failures", diagnostics.imuI2cFailures);
      appendKeyUInt_(out, depth + 4, "i2c_recoveries", diagnostics.imuI2cRecoveries);
      appendKeyUInt_(out, depth + 4, "i2c_maximum_failure_streak", diagnostics.imuI2cMaximumFailureStreak);
      appendKeyUInt_(out, depth + 4, "i2c_bus_lock_attempts", diagnostics.imuI2cBusLockAttempts);
      appendKeyUInt_(out, depth + 4, "i2c_bus_lock_timeouts", diagnostics.imuI2cBusLockTimeouts);
      appendKeyUInt_(out, depth + 4, "i2c_bus_lock_wait_total_us", diagnostics.imuI2cBusLockWaitTotalUs);
      appendKeyUInt_(out, depth + 4, "i2c_bus_lock_wait_maximum_us", diagnostics.imuI2cBusLockWaitMaximumUs);
      appendKey_(out, depth + 4, "i2c_failures_by_stage");
      out += F("{\n");
      appendKeyUInt_(out, depth + 5, "invalid_argument", diagnostics.imuI2cFailureStageCounts[1]);
      appendKeyUInt_(out, depth + 5, "bus_unavailable", diagnostics.imuI2cFailureStageCounts[2]);
      appendKeyUInt_(out, depth + 5, "bus_lock_timeout", diagnostics.imuI2cFailureStageCounts[3]);
      appendKeyUInt_(out, depth + 5, "register_address", diagnostics.imuI2cFailureStageCounts[4]);
      appendKeyUInt_(out, depth + 5, "write_payload", diagnostics.imuI2cFailureStageCounts[5]);
      appendKeyUInt_(out, depth + 5, "end_transmission", diagnostics.imuI2cFailureStageCounts[6]);
      appendKeyUInt_(out, depth + 5, "request_bytes", diagnostics.imuI2cFailureStageCounts[7]);
      appendKeyUInt_(out, depth + 5, "read_bytes", diagnostics.imuI2cFailureStageCounts[8], false);
      appendIndent_(out, depth + 4);
      out += F("},\n");
      appendKeyUInt_(out, depth + 4, "recovery_attempts", diagnostics.imuRecoveryAttempts);
      appendKeyUInt_(out, depth + 4, "recovery_successes", diagnostics.imuRecoverySuccesses);
      appendKeyUInt_(out, depth + 4, "recovery_failures", diagnostics.imuRecoveryFailures);
      appendKeyUInt_(out, depth + 4, "last_recovery_reason", diagnostics.imuLastRecoveryReason);
      appendKeyUInt_(out, depth + 4, "consecutive_recovery_failures", diagnostics.imuConsecutiveRecoveryFailures);
      appendKeyUInt_(out, depth + 4, "recovery_attempts_without_progress", diagnostics.imuRecoveryAttemptsWithoutProgress);
      appendKeyUInt_(out, depth + 4, "terminal_fault_events", diagnostics.imuTerminalFaultEvents);
      appendKeyBool_(out, depth + 4, "terminal_fault", diagnostics.imuTerminalFault);
      appendImuQualityDiagnostics_(out, depth + 4, diagnostics);
      appendKeyBool_(out, depth + 4, "counter_saturated", diagnostics.imuCounterSaturated, false);
      appendIndent_(out, depth + 3);
      out += F("},\n");
    }

    appendKey_(out, depth + 3, "events");
    out += F("[\n");
    for (uint8_t eventIndex = 0; eventIndex < diagnostics.eventCount; ++eventIndex) {
      const SensorRuntimeEvent& event = diagnostics.events[eventIndex];
      appendIndent_(out, depth + 4);
      out += F("{\n");
      appendKeyString_(out, depth + 5, "type", runtimeEventName_(event.type));
      appendKeyUInt_(out, depth + 5, "uptime_ms", event.uptimeMs);
      appendKeyUInt_(out, depth + 5, "acquisition_seq", event.acquisitionSeq);
      appendKeyUInt_(out, depth + 5, "raw_read_failures", event.rawReadFailures);
      appendKeyUInt_(out, depth + 5, "raw", event.raw);
      appendKeyHex16_(out, depth + 5, "conf", event.conf);
      appendKeyBool_(out, depth + 5, "have_sample", event.haveSample);
      appendKeyBool_(out, depth + 5, "read_ok", event.readOk);
      appendKeyBool_(out, depth + 5, "reused", event.reused);
      appendKeyBool_(out, depth + 5, "analog_rail_enabled", event.analogRailEnabled);
      appendKeyBool_(out, depth + 5, "analog_rail_fault", event.analogRailFault);
      appendRuntimeFailure_(out, depth + 5, "failure", event.failure, false);
      appendIndent_(out, depth + 4);
      out += (eventIndex + 1 < diagnostics.eventCount) ? F("},\n") : F("}\n");
    }
    appendIndent_(out, depth + 3);
    out += F("]\n");
    appendIndent_(out, depth + 2);
    out += F("}");
  }

  if (wroteSensor) out += '\n';
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

const char* storageTypeName_(StorageType t) {
  switch (t) {
    case StorageType::UInt16: return "uint16";
    case StorageType::Int16: return "int16";
    case StorageType::Int32: return "int32";
    case StorageType::UInt32: return "uint32";
    case StorageType::Float32:
    default: return "float32";
  }
}

uint16_t storageTypeSize_(StorageType t) {
  switch (t) {
    case StorageType::UInt16: return 2;
    case StorageType::Int16: return 2;
    case StorageType::Int32: return 4;
    case StorageType::UInt32: return 4;
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
  switch (desc.storageType) {
    case SensorColumnStorageType::UInt16: return StorageType::UInt16;
    case SensorColumnStorageType::Int16: return StorageType::Int16;
    case SensorColumnStorageType::Int32: return StorageType::Int32;
    case SensorColumnStorageType::UInt32: return StorageType::UInt32;
    case SensorColumnStorageType::Float32: return StorageType::Float32;
    case SensorColumnStorageType::Automatic:
    default:
      if (!desc.raw) return StorageType::Float32;
      return isUnwrappedRaw_(desc) ? StorageType::Int32 : StorageType::UInt16;
  }
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

void appendImuConfigObject_(
    String& out,
    const SensorImuConfigDescriptor& imu,
    uint8_t depth,
    bool comma) {
  out += F("{\n");
  appendKeyString_(out, depth + 1, "contract_id", imu.contractId);
  appendKeyString_(out, depth + 1, "imu_id", imu.imuId);
  appendKeyString_(out, depth + 1, "domain", imu.domain);
  if (imu.end[0]) appendKeyString_(out, depth + 1, "end", imu.end);
  if (imu.mountPoint[0]) appendKeyString_(out, depth + 1, "mount_point", imu.mountPoint);
  // Retained for readers of the original MVP metadata shape.
  appendKeyString_(out, depth + 1, "location", imu.location);
  appendKeyUInt_(out, depth + 1, "i2c_bus", imu.busIndex);
  appendKeyUInt_(out, depth + 1, "i2c_address", imu.address);
  appendKeyUInt_(out, depth + 1, "i2c_clock_hz", imu.i2cClockHz);
  appendKeyUInt_(out, depth + 1, "chip_id", imu.chipId);
  appendKeyBool_(out, depth + 1, "initialization_ok", imu.initializationOk);
  appendKeyString_(out, depth + 1, "requested_profile", imu.profile);
  appendKeyString_(out, depth + 1, "driver_revision", imu.driverRevision);
  appendKeyString_(out, depth + 1, "calibration_ref", imu.calibrationRef);
  appendKeyUInt_(out, depth + 1, "logger_rate_hz", imu.loggerRateHz);
  appendKeyUInt_(out, depth + 1, "imu_rate_hz", imu.imuRateHz);

  appendKey_(out, depth + 1, "mount_transform");
  out += F("{\n");
  appendKeyString_(out, depth + 2, "from", "sensor_native");
  appendKeyString_(out, depth + 2, "to", "body_local");
  appendKeyString_(out, depth + 2, "representation", "signed_axis_permutation");
  appendKeyString_(out, depth + 2, "body_x", imu.mountAxis[0]);
  appendKeyString_(out, depth + 2, "body_y", imu.mountAxis[1]);
  appendKeyString_(out, depth + 2, "body_z", imu.mountAxis[2], false);
  appendIndent_(out, depth + 1);
  out += F("},\n");

  appendKey_(out, depth + 1, "effective_config");
  out += F("{\n");
  appendKeyBool_(out, depth + 2, "matched", imu.effectiveConfigMatched);
  appendKeyUInt_(out, depth + 2, "config_file_major", imu.configFileMajor);
  appendKeyUInt_(out, depth + 2, "config_file_minor", imu.configFileMinor);
  appendKeyUInt_(out, depth + 2, "accel_odr_hz", 200);
  appendKeyUInt_(out, depth + 2, "accel_range_g", 16);
  appendKeyString_(out, depth + 2, "accel_bandwidth", "normal_avg4");
  appendKeyString_(out, depth + 2, "accel_filter_performance", "performance_optimized");
  appendKeyUInt_(out, depth + 2, "gyro_odr_hz", 200);
  appendKeyUInt_(out, depth + 2, "gyro_range_dps", 2000);
  appendKeyString_(out, depth + 2, "gyro_bandwidth", "normal");
  appendKeyString_(out, depth + 2, "gyro_noise_performance", "power_optimized");
  appendKeyString_(out, depth + 2, "gyro_filter_performance", "performance_optimized");
  appendKeyUInt_(out, depth + 2, "accel_odr_code", imu.accelOdr);
  appendKeyUInt_(out, depth + 2, "accel_range_code", imu.accelRange);
  appendKeyUInt_(out, depth + 2, "accel_bandwidth_code", imu.accelBandwidth);
  appendKeyUInt_(out, depth + 2, "accel_filter_performance_code", imu.accelFilterPerformance);
  appendKeyUInt_(out, depth + 2, "gyro_odr_code", imu.gyroOdr);
  appendKeyUInt_(out, depth + 2, "gyro_range_code", imu.gyroRange);
  appendKeyUInt_(out, depth + 2, "gyro_bandwidth_code", imu.gyroBandwidth);
  appendKeyUInt_(out, depth + 2, "gyro_noise_performance_code", imu.gyroNoisePerformance);
  appendKeyUInt_(out, depth + 2, "gyro_filter_performance_code", imu.gyroFilterPerformance, false);
  appendIndent_(out, depth + 1);
  out += F("},\n");

  appendKey_(out, depth + 1, "fifo");
  out += F("{\n");
  appendKeyString_(out, depth + 2, "mode", "header");
  appendKeyString_(out, depth + 2, "content", "accel,gyro,sensor_time");
  appendKeyUInt_(out, depth + 2, "poll_rate_hz", imu.fifoPollRateHz);
  appendKeyUInt_(out, depth + 2, "watermark", imu.fifoWatermark);
  appendKeyUInt_(out, depth + 2, "effective_config", imu.fifoConfig, false);
  appendIndent_(out, depth + 1);
  out += F("},\n");

  appendKey_(out, depth + 1, "sensor_time");
  out += F("{\n");
  appendKeyUInt_(out, depth + 2, "tick_numerator_us", 625);
  appendKeyUInt_(out, depth + 2, "tick_denominator", 16);
  appendKeyUInt_(out, depth + 2, "modulus_ticks", 16777216, false);
  appendIndent_(out, depth + 1);
  out += F("},\n");

  appendKey_(out, depth + 1, "temperature");
  out += F("{\n");
  appendKeyUInt_(out, depth + 2, "observation_rate_hz", imu.temperatureRateHz);
  appendKeyUInt_(out, depth + 2, "freshness_limit_us", imu.temperatureFreshnessUs);
  appendKeyString_(out, depth + 2, "sample_policy", "latest_held_value", false);
  appendIndent_(out, depth + 1);
  out += F("},\n");

  appendKeyUInt_(out, depth + 1, "startup_bias_capture_s", imu.startupBiasCaptureSeconds);
  appendKeyString_(out, depth + 1, "row_policy", "sparse_once_sample_valid");
  appendKeyString_(out, depth + 1, "invalid_placeholder_policy", "zero_except_sample_age_us_nan", false);
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

bool appendImuConfigs_(String& out) {
  const uint16_t sensorCount = SensorManager::describeSensors(nullptr, 0);
  SensorMetadataDescriptor* sensors = sensorCount ? new (std::nothrow) SensorMetadataDescriptor[sensorCount] : nullptr;
  if (sensorCount && !sensors) return false;
  const uint16_t sensorsWritten = SensorManager::describeSensors(sensors, sensorCount);
  uint16_t imuCount = 0;
  for (uint16_t i = 0; i < sensorsWritten; ++i) if (sensors[i].hasImuConfig) ++imuCount;
  if (imuCount == 0) {
    delete[] sensors;
    return false;
  }

  appendKey_(out, 1, "imu_configs");
  out += F("{\n");
  uint16_t written = 0;
  for (uint16_t i = 0; i < sensorsWritten; ++i) {
    if (!sensors[i].hasImuConfig) continue;
    appendIndent_(out, 2);
    appendJsonEscaped_(out, sensors[i].sensorId[0] ? sensors[i].sensorId : sensors[i].name);
    out += F(": ");
    appendImuConfigObject_(out, sensors[i].imuConfig, 2, ++written < imuCount);
  }
  appendIndent_(out, 1);
  out += F("},\n");
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
    copyField_(col.mountPoint, sizeof(col.mountPoint), desc.mountPoint);
    copyField_(col.quantity, sizeof(col.quantity), desc.quantity);
    copyField_(col.component, sizeof(col.component), desc.component);
    copyField_(col.coordinateFrame, sizeof(col.coordinateFrame), desc.coordinateFrame);
    copyField_(col.vectorGroup, sizeof(col.vectorGroup), desc.vectorGroup);
    copyField_(col.unit, sizeof(col.unit), desc.unit);
    copyField_(col.source, sizeof(col.source), desc.source);
    copyField_(col.kind, sizeof(col.kind), desc.kind);
    copyField_(col.processingRole, sizeof(col.processingRole), desc.processingRole);
    copyField_(col.columnClass, sizeof(col.columnClass), desc.diagnostic ? "diagnostic" : "signal");
    col.semanticSelectionExcluded = desc.semanticSelectionExcluded;
    col.allowNaN = desc.allowNaN;
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
  appendImuConfigs_(out);
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
                        const char* mountPoint,
                        const char* component,
                        const char* coordinateFrame,
                        const char* vectorGroup,
                        const char* source,
                        const char* kind,
                        const char* processingRole,
                        const char* columnClass,
                        bool raw,
                        bool semanticSelectionExcluded,
                        bool allowNaN,
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
  if (mountPoint && *mountPoint) appendKeyString_(out, 3, "mount_point", mountPoint);
  if (component && *component) appendKeyString_(out, 3, "component", component);
  if (coordinateFrame && *coordinateFrame) appendKeyString_(out, 3, "coordinate_frame", coordinateFrame);
  if (vectorGroup && *vectorGroup) appendKeyString_(out, 3, "vector_group", vectorGroup);
  if (source && *source) appendKeyString_(out, 3, "source", source);
  if ((kind && *kind) || raw) appendKeyString_(out, 3, "kind", kind && *kind ? kind : "raw");
  if (processingRole && *processingRole) appendKeyString_(out, 3, "processing_role", processingRole);
  if (semanticSelectionExcluded) appendKeyBool_(out, 3, "semantic_selection_excluded", true);
  if (allowNaN) appendKeyBool_(out, 3, "nan_allowed", true);
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
  appendChannelJson_(out, "sample_id", "sample_index", "sample", "uint32", 0, "", "", "", "", "", "", "", "frame", "", "", "index", false, false, false, true);

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
                       col.mountPoint,
                       col.component,
                       col.coordinateFrame,
                       col.vectorGroup,
                       col.source,
                       col.kind,
                       col.processingRole,
                       col.columnClass,
                       col.raw,
                       col.semanticSelectionExcluded,
                       col.allowNaN,
                       comma);
  }

  appendChannelJson_(out, "flags", "flags", "bitfield", "uint16", (uint16_t)(s_frameSize - 2), "", "", "", "", "", "", "", "frame", "qc", "qc_metric", "qc_flag", false, true, false, false);
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

int16_t floatToI16_(float value, uint16_t& flags) {
  flags = flagsFromValueError_(flags, value);
  if (!isfinite(value)) return 0;
  double rounded = round((double)value);
  if (rounded < -32768.0) {
    flags = (uint16_t)(flags | SAMPLE_FLAG_SENSOR_ERR);
    return INT16_MIN;
  }
  if (rounded > 32767.0) {
    flags = (uint16_t)(flags | SAMPLE_FLAG_SENSOR_ERR);
    return INT16_MAX;
  }
  return (int16_t)rounded;
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

uint32_t floatToU32_(float value, uint16_t& flags) {
  flags = flagsFromValueError_(flags, value);
  if (!isfinite(value)) return 0;
  double rounded = round((double)value);
  if (rounded < 0.0) {
    flags = (uint16_t)(flags | SAMPLE_FLAG_SENSOR_ERR);
    return 0;
  }
  if (rounded > 4294967295.0) {
    flags = (uint16_t)(flags | SAMPLE_FLAG_SENSOR_ERR);
    return UINT32_MAX;
  }
  return (uint32_t)rounded;
}

void putFloat32_(uint8_t* out, float value, uint16_t& flags, bool allowNaN) {
  if (!(allowNaN && isnan(value))) {
    flags = flagsFromValueError_(flags, value);
  }
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
      case StorageType::Int16:
        putU16_(dst, (uint16_t)floatToI16_(value, flags));
        break;
      case StorageType::Int32:
        putU32_(dst, (uint32_t)floatToI32_(value, flags));
        break;
      case StorageType::UInt32:
        putU32_(dst, floatToU32_(value, flags));
        break;
      case StorageType::Float32:
      default:
        putFloat32_(dst, value, flags, col.allowNaN);
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
  out.reserve(4096);
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
  appendKeyUInt_(out, 1, "flush_total_ms", info.flushTotalMs);
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
  appendI2CBusDiagnostics_(out, 1, info.boardProfile);
#endif
  appendRuntimeDiagnostics_(out, 1, false);
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
