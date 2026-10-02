#pragma once

#include <stddef.h>
#include <stdint.h>

#include "BdqV2Format.h"

// Type-erased boundary between a native-rate producer queue and the single
// storage consumer. Source callbacks must be non-blocking. Only the storage
// consumer may call the pop callbacks.
struct BdqV2StreamSource {
  uint16_t streamId = 0;
  uint16_t recordSizeBytes = 0;
  uint64_t nativeTickModulus = 0;
  void* context = nullptr;

  size_t (*pendingRecords)(const void* context) = nullptr;
  size_t (*pendingObservations)(const void* context) = nullptr;
  bool (*popRecord)(void* context, uint8_t* destination, size_t capacity) = nullptr;
  bool (*popObservation)(void* context, BdqV2Format::TimeObservation& value) = nullptr;

  bool valid() const {
    return streamId != 0 &&
           recordSizeBytes >= BdqV2Format::kStreamRecordPrefixBytes &&
           nativeTickModulus != 0 &&
           nativeTickModulus <= (uint64_t{1} << 32) &&
           context && pendingRecords && pendingObservations &&
           popRecord && popObservation;
  }
};

