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

  // Hook in the primary pot instance (used for current CSV columns pot1/pot2)
  void attachPrimaryPot(AnalogPotSensor* pot);

  // Mark API (unchanged)
  void mark();
}

