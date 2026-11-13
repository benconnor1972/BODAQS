#pragma once

#include <atomic>
#include <stddef.h>
#include <stdint.h>

#if defined(BODAQS_RECORDING_PRESSURE_DIAGNOSTICS) && BODAQS_RECORDING_PRESSURE_DIAGNOSTICS
#if !defined(BODAQS_IMU_FLOW_DIAGNOSTICS) || !BODAQS_IMU_FLOW_DIAGNOSTICS
#error "Recording pressure capture requires retired FLOW snapshots"
#endif

// Diagnostic only. Acquisition and storage each write their own bounded state;
// neither reads the other's live arrays. The only live cross-owner publication
// is the first-loss trigger. Readers serialize after producer retirement, on
// the storage owner, before another recording can reset either state.
namespace RecordingPressureDiagnostics {
constexpr uint32_t postLossUs=2000000;
constexpr uint32_t serviceGapThresholdUs=10000;
constexpr size_t storageOperationCapacity=96,serviceGapCapacity=32;
template<typename T,size_t Capacity> struct History {
  T entries[Capacity]={};
  uint32_t overwritten=0;
  size_t next=0,count=0;
  void add(const T& event) {
    entries[next]=event;next=(next+1)%Capacity;
    if(count<Capacity) ++count;else ++overwritten;
  }
  const T& at(size_t index) const {return entries[(next+Capacity-count+index)%Capacity];}
};
struct StorageOperation {
  uint32_t startedUs=0,durationUs=0,bytes=0;
  uint16_t primaryDepth=0;
  uint8_t operation=0;
};
struct ServiceGap {uint32_t startedUs=0,durationUs=0;};
struct StorageState {History<StorageOperation,storageOperationCapacity> operations;bool frozen=false;};
struct AcquisitionState {
  History<ServiceGap,serviceGapCapacity> gaps;
  uint64_t context=0;
  uint32_t lastServiceUs=0,lossCounter=0;
  uint16_t lossStage=0;
  uint8_t lossNode=0,lossClass=0,lossReason=0;
  bool haveService=false,frozen=false;
};
inline StorageState storage;
inline AcquisitionState acquisition;
static_assert(std::atomic<uint32_t>::is_always_lock_free,"Diagnostic trigger must not lock");
inline std::atomic<uint32_t> firstLossUs{0};
inline std::atomic<bool> triggered{false};

// Storage start precedes acquisition ownership publication. The preceding
// producer has retired and file finalization completed before another start.
inline void resetStorage() {
  triggered.store(false,std::memory_order_release);
  storage={};
}
inline void resetAcquisition(uint64_t context,uint32_t nowUs) {
  acquisition={};acquisition.context=context;acquisition.lastServiceUs=nowUs;
}
inline bool pastWindow(uint32_t nowUs) {
  // Signed modulo delta also handles an operation completed just before the
  // trigger is published on the other core. Diagnostic runs must be <2^31 us.
  return triggered.load(std::memory_order_acquire) &&
      int32_t(nowUs-firstLossUs.load(std::memory_order_relaxed))>=int32_t(postLossUs);
}
inline void loss(uint8_t node,uint8_t cls,uint8_t reason,uint16_t stage,uint32_t counter,uint32_t nowUs) {
  if(!counter || triggered.load(std::memory_order_relaxed)) return;
  acquisition.lossNode=node;acquisition.lossClass=cls;acquisition.lossReason=reason;
  acquisition.lossStage=stage;acquisition.lossCounter=counter;
  firstLossUs.store(nowUs,std::memory_order_relaxed);
  triggered.store(true,std::memory_order_release);
}
inline void service(uint32_t nowUs) {
  if(!acquisition.frozen) {
    const uint32_t elapsed=nowUs-acquisition.lastServiceUs;
    if(acquisition.haveService && elapsed>=serviceGapThresholdUs)
      acquisition.gaps.add({acquisition.lastServiceUs,elapsed});
    acquisition.frozen=pastWindow(nowUs);
  }
  acquisition.lastServiceUs=nowUs;acquisition.haveService=true;
}
inline void storageOperation(uint8_t operation,uint32_t startedUs,uint32_t durationUs,
                             uint32_t bytes,uint16_t primaryDepth) {
  if(storage.frozen) return;
  storage.operations.add({startedUs,durationUs,bytes,primaryDepth,operation});
  // Include the first completion crossing the cutoff, including a long write
  // that was already in flight when the producer observed the first loss.
  storage.frozen=pastWindow(startedUs+durationUs);
}
inline size_t reservedBytes() {
  return sizeof(storage)+sizeof(acquisition)+sizeof(firstLossUs)+sizeof(triggered);
}
}
#endif
