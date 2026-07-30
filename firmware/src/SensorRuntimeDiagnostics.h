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
};

struct SensorRuntimeFailure {
  SensorRuntimeFailureStage stage = SensorRuntimeFailureStage::None;
  int16_t resultCode = 0;
  uint8_t expectedBytes = 0;
  uint8_t receivedBytes = 0;
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
};
