#ifndef BODAQS_MASTER_CRC_PORT_H
#define BODAQS_MASTER_CRC_PORT_H
#include "ti_msp_dl_config.h"
#include "ti/driverlib/dl_crcp.h"
static inline bool master_crc_in_isr(void) {return __get_IPSR()!=0;}
static inline void master_crc_power_init(void) {
 DL_CRCP_reset(CRC);DL_CRCP_enablePower(CRC);DL_Common_delayCycles(32);
}
static inline void master_crc_begin(void) {
 DL_CRCP_init(CRC,DL_CRCP_POLYNOMIAL_SIZE_32,DL_CRCP_BIT_REVERSED,
  DL_CRCP_INPUT_ENDIANESS_LITTLE_ENDIAN,DL_CRCP_OUTPUT_BYTESWAP_DISABLED);
 DL_CRCP_setPolynomial(CRC,0x04c11db7U);DL_CRCP_setSeed32(CRC,0xffffffffU);
}
static inline void master_crc_feed8(uint8_t v) {DL_CRCP_feedData8(CRC,v);}
static inline void master_crc_feed32(uint32_t v) {DL_CRCP_feedData32(CRC,v);}
static inline uint32_t master_crc_result(void) {return ~DL_CRCP_getResult32(CRC);}
#endif
