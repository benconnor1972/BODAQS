#include "imu_capture.h"
#include "ti_msp_dl_config.h"
#include <assert.h>
uint32_t raw, count, cc[4];
uint32_t test_irq_mask,test_last_clear_irq_mask;
int main(void) {
    BodaqsNodeCapture c;
    uint32_t e;
    bodaqs_node_capture_init();
    raw = 5;
    count = 20;
    cc[2] = 65530;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick == 65530 && c.ordinal == 1);
    raw = 4;
    count = 40;
    cc[2] = 30;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick == 65566);
    assert(bodaqs_node_capture_clock(0, &e) == 65576 && e == 1);
    bodaqs_node_capture_init();
    raw = 5;
    count = 20;
    cc[2] = 10;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick == 65546);
    raw = 16;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_fault());
    assert(bodaqs_node_capture_clock(0, &e) == 65556);
    bodaqs_node_capture_init();
    raw = 4;
    count = 65530;
    cc[2] = 65530;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick == 65530);
    raw = 1;
    count = 0;
    bodaqs_node_capture_irq();
    raw = 4;
    count = 20;
    cc[2] = 10;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick == 65546);
    bodaqs_node_capture_init();
    for (unsigned i = 0; i < 129; ++i) {
        raw = 4;
        count = i;
        cc[2] = i;
        bodaqs_node_capture_irq();
    }
    assert(bodaqs_node_capture_fault());
    assert(bodaqs_node_capture_loss_take()==2);
    bodaqs_node_capture_discard();
    raw=4;count=200;cc[2]=200;bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.ordinal==130);
    assert(bodaqs_node_capture_loss_take()==0);
    bodaqs_node_capture_init();
    bodaqs_node_capture_supervise(140);
    /* Foreground delay alone says nothing about timer IRQ continuity. */
    assert(!bodaqs_node_capture_fault());
    bodaqs_node_capture_discard();
    assert(bodaqs_node_capture_clock_trusted());
    bodaqs_node_capture_init();
    raw=8;count=100;cc[3]=100;bodaqs_node_capture_irq();
    bodaqs_node_sync_marker(41,900000);
    uint32_t sequence,tick;
    assert(!bodaqs_node_sync_latest(&sequence,&tick));
    raw=1;count=0;bodaqs_node_capture_irq();
    raw=8;count=34564;cc[3]=34564;bodaqs_node_capture_irq();
    bodaqs_node_sync_marker(42,1000000);
    assert(!bodaqs_node_sync_latest(&sequence,&tick));
    // These captures could belong to markers 42/43 while delayed markers 41/42
    // still have perfect cadence. No delivery bound or causal seed is known.
    assert(bodaqs_node_capture_sync_observation(&c) && c.tick==100 && c.ordinal==1);
    assert(bodaqs_node_capture_sync_observation(&c) && c.tick==100100 && c.ordinal==2);
    bodaqs_node_sync_marker(40,800000);
    assert(!bodaqs_node_sync_latest(&sequence,&tick));
    bodaqs_node_capture_init();
    for(unsigned i=0;i<10;++i) {raw=8;count=i;cc[3]=i;bodaqs_node_capture_irq();}
    assert(bodaqs_node_capture_sync_loss_take()==3 && bodaqs_node_capture_sync_loss_take()==0);
    assert(!bodaqs_node_capture_fault() && bodaqs_node_capture_clock_trusted());
    bodaqs_node_capture_init();
    for(unsigned i=0;i<243;++i) {raw=8;count=i;cc[3]=i;bodaqs_node_capture_irq();}
    raw=4;count=300;cc[2]=300;bodaqs_node_capture_irq();
    raw=12;count=303;cc[2]=302;cc[3]=301; /* Pending DRDY and stale SYNC. */
    const uint32_t before=bodaqs_node_capture_clock(0,&e);
    bodaqs_node_capture_sync_discard();
    assert(test_last_clear_irq_mask==1 && test_irq_mask==0);
    assert(raw==4 && bodaqs_node_capture_clock(0,&e)==before && e==1);
    assert(!bodaqs_node_capture_sync_observation(&c) && !bodaqs_node_capture_sync_take(&c));
    assert(bodaqs_node_capture_sync_loss_take()==0);
    assert(bodaqs_node_capture_take(&c) && c.tick==300 && c.ordinal==1);
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick==302 && c.ordinal==2);
    raw=8;count=304;cc[3]=304;bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_sync_observation(&c) && c.tick==304 && c.ordinal==244);
    for(unsigned i=0;i<10;++i) {raw=8;count=310+i;cc[3]=count;bodaqs_node_capture_irq();}
    assert(bodaqs_node_capture_sync_loss_take()==3); /* Live losses still counted. */
    bodaqs_node_capture_supervise(100);assert(bodaqs_node_capture_clock_trusted());
    for (unsigned ms=1;ms<=68;++ms) bodaqs_node_capture_supervise_interrupt(ms);
    assert(!bodaqs_node_capture_clock_trusted());
    bodaqs_node_capture_sync_discard();assert(!bodaqs_node_capture_clock_trusted());
    test_irq_mask=1;bodaqs_node_capture_sync_discard();
    assert(test_irq_mask==1 && test_last_clear_irq_mask==1);test_irq_mask=0;

    /* Half a second without foreground service is healthy when ZERO IRQs
     * continue. Inputs independently model a 1 MHz, 16-bit capture timer. */
    for (unsigned systick_first=0;systick_first<2;++systick_first) {
        bodaqs_node_capture_init();
        for (uint32_t ms=1;ms<=500;++ms) {
            const bool rollover=(ms*1000U >> 16) != ((ms-1)*1000U >> 16);
            if (rollover) {raw=1;count=(ms*1000U)&65535U;}
            if (rollover && !systick_first) bodaqs_node_capture_irq();
            bodaqs_node_capture_supervise_interrupt(ms);
            if (rollover && systick_first) bodaqs_node_capture_irq();
        }
        bodaqs_node_capture_supervise(500);
        assert(bodaqs_node_capture_clock_trusted() && !bodaqs_node_capture_fault());
        assert(gNodeCaptureClockInfo.maximum_foreground_gap_ms==500);
        assert(gNodeCaptureClockInfo.rollovers_serviced==7);
        assert(gNodeCaptureClockInfo.supervisor_ticks==500);
        assert(gNodeCaptureClockInfo.maximum_rollover_age_ms>=65);
        assert(gNodeCaptureClockInfo.maximum_rollover_age_ms<=67);
        assert(gNodeCaptureClockInfo.first_fault_reason==BODAQS_CAPTURE_CLOCK_FAULT_NONE);
    }

    /* A pending ZERO can briefly precede its ISR. Reading it must not count
     * as serviced progress, nor may the watchdog consume the interrupt. */
    bodaqs_node_capture_init();
    for (uint32_t ms=1;ms<=67;++ms) {
        if(ms==66) {raw=1;count=464;}
        bodaqs_node_capture_supervise_interrupt(ms);
    }
    assert(raw==1 && bodaqs_node_capture_clock_trusted());
    assert(bodaqs_node_capture_clock(0,&e)==66000 && e==1);
    bodaqs_node_capture_irq();
    bodaqs_node_capture_supervise_interrupt(68);
    assert(bodaqs_node_capture_clock_trusted());

    /* Capture IRQ disabled, but SysTick alive: fail even with no foreground
     * call. Recovery/discard must not erase the first diagnosis or continuity. */
    bodaqs_node_capture_init();
    for (uint32_t ms=1;ms<=68;++ms) {
        if(ms==66) {raw=1;count=464;}
        bodaqs_node_capture_supervise_interrupt(ms);
    }
    assert(!bodaqs_node_capture_clock_trusted() && bodaqs_node_capture_fault());
    assert(gNodeCaptureClockInfo.first_fault_reason==BODAQS_CAPTURE_CLOCK_FAULT_ROLLOVER_TIMEOUT);
    assert(gNodeCaptureClockInfo.first_fault_ms==68);
    assert(gNodeCaptureClockInfo.maximum_rollover_age_ms==68);
    bodaqs_node_capture_irq();
    bodaqs_node_capture_discard();
    bodaqs_node_capture_supervise_interrupt(69);
    assert(!bodaqs_node_capture_clock_trusted());
    assert(gNodeCaptureClockInfo.first_fault_ms==68);

    /* Unsigned uptime rollover retains the deadline semantics. */
    bodaqs_node_capture_init();raw=1;bodaqs_node_capture_irq();
    bodaqs_node_capture_supervise_interrupt(UINT32_MAX-40);
    bodaqs_node_capture_supervise_interrupt(26);
    assert(bodaqs_node_capture_clock_trusted());
    bodaqs_node_capture_supervise_interrupt(27);
    assert(!bodaqs_node_capture_clock_trusted());
    assert(gNodeCaptureClockInfo.first_fault_ms==27);
    return 0;
}
