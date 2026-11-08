#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "bodaqs_spi_probe.h"
#include "bodaqs_record_queue.h"
#define BODAQS_SPI_ADAPTER_CAPACITY 256U
#define DMA 0
#define DMA_SPI_RX_CHAN_ID 0
#define DMA_SPI_TX_CHAN_ID 1
#define GPIO_SPI_A8_CS_PORT 0
#define GPIO_SPI_A8_CS_PIN 1
static struct {uint32_t TXDATA,RXDATA;} fake_spi;
#define SPI_A8_INST (&fake_spi)
#define POWER_STARTUP_DELAY 0
static uint8_t gTransmitSlots[2][256],gTransmitIndex,gReceiveIndex;
static struct {uint8_t before[8],slots[2][256],after[8];} guarded_rx;
#define gReceiveSlots guarded_rx.slots
static uint8_t storage[BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY][256];
static BodaqsRecordQueue gSpiReceiveQueue;
typedef struct {uint32_t generation;uint64_t context;} SpiRetirement;
static SpiRetirement gSpiRetirementRequest,gSpiRetirementProof;
static bool gSpiRetiring,gSpiTransmitReady;
static BodaqsSpiProbeEngine gSpiProbe;
static struct {uint32_t slots_received,spi_recoveries,cs_release_timeouts,can_rx_frames,can_rx_hardware_losses;} gMasterRuntimeInfo;
static BodaqsRecordQueue gCanReceiveQueue;
static struct {uint32_t boundaries,prepared,malformed,queue_dropped,queue_high_water;
    uint32_t process_calls,process_max_us,process_total_us;
    uint32_t clock_epoch,timing_invalid;BodaqsSpiProbeStats engine;} gMasterSpiProbeInfo;
static unsigned remaining=256,cs_high=1,disabled,prefetched,arms,resets,fifo_count;
static uint8_t fifo[16];static uint32_t irq_mask,tick=1,clock_epoch=1,clock_calls;
static bool snapshot_irq_pending,snapshot_delivered;
static unsigned snapshot_boundary_count;
static void snapshot_irq(void);
static uint32_t __get_PRIMASK(void) {return irq_mask;}
static void __disable_irq(void) {irq_mask=1;}
static void __set_PRIMASK(uint32_t v) {
    irq_mask=v;
    if(!v && snapshot_irq_pending) {snapshot_irq_pending=false;snapshot_irq();}
}
static void __DMB(void) {}
static unsigned DL_DMA_getTransferSize(int d,int c) {(void)d;(void)c;return remaining;}
static unsigned DL_GPIO_readPins(int p,int m) {(void)p;(void)m;return cs_high;}
static void DL_DMA_disableChannel(int d,int c) {(void)d;disabled|=1U<<c;}
static unsigned DL_SPI_drainRXFIFO8(void *d,uint8_t *out,uint32_t max) {
    (void)d;unsigned take=fifo_count<max?fifo_count:max;
    memcpy(out,fifo,take);memmove(fifo,fifo+take,fifo_count-take);fifo_count-=take;return take;
}
static void DL_SPI_disable(void *d) {(void)d;assert(disabled==3);}
static void DL_SPI_reset(void *d) {(void)d;assert(disabled==3);prefetched=0;++resets;}
static void DL_SPI_enablePower(void *d) {(void)d;}
static void delay_cycles(int d) {(void)d;}
static void SYSCFG_DL_SPI_A8_init(void) {}
static int DL_SPI_getPendingInterrupt(void *d) {(void)d;return 0;}
static unsigned dma_sizes[2];
static void DL_DMA_setSrcAddr(int d,int c,uint32_t p) {(void)d;(void)c;(void)p;}
static void DL_DMA_setDestAddr(int d,int c,uint32_t p) {(void)d;(void)c;(void)p;}
static void DL_DMA_setTransferSize(int d,int c,unsigned size) {(void)d;assert(size==256);dma_sizes[c]=size;}
static void DL_DMA_enableChannel(int d,int c) {
    (void)d;assert(disabled==3 && dma_sizes[c]==256);
    if(c==DMA_SPI_TX_CHAN_ID) {disabled=0;remaining=dma_sizes[DMA_SPI_RX_CHAN_ID];++arms;}
}
static uint32_t bodaqs_master_timing_clock(void *p,uint32_t *epoch) {
    (void)p;*epoch=clock_epoch;++clock_calls;return tick++;
}
static void retire_measurement_slot(uint8_t *p,uint64_t c) {(void)p;(void)c;assert(false);}
static void retire_spi_boundary(void);
static unsigned inject_stage;
static unsigned inject_length;
static uint8_t inject_wire[256];
static void inject_boundary(unsigned stage) {
    if(inject_stage!=stage) return;
    inject_stage=0;unsigned before=gTransmitIndex;
    memcpy(gReceiveSlots[gReceiveIndex],inject_wire,inject_length);
    remaining=256-inject_length;retire_spi_boundary();
    assert(gTransmitIndex==(stage==2?(before^1U):before));
}
static void snapshot_irq(void) {snapshot_delivered=true;inject_boundary(3);}
static void request_snapshot_irq(void) {
    if(inject_stage!=3) return;
    snapshot_boundary_count=arms;
    if(irq_mask) snapshot_irq_pending=true;
    else snapshot_irq();
}
/* ACTUAL_ADAPTER */
static void physical(const uint8_t *request,unsigned length,unsigned tail) {
    assert(length>=tail && tail<=sizeof fifo);
    unsigned dma=length-tail;if(dma>256) dma=256;
    memcpy(gReceiveSlots[gReceiveIndex],request,dma);remaining=256-dma;
    fifo_count=length-dma;assert(fifo_count<=sizeof fifo);memcpy(fifo,request+dma,fifo_count);
    cs_high=1;prefetched=1;retire_spi_boundary();
    for(unsigned i=0;i<8;++i) assert(guarded_rx.before[i]==0xa5 && guarded_rx.after[i]==0xa5);
}
static BodaqsSpiProbeFrame wire_reply(BodaqsSpiProbeFrame q,uint8_t opcode,uint32_t object) {
    uint8_t request[256],observed[256];BodaqsSpiProbeFrame r;
    unsigned bytes=bodaqs_spi_probe_frame_bytes(q.profile);
    assert(bodaqs_spi_probe_encode(&q,request,bytes));
    inject_length=bytes;memcpy(inject_wire,request,bytes);
    /* Model MISO before retirement: publication only affects later CS. */
    for(unsigned attempts=0;attempts<20;++attempts) {
        memcpy(observed,gTransmitSlots[gTransmitIndex],bytes);
        physical(request,bytes,0);service_spi_receive();
        if(bodaqs_spi_probe_decode(observed,bytes,&r) && r.case_id==q.case_id &&
            r.profile==q.profile && r.node==q.node && r.fragment==q.fragment &&
            r.opcode==opcode && (!object || r.object_id==object)) return r;
    }
    assert(!"no validated asynchronous reply");return (BodaqsSpiProbeFrame){0};
}
static uint32_t value(const BodaqsSpiProbeFrame *r,unsigned index) {
    const uint8_t *p=r->payload+4*index;
    return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
int main(void) {
    memset(guarded_rx.before,0xa5,sizeof guarded_rx.before);
    memset(guarded_rx.after,0xa5,sizeof guarded_rx.after);
    bodaqs_spi_probe_init(&gSpiProbe);
    bodaqs_spi_probe_set_clock(&gSpiProbe,bodaqs_master_timing_clock,NULL);
    bodaqs_record_queue_init(&gSpiReceiveQueue,storage,256,1);
    uint8_t qwire[272]={0};BodaqsSpiProbeFrame q={0},r;
    /* Zero clocks and low CS do not retire; queue capacity stays256. */
    unsigned calls_before=clock_calls;
    retire_spi_boundary();assert(!arms && clock_calls==calls_before);
    remaining=192;cs_high=0;retire_spi_boundary();assert(!arms && clock_calls==calls_before);cs_high=1;
    unsigned lengths[]={1,63,65,127,129,255,257};
    for(unsigned i=0;i<sizeof lengths/sizeof lengths[0];++i) {
        physical(qwire,lengths[i],lengths[i]==257?1:0);
        assert(gSpiProbeReceiveMeta[gSpiReceiveQueue.head].length==lengths[i]);service_spi_receive();
        assert(!gSpiTransmitReady && !gSpiReceiveQueue.depth && !prefetched);
    }
    assert(gSpiProbe.stats.malformed>=7);
    /* CLOCK_ORACLE */
    /* Independent zlib bytes, every bit, physical truncation/tail and full FIFO.
     * This block goes red on round9: CLOCK becomes ordinary queued work. */
    assert(!bodaqs_spi_probe_is_clock(NULL,64));
    for(unsigned bytes=64;bytes<=256;bytes*=2) {
        unsigned code=bytes==64?0:bytes==128?1:2;
        BodaqsSpiProbeFrame clock={.opcode=BODAQS_PROBE_CLOCK,.profile=(uint8_t)code};
        assert(bodaqs_spi_probe_encode(&clock,qwire,bytes));
        assert(!memcmp(qwire,clock_oracle[code],bytes));
        assert(bodaqs_spi_probe_is_clock(qwire,bytes));
        uint32_t bypass=gSpiProbeClockBypassed;
        physical(qwire,bytes,3);
        assert(gSpiReceiveQueue.depth==0 && gSpiProbeClockBypassed==bypass+1);
        for(unsigned i=0;i<bytes;++i)for(unsigned bit=0;bit<8;++bit) {
            qwire[i]^=(uint8_t)(1U<<bit);
            assert(!bodaqs_spi_probe_is_clock(qwire,bytes));
            bypass=gSpiProbeClockBypassed;physical(qwire,bytes,0);
            assert(gSpiReceiveQueue.depth==1 && gSpiProbeClockBypassed==bypass);
            service_spi_receive();assert(!gSpiTransmitReady);
            qwire[i]^=(uint8_t)(1U<<bit);
        }
        for(unsigned length=bytes-1;length<=bytes+1;length+=2) {
            assert(!bodaqs_spi_probe_is_clock(qwire,length));
            bypass=gSpiProbeClockBypassed;physical(qwire,length,length==257?1:0);
            assert(gSpiReceiveQueue.depth==1 && gSpiProbeClockBypassed==bypass);
            service_spi_receive();assert(!gSpiTransmitReady);
        }
        for(unsigned variant=0;variant<3;++variant) {
            BodaqsSpiProbeFrame other=clock;
            if(variant==0)other.case_id=1;
            if(variant==1)other.profile|=4;
            if(variant==2)other.object_id=1;
            uint8_t wire[256];assert(bodaqs_spi_probe_encode(&other,wire,bytes));
            assert(!bodaqs_spi_probe_is_clock(wire,bytes));
            physical(wire,bytes,0);assert(gSpiReceiveQueue.depth==1);
            service_spi_receive();gSpiTransmitReady=false;
        }
        bodaqs_record_queue_init(&gSpiReceiveQueue,storage,256,BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY);
        uint8_t work[256];BodaqsSpiProbeFrame begin={.opcode=BODAQS_PROBE_BEGIN,.case_id=bytes,
            .profile=bodaqs_spi_probe_profile((uint16_t)bytes,16000000,4)};
        assert(bodaqs_spi_probe_encode(&begin,work,bytes));
        for(unsigned i=0;i<gSpiReceiveQueue.capacity;++i)physical(work,bytes,0);
        unsigned drops=gSpiReceiveQueue.dropped;uint32_t enqueued=gSpiProbeTurnover.enqueued;
        unsigned txindex=gTransmitIndex;gSpiTransmitReady=true;
        memcpy(gTransmitSlots[txindex^1U],work,bytes);
        physical(qwire,bytes,0);
        assert(gSpiReceiveQueue.depth==gSpiReceiveQueue.capacity && gSpiReceiveQueue.dropped==drops);
        assert(gSpiProbeTurnover.enqueued==enqueued && !gSpiTransmitReady && gTransmitIndex==(txindex^1U));
        assert(!memcmp(gTransmitSlots[gTransmitIndex],work,bytes));
        while(gSpiReceiveQueue.depth) {service_spi_receive();physical(qwire,bytes,0);}
        /* Clocking after STOP has no session authority; BEGIN remains main-owned. */
        begin.opcode=BODAQS_PROBE_STOP;assert(bodaqs_spi_probe_encode(&begin,work,bytes));
        physical(work,bytes,0);service_spi_receive();physical(qwire,bytes,0);
        assert(!gSpiProbe.active && !gSpiReceiveQueue.depth);
        bodaqs_spi_probe_init(&gSpiProbe);
        bodaqs_spi_probe_set_clock(&gSpiProbe,bodaqs_master_timing_clock,NULL);
        bodaqs_record_queue_init(&gSpiReceiveQueue,storage,256,1);
    }
    puts("actual CLOCK: independent zlib,3584 bit mutations, noncanonical CRC-valid frames, truncation/excess, full queue and STOP PASS");
    for(unsigned bytes=64;bytes<=256;bytes*=2) {
        q=(BodaqsSpiProbeFrame){.opcode=BODAQS_PROBE_BEGIN,.case_id=bytes,
            .profile=bodaqs_spi_probe_profile((uint16_t)bytes,16000000,4)};
        assert(bodaqs_spi_probe_encode(&q,qwire,bytes));
        inject_length=bytes;memcpy(inject_wire,qwire,bytes);
        physical(qwire,bytes,3);service_spi_receive();assert(gSpiTransmitReady);
        /* Physical request may see old response; only next boundary publishes. */
        physical(qwire,bytes,0);assert(!gSpiTransmitReady);
        assert(bodaqs_spi_probe_decode(gTransmitSlots[gTransmitIndex],bytes,&r));
        assert(r.case_id==bytes && r.profile==q.profile && r.opcode==129);
        service_spi_receive();
        /* Fill queue, then repeated CS loses request explicitly. */
        physical(qwire,bytes,0);unsigned drops=gSpiReceiveQueue.dropped;
        physical(qwire,bytes,0);assert(gSpiReceiveQueue.dropped==drops+1);
        service_spi_receive();physical(qwire,bytes,0);service_spi_receive();
        physical(qwire,bytes,0); /* consume published reply and retain request */
        inject_stage=1;service_spi_receive();assert(!inject_stage && gSpiTransmitReady);
        physical(qwire,bytes,0);inject_stage=2;service_spi_receive();assert(!inject_stage && !gSpiTransmitReady);
        /* Drain injected empty receive; then explicit STOP through real owner. */
        service_spi_receive();
        if(gSpiTransmitReady) physical(qwire,bytes,0);
        q.opcode=BODAQS_PROBE_STOP;assert(bodaqs_spi_probe_encode(&q,qwire,bytes));
        if(gSpiReceiveQueue.depth) {service_spi_receive();if(gSpiTransmitReady) physical(qwire,bytes,0);}
        physical(qwire,bytes,0);service_spi_receive();
        if(gSpiTransmitReady) physical(qwire,bytes,0);
        service_spi_receive();assert(!gSpiProbe.active);
        if(gSpiTransmitReady) physical(qwire,bytes,0);
        if(gSpiReceiveQueue.depth) service_spi_receive();
        gSpiTransmitReady=false;
    }
    assert(arms==resets);
    /* Public acceptance now crosses actual DMA and CS boundary for every
     * fragment, then ACK retirement is interrupted on both publication sides. */
    for(unsigned bytes=64;bytes<=256;bytes*=2) {
        bodaqs_spi_probe_init(&gSpiProbe);gSpiTransmitReady=false;
        bodaqs_spi_probe_set_clock(&gSpiProbe,bodaqs_master_timing_clock,NULL);
        memset(gTransmitSlots,0,sizeof gTransmitSlots);
        bodaqs_record_queue_init(&gSpiReceiveQueue,storage,256,BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY);
        q=(BodaqsSpiProbeFrame){.opcode=BODAQS_PROBE_BEGIN,.case_id=1,
            .profile=bodaqs_spi_probe_profile((uint16_t)bytes,8000000,4)};
        (void)wire_reply(q,129,0);
        for(unsigned node=0;node<4;++node) {
            uint8_t accepted[1008];unsigned used=0;
            q.opcode=BODAQS_PROBE_POLL;q.node=(uint8_t)node;
            for(unsigned i=0;i<bodaqs_spi_probe_fragment_count(q.profile);++i) {
                q.fragment=(uint8_t)i;r=wire_reply(q,130,1);
                assert(r.payload_length<=sizeof accepted-used);
                memcpy(accepted+used,r.payload,r.payload_length);used+=r.payload_length;
            }
            assert(used==1008 && bodaqs_spi_probe_crc(accepted,used)==r.logical_crc);
            if(!node) assert(r.logical_crc==0x2c64f296U);
            /* No ACK is emitted until complete validated RAM acceptance. */
            q.opcode=BODAQS_PROBE_ACK;q.fragment=0;q.object_id=1;q.logical_crc=r.logical_crc^1;
            r=wire_reply(q,255,1);assert(r.payload[0]==BODAQS_PROBE_CHECKSUM);
            q.logical_crc^=1;q.opcode=BODAQS_PROBE_ACK_FETCH;
            inject_stage=node%2+1;r=wire_reply(q,132,2);assert(!inject_stage);
            r=wire_reply(q,132,2);assert(gSpiProbe.stats.retired_objects==node+1);
            q.object_id=0;q.logical_crc=0;
        }
        q=(BodaqsSpiProbeFrame){.opcode=BODAQS_PROBE_STATS,.case_id=1,.profile=q.profile,.fragment=1};
        r=wire_reply(q,133,0);assert(r.payload_length==40 && r.payload[32]==1);
        if(bytes==64) {
            /* Discard any published page1 reply, enqueue page2, and interrupt
             * between boundary count and total snapshot reads. The fake NVIC
             * honors PRIMASK, so the IRQ may run only after the whole copy. */
            q.fragment=2;assert(bodaqs_spi_probe_encode(&q,qwire,bytes));
            inject_stage=3;
            for(unsigned attempt=0;attempt<20 && !snapshot_delivered;++attempt) {
                physical(qwire,bytes,0);service_spi_receive();
            }
            assert(snapshot_delivered && !snapshot_irq_pending && !inject_stage);
            assert(gSpiTransmitReady);
            assert(gSpiProbe.receive_stats[0]==1 && gSpiProbe.receive_stats[1]==BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY);
            assert((uint32_t)(gSpiProbe.receive_stats[6]-gSpiProbe.receive_stats[7])==gSpiProbe.receive_stats[2]);
            uint32_t copied_events=gSpiProbe.receive_stats[6]+gSpiProbe.receive_stats[8]+gSpiProbe.receive_stats[9];
            uint32_t live_events=gSpiProbeTurnover.enqueued+gSpiProbeTurnover.full_ready+gSpiProbeTurnover.full_other;
            /* The injected boundary runs after ALL old/new page copies. */
            assert((uint32_t)(live_events-copied_events)==1);
            assert(gSpiProbe.turnover_stats[1]==gSpiProbeTurnover.wait_calls);
            uint8_t intended[256],observed[256];
            memcpy(intended,gTransmitSlots[gTransmitIndex^1U],bytes);
            bool delivered=false;
            for(unsigned attempt=0;attempt<20 && !delivered;++attempt) {
                memcpy(observed,gTransmitSlots[gTransmitIndex],bytes);
                physical(qwire,bytes,0);service_spi_receive();
                delivered=memcmp(observed,intended,bytes)==0;
            }
            assert(delivered && bodaqs_spi_probe_decode(observed,bytes,&r));
            assert(r.opcode==133 && r.fragment==2 && value(&r,3)==snapshot_boundary_count);
            assert(value(&r,4)==snapshot_boundary_count && value(&r,5)==1);
            assert(arms>snapshot_boundary_count);
        }
        q.fragment=2;r=wire_reply(q,133,0);
        assert(r.payload_length==40 && value(&r,0)>0 && value(&r,1)>=value(&r,0));
        assert(value(&r,2)>0 && value(&r,3)>0 && value(&r,4)>=value(&r,3));
        assert(value(&r,5)>0 && value(&r,6)>0 && value(&r,7)>=value(&r,6));
        assert(value(&r,8)>0 && value(&r,9)==0);
        uint32_t process_max=value(&r,2),retire_max=value(&r,5),wait_max=value(&r,8);
        q.fragment=3;r=wire_reply(q,133,0);
        assert(value(&r,0)>0 && value(&r,2)>0 && value(&r,4)>0 && value(&r,6)>0 && value(&r,8)>0);
        q.fragment=4;r=wire_reply(q,133,0);
        assert(value(&r,0)==1 && value(&r,1)==BODAQS_SPI_PROBE_CRC_TABLE && value(&r,2)==1 && value(&r,3)==0 && value(&r,4)==1);
        q.fragment=2;
        /* Epoch0 invalidates samples, never turns clock state into a counter
         * delta or resets boot maxima/calls, even across STOP/new case. */
        if(bytes==256) {
            clock_epoch=0;
            /* Same-identity asynchronous replies may be from the previous
             * query. Retire those before inspecting the changed clock state. */
            (void)wire_reply(q,133,0);(void)wire_reply(q,133,0);
            r=wire_reply(q,133,0);
            assert(value(&r,9)==1 && value(&r,2)>=process_max &&
                value(&r,5)>=retire_max && value(&r,8)>=wait_max);
            BodaqsSpiProbeFrame invalid=r;
            (void)wire_reply(q,133,0);r=wire_reply(q,133,0);
            assert(value(&r,0)>value(&invalid,0) && value(&r,3)>value(&invalid,3) &&
                value(&r,6)>value(&invalid,6));
            for(unsigned i=0;i<9;++i) if(i%3)
                assert(value(&r,i)==value(&invalid,i));
            clock_epoch=1;
        }
        q.opcode=BODAQS_PROBE_STOP;q.fragment=0;(void)wire_reply(q,134,0);
        assert(!gSpiProbe.active && gSpiProbe.stats.retired_objects==4);
    }
    /* Bounded backlog crosses the actual retirement, main pop, publication and
     * rearm bodies. Distinct bytes/lengths must survive DMA-buffer reuse. */
    bodaqs_spi_probe_init(&gSpiProbe);gSpiTransmitReady=false;gSpiRetiring=false;
    bodaqs_spi_probe_set_clock(&gSpiProbe,bodaqs_master_timing_clock,NULL);
    memset((void*)&gSpiProbeTurnover,0,sizeof gSpiProbeTurnover);
    memset((void*)&gSpiProbeBoundaryInfo,0,sizeof gSpiProbeBoundaryInfo);
    bodaqs_record_queue_init(&gSpiReceiveQueue,storage,256,BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY);
    clock_epoch=1;tick=UINT32_MAX-2U;
    gSpiProbeTurnover.enqueued=gSpiProbeTurnover.dequeued=UINT32_MAX-2U;
    uint8_t burst[4][256];unsigned burst_len[]={64,64,128,128};
    for(unsigned i=0;i<4;++i) {
        q=(BodaqsSpiProbeFrame){.opcode=i%2?BODAQS_PROBE_STOP:BODAQS_PROBE_BEGIN,
            .case_id=501+i/2,.profile=bodaqs_spi_probe_profile(burst_len[i],8000000,4)};
        assert(bodaqs_spi_probe_encode(&q,burst[i],burst_len[i]));
        physical(burst[i],burst_len[i],i==2?3:0);
    }
    const unsigned cap=BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY;
    assert(gSpiReceiveQueue.depth==cap && gSpiReceiveQueue.dropped==4-cap);
    assert(gSpiProbeTurnover.full_other==4-cap && !gSpiProbeTurnover.full_ready);
    for(unsigned i=0;i<cap;++i) {
        unsigned cell=(gSpiReceiveQueue.head+i)%cap;
        assert(gSpiProbeReceiveMeta[cell].length==burst_len[i]);
        assert(!memcmp(storage[cell],burst[i],burst_len[i]));
    }
    /* Full/no-reply classification, then interrupt the first writer before
     * publication to refill its freed cell. The next boundary is full/ready. */
    physical(qwire,1,0);
    unsigned full_other=gSpiProbeTurnover.full_other;
    inject_length=1;inject_wire[0]=0;inject_stage=1;service_spi_receive();
    assert(!inject_stage && gSpiTransmitReady && gSpiReceiveQueue.depth==cap);
    physical(qwire,1,0);
    assert(gSpiProbeTurnover.full_ready==1 && gSpiProbeTurnover.full_other==full_other);
    unsigned popped=1;
    for(unsigned steps=0;steps<100 && (gSpiReceiveQueue.depth || gSpiTransmitReady);++steps) {
        if(gSpiTransmitReady) {probe_turnover_blocked(true);physical(qwire,1,0);}
        if(popped<cap) {
            assert(gSpiProbeReceiveMeta[gSpiReceiveQueue.head].length==burst_len[popped]);
            assert(!memcmp(storage[gSpiReceiveQueue.head],burst[popped],burst_len[popped]));
            ++popped;
        }
        service_spi_receive();
        assert((uint32_t)(gSpiProbeTurnover.enqueued-gSpiProbeTurnover.dequeued)==gSpiReceiveQueue.depth);
    }
    assert(popped==cap && !gSpiReceiveQueue.depth && !gSpiTransmitReady);
    assert(!gSpiProbeTurnover.invalid && gSpiProbeTurnover.wait_total>0);
    if(cap==4)assert(gSpiProbeTurnover.backlog_pops>0 && !gSpiProbe.active);
    /* Read additive pages through actual snapshots and delayed physical replies. */
    q=(BodaqsSpiProbeFrame){.opcode=BODAQS_PROBE_STATS,.case_id=gSpiProbe.case_id,.profile=gSpiProbe.profile,.fragment=5};
    r=wire_reply(q,133,0);
    assert(value(&r,0)==1 && value(&r,1)==cap && value(&r,2)<=cap && value(&r,3)<=cap);
    assert((uint32_t)(value(&r,6)-value(&r,7))==value(&r,2));
    q.fragment=6;r=wire_reply(q,133,0);
    assert(value(&r,0)==1 && value(&r,1)>0 && value(&r,2)>0 && value(&r,3)>0 && value(&r,9)==0);
    /* A nonzero epoch change excludes invalid elapsed and stays sticky after
     * restoration and STOP/new scope; boot-only counters are never reset. */
    if(gSpiTransmitReady)physical(qwire,1,0);
    while(gSpiReceiveQueue.depth)service_spi_receive();
    physical(qwire,1,0);clock_epoch=2;service_spi_receive();
    assert(gSpiProbeTurnover.invalid);clock_epoch=1;
    q.fragment=5;(void)wire_reply(q,133,0);r=wire_reply(q,133,0);assert(value(&r,5)==1);
    q.opcode=BODAQS_PROBE_STOP;q.fragment=0;(void)wire_reply(q,134,0);
    q.opcode=BODAQS_PROBE_BEGIN;q.case_id+=100;(void)wire_reply(q,129,0);
    q.opcode=BODAQS_PROBE_STATS;q.fragment=5;r=wire_reply(q,133,0);assert(value(&r,5)==1);
    printf("actual probe adapter: queue%u mixed lengths/bytes/FIFO/overflow/publication/counter+tick wrap/epoch/STOP PASS\n",cap);
    puts("actual probe adapter: CS lengths/FIFO/overflow/queue/publication/entry/exit PASS");
    puts("actual probe adapter: complete RAM objects, wrong/lost/repeated ACK and ACK publication preemption PASS");
    puts("actual probe adapter: coherent IRQ-fenced STATS2, boot maxima and sticky invalid timing PASS");
    return 0;
}
