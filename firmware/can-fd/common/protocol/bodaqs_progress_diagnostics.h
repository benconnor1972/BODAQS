#ifndef BODAQS_PROGRESS_DIAGNOSTICS_H
#define BODAQS_PROGRESS_DIAGNOSTICS_H
#include "bodaqs_master_service.h"
#include <string.h>
#include "bodaqs_reply_census.h"

#ifndef BODAQS_MASTER_PROGRESS_DIAGNOSTICS
#define BODAQS_MASTER_PROGRESS_DIAGNOSTICS 0
#endif
#if BODAQS_MASTER_PROGRESS_DIAGNOSTICS != 0 && BODAQS_MASTER_PROGRESS_DIAGNOSTICS != 1
#error "Progress diagnostics must be 0 or 1"
#endif
#if BODAQS_MASTER_PROGRESS_DIAGNOSTICS
#if BODAQS_MEASUREMENT_VERSION < 4 || !BODAQS_MASTER_PHASE_TIMING
#error "Progress diagnostics require window transport and steady phase timing"
#endif
/* Main owner only. Counter observations never grant credit or retire data.
 * Targets: 0 idle, 1..5 fetch class, 6 ACK only, 7 other.
 * Empty sample state columns are overlapping per-node observations:
 * credit zero, failed, eligible, held, outside credit, partial, ingress,
 * allocation pinned by oldest unretired object, no sample work.
 * Ages are modulo uint32 ms. Totals are for short bench runs (< one wrap).
 * Preparation is not physical delivery; receive-to-ACK is not SD durability. */
typedef struct {
    uint32_t sealed_payloads[16], seal_reasons[3]; /* full, boundary, age */
    uint32_t seal_age_total_ms, seal_age_max_ms;
    uint32_t retired, receive_to_ack_total_ms, receive_to_ack_max_ms;
    uint32_t prepared_acked, first_prepare_to_ack_total_ms, first_prepare_to_ack_max_ms;
    uint32_t first_preparations, repeat_preparations;
    uint32_t empty_states[9];
} BodaqsProgressNode;
typedef struct {
    uint32_t version, size_bytes, state, reserved;
    uint64_t context, recording;
    uint32_t replies[8][16];
    uint32_t empty_with_published_samples[8];
    BodaqsProgressNode node[4];
} BodaqsProgressDiagnostics;
extern volatile BodaqsProgressDiagnostics gMasterProgressInfo;
static inline void bodaqs_progress_reset(uint64_t context,uint64_t recording) {
    memset((void *)&gMasterProgressInfo,0,sizeof gMasterProgressInfo);
    gMasterProgressInfo.version=1;gMasterProgressInfo.size_bytes=sizeof gMasterProgressInfo;
    gMasterProgressInfo.context=context;gMasterProgressInfo.recording=recording;
#if BODAQS_MASTER_REPLY_CENSUS
    bodaqs_reply_census_reset(context,recording);
#endif
}
static inline void bodaqs_progress_age(volatile uint32_t *total,volatile uint32_t *maximum,uint32_t age) {
    *total+=age;if(age>*maximum) *maximum=age;
}
static inline void bodaqs_progress_seal(unsigned node,const BodaqsSampleWindowUnit *u,uint32_t now,bool boundary) {
    if(gMasterProgressInfo.state!=2) return;
    volatile BodaqsProgressNode *d=&gMasterProgressInfo.node[node];
    if(u->count<16) ++d->sealed_payloads[u->count];
    ++d->seal_reasons[u->count==BODAQS_SAMPLE_PAYLOADS?0:boundary?1:2];
    bodaqs_progress_age(&d->seal_age_total_ms,&d->seal_age_max_ms,now-u->started_ms);
}
static inline void bodaqs_progress_retire(unsigned node,const BodaqsSampleWindowUnit *u,uint32_t now) {
    if(gMasterProgressInfo.state!=2) return;
    volatile BodaqsProgressNode *d=&gMasterProgressInfo.node[node];
    ++d->retired;
    bodaqs_progress_age(&d->receive_to_ack_total_ms,&d->receive_to_ack_max_ms,now-u->started_ms);
    if(u->attempts) {
        ++d->prepared_acked;
        bodaqs_progress_age(&d->first_prepare_to_ack_total_ms,&d->first_prepare_to_ack_max_ms,now-u->first_emit_ms);
    }
}
static inline void bodaqs_progress_prepare(unsigned node,const BodaqsSampleWindowUnit *u) {
    if(gMasterProgressInfo.state!=2) return;
    if(u->attempts) ++gMasterProgressInfo.node[node].repeat_preparations;
    else ++gMasterProgressInfo.node[node].first_preparations;
}
static inline void bodaqs_progress_reply(const BodaqsMasterService *s,
    const BodaqsMeasurementSlot *request,const BodaqsMeasurementSlot *reply) {
    if(gMasterProgressInfo.state!=2) return;
#if BODAQS_MASTER_REPLY_CENSUS
    bodaqs_reply_census_record(reply);
#endif
    unsigned target=7;
    if(request->kind==0) target=0;
    else if(request->kind==5) target=6;
    else if(request->kind==15) target=1;
    else if(request->kind==14) target=request->body[2];
    else if(request->kind==1) target=request->body[0];
    if(target>7) target=7;
    if(reply->kind<16) ++gMasterProgressInfo.replies[target][reply->kind];
    if(reply->kind || !s->window) return;
    const uint8_t *credits=request->kind==15?request->body:
        request->kind==14 && target==1?request->body+16:NULL;
    bool published=false;
    for(unsigned n=0;n<4;++n) {
        bool complete=false,partial=false,eligible=false,held=false,outside=false;
        uint32_t oldest=UINT32_MAX;
        const uint32_t base=credits?(uint32_t)bodaqs_measurement_get(credits+8*n,4):0;
        for(unsigned i=0;i<BODAQS_SAMPLE_WINDOW;++i) {
            const BodaqsSampleWindowUnit *u=&s->window->units[n][i];
            partial|=u->count && !u->object.complete;
            if(!u->object.complete) continue;
            complete=true;
            if(u->object.object<oldest) oldest=u->object.object;
            if(base && u->object.object>=base && u->object.object-base<BODAQS_SAMPLE_WINDOW) {
                if(credits[8*n+4]&(1U<<(u->object.object-base))) held=true;
                else eligible=true;
            } else outside=true;
        }
        published|=complete;
        if(!credits) continue;
        volatile uint32_t *d=gMasterProgressInfo.node[n].empty_states;
        if(!base) ++d[0];
        if(s->loss[n].failed || s->isr_loss[n].failed) ++d[1];
        if(eligible) ++d[2];
        if(held) ++d[3];
        if(outside) ++d[4];
        if(partial) ++d[5];
        if(s->ingress[n].count) ++d[6];
        if(oldest!=UINT32_MAX && s->receptions[n].next_id[0]-oldest>=BODAQS_SAMPLE_WINDOW-1) ++d[7];
        if(!complete && !partial && !s->ingress[n].count) ++d[8];
    }
    if(published) ++gMasterProgressInfo.empty_with_published_samples[target];
}
#endif
#endif
