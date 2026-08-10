#pragma once

#include <atomic>
#include <stddef.h>
#include <stdint.h>

// Fixed-capacity, allocation-free queue for one producer and one consumer.
// The producer owns tail and the consumer owns head. Monotonic uint32_t
// counters make every array slot usable and remain correct across wrap while
// the live distance is less than 2^31.
template <typename T, size_t Capacity>
class FixedSpscQueue {
public:
  static_assert(Capacity > 0, "queue capacity must be non-zero");
  static_assert((Capacity & (Capacity - 1)) == 0,
                "queue capacity must be a power of two");
  static_assert(Capacity < (UINT32_MAX / 2u), "queue capacity is too large");
  static_assert(std::atomic<uint32_t>::is_always_lock_free,
                "queue indices must be lock-free on the target");

  static constexpr size_t capacity() { return Capacity; }

  bool push(const T& value, size_t* depthAfter = nullptr) {
    const uint32_t tail = tail_.load(std::memory_order_relaxed);
    const uint32_t head = head_.load(std::memory_order_acquire);
    if (tail - head >= Capacity) return false;

    entries_[tail & kIndexMask] = value;
    tail_.store(tail + 1u, std::memory_order_release);
    if (depthAfter) *depthAfter = static_cast<size_t>((tail + 1u) - head);
    return true;
  }

  bool pop(T& value, size_t* depthAfter = nullptr) {
    const uint32_t head = head_.load(std::memory_order_relaxed);
    const uint32_t tail = tail_.load(std::memory_order_acquire);
    if (head == tail) return false;

    value = entries_[head & kIndexMask];
    head_.store(head + 1u, std::memory_order_release);
    if (depthAfter) *depthAfter = static_cast<size_t>(tail - (head + 1u));
    return true;
  }

  size_t size() const {
    const uint32_t head = head_.load(std::memory_order_acquire);
    const uint32_t tail = tail_.load(std::memory_order_acquire);
    return static_cast<size_t>(tail - head);
  }

  bool empty() const { return size() == 0; }

  // Call only while producer and consumer are stopped.
  void clear() {
    head_.store(0, std::memory_order_relaxed);
    tail_.store(0, std::memory_order_relaxed);
  }

private:
  static constexpr uint32_t kIndexMask = static_cast<uint32_t>(Capacity - 1u);

  T entries_[Capacity] {};
  alignas(4) std::atomic<uint32_t> head_ { 0 };
  alignas(4) std::atomic<uint32_t> tail_ { 0 };
};
