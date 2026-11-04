#pragma once

#include <stddef.h>
#include <stdint.h>

namespace CanMasterProtocol {

constexpr uint8_t kProtocolVersion = 1;
constexpr size_t kPayloadBytes = 64;
constexpr size_t kHeaderBytes = 16;
constexpr size_t kSlotBytes = kHeaderBytes + kPayloadBytes + 4;
constexpr uint32_t kCapabilityStatus = 1UL << 0;
constexpr uint32_t kCapabilityDiscovery = 1UL << 1;
constexpr uint16_t kStatusVersion = 1;
constexpr size_t kStatusBytes = 52;
constexpr uint8_t kDiscoveryVersion = 1;
constexpr uint8_t kDiscoveryNodeCount = 4;
constexpr size_t kDiscoveryRequestBytes = 8;
constexpr size_t kDiscoveryResponseBytes = 64;

constexpr uint8_t kDiscoveryFlagPresent = 1U << 0;
constexpr uint8_t kDiscoveryFlagStale = 1U << 1;
constexpr uint8_t kDiscoveryFlagDuplicate = 1U << 2;
constexpr uint8_t kDiscoveryFlagStatusValid = 1U << 3;

constexpr uint16_t kStatusFlagBuckEnabled = 1U << 0;
constexpr uint16_t kStatusFlagFrontEnabled = 1U << 1;
constexpr uint16_t kStatusFlagRearEnabled = 1U << 2;
constexpr uint16_t kStatusFlagFrontFault = 1U << 3;
constexpr uint16_t kStatusFlagRearFault = 1U << 4;
constexpr uint16_t kStatusFlagCanInitialized = 1U << 5;
constexpr uint16_t kStatusFlagCanBusOff = 1U << 6;
constexpr uint16_t kStatusFlagClockFault = 1U << 7;

enum class MessageType : uint8_t {
  None = 0,
  ProbeRequest = 1,
  FetchResponse = 2,
  StatusRequest = 3,
  DiscoveryRequest = 4,
  IdentityResponse = 0x81,
  StatusResponse = 0x83,
  DiscoveryResponse = 0x84,
  ErrorResponse = 0xFF,
};

enum class DecodeResult : uint8_t {
  Ok = 0,
  InvalidArgument,
  BadMagic,
  UnsupportedVersion,
  InvalidLength,
  BadCrc,
};

struct Frame {
  MessageType type = MessageType::None;
  uint16_t flags = 0;
  uint32_t sequence = 0;
  uint16_t payloadLength = 0;
  uint8_t payload[kPayloadBytes] = {0};
};

struct Identity {
  uint32_t firmwareVersion = 0;
  uint32_t capabilities = 0;
  uint64_t hardwareUid = 0;
  uint16_t minimumProtocolVersion = 0;
  uint16_t maximumProtocolVersion = 0;
};

struct Status {
  uint16_t statusVersion = 0;
  uint16_t flags = 0;
  uint32_t uptimeMs = 0;
  uint32_t resetCause = 0;
  uint32_t slotsReceived = 0;
  uint32_t malformedSlots = 0;
  uint32_t probesReceived = 0;
  uint32_t statusRequestsReceived = 0;
  uint32_t spiRecoveries = 0;
  uint32_t canRxFrames = 0;
  uint32_t canTxFrames = 0;
  uint32_t canErrorEvents = 0;
  uint16_t canRxQueueDepth = 0;
  uint16_t canRxQueueHighWater = 0;
  uint16_t spiTxQueueDepth = 0;
  uint16_t spiTxQueueHighWater = 0;
};

struct DiscoveryRecord {
  uint8_t nodeAddress = 0;
  uint8_t nodeCount = 0;
  uint8_t flags = 0;
  uint32_t generation = 0;
  uint8_t hardwareType = 0;
  uint16_t endpointMask = 0;
  uint32_t firmwareVersion = 0;
  uint32_t capabilities = 0;
  uint64_t hardwareUid = 0;
  uint64_t conflictingHardwareUid = 0;
  uint32_t bootId = 0;
  uint32_t lastSeenMs = 0;
  uint32_t nodeUptimeMs = 0;
  uint32_t nodeStatusFlags = 0;
  uint32_t canRxFrames = 0;
  uint32_t canTxFrames = 0;
  uint16_t canErrorEvents = 0;
  uint16_t txQueueHighWater = 0;
};

uint32_t crc32(const uint8_t* data, size_t length);
bool encodeSlot(const Frame& frame, uint8_t* output, size_t capacity);
DecodeResult decodeSlot(const uint8_t* input, size_t length, Frame& output);
bool decodeIdentity(const Frame& frame, Identity& output);
bool decodeStatus(const Frame& frame, Status& output);
bool encodeDiscoveryRequest(uint8_t nodeAddress, uint32_t expectedGeneration,
                            uint32_t sequence, Frame& output);
bool decodeDiscoveryResponse(const Frame& frame, DiscoveryRecord& output);

}  // namespace CanMasterProtocol
