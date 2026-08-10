#pragma once

#include <atomic>
#include <stddef.h>
#include <stdint.h>

#include "BMI270Device.h"
#include "BMI270FifoParser.h"
#include "BMI270FifoReadPlan.h"
#include "BMI270ImuSample.h"
#include "BMI270ProgressWatchdog.h"
#include "BMI270SessionQuality.h"
#include "FixedSpscQueue.h"
#include "I2CBusScheduler.h"

enum class BMI270RecoveryReason : uint8_t {
  None = 0,
  ConsecutiveDrainFailures,
  SessionStartValidation,
  NoSampleProgress,
};

static_assert(static_cast<uint8_t>(BMI270RecoveryReason::None) == 0);
static_assert(static_cast<uint8_t>(BMI270RecoveryReason::ConsecutiveDrainFailures) == 1);
static_assert(static_cast<uint8_t>(BMI270RecoveryReason::SessionStartValidation) == 2);
static_assert(static_cast<uint8_t>(BMI270RecoveryReason::NoSampleProgress) == 3);

struct BMI270FifoDiagnostics {
  uint64_t drainCalls = 0;
  uint64_t drainPasses = 0;
  uint64_t emptyPasses = 0;
  uint64_t drainFailures = 0;
  uint64_t drainPassLimitHits = 0;
  uint64_t fifoBytesRead = 0;
  uint64_t fifoFramesParsed = 0;
  uint64_t sensorTimeFrames = 0;
  uint64_t missingSensorTimeBatches = 0;
  uint64_t skipControlFrames = 0;
  uint64_t fifoOverflowEvents = 0;
  uint64_t fifoFullObservations = 0;
  uint64_t hardwareSkippedFrames = 0;
  uint64_t unpairedFrames = 0;
  uint64_t inputConfigFrames = 0;
  uint64_t invalidHeaders = 0;
  uint64_t partialFrames = 0;
  uint64_t overreadFrames = 0;
  uint64_t parserOutputDrops = 0;
  uint64_t samplesEnqueued = 0;
  uint64_t samplesDequeued = 0;
  uint64_t queueDrops = 0;
  uint64_t preSessionQueueDiscards = 0;
  uint64_t explicitQueueDiscards = 0;
  uint64_t temperatureReads = 0;
  uint64_t temperatureReadFailures = 0;
  uint64_t operationalValidationAttempts = 0;
  uint64_t operationalValidationFailures = 0;
  uint64_t sessionStartValidationAttempts = 0;
  uint64_t sessionStartValidationFailures = 0;
  uint64_t noProgressEvents = 0;
  uint64_t recoveryAttempts = 0;
  uint64_t recoverySuccesses = 0;
  uint64_t recoveryFailures = 0;
  uint64_t terminalFaultEvents = 0;
  uint64_t fifoFlushes = 0;
  uint64_t fifoFlushFailures = 0;
  uint64_t stopDrainAttempts = 0;
  uint64_t stopDrainFailures = 0;
  uint64_t accelNearRail[3] {};
  uint64_t gyroNearRail[3] {};
  uint64_t timingDegradedSamples = 0;
  uint64_t sequenceDiscontinuityEvents = 0;
  uint64_t nativeTimeDiscontinuityEvents = 0;

  uint16_t maximumFifoBytesObserved = 0;
  uint16_t queueCapacity = 0;
  uint16_t queueHighWater = 0;
  uint32_t maximumDrainDurationUs = 0;
  uint32_t maximumDrainFailureStreak = 0;
  uint32_t maximumNoProgressUs = 0;
  uint32_t lastValidationIssues = 0;
  uint32_t nextSequence = 0;
  uint16_t effectiveFifoConfig = 0;
  uint16_t effectiveFifoWatermark = 0;
  uint8_t effectiveAccelDownsample = 0;
  uint8_t effectiveGyroDownsample = 0;
  uint8_t effectiveAccelFiltered = 0;
  uint8_t effectiveGyroFiltered = 0;
  uint16_t lastValidationFifoConfig = 0;
  uint16_t lastValidationFifoWatermark = 0;
  uint8_t lastValidationChipId = 0;
  uint8_t lastValidationInternalStatus = 0;
  uint8_t lastValidationPowerControl = 0;
  uint8_t lastValidationAccelDownsample = 0;
  uint8_t lastValidationGyroDownsample = 0;
  uint8_t lastValidationAccelFiltered = 0;
  uint8_t lastValidationGyroFiltered = 0;
  uint8_t consecutiveRecoveryFailures = 0;
  uint8_t recoveryAttemptsWithoutProgress = 0;
  BMI270RecoveryReason lastRecoveryReason = BMI270RecoveryReason::None;
  int8_t lastApiResult = BMI2_OK;
  int8_t lastValidationApiResult = BMI2_OK;
  bool fifoConfigured = false;
  bool sessionActive = false;
  bool terminalFault = false;
  bool counterSaturated = false;
};

class BMI270FifoAcquisition : public I2CAsyncClient {
public:
  static constexpr size_t kQueueCapacity = 512;
  static constexpr size_t kRawBufferBytes = BMI270FifoReadPlan::kMaximumReadBytes;
  static constexpr size_t kMaximumBatchSamples = 160;
  static constexpr uint16_t kTargetRateHz = 200;
  static constexpr uint16_t kTemperatureRateHz = 10;
  static constexpr uint32_t kTemperaturePeriodUs = 1000000u / kTemperatureRateHz;
  static constexpr uint32_t kTemperatureFreshnessUs = 250000u;
  static constexpr uint32_t kNoSampleProgressTimeoutUs = 250000u;
  static constexpr uint8_t kMaximumConsecutiveRecoveryFailures = 3;
  static constexpr uint32_t kQueueCoverageMs =
      static_cast<uint32_t>((kQueueCapacity * 1000u) / kTargetRateHz);

  BMI270FifoAcquisition(uint8_t busIndex, uint8_t address, const char* name = nullptr);
  ~BMI270FifoAcquisition() override;

  BMI270FifoAcquisition(const BMI270FifoAcquisition&) = delete;
  BMI270FifoAcquisition& operator=(const BMI270FifoAcquisition&) = delete;

  // Initializes and configures the device, then leaves sensing suspended.
  bool begin();
  void shutdown();

  // These calls require the I2C scheduler to be stopped. stopSession() stops
  // new production, performs the final FIFO drain, and leaves queued samples
  // available to the Phase 4 row adapter.
  bool startSession(uint16_t startupObservationSeconds = 5);
  bool stopSession();
  size_t discardQueuedSamples();

  bool pop(BMI270ImuSample& sample);
  void recordRowEmission(uint32_t ageUs, bool ageValid);
  size_t queuedSamples() const { return queue_.size(); }
  bool sessionActive() const { return sessionActive_.load(std::memory_order_acquire); }

  // Read diagnostics only after the scheduler has stopped; cumulative 64-bit
  // fields are intentionally not synchronized on the hot acquisition path.
  const BMI270FifoDiagnostics& diagnostics() const { return diagnostics_; }
  const BMI270StartupObservationResult& startupObservation() const {
    return startupObservation_.result();
  }
  BMI270AgeSummary ageSummary() const { return ageHistogram_.summary(); }
  const BMI270RunningStats& temperatureStats() const { return temperatureStats_; }
  const BMI270Device& device() const { return device_; }
  BMI270Device& device() { return device_; }

  const char* asyncClientName() const override { return name_; }
  const char* asyncClientKind() const override { return "bmi270_imu_i2c"; }
  uint8_t asyncI2CBusIndex() const override { return device_.busIndex(); }
  uint8_t asyncI2CAddress() const override { return device_.address(); }
  uint16_t asyncTargetRateHz() const override { return kTargetRateHz; }
  uint32_t asyncMaximumLowPriorityGapUs() const override { return 50000u; }
  bool asyncMuted() const override {
    return !sessionActive() || terminalFault_.load(std::memory_order_acquire);
  }
  bool asyncAcquire() override;

private:
  enum class DrainPassResult : uint8_t { Empty = 0, Data, Failure };

  struct FifoConfigurationSnapshot {
    uint16_t config = 0;
    uint16_t watermark = 0;
    uint8_t accelDownsample = 0;
    uint8_t gyroDownsample = 0;
    uint8_t accelFiltered = 0;
    uint8_t gyroFiltered = 0;
    int8_t apiResult = BMI2_OK;
    bool readOk = false;
    bool matched = false;
  };

  bool configureFifo_();
  bool readFifoConfiguration_(FifoConfigurationSnapshot& out);
  bool validateOperationalState_(bool sensorsExpected, bool noSampleProgress);
  bool flushFifo_();
  bool drainAllAvailable_(
      uint8_t maximumPasses,
      bool readTemperature,
      bool requireEmpty = false);
  DrainPassResult drainOnePass_(bool readTemperature);
  bool recoverAcquisition_(BMI270RecoveryReason reason);
  bool handleNoSampleProgress_(uint32_t nowUs);
  void enterTerminalFault_(BMI270RecoveryReason reason);
  void resetSessionState_(uint64_t preSessionDiscards);
  void accumulateParseDiagnostics_(const BMI270FifoParseResult& parsed);
  void enqueueParsed_(
      const BMI270FifoParseResult& parsed,
      size_t count,
      int16_t temperatureRaw,
      bool temperatureFresh,
      uint64_t acquisitionStartUs,
      uint64_t acquisitionEndUs,
      size_t bytesRead,
      uint32_t acquisitionSpanUs);
  void addCounter_(uint64_t& counter, uint64_t amount = 1);

  char name_[32] = "bmi270";
  BMI270Device device_;
  FixedSpscQueue<BMI270ImuSample, kQueueCapacity> queue_;
  BMI270FifoDiagnostics diagnostics_;
  std::atomic<bool> sessionActive_ { false };
  std::atomic<bool> terminalFault_ { false };

  uint8_t rawBuffer_[kRawBufferBytes] {};
  BMI270FifoParsedSample parsed_[kMaximumBatchSamples] {};

  uint32_t nextSequence_ = 0;
  uint16_t pendingStatus_ = 0;
  uint32_t pendingSkippedFrames_ = 0;
  uint32_t consecutiveDrainFailures_ = 0;
  uint8_t consecutiveRecoveryFailures_ = 0;
  uint16_t recoveryBackoffPolls_ = 0;
  BMI270ProgressWatchdog progressWatchdog_ { kNoSampleProgressTimeoutUs };
  BMI270RecoveryBudget recoveryBudget_ { kMaximumConsecutiveRecoveryFailures };
  BMI270StartupObservation startupObservation_;
  BMI270AgeHistogram ageHistogram_;
  BMI270RunningStats temperatureStats_;
  bool havePreviousDequeuedSequence_ = false;
  uint32_t previousDequeuedSequence_ = 0;
  bool havePreviousSensorTime_ = false;
  uint32_t previousSensorTime_ = 0;
  bool haveTemperature_ = false;
  int16_t lastTemperatureRaw_ = 0;
  uint64_t lastTemperatureHostUs_ = 0;
  uint64_t nextTemperatureReadUs_ = 0;
  bool initialized_ = false;
  bool registered_ = false;
};
