#include "imu_capture.h"
#include "ti_msp_dl_config.h"
/* A pending bit cannot count overwritten captures. Faults therefore carry
 * unknown loss, never a synthetic edge or an exact hardware-loss count. */
static volatile uint32_t high, ordinal;
static volatile unsigned head, tail;
static volatile bool fault, watermark;
static volatile bool clock_untrusted;
static volatile uint32_t dropped;
static BodaqsNodeCapture captures[128], sync_capture;
static volatile bool sync_pending, sync_lost;
static bool sync_seed, sync_valid;
static uint32_t marker_sequence, marker_tick, paired_tick, paired_ordinal;
static uint32_t sync_ordinal, last_service_ms;
void bodaqs_node_capture_init(void) {
    last_service_ms = 0;
    high = ordinal = sync_ordinal = 0;
    sync_pending = sync_lost = sync_seed = sync_valid = false;
    head = tail = 0;
    fault = watermark = false;
    clock_untrusted=false;
    dropped=0;
    DL_TimerA_setTimerCount(ACQ_CAPTURE_INST, 0);
    DL_TimerA_setDebugReleaseBehavior(ACQ_CAPTURE_INST, DL_TIMER_DEBUG_RES_RESUME);
    DL_TimerA_clearInterruptStatus(ACQ_CAPTURE_INST, ~0U);
    NVIC_EnableIRQ(ACQ_CAPTURE_INST_INT_IRQN);
    DL_TimerA_startCounter(ACQ_CAPTURE_INST);
}
void bodaqs_node_capture_irq(void) {
    uint32_t raw = DL_TimerA_getRawInterruptStatus(ACQ_CAPTURE_INST, ~0U);
    uint32_t now = DL_TimerA_getTimerCount(ACQ_CAPTURE_INST), base = high;
    if (raw & DL_TIMER_INTERRUPT_ZERO_EVENT)
        high += 65536U;
    if (raw & DL_TIMER_INTERRUPT_CC2_UP_EVENT) {
        uint32_t low = DL_TimerA_getCaptureCompareValue(ACQ_CAPTURE_INST, DL_TIMER_CC_2_INDEX);
        uint32_t epoch = base;
        if ((raw & DL_TIMER_INTERRUPT_ZERO_EVENT) && low <= now)
            epoch += 65536U;
        unsigned next = (head + 1U) % 128U;
        ++ordinal; /* assign before the software queue, including rejected edges */
        if (next == tail) {
            fault = true;
            if(dropped!=UINT32_MAX) ++dropped;
            else clock_untrusted=true;
        }
        else {
            captures[head].tick = epoch + low;
            captures[head].ordinal = ordinal;
            head = next;
        }
    }
    if (raw & DL_TIMER_INTERRUPT_CC3_UP_EVENT) {
        uint32_t low = DL_TimerA_getCaptureCompareValue(ACQ_CAPTURE_INST, DL_TIMER_CC_3_INDEX);
        if(sync_pending) sync_lost=true;
        sync_capture.tick =
            base + (((raw & DL_TIMER_INTERRUPT_ZERO_EVENT) && low <= now) ? 65536U : 0U) + low;
        sync_capture.ordinal = ++sync_ordinal;
        sync_pending = true;
    }
    if (raw & DL_TIMER_INTERRUPT_CC1_UP_EVENT)
        watermark = true;
    if (raw & DL_TIMER_INTERRUPT_OVERFLOW_EVENT)
        fault = true;
    DL_TimerA_clearInterruptStatus(ACQ_CAPTURE_INST, raw);
}
uint32_t bodaqs_node_capture_clock(void *context, uint32_t *epoch) {
    uint32_t mask = __get_PRIMASK(), value, pending;
    (void)context;
    __disable_irq();
    pending = DL_TimerA_getRawInterruptStatus(ACQ_CAPTURE_INST, DL_TIMER_INTERRUPT_ZERO_EVENT);
    value = DL_TimerA_getTimerCount(ACQ_CAPTURE_INST);
    /* Re-read if ZERO arrived between status and count. */
    if (!pending &&
        DL_TimerA_getRawInterruptStatus(ACQ_CAPTURE_INST, DL_TIMER_INTERRUPT_ZERO_EVENT)) {
        pending = 1;
        value = DL_TimerA_getTimerCount(ACQ_CAPTURE_INST);
    }
    value += high + (pending ? 65536U : 0U);
    *epoch = 1;
    __set_PRIMASK(mask);
    return value;
}
bool bodaqs_node_capture_take(BodaqsNodeCapture *c) {
    uint32_t mask = __get_PRIMASK();
    bool ok;
    __disable_irq();
    ok = head != tail;
    if (ok) {
        *c = captures[tail];
        tail = (tail + 1U) % 128U;
    }
    __set_PRIMASK(mask);
    return ok;
}
void bodaqs_node_capture_discard(void) {
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    tail = head;
    fault = false;
    __set_PRIMASK(mask);
}
bool bodaqs_node_capture_fault(void) { return fault; }
bool bodaqs_node_capture_clock_trusted(void) { return !clock_untrusted; }
uint32_t bodaqs_node_capture_loss_take(void) {
    uint32_t mask=__get_PRIMASK(),value;
    __disable_irq();value=dropped;dropped=0;__set_PRIMASK(mask);
    return value;
}
bool bodaqs_node_watermark_take(void) {
    uint32_t mask = __get_PRIMASK();
    bool v;
    __disable_irq();
    v = watermark;
    watermark = false;
    __set_PRIMASK(mask);
    return v;
}

bool bodaqs_node_capture_seed_end(void) {
    uint32_t mask = __get_PRIMASK();
    bool clean;
    __disable_irq();
    clean = head == tail && !fault &&
            !(DL_TimerA_getRawInterruptStatus(ACQ_CAPTURE_INST, DL_TIMER_INTERRUPT_CC2_UP_EVENT));
    __set_PRIMASK(mask);
    return clean;
}
bool bodaqs_node_capture_sync_take(BodaqsNodeCapture *c) {
    uint32_t mask = __get_PRIMASK();
    bool ok;
    __disable_irq();
    ok = sync_pending;
    if (ok) {
        *c = sync_capture;
        sync_pending = false;
    }
    __set_PRIMASK(mask);
    return ok;
}

void bodaqs_node_capture_supervise(uint32_t milliseconds) {
    /* A single pending ZERO cannot prove the number of wraps across a long
     * service blackout. Milliseconds only detect this failure; they are never
     * substituted for captured evidence. Debugger-halt continuity is unqualified.
     */
    if ((uint32_t)(milliseconds - last_service_ms) >= 65U) {
        fault = true;
        clock_untrusted=true;
    }
    last_service_ms = milliseconds;
}

void bodaqs_node_sync_marker(uint32_t sequence,uint32_t master_tick) {
    BodaqsNodeCapture capture;
    bool lost=sync_lost;sync_lost=false;
    bool present=bodaqs_node_capture_sync_take(&capture);
    sync_valid=false;
    if(!present || lost || (sync_seed && sequence<=marker_sequence)) {sync_seed=false;return;}
    if(sync_seed && sequence==marker_sequence+1 && capture.ordinal==paired_ordinal+1 &&
       master_tick-marker_tick==100000U && capture.tick-paired_tick>=99000U &&
       capture.tick-paired_tick<=101000U) sync_valid=true;
    marker_sequence=sequence;marker_tick=master_tick;paired_tick=capture.tick;paired_ordinal=capture.ordinal;
    sync_seed=true;
}
bool bodaqs_node_sync_latest(uint32_t *sequence,uint32_t *tick) {
    uint32_t e,now=bodaqs_node_capture_clock(0,&e);
    if(!sync_valid || (uint32_t)(now-paired_tick)>150000U) return false;
    *sequence=marker_sequence;*tick=paired_tick;return true;
}
