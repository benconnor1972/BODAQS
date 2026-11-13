#ifndef BODAQS_BATCH_DIAGNOSTICS_H
#define BODAQS_BATCH_DIAGNOSTICS_H
#include <stdint.h>
#include <string.h>
#include "bodaqs_measurement.h"
#ifndef BODAQS_MASTER_BATCH_DIAGNOSTICS
#define BODAQS_MASTER_BATCH_DIAGNOSTICS 0
#endif
#if BODAQS_MASTER_BATCH_DIAGNOSTICS != 0 && BODAQS_MASTER_BATCH_DIAGNOSTICS != 1
#error "Batch diagnostics must be 0 or 1"
#endif
/* Main-owner observations only. Prepared fragments are NOT physical deliveries.
 * Histograms: class index 0=sample, 1=evidence; counts include cleanup.
 * Reasons: full, class change, identity change, reception span, age, evidence.
 * Millisecond differences use the existing service clock, modulo uint32_t.
 * Intended captures are shorter than one clock wrap. No scheduling feedback. */
typedef struct {
    uint32_t sealed[2], retired[2], discarded[2], records[2][14], reasons[2][6];
    uint64_t seal_age_total_ms[2], reception_span_total_ms[2];
    uint32_t seal_age_max_ms[2], reception_span_max_ms[2];
    uint64_t ingress_at_seal_total[2], residence_total_ms[2], prepared_to_ack_total_ms[2];
    uint32_t ingress_at_seal_max[2], residence_max_ms[2], prepared_to_ack_max_ms[2];
    uint32_t fresh_preparations[2], repeat_preparations[2], retired_without_all_prepared[2];
    /* Current-head bookkeeping, not additional queue ownership. */
    uint32_t last_arrival_ms, sealed_ms, all_prepared_ms, prepared_mask, all_prepared;
} BodaqsBatchNodeDiagnostics;
typedef struct {
    uint32_t version, size_bytes;
    uint32_t context_lo, context_hi, session_lo, session_hi;
    uint32_t recording_lo, recording_hi, boot_lo, boot_hi;
    BodaqsBatchNodeDiagnostics node[4];
} BodaqsBatchDiagnostics;
#if BODAQS_MASTER_BATCH_DIAGNOSTICS
extern BodaqsBatchDiagnostics gMasterBatchInfo;
static inline void bodaqs_batch_diag_reset(uint64_t context,uint64_t session,
    uint64_t recording,uint64_t boot) {
    memset(&gMasterBatchInfo,0,sizeof gMasterBatchInfo);
    gMasterBatchInfo.version=1;gMasterBatchInfo.size_bytes=sizeof gMasterBatchInfo;
    gMasterBatchInfo.context_lo=(uint32_t)context;gMasterBatchInfo.context_hi=(uint32_t)(context>>32);
    gMasterBatchInfo.session_lo=(uint32_t)session;gMasterBatchInfo.session_hi=(uint32_t)(session>>32);
    gMasterBatchInfo.recording_lo=(uint32_t)recording;gMasterBatchInfo.recording_hi=(uint32_t)(recording>>32);
    gMasterBatchInfo.boot_lo=(uint32_t)boot;gMasterBatchInfo.boot_hi=(uint32_t)(boot>>32);
}
static inline void bodaqs_batch_diag_add(uint64_t* total,uint32_t* maximum,uint32_t value) {
    *total+=value;if(value>*maximum) *maximum=value;
}
static inline void bodaqs_batch_diag_seal(uint8_t node,uint8_t cls,uint16_t count,
    uint8_t reason,uint32_t now,uint32_t first,uint16_t ingress) {
    BodaqsBatchNodeDiagnostics* d=&gMasterBatchInfo.node[node];unsigned c=cls-1;
    ++d->sealed[c];++d->records[c][count];++d->reasons[c][reason];
    bodaqs_batch_diag_add(&d->seal_age_total_ms[c],&d->seal_age_max_ms[c],now-first);
    bodaqs_batch_diag_add(&d->reception_span_total_ms[c],&d->reception_span_max_ms[c],d->last_arrival_ms-first);
    bodaqs_batch_diag_add(&d->ingress_at_seal_total[c],&d->ingress_at_seal_max[c],ingress);
    d->sealed_ms=now;d->prepared_mask=0;d->all_prepared=0;d->all_prepared_ms=0;
}
static inline void bodaqs_batch_diag_emit(uint8_t node,uint8_t cls,uint8_t index,
    uint16_t total,uint32_t now) {
    BodaqsBatchNodeDiagnostics* d=&gMasterBatchInfo.node[node];unsigned c=cls-1;
    uint32_t bit=1UL<<index;
    if(d->prepared_mask&bit) ++d->repeat_preparations[c];
    else {++d->fresh_preparations[c];d->prepared_mask|=bit;}
    uint32_t full=(1UL<<((total+BODAQS_MEASUREMENT_BODY_BYTES-1U)/BODAQS_MEASUREMENT_BODY_BYTES))-1U;
    if(!d->all_prepared && d->prepared_mask==full) {d->all_prepared=1;d->all_prepared_ms=now;}
}
static inline void bodaqs_batch_diag_retire(uint8_t node,uint8_t cls,uint32_t now) {
    BodaqsBatchNodeDiagnostics* d=&gMasterBatchInfo.node[node];unsigned c=cls-1;
    ++d->retired[c];
    bodaqs_batch_diag_add(&d->residence_total_ms[c],&d->residence_max_ms[c],now-d->sealed_ms);
    if(d->all_prepared) bodaqs_batch_diag_add(&d->prepared_to_ack_total_ms[c],&d->prepared_to_ack_max_ms[c],now-d->all_prepared_ms);
    else ++d->retired_without_all_prepared[c];
}
#endif
#endif
