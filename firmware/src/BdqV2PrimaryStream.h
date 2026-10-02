#pragma once

#include <stddef.h>
#include <stdint.h>

#include "BdqV2Catalog.h"
#include "LoggerLimits.h"
#include "Sensor.h"

class BdqV2PrimaryStreamSchema {
public:
  static constexpr uint16_t kStreamId = 1;
  static constexpr uint16_t kSensorErrorStatus = 0x0020;

  bool configure(
      const SensorColumnDescriptor* columns,
      uint16_t columnCount,
      uint16_t sampleRateHz,
      const BdqV2StreamSource& source);

  bool encodeRecord(
      uint32_t sequence,
      uint32_t hostMonotonicUs,
      uint16_t streamStatusFlags,
      const float* values,
      uint16_t valueCount,
      uint8_t* destination,
      size_t capacity) const;

  const BdqV2StreamDescriptor& descriptor() const { return descriptor_; }
  uint16_t recordSizeBytes() const { return descriptor_.source.recordSizeBytes; }
  uint16_t columnCount() const { return columnCount_; }

private:
  enum class StorageType : uint8_t {
    UInt16,
    Int16,
    Int32,
    UInt32,
    Float32,
  };

  struct ColumnLayout {
    StorageType storage = StorageType::Float32;
    uint16_t byteOffset = 0;
    bool allowNaN = false;
  };

  static constexpr size_t kCatalogChannelCount =
      LoggerLimits::kMaxDynamicColumns + 3;

  BdqV2StreamDescriptor descriptor_;
  BdqV2CatalogChannel catalogChannels_[kCatalogChannelCount] {};
  ColumnLayout layout_[LoggerLimits::kMaxDynamicColumns] {};
  uint16_t columnCount_ = 0;
};

