#pragma once
#include <Arduino.h>
#include "ConfigManager.h"
#include "TimingStats.h"
#include "LoggingStartStatus.h"

class AnalogPotSensor; // fwd

namespace LoggingManager {
  enum class StopReason : uint8_t {
    None = 0,
    UserRequest,
    AnalogRailFault,
    SleepRequest,
    SdCardRemoved,
    StartFailure,
    Unspecified,
    StorageFailure,
    StorageUnresponsive,
  };

  struct StopContext {
    StopReason reason = StopReason::None;
    uint32_t uptimeMs = 0;
    const char* triggerEvent = "";
    bool sdDetectAvailable = false;
    bool sdCardDetected = true;
    bool analogRailFault = false;
  };

  enum class StartFailureHint : uint8_t {
    None = 0,
    RestartNow,
    ConfigConflict,
  };

  struct RuntimeStats {
    uint32_t samplerLateTicks = 0;
    uint32_t samplerLateMaxLagMs = 0;
    uint32_t samplerLateMaxLagUs = 0;
    uint32_t samplerWakeups = 0;
    uint32_t samplerLateOverTenPercent = 0;
    uint32_t missedSampleSlots = 0;
    TimingSummary samplerWakeLagUs;
    TimingSummary sampleOnceUs;
    TimingSummary sensorSampleUs;
    TimingSummary enqueueUs;
  };

  void begin(const LoggerConfig* cfg);
  // start() returns true only once acquisition has actually started.
  bool start();
  enum class StartResult : uint8_t { Failed, Pending, Started };
  StartResult requestStart();
  bool isStarting();
  void cancelStart();
  bool configurationLocked();
  void refreshConfigurationStatus();
  LoggingConfigIssue configurationIssue();
  const char* configurationDetail();
  StartFailureHint startFailureHint();
  void stop(
      StopReason reason = StopReason::Unspecified,
      const char* triggerEvent = "unspecified");
  const char* stopReasonName(StopReason reason);
  StopContext stopContext();
  bool isRunning();
  void loop();
  void completeStorageStart();
  void finishStorageStop();
  void setSampleRateHz(uint16_t hz);
  RuntimeStats runtimeStats();

  // Mark API (unchanged)
  void mark();
}

