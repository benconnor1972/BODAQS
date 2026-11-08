#pragma once
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include <stdint.h>

// Single logger owner only. All times are relative to the timed case start.
// Idle spans retain the first cycle's boundaries and the last cycle's end;
// they never imply interpolation of individual loop checks.
struct SpiDispatchRecord {
  uint32_t begin=0,readyEnd=0,rowEnd=0,startEnd=0,decisionAt=0,end=0,spanEnd=0;
  uint32_t nextRow=0,lastCs=0,lastTransferEnd=0,cs=0,release=0;
  uint32_t row=0,slot=0,requestObject=0,replyObject=0;
  uint32_t validateUs=0,expectedUs=0,objectUs=0;
  uint16_t cycles=1;
  uint8_t decision=0,pendingBefore=0,pendingAfter=0,adcBefore=0,adcAfter=0;
  uint8_t reads=0,starts=0,published=0,clockState=0;
  uint8_t requestOpcode=0,requestNode=0,requestFragment=0;
  uint8_t replyOpcode=0,replyNode=0,replyFragment=0,replyStatus=0;
  uint8_t outcomeFlags=0; // valid, duplicate, stale, accept-error, RAM-object, ACK-retired
  bool idle() const {
    return !reads && !starts && !published && decision>=1 && decision<=3;
  }
};
static_assert(sizeof(SpiDispatchRecord)<=100,"dispatch trace RAM budget");

struct SpiDispatchTrace {
  static constexpr uint32_t kStartUs=1001000,kDurationUs=64000;
  static constexpr uint16_t kCapacity=512;
  SpiDispatchRecord records[kCapacity];
  uint16_t count=0;
  uint32_t cycles=0,overflow=0,observedEnd=0;
  uint32_t windowBegin=0,windowEnd=0,slotsBegin=0,slotsEnd=0,rowsBegin=0,rowsEnd=0;
  bool enabled=false,closed=false;
  void reset(bool enable) {
    // Old arena bytes are inaccessible after count resets. No large stack copy.
    count=0;cycles=overflow=observedEnd=0;enabled=enable;closed=false;
    windowBegin=windowEnd=slotsBegin=slotsEnd=rowsBegin=rowsEnd=0;
  }
  bool observe(uint32_t now,uint32_t slots=0,uint32_t rows=0) {
    // Identical lightweight window endpoints with trace on and off. Counts
    // cover cycles starting in the nominal interval, not pad-edge timestamps.
    if(!windowBegin && now>=kStartUs && now<kStartUs+kDurationUs) {
      windowBegin=now;slotsBegin=slots;rowsBegin=rows;
    }
    if(windowBegin && !windowEnd && now>=kStartUs+kDurationUs) {
      windowEnd=now;slotsEnd=slots;rowsEnd=rows;
    }
    if(!enabled || closed || now<kStartUs)return false;
    if(now>=kStartUs+kDurationUs) {closed=true;observedEnd=now;return false;}
    return true;
  }
  void append(const SpiDispatchRecord& r) {
    ++cycles;
    if(overflow) {++overflow;return;} // Retain a contiguous prefix after saturation.
    if(count && r.idle()) {
      auto& p=records[count-1];
      if(p.idle() && p.decision==r.decision && p.nextRow==r.nextRow &&
         p.row==r.row && p.slot==r.slot && p.pendingAfter==r.pendingBefore &&
         r.pendingBefore==r.pendingAfter && p.adcAfter==r.adcBefore &&
         r.adcBefore==r.adcAfter && p.lastCs==r.lastCs &&
         p.lastTransferEnd==r.lastTransferEnd && p.clockState==r.clockState &&
         p.cycles<UINT16_MAX) {
        ++p.cycles;p.spanEnd=r.end;return;
      }
    }
    if(count==kCapacity) {++overflow;return;}
    records[count++]=r;
  }
  bool complete() const {return enabled && closed && count && !overflow;}
};
#endif
