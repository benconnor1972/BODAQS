#pragma once
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include <stdint.h>
#include "TimingStats.h"

// Bench-only bounded RAM sink. Publication is not SD/durable acceptance.
struct SpiProbeRow {
  uint32_t index=0;
  uint64_t scheduledUs=0,publishedUs=0;
  int32_t counts[2]={};
  uint32_t conversion[2]={};
  uint64_t acquiredUs[2]={};
  uint8_t validMask=0,freshMask=0;
};
struct SpiProbeRowLedger {
  uint32_t published=0,validBoth=0,freshBoth=0,digest=2166136261U;
  TimingSummary lag;
  SpiProbeRow prefix[4],last;
  void publish(const SpiProbeRow& row) {
    if(published<4)prefix[published]=row;
    last=row;++published;
    if(row.validMask==3)++validBoth;
    if(row.freshMask==3)++freshBoth;
    TimingStats_record(lag,static_cast<uint32_t>(row.publishedUs-row.scheduledUs));
    // FNV-1a over canonical little-endian fields; diagnostic, not a wire CRC.
    auto field=[this](uint64_t value,uint8_t bytes) {
      for(uint8_t i=0;i<bytes;++i){digest^=static_cast<uint8_t>(value);digest*=16777619U;value>>=8;}
    };
    field(row.index,4);field(row.scheduledUs,8);field(row.publishedUs,8);
    for(uint8_t i=0;i<2;++i){field(static_cast<uint32_t>(row.counts[i]),4);field(row.conversion[i],4);field(row.acquiredUs[i],8);}
    field(row.validMask,1);field(row.freshMask,1);
  }
};
#endif
