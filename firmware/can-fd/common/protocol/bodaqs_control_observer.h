#ifndef BODAQS_CONTROL_OBSERVER_H
#define BODAQS_CONTROL_OBSERVER_H
#include "bodaqs_control.h"
#ifdef __cplusplus
extern "C"
{
#endif
    typedef struct
    {
        uint32_t node_boot_id, flags, pending_operation, observed_ms;
        uint64_t active_session, endpoint_epoch[6];
        uint16_t endpoint_mask, epoch_valid_mask;
        uint8_t receipt_state, reason, field;
        bool available, valid;
    } BodaqsControlObservation;
    typedef struct
    {
        uint64_t master_boot_id;
        uint32_t features, next_read_id;
        BodaqsControlObservation nodes[4];
        BodaqsControlWrapped current;
        uint8_t cursor_address, cursor_endpoint;
        bool pending;
    } BodaqsControlObserver;
    void bodaqs_control_observer_init(BodaqsControlObserver *observer);
    void bodaqs_control_observer_boot(BodaqsControlObserver *observer,
                                      uint64_t boot, uint32_t features);
    void bodaqs_control_observer_node(BodaqsControlObserver *observer,
                                      uint8_t address, uint32_t node_boot,
                                      uint16_t endpoints, bool available);
    /* Each call prepares one bounded submit/poll; no physical transport
     * dependency. */
    bool bodaqs_control_observer_next(BodaqsControlObserver *observer,
                                      BodaqsControlWrapped *request,
                                      uint8_t *type);
    bool bodaqs_control_observer_accept(BodaqsControlObserver *observer,
                                        uint8_t type,
                                        const BodaqsControlWrapped *reply,
                                        uint32_t now);
#ifdef __cplusplus
}
#endif
#endif
