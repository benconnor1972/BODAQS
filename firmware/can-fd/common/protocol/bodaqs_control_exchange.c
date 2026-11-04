#include "bodaqs_control_exchange.h"
#include <string.h>
enum
{
    EXCHANGE_EMPTY,
    EXCHANGE_PENDING,
    EXCHANGE_COMPLETE,
    EXCHANGE_UNCERTAIN,
    EXCHANGE_NOT_DISPATCHED
};
static bool inspection(uint8_t opcode)
{
    return opcode == BODAQS_CONTROL_GET_CHALLENGE ||
           opcode == BODAQS_CONTROL_GET_NODE_STATE ||
           opcode == BODAQS_CONTROL_OPEN_CAPABILITIES ||
           opcode == BODAQS_CONTROL_OPEN_EFFECTIVE ||
           opcode == BODAQS_CONTROL_READ_PAGE ||
           opcode == BODAQS_CONTROL_RELEASE_SNAPSHOT ||
           opcode == BODAQS_CONTROL_GET_OPERATION;
}
void bodaqs_control_exchange_exclude(BodaqsControlExchange *exchange, uint8_t addresses)
{
    unsigned i;
    exchange->excluded_addresses = addresses;
    for (i = 0; i < 4; ++i)
    {
        BodaqsControlExchangeSlot *slot = &exchange->slots[i];
        if ((addresses & (1U << i)) && slot->state == EXCHANGE_PENDING &&
            !inspection(slot->request.opcode))
            slot->state = slot->attempts ? EXCHANGE_UNCERTAIN : EXCHANGE_NOT_DISPATCHED;
    }
}

static bool same_header(const BodaqsControlRecord *a,
                        const BodaqsControlRecord *b)
{
    return a->opcode == b->opcode && a->endpoint == b->endpoint &&
           a->page == b->page && a->operation == b->operation &&
           a->node_boot_id == b->node_boot_id && a->session == b->session &&
           a->transfer == b->transfer;
}

static bool same_request(const BodaqsControlRecord *a,
                         const BodaqsControlRecord *b)
{
    return same_header(a, b) && a->data_length == b->data_length &&
           memcmp(a->data, b->data, 24) == 0;
}

static void receipt(BodaqsControlWrapped *response, uint8_t state,
                    uint8_t reason, uint8_t field)
{
    uint8_t opcode = response->record.opcode;
    response->record.data_length = 4;
    memset(response->record.data, 0, 24);
    response->record.data[0] = state;
    response->record.data[1] = reason;
    response->record.data[2] = field;
    response->record.data[3] = opcode;
}

void bodaqs_control_exchange_init(BodaqsControlExchange *exchange,
                                  uint64_t boot)
{
    memset(exchange, 0, sizeof(*exchange));
    exchange->master_boot_id = boot;
    exchange->next_transaction = 1;
}

bool bodaqs_control_exchange_request(BodaqsControlExchange *exchange, bool poll,
                                     const BodaqsControlWrapped *request,
                                     BodaqsControlWrapped *response,
                                     uint8_t *type)
{
    BodaqsControlExchangeSlot *slot;
    if (!exchange || !request || !response || !type ||
        !exchange->master_boot_id || request->node_address >= 4)
    {
        return false;
    }
    if (poll)
    {
        uint8_t encoded[52];
        if (!bodaqs_control_encode_record(&request->record, encoded) ||
            !request->record.operation || !request->record.node_boot_id ||
            request->record.data_length ||
            (request->record.endpoint > 5 &&
             request->record.endpoint != BODAQS_CONTROL_NODE_WIDE))
        {
            return false;
        }
    }
    else if (!bodaqs_control_request_valid(&request->record))
    {
        return false;
    }
    *response = *request;
    response->master_boot_id = exchange->master_boot_id;
    *type = BODAQS_CONTROL_RECEIPT_RESPONSE;
    if (request->master_boot_id != exchange->master_boot_id)
    {
        receipt(response, BODAQS_CONTROL_REJECTED,
                BODAQS_CONTROL_REASON_STALE_MASTER,
                BODAQS_CONTROL_FIELD_MASTER_BOOT);
        return true;
    }
    slot = &exchange->slots[request->node_address];
    if (slot->state && same_header(&slot->request, &request->record))
    {
        if (!poll && !same_request(&slot->request, &request->record))
        {
            receipt(response, BODAQS_CONTROL_REJECTED,
                    BODAQS_CONTROL_REASON_REUSED, BODAQS_CONTROL_FIELD_RECORD);
            return true;
        }
        if (slot->state == EXCHANGE_COMPLETE)
        {
            response->record = slot->result;
            *type = BODAQS_CONTROL_POLL_RESPONSE;
        }
        else if (slot->state == EXCHANGE_NOT_DISPATCHED)
        {
            receipt(response, BODAQS_CONTROL_BUSY,
                    BODAQS_CONTROL_REASON_BUSY, BODAQS_CONTROL_FIELD_RECORD);
        }
        else if (slot->state == EXCHANGE_UNCERTAIN)
        {
            receipt(response, BODAQS_CONTROL_UNCERTAIN,
                    BODAQS_CONTROL_REASON_TIMEOUT, BODAQS_CONTROL_FIELD_RECORD);
        }
        else
        {
            receipt(response,
                    poll ? BODAQS_CONTROL_WAITING : BODAQS_CONTROL_DUPLICATE,
                    BODAQS_CONTROL_REASON_NONE, BODAQS_CONTROL_FIELD_NONE);
        }
        return true;
    }
    if (poll)
    {
        receipt(response, BODAQS_CONTROL_REJECTED,
                BODAQS_CONTROL_REASON_UNKNOWN_OPERATION,
                BODAQS_CONTROL_FIELD_RECORD);
        return true;
    }
    if (((exchange->excluded_addresses & (1U << request->node_address)) &&
         !inspection(request->record.opcode)) || slot->state == EXCHANGE_PENDING)
    {
        receipt(response, BODAQS_CONTROL_BUSY, BODAQS_CONTROL_REASON_BUSY,
                BODAQS_CONTROL_FIELD_RECORD);
        return true;
    }
    memset(slot, 0, sizeof(*slot));
    slot->request = request->record;
    slot->state = EXCHANGE_PENDING;
    slot->transaction = (uint16_t) exchange->next_transaction++;
    /* Transaction is transport correlation; full common identity disambiguates
     * late replies after wrapping this 16-bit number. */
    if (exchange->next_transaction > UINT16_MAX)
    {
        exchange->next_transaction = 1;
    }
    receipt(response, BODAQS_CONTROL_QUEUED, BODAQS_CONTROL_REASON_NONE,
            BODAQS_CONTROL_FIELD_NONE);
    return true;
}

void bodaqs_control_exchange_tick(BodaqsControlExchange *exchange, uint32_t now)
{
    unsigned i;
    for (i = 0; i < 4; ++i)
    {
        BodaqsControlExchangeSlot *slot = &exchange->slots[i];
        if (slot->state == EXCHANGE_PENDING && slot->attempts == 3 &&
            (uint32_t) (now - slot->attempt_ms) >= 1000U)
        {
            slot->state = EXCHANGE_UNCERTAIN;
        }
    }
}

bool bodaqs_control_exchange_transmit(BodaqsControlExchange *exchange,
                                      uint32_t now, uint8_t *address,
                                      uint16_t *transaction,
                                      uint8_t payload[64])
{
    uint8_t i;
    if (!exchange || !address || !transaction || !payload)
    {
        return false;
    }
    bodaqs_control_exchange_tick(exchange, now);
    for (i = 0; i < 4; ++i)
    {
        BodaqsControlExchangeSlot *slot = &exchange->slots[i];
        if (slot->state != EXCHANGE_PENDING)
        {
            continue;
        }
        if (slot->attempts && (uint32_t) (now - slot->attempt_ms) < 1000U)
        {
            continue;
        }
        if (slot->attempts == 3)
        {
            slot->state = EXCHANGE_UNCERTAIN;
            continue;
        }
        ++slot->attempts;
        slot->attempt_ms = now;
        *address = i;
        *transaction = slot->transaction;
        return bodaqs_control_encode_can(&slot->request, false,
                                         slot->transaction, payload);
    }
    return false;
}

bool bodaqs_control_exchange_receive(BodaqsControlExchange *exchange,
                                     uint8_t address, uint16_t transaction,
                                     const BodaqsControlRecord *reply)
{
    BodaqsControlRecord identity;
    BodaqsControlExchangeSlot *slot;
    if (!exchange || !reply || address >= 4)
    {
        return false;
    }
    slot = &exchange->slots[address];
    identity = *reply;
    if (identity.opcode == BODAQS_CONTROL_ERROR)
    {
        if (reply->data_length != 24 ||
            reply->data[0] != BODAQS_CONTROL_COMMAND_REJECTED)
        {
            ++exchange->late_replies;
            return false;
        }
        identity.opcode = reply->data[3];
    }
    /* Assigned transfer IDs only belong to challenge/snapshot opens. */
    if (reply->opcode != BODAQS_CONTROL_ERROR &&
        (slot->request.opcode == BODAQS_CONTROL_GET_CHALLENGE ||
         slot->request.opcode == BODAQS_CONTROL_OPEN_CAPABILITIES ||
         slot->request.opcode == BODAQS_CONTROL_OPEN_EFFECTIVE) &&
        slot->request.transfer == 0 && identity.transfer != 0)
    {
        identity.transfer = 0;
    }
    if (slot->state != EXCHANGE_PENDING || slot->transaction != transaction ||
        !same_header(&slot->request, &identity))
    {
        ++exchange->late_replies;
        return false;
    }
    /* Do not pin a malformed known result in the completed cache. The original
     * exchange retains its attempt budget and can receive a later valid reply. */
    if (reply->opcode == BODAQS_CONTROL_GET_NODE_STATE && reply->data_length != 24)
    {
        ++exchange->late_replies;
        return false;
    }
    slot->result = *reply;
    slot->state = EXCHANGE_COMPLETE;
    return true;
}
