#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "BdqV2Format.h"

namespace AS5600BdqV2 {

inline constexpr uint16_t kRecordSizeBytes = 20;
inline constexpr uint64_t kNativeTickModulus = uint64_t{1} << 32;

inline constexpr uint16_t kReadFailed = 0x0020;
inline constexpr uint16_t kReusedPrevious = 0x0040;
inline constexpr uint16_t kDiagnosticsStale = 0x0080;
inline constexpr uint16_t kMagnetNotDetected = 0x0100;
inline constexpr uint16_t kMagnetTooWeak = 0x0200;
inline constexpr uint16_t kMagnetTooStrong = 0x0400;

struct Record {
  uint32_t sequence = 0;
  uint32_t nativeTick = 0;
  uint16_t statusFlags = 0;
  uint16_t rawAngle = 0;
  uint8_t sensorStatus = 0;
  uint8_t agc = 0;
  uint16_t magnitude = 0;
  bool readOk = false;
  bool reused = false;
};

inline bool encodeRecord(
    const Record& record,
    uint8_t* destination,
    size_t capacity) {
  if (!destination || capacity < kRecordSizeBytes) return false;
  memset(destination, 0, kRecordSizeBytes);

  BdqV2Format::StreamRecordPrefix prefix;
  prefix.sequence = record.sequence;
  prefix.nativeTick = record.nativeTick;
  prefix.statusFlags = record.statusFlags;
  if (!BdqV2Format::encodeStreamRecordPrefix(
          prefix, destination, capacity)) {
    return false;
  }

  BdqV2Format::putU16(destination + 12, record.rawAngle);
  destination[14] = record.sensorStatus;
  destination[15] = record.agc;
  BdqV2Format::putU16(destination + 16, record.magnitude);
  destination[18] = record.readOk ? 1u : 0u;
  destination[19] = record.reused ? 1u : 0u;
  return true;
}

static_assert(kRecordSizeBytes == 20);
static_assert(kNativeTickModulus == 4294967296ULL);

}  // namespace AS5600BdqV2
