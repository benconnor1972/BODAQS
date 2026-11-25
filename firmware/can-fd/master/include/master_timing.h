#ifndef BODAQS_MASTER_TIMING_H
#define BODAQS_MASTER_TIMING_H
#include <stdbool.h>
#include <stdint.h>
uint32_t bodaqs_master_timing_dropped(void);
void bodaqs_master_timing_init(void);
void bodaqs_master_timing_irq(void);
void bodaqs_master_timing_supervise(uint32_t milliseconds);
uint32_t bodaqs_master_timing_clock(void *,uint32_t *epoch);
bool bodaqs_master_timing_take(uint32_t *sequence,uint32_t *edge_tick);
#endif
