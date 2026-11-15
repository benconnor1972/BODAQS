#ifndef BODAQS_MASTER_PROFILE_H
#define BODAQS_MASTER_PROFILE_H
#include <stdint.h>

/* Fine work counters are optional independently of coarse phase timing. */
#ifndef BODAQS_MASTER_WORK_TIMING
#define BODAQS_MASTER_WORK_TIMING 1
#endif
#if BODAQS_MASTER_WORK_TIMING != 0 && BODAQS_MASTER_WORK_TIMING != 1
#error BODAQS_MASTER_WORK_TIMING must be 0 or 1
#endif
/* Optional main-owner diagnostic hooks; no wire or service-state changes. */
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
#ifdef __cplusplus
extern "C" {
#endif
uint32_t bodaqs_master_profile_clock(void);
void bodaqs_master_work_record(unsigned stage,uint32_t elapsed_us);
void bodaqs_master_dispatch_record(uint32_t manage_us, uint32_t transfer_us,
    uint32_t hints_us, uint8_t request_kind, uint8_t reply_kind);
void bodaqs_master_profile_record(uint32_t decode_us, uint32_t dispatch_us,
    uint32_t encode_us, uint8_t request_kind, uint8_t reply_kind);
#ifdef __cplusplus
}
#endif
#if BODAQS_MASTER_WORK_TIMING
#define BODAQS_WORK_BEGIN(name) const uint32_t name=bodaqs_master_profile_clock()
#define BODAQS_WORK_END(stage,name) bodaqs_master_work_record(stage,bodaqs_master_profile_clock()-(name))
#endif
#endif
#ifndef BODAQS_WORK_BEGIN
#define BODAQS_WORK_BEGIN(name) ((void)0)
#define BODAQS_WORK_END(stage,name) ((void)0)
#endif
#endif
