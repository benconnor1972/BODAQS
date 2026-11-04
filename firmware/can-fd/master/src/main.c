#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "bodaqs_can_network.h"
#include "bodaqs_master_service.h"
#include "bodaqs_node_inventory.h"
#include "master_identity.h"
#include "ti_msp_dl_config.h"

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
    uint32_t buck_gpio_doe31_0;
    uint32_t buck_gpio_dout31_0;
    uint32_t buck_gpio_din31_0;
    uint32_t can_rx_frames;
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

volatile MasterRuntimeInfo gMasterRuntimeInfo;
BodaqsNodeInventory gNodeInventory;

static BodaqsMasterService gService;
static BodaqsMasterDiscoveryRecord
    gDiscoveryRecords[BODAQS_MASTER_DISCOVERY_NODE_COUNT];
static uint8_t gTransmitSlots[2][BODAQS_MASTER_SLOT_BYTES];
static uint8_t gReceiveSlots[2][BODAQS_MASTER_SLOT_BYTES];
static uint8_t gTransmitIndex;
static uint8_t gReceiveIndex;
static volatile uint32_t gUptimeMs;
static volatile bool gDiscoveryDue;
static uint16_t gDiscoveryTransaction;
static uint32_t gDiscoveryNonce;
static volatile bool gCanRecoveryDue;
static volatile uint32_t gCanRecoveryDueMs;
static bool gCanWasBusOff;
static bool gLoggerCommunicationEstablished;

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

    gMasterRuntimeInfo.can_initialized =
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

static void process_can_message(const DL_MCAN_RxBufElement *message)
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
            &gNodeInventory, &announce, gUptimeMs);
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
                &gNodeInventory, node_address, &status, gUptimeMs);
        }
        return;
    }

    ++gMasterRuntimeInfo.can_unknown_frames;
}

static void drain_can_receive_fifo(void)
{
    DL_MCAN_RxBufElement message;
    DL_MCAN_RxFIFOStatus fifo_status = {0};

    fifo_status.num = DL_MCAN_RX_FIFO_NUM_0;
    DL_MCAN_getRxFIFOStatus(MCAN0_INST, &fifo_status);
    gMasterRuntimeInfo.can_rx_queue_depth =
        (uint16_t) fifo_status.fillLvl;
    if (fifo_status.fillLvl >
        gMasterRuntimeInfo.can_rx_queue_high_water) {
        gMasterRuntimeInfo.can_rx_queue_high_water =
            (uint16_t) fifo_status.fillLvl;
    }

    while (fifo_status.fillLvl != 0U) {
        DL_MCAN_readMsgRam(MCAN0_INST, DL_MCAN_MEM_TYPE_FIFO, 0U,
            fifo_status.num, &message);
        DL_MCAN_writeRxFIFOAck(
            MCAN0_INST, fifo_status.num, fifo_status.getIdx);
        ++gMasterRuntimeInfo.can_rx_frames;
        process_can_message(&message);
        DL_MCAN_getRxFIFOStatus(MCAN0_INST, &fifo_status);
    }
    gMasterRuntimeInfo.can_rx_queue_depth = 0U;
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

static bool wait_for_spi_chip_select_inactive(void)
{
    uint32_t timeout = CPUCLK_FREQ / 100U;

    while ((DL_GPIO_readPins(GPIO_SPI_A8_CS_PORT,
                GPIO_SPI_A8_CS_PIN) == 0U) && (timeout != 0U)) {
        --timeout;
    }
    return timeout != 0U;
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
        DMA, DMA_SPI_TX_CHAN_ID, BODAQS_MASTER_SLOT_BYTES);

    DL_DMA_setSrcAddr(DMA, DMA_SPI_RX_CHAN_ID,
        (uint32_t) &SPI_A8_INST->RXDATA);
    DL_DMA_setDestAddr(DMA, DMA_SPI_RX_CHAN_ID,
        (uint32_t) &gReceiveSlots[gReceiveIndex][0]);
    DL_DMA_setTransferSize(
        DMA, DMA_SPI_RX_CHAN_ID, BODAQS_MASTER_SLOT_BYTES);

    DL_DMA_enableChannel(DMA, DMA_SPI_RX_CHAN_ID);
    DL_DMA_enableChannel(DMA, DMA_SPI_TX_CHAN_ID);
}

static void recover_spi_transport(void)
{
    DL_DMA_disableChannel(DMA, DMA_SPI_RX_CHAN_ID);
    DL_DMA_disableChannel(DMA, DMA_SPI_TX_CHAN_ID);
    DL_SPI_disable(SPI_A8_INST);
    DL_SPI_reset(SPI_A8_INST);
    DL_SPI_enablePower(SPI_A8_INST);
    delay_cycles(POWER_STARTUP_DELAY);
    SYSCFG_DL_SPI_A8_init();
    SYSCFG_DL_DMA_init();

    memset(gTransmitSlots, 0, sizeof(gTransmitSlots));
    memset(gReceiveSlots, 0, sizeof(gReceiveSlots));
    gTransmitIndex = 0U;
    gReceiveIndex = 0U;
    ++gMasterRuntimeInfo.spi_recoveries;
    arm_spi_slot();
}

static void update_runtime_info(void)
{
    uint8_t node;

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
    status.can_rx_queue_depth = gMasterRuntimeInfo.can_rx_queue_depth;
    status.can_rx_queue_high_water =
        gMasterRuntimeInfo.can_rx_queue_high_water;
    bodaqs_master_service_set_status(&gService, &status);

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

int main(void)
{
    BodaqsMasterIdentity identity;
    uint32_t reset_cause = (uint32_t) DL_SYSCTL_getResetCause();

    normalize_retained_clocks();
    SYSCFG_DL_init();

    memset(gTransmitSlots, 0, sizeof(gTransmitSlots));
    memset(gReceiveSlots, 0, sizeof(gReceiveSlots));
    memset((void *) &gMasterRuntimeInfo, 0, sizeof(gMasterRuntimeInfo));
    gMasterRuntimeInfo.reset_cause = reset_cause;

    identity = master_identity_read();
    bodaqs_master_service_init(&gService, &identity);
    bodaqs_node_inventory_init(&gNodeInventory);
    gTransmitIndex = 0U;
    gReceiveIndex = 0U;
    gUptimeMs = 0U;
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
    DL_SYSTICK_init(CPUCLK_FREQ / 10U);
    DL_SYSTICK_enableInterrupt();
    DL_SYSTICK_enable();
    NVIC_EnableIRQ(SPI_A8_INST_INT_IRQN);
    NVIC_EnableIRQ(MCAN0_INST_INT_IRQN);

    while (1) {
        if (gDiscoveryDue) {
            gDiscoveryDue = false;
            send_discovery_request();
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
        if ((interrupt_status & gCanErrorInterruptMask) != 0U) {
            ++gMasterRuntimeInfo.can_error_events;
        }
        if ((interrupt_status & DL_MCAN_INTERRUPT_TC) != 0U) {
            ++gMasterRuntimeInfo.can_tx_frames;
        }
        if ((interrupt_status & (DL_MCAN_INTERRUPT_RF0N |
                DL_MCAN_INTERRUPT_RF0W |
                DL_MCAN_INTERRUPT_RF0F)) != 0U) {
            drain_can_receive_fifo();
        }
        update_can_state();
    }
}

void SPI_A8_INST_IRQHandler(void)
{
    if (DL_SPI_getPendingInterrupt(SPI_A8_INST) ==
        DL_SPI_IIDX_DMA_DONE_RX) {
        uint8_t next_transmit_index = gTransmitIndex ^ 1U;
        BodaqsMasterSlotResult result;

        /*
         * DMA completion can precede the controller releasing chip select.
         * Do not rearm either DMA channel inside the previous slot boundary.
         */
        if (!wait_for_spi_chip_select_inactive()) {
            ++gMasterRuntimeInfo.cs_release_timeouts;
            recover_spi_transport();
            update_runtime_info();
            return;
        }

        update_service_status();
        result = bodaqs_master_service_process_slot(&gService,
            gReceiveSlots[gReceiveIndex],
            gTransmitSlots[next_transmit_index]);
        if (BODAQS_ENABLE_BUCK && BODAQS_ENABLE_FRONT_BRANCH &&
            !gLoggerCommunicationEstablished &&
            ((gService.probes_received != 0U) ||
                (gService.status_requests_received != 0U))) {
            gLoggerCommunicationEstablished = true;
            DL_GPIO_setPins(
                GPIO_BOARD_PORT, GPIO_BOARD_FRONT_ENABLE_PIN);
        }
        if (result == BODAQS_MASTER_SLOT_MALFORMED) {
            recover_spi_transport();
        } else {
            gTransmitIndex = next_transmit_index;
            gReceiveIndex ^= 1U;
            arm_spi_slot();
        }
        update_runtime_info();
    }
}

void SysTick_Handler(void)
{
    static uint8_t heartbeat_ticks;
    static uint16_t discovery_ticks;

    gUptimeMs += 100U;
    ++heartbeat_ticks;
    if (heartbeat_ticks >= 5U) {
        heartbeat_ticks = 0U;
        DL_GPIO_togglePins(GPIO_BOARD_PORT, GPIO_BOARD_STATUS_LED_PIN);
    }
    ++discovery_ticks;
    if (discovery_ticks >= (DISCOVERY_INTERVAL_MS / 100U)) {
        discovery_ticks = 0U;
        gDiscoveryDue = true;
    }
    bodaqs_node_inventory_update_stale(
        &gNodeInventory, gUptimeMs, NODE_STALE_AFTER_MS);
    update_runtime_info();
}

