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
    service->measurement.quiescent = true;
    service->measurement.fenced = true;
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
    uint8_t excluded = 0U;

    if ((service == NULL) || (records == NULL) ||
        (record_count != BODAQS_MASTER_DISCOVERY_NODE_COUNT)) {
        return;
    }

    if (generation == 0U) {
        generation = 1U;
    }
    service->discovery_generation = generation;
    for (index = 0U; index < BODAQS_MASTER_DISCOVERY_NODE_COUNT; ++index) {
        if (records[index].flags & BODAQS_MASTER_DISCOVERY_FLAG_DUPLICATE)
            excluded |= (uint8_t)(1U << index);
        service->discovery[index] = records[index];
        service->discovery[index].node_address = index;
        service->discovery[index].node_count =
            BODAQS_MASTER_DISCOVERY_NODE_COUNT;
        service->discovery[index].generation = generation;
    }
    bodaqs_control_exchange_exclude(&service->control, excluded);
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

    if ((service->control.master_boot_id != 0U) && (request.sequence != 0U) &&
        (request.flags == 0U) && ((unsigned)request.type >= BODAQS_CONTROL_INFO_REQUEST) && ((unsigned)request.type <= BODAQS_CONTROL_POLL_REQUEST)) {
        BodaqsMasterFrame response;
        BodaqsControlWrapped wrapped, reply;
        uint8_t type;
        memset(&response, 0, sizeof(response));
        response.sequence = request.sequence;
        if (((unsigned)request.type == BODAQS_CONTROL_INFO_REQUEST) && (request.payload_length == 0U)) {
            response.type = (BodaqsMasterMessageType)BODAQS_CONTROL_INFO_RESPONSE;
            response.payload_length = 32;
            bodaqs_control_info(service->control.master_boot_id, response.payload);
        } else if (((unsigned)request.type != BODAQS_CONTROL_INFO_REQUEST) &&
            bodaqs_control_decode_wrapped(request.payload, request.payload_length, &wrapped) &&
            bodaqs_control_exchange_request(&service->control, (unsigned)request.type == BODAQS_CONTROL_POLL_REQUEST, &wrapped, &reply, &type)) {
            response.type = (BodaqsMasterMessageType)type;
            response.payload_length = 64;
            (void)bodaqs_control_encode_wrapped(&reply, response.payload);
        } else {
            ++service->malformed_slots;
            return BODAQS_MASTER_SLOT_MALFORMED;
        }
        (void)bodaqs_master_encode_slot(&response, next_transmit, BODAQS_MASTER_SLOT_BYTES);
        return BODAQS_MASTER_SLOT_PROCESSED;
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

void bodaqs_master_service_measurement_fence(BodaqsMasterService *service,
    bool stopped_authorization_invalid, bool data_retired)
{
    service->measurement.quiescent = stopped_authorization_invalid;
    service->measurement.fenced = data_retired;
}

BodaqsMasterSlotResult bodaqs_master_service_process_transfer(
    BodaqsMasterService *service, const uint8_t *received, size_t length,
    uint32_t now_ms, uint8_t next_transmit[BODAQS_MASTER_SLOT_BYTES])
{
    BodaqsMasterFrame request, response;
    BodaqsMeasurementMode requested, observed;
    BodaqsMeasurementSlot slot, reply;
    uint16_t reason = 0;
    if (!service || !received || !next_transmit) return BODAQS_MASTER_SLOT_MALFORMED;
    service->measurement.mode.boot = service->control.master_boot_id;
    bodaqs_measurement_tick(&service->measurement, now_ms);
    memset(next_transmit, 0, BODAQS_MASTER_SLOT_BYTES);
    if (length == 64) {
        if (!bodaqs_measurement_decode(received, length, &slot) ||
            !bodaqs_measurement_manage(&service->measurement, &slot, now_ms, &reply))
            goto malformed;
        (void)bodaqs_measurement_encode(&reply, next_transmit, 64);
        ++service->slots_received;
        return BODAQS_MASTER_SLOT_PROCESSED;
    }
    if (length != 84 || bodaqs_master_decode_slot(received, length, &request) != BODAQS_MASTER_DECODE_OK)
        goto malformed;
    if ((unsigned)request.type >= 8 && (unsigned)request.type <= 10) {
        if (!request.sequence || request.flags) goto malformed;
        if ((unsigned)request.type == 10) {
            if (request.payload_length != 16 || !bodaqs_measurement_get(request.payload,8)) goto malformed;
            if (bodaqs_measurement_get(request.payload+8,8) &&
                bodaqs_measurement_get(request.payload+8,8) != service->control.master_boot_id) reason=4;
        } else {
            unsigned i;
            if (!bodaqs_measurement_mode_decode(request.payload,request.payload_length,&requested)) goto malformed;
            /* Do not enter while old ordinary control is awaiting a result. */
            for(i=0;i<4;++i) if(service->control.slots[i].state==1) reason=8;
            if (!reason) reason=bodaqs_measurement_stage(&service->measurement,&requested,
                request.sequence,now_ms,(unsigned)request.type==9);
        }
        observed=service->measurement.mode; observed.reason=reason;
        if (observed.phase==0) {
            observed.version=1; observed.maximum=1024;
            observed.physical=84; observed.hz=4000000; observed.gap=1000;
        }
        observed.flags=(service->measurement.mode.phase==2?1U:0U) |
            (service->measurement.fenced?2U:0U) | (!service->measurement.quiescent?4U:0U);
        observed.caller=(unsigned)request.type==10 ? bodaqs_measurement_get(request.payload,8) : requested.caller;
        memset(&response,0,sizeof(response)); response.type=(BodaqsMasterMessageType)((unsigned)request.type|0x80);
        response.sequence=request.sequence; response.payload_length=64;
        bodaqs_measurement_mode_encode(&observed,response.payload);
        (void)bodaqs_master_encode_slot(&response,next_transmit,84);
        ++service->slots_received;
        return BODAQS_MASTER_SLOT_PROCESSED;
    }
    /* Live measurement mode has no ordinary legacy dispatch. Restricted
     * administrative cleanup is installed by the acquisition lifecycle slice. */
    if (service->measurement.mode.phase != 0 && (unsigned)request.type != 2 &&
        (unsigned)request.type != 5 && (unsigned)request.type != 7) goto malformed;
    return bodaqs_master_service_process_slot(service,received,next_transmit);
malformed:
    ++service->malformed_slots;
    return BODAQS_MASTER_SLOT_MALFORMED;
}
