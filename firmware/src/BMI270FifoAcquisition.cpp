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
constexpr uint64_t kIocOffsetSnapshotPeriodUs = 1000000u;
constexpr uint16_t kCarryStatusMask =
    BMI270ImuStatus::kFifoDiscontinuityBefore |
    BMI270ImuStatus::kQueueDropBefore |
    BMI270ImuStatus::kSensorRecoveryBefore |
    BMI270ImuStatus::kTimingDegraded;
constexpr int16_t kNearRailThreshold = 32760;

bool nearRail_(int16_t value) {
  return value <= -kNearRailThreshold || value >= kNearRailThreshold;
}

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

bool BMI270FifoAcquisition::setOutputRateHz(uint16_t rateHz) {
  if (initialized_ || !BMI270Profile::isSupportedOutputRate(rateHz)) return false;
  outputRateHz_ = rateHz;
  outputDecimationFactor_ = BMI270Profile::outputDecimationFactor(rateHz);
  return outputDecimationFactor_ != 0;
}

bool BMI270FifoAcquisition::setGyroBiasMode(BMI270GyroBiasMode mode) {
  if (initialized_) return false;
  gyroBiasMode_ = mode;
  return device_.setGyroBiasMode(mode);
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
  terminalFault_.store(false, std::memory_order_release);
  progressWatchdog_.disarm();
  if (registered_) {
    I2CBusScheduler::unregisterClient(this);
    registered_ = false;
  }
  device_.shutdown();
  initialized_ = false;
}

bool BMI270FifoAcquisition::startSession(uint16_t startupObservationSeconds) {
  if (!initialized_ && !begin()) return false;
  if (sessionActive()) return true;

  if (device_.state() == BMI270DeviceState::Ready && !device_.suspend()) return false;

  const uint64_t preSessionDiscards = static_cast<uint64_t>(queue_.size());
  queue_.clear();
  resetSessionState_(preSessionDiscards);
  // Keep the observer disabled until validation/recovery and the final FIFO
  // flush have completed. Those operations belong to the session boundary,
  // not to the stationary measurement window.
  startupObservation_.begin(0);
  device_.resetTransportDiagnostics();

  addCounter_(diagnostics_.sessionStartValidationAttempts);
  if (!validateOperationalState_(false, false)) {
    addCounter_(diagnostics_.sessionStartValidationFailures);
    if (!recoverAcquisition_(BMI270RecoveryReason::SessionStartValidation)) {
      return false;
    }
    if (!device_.suspend()) return false;
  }

  if (!flushFifo_()) return false;
  if (!device_.resume()) return false;

  // Preserve setup/recovery status on the first emitted stream sample while
  // keeping it distinguishable from incidents that occur after acquisition
  // starts. Consumers performing stationary measurements exclude only this
  // known pre-session boundary status.
  preSessionBoundaryStatus_ = pendingStatus_ & kCarryStatusMask;
  pendingStatus_ &= static_cast<uint16_t>(~kCarryStatusMask);
  startupObservation_.begin(startupObservationSeconds);

  progressWatchdog_.arm(micros());
  sessionActive_.store(true, std::memory_order_release);
  diagnostics_.sessionActive = true;
  return true;
}

bool BMI270FifoAcquisition::stopSession() {
  if (!sessionActive()) return true;
  sessionActive_.store(false, std::memory_order_release);
  diagnostics_.sessionActive = false;
  progressWatchdog_.disarm();

  bool ok = device_.suspend();
  addCounter_(diagnostics_.stopDrainAttempts);
  if (!drainAllAvailable_(kFinalDrainPasses, false, true)) {
    addCounter_(diagnostics_.stopDrainFailures);
    ok = false;
  }
  startupObservation_.finish();
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
  if (havePreviousDequeuedSequence_ &&
      sample.sequence != previousDequeuedSequence_ + outputDecimationFactor_) {
    addCounter_(diagnostics_.sequenceDiscontinuityEvents);
  }
  previousDequeuedSequence_ = sample.sequence;
  havePreviousDequeuedSequence_ = true;
  addCounter_(diagnostics_.samplesDequeued);
  return true;
}

bool BMI270FifoAcquisition::popIocOffsetSnapshot(BMI270IocOffsetSnapshot& snapshot) {
  return iocOffsetSnapshots_.pop(snapshot);
}

void BMI270FifoAcquisition::recordRowEmission(uint32_t ageUs, bool ageValid) {
  ageHistogram_.add(ageUs, ageValid);
}

bool BMI270FifoAcquisition::asyncAcquire() {
  if (!sessionActive()) return true;
  if (terminalFault_.load(std::memory_order_acquire)) return false;
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
    const uint32_t nowUs = micros();
    if (progressWatchdog_.expired(nowUs)) {
      return handleNoSampleProgress_(nowUs);
    }
    return true;
  }

  addCounter_(diagnostics_.drainFailures);
  ++consecutiveDrainFailures_;
  if (consecutiveDrainFailures_ > diagnostics_.maximumDrainFailureStreak) {
    diagnostics_.maximumDrainFailureStreak = consecutiveDrainFailures_;
  }
  pendingStatus_ |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                    BMI270ImuStatus::kTimingDegraded;
  startupObservation_.noteQualityIncident();
  if (consecutiveDrainFailures_ < kRecoveryFailureThreshold) return false;

  const bool recovered = recoverAcquisition_(
      BMI270RecoveryReason::ConsecutiveDrainFailures);
  consecutiveDrainFailures_ = 0;
  (void)recovered;
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

  FifoConfigurationSnapshot snapshot;
  if (result == BMI2_OK && !readFifoConfiguration_(snapshot)) {
    result = snapshot.apiResult;
  }
  diagnostics_.lastApiResult = result;
  diagnostics_.effectiveFifoConfig = snapshot.config;
  diagnostics_.effectiveFifoWatermark = snapshot.watermark;
  diagnostics_.effectiveAccelDownsample = snapshot.accelDownsample;
  diagnostics_.effectiveGyroDownsample = snapshot.gyroDownsample;
  diagnostics_.effectiveAccelFiltered = snapshot.accelFiltered;
  diagnostics_.effectiveGyroFiltered = snapshot.gyroFiltered;
  diagnostics_.fifoConfigured = result == BMI2_OK && snapshot.matched;
  if (!diagnostics_.fifoConfigured) {
    if (result == BMI2_OK) diagnostics_.lastApiResult = BMI2_E_INVALID_STATUS;
    BMI270_FIFO_LOGW(
        "FIFO configuration failed name=%s result=%d effective=0x%04X required=0x%04X\n",
        name_,
        (int)diagnostics_.lastApiResult,
        (unsigned)snapshot.config,
        (unsigned)kRequiredFifoConfig);
    return false;
  }
  return true;
}

bool BMI270FifoAcquisition::readFifoConfiguration_(
    FifoConfigurationSnapshot& out) {
  out = FifoConfigurationSnapshot{};
  struct bmi2_dev& native = device_.nativeDevice();
  int8_t result = bmi2_get_fifo_config(&out.config, &native);
  if (result == BMI2_OK) result = bmi2_get_fifo_wm(&out.watermark, &native);
  if (result == BMI2_OK) {
    result = bmi2_get_fifo_down_sample(BMI2_ACCEL, &out.accelDownsample, &native);
  }
  if (result == BMI2_OK) {
    result = bmi2_get_fifo_down_sample(BMI2_GYRO, &out.gyroDownsample, &native);
  }
  if (result == BMI2_OK) {
    result = bmi2_get_fifo_filter_data(BMI2_ACCEL, &out.accelFiltered, &native);
  }
  if (result == BMI2_OK) {
    result = bmi2_get_fifo_filter_data(BMI2_GYRO, &out.gyroFiltered, &native);
  }

  out.apiResult = result;
  out.readOk = result == BMI2_OK;
  out.matched = out.readOk &&
      (out.config & kManagedFifoConfig) == kRequiredFifoConfig &&
      out.watermark == 0 &&
      out.accelDownsample == 0 &&
      out.gyroDownsample == 0 &&
      out.accelFiltered == BMI2_FIFO_FILTERED_DATA &&
      out.gyroFiltered == BMI2_FIFO_FILTERED_DATA;
  if (out.readOk && !out.matched) out.apiResult = BMI2_E_INVALID_STATUS;
  return out.readOk && out.matched;
}

bool BMI270FifoAcquisition::validateOperationalState_(
    bool sensorsExpected,
    bool noSampleProgress) {
  addCounter_(diagnostics_.operationalValidationAttempts);

  BMI270OperationalState deviceState;
  device_.validateOperationalState(sensorsExpected, deviceState);
  FifoConfigurationSnapshot fifoState;
  readFifoConfiguration_(fifoState);

  uint32_t issues = deviceState.issues;
  if (!fifoState.readOk) {
    issues |= BMI270OperationalIssue::kFifoReadFailed;
  } else if (!fifoState.matched) {
    issues |= BMI270OperationalIssue::kFifoMismatch;
  }
  if (noSampleProgress) issues |= BMI270OperationalIssue::kNoSampleProgress;

  diagnostics_.lastValidationIssues = issues;
  diagnostics_.lastValidationChipId = deviceState.chipId;
  diagnostics_.lastValidationInternalStatus = deviceState.internalStatus;
  diagnostics_.lastValidationPowerControl = deviceState.powerControl;
  diagnostics_.lastValidationFifoConfig = fifoState.config;
  diagnostics_.lastValidationFifoWatermark = fifoState.watermark;
  diagnostics_.lastValidationAccelDownsample = fifoState.accelDownsample;
  diagnostics_.lastValidationGyroDownsample = fifoState.gyroDownsample;
  diagnostics_.lastValidationAccelFiltered = fifoState.accelFiltered;
  diagnostics_.lastValidationGyroFiltered = fifoState.gyroFiltered;
  diagnostics_.lastValidationApiResult = deviceState.lastApiResult != BMI2_OK
      ? deviceState.lastApiResult
      : fifoState.apiResult;
  if (noSampleProgress && diagnostics_.lastValidationApiResult == BMI2_OK) {
    diagnostics_.lastValidationApiResult = BMI2_E_INVALID_STATUS;
  }

  if (issues != 0) {
    addCounter_(diagnostics_.operationalValidationFailures);
    BMI270_FIFO_LOGW(
        "operational validation failed name=%s issues=0x%08lX api=%d chip=0x%02X internal=0x%02X power=0x%02X fifo=0x%04X\n",
        name_,
        (unsigned long)issues,
        (int)diagnostics_.lastValidationApiResult,
        (unsigned)deviceState.chipId,
        (unsigned)deviceState.internalStatus,
        (unsigned)deviceState.powerControl,
        (unsigned)fifoState.config);
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
  if (parsed.sampleFrames > 0) {
    progressWatchdog_.recordProgress(micros());
    recoveryBudget_.recordProgress();
    diagnostics_.recoveryAttemptsWithoutProgress = 0;
  }

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
  maybeCaptureIocOffsetSnapshot_(acquisitionEndUs);
  return DrainPassResult::Data;
}

bool BMI270FifoAcquisition::recoverAcquisition_(BMI270RecoveryReason reason) {
  if (reason != BMI270RecoveryReason::SessionStartValidation) {
    if (!recoveryBudget_.reserveAttempt()) {
      enterTerminalFault_(reason);
      return false;
    }
    diagnostics_.recoveryAttemptsWithoutProgress =
        recoveryBudget_.attemptsWithoutProgress();
  }
  addCounter_(diagnostics_.recoveryAttempts);
  diagnostics_.lastRecoveryReason = reason;
  const bool recovered = device_.recover() && configureFifo_() && flushFifo_();
  if (!recovered) {
    addCounter_(diagnostics_.recoveryFailures);
    if (consecutiveRecoveryFailures_ < UINT8_MAX) {
      ++consecutiveRecoveryFailures_;
    }
    diagnostics_.consecutiveRecoveryFailures = consecutiveRecoveryFailures_;
    progressWatchdog_.arm(micros());
    if (consecutiveRecoveryFailures_ >= kMaximumConsecutiveRecoveryFailures) {
      enterTerminalFault_(reason);
    } else {
      recoveryBackoffPolls_ = kRecoveryBackoffPolls;
    }
    return false;
  }

  addCounter_(diagnostics_.recoverySuccesses);
  consecutiveRecoveryFailures_ = 0;
  diagnostics_.consecutiveRecoveryFailures = 0;
  recoveryBackoffPolls_ = 0;
  havePreviousSensorTime_ = false;
  progressWatchdog_.arm(micros());
  pendingStatus_ |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                    BMI270ImuStatus::kSensorRecoveryBefore |
                    BMI270ImuStatus::kTimingDegraded;
  startupObservation_.noteQualityIncident();
  return true;
}

bool BMI270FifoAcquisition::handleNoSampleProgress_(uint32_t nowUs) {
  const uint32_t elapsedUs = progressWatchdog_.elapsedUs(nowUs);
  if (elapsedUs > diagnostics_.maximumNoProgressUs) {
    diagnostics_.maximumNoProgressUs = elapsedUs;
  }
  addCounter_(diagnostics_.noProgressEvents);
  validateOperationalState_(true, true);
  pendingStatus_ |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                    BMI270ImuStatus::kTimingDegraded;
  startupObservation_.noteQualityIncident();
  const bool recovered = recoverAcquisition_(BMI270RecoveryReason::NoSampleProgress);
  (void)recovered;
  return false;
}

void BMI270FifoAcquisition::enterTerminalFault_(BMI270RecoveryReason reason) {
  if (terminalFault_.exchange(true, std::memory_order_acq_rel)) return;
  diagnostics_.terminalFault = true;
  diagnostics_.lastRecoveryReason = reason;
  addCounter_(diagnostics_.terminalFaultEvents);
  BMI270_FIFO_LOGW(
      "terminal acquisition fault name=%s reason=%u failed=%u without_progress=%u\n",
      name_,
      (unsigned)reason,
      (unsigned)consecutiveRecoveryFailures_,
      (unsigned)recoveryBudget_.attemptsWithoutProgress());
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
  preSessionBoundaryStatus_ = 0;
  pendingSkippedFrames_ = 0;
  consecutiveDrainFailures_ = 0;
  recoveryBackoffPolls_ = 0;
  consecutiveRecoveryFailures_ = 0;
  recoveryBudget_.reset();
  terminalFault_.store(false, std::memory_order_release);
  progressWatchdog_.disarm();
  havePreviousSensorTime_ = false;
  previousSensorTime_ = 0;
  haveTemperature_ = false;
  lastTemperatureRaw_ = 0;
  lastTemperatureHostUs_ = 0;
  nextTemperatureReadUs_ = 0;
  nextIocOffsetReadUs_ = 0;
  iocOffsetSnapshots_.clear();
  ageHistogram_.reset();
  temperatureStats_.reset();
  havePreviousDequeuedSequence_ = false;
  previousDequeuedSequence_ = 0;
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
  if (parsed.outputDrops) startupObservation_.noteQualityIncident();
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
    if (nearRail_(sample.accelX)) {
      sample.statusFlags |= BMI270ImuStatus::kAccelNearRail;
      addCounter_(diagnostics_.accelNearRail[0]);
    }
    if (nearRail_(sample.accelY)) {
      sample.statusFlags |= BMI270ImuStatus::kAccelNearRail;
      addCounter_(diagnostics_.accelNearRail[1]);
    }
    if (nearRail_(sample.accelZ)) {
      sample.statusFlags |= BMI270ImuStatus::kAccelNearRail;
      addCounter_(diagnostics_.accelNearRail[2]);
    }
    if (nearRail_(sample.gyroX)) {
      sample.statusFlags |= BMI270ImuStatus::kGyroNearRail;
      addCounter_(diagnostics_.gyroNearRail[0]);
    }
    if (nearRail_(sample.gyroY)) {
      sample.statusFlags |= BMI270ImuStatus::kGyroNearRail;
      addCounter_(diagnostics_.gyroNearRail[1]);
    }
    if (nearRail_(sample.gyroZ)) {
      sample.statusFlags |= BMI270ImuStatus::kGyroNearRail;
      addCounter_(diagnostics_.gyroNearRail[2]);
    }
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
    if (preSessionBoundaryStatus_ != 0) {
      sample.statusFlags |=
          BMI270ImuStatus::markPreSessionBoundary(preSessionBoundaryStatus_);
    }
    if (parsed_[index].sensorTimeDiscontinuityBefore) {
      addCounter_(diagnostics_.nativeTimeDiscontinuityEvents);
    }
    if (sample.statusFlags & BMI270ImuStatus::kTimingDegraded) {
      addCounter_(diagnostics_.timingDegradedSamples);
    }
    if (temperatureFresh) {
      temperatureStats_.add(static_cast<double>(temperatureRaw) / 512.0 + 23.0);
    }
    startupObservation_.observe(
        sample.sequence,
        sample.accelX,
        sample.accelY,
        sample.accelZ,
        sample.gyroX,
        sample.gyroY,
        sample.gyroZ,
        sample.temperatureRaw,
        temperatureFresh,
        sample.measurementStatusFlags());
    const bool retainForOutput =
        outputDecimationFactor_ == 1 ||
        (sample.sequence % outputDecimationFactor_) == (outputDecimationFactor_ - 1u);
    if (!retainForOutput) {
      addCounter_(diagnostics_.samplesIntentionallyDecimated);
      continue;
    }
    if (outputDecimationFactor_ > 1) {
      sample.statusFlags |= BMI270ImuStatus::kOutputDecimated;
    }
    size_t depth = 0;
    if (queue_.push(sample, &depth)) {
      addCounter_(diagnostics_.samplesEnqueued);
      if (depth > diagnostics_.queueHighWater) {
        diagnostics_.queueHighWater = static_cast<uint16_t>(depth);
      }
      pendingStatus_ = 0;
      preSessionBoundaryStatus_ = 0;
    } else {
      addCounter_(diagnostics_.queueDrops);
      startupObservation_.noteQualityIncident();
      pendingStatus_ |= (sample.measurementStatusFlags() & kCarryStatusMask) |
                        BMI270ImuStatus::kQueueDropBefore;
    }
  }
  // Parser capacity drops can only occur after the retained prefix. Consume
  // their sequence positions after assigning the retained records.
  nextSequence_ += parsed.outputDrops;
  pendingStatus_ |= parserFutureStatus;
  diagnostics_.nextSequence = nextSequence_;
}

void BMI270FifoAcquisition::maybeCaptureIocOffsetSnapshot_(uint64_t nowUs) {
  if (!iocDiagnosticsEnabled_ ||
      gyroBiasMode_ != BMI270GyroBiasMode::InUseOffsetCorrection ||
      (nextIocOffsetReadUs_ != 0 && nowUs < nextIocOffsetReadUs_)) {
    return;
  }
  nextIocOffsetReadUs_ = nowUs + kIocOffsetSnapshotPeriodUs;
  addCounter_(diagnostics_.iocOffsetReadAttempts);
  struct bmi2_sens_axes_data axes {};
  if (!device_.readGyroOffsetCompensationAxes(axes)) {
    addCounter_(diagnostics_.iocOffsetReadFailures);
    return;
  }
  BMI270IocOffsetSnapshot snapshot;
  snapshot.x = axes.x;
  snapshot.y = axes.y;
  snapshot.z = axes.z;
  snapshot.nativeSequence = nextSequence_;
  if (!iocOffsetSnapshots_.push(snapshot)) {
    addCounter_(diagnostics_.iocOffsetSnapshotDrops);
  }
}

void BMI270FifoAcquisition::addCounter_(uint64_t& counter, uint64_t amount) {
  if (UINT64_MAX - counter < amount) {
    counter = UINT64_MAX;
    diagnostics_.counterSaturated = true;
    return;
  }
  counter += amount;
}
