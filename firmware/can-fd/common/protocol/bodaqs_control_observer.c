#include "bodaqs_control_observer.h"
#include <string.h>
enum
{
    SNAPSHOT_IDLE,
    SNAPSHOT_OPEN_CAPABILITY,
    SNAPSHOT_CAPABILITY_PAGES,
    SNAPSHOT_RELEASE_CAPABILITY,
    SNAPSHOT_OPEN_EFFECTIVE,
    SNAPSHOT_EFFECTIVE_PAGES,
    SNAPSHOT_RELEASE_EFFECTIVE,
    SNAPSHOT_REFRESH_EPOCH
};
static void invalidate_current(BodaqsControlObservation *node)
{
    unsigned endpoint;
    node->valid = false;
    node->epoch_valid_mask = 0;
    for (endpoint=0; endpoint<6; ++endpoint) node->endpoints[endpoint].current=false;
}
void bodaqs_control_observer_tick(BodaqsControlObserver *o, uint32_t now)
{
    o->now_ms = now;
    if (o->snapshot_phase && (uint32_t)(now - o->snapshot_started_ms) >=
                                 BODAQS_CONTROL_SNAPSHOT_LIFETIME_MS)
    {
        o->nodes[o->snapshot_address].endpoints[o->snapshot_endpoint].current =
            false;
        o->pending = false;
        o->snapshot_phase = 0;
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
            for (unsigned e=0; e<6; ++e)
                observer->nodes[i].endpoints[e].current = false;
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
        invalidate_current(node);
        if ((observer->pending && observer->current.node_address == address) ||
            (observer->snapshot_phase && observer->snapshot_address == address))
        {
            observer->pending = false;
            observer->snapshot_phase = 0;
        }
    }
    if (boot) node->node_boot_id = boot;
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
    if (observer->snapshot_phase)
    {
        uint8_t phase = observer->snapshot_phase;
        memset(&observer->current, 0, sizeof(observer->current));
        observer->current.master_boot_id = observer->master_boot_id;
        observer->current.node_address = observer->snapshot_address;
        observer->current.record.node_boot_id =
            observer->nodes[observer->snapshot_address].node_boot_id;
        observer->current.record.endpoint = observer->snapshot_endpoint;
        observer->current.record.operation = observer->snapshot_read_id;
        if (phase == SNAPSHOT_OPEN_CAPABILITY ||
            phase == SNAPSHOT_OPEN_EFFECTIVE)
        {
            observer->current.record.opcode =
                phase == SNAPSHOT_OPEN_CAPABILITY
                    ? BODAQS_CONTROL_OPEN_CAPABILITIES
                    : BODAQS_CONTROL_OPEN_EFFECTIVE;
            observer->snapshot_read_id = observer->next_read_id++;
            observer->current.record.operation = observer->snapshot_read_id;
            observer->snapshot_started_ms = observer->now_ms;
        }
        else if (phase == SNAPSHOT_CAPABILITY_PAGES ||
                 phase == SNAPSHOT_EFFECTIVE_PAGES)
        {
            observer->current.record.opcode = BODAQS_CONTROL_READ_PAGE;
            observer->current.record.page = observer->snapshot_page;
            observer->current.record.transfer = observer->snapshot_id;
        }
        else if (phase == SNAPSHOT_RELEASE_CAPABILITY ||
                 phase == SNAPSHOT_RELEASE_EFFECTIVE)
        {
            observer->current.record.opcode = BODAQS_CONTROL_RELEASE_SNAPSHOT;
            observer->current.record.transfer = observer->snapshot_id;
        }
        else
        {
            observer->current.record.opcode = BODAQS_CONTROL_GET_NODE_STATE;
            observer->current.record.operation = observer->next_read_id++;
        }
        observer->pending = true;
        *request = observer->current;
        *type = BODAQS_CONTROL_SUBMIT_REQUEST;
        return true;
    }
    for (i = 0; i < 28; ++i)
    {
        uint8_t address = observer->cursor_address,
                endpoint = observer->cursor_endpoint;
        BodaqsControlObservation *node = &observer->nodes[address];
        if (++observer->cursor_endpoint == 7)
        {
            observer->cursor_endpoint = 0;
            observer->cursor_address = (uint8_t)((address + 1) % 4);
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
            endpoint ? (uint8_t)(endpoint - 1)
                     : (uint8_t)BODAQS_CONTROL_NODE_WIDE;
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
    bodaqs_control_observer_tick(observer, now);
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
    if (observer->snapshot_phase &&
        request->opcode != BODAQS_CONTROL_GET_NODE_STATE)
    {
        BodaqsControlEndpointObservation *ep =
            &observer->nodes[reply->node_address]
                 .endpoints[observer->snapshot_endpoint];
        uint8_t phase = observer->snapshot_phase;
        if (record->operation != request->operation ||
            record->node_boot_id != request->node_boot_id ||
            record->endpoint != request->endpoint || record->session ||
            record->page != request->page)
            return false;
        if (type == BODAQS_CONTROL_RECEIPT_RESPONSE)
        {
            if (record->opcode != request->opcode || record->data_length != 4 ||
                record->data[3] != request->opcode)
                return false;
            if (record->data[0] >= BODAQS_CONTROL_BUSY)
            {
                observer->pending = false;
                observer->snapshot_phase = 0;
                ep->current = false;
            }
            return true;
        }
        observer->pending = false;
        if (type == BODAQS_CONTROL_POLL_RESPONSE &&
            record->opcode == BODAQS_CONTROL_ERROR &&
            record->data_length == 24 &&
            record->data[0] == BODAQS_CONTROL_COMMAND_REJECTED &&
            record->data[3] == request->opcode)
        {
            observer->nodes[reply->node_address].reason = record->data[1];
            observer->nodes[reply->node_address].field = record->data[2];
            observer->snapshot_phase = SNAPSHOT_IDLE;
            ep->current = false;
            return true;
        }
        if (type != BODAQS_CONTROL_POLL_RESPONSE ||
            record->opcode != request->opcode)
        {
            observer->snapshot_phase = 0;
            ep->current = false;
            return false;
        }
        if (phase == SNAPSHOT_OPEN_CAPABILITY ||
            phase == SNAPSHOT_OPEN_EFFECTIVE)
        {
            uint16_t length = phase == SNAPSHOT_OPEN_CAPABILITY ? 128 : 192;
            uint8_t schema = phase == SNAPSHOT_OPEN_CAPABILITY ? 2 : 3;
            if (!record->transfer || record->data_length != 24 ||
                record->data[0] != schema || record->data[1] ||
                record->data[2] != 1 || record->data[3] ||
                record->data[4] != (uint8_t)length || record->data[5] ||
                record->data[6] != (length + 23) / 24 || record->data[7] ||
                (phase == SNAPSHOT_OPEN_CAPABILITY &&
                 (bodaqs_control_get_u64(record->data + 8) ||
                  bodaqs_control_get_u64(record->data + 16))))
            {
                observer->snapshot_phase = 0;
                ep->current = false;
                return false;
            }
            observer->snapshot_length = length;
            observer->snapshot_id = record->transfer;
            observer->snapshot_page = 0;
            observer->snapshot_revision =
                bodaqs_control_get_u64(record->data + 8);
            observer->snapshot_epoch =
                bodaqs_control_get_u64(record->data + 16);
            memset(observer->snapshot_bytes, 0,
                   sizeof(observer->snapshot_bytes));
            ++observer->snapshot_phase;
            return true;
        }
        if (record->transfer != observer->snapshot_id)
        {
            observer->snapshot_phase = 0;
            ep->current = false;
            return false;
        }
        if (phase == SNAPSHOT_CAPABILITY_PAGES ||
            phase == SNAPSHOT_EFFECTIVE_PAGES)
        {
            unsigned offset = observer->snapshot_page * 24U;
            unsigned count = observer->snapshot_length - offset;
            if (count > 24)
                count = 24;
            if (record->data_length != count)
            {
                observer->snapshot_phase = 0;
                ep->current = false;
                return false;
            }
            memcpy(observer->snapshot_bytes + offset, record->data, count);
            if (++observer->snapshot_page * 24U >= observer->snapshot_length)
            {
                if (!bodaqs_control_descriptor_valid(
                        observer->snapshot_bytes, observer->snapshot_length,
                        phase == SNAPSHOT_CAPABILITY_PAGES ? 2 : 3,
                        observer->snapshot_endpoint) ||
                    (phase == SNAPSHOT_EFFECTIVE_PAGES &&
                     (bodaqs_control_get_u64(observer->snapshot_bytes + 32) !=
                          observer->snapshot_revision ||
                      bodaqs_control_get_u64(observer->snapshot_bytes + 184) !=
                          observer->snapshot_epoch)))
                {
                    observer->snapshot_phase = 0;
                    ep->current = false;
                    return false;
                }
                if (phase == SNAPSHOT_CAPABILITY_PAGES)
                {
                    memcpy(ep->capability, observer->snapshot_bytes, 128);
                    ep->capability_valid = true;
                }
                /* Keep the previous observation until the candidate effective
                 * snapshot has passed the final fresh epoch comparison. */
                ++observer->snapshot_phase;
            }
            return true;
        }
        if (record->data_length != 24 || record->data[0] || record->data[1] ||
            record->data[2] || record->data[3] != request->opcode)
        {
            observer->snapshot_phase = 0;
            ep->current = false;
            return false;
        }
        ++observer->snapshot_phase;
        return true;
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
            invalidate_current(node);
        }
        return true;
    }
    if (type != BODAQS_CONTROL_POLL_RESPONSE || record->data_length != 24)
    {
        /* A completed malformed result may be cached by a faulty peer. Abandon
         * this read rather than polling the same unusable result forever. */
        observer->pending = false;
        invalidate_current(node);
        return false;
    }
    if (record->opcode == BODAQS_CONTROL_ERROR &&
        record->data[0] == BODAQS_CONTROL_COMMAND_REJECTED &&
        record->data[3] == BODAQS_CONTROL_GET_NODE_STATE)
    {
        invalidate_current(node);
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
        node->epoch_valid_mask |= (uint16_t)(1U << record->endpoint);
    }
    observer->pending = false;
    if (record->endpoint != BODAQS_CONTROL_NODE_WIDE)
    {
        BodaqsControlEndpointObservation *ep =
            &node->endpoints[record->endpoint];
        if (observer->snapshot_phase == SNAPSHOT_REFRESH_EPOCH)
        {
            ep->current = observer->snapshot_epoch ==
                          node->endpoint_epoch[record->endpoint];
            if (ep->current)
            {
                memcpy(ep->effective, observer->snapshot_bytes, 192);
                ep->effective_valid = true;
                ep->effective_boot = node->node_boot_id;
                ep->effective_uid = bodaqs_control_get_u64(ep->capability + 40);
                ep->observed_ms = now;
            }
            observer->snapshot_phase = 0;
        }
        else
        {
            ep->current = ep->current && ep->effective_valid &&
                          bodaqs_control_get_u64(ep->effective + 184) ==
                              node->endpoint_epoch[record->endpoint];
            observer->snapshot_phase = SNAPSHOT_OPEN_CAPABILITY;
            observer->snapshot_address = reply->node_address;
            observer->snapshot_endpoint = record->endpoint;
            observer->snapshot_started_ms = now;
        }
    }
    return true;
}
