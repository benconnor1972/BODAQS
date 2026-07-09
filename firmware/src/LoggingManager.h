#pragma once
#include <Arduino.h>
#include "ConfigManager.h"
#include "TimingStats.h"

class AnalogPotSensor; // fwd

namespace LoggingManager {
  struct RuntimeStats {
    uint32_t samplerLateTicks = 0;
    uint32_t samplerLateMaxLagMs = 0;
    uint32_t missedSampleSlots = 0;
    TimingSummary sampleOnceUs;
    TimingSummary sensorSampleUs;
    TimingSummary enqueueUs;
  };

  void begin(const LoggerConfig* cfg);
  bool start();
  void stop();
  bool isRunning();
  void loop();
  void setSampleRateHz(uint16_t hz);
  RuntimeStats runtimeStats();

  // Mark API (unchanged)
  void mark();
}

