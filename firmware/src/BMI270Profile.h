#pragma once

#include <stdint.h>

namespace BMI270Profile {

inline constexpr const char* kContractId = "bodaqs.bmi270_imu_mvp.v1";
inline constexpr const char* kProfileName = "orientation_200";
inline constexpr const char* kDriverRevision = "41129fcfe39c583ee5462d79195741945d51c1fe";

inline constexpr uint8_t kPrimaryAddress = 0x68;
inline constexpr uint8_t kSecondaryAddress = 0x69;
inline constexpr uint16_t kOdrHz = 200;
inline constexpr uint16_t kLoggerRateHz = 500;
inline constexpr uint8_t kInitializationAttempts = 3;

// Bosch API values pinned by kDriverRevision. Keeping the pure profile
// definition independent of the Bosch headers makes validation host-testable.
inline constexpr uint8_t kOdrCode = 0x09;
inline constexpr uint8_t kAccelRange16GCode = 0x03;
inline constexpr uint8_t kAccelNormalAvg4Code = 0x02;
inline constexpr uint8_t kGyroRange2000DpsCode = 0x00;
inline constexpr uint8_t kGyroNormalModeCode = 0x02;
inline constexpr uint8_t kPowerOptimizedCode = 0x00;
inline constexpr uint8_t kPerformanceOptimizedCode = 0x01;

struct EffectiveConfig {
  uint8_t accelOdr = 0;
  uint8_t accelRange = 0;
  uint8_t accelBandwidth = 0;
  uint8_t accelFilterPerformance = 0;
  uint8_t gyroOdr = 0;
  uint8_t gyroRange = 0;
  uint8_t gyroBandwidth = 0;
  uint8_t gyroNoisePerformance = 0;
  uint8_t gyroFilterPerformance = 0;
};

constexpr bool isSupportedAddress(uint8_t address) {
  return address == kPrimaryAddress || address == kSecondaryAddress;
}

constexpr bool matchesOrientation200(const EffectiveConfig& config) {
  return config.accelOdr == kOdrCode &&
         config.accelRange == kAccelRange16GCode &&
         config.accelBandwidth == kAccelNormalAvg4Code &&
         config.accelFilterPerformance == kPerformanceOptimizedCode &&
         config.gyroOdr == kOdrCode &&
         config.gyroRange == kGyroRange2000DpsCode &&
         config.gyroBandwidth == kGyroNormalModeCode &&
         config.gyroNoisePerformance == kPowerOptimizedCode &&
         config.gyroFilterPerformance == kPerformanceOptimizedCode;
}

constexpr EffectiveConfig orientation200Expected() {
  return EffectiveConfig{
    kOdrCode,
    kAccelRange16GCode,
    kAccelNormalAvg4Code,
    kPerformanceOptimizedCode,
    kOdrCode,
    kGyroRange2000DpsCode,
    kGyroNormalModeCode,
    kPowerOptimizedCode,
    kPerformanceOptimizedCode,
  };
}

static_assert(isSupportedAddress(kPrimaryAddress));
static_assert(isSupportedAddress(kSecondaryAddress));
static_assert(!isSupportedAddress(0x67));
static_assert(matchesOrientation200(orientation200Expected()));

} // namespace BMI270Profile
