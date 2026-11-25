#ifndef BODAQS_MASTER_CRC_H
#define BODAQS_MASTER_CRC_H
#include "bodaqs_measurement.h"
typedef struct {
 uint32_t version,enabled,hardware_calls,isr_fallback_calls,cold_fallback_calls;
} MasterCrcInfo;
#if BODAQS_MASTER_HW_CRC
#ifdef __cplusplus
extern "C" {
#endif
extern volatile MasterCrcInfo gMasterCrcInfo;
void bodaqs_master_crc_init(void);
#if defined(BODAQS_CRC_SELFTEST) && BODAQS_CRC_SELFTEST
typedef struct {uint32_t version,state,checks,failures;} MasterCrcSelfTest;
extern volatile MasterCrcSelfTest gMasterCrcSelfTest;
void bodaqs_master_crc_selftest(void);
#endif
#ifdef __cplusplus
}
#endif
#endif
#endif
