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
#if defined(BODAQS_SPI_BOUNDARY_TRACE) && BODAQS_SPI_BOUNDARY_TRACE
    uint8_t request[replyBytes]={};
    bool requestValid=false;
#endif
  };
  unsigned count=0;
  Entry entries[capacity];
#if defined(BODAQS_SPI_BOUNDARY_TRACE) && BODAQS_SPI_BOUNDARY_TRACE
  struct BoundaryProbe {
    bool attempted=false,transferred=false,adjacent=false;
    uint32_t nonce=0,failedDeviceSequence=0,markerDeviceSequence=0,durationUs=0;
  } boundary;
#endif
};
