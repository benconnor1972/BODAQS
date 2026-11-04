#ifndef BODAQS_MASTER_PROTOCOL_H
#define BODAQS_MASTER_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BODAQS_MASTER_PROTOCOL_VERSION (1U)
#define BODAQS_MASTER_HEADER_BYTES (16U)
#define BODAQS_MASTER_PAYLOAD_BYTES (64U)
#define BODAQS_MASTER_SLOT_BYTES (84U)
#define BODAQS_MASTER_IDENTITY_BYTES (20U)
#define BODAQS_MASTER_STATUS_BYTES (52U)
#define BODAQS_MASTER_STATUS_VERSION (1U)
#define BODAQS_MASTER_DISCOVERY_VERSION (1U)
#define BODAQS_MASTER_DISCOVERY_REQUEST_BYTES (8U)
#define BODAQS_MASTER_DISCOVERY_RESPONSE_BYTES (64U)
#define BODAQS_MASTER_DISCOVERY_NODE_COUNT (4U)

#define BODAQS_MASTER_CAPABILITY_STATUS (1UL << 0)
#define BODAQS_MASTER_CAPABILITY_DISCOVERY (1UL << 1)

#define BODAQS_MASTER_DISCOVERY_FLAG_PRESENT (1U << 0)
#define BODAQS_MASTER_DISCOVERY_FLAG_STALE (1U << 1)
#define BODAQS_MASTER_DISCOVERY_FLAG_DUPLICATE (1U << 2)
#define BODAQS_MASTER_DISCOVERY_FLAG_STATUS_VALID (1U << 3)

#define BODAQS_MASTER_STATUS_FLAG_BUCK_ENABLED (1U << 0)
#define BODAQS_MASTER_STATUS_FLAG_FRONT_ENABLED (1U << 1)
#define BODAQS_MASTER_STATUS_FLAG_REAR_ENABLED (1U << 2)
#define BODAQS_MASTER_STATUS_FLAG_FRONT_FAULT (1U << 3)
#define BODAQS_MASTER_STATUS_FLAG_REAR_FAULT (1U << 4)
#define BODAQS_MASTER_STATUS_FLAG_CAN_INITIALIZED (1U << 5)
#define BODAQS_MASTER_STATUS_FLAG_CAN_BUS_OFF (1U << 6)
#define BODAQS_MASTER_STATUS_FLAG_CLOCK_FAULT (1U << 7)

typedef enum {
    BODAQS_MASTER_MESSAGE_NONE = 0x00,
    BODAQS_MASTER_MESSAGE_PROBE_REQUEST = 0x01,
    BODAQS_MASTER_MESSAGE_FETCH_RESPONSE = 0x02,
    BODAQS_MASTER_MESSAGE_STATUS_REQUEST = 0x03,
    BODAQS_MASTER_MESSAGE_DISCOVERY_REQUEST = 0x04,
    BODAQS_MASTER_MESSAGE_IDENTITY_RESPONSE = 0x81,
    BODAQS_MASTER_MESSAGE_STATUS_RESPONSE = 0x83,
    BODAQS_MASTER_MESSAGE_DISCOVERY_RESPONSE = 0x84,
    BODAQS_MASTER_MESSAGE_ERROR_RESPONSE = 0xFF
} BodaqsMasterMessageType;

typedef enum {
    BODAQS_MASTER_DECODE_OK = 0,
    BODAQS_MASTER_DECODE_INVALID_ARGUMENT,
    BODAQS_MASTER_DECODE_BAD_MAGIC,
    BODAQS_MASTER_DECODE_UNSUPPORTED_VERSION,
    BODAQS_MASTER_DECODE_INVALID_LENGTH,
    BODAQS_MASTER_DECODE_BAD_CRC
} BodaqsMasterDecodeResult;

typedef struct {
    BodaqsMasterMessageType type;
    uint16_t flags;
    uint32_t sequence;
    uint16_t payload_length;
    uint8_t payload[BODAQS_MASTER_PAYLOAD_BYTES];
} BodaqsMasterFrame;

typedef struct {
    uint32_t firmware_version;
    uint32_t capabilities;
    uint64_t hardware_uid;
    uint16_t minimum_protocol_version;
    uint16_t maximum_protocol_version;
} BodaqsMasterIdentity;

typedef struct {
    uint16_t status_version;
    uint16_t flags;
    uint32_t uptime_ms;
    uint32_t reset_cause;
    uint32_t slots_received;
    uint32_t malformed_slots;
    uint32_t probes_received;
    uint32_t status_requests_received;
    uint32_t spi_recoveries;
    uint32_t can_rx_frames;
    uint32_t can_tx_frames;
    uint32_t can_error_events;
    uint16_t can_rx_queue_depth;
    uint16_t can_rx_queue_high_water;
    uint16_t spi_tx_queue_depth;
    uint16_t spi_tx_queue_high_water;
} BodaqsMasterStatus;

typedef struct {
    uint8_t node_address;
    uint32_t expected_generation;
} BodaqsMasterDiscoveryRequest;

typedef struct {
    uint8_t node_address;
    uint8_t node_count;
    uint8_t flags;
    uint32_t generation;
    uint8_t hardware_type;
    uint16_t endpoint_mask;
    uint32_t firmware_version;
    uint32_t capabilities;
    uint64_t hardware_uid;
    uint64_t conflicting_hardware_uid;
    uint32_t boot_id;
    uint32_t last_seen_ms;
    uint32_t node_uptime_ms;
    uint32_t node_status_flags;
    uint32_t can_rx_frames;
    uint32_t can_tx_frames;
    uint16_t can_error_events;
    uint16_t tx_queue_high_water;
} BodaqsMasterDiscoveryRecord;

uint32_t bodaqs_master_crc32(const uint8_t *data, size_t length);

bool bodaqs_master_encode_slot(const BodaqsMasterFrame *frame,
    uint8_t *output, size_t capacity);

BodaqsMasterDecodeResult bodaqs_master_decode_slot(const uint8_t *input,
    size_t length, BodaqsMasterFrame *output);

bool bodaqs_master_encode_identity_response(
    const BodaqsMasterIdentity *identity, uint32_t sequence,
    uint8_t *output, size_t capacity);

bool bodaqs_master_encode_status_response(const BodaqsMasterStatus *status,
    uint32_t sequence, uint8_t *output, size_t capacity);

bool bodaqs_master_decode_discovery_request(const BodaqsMasterFrame *frame,
    BodaqsMasterDiscoveryRequest *request);

bool bodaqs_master_encode_discovery_response(
    const BodaqsMasterDiscoveryRecord *record, uint32_t sequence,
    uint8_t *output, size_t capacity);

#ifdef __cplusplus
}
#endif

#endif

