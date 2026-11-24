#ifndef BODAQS_CONTROL_APPLY_CLIENT_H
#define BODAQS_CONTROL_APPLY_CLIENT_H
#include "bodaqs_control_authority_client.h"
#ifdef __cplusplus
extern "C"
{
#endif
    typedef struct
    {
        uint64_t desired_generation, revision, accepted_generation, session;
        uint32_t operation, boot, observed_ms;
        uint8_t kind, reason;
        bool valid;
    } BodaqsControlApplyOutcome;
    typedef struct
    {
        BodaqsControlWrapped current;
        BodaqsControlApplyOutcome nodes[4], previous[4];
        uint8_t descriptor[44], metadata[24], phase, resume_phase;
        uint32_t started, committed, next_query;
        uint64_t next_transfer;
        bool pending, commit_sent;
    } BodaqsControlApplyClient;
    void bodaqs_control_apply_client_init(BodaqsControlApplyClient *);
    /* Reusable complete schema1/v1 desired seam. Sequence/read allocation remains
     * with the authority client; start does not claim node acceptance. */
    bool bodaqs_control_apply_client_start(BodaqsControlApplyClient *,
                                           BodaqsControlAuthorityClient *, uint64_t master,
                                           uint8_t address, uint64_t generation, uint64_t revision,
                                           const uint8_t descriptor[44], uint32_t now);
    bool bodaqs_control_apply_client_next(BodaqsControlApplyClient *,
                                          BodaqsControlAuthorityClient *, uint32_t now,
                                          BodaqsControlWrapped *, uint8_t *type);
    bool bodaqs_control_apply_client_accept(BodaqsControlApplyClient *,
                                            BodaqsControlAuthorityClient *, uint8_t type,
                                            const BodaqsControlWrapped *, uint32_t now);
    /* Local transport ownership and recording transitions preserve uncertainty;
     * neither transition cancels accepted node application. */
    void bodaqs_control_apply_client_transport_timeout(BodaqsControlApplyClient *, uint32_t now);
    void bodaqs_control_apply_client_quarantine(BodaqsControlApplyClient *,
                                                BodaqsControlAuthorityClient *, uint32_t now);
    void bodaqs_control_apply_client_recording_fence(BodaqsControlApplyClient *,
                                                     BodaqsControlAuthorityClient *, uint32_t now);
    void bodaqs_control_apply_client_invalidate(BodaqsControlApplyClient *, uint8_t address);
#ifdef __cplusplus
}
#endif
#endif
