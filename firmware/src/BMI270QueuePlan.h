#pragma once

#include <stddef.h>
#include <stdint.h>

namespace BMI270QueuePlan {

inline constexpr uint32_t kTargetCoverageMs = 5120;
inline constexpr size_t kMinimumCapacity = 1024;
inline constexpr size_t kMaximumCapacity = 8192;

constexpr size_t capacityForRate(uint16_t nativeRateHz) {
  size_t required =
      (static_cast<size_t>(nativeRateHz) * kTargetCoverageMs + 999u) / 1000u;
  if (required < kMinimumCapacity) required = kMinimumCapacity;
  size_t capacity = 1;
  while (capacity < required && capacity < kMaximumCapacity) capacity <<= 1u;
  return capacity > kMaximumCapacity ? kMaximumCapacity : capacity;
}

constexpr uint32_t coverageMs(size_t capacity, uint16_t nativeRateHz) {
  return nativeRateHz
      ? static_cast<uint32_t>((capacity * 1000u) / nativeRateHz)
      : 0;
}

static_assert(capacityForRate(200) == 1024);
static_assert(capacityForRate(400) == 2048);
static_assert(capacityForRate(800) == 4096);
static_assert(capacityForRate(1600) == 8192);

}  // namespace BMI270QueuePlan
