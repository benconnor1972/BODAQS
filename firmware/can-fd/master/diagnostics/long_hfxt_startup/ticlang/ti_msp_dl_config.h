/*
 * Copyright (c) 2023, Texas Instruments Incorporated - http://www.ti.com
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * *  Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *
 * *  Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * *  Neither the name of Texas Instruments Incorporated nor the names of
 *    its contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
 * THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 * EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
 * OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
 * WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
 * OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
 * EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/*
 *  ============ ti_msp_dl_config.h =============
 *  Configured MSPM0 DriverLib module declarations
 *
 *  DO NOT EDIT - This file is generated for the MSPM0G351X
 *  by the SysConfig tool.
 */
#ifndef ti_msp_dl_config_h
#define ti_msp_dl_config_h

#define CONFIG_MSPM0G351X
#define CONFIG_MSPM0G3518

#if defined(__ti_version__) || defined(__TI_COMPILER_VERSION__)
#define SYSCONFIG_WEAK __attribute__((weak))
#elif defined(__IAR_SYSTEMS_ICC__)
#define SYSCONFIG_WEAK __weak
#elif defined(__GNUC__)
#define SYSCONFIG_WEAK __attribute__((weak))
#endif

#include <ti/devices/msp/msp.h>
#include <ti/driverlib/driverlib.h>
#include <ti/driverlib/m0p/dl_core.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 *  ======== SYSCFG_DL_init ========
 *  Perform all required MSP DL initialization
 *
 *  This function should be called once at a point before any use of
 *  MSP DL.
 */


/* clang-format off */

#define POWER_STARTUP_DELAY                                                (16)


#define GPIO_HFXT_PORT                                                     GPIOA
#define GPIO_HFXIN_PIN                                             DL_GPIO_PIN_5
#define GPIO_HFXIN_IOMUX                                         (IOMUX_PINCM10)
#define GPIO_HFXOUT_PIN                                            DL_GPIO_PIN_6
#define GPIO_HFXOUT_IOMUX                                        (IOMUX_PINCM11)
#define CPUCLK_FREQ                                                     80000000
/* Defines for SYSPLL_ERR_01 Workaround */
/* Represent 1.000 as 1000 */
#define FLOAT_TO_INT_SCALE                                               (1000U)
#define FCC_EXPECTED_RATIO                                                  5000
#define FCC_UPPER_BOUND                       (FCC_EXPECTED_RATIO * (1 + 0.003))
#define FCC_LOWER_BOUND                       (FCC_EXPECTED_RATIO * (1 - 0.003))

bool SYSCFG_DL_SYSCTL_SYSPLL_init(void);



/* Port definition for Pin Group GPIO_BOARD */
#define GPIO_BOARD_PORT                                                  (GPIOA)

/* Defines for BUCK_ENABLE: GPIOA.18 with pinCMx 40 on package pin 11 */
#define GPIO_BOARD_BUCK_ENABLE_PIN                              (DL_GPIO_PIN_18)
#define GPIO_BOARD_BUCK_ENABLE_IOMUX                             (IOMUX_PINCM40)
/* Defines for FRONT_ENABLE: GPIOA.7 with pinCMx 14 on package pin 49 */
#define GPIO_BOARD_FRONT_ENABLE_PIN                              (DL_GPIO_PIN_7)
#define GPIO_BOARD_FRONT_ENABLE_IOMUX                            (IOMUX_PINCM14)
/* Defines for REAR_ENABLE: GPIOA.12 with pinCMx 34 on package pin 5 */
#define GPIO_BOARD_REAR_ENABLE_PIN                              (DL_GPIO_PIN_12)
#define GPIO_BOARD_REAR_ENABLE_IOMUX                             (IOMUX_PINCM34)
/* Defines for STATUS_LED: GPIOA.14 with pinCMx 36 on package pin 7 */
#define GPIO_BOARD_STATUS_LED_PIN                               (DL_GPIO_PIN_14)
#define GPIO_BOARD_STATUS_LED_IOMUX                              (IOMUX_PINCM36)
/* Defines for FRONT_FAULT: GPIOA.21 with pinCMx 46 on package pin 17 */
#define GPIO_BOARD_FRONT_FAULT_PIN                              (DL_GPIO_PIN_21)
#define GPIO_BOARD_FRONT_FAULT_IOMUX                             (IOMUX_PINCM46)
/* Defines for REAR_FAULT: GPIOA.22 with pinCMx 47 on package pin 18 */
#define GPIO_BOARD_REAR_FAULT_PIN                               (DL_GPIO_PIN_22)
#define GPIO_BOARD_REAR_FAULT_IOMUX                              (IOMUX_PINCM47)


/* clang-format on */

void SYSCFG_DL_init(void);
void SYSCFG_DL_initPower(void);
void SYSCFG_DL_GPIO_init(void);
void SYSCFG_DL_SYSCTL_init(void);
void SYSCFG_DL_SYSCTL_CLK_init(void);

bool SYSCFG_DL_SYSCTL_SYSPLL_init(void);



#ifdef __cplusplus
}
#endif

#endif /* ti_msp_dl_config_h */
