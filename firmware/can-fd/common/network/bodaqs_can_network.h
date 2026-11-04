#ifndef BODAQS_CAN_NETWORK_H
#define BODAQS_CAN_NETWORK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BODAQS_CAN_PROTOCOL_MAJOR (1U)
#define BODAQS_CAN_BODY_VERSION_1 (1U)
#define BODAQS_CAN_NODE_COUNT (4U)

#define BODAQS_CAN_ID_SYNC_MARKER (0x020U)
#define BODAQS_CAN_ID_BROADCAST_CONTROL (0x030U)
#define BODAQS_CAN_ID_TARGET_REQUEST_BASE (0x040U)
#define BODAQS_CAN_ID_RESPONSE_BASE (0x050U)
#define BODAQS_CAN_ID_EVENT_BASE (0x060U)
#define BODAQS_CAN_ID_ANNOUNCE_BASE (0x070U)
#define BODAQS_CAN_ID_STATUS_BASE (0x080U)
#define BODAQS_CAN_ID_TIMING_BASE (0x090U)
#define BODAQS_CAN_ID_STREAM_BASE (0x100U)

#define BODAQS_CAN_CONTROL_HEADER_BYTES (8U)
#define BODAQS_CAN_DISCOVERY_REQUEST_BYTES (16U)
#define BODAQS_CAN_NODE_ANNOUNCE_BYTES (32U)
#define BODAQS_CAN_NODE_STATUS_BYTES (32U)

#define BODAQS_CAN_MIN_DISCOVERY_WINDOW_MS (16U)
#define BODAQS_CAN_DEFAULT_DISCOVERY_WINDOW_MS (64U)

#define BODAQS_CAN_HARDWARE_FULL_NODE (1U)
#define BODAQS_CAN_HARDWARE_NO_IMU_NODE (2U)
#define BODAQS_CAN_HARDWARE_NO_I2C_NODE (3U)
#define BODAQS_CAN_HARDWARE_IMU_ONLY_NODE (4U)

#define BODAQS_CAN_ENDPOINT_IMU (0U)
#define BODAQS_CAN_ENDPOINT_ANALOG_0 (1U)
#define BODAQS_CAN_ENDPOINT_ANALOG_1 (2U)
#define BODAQS_CAN_ENDPOINT_I2C_0 (3U)
#define BODAQS_CAN_ENDPOINT_I2C_1 (4U)
#define BODAQS_CAN_ENDPOINT_GPIO (5U)

#define BODAQS_CAN_ENDPOINT_MASK(endpoint) ((uint16_t) (1U << (endpoint)))

typedef enum {
    BODAQS_CAN_MESSAGE_DISCOVERY_REQUEST = 0x01,
    BODAQS_CAN_MESSAGE_NODE_ANNOUNCE = 0x02,
    BODAQS_CAN_MESSAGE_NODE_STATUS = 0x03,
    BODAQS_CAN_MESSAGE_NODE_EVENT = 0x04,
    BODAQS_CAN_MESSAGE_CONFIG_REQUEST = 0x10,
    BODAQS_CAN_MESSAGE_CONFIG_RESULT = 0x11,
    BODAQS_CAN_MESSAGE_SYNC_MARKER = 0x20,
    BODAQS_CAN_MESSAGE_SYNC_CAPTURE = 0x21,
    BODAQS_CAN_MESSAGE_STREAM_ANCHOR = 0x22
} BodaqsCanMessageType;

typedef enum {
    BODAQS_CAN_DECODE_OK = 0,
    BODAQS_CAN_DECODE_INVALID_ARGUMENT,
    BODAQS_CAN_DECODE_INVALID_LENGTH,
    BODAQS_CAN_DECODE_UNSUPPORTED_VERSION,
    BODAQS_CAN_DECODE_WRONG_TYPE,
    BODAQS_CAN_DECODE_RESERVED_NONZERO,
    BODAQS_CAN_DECODE_INVALID_VALUE
} BodaqsCanDecodeResult;

typedef struct {
    uint16_t transaction;
    uint32_t nonce;
    uint16_t response_window_ms;
} BodaqsCanDiscoveryRequest;

typedef struct {
    uint16_t transaction;
    uint8_t node_address;
    uint8_t hardware_type;
    uint16_t endpoint_mask;
    uint32_t firmware_version;
    uint32_t capabilities;
    uint64_t hardware_uid;
    uint32_t boot_id;
} BodaqsCanNodeAnnounce;

typedef struct {
    uint32_t boot_id;
    uint32_t uptime_ms;
    uint32_t status_flags;
    uint32_t can_rx_frames;
    uint32_t can_tx_frames;
    uint16_t can_error_events;
    uint16_t queue_high_water;
} BodaqsCanNodeStatus;

bool bodaqs_can_encode_discovery_request(
    const BodaqsCanDiscoveryRequest *request,
    uint8_t *payload,
    size_t capacity);

BodaqsCanDecodeResult bodaqs_can_decode_discovery_request(
    const uint8_t *payload,
    size_t length,
    BodaqsCanDiscoveryRequest *request);

bool bodaqs_can_encode_node_announce(
    const BodaqsCanNodeAnnounce *announce,
    uint8_t *payload,
    size_t capacity);

BodaqsCanDecodeResult bodaqs_can_decode_node_announce(
    const uint8_t *payload,
    size_t length,
    BodaqsCanNodeAnnounce *announce);

bool bodaqs_can_encode_node_status(
    uint16_t transaction,
    const BodaqsCanNodeStatus *status,
    uint8_t *payload,
    size_t capacity);

BodaqsCanDecodeResult bodaqs_can_decode_node_status(
    const uint8_t *payload,
    size_t length,
    uint16_t *transaction,
    BodaqsCanNodeStatus *status);

uint8_t bodaqs_can_length_to_dlc(size_t length);
size_t bodaqs_can_dlc_to_length(uint8_t dlc);

uint16_t bodaqs_can_announce_identifier(uint8_t node_address);
uint16_t bodaqs_can_status_identifier(uint8_t node_address);
bool bodaqs_can_identifier_node(
    uint16_t identifier,
    uint16_t base_identifier,
    uint8_t *node_address);

uint16_t bodaqs_can_discovery_delay_ms(
    uint64_t hardware_uid,
    uint32_t nonce,
    uint8_t node_address,
    uint16_t response_window_ms);

#ifdef __cplusplus
}
#endif

#endif
