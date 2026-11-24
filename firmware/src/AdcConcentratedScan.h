#pragma once
#include <stdint.h>
#ifndef BODAQS_ADC_BOUNDARY_BENCH
#define BODAQS_ADC_BOUNDARY_BENCH 0
#endif
#if BODAQS_ADC_BOUNDARY_BENCH != 0 && BODAQS_ADC_BOUNDARY_BENCH != 1
#error "ADC boundary bench must be 0 or 1"
#endif
#if BODAQS_ADC_BOUNDARY_BENCH && (!BODAQS_ADC_DUAL_SCAN_BENCH || !BODAQS_ADC_COMBINED_CAPTURE)
#error "ADC boundary bench requires dual scan and combined capture"
#endif
#ifndef BODAQS_ADC_ROW_PHASE_DIAGNOSTICS
#define BODAQS_ADC_ROW_PHASE_DIAGNOSTICS 1
#endif
#if BODAQS_ADC_ROW_PHASE_DIAGNOSTICS != 0 && BODAQS_ADC_ROW_PHASE_DIAGNOSTICS != 1
#error "Row phase diagnostics must be 0 or 1"
#endif
#ifndef BODAQS_ADC_SCAN_PIPELINE
#define BODAQS_ADC_SCAN_PIPELINE 0
#endif
#ifndef BODAQS_ADC_DUAL_SCAN_BENCH
#define BODAQS_ADC_DUAL_SCAN_BENCH 0
#endif
#if BODAQS_ADC_DUAL_SCAN_BENCH != 0 && BODAQS_ADC_DUAL_SCAN_BENCH != 1
#error "Dual scan bench must be 0 or 1"
#endif
#if BODAQS_ADC_DUAL_SCAN_BENCH && (!BODAQS_ADC_SCAN_PIPELINE || !BODAQS_ADC_COMBINED_CAPTURE || !BODAQS_ADC_INLINE_ROW)
#error "Dual scan requires the verified pipeline and inline combined row owner"
#endif
#if BODAQS_ADC_SCAN_PIPELINE != 0 && BODAQS_ADC_SCAN_PIPELINE != 1
#error "Pipeline flag must be 0 or 1"
#endif

#ifndef BODAQS_ADC_CONCENTRATED_SCAN_BENCH
#define BODAQS_ADC_CONCENTRATED_SCAN_BENCH 0
#endif
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH != 0 && BODAQS_ADC_CONCENTRATED_SCAN_BENCH != 1
#error "Concentrated ADC scan bench must be 0 or 1"
#endif
#ifndef BODAQS_ADC_SCAN_MUX_ONLY
#define BODAQS_ADC_SCAN_MUX_ONLY 0
#endif
#ifndef BODAQS_ADC_SCAN_SPI_HZ
#define BODAQS_ADC_SCAN_SPI_HZ 1000000
#endif
#if BODAQS_ADC_SCAN_PIPELINE && (!BODAQS_ADC_SCAN_MUX_ONLY || !BODAQS_ADC_CONCENTRATED_SCAN_BENCH)
#error "Pipeline requires concentrated register0-only bench"
#endif
#if BODAQS_ADC_SCAN_MUX_ONLY != 0 && BODAQS_ADC_SCAN_MUX_ONLY != 1
#error "Scan register0-only flag must be0 or1"
#endif
#if BODAQS_ADC_SCAN_SPI_HZ != 1000000 && BODAQS_ADC_SCAN_SPI_HZ != 2000000
#error "Selected scan SPI trial supports1MHz or2MHz"
#endif
#if !BODAQS_ADC_CONCENTRATED_SCAN_BENCH && (BODAQS_ADC_SCAN_MUX_ONLY || BODAQS_ADC_SCAN_SPI_HZ != 1000000)
#error "Scan optimizations require the explicit concentrated bench"
#endif

#ifndef BODAQS_ADC_RATE_SWEEP_BENCH
#define BODAQS_ADC_RATE_SWEEP_BENCH 0
#endif
#if BODAQS_ADC_RATE_SWEEP_BENCH && !BODAQS_ADC_BOUNDARY_BENCH
#error "ADC rate sweep requires the explicit boundary bench"
#endif
#ifndef BODAQS_ADC_FORCE_TIMER_BENCH
#define BODAQS_ADC_FORCE_TIMER_BENCH 0
#endif
#if BODAQS_ADC_FORCE_TIMER_BENCH != 0 && BODAQS_ADC_FORCE_TIMER_BENCH != 1
#error "Force timer bench must be0 or1"
#endif
#if BODAQS_ADC_FORCE_TIMER_BENCH && !BODAQS_ADC_BOUNDARY_BENCH
#error "Force timer requires the explicit boundary bench"
#endif
namespace AdcConcentratedScan {
constexpr bool usesTickCadence(uint32_t rowUs,unsigned channels) {
  return !BODAQS_ADC_FORCE_TIMER_BENCH && rowUs==1000u*channels;
}
// Diagnostic operating points, per ADC. Both devices use the same contiguous
// channel mask and one shared row rate. This is not a production admission rule.
constexpr bool boundaryCase(unsigned channels,unsigned hz) {
#if BODAQS_ADC_RATE_SWEEP_BENCH
  return (channels==1 && (hz==700 || hz==1000 || hz==1200 || hz==1500 || hz==1667 || hz==2000)) ||
         (channels==2 && (hz==500 || hz==650 || hz==700 || hz==800 || hz==900 || hz==1000)) ||
         (channels==3 && (hz==300 || hz==400 || hz==500 || hz==550 || hz==600 || hz==650)) ||
         (channels==4 && (hz==200 || hz==300 || hz==400 || hz==450 || hz==500));
#else
  return (channels==1 && (hz==700 || hz==1000)) || (channels==2 && (hz==500 || hz==650 || hz==700)) ||
         (channels==3 && (hz==400 || hz==500)) || (channels==4 && (hz==200 || hz==300));
#endif
}
// An absolute microsecond cadence distributes a row period across its channels.
// It skips late deadlines without catch-up transfers or changing pending MUX
// identity. The remainder preserves exact row periods (e.g. 666/667/667us).
struct MicroAppointment { uint32_t waitUs,missed,lagUs; };
inline MicroAppointment claimMicros(uint64_t now,uint64_t& next,uint32_t rowUs,
                                   unsigned channels,unsigned& remainder) {
  if(now<next)return {static_cast<uint32_t>(next-now),0,0};
  const uint64_t lag=now-next;
  const uint64_t missed=((lag+1)*channels-1-remainder)/rowUs;
  const uint64_t advance=(missed+1)*rowUs+remainder;
  next+=advance/channels;remainder=static_cast<unsigned>(advance%channels);
  return {0,static_cast<uint32_t>(missed),static_cast<uint32_t>(lag)};
}
// Tick deadlines stay within INT32_MAX ticks of now. A late conversion never
// causes catch-up bursts; skipped slots do not advance the channel alternation.
struct Appointment { uint32_t waitTicks,missed,lagTicks; };
inline Appointment claim(uint32_t now,uint32_t& next,uint32_t period) {
  const int32_t lag=static_cast<int32_t>(now-next);
  if(lag<0)return {static_cast<uint32_t>(next-now),0,0};
  const uint32_t missed=static_cast<uint32_t>(lag)/period;
  next+=(missed+1)*period;
  return {0,missed,static_cast<uint32_t>(lag)};
}
}
