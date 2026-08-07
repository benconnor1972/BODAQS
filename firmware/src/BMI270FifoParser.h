#pragma once

#include <stddef.h>
#include <stdint.h>

#include "BMI270ImuSample.h"

struct BMI270FifoParsedSample {
  int16_t accelX = 0;
  int16_t accelY = 0;
  int16_t accelZ = 0;
  int16_t gyroX = 0;
  int16_t gyroY = 0;
  int16_t gyroZ = 0;
  uint16_t statusBefore = 0;
  uint32_t skippedFramesBefore = 0;
  uint32_t sensorTime = 0;
};

struct BMI270FifoParseResult {
  size_t samplesWritten = 0;
  uint32_t sampleFrames = 0;
  uint32_t outputDrops = 0;
  uint32_t skippedFrames = 0;
  uint32_t skipControlFrames = 0;
  uint32_t unpairedFrames = 0;
  uint32_t inputConfigFrames = 0;
  uint32_t invalidHeaders = 0;
  uint32_t partialFrames = 0;
  uint32_t sensorTimeFrames = 0;
  uint32_t sensorTime = 0;
  size_t sensorTimeAnchorByteOffset = 0;
  bool sensorTimePresent = false;
  bool overreadSeen = false;
  uint16_t pendingStatus = 0;
  uint32_t pendingSkippedFrames = 0;
};

namespace BMI270FifoParser {

inline constexpr size_t kCombinedFrameBytes = 13;
inline constexpr uint32_t kSensorTimeMask = 0x00FFFFFFu;
inline constexpr uint32_t kTicksPerSample200Hz = 128u;

BMI270FifoParseResult parseHeaderMode(
    const uint8_t* data,
    size_t length,
    BMI270FifoParsedSample* output,
    size_t outputCapacity,
    uint16_t initialStatus = 0,
    uint32_t initialSkippedFrames = 0);

bool assignSensorTimes200Hz(
    BMI270FifoParsedSample* parsed,
    size_t count,
    bool anchorPresent,
    uint32_t anchorSensorTime,
    bool& havePreviousSensorTime,
    uint32_t& previousSensorTime);

} // namespace BMI270FifoParser
