#pragma once

#include <Arduino.h>

struct LogMetadataContext {
  const char* csvPath = "";
  const char* sessionId = "";
  const char* startedAtLocal = "";
  const char* timezone = "";
  const char* generatedAtLocal = "";
  uint32_t rowCount = 0;
  uint16_t sampleRateHz = 0;
  bool humanReadableTime = false;
};

bool LogMetadataWriter_build(const LogMetadataContext& ctx, String& out);
String LogMetadataWriter_metadataPathForCsv(const char* csvPath);
