#pragma once
// Bench codec only. Production measurement CRC already uses the byte table.
#ifndef BODAQS_SPI_PROBE_LOGGER_CRC_TABLE
#define BODAQS_SPI_PROBE_LOGGER_CRC_TABLE 1
#endif
#if BODAQS_SPI_PROBE_LOGGER_CRC_TABLE != 0 && BODAQS_SPI_PROBE_LOGGER_CRC_TABLE != 1
#error "Logger probe CRC selection must be 0 or 1"
#endif
