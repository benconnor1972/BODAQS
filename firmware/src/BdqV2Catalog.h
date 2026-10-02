#pragma once

#include <stddef.h>
#include <stdint.h>

#include "BdqV2StreamSource.h"

struct BdqV2CatalogChannel {
  const char* field = nullptr;
  const char* quantity = nullptr;
  const char* unit = nullptr;
  const char* storageType = nullptr;
  uint16_t byteOffset = 0;
  const char* columnClass = nullptr;
  const char* component = nullptr;
  const char* coordinateFrame = nullptr;
  const char* vectorGroup = nullptr;
  const char* sensor = nullptr;
  const char* domain = nullptr;
  const char* end = nullptr;
};

struct BdqV2CatalogStatusFlag {
  const char* name = nullptr;
  uint16_t mask = 0;
};

struct BdqV2StreamDescriptor {
  BdqV2StreamSource source;
  char streamKey[40] {};
  char streamKind[20] {"regular"};
  char sensorId[32] {};
  char transport[24] {};
  char clockId[56] {};
  char clockRelation[24] {"independent"};
  char recordFormat[24] {"fixed_mixed_v2"};
  char requestedProfile[32] {};
  char domain[24] {};
  char end[16] {};
  char mountPoint[32] {};
  char calibrationRef[32] {};

  uint8_t nativeTickBits = 32;
  uint32_t nominalTickPeriodNumeratorUs = 1;
  uint32_t nominalTickPeriodDenominator = 1;
  uint32_t nominalSampleRateNumeratorHz = 0;
  uint32_t nominalSampleRateDenominator = 1;
  uint32_t expectedSequenceStep = 1;
  uint32_t effectiveAccelRateHz = 0;
  uint32_t effectiveGyroRateHz = 0;

  const BdqV2CatalogChannel* channels = nullptr;
  size_t channelCount = 0;
  const BdqV2CatalogStatusFlag* statusFlags = nullptr;
  size_t statusFlagCount = 0;

  bool valid() const;
};

namespace BdqV2Catalog {

// Returns the exact UTF-8 byte count, excluding the trailing NUL, or zero if
// the descriptor set is invalid.
size_t measure(
    const char* sourceDeviceId,
    const BdqV2StreamDescriptor* streams,
    size_t streamCount);

// Writes a compact JSON catalog and a trailing NUL. jsonLength excludes the
// NUL and is suitable for BdqV2Writer::begin().
bool write(
    const char* sourceDeviceId,
    const BdqV2StreamDescriptor* streams,
    size_t streamCount,
    char* destination,
    size_t capacity,
    size_t& jsonLength);

}  // namespace BdqV2Catalog

