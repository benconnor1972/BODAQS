/* Compile the generated configuration through one application-owned enable
 * policy. SDK definitions are included BEFORE the scoped macro; their inline
 * implementations and all generated configuration values remain unchanged.
 * Both startup and CS retirement call the resulting SPI_A8 initializer. */
#include "ti_msp_dl_config.h"
#include "master_spi_initialization.h"

static inline void master_generated_spi_enable(SPI_Regs *spi)
{
#if BODAQS_MASTER_SPI_DISABLED_INIT
    if (spi == SPI_A8_INST) return;
#endif
    DL_SPI_enable(spi);
}

#define DL_SPI_enable master_generated_spi_enable
#include "ti_msp_dl_config.c"
#undef DL_SPI_enable
