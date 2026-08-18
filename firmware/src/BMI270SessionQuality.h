#pragma once

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "BMI270ImuSample.h"

class BMI270RunningStats {
public:
  void reset() {
    count_ = 0;
    mean_ = 0.0;
    m2_ = 0.0;
    minimum_ = 0.0;
    maximum_ = 0.0;
  }

  void add(double value) {
    if (count_ == 0) {
      minimum_ = value;
      maximum_ = value;
    } else {
      if (value < minimum_) minimum_ = value;
      if (value > maximum_) maximum_ = value;
    }
    ++count_;
    const double delta = value - mean_;
    mean_ += delta / static_cast<double>(count_);
    const double delta2 = value - mean_;
    m2_ += delta * delta2;
  }

  uint32_t count() const { return count_; }
  double mean() const { return count_ ? mean_ : 0.0; }
  double variance() const { return count_ ? m2_ / static_cast<double>(count_) : 0.0; }
  double standardDeviation() const { return sqrt(variance()); }
  double minimum() const { return count_ ? minimum_ : 0.0; }
  double maximum() const { return count_ ? maximum_ : 0.0; }

private:
  uint32_t count_ = 0;
  double mean_ = 0.0;
  double m2_ = 0.0;
  double minimum_ = 0.0;
  double maximum_ = 0.0;
};

enum class BMI270StartupObservationState : uint8_t {
  Disabled = 0,
  Collecting = 1,
  Accepted = 2,
  Rejected = 3,
};

namespace BMI270StartupRejection {

inline constexpr uint16_t kInsufficientSamples = 0x0001;
inline constexpr uint16_t kQualityIncident = 0x0002;
inline constexpr uint16_t kAccelMeanOutsideGravityBand = 0x0004;
inline constexpr uint16_t kAccelMagnitudeUnstable = 0x0008;
inline constexpr uint16_t kGyroXUnstable = 0x0010;
inline constexpr uint16_t kGyroYUnstable = 0x0020;
inline constexpr uint16_t kGyroZUnstable = 0x0040;
inline constexpr uint16_t kGyroMotionDetected = 0x0080;

} // namespace BMI270StartupRejection

struct BMI270StartupObservationResult {
  BMI270StartupObservationState state = BMI270StartupObservationState::Disabled;
  uint16_t rejectionMask = 0;
  uint16_t configuredSeconds = 0;
  uint32_t targetSampleSlots = 0;
  uint32_t validSamples = 0;
  uint32_t settlingSampleSlots = 0;
  uint32_t measurementStartSequence = 0;
  uint16_t settlingStatusMask = 0;
  uint32_t temperatureSamples = 0;
  double gyroMeanRaw[3] {};
  double gyroStdRaw[3] {};
  double accelMagnitudeMeanG = 0.0;
  double accelMagnitudeStdG = 0.0;
  double maximumGyroMagnitudeDps = 0.0;
  double temperatureMeanC = 0.0;
  double temperatureMinimumC = 0.0;
  double temperatureMaximumC = 0.0;
};

class BMI270StartupObservation {
public:
  static constexpr uint16_t kNativeRateHz = 200;
  static constexpr uint32_t kMinimumSamples = 800;
  static constexpr double kAccelCountsPerG = 2048.0;
  static constexpr double kGyroCountsPerDps = 16.384;
  static constexpr double kAccelMeanToleranceG = 0.15;
  static constexpr double kAccelStdMaximumG = 0.03;
  static constexpr double kGyroStdMaximumDps = 0.5;
  static constexpr double kGyroMagnitudeMaximumDps = 5.0;
  static constexpr uint32_t kSettlingCleanSamples = 20;
  static constexpr uint32_t kMaximumSettlingSlots = 200;

  void begin(uint16_t configuredSeconds) {
    result_ = BMI270StartupObservationResult{};
    result_.configuredSeconds = configuredSeconds;
    result_.targetSampleSlots =
        static_cast<uint32_t>(configuredSeconds) * kNativeRateHz;
    result_.state = configuredSeconds
        ? BMI270StartupObservationState::Collecting
        : BMI270StartupObservationState::Disabled;
    for (size_t axis = 0; axis < 3; ++axis) gyro_[axis].reset();
    accelMagnitude_.reset();
    temperature_.reset();
    maximumGyroMagnitudeRaw_ = 0.0;
    qualityIncident_ = false;
    windowStarted_ = false;
    consecutiveCleanSamples_ = 0;
  }

  void observe(
      uint32_t sequence,
      int16_t accelX,
      int16_t accelY,
      int16_t accelZ,
      int16_t gyroX,
      int16_t gyroY,
      int16_t gyroZ,
      int16_t temperatureRaw,
      bool temperatureFresh,
      uint16_t statusFlags) {
    if (result_.state != BMI270StartupObservationState::Collecting) return;

    constexpr uint16_t kRejectedStatus =
        BMI270ImuStatus::kFifoDiscontinuityBefore |
        BMI270ImuStatus::kQueueDropBefore |
        BMI270ImuStatus::kSensorRecoveryBefore |
        BMI270ImuStatus::kTimingDegraded;
    const uint16_t rejectedStatus = statusFlags & kRejectedStatus;

    if (!windowStarted_) {
      ++result_.settlingSampleSlots;
      result_.settlingStatusMask |= rejectedStatus;
      if (rejectedStatus) {
        consecutiveCleanSamples_ = 0;
      } else {
        ++consecutiveCleanSamples_;
      }
      if (consecutiveCleanSamples_ >= kSettlingCleanSamples) {
        windowStarted_ = true;
        result_.measurementStartSequence = sequence + 1u;
      } else if (result_.settlingSampleSlots >= kMaximumSettlingSlots) {
        qualityIncident_ = true;
        finish();
      }
      return;
    }

    const uint32_t measurementSlot = sequence - result_.measurementStartSequence;
    if (measurementSlot >= result_.targetSampleSlots) {
      finish();
      return;
    }

    const double ax = accelX;
    const double ay = accelY;
    const double az = accelZ;
    const double gx = gyroX;
    const double gy = gyroY;
    const double gz = gyroZ;
    accelMagnitude_.add(sqrt(ax * ax + ay * ay + az * az));
    gyro_[0].add(gx);
    gyro_[1].add(gy);
    gyro_[2].add(gz);
    const double gyroMagnitude = sqrt(gx * gx + gy * gy + gz * gz);
    if (gyroMagnitude > maximumGyroMagnitudeRaw_) {
      maximumGyroMagnitudeRaw_ = gyroMagnitude;
    }
    if (temperatureFresh) {
      temperature_.add(static_cast<double>(temperatureRaw) / 512.0 + 23.0);
    }

    if (rejectedStatus) qualityIncident_ = true;

    if (measurementSlot + 1u >= result_.targetSampleSlots) finish();
  }

  void noteQualityIncident() {
    if (result_.state != BMI270StartupObservationState::Collecting) return;
    if (windowStarted_) {
      qualityIncident_ = true;
    } else {
      consecutiveCleanSamples_ = 0;
      result_.settlingStatusMask |= BMI270ImuStatus::kQueueDropBefore;
    }
  }

  void finish() {
    if (result_.state != BMI270StartupObservationState::Collecting) return;
    result_.validSamples = accelMagnitude_.count();
    result_.temperatureSamples = temperature_.count();
    for (size_t axis = 0; axis < 3; ++axis) {
      result_.gyroMeanRaw[axis] = gyro_[axis].mean();
      result_.gyroStdRaw[axis] = gyro_[axis].standardDeviation();
    }
    result_.accelMagnitudeMeanG = accelMagnitude_.mean() / kAccelCountsPerG;
    result_.accelMagnitudeStdG = accelMagnitude_.standardDeviation() / kAccelCountsPerG;
    result_.maximumGyroMagnitudeDps = maximumGyroMagnitudeRaw_ / kGyroCountsPerDps;
    result_.temperatureMeanC = temperature_.mean();
    result_.temperatureMinimumC = temperature_.minimum();
    result_.temperatureMaximumC = temperature_.maximum();

    uint16_t rejection = 0;
    if (result_.validSamples < kMinimumSamples) {
      rejection |= BMI270StartupRejection::kInsufficientSamples;
    }
    if (qualityIncident_) rejection |= BMI270StartupRejection::kQualityIncident;
    if (result_.validSamples > 0) {
      if (fabs(result_.accelMagnitudeMeanG - 1.0) > kAccelMeanToleranceG) {
        rejection |= BMI270StartupRejection::kAccelMeanOutsideGravityBand;
      }
      if (result_.accelMagnitudeStdG > kAccelStdMaximumG) {
        rejection |= BMI270StartupRejection::kAccelMagnitudeUnstable;
      }
      if (result_.gyroStdRaw[0] / kGyroCountsPerDps > kGyroStdMaximumDps) {
        rejection |= BMI270StartupRejection::kGyroXUnstable;
      }
      if (result_.gyroStdRaw[1] / kGyroCountsPerDps > kGyroStdMaximumDps) {
        rejection |= BMI270StartupRejection::kGyroYUnstable;
      }
      if (result_.gyroStdRaw[2] / kGyroCountsPerDps > kGyroStdMaximumDps) {
        rejection |= BMI270StartupRejection::kGyroZUnstable;
      }
      if (result_.maximumGyroMagnitudeDps > kGyroMagnitudeMaximumDps) {
        rejection |= BMI270StartupRejection::kGyroMotionDetected;
      }
    }
    result_.rejectionMask = rejection;
    result_.state = rejection
        ? BMI270StartupObservationState::Rejected
        : BMI270StartupObservationState::Accepted;
  }

  const BMI270StartupObservationResult& result() const { return result_; }

private:
  BMI270StartupObservationResult result_;
  BMI270RunningStats gyro_[3];
  BMI270RunningStats accelMagnitude_;
  BMI270RunningStats temperature_;
  double maximumGyroMagnitudeRaw_ = 0.0;
  bool qualityIncident_ = false;
  bool windowStarted_ = false;
  uint32_t consecutiveCleanSamples_ = 0;
};

struct BMI270AgeSummary {
  uint64_t count = 0;
  uint64_t unavailable = 0;
  uint64_t clipped = 0;
  uint32_t minimumUs = 0;
  uint32_t medianUs = 0;
  uint32_t p95Us = 0;
  uint32_t p99Us = 0;
  uint32_t maximumUs = 0;
  uint16_t resolutionUs = 0;
};

class BMI270AgeHistogram {
public:
  static constexpr uint16_t kResolutionUs = 256;
  static constexpr size_t kBucketCount = 256;

  void reset() {
    count_ = 0;
    unavailable_ = 0;
    clipped_ = 0;
    minimumUs_ = 0;
    maximumUs_ = 0;
    for (size_t i = 0; i < kBucketCount; ++i) buckets_[i] = 0;
  }

  void add(uint32_t ageUs, bool valid) {
    if (!valid) {
      ++unavailable_;
      return;
    }
    if (count_ == 0 || ageUs < minimumUs_) minimumUs_ = ageUs;
    if (count_ == 0 || ageUs > maximumUs_) maximumUs_ = ageUs;
    ++count_;
    size_t bucket = ageUs / kResolutionUs;
    if (bucket >= kBucketCount) {
      bucket = kBucketCount - 1;
      ++clipped_;
    }
    if (buckets_[bucket] != UINT32_MAX) ++buckets_[bucket];
  }

  BMI270AgeSummary summary() const {
    BMI270AgeSummary out;
    out.count = count_;
    out.unavailable = unavailable_;
    out.clipped = clipped_;
    out.minimumUs = count_ ? minimumUs_ : 0;
    out.medianUs = percentile_(500);
    out.p95Us = percentile_(950);
    out.p99Us = percentile_(990);
    out.maximumUs = count_ ? maximumUs_ : 0;
    out.resolutionUs = kResolutionUs;
    return out;
  }

private:
  uint32_t percentile_(uint16_t permille) const {
    if (count_ == 0) return 0;
    const uint64_t rank = (count_ * permille + 999u) / 1000u;
    uint64_t cumulative = 0;
    for (size_t bucket = 0; bucket < kBucketCount; ++bucket) {
      cumulative += buckets_[bucket];
      if (cumulative >= rank) {
        const uint32_t upper = static_cast<uint32_t>((bucket + 1) * kResolutionUs - 1);
        return upper < maximumUs_ ? upper : maximumUs_;
      }
    }
    return maximumUs_;
  }

  uint64_t count_ = 0;
  uint64_t unavailable_ = 0;
  uint64_t clipped_ = 0;
  uint32_t minimumUs_ = 0;
  uint32_t maximumUs_ = 0;
  uint32_t buckets_[kBucketCount] {};
};
