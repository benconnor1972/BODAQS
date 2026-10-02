#pragma once
#include <Arduino.h>
#include "ConfigManager.h"
#include "TimingStats.h"

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
    UseBdqV2,
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
  bool start();
  StartFailureHint startFailureHint();
  void stop(
      StopReason reason = StopReason::Unspecified,
      const char* triggerEvent = "unspecified");
  const char* stopReasonName(StopReason reason);
  StopContext stopContext();
  bool isRunning();
  void loop();
  void setSampleRateHz(uint16_t hz);
  RuntimeStats runtimeStats();

  // Mark API (unchanged)
  void mark();
}

