#pragma once

#include <stdint.h>

enum class SensorRuntimeEventType : uint8_t {
  LoggingStart = 1,
  SchedulerStart = 2,
  ReadFailureStarted = 3,
  ReadRecovered = 4,
  ConfigWriteFailed = 5,
  ConfigWriteRecovered = 6,
  SchedulerStop = 7,
  LoggingStop = 8,
};

enum class SensorRuntimeFailureStage : uint8_t {
  None = 0,
  BusUnavailable = 1,
  BusLock = 2,
  Probe = 3,
  RegisterAddress = 4,
  RequestBytes = 5,
  ReadByte = 6,
  WriteRegister = 7,
  InvalidArgument = 8,
  WritePayload = 9,
  EndTransmission = 10,
};

struct SensorRuntimeFailure {
  SensorRuntimeFailureStage stage = SensorRuntimeFailureStage::None;
  int16_t resultCode = 0;
  uint8_t registerAddress = 0;
  uint16_t expectedBytes = 0;
  uint16_t receivedBytes = 0;
};

struct SensorRuntimeEvent {
  uint32_t uptimeMs = 0;
  uint32_t acquisitionSeq = 0;
  uint32_t rawReadFailures = 0;
  uint16_t raw = 0;
  uint16_t conf = 0;
  SensorRuntimeEventType type = SensorRuntimeEventType::LoggingStart;
  SensorRuntimeFailure failure;
  bool haveSample = false;
  bool readOk = false;
  bool reused = false;
  bool analogRailEnabled = false;
  bool analogRailFault = false;
};

struct SensorRuntimeDiagnostics {
  static constexpr uint8_t kMaxEvents = 32;

  bool present = false;
  char sensorName[16] = {0};
  char kind[24] = {0};
  uint8_t busIndex = 0;
  uint8_t address = 0;

  uint32_t beginCount = 0;
  uint32_t lastBeginUptimeMs = 0;
  bool initialProbeOk = false;
  bool configWriteAttempted = false;
  bool configWriteOk = false;
  bool configReadAttempted = false;
  bool configReadOk = false;
  uint16_t configBefore = 0;
  uint16_t configAfter = 0;
  SensorRuntimeFailure initializationFailure;

  uint32_t rawReadFailures = 0;
  uint32_t diagnosticReadFailures = 0;
  uint32_t readFailureStreakMax = 0;
  uint32_t readRecoveries = 0;
  bool haveLastGoodRaw = false;
  bool lastReadOk = false;
  bool lastReadReused = false;
  uint16_t lastGoodRaw = 0;
  uint16_t lastConf = 0;
  SensorRuntimeFailure lastFailure;

  uint8_t eventCount = 0;
  uint32_t eventsTotal = 0;
  uint32_t eventsDropped = 0;
  SensorRuntimeEvent events[kMaxEvents];

  bool hasImuSession = false;
  uint64_t imuDrainCalls = 0;
  uint64_t imuDrainPasses = 0;
  uint64_t imuEmptyPasses = 0;
  uint64_t imuDrainPassLimitHits = 0;
  uint64_t imuFifoBytesRead = 0;
  uint64_t imuFifoFramesParsed = 0;
  uint64_t imuSensorTimeFrames = 0;
  uint64_t imuMissingSensorTimeBatches = 0;
  uint64_t imuSkipControlFrames = 0;
  uint64_t imuFifoOverflowEvents = 0;
  uint64_t imuFifoFullObservations = 0;
  uint64_t imuHardwareSkippedFrames = 0;
  uint64_t imuUnpairedFrames = 0;
  uint64_t imuInputConfigFrames = 0;
  uint64_t imuInvalidHeaders = 0;
  uint64_t imuPartialFrames = 0;
  uint64_t imuOverreadFrames = 0;
  uint64_t imuParserOutputDrops = 0;
  uint64_t imuSamplesEnqueued = 0;
  uint64_t imuSamplesEmitted = 0;
  uint64_t imuQueueDrops = 0;
  uint64_t imuPreSessionQueueDiscards = 0;
  uint64_t imuExplicitQueueDiscards = 0;
  uint64_t imuTemperatureReads = 0;
  uint64_t imuTemperatureReadFailures = 0;
  uint64_t imuOperationalValidationAttempts = 0;
  uint64_t imuOperationalValidationFailures = 0;
  uint64_t imuSessionStartValidationAttempts = 0;
  uint64_t imuSessionStartValidationFailures = 0;
  uint64_t imuNoProgressEvents = 0;
  uint64_t imuFifoFlushes = 0;
  uint64_t imuFifoFlushFailures = 0;
  uint64_t imuStopDrainAttempts = 0;
  uint64_t imuStopDrainFailures = 0;
  uint64_t imuI2cOperations = 0;
  uint64_t imuI2cFailures = 0;
  uint64_t imuI2cRecoveries = 0;
  uint64_t imuI2cBusLockAttempts = 0;
  uint64_t imuI2cBusLockTimeouts = 0;
  uint64_t imuI2cBusLockWaitTotalUs = 0;
  uint32_t imuI2cFailureStageCounts[9] {};
  uint64_t imuRecoveryAttempts = 0;
  uint64_t imuRecoverySuccesses = 0;
  uint64_t imuRecoveryFailures = 0;
  uint64_t imuTerminalFaultEvents = 0;
  uint16_t imuQueueCapacity = 0;
  uint16_t imuQueueHighWater = 0;
  uint16_t imuFinalQueueDepth = 0;
  uint16_t imuMaximumFifoBytesObserved = 0;
  uint32_t imuMaximumDrainDurationUs = 0;
  uint32_t imuMaximumDrainFailureStreak = 0;
  uint32_t imuNoProgressTimeoutUs = 0;
  uint32_t imuMaximumNoProgressUs = 0;
  uint32_t imuLastValidationIssues = 0;
  uint32_t imuI2cMaximumFailureStreak = 0;
  uint32_t imuI2cBusLockWaitMaximumUs = 0;
  uint16_t imuLastValidationFifoConfig = 0;
  uint16_t imuLastValidationFifoWatermark = 0;
  uint8_t imuLastValidationChipId = 0;
  uint8_t imuLastValidationInternalStatus = 0;
  uint8_t imuLastValidationPowerControl = 0;
  uint8_t imuLastValidationAccelDownsample = 0;
  uint8_t imuLastValidationGyroDownsample = 0;
  uint8_t imuLastValidationAccelFiltered = 0;
  uint8_t imuLastValidationGyroFiltered = 0;
  uint8_t imuConsecutiveRecoveryFailures = 0;
  uint8_t imuRecoveryAttemptsWithoutProgress = 0;
  uint8_t imuLastRecoveryReason = 0;
  int8_t imuLastValidationApiResult = 0;
  bool imuTerminalFault = false;
  bool imuCounterSaturated = false;
};
