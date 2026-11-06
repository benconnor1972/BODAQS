#ifndef TEST_TI_CONFIG_H
#define TEST_TI_CONFIG_H
#include <stdbool.h>
#include <stdint.h>
#define ACQ_CAPTURE_INST 0
#define ACQ_CAPTURE_INST_INT_IRQN 0
#define DL_TIMER_INTERRUPT_ZERO_EVENT 1U
#define DL_TIMER_INTERRUPT_CC1_UP_EVENT 2U
#define DL_TIMER_INTERRUPT_CC2_UP_EVENT 4U
#define DL_TIMER_INTERRUPT_CC3_UP_EVENT 8U
#define DL_TIMER_INTERRUPT_OVERFLOW_EVENT 16U
#define DL_TIMER_CC_1_INDEX 1
#define DL_TIMER_CC_2_INDEX 2
#define DL_TIMER_CC_3_INDEX 3
#define DL_TIMER_DEBUG_RES_RESUME 0
extern uint32_t raw, count, cc[4];
extern uint32_t test_irq_mask,test_last_clear_irq_mask;
static inline uint32_t __get_PRIMASK(void) { return test_irq_mask; }
static inline void __disable_irq(void) { test_irq_mask=1; }
static inline void __set_PRIMASK(uint32_t x) { test_irq_mask=x; }
static inline uint32_t DL_TimerA_getRawInterruptStatus(int x, uint32_t m) {
    (void)x;
    return raw & m;
}
static inline uint32_t DL_TimerA_getTimerCount(int x) {
    (void)x;
    return count;
}
static inline uint32_t DL_TimerA_getCaptureCompareValue(int x, int i) {
    (void)x;
    return cc[i];
}
static inline void DL_TimerA_clearInterruptStatus(int x, uint32_t m) {
    (void)x;
    test_last_clear_irq_mask=test_irq_mask;
    raw &= ~m;
}
static inline void DL_TimerA_setTimerCount(int x, uint32_t y) {
    (void)x;
    count = y;
}
static inline void DL_TimerA_startCounter(int x) { (void)x; }
static inline void DL_TimerA_setDebugReleaseBehavior(int x, int y) {
    (void)x;
    (void)y;
}
static inline void NVIC_EnableIRQ(int x) { (void)x; }

#define GPIO_NODE_PORT 0
#define GPIO_NODE_IMU_CS_PIN 1
#define DMA 0
#define DMA_IMU_TX_CHAN_ID 0
#define DMA_IMU_RX_CHAN_ID 1
#define DL_SPI_INTERRUPT_DMA_DONE_RX 1
#define DL_SPI_IIDX_DMA_DONE_RX 1
#define IMU_SPI_INST_INT_IRQN 1
#define POWER_STARTUP_DELAY 0
struct TestSpi {
    uint32_t RXDATA, TXDATA;
};
extern struct TestSpi test_spi;
#define IMU_SPI_INST (&test_spi)
void DL_GPIO_setPins(int, int);
void DL_GPIO_clearPins(int, int);
void DL_DMA_disableChannel(int, int);
void DL_DMA_enableChannel(int, int);
void DL_DMA_setSrcAddr(int, int, uint32_t);
void DL_DMA_setDestAddr(int, int, uint32_t);
void DL_DMA_setTransferSize(int, int, uint32_t);
uint16_t DL_DMA_getTransferSize(int, int);
void DL_SPI_clearInterruptStatus(struct TestSpi *, uint32_t);
uint32_t DL_SPI_getPendingInterrupt(struct TestSpi *);
bool DL_SPI_receiveDataCheck8(struct TestSpi *, uint8_t *);
bool DL_SPI_transmitDataCheck8(struct TestSpi *, uint8_t);
bool DL_SPI_isBusy(struct TestSpi *);
void DL_SPI_reset(struct TestSpi *);
void DL_SPI_enablePower(struct TestSpi *);
void SYSCFG_DL_IMU_SPI_init(void);
void NVIC_ClearPendingIRQ(int);
static inline void delay_cycles(int x) { (void)x; }
#endif
