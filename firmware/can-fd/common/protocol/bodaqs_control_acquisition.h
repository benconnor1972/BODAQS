#ifndef BODAQS_CONTROL_ACQUISITION_H
#define BODAQS_CONTROL_ACQUISITION_H
#include "bodaqs_control_authority.h"
#ifdef __cplusplus
extern "C"
{
#endif
#define BODAQS_ACQ_PREPARE_BYTES 112U
#define BODAQS_ACQ_STATE_BYTES 128U
#define BODAQS_ACQ_LEASE_MS 1000U
#define BODAQS_ACQ_RESPONSE_MS 300U
#define BODAQS_ACQ_RENEW_MS 100U
    /* One nonblocking main-loop hardware owner. Commands are delivered once; POLL
     * observes independent completion. Every event echoes generation. A backend must
     * stop/discard on STOP, even if PREPARE/START has not completed. No ISR SPI writes. */
    enum
    {
        BODAQS_ACQ_POLL,
        BODAQS_ACQ_PREPARE,
        BODAQS_ACQ_START,
        BODAQS_ACQ_STOP,
        BODAQS_ACQ_FENCE
    };
    enum
    {
        BODAQS_ACQ_NO_EVENT,
        BODAQS_ACQ_READY,
        BODAQS_ACQ_FIRST,
        BODAQS_ACQ_STOPPED,
        BODAQS_ACQ_FENCED,
        BODAQS_ACQ_FAILED
    };
    typedef struct
    {
        uint32_t generation;
        uint8_t kind, reason;
        uint8_t boundary[16];
        uint32_t node_clock_epoch, sensor_clock_epoch;
        bool known_empty, register_proof_current;
        uint8_t register_image[24];
    } BodaqsAcquisitionEvent;
    typedef uint32_t (*BodaqsAcquisitionClock)(void *context, uint32_t *clock_epoch);
    typedef void (*BodaqsAcquisitionBackend)(void *context, uint8_t command, uint32_t generation,
                                             uint64_t recording, uint32_t now,
                                             BodaqsAcquisitionEvent *event);
    typedef struct
    {
        BodaqsControlAuthority *authority;
        BodaqsControlNode *view;
        uint8_t *effective;
        BodaqsAcquisitionBackend backend;
        void *backend_context;
        BodaqsAcquisitionClock clock;
        void *clock_context;
        BodaqsControlRecord begin, pending, commit, challenge_request, renewal_request,
            renewal_result;
        uint8_t staged[112], first[16], final[16];
        uint64_t recording, owner, challenge, terminated_record;
        uint32_t staged_ms, prepared_ms, issued_ms, lease_deadline, renewal_sequence;
        uint32_t generation, node_clock_epoch, sensor_clock_epoch;
        uint32_t issued_tick, prepared_tick, lease_tick;
        uint8_t pages, phase, reason, command;
        bool staged_valid, staging, challenge_valid, lease_valid, terminal;
        bool ready, stopped, fenced, known_empty, first_valid, final_valid;
        bool command_sent, renewal_valid, commit_valid, stage_aborted;
    } BodaqsControlAcquisition;
    void bodaqs_control_acquisition_init(BodaqsControlAcquisition *, BodaqsControlAuthority *,
                                         BodaqsControlNode *, uint8_t effective[192],
                                         BodaqsAcquisitionBackend, void *);
    /* Bind before staging. #169 supplies the same low32 nominal-us capture clock
     * and epoch used by backend sample boundaries. Unbound fallback is quantized
     * milliseconds and cannot establish qualified native readiness. */
    bool bodaqs_control_acquisition_set_clock(BodaqsControlAcquisition *, BodaqsAcquisitionClock,
                                              void *);
    bool bodaqs_control_acquisition_process(BodaqsControlAcquisition *, const BodaqsControlRecord *,
                                            uint32_t now, BodaqsControlRecord *);
    void bodaqs_control_acquisition_tick(BodaqsControlAcquisition *, uint32_t now);
    void bodaqs_control_acquisition_capture(void *, const BodaqsControlNode *, uint8_t out[128],
                                            uint32_t now);
    /* Immediate logical exclusion; physical cancellation is still performed by tick. */
    void bodaqs_control_acquisition_exclude(BodaqsControlAcquisition *, uint8_t reason);
#ifdef __cplusplus
}
#endif
#endif
