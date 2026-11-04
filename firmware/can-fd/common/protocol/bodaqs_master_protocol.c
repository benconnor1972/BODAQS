#include "bodaqs_master_protocol.h"

#include <string.h>

static const uint8_t kMagic[4] = {'B', 'C', 'M', '1'};

static void put_u16(uint8_t *output, uint16_t value)
{
    output[0] = (uint8_t) value;
    output[1] = (uint8_t) (value >> 8);
}

static void put_u32(uint8_t *output, uint32_t value)
{
    uint8_t index;
    for (index = 0; index < 4U; ++index) {
        output[index] = (uint8_t) (value >> (8U * index));
    }
}

static void put_u64(uint8_t *output, uint64_t value)
{
    uint8_t index;
    for (index = 0; index < 8U; ++index) {
        output[index] = (uint8_t) (value >> (8U * index));
    }
}

static uint16_t get_u16(const uint8_t *input)
{
    return (uint16_t) input[0] | ((uint16_t) input[1] << 8);
}

static uint32_t get_u32(const uint8_t *input)
{
    return (uint32_t) input[0] | ((uint32_t) input[1] << 8) |
        ((uint32_t) input[2] << 16) | ((uint32_t) input[3] << 24);
}

uint32_t bodaqs_master_crc32(const uint8_t *data, size_t length)
{
    static const uint32_t nibble_table[16] = {
        0x00000000U, 0x1DB71064U, 0x3B6E20C8U, 0x26D930ACU,
        0x76DC4190U, 0x6B6B51F4U, 0x4DB26158U, 0x5005713CU,
        0xEDB88320U, 0xF00F9344U, 0xD6D6A3E8U, 0xCB61B38CU,
        0x9B64C2B0U, 0x86D3D2D4U, 0xA00AE278U, 0xBDBDF21CU
    };
    uint32_t crc = 0xFFFFFFFFU;
    size_t index;

    if ((data == NULL) && (length != 0U)) {
        return 0U;
    }

    for (index = 0; index < length; ++index) {
        crc ^= data[index];
        crc = (crc >> 4) ^ nibble_table[crc & 0x0FU];
        crc = (crc >> 4) ^ nibble_table[crc & 0x0FU];
    }
    return ~crc;
}

bool bodaqs_master_encode_slot(const BodaqsMasterFrame *frame,
    uint8_t *output, size_t capacity)
{
    if ((frame == NULL) || (output == NULL) ||
        (capacity < BODAQS_MASTER_SLOT_BYTES) ||
        (frame->payload_length > BODAQS_MASTER_PAYLOAD_BYTES)) {
        return false;
    }

    memset(output, 0, BODAQS_MASTER_SLOT_BYTES);
    memcpy(output, kMagic, sizeof(kMagic));
    output[4] = BODAQS_MASTER_PROTOCOL_VERSION;
    output[5] = (uint8_t) frame->type;
    put_u16(output + 6, frame->flags);
    put_u32(output + 8, frame->sequence);
    put_u16(output + 12, frame->payload_length);
    if (frame->payload_length != 0U) {
        memcpy(output + BODAQS_MASTER_HEADER_BYTES, frame->payload,
            frame->payload_length);
    }
    put_u32(output + BODAQS_MASTER_HEADER_BYTES + BODAQS_MASTER_PAYLOAD_BYTES,
        bodaqs_master_crc32(output,
            BODAQS_MASTER_HEADER_BYTES + BODAQS_MASTER_PAYLOAD_BYTES));
    return true;
}

BodaqsMasterDecodeResult bodaqs_master_decode_slot(const uint8_t *input,
    size_t length, BodaqsMasterFrame *output)
{
    uint16_t payload_length;
    uint32_t expected_crc;

    if ((input == NULL) || (output == NULL)) {
        return BODAQS_MASTER_DECODE_INVALID_ARGUMENT;
    }

    memset(output, 0, sizeof(*output));
    if (length != BODAQS_MASTER_SLOT_BYTES) {
        return BODAQS_MASTER_DECODE_INVALID_LENGTH;
    }
    if (memcmp(input, kMagic, sizeof(kMagic)) != 0) {
        return BODAQS_MASTER_DECODE_BAD_MAGIC;
    }
    if (input[4] != BODAQS_MASTER_PROTOCOL_VERSION) {
        return BODAQS_MASTER_DECODE_UNSUPPORTED_VERSION;
    }

    payload_length = get_u16(input + 12);
    if (payload_length > BODAQS_MASTER_PAYLOAD_BYTES) {
        return BODAQS_MASTER_DECODE_INVALID_LENGTH;
    }
    expected_crc = get_u32(
        input + BODAQS_MASTER_HEADER_BYTES + BODAQS_MASTER_PAYLOAD_BYTES);
    if (bodaqs_master_crc32(input,
            BODAQS_MASTER_HEADER_BYTES + BODAQS_MASTER_PAYLOAD_BYTES) !=
        expected_crc) {
        return BODAQS_MASTER_DECODE_BAD_CRC;
    }

    output->type = (BodaqsMasterMessageType) input[5];
    output->flags = get_u16(input + 6);
    output->sequence = get_u32(input + 8);
    output->payload_length = payload_length;
    if (payload_length != 0U) {
        memcpy(output->payload, input + BODAQS_MASTER_HEADER_BYTES,
            payload_length);
    }
    return BODAQS_MASTER_DECODE_OK;
}

bool bodaqs_master_encode_identity_response(
    const BodaqsMasterIdentity *identity, uint32_t sequence,
    uint8_t *output, size_t capacity)
{
    BodaqsMasterFrame frame;

    if (identity == NULL) {
        return false;
    }

    memset(&frame, 0, sizeof(frame));
    frame.type = BODAQS_MASTER_MESSAGE_IDENTITY_RESPONSE;
    frame.sequence = sequence;
    frame.payload_length = BODAQS_MASTER_IDENTITY_BYTES;
    put_u32(frame.payload, identity->firmware_version);
    put_u32(frame.payload + 4, identity->capabilities);
    put_u64(frame.payload + 8, identity->hardware_uid);
    put_u16(frame.payload + 16, identity->minimum_protocol_version);
    put_u16(frame.payload + 18, identity->maximum_protocol_version);
    return bodaqs_master_encode_slot(&frame, output, capacity);
}

bool bodaqs_master_encode_status_response(const BodaqsMasterStatus *status,
    uint32_t sequence, uint8_t *output, size_t capacity)
{
    BodaqsMasterFrame frame;

    if (status == NULL) {
        return false;
    }

    memset(&frame, 0, sizeof(frame));
    frame.type = BODAQS_MASTER_MESSAGE_STATUS_RESPONSE;
    frame.sequence = sequence;
    frame.payload_length = BODAQS_MASTER_STATUS_BYTES;
    put_u16(frame.payload, status->status_version);
    put_u16(frame.payload + 2, status->flags);
    put_u32(frame.payload + 4, status->uptime_ms);
    put_u32(frame.payload + 8, status->reset_cause);
    put_u32(frame.payload + 12, status->slots_received);
    put_u32(frame.payload + 16, status->malformed_slots);
    put_u32(frame.payload + 20, status->probes_received);
    put_u32(frame.payload + 24, status->status_requests_received);
    put_u32(frame.payload + 28, status->spi_recoveries);
    put_u32(frame.payload + 32, status->can_rx_frames);
    put_u32(frame.payload + 36, status->can_tx_frames);
    put_u32(frame.payload + 40, status->can_error_events);
    put_u16(frame.payload + 44, status->can_rx_queue_depth);
    put_u16(frame.payload + 46, status->can_rx_queue_high_water);
    put_u16(frame.payload + 48, status->spi_tx_queue_depth);
    put_u16(frame.payload + 50, status->spi_tx_queue_high_water);
    return bodaqs_master_encode_slot(&frame, output, capacity);
}

bool bodaqs_master_decode_discovery_request(const BodaqsMasterFrame *frame,
    BodaqsMasterDiscoveryRequest *request)
{
    if ((frame == NULL) || (request == NULL) ||
        (frame->type != BODAQS_MASTER_MESSAGE_DISCOVERY_REQUEST) ||
        (frame->payload_length != BODAQS_MASTER_DISCOVERY_REQUEST_BYTES) ||
        (frame->payload[0] != BODAQS_MASTER_DISCOVERY_VERSION) ||
        (frame->payload[1] >= BODAQS_MASTER_DISCOVERY_NODE_COUNT) ||
        (frame->payload[2] != 0U) || (frame->payload[3] != 0U)) {
        return false;
    }

    request->node_address = frame->payload[1];
    request->expected_generation = get_u32(frame->payload + 4);
    return true;
}

bool bodaqs_master_encode_discovery_response(
    const BodaqsMasterDiscoveryRecord *record, uint32_t sequence,
    uint8_t *output, size_t capacity)
{
    BodaqsMasterFrame frame;

    if ((record == NULL) ||
        (record->node_address >= BODAQS_MASTER_DISCOVERY_NODE_COUNT) ||
        (record->node_count != BODAQS_MASTER_DISCOVERY_NODE_COUNT)) {
        return false;
    }

    memset(&frame, 0, sizeof(frame));
    frame.type = BODAQS_MASTER_MESSAGE_DISCOVERY_RESPONSE;
    frame.sequence = sequence;
    frame.payload_length = BODAQS_MASTER_DISCOVERY_RESPONSE_BYTES;
    frame.payload[0] = BODAQS_MASTER_DISCOVERY_VERSION;
    frame.payload[1] = record->node_address;
    frame.payload[2] = record->node_count;
    frame.payload[3] = record->flags;
    put_u32(frame.payload + 4, record->generation);
    frame.payload[8] = record->hardware_type;
    frame.payload[9] = 0U;
    put_u16(frame.payload + 10, record->endpoint_mask);
    put_u32(frame.payload + 12, record->firmware_version);
    put_u32(frame.payload + 16, record->capabilities);
    put_u64(frame.payload + 20, record->hardware_uid);
    put_u64(frame.payload + 28, record->conflicting_hardware_uid);
    put_u32(frame.payload + 36, record->boot_id);
    put_u32(frame.payload + 40, record->last_seen_ms);
    put_u32(frame.payload + 44, record->node_uptime_ms);
    put_u32(frame.payload + 48, record->node_status_flags);
    put_u32(frame.payload + 52, record->can_rx_frames);
    put_u32(frame.payload + 56, record->can_tx_frames);
    put_u16(frame.payload + 60, record->can_error_events);
    put_u16(frame.payload + 62, record->tx_queue_high_water);
    return bodaqs_master_encode_slot(&frame, output, capacity);
}

