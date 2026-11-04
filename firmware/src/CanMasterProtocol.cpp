#include "CanMasterProtocol.h"

#include <string.h>

namespace {

constexpr uint8_t kMagic[4] = {'B', 'C', 'M', '1'};

void putU16_(uint8_t* output, uint16_t value) {
  output[0] = static_cast<uint8_t>(value);
  output[1] = static_cast<uint8_t>(value >> 8);
}

void putU32_(uint8_t* output, uint32_t value) {
  for (uint8_t index = 0; index < 4; ++index) {
    output[index] = static_cast<uint8_t>(value >> (8 * index));
  }
}

uint16_t getU16_(const uint8_t* input) {
  return static_cast<uint16_t>(input[0]) |
      static_cast<uint16_t>(input[1] << 8);
}

uint32_t getU32_(const uint8_t* input) {
  return static_cast<uint32_t>(input[0]) |
      (static_cast<uint32_t>(input[1]) << 8) |
      (static_cast<uint32_t>(input[2]) << 16) |
      (static_cast<uint32_t>(input[3]) << 24);
}

uint64_t getU64_(const uint8_t* input) {
  uint64_t value = 0;
  for (uint8_t index = 0; index < 8; ++index) {
    value |= static_cast<uint64_t>(input[index]) << (8 * index);
  }
  return value;
}

}  // namespace

namespace CanMasterProtocol {

uint32_t crc32(const uint8_t* data, size_t length) {
  if (!data && length != 0) return 0;
  uint32_t crc = 0xFFFFFFFFu;
  for (size_t index = 0; index < length; ++index) {
    crc ^= data[index];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc >> 1) ^ (0xEDB88320u &
          static_cast<uint32_t>(-static_cast<int32_t>(crc & 1u)));
    }
  }
  return ~crc;
}

bool encodeSlot(const Frame& frame, uint8_t* output, size_t capacity) {
  if (!output || capacity < kSlotBytes || frame.payloadLength > kPayloadBytes) {
    return false;
  }
  memset(output, 0, kSlotBytes);
  memcpy(output, kMagic, sizeof(kMagic));
  output[4] = kProtocolVersion;
  output[5] = static_cast<uint8_t>(frame.type);
  putU16_(output + 6, frame.flags);
  putU32_(output + 8, frame.sequence);
  putU16_(output + 12, frame.payloadLength);
  if (frame.payloadLength != 0) {
    memcpy(output + kHeaderBytes, frame.payload, frame.payloadLength);
  }
  putU32_(output + kHeaderBytes + kPayloadBytes,
          crc32(output, kHeaderBytes + kPayloadBytes));
  return true;
}

DecodeResult decodeSlot(const uint8_t* input, size_t length, Frame& output) {
  output = Frame{};
  if (!input) return DecodeResult::InvalidArgument;
  if (length != kSlotBytes) return DecodeResult::InvalidLength;
  if (memcmp(input, kMagic, sizeof(kMagic)) != 0) {
    return DecodeResult::BadMagic;
  }
  if (input[4] != kProtocolVersion) {
    return DecodeResult::UnsupportedVersion;
  }
  const uint16_t payloadLength = getU16_(input + 12);
  if (payloadLength > kPayloadBytes) return DecodeResult::InvalidLength;
  const uint32_t expectedCrc = getU32_(input + kHeaderBytes + kPayloadBytes);
  if (crc32(input, kHeaderBytes + kPayloadBytes) != expectedCrc) {
    return DecodeResult::BadCrc;
  }

  output.type = static_cast<MessageType>(input[5]);
  output.flags = getU16_(input + 6);
  output.sequence = getU32_(input + 8);
  output.payloadLength = payloadLength;
  if (payloadLength != 0) {
    memcpy(output.payload, input + kHeaderBytes, payloadLength);
  }
  return DecodeResult::Ok;
}

bool decodeIdentity(const Frame& frame, Identity& output) {
  if (frame.type != MessageType::IdentityResponse || frame.payloadLength < 20) {
    return false;
  }
  output.firmwareVersion = getU32_(frame.payload);
  output.capabilities = getU32_(frame.payload + 4);
  output.hardwareUid = getU64_(frame.payload + 8);
  output.minimumProtocolVersion = getU16_(frame.payload + 16);
  output.maximumProtocolVersion = getU16_(frame.payload + 18);
  return true;
}

bool decodeStatus(const Frame& frame, Status& output) {
  output = Status{};
  if (frame.type != MessageType::StatusResponse ||
      frame.payloadLength != kStatusBytes) {
    return false;
  }
  output.statusVersion = getU16_(frame.payload);
  if (output.statusVersion != kStatusVersion) return false;
  output.flags = getU16_(frame.payload + 2);
  output.uptimeMs = getU32_(frame.payload + 4);
  output.resetCause = getU32_(frame.payload + 8);
  output.slotsReceived = getU32_(frame.payload + 12);
  output.malformedSlots = getU32_(frame.payload + 16);
  output.probesReceived = getU32_(frame.payload + 20);
  output.statusRequestsReceived = getU32_(frame.payload + 24);
  output.spiRecoveries = getU32_(frame.payload + 28);
  output.canRxFrames = getU32_(frame.payload + 32);
  output.canTxFrames = getU32_(frame.payload + 36);
  output.canErrorEvents = getU32_(frame.payload + 40);
  output.canRxQueueDepth = getU16_(frame.payload + 44);
  output.canRxQueueHighWater = getU16_(frame.payload + 46);
  output.spiTxQueueDepth = getU16_(frame.payload + 48);
  output.spiTxQueueHighWater = getU16_(frame.payload + 50);
  return true;
}

bool encodeDiscoveryRequest(uint8_t nodeAddress, uint32_t expectedGeneration,
                            uint32_t sequence, Frame& output) {
  if (nodeAddress >= kDiscoveryNodeCount || sequence == 0) return false;
  output = Frame{};
  output.type = MessageType::DiscoveryRequest;
  output.sequence = sequence;
  output.payloadLength = kDiscoveryRequestBytes;
  output.payload[0] = kDiscoveryVersion;
  output.payload[1] = nodeAddress;
  putU32_(output.payload + 4, expectedGeneration);
  return true;
}

bool decodeDiscoveryResponse(const Frame& frame, DiscoveryRecord& output) {
  output = DiscoveryRecord{};
  if (frame.type != MessageType::DiscoveryResponse ||
      frame.payloadLength != kDiscoveryResponseBytes ||
      frame.payload[0] != kDiscoveryVersion ||
      frame.payload[1] >= kDiscoveryNodeCount ||
      frame.payload[2] != kDiscoveryNodeCount || frame.payload[9] != 0) {
    return false;
  }
  output.nodeAddress = frame.payload[1];
  output.nodeCount = frame.payload[2];
  output.flags = frame.payload[3];
  output.generation = getU32_(frame.payload + 4);
  if (output.generation == 0) return false;
  output.hardwareType = frame.payload[8];
  output.endpointMask = getU16_(frame.payload + 10);
  output.firmwareVersion = getU32_(frame.payload + 12);
  output.capabilities = getU32_(frame.payload + 16);
  output.hardwareUid = getU64_(frame.payload + 20);
  output.conflictingHardwareUid = getU64_(frame.payload + 28);
  output.bootId = getU32_(frame.payload + 36);
  output.lastSeenMs = getU32_(frame.payload + 40);
  output.nodeUptimeMs = getU32_(frame.payload + 44);
  output.nodeStatusFlags = getU32_(frame.payload + 48);
  output.canRxFrames = getU32_(frame.payload + 52);
  output.canTxFrames = getU32_(frame.payload + 56);
  output.canErrorEvents = getU16_(frame.payload + 60);
  output.txQueueHighWater = getU16_(frame.payload + 62);
  return true;
}

}  // namespace CanMasterProtocol
