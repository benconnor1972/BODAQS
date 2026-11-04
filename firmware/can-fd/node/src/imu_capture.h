#ifndef BODAQS_NODE_IMU_CAPTURE_H
#define BODAQS_NODE_IMU_CAPTURE_H
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    uint32_t tick, ordinal;
} BodaqsNodeCapture;
void bodaqs_node_capture_init(void);
void bodaqs_node_capture_irq(void);
void bodaqs_node_capture_supervise(uint32_t milliseconds);
uint32_t bodaqs_node_capture_clock(void *, uint32_t *epoch);
bool bodaqs_node_capture_take(BodaqsNodeCapture *);
void bodaqs_node_capture_discard(void);
bool bodaqs_node_capture_fault(void);
bool bodaqs_node_capture_clock_trusted(void);
uint32_t bodaqs_node_capture_loss_take(void);
/* FIFO transition fence: reject any edge during enable/readback, including a
 * hardware capture still pending at the end of the critical transition. */
bool bodaqs_node_capture_seed_end(void);
bool bodaqs_node_capture_sync_take(BodaqsNodeCapture *);
void bodaqs_node_sync_marker(uint32_t sequence,uint32_t master_tick);
bool bodaqs_node_sync_latest(uint32_t *sequence,uint32_t *node_tick);
bool bodaqs_node_watermark_take(void);
#endif
