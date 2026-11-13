#ifndef BODAQS_MASTER_SERVICE_H
#define BODAQS_MASTER_SERVICE_H

#include "bodaqs_master_protocol.h"
#include "bodaqs_control_exchange.h"
#include "bodaqs_fragment_transport.h"
#define BODAQS_MASTER_TRANSFER_BYTES (BODAQS_MEASUREMENT_BYTES>84U?BODAQS_MEASUREMENT_BYTES:84U)

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

/* Independent of the immutable selected head. Admission must charge this exact
 * representation and its finite burst/service envelope, not just CAN axes. */
#define BODAQS_MASTER_RETENTION_CAPACITY 128U
#ifndef BODAQS_MASTER_BOUNDARY_RESERVE
#define BODAQS_MASTER_BOUNDARY_RESERVE 0
#endif
#if BODAQS_MASTER_BOUNDARY_RESERVE != 0 && BODAQS_MASTER_BOUNDARY_RESERVE != 2
#error "Boundary reserve must be 0 or 2"
#endif
#if BODAQS_MASTER_BOUNDARY_RESERVE && BODAQS_MEASUREMENT_VERSION < 2
#error "Boundary reserve requires measurement v2"
#endif
typedef struct {
    uint8_t bytes[76];
    uint32_t boot, ordinal_high, received_ms;
    uint8_t cls;
} BodaqsRetainedReception;
#if BODAQS_MEASUREMENT_VERSION >= 4
#define BODAQS_SAMPLE_WINDOW 4U
#define BODAQS_ESSENTIAL_QUEUE 16U
#define BODAQS_ESSENTIAL_RESERVE 4U
typedef struct {
    BodaqsFragmentState object, acknowledged;
    uint8_t bytes[216];
    uint32_t started_ms, first_emit_ms;
    uint16_t count;
    uint8_t attempts;
} BodaqsSampleWindowUnit;
typedef struct {
    BodaqsSampleWindowUnit units[4][BODAQS_SAMPLE_WINDOW];
    BodaqsRetainedReception evidence[4][BODAQS_ESSENTIAL_QUEUE];
    uint8_t evidence_head[4], evidence_count[4], cursor[4];
    uint32_t repair_failures[4];
} BodaqsMasterWindowStorage;
#endif
typedef struct {
    BodaqsRetainedReception records[BODAQS_MASTER_RETENTION_CAPACITY];
    uint16_t head, count, high_water;
    uint32_t dropped;
} BodaqsReceptionIngress;
typedef struct {
    uint32_t source, evidence, first, last, tick, last_report_ms;
    uint32_t reported_source,reported_evidence;
    uint64_t ordinal;
    uint8_t epoch, stage;
    bool failed, gap,failure_reported;
} BodaqsReceptionLoss;
typedef struct {
    BodaqsFragmentState rx, tx;
    uint8_t incoming[68], outgoing[68];
    uint32_t next_id;
    bool awaiting_result;
    uint8_t rx_rejection;
} BodaqsMeasurementControlLane;
typedef struct {
    uint32_t (*native_clock)(void *, uint32_t *epoch);
#if BODAQS_MEASUREMENT_VERSION >= 4
    /* Caller-owned, main-loop only. Target places this entire bank in BANK1;
     * logical retention is separate from DMA/CS-retired physical buffers. */
    BodaqsMasterWindowStorage *window;
#endif
    void *clock_context;
    uint64_t bridge_context;
    uint32_t bridge_token, bridge_tick, bridge_epoch;
    BodaqsControlExchange control;
    BodaqsControlExchange authorization;
    BodaqsReceptionBatch receptions[4];
    BodaqsReceptionIngress ingress[4];
    BodaqsReceptionLoss loss[4];
    BodaqsReceptionLoss isr_loss[4];
    uint32_t loss_report_ms[4];
    uint8_t loss_report_stage[4];
    BodaqsMeasurementControlLane lanes[2][4];
    BodaqsFragmentState master_evidence;
    uint8_t master_evidence_bytes[1024];
    uint32_t master_evidence_next_id;
    uint64_t reception_ordinal, transfer_context;
    uint64_t transfer_session, transfer_recording, transfer_boot;
    uint32_t retained_frames, backpressure_frames, objects_acked, transfer_errors;
    uint32_t retired_tail_frames;
    BodaqsFragmentState acknowledged[5][4];
    uint8_t fair_node[6];
    uint32_t anchor_boot[4], anchor_sequence[4];
    uint8_t anchor_epoch[4];
    uint32_t ordinary_budget_ms, authorization_budget_ms[4];
    uint8_t ordinary_tokens, authorization_tokens[4];
    uint32_t lifecycle_budget_ms, acquisition_operation[4];
    uint8_t lifecycle_tokens, lifecycle_next_node;
    uint8_t acquisition_started;
    uint32_t diagnostic_operation[4];
    uint64_t diagnostic_session[4];
    /* Conservative membership survives lost COMMIT/STOP replies. A node fence
     * and physical SPI retirement are separate proofs. */
    uint64_t acquisition_record[4];
    uint32_t acquisition_boot[4], acquisition_fence_operation[4];
    uint8_t acquisition_fenced;
    bool acquisition_retirement_pending;
    /* Main-owner generation: every completed node fence invalidates prior
     * physical SPI retirement evidence, even within the same context. */
    uint32_t acquisition_retirement_generation;
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
/* Main-loop owner reports an observed rejected reception (including ISR queue
 * rejects copied out under the hardware adapter's IRQ fence). */
void bodaqs_master_service_loss(BodaqsMasterService *,uint8_t node,uint8_t stage,
    uint8_t cls,const uint8_t *payload,uint8_t length,uint32_t tick,uint64_t ordinal);
void bodaqs_master_service_loss_counts(BodaqsMasterService *,uint8_t node,uint8_t stage,
    uint8_t epoch,uint16_t first,uint16_t last,uint32_t source,uint32_t evidence,
    bool essential,uint32_t tick,uint64_t ordinal);
void bodaqs_master_service_init(BodaqsMasterService *service,
    const BodaqsMasterIdentity *identity);
#if BODAQS_MEASUREMENT_VERSION >= 4
/* Bind once after init, before entry. Storage outlives the service. */
bool bodaqs_master_service_bind_window(BodaqsMasterService *, BodaqsMasterWindowStorage *);
#endif

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
    uint32_t now_ms, uint8_t next_transmit[BODAQS_MASTER_TRANSFER_BYTES]);
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

