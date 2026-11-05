#include "ImuAdmission.h"
#include <cassert>
#include <cmath>
int main() {
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
}

