#include "imu_spi.h"
#include "ti_msp_dl_config.h"
/* Main-loop-owned, two-byte transaction; never used by an interrupt. */
static bool dma_active;
static volatile bool dma_done;
static uint8_t dma_tx[673], dma_rx[673];
static uint32_t dma_started;
static struct
{
    uint32_t started;
    uint8_t tx[2], sent, received, result;
    bool active;
} transfer;
void bodaqs_node_imu_cancel(void *context)
{
    (void)context;
    DL_DMA_disableChannel(DMA, DMA_IMU_TX_CHAN_ID);
    DL_DMA_disableChannel(DMA, DMA_IMU_RX_CHAN_ID);
    DL_SPI_clearInterruptStatus(IMU_SPI_INST, DL_SPI_INTERRUPT_DMA_DONE_RX);
    NVIC_ClearPendingIRQ(IMU_SPI_INST_INT_IRQN);
    dma_active = dma_done = false;
    DL_GPIO_setPins(GPIO_NODE_PORT, GPIO_NODE_IMU_CS_PIN);
    /* Reset removes queued TX, not just CS. Generated initialization restores the
     * configured mode/clock, with its fixed power-startup delay only. */
    DL_SPI_reset(IMU_SPI_INST);
    DL_SPI_enablePower(IMU_SPI_INST);
    delay_cycles(POWER_STARTUP_DELAY);
    SYSCFG_DL_IMU_SPI_init();
    transfer.active = false;
}
int bodaqs_node_imu_register(void *context, bool write, uint8_t address, uint8_t *value,
                             uint32_t now)
{
    uint8_t rx;
    unsigned n;
    (void)context;
    if (dma_active) return -1;
    if (!transfer.active)
    {
        for (n = 0; n < 4; n++)
            if (!DL_SPI_receiveDataCheck8(IMU_SPI_INST, &rx))
                break;
        transfer.tx[0] = write ? (address & 0x7f) : (address | 0x80);
        transfer.tx[1] = write ? *value : 0;
        transfer.sent = 0;
        transfer.received = 0;
        transfer.started = now;
        transfer.active = true;
        DL_GPIO_clearPins(GPIO_NODE_PORT, GPIO_NODE_IMU_CS_PIN);
    }
    if ((uint32_t)(now - transfer.started) >= 5)
    {
        bodaqs_node_imu_cancel(NULL);
        return -1;
    }
    for (n = 0; n < 2; n++)
    {
        if (transfer.sent < 2 &&
            DL_SPI_transmitDataCheck8(IMU_SPI_INST, transfer.tx[transfer.sent]))
            ++transfer.sent;
        if (DL_SPI_receiveDataCheck8(IMU_SPI_INST, &rx))
        {
            transfer.result = rx;
            ++transfer.received;
        }
    }
    if (transfer.sent == 2 && transfer.received == 2 && !DL_SPI_isBusy(IMU_SPI_INST))
    {
        DL_GPIO_setPins(GPIO_NODE_PORT, GPIO_NODE_IMU_CS_PIN);
        transfer.active = false;
        if (!write)
            *value = transfer.result;
        return 1;
    }
    return 0;
}

bool bodaqs_node_imu_spi_pending(void) { return dma_active; }
void bodaqs_node_imu_spi_irq(void)
{
    if (DL_SPI_getPendingInterrupt(IMU_SPI_INST) == DL_SPI_IIDX_DMA_DONE_RX && dma_active)
        dma_done = true;
}
int bodaqs_node_imu_read(uint8_t address, uint16_t bytes, const uint8_t **data, uint32_t now)
{
    uint8_t junk;
    if (!bytes || bytes > 672 || transfer.active) return -1;
    if (!dma_active) {
        unsigned i;
        for (i = 0; i < 8; ++i) if (!DL_SPI_receiveDataCheck8(IMU_SPI_INST, &junk)) break;
        DL_SPI_clearInterruptStatus(IMU_SPI_INST, DL_SPI_INTERRUPT_DMA_DONE_RX);
        NVIC_ClearPendingIRQ(IMU_SPI_INST_INT_IRQN);
        dma_tx[0] = address | 0x80;
        for (i = 1; i <= bytes; ++i) dma_tx[i] = 0;
        dma_done = false;
        dma_started = now;
        DL_DMA_setSrcAddr(DMA, DMA_IMU_RX_CHAN_ID, (uint32_t)(uintptr_t)&IMU_SPI_INST->RXDATA);
        DL_DMA_setDestAddr(DMA, DMA_IMU_RX_CHAN_ID, (uint32_t)(uintptr_t)dma_rx);
        DL_DMA_setTransferSize(DMA, DMA_IMU_RX_CHAN_ID, bytes + 1U);
        DL_DMA_setSrcAddr(DMA, DMA_IMU_TX_CHAN_ID, (uint32_t)(uintptr_t)dma_tx);
        DL_DMA_setDestAddr(DMA, DMA_IMU_TX_CHAN_ID, (uint32_t)(uintptr_t)&IMU_SPI_INST->TXDATA);
        DL_DMA_setTransferSize(DMA, DMA_IMU_TX_CHAN_ID, bytes + 1U);
        dma_active = true;
        DL_GPIO_clearPins(GPIO_NODE_PORT, GPIO_NODE_IMU_CS_PIN);
        DL_DMA_enableChannel(DMA, DMA_IMU_RX_CHAN_ID);
        DL_DMA_enableChannel(DMA, DMA_IMU_TX_CHAN_ID);
    }
    if ((uint32_t)(now - dma_started) >= 5) {
        bodaqs_node_imu_cancel(NULL);
        return -1;
    }
    if (!dma_done || DL_DMA_getTransferSize(DMA, DMA_IMU_RX_CHAN_ID) != 0 ||
        DL_SPI_isBusy(IMU_SPI_INST)) return 0;
    DL_DMA_disableChannel(DMA, DMA_IMU_TX_CHAN_ID);
    DL_DMA_disableChannel(DMA, DMA_IMU_RX_CHAN_ID);
    DL_GPIO_setPins(GPIO_NODE_PORT, GPIO_NODE_IMU_CS_PIN);
    dma_active = dma_done = false;
    *data = dma_rx + 1;
    return 1;
}
