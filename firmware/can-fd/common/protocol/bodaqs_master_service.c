#include "bodaqs_timing.h"
#include "bodaqs_master_service.h"
#include "bodaqs_master_profile.h"

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
    service->ordinary_tokens = 4;service->lifecycle_tokens=4;
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
    bodaqs_control_exchange_exclude(&service->authorization, excluded);
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
    unsigned node;
    bool all=true;
    for(node=0;node<4;++node)
        if(service->acquisition_record[node] && !(service->acquisition_fenced & (1U<<node))) all=false;
    service->measurement.quiescent = all && stopped_authorization_invalid;
    service->measurement.fenced = all && stopped_authorization_invalid && data_retired;
    if(service->measurement.fenced) {
        for(node=0;node<4;++node) {
            service->retired_tail_frames += service->receptions[node].count + service->ingress[node].count;
            service->ingress[node].head=service->ingress[node].count=0;
            service->receptions[node].count=0;
            memset(&service->receptions[node].object,0,sizeof(service->receptions[node].object));
            service->anchor_boot[node]=0;
        }
        service->master_evidence.complete=0;
        service->acquisition_retirement_pending=false;
    }
}


static void transfer_context(BodaqsMasterService *s) {
    if(s->transfer_context==s->measurement.mode.context &&
       s->transfer_session==s->measurement.mode.session &&
       s->transfer_recording==s->measurement.mode.recording &&
       s->transfer_boot==s->control.master_boot_id) return;
    memset(s->receptions,0,sizeof(s->receptions));
    memset(s->ingress,0,sizeof(s->ingress));
    memset(s->loss,0,sizeof(s->loss));
    memset(s->isr_loss,0,sizeof(s->isr_loss));
    memset(s->loss_report_ms,0,sizeof(s->loss_report_ms));
    memset(s->loss_report_stage,0,sizeof(s->loss_report_stage));
    memset(s->lanes,0,sizeof(s->lanes));
    memset(s->acknowledged,0,sizeof(s->acknowledged));
    memset(&s->master_evidence,0,sizeof(s->master_evidence));
    s->master_evidence_next_id=0;
    s->transfer_context=s->measurement.mode.context;
    s->transfer_session=s->measurement.mode.session;
    s->transfer_recording=s->measurement.mode.recording;
    s->transfer_boot=s->control.master_boot_id;
    s->bridge_context=0;s->bridge_token=0;s->bridge_tick=0;s->bridge_epoch=0;
    bodaqs_control_exchange_init(&s->authorization,s->control.master_boot_id);
    s->authorization.excluded_addresses=s->control.excluded_addresses;
    memset(s->anchor_boot,0,sizeof(s->anchor_boot));
    s->acquisition_started=0;
    memset(s->diagnostic_operation,0,sizeof(s->diagnostic_operation));
    memset(s->authorization_tokens,2,sizeof(s->authorization_tokens));
}
static bool next_object(uint32_t *id) {
    if(*id==UINT32_MAX) return false;
    ++*id; return true;
}
static bool seal_receptions(BodaqsMasterService *s,uint8_t node) {
    BodaqsReceptionBatch *b=&s->receptions[node];
    if(b->object.complete) return true;
    if(!b->count || !next_object(&b->next_id[b->cls-1])) return false;
    bodaqs_measurement_put(b->bytes+12,b->count,2);
    return bodaqs_fragment_seal(&b->object,b->bytes,sizeof(b->bytes),s->transfer_context,
        b->next_id[b->cls-1],node,b->cls,1,(uint16_t)(16+b->count*76));
}
/* Only the main-loop owner moves ingress into the selected head. Queued records
 * retain their original reception order, boot and oldest-arrival deadline. */
static void advance_receptions(BodaqsMasterService *s,uint8_t node,uint32_t now) {
    BodaqsReceptionBatch *b=&s->receptions[node];
    BodaqsReceptionIngress *q=&s->ingress[node];
    if(b->object.complete) return;
    if(b->count>=13) { (void)seal_receptions(s,node); return; }
    while(q->count) {
        const BodaqsRetainedReception *r=&q->records[q->head];
        if(b->count && (b->cls!=r->cls ||
           bodaqs_measurement_get(b->bytes+4,4)!=r->boot ||
           bodaqs_measurement_get(b->bytes+8,4)!=r->ordinal_high ||
           (uint32_t)(r->received_ms-b->started_ms)>=20)) {
            (void)seal_receptions(s,node); return;
        }
        if(!b->count) {
            memset(b->bytes,0,16); b->cls=r->cls; b->started_ms=r->received_ms;
            bodaqs_measurement_put(b->bytes,1,2); b->bytes[2]=r->cls; b->bytes[3]=node;
            bodaqs_measurement_put(b->bytes+4,r->boot,4);
            bodaqs_measurement_put(b->bytes+8,r->ordinal_high,4);
        }
        memcpy(b->bytes+16+b->count*76,r->bytes,76); ++b->count;
        q->head=(uint16_t)((q->head+1U)%BODAQS_MASTER_RETENTION_CAPACITY); --q->count;
        /* Evidence/boundaries never wait for normal sample-batch filling. */
        if(b->cls==2 || b->count==13) { (void)seal_receptions(s,node); return; }
    }
    if(b->count && (uint32_t)(now-b->started_ms)>=20) (void)seal_receptions(s,node);
}
bool bodaqs_master_service_receive_can(BodaqsMasterService *s,uint8_t node,
    uint8_t cls,uint16_t identifier,const uint8_t *payload,uint8_t length,
    uint8_t flags,uint32_t tick,uint32_t now) {
    if(!s || s->reception_ordinal==UINT64_MAX) return false;
    return bodaqs_master_service_receive_can_ordered(s,node,cls,identifier,payload,length,flags,
        tick,s->reception_ordinal+1,now);
}
void bodaqs_master_service_loss(BodaqsMasterService *s,uint8_t node,uint8_t stage,
    uint8_t cls,const uint8_t *p,uint8_t length,uint32_t tick,uint64_t ordinal) {
    BodaqsReceptionLoss *l; uint32_t count;
    if(!s || !p || node>3 || !s->acquisition_record[node]) return;
    l=&s->loss[node]; l->stage=stage; l->tick=tick; l->ordinal=ordinal;
    if(cls==1 && length>=4 && (count=p[3]&7)!=0 && count<=5) {
#if BODAQS_MEASUREMENT_VERSION == 2
        /* Count is known; low16 alone cannot locate the full interval. */
        l->first=l->last=0;l->gap=false;
#else
        uint32_t first=s->anchor_sequence[node]+(uint16_t)((uint16_t)bodaqs_measurement_get(p,2)-(uint16_t)s->anchor_sequence[node]);
        if(!l->source) l->first=first;
        l->last=first+count-1;l->gap=true;
#endif
        l->epoch=p[2];
        if(UINT32_MAX-l->source<count) l->failed=true; else l->source+=count;
    } else {
        if(l->evidence==UINT32_MAX) l->failed=true; else ++l->evidence;
        l->epoch=length>=14?p[13]:s->anchor_epoch[node];
        /* Ordinary snapshots may be lost with degraded alignment. All other
         * interpretation metadata is essential; preserve old heads and exclude. */
#if BODAQS_MEASUREMENT_VERSION == 2
        if(length<8 || p[1]<0x21 || p[1]>0x24) l->failed=true;
#else
        if(length<8 || p[1]!=0x23) l->failed=true;
#endif
    }
}
void bodaqs_master_service_loss_counts(BodaqsMasterService *s,uint8_t node,uint8_t stage,
    uint8_t epoch,uint16_t first,uint16_t last,uint32_t source,uint32_t evidence,
    bool essential,uint32_t tick,uint64_t ordinal) {
    BodaqsReceptionLoss *l;
    if(!s || node>3 || !s->acquisition_record[node]) return;
    l=&s->isr_loss[node];
    if(source) {
#if BODAQS_MEASUREMENT_VERSION == 2
        (void)first;(void)last;
        l->first=l->last=0;l->gap=false;
#else
        uint32_t base=s->anchor_sequence[node];
        uint32_t start=base+(uint16_t)(first-(uint16_t)base);
        if(!l->source) l->first=start;
        l->last=start+(uint16_t)(last-first);
        l->gap=true;
#endif
        if(UINT32_MAX-l->source<source) essential=true; else l->source+=source;
    }
    if(UINT32_MAX-l->evidence<evidence) essential=true; else l->evidence+=evidence;
    l->epoch=epoch;l->stage=stage;l->tick=tick;l->ordinal=ordinal;
    l->failed=l->failed||essential;
}
bool bodaqs_master_service_receive_can_ordered(BodaqsMasterService *s,uint8_t node,
    uint8_t cls,uint16_t identifier,const uint8_t *payload,uint8_t length,
    uint8_t flags,uint32_t tick,uint64_t ordinal,uint32_t now) {
    BodaqsReceptionIngress *q; BodaqsRetainedReception *entry; uint8_t *r;
    bool anchor=false; uint32_t sequence=0;uint8_t stream_epoch=0;
    if(!s || !payload || node>3 || cls<1 || cls>2 || length>64 || identifier>0x7ff ||
       s->measurement.mode.phase!=2) return false;
    transfer_context(s);
    if(!ordinal || ordinal<=s->reception_ordinal) {++s->backpressure_frames;return false;}
    s->reception_ordinal=ordinal;
    if(!s->acquisition_record[node] || s->acquisition_record[node]!=s->measurement.mode.recording ||
       s->acquisition_boot[node]!=s->discovery[node].boot_id ||
       (s->acquisition_fenced&(1U<<node))) return false;
    if(!(s->discovery[node].flags&1) || (s->discovery[node].flags&(BODAQS_MASTER_DISCOVERY_FLAG_STALE|BODAQS_MASTER_DISCOVERY_FLAG_DUPLICATE)) || !s->discovery[node].boot_id) return false;
    if(cls==1) {
        unsigned count=length>=4?(payload[3]&7):0;
        if(identifier!=0x100U+node*8U || !count || count>5 || length<4+count*12 ||
           !bodaqs_measurement_zero(payload+4+count*12,length-4-count*12) ||
           s->anchor_boot[node]!=s->discovery[node].boot_id || payload[2]!=s->anchor_epoch[node]) return false;
#if BODAQS_MEASUREMENT_VERSION == 1
        uint16_t delta=(uint16_t)((uint16_t)bodaqs_measurement_get(payload,2)-(uint16_t)s->anchor_sequence[node]);
        if(delta>=32768) {s->anchor_boot[node]=0;return false;}
        sequence=s->anchor_sequence[node]+delta+count;
#endif
    } else {
        if(identifier!=0x090U+node && identifier!=0x060U+node) return false;
        if(identifier==0x090U+node && length>=8 && payload[1]==0x22) {
            if(length!=32 || payload[0]!=1 || payload[2]!=1 || payload[3] || payload[6]!=20 || payload[7] ||
               payload[8]!=0 || payload[9]!=1 || !bodaqs_measurement_get(payload+24,2) ||
               !bodaqs_measurement_zero(payload+26,6)) return false;
            anchor=true; sequence=(uint32_t)bodaqs_measurement_get(payload+12,4);stream_epoch=payload[10];
        }
#if BODAQS_MEASUREMENT_VERSION == 2
        if(identifier==0x090U+node && length==64 && payload[1]==0x25 && payload[14]==2) {
            if(payload[0]!=1 || payload[2]!=1 || payload[3] || payload[6]!=56 || payload[7] ||
               bodaqs_measurement_get(payload+8,4)!=s->discovery[node].boot_id || payload[12] ||
               !payload[13] || !(bodaqs_measurement_get(payload+54,2)&1U)) return false;
            anchor=true;sequence=(uint32_t)bodaqs_measurement_get(payload+28,4);stream_epoch=payload[13];
        }
#endif
    }
    advance_receptions(s,node,now);
    q=&s->ingress[node];
    if(s->loss[node].failed || s->isr_loss[node].failed) {++s->backpressure_frames;return false;}
    unsigned limit=BODAQS_MASTER_RETENTION_CAPACITY;
#if BODAQS_MASTER_BOUNDARY_RESERVE
    /* Normal traffic cannot consume the final two FIFO entries. Preserve
     * canonical source boundaries without replacing/reordering an old head.
     * A full reserve still fails honestly through the existing loss path. */
    const bool boundary=cls==2 && identifier==0x090U+node && length==64 &&
        payload[0]==1 && payload[1]==0x25 && payload[2]==1 && !payload[3] &&
        payload[6]==56 && !payload[7] && !payload[12] && payload[13] &&
        payload[14]>=1 && payload[14]<=8 &&
        bodaqs_measurement_get(payload+8,4)==s->discovery[node].boot_id &&
        !(bodaqs_measurement_get(payload+54,2)&~2047ULL);
    if(!boundary) limit-=BODAQS_MASTER_BOUNDARY_RESERVE;
#endif
    if(q->count>=limit) {
        ++q->dropped; ++s->backpressure_frames;
        bodaqs_master_service_loss(s,node,6,cls,payload,length,tick,ordinal); return false;
    }
    entry=&q->records[(q->head+q->count)%BODAQS_MASTER_RETENTION_CAPACITY];
    entry->boot=s->discovery[node].boot_id; entry->ordinal_high=(uint32_t)(ordinal>>32);
    entry->received_ms=now; entry->cls=cls;
    r=entry->bytes; memset(r,0,76);
    bodaqs_measurement_put(r,identifier,2); r[2]=length; r[3]=flags;
    bodaqs_measurement_put(r+4,tick,4); bodaqs_measurement_put(r+8,ordinal,4);
    memcpy(r+12,payload,length); ++q->count; ++s->retained_frames;
    if(q->count>q->high_water) q->high_water=q->count;
    if(anchor) {s->anchor_boot[node]=s->discovery[node].boot_id;s->anchor_epoch[node]=stream_epoch;}
#if BODAQS_MEASUREMENT_VERSION == 2
    if(anchor) s->anchor_sequence[node]=sequence; // only observed full sequence, never low16 inference
#else
    if(anchor || cls==1) s->anchor_sequence[node]=sequence;
#endif
    advance_receptions(s,node,now);
    return true;
}
static void refill_budget(uint32_t now,uint32_t *last,uint8_t *tokens,uint32_t interval,uint8_t burst) {
    uint32_t periods=(uint32_t)(now-*last)/interval;
    if(periods) { *tokens=(uint8_t)(periods>=burst || *tokens+periods>=burst?burst:*tokens+periods); *last+=periods*interval; }
}
bool bodaqs_master_service_control_transmit(BodaqsMasterService *s,uint32_t now,
    uint8_t *address,uint16_t *transaction,uint8_t payload[64]) {
    unsigned priority,node;
    bodaqs_control_exchange_tick(&s->control,now);
    /* Authorization never queues behind ordinary retry timers. STOP has three
     * identical attempts in 300ms; renewal deadline ownership stays at node. */
    for(priority=0;s->measurement.mode.phase==2 && priority<2;++priority) for(node=0;node<4;++node) {
        BodaqsControlExchangeSlot *slot=&s->authorization.slots[node];
        bool stop=slot->request.opcode==0x25;
        if(slot->state!=1 || stop!=(priority==0)) continue;
        if(slot->attempts && (uint32_t)(now-slot->attempt_ms)<100) continue;
        if(slot->attempts==3) { slot->state=3;continue; }
        refill_budget(now,&s->authorization_budget_ms[node],&s->authorization_tokens[node],50,2);
        if(!s->authorization_tokens[node]) continue;
        --s->authorization_tokens[node];++slot->attempts;slot->attempt_ms=now;
        *address=(uint8_t)node;*transaction=slot->transaction;
        return bodaqs_control_encode_can(&slot->request,false,slot->transaction,payload);
    }
    if(s->measurement.mode.phase!=2)
        return bodaqs_control_exchange_transmit(&s->control,now,address,transaction,payload);
    refill_budget(now,&s->ordinary_budget_ms,&s->ordinary_tokens,250,4);
    refill_budget(now,&s->lifecycle_budget_ms,&s->lifecycle_tokens,50,4);
    for(priority=0;priority<4;++priority) {
        uint8_t op,*tokens;
        bool lifecycle,optional;
        node=(s->lifecycle_next_node+priority)%4;
        BodaqsControlExchangeSlot *slot=&s->control.slots[node];
        if(slot->state!=1 || (slot->attempts && (uint32_t)(now-slot->attempt_ms)<1000U)) continue;
        if(slot->attempts==3) {slot->state=3;continue;}
        op=slot->request.opcode;
        optional=(op==0x28 && (s->acquisition_started&(1U<<node))) ||
            ((op==7 || op==8) && slot->request.operation==s->diagnostic_operation[node] &&
             slot->request.session==s->diagnostic_session[node]);
        if(optional && op==0x28) {
            s->diagnostic_operation[node]=slot->request.operation;
            s->diagnostic_session[node]=slot->request.session;
        }
        lifecycle=(op>=0x20 && op<=0x2A) ||
            ((op==7 || op==8) && slot->request.endpoint==255) ||
            (op==0x14 && s->acquisition_operation[node] &&
             bodaqs_control_get_u32(slot->request.data)==s->acquisition_operation[node]);
        tokens=lifecycle && !optional?&s->lifecycle_tokens:&s->ordinary_tokens;
        if(!*tokens) continue;
        --*tokens;++slot->attempts;slot->attempt_ms=now;
        s->lifecycle_next_node=(uint8_t)((node+1)%4);
        *address=(uint8_t)node;*transaction=slot->transaction;
        return bodaqs_control_encode_can(&slot->request,false,slot->transaction,payload);
    }
    return false;
}
static void acquisition_result(BodaqsMasterService *s,uint8_t node,
    const BodaqsControlRecord *reply,const BodaqsControlRecord *request) {
    bool fence=(request->opcode==BODAQS_CONTROL_FENCE_OLD_DATA &&
        bodaqs_control_get_u64(request->data)==s->acquisition_record[node]) ||
        (request->opcode==BODAQS_CONTROL_GET_OPERATION &&
         bodaqs_control_get_u32(request->data)==s->acquisition_fence_operation[node] &&
         s->acquisition_fence_operation[node]!=0);
    /* Cleanup may fence an old retained recording on a freshly observed node
     * boot. The current node itself must explicitly complete its hardware fence. */
    if(reply->node_boot_id!=s->acquisition_boot[node] &&
       !(fence && reply->node_boot_id==s->discovery[node].boot_id)) return;
    if(request->opcode==BODAQS_CONTROL_COMMIT_PREPARE && reply->opcode==127) {
        s->acquisition_record[node]=0;
        bodaqs_master_service_measurement_fence(s,true,false);
    }
    if(fence && reply->opcode!=127 && reply->data_length==24 && reply->data[0]==3) {
        BodaqsReceptionBatch *batch=&s->receptions[node];
        /* Retire old data but preserve object allocators/ACK identity in context. */
        s->retired_tail_frames+=batch->count+s->ingress[node].count;
        s->ingress[node].head=s->ingress[node].count=0;
        batch->count=0;memset(&batch->object,0,sizeof(batch->object));
        s->anchor_boot[node]=0;s->acquisition_fenced |= (uint8_t)(1U<<node);
        if(s->acquisition_retirement_generation!=UINT32_MAX)
            ++s->acquisition_retirement_generation;
        s->acquisition_retirement_pending=true;
        s->measurement.fenced=false;
    }
}
bool bodaqs_master_service_control_receive(BodaqsMasterService *s,uint8_t address,
    uint16_t transaction,const BodaqsControlRecord *reply) {
    if(address>3) return false;
    /* Full common identity, not transaction alone, selects the lane. */
    if(s->authorization.slots[address].state==1 &&
       s->authorization.slots[address].request.operation==reply->operation &&
       s->authorization.slots[address].request.session==reply->session &&
       s->authorization.slots[address].request.opcode==(reply->opcode==0x7f?reply->data[3]:reply->opcode))
        return bodaqs_control_exchange_receive(&s->authorization,address,transaction,reply);
    {
        BodaqsControlRecord request=s->control.slots[address].request;
        bool accepted=bodaqs_control_exchange_receive(&s->control,address,transaction,reply);
        if(accepted) acquisition_result(s,address,reply,&request);
        return accepted;
    }
}
bool bodaqs_master_service_publish_evidence(BodaqsMasterService *s,const uint8_t *data,uint16_t length) {
    unsigned i,count;
    if(!s || !data || s->measurement.fenced || s->measurement.mode.phase!=2 || length<24 || length>1020 || (length-8)%16) return false;
    count=(length-8)/16;
    if(bodaqs_measurement_get(data,2)!=1 || data[2]!=1 ||
       bodaqs_measurement_get(data+4,2)!=count || !bodaqs_measurement_zero(data+6,2)) return false;
    for(i=0;i<count;++i) if(data[8+i*16]!=1 || data[9+i*16]) return false;
    transfer_context(s);
    if(s->master_evidence.complete || !next_object(&s->master_evidence_next_id)) return false;
    memcpy(s->master_evidence_bytes,data,length);
    return bodaqs_fragment_seal(&s->master_evidence,s->master_evidence_bytes,1024,
        s->transfer_context,s->master_evidence_next_id,255,5,1,length);
}
static void transfer_error(const BodaqsMeasurementSlot *r,BodaqsMeasurementSlot *out,uint8_t reason) {
    *out=*r; out->kind=7; out->index=0; memset(out->body,0,sizeof out->body);
    out->body[0]=(r->kind==1 || r->kind==5)?r->body[0]:bodaqs_fragment_class(r->kind);
    out->body[1]=reason;
}
static bool measurement_ack_matches(const BodaqsFragmentState *state,
    const BodaqsMeasurementSlot *r,bool combined) {
    if(!combined) return bodaqs_fragment_ack_matches(state,r);
    /* The combined caller has validated the fetch fields/reserved tail. These
     * are exactly the identity/disposition checks on its normalized ACK view;
     * fetch fields are not part of that view and need no large slot copy. */
    return state->complete && r->kind==14 && !r->index &&
        r->context==state->context && r->object==state->object &&
        r->node==state->node && r->total==state->total && r->body[0]==state->cls &&
        (r->body[1]==1 || r->body[1]==2) &&
        bodaqs_measurement_get(r->body+4,4)==state->checksum;
}
/* 0 malformed, 1 retired/already retired, 2 explicit proof error. The caller
 * owns context validation and initializes its response if one is required. */
static unsigned measurement_retire(BodaqsMasterService *s,const BodaqsMeasurementSlot *r,
    uint32_t now,BodaqsMeasurementSlot *out,bool combined) {
    const uint8_t cls=r->body[0];
    if(cls<1 || cls>5 || (cls==5?r->node!=255:r->node>3)) return 0;
    if(measurement_ack_matches(&s->acknowledged[cls-1][cls==5?0:r->node],r,combined)) return 1;
    if(cls==1 || cls==2) {
        BodaqsReceptionBatch *b=&s->receptions[r->node];
        if(!measurement_ack_matches(&b->object,r,combined)) goto proof_error;
        s->acknowledged[cls-1][r->node]=b->object;
        b->count=0;memset(&b->object,0,sizeof(b->object));
        advance_receptions(s,r->node,now);
    } else if(cls==3 || cls==4) {
        BodaqsMeasurementControlLane *lane=&s->lanes[cls-3][r->node];
        if(!measurement_ack_matches(&lane->tx,r,combined)) goto proof_error;
        s->acknowledged[cls-1][r->node]=lane->tx;
        lane->tx.complete=0;
    } else if(measurement_ack_matches(&s->master_evidence,r,combined)) {
        s->acknowledged[4][0]=s->master_evidence;
        s->master_evidence.complete=0;
    } else return 0;
    ++s->objects_acked;return 1;
proof_error:
    transfer_error(r,out,5);
    out->body[0]=cls; /* Same error bytes as the normalized kind5 request. */
    return 2;
}
static bool measurement_transfer_core(BodaqsMasterService *s,const BodaqsMeasurementSlot *r,
    uint32_t now,BodaqsMeasurementSlot *out) {
    uint8_t cls=bodaqs_fragment_class(r->kind); unsigned i;
    transfer_context(s); memset(out,0,sizeof(*out)); out->context=s->transfer_context; out->node=255;
    if(r->context!=s->transfer_context) { transfer_error(r,out,4); return true; }
    if(r->kind==10) {
        if(!bodaqs_bridge_valid(r,0)) return false;
        if(s->bridge_context!=r->context) {
            s->bridge_context=r->context;s->bridge_token=0;
        }
        if(r->object<s->bridge_token) return false;
        if(r->object!=s->bridge_token) {
            s->bridge_epoch=0;
            s->bridge_tick=s->native_clock?s->native_clock(s->clock_context,&s->bridge_epoch):0;
            if(!s->bridge_epoch) s->bridge_tick=0;
            s->bridge_token=r->object;
        }
        *out=*r;out->kind=11;out->total=16;memset(out->body,0,sizeof out->body);
        bodaqs_measurement_put(out->body,r->object,4);
        bodaqs_measurement_put(out->body+4,s->bridge_tick,4);
        bodaqs_measurement_put(out->body+8,s->bridge_epoch,4);
        bodaqs_measurement_put(out->body+12,bodaqs_bridge_crc(out,1),4);
        return true;
    }
    if(cls==3 || cls==4) {
        BodaqsMeasurementControlLane *lane; BodaqsControlWrapped request,reply;
        BodaqsControlExchange *exchange; uint8_t type; int result;
        if(r->node>3 || r->total!=68) { transfer_error(r,out,2); return true; }
        lane=&s->lanes[cls-3][r->node]; exchange=cls==3?&s->control:&s->authorization;
        bool stop_fragment=cls==4 && r->index==0 && r->body[12]==0x25;
        bool stop_continuation=cls==4 && lane->rx.object==r->object && lane->incoming[12]==0x25;
        if(lane->rx.object!=r->object && (lane->awaiting_result || lane->tx.complete) && !stop_fragment && !stop_continuation) {
            transfer_error(r,out,8); return true;
        }
        if(stop_fragment && lane->rx.object!=r->object && !lane->rx.complete) {
            /* Abandon only incomplete renewal assembly; no permission changes. */
            memset(&lane->rx,0,sizeof(lane->rx));
        }
        result=bodaqs_fragment_accept(&lane->rx,lane->incoming,68,r,0,out);
        if(result<0) { transfer_error(r,out,(uint8_t)-result); return true; }
        if(result==2 && lane->rx_rejection) {transfer_error(r,out,lane->rx_rejection);return true;}
        if(result!=1) return true;
        lane->rx_rejection=0;
        if(!bodaqs_control_decode_wrapped(lane->incoming,64,&request) || request.node_address!=r->node ||
           (cls==4 && request.record.opcode!=0x25 && request.record.opcode!=0x26 && request.record.opcode!=0x27) ||
           (cls==3 && (request.record.opcode==0x25 || request.record.opcode==0x26 || request.record.opcode==0x27)) ||
           !bodaqs_control_request_valid(&request.record)) {
            /* Do not cache transport acceptance of an invalid control object. */
            lane->rx_rejection=13; transfer_error(r,out,13); return true;
        }
        if(request.record.opcode>=0x20 && request.record.opcode<=0x27 &&
           request.record.opcode!=0x21 && request.record.opcode!=0x23) {
            unsigned offset=request.record.opcode==0x20?8:0;
            if(request.record.session!=s->measurement.mode.session ||
               bodaqs_control_get_u64(request.record.data+offset)!=s->measurement.mode.recording) {
                lane->rx_rejection=4;transfer_error(r,out,4);return true;
            }
        }
        if(cls==4 && request.record.opcode==0x25 && exchange->slots[r->node].request.opcode!=0x25) {
            if(exchange->slots[r->node].state==1) exchange->slots[r->node].state=3;
            lane->tx.complete=0; lane->awaiting_result=false;
        }
        if(cls==4 && request.record.opcode==0x25 && exchange->slots[r->node].state==3 &&
           !(exchange->excluded_addresses&(1U<<r->node)) && request.master_boot_id==exchange->master_boot_id) {
            uint8_t original[52],retry[52];
            /* Only a fresh immutable SPI object reaches result==1 here.
             * Re-arm this identical terminal operation for another bounded
             * CAN attempt group; its mutation identity never changes. */
            if(bodaqs_control_encode_record(&exchange->slots[r->node].request,original) &&
               bodaqs_control_encode_record(&request.record,retry) && !memcmp(original,retry,52)) {
                exchange->slots[r->node].state=1;
                exchange->slots[r->node].attempts=0;
                exchange->slots[r->node].attempt_ms=now;
            }
        }
        if(!bodaqs_control_exchange_request(exchange,false,&request,&reply,&type)) {
            transfer_error(r,out,13);return true;
        }
        if(type==BODAQS_CONTROL_POLL_RESPONSE || reply.record.data[0]>=BODAQS_CONTROL_BUSY) {
            if(!next_object(&lane->next_id)) { transfer_error(r,out,9); return true; }
            (void)bodaqs_control_encode_wrapped(&reply,lane->outgoing);
            (void)bodaqs_fragment_seal(&lane->tx,lane->outgoing,68,s->transfer_context,
                lane->next_id,r->node,cls,1,64);
        } else {
            lane->awaiting_result=true;
            if(request.record.opcode==0x24) s->acquisition_started|=(uint8_t)(1U<<r->node);
            if(request.record.opcode==0x25) s->acquisition_started&=(uint8_t)~(1U<<r->node);
            if((request.record.opcode>=0x20 && request.record.opcode<=0x25) ||
               request.record.opcode==0x29 || request.record.opcode==0x2A)
                s->acquisition_operation[r->node]=request.record.operation;
            if(request.record.opcode==BODAQS_CONTROL_COMMIT_PREPARE) {
                s->acquisition_record[r->node]=bodaqs_control_get_u64(request.record.data);
                s->acquisition_boot[r->node]=request.record.node_boot_id;
                s->acquisition_fenced &= (uint8_t)~(1U<<r->node);
                s->measurement.quiescent=false;s->measurement.fenced=false;
            }
            if(request.record.opcode==BODAQS_CONTROL_FENCE_OLD_DATA &&
               bodaqs_control_get_u64(request.record.data)==s->acquisition_record[r->node])
                s->acquisition_fence_operation[r->node]=request.record.operation;
        }
        return true;
    }
    if(r->kind==0) return r->node==255 && !r->object && !r->index && !r->total && bodaqs_measurement_zero(r->body,40);
    if(r->kind==5) return measurement_retire(s,r,now,out,false)!=0;
    if(r->kind!=1 || r->total || (!r->object && r->index) || !bodaqs_measurement_zero(r->body+1,39)) return false;
    cls=r->body[0]; if(cls<1 || cls>5) return false;
    if(cls==5) {
        if(r->node!=255) return false;
        if(!r->object || r->object==s->master_evidence.object)
            (void)bodaqs_fragment_emit(&s->master_evidence,s->master_evidence_bytes,r->index,out);
        return true;
    }
    for(i=0;i<4;++i) {
        uint8_t node=r->node==255?(uint8_t)((s->fair_node[cls]+i)%4):r->node;
        if(node>3) return false;
        if(cls<3) {
            BodaqsReceptionBatch *b=&s->receptions[node];
            unsigned turn;
            for(turn=0;turn<2;++turn) {
                unsigned stage=(s->loss_report_stage[node]+turn)%2;
                BodaqsReceptionLoss *l=stage?&s->isr_loss[node]:&s->loss[node];
                uint8_t loss_class=l->source!=l->reported_source?1:l->evidence!=l->reported_evidence?2:
                    cls==1?(l->source?1:2):(l->evidence?2:1);
                uint32_t total=loss_class==1?l->source:l->evidence;
                uint32_t *reported=loss_class==1?&l->reported_source:&l->reported_evidence;
                if(total && (total!=*reported || !l->failed || !l->failure_reported) &&
                   (uint32_t)(now-s->loss_report_ms[node])>=100) {
                    transfer_error(r,out,9);out->node=node;
                    out->body[0]=loss_class;
                    bodaqs_measurement_put(out->body+2,stage?5:6,2);
                    bodaqs_measurement_put(out->body+4,total,4);
                    *reported=total;s->loss_report_ms[node]=now;
                    s->loss_report_stage[node]=(uint8_t)(1-stage);
                    if(l->failed) l->failure_reported=true;
                    return true;
                }
                if(l->failed && l->source==l->reported_source && l->evidence==l->reported_evidence &&
                   (uint32_t)(now-s->loss_report_ms[node])>=100) {
                    transfer_error(r,out,14);out->node=node;
                    bodaqs_measurement_put(out->body+2,stage?5:6,2);
                    l->failure_reported=false;s->loss_report_ms[node]=now;
                    s->loss_report_stage[node]=(uint8_t)(1-stage);return true;
                }
            }
            advance_receptions(s,node,now);
            if(b->count && !b->object.complete && b->next_id[b->cls-1]==UINT32_MAX) {
#if BODAQS_MEASUREMENT_VERSION == 2
                transfer_error(r,out,14);out->node=node;return true;
#else
                transfer_error(r,out,9); return true;
#endif
            }
            if(b->cls==cls && (!r->object || r->object==b->object.object) &&
               bodaqs_fragment_emit(&b->object,b->bytes,r->index,out)) { s->fair_node[cls]=(node+1)%4; return true; }
        } else {
            BodaqsMeasurementControlLane *lane=&s->lanes[cls-3][node];
            BodaqsControlExchange *exchange=cls==3?&s->control:&s->authorization;
            BodaqsControlExchangeSlot *slot=&exchange->slots[node];
            if(lane->awaiting_result && !lane->tx.complete && slot->state>=2) {
                BodaqsControlWrapped request,reply; uint8_t type;
                memset(&request,0,sizeof(request));
                request.master_boot_id=exchange->master_boot_id; request.node_address=node; request.record=slot->request;
                request.record.data_length=0; memset(request.record.data,0,24);
                if(bodaqs_control_exchange_request(exchange,true,&request,&reply,&type) && next_object(&lane->next_id)) {
                    (void)bodaqs_control_encode_wrapped(&reply,lane->outgoing);
                    (void)bodaqs_fragment_seal(&lane->tx,lane->outgoing,68,s->transfer_context,lane->next_id,node,cls,1,64);
                    lane->awaiting_result=false;
                }
            }
            if((!r->object || r->object==lane->tx.object) && bodaqs_fragment_emit(&lane->tx,lane->outgoing,r->index,out)) {
                s->fair_node[cls]=(node+1)%4; return true;
            }
        }
        if(r->node!=255) break;
    }
    return true;
}

static bool measurement_transfer(BodaqsMasterService *s,const BodaqsMeasurementSlot *r,
    uint32_t now,BodaqsMeasurementSlot *out) {
#if BODAQS_MEASUREMENT_VERSION == 2
    if(r->retired || r->available) return false; /* requests carry no response proof */
    if(r->kind==14) {
        if(r->index || r->body[2]<1 || r->body[2]>5 ||
           (r->body[2]==5?r->body[3]!=255:r->body[3]>3) ||
           r->body[12]>=BODAQS_MEASUREMENT_FRAGMENT_COUNT ||
           (!bodaqs_measurement_get(r->body+8,4) && r->body[12]) ||
           !bodaqs_measurement_zero(r->body+13,BODAQS_MEASUREMENT_BODY_BYTES-13)) return false;
        transfer_context(s);
        if(r->context!=s->transfer_context) {
            transfer_error(r,out,4);out->body[0]=r->body[0];return true;
        }
        const unsigned retired=measurement_retire(s,r,now,out,true);
        if(!retired) return false;
        if(retired==2) return true; /* invalid proof never retires */
        BodaqsMeasurementSlot command;
        memset(&command,0,sizeof command);
        command.kind=1;command.context=r->context;command.node=r->body[3];
        command.object=(uint32_t)bodaqs_measurement_get(r->body+8,4);command.index=r->body[12];
        command.body[0]=r->body[2];
        if(!measurement_transfer_core(s,&command,now,out)) return false;
        out->retired=true;out->retiredClass=r->body[0];out->retiredNode=r->node;
        out->retiredObject=r->object;out->retiredTotal=r->total;
        out->retiredChecksum=(uint32_t)bodaqs_measurement_get(r->body+4,4);
        return true;
    }
#endif
    return measurement_transfer_core(s,r,now,out);
}

BodaqsMasterSlotResult bodaqs_master_service_process_transfer(
    BodaqsMasterService *service, const uint8_t *received, size_t length,
    uint32_t now_ms, uint8_t next_transmit[BODAQS_MASTER_TRANSFER_BYTES])
{
    BodaqsMasterFrame request, response;
    BodaqsMeasurementMode requested, observed;
    BodaqsMeasurementSlot slot, reply;
    uint16_t reason = 0;
    if (!service || !received || !next_transmit) return BODAQS_MASTER_SLOT_MALFORMED;
    service->measurement.mode.boot = service->control.master_boot_id;
    bodaqs_measurement_tick(&service->measurement, now_ms);
    memset(next_transmit, 0, BODAQS_MASTER_TRANSFER_BYTES);
    if (length == BODAQS_MEASUREMENT_BYTES) {
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
        const uint32_t profile_begin = bodaqs_master_profile_clock();
#endif
        if (!bodaqs_measurement_decode(received, length, &slot)) goto malformed;
#if BODAQS_MEASUREMENT_VERSION == 2
        if(slot.retired || slot.available) goto malformed;
#endif
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
        const uint32_t profile_decoded = bodaqs_master_profile_clock();
#endif
        if (!bodaqs_measurement_manage(&service->measurement, &slot, now_ms, &reply) &&
            !(service->measurement.mode.phase==2 && slot.kind!=6 && slot.kind!=8 && slot.kind!=9 &&
              measurement_transfer(service,&slot,now_ms,&reply)))
            goto malformed;
#if BODAQS_MEASUREMENT_VERSION == 2
        /* Bounded stale scheduling hint, never readiness/retirement proof. */
        for(unsigned n=0;n<4;++n) {
            const BodaqsReceptionBatch *batch=&service->receptions[n];
            if(batch->object.complete && batch->cls>=1 && batch->cls<=2)
                reply.available |= (uint16_t)(1U<<(n+4U*(batch->cls-1U)));
            const BodaqsReceptionIngress *queue=&service->ingress[n];
            if(queue->count) {
                const uint8_t cls=queue->records[queue->head].cls;
                if(cls>=1 && cls<=2) reply.available |= (uint16_t)(1U<<(n+4U*(cls-1U)));
            }
        }
#endif
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
        const uint32_t profile_dispatched = bodaqs_master_profile_clock();
#endif
        (void)bodaqs_measurement_encode(&reply, next_transmit, BODAQS_MEASUREMENT_BYTES);
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
        const uint32_t profile_encoded = bodaqs_master_profile_clock();
        bodaqs_master_profile_record(profile_decoded-profile_begin,
            profile_dispatched-profile_decoded, profile_encoded-profile_dispatched,
            slot.kind, reply.kind);
#endif
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
    /* Q144: a restarted owner may inspect/bind/fence/release an abandoned
     * recording. Node authority checks remain binding; never grant acquisition
     * through an active-mode legacy route. */
    if(service->measurement.mode.phase!=0 && (unsigned)request.type==6) {
        BodaqsControlWrapped admin;
        uint8_t op;
        if(!bodaqs_control_decode_wrapped(request.payload,request.payload_length,&admin)) goto malformed;
        op=admin.record.opcode;
        if(op!=1 && op!=2 && op!=4 && op!=5 && op!=6 && op!=7 && op!=8 &&
           op!=0x14 && op!=0x28 && op!=0x29 && op!=0x2A) goto malformed;
        if(op==0x2A) {
            unsigned node=admin.node_address;
            uint64_t record=bodaqs_control_get_u64(admin.record.data);
            if(record!=service->measurement.mode.recording) goto malformed;
            if(!service->acquisition_record[node]) {
                service->acquisition_record[node]=record;
                service->acquisition_boot[node]=admin.record.node_boot_id;
            }
            if(record==service->acquisition_record[node])
                service->acquisition_fence_operation[node]=admin.record.operation;
        }
    } else if(service->measurement.mode.phase!=0 && (unsigned)request.type!=2 &&
        (unsigned)request.type!=4 && /* retained inventory only; no CAN scan */
        (unsigned)request.type!=5 && (unsigned)request.type!=7) goto malformed;
    return bodaqs_master_service_process_slot(service,received,next_transmit);
malformed:
    ++service->malformed_slots;
    return BODAQS_MASTER_SLOT_MALFORMED;
}
