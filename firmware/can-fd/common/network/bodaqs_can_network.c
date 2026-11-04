#include "bodaqs_can_network.h"

#include <string.h>

typedef struct {
    uint8_t message_type;
    uint8_t flags;
    uint16_t transaction;
    uint8_t body_length;
} BodaqsCanEnvelope;

static void put_u16(uint8_t *out, uint16_t value)
{
    out[0] = (uint8_t) value;
    out[1] = (uint8_t) (value >> 8);
}

static void put_u32(uint8_t *out, uint32_t value)
{
    out[0] = (uint8_t) value;
    out[1] = (uint8_t) (value >> 8);
    out[2] = (uint8_t) (value >> 16);
    out[3] = (uint8_t) (value >> 24);
}

static void put_u64(uint8_t *out, uint64_t value)
{
    put_u32(out, (uint32_t) value);
    put_u32(out + 4, (uint32_t) (value >> 32));
}

static uint16_t get_u16(const uint8_t *in)
{
    return (uint16_t) in[0] | ((uint16_t) in[1] << 8);
}

static uint32_t get_u32(const uint8_t *in)
{
    return (uint32_t) in[0] |
        ((uint32_t) in[1] << 8) |
        ((uint32_t) in[2] << 16) |
        ((uint32_t) in[3] << 24);
}

static uint64_t get_u64(const uint8_t *in)
{
    return (uint64_t) get_u32(in) | ((uint64_t) get_u32(in + 4) << 32);
}

static void encode_envelope(uint8_t *payload, uint8_t message_type,
    uint16_t transaction, uint8_t body_length)
{
    payload[0] = BODAQS_CAN_PROTOCOL_MAJOR;
    payload[1] = message_type;
    payload[2] = BODAQS_CAN_BODY_VERSION_1;
    payload[3] = 0U;
    put_u16(payload + 4, transaction);
    payload[6] = body_length;
    payload[7] = 0U;
}

static BodaqsCanDecodeResult decode_envelope(const uint8_t *payload,
    size_t length, uint8_t expected_type, uint8_t expected_body_length,
    BodaqsCanEnvelope *envelope)
{
    if ((payload == NULL) || (envelope == NULL)) {
        return BODAQS_CAN_DECODE_INVALID_ARGUMENT;
    }
    if ((length < BODAQS_CAN_CONTROL_HEADER_BYTES) ||
        (length != (size_t) BODAQS_CAN_CONTROL_HEADER_BYTES +
                expected_body_length)) {
        return BODAQS_CAN_DECODE_INVALID_LENGTH;
    }
    if ((payload[0] != BODAQS_CAN_PROTOCOL_MAJOR) ||
        (payload[2] != BODAQS_CAN_BODY_VERSION_1)) {
        return BODAQS_CAN_DECODE_UNSUPPORTED_VERSION;
    }
    if (payload[1] != expected_type) {
        return BODAQS_CAN_DECODE_WRONG_TYPE;
    }
    if ((payload[3] != 0U) || (payload[7] != 0U)) {
        return BODAQS_CAN_DECODE_RESERVED_NONZERO;
    }
    if (payload[6] != expected_body_length) {
        return BODAQS_CAN_DECODE_INVALID_LENGTH;
    }

    envelope->message_type = payload[1];
    envelope->flags = payload[3];
    envelope->transaction = get_u16(payload + 4);
    envelope->body_length = payload[6];
    return BODAQS_CAN_DECODE_OK;
}

bool bodaqs_can_encode_discovery_request(
    const BodaqsCanDiscoveryRequest *request,
    uint8_t *payload,
    size_t capacity)
{
    if ((request == NULL) || (payload == NULL) ||
        (capacity < BODAQS_CAN_DISCOVERY_REQUEST_BYTES) ||
        (request->response_window_ms < BODAQS_CAN_MIN_DISCOVERY_WINDOW_MS)) {
        return false;
    }

    memset(payload, 0, BODAQS_CAN_DISCOVERY_REQUEST_BYTES);
    encode_envelope(payload, BODAQS_CAN_MESSAGE_DISCOVERY_REQUEST,
        request->transaction, 8U);
    put_u32(payload + 8, request->nonce);
    put_u16(payload + 12, request->response_window_ms);
    return true;
}

BodaqsCanDecodeResult bodaqs_can_decode_discovery_request(
    const uint8_t *payload,
    size_t length,
    BodaqsCanDiscoveryRequest *request)
{
    BodaqsCanEnvelope envelope;
    BodaqsCanDecodeResult result;

    if (request == NULL) {
        return BODAQS_CAN_DECODE_INVALID_ARGUMENT;
    }
    result = decode_envelope(payload, length,
        BODAQS_CAN_MESSAGE_DISCOVERY_REQUEST, 8U, &envelope);
    if (result != BODAQS_CAN_DECODE_OK) {
        return result;
    }
    if ((payload[14] != 0U) || (payload[15] != 0U)) {
        return BODAQS_CAN_DECODE_RESERVED_NONZERO;
    }

    request->transaction = envelope.transaction;
    request->nonce = get_u32(payload + 8);
    request->response_window_ms = get_u16(payload + 12);
    if (request->response_window_ms < BODAQS_CAN_MIN_DISCOVERY_WINDOW_MS) {
        return BODAQS_CAN_DECODE_INVALID_VALUE;
    }
    return BODAQS_CAN_DECODE_OK;
}

bool bodaqs_can_encode_node_announce(
    const BodaqsCanNodeAnnounce *announce,
    uint8_t *payload,
    size_t capacity)
{
    if ((announce == NULL) || (payload == NULL) ||
        (capacity < BODAQS_CAN_NODE_ANNOUNCE_BYTES) ||
        (announce->node_address >= BODAQS_CAN_NODE_COUNT) ||
        (announce->boot_id == 0U)) {
        return false;
    }

    memset(payload, 0, BODAQS_CAN_NODE_ANNOUNCE_BYTES);
    encode_envelope(payload, BODAQS_CAN_MESSAGE_NODE_ANNOUNCE,
        announce->transaction, 24U);
    payload[8] = announce->node_address;
    payload[9] = announce->hardware_type;
    put_u16(payload + 10, announce->endpoint_mask);
    put_u32(payload + 12, announce->firmware_version);
    put_u32(payload + 16, announce->capabilities);
    put_u64(payload + 20, announce->hardware_uid);
    put_u32(payload + 28, announce->boot_id);
    return true;
}

BodaqsCanDecodeResult bodaqs_can_decode_node_announce(
    const uint8_t *payload,
    size_t length,
    BodaqsCanNodeAnnounce *announce)
{
    BodaqsCanEnvelope envelope;
    BodaqsCanDecodeResult result;

    if (announce == NULL) {
        return BODAQS_CAN_DECODE_INVALID_ARGUMENT;
    }
    result = decode_envelope(payload, length,
        BODAQS_CAN_MESSAGE_NODE_ANNOUNCE, 24U, &envelope);
    if (result != BODAQS_CAN_DECODE_OK) {
        return result;
    }
    if ((payload[8] >= BODAQS_CAN_NODE_COUNT) ||
        (get_u32(payload + 28) == 0U)) {
        return BODAQS_CAN_DECODE_INVALID_VALUE;
    }

    announce->transaction = envelope.transaction;
    announce->node_address = payload[8];
    announce->hardware_type = payload[9];
    announce->endpoint_mask = get_u16(payload + 10);
    announce->firmware_version = get_u32(payload + 12);
    announce->capabilities = get_u32(payload + 16);
    announce->hardware_uid = get_u64(payload + 20);
    announce->boot_id = get_u32(payload + 28);
    return BODAQS_CAN_DECODE_OK;
}

bool bodaqs_can_encode_node_status(
    uint16_t transaction,
    const BodaqsCanNodeStatus *status,
    uint8_t *payload,
    size_t capacity)
{
    if ((status == NULL) || (payload == NULL) ||
        (capacity < BODAQS_CAN_NODE_STATUS_BYTES) ||
        (status->boot_id == 0U)) {
        return false;
    }

    memset(payload, 0, BODAQS_CAN_NODE_STATUS_BYTES);
    encode_envelope(payload, BODAQS_CAN_MESSAGE_NODE_STATUS,
        transaction, 24U);
    put_u32(payload + 8, status->boot_id);
    put_u32(payload + 12, status->uptime_ms);
    put_u32(payload + 16, status->status_flags);
    put_u32(payload + 20, status->can_rx_frames);
    put_u32(payload + 24, status->can_tx_frames);
    put_u16(payload + 28, status->can_error_events);
    put_u16(payload + 30, status->queue_high_water);
    return true;
}

BodaqsCanDecodeResult bodaqs_can_decode_node_status(
    const uint8_t *payload,
    size_t length,
    uint16_t *transaction,
    BodaqsCanNodeStatus *status)
{
    BodaqsCanEnvelope envelope;
    BodaqsCanDecodeResult result;

    if ((transaction == NULL) || (status == NULL)) {
        return BODAQS_CAN_DECODE_INVALID_ARGUMENT;
    }
    result = decode_envelope(payload, length,
        BODAQS_CAN_MESSAGE_NODE_STATUS, 24U, &envelope);
    if (result != BODAQS_CAN_DECODE_OK) {
        return result;
    }
    if (get_u32(payload + 8) == 0U) {
        return BODAQS_CAN_DECODE_INVALID_VALUE;
    }

    *transaction = envelope.transaction;
    status->boot_id = get_u32(payload + 8);
    status->uptime_ms = get_u32(payload + 12);
    status->status_flags = get_u32(payload + 16);
    status->can_rx_frames = get_u32(payload + 20);
    status->can_tx_frames = get_u32(payload + 24);
    status->can_error_events = get_u16(payload + 28);
    status->queue_high_water = get_u16(payload + 30);
    return BODAQS_CAN_DECODE_OK;
}

uint8_t bodaqs_can_length_to_dlc(size_t length)
{
    if (length <= 8U) {
        return (uint8_t) length;
    }
    switch (length) {
        case 12U: return 9U;
        case 16U: return 10U;
        case 20U: return 11U;
        case 24U: return 12U;
        case 32U: return 13U;
        case 48U: return 14U;
        case 64U: return 15U;
        default: return UINT8_MAX;
    }
}

size_t bodaqs_can_dlc_to_length(uint8_t dlc)
{
    static const uint8_t lengths[16] = {
        0U, 1U, 2U, 3U, 4U, 5U, 6U, 7U,
        8U, 12U, 16U, 20U, 24U, 32U, 48U, 64U
    };
    return dlc < 16U ? lengths[dlc] : 0U;
}

uint16_t bodaqs_can_announce_identifier(uint8_t node_address)
{
    return (uint16_t) (BODAQS_CAN_ID_ANNOUNCE_BASE + node_address);
}

uint16_t bodaqs_can_status_identifier(uint8_t node_address)
{
    return (uint16_t) (BODAQS_CAN_ID_STATUS_BASE + node_address);
}

bool bodaqs_can_identifier_node(
    uint16_t identifier,
    uint16_t base_identifier,
    uint8_t *node_address)
{
    uint16_t offset;

    if (node_address == NULL) {
        return false;
    }
    if (identifier < base_identifier) {
        return false;
    }
    offset = (uint16_t) (identifier - base_identifier);
    if (offset >= BODAQS_CAN_NODE_COUNT) {
        return false;
    }
    *node_address = (uint8_t) offset;
    return true;
}

uint16_t bodaqs_can_discovery_delay_ms(
    uint64_t hardware_uid,
    uint32_t nonce,
    uint8_t node_address,
    uint16_t response_window_ms)
{
    uint32_t hash;

    if (response_window_ms < BODAQS_CAN_MIN_DISCOVERY_WINDOW_MS) {
        return 0U;
    }
    hash = (uint32_t) hardware_uid ^ (uint32_t) (hardware_uid >> 32) ^ nonce;
    hash ^= (uint32_t) node_address * UINT32_C(0x9E3779B9);
    hash ^= hash >> 16;
    hash *= UINT32_C(0x7FEB352D);
    hash ^= hash >> 15;
    hash *= UINT32_C(0x846CA68B);
    hash ^= hash >> 16;
    return (uint16_t) (hash % response_window_ms);
}
