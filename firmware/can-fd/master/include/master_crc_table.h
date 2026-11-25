#ifndef BODAQS_MASTER_CRC_TABLE_H
#define BODAQS_MASTER_CRC_TABLE_H
#include "bodaqs_measurement.h"
#if defined(BODAQS_MASTER_CRC_RAM) && BODAQS_MASTER_CRC_RAM
/* RW section ensures C-runtime initialization; no runtime writer after startup.
 * Main and ISR share read-only access through the codec. */
uint32_t bodaqs_master_crc_table[256]
    __attribute__((section(".bodaqs_crc_table"),aligned(4))) = {
#include "bodaqs_crc32_table_values.h"
};
#endif
#endif
