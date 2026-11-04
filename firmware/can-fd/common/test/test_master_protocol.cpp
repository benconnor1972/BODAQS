#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "CanMasterProtocol.h"

extern "C" {
#include "bodaqs_master_protocol.h"
#include "bodaqs_master_service.h"
}

namespace {

void testLoggerProbeProducesMasterIdentity() {
  constexpr uint32_t kSequence = 0x12345678u;
  uint8_t request[BODAQS_MASTER_SLOT_BYTES] = {};
  uint8_t response[BODAQS_MASTER_SLOT_BYTES] = {};

  CanMasterProtocol::Frame loggerRequest;
  loggerRequest.type = CanMasterProtocol::MessageType::ProbeRequest;
  loggerRequest.sequence = kSequence;
  assert(CanMasterProtocol::encodeSlot(
      loggerRequest, request, sizeof(request)));

  BodaqsMasterIdentity identity = {};
  identity.firmware_version = 0x00010000u;
  identity.capabilities = 0u;
  identity.hardware_uid = UINT64_C(0x1122334455667788);
  identity.minimum_protocol_version = 1u;
  identity.maximum_protocol_version = 1u;

  BodaqsMasterService service;
  bodaqs_master_service_init(&service, &identity);
  bodaqs_master_service_process_slot(&service, request, response);

  CanMasterProtocol::Frame loggerResponse;
  assert(CanMasterProtocol::decodeSlot(
             response, sizeof(response), loggerResponse) ==
      CanMasterProtocol::DecodeResult::Ok);
  assert(loggerResponse.sequence == kSequence);

  CanMasterProtocol::Identity decodedIdentity;
  assert(CanMasterProtocol::decodeIdentity(loggerResponse, decodedIdentity));
  assert(decodedIdentity.firmwareVersion == identity.firmware_version);
  assert(decodedIdentity.capabilities == identity.capabilities);
  assert(decodedIdentity.hardwareUid == identity.hardware_uid);
  assert(decodedIdentity.minimumProtocolVersion == 1u);
  assert(decodedIdentity.maximumProtocolVersion == 1u);
  assert(service.slots_received == 1u);
  assert(service.probes_received == 1u);
  assert(service.malformed_slots == 0u);
}

void testMasterAndLoggerCrcAgree() {
  uint8_t data[80];
  for (size_t index = 0; index < sizeof(data); ++index) {
    data[index] = static_cast<uint8_t>(index * 3u + 1u);
  }
  assert(bodaqs_master_crc32(data, sizeof(data)) ==
      CanMasterProtocol::crc32(data, sizeof(data)));
}

void testMalformedRequestProducesNoResponse() {
  uint8_t request[BODAQS_MASTER_SLOT_BYTES] = {};
  uint8_t response[BODAQS_MASTER_SLOT_BYTES];
  memset(response, 0xA5, sizeof(response));

  BodaqsMasterIdentity identity = {};
  BodaqsMasterService service;
  bodaqs_master_service_init(&service, &identity);
  bodaqs_master_service_process_slot(&service, request, response);

  const uint8_t empty[BODAQS_MASTER_SLOT_BYTES] = {};
  assert(memcmp(response, empty, sizeof(response)) == 0);
  assert(service.malformed_slots == 1u);
  assert(service.bad_magic_slots == 1u);
  assert(service.bad_crc_slots == 0u);
  assert(service.last_decode_result == BODAQS_MASTER_DECODE_BAD_MAGIC);
}

void testMalformedCrcIsClassified() {
  CanMasterProtocol::Frame requestFrame;
  requestFrame.type = CanMasterProtocol::MessageType::ProbeRequest;
  requestFrame.sequence = 11u;
  uint8_t request[BODAQS_MASTER_SLOT_BYTES] = {};
  uint8_t response[BODAQS_MASTER_SLOT_BYTES] = {};
  assert(CanMasterProtocol::encodeSlot(
      requestFrame, request, sizeof(request)));
  request[BODAQS_MASTER_SLOT_BYTES - 1] ^= 0x80u;

  BodaqsMasterIdentity identity = {};
  BodaqsMasterService service;
  bodaqs_master_service_init(&service, &identity);
  assert(bodaqs_master_service_process_slot(&service, request, response) ==
      BODAQS_MASTER_SLOT_MALFORMED);
  assert(service.malformed_slots == 1u);
  assert(service.bad_magic_slots == 0u);
  assert(service.bad_crc_slots == 1u);
  assert(service.last_decode_result == BODAQS_MASTER_DECODE_BAD_CRC);
}

void testFetchConsumesPendingResponse() {
  CanMasterProtocol::Frame fetch;
  fetch.type = CanMasterProtocol::MessageType::FetchResponse;
  fetch.sequence = 7u;
  uint8_t request[BODAQS_MASTER_SLOT_BYTES] = {};
  uint8_t response[BODAQS_MASTER_SLOT_BYTES];
  assert(CanMasterProtocol::encodeSlot(fetch, request, sizeof(request)));

  BodaqsMasterIdentity identity = {};
  BodaqsMasterService service;
  bodaqs_master_service_init(&service, &identity);
  bodaqs_master_service_process_slot(&service, request, response);

  const uint8_t empty[BODAQS_MASTER_SLOT_BYTES] = {};
  assert(memcmp(response, empty, sizeof(response)) == 0);
  assert(service.malformed_slots == 0u);
}

void testLoggerStatusRequestProducesMasterStatus() {
  constexpr uint32_t kSequence = 0x10203040u;
  CanMasterProtocol::Frame loggerRequest;
  loggerRequest.type = CanMasterProtocol::MessageType::StatusRequest;
  loggerRequest.sequence = kSequence;
  uint8_t request[BODAQS_MASTER_SLOT_BYTES] = {};
  uint8_t response[BODAQS_MASTER_SLOT_BYTES] = {};
  assert(CanMasterProtocol::encodeSlot(
      loggerRequest, request, sizeof(request)));

  BodaqsMasterIdentity identity = {};
  BodaqsMasterService service;
  bodaqs_master_service_init(&service, &identity);
  BodaqsMasterStatus status = {};
  status.status_version = BODAQS_MASTER_STATUS_VERSION;
  status.flags = BODAQS_MASTER_STATUS_FLAG_FRONT_FAULT |
      BODAQS_MASTER_STATUS_FLAG_REAR_FAULT;
  status.uptime_ms = 123400u;
  status.reset_cause = 12u;
  status.spi_recoveries = 3u;
  status.can_rx_frames = 4u;
  status.can_tx_frames = 5u;
  status.can_error_events = 6u;
  status.can_rx_queue_depth = 7u;
  status.can_rx_queue_high_water = 8u;
  status.spi_tx_queue_depth = 9u;
  status.spi_tx_queue_high_water = 10u;
  bodaqs_master_service_set_status(&service, &status);
  assert(bodaqs_master_service_process_slot(&service, request, response) ==
      BODAQS_MASTER_SLOT_PROCESSED);

  CanMasterProtocol::Frame loggerResponse;
  assert(CanMasterProtocol::decodeSlot(
             response, sizeof(response), loggerResponse) ==
      CanMasterProtocol::DecodeResult::Ok);
  assert(loggerResponse.sequence == kSequence);
  CanMasterProtocol::Status decoded;
  assert(CanMasterProtocol::decodeStatus(loggerResponse, decoded));
  assert(decoded.flags == status.flags);
  assert(decoded.uptimeMs == status.uptime_ms);
  assert(decoded.resetCause == status.reset_cause);
  assert(decoded.slotsReceived == 1u);
  assert(decoded.malformedSlots == 0u);
  assert(decoded.probesReceived == 0u);
  assert(decoded.statusRequestsReceived == 1u);
  assert(decoded.spiRecoveries == status.spi_recoveries);
  assert(decoded.canRxFrames == status.can_rx_frames);
  assert(decoded.canTxFrames == status.can_tx_frames);
  assert(decoded.canErrorEvents == status.can_error_events);
  assert(decoded.canRxQueueDepth == status.can_rx_queue_depth);
  assert(decoded.canRxQueueHighWater == status.can_rx_queue_high_water);
  assert(decoded.spiTxQueueDepth == status.spi_tx_queue_depth);
  assert(decoded.spiTxQueueHighWater == status.spi_tx_queue_high_water);
}

void testLoggerDiscoveryRequestProducesInventoryRecord() {
  constexpr uint32_t kSequence = 0x55667788u;
  CanMasterProtocol::Frame loggerRequest;
  assert(CanMasterProtocol::encodeDiscoveryRequest(
      2u, 17u, kSequence, loggerRequest));
  uint8_t request[BODAQS_MASTER_SLOT_BYTES] = {};
  uint8_t response[BODAQS_MASTER_SLOT_BYTES] = {};
  assert(CanMasterProtocol::encodeSlot(
      loggerRequest, request, sizeof(request)));

  BodaqsMasterIdentity identity = {};
  BodaqsMasterService service;
  bodaqs_master_service_init(&service, &identity);
  BodaqsMasterDiscoveryRecord records[
      BODAQS_MASTER_DISCOVERY_NODE_COUNT] = {};
  records[2].flags = BODAQS_MASTER_DISCOVERY_FLAG_PRESENT |
      BODAQS_MASTER_DISCOVERY_FLAG_STATUS_VALID;
  records[2].hardware_type = 3u;
  records[2].endpoint_mask = 0x001Fu;
  records[2].firmware_version = 0x00010002u;
  records[2].capabilities = 0x11223344u;
  records[2].hardware_uid = UINT64_C(0x0123456789ABCDEF);
  records[2].conflicting_hardware_uid =
      UINT64_C(0x8877665544332211);
  records[2].boot_id = 0xA5A55A5Au;
  records[2].last_seen_ms = 12345u;
  records[2].node_uptime_ms = 67890u;
  records[2].node_status_flags = 0x55AAu;
  records[2].can_rx_frames = 101u;
  records[2].can_tx_frames = 202u;
  records[2].can_error_events = 303u;
  records[2].tx_queue_high_water = 4u;
  bodaqs_master_service_set_inventory(&service, 18u, records,
      BODAQS_MASTER_DISCOVERY_NODE_COUNT);

  assert(bodaqs_master_service_process_slot(&service, request, response) ==
      BODAQS_MASTER_SLOT_PROCESSED);
  assert(service.discovery_requests_received == 1u);

  CanMasterProtocol::Frame loggerResponse;
  assert(CanMasterProtocol::decodeSlot(
             response, sizeof(response), loggerResponse) ==
      CanMasterProtocol::DecodeResult::Ok);
  assert(loggerResponse.sequence == kSequence);
  CanMasterProtocol::DiscoveryRecord decoded;
  assert(CanMasterProtocol::decodeDiscoveryResponse(
      loggerResponse, decoded));
  assert(decoded.nodeAddress == 2u);
  assert(decoded.nodeCount == 4u);
  assert(decoded.generation == 18u);
  assert(decoded.flags == records[2].flags);
  assert(decoded.hardwareType == records[2].hardware_type);
  assert(decoded.endpointMask == records[2].endpoint_mask);
  assert(decoded.firmwareVersion == records[2].firmware_version);
  assert(decoded.capabilities == records[2].capabilities);
  assert(decoded.hardwareUid == records[2].hardware_uid);
  assert(decoded.conflictingHardwareUid ==
      records[2].conflicting_hardware_uid);
  assert(decoded.bootId == records[2].boot_id);
  assert(decoded.lastSeenMs == records[2].last_seen_ms);
  assert(decoded.nodeUptimeMs == records[2].node_uptime_ms);
  assert(decoded.nodeStatusFlags == records[2].node_status_flags);
  assert(decoded.canRxFrames == records[2].can_rx_frames);
  assert(decoded.canTxFrames == records[2].can_tx_frames);
  assert(decoded.canErrorEvents == records[2].can_error_events);
  assert(decoded.txQueueHighWater == records[2].tx_queue_high_water);
}

}  // namespace

int main() {
  testLoggerProbeProducesMasterIdentity();
  testMasterAndLoggerCrcAgree();
  testMalformedRequestProducesNoResponse();
  testMalformedCrcIsClassified();
  testFetchConsumesPendingResponse();
  testLoggerStatusRequestProducesMasterStatus();
  testLoggerDiscoveryRequestProducesInventoryRecord();
  return 0;
}

