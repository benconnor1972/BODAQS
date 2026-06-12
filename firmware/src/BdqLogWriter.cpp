#include "BdqLogWriter.h"

#include <math.h>
#include <string.h>
#include <stdlib.h>
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

void appendKeyBool_(String& out, uint8_t depth, const char* key, bool value, bool comma = true) {
  appendKey_(out, depth, key);
  out += value ? F("true") : F("false");
  out += comma ? F(",\n") : F("\n");
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
  out.reserve(768);
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
                        bool raw,
                        bool semanticSelectionExcluded,
                        bool comma) {
  out += F("    {\n");
  appendKeyString_(out, 3, "field", field);
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
  appendChannelJson_(out, "sample_id", "sample_index", "sample", "uint32", 0, "", "", "", "frame", "", "", false, false, true);

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
                       col.raw,
                       col.semanticSelectionExcluded,
                       comma);
  }

  appendChannelJson_(out, "flags", "flags", "bitfield", "uint16", (uint16_t)(s_frameSize - 2), "", "", "", "frame", "qc", "qc_metric", false, true, false);
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
  appendKeyUInt_(out, 1, "flush_total_ms", info.flushTotalMs, false);
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
