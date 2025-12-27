#pragma once

#include <stdint.h>

// Forward declaration to avoid heavy includes
struct BoardProfile;

class IndicatorManager {
public:
  // Must be called once after BoardProfile is known
  static void begin(const BoardProfile& bp);

  // Simple handlers (safe no-ops if LED not present)
  static void ledOn();
  static void ledOff();

  // Optional helper
  static bool hasLed();

private:
  static bool s_hasLed;
  static int8_t s_ledPin;
  static bool s_ledActiveHigh;
};
