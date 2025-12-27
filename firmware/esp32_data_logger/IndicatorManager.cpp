#include "IndicatorManager.h"
#include "BoardProfile.h"   // provides board::BoardProfile definition
#include <Arduino.h>

bool  IndicatorManager::s_hasLed = false;
int8_t IndicatorManager::s_ledPin = -1;
bool  IndicatorManager::s_ledActiveHigh = true;

void IndicatorManager::begin(const board::BoardProfile& bp) {
  const auto& ind = bp.indicators;

  s_hasLed = ind.has_led && (ind.led_pin >= 0);
  s_ledPin = ind.led_pin;
  s_ledActiveHigh = ind.led_active_high;

  if (!s_hasLed) return;

  pinMode(s_ledPin, OUTPUT);
  ledOff();
}

bool IndicatorManager::hasLed() {
  return s_hasLed;
}

void IndicatorManager::ledOn() {
  if (!s_hasLed) return;
  digitalWrite(s_ledPin, s_ledActiveHigh ? HIGH : LOW);
}

void IndicatorManager::ledOff() {
  if (!s_hasLed) return;
  digitalWrite(s_ledPin, s_ledActiveHigh ? LOW : HIGH);
}
