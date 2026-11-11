#ifndef BODAQS_MASTER_SPI_INITIALIZATION_H
#define BODAQS_MASTER_SPI_INITIALIZATION_H
#include "master_spi_priming.h"

/* r9 master-only control; normal initialization keeps its existing behavior. */
#ifndef BODAQS_MASTER_SPI_DISABLED_INIT
#define BODAQS_MASTER_SPI_DISABLED_INIT 0
#endif
#if BODAQS_MASTER_SPI_DISABLED_INIT != 0 && BODAQS_MASTER_SPI_DISABLED_INIT != 1
#error "Disabled SPI initialization must be 0 or 1"
#endif
#if BODAQS_MASTER_SPI_DISABLED_INIT && (!BODAQS_MASTER_SPI_TX_PRIME || BODAQS_CAN_SPI_BENCH_MODE != 0)
#error "Disabled SPI initialization requires the explicit primed mode0 v2 build"
#endif
#endif
