#pragma once

#include <Arduino.h>
#include <stdint.h>
#include "SensorTypes.h"

#ifndef BODAQS_TIMING_INSTRUMENTATION
#define BODAQS_TIMING_INSTRUMENTATION 1
#endif

#if BODAQS_TIMING_INSTRUMENTATION
static constexpr bool kBodaqsTimingInstrumentationEnabled = true;
#else
static constexpr bool kBodaqsTimingInstrumentationEnabled = false;
#endif

struct TimingSummary {
  uint32_t count = 0;
  uint32_t minUs = 0;
  uint32_t maxUs = 0;
  uint64_t totalUs = 0;
  uint32_t bucketLt250 = 0;
  uint32_t bucket250To500 = 0;
  uint32_t bucket500To1000 = 0;
  uint32_t bucket1000To1500 = 0;
  uint32_t bucket1500To2000 = 0;
  uint32_t bucketGe2000 = 0;
};

struct ExternalAdcChannelTimingStats {
  TimingSummary totalUs;
  TimingSummary waitUs;
  TimingSummary rowAgeUs;
  uint32_t acquireOk = 0;
  uint32_t acquireFail = 0;
  uint32_t rowUses = 0;
  uint32_t rowFresh = 0;
  uint32_t rowReused = 0;
  uint32_t rowNoSample = 0;
};

struct ExternalAdcTimingStats {
  static constexpr uint8_t kMaxAdcs = 4;
  static constexpr uint8_t kMaxChannels = 4;

  struct AdcStats {
    bool present = false;
    bool asyncRunning = false;
    uint8_t activeChannels = 0;
    uint16_t configuredSps = 0;
    TimingSummary scanUs;
    TimingSummary asyncLoopUs;
    TimingSummary configUs;
    TimingSummary startUs;
    TimingSummary waitUs;
    TimingSummary readUs;
    uint32_t waitTimeouts = 0;
    uint32_t drdyAlreadyReady = 0;
    ExternalAdcChannelTimingStats channel[kMaxChannels];
  };

  AdcStats adc[kMaxAdcs];
};

struct StorageTimingStats {
  TimingSummary rowWriteUs;
  TimingSummary drainLoopUs;
  uint32_t drainLoops = 0;
  uint32_t drainRows = 0;
};

struct SensorTimingStats {
  static constexpr uint8_t kMaxSensors = MAX_SENSORS;

  struct SensorStats {
    bool present = false;
    bool muted = false;
    bool synchronous = true;
    char name[16] = {0};
    char label[24] = {0};
    uint8_t columnCount = 0;
    TimingSummary sampleUs;
  };

  uint8_t sensorCount = 0;
  SensorStats sensor[kMaxSensors];
};

struct I2CBusSchedulerTimingStats {
  static constexpr uint8_t kMaxBuses = 2;
  static constexpr uint8_t kMaxClients = MAX_SENSORS;

  struct BusStats {
    bool present = false;
    bool running = false;
    uint8_t clientCount = 0;
    uint32_t hz = 0;
    TimingSummary acquireLoopUs;
  };

  struct ClientStats {
    bool present = false;
    bool active = false;
    char name[16] = {0};
    char kind[24] = {0};
    uint8_t busIndex = 0;
    uint8_t address = 0;
    uint16_t targetRateHz = 0;
    uint32_t periodUs = 0;
    uint32_t acquireOk = 0;
    uint32_t acquireFail = 0;
    uint32_t rowUses = 0;
    uint32_t rowFresh = 0;
    uint32_t rowReused = 0;
    uint32_t rowNoSample = 0;
    uint32_t acquireFailStreakMax = 0;
    uint32_t rowReuseStreakMax = 0;
    uint32_t rowNoSampleStreakMax = 0;
    TimingSummary acquireUs;
    TimingSummary rowAgeUs;
  };

  uint8_t clientCount = 0;
  BusStats bus[kMaxBuses];
  ClientStats client[kMaxClients];
};

static inline void TimingStats_reset(TimingSummary& s) {
  s = TimingSummary{};
}

static inline void TimingStats_record(TimingSummary& s, uint32_t us) {
#if BODAQS_TIMING_INSTRUMENTATION
  if (s.count == 0 || us < s.minUs) s.minUs = us;
  if (us > s.maxUs) s.maxUs = us;
  s.totalUs += us;
  ++s.count;

  if (us < 250UL) {
    ++s.bucketLt250;
  } else if (us < 500UL) {
    ++s.bucket250To500;
  } else if (us < 1000UL) {
    ++s.bucket500To1000;
  } else if (us < 1500UL) {
    ++s.bucket1000To1500;
  } else if (us < 2000UL) {
    ++s.bucket1500To2000;
  } else {
    ++s.bucketGe2000;
  }
#else
  (void)s;
  (void)us;
#endif
}

static inline float TimingStats_avgUs(const TimingSummary& s) {
  return s.count ? (float)((double)s.totalUs / (double)s.count) : 0.0f;
}
