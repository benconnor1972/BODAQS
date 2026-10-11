#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

// Caller-owned startup-only storage. Retain a prefix of complete messages and
// reserve room for a completion/truncation footer even after overflow.
class StartupReportBuffer {
public:
  static constexpr size_t kFooterReserve = 512;
  void reset(char* storage = nullptr, size_t capacity = 0) {
    storage_ = storage;
    capacity_ = capacity;
    used_ = 0;
    droppedMessages_ = droppedBytes_ = 0;
    if (storage_ && capacity_) storage_[0] = '\0';
  }
  void append(const char* text, size_t length) {
    if (!storage_ || capacity_ <= kFooterReserve || !text) return;
    const size_t limit = capacity_ - kFooterReserve;
    if (droppedMessages_ || used_ > limit || length > limit - used_) {
      drop(length);
      return;
    }
    memcpy(storage_ + used_, text, length);
    used_ += length;
    storage_[used_] = '\0';
  }
  void drop(size_t length) { ++droppedMessages_; droppedBytes_ += length; }
  bool footer(const char* text) {
    if (!storage_ || !text || strlen(text) >= capacity_ - used_) return false;
    const size_t length = strlen(text);
    memcpy(storage_ + used_, text, length + 1);
    used_ += length;
    return true;
  }
  const char* data() const { return storage_ ? storage_ : ""; }
  size_t size() const { return used_; }
  uint64_t droppedMessages() const { return droppedMessages_; }
  uint64_t droppedBytes() const { return droppedBytes_; }
private:
  char* storage_ = nullptr;
  size_t capacity_ = 0, used_ = 0;
  uint64_t droppedMessages_ = 0, droppedBytes_ = 0;
};
