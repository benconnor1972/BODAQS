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
/* Call once per SysTick, independently of foreground acquisition progress. */
void bodaqs_node_capture_supervise_interrupt(uint32_t milliseconds);
enum {
    BODAQS_CAPTURE_CLOCK_FAULT_NONE = 0,
    BODAQS_CAPTURE_CLOCK_FAULT_ROLLOVER_TIMEOUT = 1,
    BODAQS_CAPTURE_CLOCK_FAULT_LOSS_COUNTER_EXHAUSTED = 2
};
/* Read-only debugger diagnostics. No protocol or recording-format extension. */
typedef struct {
    uint32_t version;
    uint32_t first_fault_reason, first_fault_ms;
    uint32_t maximum_foreground_gap_ms, maximum_rollover_age_ms;
    uint32_t rollovers_serviced, supervisor_ticks;
} BodaqsNodeCaptureClockInfo;
extern volatile BodaqsNodeCaptureClockInfo gNodeCaptureClockInfo;
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
uint32_t bodaqs_node_capture_sync_loss_take(void);
bool bodaqs_node_capture_sync_observation(BodaqsNodeCapture *);
/* START boundary for SYNC observations/loss only. Preserve clocks, ordinals,
 * DRDY captures and faults; subsequent observation loss remains accountable. */
void bodaqs_node_capture_sync_discard(void);
void bodaqs_node_sync_marker(uint32_t sequence,uint32_t master_tick);
bool bodaqs_node_sync_latest(uint32_t *sequence,uint32_t *node_tick);
bool bodaqs_node_watermark_take(void);
#endif
