#ifndef BODAQS_MASTER_PROFILE_H
#define BODAQS_MASTER_PROFILE_H
#include <stdint.h>

/* Optional main-owner diagnostic hooks; no wire or service-state changes. */
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
#ifdef __cplusplus
extern "C" {
#endif
uint32_t bodaqs_master_profile_clock(void);
void bodaqs_master_profile_record(uint32_t decode_us, uint32_t dispatch_us,
    uint32_t encode_us, uint8_t request_kind, uint8_t reply_kind);
#ifdef __cplusplus
}
#endif
#endif
#endif
