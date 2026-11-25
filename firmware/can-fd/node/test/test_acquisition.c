#include "bodaqs_control.h"
#include "imu_acquisition.h"
#include "imu_capture.h"
#include "imu_spi.h"
#include "ti_msp_dl_config.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef BODAQS_TEST_NATIVE_PROFILE
#define BODAQS_TEST_NATIVE_PROFILE 1
#endif
#define SAMPLE_PERIOD_US (BODAQS_TEST_NATIVE_PROFILE==1?300U:BODAQS_TEST_NATIVE_PROFILE==2?600U:1200U)
#define TEST_ODR (BODAQS_TEST_NATIVE_PROFILE==1?0x90:BODAQS_TEST_NATIVE_PROFILE==2?0x80:0x70)
struct TestSpi test_spi;
uint32_t raw, count, cc[4];
uint32_t test_irq_mask,test_last_clear_irq_mask;
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
static unsigned fifo_order;
/* First two FIFO slots captured from the failing node, byte-for-byte. */
static const uint8_t captured_timestamp_first[] = {
    0x21,0x0a,0x00,0x00,0x00,0x00,0x99, 0x09,0x1d,0x00,0xff,0xff,0xec,0xff,
    0x11,0x72,0xff,0x4a,0x03,0x94,0xfd, 0x22,0x16,0x00,0x00,0x00,0x00,0x99,
    0x0a,0x15,0x00,0x0c,0x00,0x16,0x00, 0x12,0x74,0xff,0x43,0x03,0x95,0xfd
};
static bool fifo_drained;
static FILE *wire;
static uint32_t next_tx_tick, tx_blocked_until;
static bool seen_boundary, seen_model, seen_anchor, seen_snapshot;
static unsigned snapshot_count;
static uint8_t last_snapshot[64];
static unsigned recovery_began;
static uint32_t reported_evidence_loss;
static unsigned recovery_events, raw_sync_events;
static bool sync_scope_checks;
static uint32_t sync_scope_start;
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
            if(sync_scope_checks) assert(bodaqs_control_get_u32(p+12)>=sync_scope_start);
        }
        if(sync_scope_checks && p[1]==0x23 && (p[59]&32))
            assert(bodaqs_control_get_u32(p+48)>=sync_scope_start);
        if(p[1]==0x25 && p[14]==3 && p[15]==4) reported_loss+=bodaqs_control_get_u32(p+40);
        if(p[1]==0x25 && p[14]==3 && p[15]==4) reported_evidence_loss+=bodaqs_control_get_u32(p+48);
        if(p[1]==0x25 && p[14]==1) ++recovery_began;
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
        if (p[1] == 0x23) {
            seen_snapshot = true;
            ++snapshot_count;memcpy(last_snapshot,p,64);
        }
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
        assert(bodaqs_control_get_u32(p + 36) == 32U*SAMPLE_PERIOD_US);
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
                               fifo_order ? 10U+(slots-1)*12U :
                               0xfffffff0U + t / 25 + (fault_mode == 3 ? 100 : 0));
        fifo[used + 19] = fifo[used + 20] = 0;
        if(fifo_order) {
            uint8_t timestamp[7];memcpy(timestamp,fifo+used+14,7);
            if(fifo_order==1) {
                memmove(fifo+used+7,fifo+used,14);memcpy(fifo+used,timestamp,7);
                if(slots<=2) memcpy(fifo+used,captured_timestamp_first+21*(slots-1),21);
            } else {
                memcpy(fifo+used+14,fifo+used+7,7);memcpy(fifo+used+7,timestamp,7);
            }
        }
        used += 21;
        next_slot += SAMPLE_PERIOD_US;
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
                next_slot = sim_tick + SAMPLE_PERIOD_US;
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
static void completed_recording_turnovers(unsigned recordings) {
    BodaqsAcquisitionEvent e;
        /* Exercise the real register/FIFO/DMA adapter across boot-lifetime
         * capacity. Each successor starts only after stopped proof and an idle
         * hardware transmit fence, without reinitializing acquisition. */
        for (unsigned recording = 1; recording <= recordings; ++recording) {
            memset(&e, 0, sizeof e);
            bodaqs_node_acquisition_backend(0, BODAQS_ACQ_STOP, 3, recording, sim_tick/1000, &e);
            bool done = false;
            uint32_t deadline = sim_tick + 100000;
            while (sim_tick < deadline) {
                advance(sim_tick + 100); bodaqs_node_imu_spi_irq(); memset(&e, 0, sizeof e);
                bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 3, recording, sim_tick/1000, &e);
                assert(e.kind != BODAQS_ACQ_FAILED);
                if (e.kind == BODAQS_ACQ_STOPPED) {done = true; break;}
            }
            assert(done);
            next_tx_tick = sim_tick + 500;
            memset(&e, 0, sizeof e);
            bodaqs_node_acquisition_backend(0, BODAQS_ACQ_FENCE, 4, recording, sim_tick/1000, &e);
            assert(e.kind == BODAQS_ACQ_NO_EVENT);
            advance(sim_tick + 500); memset(&e, 0, sizeof e);
            bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 4, recording, sim_tick/1000, &e);
            assert(e.kind == BODAQS_ACQ_FENCED);
            if (recording == recordings) break;
            used = 0; next_slot = sim_tick + SAMPLE_PERIOD_US;
            seen_boundary = seen_model = seen_anchor = seen_snapshot = false;
            previous_end = 0;
            memset(&e, 0, sizeof e);
            bodaqs_node_acquisition_backend(0, BODAQS_ACQ_PREPARE, 5, recording+1, sim_tick/1000, &e);
            done = false; deadline = sim_tick + 500000;
            while (sim_tick < deadline) {
                advance(sim_tick + 100); bodaqs_node_imu_spi_irq(); memset(&e, 0, sizeof e);
                bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 5, recording+1, sim_tick/1000, &e);
                assert(e.kind != BODAQS_ACQ_FAILED);
                if (e.kind == BODAQS_ACQ_READY) {done = true; break;}
            }
            assert(done);
            memset(&e, 0, sizeof e);
            if(sync_scope_checks) sync_scope_start=sim_tick;
            bodaqs_node_acquisition_backend(0, BODAQS_ACQ_START, 6, recording+1, sim_tick/1000, &e);
            done = false; deadline = sim_tick + 20000;
            while (sim_tick < deadline) {
                advance(sim_tick + 100); bodaqs_node_imu_spi_irq(); memset(&e, 0, sizeof e);
                bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 6, recording+1, sim_tick/1000, &e);
                assert(e.kind != BODAQS_ACQ_FAILED);
                if (e.kind == BODAQS_ACQ_FIRST) {assert(e.boundary[8] == 1); done = true; break;}
            }
            assert(done);
        }
}
static BodaqsAcquisitionEvent stop_observation(uint64_t recording) {
    BodaqsAcquisitionEvent event={0};
    bodaqs_node_acquisition_backend(0,BODAQS_ACQ_STOP,30,recording,sim_tick/1000,&event);
    const uint32_t until=sim_tick+300000;
    while(sim_tick<until) {
        advance(sim_tick+100);bodaqs_node_imu_spi_irq();memset(&event,0,sizeof event);
        bodaqs_node_acquisition_backend(0,BODAQS_ACQ_POLL,30,recording,sim_tick/1000,&event);
        assert(event.kind!=BODAQS_ACQ_FAILED);
        if(event.kind==BODAQS_ACQ_STOPPED) return event;
    }
    assert(false);return event;
}
int main(int argc, char **argv) {
    unsigned selected_fault = argc > 1 ? (unsigned)strtoul(argv[1], 0, 10) : 1;
    sync_scope_checks=selected_fault==16;
    fifo_order=selected_fault==14?1:selected_fault==15?2:0;
    const char *out = getenv("BODAQS_NODE_FIXTURE_OUT");
    if (out) {
        wire = fopen(out, "w");
        assert(wire);
    }
    const uint8_t image[] = {0,    0,    0, 0, 0, 0, 0,    0, 0x6c, (TEST_ODR|4), (TEST_ODR|12),
                             0x44, 0x0c, 0, 0, 0, 0, 0xe2, 0, 0,    0,    0};
    const uint8_t addrs[] = {7,  8,  9,  10, 11, 12, 13, 14, 15, 16,   17,
                             18, 19, 20, 21, 22, 23, 24, 25, 1,  0x5e, 0x5f};
    BodaqsImuDisabled stopped;
    BodaqsAcquisitionEvent e;
    bool ready = false, first = false;
    bodaqs_imu_disabled_init(&stopped, bodaqs_node_imu_register, bodaqs_node_imu_cancel, 0);
    stopped.profile_id=BODAQS_TEST_NATIVE_PROFILE;
    memcpy(stopped.image, image, sizeof(image));
    for (unsigned i = 0; i < sizeof(image); ++i)
        regs[addrs[i]] = image[i];
    bodaqs_node_capture_init();
    bodaqs_node_acquisition_init(17, 0, &stopped, sent, tx_idle);
    memset(&e, 0, sizeof(e));
    bodaqs_node_acquisition_backend(0, BODAQS_ACQ_PREPARE, 1, 1, 0, &e);
    for (uint32_t us = 100; us < 500000; us += 100) {
        advance(us);
        bodaqs_node_imu_spi_irq();
        memset(&e, 0, sizeof(e));
        bodaqs_node_acquisition_backend(0, BODAQS_ACQ_POLL, 1, 1, us / 1000, &e);
        assert(e.kind != BODAQS_ACQ_FAILED);
        if (e.kind == BODAQS_ACQ_READY) {
            assert(us >= 70000U + 270U*SAMPLE_PERIOD_US);
            assert(e.sensor_clock_epoch == 1);
            ready = true;
            break;
        }
    }
    assert(ready && samples == 0);
    uint32_t start = sim_tick;
    if(selected_fault==16) {
        /* Captures accumulated while IDLE/PREPARED must not burst into the
         * next recording or charge its loss ledger (7 retained, 236 lost). */
        uint32_t saved_count=count;
        for(unsigned i=0;i<243;++i) {raw=8;count=100+i;cc[3]=count;bodaqs_node_capture_irq();}
        count=saved_count;raw=0;
    }
    tx_blocked_until = start + 6000;
    if(sync_scope_checks) sync_scope_start=start;
    memset(&e, 0, sizeof(e));
    bodaqs_node_acquisition_backend(0, BODAQS_ACQ_START, 2, 1, sim_tick / 1000, &e);
    /* The sample-unit integration regression needs a nonempty STOP tail, not
     * just the default 65 readings that exactly fill five-reading packets. */
    const uint32_t initial_window = getenv("BODAQS_NODE_FIXTURE_PARTIAL_STOP") ? 19700 : 20000;
    for (uint32_t us = sim_tick + 100; us < start + initial_window; us += 100) {
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
    if(fifo_order || selected_fault==16) {
        completed_recording_turnovers(2);
        puts(selected_fault==16?"START-scoped sync capture: idle backlog discarded, fresh capture retained, turnover passed":"nonfinal timestamp FIFO ordering: PREPARE/START/samples/STOP/FENCE passed");
        return 0;
    }
    if (selected_fault == 13) {
        completed_recording_turnovers(260);
        return 0;
    }
    if(selected_fault==17) {
        fault_mode=6;fifo_drained=false;
        const uint32_t until=sim_tick+100000;
        while(sim_tick<until && !recovery_began) {
            advance(sim_tick+100);bodaqs_node_imu_spi_irq();memset(&e,0,sizeof e);
            bodaqs_node_acquisition_backend(0,BODAQS_ACQ_POLL,2,1,sim_tick/1000,&e);
            assert(e.kind!=BODAQS_ACQ_FAILED);
        }
        assert(recovery_began && !recovery_events);
        const unsigned before=snapshot_count;
        e=stop_observation(1);
        assert(snapshot_count==before+1 && last_snapshot[13]==e.boundary[8]);
        assert(bodaqs_control_get_u32(last_snapshot+20)==bodaqs_control_get_u32(e.boundary));
        assert(bodaqs_control_get_u32(last_snapshot+36)==first_tick+SAMPLE_PERIOD_US*bodaqs_control_get_u32(e.boundary));
        assert(bodaqs_control_get_u32(last_snapshot+32)==0xfffffff0U+bodaqs_control_get_u32(last_snapshot+36)/25);
        puts("STOP during recovery retains the last associated raw pair: PASS");return 0;
    }
    if(selected_fault==18) {
        const unsigned before=snapshot_count;
        tx_blocked_until=sim_tick+1000000;
        const uint32_t until=sim_tick+120000;
        while(sim_tick<until) {
            advance(sim_tick+100);bodaqs_node_imu_spi_irq();memset(&e,0,sizeof e);
            bodaqs_node_acquisition_backend(0,BODAQS_ACQ_POLL,2,1,sim_tick/1000,&e);
            assert(e.kind!=BODAQS_ACQ_FAILED);
        }
        tx_blocked_until=0;
        e=stop_observation(1);
        assert(!e.known_empty && snapshot_count==before && reported_evidence_loss>0);
        puts("STOP snapshot pressure is explicitly accounted without stale pairing: PASS");return 0;
    }
    if(selected_fault==19) {
        completed_recording_turnovers(1);
        used=0;next_slot=sim_tick+SAMPLE_PERIOD_US;
        memset(&e,0,sizeof e);
        bodaqs_node_acquisition_backend(0,BODAQS_ACQ_PREPARE,5,2,sim_tick/1000,&e);
        bool warm_ready=false;const uint32_t until=sim_tick+500000;
        while(sim_tick<until) {
            advance(sim_tick+100);bodaqs_node_imu_spi_irq();memset(&e,0,sizeof e);
            bodaqs_node_acquisition_backend(0,BODAQS_ACQ_POLL,5,2,sim_tick/1000,&e);
            assert(e.kind!=BODAQS_ACQ_FAILED);
            if(e.kind==BODAQS_ACQ_READY) {warm_ready=true;break;}
        }
        assert(warm_ready);const unsigned before=snapshot_count;
        e=stop_observation(2);
        assert(e.known_empty && snapshot_count==before);
        puts("empty successor STOP emits no cached prior-recording observation: PASS");return 0;
    }
    if (selected_fault >= 6) {
        unsigned before_recovery = samples;
        fault_mode = selected_fault>=9?0:6;
        silence_after_overrun=selected_fault==7;
        if(selected_fault==9 || selected_fault==12) tx_blocked_until=sim_tick+(selected_fault==12?50000:110000);
        fifo_drained = false;
        bool recovery_failed=false;
        unsigned failure_reason=0;
        if(selected_fault==11) {
            /* SysTick runs while capture IRQ servicing is deliberately absent. */
            for(unsigned ms=0;ms<=68;++ms)
                bodaqs_node_capture_supervise_interrupt(sim_tick/1000+ms);
        }
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
        if(selected_fault==12) assert(!recovery_failed && detected_loss==0 && reported_loss==0 && !gap_seen && samples>before_recovery);
        if(selected_fault==9) assert(!recovery_failed && detected_loss>0 && reported_loss==detected_loss && gap_seen);
        if(selected_fault==10) {
            assert(recovery_failed && failure_reason==31 && recovery_events==254);
            fault_mode=0;
            completed_recording_turnovers(2);
        }
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
    assert(stopped_ok && regs[10] == 0 && regs[25] == 0 && regs[16] == (TEST_ODR|4) && regs[17] == (TEST_ODR|12));
    assert(snapshot_count>=2);
    assert(bodaqs_control_get_u32(last_snapshot+20)==bodaqs_control_get_u32(e.boundary));
    assert(bodaqs_control_get_u32(last_snapshot+36)==bodaqs_control_get_u32(e.boundary+4));
    assert(bodaqs_control_get_u32(last_snapshot+32)==0xfffffff0U+bodaqs_control_get_u32(e.boundary+4)/25U);
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
    for (uint32_t us = warm + 100; us < warm + 500000; us += 100) {
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
