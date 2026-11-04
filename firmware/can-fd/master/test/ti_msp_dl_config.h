#ifndef MASTER_TIMING_TEST_TI_H
#define MASTER_TIMING_TEST_TI_H
#include <stdint.h>
#include <assert.h>
#define TIMA0 0
#define TIMA0_INT_IRQn 0
#define POWER_STARTUP_DELAY 0
#define IOMUX_PINCM55 55
#define IOMUX_PINCM55_PF_TIMA0_CCP3 5
#define DL_TIMER_CLOCK_BUSCLK 0
#define DL_TIMER_CLOCK_DIVIDE_1 0
#define DL_TIMER_TIMER_MODE_PERIODIC_UP 1
#define DL_TIMER_STOP 0
#define DL_TIMER_INTERM_INT_DISABLED 0
#define DL_TIMER_CC_OCTL_INIT_VAL_LOW 0
#define DL_TIMER_CC_OCTL_INV_OUT_DISABLED 0
#define DL_TIMER_CC_OCTL_SRC_FUNCVAL 0
#define DL_TIMER_CC_3_INDEX 3
#define DL_TIMER_CC_ZACT_CCP_TOGGLE 1
#define DL_TIMER_CC3_OUTPUT 8
#define DL_TIMER_DEBUG_RES_RESUME 0
#define DL_TIMER_INTERRUPT_ZERO_EVENT 1
extern uint32_t raw,count;
typedef struct {uint32_t sourceClock,divideRatio,prescale;} DL_TimerA_ClockConfig;
typedef struct {uint32_t timerMode,period,startTimer,genIntermInt,counterVal;} DL_TimerA_TimerConfig;
#define IGNORE_FN(name) static inline void name(int x) {(void)x;}
IGNORE_FN(DL_TimerA_reset)
IGNORE_FN(DL_TimerA_enablePower)
IGNORE_FN(DL_TimerA_enableClock)
IGNORE_FN(DL_TimerA_startCounter)
IGNORE_FN(NVIC_EnableIRQ)
IGNORE_FN(delay_cycles)
static inline void DL_TimerA_setClockConfig(int x,DL_TimerA_ClockConfig*c) {(void)x;assert(c->prescale==79);}
static inline void DL_TimerA_initTimerMode(int x,DL_TimerA_TimerConfig*c) {(void)x;assert(c->period==49999&&c->timerMode==1);}
static inline void DL_TimerA_setCaptureCompareOutCtl(int a,int b,int c,int d,int e) {(void)a;(void)b;(void)c;(void)d;assert(e==3);}
static inline void DL_TimerA_setCaptureCompareAction(int a,int b,int c) {(void)a;assert(b==1&&c==3);}
static inline void DL_TimerA_setCCPDirection(int a,int b) {(void)a;assert(b==8);}
static inline void DL_TimerA_setDebugReleaseBehavior(int a,int b) {(void)a;(void)b;}
static inline void DL_GPIO_initPeripheralOutputFunction(int a,int b) {assert(a==55&&b==5);}
static inline void DL_TimerA_setTimerCount(int a,uint32_t b) {(void)a;count=b;}
static inline uint32_t DL_TimerA_getTimerCount(int a) {(void)a;return count;}
static inline uint32_t DL_TimerA_getRawInterruptStatus(int a,uint32_t b) {(void)a;return raw&b;}
static inline void DL_TimerA_clearInterruptStatus(int a,uint32_t b) {(void)a;raw&=~b;}
static inline void DL_TimerA_enableInterrupt(int a,uint32_t b) {(void)a;(void)b;}
static inline uint32_t __get_PRIMASK(void) {return 0;}
static inline void __disable_irq(void) {}
static inline void __set_PRIMASK(uint32_t a) {(void)a;}
#endif
