#pragma once
#include <stdint.h>
#include "SpiTransactionContext.h"

// Diagnostic storage only; never a wire representation. Fixed v2 reply size.
struct MeasurementReplyCapture {
  static constexpr unsigned capacity=4, replyBytes=256;
  struct Entry {
    uint32_t slot=0; // One-based physical exchange ordinal in measurement timing.
    uint8_t requestKind=0; // MOSI kind; MISO belongs to its own pipelined identity.
    uint8_t decodeReason=0;
    SpiTransactionContext bus;
    uint8_t reply[replyBytes]={};
  };
  unsigned count=0;
  Entry entries[capacity];
};
