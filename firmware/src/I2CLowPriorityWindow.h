#pragma once

#include <stdint.h>

namespace I2CLowPriorityWindow {

constexpr bool fits(
    uint32_t elapsedSinceServiceUs,
    uint32_t transferDurationUs,
    uint32_t guardUs,
    uint32_t maximumServiceGapUs) {
  if (maximumServiceGapUs == 0 || elapsedSinceServiceUs >= maximumServiceGapUs) {
    return false;
  }
  const uint32_t remainingUs = maximumServiceGapUs - elapsedSinceServiceUs;
  if (transferDurationUs > remainingUs) return false;
  return guardUs <= remainingUs - transferDurationUs;
}

} // namespace I2CLowPriorityWindow
