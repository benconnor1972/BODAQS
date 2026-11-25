#include "BdqAdcTimingJson.h"
#include "BdqLogWriter.h"
#include "MeasurementReplyCapture.h"
#include "../can-fd/common/protocol/bodaqs_measurement.h"
#include <cassert>
#include <string>
#include <cstdio>

static bool failuresAvailable=true;
static MeasurementReplyCapture replyCapture;
namespace RemoteImuRecording {
const uint32_t* finalMeasurementDecodeReasons() {
 static uint32_t reasons[BODAQS_MEASUREMENT_DECODE_COUNT]={};
 reasons[BODAQS_MEASUREMENT_DECODE_MAGIC]=11;return failuresAvailable?reasons:nullptr;
}
const MeasurementReplyCapture* finalRejectedMeasurementReplies() {return failuresAvailable?&replyCapture:nullptr;}
bool finalMeasurementFailures(uint32_t& transfer,uint32_t& decode) {
  if(!failuresAvailable) return false;
  transfer=7;decode=11;return true;
}
}
// PRODUCTION_APPEND

#if BODAQS_ADC_ROW_PACING
#include <type_traits>
#include <utility>
template<class T,class=void>struct HasRowDispatchLag:std::false_type{};
template<class T>struct HasRowDispatchLag<T,std::void_t<decltype(std::declval<T>().rowDispatchLagUs)>>:std::true_type{};
static_assert(HasRowDispatchLag<ExternalAdcTimingStats::AdcStats>::value);
static_assert(!HasRowDispatchLag<SensorTimingStats::SensorStats>::value);
static_assert(!HasRowDispatchLag<I2CBusSchedulerTimingStats::BusStats>::value);
static_assert(!HasRowDispatchLag<I2CBusSchedulerTimingStats::ClientStats>::value);
#endif
int main() {
  ExternalAdcTimingStats stats;
  for(unsigned a=0;a<2;++a) {
    auto& adc=stats.adc[a];adc.present=true;adc.activeChannels=1;adc.configuredSps=1000;
    adc.configUs.count=23+a;adc.configUs.totalUs=UINT64_C(9000000000)+a;
    adc.waitTimeouts=a;adc.startUs.count=0;
#if BODAQS_ADC_SPI_PHASE_TIMING
    adc.setupSpi.completed=2;adc.setupSpi.failed=1;adc.setupSpi.failedWaitUs=50000;
    adc.setupSpi.totalUs[0]=UINT64_C(9000000000)+a;adc.setupSpi.maxUs[0]=123;
    adc.setupSpi.totalUs[1]=22;adc.setupSpi.totalUs[2]=96;adc.setupSpi.totalUs[3]=14;
#endif
#if BODAQS_ADC_ROW_PACING
    adc.rowDispatchLagUs.count=4;adc.rowDispatchLagUs.totalUs=1700;adc.rowDispatchLagUs.maxUs=700;
    adc.rowPacingStarts=500;adc.rowPacingMissed=3;adc.rowPacingOverruns=2;
#endif
    auto& ch=adc.channel[0];ch.acquireOk=20+a;ch.acquireFail=a;ch.rowUses=12+a;
    ch.rowFresh=10;ch.rowReused=1+a;ch.rowNoSample=1;
    ch.rowAgeUs.count=11+a;ch.rowAgeUs.totalUs=1234+a;ch.rowAgeUs.maxUs=456+a;
  }
  BdqLogEndInfo info;info.externalAdcTiming=&stats;
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
  stats.adc[0].concentratedScan=true;stats.adc[0].scanStarts=12;stats.adc[0].scanReads=12;
  stats.adc[0].scanMissedAppointments=3;stats.adc[0].scanMaximumLagTicks=2;
#endif
  JsonDocument document;document["summary_format"]="bdq.final_summary.v2";
  appendBdqV2AdcTiming_(document,info);
  std::string bytes;serializeJson(document,bytes);
  JsonDocument parsed;assert(!deserializeJson(parsed,bytes));
  auto adcs=parsed["external_adc_timing"];
  assert(adcs.size()==2);
#if BODAQS_ADC_ROW_PACING
  assert(adcs["adc0"]["row_pacing_starts"]==500);
  assert(adcs["adc1"]["row_dispatch_lag_us"]["count"]==4 && adcs["adc1"]["row_dispatch_lag_us"]["max_us"]==700);
  assert(adcs["adc1"]["row_pacing_missed"]==3 && adcs["adc1"]["row_pacing_overruns"]==2);
#endif
  assert(parsed["external_adc_timing_status"]=="complete");
#if BODAQS_ADC_CONTINUOUS_LATEST
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
  assert(adcs["adc0"]["conversion_mode"]=="paced_verified_single_shot_scan");
  assert(adcs["adc0"]["concentrated_scan"].as<bool>());
  assert(adcs["adc0"]["scan_starts"].as<unsigned>()==12 && adcs["adc0"]["scan_reads"].as<unsigned>()==12);
  assert(adcs["adc0"]["scan_appointment_us"].as<unsigned>()==1000);
  assert(adcs["adc0"]["scan_spi_hz"].as<unsigned>()==BODAQS_ADC_SCAN_SPI_HZ);
  assert(adcs["adc0"]["scan_setup_policy"]==(BODAQS_ADC_SCAN_MUX_ONLY?"reg0_after_full_prime":"full_wreg_each_conversion"));
  assert(adcs["adc0"]["scan_full_prime_target"]==2 && adcs["adc0"]["scan_verified_registers"]==4);
  assert(adcs["adc1"]["scan_spi_hz"].isNull());
  assert(adcs["adc0"]["scan_missed_appointments"].as<unsigned>()==3);
  assert(adcs["adc0"]["scan_maximum_lag_ticks"].as<unsigned>()==2);
  assert(!adcs["adc1"]["concentrated_scan"].as<bool>() && adcs["adc1"]["scan_starts"].isNull());
  assert(adcs["adc1"]["conversion_mode"]=="continuous_latest_verified");
#else
  assert(adcs["adc0"]["conversion_mode"]=="continuous_latest_verified");
#endif
  assert(adcs["adc1"]["continuous_polls"].as<unsigned>()==0);
  assert(!adcs["adc1"]["continuous_running"].as<bool>());
  assert(adcs["adc0"]["row_pacing_starts"].isNull());
#endif
  assert(adcs["adc0"]["config_us"]["total_us"].as<uint64_t>()==UINT64_C(9000000000));
  assert(adcs["adc1"]["config_us"]["total_us"].as<uint64_t>()==UINT64_C(9000000001));
  assert(adcs["adc1"]["wait_timeouts"].as<unsigned>()==1);
  assert(adcs["adc0"]["start_us"]["count"].as<unsigned>()==0);
#if BODAQS_ADC_SPI_PHASE_TIMING
  assert(adcs["adc0"]["shared_spi_phases"]["version"]==1);
  auto setup=adcs["adc1"]["shared_spi_phases"]["setup_start"];
  assert(!setup["transfer_us"].isNull() && !setup["finish_us"].isNull());
  assert(setup["completed"]==2 && setup["failed"]==1 && setup["failed_wait_total_us"]==50000);
  assert(setup["lock_wait_us"]["total_us"].as<uint64_t>()==UINT64_C(9000000001));
  assert(setup["prepare_us"]["avg_us"].as<double>()==11.0);
  assert(adcs["adc0"]["shared_spi_phases"]["read_data"]["transfer_us"]["avg_us"].as<double>()==0.0);
#else
  assert(adcs["adc0"]["shared_spi_phases"].isNull());
#endif
  auto ch=adcs["adc1"]["channels"]["ch0"];
  assert(ch["acquire_ok"].as<unsigned>()==21 && ch["acquire_fail"].as<unsigned>()==1);
  assert(ch["row_fresh"].as<unsigned>()==10 && ch["row_reused"].as<unsigned>()==2);
  assert(ch["row_no_sample"].as<unsigned>()==1 && ch["row_age_us"]["max_us"].as<unsigned>()==457);
  JsonDocument empty;info.externalAdcTiming=nullptr;appendBdqV2AdcTiming_(empty,info);
  assert(empty["external_adc_timing"].isNull());
  assert(empty["external_adc_timing_status"]=="worker_not_retired");
  appendBdqV2MeasurementFailures_(document);
  replyCapture.count=4;
  for(unsigned i=0;i<4;++i) {
    auto& entry=replyCapture.entries[i];entry.slot=100+i;entry.requestKind=14;
    entry.decodeReason=BODAQS_MEASUREMENT_DECODE_MAGIC;
    entry.bus.valid=true;entry.bus.cs=4;entry.bus.previousValid=true;
    entry.bus.previousCs=10;entry.bus.previousCommand=0x12;entry.bus.previousBytes=4;
    for(unsigned b=0;b<256;++b) entry.reply[b]=uint8_t(b+i);
  }
  appendBdqV2MeasurementFailures_(document);
  bytes.clear();serializeJson(document,bytes);assert(!deserializeJson(parsed,bytes));
  auto failures=parsed["remote_measurement_failures"];
  assert(failures["available"]==true && failures["transfer_failed_slots"]==7 && failures["decode_failed_slots"]==11);
  assert(failures["scope"]=="measurement_mode_through_cleanup");
  assert(failures["decode_reasons"]["magic"]==11 && failures["decode_reasons"]["crc"]==0);
  auto replies=failures["rejected_replies"];
  assert(replies["available"]==true && replies["captured"]==4 && replies["capacity"]==4);
  assert(replies["entries"].size()==4);
  for(unsigned i=0;i<4;++i) {
    auto entry=replies["entries"][i];assert(entry["slot"]==100+i && entry["request_kind"]==14);
    assert(entry["decode_reason"]=="magic" && entry["bus"]["available"]==true);
    assert(entry["bus"]["previous_cs"]==10 && entry["bus"]["previous_command"]==0x12 && entry["bus"]["previous_bytes"]==4);
    const std::string hex=entry["reply_hex"].as<std::string>();assert(hex.size()==512);
    for(unsigned b=0;b<256;++b) assert(std::stoul(hex.substr(2*b,2),nullptr,16)==uint8_t(b+i));
  }
  failuresAvailable=false;appendBdqV2MeasurementFailures_(empty);
  assert(empty["remote_measurement_failures"]["available"]==false);
  assert(empty["remote_measurement_failures"]["transfer_failed_slots"].isNull());
  assert(empty["remote_measurement_failures"]["rejected_replies"]["available"]==false);
  assert(empty["remote_measurement_failures"]["rejected_replies"]["entries"].isNull());
  failuresAvailable=true;replyCapture.count=0;JsonDocument zero;appendBdqV2MeasurementFailures_(zero);
  assert(zero["remote_measurement_failures"]["rejected_replies"]["available"]==true);
  assert(zero["remote_measurement_failures"]["rejected_replies"]["entries"].size()==0);
  puts("Production v2 footer ADC snapshot: both ADCs, 64-bit costs, failure/freshness and absent snapshot PASS");
}
