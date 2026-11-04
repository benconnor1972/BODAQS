#ifndef BODAQS_CONTROL_APPLY_H
#define BODAQS_CONTROL_APPLY_H
#include "bodaqs_control_authority.h"
#include "bodaqs_control_snapshot.h"
#include "bodaqs_imu_disabled.h"
#ifdef __cplusplus
extern "C"
{
#endif
    typedef struct
    {
        BodaqsControlAuthority *authority;
        BodaqsControlNode *view;
        BodaqsImuDisabled *backend;
        BodaqsControlRecord begin;
        uint8_t staging[512], effective[192];
        uint32_t started;
        uint8_t phase, pages;
        bool valid;
    } BodaqsControlApply;
    void bodaqs_control_apply_init(BodaqsControlApply *, BodaqsControlAuthority *,
                                   BodaqsControlNode *, BodaqsImuDisabled *);
    bool bodaqs_control_apply_process(BodaqsControlApply *, const BodaqsControlRecord *,
                                      uint32_t now, BodaqsControlRecord *);
    void bodaqs_control_apply_tick(BodaqsControlApply *, uint32_t now);
    /* Snapshot capture callback; caller can append firmware/UID capability provenance. */
    void bodaqs_control_apply_capture(void *, const BodaqsControlNode *, uint8_t endpoint,
                                      bool effective, uint8_t *);
#ifdef __cplusplus
}
#endif
#endif
