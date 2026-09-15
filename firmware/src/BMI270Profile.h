#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace BMI270Profile {

inline constexpr const char* kContractId = "bodaqs.bmi270_imu_mvp.v4";
inline constexpr const char* kProfileName = "orientation_200";
inline constexpr const char* kDriverRevision = "41129fcfe39c583ee5462d79195741945d51c1fe";

inline constexpr uint8_t kPrimaryAddress = 0x68;
inline constexpr uint8_t kSecondaryAddress = 0x69;
inline constexpr uint16_t kOdrHz = 200;
inline constexpr uint16_t kLoggerRateHz = 500;
inline constexpr uint8_t kInitializationAttempts = 5;
inline constexpr uint32_t kSensorTimeRateHz = 25600;

// Bosch API values pinned by kDriverRevision. Keeping the pure profile
// definition independent of the Bosch headers makes validation host-testable.
inline constexpr uint8_t kOdrCode = 0x09;
inline constexpr uint8_t kAccelRange16GCode = 0x03;
inline constexpr uint8_t kAccelNormalAvg4Code = 0x02;
inline constexpr uint8_t kGyroRange2000DpsCode = 0x00;
inline constexpr uint8_t kGyroNormalModeCode = 0x02;
inline constexpr uint8_t kPowerOptimizedCode = 0x00;
inline constexpr uint8_t kPerformanceOptimizedCode = 0x01;

struct NativeProfile {
  const char* name = nullptr;
  uint16_t odrHz = 0;
  uint8_t odrCode = 0;
};

inline constexpr NativeProfile kNativeProfiles[] = {
    {"orientation_200", 200, 0x09},
    {"orientation_400", 400, 0x0A},
    {"orientation_800", 800, 0x0B},
    {"orientation_1600", 1600, 0x0C},
};
inline constexpr size_t kNativeProfileCount =
    sizeof(kNativeProfiles) / sizeof(kNativeProfiles[0]);

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

constexpr bool isSupportedNativeRate(uint16_t odrHz) {
  return odrHz == 200 || odrHz == 400 || odrHz == 800 || odrHz == 1600;
}

constexpr uint8_t odrCodeForRate(uint16_t odrHz) {
  return odrHz == 200 ? 0x09 :
         odrHz == 400 ? 0x0A :
         odrHz == 800 ? 0x0B :
         odrHz == 1600 ? 0x0C : 0;
}

constexpr uint16_t nativeRateForOdrCode(uint8_t odrCode) {
  return odrCode == 0x09 ? 200 :
         odrCode == 0x0A ? 400 :
         odrCode == 0x0B ? 800 :
         odrCode == 0x0C ? 1600 : 0;
}

constexpr uint32_t sensorTimeTicksPerSample(uint16_t odrHz) {
  return isSupportedNativeRate(odrHz) ? kSensorTimeRateHz / odrHz : 0;
}

inline const NativeProfile* find(const char* name) {
  if (!name) return nullptr;
  for (size_t index = 0; index < kNativeProfileCount; ++index) {
    if (strcmp(name, kNativeProfiles[index].name) == 0) {
      return &kNativeProfiles[index];
    }
  }
  return nullptr;
}

inline const NativeProfile* find(uint16_t odrHz) {
  for (size_t index = 0; index < kNativeProfileCount; ++index) {
    if (odrHz == kNativeProfiles[index].odrHz) return &kNativeProfiles[index];
  }
  return nullptr;
}

constexpr bool matches(
    const EffectiveConfig& config,
    uint16_t nativeRateHz) {
  const uint8_t odrCode = odrCodeForRate(nativeRateHz);
  return odrCode != 0 && config.accelOdr == odrCode &&
         config.accelRange == kAccelRange16GCode &&
         config.accelBandwidth == kAccelNormalAvg4Code &&
         config.accelFilterPerformance == kPerformanceOptimizedCode &&
         config.gyroOdr == odrCode &&
         config.gyroRange == kGyroRange2000DpsCode &&
         config.gyroBandwidth == kGyroNormalModeCode &&
         config.gyroNoisePerformance == kPowerOptimizedCode &&
         config.gyroFilterPerformance == kPerformanceOptimizedCode;
}

constexpr EffectiveConfig expected(uint16_t nativeRateHz) {
  const uint8_t odrCode = odrCodeForRate(nativeRateHz);
  return EffectiveConfig{
    odrCode,
    kAccelRange16GCode,
    kAccelNormalAvg4Code,
    kPerformanceOptimizedCode,
    odrCode,
    kGyroRange2000DpsCode,
    kGyroNormalModeCode,
    kPowerOptimizedCode,
    kPerformanceOptimizedCode,
  };
}

constexpr bool matchesOrientation200(const EffectiveConfig& config) {
  return matches(config, kOdrHz);
}

constexpr EffectiveConfig orientation200Expected() {
  return expected(kOdrHz);
}

// These are the deliberately supported sparse-row output selections for the
// legacy CSV and BDQ-v1 adapters. The physical FIFO is always acquired at the
// selected native profile rate; this list governs which samples may be
// materialised into logger rows.
inline constexpr uint16_t kOutputRateOptionsHz[] = {
    5, 10, 20, 25, 40, 50, 100, 200,
};
inline constexpr size_t kOutputRateOptionCount =
    sizeof(kOutputRateOptionsHz) / sizeof(kOutputRateOptionsHz[0]);

constexpr bool isSupportedOutputRate(uint16_t outputRateHz) {
  for (size_t i = 0; i < kOutputRateOptionCount; ++i) {
    if (kOutputRateOptionsHz[i] == outputRateHz) return true;
  }
  return false;
}

constexpr uint16_t outputDecimationFactor(uint16_t outputRateHz) {
  return isSupportedOutputRate(outputRateHz) ? kOdrHz / outputRateHz : 0;
}

constexpr uint16_t outputDecimationFactor(
    uint16_t nativeRateHz,
    uint16_t outputRateHz) {
  return isSupportedNativeRate(nativeRateHz) &&
         isSupportedOutputRate(outputRateHz) &&
         outputRateHz <= nativeRateHz &&
         nativeRateHz % outputRateHz == 0
      ? nativeRateHz / outputRateHz
      : 0;
}

constexpr uint16_t minimumSparseRowLoggerRateHz(uint16_t outputRateHz) {
  // The current BDQ-v1 adapter carries each emitted IMU sample in a primary
  // logger row.  Leave one row of headroom per sample; full-rate output keeps
  // its previously accepted 500 Hz requirement.  This is an adapter limit,
  // not an IMU-profile or future native-stream limit.
  return outputRateHz == kOdrHz
      ? kLoggerRateHz
      : static_cast<uint16_t>(outputRateHz * 2u);
}

constexpr uint16_t resolveSparseRowOutputRateHz(
    uint16_t nativeRateHz,
    uint16_t maximumOutputRateHz,
    uint16_t loggerRateHz) {
  uint16_t resolved = 0;
  for (size_t i = 0; i < kOutputRateOptionCount; ++i) {
    const uint16_t candidate = kOutputRateOptionsHz[i];
    if (candidate <= maximumOutputRateHz &&
        outputDecimationFactor(nativeRateHz, candidate) != 0 &&
        minimumSparseRowLoggerRateHz(candidate) <= loggerRateHz) {
      resolved = candidate;
    }
  }
  return resolved;
}

constexpr uint16_t resolveSparseRowOutputRateHz(
    uint16_t maximumOutputRateHz,
    uint16_t loggerRateHz) {
  return resolveSparseRowOutputRateHz(kOdrHz, maximumOutputRateHz, loggerRateHz);
}

static_assert(isSupportedAddress(kPrimaryAddress));
static_assert(isSupportedAddress(kSecondaryAddress));
static_assert(!isSupportedAddress(0x67));
static_assert(matchesOrientation200(orientation200Expected()));
static_assert(matches(expected(1600), 1600));
static_assert(sensorTimeTicksPerSample(200) == 128);
static_assert(sensorTimeTicksPerSample(1600) == 16);
static_assert(isSupportedOutputRate(10));
static_assert(isSupportedOutputRate(5));
static_assert(isSupportedOutputRate(200));
static_assert(!isSupportedOutputRate(30));
static_assert(resolveSparseRowOutputRateHz(200, 10) == 5);
static_assert(resolveSparseRowOutputRateHz(200, 500) == 200);

} // namespace BMI270Profile
