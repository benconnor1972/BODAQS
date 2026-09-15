// Rates.h (new)  — keep tiny and focused
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace Rates {
  static constexpr uint16_t kList[] = {10, 20, 50, 100, 200, 500, 1000};
  static constexpr size_t   kCount  = sizeof(kList)/sizeof(kList[0]);

  inline int indexOf(uint16_t hz) {
    for (size_t i = 0; i < kCount; ++i) if (kList[i] == hz) return (int)i;
    return -1;
  }

  inline bool isSupported(uint16_t hz) { return indexOf(hz) >= 0; }

  constexpr uint32_t periodUs(uint16_t hz) {
    return hz ? 1000000UL / hz : 0;
  }

  constexpr uint64_t scheduledTimeUs(
      uint64_t anchorUs,
      uint32_t sampleIndex,
      uint32_t periodUsValue) {
    return anchorUs + static_cast<uint64_t>(sampleIndex) * periodUsValue;
  }

  constexpr uint32_t missedSlots(uint64_t latenessUs, uint32_t periodUsValue) {
    if (!periodUsValue) return 0;
    const uint64_t slots = latenessUs / periodUsValue;
    return slots > UINT32_MAX ? UINT32_MAX : static_cast<uint32_t>(slots);
  }

  inline uint16_t nearest(uint16_t hz) {
    uint16_t best = kList[0];
    uint32_t bestErr = UINT32_MAX;
    for (size_t i = 0; i < kCount; ++i) {
      const uint32_t error = hz > kList[i] ? hz - kList[i] : kList[i] - hz;
      if (error < bestErr) {
        bestErr = error;
        best = kList[i];
      }
    }
    return best;
  }
}
