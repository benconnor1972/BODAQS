#ifndef BODAQS_MASTER_SERVICE_H
#define BODAQS_MASTER_SERVICE_H

#include "bodaqs_master_protocol.h"
#include "bodaqs_control_exchange.h"
#include "bodaqs_fragment_transport.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    BodaqsFragmentState object;
    uint8_t bytes[1024];
    uint32_t started_ms, next_id[2];
    uint16_t count;
    uint8_t cls;
} BodaqsReceptionBatch;
typedef struct {
    BodaqsFragmentState rx, tx;
    uint8_t incoming[68], outgoing[68];
    uint32_t next_id;
    bool awaiting_result;
    uint8_t rx_rejection;
} BodaqsMeasurementControlLane;
typedef struct {
    BodaqsControlExchange control;
    BodaqsControlExchange authorization;
    BodaqsReceptionBatch receptions[4];
    BodaqsMeasurementControlLane lanes[2][4];
    BodaqsFragmentState master_evidence;
    uint8_t master_evidence_bytes[1024];
    uint32_t master_evidence_next_id;
    uint64_t reception_ordinal, transfer_context;
    uint32_t retained_frames, backpressure_frames, objects_acked, transfer_errors;
    BodaqsFragmentState acknowledged[5][4];
    uint8_t fair_node[6];
    uint32_t anchor_boot[4], anchor_sequence[4];
    uint8_t anchor_epoch[4];
    uint32_t ordinary_budget_ms, authorization_budget_ms[4];
    uint8_t ordinary_tokens, authorization_tokens[4];
    BodaqsMeasurementState measurement;
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

/* Capture timestamp is supplied by the CAN ISR/driver, never poll time. False
 * reports bounded backpressure; caller must account for the lost reception. */
bool bodaqs_master_service_receive_can(BodaqsMasterService *, uint8_t node,
    uint8_t cls, uint16_t identifier, const uint8_t *payload, uint8_t length,
    uint8_t flags, uint32_t receive_tick, uint32_t now_ms);
/* Hardware ingress supplies the ISR-assigned global ordinal, including gaps
 * from dropped/unforwarded CAN traffic. The convenience ingress above allocates
 * a local ordinal for host callers without a capture driver. */
bool bodaqs_master_service_receive_can_ordered(BodaqsMasterService *, uint8_t node,
    uint8_t cls, uint16_t identifier, const uint8_t *payload, uint8_t length,
    uint8_t flags, uint32_t receive_tick, uint64_t ordinal, uint32_t now_ms);
bool bodaqs_master_service_control_transmit(BodaqsMasterService *, uint32_t now,
    uint8_t *, uint16_t *, uint8_t payload[64]);
bool bodaqs_master_service_control_receive(BodaqsMasterService *, uint8_t,
    uint16_t, const BodaqsControlRecord *);
bool bodaqs_master_service_publish_evidence(BodaqsMasterService *, const uint8_t *, uint16_t);
void bodaqs_master_service_init(BodaqsMasterService *service,
    const BodaqsMasterIdentity *identity);

void bodaqs_master_service_set_status(BodaqsMasterService *service,
    const BodaqsMasterStatus *status);

/* Publish current inventory before SPI admission and after CAN discovery changes,
 * before every dispatch/retry. Duplicate routes fence mutating control traffic. */
void bodaqs_master_service_set_inventory(BodaqsMasterService *service,
    uint32_t generation, const BodaqsMasterDiscoveryRecord *records,
    uint8_t record_count);

/* Actual CS-bounded length: short or oversized transfers never change mode. */
BodaqsMasterSlotResult bodaqs_master_service_process_transfer(
    BodaqsMasterService *service, const uint8_t *received, size_t length,
    uint32_t now_ms, uint8_t next_transmit[BODAQS_MASTER_SLOT_BYTES]);
void bodaqs_master_service_measurement_fence(BodaqsMasterService *service,
    bool stopped_authorization_invalid, bool data_retired);

BodaqsMasterSlotResult bodaqs_master_service_process_slot(
    BodaqsMasterService *service,
    const uint8_t received[BODAQS_MASTER_SLOT_BYTES],
    uint8_t next_transmit[BODAQS_MASTER_SLOT_BYTES]);

#ifdef __cplusplus
}
#endif

#endif

