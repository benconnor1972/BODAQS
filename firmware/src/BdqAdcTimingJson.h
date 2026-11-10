#pragma once

#include <ArduinoJson.h>
#include "TimingStats.h"

// Finalization-only diagnostics. Call after ADC workers have stopped; these are
// aggregate conversion/freshness counters, not per-reading acquisition times.
namespace BdqAdcTimingJson {
inline void timing(JsonObject out, const TimingSummary& s) {
  out["count"]=s.count;out["min_us"]=s.minUs;out["max_us"]=s.maxUs;
  out["total_us"]=s.totalUs;
  out["avg_us"]=s.count?static_cast<double>(s.totalUs)/s.count:0.0;
  JsonObject buckets=out["buckets_us"].to<JsonObject>();
  buckets["lt_250"]=s.bucketLt250;buckets["250_500"]=s.bucket250To500;
  buckets["500_1000"]=s.bucket500To1000;buckets["1000_1500"]=s.bucket1000To1500;
  buckets["1500_2000"]=s.bucket1500To2000;buckets["ge_2000"]=s.bucketGe2000;
}
inline void append(JsonObject out, const ExternalAdcTimingStats& stats) {
  constexpr const char* adcKeys[]={"adc0","adc1","adc2","adc3"};
  constexpr const char* channelKeys[]={"ch0","ch1","ch2","ch3"};
  static_assert(ExternalAdcTimingStats::kMaxAdcs==4 && ExternalAdcTimingStats::kMaxChannels==4);
  for(unsigned i=0;i<4;++i) {
    const auto& a=stats.adc[i];
    if(!a.present && !a.activeChannels && !a.scanUs.count) continue;
    JsonObject value=out[adcKeys[i]].to<JsonObject>();
    value["present"]=a.present;value["async_running"]=a.asyncRunning;
    value["active_channels"]=a.activeChannels;value["configured_sps"]=a.configuredSps;
    value["wait_timeouts"]=a.waitTimeouts;value["drdy_already_ready"]=a.drdyAlreadyReady;
    timing(value["scan_us"].to<JsonObject>(),a.scanUs);
    timing(value["async_loop_us"].to<JsonObject>(),a.asyncLoopUs);
    timing(value["config_us"].to<JsonObject>(),a.configUs);
    timing(value["start_us"].to<JsonObject>(),a.startUs);
    timing(value["wait_us"].to<JsonObject>(),a.waitUs);
    timing(value["read_us"].to<JsonObject>(),a.readUs);
    JsonObject channels=value["channels"].to<JsonObject>();
    for(unsigned ch=0;ch<4;++ch) {
      const auto& c=a.channel[ch];
      if(!c.totalUs.count && !c.waitUs.count && !c.rowUses) continue;
      JsonObject v=channels[channelKeys[ch]].to<JsonObject>();
      timing(v["total_us"].to<JsonObject>(),c.totalUs);
      timing(v["wait_us"].to<JsonObject>(),c.waitUs);
      timing(v["row_age_us"].to<JsonObject>(),c.rowAgeUs);
      v["acquire_ok"]=c.acquireOk;v["acquire_fail"]=c.acquireFail;
      v["row_uses"]=c.rowUses;v["row_fresh"]=c.rowFresh;
      v["row_reused"]=c.rowReused;v["row_no_sample"]=c.rowNoSample;
    }
  }
}
} // namespace BdqAdcTimingJson
