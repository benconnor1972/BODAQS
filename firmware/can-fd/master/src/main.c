#include "master_timing.h"
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "bodaqs_can_network.h"
#include "bodaqs_record_queue.h"
#include "bodaqs_master_service.h"
#include "bodaqs_node_inventory.h"
#include "master_identity.h"
#include "ti_msp_dl_config.h"
#include "bodaqs_can_link_ti.h"
#include "bodaqs_spi_probe.h"

#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#define BODAQS_SPI_ADAPTER_CAPACITY BODAQS_SPI_PROBE_CAPACITY
#ifndef BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY
#define BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY 1
#endif
#if BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY != 1 && BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY != 4
#error "Probe receive queue capacity must be 1 or 4"
#endif
#else
#define BODAQS_SPI_ADAPTER_CAPACITY BODAQS_MASTER_SLOT_BYTES
#endif

#define NODE_STALE_AFTER_MS (3000U)
#define DISCOVERY_INTERVAL_MS (5000U)
#define CAN_RECOVERY_DELAY_MS (1000U)
#ifndef BODAQS_ENABLE_BUCK
#define BODAQS_ENABLE_BUCK (1)
#endif
#ifndef BODAQS_ENABLE_FRONT_BRANCH
#define BODAQS_ENABLE_FRONT_BRANCH (1)
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

#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
static BodaqsSpiProbeEngine gSpiProbe;
/* Observed software costs; never pad timing or physical delivery evidence. */
typedef struct {
    uint32_t boundaries,prepared,malformed,queue_dropped,queue_high_water;
    uint32_t process_calls,process_max_us,process_total_us;
    uint32_t clock_epoch,timing_invalid;
    BodaqsSpiProbeStats engine;
} MasterSpiProbeInfo;
volatile MasterSpiProbeInfo gMasterSpiProbeInfo;
/* Retirement fields belong to the boundary owner. Publication observations are
 * shared with the IRQ-fenced main gap path; tick/epoch become readable together
 * with gSpiTransmitReady. */
typedef struct {
    uint32_t boundaries,retire_total_us,retire_max_us;
    uint32_t publish_calls,publish_wait_total_us,publish_wait_max_us,timing_invalid;
} MasterSpiProbeBoundaryInfo;
static volatile MasterSpiProbeBoundaryInfo gSpiProbeBoundaryInfo;
static uint32_t gSpiProbePublishedTick,gSpiProbePublishedEpoch;
/* Round13 observer. Main fills identities only after successful engine processing.
 * IRQ updates fixed indices only; none of this state affects DMA or ACK authority.
 * A full exchange observation is NOT proof of valid MISO or logger acceptance. */
#ifndef BODAQS_SPI_PROBE_TRACE
#define BODAQS_SPI_PROBE_TRACE 0
#endif
#if BODAQS_SPI_PROBE_TRACE != 0 && BODAQS_SPI_PROBE_TRACE != 1
#error "BODAQS_SPI_PROBE_TRACE must be 0 or 1"
#endif
#define PROBE_TRACE_CAPACITY 8U
#define PROBE_TRACE_SKIP 256U
/* Round14 bench only. Both variants observe both CS edges, but only the
 * candidate may replace an already observed reply in a CS-high gap. */
#ifndef BODAQS_SPI_PROBE_EARLY_PUBLISH
#define BODAQS_SPI_PROBE_EARLY_PUBLISH 0
#endif
#if BODAQS_SPI_PROBE_EARLY_PUBLISH != 0 && BODAQS_SPI_PROBE_EARLY_PUBLISH != 1
#error "BODAQS_SPI_PROBE_EARLY_PUBLISH must be 0 or 1"
#endif
static volatile bool gSpiProbeActiveObserved=true,gSpiProbeQuarantine;
static volatile uint16_t gSpiProbeActiveBytes;
typedef struct {uint32_t attempts,published,busy,collisions,discarded,max_us,invalid;} ProbeEarly;
static volatile ProbeEarly gSpiProbeEarly;
#if BODAQS_SPI_PROBE_TRACE
typedef struct {uint32_t words[20];} ProbeReplyTrace;
static volatile ProbeReplyTrace gSpiProbeTrace[PROBE_TRACE_CAPACITY];
static uint32_t gSpiProbeTraceCase,gSpiProbeTraceSeen,gSpiProbeTraceCount;
static uint32_t gSpiProbeTraceEpoch,gSpiProbeTraceInvalid;
/* Index+1 (zero means none), published atomically with the ready tuple. */
static uint8_t gSpiProbeTraceTx[2];
#endif
/* End probe reply trace state. */
#endif

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
static uint8_t gTransmitSlots[2][BODAQS_SPI_ADAPTER_CAPACITY];
static uint8_t gReceiveSlots[2][BODAQS_SPI_ADAPTER_CAPACITY];
static uint8_t gTransmitIndex;
static uint8_t gReceiveIndex;
/* DMA rearms immediately. Each probe queue cell retains its own length/time;
 * the production adapter retains its existing single-cell representation. */
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
static uint8_t gSpiReceiveStorage[BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY][BODAQS_SPI_ADAPTER_CAPACITY];
/* Probe receive turnover state. Each field has one writer, except epoch/invalid
 * which all callers serialize against the boundary ISR. No DMA pointers retained. */
typedef struct {uint32_t tick,epoch,boundary;uint16_t length;} ProbeReceiveMeta;
static ProbeReceiveMeta gSpiProbeReceiveMeta[BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY];
typedef struct {
    uint32_t enqueued,dequeued,full_ready,full_other;
    uint32_t wait_calls,wait_total,wait_max,backlog_pops;
    uint32_t blocked_calls,blocked_total,blocked_max;
    uint32_t epoch,invalid,blocked_tick,blocked_epoch;
    bool blocked;
} ProbeTurnover;
static volatile ProbeTurnover gSpiProbeTurnover;
static volatile uint32_t gSpiProbeClockBypassed;
/* End probe receive turnover state. */
#else
static uint8_t gSpiReceiveStorage[1][BODAQS_SPI_ADAPTER_CAPACITY];
#endif
static BodaqsRecordQueue gSpiReceiveQueue;
/* Main publishes requests and consumes proof under a short IRQ fence. Only
 * the ISR adapter touches hardware; it never mutates the protocol service. */
typedef struct { uint32_t generation; uint64_t context; } SpiRetirement;
static volatile SpiRetirement gSpiRetirementRequest, gSpiRetirementProof;
static volatile bool gSpiRetiring;
static volatile bool gSpiTransmitReady;
#if !defined(BODAQS_SPI_PROBE) || !BODAQS_SPI_PROBE
static volatile uint16_t gSpiReceiveLength;
#endif
static volatile uint32_t gUptimeMs;
static volatile bool gDiscoveryDue;
static uint16_t gDiscoveryTransaction;
static uint32_t gDiscoveryNonce;
static volatile bool gCanRecoveryDue;
static volatile uint32_t gCanRecoveryDueMs;
static bool gCanWasBusOff;
static bool gCanLinkReady;
static bool gLoggerCommunicationEstablished;

#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
/* Called with the boundary owner or PRIMASK fence; uint32 tick wrap is valid
 * within one nonzero epoch. A changed epoch remains invalid until reboot. */
static void probe_turnover_epoch(uint32_t epoch)
{
    if(!epoch || (gSpiProbeTurnover.epoch && epoch!=gSpiProbeTurnover.epoch))
        gSpiProbeTurnover.invalid=1;
    gSpiProbeTurnover.epoch=epoch;
}
/* Main-owner observed deferral episode, not a physical-ready edge duration.
 * No clock read or counter increment on repeated busy-loop observations. */
static void probe_turnover_blocked(bool ready)
{
    if(ready==gSpiProbeTurnover.blocked)return;
    uint32_t mask=__get_PRIMASK(),epoch;
    __disable_irq();
    uint32_t now=bodaqs_master_timing_clock(NULL,&epoch);
    probe_turnover_epoch(epoch);
    if(ready) {
        gSpiProbeTurnover.blocked_tick=now;gSpiProbeTurnover.blocked_epoch=epoch;
        ++gSpiProbeTurnover.blocked_calls;
    } else if(epoch && epoch==gSpiProbeTurnover.blocked_epoch) {
        uint32_t elapsed=now-gSpiProbeTurnover.blocked_tick;
        gSpiProbeTurnover.blocked_total+=elapsed;
        if(elapsed>gSpiProbeTurnover.blocked_max)gSpiProbeTurnover.blocked_max=elapsed;
    } else gSpiProbeTurnover.invalid=1;
    gSpiProbeTurnover.blocked=ready;
    __set_PRIMASK(mask);
}
#endif

static uint32_t drain_clock(void)
{
    uint32_t epoch;
    uint32_t tick=bodaqs_master_timing_clock(NULL,&epoch);
    if(gMasterDrainInfo.state==1 && (!epoch || epoch!=gMasterDrainInfo.clock_epoch))
        gMasterDrainInfo.timing_invalid=1;
    return tick;
}

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
                if((r->source || r->evidence) && r->epoch!=epoch) r->essential=true;
                r->epoch=epoch;r->tick=record.received_tick;r->ordinal=record.ordinal;
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
                    if(length!=64 || p[1]!=0x23) r->essential=true;
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
        DMA, DMA_SPI_TX_CHAN_ID, BODAQS_SPI_ADAPTER_CAPACITY);

    DL_DMA_setSrcAddr(DMA, DMA_SPI_RX_CHAN_ID,
        (uint32_t) &SPI_A8_INST->RXDATA);
    DL_DMA_setDestAddr(DMA, DMA_SPI_RX_CHAN_ID,
        (uint32_t) &gReceiveSlots[gReceiveIndex][0]);
    DL_DMA_setTransferSize(
        DMA, DMA_SPI_RX_CHAN_ID, BODAQS_SPI_ADAPTER_CAPACITY);

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

#if !defined(BODAQS_SPI_PROBE) || !BODAQS_SPI_PROBE
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
#endif

static void service_spi_receive(void);
static void retire_spi_boundary(void);
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
static void probe_early_publish(void);
#endif
#if !defined(BODAQS_SPI_PROBE) || !BODAQS_SPI_PROBE
static void service_spi_retirement(void);
#endif

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
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    bodaqs_spi_probe_init(&gSpiProbe);
#endif
    bodaqs_master_timing_init();
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    bodaqs_spi_probe_set_clock(&gSpiProbe,bodaqs_master_timing_clock,NULL);
#endif
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
        BODAQS_SPI_ADAPTER_CAPACITY, sizeof(gSpiReceiveStorage)/sizeof(gSpiReceiveStorage[0]));
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
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    DL_GPIO_setLowerPinsPolarity(GPIO_SPI_A8_CS_PORT, DL_GPIO_PIN_8_EDGE_RISE_FALL);
#else
    DL_GPIO_setLowerPinsPolarity(GPIO_SPI_A8_CS_PORT, DL_GPIO_PIN_8_EDGE_RISE);
#endif
    DL_GPIO_clearInterruptStatus(GPIO_SPI_A8_CS_PORT, GPIO_SPI_A8_CS_PIN);
    DL_GPIO_enableInterrupt(GPIO_SPI_A8_CS_PORT, GPIO_SPI_A8_CS_PIN);
    NVIC_SetPriority(GPIOA_INT_IRQn, 0U);
    NVIC_EnableIRQ(GPIOA_INT_IRQn);
    NVIC_EnableIRQ(SPI_A8_INST_INT_IRQN);
    NVIC_EnableIRQ(MCAN0_INST_INT_IRQN);

    while (1) {
        bodaqs_master_timing_supervise(gUptimeMs);
#if !defined(BODAQS_SPI_PROBE) || !BODAQS_SPI_PROBE
        service_sync();
        bodaqs_control_exchange_tick(&gService.control, gUptimeMs);
        service_spi_retirement();
#endif
        retire_spi_boundary();
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
        probe_early_publish();
#endif
#if !defined(BODAQS_SPI_PROBE) || !BODAQS_SPI_PROBE
        service_spi_retirement();
#endif
        service_spi_receive();
        gMasterRuntimeInfo.spi_rx_capacity = gSpiReceiveQueue.capacity;
        gMasterRuntimeInfo.spi_rx_high_water = gSpiReceiveQueue.high_water;
        gMasterRuntimeInfo.spi_rx_dropped = gSpiReceiveQueue.dropped;
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
        /* Known synthetic objects substitute acquisition/CAN processing. */
        continue;
#endif
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
#if !defined(BODAQS_SPI_PROBE) || !BODAQS_SPI_PROBE
static void drain_transfer(const uint8_t *request,size_t length,const uint8_t *reply,
    uint32_t acked_before,uint16_t ack_records)
{
    uint8_t cls,node,index;
    uint32_t object,bit;
    if(gMasterDrainInfo.state!=1 || length!=64) return;
    /* Caller has completed protocol validation; never repeat a wire CRC here.
     * Both byte arrays are still owned by main, before response publication. */
    cls=request[20];
    if(cls>=1 && cls<=2) {
        if(request[3]==1) {
            if(!bodaqs_measurement_get(request+12,4)) ++gMasterDrainInfo.data_head_polls[cls-1];
            if(!reply[3]) ++gMasterDrainInfo.data_empty_polls[cls-1];
        } else if(request[3]==5 && gService.objects_acked!=acked_before) {
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
#endif

/* Called only for a DMA-owned buffer or by its main-loop writer before
 * publication. Control replies are retained. */
static void retire_measurement_slot(uint8_t *bytes,uint64_t context)
{
    BodaqsMeasurementSlot object;
    if(bodaqs_measurement_decode(bytes,64,&object) &&
       (object.kind==2 || object.kind==3 || object.kind==13)) {
        memset(&object,0,sizeof object);object.context=context;object.node=255;
        (void)bodaqs_measurement_encode(&object,bytes,64);
    }
}

#if !defined(BODAQS_SPI_PROBE) || !BODAQS_SPI_PROBE
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
#endif

/* Retire from the CS boundary and remaining RX DMA count, not DMA completion.
 * Keeping the 84-byte capacity permits observational legacy MODE_INFO while
 * the active protocol uses 64 bytes. SPI reset empties prefetched TX FIFO bytes
 * so a short transaction cannot shift the next response. */
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
/* Caller owns PRIMASK or CS retirement. Selection for rearm is publication;
 * neither this helper nor a gap rearm proves that MISO was clocked. */
static void probe_publish_reply(uint32_t boundary_started,uint32_t boundary_epoch,uint32_t boundary_ordinal)
{
    (void)boundary_ordinal;
#if BODAQS_SPI_PROBE_TRACE
        const uint8_t published_trace=gSpiProbeTraceTx[gTransmitIndex^1U];
        if(published_trace) {
            volatile uint32_t *w=gSpiProbeTrace[published_trace-1U].words;
            w[9]=boundary_started;w[12]=boundary_ordinal;w[4]|=2U;
            if(!boundary_epoch || boundary_epoch!=w[3]) {
                w[4]|=8U;gSpiProbeTraceInvalid=1;
            }
        }
#endif
        ++gSpiProbeBoundaryInfo.publish_calls;
        if(!boundary_epoch || boundary_epoch!=gSpiProbePublishedEpoch)
            gSpiProbeBoundaryInfo.timing_invalid=1;
        else {
            uint32_t wait=boundary_started-gSpiProbePublishedTick;
            gSpiProbeBoundaryInfo.publish_wait_total_us+=wait;
            if(wait>gSpiProbeBoundaryInfo.publish_wait_max_us)
                gSpiProbeBoundaryInfo.publish_wait_max_us=wait;
        }
        gTransmitIndex ^= 1U;
        gSpiTransmitReady=false;
        gSpiProbeActiveObserved=false;
        gSpiProbeActiveBytes=(uint16_t)(64U<<(gTransmitSlots[gTransmitIndex][15]&3U));
}

static void probe_early_publish(void)
{
#if BODAQS_SPI_PROBE_EARLY_PUBLISH
    uint32_t mask=__get_PRIMASK();
    __disable_irq();
    if(!gSpiTransmitReady || gSpiRetiring || gSpiProbeQuarantine || !gSpiProbeActiveObserved) {
        __set_PRIMASK(mask);return;
    }
    ++gSpiProbeEarly.attempts;
    /* DMA/FIFO progress belongs to a real physical transaction, even while
     * CS is already high and its rising interrupt has not yet been serviced. */
    if(!DL_GPIO_readPins(GPIO_SPI_A8_CS_PORT,GPIO_SPI_A8_CS_PIN) ||
       DL_DMA_getTransferSize(DMA,DMA_SPI_RX_CHAN_ID)!=BODAQS_SPI_ADAPTER_CAPACITY ||
       !DL_SPI_isRXFIFOEmpty(SPI_A8_INST)) {
        ++gSpiProbeEarly.busy;__set_PRIMASK(mask);return;
    }
    /* Both-edge RIS is independent of PRIMASK and survives SPI reset. Clear
     * stale evidence before the FINAL untouched/high check, never afterward. */
    DL_GPIO_clearInterruptStatus(GPIO_SPI_A8_CS_PORT,GPIO_SPI_A8_CS_PIN);
    if(!DL_GPIO_readPins(GPIO_SPI_A8_CS_PORT,GPIO_SPI_A8_CS_PIN) ||
       DL_DMA_getTransferSize(DMA,DMA_SPI_RX_CHAN_ID)!=BODAQS_SPI_ADAPTER_CAPACITY ||
       !DL_SPI_isRXFIFOEmpty(SPI_A8_INST) ||
       DL_GPIO_getRawInterruptStatus(GPIO_SPI_A8_CS_PORT,GPIO_SPI_A8_CS_PIN)) {
        ++gSpiProbeEarly.busy;__set_PRIMASK(mask);return;
    }
    uint32_t epoch,finished_epoch;
    uint32_t started=bodaqs_master_timing_clock(NULL,&epoch);
    gSpiRetiring=true;
    DL_DMA_disableChannel(DMA,DMA_SPI_RX_CHAN_ID);
    DL_DMA_disableChannel(DMA,DMA_SPI_TX_CHAN_ID);
    /* IRQ masking cannot stop the peer. Preserve a complete edge pulse or
     * receive progress across reset, including a burst with zero retained RX. */
    bool collided=!DL_GPIO_readPins(GPIO_SPI_A8_CS_PORT,GPIO_SPI_A8_CS_PIN) ||
        DL_GPIO_getRawInterruptStatus(GPIO_SPI_A8_CS_PORT,GPIO_SPI_A8_CS_PIN) ||
        DL_DMA_getTransferSize(DMA,DMA_SPI_RX_CHAN_ID)!=BODAQS_SPI_ADAPTER_CAPACITY ||
        !DL_SPI_isRXFIFOEmpty(SPI_A8_INST);
    DL_SPI_disable(SPI_A8_INST);
    DL_SPI_reset(SPI_A8_INST);
    DL_SPI_enablePower(SPI_A8_INST);
    delay_cycles(POWER_STARTUP_DELAY);
    SYSCFG_DL_SPI_A8_init();
    (void)DL_SPI_getPendingInterrupt(SPI_A8_INST);
    uint32_t publish_epoch;
    uint32_t publish_tick=bodaqs_master_timing_clock(NULL,&publish_epoch);
    probe_publish_reply(publish_tick,publish_epoch,gSpiProbeBoundaryInfo.boundaries);
    /* Same RX slot: no fabricated boundary, queue credit or retirement proof. */
    arm_spi_slot();
    collided=collided || !DL_GPIO_readPins(GPIO_SPI_A8_CS_PORT,GPIO_SPI_A8_CS_PIN) ||
        DL_GPIO_getRawInterruptStatus(GPIO_SPI_A8_CS_PORT,GPIO_SPI_A8_CS_PIN) ||
        DL_DMA_getTransferSize(DMA,DMA_SPI_RX_CHAN_ID)!=BODAQS_SPI_ADAPTER_CAPACITY ||
        !DL_SPI_isRXFIFOEmpty(SPI_A8_INST);
    uint32_t elapsed=bodaqs_master_timing_clock(NULL,&finished_epoch)-started;
    if(!epoch || epoch!=finished_epoch || epoch!=publish_epoch)gSpiProbeEarly.invalid=1;
    else if(elapsed>gSpiProbeEarly.max_us)gSpiProbeEarly.max_us=elapsed;
    ++gSpiProbeEarly.published;
    if(collided) {
        ++gSpiProbeEarly.collisions;gSpiProbeQuarantine=true;
#if BODAQS_SPI_PROBE_TRACE
        const uint8_t active=gSpiProbeTraceTx[gTransmitIndex];
        if(active)gSpiProbeTrace[active-1U].words[4]|=8U;
        gSpiProbeTraceInvalid=1;
#endif
    }
    gSpiRetiring=false;
    __set_PRIMASK(mask);
#endif
}
#endif

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
    /* In peripheral mode CS high ends the physical transaction. STAT.BUSY
     * also includes unsent TX FIFO bytes: a 64-byte measurement slot leaves
     * prefetched bytes from the 84-byte DMA capacity, so waiting for !BUSY
     * would prevent the reset below from ever retiring that short slot. */
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    const bool quarantined=gSpiProbeQuarantine;
    /* A reset-time collision can retain no bytes. It still requires a clean
     * CS-high reset; it is never submitted as an empty request. */
    if ((!quarantined && remaining == BODAQS_SPI_ADAPTER_CAPACITY) ||
#else
    if (remaining == BODAQS_SPI_ADAPTER_CAPACITY ||
#endif
        DL_GPIO_readPins(GPIO_SPI_A8_CS_PORT, GPIO_SPI_A8_CS_PIN) == 0U) {
        gSpiRetiring=false; return;
    }
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    /* TIMA0 native 1MHz clock preserves PRIMASK and accounts for a pending
     * rollover, so this call is also safe from the CS ISR. Software entry,
     * not a timestamp of the CS pad edge. */
    uint32_t boundary_epoch,boundary_finished_epoch;
    uint32_t boundary_started=bodaqs_master_timing_clock(NULL,&boundary_epoch);
#endif
    DL_DMA_disableChannel(DMA, DMA_SPI_RX_CHAN_ID);
    DL_DMA_disableChannel(DMA, DMA_SPI_TX_CHAN_ID);
    /* Snapshot the owner-published identity, never partially updated service
     * state. Only the active or fully published inactive DMA buffer is ours. */
    SpiRetirement retirement = {gSpiRetirementRequest.generation,gSpiRetirementRequest.context};
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    if(quarantined)retirement.generation=0;
#endif
    if(retirement.generation) {
        retire_measurement_slot(gTransmitSlots[gTransmitIndex],retirement.context);
        if(gSpiTransmitReady)
            retire_measurement_slot(gTransmitSlots[gTransmitIndex^1U],retirement.context);
    }
    remaining = DL_DMA_getTransferSize(DMA, DMA_SPI_RX_CHAN_ID);
    length = BODAQS_SPI_ADAPTER_CAPACITY - remaining;
    length += DL_SPI_drainRXFIFO8(SPI_A8_INST,
        &gReceiveSlots[gReceiveIndex][length], (uint32_t)remaining);
    if (DL_SPI_drainRXFIFO8(SPI_A8_INST, &excess, 1U)) length = BODAQS_SPI_ADAPTER_CAPACITY+1U;
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    const uint32_t boundary_ordinal=gSpiProbeBoundaryInfo.boundaries+1U;
#if BODAQS_SPI_PROBE_TRACE
    /* The ACTIVE buffer was clocked before any publication below. A short or
     * excessive burst cannot complete this observation. Do not inspect DMA bytes. */
    const uint8_t active_trace=gSpiProbeTraceTx[gTransmitIndex];
    if(active_trace) {
        volatile uint32_t *w=gSpiProbeTrace[active_trace-1U].words;
        const uint32_t bytes=64U<<((w[2]>>24)&3U);
        if(!quarantined && !(w[4]&4U) && length==bytes) {
            w[10]=boundary_started;w[13]=boundary_ordinal;w[4]|=4U;
            if(!boundary_epoch || boundary_epoch!=w[3]) {
                w[4]|=8U;gSpiProbeTraceInvalid=1;
            }
        }
    }
#endif
    if(!quarantined && length==gSpiProbeActiveBytes)gSpiProbeActiveObserved=true;
    probe_turnover_epoch(boundary_epoch);
    /* Exact CLOCK can publish an already prepared MISO reply below, but never
     * submits work. Full length, including FIFO excess, was established above. */
    if(quarantined) {
        ++gSpiProbeEarly.discarded;
        gSpiProbeQuarantine=false;
    } else if(bodaqs_spi_probe_is_clock(gReceiveSlots[gReceiveIndex],length)) {
        ++gSpiProbeClockBypassed;
    } else if(gSpiReceiveQueue.depth<gSpiReceiveQueue.capacity) {
        ProbeReceiveMeta *meta=&gSpiProbeReceiveMeta[gSpiReceiveQueue.tail];
        meta->length=(uint16_t)length;meta->tick=boundary_started;meta->epoch=boundary_epoch;
        meta->boundary=boundary_ordinal;
        (void)bodaqs_record_queue_push(&gSpiReceiveQueue,gReceiveSlots[gReceiveIndex]);
        ++gSpiProbeTurnover.enqueued;
    } else {
        ++gSpiReceiveQueue.dropped;
        if(gSpiTransmitReady)++gSpiProbeTurnover.full_ready;
        else ++gSpiProbeTurnover.full_other;
    }
#else
    if (gSpiReceiveQueue.depth == 0U) {
        gSpiReceiveLength = (uint16_t)length;
        (void)bodaqs_record_queue_push(&gSpiReceiveQueue,gReceiveSlots[gReceiveIndex]);
    } else {
        ++gSpiReceiveQueue.dropped;
    }
#endif
    /* Quarantine cannot replace an unobserved active reply with later work. */
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    if(gSpiTransmitReady && !quarantined &&
       (!BODAQS_SPI_PROBE_EARLY_PUBLISH || gSpiProbeActiveObserved))
        probe_publish_reply(boundary_started,boundary_epoch,boundary_ordinal);
#else
    if(gSpiTransmitReady) {gTransmitIndex^=1U;gSpiTransmitReady=false;}
#endif
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
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    uint32_t retire_elapsed=bodaqs_master_timing_clock(NULL,&boundary_finished_epoch)-boundary_started;
    ++gSpiProbeBoundaryInfo.boundaries;
    if(!boundary_epoch || boundary_epoch!=boundary_finished_epoch)
        gSpiProbeBoundaryInfo.timing_invalid=1;
    else {
        gSpiProbeBoundaryInfo.retire_total_us+=retire_elapsed;
        if(retire_elapsed>gSpiProbeBoundaryInfo.retire_max_us)
            gSpiProbeBoundaryInfo.retire_max_us=retire_elapsed;
    }
#endif
    gSpiRetiring = false;
}

static void service_spi_receive(void)
{
    uint8_t received[BODAQS_SPI_ADAPTER_CAPACITY];
    uint16_t length;
    uint8_t next_index;
    uint32_t primask;
#if !defined(BODAQS_SPI_PROBE) || !BODAQS_SPI_PROBE
    uint32_t started;
    uint8_t reply_kind=0;
    uint32_t acked_before;
    uint16_t ack_records=0;
    BodaqsMasterSlotResult result;
#endif
    if (gSpiTransmitReady) {
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
        probe_turnover_blocked(true);
#endif
        return;
    }
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    probe_turnover_blocked(false);
#endif
    primask=__get_PRIMASK();
    __disable_irq();
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    ProbeReceiveMeta meta=gSpiProbeReceiveMeta[gSpiReceiveQueue.head];
    uint16_t queued_depth=gSpiReceiveQueue.depth;
    length=meta.length;
#else
    length=gSpiReceiveLength;
#endif
    if (!bodaqs_record_queue_pop(&gSpiReceiveQueue,received)) {
        __set_PRIMASK(primask); return;
    }
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    uint32_t dequeue_epoch;
    uint32_t dequeue_tick=bodaqs_master_timing_clock(NULL,&dequeue_epoch);
    probe_turnover_epoch(dequeue_epoch);
    ++gSpiProbeTurnover.dequeued;++gSpiProbeTurnover.wait_calls;
    if(queued_depth>1)++gSpiProbeTurnover.backlog_pops;
    if(dequeue_epoch && dequeue_epoch==meta.epoch) {
        uint32_t wait=dequeue_tick-meta.tick;
        gSpiProbeTurnover.wait_total+=wait;
        if(wait>gSpiProbeTurnover.wait_max)gSpiProbeTurnover.wait_max=wait;
    } else gSpiProbeTurnover.invalid=1;
#endif
    __set_PRIMASK(primask);
    next_index=gTransmitIndex^1U;
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    {
        uint32_t epoch,finished_epoch;
        uint32_t started=bodaqs_master_timing_clock(NULL,&epoch);
        ++gMasterRuntimeInfo.slots_received;
        {
            uint32_t mask=__get_PRIMASK();
            __disable_irq();
            gSpiProbe.adapter_stats[0]=gMasterRuntimeInfo.slots_received;
            gSpiProbe.adapter_stats[1]=gSpiReceiveQueue.dropped;
            gSpiProbe.adapter_stats[2]=gMasterSpiProbeInfo.malformed;
            gSpiProbe.adapter_stats[3]=gMasterRuntimeInfo.spi_recoveries;
            gSpiProbe.adapter_stats[4]=gMasterRuntimeInfo.cs_release_timeouts;
            gSpiProbe.adapter_stats[5]=gMasterRuntimeInfo.can_rx_frames;
            gSpiProbe.adapter_stats[6]=gCanReceiveQueue.dropped;
            gSpiProbe.adapter_stats[7]=gMasterRuntimeInfo.can_rx_hardware_losses;
            gSpiProbe.adapter_stats[8]=epoch;
            uint32_t invalid=gMasterSpiProbeInfo.timing_invalid ||
                gSpiProbeBoundaryInfo.timing_invalid || !epoch;
            gSpiProbe.adapter_stats[9]=invalid;
            /* Completed calls only: this STATS request is included in the
             * following snapshot. Both owners are frozen during this copy. */
            gSpiProbe.diagnostic_stats[0]=gMasterSpiProbeInfo.process_calls;
            gSpiProbe.diagnostic_stats[1]=gMasterSpiProbeInfo.process_total_us;
            gSpiProbe.diagnostic_stats[2]=gMasterSpiProbeInfo.process_max_us;
            gSpiProbe.diagnostic_stats[3]=gSpiProbeBoundaryInfo.boundaries;
            gSpiProbe.diagnostic_stats[4]=gSpiProbeBoundaryInfo.retire_total_us;
            gSpiProbe.diagnostic_stats[5]=gSpiProbeBoundaryInfo.retire_max_us;
            gSpiProbe.diagnostic_stats[6]=gSpiProbeBoundaryInfo.publish_calls;
            gSpiProbe.diagnostic_stats[7]=gSpiProbeBoundaryInfo.publish_wait_total_us;
            gSpiProbe.diagnostic_stats[8]=gSpiProbeBoundaryInfo.publish_wait_max_us;
            gSpiProbe.diagnostic_stats[9]=invalid;
            probe_turnover_epoch(epoch);
            const uint32_t receive_page[]={1,gSpiReceiveQueue.capacity,
                gSpiReceiveQueue.depth,gSpiReceiveQueue.high_water,epoch,gSpiProbeTurnover.invalid,
                gSpiProbeTurnover.enqueued,gSpiProbeTurnover.dequeued,
                gSpiProbeTurnover.full_ready,gSpiProbeTurnover.full_other};
            const uint32_t turnover_page[]={1,gSpiProbeTurnover.wait_calls,
                gSpiProbeTurnover.wait_total,gSpiProbeTurnover.wait_max,
                gSpiProbeTurnover.blocked_calls,gSpiProbeTurnover.blocked_total,
                gSpiProbeTurnover.blocked_max,gSpiProbeTurnover.backlog_pops,
                epoch,gSpiProbeTurnover.invalid};
            memcpy(gSpiProbe.receive_stats,receive_page,sizeof receive_page);
            memcpy(gSpiProbe.turnover_stats,turnover_page,sizeof turnover_page);
            const uint32_t flow_page[]={1,1,gSpiProbeClockBypassed,0,0,0,0,0,0,0};
            memcpy(gSpiProbe.flow_stats,flow_page,sizeof flow_page);
            /* Only an observer page selector is read before decode. A malformed
             * request still fails in the engine and cannot obtain a response. */
            memset(gSpiProbe.trace_stats,0,sizeof gSpiProbe.trace_stats);
            if(length>=20 && received[3]==BODAQS_PROBE_STATS && received[13]>=8 && received[13]<=24) {
                const uint8_t page=received[13];
                if(page==8) {
                    uint32_t header[]={1,BODAQS_SPI_PROBE_TRACE,PROBE_TRACE_CAPACITY,PROBE_TRACE_SKIP,
                        0,0,gSpiProbe.case_id,epoch,0,0};
#if BODAQS_SPI_PROBE_TRACE
                    header[4]=gSpiProbeTraceCount;header[5]=gSpiProbeTraceSeen;header[6]=gSpiProbeTraceCase;
                    header[7]=gSpiProbeTraceEpoch;header[8]=gSpiProbeTraceInvalid;
#endif
                    memcpy(gSpiProbe.trace_stats,header,sizeof header);
                }
#if BODAQS_SPI_PROBE_TRACE
                else {
                    const unsigned index=(page-9U)/2U,offset=((page-9U)%2U)*10U;
                    if(index<gSpiProbeTraceCount)
                        for(unsigned i=0;i<10;++i)gSpiProbe.trace_stats[i]=gSpiProbeTrace[index].words[offset+i];
                }
#endif
            }
            if(length>=20 && received[3]==BODAQS_PROBE_STATS && received[13]==25) {
                const uint32_t early[]={1,BODAQS_SPI_PROBE_EARLY_PUBLISH,gSpiProbeEarly.attempts,
                    gSpiProbeEarly.published,gSpiProbeEarly.busy,gSpiProbeEarly.collisions,
                    gSpiProbeEarly.discarded,gSpiProbeEarly.max_us,epoch,gSpiProbeEarly.invalid};
                memcpy(gSpiProbe.trace_stats,early,sizeof early);
            }
            gMasterSpiProbeInfo.boundaries=gSpiProbeBoundaryInfo.boundaries;
            __set_PRIMASK(mask);
        }
        const uint32_t previous_case=gSpiProbe.case_id;
        bool prepared=bodaqs_spi_probe_process(&gSpiProbe,received,length,
            gTransmitSlots[next_index],BODAQS_SPI_ADAPTER_CAPACITY);
        uint32_t elapsed=bodaqs_master_timing_clock(NULL,&finished_epoch)-started;
        if(!epoch || epoch!=finished_epoch) gMasterSpiProbeInfo.timing_invalid=1;
        else {
            gMasterSpiProbeInfo.process_total_us+=elapsed;
            if(elapsed>gMasterSpiProbeInfo.process_max_us) gMasterSpiProbeInfo.process_max_us=elapsed;
        }
        gMasterSpiProbeInfo.clock_epoch=epoch;
        ++gMasterSpiProbeInfo.process_calls;
        gMasterSpiProbeInfo.engine=gSpiProbe.stats;
        gMasterSpiProbeInfo.queue_dropped=gSpiReceiveQueue.dropped;
        gMasterSpiProbeInfo.queue_high_water=gSpiReceiveQueue.high_water;
        if(prepared) {
            ++gMasterSpiProbeInfo.prepared;
            /* Timestamp and fully prepared bytes belong to this publication.
             * A boundary before this fence keeps the old reply; one after it
             * sees the complete timestamp/epoch/ready tuple. */
            uint32_t publish_mask=__get_PRIMASK();
            __disable_irq();
            /* New admitted BEGIN explicitly replaces the previous case, even
             * if its last reply used a different physical frame size. */
            if(gSpiProbe.case_id!=previous_case)gSpiProbeActiveObserved=true;
#if BODAQS_SPI_PROBE_TRACE
            /* A newly admitted BEGIN changes the engine case. Idempotent BEGIN,
             * STOP and diagnostic readout retain the capture. Reset all indices
             * together so an old active buffer cannot write into the new arena. */
            if(gSpiProbeTraceCase!=gSpiProbe.case_id) {
                memset((void *)gSpiProbeTrace,0,sizeof gSpiProbeTrace);
                gSpiProbeTraceCase=gSpiProbe.case_id;gSpiProbeTraceCount=0;gSpiProbeTraceSeen=0;
                gSpiProbeTraceTx[0]=gSpiProbeTraceTx[1]=0;
                gSpiProbeTraceEpoch=epoch;gSpiProbeTraceInvalid=!epoch;
            }
            gSpiProbeTraceTx[next_index]=0;
            volatile uint32_t *trace_words=NULL;
            const uint8_t *reply=gTransmitSlots[next_index];
            if(reply[3]==(BODAQS_PROBE_POLL|BODAQS_PROBE_RESPONSE) ||
               reply[3]==(BODAQS_PROBE_ACK|BODAQS_PROBE_RESPONSE)) {
                ++gSpiProbeTraceSeen;
                if(gSpiProbeTraceSeen>PROBE_TRACE_SKIP && gSpiProbeTraceCount<PROBE_TRACE_CAPACITY) {
                    const unsigned index=gSpiProbeTraceCount++;
                    trace_words=gSpiProbeTrace[index].words;
                    trace_words[0]=gSpiProbeTraceSeen;
                    trace_words[1]=(uint32_t)reply[8]|((uint32_t)reply[9]<<8)|((uint32_t)reply[10]<<16)|((uint32_t)reply[11]<<24);
                    trace_words[2]=(reply[3]&127U)|((uint32_t)reply[12]<<8)|((uint32_t)reply[13]<<16)|((uint32_t)(reply[15]&3U)<<24);
                    trace_words[3]=epoch;trace_words[4]=1;
                    trace_words[5]=meta.tick;trace_words[6]=started;trace_words[7]=started+elapsed;
                    trace_words[11]=meta.boundary;trace_words[14]=queued_depth;trace_words[15]=gSpiProbe.case_id;
                    if(!epoch || meta.epoch!=epoch || dequeue_epoch!=epoch || finished_epoch!=epoch || gSpiProbeTraceEpoch!=epoch) {
                        trace_words[4]|=8U;gSpiProbeTraceInvalid=1;
                    }
                    gSpiProbeTraceTx[next_index]=(uint8_t)(index+1U);
                }
            }
#endif
            gSpiProbePublishedTick=bodaqs_master_timing_clock(NULL,&gSpiProbePublishedEpoch);
#if BODAQS_SPI_PROBE_TRACE
            if(trace_words) {
                trace_words[8]=gSpiProbePublishedTick;
                if(gSpiProbePublishedEpoch!=epoch) {trace_words[4]|=8U;gSpiProbeTraceInvalid=1;}
            }
#endif
            __DMB();
            gSpiTransmitReady=true;
            __set_PRIMASK(publish_mask);
        } else {++gMasterSpiProbeInfo.malformed;++gMasterRuntimeInfo.spi_recoveries;}
    }
#else
    drain_check();
    started=gMasterDrainInfo.state==1?drain_clock():0;
    update_service_status();
    drain_cost(0,started);
    started=gMasterDrainInfo.state==1?drain_clock():0;
    acked_before=gService.objects_acked;
    if(length==64 && received[3]==5 && received[16]<4 &&
       (received[20]==1 || received[20]==2))
        ack_records=gService.receptions[received[16]].count;
    result=bodaqs_master_service_process_transfer(&gService,received,length,
        gUptimeMs,gTransmitSlots[next_index]);
    if (result==BODAQS_MASTER_SLOT_PROCESSED) {
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
        else if(length==64) {
            uint8_t cls=bodaqs_fragment_class(reply_kind);
            if(received[3]==1 && received[20]>=1 && received[20]<=5)
                ++gMasterDrainInfo.polls[received[20]-1];
            if(received[3]==5 && received[20]>=1 && received[20]<=5)
                ++gMasterDrainInfo.acks[received[20]-1];
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
#endif
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
