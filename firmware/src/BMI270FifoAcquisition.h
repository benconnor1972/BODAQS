#pragma once

#include <atomic>
#include <stddef.h>
#include <stdint.h>

#include "BMI270Device.h"
#include "BMI270FifoParser.h"
#include "BMI270FifoReadPlan.h"
#include "BMI270ImuSample.h"
#include "FixedSpscQueue.h"
#include "I2CBusScheduler.h"

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
  uint64_t recoveryAttempts = 0;
  uint64_t recoverySuccesses = 0;
  uint64_t fifoFlushes = 0;
  uint64_t fifoFlushFailures = 0;
  uint64_t stopDrainAttempts = 0;
  uint64_t stopDrainFailures = 0;

  uint16_t maximumFifoBytesObserved = 0;
  uint16_t queueCapacity = 0;
  uint16_t queueHighWater = 0;
  uint32_t maximumDrainDurationUs = 0;
  uint32_t maximumDrainFailureStreak = 0;
  uint32_t nextSequence = 0;
  uint16_t effectiveFifoConfig = 0;
  uint16_t effectiveFifoWatermark = 0;
  uint8_t effectiveAccelDownsample = 0;
  uint8_t effectiveGyroDownsample = 0;
  uint8_t effectiveAccelFiltered = 0;
  uint8_t effectiveGyroFiltered = 0;
  int8_t lastApiResult = BMI2_OK;
  bool fifoConfigured = false;
  bool sessionActive = false;
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
  bool startSession();
  bool stopSession();
  size_t discardQueuedSamples();

  bool pop(BMI270ImuSample& sample);
  size_t queuedSamples() const { return queue_.size(); }
  bool sessionActive() const { return sessionActive_.load(std::memory_order_acquire); }

  // Read diagnostics only after the scheduler has stopped; cumulative 64-bit
  // fields are intentionally not synchronized on the hot acquisition path.
  const BMI270FifoDiagnostics& diagnostics() const { return diagnostics_; }
  const BMI270Device& device() const { return device_; }
  BMI270Device& device() { return device_; }

  const char* asyncClientName() const override { return name_; }
  const char* asyncClientKind() const override { return "bmi270_imu_i2c"; }
  uint8_t asyncI2CBusIndex() const override { return device_.busIndex(); }
  uint8_t asyncI2CAddress() const override { return device_.address(); }
  uint16_t asyncTargetRateHz() const override { return kTargetRateHz; }
  uint32_t asyncMaximumLowPriorityGapUs() const override { return 50000u; }
  bool asyncMuted() const override { return !sessionActive(); }
  bool asyncAcquire() override;

private:
  enum class DrainPassResult : uint8_t { Empty = 0, Data, Failure };

  bool configureFifo_();
  bool flushFifo_();
  bool drainAllAvailable_(
      uint8_t maximumPasses,
      bool readTemperature,
      bool requireEmpty = false);
  DrainPassResult drainOnePass_(bool readTemperature);
  bool recoverAcquisition_();
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

  uint8_t rawBuffer_[kRawBufferBytes] {};
  BMI270FifoParsedSample parsed_[kMaximumBatchSamples] {};

  uint32_t nextSequence_ = 0;
  uint16_t pendingStatus_ = 0;
  uint32_t pendingSkippedFrames_ = 0;
  uint32_t consecutiveDrainFailures_ = 0;
  uint16_t recoveryBackoffPolls_ = 0;
  bool havePreviousSensorTime_ = false;
  uint32_t previousSensorTime_ = 0;
  bool haveTemperature_ = false;
  int16_t lastTemperatureRaw_ = 0;
  uint64_t lastTemperatureHostUs_ = 0;
  uint64_t nextTemperatureReadUs_ = 0;
  bool initialized_ = false;
  bool registered_ = false;
};
