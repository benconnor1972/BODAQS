#pragma once
#include "RecordingFeatures.h"

#include <Arduino.h>
#include <stdint.h>
#include "SensorTypes.h"
#include "SpiTransferTiming.h"
#include "AdcConcentratedScan.h"

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
#if BODAQS_VARIABLE_ADC_SCAN
  // One shared owner, reset after retirement with the session statistics.
  struct AppointmentWait {
    uint32_t episodes=0,armAttempts=0,armFailures=0,elapsedBeforeArm=0;
    uint32_t earlyWakes=0,dueWakes=0,cancelledWakes=0;
    uint64_t totalUs=0;
    uint32_t maxUs=0;
  } scanAppointmentWait;
#endif
  #if BODAQS_ADC_ROW_PACING || BODAQS_ADC_CONTINUOUS_LATEST
  static constexpr uint8_t kMaxAdcs = 2; // Exact two-ADC bench; retain hot counters internally.
#else
  static constexpr uint8_t kMaxAdcs = 4;
#endif
  static constexpr uint8_t kMaxChannels = 4;
#if BODAQS_ADC_SPI_PHASE_TIMING
  struct SpiPhases {
    uint32_t completed = 0;
    uint32_t failed = 0;
    uint64_t totalUs[4] = {};
    uint32_t maxUs[4] = {};
    uint64_t failedWaitUs = 0;
  };
#endif

  struct AdcStats {
#if BODAQS_SCANNED_ADC_ACQUISITION
    bool concentratedScan=false;
    uint32_t scanStarts=0,scanMissedAppointments=0,scanMaximumLagTicks=0;
#if BODAQS_VARIABLE_ADC_SCAN
    uint32_t scanRowPeriodUs=0,scanMaximumLagUs=0;
#endif
    uint32_t scanReads=0,scanReadFailures=0,scanConfigFaults=0,scanWaitTimeouts=0;
#if BODAQS_ADC_SCAN_PIPELINE
    uint32_t scanCombinedCalls=0;
#if BODAQS_ADC_SCAN_ROW_PHASE
    TimingSummary scanRowPhaseUs;
#endif
#endif
#endif
#if BODAQS_ADC_CONTINUOUS_LATEST
    bool continuousRunning=false;
    uint32_t continuousPolls=0,continuousNoNew=0,continuousReads=0;
    uint32_t continuousConfigFaults=0,continuousReadFailures=0,continuousStalls=0,continuousStopFailures=0;
#endif
#if BODAQS_ADC_ROW_PACING
    uint32_t rowPacingStarts=0,rowPacingMissed=0,rowPacingOverruns=0;
    TimingSummary rowDispatchLagUs;
#endif
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
#if BODAQS_ADC_SPI_PHASE_TIMING
    SpiPhases setupSpi;
    SpiPhases readSpi;
#endif
    ExternalAdcChannelTimingStats channel[kMaxChannels];
  };

  AdcStats adc[kMaxAdcs];
};

struct StorageTimingStats {
  static constexpr uint8_t kMaxWriteStallEvents = 16;

  struct WriteStallEvent {
    uint32_t sampleId = 0;
    uint32_t durationUs = 0;
    uint32_t bytesAttempted = 0;
    uint16_t queueDepthRows = 0;
    uint16_t dataFrameCount = 0;
    uint8_t operation = 0;
  };

  TimingSummary rowWriteUs;
  TimingSummary drainLoopUs;
  uint32_t drainLoops = 0;
  uint32_t drainRows = 0;
  uint32_t writeStallThresholdUs = 0;
  uint32_t writeStallCount = 0;
  uint8_t writeStallStoredCount = 0;
  bool writeStallEventsTruncated = false;
  WriteStallEvent writeStallEvents[kMaxWriteStallEvents];
};

struct SensorTimingStats {
  static constexpr uint8_t kMaxSensors = MAX_SENSORS;

  struct SensorStats {
#if BODAQS_ADC_ROW_PACING
    uint32_t rowPacingStarts=0,rowPacingMissed=0,rowPacingOverruns=0;
#endif
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
#if BODAQS_ADC_ROW_PACING
    uint32_t rowPacingStarts=0,rowPacingMissed=0,rowPacingOverruns=0;
#endif
    bool present = false;
    bool running = false;
    uint8_t clientCount = 0;
    uint32_t hz = 0;
    uint16_t rollingLoadAveragePermille = 0;
    uint16_t rollingLoadMaximumPermille = 0;
    uint32_t rollingLoadWindows = 0;
    uint32_t recoveryAttempts = 0;
    uint32_t recoverySuccesses = 0;
    uint32_t recoveryFailures = 0;
    uint8_t lastRecoveryClockPulses = 0;
    bool lastRecoverySdaLowBefore = false;
    bool lastRecoverySclLowBefore = false;
    bool lastRecoverySdaLowAfter = false;
    bool lastRecoverySclLowAfter = false;
    TimingSummary acquireLoopUs;
  };

  struct ClientStats {
#if BODAQS_ADC_ROW_PACING
    uint32_t rowPacingStarts=0,rowPacingMissed=0,rowPacingOverruns=0;
#endif
    bool present = false;
    bool active = false;
    char name[16] = {0};
    char kind[24] = {0};
    uint8_t busIndex = 0;
    uint8_t address = 0;
    uint16_t targetRateHz = 0;
    uint32_t periodUs = 0;
    bool latencySensitive = false;
    uint32_t maximumServiceGapUs = 0;
    uint8_t priorityYieldLimit = 0;
    uint32_t acquireOk = 0;
    uint32_t acquireFail = 0;
    uint32_t rowUses = 0;
    uint32_t rowFresh = 0;
    uint32_t rowReused = 0;
    uint32_t rowNoSample = 0;
    uint32_t acquireFailStreakMax = 0;
    uint32_t serviceDeadlineMisses = 0;
    uint32_t missedServiceSlots = 0;
    uint32_t maximumStartLatenessUs = 0;
    uint32_t maximumSuccessfulServiceIntervalUs = 0;
    uint32_t priorityServiceCount = 0;
    uint32_t priorityDeferralCount = 0;
    uint32_t priorityDeferralMaximumUs = 0;
    uint32_t rowReuseStreakMax = 0;
    uint32_t rowNoSampleStreakMax = 0;
    TimingSummary acquireUs;
    TimingSummary rowAgeUs;
  };

  uint64_t sessionDurationUs = 0;
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
