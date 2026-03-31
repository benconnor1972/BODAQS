#pragma once
#include <stdint.h>

class TwoWire;

namespace PowerManager {

  // Sleep; wake when ENTER (GPIO13) is pressed (active-LOW -> wake level 0).
  void sleepOnEnterEXT0();

  // CPU frequency tweaks during logging
  void setCpuFreqForLogging();
  void restoreCpuFreqAfterLogging();

  // ---------------- Fuel gauge (MAX17048) ----------------
  // Call once from setup() (optional). If you don't call it, the gauge will
  // still be lazily initialised on first poll/get.
  void fuelGaugeBegin(uint8_t i2c_addr = 0x36, TwoWire* wire = nullptr);

  // Call from loop() (optional). Polls at a safe interval internally.
  void fuelGaugeLoop();

  // Latest cached readings (updated by fuelGaugeLoop()).
  bool  fuelGaugeOk();
  float batterySocPercent();   // 0..100 (approx)
  float batteryVoltage();      // volts

} // namespace PowerManager
