#pragma once
#include <atomic>
#include <stdint.h>

// One acquisition owner publishes. UI/calibration readers never acquire hardware
// or wait for the owner. Atomic members avoid a data race even if publication
// overlaps a read; a changed generation rejects the incomplete observation.
class PublishedSensorCounts {
public:
  struct Value { int32_t counts=0; uint32_t tickUs=0; uint16_t status=0; };
  // Reset only while the acquisition owner is retired.
  void invalidate() { generation_.store(0); }
  void publish(int32_t counts, uint32_t tickUs, uint16_t status=0) {
    generation_.fetch_add(1);
    counts_.store(counts); tick_.store(tickUs); status_.store(status);
    generation_.fetch_add(1);
  }
  bool read(Value& value) const {
    const auto before=generation_.load();
    if(!before || (before&1u)) return false;
    Value candidate{counts_.load(),tick_.load(),static_cast<uint16_t>(status_.load())};
    if(generation_.load()!=before) return false;
    value=candidate;
    return true;
  }
private:
  std::atomic<uint32_t> generation_{0},tick_{0},status_{0};
  std::atomic<int32_t> counts_{0};
};
