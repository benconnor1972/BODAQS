#include "master_timing.h"
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "bodaqs_can_network.h"
#include "bodaqs_record_queue.h"
#include "bodaqs_master_service.h"
#include "bodaqs_master_profile.h"
#include "bodaqs_node_inventory.h"
#include "master_identity.h"
#include "ti_msp_dl_config.h"
#include "bodaqs_can_link_ti.h"

#define NODE_STALE_AFTER_MS (3000U)
#define DISCOVERY_INTERVAL_MS (5000U)
#define CAN_RECOVERY_DELAY_MS (1000U)
#ifndef BODAQS_ENABLE_BUCK
#define BODAQS_ENABLE_BUCK (1)
#endif
#ifndef BODAQS_ENABLE_FRONT_BRANCH
#define BODAQS_ENABLE_FRONT_BRANCH (1)
#endif
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
#if !defined(BODAQS_MASTER_PHASE_TIMING) || !BODAQS_MASTER_PHASE_TIMING || BODAQS_MEASUREMENT_VERSION != 2
#error "Queue timing requires v2 and phase timing"
#endif
#endif

typedef struct {
    uint32_t reset_cause;
    uint32_t can_link_profile;
    uint32_t uptime_ms;
    uint32_t slots_received;
    uint32_t probes_received;
    uint32_t status_requests_received;
    uint32_t inventory_requests_received;
    uint32_t malformed_slots;
    uint32_t spi_recoveries;
    uint32_t bad_magic_slots;
    uint32_t unsupported_version_slots;
    uint32_t invalid_length_slots;
    uint32_t bad_crc_slots;
    uint32_t invalid_argument_slots;
    uint32_t last_decode_result;
    uint32_t cs_release_timeouts;
    uint32_t spi_rx_dropped;
    uint16_t spi_rx_capacity;
    uint16_t spi_rx_high_water;
    uint32_t buck_gpio_doe31_0;
    uint32_t buck_gpio_dout31_0;
    uint32_t buck_gpio_din31_0;
    uint32_t can_rx_frames;
    uint32_t can_rx_dropped;
    uint32_t can_rx_hardware_losses;
    uint16_t can_rx_capacity;
    uint16_t can_rx_pending;
    uint16_t can_rx_pending_high_water;
    uint32_t can_tx_frames;
    uint32_t can_error_events;
    uint32_t can_bus_off_recovery_attempts;
    uint32_t can_bus_off_recoveries;
    uint32_t can_last_interrupts;
    uint32_t can_malformed_frames;
    uint32_t can_unsupported_version_frames;
    uint32_t can_unknown_frames;
    uint32_t can_address_mismatches;
    uint32_t discovery_requests_sent;
    uint32_t discovery_enqueue_failures;
    uint32_t last_can_decode_result;
    uint16_t can_rx_queue_depth;
    uint16_t can_rx_queue_high_water;
    uint16_t ingress_capacity[4], ingress_depth[4], ingress_high_water[4];
    uint32_t ingress_dropped[4];
    uint8_t nodes_present;
    uint8_t nodes_stale;
    uint8_t nodes_duplicate;
    bool can_initialized;
    bool can_bus_off;
    bool clock_fault;
    bool buck_build_enabled;
    bool buck_output_enabled;
    bool buck_output_latch_high;
    bool buck_pin_high;
    bool buck_driverlib_read_high;
    bool front_power_fault;
    bool rear_power_fault;
} MasterRuntimeInfo;

/* Active drain diagnostic state. */
/* Main-loop writer only; debugger observation, never protocol/authority state.
 * Scope begins when START is admitted to the CAN control exchange, not when
 * the node physically starts. Freeze after the first observed retention loss
 * (including sample-only loss), STOP admission or identity change. */
typedef struct {
    uint32_t version, state, finish_reason; /* 0 idle, 1 active, 2 frozen; reasons 1 loss, 2 STOP, 3 identity */
    uint64_t context, recording;
    uint32_t started_tick, elapsed_us, clock_epoch, timing_invalid;
    uint32_t nodes_seen;
    uint32_t spi_dropped_base, can_dropped_base, can_hardware_base, retained_base;
    uint32_t spi_dropped, can_dropped, can_hardware_losses, retained_frames;
    uint32_t polls[5], acks[5], fragments[5], empty_replies, malformed_slots;
    uint32_t ingress_dropped_base[4], ingress_dropped[4];
    uint16_t ingress_depth[4], ingress_sampled_high_water[4], can_queue_sampled_high_water;
    /* Lanes: update_service_status, process_transfer, CAN work from its first
     * copied loss/record through bounded drain completion (excludes first pop).
     * Histograms: <=50, <=100, <=250, <=1000, >1000 us; IRQ time included. */
    uint32_t calls[3], max_us[3], histogram[3][5];
    uint64_t total_us[3];
    /* Version 2: prepared replies, NOT physical MISO delivery or logger receipt.
     * Data lanes: sample, evidence. Batch sizes count CAN records, not samples.
     * Batch histogram index is the record count (1..13; index 0 is unused). */
    uint32_t data_objects[2], data_records[2], data_unique_fragments[2], data_repeat_fragments[2];
    uint32_t data_acked_objects[2], data_acked_records[2], data_head_polls[2], data_empty_polls[2];
    uint32_t data_batch_records[2][14];
    /* Main-owned bookkeeping, reset with the START scope. */
    uint32_t data_last_object[2][4], data_fragment_mask[2][4];
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
    /* Version3, successful measurement requests only. Rows: ACK_FETCH (any
     * reply), other empty, other data fragment, other reply. Columns:
     * physical decode/validation, dispatch plus hints, physical encode. */
    uint32_t phase_calls[4], phase_max_us[4][3];
    uint64_t phase_total_us[4][3];
#endif
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
    /* Version4: boundary enqueue observation -> main pop (before wire decode).
     * Valid current-context measurement slots enqueued within this START scope
     * only. Histogram <=250, <=500, <=1000, <=2000, <=4000, >4000 us.
     * Depth histogram counts depth BEFORE pop (1..4); index0 unused.
     * Instantaneous depth/head age are sampled at drain_check, including freeze.
     * No queue clearing, readiness or ownership decision uses these fields. */
    uint32_t spi_queue_wait_count, spi_queue_wait_excluded, spi_queue_time_invalid;
    uint32_t spi_queue_wait_max_us, spi_queue_wait_hist[6], spi_queue_depth_hist[5];
    uint32_t spi_queue_depth, spi_queue_peak, spi_queue_head_age_us, spi_queue_head_valid;
    uint64_t spi_queue_wait_total_us;
#endif
#if BODAQS_MEASUREMENT_VERSION == 2
    /* Version5: processed ACK_FETCH requests by predecessor ACK class and
     * successor fetch class. acks[] remains separate-ACK-only. Retirement
     * counters credit a new object once, never a cached proof replay. */
    uint32_t ack_fetches[5], ack_fetch_targets[5];
    uint32_t layout_flags, size_bytes; /* bit0 phase timing, bit1 queue timing */
#endif
} MasterDrainInfo;
volatile MasterDrainInfo gMasterDrainInfo;
/* End drain diagnostic state. */

/* Snapshot at most the configured hardware FIFO depth per interrupt. */
#define CAN_RX_CAPACITY (8U)
typedef struct {
    DL_MCAN_RxBufElement message;
    uint32_t received_ms, received_tick;
    uint8_t received_flags;
    uint64_t ordinal;
} CanReceiveRecord;
static uint64_t gCanReceiveOrdinal;
static CanReceiveRecord gCanReceiveStorage[CAN_RX_CAPACITY];
static BodaqsRecordQueue gCanReceiveQueue;
/* ISR-only accumulation; main copies/clears under a short IRQ fence. No
 * selected reception or service-owned definition is edited in the ISR. */
typedef struct {
    uint32_t source,evidence,tick;
    uint64_t ordinal;
    uint16_t first,last;
    uint8_t epoch;
    bool essential;
} RejectedCan;
static RejectedCan gRejectedCan[4];
static volatile bool gHealthDue;

/* Queue metadata and record copies are serialized; decoding never masks IRQs. */
static bool take_record(BodaqsRecordQueue *queue, void *record)
{
    uint32_t primask = __get_PRIMASK();
    bool available;
    __disable_irq();
    available = bodaqs_record_queue_pop(queue, record);
    __set_PRIMASK(primask);
    return available;
}

volatile MasterRuntimeInfo gMasterRuntimeInfo;
BodaqsNodeInventory gNodeInventory;

static BodaqsMasterService gService;
static BodaqsMasterDiscoveryRecord
    gDiscoveryRecords[BODAQS_MASTER_DISCOVERY_NODE_COUNT];
/* SPI adapter ownership storage. */
#if BODAQS_MEASUREMENT_VERSION == 2
#ifndef BODAQS_MASTER_SPI_RX_CAPACITY
#define BODAQS_MASTER_SPI_RX_CAPACITY 4U
#endif
#if BODAQS_MASTER_SPI_RX_CAPACITY != 2 && BODAQS_MASTER_SPI_RX_CAPACITY != 4
#error "V2 SPI RX capacity must be 2 or 4"
#endif
#define BODAQS_SPI_BUFFER_STORAGE __attribute__((section(".bodaqs_spi_buffers"),aligned(4)))
#else
#ifndef BODAQS_MASTER_SPI_RX_CAPACITY
#define BODAQS_MASTER_SPI_RX_CAPACITY 1U
#endif
#if BODAQS_MASTER_SPI_RX_CAPACITY != 1
#error "Legacy SPI RX capacity must remain 1"
#endif
#define BODAQS_SPI_BUFFER_STORAGE
#endif
static uint8_t gTransmitSlots[2][BODAQS_MASTER_TRANSFER_BYTES] BODAQS_SPI_BUFFER_STORAGE;
static uint8_t gReceiveSlots[2][BODAQS_MASTER_TRANSFER_BYTES] BODAQS_SPI_BUFFER_STORAGE;
static uint8_t gTransmitIndex;
static uint8_t gReceiveIndex;
/* Each queued physical transaction owns its exact extent until the main pop. */
static uint8_t gSpiReceiveStorage[BODAQS_MASTER_SPI_RX_CAPACITY][BODAQS_MASTER_TRANSFER_BYTES] BODAQS_SPI_BUFFER_STORAGE;
static uint16_t gSpiReceiveLengths[BODAQS_MASTER_SPI_RX_CAPACITY];
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
/* Same ownership and cell lifetime as lengths: ISR writes before queue push;
 * main copies metadata and payload together under the existing pop IRQ fence.
 * The ISR never reads or writes the main-owned drain snapshot. */
typedef struct { uint32_t tick, epoch; } SpiReceiveTiming;
static SpiReceiveTiming gSpiReceiveTiming[BODAQS_MASTER_SPI_RX_CAPACITY] BODAQS_SPI_BUFFER_STORAGE;
#endif
static BodaqsRecordQueue gSpiReceiveQueue;
/* Main publishes requests and consumes proof under a short IRQ fence. Only
 * the ISR adapter touches hardware; it never mutates the protocol service. */
typedef struct { uint32_t generation; uint64_t context; } SpiRetirement;
static volatile SpiRetirement gSpiRetirementRequest, gSpiRetirementProof;
static volatile bool gSpiRetiring;
static volatile bool gSpiTransmitReady;
/* End SPI adapter ownership storage. */
static volatile uint32_t gUptimeMs;
static volatile bool gDiscoveryDue;
static uint16_t gDiscoveryTransaction;
static uint32_t gDiscoveryNonce;
static volatile bool gCanRecoveryDue;
static volatile uint32_t gCanRecoveryDueMs;
static bool gCanWasBusOff;
static bool gCanLinkReady;
static bool gLoggerCommunicationEstablished;

static uint32_t drain_clock(void)
{
    uint32_t epoch;
    uint32_t tick=bodaqs_master_timing_clock(NULL,&epoch);
    if(gMasterDrainInfo.state==1 && (!epoch || epoch!=gMasterDrainInfo.clock_epoch))
        gMasterDrainInfo.timing_invalid=1;
    return tick;
}

#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
static void drain_queue_sample(void)
{
    uint32_t tick=0,epoch=0,primask=__get_PRIMASK();
    SpiReceiveTiming received={0};
    uint16_t depth;
    __disable_irq();
    depth=gSpiReceiveQueue.depth;
    if(depth) {
        received=gSpiReceiveTiming[gSpiReceiveQueue.head];
        tick=bodaqs_master_timing_clock(NULL,&epoch);
    }
    __set_PRIMASK(primask);
    gMasterDrainInfo.spi_queue_depth=depth;
    if(depth>gMasterDrainInfo.spi_queue_peak) gMasterDrainInfo.spi_queue_peak=depth;
    gMasterDrainInfo.spi_queue_head_age_us=0;
    gMasterDrainInfo.spi_queue_head_valid=0;
    if(!depth) return;
    if(!epoch || received.epoch!=epoch || epoch!=gMasterDrainInfo.clock_epoch) {
        gMasterDrainInfo.timing_invalid=1;return;
    }
    /* For the bounded diagnostic run (<one low32 clock period), this also
     * excludes cells enqueued before START, including across low32 wrap. */
    const uint32_t age=tick-received.tick;
    if(age>tick-gMasterDrainInfo.started_tick) return;
    gMasterDrainInfo.spi_queue_head_age_us=age;
    gMasterDrainInfo.spi_queue_head_valid=1;
}

static void drain_queue_record(const uint8_t *request,size_t length,
    SpiReceiveTiming received,uint32_t tick,uint32_t epoch,uint16_t depth,bool scoped)
{
    uint32_t age;
    unsigned bucket;
    if(gMasterDrainInfo.state!=1 || length!=BODAQS_MEASUREMENT_BYTES) return;
    if(!scoped || bodaqs_measurement_get(request+4,8)!=gMasterDrainInfo.context) {
        ++gMasterDrainInfo.spi_queue_wait_excluded;return;
    }
    if(!epoch || received.epoch!=epoch || epoch!=gMasterDrainInfo.clock_epoch) {
        ++gMasterDrainInfo.spi_queue_time_invalid;gMasterDrainInfo.timing_invalid=1;return;
    }
    age=tick-received.tick;
    if(age>tick-gMasterDrainInfo.started_tick) {
        ++gMasterDrainInfo.spi_queue_wait_excluded;return;
    }
    bucket=age<=250?0:age<=500?1:age<=1000?2:age<=2000?3:age<=4000?4:5;
    ++gMasterDrainInfo.spi_queue_wait_count;
    gMasterDrainInfo.spi_queue_wait_total_us+=age;
    if(age>gMasterDrainInfo.spi_queue_wait_max_us) gMasterDrainInfo.spi_queue_wait_max_us=age;
    ++gMasterDrainInfo.spi_queue_wait_hist[bucket];
    if(depth>0 && depth<=BODAQS_MASTER_SPI_RX_CAPACITY) ++gMasterDrainInfo.spi_queue_depth_hist[depth];
    if(depth>gMasterDrainInfo.spi_queue_peak) gMasterDrainInfo.spi_queue_peak=depth;
}
#endif

#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
uint32_t bodaqs_master_profile_clock(void)
{
    return gMasterDrainInfo.state==1 ? drain_clock() : 0;
}

void bodaqs_master_profile_record(uint32_t decode_us,uint32_t dispatch_us,
    uint32_t encode_us,uint8_t request_kind,uint8_t reply_kind)
{
    unsigned row,phase;
    const uint32_t durations[3]={decode_us,dispatch_us,encode_us};
    if(gMasterDrainInfo.state!=1) return;
    row=request_kind==14?0:reply_kind==0?1:bodaqs_fragment_class(reply_kind)?2:3;
    ++gMasterDrainInfo.phase_calls[row];
    for(phase=0;phase<3;++phase) {
        gMasterDrainInfo.phase_total_us[row][phase]+=durations[phase];
        if(durations[phase]>gMasterDrainInfo.phase_max_us[row][phase])
            gMasterDrainInfo.phase_max_us[row][phase]=durations[phase];
    }
}
#endif

static void drain_cost(unsigned lane,uint32_t started)
{
    uint32_t duration;
    unsigned bucket;
    if(gMasterDrainInfo.state!=1) return;
    duration=drain_clock()-started;
    bucket=duration<=50?0:duration<=100?1:duration<=250?2:duration<=1000?3:4;
    ++gMasterDrainInfo.calls[lane];
    gMasterDrainInfo.total_us[lane]+=duration;
    if(duration>gMasterDrainInfo.max_us[lane]) gMasterDrainInfo.max_us[lane]=duration;
    ++gMasterDrainInfo.histogram[lane][bucket];
}

static void drain_check(void)
{
    unsigned node;
    uint32_t reason=0,epoch;
    const uint64_t context=gService.measurement.mode.context;
    const uint64_t recording=gService.measurement.mode.recording;
    if(gMasterDrainInfo.state==1 &&
       (gMasterDrainInfo.context!=context || gMasterDrainInfo.recording!=recording)) {
        /* New-context counters may have reset: never subtract old baselines. */
        gMasterDrainInfo.finish_reason=3;__DMB();gMasterDrainInfo.state=2;return;
    }
    if(gMasterDrainInfo.state!=1) {
        if(!gService.acquisition_started || (gMasterDrainInfo.state==2 &&
           gMasterDrainInfo.context==context && gMasterDrainInfo.recording==recording)) return;
        memset((void *)&gMasterDrainInfo,0,sizeof gMasterDrainInfo);
        gMasterDrainInfo.version=2;
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
        gMasterDrainInfo.version=3;
#endif
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
        gMasterDrainInfo.version=4;
#endif
#if BODAQS_MEASUREMENT_VERSION == 2
        gMasterDrainInfo.version=5;
    gMasterDrainInfo.size_bytes=sizeof(gMasterDrainInfo);
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
    gMasterDrainInfo.layout_flags|=1;
#endif
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
    gMasterDrainInfo.layout_flags|=2;
#endif
#endif
        gMasterDrainInfo.context=context;gMasterDrainInfo.recording=recording;
        gMasterDrainInfo.started_tick=bodaqs_master_timing_clock(NULL,&epoch);
        gMasterDrainInfo.clock_epoch=epoch;
        gMasterDrainInfo.timing_invalid=!gMasterDrainInfo.clock_epoch;
        gMasterDrainInfo.spi_dropped_base=gSpiReceiveQueue.dropped;
        gMasterDrainInfo.can_dropped_base=gCanReceiveQueue.dropped;
        gMasterDrainInfo.can_hardware_base=gMasterRuntimeInfo.can_rx_hardware_losses;
        gMasterDrainInfo.retained_base=gService.retained_frames;
        for(node=0;node<4;++node) gMasterDrainInfo.ingress_dropped_base[node]=gService.ingress[node].dropped;
        gMasterDrainInfo.state=1;
    }
    gMasterDrainInfo.elapsed_us=drain_clock()-gMasterDrainInfo.started_tick;
    gMasterDrainInfo.nodes_seen|=gService.acquisition_started;
    gMasterDrainInfo.spi_dropped=gSpiReceiveQueue.dropped-gMasterDrainInfo.spi_dropped_base;
    gMasterDrainInfo.can_dropped=gCanReceiveQueue.dropped-gMasterDrainInfo.can_dropped_base;
    gMasterDrainInfo.can_hardware_losses=gMasterRuntimeInfo.can_rx_hardware_losses-gMasterDrainInfo.can_hardware_base;
    gMasterDrainInfo.retained_frames=gService.retained_frames-gMasterDrainInfo.retained_base;
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
    drain_queue_sample();
#endif
    if(gCanReceiveQueue.depth>gMasterDrainInfo.can_queue_sampled_high_water)
        gMasterDrainInfo.can_queue_sampled_high_water=gCanReceiveQueue.depth;
    for(node=0;node<4;++node) {
        gMasterDrainInfo.ingress_depth[node]=gService.ingress[node].count;
        if(gService.ingress[node].count>gMasterDrainInfo.ingress_sampled_high_water[node])
            gMasterDrainInfo.ingress_sampled_high_water[node]=gService.ingress[node].count;
        gMasterDrainInfo.ingress_dropped[node]=gService.ingress[node].dropped-gMasterDrainInfo.ingress_dropped_base[node];
        if(gMasterDrainInfo.ingress_dropped[node]) reason=1;
    }
    if(!reason && !gService.acquisition_started) reason=2;
    if(reason) {gMasterDrainInfo.finish_reason=reason;__DMB();gMasterDrainInfo.state=2;}
}

static const uint32_t gCanErrorInterruptMask =
    DL_MCAN_INTERRUPT_ARA |
    DL_MCAN_INTERRUPT_PED |
    DL_MCAN_INTERRUPT_PEA |
    DL_MCAN_INTERRUPT_WDI |
    DL_MCAN_INTERRUPT_BO |
    DL_MCAN_INTERRUPT_EW |
    DL_MCAN_INTERRUPT_EP |
    DL_MCAN_INTERRUPT_ELO |
    DL_MCAN_INTERRUPT_BEU |
    DL_MCAN_INTERRUPT_MRAF |
    DL_MCAN_INTERRUPT_RF0L;

static bool time_reached(uint32_t now, uint32_t deadline)
{
    return (int32_t) (now - deadline) >= 0;
}

static void update_can_state(void)
{
    DL_MCAN_ProtocolStatus protocol_status = {0};
    uint32_t clock_status = DL_SYSCTL_getClockStatus();

    gMasterRuntimeInfo.can_initialized = gCanLinkReady &&
        DL_MCAN_isMemInitDone(MCAN0_INST) &&
        (DL_MCAN_getOpMode(MCAN0_INST) == DL_MCAN_OPERATION_MODE_NORMAL);
    DL_MCAN_getProtocolStatus(MCAN0_INST, &protocol_status);
    gMasterRuntimeInfo.can_bus_off = protocol_status.busOffStatus != 0U;
    if (gMasterRuntimeInfo.can_bus_off && !gCanWasBusOff) {
        gCanRecoveryDueMs = gUptimeMs + CAN_RECOVERY_DELAY_MS;
        gCanRecoveryDue = true;
    } else if (!gMasterRuntimeInfo.can_bus_off && gCanWasBusOff) {
        ++gMasterRuntimeInfo.can_bus_off_recoveries;
    }
    gCanWasBusOff = gMasterRuntimeInfo.can_bus_off;
    gMasterRuntimeInfo.clock_fault =
        (clock_status & (DL_SYSCTL_CLK_STATUS_HFCLK_GOOD |
            DL_SYSCTL_CLK_STATUS_SYSPLL_GOOD)) !=
        (DL_SYSCTL_CLK_STATUS_HFCLK_GOOD |
            DL_SYSCTL_CLK_STATUS_SYSPLL_GOOD);
}

static uint16_t can_standard_identifier(const DL_MCAN_RxBufElement *message)
{
    return (uint16_t) ((message->id >> 18U) & 0x7FFU);
}

static void note_can_decode_result(BodaqsCanDecodeResult result)
{
    gMasterRuntimeInfo.last_can_decode_result = (uint32_t) result;
    if (result == BODAQS_CAN_DECODE_UNSUPPORTED_VERSION) {
        ++gMasterRuntimeInfo.can_unsupported_version_frames;
    } else if (result != BODAQS_CAN_DECODE_OK) {
        ++gMasterRuntimeInfo.can_malformed_frames;
    }
}

static void process_can_message(
    const DL_MCAN_RxBufElement *message, uint32_t received_ms, uint32_t received_tick, uint64_t ordinal, uint8_t received_flags)
{
    uint16_t identifier;
    size_t length;
    uint8_t node_address;

    if ((message->xtd != 0U) || (message->rtr != 0U) ||
        (message->fdf == 0U) || (message->brs == 0U)) {
        ++gMasterRuntimeInfo.can_malformed_frames;
        return;
    }
    length = bodaqs_can_dlc_to_length((uint8_t) message->dlc);
    if (length == 0U) {
        ++gMasterRuntimeInfo.can_malformed_frames;
        return;
    }
    identifier = can_standard_identifier(message);

    if (bodaqs_can_identifier_node(identifier, BODAQS_CAN_ID_RESPONSE_BASE, &node_address)) {
        BodaqsControlRecord reply;
        uint16_t transaction;
        if (bodaqs_control_decode_can(message->data, length, true, &transaction, &reply)) {
            (void)bodaqs_master_service_control_receive(&gService, node_address, transaction, &reply);
        } else {
            ++gMasterRuntimeInfo.can_malformed_frames;
        }
        return;
    }

    if (bodaqs_can_identifier_node(identifier,
            BODAQS_CAN_ID_ANNOUNCE_BASE, &node_address)) {
        BodaqsCanNodeAnnounce announce;
        BodaqsCanDecodeResult result = bodaqs_can_decode_node_announce(
            message->data, length, &announce);
        note_can_decode_result(result);
        if (result != BODAQS_CAN_DECODE_OK) {
            return;
        }
        if (announce.node_address != node_address) {
            ++gMasterRuntimeInfo.can_address_mismatches;
            return;
        }
        (void) bodaqs_node_inventory_observe_announce(
            &gNodeInventory, &announce, received_ms);
        return;
    }

    if (bodaqs_can_identifier_node(identifier,
            BODAQS_CAN_ID_STATUS_BASE, &node_address)) {
        BodaqsCanNodeStatus status;
        uint16_t transaction;
        BodaqsCanDecodeResult result = bodaqs_can_decode_node_status(
            message->data, length, &transaction, &status);
        (void) transaction;
        note_can_decode_result(result);
        if (result == BODAQS_CAN_DECODE_OK) {
            (void) bodaqs_node_inventory_observe_status(
                &gNodeInventory, node_address, &status, received_ms);
        }
        return;
    }

    /* Forward compact receptions only from current discovered identities.
     * Stream data is gated on a same-boot/epoch anchor below. */
    if(identifier>=BODAQS_CAN_ID_STREAM_BASE && identifier<BODAQS_CAN_ID_STREAM_BASE+32) {
        node_address=(uint8_t)((identifier-BODAQS_CAN_ID_STREAM_BASE)/8);
        (void)bodaqs_master_service_receive_can_ordered(&gService,node_address,1,identifier,
            message->data,(uint8_t)length,received_flags,received_tick,ordinal,gUptimeMs);
        return;
    }
    if(bodaqs_can_identifier_node(identifier,BODAQS_CAN_ID_TIMING_BASE,&node_address) ||
       bodaqs_can_identifier_node(identifier,BODAQS_CAN_ID_EVENT_BASE,&node_address)) {
        (void)bodaqs_master_service_receive_can_ordered(&gService,node_address,2,identifier,
            message->data,(uint8_t)length,received_flags,received_tick,ordinal,gUptimeMs);
        return;
    }
    ++gMasterRuntimeInfo.can_unknown_frames;
}

static void capture_can_receive_fifo(void)
{
    CanReceiveRecord record;
    DL_MCAN_RxFIFOStatus fifo_status = {0};
    uint32_t remaining;

    fifo_status.num = DL_MCAN_RX_FIFO_NUM_0;
    DL_MCAN_getRxFIFOStatus(MCAN0_INST, &fifo_status);
    remaining = fifo_status.fillLvl;
    if (remaining > CAN_RX_CAPACITY) {
        remaining = CAN_RX_CAPACITY;
    }
    while (remaining-- != 0U) {
        DL_MCAN_readMsgRam(MCAN0_INST, DL_MCAN_MEM_TYPE_FIFO, 0U,
            fifo_status.num, &record.message);
        record.received_ms = gUptimeMs;
        uint32_t clock_epoch;
        record.received_tick = bodaqs_master_timing_clock(NULL,&clock_epoch);
        record.received_flags=clock_epoch?0:1;
        if(!clock_epoch) record.received_tick=0;
        /* ISR capture order includes frames later rejected or dropped by queues. */
        if(gCanReceiveOrdinal==UINT64_MAX) {
            ++gMasterRuntimeInfo.can_malformed_frames;
            record.ordinal=0; /* Fail closed while still retiring the hardware FIFO. */
        } else record.ordinal=++gCanReceiveOrdinal;
        DL_MCAN_writeRxFIFOAck(
            MCAN0_INST, fifo_status.num, fifo_status.getIdx);
        ++gMasterRuntimeInfo.can_rx_frames;
        if(!bodaqs_record_queue_push(&gCanReceiveQueue, &record) && !record.message.xtd &&
           !record.message.rtr && record.message.fdf) {
            uint16_t id=can_standard_identifier(&record.message);
            bool sample=id>=0x100 && id<=0x118 && !(id&7);
            bool evidence=id>=0x90 && id<=0x93;
            uint8_t node=sample?(uint8_t)((id-0x100)/8):(uint8_t)(id-0x90);
            if(sample || evidence) {
                RejectedCan *r=&gRejectedCan[node];
                uint8_t *p=record.message.data;
                size_t length=bodaqs_can_dlc_to_length((uint8_t)record.message.dlc);
                uint8_t epoch=sample&&length>=4?p[2]:!sample&&length>=14?p[13]:0;
#if BODAQS_MEASUREMENT_VERSION == 2
                if(!sample) epoch=length>=14 && (p[1]==0x23 || p[1]==0x24 || p[1]==0x25)?p[13]:
                    length>=14 && p[1]==0x22?p[10]:0;
                if(epoch && r->epoch && (r->source || r->evidence) && r->epoch!=epoch) r->essential=true;
                if(epoch) r->epoch=epoch;
#else
                if((r->source || r->evidence) && r->epoch!=epoch) r->essential=true;
                r->epoch=epoch;
#endif
                r->tick=record.received_tick;r->ordinal=record.ordinal;
                if(sample) {
                    uint32_t n=p[3]&7;
                    if(!n || n>5 || length<4+12*n || UINT32_MAX-r->source<n) r->essential=true;
                    else {
                        if(!r->source) r->first=(uint16_t)bodaqs_measurement_get(p,2);
                        r->last=(uint16_t)(bodaqs_measurement_get(p,2)+n-1);
                        r->source+=n;
                    }
                } else {
                    if(r->evidence==UINT32_MAX) r->essential=true; else ++r->evidence;
#if BODAQS_MEASUREMENT_VERSION == 2
                    const bool optional=(p[1]==0x21 && length==24) || (p[1]==0x22 && length==32) ||
                        ((p[1]==0x23 || p[1]==0x24) && length==64);
                    if(!optional) r->essential=true;
#else
                    if(length!=64 || p[1]!=0x23) r->essential=true;
#endif
                }
            }
        }
        DL_MCAN_getRxFIFOStatus(MCAN0_INST, &fifo_status);
    }
}

/* Retire a bounded CAN batch before the next main-loop turn. A single pop
 * leaves a nearly full capture queue vulnerable to the next metadata burst.
 * The fixed budget still returns to SPI/control if an ISR refills the queue. */
static void service_can_receive(void)
{
    CanReceiveRecord record;
    unsigned node;
    unsigned remaining = CAN_RX_CAPACITY;
    bool timed=false;
    uint32_t started=0;
    bool losses=false;
    if(gMasterDrainInfo.state==1 && gCanReceiveQueue.depth>gMasterDrainInfo.can_queue_sampled_high_water)
        gMasterDrainInfo.can_queue_sampled_high_water=gCanReceiveQueue.depth;
    for(node=0;node<4;++node) {
        RejectedCan lost;
        uint32_t primask=__get_PRIMASK();
        __disable_irq();lost=gRejectedCan[node];memset(&gRejectedCan[node],0,sizeof lost);__set_PRIMASK(primask);
        if(lost.source || lost.evidence || lost.essential) {
            losses=true;
            if(!timed && gMasterDrainInfo.state==1) {started=drain_clock();timed=true;}
            bodaqs_master_service_loss_counts(&gService,(uint8_t)node,5,lost.epoch,
                lost.first,lost.last,lost.source,lost.evidence,lost.essential,lost.tick,lost.ordinal);
        }
    }
    while (remaining-- != 0U && take_record(&gCanReceiveQueue, &record)) {
        /* An ISR can enqueue after an initially empty depth observation. */
        if(!timed && gMasterDrainInfo.state==1) {started=drain_clock();timed=true;}
        process_can_message(&record.message, record.received_ms, record.received_tick, record.ordinal, record.received_flags);
    }
    if(timed) drain_cost(2,started);
    if(timed || losses) drain_check();
}

static bool send_can_frame(
    uint16_t identifier, const uint8_t *payload, size_t length)
{
    if (!gCanLinkReady) return false;
    DL_MCAN_TxBufElement message = {0};
    DL_MCAN_TxFIFOStatus fifo_status = {0};
    uint8_t dlc = bodaqs_can_length_to_dlc(length);

    if ((payload == NULL) || (dlc == UINT8_MAX) || (identifier > 0x7FFU)) {
        return false;
    }
    DL_MCAN_getTxFIFOQueStatus(MCAN0_INST, &fifo_status);
    if (fifo_status.fifoFull != 0U) {
        return false;
    }
    if (DL_MCAN_TXBufTransIntrEnable(
            MCAN0_INST, fifo_status.putIdx, true) != 0) {
        return false;
    }

    message.id = (uint32_t) identifier << 18U;
    message.rtr = 0U;
    message.xtd = 0U;
    message.esi = 0U;
    message.dlc = dlc;
    message.brs = 1U;
    message.fdf = 1U;
    message.efc = 0U;
    message.mm = (uint8_t) gDiscoveryTransaction;
    memcpy(message.data, payload, length);
    DL_MCAN_writeMsgRam(
        MCAN0_INST, DL_MCAN_MEM_TYPE_FIFO, 0U, &message);
    return DL_MCAN_TXBufAddReq(MCAN0_INST, fifo_status.putIdx) == 0;
}

static void send_discovery_request(void)
{
    BodaqsCanDiscoveryRequest request = {0};
    uint8_t payload[BODAQS_CAN_DISCOVERY_REQUEST_BYTES];

    ++gDiscoveryTransaction;
    gDiscoveryNonce = gDiscoveryNonce * UINT32_C(1664525) +
        UINT32_C(1013904223);
    request.transaction = gDiscoveryTransaction;
    request.nonce = gDiscoveryNonce;
    request.response_window_ms = BODAQS_CAN_DEFAULT_DISCOVERY_WINDOW_MS;
    if (!bodaqs_can_encode_discovery_request(
            &request, payload, sizeof(payload)) ||
        !send_can_frame(BODAQS_CAN_ID_BROADCAST_CONTROL,
            payload, sizeof(payload))) {
        ++gMasterRuntimeInfo.discovery_enqueue_failures;
        return;
    }
    ++gMasterRuntimeInfo.discovery_requests_sent;
}



static void normalize_retained_clocks(void)
{
    DL_SYSCTL_MCLK_SOURCE source = DL_SYSCTL_getMCLKSource();

    /*
     * HFXT and SYSPLL state can survive the lower-level reset used by a CCS
     * debug launch. Return MCLK to SYSOSC and wait for both retained sources
     * to stop before SysConfig enables and configures them again.
     */
    if (source == DL_SYSCTL_MCLK_SOURCE_HSCLK) {
        DL_SYSCTL_setMCLKSource(HSCLK, SYSOSC);
    } else if (source == DL_SYSCTL_MCLK_SOURCE_LFCLK) {
        DL_SYSCTL_setMCLKSource(LFCLK, SYSOSC);
    }

    DL_SYSCTL_disableSYSPLL();
    while ((DL_SYSCTL_getClockStatus() & DL_SYSCTL_CLK_STATUS_SYSPLL_OFF) ==
           0U) {
        ;
    }
    DL_SYSCTL_disableHFXT();
    while ((DL_SYSCTL_getClockStatus() & DL_SYSCTL_CLK_STATUS_HFCLK_OFF) ==
           0U) {
        ;
    }
}

static void arm_spi_slot(void)
{
    DL_DMA_setSrcAddr(DMA, DMA_SPI_TX_CHAN_ID,
        (uint32_t) &gTransmitSlots[gTransmitIndex][0]);
    DL_DMA_setDestAddr(DMA, DMA_SPI_TX_CHAN_ID,
        (uint32_t) &SPI_A8_INST->TXDATA);
    DL_DMA_setTransferSize(
        DMA, DMA_SPI_TX_CHAN_ID, BODAQS_MASTER_TRANSFER_BYTES);

    DL_DMA_setSrcAddr(DMA, DMA_SPI_RX_CHAN_ID,
        (uint32_t) &SPI_A8_INST->RXDATA);
    DL_DMA_setDestAddr(DMA, DMA_SPI_RX_CHAN_ID,
        (uint32_t) &gReceiveSlots[gReceiveIndex][0]);
    DL_DMA_setTransferSize(
        DMA, DMA_SPI_RX_CHAN_ID, BODAQS_MASTER_TRANSFER_BYTES);

    DL_DMA_enableChannel(DMA, DMA_SPI_RX_CHAN_ID);
    DL_DMA_enableChannel(DMA, DMA_SPI_TX_CHAN_ID);
}


static void update_runtime_info(void)
{
    uint8_t node;

    gMasterRuntimeInfo.can_rx_queue_depth = gCanReceiveQueue.depth;
    gMasterRuntimeInfo.can_rx_queue_high_water = gCanReceiveQueue.high_water;
    gMasterRuntimeInfo.uptime_ms = gUptimeMs;
    gMasterRuntimeInfo.slots_received = gService.slots_received;
    gMasterRuntimeInfo.probes_received = gService.probes_received;
    gMasterRuntimeInfo.status_requests_received =
        gService.status_requests_received;
    gMasterRuntimeInfo.inventory_requests_received =
        gService.discovery_requests_received;
    gMasterRuntimeInfo.malformed_slots = gService.malformed_slots;
    gMasterRuntimeInfo.bad_magic_slots = gService.bad_magic_slots;
    gMasterRuntimeInfo.unsupported_version_slots =
        gService.unsupported_version_slots;
    gMasterRuntimeInfo.invalid_length_slots = gService.invalid_length_slots;
    gMasterRuntimeInfo.bad_crc_slots = gService.bad_crc_slots;
    gMasterRuntimeInfo.invalid_argument_slots =
        gService.invalid_argument_slots;
    gMasterRuntimeInfo.last_decode_result =
        (uint32_t) gService.last_decode_result;
    gMasterRuntimeInfo.buck_gpio_doe31_0 = GPIO_BOARD_PORT->DOE31_0;
    gMasterRuntimeInfo.buck_gpio_dout31_0 = GPIO_BOARD_PORT->DOUT31_0;
    gMasterRuntimeInfo.buck_gpio_din31_0 = GPIO_BOARD_PORT->DIN31_0;
    gMasterRuntimeInfo.buck_build_enabled = BODAQS_ENABLE_BUCK != 0;
    gMasterRuntimeInfo.buck_output_enabled =
        (gMasterRuntimeInfo.buck_gpio_doe31_0 &
            GPIO_BOARD_BUCK_ENABLE_PIN) != 0U;
    gMasterRuntimeInfo.buck_output_latch_high =
        (gMasterRuntimeInfo.buck_gpio_dout31_0 &
            GPIO_BOARD_BUCK_ENABLE_PIN) != 0U;
    gMasterRuntimeInfo.buck_pin_high =
        (gMasterRuntimeInfo.buck_gpio_din31_0 &
            GPIO_BOARD_BUCK_ENABLE_PIN) != 0U;
    gMasterRuntimeInfo.buck_driverlib_read_high =
        DL_GPIO_readPins(GPIO_BOARD_PORT,
            GPIO_BOARD_BUCK_ENABLE_PIN) != 0U;
    gMasterRuntimeInfo.front_power_fault =
        (DL_GPIO_readPins(GPIO_BOARD_PORT, GPIO_BOARD_FRONT_FAULT_PIN) == 0U);
    gMasterRuntimeInfo.rear_power_fault =
        (DL_GPIO_readPins(GPIO_BOARD_PORT, GPIO_BOARD_REAR_FAULT_PIN) == 0U);
    gMasterRuntimeInfo.nodes_present = 0U;
    gMasterRuntimeInfo.nodes_stale = 0U;
    gMasterRuntimeInfo.nodes_duplicate = 0U;
    for (node = 0U; node < BODAQS_CAN_NODE_COUNT; ++node) {
        const BodaqsNodeInventoryEntry *entry = &gNodeInventory.nodes[node];
        gMasterRuntimeInfo.ingress_capacity[node]=BODAQS_MASTER_RETENTION_CAPACITY;
        gMasterRuntimeInfo.ingress_depth[node]=gService.ingress[node].count;
        gMasterRuntimeInfo.ingress_high_water[node]=gService.ingress[node].high_water;
        gMasterRuntimeInfo.ingress_dropped[node]=gService.ingress[node].dropped;
        if (entry->present) {
            ++gMasterRuntimeInfo.nodes_present;
        }
        if (entry->stale) {
            ++gMasterRuntimeInfo.nodes_stale;
        }
        if (entry->duplicate) {
            ++gMasterRuntimeInfo.nodes_duplicate;
        }
    }
    update_can_state();
}

static void update_service_status(void)
{
    BodaqsMasterStatus status = {0};
    uint32_t generation;
    uint32_t generation_after;
    uint8_t node;

    status.status_version = BODAQS_MASTER_STATUS_VERSION;
    status.uptime_ms = gUptimeMs;
    status.reset_cause = gMasterRuntimeInfo.reset_cause;
    status.spi_recoveries = gMasterRuntimeInfo.spi_recoveries;
    if (DL_GPIO_readPins(GPIO_BOARD_PORT, GPIO_BOARD_BUCK_ENABLE_PIN) != 0U) {
        status.flags |= BODAQS_MASTER_STATUS_FLAG_BUCK_ENABLED;
    }
    if (DL_GPIO_readPins(GPIO_BOARD_PORT, GPIO_BOARD_FRONT_ENABLE_PIN) != 0U) {
        status.flags |= BODAQS_MASTER_STATUS_FLAG_FRONT_ENABLED;
    }
    if (DL_GPIO_readPins(GPIO_BOARD_PORT, GPIO_BOARD_REAR_ENABLE_PIN) != 0U) {
        status.flags |= BODAQS_MASTER_STATUS_FLAG_REAR_ENABLED;
    }
    if (DL_GPIO_readPins(GPIO_BOARD_PORT, GPIO_BOARD_FRONT_FAULT_PIN) == 0U) {
        status.flags |= BODAQS_MASTER_STATUS_FLAG_FRONT_FAULT;
    }
    if (DL_GPIO_readPins(GPIO_BOARD_PORT, GPIO_BOARD_REAR_FAULT_PIN) == 0U) {
        status.flags |= BODAQS_MASTER_STATUS_FLAG_REAR_FAULT;
    }
    if (gMasterRuntimeInfo.can_initialized) {
        status.flags |= BODAQS_MASTER_STATUS_FLAG_CAN_INITIALIZED;
    }
    if (gMasterRuntimeInfo.can_bus_off) {
        status.flags |= BODAQS_MASTER_STATUS_FLAG_CAN_BUS_OFF;
    }
    if (gMasterRuntimeInfo.clock_fault) {
        status.flags |= BODAQS_MASTER_STATUS_FLAG_CLOCK_FAULT;
    }
    status.can_rx_frames = gMasterRuntimeInfo.can_rx_frames;
    status.can_tx_frames = gMasterRuntimeInfo.can_tx_frames;
    status.can_error_events = gMasterRuntimeInfo.can_error_events;
    status.can_rx_queue_depth = gCanReceiveQueue.depth;
    status.can_rx_queue_high_water =
        gCanReceiveQueue.high_water;
    status.spi_tx_queue_depth=gService.master_evidence.complete?1U:0U;
    for(node=0;node<4;++node) {
        if(gService.receptions[node].count) ++status.spi_tx_queue_depth;
        if(gService.lanes[0][node].tx.complete) ++status.spi_tx_queue_depth;
        if(gService.lanes[1][node].tx.complete) ++status.spi_tx_queue_depth;
    }
    status.spi_tx_queue_high_water=gService.status.spi_tx_queue_high_water;
    if(status.spi_tx_queue_depth>status.spi_tx_queue_high_water)
        status.spi_tx_queue_high_water=status.spi_tx_queue_depth;
    bodaqs_master_service_set_status(&gService, &status);

    /* Inventory is main-owned; accepted observations and stale/duplicate/boot
     * changes advance its generation. Keep live status above fresh, but avoid
     * recopying all four unchanged records on every measurement poll/ACK. */
    if (gService.discovery_generation == gNodeInventory.generation) return;

    do {
        generation = gNodeInventory.generation;
        for (node = 0U; node < BODAQS_CAN_NODE_COUNT; ++node) {
            const BodaqsNodeInventoryEntry *entry =
                &gNodeInventory.nodes[node];
            BodaqsMasterDiscoveryRecord *record =
                &gDiscoveryRecords[node];

            memset(record, 0, sizeof(*record));
            record->node_address = node;
            record->node_count = BODAQS_MASTER_DISCOVERY_NODE_COUNT;
            if (entry->present) {
                record->flags |= BODAQS_MASTER_DISCOVERY_FLAG_PRESENT;
            }
            if (entry->stale) {
                record->flags |= BODAQS_MASTER_DISCOVERY_FLAG_STALE;
            }
            if (entry->duplicate) {
                record->flags |= BODAQS_MASTER_DISCOVERY_FLAG_DUPLICATE;
            }
            if ((entry->last_status_ms != 0U) &&
                (entry->status.boot_id == entry->identity.boot_id)) {
                record->flags |=
                    BODAQS_MASTER_DISCOVERY_FLAG_STATUS_VALID;
            }
            record->hardware_type = entry->identity.hardware_type;
            record->endpoint_mask = entry->identity.endpoint_mask;
            record->firmware_version = entry->identity.firmware_version;
            record->capabilities = entry->identity.capabilities;
            record->hardware_uid = entry->identity.hardware_uid;
            record->conflicting_hardware_uid =
                entry->conflicting_hardware_uid;
            record->boot_id = entry->identity.boot_id;
            record->last_seen_ms = entry->last_seen_ms;
            record->node_uptime_ms = entry->status.uptime_ms;
            record->node_status_flags = entry->status.status_flags;
            record->can_rx_frames = entry->status.can_rx_frames;
            record->can_tx_frames = entry->status.can_tx_frames;
            record->can_error_events = entry->status.can_error_events;
            record->tx_queue_high_water = entry->status.queue_high_water;
        }
        generation_after = gNodeInventory.generation;
    } while (generation != generation_after);
    bodaqs_master_service_set_inventory(&gService, generation,
        gDiscoveryRecords,
        BODAQS_MASTER_DISCOVERY_NODE_COUNT);
}

static void service_sync(void) {
    static uint32_t sequence, edge, evidence_sequence, evidence_edge;
    static bool marker_pending, evidence_pending;
    uint8_t p[64]={0};
    if(!marker_pending && bodaqs_master_timing_take(&sequence,&edge)) {
        marker_pending=true;
        if(!evidence_pending && gService.measurement.mode.phase==2) {
            evidence_sequence=sequence;evidence_edge=edge;evidence_pending=true;
        }
    }
    if(marker_pending) {
        p[0]=1;p[1]=0x20;p[2]=1;p[4]=(uint8_t)sequence;p[5]=(uint8_t)(sequence>>8);p[6]=8;
        bodaqs_control_put_u32(p+8,sequence);bodaqs_control_put_u32(p+12,edge);
        if(send_can_frame(0x20,p,16)) marker_pending=false;
    }
    if(evidence_pending) {
        memset(p,0,sizeof p);p[0]=1;p[2]=1;p[4]=1;p[8]=1;
        bodaqs_control_put_u32(p+12,evidence_sequence);bodaqs_control_put_u32(p+16,evidence_edge);
        bodaqs_control_put_u32(p+20,1);
        if(gService.measurement.mode.phase!=2 || bodaqs_master_service_publish_evidence(&gService,p,24))
            evidence_pending=false;
    }
}

static void service_spi_receive(void);
static void retire_spi_boundary(void);
static void service_spi_retirement(void);

int main(void)
{
    BodaqsMasterIdentity identity;
    uint32_t reset_cause = (uint32_t) DL_SYSCTL_getResetCause();

    normalize_retained_clocks();
    SYSCFG_DL_init();
    gCanLinkReady = bodaqs_can_link_apply(MCAN0_INST, BODAQS_CAN_LINK_PROFILE);

    memset(gTransmitSlots, 0, sizeof(gTransmitSlots));
    memset(gReceiveSlots, 0, sizeof(gReceiveSlots));
    memset((void *) &gMasterRuntimeInfo, 0, sizeof(gMasterRuntimeInfo));
    gMasterRuntimeInfo.reset_cause = reset_cause;
    gMasterRuntimeInfo.can_link_profile = gCanLinkReady ? BODAQS_CAN_LINK_PROFILE : BODAQS_CAN_LINK_UNKNOWN;

    identity = master_identity_read();
    bodaqs_master_service_init(&gService, &identity);
    bodaqs_master_timing_init();
    gService.native_clock=bodaqs_master_timing_clock;
    bodaqs_control_exchange_init(&gService.control, master_control_boot_id_read());
    bodaqs_node_inventory_init(&gNodeInventory);
    gTransmitIndex = 0U;
    gReceiveIndex = 0U;
    gUptimeMs = 0U;
    bodaqs_record_queue_init(&gCanReceiveQueue, gCanReceiveStorage,
        sizeof(gCanReceiveStorage[0]), CAN_RX_CAPACITY);
    gHealthDue = true;
    bodaqs_record_queue_init(&gSpiReceiveQueue, gSpiReceiveStorage,
        BODAQS_MASTER_TRANSFER_BYTES, BODAQS_MASTER_SPI_RX_CAPACITY);
    memset(gTransmitSlots,0,sizeof gTransmitSlots);
    gDiscoveryTransaction = 0U;
    gDiscoveryNonce = (uint32_t) identity.hardware_uid ^
        (uint32_t) (identity.hardware_uid >> 32);
    gDiscoveryDue = true;
    gCanRecoveryDue = false;
    gCanWasBusOff = false;
    gLoggerCommunicationEstablished = false;
    arm_spi_slot();

    /* Prepare the trunk supply, but leave both branches off until the logger
     * has successfully communicated with the master. */
    DL_GPIO_clearPins(GPIO_BOARD_PORT,
        GPIO_BOARD_BUCK_ENABLE_PIN | GPIO_BOARD_FRONT_ENABLE_PIN |
            GPIO_BOARD_REAR_ENABLE_PIN);
    if (BODAQS_ENABLE_BUCK) {
        DL_GPIO_setPins(GPIO_BOARD_PORT, GPIO_BOARD_BUCK_ENABLE_PIN);
    }

    update_runtime_info();
    DL_SYSTICK_init(CPUCLK_FREQ / 1000U);
    DL_SYSTICK_enableInterrupt();
    DL_SYSTICK_enable();
    /* CS input is already enabled by the SPI peripheral pin configuration.
     * GPIO edge observation is independent of the selected peripheral function. */
    DL_GPIO_setLowerPinsPolarity(GPIO_SPI_A8_CS_PORT, DL_GPIO_PIN_8_EDGE_RISE);
    DL_GPIO_clearInterruptStatus(GPIO_SPI_A8_CS_PORT, GPIO_SPI_A8_CS_PIN);
    DL_GPIO_enableInterrupt(GPIO_SPI_A8_CS_PORT, GPIO_SPI_A8_CS_PIN);
    NVIC_SetPriority(GPIOA_INT_IRQn, 0U);
    NVIC_EnableIRQ(GPIOA_INT_IRQn);
    NVIC_EnableIRQ(SPI_A8_INST_INT_IRQN);
    NVIC_EnableIRQ(MCAN0_INST_INT_IRQN);

    while (1) {
        bodaqs_master_timing_supervise(gUptimeMs);
        service_sync();
        bodaqs_control_exchange_tick(&gService.control, gUptimeMs);
        service_spi_retirement();
        retire_spi_boundary();
        service_spi_retirement();
        service_spi_receive();
        gMasterRuntimeInfo.spi_rx_capacity = gSpiReceiveQueue.capacity;
        gMasterRuntimeInfo.spi_rx_high_water = gSpiReceiveQueue.high_water;
        gMasterRuntimeInfo.spi_rx_dropped = gSpiReceiveQueue.dropped;
        service_can_receive();
        /* A newly received conflicting UID must fence this very dispatch,
         * including retries admitted before the duplicate was observed. */
        if (gService.discovery_generation != gNodeInventory.generation) {
            update_service_status();
        }
        {
            uint8_t address, payload[64];
            uint16_t transaction;
            if (bodaqs_master_service_control_transmit(&gService, gUptimeMs, &address, &transaction, payload)) {
                (void)send_can_frame((uint16_t)(BODAQS_CAN_ID_TARGET_REQUEST_BASE + address), payload, sizeof(payload));
            }
        }
        gMasterRuntimeInfo.can_rx_capacity = gCanReceiveQueue.capacity;
        gMasterRuntimeInfo.can_rx_pending = gCanReceiveQueue.depth;
        gMasterRuntimeInfo.can_rx_pending_high_water = gCanReceiveQueue.high_water;
        gMasterRuntimeInfo.can_rx_dropped = gCanReceiveQueue.dropped;
        if (gHealthDue) {
            gHealthDue = false;
            bodaqs_node_inventory_update_stale(
                &gNodeInventory, gUptimeMs, NODE_STALE_AFTER_MS);
            update_runtime_info();
        }
        if (gDiscoveryDue) {
            gDiscoveryDue = false;
            if(gService.measurement.mode.phase==BODAQS_MODE_LEGACY) send_discovery_request();
        }
        if (gCanRecoveryDue &&
            time_reached(gUptimeMs, gCanRecoveryDueMs)) {
            gCanRecoveryDue = false;
            ++gMasterRuntimeInfo.can_bus_off_recovery_attempts;
            DL_MCAN_setOpMode(
                MCAN0_INST, DL_MCAN_OPERATION_MODE_NORMAL);
        }
        /* MSPM0Gx51x SPI_ERR_02 precludes sleeping between SPI slots. */
        __NOP();
    }
}

void MCAN0_INST_IRQHandler(void)
{
    if (DL_MCAN_getPendingInterrupt(MCAN0_INST) == DL_MCAN_IIDX_LINE1) {
        uint32_t interrupt_status = DL_MCAN_getIntrStatus(MCAN0_INST);

        gMasterRuntimeInfo.can_last_interrupts = interrupt_status;
        DL_MCAN_clearIntrStatus(MCAN0_INST, interrupt_status,
            DL_MCAN_INTR_SRC_MCAN_LINE_1);
        if ((interrupt_status & DL_MCAN_INTERRUPT_RF0L) != 0U) {
            ++gMasterRuntimeInfo.can_rx_hardware_losses;
            /* Hardware does not identify how many messages or which source
             * was overwritten. Preserve unknown counts and fail closed. */
            for(unsigned node=0;node<4;++node) gRejectedCan[node].essential=true;
        }
        if ((interrupt_status & gCanErrorInterruptMask) != 0U) {
            ++gMasterRuntimeInfo.can_error_events;
        }
        if ((interrupt_status & DL_MCAN_INTERRUPT_TC) != 0U) {
            ++gMasterRuntimeInfo.can_tx_frames;
        }
        if ((interrupt_status & (DL_MCAN_INTERRUPT_RF0N |
                DL_MCAN_INTERRUPT_RF0W |
                DL_MCAN_INTERRUPT_RF0F)) != 0U) {
            capture_can_receive_fifo();
        }
        gHealthDue = true;
    }
}

/* Observe only main-owned request/reply state before publication. */
static void drain_transfer(const uint8_t *request,size_t length,const uint8_t *reply,
    uint32_t acked_before,uint16_t ack_records)
{
    uint8_t cls,node,index;
    uint32_t object,bit;
    if(gMasterDrainInfo.state!=1 || length!=BODAQS_MEASUREMENT_BYTES) return;
    /* Caller has completed protocol validation; never repeat a wire CRC here.
     * Both byte arrays are still owned by main, before response publication. */
    cls=request[20];
    if(cls>=1 && cls<=2) {
        if(request[3]==1) {
            if(!bodaqs_measurement_get(request+12,4)) ++gMasterDrainInfo.data_head_polls[cls-1];
            if(!reply[3]) ++gMasterDrainInfo.data_empty_polls[cls-1];
        } else if((request[3]==5 || request[3]==14) && gService.objects_acked!=acked_before) {
            ++gMasterDrainInfo.data_acked_objects[cls-1];
            gMasterDrainInfo.data_acked_records[cls-1]+=ack_records;
        }
    }
    cls=bodaqs_fragment_class(reply[3]);node=reply[16];index=reply[17];
    if(cls<1 || cls>2 || node>3 || index>=26) return;
    --cls;
    object=(uint32_t)bodaqs_measurement_get(reply+12,4);
    if(gMasterDrainInfo.data_last_object[cls][node]!=object) {
        const uint16_t records=gService.receptions[node].count;
        gMasterDrainInfo.data_last_object[cls][node]=object;
        gMasterDrainInfo.data_fragment_mask[cls][node]=0;
        ++gMasterDrainInfo.data_objects[cls];
        gMasterDrainInfo.data_records[cls]+=records;
        if(records>=1 && records<=13) ++gMasterDrainInfo.data_batch_records[cls][records];
    }
    bit=1UL<<index;
    if(gMasterDrainInfo.data_fragment_mask[cls][node]&bit)
        ++gMasterDrainInfo.data_repeat_fragments[cls];
    else {
        gMasterDrainInfo.data_fragment_mask[cls][node]|=bit;
        ++gMasterDrainInfo.data_unique_fragments[cls];
    }
}

/* Called only for a DMA-owned buffer or by its main-loop writer before
 * publication. Control replies are retained. */
static void retire_measurement_slot(uint8_t *bytes,uint64_t context)
{
    BodaqsMeasurementSlot object;
    if(bodaqs_measurement_decode(bytes,BODAQS_MEASUREMENT_BYTES,&object) &&
       (object.kind==2 || object.kind==3 || object.kind==13)) {
        memset(&object,0,sizeof object);object.context=context;object.node=255;
        (void)bodaqs_measurement_encode(&object,bytes,BODAQS_MEASUREMENT_BYTES);
    }
}

static void service_spi_retirement(void)
{
    SpiRetirement proof;
    uint32_t primask=__get_PRIMASK();
    __disable_irq();
    proof.generation=gSpiRetirementProof.generation;
    proof.context=gSpiRetirementProof.context;
    /* Saturation fails closed: no previously issued proof can be recycled. */
    gSpiRetirementRequest.generation=gService.acquisition_retirement_pending &&
        gService.acquisition_retirement_generation!=UINT32_MAX ?
        gService.acquisition_retirement_generation:0;
    gSpiRetirementRequest.context=gService.measurement.mode.context;
    __DMB();
    __set_PRIMASK(primask);
    if(gService.acquisition_retirement_pending && proof.generation &&
       proof.generation==gService.acquisition_retirement_generation &&
       proof.context==gService.measurement.mode.context &&
       gService.acquisition_retirement_generation!=UINT32_MAX)
        bodaqs_master_service_measurement_fence(&gService,true,true);
}

/* Retire from the CS boundary and remaining RX DMA count, not DMA completion.
 * The selected capacity also permits legacy 84-byte MODE_INFO.
 * Each queued cell retains the measured physical extent. SPI reset empties prefetched TX FIFO bytes
 * so a short transaction cannot shift the next response. */
static void retire_spi_boundary(void)
{
    uint32_t primask = __get_PRIMASK();
    uint16_t remaining;
    size_t length;
    uint8_t excess;
    __disable_irq();
    if (gSpiRetiring) { __set_PRIMASK(primask); return; }
    gSpiRetiring = true;
    __set_PRIMASK(primask);
    remaining = DL_DMA_getTransferSize(DMA, DMA_SPI_RX_CHAN_ID);
    /* CS high ends the physical transaction. STAT.BUSY also includes unsent
     * TX FIFO bytes after a short transfer, so waiting for !BUSY would prevent
     * the reset below from retiring it. DMA completion alone is not CS proof. */
    if (remaining == BODAQS_MASTER_TRANSFER_BYTES ||
        DL_GPIO_readPins(GPIO_SPI_A8_CS_PORT, GPIO_SPI_A8_CS_PIN) == 0U) {
        gSpiRetiring=false; return;
    }
    DL_DMA_disableChannel(DMA, DMA_SPI_RX_CHAN_ID);
    DL_DMA_disableChannel(DMA, DMA_SPI_TX_CHAN_ID);
    /* Snapshot the owner-published identity, never partially updated service
     * state. Only the active or fully published inactive DMA buffer is ours. */
    SpiRetirement retirement = {gSpiRetirementRequest.generation,gSpiRetirementRequest.context};
    if(retirement.generation) {
        retire_measurement_slot(gTransmitSlots[gTransmitIndex],retirement.context);
        if(gSpiTransmitReady)
            retire_measurement_slot(gTransmitSlots[gTransmitIndex^1U],retirement.context);
    }
    remaining = DL_DMA_getTransferSize(DMA, DMA_SPI_RX_CHAN_ID);
    length = BODAQS_MASTER_TRANSFER_BYTES - remaining;
    length += DL_SPI_drainRXFIFO8(SPI_A8_INST,
        &gReceiveSlots[gReceiveIndex][length], (uint32_t)remaining);
    if (DL_SPI_drainRXFIFO8(SPI_A8_INST, &excess, 1U)) length = BODAQS_MASTER_TRANSFER_BYTES+1U;
    if(gSpiReceiveQueue.depth<gSpiReceiveQueue.capacity) {
        gSpiReceiveLengths[gSpiReceiveQueue.tail]=(uint16_t)length;
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
        SpiReceiveTiming *timing=&gSpiReceiveTiming[gSpiReceiveQueue.tail];
        timing->tick=bodaqs_master_timing_clock(NULL,&timing->epoch);
#endif
    }
    (void)bodaqs_record_queue_push(&gSpiReceiveQueue,gReceiveSlots[gReceiveIndex]);
    /* Publish only a fully prepared response at a physical boundary. Parsing,
     * control dispatch and all ownership changes remain in the main loop. */
    if (gSpiTransmitReady) {
        gTransmitIndex ^= 1U;
        gSpiTransmitReady = false;
    }
    DL_SPI_disable(SPI_A8_INST);
    DL_SPI_reset(SPI_A8_INST);
    DL_SPI_enablePower(SPI_A8_INST);
    delay_cycles(POWER_STARTUP_DELAY);
    SYSCFG_DL_SPI_A8_init();
    (void)DL_SPI_getPendingInterrupt(SPI_A8_INST);
    /* Proof follows DMA disable and FIFO/peripheral reset, before rearm. It
     * authorizes exactly the captured generation/context, never a later fence. */
    if(retirement.generation) {
        gSpiRetirementProof.context=retirement.context;
        __DMB();
        gSpiRetirementProof.generation=retirement.generation;
    }
    gReceiveIndex ^= 1U;
    arm_spi_slot();
    gSpiRetiring = false;
}

static void service_spi_receive(void)
{
    static uint8_t received[BODAQS_MASTER_TRANSFER_BYTES] BODAQS_SPI_BUFFER_STORAGE;
    uint16_t length;
    uint8_t next_index;
    uint32_t primask;
    uint32_t started;
    uint8_t reply_kind=0;
    uint32_t acked_before;
    uint16_t ack_records=0;
    BodaqsMasterSlotResult result;
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
    SpiReceiveTiming received_time;
    uint32_t pop_tick=0,pop_epoch=0;
    uint16_t queue_depth;
    const bool queue_scoped=gMasterDrainInfo.state==1;
#endif
    if (gSpiTransmitReady) return;
    primask=__get_PRIMASK();
    __disable_irq();
    length=gSpiReceiveLengths[gSpiReceiveQueue.head];
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
    received_time=gSpiReceiveTiming[gSpiReceiveQueue.head];
    queue_depth=gSpiReceiveQueue.depth;
    if(queue_depth) pop_tick=bodaqs_master_timing_clock(NULL,&pop_epoch);
#endif
    if (!bodaqs_record_queue_pop(&gSpiReceiveQueue,received)) {
        __set_PRIMASK(primask); return;
    }
    __set_PRIMASK(primask);
    next_index=gTransmitIndex^1U;
    drain_check();
    started=gMasterDrainInfo.state==1?drain_clock():0;
    update_service_status();
    drain_cost(0,started);
    started=gMasterDrainInfo.state==1?drain_clock():0;
    acked_before=gService.objects_acked;
    if(length==BODAQS_MEASUREMENT_BYTES && (received[3]==5 || received[3]==14) && received[16]<4 &&
       (received[20]==1 || received[20]==2))
        ack_records=gService.receptions[received[16]].count;
    result=bodaqs_master_service_process_transfer(&gService,received,length,
        gUptimeMs,gTransmitSlots[next_index]);
    if (result==BODAQS_MASTER_SLOT_PROCESSED) {
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
        drain_queue_record(received,length,received_time,pop_tick,pop_epoch,queue_depth,queue_scoped);
#endif
        if(gService.acquisition_retirement_pending)
            retire_measurement_slot(gTransmitSlots[next_index],gService.measurement.mode.context);
        reply_kind=gTransmitSlots[next_index][3];
        drain_transfer(received,length,gTransmitSlots[next_index],acked_before,ack_records);
        __DMB();
        gSpiTransmitReady=true;
    } else {
        ++gMasterRuntimeInfo.spi_recoveries;
    }
    drain_cost(1,started);
    /* Count only the already validated slot; do not run another wire CRC. */
    if(gMasterDrainInfo.state==1) {
        if(result!=BODAQS_MASTER_SLOT_PROCESSED) ++gMasterDrainInfo.malformed_slots;
        else if(length==BODAQS_MEASUREMENT_BYTES) {
            uint8_t cls=bodaqs_fragment_class(reply_kind);
            if(received[3]==1 && received[20]>=1 && received[20]<=5)
                ++gMasterDrainInfo.polls[received[20]-1];
            if(received[3]==5 && received[20]>=1 && received[20]<=5)
                ++gMasterDrainInfo.acks[received[20]-1];
#if BODAQS_MEASUREMENT_VERSION == 2
            if(received[3]==14) {
                if(received[20]>=1 && received[20]<=5)
                    ++gMasterDrainInfo.ack_fetches[received[20]-1];
                if(received[22]>=1 && received[22]<=5)
                    ++gMasterDrainInfo.ack_fetch_targets[received[22]-1];
            }
#endif
            if(cls) ++gMasterDrainInfo.fragments[cls-1];
            if(!reply_kind) ++gMasterDrainInfo.empty_replies;
        }
    }
    drain_check();
    if (BODAQS_ENABLE_BUCK && BODAQS_ENABLE_FRONT_BRANCH &&
        !gLoggerCommunicationEstablished &&
        ((gService.probes_received != 0U) || (gService.status_requests_received != 0U))) {
        gLoggerCommunicationEstablished=true;
        DL_GPIO_setPins(GPIO_BOARD_PORT,GPIO_BOARD_FRONT_ENABLE_PIN);
    }
}

/* GPIOA IRQ 1 is dispatched through GROUP1 in the MSPM0G3518 vector table. */
void GROUP1_IRQHandler(void)
{
    if (DL_GPIO_getEnabledInterruptStatus(GPIO_SPI_A8_CS_PORT, GPIO_SPI_A8_CS_PIN)) {
        DL_GPIO_clearInterruptStatus(GPIO_SPI_A8_CS_PORT, GPIO_SPI_A8_CS_PIN);
        retire_spi_boundary();
    }
}

void SPI_A8_INST_IRQHandler(void)
{
    /* DMA completion is an observation; CS still owns retirement. */
    (void) DL_SPI_getPendingInterrupt(SPI_A8_INST);
}

void SysTick_Handler(void)
{
    static uint16_t heartbeat_ticks;
    static uint16_t discovery_ticks;

    gUptimeMs += 1U;
    ++heartbeat_ticks;
    if (heartbeat_ticks >= 500U) {
        heartbeat_ticks = 0U;
        DL_GPIO_togglePins(GPIO_BOARD_PORT, GPIO_BOARD_STATUS_LED_PIN);
    }
    ++discovery_ticks;
    if (discovery_ticks >= (DISCOVERY_INTERVAL_MS)) {
        discovery_ticks = 0U;
        gDiscoveryDue = true;
    }
    if ((gUptimeMs % 100U)==0U) gHealthDue = true;
}


void TIMA0_IRQHandler(void) { bodaqs_master_timing_irq(); }
