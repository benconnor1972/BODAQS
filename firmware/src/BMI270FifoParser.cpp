#include "BMI270FifoParser.h"

namespace {

constexpr uint8_t kHeaderMask = 0xFC;
constexpr uint8_t kAccelHeader = 0x84;
constexpr uint8_t kGyroHeader = 0x88;
constexpr uint8_t kGyroAccelHeader = 0x8C;
constexpr uint8_t kSensorTimeHeader = 0x44;
constexpr uint8_t kSkipHeader = 0x40;
constexpr uint8_t kInputConfigHeader = 0x48;
constexpr uint8_t kOverreadHeader = 0x80;

int16_t readI16_(const uint8_t* data) {
  const uint16_t raw = static_cast<uint16_t>(data[0]) |
                       (static_cast<uint16_t>(data[1]) << 8);
  return static_cast<int16_t>(raw);
}

uint32_t readU24_(const uint8_t* data) {
  return static_cast<uint32_t>(data[0]) |
         (static_cast<uint32_t>(data[1]) << 8) |
         (static_cast<uint32_t>(data[2]) << 16);
}

bool require_(size_t index, size_t bytes, size_t length) {
  return index <= length && bytes <= length - index;
}

} // namespace

BMI270FifoParseResult BMI270FifoParser::parseHeaderMode(
    const uint8_t* data,
    size_t length,
    BMI270FifoParsedSample* output,
    size_t outputCapacity,
    uint16_t initialStatus,
    uint32_t initialSkippedFrames) {
  BMI270FifoParseResult result;
  result.pendingStatus = initialStatus;
  result.pendingSkippedFrames = initialSkippedFrames;
  if (!data && length) {
    result.invalidHeaders = 1;
    result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                            BMI270ImuStatus::kTimingDegraded;
    return result;
  }

  size_t index = 0;
  while (index < length) {
    const uint8_t header = data[index++] & kHeaderMask;
    switch (header) {
      case kGyroAccelHeader: {
        if (!require_(index, 12, length)) {
          ++result.partialFrames;
          result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                  BMI270ImuStatus::kTimingDegraded;
          index = length;
          break;
        }

        ++result.sampleFrames;
        if (output && result.samplesWritten < outputCapacity) {
          BMI270FifoParsedSample& sample = output[result.samplesWritten++];
          // Bosch header mode stores gyro first, then accelerometer.
          sample.gyroX = readI16_(&data[index]);
          sample.gyroY = readI16_(&data[index + 2]);
          sample.gyroZ = readI16_(&data[index + 4]);
          sample.accelX = readI16_(&data[index + 6]);
          sample.accelY = readI16_(&data[index + 8]);
          sample.accelZ = readI16_(&data[index + 10]);
          sample.statusBefore = result.pendingStatus;
          sample.skippedFramesBefore = result.pendingSkippedFrames;
          result.pendingStatus = 0;
          result.pendingSkippedFrames = 0;
        } else {
          ++result.outputDrops;
          result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                  BMI270ImuStatus::kQueueDropBefore;
        }
        index += 12;
        break;
      }

      case kAccelHeader:
      case kGyroHeader:
        if (!require_(index, 6, length)) {
          ++result.partialFrames;
          index = length;
        } else {
          index += 6;
        }
        ++result.unpairedFrames;
        result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                BMI270ImuStatus::kTimingDegraded;
        break;

      case kSensorTimeHeader:
        result.sensorTimeAnchorByteOffset = index - 1;
        if (!require_(index, 3, length)) {
          ++result.partialFrames;
          result.pendingStatus |= BMI270ImuStatus::kTimingDegraded;
          index = length;
          break;
        }
        result.sensorTime = readU24_(&data[index]);
        result.sensorTimePresent = true;
        ++result.sensorTimeFrames;
        index += 3;
        break;

      case kSkipHeader:
        if (!require_(index, 1, length)) {
          ++result.partialFrames;
          result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                  BMI270ImuStatus::kTimingDegraded;
          index = length;
          break;
        }
        ++result.skipControlFrames;
        result.skippedFrames += data[index];
        result.pendingSkippedFrames += data[index];
        result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore;
        ++index;
        break;

      case kInputConfigHeader:
        if (!require_(index, 4, length)) {
          ++result.partialFrames;
          index = length;
        } else {
          index += 4;
        }
        ++result.inputConfigFrames;
        result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                BMI270ImuStatus::kTimingDegraded;
        break;

      case kOverreadHeader:
        result.overreadSeen = true;
        index = length;
        break;

      default:
        ++result.invalidHeaders;
        result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                BMI270ImuStatus::kTimingDegraded;
        index = length;
        break;
    }
  }

  return result;
}

bool BMI270FifoParser::assignSensorTimes200Hz(
    BMI270FifoParsedSample* parsed,
    size_t count,
    bool anchorPresent,
    uint32_t anchorSensorTime,
    bool& havePreviousSensorTime,
    uint32_t& previousSensorTime) {
  if (!parsed || count == 0) return false;

  if (anchorPresent) {
    const bool hadPreviousSensorTime = havePreviousSensorTime;
    const uint32_t priorSensorTime = previousSensorTime;
    uint32_t cursor =
        (anchorSensorTime & kSensorTimeMask) & ~(kTicksPerSample200Hz - 1u);
    for (size_t reverse = count; reverse > 0; --reverse) {
      const size_t index = reverse - 1;
      parsed[index].sensorTime = cursor;
      parsed[index].statusBefore |= BMI270ImuStatus::kSensorTimeEstimated;
      const uint32_t intervals = 1u + parsed[index].skippedFramesBefore;
      cursor = (cursor - intervals * kTicksPerSample200Hz) & kSensorTimeMask;
    }
    if (hadPreviousSensorTime) {
      const uint32_t expected =
          (priorSensorTime +
           (1u + parsed[0].skippedFramesBefore) * kTicksPerSample200Hz) &
          kSensorTimeMask;
      if (parsed[0].sensorTime != expected) {
        parsed[0].statusBefore |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                  BMI270ImuStatus::kTimingDegraded;
        parsed[0].sensorTimeDiscontinuityBefore = true;
      }
    }
    previousSensorTime = parsed[count - 1].sensorTime;
    havePreviousSensorTime = true;
    return true;
  }

  if (!havePreviousSensorTime) {
    for (size_t index = 0; index < count; ++index) {
      parsed[index].sensorTime = 0;
      parsed[index].statusBefore |= BMI270ImuStatus::kSensorTimeEstimated |
                                    BMI270ImuStatus::kTimingDegraded;
    }
    return false;
  }

  for (size_t index = 0; index < count; ++index) {
    const uint32_t intervals = 1u + parsed[index].skippedFramesBefore;
    previousSensorTime =
        (previousSensorTime + intervals * kTicksPerSample200Hz) & kSensorTimeMask;
    parsed[index].sensorTime = previousSensorTime;
    parsed[index].statusBefore |= BMI270ImuStatus::kSensorTimeEstimated |
                                  BMI270ImuStatus::kTimingDegraded;
  }
  return true;
}
