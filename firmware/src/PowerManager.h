#pragma once
#include <stdint.h>

class TwoWire;
namespace board { struct BoardProfile; }

namespace PowerManager {

  void begin(const board::BoardProfile& board);

  // Sleep; wake when the board-profile `nav_enter` button is pressed.
  void sleepOnEnterEXT0();
  void noteActivity();
  void loop();

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
  bool  batteryLow();

  // ---------------- Analog rail control ----------------
  void setAnalogRailEnabled(bool enabled);
  bool analogRailEnabled();
  bool canStartLogging();

} // namespace PowerManager
