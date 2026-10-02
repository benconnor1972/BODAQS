#pragma once

#include <atomic>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <type_traits>

#if defined(ESP32)
#include <esp_heap_caps.h>
#endif

namespace DynamicSpscQueueDetail {

inline void* allocateBytes(size_t bytes) {
  if (bytes == 0) return nullptr;
#if defined(ESP32)
  void* memory = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!memory) memory = heap_caps_malloc(bytes, MALLOC_CAP_8BIT);
  return memory;
#else
  return malloc(bytes);
#endif
}

inline void releaseBytes(void* memory) {
  if (!memory) return;
#if defined(ESP32)
  heap_caps_free(memory);
#else
  free(memory);
#endif
}

constexpr bool isPowerOfTwo(size_t value) {
  return value != 0 && (value & (value - 1u)) == 0;
}

}  // namespace DynamicSpscQueueDetail

// Runtime-sized, allocation-on-configuration SPSC queue. Queue memory is
// preferentially placed in PSRAM on ESP32 targets so rate-dependent logging
// buffers do not consume scarce internal RAM. Allocation and release are only
// valid while producer and consumer are stopped.
template <typename T>
class DynamicSpscQueue {
public:
  static_assert(std::is_trivially_copyable_v<T>,
                "dynamic SPSC entries must be trivially copyable");
  static_assert(std::atomic<uint32_t>::is_always_lock_free,
                "queue indices must be lock-free on the target");

  DynamicSpscQueue() = default;
  ~DynamicSpscQueue() { release(); }

  DynamicSpscQueue(const DynamicSpscQueue&) = delete;
  DynamicSpscQueue& operator=(const DynamicSpscQueue&) = delete;

  bool allocate(size_t capacity) {
    if (!DynamicSpscQueueDetail::isPowerOfTwo(capacity) ||
        capacity >= (UINT32_MAX / 2u) || !empty()) {
      return false;
    }
    if (entries_ && capacity_ == capacity) {
      clear();
      return true;
    }
    if (capacity > SIZE_MAX / sizeof(T)) return false;
    void* memory = DynamicSpscQueueDetail::allocateBytes(capacity * sizeof(T));
    if (!memory) return false;
    release();
    entries_ = static_cast<T*>(memory);
    capacity_ = capacity;
    mask_ = static_cast<uint32_t>(capacity - 1u);
    clear();
    return true;
  }

  void release() {
    DynamicSpscQueueDetail::releaseBytes(entries_);
    entries_ = nullptr;
    capacity_ = 0;
    mask_ = 0;
    head_.store(0, std::memory_order_relaxed);
    tail_.store(0, std::memory_order_relaxed);
  }

  bool push(const T& value, size_t* depthAfter = nullptr) {
    if (!entries_) return false;
    const uint32_t tail = tail_.load(std::memory_order_relaxed);
    const uint32_t head = head_.load(std::memory_order_acquire);
    if (tail - head >= capacity_) return false;
    memcpy(&entries_[tail & mask_], &value, sizeof(T));
    tail_.store(tail + 1u, std::memory_order_release);
    if (depthAfter) *depthAfter = static_cast<size_t>((tail + 1u) - head);
    return true;
  }

  bool pop(T& value, size_t* depthAfter = nullptr) {
    if (!entries_) return false;
    const uint32_t head = head_.load(std::memory_order_relaxed);
    const uint32_t tail = tail_.load(std::memory_order_acquire);
    if (head == tail) return false;
    memcpy(&value, &entries_[head & mask_], sizeof(T));
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
  size_t capacity() const { return capacity_; }

  void clear() {
    head_.store(0, std::memory_order_relaxed);
    tail_.store(0, std::memory_order_relaxed);
  }

private:
  T* entries_ = nullptr;
  size_t capacity_ = 0;
  uint32_t mask_ = 0;
  alignas(4) std::atomic<uint32_t> head_ { 0 };
  alignas(4) std::atomic<uint32_t> tail_ { 0 };
};

// Variable-record-size form used by the compact BDQ primary stream. Every
// record in one session has the same schema-defined size.
class DynamicSpscRecordQueue {
public:
  DynamicSpscRecordQueue() = default;
  ~DynamicSpscRecordQueue() { release(); }

  DynamicSpscRecordQueue(const DynamicSpscRecordQueue&) = delete;
  DynamicSpscRecordQueue& operator=(const DynamicSpscRecordQueue&) = delete;

  bool allocate(size_t recordSize, size_t capacity) {
    if (recordSize == 0 ||
        !DynamicSpscQueueDetail::isPowerOfTwo(capacity) ||
        capacity >= (UINT32_MAX / 2u) || !empty() ||
        capacity > SIZE_MAX / recordSize) {
      return false;
    }
    if (entries_ && recordSize_ == recordSize && capacity_ == capacity) {
      clear();
      return true;
    }
    void* memory =
        DynamicSpscQueueDetail::allocateBytes(recordSize * capacity);
    if (!memory) return false;
    release();
    entries_ = static_cast<uint8_t*>(memory);
    recordSize_ = recordSize;
    capacity_ = capacity;
    mask_ = static_cast<uint32_t>(capacity - 1u);
    clear();
    return true;
  }

  void release() {
    DynamicSpscQueueDetail::releaseBytes(entries_);
    entries_ = nullptr;
    recordSize_ = 0;
    capacity_ = 0;
    mask_ = 0;
    head_.store(0, std::memory_order_relaxed);
    tail_.store(0, std::memory_order_relaxed);
  }

  bool push(const uint8_t* record, size_t length, size_t* depthAfter = nullptr) {
    if (!entries_ || !record || length != recordSize_) return false;
    const uint32_t tail = tail_.load(std::memory_order_relaxed);
    const uint32_t head = head_.load(std::memory_order_acquire);
    if (tail - head >= capacity_) return false;
    memcpy(entries_ + (tail & mask_) * recordSize_, record, recordSize_);
    tail_.store(tail + 1u, std::memory_order_release);
    if (depthAfter) *depthAfter = static_cast<size_t>((tail + 1u) - head);
    return true;
  }

  bool pop(uint8_t* destination, size_t capacity, size_t* depthAfter = nullptr) {
    if (!entries_ || !destination || capacity < recordSize_) return false;
    const uint32_t head = head_.load(std::memory_order_relaxed);
    const uint32_t tail = tail_.load(std::memory_order_acquire);
    if (head == tail) return false;
    memcpy(destination, entries_ + (head & mask_) * recordSize_, recordSize_);
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
  size_t capacity() const { return capacity_; }
  size_t recordSize() const { return recordSize_; }

  void clear() {
    head_.store(0, std::memory_order_relaxed);
    tail_.store(0, std::memory_order_relaxed);
  }

private:
  uint8_t* entries_ = nullptr;
  size_t recordSize_ = 0;
  size_t capacity_ = 0;
  uint32_t mask_ = 0;
  alignas(4) std::atomic<uint32_t> head_ { 0 };
  alignas(4) std::atomic<uint32_t> tail_ { 0 };
};
