#pragma once

#include <stddef.h>
#include <stdint.h>

namespace BMI270ImuTiming {

inline constexpr uint32_t kSensorTimeMask = 0x00FFFFFFu;

inline uint64_t interpolateTransferTimeUs(
    uint64_t transferStartUs,
    uint64_t transferEndUs,
    size_t byteOffset,
    size_t totalBytes) {
  if (transferEndUs <= transferStartUs || totalBytes == 0) return transferStartUs;
  if (byteOffset > totalBytes) byteOffset = totalBytes;
  const uint64_t durationUs = transferEndUs - transferStartUs;
  return transferStartUs +
      (durationUs * static_cast<uint64_t>(byteOffset)) /
          static_cast<uint64_t>(totalBytes);
}

inline bool estimateHostSampleTimeUs(
    uint32_t referenceSensorTime,
    uint32_t sampleSensorTime,
    uint64_t referenceHostUs,
    uint64_t& sampleHostUs) {
  if (referenceHostUs == 0) return false;
  const uint32_t ticksBeforeReference =
      (referenceSensorTime - sampleSensorTime) & kSensorTimeMask;
  // BMI270 sensor-time tick is 39.0625 us = 625/16 us.
  const uint64_t offsetUs =
      (static_cast<uint64_t>(ticksBeforeReference) * 625u + 8u) / 16u;
  if (offsetUs > referenceHostUs) return false;
  sampleHostUs = referenceHostUs - offsetUs;
  return true;
}

} // namespace BMI270ImuTiming
