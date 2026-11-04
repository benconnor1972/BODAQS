#include "bodaqs_control.h"
#include "imu_acquisition.h"
#include "imu_capture.h"
#include "imu_spi.h"
#include "ti_msp_dl_config.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct TestSpi test_spi;
uint32_t raw, count, cc[4];
static uintptr_t src[2], dst[2];
static uint32_t sizes[2];
static bool enabled[2], cs, busy, irq;
static unsigned arm_order;
static uint8_t regs[256], pio[2], pcount, pindex, command;
static uint8_t fifo[4096];
static unsigned used;
static uint32_t sim_tick, next_slot, slots, frames, samples, first_tick;
static uint8_t saved_sample[64];
static unsigned fault_mode;
static bool fifo_drained;
static FILE *wire;
static uint32_t next_tx_tick, tx_blocked_until;
static bool seen_boundary, seen_model, seen_anchor, seen_snapshot;
static unsigned recovery_events, raw_sync_events;
static uint32_t reported_loss, previous_end;
static unsigned detected_loss;
static bool gap_seen, silence_after_overrun;
static bool tx_idle(void) { return sim_tick >= next_tx_tick; }
static bool sent(uint16_t id, const uint8_t *p, size_t n) {
    if (sim_tick < next_tx_tick || sim_tick < tx_blocked_until)
        return false;
    next_tx_tick = sim_tick + 400;
    if (id == 0x90) {
        if(p[1]==0x21) {
            assert(n==24 && bodaqs_control_get_u32(p+8)==0 && p[20]==0 && p[21]==0);
            assert(bodaqs_control_get_u32(p+12)>0 && bodaqs_control_get_u32(p+16)==17);
            ++raw_sync_events;
        }
        if(p[1]==0x25 && p[14]==3 && p[15]==4) reported_loss+=bodaqs_control_get_u32(p+40);
        if (p[1] == 0x25 && p[14] == 5) {
            assert(p[13] > 1 && !(p[54] & 0x1c)); /* unknown loss counts */
            assert(bodaqs_control_get_u32(p + 20) == 1); /* sensor clock retained */
            ++recovery_events;
        }
        if (p[1] == 0x25 && p[14] == 2)
            seen_boundary = true;
        if (p[1] == 0x24)
            seen_model = true;
        if (p[1] == 0x22)
            seen_anchor = true;
        if (p[1] == 0x23)
            seen_snapshot = true;
    }
    if (id == 0x100)
        assert(seen_boundary && seen_model && seen_anchor && seen_snapshot);
    if (wire) {
        fprintf(wire, "%u %u ", id, (unsigned)n);
        for (unsigned i = 0; i < n; ++i)
            fprintf(wire, "%02x", p[i]);
        fprintf(wire, "\n");
    }
    ++frames;
    if (id == 0x90 && p[1] == 0x24) {
        assert((p[14] & 2) == 0);
        assert(bodaqs_control_get_u32(p + 36) == 9600);
        assert(p[40] == 32 && p[41] == 0);
    }
    if (id == 0x100) {
        assert(p[2] == 1 || recovery_events);
        samples += p[3] & 7;
        uint32_t first=bodaqs_control_get_u32(p)&65535;
        if(!recovery_events) {detected_loss+=first-previous_end;previous_end=first+(p[3]&7);}
        if(p[3]&16) gap_seen=true;
        memcpy(saved_sample, p, 64);
    }
    return true;
}
static void complete(void) {
    uint8_t *tx = (uint8_t *)src[0], *rx = (uint8_t *)dst[1];
    unsigned bytes = sizes[1] - 1;
    rx[0] = 0xee;
    if (tx[0] == 0xba) {
        rx[1] = (uint8_t)(used / 7);
        rx[2] = (uint8_t)((used / 7) >> 8);
        if ((fault_mode == 4 || fault_mode == 6) && fifo_drained) {
            rx[2] |= 0x40;
            if (fault_mode == 6) fault_mode = 7;
        }
    } else if (tx[0] == 0xc0) {
        bodaqs_control_put_u32(rx + 1, fault_mode >= 6 ? 0xfffffff0U + sim_tick / 25 : 0);
    } else {
        assert(tx[0] == 0xf8 && bytes <= used);
        memcpy(rx + 1, fifo, bytes);
        memmove(fifo, fifo + bytes, used - bytes);
        used -= bytes;
        fifo_drained = true;
    }
    sizes[1] = 0;
    irq = true;
}
static void advance(uint32_t target) {
    while (next_slot <= target && regs[10] == 0x46 && !(silence_after_overrun && fault_mode==7)) {
        uint32_t t = next_slot;
        uint8_t c = (uint8_t)((slots++ & 3) << 1);
        if ((t >> 16) != (sim_tick >> 16))
            raw |= 1;
        count = t & 65535;
        cc[2] = count;
        if (fault_mode != 5)
            raw |= 4;
        bodaqs_node_capture_irq();
        sim_tick = t;
        const uint8_t axes[] = {0x00, 0x80, 0xff, 0x7f, 0xff, 0xff};
        assert(used + 21 <= sizeof(fifo));
        fifo[used] = 0x08 | c;
        memcpy(fifo + used + 1, axes, 6);
        fifo[used + 7] = 0x10 | c;
        memcpy(fifo + used + 8, axes, 6);
        if (fault_mode == 1)
            fifo[used + 7] = 0x08 | c;
        if (fault_mode == 2)
            fifo[used + 7] = 0x38 | c;
        fifo[used + 14] = 0x20 | c;
        bodaqs_control_put_u32(fifo + used + 15,
                               0xfffffff0U + t / 25 + (fault_mode == 3 ? 100 : 0));
        fifo[used + 19] = fifo[used + 20] = 0;
        used += 21;
        next_slot += 300;
    }
    if ((target >> 16) != (sim_tick >> 16)) {
        raw |= 1;
        count = target & 65535;
        bodaqs_node_capture_irq();
    }
    count = target & 65535;
    sim_tick = target;
}

static uintptr_t address(uint32_t low) {
    return ((uintptr_t)&test_spi & ~(uintptr_t)UINT32_MAX) | low;
}
void DL_GPIO_setPins(int p, int m) {
    (void)p;
    (void)m;
    cs = false;
}
void DL_GPIO_clearPins(int p, int m) {
    (void)p;
    (void)m;
    cs = true;
    pcount = pindex = 0;
}
void DL_DMA_disableChannel(int d, int c) {
    (void)d;
    enabled[c] = false;
}
void DL_DMA_enableChannel(int d, int c) {
    (void)d;
    assert(cs);
    enabled[c] = true;
    arm_order = 10 * arm_order + (unsigned)c + 1;
    if (c == 0)
        complete();
}
void DL_DMA_setSrcAddr(int d, int c, uint32_t v) {
    (void)d;
    src[c] = address(v);
}
void DL_DMA_setDestAddr(int d, int c, uint32_t v) {
    (void)d;
    dst[c] = address(v);
}
void DL_DMA_setTransferSize(int d, int c, uint32_t n) {
    (void)d;
    sizes[c] = n;
}
uint16_t DL_DMA_getTransferSize(int d, int c) {
    (void)d;
    return (uint16_t)sizes[c];
}
void DL_SPI_clearInterruptStatus(struct TestSpi *s, uint32_t m) {
    (void)s;
    (void)m;
    irq = false;
}
uint32_t DL_SPI_getPendingInterrupt(struct TestSpi *s) {
    (void)s;
    bool v = irq;
    irq = false;
    return v ? 1 : 0;
}
bool DL_SPI_receiveDataCheck8(struct TestSpi *s, uint8_t *p) {
    (void)s;
    if (pindex == pcount)
        return false;
    *p = pio[pindex++];
    return true;
}
bool DL_SPI_transmitDataCheck8(struct TestSpi *s, uint8_t b) {
    (void)s;
    if (!pcount) {
        command = b;
        pio[pcount++] = 0;
    } else {
        uint8_t addr = command & 0x7f;
        if (command & 0x80)
            pio[pcount++] = regs[addr];
        else {
            regs[addr] = b;
            pio[pcount++] = 0;
            if (addr == 10 && b == 0)
                used = 0;
            if (addr == 10 && b == 0x46)
                next_slot = sim_tick + 300;
        }
    }
    return true;
}
bool DL_SPI_isBusy(struct TestSpi *s) {
    (void)s;
    return busy;
}
void DL_SPI_reset(struct TestSpi *s) { (void)s; }
void DL_SPI_enablePower(struct TestSpi *s) { (void)s; }
void SYSCFG_DL_IMU_SPI_init(void) {}
void NVIC_ClearPendingIRQ(int n) { (void)n; }
int main(int argc, char **argv) {
    unsigned selected_fault = argc > 1 ? (unsigned)strtoul(argv[1], 0, 10) : 1;
    const char *out = getenv("BODAQS_NODE_FIXTURE_OUT");
    if (out) {
        wire = fopen(out, "w");
        assert(wire);
    }
    const uint8_t image[] = {0,    0,    0, 0, 0, 0, 0,    0, 0x6c, 0x94, 0x9c,
                             0x44, 0x0c, 0, 0, 0, 0, 0xe2, 0, 0,    0,    0};
    const uint8_t addrs[] = {7,  8,  9,  10, 11, 12, 13, 14, 15, 16,   17,
                             18, 19, 20, 21, 22, 23, 24, 25, 1,  0x5e, 0x5f};
    BodaqsImuDisabled stopped;
    BodaqsAcquisitionEvent e;
    bool ready = false, first = false;
    bodaqs_imu_disabled_init(&stopped, bodaqs_node_imu_register, bodaqs_node_imu_cancel, 0);
    memcpy(stopped.image, image, sizeof(image));
    for (unsigned i = 0; i < sizeof(image); ++i)
        regs[addrs[i]] = image[i];
    bodaqs_node_capture_init();
    bodaqs_node_acquisition_init(17, 0, &stopped, sent, tx_idle);
    memset(&e, 0, sizeof(e));
    bodaqs_node_acquisition_backend(0, BODAQS_ACQ_PREPARE, 1, 1, 0, &e);
    for (uint32_t us = 100; us < 200000; us += 100) {
        advance(us);
        bodaqs_node_imu_spi_irq();
        memset(&e, 0, sizeof(e));
        bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 1, 1, us / 1000, &e);
        assert(e.kind != BODAQS_ACQ_FAILED);
        if (e.kind == BODAQS_ACQ_READY) {
            assert(us >= 151000);
            assert(e.sensor_clock_epoch == 1);
            ready = true;
            break;
        }
    }
    assert(ready && samples == 0);
    uint32_t start = sim_tick;
    tx_blocked_until = start + 6000;
    memset(&e, 0, sizeof(e));
    bodaqs_node_acquisition_backend(0, BODAQS_ACQ_START, 2, 1, sim_tick / 1000, &e);
    for (uint32_t us = sim_tick + 100; us < start + 20000; us += 100) {
        advance(us);
        if(us==start+5000) {raw=8;cc[3]=count;bodaqs_node_capture_irq();}
        bodaqs_node_imu_spi_irq();
        memset(&e, 0, sizeof(e));
        bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 2, 1, us / 1000, &e);
        assert(e.kind != BODAQS_ACQ_FAILED);
        if (e.kind == BODAQS_ACQ_FIRST) {
            assert(!first);
            first = true;
            first_tick = bodaqs_control_get_u32(e.boundary + 4);
            assert(first_tick > start && bodaqs_control_get_u32(e.boundary) == 0);
        }
    }
    assert(raw_sync_events==1);
    assert(first && samples >= 5 && saved_sample[4] == 0 && saved_sample[5] == 0x80 && frames > 4);
    if (selected_fault >= 6) {
        unsigned before_recovery = samples;
        fault_mode = selected_fault>=9?0:6;
        silence_after_overrun=selected_fault==7;
        if(selected_fault==9) tx_blocked_until=sim_tick+60000;
        fifo_drained = false;
        bool recovery_failed=false;
        unsigned failure_reason=0;
        if(selected_fault==11) bodaqs_node_capture_supervise(sim_tick/1000+65);
        uint32_t next_fault=sim_tick+1000;
        for (uint32_t us = sim_tick + 100; us < start + (selected_fault==10?90000000:250000); us += 100) {
            if(selected_fault==10 && us>=next_fault) {fault_mode=6;fifo_drained=false;next_fault+=350000;}
            advance(us);
            bodaqs_node_imu_spi_irq();
            memset(&e, 0, sizeof(e));
            bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 2, 1, us / 1000, &e);
            if(e.kind==BODAQS_ACQ_FAILED) {recovery_failed=true;failure_reason=e.reason;break;}
            if(selected_fault==8 && recovery_events && fault_mode==7) {fault_mode=6;fifo_drained=false;}
        }
        if(selected_fault==6) assert(!recovery_failed && recovery_events == 1 && samples > before_recovery);
        if(selected_fault==7 || selected_fault==8) assert(recovery_failed && failure_reason==32);
        if(selected_fault==9) assert(!recovery_failed && detected_loss>0 && reported_loss==detected_loss && gap_seen);
        if(selected_fault==10) assert(recovery_failed && failure_reason==31 && recovery_events==254);
        if(selected_fault==11) {
            assert(recovery_failed && failure_reason==35);
            memset(&e,0,sizeof e);
            bodaqs_node_acquisition_backend(0,BODAQS_ACQ_PREPARE,3,2,sim_tick/1000,&e);
            assert(e.kind==BODAQS_ACQ_FAILED && e.reason==35); // discard cannot repair a missed clock wrap
        }
        return 0;
    }
    memset(&e, 0, sizeof(e));
    bodaqs_node_acquisition_backend(0, BODAQS_ACQ_STOP, 3, 1, sim_tick / 1000, &e);
    bool stopped_ok = false;
    for (uint32_t us = sim_tick + 100; us < start + 100000; us += 100) {
        advance(us);
        bodaqs_node_imu_spi_irq();
        memset(&e, 0, sizeof(e));
        bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 3, 1, us / 1000, &e);
        assert(e.kind != BODAQS_ACQ_FAILED);
        if (e.kind == BODAQS_ACQ_STOPPED) {
            assert(e.register_proof_current);
            stopped_ok = true;
            break;
        }
    }
    assert(stopped_ok && regs[10] == 0 && regs[25] == 0 && regs[16] == 0x94 && regs[17] == 0x9c);
    /* FENCE is not complete while an already accepted hardware TX is pending. */
    next_tx_tick = sim_tick + 500;
    memset(&e, 0, sizeof(e));
    bodaqs_node_acquisition_backend(0, BODAQS_ACQ_FENCE, 4, 1, sim_tick / 1000, &e);
    assert(e.kind == BODAQS_ACQ_NO_EVENT);
    advance(sim_tick + 500);
    memset(&e, 0, sizeof(e));
    bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 4, 1, sim_tick / 1000, &e);
    assert(e.kind == BODAQS_ACQ_FENCED);
    /* Every warm preparation must repeat the full conservative observation
     * window. */
    uint32_t warm = sim_tick;
    ready = false;
    memset(&e, 0, sizeof(e));
    bodaqs_node_acquisition_backend(0, BODAQS_ACQ_PREPARE, 5, 2, warm / 1000, &e);
    for (uint32_t us = warm + 100; us < warm + 200000; us += 100) {
        advance(us);
        bodaqs_node_imu_spi_irq();
        memset(&e, 0, sizeof(e));
        bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 5, 2, us / 1000, &e);
        assert(e.kind != BODAQS_ACQ_FAILED);
        if (e.kind == BODAQS_ACQ_READY) {
            assert(us - warm >= 151000);
            assert(e.sensor_clock_epoch == 2);
            ready = true;
            break;
        }
    }
    assert(ready);
    /* Corrupt an actual FIFO engine word before DMA receives it: no ambiguous
     * six-axis sample, no fabricated loss count, and a terminal failure event. */
    unsigned before = samples;
    fault_mode = selected_fault;
    fifo_drained = false;
    bool failed = false;
    memset(&e, 0, sizeof(e));
    bodaqs_node_acquisition_backend(0, BODAQS_ACQ_START, 6, 2, sim_tick / 1000, &e);
    uint32_t fault_start = sim_tick;
    for (uint32_t us = fault_start + 100; us < fault_start + 20000; us += 100) {
        advance(us);
        bodaqs_node_imu_spi_irq();
        memset(&e, 0, sizeof(e));
        bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 6, 2, us / 1000, &e);
        if (e.kind == BODAQS_ACQ_FAILED) {
            failed = true;
            break;
        }
    }
    assert(failed && samples == before);
    if (wire)
        fclose(wire);
    return 0;
}
