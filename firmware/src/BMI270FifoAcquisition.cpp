#include "BMI270FifoAcquisition.h"

#include <Arduino.h>
#include <limits.h>
#include <string.h>

#include <bmi2.h>
#include <bmi270.h>

#include "DebugLog.h"
#include "BMI270ImuTiming.h"
#include "I2CManager.h"
#include "esp_timer.h"

#define BMI270_FIFO_LOGI(...) LOGI_TAG("BMI270FIFO", __VA_ARGS__)
#define BMI270_FIFO_LOGW(...) LOGW_TAG("BMI270FIFO", __VA_ARGS__)

namespace {

constexpr uint16_t kRequiredFifoConfig =
    BMI2_FIFO_HEADER_EN | BMI2_FIFO_TIME_EN | BMI2_FIFO_ACC_EN | BMI2_FIFO_GYR_EN;
constexpr uint16_t kManagedFifoConfig =
    BMI2_FIFO_STOP_ON_FULL | BMI2_FIFO_TIME_EN | BMI2_FIFO_TAG_INT1 |
    BMI2_FIFO_TAG_INT2 | BMI2_FIFO_HEADER_EN | BMI2_FIFO_ALL_EN;
constexpr uint8_t kNormalDrainPasses = 2;
constexpr uint8_t kFinalDrainPasses = 4;
constexpr uint32_t kRecoveryFailureThreshold = 3;
constexpr uint16_t kRecoveryBackoffPolls = 200;
constexpr uint16_t kCarryStatusMask =
    BMI270ImuStatus::kFifoDiscontinuityBefore |
    BMI270ImuStatus::kQueueDropBefore |
    BMI270ImuStatus::kSensorRecoveryBefore |
    BMI270ImuStatus::kTimingDegraded;

static_assert(BMI270FifoAcquisition::kRawBufferBytes >=
              BMI270FifoReadPlan::bytesToRead(2048));
static_assert(BMI270I2CTransport::kMaximumReadBytes >=
              BMI270FifoAcquisition::kRawBufferBytes);
static_assert(BMI270FifoAcquisition::kMaximumBatchSamples >= (2048 / 13) + 1);
static_assert(sizeof(BMI270FifoAcquisition) <= 32 * 1024,
              "single-IMU acquisition state exceeds its provisional RAM budget");
static_assert((kRequiredFifoConfig & kManagedFifoConfig) == kRequiredFifoConfig);
static_assert(BMI2_FIFO_HEADER_ACC_FRM == 0x84);
static_assert(BMI2_FIFO_HEADER_GYR_FRM == 0x88);
static_assert(BMI2_FIFO_HEADER_GYR_ACC_FRM == 0x8C);
static_assert(BMI2_FIFO_HEADER_SENS_TIME_FRM == 0x44);
static_assert(BMI2_FIFO_HEADER_SKIP_FRM == 0x40);
static_assert(BMI2_FIFO_HEADER_INPUT_CFG_FRM == 0x48);
static_assert(BMI2_FIFO_HEAD_OVER_READ_MSB == 0x80);
static_assert(BMI2_FIFO_LENGTH_0_ADDR == 0x24);

void copyName_(char* destination, size_t capacity, const char* source) {
  if (!destination || capacity == 0) return;
  if (!source || !*source) source = "bmi270";
  size_t length = strlen(source);
  if (length >= capacity) length = capacity - 1;
  memcpy(destination, source, length);
  destination[length] = '\0';
}

} // namespace

BMI270FifoAcquisition::BMI270FifoAcquisition(
    uint8_t busIndex,
    uint8_t address,
    const char* name)
    : device_(busIndex, address) {
  copyName_(name_, sizeof(name_), name);
  diagnostics_.queueCapacity = static_cast<uint16_t>(kQueueCapacity);
}

BMI270FifoAcquisition::~BMI270FifoAcquisition() {
  shutdown();
}

bool BMI270FifoAcquisition::begin() {
  if (initialized_) return true;
  sessionActive_.store(false, std::memory_order_release);

  if (!I2CManager::ensureBufferCapacity(device_.busIndex(), kRawBufferBytes) ||
      !I2CManager::setTransactionTimeout(device_.busIndex(), 100)) {
    BMI270_FIFO_LOGW("unable to configure I2C burst capacity name=%s\n", name_);
    return false;
  }
  if (!device_.begin()) return false;
  if (!configureFifo_()) {
    device_.shutdown();
    return false;
  }
  if (!device_.suspend()) {
    device_.shutdown();
    return false;
  }

  if (!registered_) {
    registered_ = I2CBusScheduler::registerClient(this);
    if (!registered_) {
      device_.shutdown();
      return false;
    }
  }

  initialized_ = true;
  BMI270_FIFO_LOGI(
      "initialized name=%s bus=%u addr=0x%02X queue=%u profile=%s\n",
      name_,
      (unsigned)device_.busIndex(),
      (unsigned)device_.address(),
      (unsigned)kQueueCapacity,
      BMI270Profile::kProfileName);
  return true;
}

void BMI270FifoAcquisition::shutdown() {
  sessionActive_.store(false, std::memory_order_release);
  if (registered_) {
    I2CBusScheduler::unregisterClient(this);
    registered_ = false;
  }
  device_.shutdown();
  initialized_ = false;
}

bool BMI270FifoAcquisition::startSession() {
  if (!initialized_ && !begin()) return false;
  if (sessionActive()) return true;

  if (device_.state() == BMI270DeviceState::Ready && !device_.suspend()) return false;

  const uint64_t preSessionDiscards = static_cast<uint64_t>(queue_.size());
  queue_.clear();
  resetSessionState_(preSessionDiscards);
  device_.resetTransportDiagnostics();

  if (!flushFifo_()) return false;
  if (!device_.resume()) return false;

  sessionActive_.store(true, std::memory_order_release);
  diagnostics_.sessionActive = true;
  return true;
}

bool BMI270FifoAcquisition::stopSession() {
  if (!sessionActive()) return true;
  sessionActive_.store(false, std::memory_order_release);
  diagnostics_.sessionActive = false;

  bool ok = device_.suspend();
  addCounter_(diagnostics_.stopDrainAttempts);
  if (!drainAllAvailable_(kFinalDrainPasses, false, true)) {
    addCounter_(diagnostics_.stopDrainFailures);
    ok = false;
  }
  return ok;
}

size_t BMI270FifoAcquisition::discardQueuedSamples() {
  const size_t count = queue_.size();
  queue_.clear();
  addCounter_(diagnostics_.explicitQueueDiscards, static_cast<uint64_t>(count));
  return count;
}

bool BMI270FifoAcquisition::pop(BMI270ImuSample& sample) {
  if (!queue_.pop(sample)) return false;
  addCounter_(diagnostics_.samplesDequeued);
  return true;
}

bool BMI270FifoAcquisition::asyncAcquire() {
  if (!sessionActive()) return true;
  if (recoveryBackoffPolls_ > 0) {
    --recoveryBackoffPolls_;
    return false;
  }

  addCounter_(diagnostics_.drainCalls);
  const uint32_t startedUs = micros();
  const bool ok = drainAllAvailable_(kNormalDrainPasses, true);
  const uint32_t durationUs = static_cast<uint32_t>(micros() - startedUs);
  if (durationUs > diagnostics_.maximumDrainDurationUs) {
    diagnostics_.maximumDrainDurationUs = durationUs;
  }

  if (ok) {
    consecutiveDrainFailures_ = 0;
    return true;
  }

  addCounter_(diagnostics_.drainFailures);
  ++consecutiveDrainFailures_;
  if (consecutiveDrainFailures_ > diagnostics_.maximumDrainFailureStreak) {
    diagnostics_.maximumDrainFailureStreak = consecutiveDrainFailures_;
  }
  pendingStatus_ |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                    BMI270ImuStatus::kTimingDegraded;
  if (consecutiveDrainFailures_ < kRecoveryFailureThreshold) return false;

  const bool recovered = recoverAcquisition_();
  consecutiveDrainFailures_ = 0;
  if (!recovered) recoveryBackoffPolls_ = kRecoveryBackoffPolls;
  return false;
}

bool BMI270FifoAcquisition::configureFifo_() {
  struct bmi2_dev& native = device_.nativeDevice();
  int8_t result = bmi2_set_fifo_config(kManagedFifoConfig, BMI2_DISABLE, &native);
  if (result == BMI2_OK) {
    result = bmi2_set_fifo_down_sample(BMI2_ACCEL, 0, &native);
  }
  if (result == BMI2_OK) {
    result = bmi2_set_fifo_down_sample(BMI2_GYRO, 0, &native);
  }
  if (result == BMI2_OK) {
    result = bmi2_set_fifo_filter_data(BMI2_ACCEL, BMI2_FIFO_FILTERED_DATA, &native);
  }
  if (result == BMI2_OK) {
    result = bmi2_set_fifo_filter_data(BMI2_GYRO, BMI2_FIFO_FILTERED_DATA, &native);
  }
  if (result == BMI2_OK) result = bmi2_set_fifo_wm(0, &native);
  if (result == BMI2_OK) {
    result = bmi2_set_fifo_config(kRequiredFifoConfig, BMI2_ENABLE, &native);
  }

  uint16_t effective = 0;
  if (result == BMI2_OK) result = bmi2_get_fifo_config(&effective, &native);
  if (result == BMI2_OK) {
    result = bmi2_get_fifo_wm(&diagnostics_.effectiveFifoWatermark, &native);
  }
  if (result == BMI2_OK) {
    result = bmi2_get_fifo_down_sample(
        BMI2_ACCEL,
        &diagnostics_.effectiveAccelDownsample,
        &native);
  }
  if (result == BMI2_OK) {
    result = bmi2_get_fifo_down_sample(
        BMI2_GYRO,
        &diagnostics_.effectiveGyroDownsample,
        &native);
  }
  if (result == BMI2_OK) {
    result = bmi2_get_fifo_filter_data(
        BMI2_ACCEL,
        &diagnostics_.effectiveAccelFiltered,
        &native);
  }
  if (result == BMI2_OK) {
    result = bmi2_get_fifo_filter_data(
        BMI2_GYRO,
        &diagnostics_.effectiveGyroFiltered,
        &native);
  }
  diagnostics_.lastApiResult = result;
  diagnostics_.effectiveFifoConfig = effective;
  diagnostics_.fifoConfigured =
      result == BMI2_OK &&
      (effective & kManagedFifoConfig) == kRequiredFifoConfig &&
      diagnostics_.effectiveFifoWatermark == 0 &&
      diagnostics_.effectiveAccelDownsample == 0 &&
      diagnostics_.effectiveGyroDownsample == 0 &&
      diagnostics_.effectiveAccelFiltered == BMI2_FIFO_FILTERED_DATA &&
      diagnostics_.effectiveGyroFiltered == BMI2_FIFO_FILTERED_DATA;
  if (!diagnostics_.fifoConfigured) {
    if (result == BMI2_OK) diagnostics_.lastApiResult = BMI2_E_INVALID_STATUS;
    BMI270_FIFO_LOGW(
        "FIFO configuration failed name=%s result=%d effective=0x%04X required=0x%04X\n",
        name_,
        (int)diagnostics_.lastApiResult,
        (unsigned)effective,
        (unsigned)kRequiredFifoConfig);
    return false;
  }
  return true;
}

bool BMI270FifoAcquisition::flushFifo_() {
  const int8_t result =
      bmi2_set_command_register(BMI2_FIFO_FLUSH_CMD, &device_.nativeDevice());
  diagnostics_.lastApiResult = result;
  if (result != BMI2_OK) {
    addCounter_(diagnostics_.fifoFlushFailures);
    return false;
  }
  addCounter_(diagnostics_.fifoFlushes);
  return true;
}

bool BMI270FifoAcquisition::drainAllAvailable_(
    uint8_t maximumPasses,
    bool readTemperature,
    bool requireEmpty) {
  for (uint8_t pass = 0; pass < maximumPasses; ++pass) {
    const DrainPassResult result = drainOnePass_(readTemperature);
    if (result == DrainPassResult::Failure) return false;
    if (result == DrainPassResult::Empty) return true;
  }
  addCounter_(diagnostics_.drainPassLimitHits);
  return !requireEmpty;
}

BMI270FifoAcquisition::DrainPassResult BMI270FifoAcquisition::drainOnePass_(
    bool readTemperature) {
  struct bmi2_dev& native = device_.nativeDevice();
  if (!device_.beginBusTransaction(BMI2_FIFO_LENGTH_0_ADDR, 2)) {
    diagnostics_.lastApiResult = BMI2_E_COM_FAIL;
    return DrainPassResult::Failure;
  }
  uint16_t fifoLength = 0;
  int8_t result = bmi2_get_fifo_length(&fifoLength, &native);
  diagnostics_.lastApiResult = result;
  if (result != BMI2_OK) {
    device_.endBusTransaction();
    return DrainPassResult::Failure;
  }
  addCounter_(diagnostics_.drainPasses);

  if (fifoLength == 0) {
    device_.endBusTransaction();
    addCounter_(diagnostics_.emptyPasses);
    return DrainPassResult::Empty;
  }
  if (fifoLength > 2048) {
    device_.endBusTransaction();
    diagnostics_.lastApiResult = BMI2_E_INVALID_STATUS;
    pendingStatus_ |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                      BMI270ImuStatus::kTimingDegraded;
    return DrainPassResult::Failure;
  }
  if (fifoLength > diagnostics_.maximumFifoBytesObserved) {
    diagnostics_.maximumFifoBytesObserved = fifoLength;
  }
  if (fifoLength == 2048) addCounter_(diagnostics_.fifoFullObservations);

  const size_t bytesToRead = BMI270FifoReadPlan::bytesToRead(fifoLength);
  if (bytesToRead == 0 || bytesToRead > sizeof(rawBuffer_)) {
    device_.endBusTransaction();
    diagnostics_.lastApiResult = BMI2_E_INVALID_STATUS;
    return DrainPassResult::Failure;
  }
  native.intf_rslt = native.read(
      BMI2_FIFO_DATA_ADDR,
      rawBuffer_,
      static_cast<uint32_t>(bytesToRead),
      native.intf_ptr);
  const BMI270I2CReadTiming transferTiming = device_.lastReadTiming();
  device_.endBusTransaction();
  if (native.intf_rslt != BMI2_INTF_RET_SUCCESS) {
    diagnostics_.lastApiResult = BMI2_E_COM_FAIL;
    return DrainPassResult::Failure;
  }
  if (!transferTiming.valid ||
      transferTiming.registerAddress != BMI2_FIFO_DATA_ADDR ||
      transferTiming.bytes != bytesToRead ||
      transferTiming.transferEndUs < transferTiming.transferStartUs) {
    diagnostics_.lastApiResult = BMI2_E_INVALID_STATUS;
    return DrainPassResult::Failure;
  }
  const uint64_t acquisitionStartUs = transferTiming.transferStartUs;
  const uint64_t acquisitionEndUs = transferTiming.transferEndUs;
  addCounter_(diagnostics_.fifoBytesRead, bytesToRead);

  const BMI270FifoParseResult parsed = BMI270FifoParser::parseHeaderMode(
      rawBuffer_,
      bytesToRead,
      parsed_,
      kMaximumBatchSamples,
      pendingStatus_,
      pendingSkippedFrames_);
  pendingStatus_ = parsed.pendingStatus;
  pendingSkippedFrames_ = parsed.pendingSkippedFrames;
  accumulateParseDiagnostics_(parsed);

  if (parsed.samplesWritten == 0) return DrainPassResult::Data;
  if (!parsed.sensorTimePresent) addCounter_(diagnostics_.missingSensorTimeBatches);

  int16_t temperatureRaw = lastTemperatureRaw_;
  if (readTemperature &&
      (!haveTemperature_ || acquisitionEndUs >= nextTemperatureReadUs_)) {
    addCounter_(diagnostics_.temperatureReads);
    result = bmi2_get_temperature_data(&temperatureRaw, &native);
    if (result == BMI2_OK) {
      lastTemperatureRaw_ = temperatureRaw;
      haveTemperature_ = true;
      lastTemperatureHostUs_ = acquisitionEndUs;
      nextTemperatureReadUs_ = acquisitionEndUs + kTemperaturePeriodUs;
    } else {
      addCounter_(diagnostics_.temperatureReadFailures);
      diagnostics_.lastApiResult = result;
      temperatureRaw = haveTemperature_ ? lastTemperatureRaw_ : 0;
      nextTemperatureReadUs_ = acquisitionEndUs + kTemperaturePeriodUs;
    }
  }
  const bool temperatureFresh = haveTemperature_ &&
      acquisitionEndUs - lastTemperatureHostUs_ <= kTemperatureFreshnessUs;

  const uint64_t span64 = acquisitionEndUs - acquisitionStartUs;
  const uint32_t spanUs = span64 > UINT32_MAX
      ? UINT32_MAX
      : static_cast<uint32_t>(span64);
  enqueueParsed_(
      parsed,
      parsed.samplesWritten,
      temperatureRaw,
      temperatureFresh,
      acquisitionStartUs,
      acquisitionEndUs,
      bytesToRead,
      spanUs);
  return DrainPassResult::Data;
}

bool BMI270FifoAcquisition::recoverAcquisition_() {
  addCounter_(diagnostics_.recoveryAttempts);
  if (!device_.recover()) return false;
  if (!configureFifo_()) return false;
  if (!flushFifo_()) return false;

  addCounter_(diagnostics_.recoverySuccesses);
  recoveryBackoffPolls_ = 0;
  havePreviousSensorTime_ = false;
  pendingStatus_ |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                    BMI270ImuStatus::kSensorRecoveryBefore |
                    BMI270ImuStatus::kTimingDegraded;
  return true;
}

void BMI270FifoAcquisition::resetSessionState_(uint64_t preSessionDiscards) {
  const uint16_t effectiveFifoConfig = diagnostics_.effectiveFifoConfig;
  const uint16_t effectiveFifoWatermark = diagnostics_.effectiveFifoWatermark;
  const uint8_t effectiveAccelDownsample = diagnostics_.effectiveAccelDownsample;
  const uint8_t effectiveGyroDownsample = diagnostics_.effectiveGyroDownsample;
  const uint8_t effectiveAccelFiltered = diagnostics_.effectiveAccelFiltered;
  const uint8_t effectiveGyroFiltered = diagnostics_.effectiveGyroFiltered;
  const bool fifoConfigured = diagnostics_.fifoConfigured;
  diagnostics_ = BMI270FifoDiagnostics{};
  diagnostics_.queueCapacity = static_cast<uint16_t>(kQueueCapacity);
  diagnostics_.effectiveFifoConfig = effectiveFifoConfig;
  diagnostics_.effectiveFifoWatermark = effectiveFifoWatermark;
  diagnostics_.effectiveAccelDownsample = effectiveAccelDownsample;
  diagnostics_.effectiveGyroDownsample = effectiveGyroDownsample;
  diagnostics_.effectiveAccelFiltered = effectiveAccelFiltered;
  diagnostics_.effectiveGyroFiltered = effectiveGyroFiltered;
  diagnostics_.fifoConfigured = fifoConfigured;
  diagnostics_.preSessionQueueDiscards = preSessionDiscards;
  nextSequence_ = 0;
  pendingStatus_ = 0;
  pendingSkippedFrames_ = 0;
  consecutiveDrainFailures_ = 0;
  recoveryBackoffPolls_ = 0;
  havePreviousSensorTime_ = false;
  previousSensorTime_ = 0;
  haveTemperature_ = false;
  lastTemperatureRaw_ = 0;
  lastTemperatureHostUs_ = 0;
  nextTemperatureReadUs_ = 0;
}

void BMI270FifoAcquisition::accumulateParseDiagnostics_(
    const BMI270FifoParseResult& parsed) {
  addCounter_(diagnostics_.fifoFramesParsed, parsed.sampleFrames);
  addCounter_(diagnostics_.sensorTimeFrames, parsed.sensorTimeFrames);
  addCounter_(diagnostics_.skipControlFrames, parsed.skipControlFrames);
  addCounter_(diagnostics_.fifoOverflowEvents, parsed.skipControlFrames);
  addCounter_(diagnostics_.hardwareSkippedFrames, parsed.skippedFrames);
  addCounter_(diagnostics_.unpairedFrames, parsed.unpairedFrames);
  addCounter_(diagnostics_.inputConfigFrames, parsed.inputConfigFrames);
  addCounter_(diagnostics_.invalidHeaders, parsed.invalidHeaders);
  addCounter_(diagnostics_.partialFrames, parsed.partialFrames);
  if (parsed.overreadSeen) addCounter_(diagnostics_.overreadFrames);
  addCounter_(diagnostics_.parserOutputDrops, parsed.outputDrops);
}

void BMI270FifoAcquisition::enqueueParsed_(
    const BMI270FifoParseResult& parsed,
    size_t count,
    int16_t temperatureRaw,
    bool temperatureFresh,
    uint64_t acquisitionStartUs,
    uint64_t acquisitionEndUs,
    size_t bytesRead,
    uint32_t acquisitionSpanUs) {
  const bool hadPreviousSensorTime = havePreviousSensorTime_;
  const bool haveSensorTimeReference = BMI270FifoParser::assignSensorTimes200Hz(
      parsed_,
      count,
      parsed.sensorTimePresent,
      parsed.sensorTime,
      havePreviousSensorTime_,
      previousSensorTime_);

  uint32_t referenceSensorTime = 0;
  uint64_t referenceHostUs = 0;
  if (parsed.sensorTimePresent) {
    referenceSensorTime = parsed.sensorTime & BMI270FifoParser::kSensorTimeMask;
    referenceHostUs = BMI270ImuTiming::interpolateTransferTimeUs(
        acquisitionStartUs,
        acquisitionEndUs,
        parsed.sensorTimeAnchorByteOffset,
        bytesRead);
  } else if (hadPreviousSensorTime && haveSensorTimeReference && count) {
    referenceSensorTime = parsed_[count - 1].sensorTime;
    referenceHostUs = acquisitionStartUs +
        ((acquisitionEndUs - acquisitionStartUs) / 2u);
  }

  // Parser events after the last retained sample belong to a future sample.
  // Keep them separate while queue-full events are propagated through this
  // batch to the first sample that can actually be stored.
  const uint16_t parserFutureStatus = pendingStatus_;
  pendingStatus_ = 0;
  for (size_t index = 0; index < count; ++index) {
    BMI270ImuSample sample;
    sample.accelX = parsed_[index].accelX;
    sample.accelY = parsed_[index].accelY;
    sample.accelZ = parsed_[index].accelZ;
    sample.gyroX = parsed_[index].gyroX;
    sample.gyroY = parsed_[index].gyroY;
    sample.gyroZ = parsed_[index].gyroZ;
    sample.temperatureRaw = temperatureRaw;
    sample.statusFlags = parsed_[index].statusBefore;
    sample.sensorTime = parsed_[index].sensorTime;
    if (!temperatureFresh) sample.statusFlags |= BMI270ImuStatus::kTemperatureStale;
    uint64_t estimatedHostUs = 0;
    sample.acquisitionAnchorUs = BMI270ImuTiming::estimateHostSampleTimeUs(
        referenceSensorTime,
        parsed_[index].sensorTime,
        referenceHostUs,
        estimatedHostUs)
        ? estimatedHostUs
        : 0;
    sample.acquisitionSpanUs = acquisitionSpanUs;

    nextSequence_ += parsed_[index].skippedFramesBefore;
    sample.sequence = nextSequence_++;
    sample.statusFlags |= pendingStatus_;
    size_t depth = 0;
    if (queue_.push(sample, &depth)) {
      addCounter_(diagnostics_.samplesEnqueued);
      if (depth > diagnostics_.queueHighWater) {
        diagnostics_.queueHighWater = static_cast<uint16_t>(depth);
      }
      pendingStatus_ = 0;
    } else {
      addCounter_(diagnostics_.queueDrops);
      pendingStatus_ |= (sample.statusFlags & kCarryStatusMask) |
                        BMI270ImuStatus::kQueueDropBefore;
    }
  }
  // Parser capacity drops can only occur after the retained prefix. Consume
  // their sequence positions after assigning the retained records.
  nextSequence_ += parsed.outputDrops;
  pendingStatus_ |= parserFutureStatus;
  diagnostics_.nextSequence = nextSequence_;
}

void BMI270FifoAcquisition::addCounter_(uint64_t& counter, uint64_t amount) {
  if (UINT64_MAX - counter < amount) {
    counter = UINT64_MAX;
    diagnostics_.counterSaturated = true;
    return;
  }
  counter += amount;
}
