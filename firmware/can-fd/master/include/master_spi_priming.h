#ifndef BODAQS_MASTER_SPI_PRIMING_H
#define BODAQS_MASTER_SPI_PRIMING_H
#include "../../common/transport/bodaqs_spi_bench.h"
/* Bench-only A/B control. Normal builds retain the original all-DMA sequence. */
#ifndef BODAQS_MASTER_SPI_TX_PRIME
#define BODAQS_MASTER_SPI_TX_PRIME 0
#endif
#if BODAQS_MASTER_SPI_TX_PRIME != 0 && BODAQS_MASTER_SPI_TX_PRIME != 1
#error "SPI TX priming must be 0 or 1"
#endif
#if BODAQS_MASTER_SPI_TX_PRIME && (!defined(BODAQS_SPI_MEASUREMENT_V2) || !BODAQS_SPI_MEASUREMENT_V2)
#error "SPI TX priming is restricted to the explicit v2 bench build"
#endif
#if BODAQS_CAN_SPI_BENCH_MODE && !BODAQS_MASTER_SPI_TX_PRIME
#error "Mode1 comparison keeps TX priming enabled"
#endif
#if BODAQS_SPI_BOUNDARY_TRACE && !BODAQS_MASTER_SPI_TX_PRIME
#error "SPI boundary trace keeps TX priming enabled"
#endif
#endif
