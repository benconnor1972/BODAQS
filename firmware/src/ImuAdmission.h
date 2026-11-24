#pragma once
#include <stdint.h>
#include <stddef.h>
#include "AdcConcentratedScan.h"
namespace ImuAdmission {

#if defined(BODAQS_ADC_CHANNEL_RATE_BENCH) && BODAQS_ADC_CHANNEL_RATE_BENCH != 0 && BODAQS_ADC_CHANNEL_RATE_BENCH != 1
#error BODAQS_ADC_CHANNEL_RATE_BENCH must be 0 or 1
#endif

constexpr bool channelRateBenchBuild() {
#if defined(BODAQS_ADC_CHANNEL_RATE_BENCH) && BODAQS_ADC_CHANNEL_RATE_BENCH == 1
 static_assert(BODAQS_SINGLE_NODE_IMU_ADC_SMOKE == 1, "Channel/rate bench requires ADC smoke scope");
 return true;
#else
 return false;
#endif
}
enum class Reason : uint8_t { None, Unqualified, Link, CanCapacity, SpiCapacity, DrainCapacity, Coverage, Allocation, Eligibility, SmokeScope, MixedSmokeScope, MultiNodeBenchScope, SampleUnitBenchScope, BulkMixedBenchScope };
#if defined(BODAQS_ADC_SCALING_BENCH) && BODAQS_ADC_SCALING_BENCH != 0 && BODAQS_ADC_SCALING_BENCH != 1
#error BODAQS_ADC_SCALING_BENCH must be 0 or 1
#endif
constexpr bool scalingBenchBuild() {
#if defined(BODAQS_ADC_SCALING_BENCH) && BODAQS_ADC_SCALING_BENCH == 1
 static_assert(channelRateBenchBuild(), "Scaling bench requires channel/rate bench scope");
 return true;
#else
 return false;
#endif
}
constexpr bool singleNodeSmokeBuild() {
#if defined(BODAQS_SINGLE_NODE_IMU_SMOKE) && BODAQS_SINGLE_NODE_IMU_SMOKE == 1
 return true;
#else
 return false;
#endif
}
#if defined(BODAQS_V3_TWO_NODE_BENCH) && BODAQS_V3_TWO_NODE_BENCH != 0 && BODAQS_V3_TWO_NODE_BENCH != 1
#error BODAQS_V3_TWO_NODE_BENCH must be 0 or 1
#endif
constexpr bool sampleUnitBenchBuild() {
#if defined(BODAQS_V3_TWO_NODE_BENCH) && BODAQS_V3_TWO_NODE_BENCH == 1
#if !defined(BODAQS_SPI_MEASUREMENT_V3) || BODAQS_SPI_MEASUREMENT_V3 != 1
#error Sample-unit two-node bench requires v3 measurement
#endif
#if (defined(BODAQS_SINGLE_NODE_IMU_ADC_SMOKE) && BODAQS_SINGLE_NODE_IMU_ADC_SMOKE == 1) || (defined(BODAQS_MULTI_NODE_BENCH) && BODAQS_MULTI_NODE_BENCH == 1)
#error Sample-unit bench cannot enable legacy ADC or multi-node admission
#endif
 static_assert(singleNodeSmokeBuild(), "Sample-unit bench requires compact sample custody");
 return true;
#else
 return false;
#endif
}
#if defined(BODAQS_V4_FOUR_NODE_BENCH) && BODAQS_V4_FOUR_NODE_BENCH != 0 && BODAQS_V4_FOUR_NODE_BENCH != 1
#error BODAQS_V4_FOUR_NODE_BENCH must be 0 or 1
#endif
constexpr bool fourNodeSampleUnitBenchBuild() {
#if defined(BODAQS_V4_FOUR_NODE_BENCH) && BODAQS_V4_FOUR_NODE_BENCH == 1
#if !defined(BODAQS_SPI_MEASUREMENT_V4) || BODAQS_SPI_MEASUREMENT_V4 != 1
#error Four-node sample-unit bench requires v4 measurement
#endif
 static_assert(sampleUnitBenchBuild(), "Four-node bench requires sample-unit custody and ADC-off scope");
 return true;
#else
 return false;
#endif
}
#if defined(BODAQS_MULTI_NODE_BENCH) && BODAQS_MULTI_NODE_BENCH != 0 && BODAQS_MULTI_NODE_BENCH != 1
#error BODAQS_MULTI_NODE_BENCH must be 0 or 1
#endif
constexpr bool multiNodeBenchBuild() {
#if defined(BODAQS_MULTI_NODE_BENCH) && BODAQS_MULTI_NODE_BENCH == 1
 static_assert(scalingBenchBuild() && singleNodeSmokeBuild(), "Multi-node bench requires compact scaling scope");
 return true;
#else
 return false;
#endif
}
#ifndef BODAQS_BULK_MIXED_ADC_BENCH
#define BODAQS_BULK_MIXED_ADC_BENCH 0
#endif
#if BODAQS_BULK_MIXED_ADC_BENCH != 0 && BODAQS_BULK_MIXED_ADC_BENCH != 1
#error "Bulk mixed ADC bench must be0or1"
#endif
constexpr bool bulkMixedAdcBenchBuild() {
#if BODAQS_BULK_MIXED_ADC_BENCH
 static_assert(fourNodeSampleUnitBenchBuild(), "Bulk mixed scope requires four-node sample custody");
 static_assert(BODAQS_SPI_BULK_BYTES==512, "Bulk mixed scope requires selected512 geometry");
 return true;
#else
 return false;
#endif
}
constexpr const char* buildMode() {
 if(bulkMixedAdcBenchBuild()) return BODAQS_ADC_CONCENTRATED_SCAN_BENCH?"bulk_four_node_adc_scan_unqualified":"bulk_four_node_adc_smoke_unqualified";
 if(sampleUnitBenchBuild()) return fourNodeSampleUnitBenchBuild()?"sample_unit_four_node_unqualified":"sample_unit_two_node_unqualified";
 #if defined(BODAQS_SINGLE_NODE_IMU_ADC_SMOKE) && BODAQS_SINGLE_NODE_IMU_ADC_SMOKE == 1
 static_assert(singleNodeSmokeBuild(), "ADC smoke requires the compact single-node smoke build");
 return multiNodeBenchBuild()?"multi_node_polling_unqualified":scalingBenchBuild()?"single_node_adc_scaling_unqualified":channelRateBenchBuild()?"single_node_adc_channel_rate_unqualified":"single_node_adc_smoke_unqualified";
 #else
 return singleNodeSmokeBuild()?"single_node_smoke_unqualified":"production";
 #endif
}
constexpr bool singleNodeAdcSmokeBuild() {
#if defined(BODAQS_SINGLE_NODE_IMU_ADC_SMOKE) && BODAQS_SINGLE_NODE_IMU_ADC_SMOKE == 1
 return true;
#else
 return false;
#endif
}
struct Adc { uint32_t conversionsPerSecond=0, spiHz=0; uint8_t activeChannels=0; };
// Bounds include all software, CS, arbitration and non-overlapped rearm work.
// A profile is supplied only by qualification or a deterministic host fixture.
struct Profile {
 bool qualified=false;
 uint32_t nominalBitrate=1000000, dataBitrate=4000000;
 double sampleMutexHoldUs=64, auxiliaryMutexHoldUs=64;
 double maximumSourceSamplesPerSecond=0;
 double sampleSlotUs=0, auxiliarySlotUs=0, adcTransactionUs=0, adcPollUsPerConversion=0;
 double canFrameUs=196.25;
 double adcAttemptsPerConversion=0;
 // Independent finite service envelopes, including START/STOP/fence and
 // controller-error/retry bursts. Qualified profiles must supply nonzero bounds.
 uint32_t canBurstFrames=0, spiBurstSlots=0;
 uint32_t canExceptionalFramesPerSecond=0, spiExceptionalSlotsPerSecond=0;
 uint32_t nodeServiceBlackoutUs=50000, masterServiceBlackoutUs=100000, storageBlackoutUs=1000000;
 uint32_t arrivalBurstPackets=0, arrivalBurstEvidence=0;
 uint32_t sampleDrainSlotsPerSecond=0;
};
struct Demand { uint8_t nodes=0; Adc adc[2]; uint16_t loggerRateHz=0; };
struct Report {
 Reason reason=Reason::None; bool qualified=false, attempted=false, benchOnly=false;
 double canOccupancy=0, spiOccupancy=0, drainRatio=0;
 size_t loggerBytes=0, masterBytes=0, nodeBytes=0;
 uint32_t nodePackets=0, masterPackets=0, loggerSamples=0, loggerEvidence=0;
};
Report evaluate(const Demand&,const Profile&);
// Experimental opt-in only: no measured costs, capacity or readiness is claimed.
Report evaluateSingleNodeSmoke(const Demand&,bool otherActiveSensors);
// Explicit v3 bench: 1/2 IMUs; v4 four-node opt-in also admits4. 500Hz, ADC off.
Report evaluateSampleUnitBench(const Demand&,bool otherActiveSensors);
// Explicit 512-byte bench: retain ADC-off cases; add exactly0/4 IMUs plus
// ain0/4, one channel/ADC,1000SPS each at1MHz,500Hz primary. Caller checks pins.
Report evaluateBulkMixedBench(const Demand&,bool otherActiveSensors);
// Exact bench load only, with an ADC-only control using the same image.
Report evaluateSingleNodeAdcSmoke(const Demand&,bool otherActiveSensors);
Report evaluateMultiNodeBench(const Demand&,bool otherActiveSensors);
const char* reasonText(Reason);
inline const char* reportText(const Report& r) {
 if(r.benchOnly && r.reason==Reason::None && bulkMixedAdcBenchBuild())return BODAQS_ADC_CONCENTRATED_SCAN_BENCH
     ?"four-node plus split/ADC0 concentrated bench (unqualified)":"four-node plus ain0/4 bulk bench (unqualified)";
 return r.benchOnly && r.reason==Reason::None
     ? (sampleUnitBenchBuild()?(fourNodeSampleUnitBenchBuild()?"one/two/four-node sample-unit bench (unqualified)":"one/two-node sample-unit bench (unqualified)"):multiNodeBenchBuild()?"multi-node polling bench (unqualified)":scalingBenchBuild()?"single-node ADC scaling bench (unqualified)":singleNodeAdcSmokeBuild()?"single-node plus two ADC channels (unqualified)":"single-node smoke test (unqualified)")
     : reasonText(r.reason);
}
}
