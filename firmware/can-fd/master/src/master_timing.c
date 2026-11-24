#include "master_timing.h"
#include "ti_msp_dl_config.h"
/* TIMA0/PA25 is reserved by this adapter. BUSCLK=80MHz /80 gives native
 * 1MHz. A 16-bit 100000-count period would truncate: toggle CH3 on each
 * 50000-count ZERO instead. Only rising hardware-output events are SYNC.
 * These are output-generation observations, not measured pad propagation. */
static volatile uint32_t base, sequence, edge, pending_sequence, dropped;
static volatile bool high_output, pending, fault;
static uint32_t last_service;
void bodaqs_master_timing_init(void) {
    const DL_TimerA_ClockConfig clock={DL_TIMER_CLOCK_BUSCLK,DL_TIMER_CLOCK_DIVIDE_1,79};
    const DL_TimerA_TimerConfig timer={DL_TIMER_TIMER_MODE_PERIODIC_UP,49999,DL_TIMER_STOP,
        DL_TIMER_INTERM_INT_DISABLED,0};
    base=sequence=edge=pending_sequence=dropped=last_service=0;high_output=pending=fault=false;
    DL_TimerA_reset(TIMA0);DL_TimerA_enablePower(TIMA0);delay_cycles(POWER_STARTUP_DELAY);
    DL_GPIO_initPeripheralOutputFunction(IOMUX_PINCM55,IOMUX_PINCM55_PF_TIMA0_CCP3);
    DL_TimerA_setClockConfig(TIMA0,(DL_TimerA_ClockConfig *)&clock);
    DL_TimerA_initTimerMode(TIMA0,(DL_TimerA_TimerConfig *)&timer);
    DL_TimerA_setCaptureCompareOutCtl(TIMA0,DL_TIMER_CC_OCTL_INIT_VAL_LOW,
        DL_TIMER_CC_OCTL_INV_OUT_DISABLED,DL_TIMER_CC_OCTL_SRC_FUNCVAL,DL_TIMER_CC_3_INDEX);
    DL_TimerA_setCaptureCompareAction(TIMA0,DL_TIMER_CC_ZACT_CCP_TOGGLE,DL_TIMER_CC_3_INDEX);
    DL_TimerA_setCCPDirection(TIMA0,DL_TIMER_CC3_OUTPUT);
    DL_TimerA_setTimerCount(TIMA0,0);
    DL_TimerA_setDebugReleaseBehavior(TIMA0,DL_TIMER_DEBUG_RES_RESUME);
    DL_TimerA_clearInterruptStatus(TIMA0,~0U);
    DL_TimerA_enableInterrupt(TIMA0,DL_TIMER_INTERRUPT_ZERO_EVENT);
    DL_TimerA_enableClock(TIMA0);NVIC_EnableIRQ(TIMA0_INT_IRQn);
    DL_TimerA_startCounter(TIMA0);
}
void bodaqs_master_timing_irq(void) {
    uint32_t raw=DL_TimerA_getRawInterruptStatus(TIMA0,DL_TIMER_INTERRUPT_ZERO_EVENT);
    if(raw) {
        base+=50000U;high_output=!high_output;
        if(high_output) {
            if(sequence==UINT32_MAX) fault=true;
            else {
                ++sequence;
                if(!pending) {edge=base;pending_sequence=sequence;pending=true;}
                else if(dropped!=UINT32_MAX) ++dropped;
                // Periodic evidence backpressure does not reset the native clock.
            }
        }
        DL_TimerA_clearInterruptStatus(TIMA0,raw);
    }
}
uint32_t bodaqs_master_timing_clock(void *unused,uint32_t *epoch) {
    uint32_t mask=__get_PRIMASK(),low,raw,value;(void)unused;
    __disable_irq();raw=DL_TimerA_getRawInterruptStatus(TIMA0,DL_TIMER_INTERRUPT_ZERO_EVENT);
    low=DL_TimerA_getTimerCount(TIMA0);
    if(!raw && DL_TimerA_getRawInterruptStatus(TIMA0,DL_TIMER_INTERRUPT_ZERO_EVENT)) {
        raw=1;low=DL_TimerA_getTimerCount(TIMA0);
    }
    value=base+(raw?50000U:0U)+low;*epoch=fault?0:1;__set_PRIMASK(mask);return value;
}
bool bodaqs_master_timing_take(uint32_t *seq,uint32_t *tick) {
    uint32_t mask=__get_PRIMASK();bool ok;__disable_irq();ok=pending&&!fault;
    if(ok) {*seq=pending_sequence;*tick=edge;pending=false;}__set_PRIMASK(mask);return ok;
}
void bodaqs_master_timing_supervise(uint32_t milliseconds) {
    if((uint32_t)(milliseconds-last_service)>=50U) fault=true;
    last_service=milliseconds;
}

uint32_t bodaqs_master_timing_dropped(void) { return dropped; }
