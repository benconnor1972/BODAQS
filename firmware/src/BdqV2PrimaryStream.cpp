#include "BdqV2PrimaryStream.h"

#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "BdqV2Format.h"

namespace {

const BdqV2CatalogStatusFlag kPrimaryStatusFlags[] = {
    {"discontinuity_before", BdqV2Format::DiscontinuityBefore},
    {"producer_queue_drop_before", BdqV2Format::ProducerQueueDropBefore},
    {"sensor_error", BdqV2PrimaryStreamSchema::kSensorErrorStatus},
};

bool isUnwrappedRaw_(const SensorColumnDescriptor& column) {
  return strcasecmp(column.source, "unwrapped_raw_counts") == 0 ||
         strcasecmp(column.source, "unwrapped_raw") == 0 ||
         strstr(column.columnId, "unwrapped") != nullptr ||
         strstr(column.csvHeader, "unwrapped") != nullptr;
}

const char* nonEmptyOr_(const char* value, const char* fallback) {
  return value && value[0] ? value : fallback;
}

uint16_t clampUInt16_(float value, uint16_t& status) {
  if (!isfinite(value) || value < 0.0f) {
    status |= BdqV2PrimaryStreamSchema::kSensorErrorStatus;
    return 0;
  }
  if (value > 65535.0f) {
    status |= BdqV2PrimaryStreamSchema::kSensorErrorStatus;
    return UINT16_MAX;
  }
  return static_cast<uint16_t>(lroundf(value));
}

int16_t clampInt16_(float value, uint16_t& status) {
  if (!isfinite(value)) {
    status |= BdqV2PrimaryStreamSchema::kSensorErrorStatus;
    return 0;
  }
  const double rounded = round(static_cast<double>(value));
  if (rounded < INT16_MIN) {
    status |= BdqV2PrimaryStreamSchema::kSensorErrorStatus;
    return INT16_MIN;
  }
  if (rounded > INT16_MAX) {
    status |= BdqV2PrimaryStreamSchema::kSensorErrorStatus;
    return INT16_MAX;
  }
  return static_cast<int16_t>(rounded);
}

int32_t clampInt32_(float value, uint16_t& status) {
  if (!isfinite(value)) {
    status |= BdqV2PrimaryStreamSchema::kSensorErrorStatus;
    return 0;
  }
  const double rounded = round(static_cast<double>(value));
  if (rounded < static_cast<double>(INT32_MIN)) {
    status |= BdqV2PrimaryStreamSchema::kSensorErrorStatus;
    return INT32_MIN;
  }
  if (rounded > static_cast<double>(INT32_MAX)) {
    status |= BdqV2PrimaryStreamSchema::kSensorErrorStatus;
    return INT32_MAX;
  }
  return static_cast<int32_t>(rounded);
}

uint32_t clampUInt32_(float value, uint16_t& status) {
  if (!isfinite(value) || value < 0.0f) {
    status |= BdqV2PrimaryStreamSchema::kSensorErrorStatus;
    return 0;
  }
  const double rounded = round(static_cast<double>(value));
  if (rounded > static_cast<double>(UINT32_MAX)) {
    status |= BdqV2PrimaryStreamSchema::kSensorErrorStatus;
    return UINT32_MAX;
  }
  return static_cast<uint32_t>(rounded);
}

}  // namespace

bool BdqV2PrimaryStreamSchema::configure(
    const SensorColumnDescriptor* columns,
    uint16_t columnCount,
    uint16_t sampleRateHz,
    const BdqV2StreamSource& source) {
  if ((!columns && columnCount != 0) ||
      columnCount > LoggerLimits::kMaxDynamicColumns ||
      sampleRateHz == 0 || source.streamId != kStreamId) {
    return false;
  }

  descriptor_ = BdqV2StreamDescriptor{};
  columnCount_ = columnCount;
  descriptor_.source = source;
  snprintf(descriptor_.streamKey, sizeof(descriptor_.streamKey), "primary");
  snprintf(descriptor_.transport, sizeof(descriptor_.transport), "internal");
  snprintf(descriptor_.clockId, sizeof(descriptor_.clockId), "logger_monotonic");
  snprintf(descriptor_.clockRelation, sizeof(descriptor_.clockRelation), "logger_clock");
  descriptor_.nativeTickBits = 32;
  descriptor_.nominalTickPeriodNumeratorUs = 1;
  descriptor_.nominalTickPeriodDenominator = 1;
  descriptor_.nominalSampleRateNumeratorHz = sampleRateHz;
  descriptor_.nominalSampleRateDenominator = 1;
  descriptor_.expectedSequenceStep = 1;

  catalogChannels_[0] = {
      "sequence", "sample_sequence", "count", "uint32", 0, "diagnostic"};
  catalogChannels_[1] = {
      "native_tick", "logger_monotonic_time", "us", "uint32", 4, "diagnostic"};
  catalogChannels_[2] = {
      "status_flags", "status", "bitfield", "uint16", 8, "diagnostic"};

  uint16_t offset = BdqV2Format::kStreamRecordPrefixBytes;
  for (uint16_t index = 0; index < columnCount_; ++index) {
    const SensorColumnDescriptor& column = columns[index];
    ColumnLayout& layout = layout_[index];
    const char* storageType = "float32";
    uint16_t storageBytes = 4;
    switch (column.storageType) {
      case SensorColumnStorageType::UInt16:
        layout.storage = StorageType::UInt16;
        storageType = "uint16";
        storageBytes = 2;
        break;
      case SensorColumnStorageType::Int16:
        layout.storage = StorageType::Int16;
        storageType = "int16";
        storageBytes = 2;
        break;
      case SensorColumnStorageType::Int32:
        layout.storage = StorageType::Int32;
        storageType = "int32";
        break;
      case SensorColumnStorageType::UInt32:
        layout.storage = StorageType::UInt32;
        storageType = "uint32";
        break;
      case SensorColumnStorageType::Float32:
        layout.storage = StorageType::Float32;
        break;
      case SensorColumnStorageType::Automatic:
      default:
        if (column.raw) {
          if (isUnwrappedRaw_(column)) {
            layout.storage = StorageType::Int32;
            storageType = "int32";
          } else {
            layout.storage = StorageType::UInt16;
            storageType = "uint16";
            storageBytes = 2;
          }
        } else {
          layout.storage = StorageType::Float32;
        }
        break;
    }
    layout.byteOffset = offset;
    layout.allowNaN = column.allowNaN;

    BdqV2CatalogChannel& catalog = catalogChannels_[index + 3];
    catalog = BdqV2CatalogChannel{};
    catalog.field = nonEmptyOr_(column.columnId, column.csvHeader);
    catalog.quantity = nonEmptyOr_(column.quantity, column.raw ? "raw" : "value");
    catalog.unit = nonEmptyOr_(column.unit, column.raw ? "count" : "unknown");
    catalog.storageType = storageType;
    catalog.byteOffset = offset;
    catalog.columnClass = column.diagnostic ? "diagnostic" : "signal";
    catalog.component = column.component;
    catalog.coordinateFrame = column.coordinateFrame;
    catalog.vectorGroup = column.vectorGroup;
    catalog.sensor = column.sensorName;
    catalog.domain = column.domain;
    catalog.end = column.end;
    offset = static_cast<uint16_t>(offset + storageBytes);
  }

  descriptor_.source.recordSizeBytes = offset;
  descriptor_.channels = catalogChannels_;
  descriptor_.channelCount = static_cast<size_t>(columnCount_) + 3u;
  descriptor_.statusFlags = kPrimaryStatusFlags;
  descriptor_.statusFlagCount =
      sizeof(kPrimaryStatusFlags) / sizeof(kPrimaryStatusFlags[0]);
  return descriptor_.valid();
}

bool BdqV2PrimaryStreamSchema::encodeRecord(
    uint32_t sequence,
    uint32_t hostMonotonicUs,
    uint16_t streamStatusFlags,
    const float* values,
    uint16_t valueCount,
    uint8_t* destination,
    size_t capacity) const {
  const uint16_t recordSize = descriptor_.source.recordSizeBytes;
  if (recordSize < BdqV2Format::kStreamRecordPrefixBytes ||
      !destination || capacity < recordSize ||
      (!values && valueCount != 0)) {
    return false;
  }
  memset(destination, 0, recordSize);
  uint16_t status = streamStatusFlags;
  if (valueCount < columnCount_) status |= kSensorErrorStatus;

  for (uint16_t index = 0; index < columnCount_; ++index) {
    const ColumnLayout& layout = layout_[index];
    const float value = index < valueCount ? values[index] : NAN;
    uint8_t* output = destination + layout.byteOffset;
    switch (layout.storage) {
      case StorageType::UInt16:
        BdqV2Format::putU16(output, clampUInt16_(value, status));
        break;
      case StorageType::Int16:
        BdqV2Format::putU16(
            output, static_cast<uint16_t>(clampInt16_(value, status)));
        break;
      case StorageType::Int32:
        BdqV2Format::putU32(
            output, static_cast<uint32_t>(clampInt32_(value, status)));
        break;
      case StorageType::UInt32:
        BdqV2Format::putU32(output, clampUInt32_(value, status));
        break;
      case StorageType::Float32:
      default: {
        float stored = value;
        if (!isfinite(stored) && !(layout.allowNaN && isnan(stored))) {
          status |= kSensorErrorStatus;
        }
        if (!isfinite(stored)) stored = NAN;
        uint32_t raw = 0;
        memcpy(&raw, &stored, sizeof(raw));
        BdqV2Format::putU32(output, raw);
        break;
      }
    }
  }

  BdqV2Format::StreamRecordPrefix prefix;
  prefix.sequence = sequence;
  prefix.nativeTick = hostMonotonicUs;
  prefix.statusFlags = status;
  return BdqV2Format::encodeStreamRecordPrefix(
      prefix, destination, capacity);
}

static_assert(sizeof(float) == 4, "BDQ v2 primary stream requires float32");
