/* Private main-owner implementation, included by bodaqs_master_service.c.
 * All storage is caller-owned; no published unit aliases an ingress/DMA slot. */
#ifndef BODAQS_MASTER_WINDOW_H
#define BODAQS_MASTER_WINDOW_H
bool bodaqs_master_service_bind_window(BodaqsMasterService *s,BodaqsMasterWindowStorage *w) {
    if(!s || !w || s->measurement.mode.phase) return false;
    s->window=w;memset(w,0,sizeof(*w));return true;
}
static void window_clear_node(BodaqsMasterService *s,unsigned node) {
    if(!s->window) return;
    for(unsigned i=0;i<BODAQS_SAMPLE_WINDOW;++i) {
        BodaqsSampleWindowUnit *u=&s->window->units[node][i];
        s->retired_tail_frames+=u->count;
        /* Keep the exact retirement cache and allocator through a node fence. */
        u->count=0;memset(&u->object,0,sizeof(u->object));
    }
    s->retired_tail_frames+=s->window->evidence_count[node];
    s->window->evidence_count[node]=s->window->evidence_head[node]=0;
}
static void window_advance(BodaqsMasterService *s,uint8_t node,uint32_t now) {
    BodaqsMasterWindowStorage *w=s->window;
    BodaqsReceptionBatch *b=&s->receptions[node];
    BodaqsReceptionIngress *q=&s->ingress[node];
    if(!w) return;
    /* Independent, FIFO evidence head: samples never hold its publication. */
    if(!b->object.complete && w->evidence_count[node]) {
        const BodaqsRetainedReception *r=&w->evidence[node][w->evidence_head[node]];
        if(b->next_id[1]!=UINT32_MAX) {
            memset(b->bytes,0,16);b->cls=2;b->count=1;b->started_ms=r->received_ms;
            bodaqs_measurement_put(b->bytes,1,2);b->bytes[2]=2;b->bytes[3]=node;
            bodaqs_measurement_put(b->bytes+4,r->boot,4);
            bodaqs_measurement_put(b->bytes+8,r->ordinal_high,4);
            bodaqs_measurement_put(b->bytes+12,1,2);memcpy(b->bytes+16,r->bytes,76);
            ++b->next_id[1];
            (void)bodaqs_fragment_seal(&b->object,b->bytes,sizeof(b->bytes),s->transfer_context,
                b->next_id[1],node,2,1,92);
            w->evidence_head[node]=(uint8_t)((w->evidence_head[node]+1)%BODAQS_ESSENTIAL_QUEUE);
            --w->evidence_count[node];
        } else s->loss[node].failed=true;
    }
    for(unsigned work=0;work<BODAQS_SAMPLE_WINDOW;++work) {
        BodaqsSampleWindowUnit *u=NULL;uint32_t oldest=UINT32_MAX;
        for(unsigned i=0;i<BODAQS_SAMPLE_WINDOW;++i) {
            BodaqsSampleWindowUnit *candidate=&w->units[node][i];
            if(candidate->object.complete && candidate->object.object<oldest) oldest=candidate->object.object;
            if(candidate->count && !candidate->object.complete) u=candidate;
        }
        if(!u) {
            if(q->count && b->next_id[0]>=UINT32_MAX-BODAQS_SAMPLE_WINDOW) s->loss[node].failed=true;
            if(!q->count || b->next_id[0]>=UINT32_MAX-BODAQS_SAMPLE_WINDOW ||
               (oldest!=UINT32_MAX && b->next_id[0]-oldest>=BODAQS_SAMPLE_WINDOW-1)) return;
            u=&w->units[node][b->next_id[0]%BODAQS_SAMPLE_WINDOW];
            if(u->count || u->object.complete) return;
            const BodaqsRetainedReception *r=&q->records[q->head];
            memset(u->bytes,0,sizeof(u->bytes));u->started_ms=r->received_ms;u->attempts=0;
            bodaqs_measurement_put(u->bytes,2,2);u->bytes[2]=1;u->bytes[3]=node;
            bodaqs_measurement_put(u->bytes+4,r->boot,4);
            bodaqs_measurement_put(u->bytes+8,r->ordinal_high,4);
        }
        while(q->count && u->count<BODAQS_SAMPLE_PAYLOADS) {
            const BodaqsRetainedReception *r=&q->records[q->head];
            if(bodaqs_measurement_get(u->bytes+4,4)!=r->boot ||
               bodaqs_measurement_get(u->bytes+8,4)!=r->ordinal_high ||
               (u->count && (uint32_t)(r->received_ms-u->started_ms)>=20)) break;
            memcpy(u->bytes+16+64*u->count,r->bytes+12,64);++u->count;
            q->head=(uint16_t)((q->head+1)%BODAQS_MASTER_RETENTION_CAPACITY);--q->count;
        }
        if(u->count && (u->count==BODAQS_SAMPLE_PAYLOADS || q->count || (uint32_t)(now-u->started_ms)>=20)) {
            bodaqs_measurement_put(u->bytes+12,u->count,2);++b->next_id[0];
            (void)bodaqs_fragment_seal(&u->object,u->bytes,sizeof(u->bytes),s->transfer_context,
                b->next_id[0],node,1,1,(uint16_t)(16+64*u->count));
#if BODAQS_MASTER_PROGRESS_DIAGNOSTICS
            bodaqs_progress_seal(node,u,now,q->count!=0);
#endif
        } else return;
    }
}
static bool window_request_valid(const uint8_t *p) {
    for(unsigned n=0;n<4;++n) {
        const uint32_t base=(uint32_t)bodaqs_measurement_get(p+8*n,4);
        if(base>UINT32_MAX-BODAQS_SAMPLE_WINDOW || (p[8*n+4]&~15U) ||
           (!base && p[8*n+4]) || !bodaqs_measurement_zero(p+8*n+5,3)) return false;
    }
    return true;
}
/* The advertised [base,base+3] is bounded receiver RAM credit, never an ACK.
 * Present bits suppress repair of validated units already held by the logger. */
static BodaqsSampleWindowUnit *window_select(BodaqsMasterService *s,const uint8_t *credits,uint32_t now) {
    if(!s->window) return NULL;
    for(unsigned turn=0;turn<4;++turn) {
        const uint8_t n=(uint8_t)((s->fair_node[1]+turn)%4);
        const uint32_t base=(uint32_t)bodaqs_measurement_get(credits+8*n,4);
        window_advance(s,n,now);
        if(!base || s->loss[n].failed || s->isr_loss[n].failed) continue;
        for(unsigned i=0;i<BODAQS_SAMPLE_WINDOW;++i) {
            const unsigned index=(s->window->cursor[n]+i)%BODAQS_SAMPLE_WINDOW;
            BodaqsSampleWindowUnit *u=&s->window->units[n][index];
            if(!u->object.complete || u->object.object<base || u->object.object-base>=BODAQS_SAMPLE_WINDOW ||
               (credits[8*n+4]&(1U<<(u->object.object-base)))) continue;
            /* Eight unsuccessful repair deliveries plus 100ms exhaust only this
             * source. Published bytes remain owned until its explicit fence;
             * no invented count claims these possibly delivered rows were lost. */
            if(u->attempts>=8 && (uint32_t)(now-u->first_emit_ms)>=100) {
                s->loss[n].failed=true;++s->window->repair_failures[n];break;
            }
#if BODAQS_MASTER_PROGRESS_DIAGNOSTICS
            bodaqs_progress_prepare(n,u);
#endif
            if(!u->attempts) u->first_emit_ms=now;
            if(u->attempts<255) ++u->attempts;
            s->window->cursor[n]=(uint8_t)((index+1)%BODAQS_SAMPLE_WINDOW);
            s->fair_node[1]=(uint8_t)((n+1)%4);
            return u;
        }
    }
    return NULL;
}
static bool window_emit(BodaqsMasterService *s,const uint8_t *credits,uint32_t now,BodaqsMeasurementSlot *out) {
    const BodaqsSampleWindowUnit *u=window_select(s,credits,now);
    return u && bodaqs_fragment_emit(&u->object,u->bytes,0,out);
}
#endif
