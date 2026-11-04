#include "ImuAdmission.h"
#include <cassert>
#include <cmath>
int main() {
 ImuAdmission::Demand d;d.nodes=4;
 ImuAdmission::Profile p;p.qualified=true;p.sampleSlotUs=64;p.auxiliarySlotUs=64;p.sampleDrainSlotsPerSecond=14000;
 auto r=ImuAdmission::evaluate(d,p);
 assert(r.reason==ImuAdmission::Reason::None);
 assert(r.nodePackets==46 && r.masterPackets==82 && r.loggerSamples==3527 && r.loggerEvidence==104);
 assert(r.loggerBytes==663808); // independent layout sum for four sources
 d.adc[0]={1200,1000000};d.adc[1]={1200,1000000};
 assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::None);
 d.adc[0].conversionsPerSecond=2000;d.adc[1].conversionsPerSecond=2000;
 assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::DrainCapacity);
 p.qualified=false;assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::Unqualified);
 p.qualified=true;p.arrivalBurstEvidence=25;assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::DrainCapacity);
 d.adc[0]={};d.adc[1]={};assert(ImuAdmission::evaluate(d,p).reason==ImuAdmission::Reason::Coverage);
}

