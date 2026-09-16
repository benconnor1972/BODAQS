#pragma once

#include <stdint.h>

namespace I2CSchedulePlan {

// Spread equal-rate clients evenly through their shared period. This prevents
// simultaneous deadlines from consistently favouring registration order.
constexpr uint32_t staggerOffsetUs(
    uint32_t periodUs,
    uint8_t ordinal,
    uint8_t peerCount) {
  return peerCount > 1
      ? static_cast<uint32_t>(
            (static_cast<uint64_t>(periodUs) * ordinal) / peerCount)
      : 0u;
}

constexpr uint8_t nextTieCursor(uint8_t selectedIndex, uint8_t slotCount) {
  return slotCount
      ? static_cast<uint8_t>((selectedIndex + 1u) % slotCount)
      : 0u;
}

static_assert(staggerOffsetUs(20000, 0, 2) == 0);
static_assert(staggerOffsetUs(20000, 1, 2) == 10000);

}  // namespace I2CSchedulePlan
