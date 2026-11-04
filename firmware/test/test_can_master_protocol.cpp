#include <cstdio>
#include <cstring>

#include "CanMasterProtocol.h"

int runCanMasterProtocolTests() {
    int passed = 0;
    int failed = 0;
    auto check = [&](bool condition, const char* description) {
        if (condition) ++passed;
        else {
            std::printf("    FAIL: CAN master protocol: %s\n", description);
            ++failed;
        }
    };

    CanMasterProtocol::Frame request;
    request.type = CanMasterProtocol::MessageType::ProbeRequest;
    request.flags = 0x1234;
    request.sequence = 42;
    request.payloadLength = 3;
    request.payload[0] = 1;
    request.payload[1] = 2;
    request.payload[2] = 3;
    uint8_t slot[CanMasterProtocol::kSlotBytes];
    check(CanMasterProtocol::encodeSlot(request, slot, sizeof(slot)),
          "fixed mailbox slot encodes");

    CanMasterProtocol::Frame decoded;
    check(CanMasterProtocol::decodeSlot(slot, sizeof(slot), decoded) ==
              CanMasterProtocol::DecodeResult::Ok &&
              decoded.type == request.type && decoded.flags == request.flags &&
              decoded.sequence == request.sequence && decoded.payloadLength == 3 &&
              std::memcmp(decoded.payload, request.payload, 3) == 0,
          "slot round trip preserves header and payload");

    slot[CanMasterProtocol::kHeaderBytes + 1] ^= 0x80;
    check(CanMasterProtocol::decodeSlot(slot, sizeof(slot), decoded) ==
              CanMasterProtocol::DecodeResult::BadCrc,
          "payload corruption is rejected by CRC");
    slot[CanMasterProtocol::kHeaderBytes + 1] ^= 0x80;
    slot[4] = CanMasterProtocol::kProtocolVersion + 1;
    check(CanMasterProtocol::decodeSlot(slot, sizeof(slot), decoded) ==
              CanMasterProtocol::DecodeResult::UnsupportedVersion,
          "unsupported protocol version is distinguished");

    CanMasterProtocol::Frame identity;
    identity.type = CanMasterProtocol::MessageType::IdentityResponse;
    identity.payloadLength = 20;
    const uint8_t identityPayload[20] = {
        0x04, 0x03, 0x02, 0x01,
        0x44, 0x33, 0x22, 0x11,
        0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01,
        0x01, 0x00, 0x02, 0x00,
    };
    std::memcpy(identity.payload, identityPayload, sizeof(identityPayload));
    CanMasterProtocol::Identity parsed;
    check(CanMasterProtocol::decodeIdentity(identity, parsed) &&
              parsed.firmwareVersion == 0x01020304u &&
              parsed.capabilities == 0x11223344u &&
              parsed.hardwareUid == 0x0102030405060708ULL &&
              parsed.minimumProtocolVersion == 1 &&
              parsed.maximumProtocolVersion == 2,
          "identity response uses explicit little-endian fields");

    CanMasterProtocol::Frame status;
    status.type = CanMasterProtocol::MessageType::StatusResponse;
    status.payloadLength = CanMasterProtocol::kStatusBytes;
    const uint8_t statusPayload[CanMasterProtocol::kStatusBytes] = {
        0x01, 0x00, 0x18, 0x00,
        0x04, 0x03, 0x02, 0x01, 0x0C, 0x00, 0x00, 0x00,
        0x10, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00,
        0x02, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00,
        0x04, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00,
        0x06, 0x00, 0x00, 0x00, 0x07, 0x00, 0x00, 0x00,
        0x08, 0x00, 0x09, 0x00, 0x0A, 0x00, 0x0B, 0x00,
    };
    std::memcpy(status.payload, statusPayload, sizeof(statusPayload));
    CanMasterProtocol::Status parsedStatus;
    check(CanMasterProtocol::decodeStatus(status, parsedStatus) &&
              parsedStatus.flags == 0x0018u &&
              parsedStatus.uptimeMs == 0x01020304u &&
              parsedStatus.resetCause == 12u &&
              parsedStatus.slotsReceived == 16u &&
              parsedStatus.malformedSlots == 1u &&
              parsedStatus.probesReceived == 2u &&
              parsedStatus.statusRequestsReceived == 3u &&
              parsedStatus.spiRecoveries == 4u &&
              parsedStatus.canRxFrames == 5u &&
              parsedStatus.canTxFrames == 6u &&
              parsedStatus.canErrorEvents == 7u &&
              parsedStatus.canRxQueueDepth == 8u &&
              parsedStatus.canRxQueueHighWater == 9u &&
              parsedStatus.spiTxQueueDepth == 10u &&
              parsedStatus.spiTxQueueHighWater == 11u,
          "status response uses explicit versioned little-endian fields");

    CanMasterProtocol::Frame discoveryRequest;
    check(CanMasterProtocol::encodeDiscoveryRequest(
              3, 0x10203040u, 77u, discoveryRequest) &&
              discoveryRequest.type ==
                  CanMasterProtocol::MessageType::DiscoveryRequest &&
              discoveryRequest.sequence == 77u &&
              discoveryRequest.payloadLength ==
                  CanMasterProtocol::kDiscoveryRequestBytes &&
              discoveryRequest.payload[0] ==
                  CanMasterProtocol::kDiscoveryVersion &&
              discoveryRequest.payload[1] == 3u &&
              discoveryRequest.payload[4] == 0x40u &&
              discoveryRequest.payload[7] == 0x10u,
          "discovery request selects a page and snapshot generation");

    CanMasterProtocol::Frame discovery;
    discovery.type = CanMasterProtocol::MessageType::DiscoveryResponse;
    discovery.payloadLength = CanMasterProtocol::kDiscoveryResponseBytes;
    const uint8_t discoveryPayload[CanMasterProtocol::kDiscoveryResponseBytes] = {
        0x01, 0x02, 0x04, 0x09,
        0x44, 0x33, 0x22, 0x11,
        0x03, 0x00, 0x1F, 0x00,
        0x02, 0x00, 0x01, 0x00,
        0x88, 0x77, 0x66, 0x55,
        0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01,
        0x18, 0x17, 0x16, 0x15, 0x14, 0x13, 0x12, 0x11,
        0x5A, 0x5A, 0xA5, 0xA5,
        0x39, 0x30, 0x00, 0x00,
        0x32, 0x09, 0x01, 0x00,
        0xAA, 0x55, 0x00, 0x00,
        0x65, 0x00, 0x00, 0x00,
        0xCA, 0x00, 0x00, 0x00,
        0x2F, 0x01, 0x04, 0x00,
    };
    std::memcpy(discovery.payload, discoveryPayload,
                sizeof(discoveryPayload));
    CanMasterProtocol::DiscoveryRecord parsedDiscovery;
    check(CanMasterProtocol::decodeDiscoveryResponse(
              discovery, parsedDiscovery) &&
              parsedDiscovery.nodeAddress == 2u &&
              parsedDiscovery.nodeCount == 4u &&
              parsedDiscovery.flags == 0x09u &&
              parsedDiscovery.generation == 0x11223344u &&
              parsedDiscovery.hardwareType == 3u &&
              parsedDiscovery.endpointMask == 0x001Fu &&
              parsedDiscovery.firmwareVersion == 0x00010002u &&
              parsedDiscovery.capabilities == 0x55667788u &&
              parsedDiscovery.hardwareUid == 0x0102030405060708ULL &&
              parsedDiscovery.conflictingHardwareUid ==
                  0x1112131415161718ULL &&
              parsedDiscovery.bootId == 0xA5A55A5Au &&
              parsedDiscovery.lastSeenMs == 12345u &&
              parsedDiscovery.nodeUptimeMs == 67890u &&
              parsedDiscovery.nodeStatusFlags == 0x55AAu &&
              parsedDiscovery.canRxFrames == 101u &&
              parsedDiscovery.canTxFrames == 202u &&
              parsedDiscovery.canErrorEvents == 303u &&
              parsedDiscovery.txQueueHighWater == 4u,
          "discovery response uses the fixed four-page inventory schema");
    discovery.payload[4] = 0;
    discovery.payload[5] = 0;
    discovery.payload[6] = 0;
    discovery.payload[7] = 0;
    check(!CanMasterProtocol::decodeDiscoveryResponse(
              discovery, parsedDiscovery),
          "zero is rejected as an invalid inventory generation");

    std::printf("CAN master protocol: %d passed, %d failed\n", passed, failed);
    return failed;
}
