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

// A buffered client may yield to a latency-sensitive peer whose deadline would
// otherwise fall inside the buffered client's non-preemptible transfer. The
// yield is admitted only while the per-service yield budget is not exhausted
// and the buffered client can still begin service within its declared maximum
// gap from the previous successful completion.
constexpr bool shouldYieldToLatencySensitive(
    uint32_t bufferedAcquireUs,
    uint32_t latencyWaitUs,
    uint32_t latencyAcquireUs,
    uint32_t bufferedServiceAgeUs,
    bool bufferedHasSuccessfulService,
    uint32_t bufferedMaximumGapUs,
    uint8_t completedYields,
    uint8_t maximumYields) {
  if (bufferedAcquireUs == 0 || latencyAcquireUs == 0 ||
      !bufferedHasSuccessfulService || bufferedMaximumGapUs == 0 ||
      maximumYields == 0 || completedYields >= maximumYields) {
    return false;
  }

  if (latencyWaitUs > bufferedAcquireUs) return false;

  const uint64_t bufferedStartAgeUs =
      static_cast<uint64_t>(bufferedServiceAgeUs) + latencyWaitUs + latencyAcquireUs;
  return bufferedStartAgeUs <= bufferedMaximumGapUs;
}

static_assert(staggerOffsetUs(20000, 0, 2) == 0);
static_assert(staggerOffsetUs(20000, 1, 2) == 10000);
static_assert(shouldYieldToLatencySensitive(
    15000, 3000, 2000, 29000, true, 50000, 0, 1));
static_assert(!shouldYieldToLatencySensitive(
    15000, 16000, 2000, 29000, true, 50000, 0, 1));
static_assert(shouldYieldToLatencySensitive(
    15000, 3000, 2000, 45000, true, 70000, 1, 2));
static_assert(!shouldYieldToLatencySensitive(
    15000, 3000, 2000, 45000, true, 70000, 2, 2));

}  // namespace I2CSchedulePlan
