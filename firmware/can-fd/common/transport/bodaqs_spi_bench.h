#ifndef BODAQS_SPI_BENCH_H
#define BODAQS_SPI_BENCH_H
/* Explicit paired bench images only. Normal firmware remains mode0. */
#ifndef BODAQS_CAN_SPI_BENCH_MODE
#define BODAQS_CAN_SPI_BENCH_MODE 0
#endif
#if BODAQS_CAN_SPI_BENCH_MODE != 0 && BODAQS_CAN_SPI_BENCH_MODE != 1
#error "CAN SPI bench mode must be 0 or 1"
#endif
#if BODAQS_CAN_SPI_BENCH_MODE && (!defined(BODAQS_SPI_MEASUREMENT_V2) || !BODAQS_SPI_MEASUREMENT_V2)
#error "CAN SPI mode1 is restricted to the explicit v2 bench build"
#endif
#endif
