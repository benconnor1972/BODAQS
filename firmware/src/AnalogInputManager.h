#pragma once

#include <Arduino.h>
#include <stdint.h>
#include "BoardProfile.h"

struct LoggerConfig;

namespace AnalogInputManager {

  void begin(const board::BoardProfile& board);

  bool available(uint8_t ain);
  bool inputIsExternal(uint8_t ain);
  int8_t pinForAin(uint8_t ain);

  bool readCounts(uint8_t ain, int32_t& outCounts);

  // Scans configured, unmuted analog sensors and selects an effective logging
  // rate that each external ADC can actually service.
  uint16_t configureFromConfig(const LoggerConfig& cfg, uint16_t requestedHz);
  uint16_t effectiveSampleRateHz();
  uint16_t requestedSampleRateHz();
  uint8_t activeChannelCount(uint8_t externalAdcIndex);
  uint16_t configuredDataRateSps(uint8_t externalAdcIndex);

  // Called once around each logger sample so external ADC channels can be
  // converted once and then reused by all sensor columns in that row.
  void beginSample();
  void endSample();

} // namespace AnalogInputManager
