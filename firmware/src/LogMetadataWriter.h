#pragma once

#include <Arduino.h>
#include "ConfigManager.h"

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
};

bool LogMetadataWriter_build(const LogMetadataContext& ctx, String& out);
String LogMetadataWriter_metadataPathForCsv(const char* csvPath);
