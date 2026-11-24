#pragma once
#include <stdint.h>

#ifndef BODAQS_ADC_SPI_PHASE_TIMING
#define BODAQS_ADC_SPI_PHASE_TIMING 0
#endif
#if BODAQS_ADC_SPI_PHASE_TIMING != 0 && BODAQS_ADC_SPI_PHASE_TIMING != 1
#error "ADC SPI phase timing must be 0 or 1"
#endif

// Caller-owned wall-clock observation. No transfer buffers or shared ownership.
// transferUs includes HAL work and preemption, not just physical clocking.
struct SpiTransferTiming {
  uint32_t lockWaitUs = 0;
  uint32_t prepareUs = 0;
  uint32_t transferUs = 0;
  uint32_t finishUs = 0;
};
