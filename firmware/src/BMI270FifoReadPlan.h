#pragma once

#include <stddef.h>
#include <stdint.h>

namespace BMI270FifoReadPlan {

inline constexpr size_t kFifoCapacityBytes = 2048;
inline constexpr size_t kCombinedFrameBytes = 13;
inline constexpr size_t kSensorTimeFrameBytes = 4;
inline constexpr uint16_t kDefaultSampleRateHz = 200;
inline constexpr uint32_t kI2CClockHz = 400000;
// Nine clock pulses per transferred byte plus a conservative allowance for
// transaction setup and clock stretching.
inline constexpr uint32_t kWireBitsPerByte = 10;
inline constexpr size_t kWireProtocolBytes = 8;
inline constexpr size_t kArrivalGuardFrames = 1;
inline constexpr size_t kMaximumReadBytes = 2304;

constexpr uint32_t transferDurationUs(size_t bytes) {
  const uint64_t bits =
      static_cast<uint64_t>(bytes + kWireProtocolBytes) * kWireBitsPerByte;
  return static_cast<uint32_t>((bits * 1000000u + kI2CClockHz - 1u) /
                               kI2CClockHz);
}

constexpr uint32_t samplePeriodUs(uint16_t sampleRateHz) {
  return sampleRateHz != 0 && (1000000u % sampleRateHz) == 0
      ? 1000000u / sampleRateHz
      : 0;
}

constexpr size_t framesArrivingDuringRead(
    size_t bytes,
    uint16_t sampleRateHz = kDefaultSampleRateHz) {
  const uint32_t periodUs = samplePeriodUs(sampleRateHz);
  return periodUs
      ? (transferDurationUs(bytes) + periodUs - 1u) / periodUs
      : 0;
}

// FIFO_LENGTH excludes the sensor-time frame appended when FIFO_DATA becomes
// empty. Include enough complete sample frames for data that can arrive during
// the burst, then a complete four-byte sensor-time frame. Iterate to a fixed
// point because the additional bytes themselves extend the transaction.
constexpr size_t bytesToRead(
    size_t fifoLength,
    uint16_t sampleRateHz = kDefaultSampleRateHz) {
  if (fifoLength == 0 || fifoLength > kFifoCapacityBytes ||
      samplePeriodUs(sampleRateHz) == 0) {
    return 0;
  }
  size_t planned = fifoLength + kSensorTimeFrameBytes;
  for (uint8_t iteration = 0; iteration < 8; ++iteration) {
    const size_t arrivals =
        framesArrivingDuringRead(planned, sampleRateHz) + kArrivalGuardFrames;
    const size_t next = fifoLength + arrivals * kCombinedFrameBytes +
                        kSensorTimeFrameBytes;
    if (next <= planned) break;
    planned = next < kMaximumReadBytes ? next : kMaximumReadBytes;
    if (planned == kMaximumReadBytes) break;
  }
  return planned;
}

static_assert(bytesToRead(kFifoCapacityBytes) <= kMaximumReadBytes,
              "BMI270 FIFO burst exceeds the allocated Wire/read buffer");
static_assert(bytesToRead(kFifoCapacityBytes, 1600) == kMaximumReadBytes,
              "high-rate FIFO reads must make bounded forward progress");

} // namespace BMI270FifoReadPlan
