#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "bodaqs_record_queue.h"
#include "bodaqs_measurement.h"
#include "bodaqs_can_network.h"
#include "bodaqs_master_service.h"
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
static struct {unsigned can_malformed_frames,can_rx_frames;} gMasterRuntimeInfo;
static DL_MCAN_RxBufElement hardware;
static unsigned hardware_depth;
static void DL_MCAN_getRxFIFOStatus(int dev,DL_MCAN_RxFIFOStatus *f) {(void)dev;f->fillLvl=hardware_depth;f->getIdx=0;}
static void DL_MCAN_readMsgRam(int d,int type,int index,unsigned num,DL_MCAN_RxBufElement *m) {(void)d;(void)type;(void)index;(void)num;*m=hardware;}
static void DL_MCAN_writeRxFIFOAck(int d,unsigned num,unsigned idx) {(void)d;(void)num;(void)idx;--hardware_depth;}
static uint32_t bodaqs_master_timing_clock(void *c,uint32_t *epoch) {(void)c;*epoch=1;return 12345;}
#define DMA 0
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
static unsigned remaining=20,cs_high=1,spi_busy,disabled,reset_count,arm_count;
static uint32_t __get_PRIMASK(void) {return 0;}
static void __disable_irq(void) {}
static void __DMB(void) {}
static void __set_PRIMASK(uint32_t p) {(void)p;}
static unsigned DL_DMA_getTransferSize(int d,int c) {(void)d;(void)c;return remaining;}
static unsigned DL_GPIO_readPins(int p,int m) {(void)p;(void)m;return cs_high;}
static bool DL_SPI_isBusy(int d) {(void)d;return spi_busy;}
static void DL_DMA_disableChannel(int d,int c) {(void)d;disabled|=1U<<c;}
static unsigned DL_SPI_drainRXFIFO8(int d,uint8_t *p,unsigned n) {(void)d;(void)p;(void)n;return 0;}
static void DL_SPI_disable(int d) {(void)d;}
static void DL_SPI_reset(int d) {(void)d;assert(disabled==3);++reset_count;}
static void DL_SPI_enablePower(int d) {(void)d;}
static void delay_cycles(int d) {(void)d;}
static void SYSCFG_DL_SPI_A8_init(void) {}
static int DL_SPI_getPendingInterrupt(int d) {(void)d;return 0;}
static void arm_spi_slot(void) {assert(reset_count);disabled=0;++arm_count;}
static void injected_cs_preemption(void);
/* PRODUCTION_FUNCTIONS */
static void injected_cs_preemption(void) {retire_spi_boundary();}
int main(void) {
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
    cs_high=1;spi_busy=1;retire_spi_boundary();
    assert(gSpiRetirementProof.generation==0); /* peripheral still shifting */
    spi_busy=0;
    BodaqsMeasurementSlot data={0};data.kind=2;data.context=77;data.node=0;
    assert(bodaqs_measurement_encode(&data,gTransmitSlots[0],64));
    assert(bodaqs_measurement_encode(&data,gTransmitSlots[1],64));
    gSpiTransmitReady=true;
    retire_spi_boundary();
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
    return 0;
}
