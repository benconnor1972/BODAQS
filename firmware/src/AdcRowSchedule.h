#pragma once
#include <stdint.h>
#ifndef BODAQS_ADC_ROW_MAX_START_LAG_US
#define BODAQS_ADC_ROW_MAX_START_LAG_US 300
#endif
#if BODAQS_ADC_ROW_MAX_START_LAG_US <= 0 || BODAQS_ADC_ROW_MAX_START_LAG_US >= 1800
#error "ADC latest start must be positive and before the common completion target"
#endif
namespace AdcRowSchedule {
constexpr int64_t periodUs=2000, completionUs=1800, maxStartLagUs=BODAQS_ADC_ROW_MAX_START_LAG_US;
struct Decision {bool acquire=false,observed=false;uint32_t missed=0,startLagUs=0;int64_t deadline=0;};
inline Decision claim(int64_t now,int64_t origin,int64_t& previous) {
  Decision d;if(now<origin)return d;
  const int64_t epoch=(now-origin)/periodUs;
  if(epoch<=previous)return d;
  d.observed=true;d.startLagUs=static_cast<uint32_t>((now-origin)%periodUs);
  d.missed=static_cast<uint32_t>(epoch-previous-1);previous=epoch;
  if((now-origin)%periodUs>maxStartLagUs){++d.missed;return d;}
  d.acquire=true;d.deadline=origin+epoch*periodUs+completionUs;return d;
}
}
