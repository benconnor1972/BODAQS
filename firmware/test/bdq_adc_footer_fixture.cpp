#include "BdqAdcTimingJson.h"
#include "BdqLogWriter.h"
#include <cassert>
#include <string>
#include <cstdio>

// PRODUCTION_APPEND

int main() {
  ExternalAdcTimingStats stats;
  for(unsigned a=0;a<2;++a) {
    auto& adc=stats.adc[a];adc.present=true;adc.activeChannels=1;adc.configuredSps=1000;
    adc.configUs.count=23+a;adc.configUs.totalUs=UINT64_C(9000000000)+a;
    adc.waitTimeouts=a;adc.startUs.count=0;
    auto& ch=adc.channel[0];ch.acquireOk=20+a;ch.acquireFail=a;ch.rowUses=12+a;
    ch.rowFresh=10;ch.rowReused=1+a;ch.rowNoSample=1;
    ch.rowAgeUs.count=11+a;ch.rowAgeUs.totalUs=1234+a;ch.rowAgeUs.maxUs=456+a;
  }
  BdqLogEndInfo info;info.externalAdcTiming=&stats;
  JsonDocument document;document["summary_format"]="bdq.final_summary.v2";
  appendBdqV2AdcTiming_(document,info);
  std::string bytes;serializeJson(document,bytes);
  JsonDocument parsed;assert(!deserializeJson(parsed,bytes));
  auto adcs=parsed["external_adc_timing"];
  assert(adcs.size()==2);
  assert(parsed["external_adc_timing_status"]=="complete");
  assert(adcs["adc0"]["config_us"]["total_us"].as<uint64_t>()==UINT64_C(9000000000));
  assert(adcs["adc1"]["config_us"]["total_us"].as<uint64_t>()==UINT64_C(9000000001));
  assert(adcs["adc1"]["wait_timeouts"].as<unsigned>()==1);
  assert(adcs["adc0"]["start_us"]["count"].as<unsigned>()==0);
  auto ch=adcs["adc1"]["channels"]["ch0"];
  assert(ch["acquire_ok"].as<unsigned>()==21 && ch["acquire_fail"].as<unsigned>()==1);
  assert(ch["row_fresh"].as<unsigned>()==10 && ch["row_reused"].as<unsigned>()==2);
  assert(ch["row_no_sample"].as<unsigned>()==1 && ch["row_age_us"]["max_us"].as<unsigned>()==457);
  JsonDocument empty;info.externalAdcTiming=nullptr;appendBdqV2AdcTiming_(empty,info);
  assert(empty["external_adc_timing"].isNull());
  assert(empty["external_adc_timing_status"]=="worker_not_retired");
  puts("Production v2 footer ADC snapshot: both ADCs, 64-bit costs, failure/freshness and absent snapshot PASS");
}
