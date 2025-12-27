#pragma once
#include <Arduino.h>
#include "ConfigManager.h"

class AnalogPotSensor; // fwd

namespace LoggingManager {
  void begin(const LoggerConfig* cfg);
  bool start();
  void stop();
  bool isRunning();
  void loop();
  void setSampleRateHz(uint16_t hz);

  // Mark API (unchanged)
  void mark();
}

