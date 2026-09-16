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
    uint32_t initialSkippedFrames,
    bool retainUnpairedFrames) {
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
        ++result.accelFrames;
        ++result.gyroFrames;
        ++result.combinedFrames;
        if (output && result.samplesWritten < outputCapacity) {
          BMI270FifoParsedSample& sample = output[result.samplesWritten++];
          sample = BMI270FifoParsedSample{};
          // Bosch header mode stores gyro first, then accelerometer.
          sample.gyroX = readI16_(&data[index]);
          sample.gyroY = readI16_(&data[index + 2]);
          sample.gyroZ = readI16_(&data[index + 4]);
          sample.accelX = readI16_(&data[index + 6]);
          sample.accelY = readI16_(&data[index + 8]);
          sample.accelZ = readI16_(&data[index + 10]);
          sample.accelValid = true;
          sample.gyroValid = true;
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
      case kGyroHeader: {
        if (!require_(index, 6, length)) {
          ++result.partialFrames;
          result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                  BMI270ImuStatus::kTimingDegraded;
          index = length;
        } else {
          if (retainUnpairedFrames) ++result.sampleFrames;
          if (header == kAccelHeader) {
            ++result.accelFrames;
          } else {
            ++result.gyroFrames;
          }
          if (retainUnpairedFrames && output &&
              result.samplesWritten < outputCapacity) {
            BMI270FifoParsedSample& sample = output[result.samplesWritten++];
            sample = BMI270FifoParsedSample{};
            if (header == kAccelHeader) {
              sample.accelX = readI16_(&data[index]);
              sample.accelY = readI16_(&data[index + 2]);
              sample.accelZ = readI16_(&data[index + 4]);
              sample.accelValid = true;
            } else {
              sample.gyroX = readI16_(&data[index]);
              sample.gyroY = readI16_(&data[index + 2]);
              sample.gyroZ = readI16_(&data[index + 4]);
              sample.gyroValid = true;
            }
            sample.statusBefore = result.pendingStatus;
            sample.skippedFramesBefore = result.pendingSkippedFrames;
            result.pendingStatus = 0;
            result.pendingSkippedFrames = 0;
          } else if (retainUnpairedFrames) {
            ++result.outputDrops;
            result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                    BMI270ImuStatus::kQueueDropBefore;
          }
          index += 6;
        }
        if (!retainUnpairedFrames) ++result.unpairedFrames;
        if (!retainUnpairedFrames) {
          result.pendingStatus |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                  BMI270ImuStatus::kTimingDegraded;
        }
        break;
      }

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

bool BMI270FifoParser::assignSensorTimesMixed(
    BMI270FifoParsedSample* parsed,
    size_t count,
    bool anchorPresent,
    uint32_t anchorSensorTime,
    uint32_t accelTicksPerSample,
    uint32_t gyroTicksPerSample,
    bool& havePreviousAccelSensorTime,
    uint32_t& previousAccelSensorTime,
    bool& havePreviousGyroSensorTime,
    uint32_t& previousGyroSensorTime) {
  if (!parsed || count == 0 || accelTicksPerSample == 0 ||
      gyroTicksPerSample == 0 ||
      (accelTicksPerSample & (accelTicksPerSample - 1u)) != 0 ||
      (gyroTicksPerSample & (gyroTicksPerSample - 1u)) != 0) {
    return false;
  }

  const bool hadPreviousAccel = havePreviousAccelSensorTime;
  const bool hadPreviousGyro = havePreviousGyroSensorTime;
  const uint32_t priorAccel = previousAccelSensorTime;
  const uint32_t priorGyro = previousGyroSensorTime;
  uint32_t accelCursor = previousAccelSensorTime;

  if (anchorPresent) {
    const uint32_t anchor = anchorSensorTime & kSensorTimeMask;
    accelCursor = anchor & ~(accelTicksPerSample - 1u);
    for (size_t reverse = count; reverse > 0; --reverse) {
      BMI270FifoParsedSample& sample = parsed[reverse - 1];
      if (sample.accelValid) {
        sample.sensorTime = accelCursor;
        accelCursor = (accelCursor - accelTicksPerSample) & kSensorTimeMask;
      }
      sample.statusBefore |= BMI270ImuStatus::kSensorTimeEstimated;
      if (sample.skippedFramesBefore != 0) {
        sample.statusBefore |= BMI270ImuStatus::kTimingDegraded;
        if (sample.accelValid) sample.accelTimingDegraded = true;
        if (sample.gyroValid) sample.gyroTimingDegraded = true;
      }
    }
  } else if (!hadPreviousAccel && !hadPreviousGyro) {
    for (size_t index = 0; index < count; ++index) {
      parsed[index].sensorTime = 0;
      parsed[index].statusBefore |= BMI270ImuStatus::kSensorTimeEstimated |
                                    BMI270ImuStatus::kTimingDegraded;
      if (parsed[index].accelValid) parsed[index].accelTimingDegraded = true;
      if (parsed[index].gyroValid) parsed[index].gyroTimingDegraded = true;
    }
    return false;
  } else {
    for (size_t index = 0; index < count; ++index) {
      BMI270FifoParsedSample& sample = parsed[index];
      if (sample.accelValid && havePreviousAccelSensorTime) {
        accelCursor = (accelCursor + accelTicksPerSample) & kSensorTimeMask;
        sample.sensorTime = accelCursor;
      }
      sample.statusBefore |= BMI270ImuStatus::kSensorTimeEstimated |
                             BMI270ImuStatus::kTimingDegraded;
      if (sample.accelValid) sample.accelTimingDegraded = true;
      if (sample.gyroValid) sample.gyroTimingDegraded = true;
    }
  }

  // Accel is the fastest clock and therefore fixes the chronological grid.
  // A sparse gyro-only frame is placed on the nearest accel slot with the
  // gyro phase. This avoids incorrectly assigning an old gyro frame to the
  // newest anchor when newer accel-only frames follow it in the FIFO.
  const uint32_t gyroPhaseMask = gyroTicksPerSample - 1u;
  uint32_t gyroPhase = hadPreviousGyro ? priorGyro & gyroPhaseMask : 0;
  if (!hadPreviousGyro) {
    for (size_t index = 0; index < count; ++index) {
      if (parsed[index].accelValid && parsed[index].gyroValid) {
        gyroPhase = parsed[index].sensorTime & gyroPhaseMask;
        break;
      }
    }
  }
  size_t gyroOnlyCount = 0;
  bool haveCompatibleAccel = false;
  for (size_t index = 0; index < count; ++index) {
    if (parsed[index].gyroValid && !parsed[index].accelValid) ++gyroOnlyCount;
    if (parsed[index].accelValid &&
        (parsed[index].sensorTime & gyroPhaseMask) == gyroPhase) {
      haveCompatibleAccel = true;
    }
  }
  uint32_t gyroFallbackCursor = previousGyroSensorTime;
  if (anchorPresent) {
    gyroFallbackCursor =
        (anchorSensorTime & kSensorTimeMask) & ~gyroPhaseMask;
    if (!haveCompatibleAccel && gyroOnlyCount > 1) {
      gyroFallbackCursor =
          (gyroFallbackCursor -
           static_cast<uint32_t>(gyroOnlyCount - 1u) * gyroTicksPerSample) &
          kSensorTimeMask;
    }
  }
  bool haveExpectedGyro = hadPreviousGyro;
  uint32_t expectedGyro =
      (priorGyro + gyroTicksPerSample) & kSensorTimeMask;
  for (size_t index = 0; index < count; ++index) {
    BMI270FifoParsedSample& gyro = parsed[index];
    if (!gyro.gyroValid) continue;
    if (gyro.accelValid) {
      expectedGyro =
          (gyro.sensorTime + gyroTicksPerSample) & kSensorTimeMask;
      haveExpectedGyro = true;
      continue;
    }

    size_t bestIndex = count;
    size_t bestDistance = count + 1u;
    for (size_t candidate = 0; candidate < count; ++candidate) {
      if (!parsed[candidate].accelValid ||
          (parsed[candidate].sensorTime & gyroPhaseMask) != gyroPhase) {
        continue;
      }
      if (haveExpectedGyro &&
          parsed[candidate].sensorTime != expectedGyro) {
        continue;
      }
      const size_t distance = candidate > index
          ? candidate - index
          : index - candidate;
      if (distance < bestDistance) {
        bestDistance = distance;
        bestIndex = candidate;
      }
    }
    if (bestIndex < count) {
      gyro.sensorTime = parsed[bestIndex].sensorTime;
    } else if (haveExpectedGyro) {
      gyro.sensorTime = expectedGyro;
      gyro.statusBefore |= BMI270ImuStatus::kTimingDegraded;
      gyro.gyroTimingDegraded = true;
      gyro.gyroAssociationFallback = true;
    } else if (!anchorPresent && hadPreviousGyro) {
      gyroFallbackCursor =
          (gyroFallbackCursor + gyroTicksPerSample) & kSensorTimeMask;
      gyro.sensorTime = gyroFallbackCursor;
      gyro.statusBefore |= BMI270ImuStatus::kTimingDegraded;
      gyro.gyroTimingDegraded = true;
      gyro.gyroAssociationFallback = true;
    } else {
      gyro.sensorTime = gyroFallbackCursor;
      gyroFallbackCursor =
          (gyroFallbackCursor + gyroTicksPerSample) & kSensorTimeMask;
      gyro.statusBefore |= BMI270ImuStatus::kTimingDegraded;
      gyro.gyroTimingDegraded = true;
      gyro.gyroAssociationFallback = true;
    }
    expectedGyro =
        (gyro.sensorTime + gyroTicksPerSample) & kSensorTimeMask;
    haveExpectedGyro = true;
  }

  bool checkedAccelContinuity = false;
  bool checkedGyroContinuity = false;
  for (size_t index = 0; index < count; ++index) {
    BMI270FifoParsedSample& sample = parsed[index];
    if (sample.accelValid) {
      if (!checkedAccelContinuity && hadPreviousAccel &&
          sample.sensorTime !=
              ((priorAccel + accelTicksPerSample) & kSensorTimeMask)) {
        sample.statusBefore |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                               BMI270ImuStatus::kTimingDegraded;
        sample.sensorTimeDiscontinuityBefore = true;
        sample.accelTimeDiscontinuityBefore = true;
        sample.accelTimingDegraded = true;
      }
      checkedAccelContinuity = true;
      previousAccelSensorTime = sample.sensorTime;
      havePreviousAccelSensorTime = true;
    }
    if (sample.gyroValid) {
      if (!checkedGyroContinuity && hadPreviousGyro &&
          sample.sensorTime !=
              ((priorGyro + gyroTicksPerSample) & kSensorTimeMask)) {
        sample.statusBefore |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                               BMI270ImuStatus::kTimingDegraded;
        sample.sensorTimeDiscontinuityBefore = true;
        sample.gyroTimeDiscontinuityBefore = true;
        sample.gyroTimingDegraded = true;
      }
      checkedGyroContinuity = true;
      previousGyroSensorTime = sample.sensorTime;
      havePreviousGyroSensorTime = true;
    }
  }
  return anchorPresent || (hadPreviousAccel && hadPreviousGyro);
}

size_t BMI270FifoParser::mergeMixedRateFrames(
    BMI270FifoParsedSample* parsed,
    size_t count) {
  if (!parsed || count == 0) return 0;

  for (size_t accelIndex = 0; accelIndex < count; ++accelIndex) {
    BMI270FifoParsedSample& accel = parsed[accelIndex];
    if (!accel.accelValid || accel.gyroValid) continue;
    for (size_t gyroIndex = 0; gyroIndex < count; ++gyroIndex) {
      BMI270FifoParsedSample& gyro = parsed[gyroIndex];
      if (!gyro.gyroValid || gyro.accelValid ||
          gyro.sensorTime != accel.sensorTime) {
        continue;
      }
      accel.gyroX = gyro.gyroX;
      accel.gyroY = gyro.gyroY;
      accel.gyroZ = gyro.gyroZ;
      accel.gyroValid = true;
      accel.statusBefore |= gyro.statusBefore;
      accel.sensorTimeDiscontinuityBefore =
          accel.sensorTimeDiscontinuityBefore ||
          gyro.sensorTimeDiscontinuityBefore;
      accel.gyroTimeDiscontinuityBefore =
          accel.gyroTimeDiscontinuityBefore ||
          gyro.gyroTimeDiscontinuityBefore;
      accel.gyroTimingDegraded =
          accel.gyroTimingDegraded || gyro.gyroTimingDegraded;
      accel.gyroAssociationFallback =
          accel.gyroAssociationFallback || gyro.gyroAssociationFallback;
      gyro.gyroValid = false;
      break;
    }
  }

  for (size_t gyroIndex = 0; gyroIndex < count; ++gyroIndex) {
    const BMI270FifoParsedSample& gyro = parsed[gyroIndex];
    if (!gyro.gyroValid || gyro.accelValid) continue;
    size_t nearestAccel = count;
    size_t nearestDistance = count + 1u;
    for (size_t accelIndex = 0; accelIndex < count; ++accelIndex) {
      if (!parsed[accelIndex].accelValid) continue;
      const size_t distance = accelIndex > gyroIndex
          ? accelIndex - gyroIndex
          : gyroIndex - accelIndex;
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestAccel = accelIndex;
      }
    }
    if (nearestAccel < count) {
      parsed[nearestAccel].statusBefore |=
          BMI270ImuStatus::kFifoDiscontinuityBefore |
          BMI270ImuStatus::kTimingDegraded;
      parsed[nearestAccel].sensorTimeDiscontinuityBefore = true;
      parsed[nearestAccel].gyroTimeDiscontinuityBefore = true;
      parsed[nearestAccel].gyroTimingDegraded = true;
      parsed[nearestAccel].gyroAssociationFallback = true;
    }
  }

  size_t written = 0;
  for (size_t index = 0; index < count; ++index) {
    if (!parsed[index].accelValid) continue;
    if (written != index) parsed[written] = parsed[index];
    ++written;
  }
  return written;
}

bool BMI270FifoParser::assignSensorTimes(
    BMI270FifoParsedSample* parsed,
    size_t count,
    bool anchorPresent,
    uint32_t anchorSensorTime,
    uint32_t ticksPerSample,
    bool& havePreviousSensorTime,
    uint32_t& previousSensorTime) {
  if (!parsed || count == 0 || ticksPerSample == 0 ||
      (ticksPerSample & (ticksPerSample - 1u)) != 0) {
    return false;
  }

  if (anchorPresent) {
    const bool hadPreviousSensorTime = havePreviousSensorTime;
    const uint32_t priorSensorTime = previousSensorTime;
    uint32_t cursor =
        (anchorSensorTime & kSensorTimeMask) & ~(ticksPerSample - 1u);
    for (size_t reverse = count; reverse > 0; --reverse) {
      const size_t index = reverse - 1;
      parsed[index].sensorTime = cursor;
      parsed[index].statusBefore |= BMI270ImuStatus::kSensorTimeEstimated;
      const uint32_t intervals = 1u + parsed[index].skippedFramesBefore;
      cursor = (cursor - intervals * ticksPerSample) & kSensorTimeMask;
    }
    if (hadPreviousSensorTime) {
      const uint32_t expected =
          (priorSensorTime +
           (1u + parsed[0].skippedFramesBefore) * ticksPerSample) &
          kSensorTimeMask;
      if (parsed[0].sensorTime != expected) {
        parsed[0].statusBefore |= BMI270ImuStatus::kFifoDiscontinuityBefore |
                                  BMI270ImuStatus::kTimingDegraded;
        parsed[0].sensorTimeDiscontinuityBefore = true;
        parsed[0].accelTimeDiscontinuityBefore = true;
        parsed[0].accelTimingDegraded = true;
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
      parsed[index].accelTimingDegraded = true;
      if (parsed[index].gyroValid) parsed[index].gyroTimingDegraded = true;
    }
    return false;
  }

  for (size_t index = 0; index < count; ++index) {
    const uint32_t intervals = 1u + parsed[index].skippedFramesBefore;
    previousSensorTime =
        (previousSensorTime + intervals * ticksPerSample) & kSensorTimeMask;
    parsed[index].sensorTime = previousSensorTime;
    parsed[index].statusBefore |= BMI270ImuStatus::kSensorTimeEstimated |
                                  BMI270ImuStatus::kTimingDegraded;
    parsed[index].accelTimingDegraded = true;
    if (parsed[index].gyroValid) parsed[index].gyroTimingDegraded = true;
  }
  return true;
}

bool BMI270FifoParser::assignSensorTimes200Hz(
    BMI270FifoParsedSample* parsed,
    size_t count,
    bool anchorPresent,
    uint32_t anchorSensorTime,
    bool& havePreviousSensorTime,
    uint32_t& previousSensorTime) {
  return assignSensorTimes(
      parsed,
      count,
      anchorPresent,
      anchorSensorTime,
      kTicksPerSample200Hz,
      havePreviousSensorTime,
      previousSensorTime);
}
