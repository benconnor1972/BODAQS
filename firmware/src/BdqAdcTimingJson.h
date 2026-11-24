#pragma once

#include <ArduinoJson.h>
#include "TimingStats.h"
#include "AdcConcentratedScan.h"

// Finalization-only diagnostics. Call after ADC workers have stopped; these are
// aggregate conversion/freshness counters, not per-reading acquisition times.
namespace BdqAdcTimingJson {
#if BODAQS_ADC_SPI_PHASE_TIMING
inline void spiPhases(JsonObject out,const ExternalAdcTimingStats::SpiPhases& s) {
  out["completed"]=s.completed;out["failed"]=s.failed;out["failed_wait_total_us"]=s.failedWaitUs;
  constexpr const char* names[]={"lock_wait_us","prepare_us","transfer_us","finish_us"};
  for(unsigned i=0;i<4;++i) {
    JsonObject phase=out[names[i]].to<JsonObject>();
    phase["total_us"]=s.totalUs[i];phase["max_us"]=s.maxUs[i];
    phase["avg_us"]=s.completed?static_cast<double>(s.totalUs[i])/s.completed:0.0;
  }
}
#endif
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
  static_assert((ExternalAdcTimingStats::kMaxAdcs==2 || ExternalAdcTimingStats::kMaxAdcs==4) && ExternalAdcTimingStats::kMaxChannels==4);
  for(unsigned i=0;i<ExternalAdcTimingStats::kMaxAdcs;++i) {
    const auto& a=stats.adc[i];
    if(!a.present && !a.activeChannels && !a.scanUs.count) continue;
    JsonObject value=out[adcKeys[i]].to<JsonObject>();
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
    value["concentrated_scan"]=a.concentratedScan;
    if(a.concentratedScan) {
      value["scan_starts"]=a.scanStarts;value["scan_missed_appointments"]=a.scanMissedAppointments;
      value["scan_maximum_lag_ticks"]=a.scanMaximumLagTicks;
#if BODAQS_ADC_BOUNDARY_BENCH
      value["scan_row_period_us"]=a.scanRowPeriodUs;
      value["scan_appointment_numerator_us"]=a.scanRowPeriodUs;
      value["scan_appointment_denominator"]=a.activeChannels;
      value["scan_appointment_us"]=a.activeChannels?a.scanRowPeriodUs/a.activeChannels:0;
      value["scan_scheduler"]=AdcConcentratedScan::usesTickCadence(a.scanRowPeriodUs,a.activeChannels)?"rtos_tick":"timer_deadline_notify";
      value["scan_maximum_lag_us"]=a.scanMaximumLagUs;
      const auto& w=stats.scanAppointmentWait;
      JsonObject wait=value["scan_appointment_wait"].to<JsonObject>();
      wait["enabled"]=!AdcConcentratedScan::usesTickCadence(a.scanRowPeriodUs,a.activeChannels);
      wait["scope"]="shared owner appointment wait wall time; repeated for each ADC, do not sum; excludes service body";
      wait["episodes"]=w.episodes;wait["arm_attempts"]=w.armAttempts;
      wait["arm_failures"]=w.armFailures;wait["elapsed_before_arm"]=w.elapsedBeforeArm;
      wait["early_wakes"]=w.earlyWakes;wait["due_wakes"]=w.dueWakes;
      wait["cancelled_wakes"]=w.cancelledWakes;
      wait["total_us"]=w.totalUs;wait["max_us"]=w.maxUs;
#else
      value["scan_appointment_us"]=1000;
#endif
      value["scan_reads"]=a.scanReads;value["scan_read_failures"]=a.scanReadFailures;
      value["scan_config_faults"]=a.scanConfigFaults;value["scan_wait_timeouts"]=a.scanWaitTimeouts;
      value["scan_spi_hz"]=BODAQS_ADC_SCAN_SPI_HZ;
      value["scan_setup_policy"]=BODAQS_ADC_SCAN_MUX_ONLY?"reg0_after_full_prime":"full_wreg_each_conversion";
      value["scan_full_prime_target"]=BODAQS_ADC_BOUNDARY_BENCH?a.activeChannels:2;value["scan_verified_registers"]=4;
#if BODAQS_ADC_SCAN_PIPELINE
      #if BODAQS_ADC_SCAN_ROW_PHASE
      value["scan_row_phase_offset_us"]=250;
      value["scan_row_phase_diagnostics_enabled"]=bool(BODAQS_ADC_ROW_PHASE_DIAGNOSTICS);
#if BODAQS_ADC_ROW_PHASE_DIAGNOSTICS
      value["scan_row_phase_scope"]="actual cache-copy observations modulo2000us since first validated runtime pipeline publication; two observations per two-column row";
      timing(value["scan_row_phase_us"].to<JsonObject>(),a.scanRowPhaseUs);
#else
      value["scan_row_phase_scope"]="disabled; phase alignment remains enabled; no per-row phase observations collected";
#endif
#endif
      value["scan_pipeline"]=true;value["scan_combined_calls"]=a.scanCombinedCalls;
      value["scan_unpublished_attempts"]=a.scanStarts-a.scanReads;
      value["scan_read_phase_scope"]="priming reads plus compound verified-read/next-start calls";
#endif
      value["scan_scope"]=BODAQS_ADC_BOUNDARY_BENCH
          ?"both ADCs contiguous equal1..4 channels; one owner, full-image prime per channel, verified single-shot pipeline; fractional microsecond appointments, no catch-up; shared wall intervals overlap"
          :BODAQS_ADC_DUAL_SCAN_BENCH
          ?"each active ADC channels0/1; one shared owner, verified single-shot pipeline, bounded1ms appointments; async_loop_us repeats shared owner wall time, not additive CPU time"
          :"ADC0 channels0/1; single-shot WREG+START, DRDY notification wait, register-verified read; bounded 1ms tick appointments; no catch-up";
    }
#endif
#if BODAQS_ADC_ROW_PACING
    timing(value["row_dispatch_lag_us"].to<JsonObject>(),a.rowDispatchLagUs);
    value["row_pacing_starts"]=a.rowPacingStarts;value["row_pacing_missed"]=a.rowPacingMissed;value["row_pacing_overruns"]=a.rowPacingOverruns;
#endif
#if BODAQS_ADC_CONTINUOUS_LATEST
    value["conversion_mode"]="continuous_latest_verified";
    value["total_us_scope"]="DRDY-qualified register-verification plus latest-result read; excludes conversion duration";
    value["cache_age_scope"]="time since software read/publication; not physical conversion age";
    value["continuous_running"]=a.continuousRunning;
    value["continuous_polls"]=a.continuousPolls;value["continuous_no_new"]=a.continuousNoNew;
    value["continuous_reads"]=a.continuousReads;value["continuous_config_faults"]=a.continuousConfigFaults;
    value["continuous_read_failures"]=a.continuousReadFailures;value["continuous_stalls"]=a.continuousStalls;
    value["continuous_stop_failures"]=a.continuousStopFailures;
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
    if(a.concentratedScan) {
      value["conversion_mode"]="paced_verified_single_shot_scan";
      value["total_us_scope"]="setup plus conversion wait plus register-verified data read; publication is after validation";
#if BODAQS_ADC_SCAN_PIPELINE
      value["total_us_scope"]="startup primes include setup/conversion wait/read; runtime appointment service includes remaining wait and compound read/next-start, excludes off-bus conversion time";
      value["config_us_scope"]="full startup prime setup and standalone pipeline seed; compound next-start is in read_us";
#endif
    }
#endif
#endif
    value["present"]=a.present;value["async_running"]=a.asyncRunning;
    value["active_channels"]=a.activeChannels;value["configured_sps"]=a.configuredSps;
    value["wait_timeouts"]=a.waitTimeouts;value["drdy_already_ready"]=a.drdyAlreadyReady;
    timing(value["scan_us"].to<JsonObject>(),a.scanUs);
    timing(value["async_loop_us"].to<JsonObject>(),a.asyncLoopUs);
    timing(value["config_us"].to<JsonObject>(),a.configUs);
    timing(value["start_us"].to<JsonObject>(),a.startUs);
    timing(value["wait_us"].to<JsonObject>(),a.waitUs);
    timing(value["read_us"].to<JsonObject>(),a.readUs);
#if BODAQS_ADC_SPI_PHASE_TIMING
    JsonObject phases=value["shared_spi_phases"].to<JsonObject>();
    phases["version"]=1;
    phases["scope"]="completed_adc_calls_wall_clock; wait_includes_pacing; transfer_includes_HAL; finish_excludes_unlock";
    spiPhases(phases["setup_start"].to<JsonObject>(),a.setupSpi);
    spiPhases(phases["read_data"].to<JsonObject>(),a.readSpi);
#endif
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
