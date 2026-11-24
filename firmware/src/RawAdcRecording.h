#pragma once
#include <stddef.h>
#include <stdint.h>
#include "BdqV2Format.h"
#include "AdcConcentratedScan.h"
#include "AdcAcquisitionPlan.h"

#ifndef BODAQS_PRODUCTION_RECORDING
#define BODAQS_PRODUCTION_RECORDING 0
#endif

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
#if BODAQS_PRODUCTION_RECORDING
constexpr unsigned kColumns = LocalAnalogRecordingPlan::kMaximumColumns;
#else
constexpr unsigned kColumns = 2 * kChannelsPerAdc;
#endif
constexpr unsigned recordBytes(unsigned columns) { return 12 + 2 * columns; }
constexpr unsigned kRecordBytes = 12 + 2 * kColumns;
constexpr unsigned kRateHz = kChannelsPerAdc == 1 ? 1000 : (kChannelsPerAdc == 2 ? 650 : (kChannelsPerAdc == 3 ? 400 : 300));
inline bool supportsGeometry(unsigned rateHz,unsigned columns) {
  #if BODAQS_PRODUCTION_RECORDING
  return rateHz > 0 && rateHz <= 2000 && columns <= kColumns;
#elif BODAQS_ADC_RATE_SWEEP_BENCH
  return columns==kColumns && AdcConcentratedScan::boundaryCase(kChannelsPerAdc,rateHz);
#else
  return rateHz==kRateHz && columns==kColumns;
#endif
}
}

// Production copies the declared typed prefix in configured sensor order.
// Diagnostic layouts retain their historical RAM layout and storage encoding.
struct RawAdcRecord {
  uint32_t sequence=0,tick=0;
#if BODAQS_PRODUCTION_RECORDING
  // ESP32 is little-endian. The producer copies only the configured prefix.
  uint16_t status=0,reserved=0,counts[RawAdcRecording::kColumns]={};
#else
  uint16_t counts[RawAdcRecording::kColumns]={},status=0,reserved=0;
#endif
};
#if BODAQS_PRODUCTION_RECORDING
static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "Typed recording prefix requires little-endian target");
static_assert(offsetof(RawAdcRecord, status) == 8 && offsetof(RawAdcRecord, counts) == 12,
              "Typed recording prefix must match the declared BDQ offsets");
#endif
static_assert(sizeof(RawAdcRecord)==RawAdcRecording::kRecordBytes,
              "RAM queue records match the existing primary record size");

namespace RawAdcRecording {
constexpr uint16_t kSensorError=0x0020;
inline uint16_t count(int32_t value,uint16_t& status) {
  if(value<0){status|=kSensorError;return 0;}
  if(value>4095){status|=kSensorError;return 4095;}
  return static_cast<uint16_t>(value);
}
inline bool encode(const RawAdcRecord& record,uint8_t* out,size_t capacity,unsigned columns=kColumns) {
  if(!out || columns>kColumns || capacity<recordBytes(columns) || record.reserved)return false;
  const BdqV2Format::StreamRecordPrefix prefix={record.sequence,record.tick,record.status,0};
  if(!BdqV2Format::encodeStreamRecordPrefix(prefix,out,capacity))return false;
  for(unsigned column=0;column<columns;++column)
    BdqV2Format::putU16(out+12+2*column,record.counts[column]);
  return true;
}
}

// Read only after producer and storage owner retirement; no concurrent live UI.
struct RawAdcRecordingStats {
  bool active=false,qualified=false;
  uint32_t capacity=0,submitted=0,enqueued=0,encoded=0,rejected=0,genericAttempts=0;
};
