#pragma once
#include <stdint.h>

namespace board { struct BoardProfile; }   // <-- forward declare in correct namespace

class IndicatorManager {
public:
  static void begin(const board::BoardProfile& bp);

  static void ledOn();
  static void ledOff();
  static bool hasLed();

private:
  static bool  s_hasLed;
  static int8_t s_ledPin;
  static bool  s_ledActiveHigh;
};
