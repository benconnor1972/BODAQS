#pragma once

#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "BdqV2Format.h"
#include "BMI270ImuSample.h"

namespace BMI270BdqV2 {

inline constexpr uint16_t kRecordSizeBytes = 28;
inline constexpr uint64_t kNativeTickModulus = uint64_t{1} << 24;
inline constexpr uint32_t kDefaultObservationPeriodUs = 100000;

inline bool encodeRecord(
    const BMI270ImuSample& sample,
    uint8_t* destination,
    size_t capacity) {
  if (!destination || capacity < kRecordSizeBytes) return false;
  memset(destination, 0, kRecordSizeBytes);

  BdqV2Format::StreamRecordPrefix prefix;
  prefix.sequence = sample.sequence;
  prefix.nativeTick = sample.sensorTime & 0x00FFFFFFu;
  prefix.statusFlags = sample.streamStatusFlags();
  if (!BdqV2Format::encodeStreamRecordPrefix(
          prefix, destination, capacity)) {
    return false;
  }
  BdqV2Format::putU16(destination + 12, static_cast<uint16_t>(sample.accelX));
  BdqV2Format::putU16(destination + 14, static_cast<uint16_t>(sample.accelY));
  BdqV2Format::putU16(destination + 16, static_cast<uint16_t>(sample.accelZ));
  BdqV2Format::putU16(destination + 18, static_cast<uint16_t>(sample.gyroX));
  BdqV2Format::putU16(destination + 20, static_cast<uint16_t>(sample.gyroY));
  BdqV2Format::putU16(destination + 22, static_cast<uint16_t>(sample.gyroZ));
  BdqV2Format::putU16(
      destination + 24, static_cast<uint16_t>(sample.temperatureRaw));
  return true;
}

class TimingObservationSampler {
public:
  explicit TimingObservationSampler(
      uint32_t minimumPeriodUs = kDefaultObservationPeriodUs)
      : minimumPeriodUs_(minimumPeriodUs) {}

  bool observe(
      const BMI270ImuSample& sample,
      BdqV2Format::TimeObservation& observation) {
    if (haveBatch_ && sample.acquisitionBatchId == previousBatchId_) return false;
    previousBatchId_ = sample.acquisitionBatchId;
    haveBatch_ = true;

    if (sample.acquisitionAnchorUs == 0 ||
        (sample.acquisitionBeforeUs == 0 && sample.acquisitionAfterUs == 0)) {
      return false;
    }
    if (haveObservation_ &&
        sample.acquisitionAnchorUs >= previousObservationHostUs_ &&
        sample.acquisitionAnchorUs - previousObservationHostUs_ < minimumPeriodUs_) {
      return false;
    }

    const uint64_t beforeUs = sample.acquisitionBeforeUs;
    const uint64_t afterUs = sample.acquisitionAfterUs;
    observation = {};
    observation.nativeTick = sample.sensorTime & 0x00FFFFFFu;
    observation.relatedSequence = sample.sequence;
    observation.hostMinUs = sample.acquisitionAnchorUs > beforeUs
        ? sample.acquisitionAnchorUs - beforeUs
        : 0;
    observation.hostMaxUs = sample.acquisitionAnchorUs > UINT64_MAX - afterUs
        ? UINT64_MAX
        : sample.acquisitionAnchorUs + afterUs;
    observation.kind = BdqV2Format::TimeObservationKind::AcquisitionWindow;
    observation.flags = BdqV2Format::ObservationHostBoundsConservative;
    const uint16_t status = sample.streamStatusFlags();
    if (status & BMI270ImuStatus::kSensorTimeEstimated) {
      observation.flags = static_cast<uint16_t>(
          observation.flags | BdqV2Format::ObservationNativeTickEstimated);
    }
    if (status & BMI270ImuStatus::kTimingDegraded) {
      observation.flags = static_cast<uint16_t>(
          observation.flags | BdqV2Format::ObservationTimingDegraded);
    }
    if (status & BMI270ImuStatus::kSensorRecoveryBefore) {
      observation.flags = static_cast<uint16_t>(
          observation.flags | BdqV2Format::ObservationPostRecovery);
    }

    previousObservationHostUs_ = sample.acquisitionAnchorUs;
    haveObservation_ = true;
    return true;
  }

  void reset() {
    previousBatchId_ = 0;
    previousObservationHostUs_ = 0;
    haveBatch_ = false;
    haveObservation_ = false;
  }

private:
  uint32_t minimumPeriodUs_;
  uint32_t previousBatchId_ = 0;
  uint64_t previousObservationHostUs_ = 0;
  bool haveBatch_ = false;
  bool haveObservation_ = false;
};

static_assert(kRecordSizeBytes == 28);
static_assert(kNativeTickModulus == 16777216ULL);

}  // namespace BMI270BdqV2
