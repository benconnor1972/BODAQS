#pragma once

#include <stddef.h>
#include <stdint.h>

namespace BMI270FifoReadPlan {

inline constexpr size_t kFifoCapacityBytes = 2048;
inline constexpr size_t kCombinedFrameBytes = 13;
inline constexpr size_t kSingleSensorFrameBytes = 7;
inline constexpr size_t kSensorTimeFrameBytes = 4;
inline constexpr uint16_t kDefaultSampleRateHz = 200;
inline constexpr uint32_t kI2CClockHz = 400000;
// Nine clock pulses per transferred byte plus a conservative allowance for
// transaction setup and clock stretching.
inline constexpr uint32_t kWireBitsPerByte = 10;
inline constexpr size_t kWireProtocolBytes = 8;
inline constexpr size_t kArrivalGuardFrames = 1;
inline constexpr size_t kMaximumReadBytes = 2304;
inline constexpr uint8_t kAdaptiveBacklogPeriods = 2;

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

constexpr uint32_t mixedBytesPerSecond(
    uint16_t accelRateHz,
    uint16_t gyroRateHz) {
  // Treat coincident accel and gyro frames as two single-sensor frames. The
  // actual combined header saves one byte, so this remains conservative.
  return static_cast<uint32_t>(accelRateHz + gyroRateHz) *
      kSingleSensorFrameBytes;
}

constexpr size_t mixedBytesArrivingDuringRead(
    size_t bytes,
    uint16_t accelRateHz,
    uint16_t gyroRateHz) {
  const uint64_t numerator =
      static_cast<uint64_t>(transferDurationUs(bytes)) *
      mixedBytesPerSecond(accelRateHz, gyroRateHz);
  return mixedBytesPerSecond(accelRateHz, gyroRateHz) != 0
      ? static_cast<size_t>((numerator + 999999u) / 1000000u)
      : 0;
}

constexpr size_t bytesToRead(
    size_t fifoLength,
    uint16_t accelRateHz,
    uint16_t gyroRateHz) {
  if (accelRateHz == gyroRateHz) return bytesToRead(fifoLength, accelRateHz);
  if (fifoLength == 0 || fifoLength > kFifoCapacityBytes ||
      mixedBytesPerSecond(accelRateHz, gyroRateHz) == 0) {
    return 0;
  }
  size_t planned = fifoLength + kSensorTimeFrameBytes;
  for (uint8_t iteration = 0; iteration < 8; ++iteration) {
    const size_t arrivals = mixedBytesArrivingDuringRead(
        planned, accelRateHz, gyroRateHz);
    const size_t next = fifoLength + arrivals + kCombinedFrameBytes +
                        kSensorTimeFrameBytes;
    if (next <= planned) break;
    planned = next < kMaximumReadBytes ? next : kMaximumReadBytes;
    if (planned == kMaximumReadBytes) break;
  }
  return planned;
}

constexpr size_t expectedBytesPerPoll(
    uint16_t sampleRateHz,
    uint16_t pollRateHz) {
  return sampleRateHz != 0 && pollRateHz != 0
      ? ((static_cast<size_t>(sampleRateHz) + pollRateHz - 1u) / pollRateHz) *
            kCombinedFrameBytes
      : 0;
}

constexpr size_t expectedBytesPerPoll(
    uint16_t accelRateHz,
    uint16_t gyroRateHz,
    uint16_t pollRateHz) {
  if (accelRateHz == gyroRateHz) {
    return expectedBytesPerPoll(accelRateHz, pollRateHz);
  }
  return pollRateHz != 0
      ? (static_cast<size_t>(mixedBytesPerSecond(accelRateHz, gyroRateHz)) +
         pollRateHz - 1u) / pollRateHz
      : 0;
}

// A normal acquisition is allowed to contain two poll periods of samples.
// A second pass is reserved for a FIFO that has grown beyond that allowance,
// or beyond half its capacity at very high ODRs.
constexpr size_t adaptiveFollowupThresholdBytes(
    uint16_t sampleRateHz,
    uint16_t pollRateHz) {
  const size_t expected = expectedBytesPerPoll(sampleRateHz, pollRateHz);
  if (expected == 0) return 0;
  const size_t periods = expected * kAdaptiveBacklogPeriods;
  return periods < (kFifoCapacityBytes / 2u)
      ? periods
      : (kFifoCapacityBytes / 2u);
}

constexpr size_t adaptiveFollowupThresholdBytes(
    uint16_t accelRateHz,
    uint16_t gyroRateHz,
    uint16_t pollRateHz) {
  const size_t expected =
      expectedBytesPerPoll(accelRateHz, gyroRateHz, pollRateHz);
  if (expected == 0) return 0;
  const size_t periods = expected * kAdaptiveBacklogPeriods;
  return periods < (kFifoCapacityBytes / 2u)
      ? periods
      : (kFifoCapacityBytes / 2u);
}

constexpr bool needsAdaptiveFollowup(
    size_t fifoLength,
    uint16_t sampleRateHz,
    uint16_t pollRateHz) {
  const size_t threshold =
      adaptiveFollowupThresholdBytes(sampleRateHz, pollRateHz);
  return threshold != 0 && fifoLength > threshold;
}

constexpr bool needsAdaptiveFollowup(
    size_t fifoLength,
    uint16_t accelRateHz,
    uint16_t gyroRateHz,
    uint16_t pollRateHz) {
  const size_t threshold = adaptiveFollowupThresholdBytes(
      accelRateHz, gyroRateHz, pollRateHz);
  return threshold != 0 && fifoLength > threshold;
}

static_assert(bytesToRead(kFifoCapacityBytes) <= kMaximumReadBytes,
              "BMI270 FIFO burst exceeds the allocated Wire/read buffer");
static_assert(bytesToRead(kFifoCapacityBytes, 1600) == kMaximumReadBytes,
              "high-rate FIFO reads must make bounded forward progress");
static_assert(expectedBytesPerPoll(1600, 200, 200) == 63,
              "mixed profile read planning accounts for both sensors");

} // namespace BMI270FifoReadPlan
