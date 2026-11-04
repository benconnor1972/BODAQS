#ifndef BODAQS_CONTROL_AUTHORITY_CLIENT_H
#define BODAQS_CONTROL_AUTHORITY_CLIENT_H
#include "bodaqs_control.h"
#ifdef __cplusplus
extern "C"
{
#endif
    typedef struct
    {
        BodaqsControlWrapped bind; /* Exact successful/uncertain BIND retry identity. */
        uint32_t boot;
        uint32_t next_mutation;
        uint32_t confirmed_ms;
        uint8_t phase, reason;
        bool available, bound, releasing, ever_bound;
    } BodaqsControlAuthorityPeer;
    typedef struct
    {
        uint64_t session;
        uint32_t next_read;
        bool pending;
        BodaqsControlWrapped current;
        BodaqsControlAuthorityPeer nodes[4];
    } BodaqsControlAuthorityClient;
    void bodaqs_control_authority_client_init(BodaqsControlAuthorityClient *, uint64_t session);
    void bodaqs_control_authority_client_node(BodaqsControlAuthorityClient *, uint8_t address, uint32_t boot,
                                              bool available);
    bool bodaqs_control_authority_client_next(BodaqsControlAuthorityClient *, uint64_t master_boot,
                                              BodaqsControlWrapped *, uint8_t *);
    bool bodaqs_control_authority_client_accept(BodaqsControlAuthorityClient *, uint8_t type,
                                                const BodaqsControlWrapped *, uint32_t now);
    /* A fresh node-wide observation can revoke acknowledged authority, never grant it. */
    void bodaqs_control_authority_client_observe_session(BodaqsControlAuthorityClient *, uint8_t address,
                                                         uint64_t active_session);
    bool bodaqs_control_authority_client_release(BodaqsControlAuthorityClient *, uint8_t address);
#ifdef __cplusplus
}
#endif
#endif
