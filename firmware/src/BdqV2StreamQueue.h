#pragma once

#include <atomic>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "BdqV2StreamSource.h"
#include "FixedSpscQueue.h"

struct BdqV2StreamQueueStats {
  uint32_t recordsEnqueued = 0;
  uint32_t recordsDequeued = 0;
  uint32_t recordsDropped = 0;
  uint32_t recordsRejected = 0;
  uint32_t observationsEnqueued = 0;
  uint32_t observationsDequeued = 0;
  uint32_t observationsDropped = 0;
  uint32_t observationsRejected = 0;
  uint32_t recordQueueHighWater = 0;
  uint32_t observationQueueHighWater = 0;
};

// Allocation-free queue for producers that already emit encoded BDQ v2
// records. Queue overflow drops the newest record and marks the next retained
// record with both discontinuity and producer-queue-loss evidence.
template <size_t RecordBytes, size_t RecordCapacity, size_t ObservationCapacity>
class BdqV2StreamQueue {
public:
  static_assert(RecordBytes >= BdqV2Format::kStreamRecordPrefixBytes,
                "BDQ v2 records must contain the common prefix");
  static_assert(RecordBytes <= UINT16_MAX,
                "BDQ v2 fixed record size must fit the stream header");

  explicit BdqV2StreamQueue(uint16_t streamId, uint64_t nativeTickModulus)
      : streamId_(streamId), nativeTickModulus_(nativeTickModulus) {}

  bool enqueueRecord(const uint8_t* record, size_t length) {
    RecordSlot slot;
    BdqV2Format::StreamRecordPrefix prefix;
    if (!record || length != RecordBytes ||
        !BdqV2Format::decodeStreamRecordPrefix(record, length, prefix) ||
        prefix.reserved != 0 || prefix.nativeTick >= nativeTickModulus_) {
      increment_(recordsRejected_);
      return false;
    }

    memcpy(slot.bytes, record, RecordBytes);
    prefix.statusFlags = static_cast<uint16_t>(
        prefix.statusFlags | pendingStatusBeforeNextRecord_);
    BdqV2Format::encodeStreamRecordPrefix(prefix, slot.bytes, RecordBytes);

    size_t depth = 0;
    if (!records_.push(slot, &depth)) {
      increment_(recordsDropped_);
      pendingStatusBeforeNextRecord_ = static_cast<uint16_t>(
          pendingStatusBeforeNextRecord_ |
          (prefix.statusFlags & kCarryForwardStatusMask) |
          BdqV2Format::DiscontinuityBefore |
          BdqV2Format::ProducerQueueDropBefore);
      return false;
    }

    pendingStatusBeforeNextRecord_ = 0;
    increment_(recordsEnqueued_);
    updateHighWater_(recordQueueHighWater_, depth);
    return true;
  }

  bool enqueueObservation(const BdqV2Format::TimeObservation& observation) {
    if (!BdqV2Format::validTimeObservation(observation) ||
        observation.nativeTick >= nativeTickModulus_) {
      increment_(observationsRejected_);
      return false;
    }

    size_t depth = 0;
    if (!observations_.push(observation, &depth)) {
      increment_(observationsDropped_);
      pendingStatusBeforeNextRecord_ = static_cast<uint16_t>(
          pendingStatusBeforeNextRecord_ | BdqV2Format::TimingDegraded);
      return false;
    }

    increment_(observationsEnqueued_);
    updateHighWater_(observationQueueHighWater_, depth);
    return true;
  }

  // Producer-side hook for source reset, transport loss, or other evidence
  // that applies immediately before the next successfully queued record.
  void markStatusBeforeNextRecord(uint16_t statusFlags) {
    pendingStatusBeforeNextRecord_ = static_cast<uint16_t>(
        pendingStatusBeforeNextRecord_ | statusFlags);
  }

  size_t pendingRecords() const { return records_.size(); }
  size_t pendingObservations() const { return observations_.size(); }

  BdqV2StreamSource source() {
    BdqV2StreamSource out;
    out.streamId = streamId_;
    out.recordSizeBytes = static_cast<uint16_t>(RecordBytes);
    out.nativeTickModulus = nativeTickModulus_;
    out.context = this;
    out.pendingRecords = &pendingRecordsThunk_;
    out.pendingObservations = &pendingObservationsThunk_;
    out.popRecord = &popRecordThunk_;
    out.popObservation = &popObservationThunk_;
    return out;
  }

  BdqV2StreamQueueStats stats() const {
    BdqV2StreamQueueStats out;
    out.recordsEnqueued = recordsEnqueued_.load(std::memory_order_relaxed);
    out.recordsDequeued = recordsDequeued_.load(std::memory_order_relaxed);
    out.recordsDropped = recordsDropped_.load(std::memory_order_relaxed);
    out.recordsRejected = recordsRejected_.load(std::memory_order_relaxed);
    out.observationsEnqueued = observationsEnqueued_.load(std::memory_order_relaxed);
    out.observationsDequeued = observationsDequeued_.load(std::memory_order_relaxed);
    out.observationsDropped = observationsDropped_.load(std::memory_order_relaxed);
    out.observationsRejected = observationsRejected_.load(std::memory_order_relaxed);
    out.recordQueueHighWater = recordQueueHighWater_.load(std::memory_order_relaxed);
    out.observationQueueHighWater = observationQueueHighWater_.load(std::memory_order_relaxed);
    return out;
  }

  // Call only when producer and consumer are stopped.
  void reset() {
    records_.clear();
    observations_.clear();
    pendingStatusBeforeNextRecord_ = 0;
    recordsEnqueued_.store(0, std::memory_order_relaxed);
    recordsDequeued_.store(0, std::memory_order_relaxed);
    recordsDropped_.store(0, std::memory_order_relaxed);
    recordsRejected_.store(0, std::memory_order_relaxed);
    observationsEnqueued_.store(0, std::memory_order_relaxed);
    observationsDequeued_.store(0, std::memory_order_relaxed);
    observationsDropped_.store(0, std::memory_order_relaxed);
    observationsRejected_.store(0, std::memory_order_relaxed);
    recordQueueHighWater_.store(0, std::memory_order_relaxed);
    observationQueueHighWater_.store(0, std::memory_order_relaxed);
  }

private:
  struct RecordSlot {
    uint8_t bytes[RecordBytes] {};
  };

  static constexpr uint16_t kCarryForwardStatusMask =
      BdqV2Format::DiscontinuityBefore |
      BdqV2Format::ProducerQueueDropBefore |
      BdqV2Format::SourceRecoveryBefore |
      BdqV2Format::TimingDegraded;

  static void increment_(std::atomic<uint32_t>& counter) {
    counter.fetch_add(1, std::memory_order_relaxed);
  }

  static void updateHighWater_(std::atomic<uint32_t>& highWater, size_t depth) {
    const uint32_t candidate = static_cast<uint32_t>(depth);
    uint32_t current = highWater.load(std::memory_order_relaxed);
    while (candidate > current &&
           !highWater.compare_exchange_weak(
               current, candidate,
               std::memory_order_relaxed,
               std::memory_order_relaxed)) {}
  }

  bool popRecord_(uint8_t* destination, size_t capacity) {
    if (!destination || capacity < RecordBytes) return false;
    RecordSlot slot;
    if (!records_.pop(slot)) return false;
    memcpy(destination, slot.bytes, RecordBytes);
    increment_(recordsDequeued_);
    return true;
  }

  bool popObservation_(BdqV2Format::TimeObservation& observation) {
    if (!observations_.pop(observation)) return false;
    increment_(observationsDequeued_);
    return true;
  }

  static size_t pendingRecordsThunk_(const void* context) {
    return static_cast<const BdqV2StreamQueue*>(context)->pendingRecords();
  }

  static size_t pendingObservationsThunk_(const void* context) {
    return static_cast<const BdqV2StreamQueue*>(context)->pendingObservations();
  }

  static bool popRecordThunk_(void* context, uint8_t* destination, size_t capacity) {
    return static_cast<BdqV2StreamQueue*>(context)->popRecord_(destination, capacity);
  }

  static bool popObservationThunk_(
      void* context,
      BdqV2Format::TimeObservation& observation) {
    return static_cast<BdqV2StreamQueue*>(context)->popObservation_(observation);
  }

  const uint16_t streamId_;
  const uint64_t nativeTickModulus_;
  FixedSpscQueue<RecordSlot, RecordCapacity> records_;
  FixedSpscQueue<BdqV2Format::TimeObservation, ObservationCapacity> observations_;

  // Producer-owned: no atomic read-modify-write is needed on the hot path.
  uint16_t pendingStatusBeforeNextRecord_ = 0;
  std::atomic<uint32_t> recordsEnqueued_ {0};
  std::atomic<uint32_t> recordsDequeued_ {0};
  std::atomic<uint32_t> recordsDropped_ {0};
  std::atomic<uint32_t> recordsRejected_ {0};
  std::atomic<uint32_t> observationsEnqueued_ {0};
  std::atomic<uint32_t> observationsDequeued_ {0};
  std::atomic<uint32_t> observationsDropped_ {0};
  std::atomic<uint32_t> observationsRejected_ {0};
  std::atomic<uint32_t> recordQueueHighWater_ {0};
  std::atomic<uint32_t> observationQueueHighWater_ {0};
};
