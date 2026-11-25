#pragma once

#include <atomic>
#include <stddef.h>
#include <stdint.h>
#include <cstring>
#include <type_traits>

// Single acquisition owner publishes; observers make one bounded copy and never
// touch the recording queue. Atomic words prevent C++ data races during a copy,
// including on the ESP32's 32-bit cores. A changing generation rejects the copy.
template <typename T>
class BMI270PublishedSnapshot {
public:
  static_assert(std::is_trivially_copyable<T>::value, "snapshot must be copyable");
  static_assert(std::atomic<uint32_t>::is_always_lock_free, "snapshot words must be lock free");

  // Call only after the producer retires, before beginning a new session.
  void invalidate() {
    available_.store(false);
    generation_.fetch_add(2);
  }

  void publish(const T& value) {
    uint32_t words[kWords] {};
    std::memcpy(words, &value, sizeof(value));
    generation_.fetch_add(1);
    for (size_t i = 0; i < kWords; ++i) words_[i].store(words[i]);
    generation_.fetch_add(1);
    available_.store(true);
  }

  bool read(T& value) const {
    const uint32_t before = generation_.load();
    if (!available_.load() || (before & 1u)) return false;
    uint32_t words[kWords];
    for (size_t i = 0; i < kWords; ++i) words[i] = words_[i].load();
    if (generation_.load() != before || !available_.load()) return false;
    std::memcpy(&value, words, sizeof(value));
    return true;
  }

private:
  static constexpr size_t kWords = (sizeof(T) + sizeof(uint32_t) - 1) / sizeof(uint32_t);
  std::atomic<uint32_t> generation_ { 0 };
  std::atomic<bool> available_ { false };
  std::atomic<uint32_t> words_[kWords] {};
};
