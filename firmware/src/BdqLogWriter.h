#pragma once

#include <Arduino.h>
#include <FS.h>
#include "ConfigManager.h"

struct BdqLogSessionInfo {
  const LoggerConfig* config = nullptr;
  const char* logPath = "";
  const char* sessionId = "";
  const char* startedAtUtc = "";
  const char* startedAtLocal = "";
  const char* timezone = "";
  uint64_t createdUnixUs = 0;
  uint16_t sampleRateHz = 0;
  uint32_t samplePeriodUs = 0;
  uint32_t targetChunkBytes = 8192;
};

struct BdqLogEndInfo {
  uint32_t samplesDropped = 0;
  uint16_t queueMax = 0;
  uint16_t queueDepth = 0;
  uint32_t flushCount = 0;
  uint32_t flushMaxMs = 0;
  uint64_t flushTotalMs = 0;
};

namespace BdqLogWriter {
  bool begin(File& file, const BdqLogSessionInfo& info);
  bool writeSample(uint32_t sampleId, uint64_t tsMs, const float* values, uint16_t nValues, bool mark);
  bool flushDataChunk();
  void flushFile();
  bool end(const BdqLogEndInfo& info);
  void reset();

  bool isActive();
  uint16_t frameSizeBytes();
  uint16_t pendingFrameCount();
  uint32_t samplesWritten();
  uint32_t dataChunksWritten();
}
