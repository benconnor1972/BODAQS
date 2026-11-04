#include <stdint.h>

#include "ti_msp_dl_config.h"

typedef struct {
    uint32_t systick_interrupts;
    uint32_t led_toggles;
} LongHfxtStartupTestInfo;

volatile LongHfxtStartupTestInfo gLongHfxtStartupTestInfo;

int main(void)
{
    SYSCFG_DL_init();

    gLongHfxtStartupTestInfo.systick_interrupts = 0U;
    gLongHfxtStartupTestInfo.led_toggles = 0U;

    DL_SYSTICK_init(CPUCLK_FREQ / 10U);
    DL_SYSTICK_enableInterrupt();
    DL_SYSTICK_enable();

    while (1) {
        __WFI();
    }
}

void SysTick_Handler(void)
{
    ++gLongHfxtStartupTestInfo.systick_interrupts;
    if ((gLongHfxtStartupTestInfo.systick_interrupts % 5U) == 0U) {
        ++gLongHfxtStartupTestInfo.led_toggles;
        DL_GPIO_togglePins(GPIO_BOARD_PORT, GPIO_BOARD_STATUS_LED_PIN);
    }
}

