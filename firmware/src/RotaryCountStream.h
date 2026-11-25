#pragma once
#include "BdqV2StreamSource.h"
#include "BdqV2StreamQueue.h"
#include "DynamicSpscQueue.h"
#include <atomic>
#include <string.h>

// Acquisition owns push/start/stop; storage alone pops. Allocation and clearing
// happen outside acquisition, after the preceding file owner has retired.
class RotaryCountStream {
public:
  struct Observation {
    uint32_t sequence=0,tickUs=0,readFailures=0,diagnosticFailures=0;
    uint16_t raw=0,angle=0,deviceStatus=0,magnitude=0,status=0;
    uint8_t agc=0,validity=0; // 1=current RAW, 2=current ANGLE, 4=available diagnostics, 8=reused RAW.
  };
  bool begin(size_t capacity=512) {
    if(active_ || queue_.size() || !queue_.allocate(capacity)) return false;
    enqueued_=0;dequeued_=0;dropped_=0;highWater_=0;capacity_=capacity;
    pendingStatus_=0;haveSequence_=false;active_=true;return true;
  }
  void stop() {active_=false;}
  void finalizeSession() {if(!active_) queue_.clear();}
  size_t pendingRecords() const {return queue_.size();}
  size_t capacity() const {return capacity_.load();}
  BdqV2StreamQueueStats stats() const {
    BdqV2StreamQueueStats value;value.recordsEnqueued=enqueued_.load();
    value.recordsDequeued=dequeued_.load();value.recordsDropped=dropped_.load();
    value.recordQueueHighWater=highWater_.load();return value;
  }
  void markGap() {pendingStatus_|=BdqV2Format::DiscontinuityBefore|BdqV2Format::TimingDegraded;}
  bool observe(const Observation& value) {
    if(!active_) return false;
    if(haveSequence_ && value.sequence!=previousSequence_+1u) markGap();
    previousSequence_=value.sequence;haveSequence_=true;
    Record record{};
    BdqV2Format::putU32(record.bytes,value.sequence);
    BdqV2Format::putU32(record.bytes+4,value.tickUs);
    BdqV2Format::putU16(record.bytes+8,value.status|pendingStatus_);
    BdqV2Format::putU16(record.bytes+12,value.raw);
    BdqV2Format::putU16(record.bytes+14,value.angle);
    BdqV2Format::putU16(record.bytes+16,value.deviceStatus);
    record.bytes[18]=value.agc;record.bytes[19]=value.validity;
    BdqV2Format::putU16(record.bytes+20,value.magnitude);
    BdqV2Format::putU32(record.bytes+24,value.readFailures);
    BdqV2Format::putU32(record.bytes+28,value.diagnosticFailures);
    size_t depth=0;
    if(!queue_.push(record,&depth)) {
      increment_(dropped_);pendingStatus_|=BdqV2Format::DiscontinuityBefore|BdqV2Format::ProducerQueueDropBefore;
      return false;
    }
    increment_(enqueued_);pendingStatus_=0;
    if(depth>highWater_.load()) highWater_=static_cast<uint32_t>(depth);
    return true;
  }
  BdqV2StreamSource source(uint16_t id) {
    BdqV2StreamSource value;value.streamId=id;value.recordSizeBytes=32;
    value.snapshotPendingSafe=true;value.nativeTickModulus=uint64_t{1}<<32;value.context=this;
    value.pendingRecords=[](const void* p){return static_cast<const RotaryCountStream*>(p)->pendingRecords();};
    value.pendingObservations=[](const void*)->size_t{return 0;};
    value.popObservation=[](void*,BdqV2Format::TimeObservation&){return false;};
    value.popRecord=[](void* p,uint8_t* out,size_t capacity) {
      if(!out || capacity<32) return false;
      auto* self=static_cast<RotaryCountStream*>(p);Record record;
      if(!self->queue_.pop(record)) return false;
      increment_(self->dequeued_);memcpy(out,record.bytes,32);return true;
    };
    return value;
  }
private:
  static void increment_(std::atomic<uint32_t>& counter) {
    const auto value=counter.load();if(value!=UINT32_MAX) counter.store(value+1);
  }
  struct Record {uint8_t bytes[32];};
  DynamicSpscQueue<Record> queue_;
  std::atomic<uint32_t> enqueued_{0},dequeued_{0},dropped_{0},highWater_{0},capacity_{0};
  uint32_t previousSequence_=0;
  uint16_t pendingStatus_=0;
  bool active_=false,haveSequence_=false;
};
