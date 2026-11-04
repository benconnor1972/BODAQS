#ifndef BODAQS_CONTROL_EXCHANGE_H
#define BODAQS_CONTROL_EXCHANGE_H
#include "bodaqs_control.h"
#ifdef __cplusplus
extern "C"
{
#endif
    typedef struct
    {
        BodaqsControlRecord request, result;
        uint32_t attempt_ms;
        uint16_t transaction;
        uint8_t attempts;
        uint8_t state; /* 0 empty, 1 pending, 2 complete, 3 uncertain, 4 not dispatched */
    } BodaqsControlExchangeSlot;
    typedef struct
    {
        uint64_t master_boot_id;
        uint32_t next_transaction;
        uint32_t late_replies;
        uint8_t excluded_addresses;
        BodaqsControlExchangeSlot slots[4];
    } BodaqsControlExchange;
    void bodaqs_control_exchange_init(BodaqsControlExchange *exchange,
                                      uint64_t boot);
    /* Live master duplicate latch. Stop configuration dispatch/retry; a possibly
     * transmitted exchange becomes uncertain, never a node rejection/cancel. */
    void bodaqs_control_exchange_exclude(BodaqsControlExchange *, uint8_t addresses);
    bool bodaqs_control_exchange_request(BodaqsControlExchange *exchange,
                                         bool poll,
                                         const BodaqsControlWrapped *request,
                                         BodaqsControlWrapped *response,
                                         uint8_t *response_type);
    /* One bounded outgoing attempt per main-loop call; failed enqueue still
     * consumes an attempt, retaining a finite budget during controller faults.
     */
    void bodaqs_control_exchange_tick(BodaqsControlExchange *exchange,
                                      uint32_t now);
    bool bodaqs_control_exchange_transmit(BodaqsControlExchange *exchange,
                                          uint32_t now, uint8_t *address,
                                          uint16_t *transaction,
                                          uint8_t payload[64]);
    bool bodaqs_control_exchange_receive(BodaqsControlExchange *exchange,
                                         uint8_t address, uint16_t transaction,
                                         const BodaqsControlRecord *reply);
#ifdef __cplusplus
}
#endif
#endif
