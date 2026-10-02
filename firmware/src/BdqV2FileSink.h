#pragma once

#include <Arduino.h>
#include <FS.h>
#include <string.h>

#include "BdqV2Writer.h"

enum class BdqV2FileSinkOperation : uint8_t {
  BufferedWrite = 1,
  FileFlush = 2,
};

struct BdqV2FileSinkStats {
  uint32_t logicalWriteCalls = 0;
  uint32_t physicalWriteCalls = 0;
  uint32_t bufferFlushes = 0;
  uint32_t fileFlushCalls = 0;
  uint64_t logicalBytes = 0;
  uint64_t physicalBytes = 0;
  uint64_t writeTimeTotalUs = 0;
  uint64_t flushTimeTotalUs = 0;
  uint32_t writeTimeMaximumUs = 0;
  uint32_t flushTimeMaximumUs = 0;
  size_t bufferCapacityBytes = 0;
  size_t bufferHighWaterBytes = 0;
};

using BdqV2FileSinkObserver = void (*)(
    void* context,
    BdqV2FileSinkOperation operation,
    uint32_t durationUs,
    size_t bytes);

// Coalescing storage-boundary adapter. Keeping File out of BdqV2Writer makes
// the writer core host-testable while this target adapter turns the writer's
// small logical header/payload writes into SD-friendly physical writes.
class BdqV2FileSink final : public BdqV2ByteSink {
public:
  explicit BdqV2FileSink(File& file) : file_(file) {}

  void configure(
      uint8_t* buffer,
      size_t capacity,
      BdqV2FileSinkObserver observer = nullptr,
      void* observerContext = nullptr) {
    buffer_ = buffer;
    bufferCapacity_ = buffer ? capacity : 0;
    bufferedBytes_ = 0;
    observer_ = observer;
    observerContext_ = observerContext;
    stats_ = {};
    stats_.bufferCapacityBytes = bufferCapacity_;
  }

  void reset() {
    buffer_ = nullptr;
    bufferCapacity_ = 0;
    bufferedBytes_ = 0;
    observer_ = nullptr;
    observerContext_ = nullptr;
  }

  bool write(const uint8_t* data, size_t length) override {
    if (!file_ || (!data && length != 0)) return false;
    if (length == 0) return true;
    ++stats_.logicalWriteCalls;
    stats_.logicalBytes += length;

    if (!buffer_ || bufferCapacity_ == 0) {
      return writePhysical_(data, length);
    }

    while (length != 0) {
      if (bufferedBytes_ == 0 && length >= bufferCapacity_) {
        return writePhysical_(data, length);
      }
      const size_t available = bufferCapacity_ - bufferedBytes_;
      const size_t copied = length < available ? length : available;
      memcpy(buffer_ + bufferedBytes_, data, copied);
      bufferedBytes_ += copied;
      if (bufferedBytes_ > stats_.bufferHighWaterBytes) {
        stats_.bufferHighWaterBytes = bufferedBytes_;
      }
      data += copied;
      length -= copied;
      if (bufferedBytes_ == bufferCapacity_ && !flushBuffer_()) return false;
    }
    return true;
  }

  bool flush() override {
    if (!file_) return false;
    if (!flushBuffer_()) return false;
    const uint32_t startedUs = micros();
    file_.flush();
    const uint32_t durationUs = static_cast<uint32_t>(micros() - startedUs);
    ++stats_.fileFlushCalls;
    stats_.flushTimeTotalUs += durationUs;
    if (durationUs > stats_.flushTimeMaximumUs) {
      stats_.flushTimeMaximumUs = durationUs;
    }
    observe_(BdqV2FileSinkOperation::FileFlush, durationUs, 0);
    return true;
  }

  const BdqV2FileSinkStats& stats() const { return stats_; }
  size_t bufferedBytes() const { return bufferedBytes_; }

private:
  bool writePhysical_(const uint8_t* data, size_t length) {
    const uint32_t startedUs = micros();
    const size_t written = file_.write(data, length);
    const uint32_t durationUs = static_cast<uint32_t>(micros() - startedUs);
    ++stats_.physicalWriteCalls;
    stats_.physicalBytes += written;
    stats_.writeTimeTotalUs += durationUs;
    if (durationUs > stats_.writeTimeMaximumUs) {
      stats_.writeTimeMaximumUs = durationUs;
    }
    observe_(BdqV2FileSinkOperation::BufferedWrite, durationUs, length);
    return written == length;
  }

  bool flushBuffer_() {
    if (bufferedBytes_ == 0) return true;
    const size_t length = bufferedBytes_;
    if (!writePhysical_(buffer_, length)) return false;
    bufferedBytes_ = 0;
    ++stats_.bufferFlushes;
    return true;
  }

  void observe_(
      BdqV2FileSinkOperation operation,
      uint32_t durationUs,
      size_t bytes) {
    if (observer_) observer_(observerContext_, operation, durationUs, bytes);
  }

  File& file_;
  uint8_t* buffer_ = nullptr;
  size_t bufferCapacity_ = 0;
  size_t bufferedBytes_ = 0;
  BdqV2FileSinkObserver observer_ = nullptr;
  void* observerContext_ = nullptr;
  BdqV2FileSinkStats stats_;
};

