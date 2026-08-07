#pragma once

#include <stdint.h>

namespace BMI270ImuStatus {

inline constexpr uint16_t kFifoDiscontinuityBefore = 0x0001;
inline constexpr uint16_t kQueueDropBefore = 0x0002;
inline constexpr uint16_t kSensorRecoveryBefore = 0x0004;
inline constexpr uint16_t kTimingDegraded = 0x0008;
inline constexpr uint16_t kSensorTimeEstimated = 0x0010;
inline constexpr uint16_t kTemperatureStale = 0x0020;

} // namespace BMI270ImuStatus

struct BMI270ImuSample {
  int16_t accelX = 0;
  int16_t accelY = 0;
  int16_t accelZ = 0;
  int16_t gyroX = 0;
  int16_t gyroY = 0;
  int16_t gyroZ = 0;
  int16_t temperatureRaw = 0;
  uint16_t statusFlags = 0;

  // The sensor and row contracts emit only the low 24 bits. Keeping full
  // width internally makes wrap and loss handling explicit.
  uint32_t sensorTime = 0;
  uint32_t sequence = 0;

  // Best estimate of the native sample time in the ESP monotonic clock
  // domain. FIFO batches are anchored at the I2C acquisition midpoint and
  // older samples are projected backwards using the 24-bit sensor clock.
  uint64_t acquisitionAnchorUs = 0;
  uint32_t acquisitionSpanUs = 0;
};

static_assert(BMI270ImuStatus::kFifoDiscontinuityBefore == 0x0001);
static_assert(BMI270ImuStatus::kQueueDropBefore == 0x0002);
static_assert(BMI270ImuStatus::kSensorRecoveryBefore == 0x0004);
static_assert(BMI270ImuStatus::kTimingDegraded == 0x0008);
static_assert(BMI270ImuStatus::kSensorTimeEstimated == 0x0010);
static_assert(BMI270ImuStatus::kTemperatureStale == 0x0020);
