#include <assert.h>
#include <stdint.h>
#include <string.h>

extern "C" {
#include "bodaqs_can_network.h"
#include "bodaqs_node_inventory.h"
}

namespace {

void testDiscoveryGoldenVector() {
  BodaqsCanDiscoveryRequest request = {};
  request.transaction = 0x1234u;
  request.nonce = 0x89ABCDEFu;
  request.response_window_ms = 64u;
  uint8_t payload[BODAQS_CAN_DISCOVERY_REQUEST_BYTES] = {};
  assert(bodaqs_can_encode_discovery_request(
      &request, payload, sizeof(payload)));

  const uint8_t expected[] = {
      0x01, 0x01, 0x01, 0x00, 0x34, 0x12, 0x08, 0x00,
      0xEF, 0xCD, 0xAB, 0x89, 0x40, 0x00, 0x00, 0x00};
  assert(memcmp(payload, expected, sizeof(expected)) == 0);

  BodaqsCanDiscoveryRequest decoded = {};
  assert(bodaqs_can_decode_discovery_request(
             payload, sizeof(payload), &decoded) == BODAQS_CAN_DECODE_OK);
  assert(decoded.transaction == request.transaction);
  assert(decoded.nonce == request.nonce);
  assert(decoded.response_window_ms == request.response_window_ms);
}

void testAnnounceGoldenVector() {
  BodaqsCanNodeAnnounce announce = {};
  announce.transaction = 0x5678u;
  announce.node_address = 2u;
  announce.hardware_type = BODAQS_CAN_HARDWARE_FULL_NODE;
  announce.endpoint_mask = 0x003Fu;
  announce.firmware_version = 0x00010002u;
  announce.capabilities = 0x11223344u;
  announce.hardware_uid = UINT64_C(0x0123456789ABCDEF);
  announce.boot_id = 0xA5A55A5Au;
  uint8_t payload[BODAQS_CAN_NODE_ANNOUNCE_BYTES] = {};
  assert(bodaqs_can_encode_node_announce(
      &announce, payload, sizeof(payload)));
  assert(payload[0] == 1u && payload[1] == 2u && payload[6] == 24u);
  assert(payload[8] == 2u && payload[9] == 1u);
  assert(payload[20] == 0xEFu && payload[27] == 0x01u);

  BodaqsCanNodeAnnounce decoded = {};
  assert(bodaqs_can_decode_node_announce(
             payload, sizeof(payload), &decoded) == BODAQS_CAN_DECODE_OK);
  assert(memcmp(&announce, &decoded, sizeof(announce)) == 0);
  assert(bodaqs_can_announce_identifier(2u) == 0x072u);
}

void testStatusRoundTrip() {
  BodaqsCanNodeStatus status = {};
  status.boot_id = 0x10203040u;
  status.uptime_ms = 123400u;
  status.status_flags = 0x55AAu;
  status.can_rx_frames = 10u;
  status.can_tx_frames = 11u;
  status.can_error_events = 12u;
  status.queue_high_water = 13u;
  uint8_t payload[BODAQS_CAN_NODE_STATUS_BYTES] = {};
  assert(bodaqs_can_encode_node_status(
      7u, &status, payload, sizeof(payload)));

  BodaqsCanNodeStatus decoded = {};
  uint16_t transaction = 0u;
  assert(bodaqs_can_decode_node_status(payload, sizeof(payload),
             &transaction, &decoded) == BODAQS_CAN_DECODE_OK);
  assert(transaction == 7u);
  assert(memcmp(&status, &decoded, sizeof(status)) == 0);
}

void testMalformedMessagesAreClassified() {
  BodaqsCanDiscoveryRequest request = {};
  request.response_window_ms = 64u;
  uint8_t payload[BODAQS_CAN_DISCOVERY_REQUEST_BYTES] = {};
  assert(bodaqs_can_encode_discovery_request(
      &request, payload, sizeof(payload)));
  assert(bodaqs_can_decode_discovery_request(
             payload, sizeof(payload) - 1u, &request) ==
      BODAQS_CAN_DECODE_INVALID_LENGTH);
  payload[0] = 2u;
  assert(bodaqs_can_decode_discovery_request(
             payload, sizeof(payload), &request) ==
      BODAQS_CAN_DECODE_UNSUPPORTED_VERSION);
  payload[0] = 1u;
  payload[15] = 1u;
  assert(bodaqs_can_decode_discovery_request(
             payload, sizeof(payload), &request) ==
      BODAQS_CAN_DECODE_RESERVED_NONZERO);
}

void testDlcAndIdentifiers() {
  assert(bodaqs_can_length_to_dlc(16u) == 10u);
  assert(bodaqs_can_length_to_dlc(32u) == 13u);
  assert(bodaqs_can_length_to_dlc(64u) == 15u);
  assert(bodaqs_can_length_to_dlc(17u) == UINT8_MAX);
  assert(bodaqs_can_dlc_to_length(10u) == 16u);
  assert(bodaqs_can_dlc_to_length(13u) == 32u);
  assert(bodaqs_can_dlc_to_length(15u) == 64u);

  uint8_t node = 0xFFu;
  assert(bodaqs_can_identifier_node(0x073u,
      BODAQS_CAN_ID_ANNOUNCE_BASE, &node));
  assert(node == 3u);
  assert(!bodaqs_can_identifier_node(0x074u,
      BODAQS_CAN_ID_ANNOUNCE_BASE, &node));
}

void testDiscoveryDelayIsBoundedAndNonceDependent() {
  const uint64_t uid = UINT64_C(0x1122334455667788);
  const uint16_t first = bodaqs_can_discovery_delay_ms(uid, 1u, 2u, 64u);
  const uint16_t second = bodaqs_can_discovery_delay_ms(uid, 2u, 2u, 64u);
  assert(first < 64u);
  assert(second < 64u);
  assert(first != second);
  assert(bodaqs_can_discovery_delay_ms(uid, 1u, 2u, 8u) == 0u);
}

void testInventoryTracksBootStaleAndDuplicate() {
  BodaqsNodeInventory inventory;
  bodaqs_node_inventory_init(&inventory);
  assert(inventory.generation == 1u);

  BodaqsCanNodeAnnounce announce = {};
  announce.node_address = 1u;
  announce.hardware_uid = UINT64_C(0x1111222233334444);
  announce.boot_id = 10u;
  assert(bodaqs_node_inventory_observe_announce(
      &inventory, &announce, 100u));
  assert(inventory.nodes[1].present);
  assert(!inventory.nodes[1].stale);
  assert(inventory.generation == 2u);

  BodaqsCanNodeStatus status = {};
  status.boot_id = 10u;
  status.uptime_ms = 200u;
  assert(bodaqs_node_inventory_observe_status(
      &inventory, 1u, &status, 200u));
  assert(inventory.generation == 3u);
  bodaqs_node_inventory_update_stale(&inventory, 3200u, 3000u);
  assert(!inventory.nodes[1].stale);
  bodaqs_node_inventory_update_stale(&inventory, 3201u, 3000u);
  assert(inventory.nodes[1].stale);
  assert(inventory.generation == 4u);
  bodaqs_node_inventory_update_stale(&inventory, 4000u, 3000u);
  assert(inventory.generation == 4u);

  announce.boot_id = 11u;
  assert(bodaqs_node_inventory_observe_announce(
      &inventory, &announce, 3300u));
  assert(inventory.nodes[1].boot_changes == 1u);
  assert(!inventory.nodes[1].stale);
  assert(inventory.generation == 5u);

  announce.hardware_uid = UINT64_C(0xAAAABBBBCCCCDDDD);
  assert(!bodaqs_node_inventory_observe_announce(
      &inventory, &announce, 3400u));
  assert(inventory.nodes[1].duplicate);
  assert(inventory.duplicate_observations == 1u);
  assert(inventory.nodes[1].conflicting_hardware_uid ==
      announce.hardware_uid);
  assert(inventory.generation == 6u);
}

}  // namespace

int main() {
  testDiscoveryGoldenVector();
  testAnnounceGoldenVector();
  testStatusRoundTrip();
  testMalformedMessagesAreClassified();
  testDlcAndIdentifiers();
  testDiscoveryDelayIsBoundedAndNonceDependent();
  testInventoryTracksBootStaleAndDuplicate();
  return 0;
}
