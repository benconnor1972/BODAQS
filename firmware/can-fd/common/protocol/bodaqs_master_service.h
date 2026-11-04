#ifndef BODAQS_MASTER_SERVICE_H
#define BODAQS_MASTER_SERVICE_H

#include "bodaqs_master_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    BodaqsMasterIdentity identity;
    BodaqsMasterStatus status;
    BodaqsMasterDiscoveryRecord
        discovery[BODAQS_MASTER_DISCOVERY_NODE_COUNT];
    uint32_t discovery_generation;
    uint32_t slots_received;
    uint32_t probes_received;
    uint32_t status_requests_received;
    uint32_t discovery_requests_received;
    uint32_t malformed_slots;
    uint32_t bad_magic_slots;
    uint32_t unsupported_version_slots;
    uint32_t invalid_length_slots;
    uint32_t bad_crc_slots;
    uint32_t invalid_argument_slots;
    BodaqsMasterDecodeResult last_decode_result;
} BodaqsMasterService;

typedef enum {
    BODAQS_MASTER_SLOT_PROCESSED = 0,
    BODAQS_MASTER_SLOT_MALFORMED
} BodaqsMasterSlotResult;

void bodaqs_master_service_init(BodaqsMasterService *service,
    const BodaqsMasterIdentity *identity);

void bodaqs_master_service_set_status(BodaqsMasterService *service,
    const BodaqsMasterStatus *status);

void bodaqs_master_service_set_inventory(BodaqsMasterService *service,
    uint32_t generation, const BodaqsMasterDiscoveryRecord *records,
    uint8_t record_count);

BodaqsMasterSlotResult bodaqs_master_service_process_slot(
    BodaqsMasterService *service,
    const uint8_t received[BODAQS_MASTER_SLOT_BYTES],
    uint8_t next_transmit[BODAQS_MASTER_SLOT_BYTES]);

#ifdef __cplusplus
}
#endif

#endif

