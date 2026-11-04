#include "bodaqs_master_service.h"

#include <string.h>

void bodaqs_master_service_init(BodaqsMasterService *service,
    const BodaqsMasterIdentity *identity)
{
    if (service == NULL) {
        return;
    }

    memset(service, 0, sizeof(*service));
    if (identity != NULL) {
        service->identity = *identity;
    }
    service->status.status_version = BODAQS_MASTER_STATUS_VERSION;
}

void bodaqs_master_service_set_status(BodaqsMasterService *service,
    const BodaqsMasterStatus *status)
{
    if ((service == NULL) || (status == NULL)) {
        return;
    }
    service->status = *status;
}

void bodaqs_master_service_set_inventory(BodaqsMasterService *service,
    uint32_t generation, const BodaqsMasterDiscoveryRecord *records,
    uint8_t record_count)
{
    uint8_t index;

    if ((service == NULL) || (records == NULL) ||
        (record_count != BODAQS_MASTER_DISCOVERY_NODE_COUNT)) {
        return;
    }

    if (generation == 0U) {
        generation = 1U;
    }
    service->discovery_generation = generation;
    for (index = 0U; index < BODAQS_MASTER_DISCOVERY_NODE_COUNT; ++index) {
        service->discovery[index] = records[index];
        service->discovery[index].node_address = index;
        service->discovery[index].node_count =
            BODAQS_MASTER_DISCOVERY_NODE_COUNT;
        service->discovery[index].generation = generation;
    }
}

BodaqsMasterSlotResult bodaqs_master_service_process_slot(
    BodaqsMasterService *service,
    const uint8_t received[BODAQS_MASTER_SLOT_BYTES],
    uint8_t next_transmit[BODAQS_MASTER_SLOT_BYTES])
{
    BodaqsMasterFrame request;
    BodaqsMasterDiscoveryRequest discovery_request;
    BodaqsMasterDecodeResult result;

    if ((service == NULL) || (received == NULL) ||
        (next_transmit == NULL)) {
        return BODAQS_MASTER_SLOT_MALFORMED;
    }

    memset(next_transmit, 0, BODAQS_MASTER_SLOT_BYTES);
    ++service->slots_received;
    result = bodaqs_master_decode_slot(
        received, BODAQS_MASTER_SLOT_BYTES, &request);
    service->last_decode_result = result;
    if (result != BODAQS_MASTER_DECODE_OK) {
        ++service->malformed_slots;
        switch (result) {
        case BODAQS_MASTER_DECODE_BAD_MAGIC:
            ++service->bad_magic_slots;
            break;
        case BODAQS_MASTER_DECODE_UNSUPPORTED_VERSION:
            ++service->unsupported_version_slots;
            break;
        case BODAQS_MASTER_DECODE_INVALID_LENGTH:
            ++service->invalid_length_slots;
            break;
        case BODAQS_MASTER_DECODE_BAD_CRC:
            ++service->bad_crc_slots;
            break;
        case BODAQS_MASTER_DECODE_INVALID_ARGUMENT:
            ++service->invalid_argument_slots;
            break;
        case BODAQS_MASTER_DECODE_OK:
        default:
            break;
        }
        return BODAQS_MASTER_SLOT_MALFORMED;
    }

    if ((request.type == BODAQS_MASTER_MESSAGE_PROBE_REQUEST) &&
        (request.payload_length == 0U) && (request.sequence != 0U)) {
        ++service->probes_received;
        (void) bodaqs_master_encode_identity_response(&service->identity,
            request.sequence, next_transmit, BODAQS_MASTER_SLOT_BYTES);
    } else if ((request.type == BODAQS_MASTER_MESSAGE_STATUS_REQUEST) &&
        (request.payload_length == 0U) && (request.sequence != 0U)) {
        ++service->status_requests_received;
        service->status.slots_received = service->slots_received;
        service->status.malformed_slots = service->malformed_slots;
        service->status.probes_received = service->probes_received;
        service->status.status_requests_received =
            service->status_requests_received;
        (void) bodaqs_master_encode_status_response(&service->status,
            request.sequence, next_transmit, BODAQS_MASTER_SLOT_BYTES);
    } else if ((request.sequence != 0U) &&
        bodaqs_master_decode_discovery_request(
            &request, &discovery_request)) {
        ++service->discovery_requests_received;
        (void) bodaqs_master_encode_discovery_response(
            &service->discovery[discovery_request.node_address],
            request.sequence, next_transmit, BODAQS_MASTER_SLOT_BYTES);
    }
    return BODAQS_MASTER_SLOT_PROCESSED;
}

