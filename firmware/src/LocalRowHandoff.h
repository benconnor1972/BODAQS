#pragma once
#include <stdint.h>
#include <stddef.h>
#include "AdcConcentratedScan.h"

// The boundary bench reserves four slots per ADC; legacy scan reserves two.
// Slots are adc*kPerAdc+channel. Values and publication identities
// travel by value; a consumer never borrows producer-owned mutable cache memory.
struct LocalAdcSnapshot {
  uint64_t capturedUs = 0;
  static constexpr unsigned kPerAdc = BODAQS_ADC_BOUNDARY_BENCH ? 4 : 2;
  static constexpr unsigned kChannels = BODAQS_ADC_DUAL_SCAN_BENCH ? 2*kPerAdc : kPerAdc;
  int32_t counts[kChannels] = {};
  uint32_t sequence[kChannels] = {};
  uint64_t acquiredUs[kChannels] = {};
  bool valid[kChannels] = {};
};
struct LocalRowFrame {
  LocalAdcSnapshot adc;
  uint64_t scheduledUnixUs = 0;
  uint64_t markTime = 0;
  uint32_t sampleId = 0;
  bool marked = false;
};
// Caller serializes queue operations, including the consumer's in-progress
// transition, with one short critical section. Reset only with both owners idle.
template<size_t Capacity> class LocalRowQueue {
 public:
  bool push(const LocalRowFrame& value) {
    if (count_ == Capacity) return false;
    slots_[(head_ + count_) % Capacity] = value;
    ++count_; return true;
  }
  bool pop(LocalRowFrame& value) {
    if (!count_) return false;
    value = slots_[head_]; head_ = (head_ + 1) % Capacity;
    --count_; return true;
  }
  size_t size() const { return count_; }
  void reset() { head_ = count_ = 0; }
 private:
  static_assert(Capacity > 0, "Handoff must have bounded nonzero capacity");
  LocalRowFrame slots_[Capacity] = {};
  size_t head_ = 0, count_ = 0;
};
