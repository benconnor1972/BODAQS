#include "imu_acquisition.h"
#include "bodaqs_control.h"
#include "imu_capture.h"
#include "imu_spi.h"
#include <string.h>
/* One main-loop owner: runtime writes never overlap profile apply or DMA.
 * Unknown alignment/uncertainty is explicitly retained on the wire. */
enum { IDLE, CONFIG, VERIFY, SETTLE, DISCARD, READY, STARTING, RECORDING, STOPPING, FAILED, RECOVER };
typedef struct {
    uint32_t sequence,tick,sensor,sensor_epoch,capture,slot,model;
    uint32_t sync_sequence,sync_tick;
    uint8_t tags[3],epoch;
    bool sync_associated,sync_present;
} SampleObservation;
static struct {
    BodaqsImuDisabled *stopped;
    BodaqsNodeCanSend send;
    bool (*transmit_idle)(void);
    bool fencing, failure_after_first, epoch_reusable;
    uint64_t recording;
    uint32_t boot, generation, prepared, last_poll, sequence, slot, gyro, accel, sensor_epoch;
    uint32_t settle_tick, first_record_tick, reset_tick, ticks[33];
    uint32_t start_tick, last_tick, last_sensor, model_seq;
    uint32_t numerator, model_id, evidence, model_ms, last_capture;
    uint8_t address, phase, index, step, value, epoch, mask, counter, last_counter, drain_phase;
    uint8_t pending_words[672];
    uint8_t image[24], tags[3], axes[12], packet[64], count, pending_event, reason;
    uint16_t words, denominator, pending_count;
    bool have_previous, recorded, ready_event;
    BodaqsNodeCapture capture, sync;
    bool sync_present, seed_started;
    uint8_t seed_attempts;
    uint8_t recovery_step, recovery_count, recovery_stage;
    uint32_t recovery_ms, recovery_tick, attempts[3], resync_timestamp;
    uint32_t loss_count, loss_evidence, loss_first, loss_last, loss_ms, model_tick, model_anchor_tick, model_numerator, sent_sync;
    uint16_t model_denominator;
    uint32_t recovery_capture;
    bool gap, recovered, evidence_gap;
    uint32_t slot_timestamp;
    SampleObservation final_sample;
} a;
/* FIFO drains decode up to 32 slots in one turn. Keep CAN backpressure out of
 * that deadline: immutable frames retain evidence/data order until hardware
 * accepts them. Exhaustion excludes rather than dropping interpretation data. */
static struct {
    uint16_t id;
    uint8_t length, bytes[64];
} tx_frames[64];
static uint8_t tx_head, tx_tail, tx_depth;
static bool queue_frame(uint16_t id, const uint8_t *p, size_t n) {
    if (tx_depth == 64 || n > 64)
        return false;
    tx_frames[tx_head].id = id;
    tx_frames[tx_head].length = (uint8_t)n;
    memcpy(tx_frames[tx_head].bytes, p, n);
    tx_head = (uint8_t)((tx_head + 1) % 64);
    ++tx_depth;
    return true;
}
static void service_transmit(void) {
    if (tx_depth &&
        a.send(tx_frames[tx_tail].id, tx_frames[tx_tail].bytes, tx_frames[tx_tail].length)) {
        tx_tail = (uint8_t)((tx_tail + 1) % 64);
        --tx_depth;
    }
}
static const uint8_t proof_addresses[] = {7,  8,  9,  10, 11, 12, 13, 14, 15, 16,   17,
                                          18, 19, 20, 21, 22, 23, 24, 25, 1,  0x5e, 0x5f};
static const uint8_t proof_masks[] = {255,  0xd7, 255,  0xf7, 0xe7, 255,  255, 0x7f,
                                      255,  0xfe, 0xfe, 0xfd, 0x6e, 0xef, 255, 0xf2,
                                      0xfd, 0xfe, 0x20, 0xc0, 255,  255};
static const uint8_t addresses[] = {10, 7, 8, 9, 11, 13, 14, 25, 0x42, 10};
static const uint8_t image_index[] = {3, 0, 1, 2, 4, 6, 7, 18, 0, 3};
static const uint8_t masks[] = {0xf7, 255, 0xd7, 255, 0xe7, 255, 0x7f, 0x20, 255, 0xf7};
static const uint8_t values[] = {0, 96, 0, 0x99, 0x80, 1, 8, 0x20, 0xaa, 0x46};
static void put16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}
static uint32_t clock_tick(void) {
    uint32_t e;
    return bodaqs_node_capture_clock(0, &e);
}
static void envelope(uint8_t *p, uint8_t type, uint8_t n) {
    memset(p, 0, 64);
    p[0] = 1;
    p[1] = type;
    p[2] = 1;
    p[6] = n;
}
static bool emit(uint8_t type, uint8_t *p, size_t n) {
    (void)type;
    if (a.evidence == UINT32_MAX || !queue_frame((uint16_t)(0x90 + a.address), p, n)) {
        a.reason = 31;
        return false;
    }
    return true;
}
static bool evidence_available(void) {
    if(a.evidence>=UINT32_MAX-1) {a.reason=31;return false;}
    return true;
}
static bool boundary(uint8_t kind, uint16_t reason, uint32_t tick) {
    uint8_t p[64], *b = p + 8;
    if(!evidence_available()) return false;
    envelope(p, 0x25, 56);
    bodaqs_control_put_u32(b, a.boot);
    b[5] = a.epoch;
    b[6] = kind;
    b[7] = 2;
    bodaqs_control_put_u32(b + 8, ++a.evidence);
    bodaqs_control_put_u32(b + 12, a.sensor_epoch);
    bodaqs_control_put_u32(b + 16, 1);
    bodaqs_control_put_u32(b + 20, a.sequence ? a.sequence - 1 : 0);
    put16(b + 44, reason);
    put16(b + 46, kind == 7 ? 0xe0U
                            : (uint16_t)(0x60U | (kind == 2    ? 0x101U
                                                  : a.recorded ? 0x201U
                                                               : 0x400U)));
    bodaqs_control_put_u32(b + 52, tick);
    return emit(0x25, p, 64);
}
static void fail(uint8_t reason) {
    a.reason = reason;
    a.phase = FAILED;
    a.ready_event = false;
    if (a.pending_event == BODAQS_ACQ_FIRST)
        a.failure_after_first = true;
    else
        a.pending_event = BODAQS_ACQ_FAILED;
    bodaqs_node_imu_cancel(0);
}
static bool snapshot_observation(uint32_t seq, uint32_t tick, uint32_t ts,const SampleObservation *sample) {
    uint8_t p[64], *b = p + 8;
    if(!evidence_available()) return false;
    uint32_t sync_sequence=0,sync_tick=0;
    if(seq && tx_depth>=56) {
        if(a.loss_evidence==UINT32_MAX || a.evidence==UINT32_MAX) return false;
        ++a.loss_evidence; ++a.evidence; a.evidence_gap=true;
        return true;
    }
    const bool sync_associated=sample?sample->sync_associated:bodaqs_node_sync_latest(&sync_sequence,&sync_tick);
    if(sample) {sync_sequence=sample->sync_sequence;sync_tick=sample->sync_tick;}
    envelope(p, 0x23, 56);
    bodaqs_control_put_u32(b, a.boot);
    b[5] = sample?sample->epoch:a.epoch;
    put16(b + 6, (uint16_t)(0x37 | (sync_associated?8:0) | (a.evidence_gap?64:0)));
    bodaqs_control_put_u32(b + 8, ++a.evidence);
    bodaqs_control_put_u32(b + 12, seq);
    bodaqs_control_put_u32(b + 16, sample?sample->sensor_epoch:a.sensor_epoch);
    bodaqs_control_put_u32(b + 20, 1);
    bodaqs_control_put_u32(b + 24, ts);
    bodaqs_control_put_u32(b + 28, tick);
    bodaqs_control_put_u32(b + 32, sample?sample->capture:a.capture.ordinal);
    bodaqs_control_put_u32(b + 44, sample?sample->model:a.model_id);
    memcpy(b + 48, sample?sample->tags:a.tags, 3);
    const bool sync_present=sample?sample->sync_present:a.sync_present;
    b[51] = (uint8_t)(0xdf | (sync_present ? 0x20 : 0));
    if (sync_present) {
        bodaqs_control_put_u32(b + 36, sync_sequence);
        bodaqs_control_put_u32(b + 40, sample?sample->sync_tick:a.sync.tick);
    }
    bodaqs_control_put_u32(b + 52, sample?sample->slot:a.slot);
    a.evidence_gap=false;
    return emit(0x23, p, 64);
}
static bool snapshot(uint32_t seq,uint32_t tick,uint32_t ts) {
    return snapshot_observation(seq,tick,ts,NULL);
}
static bool model(uint32_t seq, uint32_t tick, uint32_t now) {
    uint8_t p[64], *b = p + 8;
    if (a.model_id == UINT32_MAX) {
        a.reason=31;
        return false;
    }
    ++a.model_id;
    a.model_seq = seq;
    a.model_ms = now;
    a.model_tick = a.model_anchor_tick = tick;
    a.model_numerator=a.numerator; a.model_denominator=a.denominator;
    envelope(p, 0x24, 56);
    bodaqs_control_put_u32(b, a.boot);
    b[5] = a.epoch;
    put16(b + 6, (uint16_t)(5 | (a.recovered ? 24 : 0))); /* finite uncertainty unknown */
    bodaqs_control_put_u32(b + 8, a.model_id);
    bodaqs_control_put_u32(b + 12, 1);
    bodaqs_control_put_u32(b + 16, a.sensor_epoch);
    bodaqs_control_put_u32(b + 20, seq);
    bodaqs_control_put_u32(b + 24, tick);
    bodaqs_control_put_u32(b + 28, a.numerator);
    put16(b + 32, a.denominator);
    b[34] = 1;
    bodaqs_control_put_u32(b + 36, 500);
    bodaqs_control_put_u32(b + 44, 150000);
    bodaqs_control_put_u32(b + 48, a.last_capture - 32);
    bodaqs_control_put_u32(b + 52, a.last_capture);
    if (!emit(0x24, p, 64))
        return false;
    envelope(p, 0x22, 20);
    b[1] = 1;
    b[2] = a.epoch;
    b[3] = 0x40;
    bodaqs_control_put_u32(b + 4, seq);
    bodaqs_control_put_u32(b + 8, tick);
    bodaqs_control_put_u32(b + 12, a.numerator);
    put16(b + 16, a.denominator);
    return emit(0x22, p, 32);
}
static bool flush(void) {
    if (!a.count)
        return true;
    /* Bit 7 is reserved, including on a partial STOP packet. The separate
     * source boundary carries the terminal sequence; samples need no STOP flag. */
    a.packet[3] = (uint8_t)(a.count | 0x40 | (a.sequence == a.count ? 8 : 0) | (a.gap ? 16 : 0));
    size_t n = 4 + 12 * a.count;
    if (n <= 16)
        n = 16;
    else if (n <= 32)
        n = 32;
    else if (n <= 48)
        n = 48;
    else
        n = 64;
    /* Keep eight slots unavailable to data so an already full CAN lane cannot
     * destroy essential recovery definitions. Sequence is assigned upstream. */
    if (tx_depth >= 56) {
        if (UINT32_MAX - a.loss_count < a.count)
            return false;
        if (!a.loss_count) a.loss_first = a.sequence - a.count;
        a.loss_last = a.sequence - 1;
        a.loss_count += a.count;
        a.gap = true;
    } else {
        if (!queue_frame((uint16_t)(0x100 + (a.address << 3)), a.packet, n))
            return false;
        a.gap = false;
    }
    memset(a.packet, 0, 64);
    a.count = 0;
    return true;
}
static bool loss_report(uint32_t now, bool anchor) {
    uint8_t p[64], *b=p+8;
    if ((!a.loss_count && !a.loss_evidence) || (uint32_t)(now-a.loss_ms)<100) return true;
    if(!evidence_available()) return false;
    if (tx_depth>(anchor?62:63)) return false;
    envelope(p,0x25,56);
    bodaqs_control_put_u32(b,a.boot); b[5]=a.epoch; b[6]=3; b[7]=4;
    bodaqs_control_put_u32(b+8,++a.evidence);
    bodaqs_control_put_u32(b+12,a.sensor_epoch); bodaqs_control_put_u32(b+16,1);
    if(a.loss_count) {bodaqs_control_put_u32(b+24,a.loss_first); bodaqs_control_put_u32(b+28,a.loss_last);}
    bodaqs_control_put_u32(b+32,a.loss_count); bodaqs_control_put_u32(b+40,a.loss_evidence);
    put16(b+46,(uint16_t)(0x20 | (a.loss_count?6:0) | (a.loss_evidence?8:0)));
    if (!emit(0x25,p,64)) return false;
    if(anchor) {
        envelope(p,0x22,20); b[1]=1; b[2]=a.epoch; b[3]=0x40;
        bodaqs_control_put_u32(b+4,a.model_seq); bodaqs_control_put_u32(b+8,a.model_anchor_tick);
        bodaqs_control_put_u32(b+12,a.model_numerator); put16(b+16,a.model_denominator);
        if (!emit(0x22,p,32)) return false;
    }
    a.loss_ms=now; a.loss_count=a.loss_evidence=0;
    return true;
}
static bool recovery_boundary(uint8_t kind,uint32_t now) {
    uint8_t p[64],*b=p+8;
    (void)now;
    if(!evidence_available()) return false;
    envelope(p,0x25,56); bodaqs_control_put_u32(b,a.boot);
    b[5]=a.epoch; b[6]=kind; b[7]=a.recovery_stage;
    bodaqs_control_put_u32(b+8,++a.evidence);
    bodaqs_control_put_u32(b+12,a.sensor_epoch); bodaqs_control_put_u32(b+16,1);
    if (a.sequence) bodaqs_control_put_u32(b+20,a.sequence-1);
    put16(b+44,27); put16(b+46,(uint16_t)(0x60 | (a.sequence || kind==2 || kind==5?1:0) | (kind==2?256:0)));
    if(kind==4 && a.recovery_capture) {
        bodaqs_control_put_u32(b+36,a.recovery_capture);
        put16(b+46,(uint16_t)(0x70 | (a.sequence?1:0)));
    }
    bodaqs_control_put_u32(b+48,clock_tick()-a.recovery_tick);
    bodaqs_control_put_u32(b+52,clock_tick());
    return emit(0x25,p,64);
}
static void recover(uint8_t stage,uint32_t now) {
    if (a.phase!=RECORDING && a.phase!=RECOVER) {fail(27);return;}
    /* A retry counts as another attempt; the original deadline never moves. */
    unsigned active=0;
    for(unsigned i=0;i<a.recovery_count;++i)
        if((uint32_t)(now-a.attempts[i])<1000) a.attempts[active++]=a.attempts[i];
    a.recovery_count=(uint8_t)active;
    if(active==3 || (a.phase==RECOVER && (uint32_t)(now-a.recovery_ms)>=100)) {fail(32);return;}
    if(tx_depth>55 || a.epoch==255 || a.evidence>UINT32_MAX-8 || a.model_id==UINT32_MAX) {fail(31);return;}
    a.attempts[a.recovery_count++]=now;
    if(a.phase!=RECOVER) {
        a.recovery_ms=now; a.recovery_tick=clock_tick(); a.recovery_stage=stage;
        a.recovery_capture=bodaqs_node_capture_loss_take();
        if(!flush() || !recovery_boundary(1,now) || !recovery_boundary(4,now)) {fail(31);return;}
    }
    a.phase=RECOVER; a.recovery_step=0; a.step=0;
    a.mask=a.count=a.drain_phase=0; a.pending_count=0;
    a.have_previous=false; a.slot=0;
    bodaqs_node_imu_cancel(0);
    bodaqs_node_capture_discard();
}
/* Called only with complete FIFO data, preserving partial triples over bursts.
 */
static bool word(const uint8_t *w, uint32_t now) {
    uint8_t sensor = w[0] >> 3, counter = (w[0] >> 1) & 3, bit;
    if (sensor != 1 && sensor != 2 && sensor != 4)
        return false;
    bit = sensor == 1 ? 2 : sensor == 2 ? 1 : 4;
    if (!a.mask) {
        a.counter = counter;
    }
    if (counter != a.counter || (a.mask & bit))
        return false;
    a.mask |= bit;
    a.tags[sensor == 2 ? 0 : sensor == 1 ? 1 : 2] = w[0];
    if (sensor == 1) {
        memcpy(a.axes + 6, w + 1, 6);
    }
    if (sensor == 2) {
        memcpy(a.axes, w + 1, 6);
    }
    if (sensor == 4) {
        a.slot_timestamp = bodaqs_control_get_u32(w + 1);
    }
    if (a.mask != 7)
        return true;
    /* Tags and TAG_CNT identify a complete slot; timestamp need not be last.
     * Retain its value until both axis words from that same counter arrive. */
    uint32_t ts = a.slot_timestamp;
    if (!bodaqs_node_capture_take(&a.capture))
        return false;
    uint32_t tick = a.capture.tick;
    if (a.have_previous) {
        uint32_t dt = tick - a.last_tick, ds = ts - a.last_sensor;
        const uint32_t scale=a.stopped->profile_id==1?1U:a.stopped->profile_id==2?2U:4U;
        if (counter != ((a.last_counter + 1) & 3) || dt < 250U*scale || dt > 350U*scale || ds < 9U*scale || ds > 15U*scale ||
            a.capture.ordinal != a.last_capture + 1)
            return false;
    }
    if (a.phase == RECOVER && !a.have_previous && (uint32_t)(ts-a.resync_timestamp)>4000)
        return false;
    a.last_counter = counter;
    a.last_tick = tick;
    a.last_sensor = ts;
    a.last_capture = a.capture.ordinal;
    a.have_previous = true;
    a.mask = 0;
    ++a.slot;
    a.ticks[(a.slot - 1) % 33] = tick;
    if (a.slot >= 33) {
        a.numerator = tick - a.ticks[(a.slot - 33) % 33];
        a.denominator = 32;
    }
    if (a.phase == RECOVER && a.recovery_step == 4 && a.slot >= 33) {
        /* Retain prior-epoch exact software loss through the normal coalescing
         * interval. The recovery's matching anchor replaces the extra loss
         * anchor, keeping this whole attempt within eight essential frames. */
        if((a.loss_count || a.loss_evidence) && (uint32_t)(now-a.loss_ms)<100) return true;
        if(!loss_report(now,false)) return false;
        ++a.epoch;
        a.sequence=0;
        a.recovered=true;
        a.gap=false;
        if (!recovery_boundary(2,now) || !recovery_boundary(5,now) ||
            !model(0,tick,now) || !snapshot(0,tick,ts)) return false;
        a.phase=RECORDING;
    }
    if (a.phase == DISCARD && (int32_t)(tick - a.settle_tick) >= 0) {
        ++a.gyro;
        ++a.accel;
    }
    /* Keep the established discard count at lower ODRs. Extra startup time
     * is outside the throughput window and does not relax settling assumptions. */
    if (a.phase == DISCARD && a.gyro >= 270 && a.accel >= 10 && a.slot >= 33) {
        a.phase = READY;
        a.ready_event = true;
    }
    if (a.phase == STARTING && (int32_t)(tick - a.start_tick) > 0) {
        if (a.epoch == 255) {
            a.reason=31;
            return false;
        }
        ++a.epoch;
        a.sequence = 0;
        a.recorded = false;
        a.phase = RECORDING;
        if (!boundary(2, 0, tick) || !boundary(7, 0, a.reset_tick) || !model(0, tick, now) ||
            !snapshot(0, tick, ts))
            return false;
        a.first_record_tick = tick;

        a.pending_event = BODAQS_ACQ_FIRST;
    }
    if (a.phase == RECORDING) {
        if (a.sequence == UINT32_MAX) {
            a.reason=31;
            return false;
        }
        if ((uint32_t)(tick - a.model_tick) >= 100000 || a.sequence - a.model_seq >= 500) {
            if (!flush() || !loss_report(now,true) || !model(a.sequence, tick, now) || !snapshot(a.sequence, tick, ts))
                return false;
        }
        if (!a.count) {
            put16(a.packet, (uint16_t)a.sequence);
            a.packet[2] = a.epoch;
        }
        memcpy(a.packet + 4 + 12 * a.count, a.axes, 12);
        SampleObservation *last=&a.final_sample;
        last->sequence=a.sequence;last->tick=tick;last->sensor=ts;
        last->sensor_epoch=a.sensor_epoch;last->capture=a.capture.ordinal;
        last->slot=a.slot;last->model=a.model_id;last->epoch=a.epoch;
        memcpy(last->tags,a.tags,3);
        last->sync_sequence=last->sync_tick=0;
        last->sync_associated=bodaqs_node_sync_latest(&last->sync_sequence,&last->sync_tick);
        last->sync_present=a.sync_present;
        if(!last->sync_associated && last->sync_present) last->sync_tick=a.sync.tick;
        ++a.count;
        ++a.sequence;
        a.recorded = true;
        if (a.count == 5 && !flush())
            return false;
    }
    return true;
}
void bodaqs_node_acquisition_init(uint32_t boot, uint8_t address, BodaqsImuDisabled *stopped,
                                  BodaqsNodeCanSend send, bool (*transmit_idle)(void)) {
    memset(&a, 0, sizeof(a));
    a.boot = boot;
    a.address = address;
    a.stopped = stopped;
    a.send = send;
    a.transmit_idle = transmit_idle;
    a.sensor_epoch = 0;
    tx_head = tx_tail = tx_depth = 0;
}
void bodaqs_node_acquisition_service(uint32_t now) {
    const uint8_t *data;
    int rc=0;
    service_transmit();
    if (a.phase == IDLE || a.phase == FAILED)
        return;
    if(a.phase!=STOPPING && !bodaqs_node_capture_clock_trusted()) {fail(35);return;}
    if (a.phase == RECOVER) {
        if ((uint32_t)(now-a.recovery_ms)>=100) {(void)recovery_boundary(6,now);fail(32);return;}
        /* Bypass FIFO and discard all ambiguous words/captures, observe a fresh
         * running timestamp, then fence FIFO enable against concurrent DRDY.
         * This does not issue TIMESTAMP2 reset or change either clock epoch. */
        if (a.recovery_step < 4) {
            if (a.recovery_step==1) {
                rc=bodaqs_node_imu_read(0x40,4,&data,now);
                if(rc==1) {
                    a.resync_timestamp=bodaqs_control_get_u32(data);
                    /* Natural modular wrap is small forward progress. An
                     * unexplained jump/reset cannot inherit the old clock. */
                    if((uint32_t)(a.resync_timestamp-a.last_sensor)>
                       (uint32_t)(clock_tick()-a.last_tick)/20U+1000U) {fail(35);return;}
                    ++a.recovery_step;
                }
            } else if (a.recovery_step==3) {
                if(!bodaqs_node_capture_seed_end()) {recover(a.recovery_stage,now);return;}
                ++a.recovery_step;
            } else {
                if(a.recovery_step==2 && !a.step) {bodaqs_node_capture_discard();a.step=1;}
                a.value=a.recovery_step==0?0:0x46;
                rc=bodaqs_node_imu_register(0,true,10,&a.value,now);
                if(rc==1) {++a.recovery_step;a.step=0;}
            }
            if(rc<0) fail(14);
            return;
        }
    }
    if (a.phase == CONFIG || (a.phase == STOPPING && a.index < sizeof(addresses))) {
        bool stopping = a.phase == STOPPING;
        /* Exact-part timestamp reset command (TIMESTAMP2=AA), followed by an
         * independently read raw counter. Unlike FIFO/source restart this really
         * restarts the sensor counter, and is the only acquisition epoch advance. */
        if (a.index == 8) {
            if (stopping) {
                ++a.index;
                return;
            }
            if (!a.step) {
                a.value = 0xaa;
                rc = bodaqs_node_imu_register(0, true, 0x42, &a.value, now);
                if (rc < 0) {
                    fail(14);
                    return;
                }
                if (rc == 1)
                    a.step = 1;
            } else {
                rc = bodaqs_node_imu_read(0x40, 4, &data, now);
                if (rc < 0) {
                    fail(14);
                    return;
                }
                if (rc == 1) {
                    if (bodaqs_control_get_u32(data) > 2000 || a.sensor_epoch == UINT32_MAX) {
                        fail(35);
                        return;
                    }
                    ++a.sensor_epoch;
                    a.reset_tick = clock_tick();
                    ++a.index;
                    a.step = 0;
                }
            }
            return;
        }
        uint8_t desired = stopping ? 0 : values[a.index];
        if (!stopping && a.index==3) {
            const uint8_t odr=bodaqs_imu_profile_odr(a.stopped->profile_id);
            if (!odr) {fail(17);return;}
            desired=(uint8_t)(odr | (odr>>4));
        }
        uint8_t addr = addresses[a.index];
        if (!stopping && a.index == 9 && a.step == 1 && !a.seed_started) {
            bodaqs_node_capture_discard();
            a.seed_started = true;
        }
        if (a.step == 0) {
            rc = bodaqs_node_imu_register(0, false, addr, &a.value, now);
            if (rc == 1) {
                a.value = (a.value & ~masks[a.index]) | desired;
                a.step = 1;
            }
        } else if (a.step == 1) {
            rc = bodaqs_node_imu_register(0, true, addr, &a.value, now);
            if (rc == 1)
                a.step = 2;
        } else {
            uint8_t v = 0;
            rc = bodaqs_node_imu_register(0, false, addr, &v, now);
            if (rc == 1) {
                if ((v & masks[a.index]) != desired) {
                    fail(17);
                    return;
                }
                a.image[image_index[a.index]] = v;
                a.step = 0;
                if (++a.index == sizeof(addresses)) {
                    if (stopping) {
                        bodaqs_imu_profile_start(a.stopped, true, true, now);
                    } else {
                        if (!bodaqs_node_capture_seed_end()) {
                            if (++a.seed_attempts >= 3) {
                                fail(27);
                                return;
                            }
                            a.seed_started = false;
                            a.index = a.step = 0;
                            return;
                        }
                        a.phase = VERIFY;
                        a.index = 0;
                    }
                }
            }
        }
        if (rc < 0)
            fail(14);
        return;
    }
    if (a.phase == VERIFY) {
        uint8_t v = 0;
        rc = bodaqs_node_imu_register(0, false, proof_addresses[a.index], &v, now);
        if (rc < 0) {
            fail(14);
            return;
        }
        if (!rc)
            return;
        if ((v & proof_masks[a.index]) != (a.image[a.index] & proof_masks[a.index])) {
            fail(17);
            return;
        }
        a.image[a.index] = v;
        if (++a.index == sizeof(proof_addresses)) {
            a.phase = SETTLE;
            a.prepared = now;
            a.settle_tick = clock_tick() + 70000U;
            a.last_poll = now;
        }
        return;
    }
    if (a.phase == STOPPING) {
        if(a.loss_count || a.loss_evidence) {
            if((uint32_t)(now-a.loss_ms)<100) return;
            if(!loss_report(now,true)) {fail(31);return;}
        }
        rc = bodaqs_imu_disabled_tick(a.stopped, now);
        if (rc < 0)
            fail(a.stopped->reason);
        else if (rc == 1 && !tx_depth) {
            memset(a.packet, 0, sizeof(a.packet));
            memcpy(a.image, a.stopped->image, 24);
            a.pending_event = BODAQS_ACQ_STOPPED;
            a.phase = IDLE;
        }
        return;
    }
    if(a.phase==RECORDING || a.phase==STARTING) {
        BodaqsNodeCapture raw_sync;
        uint32_t sync_lost=bodaqs_node_capture_sync_loss_take();
        if(sync_lost) {
            if(UINT32_MAX-a.loss_evidence<sync_lost) {fail(31);return;}
            a.loss_evidence+=sync_lost;a.evidence_gap=true;
        }
        if(bodaqs_node_capture_sync_observation(&raw_sync)) {
            uint8_t p[64],*b=p+8;
            a.sync=raw_sync;a.sync_present=true;
            envelope(p,0x21,16);
            bodaqs_control_put_u32(b+4,raw_sync.tick);bodaqs_control_put_u32(b+8,a.boot);
            /* Sequence/association unknown. flags=0 preserves that distinction;
             * the independently retained master edge does not supply a pairing. */
            if(!(tx_depth<56 && queue_frame((uint16_t)(0x90+a.address),p,24))) {
                if(a.loss_evidence==UINT32_MAX) {fail(31);return;}
                ++a.loss_evidence;a.evidence_gap=true;
            }
        }
    }
    if (bodaqs_node_capture_fault()) {
        if(!bodaqs_node_capture_clock_trusted()) fail(35); else recover(11,now);
        return;
    }
    if (a.phase == SETTLE && (uint32_t)(now - a.prepared) >= 70) {
        a.phase = DISCARD;
        a.gyro = a.accel = 0;
    }
    if (!a.drain_phase) {
        if (!bodaqs_node_watermark_take() && (uint32_t)(now - a.last_poll) < 5)
            return;
        a.drain_phase = 1;
    }
    if (a.drain_phase == 1 || a.drain_phase == 3) {
        bool after = a.drain_phase == 3;
        rc = bodaqs_node_imu_read(0x3a, 2, &data, now);
        if (rc < 0) {
            fail(14);
            return;
        }
        if (!rc)
            return;
        a.last_poll = now;
        if (data[1] & 0x48) {
            recover(1,now);
            return;
        }
        a.words = (uint16_t)(data[0] | ((data[1] & 3) << 8));
        /* Retain the burst until post-read status preserves any
         * overrun-during-drain evidence. Do not publish data first and discover
         * ambiguous slots later. */
        if (after)
            for (unsigned i = 0; i < a.pending_count; ++i)
                if (!word(a.pending_words + 7 * i, now)) {
                    if(a.reason) fail(a.reason); else recover(2,now);
                    return;
                }
        if (!a.words) {
            a.drain_phase = 0;
            return;
        }
        if (a.words > 96)
            a.words = 96;
        a.drain_phase = 2;
    }
    rc = bodaqs_node_imu_read(0x78, (uint16_t)(7 * a.words), &data, now);
    if (rc < 0) {
        fail(14);
        return;
    }
    if (!rc)
        return;
    memcpy(a.pending_words, data, 7 * a.words);
    a.pending_count = a.words;
    /* Immediately recheck, including a stuck-high watermark, rather than await a
     * new edge. */
    a.drain_phase = 3;
}
void bodaqs_node_acquisition_backend(void *context, uint8_t command, uint32_t generation,
                                     uint64_t recording, uint32_t now, BodaqsAcquisitionEvent *e) {
    (void)context;
    if (command != BODAQS_ACQ_POLL)
        a.generation = generation;
    if (command == BODAQS_ACQ_PREPARE) {
        /* Reuse is scoped to a new recording after both verified stop and the
         * hardware transmit fence. PREPARE alone cannot erase exhaustion. */
        if (a.epoch_reusable && recording != a.recording) a.epoch = 0;
        a.epoch_reusable = false;
        a.recording = recording;
        a.recovery_count = 0;
        bodaqs_node_imu_cancel(0);
        a.phase = CONFIG;
        a.index = a.step = a.mask = a.count = a.drain_phase = 0;
        memset(a.packet, 0, sizeof(a.packet));
        memcpy(a.image, a.stopped->image, 24);
        a.seed_attempts = 0;
        a.seed_started = false;
        a.have_previous = a.recorded = a.ready_event = false;
        a.slot = a.gyro = a.accel = 0;
        a.reason = 0;
        a.pending_event = 0;
        a.failure_after_first = false;
        a.recovered=a.gap=a.evidence_gap=false; a.loss_count=a.loss_evidence=0;
        bodaqs_node_capture_discard();
    } else if (command == BODAQS_ACQ_START) {
        bodaqs_node_capture_sync_discard();
        a.sync_present=false;
        a.start_tick = clock_tick();
        a.phase = STARTING;
    } else if (command == BODAQS_ACQ_STOP) {
        bodaqs_node_imu_cancel(0);
        if (!flush() || (a.recorded &&
            (!snapshot_observation(a.final_sample.sequence,a.final_sample.tick,a.final_sample.sensor,&a.final_sample) ||
             !boundary(8, 0, clock_tick()))))
            a.reason = 31;
        a.drain_phase = 0;
        a.pending_event = 0;
        a.phase = STOPPING;
        a.index = a.step = 0;
    } else if (command == BODAQS_ACQ_FENCE) {
        a.count = 0;
        memset(a.packet, 0, sizeof(a.packet));
        tx_head = tx_tail = tx_depth = 0;
        a.fencing = true;
    }
    bodaqs_node_acquisition_service(now);
    if (a.fencing && !tx_depth && a.transmit_idle && a.transmit_idle()) {
        a.fencing = false;
        a.epoch_reusable = a.phase == IDLE;
        a.pending_event = BODAQS_ACQ_FENCED;
    }
    e->generation = a.generation;
    e->node_clock_epoch = 1;
    e->sensor_clock_epoch = a.sensor_epoch;
    if (a.ready_event) {
        e->kind = BODAQS_ACQ_READY;
        a.ready_event = false;
        e->register_proof_current = true;
        memcpy(e->register_image, a.image, 24);
    } else if (a.pending_event) {
        e->kind = a.pending_event;
        a.pending_event = a.failure_after_first ? BODAQS_ACQ_FAILED : 0;
        a.failure_after_first = false;
        e->reason = a.reason;
        if (e->kind == BODAQS_ACQ_STOPPED) {
            e->register_proof_current = true;
            e->known_empty = !a.recorded;
            memcpy(e->register_image, a.image, 24);
        }
        if (e->kind == BODAQS_ACQ_FIRST || (e->kind == BODAQS_ACQ_STOPPED && a.recorded)) {
            bodaqs_control_put_u32(e->boundary, e->kind == BODAQS_ACQ_FIRST ? 0 : a.sequence - 1);
            bodaqs_control_put_u32(e->boundary + 4,
                                   e->kind == BODAQS_ACQ_FIRST ? a.first_record_tick : a.last_tick);
            e->boundary[8] = a.epoch;
            e->boundary[9] = 7;
        }
    }
}
