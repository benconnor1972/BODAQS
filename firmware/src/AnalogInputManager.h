#pragma once

#include <Arduino.h>
#include <stdint.h>
#include "BoardProfile.h"
#include "TimingStats.h"

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
  void resetTimingStats();
  const ExternalAdcTimingStats& timingStats();
  void onLoggingStart();
  void onLoggingStop();

#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  struct ProbeRow {
    bool valid = false;
    bool fresh = false;
    uint32_t sequence = 0;
    uint64_t afterReadUs = 0;
  };
  struct ProbeDrdy {
    uint32_t observed = 0, paired = 0, missing = 0, extra = 0, unpaired = 0;
    TimingSummary toReadStart, toReadEnd;
  };
  struct ProbeDrdyStats { ProbeDrdy adc[board::BOARD_MAX_EXTERNAL_ADCS]; };
  bool probeWorkersRunning();
  bool probeWorkersStopped();
  // Last readCounts cache observation, without consuming the conversion again.
  ProbeRow probeLastRow(uint8_t ain);
  // Only returns counters after complete worker shutdown; empty otherwise.
  ExternalAdcTimingStats probeTimingSnapshot();
  ProbeDrdyStats probeDrdySnapshot();
#endif

  // Called once around each logger sample so external ADC channels can be
  // converted once and then reused by all sensor columns in that row.
  void beginSample();
  void endSample();

} // namespace AnalogInputManager
