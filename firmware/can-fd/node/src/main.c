#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "bodaqs_can_network.h"
#include "ti_msp_dl_config.h"

#define NODE_FIRMWARE_VERSION (0x00010001U)
#define NODE_HARDWARE_TYPE BODAQS_CAN_HARDWARE_IMU_ONLY_NODE
#define NODE_ENDPOINT_MASK ((uint16_t) BODAQS_CAN_ENDPOINT_MASK(            \
    BODAQS_CAN_ENDPOINT_IMU))

#define STATUS_INTERVAL_MS (1000U)
#define TRANSMIT_RETRY_MS (100U)
#define CAN_RECOVERY_DELAY_MS (1000U)
#define TX_FIFO_SIZE (4U)

typedef struct {
    uint32_t reset_cause;
    uint32_t uptime_ms;
    uint64_t hardware_uid;
    uint32_t boot_id;
    uint32_t can_rx_frames;
    uint32_t can_tx_frames;
    uint32_t can_error_events;
    uint32_t can_bus_off_recovery_attempts;
    uint32_t can_bus_off_recoveries;
    uint32_t can_last_interrupts;
    uint32_t malformed_frames;
    uint32_t unsupported_version_frames;
    uint32_t unknown_frames;
    uint32_t discovery_requests_received;
    uint32_t announcements_queued;
    uint32_t statuses_queued;
    uint32_t transmit_enqueue_failures;
    uint32_t last_decode_result;
    uint16_t tx_queue_depth;
    uint16_t tx_queue_high_water;
    uint8_t node_address;
    bool can_initialized;
    bool can_error_passive;
    bool can_bus_off;
    bool can_bus_off_recovered;
    bool clock_fault;
} NodeRuntimeInfo;

volatile NodeRuntimeInfo gNodeRuntimeInfo;

static volatile uint32_t gUptimeMs;
static volatile bool gAnnounceScheduled;
static volatile uint32_t gAnnounceDueMs;
static volatile uint16_t gAnnounceTransaction;
static bool gStatusScheduled;
static uint32_t gStatusDueMs;
static volatile bool gCanRecoveryDue;
static volatile uint32_t gCanRecoveryDueMs;
static bool gCanWasBusOff;

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

static void normalize_retained_clocks(void)
{
    DL_SYSCTL_MCLK_SOURCE source = DL_SYSCTL_getMCLKSource();

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

static uint64_t read_hardware_uid(void)
{
    uint32_t device_description =
        ((uint32_t) DL_FactoryRegion_getPartNumber() << 16) |
        ((uint32_t) DL_FactoryRegion_getUserIDVariant() << 8) |
        ((uint32_t) DL_FactoryRegion_getUserIDMajorRev() << 4) |
        (uint32_t) DL_FactoryRegion_getUserIDMinorRev();
    return ((uint64_t) device_description << 32) |
        DL_FactoryRegion_getTraceID();
}

static uint32_t read_boot_id(uint64_t hardware_uid)
{
    uint32_t boot_id;

    while (!DL_TRNG_isCaptureReady(TRNG)) {
        ;
    }
    DL_TRNG_clearInterruptStatus(TRNG, DL_TRNG_INTERRUPT_CAPTURE_RDY_EVENT);
    boot_id = DL_TRNG_getCapture(TRNG);
    DL_TRNG_disablePower(TRNG);
    if (boot_id == 0U) {
        boot_id = (uint32_t) hardware_uid ^
            (uint32_t) (hardware_uid >> 32) ^ UINT32_C(0xB0DA0501);
        if (boot_id == 0U) {
            boot_id = 1U;
        }
    }
    return boot_id;
}

static uint8_t read_node_address(void)
{
    uint8_t address = 0U;

    if (DL_GPIO_readPins(GPIO_NODE_PORT, GPIO_NODE_NODE_ID_0_PIN) != 0U) {
        address |= 1U;
    }
    if (DL_GPIO_readPins(GPIO_NODE_PORT, GPIO_NODE_NODE_ID_1_PIN) != 0U) {
        address |= 2U;
    }
    return address;
}

static void update_can_state(void)
{
    DL_MCAN_ProtocolStatus protocol_status = {0};
    uint32_t clock_status = DL_SYSCTL_getClockStatus();
    gNodeRuntimeInfo.can_initialized =
        DL_MCAN_isMemInitDone(MCAN0_INST) &&
        (DL_MCAN_getOpMode(MCAN0_INST) == DL_MCAN_OPERATION_MODE_NORMAL);
    DL_MCAN_getProtocolStatus(MCAN0_INST, &protocol_status);
    gNodeRuntimeInfo.can_error_passive =
        protocol_status.errPassive != 0U;
    gNodeRuntimeInfo.can_bus_off = protocol_status.busOffStatus != 0U;
    if (gNodeRuntimeInfo.can_bus_off && !gCanWasBusOff) {
        gCanRecoveryDueMs = gUptimeMs + CAN_RECOVERY_DELAY_MS;
        gCanRecoveryDue = true;
    } else if (!gNodeRuntimeInfo.can_bus_off && gCanWasBusOff) {
        gNodeRuntimeInfo.can_bus_off_recovered = true;
        ++gNodeRuntimeInfo.can_bus_off_recoveries;
        gAnnounceTransaction = 0U;
        gAnnounceDueMs = gUptimeMs + 1U;
        gAnnounceScheduled = true;
    }
    gCanWasBusOff = gNodeRuntimeInfo.can_bus_off;
    gNodeRuntimeInfo.clock_fault =
        (clock_status & (DL_SYSCTL_CLK_STATUS_HFCLK_GOOD |
            DL_SYSCTL_CLK_STATUS_SYSPLL_GOOD)) !=
        (DL_SYSCTL_CLK_STATUS_HFCLK_GOOD |
            DL_SYSCTL_CLK_STATUS_SYSPLL_GOOD);
}

static void update_tx_queue_state(void)
{
    DL_MCAN_TxFIFOStatus fifo_status = {0};
    uint16_t depth;

    DL_MCAN_getTxFIFOQueStatus(MCAN0_INST, &fifo_status);
    depth = (uint16_t) (TX_FIFO_SIZE - fifo_status.freeLvl);
    gNodeRuntimeInfo.tx_queue_depth = depth;
    if (depth > gNodeRuntimeInfo.tx_queue_high_water) {
        gNodeRuntimeInfo.tx_queue_high_water = depth;
    }
}

static bool send_can_frame(
    uint16_t identifier, const uint8_t *payload, size_t length)
{
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
    message.mm = (uint8_t) gNodeRuntimeInfo.can_tx_frames;
    memcpy(message.data, payload, length);
    DL_MCAN_writeMsgRam(
        MCAN0_INST, DL_MCAN_MEM_TYPE_FIFO, 0U, &message);
    if (DL_MCAN_TXBufAddReq(MCAN0_INST, fifo_status.putIdx) != 0) {
        return false;
    }
    update_tx_queue_state();
    return true;
}

static bool send_announcement(void)
{
    BodaqsCanNodeAnnounce announce = {0};
    uint8_t payload[BODAQS_CAN_NODE_ANNOUNCE_BYTES];

    announce.transaction = gAnnounceTransaction;
    announce.node_address = gNodeRuntimeInfo.node_address;
    announce.hardware_type = NODE_HARDWARE_TYPE;
    announce.endpoint_mask = NODE_ENDPOINT_MASK;
    announce.firmware_version = NODE_FIRMWARE_VERSION;
    announce.capabilities = 0U;
    announce.hardware_uid = gNodeRuntimeInfo.hardware_uid;
    announce.boot_id = gNodeRuntimeInfo.boot_id;
    return bodaqs_can_encode_node_announce(
               &announce, payload, sizeof(payload)) &&
        send_can_frame(bodaqs_can_announce_identifier(announce.node_address),
            payload, sizeof(payload));
}

static bool send_status(void)
{
    BodaqsCanNodeStatus status = {0};
    uint8_t payload[BODAQS_CAN_NODE_STATUS_BYTES];

    status.boot_id = gNodeRuntimeInfo.boot_id;
    status.uptime_ms = gUptimeMs;
    status.status_flags = 0U;
    if (gNodeRuntimeInfo.can_error_passive) {
        status.status_flags |= (1UL << 2);
    }
    if (gNodeRuntimeInfo.can_bus_off_recovered) {
        status.status_flags |= (1UL << 3);
    }
    if (gNodeRuntimeInfo.clock_fault) {
        status.status_flags |= (1UL << 8);
    }
    status.can_rx_frames = gNodeRuntimeInfo.can_rx_frames;
    status.can_tx_frames = gNodeRuntimeInfo.can_tx_frames;
    status.can_error_events =
        (uint16_t) gNodeRuntimeInfo.can_error_events;
    status.queue_high_water = gNodeRuntimeInfo.tx_queue_high_water;
    return bodaqs_can_encode_node_status(0U,
               &status, payload, sizeof(payload)) &&
        send_can_frame(bodaqs_can_status_identifier(
                           gNodeRuntimeInfo.node_address),
            payload, sizeof(payload));
}

static uint16_t can_standard_identifier(const DL_MCAN_RxBufElement *message)
{
    return (uint16_t) ((message->id >> 18U) & 0x7FFU);
}

static void process_can_message(const DL_MCAN_RxBufElement *message)
{
    BodaqsCanDiscoveryRequest request;
    BodaqsCanDecodeResult result;
    size_t length;

    if ((message->xtd != 0U) || (message->rtr != 0U) ||
        (message->fdf == 0U) || (message->brs == 0U)) {
        ++gNodeRuntimeInfo.malformed_frames;
        return;
    }
    if (can_standard_identifier(message) !=
        BODAQS_CAN_ID_BROADCAST_CONTROL) {
        ++gNodeRuntimeInfo.unknown_frames;
        return;
    }
    length = bodaqs_can_dlc_to_length((uint8_t) message->dlc);
    result = bodaqs_can_decode_discovery_request(
        message->data, length, &request);
    gNodeRuntimeInfo.last_decode_result = (uint32_t) result;
    if (result == BODAQS_CAN_DECODE_UNSUPPORTED_VERSION) {
        ++gNodeRuntimeInfo.unsupported_version_frames;
        return;
    }
    if (result != BODAQS_CAN_DECODE_OK) {
        ++gNodeRuntimeInfo.malformed_frames;
        return;
    }

    ++gNodeRuntimeInfo.discovery_requests_received;
    gAnnounceTransaction = request.transaction;
    gAnnounceDueMs = gUptimeMs + bodaqs_can_discovery_delay_ms(
        gNodeRuntimeInfo.hardware_uid, request.nonce,
        gNodeRuntimeInfo.node_address, request.response_window_ms);
    gAnnounceScheduled = true;
}

static void drain_can_receive_fifo(void)
{
    DL_MCAN_RxBufElement message;
    DL_MCAN_RxFIFOStatus fifo_status = {0};

    fifo_status.num = DL_MCAN_RX_FIFO_NUM_0;
    DL_MCAN_getRxFIFOStatus(MCAN0_INST, &fifo_status);
    while (fifo_status.fillLvl != 0U) {
        DL_MCAN_readMsgRam(MCAN0_INST, DL_MCAN_MEM_TYPE_FIFO, 0U,
            fifo_status.num, &message);
        DL_MCAN_writeRxFIFOAck(
            MCAN0_INST, fifo_status.num, fifo_status.getIdx);
        ++gNodeRuntimeInfo.can_rx_frames;
        process_can_message(&message);
        DL_MCAN_getRxFIFOStatus(MCAN0_INST, &fifo_status);
    }
}

int main(void)
{
    uint32_t reset_cause = (uint32_t) DL_SYSCTL_getResetCause();

    normalize_retained_clocks();
    SYSCFG_DL_init();
    memset((void *) &gNodeRuntimeInfo, 0, sizeof(gNodeRuntimeInfo));
    gNodeRuntimeInfo.reset_cause = reset_cause;
    gNodeRuntimeInfo.hardware_uid = read_hardware_uid();
    gNodeRuntimeInfo.boot_id = read_boot_id(gNodeRuntimeInfo.hardware_uid);
    gNodeRuntimeInfo.node_address = read_node_address();
    gUptimeMs = 0U;
    gCanRecoveryDue = false;
    gCanWasBusOff = false;

    DL_GPIO_clearPins(GPIO_NODE_PORT, GPIO_NODE_CAN_STANDBY_PIN);
    gAnnounceTransaction = 0U;
    gAnnounceDueMs = 100U;
    gAnnounceScheduled = true;
    gStatusDueMs = 1000U +
        ((uint32_t) gNodeRuntimeInfo.hardware_uid % STATUS_INTERVAL_MS);
    gStatusScheduled = true;

    update_can_state();
    DL_SYSTICK_init(CPUCLK_FREQ / 1000U);
    DL_SYSTICK_enableInterrupt();
    DL_SYSTICK_enable();
    NVIC_EnableIRQ(MCAN0_INST_INT_IRQN);

    while (1) {
        uint32_t now = gUptimeMs;

        if (gAnnounceScheduled && time_reached(now, gAnnounceDueMs)) {
            if (send_announcement()) {
                ++gNodeRuntimeInfo.announcements_queued;
                gAnnounceScheduled = false;
            } else {
                ++gNodeRuntimeInfo.transmit_enqueue_failures;
                gAnnounceDueMs = now + TRANSMIT_RETRY_MS;
            }
        }
        if (gStatusScheduled && time_reached(now, gStatusDueMs)) {
            if (send_status()) {
                ++gNodeRuntimeInfo.statuses_queued;
                gStatusDueMs += STATUS_INTERVAL_MS;
            } else {
                ++gNodeRuntimeInfo.transmit_enqueue_failures;
                gStatusDueMs = now + TRANSMIT_RETRY_MS;
            }
        }
        if (gCanRecoveryDue && time_reached(now, gCanRecoveryDueMs)) {
            gCanRecoveryDue = false;
            ++gNodeRuntimeInfo.can_bus_off_recovery_attempts;
            DL_MCAN_setOpMode(
                MCAN0_INST, DL_MCAN_OPERATION_MODE_NORMAL);
        }
        __WFE();
    }
}

void MCAN0_INST_IRQHandler(void)
{
    if (DL_MCAN_getPendingInterrupt(MCAN0_INST) == DL_MCAN_IIDX_LINE1) {
        uint32_t interrupt_status = DL_MCAN_getIntrStatus(MCAN0_INST);

        gNodeRuntimeInfo.can_last_interrupts = interrupt_status;
        DL_MCAN_clearIntrStatus(MCAN0_INST, interrupt_status,
            DL_MCAN_INTR_SRC_MCAN_LINE_1);
        if ((interrupt_status & gCanErrorInterruptMask) != 0U) {
            ++gNodeRuntimeInfo.can_error_events;
        }
        if ((interrupt_status & DL_MCAN_INTERRUPT_TC) != 0U) {
            ++gNodeRuntimeInfo.can_tx_frames;
            update_tx_queue_state();
        }
        if ((interrupt_status & (DL_MCAN_INTERRUPT_RF0N |
                DL_MCAN_INTERRUPT_RF0W |
                DL_MCAN_INTERRUPT_RF0F)) != 0U) {
            drain_can_receive_fifo();
        }
        update_can_state();
    }
}

void SysTick_Handler(void)
{
    static uint16_t heartbeat_ticks;
    static uint8_t health_ticks;

    ++gUptimeMs;
    gNodeRuntimeInfo.uptime_ms = gUptimeMs;
    ++heartbeat_ticks;
    if (heartbeat_ticks >= 500U) {
        heartbeat_ticks = 0U;
        DL_GPIO_togglePins(GPIO_NODE_PORT, GPIO_NODE_STATUS_LED_PIN);
    }
    ++health_ticks;
    if (health_ticks >= 100U) {
        health_ticks = 0U;
        update_can_state();
    }
}
