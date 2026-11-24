#pragma once
#include <stddef.h>
#include <stdint.h>
#include "BdqV2Format.h"
#include "AdcConcentratedScan.h"

#ifndef BODAQS_ADC_RAW_RECORDING_BENCH
#define BODAQS_ADC_RAW_RECORDING_BENCH 0
#endif
#ifndef BODAQS_ADC_RAW_CHANNELS_PER_ADC
#define BODAQS_ADC_RAW_CHANNELS_PER_ADC 1
#endif

namespace RawAdcRecording {
constexpr unsigned kChannelsPerAdc = BODAQS_ADC_RAW_CHANNELS_PER_ADC;
static_assert(kChannelsPerAdc >= 1 && kChannelsPerAdc <= 4,
              "Raw recording supports the qualified one/two/three/four-channel layouts");
constexpr unsigned kColumns = 2 * kChannelsPerAdc;
constexpr unsigned kRecordBytes = 12 + 2 * kColumns;
constexpr unsigned kRateHz = kChannelsPerAdc == 1 ? 1000 : (kChannelsPerAdc == 2 ? 650 : (kChannelsPerAdc == 3 ? 400 : 300));
inline bool supportsGeometry(unsigned rateHz,unsigned columns) {
  #if BODAQS_ADC_RATE_SWEEP_BENCH
  return columns==kColumns && AdcConcentratedScan::boundaryCase(kChannelsPerAdc,rateHz);
#else
  return rateHz==kRateHz && columns==kColumns;
#endif
}
}

// Private RAM representation, not a wire struct. The storage owner serializes it.
// Columns retain the configured AIN0,AIN4[,AIN1,AIN5[,AIN2,AIN6[,AIN3,AIN7]]] order.
struct RawAdcRecord {
  uint32_t sequence=0,tick=0;
  uint16_t counts[RawAdcRecording::kColumns]={},status=0,reserved=0;
};
static_assert(sizeof(RawAdcRecord)==RawAdcRecording::kRecordBytes,
              "RAM queue records match the existing primary record size");

namespace RawAdcRecording {
constexpr uint16_t kSensorError=0x0020;
inline uint16_t count(int32_t value,uint16_t& status) {
  if(value<0){status|=kSensorError;return 0;}
  if(value>UINT16_MAX){status|=kSensorError;return UINT16_MAX;}
  return static_cast<uint16_t>(value);
}
inline bool encode(const RawAdcRecord& record,uint8_t* out,size_t capacity) {
  if(!out || capacity<kRecordBytes || record.reserved)return false;
  const BdqV2Format::StreamRecordPrefix prefix={record.sequence,record.tick,record.status,0};
  if(!BdqV2Format::encodeStreamRecordPrefix(prefix,out,capacity))return false;
  for(unsigned column=0;column<kColumns;++column)
    BdqV2Format::putU16(out+12+2*column,record.counts[column]);
  return true;
}
}

// Read only after producer and storage owner retirement; no concurrent live UI.
struct RawAdcRecordingStats {
  bool active=false,qualified=false;
  uint32_t capacity=0,submitted=0,enqueued=0,encoded=0,rejected=0,genericAttempts=0;
};
