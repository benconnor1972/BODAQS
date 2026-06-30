#pragma once

#include <Arduino.h>
#include "ConfigManager.h"
#include "TimingStats.h"

namespace board { struct BoardProfile; }

struct LogMetadataContext {
  const char* csvPath = "";
  const char* sessionId = "";
  const char* startedAtUtc = "";
  const char* startedAtLocal = "";
  const char* timezone = "";
  const char* generatedAtLocal = "";
  uint32_t rowCount = 0;
  uint16_t sampleRateHz = 0;
  bool humanReadableTime = false;
  LogFormat logFormat = LogFormat::BodaqsStandard;
  uint32_t samplesDropped = 0;
  uint16_t queueMax = 0;
  uint16_t queueDepth = 0;
  uint32_t flushCount = 0;
  uint32_t flushMaxMs = 0;
  uint64_t flushTotalMs = 0;
  uint32_t bufferSize = 0;
  uint32_t samplerLateTicks = 0;
  uint32_t samplerLateMaxLagMs = 0;
  uint32_t missedSampleSlots = 0;
  const TimingSummary* sampleOnceUs = nullptr;
  const TimingSummary* sensorSampleUs = nullptr;
  const TimingSummary* enqueueUs = nullptr;
  const StorageTimingStats* storageTiming = nullptr;
  const ExternalAdcTimingStats* externalAdcTiming = nullptr;
  const SensorTimingStats* sensorTiming = nullptr;
  const I2CBusSchedulerTimingStats* i2cSchedulerTiming = nullptr;
  const board::BoardProfile* boardProfile = nullptr;
};

bool LogMetadataWriter_build(const LogMetadataContext& ctx, String& out);
String LogMetadataWriter_metadataPathForCsv(const char* csvPath);
