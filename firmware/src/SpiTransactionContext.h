#pragma once
#include <stdint.h>

// Observation only. Copied under the bus mutex, never consulted by scheduling.
// Times are micros() modulo 2^32; subtract unsigned within one wrap interval.
struct SpiTransactionContext {
  uint32_t sequence=0, selectedUs=0, releasedUs=0, previousReleaseUs=0;
  uint16_t bytes=0;
  uint16_t previousBytes=0;
  int8_t cs=-1, previousCs=-1;
  uint8_t command=0;
  uint8_t previousCommand=0;
  bool previousCommandValid=false;
  bool valid=false, previousValid=false, commandValid=false;
  uint32_t deviceSequence=0;
  bool deviceSequenceValid=false;
};
