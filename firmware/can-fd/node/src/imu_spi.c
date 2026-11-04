#include "imu_spi.h"
#include "ti_msp_dl_config.h"
/* Main-loop-owned, two-byte transaction; never used by an interrupt. */
static struct
{
    uint32_t started;
    uint8_t tx[2], sent, received, result;
    bool active;
} transfer;
void bodaqs_node_imu_cancel(void *context)
{
    (void)context;
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
