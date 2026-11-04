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
    service->ordinary_tokens = 4;
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
    service->measurement.quiescent = stopped_authorization_invalid;
    service->measurement.fenced = data_retired;
}


static void transfer_context(BodaqsMasterService *s) {
    if(s->transfer_context==s->measurement.mode.context) return;
    memset(s->receptions,0,sizeof(s->receptions));
    memset(s->lanes,0,sizeof(s->lanes));
    memset(s->acknowledged,0,sizeof(s->acknowledged));
    memset(&s->master_evidence,0,sizeof(s->master_evidence));
    s->master_evidence_next_id=0;
    s->transfer_context=s->measurement.mode.context;
    bodaqs_control_exchange_init(&s->authorization,s->control.master_boot_id);
    memset(s->anchor_boot,0,sizeof(s->anchor_boot));
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
bool bodaqs_master_service_receive_can(BodaqsMasterService *s,uint8_t node,
    uint8_t cls,uint16_t identifier,const uint8_t *payload,uint8_t length,
    uint8_t flags,uint32_t tick,uint32_t now) {
    BodaqsReceptionBatch *b; uint8_t *r; uint64_t ordinal; bool anchor=false; uint32_t sequence=0;
    if(!s || !payload || node>3 || cls<1 || cls>2 || length>64 || identifier>0x7ff ||
       s->measurement.mode.phase!=2) return false;
    transfer_context(s);
    if(s->reception_ordinal==UINT64_MAX) {++s->backpressure_frames;return false;}
    ordinal=++s->reception_ordinal;
    if(!(s->discovery[node].flags&1) || (s->discovery[node].flags&(BODAQS_MASTER_DISCOVERY_FLAG_STALE|BODAQS_MASTER_DISCOVERY_FLAG_DUPLICATE)) || !s->discovery[node].boot_id) return false;
    if(cls==1) {
        unsigned count=length>=4?(payload[3]&7):0;
        uint16_t delta;
        if(identifier!=0x100U+node*8U || !count || count>5 || length<4+count*12 ||
           !bodaqs_measurement_zero(payload+4+count*12,length-4-count*12) ||
           s->anchor_boot[node]!=s->discovery[node].boot_id || payload[2]!=s->anchor_epoch[node]) return false;
        delta=(uint16_t)((uint16_t)bodaqs_measurement_get(payload,2)-(uint16_t)s->anchor_sequence[node]);
        if(delta>=32768) {s->anchor_boot[node]=0;return false;}
        sequence=s->anchor_sequence[node]+delta+count;
    } else {
        if(identifier!=0x090U+node && identifier!=0x060U+node) return false;
        if(identifier==0x090U+node && length>=8 && payload[1]==0x22) {
            if(length!=32 || payload[0]!=1 || payload[2]!=1 || payload[3] || payload[6]!=20 || payload[7] ||
               payload[8]!=0 || payload[9]!=1 || !bodaqs_measurement_get(payload+24,2) ||
               !bodaqs_measurement_zero(payload+26,6)) return false;
            anchor=true; sequence=(uint32_t)bodaqs_measurement_get(payload+12,4);
        }
    }
    b=&s->receptions[node];
    if(b->count && (uint32_t)(now-b->started_ms)>=20) (void)seal_receptions(s,node);
    if(b->object.complete || (b->count && (b->cls!=cls ||
       bodaqs_measurement_get(b->bytes+8,4)!=(ordinal>>32) ||
       bodaqs_measurement_get(b->bytes+4,4)!=s->discovery[node].boot_id))) {
        if(b->count && !b->object.complete) (void)seal_receptions(s,node);
        ++s->backpressure_frames; return false;
    }
    if(!b->count) {
        memset(b->bytes,0,16); b->cls=cls; b->started_ms=now;
        bodaqs_measurement_put(b->bytes,1,2); b->bytes[2]=cls; b->bytes[3]=node;
        bodaqs_measurement_put(b->bytes+4,s->discovery[node].boot_id,4);
        bodaqs_measurement_put(b->bytes+8,ordinal>>32,4);
    }
    r=b->bytes+16+b->count*76; memset(r,0,76);
    bodaqs_measurement_put(r,identifier,2); r[2]=length; r[3]=flags;
    bodaqs_measurement_put(r+4,tick,4); bodaqs_measurement_put(r+8,ordinal,4);
    memcpy(r+12,payload,length); ++b->count; ++s->retained_frames;
    if(anchor) {s->anchor_boot[node]=s->discovery[node].boot_id;s->anchor_epoch[node]=payload[10];}
    if(anchor || cls==1) s->anchor_sequence[node]=sequence;
    if(b->count==13) (void)seal_receptions(s,node);
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
    for(priority=0;priority<2;++priority) for(node=0;node<4;++node) {
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
    if(!s->ordinary_tokens) return false;
    if(!bodaqs_control_exchange_transmit(&s->control,now,address,transaction,payload)) return false;
    --s->ordinary_tokens;return true;
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
    return bodaqs_control_exchange_receive(&s->control,address,transaction,reply);
}
bool bodaqs_master_service_publish_evidence(BodaqsMasterService *s,const uint8_t *data,uint16_t length) {
    if(!s || !data || s->measurement.mode.phase!=2 || length>1020) return false;
    transfer_context(s);
    if(s->master_evidence.complete || !next_object(&s->master_evidence_next_id)) return false;
    memcpy(s->master_evidence_bytes,data,length);
    return bodaqs_fragment_seal(&s->master_evidence,s->master_evidence_bytes,1024,
        s->transfer_context,s->master_evidence_next_id,255,5,1,length);
}
static void transfer_error(const BodaqsMeasurementSlot *r,BodaqsMeasurementSlot *out,uint8_t reason) {
    *out=*r; out->kind=7; out->index=0; memset(out->body,0,40);
    out->body[0]=bodaqs_fragment_class(r->kind); out->body[1]=reason;
}
static bool measurement_transfer(BodaqsMasterService *s,const BodaqsMeasurementSlot *r,
    uint32_t now,BodaqsMeasurementSlot *out) {
    uint8_t cls=bodaqs_fragment_class(r->kind); unsigned i;
    transfer_context(s); memset(out,0,sizeof(*out)); out->context=s->transfer_context; out->node=255;
    if(r->context!=s->transfer_context) { transfer_error(r,out,4); return true; }
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
        if(result!=1) return true;
        if(!bodaqs_control_decode_wrapped(lane->incoming,64,&request) || request.node_address!=r->node ||
           (cls==4 && request.record.opcode!=0x25 && request.record.opcode!=0x26 && request.record.opcode!=0x27) ||
           (cls==3 && (request.record.opcode==0x25 || request.record.opcode==0x26 || request.record.opcode==0x27)) ||
           !bodaqs_control_request_valid(&request.record)) {
            /* Do not cache transport acceptance of an invalid control object. */
            memset(&lane->rx,0,sizeof(lane->rx)); transfer_error(r,out,13); return true;
        }
        if(cls==4 && request.record.opcode==0x25 && exchange->slots[r->node].request.opcode!=0x25) {
            if(exchange->slots[r->node].state==1) exchange->slots[r->node].state=3;
            lane->tx.complete=0; lane->awaiting_result=false;
        }
        if(!bodaqs_control_exchange_request(exchange,false,&request,&reply,&type)) {
            transfer_error(r,out,13);return true;
        }
        if(type==BODAQS_CONTROL_POLL_RESPONSE || reply.record.data[0]>=BODAQS_CONTROL_BUSY) {
            if(!next_object(&lane->next_id)) { transfer_error(r,out,9); return true; }
            (void)bodaqs_control_encode_wrapped(&reply,lane->outgoing);
            (void)bodaqs_fragment_seal(&lane->tx,lane->outgoing,68,s->transfer_context,
                lane->next_id,r->node,cls,1,64);
        } else lane->awaiting_result=true;
        return true;
    }
    if(r->kind==0) return !r->object && !r->index && !r->total && bodaqs_measurement_zero(r->body,40);
    if(r->kind==5) {
        cls=r->body[0];
        if(cls<1 || cls>5 || (cls==5?r->node!=255:r->node>3)) return false;
        if(bodaqs_fragment_ack_matches(&s->acknowledged[cls-1][cls==5?0:r->node],r)) return true;
        if(cls==1 || cls==2) {
            BodaqsReceptionBatch *b;
            if(r->node>3) return false;
            b=&s->receptions[r->node];
            if(!bodaqs_fragment_ack_matches(&b->object,r)) { transfer_error(r,out,5); return true; }
            s->acknowledged[cls-1][r->node]=b->object;
            b->count=0; memset(&b->object,0,sizeof(b->object));
        } else if(cls==3 || cls==4) {
            BodaqsMeasurementControlLane *lane;
            if(r->node>3) return false;
            lane=&s->lanes[cls-3][r->node];
            if(!bodaqs_fragment_ack_matches(&lane->tx,r)) { transfer_error(r,out,5); return true; }
            s->acknowledged[cls-1][r->node]=lane->tx;
            lane->tx.complete=0;
        } else if(cls==5 && r->node==255 && bodaqs_fragment_ack_matches(&s->master_evidence,r)) {
            s->acknowledged[4][0]=s->master_evidence;
            s->master_evidence.complete=0;
        } else return false;
        ++s->objects_acked; return true;
    }
    if(r->kind!=1 || !bodaqs_measurement_zero(r->body+1,39)) return false;
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
            if(b->count && (uint32_t)(now-b->started_ms)>=20) (void)seal_receptions(s,node);
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
        if (!bodaqs_measurement_decode(received, length, &slot)) goto malformed;
        if (!bodaqs_measurement_manage(&service->measurement, &slot, now_ms, &reply) &&
            !(service->measurement.mode.phase==2 && slot.kind!=6 && slot.kind!=8 && slot.kind!=9 &&
              measurement_transfer(service,&slot,now_ms,&reply)))
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
