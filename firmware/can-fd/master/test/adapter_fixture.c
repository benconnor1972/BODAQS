#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "bodaqs_record_queue.h"
#include "bodaqs_measurement.h"
#include "bodaqs_can_network.h"
#include "bodaqs_master_service.h"
/* DRAIN_TYPES */
#define CAN_RX_CAPACITY 8U
#define MCAN0_INST 0
#define DL_MCAN_RX_FIFO_NUM_0 0
#define DL_MCAN_MEM_TYPE_FIFO 0
typedef struct {uint32_t id; uint8_t xtd,rtr,fdf,brs,dlc,data[64];} DL_MCAN_RxBufElement;
typedef struct {unsigned num,fillLvl,getIdx;} DL_MCAN_RxFIFOStatus;
typedef struct {DL_MCAN_RxBufElement message; uint32_t received_ms,received_tick; uint8_t received_flags; uint64_t ordinal;} CanReceiveRecord;
typedef struct {uint32_t source,evidence,tick;uint64_t ordinal;uint16_t first,last;uint8_t epoch;bool essential;} RejectedCan;
static CanReceiveRecord storage[8];
static BodaqsRecordQueue gCanReceiveQueue;
static RejectedCan gRejectedCan[4];
static uint64_t gCanReceiveOrdinal;
static uint32_t gUptimeMs;
static struct {unsigned can_malformed_frames,can_rx_frames,can_rx_hardware_losses,spi_recoveries;} gMasterRuntimeInfo;
static DL_MCAN_RxBufElement hardware;
static unsigned hardware_depth;
static void DL_MCAN_getRxFIFOStatus(int dev,DL_MCAN_RxFIFOStatus *f) {(void)dev;f->fillLvl=hardware_depth;f->getIdx=0;}
static void DL_MCAN_readMsgRam(int d,int type,int index,unsigned num,DL_MCAN_RxBufElement *m) {(void)d;(void)type;(void)index;(void)num;*m=hardware;}
static void DL_MCAN_writeRxFIFOAck(int d,unsigned num,unsigned idx) {(void)d;(void)num;(void)idx;--hardware_depth;}
static uint32_t test_tick=12345,test_epoch=1;
static uint32_t bodaqs_master_timing_clock(void *c,uint32_t *epoch) {(void)c;*epoch=test_epoch;return test_tick;}
#define DMA 0
#define BODAQS_SPI_ADAPTER_CAPACITY BODAQS_MASTER_SLOT_BYTES
#define DMA_SPI_RX_CHAN_ID 0
#define DMA_SPI_TX_CHAN_ID 1
#define GPIO_SPI_A8_CS_PORT 0
#define GPIO_SPI_A8_CS_PIN 1
#define SPI_A8_INST 0
#define POWER_STARTUP_DELAY 0
static BodaqsMasterService gService;
static uint8_t gTransmitSlots[2][84],gReceiveSlots[2][84],gTransmitIndex,gReceiveIndex;
static uint8_t receive_storage[1][84];
static BodaqsRecordQueue gSpiReceiveQueue;
typedef struct {uint32_t generation; uint64_t context;} SpiRetirement;
static volatile SpiRetirement gSpiRetirementRequest,gSpiRetirementProof;
static bool gSpiRetiring,gSpiTransmitReady;
static uint16_t gSpiReceiveLength;
#define BODAQS_ENABLE_BUCK 0
#define BODAQS_ENABLE_FRONT_BRANCH 0
#define GPIO_BOARD_PORT 0
#define GPIO_BOARD_FRONT_ENABLE_PIN 1
static bool gLoggerCommunicationEstablished;
static void DL_GPIO_setPins(int p,int m) {(void)p;(void)m;assert(false);}
static void update_service_status(void) {test_tick+=3;}
static unsigned remaining=20,cs_high=1,prefetched_tx,disabled,reset_count,arm_count;
static uint32_t irq_mask;
static uint32_t __get_PRIMASK(void) {return irq_mask;}
static void __disable_irq(void) {irq_mask=1;}
static void __DMB(void) {}
static void __set_PRIMASK(uint32_t p) {irq_mask=p;}
static unsigned DL_DMA_getTransferSize(int d,int c) {(void)d;(void)c;return remaining;}
static unsigned DL_GPIO_readPins(int p,int m) {(void)p;(void)m;return cs_high;}
/* TI STAT.BUSY includes a nonempty TX FIFO, even with CS inactive. */
static inline bool DL_SPI_isBusy(int d) {(void)d;return !cs_high || prefetched_tx!=0;}
static void DL_DMA_disableChannel(int d,int c) {(void)d;disabled|=1U<<c;}
static unsigned DL_SPI_drainRXFIFO8(int d,uint8_t *p,unsigned n) {(void)d;(void)p;(void)n;return 0;}
static void DL_SPI_disable(int d) {(void)d;}
static void DL_SPI_reset(int d) {(void)d;assert(disabled==3);prefetched_tx=0;++reset_count;}
static void DL_SPI_enablePower(int d) {(void)d;}
static void delay_cycles(int d) {(void)d;}
static void SYSCFG_DL_SPI_A8_init(void) {}
static int DL_SPI_getPendingInterrupt(int d) {(void)d;return 0;}
static void arm_spi_slot(void) {assert(reset_count);disabled=0;++arm_count;}
static unsigned processed_can;
static uint64_t processed_ordinal;
static bool refill_during_decode;
static bool inject_can_on_take,drop_during_decode;
static bool inject_reply_retirement;
static void inject_can_arrival(BodaqsRecordQueue *queue);
static void injected_reply_retirement(void);
static void capture_can_receive_fifo(void);
static void process_can_message(const DL_MCAN_RxBufElement *message,
    uint32_t received_ms,uint32_t received_tick,uint64_t ordinal,uint8_t flags) {
    (void)message;(void)received_ms;(void)received_tick;(void)flags;
    assert(!irq_mask); /* The main owner decodes with IRQs enabled. */
    test_tick+=7;
    if(drop_during_decode) {drop_during_decode=false;++gService.ingress[0].dropped;}
    assert(ordinal>processed_ordinal);processed_ordinal=ordinal;++processed_can;
    if(refill_during_decode) {refill_during_decode=false;hardware_depth=1;capture_can_receive_fifo();}
}
static void injected_cs_preemption(void);
/* PRODUCTION_FUNCTIONS */
static void injected_reply_retirement(void) {
    if(inject_reply_retirement) {
        assert(gSpiTransmitReady);inject_reply_retirement=false;
        retire_measurement_slot(gTransmitSlots[gTransmitIndex^1U],gService.measurement.mode.context);
    }
}
static void inject_can_arrival(BodaqsRecordQueue *queue) {
    if(queue==&gCanReceiveQueue && inject_can_on_take) {
        assert(!irq_mask);inject_can_on_take=false;
        hardware_depth=1;capture_can_receive_fifo();
    }
}
static void injected_cs_preemption(void) {retire_spi_boundary();}
int main(void) {
    /* START-like consecutive metadata bursts, with one main-loop CAN turn
     * between them. Exercise actual capture, pop and drain function bodies. */
    bodaqs_record_queue_init(&gCanReceiveQueue,storage,sizeof storage[0],8);
    hardware=(DL_MCAN_RxBufElement){.id=0x90U<<18,.fdf=1,.brs=1,.dlc=15};
    hardware.data[0]=1;hardware.data[1]=0x24;
    hardware_depth=8;capture_can_receive_fifo();service_can_receive();
    hardware_depth=4;capture_can_receive_fifo();
    fprintf(stderr,"START burst: queued=%u dropped=%lu processed=%u essential=%u\n",
        gCanReceiveQueue.depth,(unsigned long)gCanReceiveQueue.dropped,processed_can,gRejectedCan[0].essential);
    assert(!gCanReceiveQueue.dropped && !gRejectedCan[0].essential);
    service_can_receive();assert(processed_can==12 && processed_ordinal==12);
    assert(!gCanReceiveQueue.depth);
    /* An IRQ may refill during decoding; a turn must still return to SPI. */
    hardware_depth=8;capture_can_receive_fifo();refill_during_decode=true;
    service_can_receive();
    assert(processed_can==20 && gCanReceiveQueue.depth==1);
    service_can_receive();assert(processed_can==21 && !gCanReceiveQueue.depth);
    puts("bounded CAN START-burst drain and ISR refill: PASS");
    gCanReceiveOrdinal=0;
    bodaqs_record_queue_init(&gCanReceiveQueue,storage,sizeof storage[0],8);
    hardware=(DL_MCAN_RxBufElement){.id=0x118U<<18,.fdf=1,.brs=1,.dlc=15};
    hardware.data[0]=40;hardware.data[2]=7;hardware.data[3]=5;
    assert(can_standard_identifier(&hardware)==0x118);
    hardware_depth=8;capture_can_receive_fifo();
    assert(gCanReceiveQueue.depth==8);
    hardware_depth=1;capture_can_receive_fifo();
    assert(gRejectedCan[3].source==5 && gRejectedCan[3].first==40 && gRejectedCan[3].last==44);
    assert(gRejectedCan[3].epoch==7 && gRejectedCan[3].ordinal==9 && !gRejectedCan[3].essential);
    hardware.id=0x92U<<18;hardware.data[1]=0x23;hardware.data[13]=9;
    hardware_depth=1;capture_can_receive_fifo();
    assert(gRejectedCan[2].evidence==1 && !gRejectedCan[2].essential);
    hardware.data[1]=0x24;hardware_depth=1;capture_can_receive_fifo();
    assert(gRejectedCan[2].evidence==2 && gRejectedCan[2].essential);
    puts("raw MCAN queue overflow: PASS");
    bodaqs_record_queue_init(&gSpiReceiveQueue,receive_storage,84,1);
    gService.receptions[0].count=2;
    gService.acquisition_record[0]=13;gService.acquisition_boot[0]=17;
    BodaqsControlRecord request={0},reply={0};
    request.opcode=BODAQS_CONTROL_FENCE_OLD_DATA;
    bodaqs_control_put_u64(request.data,13);
    reply.node_boot_id=17;reply.data_length=24;reply.data[0]=3;
    /* Actual service result code is interrupted after pending publication,
     * exactly before the store that used to overwrite the ISR's fenced=true. */
    acquisition_result(&gService,0,&reply,&request);
    gService.receptions[0].count=2; /* model another retained ingress tail */
    assert(gService.acquisition_retirement_pending && !gService.measurement.fenced);
    assert(gService.receptions[0].count==2);
    assert(arm_count==1 && gService.acquisition_retirement_generation==1);
    gService.measurement.mode.context=77;
    gService.acquisition_retirement_generation=1;
    service_spi_retirement();
    assert(!gService.measurement.fenced); /* earlier CS is not current proof */
    remaining=84;retire_spi_boundary();
    assert(gSpiRetirementProof.generation==0); /* no clocked slot */
    remaining=20;cs_high=0;retire_spi_boundary();
    assert(gSpiRetirementProof.generation==0); /* DMA/CS still in flight */
    /* A 64-byte transaction leaves bytes from the 84-byte TX DMA capacity.
     * CS is high: the wire is finished, but STAT.BUSY remains set for TX FIFO.
     * The boundary must reset that FIFO and deliver the received short slot. */
    cs_high=1;prefetched_tx=1; // At least one unsent FIFO byte keeps BUSY set.
    assert(DL_SPI_isBusy(SPI_A8_INST));
    BodaqsMeasurementSlot data={0};data.kind=2;data.context=77;data.node=0;
    assert(bodaqs_measurement_encode(&data,gTransmitSlots[0],64));
    assert(bodaqs_measurement_encode(&data,gTransmitSlots[1],64));
    gSpiTransmitReady=true;
    retire_spi_boundary();
    assert(gSpiReceiveLength==64 && prefetched_tx==0 && reset_count!=0);
    assert(gSpiRetirementProof.generation==1 && gSpiRetirementProof.context==77);
    assert(gService.receptions[0].count==2 && !gService.measurement.fenced);
    BodaqsMeasurementSlot decoded;
    assert(bodaqs_measurement_decode(gTransmitSlots[0],64,&decoded) && decoded.kind==0);
    assert(bodaqs_measurement_decode(gTransmitSlots[1],64,&decoded) && decoded.kind==0);
    /* A second node finishes its fence before main consumes the first proof. */
    acquisition_result(&gService,0,&reply,&request);
    assert(gService.acquisition_retirement_generation==2);
    gService.receptions[0].count=2;
    service_spi_retirement();
    assert(gService.acquisition_retirement_pending && !gService.measurement.fenced);
    retire_spi_boundary();
    assert(gService.receptions[0].count==2); /* ISR still cannot retire rings */
    service_spi_retirement();
    assert(gService.measurement.fenced && !gService.acquisition_retirement_pending);
    assert(gService.receptions[0].count==0 && gService.retired_tail_frames==6);
    /* Context changes also invalidate an otherwise matching generation. */
    gService.acquisition_retirement_pending=true;gService.measurement.fenced=false;
    gService.measurement.mode.context=88;
    service_spi_retirement();
    assert(!gService.measurement.fenced);
    retire_spi_boundary();service_spi_retirement();
    assert(gService.measurement.fenced);
    /* A preempted writer owns the unpublished inactive buffer. */
    gSpiTransmitReady=false;
    assert(bodaqs_measurement_encode(&data,gTransmitSlots[gTransmitIndex^1U],64));
    uint8_t saved[84];memcpy(saved,gTransmitSlots[gTransmitIndex^1U],84);
    retire_spi_boundary();
    assert(memcmp(saved,gTransmitSlots[gTransmitIndex^1U],84)==0);
    /* Control replies survive retirement, including a published inactive one. */
    data.kind=5;
    assert(bodaqs_measurement_encode(&data,gTransmitSlots[gTransmitIndex^1U],64));
    memcpy(saved,gTransmitSlots[gTransmitIndex^1U],84);gSpiTransmitReady=true;
    retire_spi_boundary();
    assert(memcmp(saved,gTransmitSlots[gTransmitIndex],84)==0);
    puts("CS preemption and generation/context retirement: PASS");
    /* Historical losses and PREPARE work must not enter a START window. */
    memset(&gService,0,sizeof gService);
    memset((void *)&gMasterDrainInfo,0,sizeof gMasterDrainInfo);
    gSpiReceiveQueue.dropped=30;gCanReceiveQueue.dropped=40;
    gMasterRuntimeInfo.can_rx_hardware_losses=9;
    gService.ingress[0].dropped=17;gService.ingress[0].high_water=128;
    gService.ingress[0].count=5;
    gService.measurement.mode.context=456;gService.measurement.mode.recording=123;
    test_tick=UINT32_MAX-31;
    drain_check();drain_cost(0,0);assert(!gMasterDrainInfo.state && !gMasterDrainInfo.calls[0]);
    gService.acquisition_started=1;drain_check();
    assert(gMasterDrainInfo.state==1 && gMasterDrainInfo.ingress_sampled_high_water[0]==5);
    const uint32_t started=test_tick;test_tick+=100;
    gSpiReceiveQueue.dropped+=2;gCanReceiveQueue.dropped+=3;
    ++gMasterRuntimeInfo.can_rx_hardware_losses;gService.retained_frames=7;
    gService.ingress[0].count=9;
    drain_cost(1,started);drain_check();
    assert(gMasterDrainInfo.elapsed_us==100 && gMasterDrainInfo.spi_dropped==2);
    assert(gMasterDrainInfo.can_dropped==3 && gMasterDrainInfo.can_hardware_losses==1);
    assert(gMasterDrainInfo.retained_frames==7 && gMasterDrainInfo.ingress_sampled_high_water[0]==9);
    assert(gMasterDrainInfo.calls[1]==1 && gMasterDrainInfo.total_us[1]==100 && gMasterDrainInfo.histogram[1][1]==1);
    ++gService.ingress[0].dropped;gService.ingress[0].count=128;drain_check();
    assert(gMasterDrainInfo.state==2 && gMasterDrainInfo.finish_reason==1);
    MasterDrainInfo frozen;memcpy(&frozen,(const void *)&gMasterDrainInfo,sizeof frozen);
    test_tick+=200;gSpiReceiveQueue.dropped+=500;gService.acquisition_started=0;
    drain_check();drain_cost(1,started);
    assert(memcmp(&frozen,(const void *)&gMasterDrainInfo,sizeof frozen)==0);
    /* A new context gets new baselines, including a distrusted clock. */
    gService.measurement.mode.context=457;gService.acquisition_started=1;
    gService.ingress[0].dropped=0;gService.ingress[0].count=0;test_epoch=0;
    drain_check();assert(gMasterDrainInfo.state==1 && gMasterDrainInfo.timing_invalid);
    assert(!gMasterDrainInfo.spi_dropped && !gMasterDrainInfo.ingress_dropped[0]);
    gService.acquisition_started=0;drain_check();
    assert(gMasterDrainInfo.state==2 && gMasterDrainInfo.finish_reason==2);
    gService.measurement.mode.context=458;gService.acquisition_started=1;test_epoch=1;drain_check();
    gService.measurement.mode.context=459;gService.ingress[0].dropped=0;drain_check();
    assert(gMasterDrainInfo.state==2 && gMasterDrainInfo.finish_reason==3);
    /* Execute the actual SPI owner and bounded CAN drain with deterministic
     * clock costs. Downstream CAN decode remains a mock, not a capacity test. */
    bodaqs_master_service_init(&gService,NULL);
    memset((void *)&gMasterDrainInfo,0,sizeof gMasterDrainInfo);
    bodaqs_record_queue_init(&gSpiReceiveQueue,receive_storage,84,1);
    bodaqs_record_queue_init(&gCanReceiveQueue,storage,sizeof storage[0],8);
    gService.measurement.mode.phase=2;gService.measurement.mode.context=460;
    processed_ordinal=0;
    gService.measurement.mode.recording=124;
    data=(BodaqsMeasurementSlot){0};data.node=255;data.context=460;
    assert(bodaqs_measurement_encode(&data,saved,64));
    gSpiReceiveLength=64;gSpiTransmitReady=false;
    assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    assert(!gMasterDrainInfo.state && gSpiTransmitReady);
    gService.acquisition_started=1;gSpiTransmitReady=false;
    assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    assert(gMasterDrainInfo.state==1 && gMasterDrainInfo.calls[0]==1 && gMasterDrainInfo.calls[1]==1);
    assert(gMasterDrainInfo.total_us[0]==3 && gSpiTransmitReady && !irq_mask);
    /* A CS retirement immediately after publication can replace a data reply
     * with IDLE. Its produced-kind counter must use the owner's local copy. */
    gService.receptions[0].count=1;gService.receptions[0].cls=1;
    assert(bodaqs_fragment_seal(&gService.receptions[0].object,gService.receptions[0].bytes,1024,460,1,0,1,1,92));
    data.kind=1;data.node=0;data.body[0]=1;
    assert(bodaqs_measurement_encode(&data,saved,64));
    gSpiTransmitReady=false;inject_reply_retirement=true;
    assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    assert(!inject_reply_retirement && gMasterDrainInfo.fragments[0]==1 && gMasterDrainInfo.polls[0]==1);
    assert(gMasterDrainInfo.version==2 && gMasterDrainInfo.data_unique_fragments[0]==1);
    assert(gMasterDrainInfo.data_objects[0]==1 && gMasterDrainInfo.data_records[0]==1);
    assert(gMasterDrainInfo.data_batch_records[0][1]==1);
    assert(bodaqs_measurement_decode(gTransmitSlots[gTransmitIndex^1U],64,&decoded) && decoded.kind==0);
    hardware_depth=8;capture_can_receive_fifo();service_can_receive();
    assert(gMasterDrainInfo.calls[2]==1 && gMasterDrainInfo.total_us[2]==56);
    assert(gMasterDrainInfo.can_queue_sampled_high_water==8 && !gCanReceiveQueue.depth);
    test_epoch=0;drain_check();assert(gMasterDrainInfo.timing_invalid);
    /* Arrival after the entry depth peek must still be timed and freeze loss. */
    inject_can_on_take=true;drop_during_decode=true;
    service_can_receive();
    assert(!inject_can_on_take && !drop_during_decode);
    assert(gMasterDrainInfo.calls[2]==2 && gMasterDrainInfo.total_us[2]==63);
    assert(gMasterDrainInfo.state==2 && gMasterDrainInfo.finish_reason==1);
    puts("START-scoped drain timing, loss baselines, first-loss freeze and turnover: PASS");
    /* Count distinct prepared fragments and genuine ACK retirement through the
     * real SPI owner. This does not assert physical delivery of those replies. */
    bodaqs_master_service_init(&gService,NULL);
    bodaqs_record_queue_init(&gSpiReceiveQueue,receive_storage,84,1);
    memset((void *)&gMasterDrainInfo,0,sizeof gMasterDrainInfo);
    gService.measurement.mode.phase=2;gService.measurement.mode.context=461;
    gService.measurement.mode.recording=125;
    data=(BodaqsMeasurementSlot){0};data.node=255;data.context=461;
    assert(bodaqs_measurement_encode(&data,saved,64));gSpiTransmitReady=false;
    assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    gService.acquisition_started=1;
    gService.receptions[0].count=3;gService.receptions[0].cls=1;
    assert(bodaqs_fragment_seal(&gService.receptions[0].object,gService.receptions[0].bytes,1024,461,5,0,1,1,244));
    data=(BodaqsMeasurementSlot){0};data.kind=1;data.node=0;data.context=461;data.body[0]=1;
    const uint8_t requested_indices[]={0,1,1,6};
    for(unsigned i=0;i<sizeof requested_indices;++i) {
        data.index=requested_indices[i];data.object=i?5:0;
        assert(bodaqs_measurement_encode(&data,saved,64));
        gSpiTransmitReady=false;
        assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    }
    assert(gMasterDrainInfo.data_objects[0]==1 && gMasterDrainInfo.data_records[0]==3);
    assert(gMasterDrainInfo.data_batch_records[0][3]==1);
    assert(gMasterDrainInfo.data_unique_fragments[0]==3 && gMasterDrainInfo.data_repeat_fragments[0]==1);
    assert(gMasterDrainInfo.data_head_polls[0]==1 && !gMasterDrainInfo.data_empty_polls[0]);
    bodaqs_fragment_ack(&gService.receptions[0].object,1,&data);
    assert(bodaqs_measurement_encode(&data,saved,64));
    for(unsigned i=0;i<2;++i) {
        gSpiTransmitReady=false;
        assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    }
    assert(gMasterDrainInfo.data_acked_objects[0]==1 && gMasterDrainInfo.data_acked_records[0]==3);
    assert(gService.objects_acked==1); /* The replay was accepted but retired nothing. */
    data=(BodaqsMeasurementSlot){0};data.kind=1;data.node=0;data.context=461;data.body[0]=2;
    assert(bodaqs_measurement_encode(&data,saved,64));gSpiTransmitReady=false;
    assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    assert(gMasterDrainInfo.data_head_polls[1]==1 && gMasterDrainInfo.data_empty_polls[1]==1);
    /* Equal object identifiers on distinct nodes/classes are independent.
     * Exercise index 25 and the maximum 13-record batch without aliasing masks. */
    gService.receptions[1].count=13;gService.receptions[1].cls=1;
    assert(bodaqs_fragment_seal(&gService.receptions[1].object,gService.receptions[1].bytes,1024,461,5,1,1,1,1004));
    data.node=1;data.body[0]=1;data.object=5;data.index=25;
    assert(bodaqs_measurement_encode(&data,saved,64));gSpiTransmitReady=false;
    assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    assert(gMasterDrainInfo.data_objects[0]==2 && gMasterDrainInfo.data_records[0]==16);
    assert(gMasterDrainInfo.data_batch_records[0][13]==1 && gMasterDrainInfo.data_unique_fragments[0]==4);
    gService.receptions[0].count=1;gService.receptions[0].cls=2;
    assert(bodaqs_fragment_seal(&gService.receptions[0].object,gService.receptions[0].bytes,1024,461,5,0,2,1,92));
    data.node=0;data.body[0]=2;data.object=0;data.index=0;
    assert(bodaqs_measurement_encode(&data,saved,64));gSpiTransmitReady=false;
    assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    assert(gMasterDrainInfo.data_objects[1]==1 && gMasterDrainInfo.data_records[1]==1);
    assert(gMasterDrainInfo.data_batch_records[1][1]==1 && gMasterDrainInfo.data_unique_fragments[1]==1);
    bodaqs_fragment_ack(&gService.receptions[0].object,1,&data);
    data.body[4]^=1; /* Rejected checksum is not an actual retirement. */
    assert(bodaqs_measurement_encode(&data,saved,64));gSpiTransmitReady=false;
    assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    assert(!gMasterDrainInfo.data_acked_objects[1]);
    data.body[4]^=1;
    assert(bodaqs_measurement_encode(&data,saved,64));gSpiTransmitReady=false;
    assert(bodaqs_record_queue_push(&gSpiReceiveQueue,saved));service_spi_receive();
    assert(gMasterDrainInfo.data_acked_objects[1]==1 && gMasterDrainInfo.data_acked_records[1]==1);
    ++gService.ingress[0].dropped;drain_check();
    memcpy(&frozen,(const void *)&gMasterDrainInfo,sizeof frozen);
    drain_transfer(saved,64,gTransmitSlots[gTransmitIndex^1U],0,3);
    assert(memcmp(&frozen,(const void *)&gMasterDrainInfo,sizeof frozen)==0);
    gService.measurement.mode.context=462;gService.ingress[0].dropped=0;drain_check();
    assert(gMasterDrainInfo.state==1 && !gMasterDrainInfo.data_objects[0] &&
        !gMasterDrainInfo.data_fragment_mask[0][0] && !gMasterDrainInfo.data_acked_objects[0]);
    puts("prepared data uniqueness, batch sizes, actual ACK retirement and scope reset: PASS");
    return 0;
}
