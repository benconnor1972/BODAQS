#include "bodaqs_control_observer.h"
#include <string.h>
void bodaqs_control_observer_tick(BodaqsControlObserver *o,uint32_t now) {
    o->now_ms=now;
    if(o->snapshot_phase && (uint32_t)(now-o->snapshot_started_ms)>=BODAQS_CONTROL_SNAPSHOT_LIFETIME_MS) {
        o->nodes[o->snapshot_address].endpoints[o->snapshot_endpoint].current=false;
        o->pending=false;o->snapshot_phase=0;
    }
}
void bodaqs_control_observer_init(BodaqsControlObserver *observer)
{
    memset(observer, 0, sizeof(*observer));
    observer->next_read_id = 1;
}

void bodaqs_control_observer_boot(BodaqsControlObserver *observer,
                                  uint64_t boot, uint32_t features)
{
    unsigned i;
    if (observer->master_boot_id != boot ||
        !(features & BODAQS_CONTROL_FEATURE_OBSERVATION))
    {
        observer->pending = false;
        observer->snapshot_phase = 0;
        observer->cursor_address = 0;
        observer->cursor_endpoint = 0;
        for (i = 0; i < 4; ++i)
        {
            observer->nodes[i].valid = false;
            observer->nodes[i].epoch_valid_mask = 0;
            memset(observer->nodes[i].endpoints,0,sizeof(observer->nodes[i].endpoints));
        }
    }
    observer->master_boot_id = boot;
    observer->features = features;
}

void bodaqs_control_observer_node(BodaqsControlObserver *observer,
                                  uint8_t address, uint32_t boot,
                                  uint16_t endpoints, bool available)
{
    BodaqsControlObservation *node;
    if (address >= 4)
    {
        return;
    }
    node = &observer->nodes[address];
    if (node->node_boot_id != boot || !available ||
        node->endpoint_mask != endpoints)
    {
        memset(node, 0, sizeof(*node));
        if (observer->pending && observer->current.node_address == address)
        {
            observer->pending = false;
            observer->snapshot_phase = 0;
        }
    }
    node->node_boot_id = boot;
    node->endpoint_mask = endpoints;
    node->available = available && boot != 0;
}

bool bodaqs_control_observer_next(BodaqsControlObserver *observer,
                                  BodaqsControlWrapped *request, uint8_t *type)
{
    unsigned i;
    if (!observer->master_boot_id || (observer->features & 3U) != 3U ||
        !observer->next_read_id)
    {
        return false;
    }
    if (observer->pending)
    {
        *request = observer->current;
        *type = BODAQS_CONTROL_POLL_REQUEST;
        return true;
    }
    if(observer->snapshot_phase) {
        uint8_t phase=observer->snapshot_phase;
        memset(&observer->current,0,sizeof(observer->current));
        observer->current.master_boot_id=observer->master_boot_id;
        observer->current.node_address=observer->snapshot_address;
        observer->current.record.node_boot_id=observer->nodes[observer->snapshot_address].node_boot_id;
        observer->current.record.endpoint=observer->snapshot_endpoint;
        observer->current.record.operation=observer->snapshot_read_id;
        if(phase==1 || phase==4) {
            observer->current.record.opcode=phase==1?5:6;
            observer->snapshot_read_id=observer->next_read_id++;
            observer->current.record.operation=observer->snapshot_read_id;
            observer->snapshot_started_ms=observer->now_ms;
        } else if(phase==2 || phase==5) {
            observer->current.record.opcode=7;observer->current.record.page=observer->snapshot_page;
            observer->current.record.transfer=observer->snapshot_id;
        } else if(phase==3 || phase==6) {
            observer->current.record.opcode=8;observer->current.record.transfer=observer->snapshot_id;
        } else {
            observer->current.record.opcode=4;observer->current.record.operation=observer->next_read_id++;
        }
        observer->pending=true;*request=observer->current;*type=BODAQS_CONTROL_SUBMIT_REQUEST;return true;
    }
    for (i = 0; i < 28; ++i)
    {
        uint8_t address = observer->cursor_address,
                endpoint = observer->cursor_endpoint;
        BodaqsControlObservation *node = &observer->nodes[address];
        if (++observer->cursor_endpoint == 7)
        {
            observer->cursor_endpoint = 0;
            observer->cursor_address = (uint8_t) ((address + 1) % 4);
        }
        if (!node->available ||
            (endpoint && !(node->endpoint_mask & (1U << (endpoint - 1)))))
        {
            continue;
        }
        memset(&observer->current, 0, sizeof(observer->current));
        observer->current.master_boot_id = observer->master_boot_id;
        observer->current.node_address = address;
        observer->current.record.opcode = BODAQS_CONTROL_GET_NODE_STATE;
        observer->current.record.endpoint =
            endpoint ? (uint8_t) (endpoint - 1)
                     : (uint8_t) BODAQS_CONTROL_NODE_WIDE;
        observer->current.record.node_boot_id = node->node_boot_id;
        observer->current.record.operation = observer->next_read_id++;
        observer->pending = true;
        *request = observer->current;
        *type = BODAQS_CONTROL_SUBMIT_REQUEST;
        return true;
    }
    return false;
}

bool bodaqs_control_observer_accept(BodaqsControlObserver *observer,
                                    uint8_t type,
                                    const BodaqsControlWrapped *reply,
                                    uint32_t now)
{
    const BodaqsControlRecord *record = &reply->record,
                              *request = &observer->current.record;
    BodaqsControlObservation *node;
    if (!observer->pending ||
        reply->node_address != observer->current.node_address)
    {
        return false;
    }
    if (reply->master_boot_id != observer->master_boot_id)
    {
        bodaqs_control_observer_boot(observer, reply->master_boot_id, 0);
        return false;
    }
    if(observer->snapshot_phase && request->opcode!=4) {
        BodaqsControlEndpointObservation *ep=&observer->nodes[reply->node_address].endpoints[observer->snapshot_endpoint];
        uint8_t phase=observer->snapshot_phase;
        if(record->operation!=request->operation || record->node_boot_id!=request->node_boot_id || record->endpoint!=request->endpoint || record->session || record->page!=request->page) return false;
        if(type==BODAQS_CONTROL_RECEIPT_RESPONSE) {
            if(record->opcode!=request->opcode || record->data_length!=4 || record->data[3]!=request->opcode) return false;
            if(record->data[0]>=BODAQS_CONTROL_BUSY) {observer->pending=false;observer->snapshot_phase=0;ep->current=false;}
            return true;
        }
        observer->pending=false;
        if(type!=BODAQS_CONTROL_POLL_RESPONSE || record->opcode!=request->opcode) {observer->snapshot_phase=0;ep->current=false;return false;}
        if(phase==1 || phase==4) {
            uint16_t length=phase==1?128:192;
            uint8_t schema=phase==1?2:3;
            if(!record->transfer || record->data_length!=24 || record->data[0]!=schema || record->data[1] || record->data[2]!=1 || record->data[3] || record->data[4]!=(uint8_t)length || record->data[5] || record->data[6]!=(length+23)/24 || record->data[7] ||
               (phase==1 && (bodaqs_control_get_u64(record->data+8)||bodaqs_control_get_u64(record->data+16)))) {observer->snapshot_phase=0;ep->current=false;return false;}
            observer->snapshot_length=length;observer->snapshot_id=record->transfer;observer->snapshot_page=0;
            observer->snapshot_revision=bodaqs_control_get_u64(record->data+8);observer->snapshot_epoch=bodaqs_control_get_u64(record->data+16);
            memset(observer->snapshot_bytes,0,sizeof(observer->snapshot_bytes));++observer->snapshot_phase;return true;
        }
        if(record->transfer!=observer->snapshot_id) {observer->snapshot_phase=0;ep->current=false;return false;}
        if(phase==2 || phase==5) {
            unsigned offset=observer->snapshot_page*24U;
            unsigned count=observer->snapshot_length-offset;if(count>24) count=24;
            if(record->data_length!=count) {observer->snapshot_phase=0;ep->current=false;return false;}
            memcpy(observer->snapshot_bytes+offset,record->data,count);
            if(++observer->snapshot_page*24U>=observer->snapshot_length) {
                if(!bodaqs_control_descriptor_valid(observer->snapshot_bytes,observer->snapshot_length,phase==2?2:3,observer->snapshot_endpoint) ||
                  (phase==5 && (bodaqs_control_get_u64(observer->snapshot_bytes+32)!=observer->snapshot_revision || bodaqs_control_get_u64(observer->snapshot_bytes+184)!=observer->snapshot_epoch))) {observer->snapshot_phase=0;ep->current=false;return false;}
                if(phase==2) {memcpy(ep->capability,observer->snapshot_bytes,128);ep->capability_valid=true;}
                else {memcpy(ep->effective,observer->snapshot_bytes,192);ep->effective_valid=true;ep->observed_ms=now;ep->current=false;}
                ++observer->snapshot_phase;
            }
            return true;
        }
        if(record->data_length!=24 || record->data[0] || record->data[1] || record->data[2]) {observer->snapshot_phase=0;ep->current=false;return false;}
        ++observer->snapshot_phase;return true;
    }
    if (record->operation != request->operation ||
        record->node_boot_id != request->node_boot_id ||
        record->endpoint != request->endpoint || record->page ||
        record->session || record->transfer)
    {
        return false;
    }
    node = &observer->nodes[reply->node_address];
    if (type == BODAQS_CONTROL_RECEIPT_RESPONSE &&
        record->opcode == BODAQS_CONTROL_GET_NODE_STATE &&
        record->data_length == 4 &&
        record->data[3] == BODAQS_CONTROL_GET_NODE_STATE)
    {
        if (record->data[0] > BODAQS_CONTROL_UNCERTAIN)
        {
            return false;
        }
        node->receipt_state = record->data[0];
        node->reason = record->data[1];
        node->field = record->data[2];
        if (record->data[0] >= BODAQS_CONTROL_BUSY)
        {
            observer->pending = false;
            node->valid = false;
            node->epoch_valid_mask = 0;
        }
        return true;
    }
    if (type != BODAQS_CONTROL_POLL_RESPONSE || record->data_length != 24)
    {
        /* A completed malformed result may be cached by a faulty peer. Abandon
         * this read rather than polling the same unusable result forever. */
        observer->pending = false;
        node->valid = false;
        node->epoch_valid_mask = 0;
        return false;
    }
    if (record->opcode == BODAQS_CONTROL_ERROR &&
        record->data[0] == BODAQS_CONTROL_COMMAND_REJECTED &&
        record->data[3] == BODAQS_CONTROL_GET_NODE_STATE)
    {
        node->valid = false;
        node->epoch_valid_mask = 0;
        node->reason = record->data[1];
        node->field = record->data[2];
        observer->pending = false;
        return true;
    }
    if (record->opcode != BODAQS_CONTROL_GET_NODE_STATE)
    {
        return false;
    }
    node->active_session = bodaqs_control_get_u64(record->data);
    node->flags = bodaqs_control_get_u32(record->data + 16);
    node->pending_operation = bodaqs_control_get_u32(record->data + 20);
    node->observed_ms = now;
    node->reason = 0;
    node->field = 0;
    if (record->endpoint == BODAQS_CONTROL_NODE_WIDE)
    {
        node->valid = true;
    }
    else
    {
        node->endpoint_epoch[record->endpoint] =
            bodaqs_control_get_u64(record->data + 8);
        node->epoch_valid_mask |= (uint16_t) (1U << record->endpoint);
    }
    observer->pending = false;
    if(record->endpoint!=BODAQS_CONTROL_NODE_WIDE) {
        BodaqsControlEndpointObservation *ep=&node->endpoints[record->endpoint];
        if(observer->snapshot_phase==7) {
            ep->current=ep->effective_valid && bodaqs_control_get_u64(ep->effective+184)==node->endpoint_epoch[record->endpoint];
            observer->snapshot_phase=0;
        } else {
            ep->current=false;observer->snapshot_phase=1;observer->snapshot_address=reply->node_address;observer->snapshot_endpoint=record->endpoint;observer->snapshot_started_ms=now;
        }
    }
    return true;
}
