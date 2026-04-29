#pragma once

#include <Arduino.h>
#include "ConfigManager.h"

struct LogMetadataContext {
  const char* csvPath = "";
  const char* sessionId = "";
  const char* startedAtLocal = "";
  const char* timezone = "";
  const char* generatedAtLocal = "";
  uint32_t rowCount = 0;
  uint16_t sampleRateHz = 0;
  bool humanReadableTime = false;
  LogFormat logFormat = LogFormat::BodaqsStandard;
};

bool LogMetadataWriter_build(const LogMetadataContext& ctx, String& out);
String LogMetadataWriter_metadataPathForCsv(const char* csvPath);
