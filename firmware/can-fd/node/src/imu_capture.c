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
static volatile bool sync_pending;
static BodaqsNodeCapture sync_observations[8];
static volatile unsigned sync_head, sync_tail;
static volatile uint32_t sync_dropped;
static uint32_t sync_ordinal, last_service_ms;
static uint32_t observed_high, rollover_observed_ms;
static volatile uint32_t last_interrupt_ms;
volatile BodaqsNodeCaptureClockInfo gNodeCaptureClockInfo;

/* Native ZERO period is 65.536 ms. Allow two rounded SysTicks of observation
 * margin, but detect absent servicing before two uncounted periods can pass.
 * This is an IRQ-progress deadline, not a foreground scheduling deadline. */
#define ROLLOVER_SERVICE_DEADLINE_MS 68U

static void clock_failure(uint32_t reason, uint32_t milliseconds) {
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    if (!clock_untrusted) {
        gNodeCaptureClockInfo.first_fault_reason = reason;
        gNodeCaptureClockInfo.first_fault_ms = milliseconds;
    }
    clock_untrusted = true;
    fault = true;
    __set_PRIMASK(mask);
}
void bodaqs_node_capture_init(void) {
    last_service_ms = 0;
    observed_high = rollover_observed_ms = last_interrupt_ms = 0;
    gNodeCaptureClockInfo = (BodaqsNodeCaptureClockInfo){.version = 1};
    high = ordinal = sync_ordinal = 0;
    sync_pending = false;sync_head=sync_tail=0;sync_dropped=0;
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
    if (raw & DL_TIMER_INTERRUPT_ZERO_EVENT) {
        high += 65536U;
        if (gNodeCaptureClockInfo.rollovers_serviced != UINT32_MAX)
            ++gNodeCaptureClockInfo.rollovers_serviced;
    }
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
            else clock_failure(BODAQS_CAPTURE_CLOCK_FAULT_LOSS_COUNTER_EXHAUSTED, last_interrupt_ms);
        }
        else {
            captures[head].tick = epoch + low;
            captures[head].ordinal = ordinal;
            head = next;
        }
    }
    if (raw & DL_TIMER_INTERRUPT_CC3_UP_EVENT) {
        uint32_t low = DL_TimerA_getCaptureCompareValue(ACQ_CAPTURE_INST, DL_TIMER_CC_3_INDEX);
        sync_capture.tick =
            base + (((raw & DL_TIMER_INTERRUPT_ZERO_EVENT) && low <= now) ? 65536U : 0U) + low;
        sync_capture.ordinal = ++sync_ordinal;
        sync_pending = true;
        unsigned next_sync=(sync_head+1U)%8U;
        if(next_sync!=sync_tail) {sync_observations[sync_head]=sync_capture;sync_head=next_sync;}
        else if(sync_dropped!=UINT32_MAX) ++sync_dropped;
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
    const uint32_t gap = milliseconds - last_service_ms;
    if (gap > gNodeCaptureClockInfo.maximum_foreground_gap_ms)
        gNodeCaptureClockInfo.maximum_foreground_gap_ms = gap;
    last_service_ms = milliseconds;
}

void bodaqs_node_capture_supervise_interrupt(uint32_t milliseconds) {
    /* SysTick and the capture IRQ continue while the foreground is delayed.
     * Observe the software high word, not a pending ZERO: a pending bit cannot
     * prove that every rollover was serviced. Never reconstruct ticks from ms.
     * A halt/global IRQ blackout can also lose SysTicks; continuity across that
     * condition remains unqualified, as it was with foreground supervision. */
    const uint32_t current_high = high;
    last_interrupt_ms = milliseconds;
    if (gNodeCaptureClockInfo.supervisor_ticks != UINT32_MAX)
        ++gNodeCaptureClockInfo.supervisor_ticks;
    const uint32_t age = milliseconds - rollover_observed_ms;
    if (age > gNodeCaptureClockInfo.maximum_rollover_age_ms)
        gNodeCaptureClockInfo.maximum_rollover_age_ms = age;
    if (current_high != observed_high) {
        observed_high = current_high;
        rollover_observed_ms = milliseconds;
        return;
    }
    if (age >= ROLLOVER_SERVICE_DEADLINE_MS)
        clock_failure(BODAQS_CAPTURE_CLOCK_FAULT_ROLLOVER_TIMEOUT, milliseconds);
}

void bodaqs_node_sync_marker(uint32_t sequence,uint32_t master_tick) {
    (void)sequence;(void)master_tick;
    /* Periodic trains cannot resolve a whole-period marker delay. No proven
     * delivery bound or unique causal seed exists: retain captures separately. */
}
bool bodaqs_node_sync_latest(uint32_t *sequence,uint32_t *tick) {
    (void)sequence;(void)tick;return false;
}
bool bodaqs_node_capture_sync_observation(BodaqsNodeCapture *capture) {
    uint32_t mask=__get_PRIMASK();bool present;__disable_irq();
    present=sync_head!=sync_tail;
    if(present) {*capture=sync_observations[sync_tail];sync_tail=(sync_tail+1U)%8U;}
    __set_PRIMASK(mask);return present;
}

uint32_t bodaqs_node_capture_sync_loss_take(void) {
    uint32_t mask=__get_PRIMASK(),value;__disable_irq();
    value=sync_dropped;sync_dropped=0;__set_PRIMASK(mask);return value;
}
void bodaqs_node_capture_sync_discard(void) {
    uint32_t mask=__get_PRIMASK();__disable_irq();
    sync_tail=sync_head;sync_dropped=0;sync_pending=false;
    /* A pre-boundary capture still waiting for its ISR is stale too. */
    DL_TimerA_clearInterruptStatus(ACQ_CAPTURE_INST,DL_TIMER_INTERRUPT_CC3_UP_EVENT);
    __set_PRIMASK(mask);
}
