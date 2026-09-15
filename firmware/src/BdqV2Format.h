#pragma once

#include <stddef.h>
#include <stdint.h>

namespace BdqV2Format {

inline constexpr uint8_t kFileMagic[8] = {
    'B', 'D', 'Q', 'L', 'O', 'G', 0x00, 0x02,
};
inline constexpr uint8_t kChunkMagic[4] = {'B', 'D', 'Q', 'C'};

inline constexpr uint16_t kFormatMajor = 2;
inline constexpr uint16_t kFormatMinor = 0;
inline constexpr size_t kFileHeaderBytes = 32;
inline constexpr size_t kChunkHeaderBytes = 20;
inline constexpr size_t kStreamDataHeaderBytes = 24;
inline constexpr size_t kStreamRecordPrefixBytes = 12;
inline constexpr size_t kTimeObservationBytes = 32;

enum class ChunkType : uint16_t {
  Metadata = 1,
  StreamCatalog = 2,
  StreamData = 3,
  Event = 4,
  FinalSummary = 5,
};

enum StreamStatus : uint16_t {
  DiscontinuityBefore = 0x0001,
  ProducerQueueDropBefore = 0x0002,
  SourceRecoveryBefore = 0x0004,
  TimingDegraded = 0x0008,
  NativeTickEstimated = 0x0010,
};

enum class TimeObservationKind : uint16_t {
  AcquisitionWindow = 1,
  ClockSyncWindow = 2,
  TransportReceiveWindow = 3,
  HardwareCapture = 4,
  DerivedMappingPoint = 5,
};

enum TimeObservationFlags : uint16_t {
  ObservationNativeTickEstimated = 0x0001,
  ObservationHostBoundsConservative = 0x0002,
  ObservationTimingDegraded = 0x0004,
  ObservationPreSession = 0x0008,
  ObservationPostRecovery = 0x0010,
};

struct FileHeader {
  uint64_t createdUnixUs = 0;
  uint32_t flags = 0;
  uint32_t headerCrc32 = 0;
};

struct ChunkHeader {
  uint16_t headerVersion = 1;
  ChunkType type = ChunkType::Metadata;
  uint32_t sequence = 0;
  uint32_t payloadLength = 0;
  uint32_t payloadCrc32 = 0;
};

struct StreamDataHeader {
  uint16_t streamId = 0;
  uint16_t payloadVersion = 1;
  uint32_t flags = 0;
  uint32_t firstSequence = 0;
  uint32_t recordCount = 0;
  uint16_t recordSizeBytes = 0;
  uint16_t observationCount = 0;
  uint32_t reserved = 0;
};

struct StreamRecordPrefix {
  uint32_t sequence = 0;
  uint32_t nativeTick = 0;
  uint16_t statusFlags = 0;
  uint16_t reserved = 0;
};

struct TimeObservation {
  uint32_t nativeTick = 0;
  uint32_t relatedSequence = UINT32_MAX;
  uint64_t hostMinUs = 0;
  uint64_t hostMaxUs = 0;
  TimeObservationKind kind = TimeObservationKind::AcquisitionWindow;
  uint16_t flags = 0;
  uint32_t reserved = 0;
};

inline void putU16(uint8_t* out, uint16_t value) {
  out[0] = static_cast<uint8_t>(value & 0xFFu);
  out[1] = static_cast<uint8_t>((value >> 8) & 0xFFu);
}

inline void putU32(uint8_t* out, uint32_t value) {
  for (uint8_t i = 0; i < 4; ++i) {
    out[i] = static_cast<uint8_t>((value >> (8u * i)) & 0xFFu);
  }
}

inline void putU64(uint8_t* out, uint64_t value) {
  for (uint8_t i = 0; i < 8; ++i) {
    out[i] = static_cast<uint8_t>((value >> (8u * i)) & 0xFFu);
  }
}

inline uint16_t getU16(const uint8_t* in) {
  return static_cast<uint16_t>(in[0]) |
         static_cast<uint16_t>(static_cast<uint16_t>(in[1]) << 8);
}

inline uint32_t getU32(const uint8_t* in) {
  uint32_t value = 0;
  for (uint8_t i = 0; i < 4; ++i) {
    value |= static_cast<uint32_t>(in[i]) << (8u * i);
  }
  return value;
}

inline uint64_t getU64(const uint8_t* in) {
  uint64_t value = 0;
  for (uint8_t i = 0; i < 8; ++i) {
    value |= static_cast<uint64_t>(in[i]) << (8u * i);
  }
  return value;
}

inline uint32_t crc32(const uint8_t* data, size_t length) {
  if (!data && length != 0) return 0;
  uint32_t crc = 0xFFFFFFFFu;
  for (size_t index = 0; index < length; ++index) {
    crc ^= data[index];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc >> 1) ^ (0xEDB88320u &
                          static_cast<uint32_t>(-
                              static_cast<int32_t>(crc & 1u)));
    }
  }
  return ~crc;
}

inline bool encodeFileHeader(
    const FileHeader& value,
    uint8_t* out,
    size_t capacity) {
  if (!out || capacity < kFileHeaderBytes) return false;
  for (size_t index = 0; index < sizeof(kFileMagic); ++index) {
    out[index] = kFileMagic[index];
  }
  putU16(out + 8, kFormatMajor);
  putU16(out + 10, kFormatMinor);
  putU32(out + 12, static_cast<uint32_t>(kFileHeaderBytes));
  putU64(out + 16, value.createdUnixUs);
  putU32(out + 24, value.flags);
  putU32(out + 28, value.headerCrc32);
  return true;
}

inline bool encodeChunkHeader(
    const ChunkHeader& value,
    uint8_t* out,
    size_t capacity) {
  if (!out || capacity < kChunkHeaderBytes) return false;
  for (size_t index = 0; index < sizeof(kChunkMagic); ++index) {
    out[index] = kChunkMagic[index];
  }
  putU16(out + 4, value.headerVersion);
  putU16(out + 6, static_cast<uint16_t>(value.type));
  putU32(out + 8, value.sequence);
  putU32(out + 12, value.payloadLength);
  putU32(out + 16, value.payloadCrc32);
  return true;
}

inline bool encodeStreamDataHeader(
    const StreamDataHeader& value,
    uint8_t* out,
    size_t capacity) {
  if (!out || capacity < kStreamDataHeaderBytes) return false;
  putU16(out + 0, value.streamId);
  putU16(out + 2, value.payloadVersion);
  putU32(out + 4, value.flags);
  putU32(out + 8, value.firstSequence);
  putU32(out + 12, value.recordCount);
  putU16(out + 16, value.recordSizeBytes);
  putU16(out + 18, value.observationCount);
  putU32(out + 20, value.reserved);
  return true;
}

inline bool decodeStreamDataHeader(
    const uint8_t* in,
    size_t length,
    StreamDataHeader& out) {
  if (!in || length < kStreamDataHeaderBytes) return false;
  out.streamId = getU16(in + 0);
  out.payloadVersion = getU16(in + 2);
  out.flags = getU32(in + 4);
  out.firstSequence = getU32(in + 8);
  out.recordCount = getU32(in + 12);
  out.recordSizeBytes = getU16(in + 16);
  out.observationCount = getU16(in + 18);
  out.reserved = getU32(in + 20);
  return true;
}

inline bool encodeStreamRecordPrefix(
    const StreamRecordPrefix& value,
    uint8_t* out,
    size_t capacity) {
  if (!out || capacity < kStreamRecordPrefixBytes) return false;
  putU32(out + 0, value.sequence);
  putU32(out + 4, value.nativeTick);
  putU16(out + 8, value.statusFlags);
  putU16(out + 10, value.reserved);
  return true;
}

inline bool decodeStreamRecordPrefix(
    const uint8_t* in,
    size_t length,
    StreamRecordPrefix& out) {
  if (!in || length < kStreamRecordPrefixBytes) return false;
  out.sequence = getU32(in + 0);
  out.nativeTick = getU32(in + 4);
  out.statusFlags = getU16(in + 8);
  out.reserved = getU16(in + 10);
  return true;
}

inline bool encodeTimeObservation(
    const TimeObservation& value,
    uint8_t* out,
    size_t capacity) {
  if (!out || capacity < kTimeObservationBytes) return false;
  putU32(out + 0, value.nativeTick);
  putU32(out + 4, value.relatedSequence);
  putU64(out + 8, value.hostMinUs);
  putU64(out + 16, value.hostMaxUs);
  putU16(out + 24, static_cast<uint16_t>(value.kind));
  putU16(out + 26, value.flags);
  putU32(out + 28, value.reserved);
  return true;
}

inline bool decodeTimeObservation(
    const uint8_t* in,
    size_t length,
    TimeObservation& out) {
  if (!in || length < kTimeObservationBytes) return false;
  out.nativeTick = getU32(in + 0);
  out.relatedSequence = getU32(in + 4);
  out.hostMinUs = getU64(in + 8);
  out.hostMaxUs = getU64(in + 16);
  out.kind = static_cast<TimeObservationKind>(getU16(in + 24));
  out.flags = getU16(in + 26);
  out.reserved = getU32(in + 28);
  return true;
}

constexpr bool validTimeObservationKind(TimeObservationKind kind) {
  return kind >= TimeObservationKind::AcquisitionWindow &&
         kind <= TimeObservationKind::DerivedMappingPoint;
}

constexpr bool validTimeObservation(const TimeObservation& value) {
  return value.hostMinUs <= value.hostMaxUs &&
         validTimeObservationKind(value.kind) &&
         value.reserved == 0;
}

static_assert(kFileHeaderBytes == 32);
static_assert(kChunkHeaderBytes == 20);
static_assert(kStreamDataHeaderBytes == 24);
static_assert(kStreamRecordPrefixBytes == 12);
static_assert(kTimeObservationBytes == 32);
static_assert(static_cast<uint16_t>(ChunkType::StreamData) == 3);
static_assert(DiscontinuityBefore == 0x0001);
static_assert(NativeTickEstimated == 0x0010);

}  // namespace BdqV2Format
