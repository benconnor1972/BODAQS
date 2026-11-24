#pragma once
#include "BdqV2StreamSource.h"
#include "BdqV2StreamQueue.h"
#include "DynamicSpscQueue.h"
#include <atomic>
#include <cstring>

// GPS task is the sole producer; lifecycle changes are fenced by its sensor mutex.
class GpsNativeStream {
public:
  struct Observation {
    int32_t latE7=0,lonE7=0,altMslMm=0,groundSpeedMmS=0,headingDegE5=0;
    uint32_t hAccMm=0,vAccMm=0,speedAccMmS=0,headingAccDegE5=0;
    uint32_t gpsTowMs=0,gpsUnixSeconds=0,receivedMs=0;
    // have, fixOK, invalidLLH, dateValid, timeValid. UTC is unknown without both validity bits.
    uint16_t flags=0;
    uint8_t fixType=0,satellites=0;
  };
  bool begin(size_t capacity=128) {
    if(active_ || pending() || !queue_.allocate(capacity)) return false;
    sequence_=pendingStatus_=0;capacity_=capacity;enqueued_=dequeued_=dropped_=highWater_=0;
    active_=true;return true;
  }
  void stop() {active_=false;}
  bool active() const {return active_;}
  size_t finalizeSession() {if(active_) return 0;const auto n=pending();queue_.clear();return n;}
  size_t pending() const {return queue_.size();}
  uint32_t capacity() const {return capacity_;}
  BdqV2StreamQueueStats stats() const {
    BdqV2StreamQueueStats s;s.recordsEnqueued=enqueued_;s.recordsDequeued=dequeued_;
    s.recordsDropped=dropped_;s.recordQueueHighWater=highWater_;return s;
  }
  void observe(const Observation& p,uint32_t tickUs) {
    if(!active_) return;
    Record r{};auto* b=r.bytes;
    BdqV2Format::putU32(b,sequence_++);BdqV2Format::putU32(b+4,tickUs);
    const bool valid=(p.flags&7)==3 && p.fixType>=2 && p.fixType<=4 &&
      p.latE7>=-900000000 && p.latE7<=900000000 && p.lonE7>=-1800000000 && p.lonE7<=1800000000;
    BdqV2Format::putU16(b+8,pendingStatus_|(valid?0:32));
    const uint32_t words[]={uint32_t(p.latE7),uint32_t(p.lonE7),uint32_t(p.altMslMm),
      uint32_t(p.groundSpeedMmS),uint32_t(p.headingDegE5),p.hAccMm,p.vAccMm,p.speedAccMmS,
      p.headingAccDegE5,p.gpsTowMs,p.gpsUnixSeconds,p.receivedMs};
    for(size_t i=0;i<12;++i) BdqV2Format::putU32(b+12+4*i,words[i]);
    BdqV2Format::putU16(b+60,p.flags);b[62]=p.fixType;b[63]=p.satellites;
    size_t depth=0;
    if(!queue_.push(r,&depth)) {increment_(dropped_);pendingStatus_|=3;}
    else {increment_(enqueued_);pendingStatus_=0;if(depth>highWater_) highWater_=depth;}
  }
  BdqV2StreamSource source(uint16_t id) {
    BdqV2StreamSource s;s.streamId=id;s.recordSizeBytes=64;s.nativeTickModulus=uint64_t{1}<<32;
    s.snapshotPendingSafe=true;s.context=this;
    s.pendingRecords=[](const void* p){return static_cast<const GpsNativeStream*>(p)->pending();};
    s.pendingObservations=[](const void*)->size_t{return 0;};
    s.popObservation=[](void*,BdqV2Format::TimeObservation&){return false;};
    s.popRecord=[](void* p,uint8_t* out,size_t cap) {
      auto* stream=static_cast<GpsNativeStream*>(p);Record r;
      if(!out || cap<64 || !stream->queue_.pop(r)) return false;
      increment_(stream->dequeued_);memcpy(out,r.bytes,64);return true;
    };return s;
  }
private:
  static void increment_(std::atomic<uint32_t>& n) {const auto v=n.load();if(v!=UINT32_MAX) n=v+1;}
  struct Record {uint8_t bytes[64];};
  DynamicSpscQueue<Record> queue_;
  std::atomic<uint32_t> enqueued_{0},dequeued_{0},dropped_{0},highWater_{0};
  uint32_t capacity_=0,sequence_=0;
  uint16_t pendingStatus_=0;
  bool active_=false;
};
