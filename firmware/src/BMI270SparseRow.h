#pragma once

#include <math.h>
#include <stdint.h>

#include "BMI270ImuSample.h"

namespace BMI270SparseRow {

inline constexpr uint8_t kColumnCount = 12;
inline constexpr uint32_t kU24Mask = 0x00FFFFFFu;

inline void encode(
    const BMI270ImuSample* sample,
    uint64_t rowMonotonicUs,
    float (&out)[kColumnCount],
    uint32_t& ageUs,
    bool& ageValid) {
  for (float& value : out) value = 0.0f;
  out[9] = NAN;
  ageUs = 0;
  ageValid = false;
  if (!sample) return;

  out[0] = static_cast<float>(sample->accelX);
  out[1] = static_cast<float>(sample->accelY);
  out[2] = static_cast<float>(sample->accelZ);
  out[3] = static_cast<float>(sample->gyroX);
  out[4] = static_cast<float>(sample->gyroY);
  out[5] = static_cast<float>(sample->gyroZ);
  out[6] = static_cast<float>(sample->sensorTime & kU24Mask);
  out[7] = static_cast<float>(sample->sequence & kU24Mask);
  out[8] = static_cast<float>(sample->temperatureRaw);

  uint16_t status = sample->statusFlags;
  if (sample->acquisitionAnchorUs != 0 && rowMonotonicUs >= sample->acquisitionAnchorUs) {
    const uint64_t age64 = rowMonotonicUs - sample->acquisitionAnchorUs;
    if (age64 <= UINT32_MAX) {
      ageUs = static_cast<uint32_t>(age64);
      out[9] = static_cast<float>(ageUs);
      ageValid = true;
    }
  }
  if (!ageValid) status |= BMI270ImuStatus::kTimingDegraded;
  out[10] = static_cast<float>(status);
  out[11] = 1.0f;
}

} // namespace BMI270SparseRow
