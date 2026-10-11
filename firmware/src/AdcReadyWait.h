#pragma once

#include <stdint.h>

namespace AdcReadyWait {

inline uint32_t timeoutTicks(uint32_t timeoutUs, uint32_t tickRateHz) {
  return static_cast<uint32_t>(
      (static_cast<uint64_t>(timeoutUs) * tickRateHz + 999999ULL) / 1000000ULL);
}

struct Result {
  bool ready;
  uint32_t elapsedUs;
};

// Wait must preserve a notification arriving between the level check and the
// blocking call. Recheck the level after every wake, including timeout wakes.
template <typename Clock, typename Ready, typename Wait>
Result wait(uint32_t timeoutUs, Clock clock, Ready ready, Wait block) {
  const uint32_t start = clock();
  for (;;) {
    const uint32_t elapsed = static_cast<uint32_t>(clock() - start);
    if (ready()) return {true, elapsed};
    if (elapsed >= timeoutUs) return {false, elapsed};
    block(timeoutUs - elapsed);
  }
}

} // namespace AdcReadyWait
