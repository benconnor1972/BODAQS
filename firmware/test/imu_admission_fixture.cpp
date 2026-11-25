#include "ImuAdmission.h"
#include <cassert>
#include <cmath>
#include <initializer_list>
#include <cstring>
int main() {
#if BODAQS_BULK_MIXED_ADC_BENCH
 assert(ImuAdmission::bulkMixedAdcBenchBuild());
 assert(std::strcmp(ImuAdmission::buildMode(),"bulk_four_node_adc_smoke_unqualified")==0);
 for(uint8_t nodes:{0,4}) {
  ImuAdmission::Demand d;d.nodes=nodes;d.loggerRateHz=500;
  d.adc[0]={1000,1000000,1};d.adc[1]={1000,1000000,1};
  auto r=ImuAdmission::evaluateBulkMixedBench(d,false);
  assert(r.reason==ImuAdmission::Reason::None && r.benchOnly && !r.qualified);
  assert(r.attempted==(nodes!=0));
  assert(ImuAdmission::evaluateSampleUnitBench(d,false).reason==ImuAdmission::Reason::SampleUnitBenchScope);
  assert(ImuAdmission::evaluateBulkMixedBench(d,true).reason==ImuAdmission::Reason::BulkMixedBenchScope);
  for(unsigned adc=0;adc<2;++adc) {
   auto bad=d;bad.adc[adc].activeChannels=2;assert(ImuAdmission::evaluateBulkMixedBench(bad,false).reason==ImuAdmission::Reason::BulkMixedBenchScope);
   bad=d;bad.adc[adc].conversionsPerSecond=600;assert(ImuAdmission::evaluateBulkMixedBench(bad,false).reason==ImuAdmission::Reason::BulkMixedBenchScope);
   bad=d;bad.adc[adc].spiHz=2000000;assert(ImuAdmission::evaluateBulkMixedBench(bad,false).reason==ImuAdmission::Reason::BulkMixedBenchScope);
  }
  for(uint8_t badNodes:{1,2,3,5}){auto bad=d;bad.nodes=badNodes;assert(ImuAdmission::evaluateBulkMixedBench(bad,false).reason==ImuAdmission::Reason::BulkMixedBenchScope);}
  for(uint16_t rate:{0,200,700}){auto bad=d;bad.loggerRateHz=rate;assert(ImuAdmission::evaluateBulkMixedBench(bad,false).reason==ImuAdmission::Reason::BulkMixedBenchScope);}
 }
#endif
#if defined(BODAQS_V3_TWO_NODE_BENCH) && BODAQS_V3_TWO_NODE_BENCH
#if defined(BODAQS_V4_FOUR_NODE_BENCH) && BODAQS_V4_FOUR_NODE_BENCH
 for(uint8_t nodes:{1,2,4}) {
#else
 for(uint8_t nodes:{1,2}) {
#endif
  ImuAdmission::Demand bench;bench.nodes=nodes;bench.loggerRateHz=500;
  auto accepted=ImuAdmission::evaluateSampleUnitBench(bench,false);
  assert(accepted.reason==ImuAdmission::Reason::None && accepted.benchOnly && !accepted.qualified);
  assert(ImuAdmission::evaluate(bench,ImuAdmission::Profile{}).reason==ImuAdmission::Reason::Unqualified);
  assert(ImuAdmission::evaluateSampleUnitBench(bench,true).reason==ImuAdmission::Reason::SampleUnitBenchScope);
  for(auto& adc:bench.adc) {
   adc.activeChannels=1;assert(ImuAdmission::evaluateSampleUnitBench(bench,false).reason==ImuAdmission::Reason::SampleUnitBenchScope);adc={};
   adc.conversionsPerSecond=1;assert(ImuAdmission::evaluateSampleUnitBench(bench,false).reason==ImuAdmission::Reason::SampleUnitBenchScope);adc={};
  }
  for(uint16_t rate:{0,200,1000}) {
   bench.loggerRateHz=rate;assert(ImuAdmission::evaluateSampleUnitBench(bench,false).reason==ImuAdmission::Reason::SampleUnitBenchScope);
  }
 }
#if defined(BODAQS_V4_FOUR_NODE_BENCH) && BODAQS_V4_FOUR_NODE_BENCH
#if !BODAQS_BULK_MIXED_ADC_BENCH
 assert(std::strcmp(ImuAdmission::buildMode(),"sample_unit_four_node_unqualified")==0);
#endif
#endif
#if defined(BODAQS_V4_FOUR_NODE_BENCH) && BODAQS_V4_FOUR_NODE_BENCH
 for(uint8_t nodes:{0,3,5}) {
#else
 for(uint8_t nodes:{0,3,4}) {
#endif
  ImuAdmission::Demand bench;bench.nodes=nodes;bench.loggerRateHz=500;
  assert(ImuAdmission::evaluateSampleUnitBench(bench,false).reason==ImuAdmission::Reason::SampleUnitBenchScope);
 }
#else
 ImuAdmission::Demand unitBench;unitBench.nodes=2;unitBench.loggerRateHz=500;
 assert(ImuAdmission::evaluateSampleUnitBench(unitBench,false).reason==ImuAdmission::Reason::SampleUnitBenchScope);
#endif
 ImuAdmission::Demand d;d.nodes=4;
 ImuAdmission::Profile p;p.maximumSourceSamplesPerSecond=3333;p.qualified=true;p.adcAttemptsPerConversion=1;p.canBurstFrames=20;p.spiBurstSlots=32;p.sampleSlotUs=64;p.auxiliarySlotUs=64;p.sampleDrainSlotsPerSecond=14000;
 auto r=ImuAdmission::evaluate(d,p);
 assert(r.reason==ImuAdmission::Reason::None);
 assert(r.nodePackets==46 && r.masterPackets==116 && r.loggerSamples==4487 && r.loggerEvidence==502);
 assert(r.loggerBytes==1532160); // independent layout sum for four sources
 assert(std::fabs(r.canOccupancy-0.6249385)<0.0000001);
 assert(std::fabs(r.spiOccupancy-0.6344329846153846)<0.0000001);
 d.adc[0]={600,1000000};d.adc[1]={600,1000000};
 assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::None);
 d.adc[0].conversionsPerSecond=2000;d.adc[1].conversionsPerSecond=2000;
 assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::SpiCapacity);
 p.qualified=false;assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::Unqualified);
 p.maximumSourceSamplesPerSecond=3333;p.qualified=true;p.adcAttemptsPerConversion=1;p.canBurstFrames=20;p.spiBurstSlots=32;p.arrivalBurstEvidence=77;assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::SpiCapacity);
 d.adc[0]={};d.adc[1]={};assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::Coverage);
 p.arrivalBurstEvidence=0;
 p.arrivalBurstPackets=UINT32_MAX;assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::Coverage);
 p.arrivalBurstPackets=0;p.sampleSlotUs=NAN;assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::Unqualified);
 p.sampleSlotUs=64;p.adcTransactionUs=-1;assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::Unqualified);
 p.adcTransactionUs=0;p.sampleDrainSlotsPerSecond=7000;assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::DrainCapacity);
 p.sampleDrainSlotsPerSecond=14000;p.canExceptionalFramesPerSecond=1000;assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::CanCapacity);
 // An explicitly selected bench build admits no claimed timing/bandwidth bound.
 d={};d.nodes=1;
 r=ImuAdmission::evaluateSingleNodeSmoke(d,false);
 assert(r.reason==ImuAdmission::Reason::None && r.benchOnly && !r.qualified);
 assert(r.canOccupancy==0 && r.spiOccupancy==0 && r.drainRatio==0);
 assert(ImuAdmission::evaluate(d,ImuAdmission::Profile{}).reason==ImuAdmission::Reason::Unqualified);
 d.nodes=2;assert(ImuAdmission::evaluateSingleNodeSmoke(d,false).reason==ImuAdmission::Reason::SmokeScope);
 d.nodes=1;assert(ImuAdmission::evaluateSingleNodeSmoke(d,true).reason==ImuAdmission::Reason::SmokeScope);
 d.adc[0]={1,1000000};assert(ImuAdmission::evaluateSingleNodeSmoke(d,false).reason==ImuAdmission::Reason::SmokeScope);
 // Separate explicit mixed bench opt-in. No production timing bounds claimed.
 d={};d.nodes=1;d.loggerRateHz=500;
 d.adc[0]={1000,1000000,1};d.adc[1]={1000,1000000,1};
 r=ImuAdmission::evaluateSingleNodeAdcSmoke(d,false);
 assert(r.reason==ImuAdmission::Reason::None && r.benchOnly && !r.qualified);
 assert(r.canOccupancy==0 && r.spiOccupancy==0 && r.drainRatio==0);
 assert(ImuAdmission::evaluateSingleNodeSmoke(d,false).reason==ImuAdmission::Reason::SmokeScope);
 assert(ImuAdmission::evaluate(d,ImuAdmission::Profile{}).reason==ImuAdmission::Reason::Unqualified);
 d.nodes=0;assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::None);
 d.nodes=2;assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);
 d.nodes=1;d.loggerRateHz=200;assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);
 d.loggerRateHz=500;
 for(unsigned a=0;a<2;++a) {
  d.adc[a].activeChannels=2;assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);
  d.adc[a].activeChannels=1;d.adc[a].conversionsPerSecond=2000;
  assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);
  d.adc[a].conversionsPerSecond=1000;d.adc[a].spiHz=8000000;
  assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);
  d.adc[a].spiHz=1000000;
 }
 assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,true).reason==ImuAdmission::Reason::MixedSmokeScope);
 d.adc[0]={2000,1000000,2};d.adc[1]={};
 for(uint16_t rate:{500,700,1000}) {
  d.loggerRateHz=rate;
  assert((ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::None)==ImuAdmission::channelRateBenchBuild());
 }
 for(uint16_t rate:{200,500}) {
  d={};d.nodes=1;d.loggerRateHz=rate;
  const uint32_t sps=rate==200?600:2000;
  d.adc[0]={sps,1000000,2};d.adc[1]={sps,1000000,2};
  r=ImuAdmission::evaluateSingleNodeAdcSmoke(d,false);
  assert((r.reason==ImuAdmission::Reason::None)==ImuAdmission::scalingBenchBuild());
  if(ImuAdmission::scalingBenchBuild()) {
   assert(r.benchOnly && !r.qualified && r.attempted);
   assert(ImuAdmission::evaluate(d,ImuAdmission::Profile{}).reason==ImuAdmission::Reason::Unqualified);
   assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,true).reason==ImuAdmission::Reason::MixedSmokeScope);
   d.nodes=2;assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);d.nodes=1;
   for(unsigned a=0;a<2;++a) {
    d.adc[a].activeChannels=3;assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);d.adc[a].activeChannels=2;
    d.adc[a].spiHz=8000000;assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);d.adc[a].spiHz=1000000;
    d.adc[a].conversionsPerSecond=sps==600?1000:1200;
    assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);d.adc[a].conversionsPerSecond=sps;
   }
   for(uint16_t rejected:{100,700,1000}) {
    d.loggerRateHz=rejected;assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);
   }
  }
 }
 d={};d.nodes=1;d.adc[0]={2000,1000000,2};
 if(ImuAdmission::channelRateBenchBuild()) {
  d.loggerRateHz=200;assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);
  d.loggerRateHz=700;d.adc[0].activeChannels=3;
  assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);
  d.adc[0].activeChannels=2;d.nodes=2;
  assert(ImuAdmission::evaluateSingleNodeAdcSmoke(d,false).reason==ImuAdmission::Reason::MixedSmokeScope);
 }
 for(uint8_t nodes:{1,2,4}) {
  d={};d.nodes=nodes;d.loggerRateHz=500;
  auto multi=ImuAdmission::evaluateMultiNodeBench(d,false);
  assert((multi.reason==ImuAdmission::Reason::None)==ImuAdmission::multiNodeBenchBuild());
  assert(multi.benchOnly && !multi.qualified);
  if(ImuAdmission::multiNodeBenchBuild()) {
   assert(ImuAdmission::evaluateMultiNodeBench(d,true).reason==ImuAdmission::Reason::MultiNodeBenchScope);
   d.loggerRateHz=200;assert(ImuAdmission::evaluateMultiNodeBench(d,false).reason==ImuAdmission::Reason::MultiNodeBenchScope);
   for(uint16_t rate:{200,500}) {
    d.loggerRateHz=rate;for(auto& adc:d.adc) adc={rate==200?600u:2000u,1000000,2};
    assert(ImuAdmission::evaluateMultiNodeBench(d,false).reason==ImuAdmission::Reason::None);
   }
  }
 }
 d={};d.nodes=3;d.loggerRateHz=500;
 assert(ImuAdmission::evaluateMultiNodeBench(d,false).reason==ImuAdmission::Reason::MultiNodeBenchScope);

}

