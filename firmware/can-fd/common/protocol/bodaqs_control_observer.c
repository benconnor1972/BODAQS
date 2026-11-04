#include "bodaqs_control_observer.h"
#include <string.h>
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
        observer->cursor_address = 0;
        observer->cursor_endpoint = 0;
        for (i = 0; i < 4; ++i)
        {
            observer->nodes[i].valid = false;
            observer->nodes[i].epoch_valid_mask = 0;
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
    return true;
}
