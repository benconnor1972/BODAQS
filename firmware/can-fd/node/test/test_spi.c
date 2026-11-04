#include "imu_spi.h"
#include "ti_msp_dl_config.h"
#include <assert.h>
#include <string.h>
struct TestSpi test_spi;
uint32_t raw, count, cc[4];
static uintptr_t src[2], dst[2];
static uint32_t sizes[2];
static bool enabled[2], cs, busy, irq;
static unsigned arm_order;
static uintptr_t address(uint32_t low) {
    return ((uintptr_t)&test_spi & ~(uintptr_t)UINT32_MAX) | low;
}
void DL_GPIO_setPins(int p, int m) {
    (void)p;
    (void)m;
    cs = false;
}
void DL_GPIO_clearPins(int p, int m) {
    (void)p;
    (void)m;
    cs = true;
}
void DL_DMA_disableChannel(int d, int c) {
    (void)d;
    enabled[c] = false;
}
void DL_DMA_enableChannel(int d, int c) {
    (void)d;
    assert(cs);
    enabled[c] = true;
    arm_order = 10 * arm_order + (unsigned)c + 1;
}
void DL_DMA_setSrcAddr(int d, int c, uint32_t v) {
    (void)d;
    src[c] = address(v);
}
void DL_DMA_setDestAddr(int d, int c, uint32_t v) {
    (void)d;
    dst[c] = address(v);
}
void DL_DMA_setTransferSize(int d, int c, uint32_t n) {
    (void)d;
    sizes[c] = n;
}
uint16_t DL_DMA_getTransferSize(int d, int c) {
    (void)d;
    return (uint16_t)sizes[c];
}
void DL_SPI_clearInterruptStatus(struct TestSpi *s, uint32_t m) {
    (void)s;
    (void)m;
    irq = false;
}
uint32_t DL_SPI_getPendingInterrupt(struct TestSpi *s) {
    (void)s;
    bool v = irq;
    irq = false;
    return v ? 1 : 0;
}
bool DL_SPI_receiveDataCheck8(struct TestSpi *s, uint8_t *p) {
    (void)s;
    (void)p;
    return false;
}
bool DL_SPI_transmitDataCheck8(struct TestSpi *s, uint8_t b) {
    (void)s;
    (void)b;
    return false;
}
bool DL_SPI_isBusy(struct TestSpi *s) {
    (void)s;
    return busy;
}
void DL_SPI_reset(struct TestSpi *s) { (void)s; }
void DL_SPI_enablePower(struct TestSpi *s) { (void)s; }
void SYSCFG_DL_IMU_SPI_init(void) {}
void NVIC_ClearPendingIRQ(int n) { (void)n; }
int main(void) {
    const uint8_t *p = 0;
    assert(bodaqs_node_imu_read(0x78, 672, &p, 0) == 0);
    assert(cs && enabled[0] && enabled[1] && arm_order == 21);
    assert(sizes[0] == 673 && sizes[1] == 673 && *(uint8_t *)src[0] == 0xf8);
    memset((void *)dst[1], 0xee, 673);
    ((uint8_t *)dst[1])[1] = 0x08;
    sizes[1] = 0;
    irq = true;
    busy = true;
    bodaqs_node_imu_spi_irq();
    assert(bodaqs_node_imu_read(0x78, 672, &p, 1) == 0 && cs);
    busy = false;
    assert(bodaqs_node_imu_read(0x78, 672, &p, 2) == 1);
    assert(!cs && !enabled[0] && !enabled[1] && p[0] == 8 && p[671] == 0xee);
    assert(bodaqs_node_imu_read(0x78, 672, &p, 10) == 0);
    assert(bodaqs_node_imu_read(0x78, 672, &p, 15) == -1);
    assert(!cs && !enabled[0] && !enabled[1]);
    irq = true;
    bodaqs_node_imu_spi_irq();
    assert(bodaqs_node_imu_read(0x78, 672, &p, 16) == 0);
    assert(bodaqs_node_imu_read(0x78, 672, &p, 17) == 0);
    /* A stale completion interrupt after rearm cannot complete a new DMA block. */
    irq = true;
    bodaqs_node_imu_spi_irq();
    assert(bodaqs_node_imu_read(0x78, 672, &p, 18) == 0 && cs && sizes[1] == 673);
    bodaqs_node_imu_cancel(0);
    assert(!cs && !enabled[0] && !enabled[1]);
    return 0;
}
