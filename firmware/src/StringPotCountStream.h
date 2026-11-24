#pragma once
#include "BdqV2StreamSource.h"
#include "BdqV2StreamQueue.h"
#include "DynamicSpscQueue.h"
#include "StringPotWrapTracker.h"
#include <atomic>
#include <string.h>

// One acquisition owner performs tracking and publication. The storage owner
// pops encoded records; previews only inspect a coherent published observation.
class StringPotCountStream {
public:
  enum Quality : uint16_t {
    AssumedOrigin=1, SettlingHeld=2, ObservationGap=4, Uncertain=8,
    InvalidInput=16, Reset=32, Overflow=64
  };
  struct Configuration {
    uint16_t countsPerTurn=4096, threshold=2048;
    int32_t installedZero=0;
    bool assumeTurnZero=true, analogSettling=false, recordAuxiliary=false;
  };
  struct Auxiliary {
    uint16_t angle=0,magnitude=0,validity=0;
    uint8_t deviceStatus=0,agc=0;
    uint32_t readFailures=0,diagnosticFailures=0;
  };
  struct Sample {
    uint32_t sequence=0,tickUs=0,epoch=0;
    int32_t unwrapped=0;
    uint16_t wrapped=0,quality=0,status=0;
  };
  bool configure(const Configuration& config) {
    if(active_ || queue_.size() || config.countsPerTurn<2 ||
       !config.threshold || config.threshold>=config.countsPerTurn) return false;
    config_=config;initialized_=haveSequence_=uncertain_=overflow_=missingObservation_=false;unwrapped_=0;
    tracker_.reset(0,0,config_.countsPerTurn);generation_.store(0);
    return true;
  }
  bool begin(size_t capacity=512) {
    if(active_ || queue_.size() || epoch_==UINT32_MAX || !queue_.allocate(capacity)) return false;
    initialized_=haveSequence_=uncertain_=overflow_=missingObservation_=false;pendingStatus_=0;unwrapped_=0;
    enqueued_.store(0);dequeued_.store(0);dropped_.store(0);highWater_.store(0);capacity_.store(capacity);
    generation_.store(0);++epoch_;active_=true;
    return true;
  }
  void stop() {active_=false;} // Called after the acquisition owner retires.
  // The file owner has finished its final-depth diagnostics and retired I/O.
  // A failed open/write may leave rows which belong only to that old session.
  size_t finalizeSession() {
    if(active_) return 0;
    const auto discarded=queue_.size();queue_.clear();return discarded;
  }
  bool active() const {return active_;}
  size_t pending() const {return queue_.size();}
  BdqV2StreamQueueStats stats() const {
    BdqV2StreamQueueStats result;
    result.recordsEnqueued=enqueued_.load();result.recordsDequeued=dequeued_.load();
    result.recordsDropped=dropped_.load();result.recordQueueHighWater=highWater_.load();
    return result;
  }
  uint32_t capacity() const {return capacity_.load();}
  void markObservationGap() {missingObservation_=true;}
  void observe(int32_t counts,uint32_t sequence,uint32_t tickUs,uint16_t status) {
    observe(counts,sequence,tickUs,status,Auxiliary{});
  }
  void observe(int32_t counts,uint32_t sequence,uint32_t tickUs,uint16_t status,const Auxiliary& auxiliary) {
    Sample value;value.sequence=sequence;value.tickUs=tickUs;value.epoch=epoch_;value.status=status;
    value.quality=AssumedOrigin; // Absolute physical turns were never observed.
    const bool invalid=(status&0x20) || counts<0 || counts>=config_.countsPerTurn;
    value.wrapped=counts<0?0:counts>UINT16_MAX?UINT16_MAX:static_cast<uint16_t>(counts);
    if(missingObservation_ || (haveSequence_ && sequence!=previousSequence_+1u)) {
      value.quality|=ObservationGap;uncertain_=true;
      value.status|=BdqV2Format::DiscontinuityBefore|BdqV2Format::TimingDegraded;
    }
    missingObservation_=false;
    if(invalid) {value.quality|=InvalidInput;uncertain_=true;value.status|=0x20;}
    if(status&BdqV2Format::TimingDegraded) uncertain_=true;
    if(!invalid) {
      if(!initialized_) {
        int64_t initial=value.wrapped;
        if(config_.assumeTurnZero) {
          const int64_t turn=config_.countsPerTurn;
          int64_t phase=int64_t(config_.installedZero)%turn;if(phase<0) phase+=turn;
          initial=int64_t(config_.installedZero)-phase+value.wrapped;
          if(value.wrapped<phase) initial+=turn;
        }
        if(initial>INT32_MAX || initial<INT32_MIN) {
          initial=initial>INT32_MAX?INT32_MAX:INT32_MIN;uncertain_=overflow_=true;
        }
        unwrapped_=static_cast<int32_t>(initial);
        tracker_.reset(value.wrapped,unwrapped_,config_.countsPerTurn);
        initialized_=true;value.quality|=Reset;
      } else if(!overflow_) {
        const int delta=int(value.wrapped)-lastWrapped_;
        if(delta==config_.threshold || delta==-int(config_.threshold)) uncertain_=true;
        unwrapped_=tracker_.update(value.wrapped,config_.countsPerTurn,config_.threshold,config_.analogSettling);
      }
      if(tracker_.settlingHeld()) value.quality|=SettlingHeld;
      if(tracker_.overflowed()) {overflow_=uncertain_=true;}
      if(tracker_.settlingTimedOut()) uncertain_=true;
      lastWrapped_=value.wrapped;
    }
    value.unwrapped=unwrapped_;
    if(overflow_) value.quality|=Overflow;
    if(uncertain_) value.quality|=Uncertain;
    previousSequence_=sequence;haveSequence_=true;
    publish_(value);
    if(!active_) return;
    Record record={};
    BdqV2Format::putU32(record.bytes,value.sequence);BdqV2Format::putU32(record.bytes+4,value.tickUs);
    BdqV2Format::putU16(record.bytes+8,value.status|pendingStatus_);
    BdqV2Format::putU16(record.bytes+12,value.wrapped);BdqV2Format::putU16(record.bytes+14,value.quality);
    BdqV2Format::putU32(record.bytes+16,static_cast<uint32_t>(value.unwrapped));
    BdqV2Format::putU32(record.bytes+20,value.epoch);
    if(config_.recordAuxiliary) {
      BdqV2Format::putU16(record.bytes+24,auxiliary.angle);
      record.bytes[26]=auxiliary.deviceStatus;record.bytes[27]=auxiliary.agc;
      BdqV2Format::putU16(record.bytes+28,auxiliary.magnitude);
      BdqV2Format::putU16(record.bytes+30,auxiliary.validity);
      BdqV2Format::putU32(record.bytes+32,auxiliary.readFailures);
      BdqV2Format::putU32(record.bytes+36,auxiliary.diagnosticFailures);
    }
    size_t depth=0;
    if(!queue_.push(record,&depth)) {
      increment_(dropped_);
      pendingStatus_|=BdqV2Format::DiscontinuityBefore|BdqV2Format::ProducerQueueDropBefore;
    } else {
      increment_(enqueued_);pendingStatus_=0;
      if(depth>highWater_.load()) highWater_.store(static_cast<uint32_t>(depth));
    }
  }
  bool snapshot(Sample& sample) const {
    const auto version=generation_.load();if(!version || (version&1u)) return false;
    Sample value;
    value.sequence=published_[0].load();value.tickUs=published_[1].load();value.epoch=published_[2].load();
    const uint32_t unwrapped=published_[3].load();memcpy(&value.unwrapped,&unwrapped,4);
    const auto combined=published_[4].load();value.wrapped=combined&0xffff;value.quality=combined>>16;
    value.status=published_[5].load();
    if(generation_.load()!=version) return false;
    sample=value;return true;
  }
  BdqV2StreamSource source(uint16_t id) {
    BdqV2StreamSource source;source.streamId=id;source.recordSizeBytes=config_.recordAuxiliary?40:24;
    source.snapshotPendingSafe=true;source.nativeTickModulus=uint64_t{1}<<32;source.context=this;
    source.pendingRecords=[](const void* p){return static_cast<const StringPotCountStream*>(p)->pending();};
    source.pendingObservations=[](const void*)->size_t{return 0;};
    source.popObservation=[](void*,BdqV2Format::TimeObservation&){return false;};
    source.popRecord=[](void* p,uint8_t* out,size_t capacity) {
      auto* stream=static_cast<StringPotCountStream*>(p);
      const size_t bytes=stream->config_.recordAuxiliary?40:24;
      if(!out || capacity<bytes) return false;
      Record record;if(!stream->queue_.pop(record)) return false;
      increment_(stream->dequeued_);
      memcpy(out,record.bytes,bytes);return true;
    };
    return source;
  }
private:
  static void increment_(std::atomic<uint32_t>& counter) {
    const auto value=counter.load();if(value!=UINT32_MAX) counter.store(value+1);
  }
  struct Record {uint8_t bytes[40];};
  void publish_(const Sample& value) {
    generation_.fetch_add(1);
    published_[0].store(value.sequence);published_[1].store(value.tickUs);published_[2].store(value.epoch);
    published_[3].store(static_cast<uint32_t>(value.unwrapped));
    published_[4].store(uint32_t(value.wrapped)|(uint32_t(value.quality)<<16));published_[5].store(value.status);
    generation_.fetch_add(1);
  }
  Configuration config_;
  StringPotWrapTracker tracker_;
  DynamicSpscQueue<Record> queue_;
  std::atomic<uint32_t> generation_{0},published_[6]{};
  std::atomic<uint32_t> enqueued_{0},dequeued_{0},dropped_{0},highWater_{0},capacity_{0};
  uint32_t epoch_=0,previousSequence_=0;
  int32_t unwrapped_=0;
  int lastWrapped_=0;
  uint16_t pendingStatus_=0;
  bool active_=false,initialized_=false,haveSequence_=false,uncertain_=false,overflow_=false,missingObservation_=false;
};
