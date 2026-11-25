#include "ImuAdmission.h"
#include <cassert>
#include <cstring>
#include <cstdio>
int main(){
 assert(std::strcmp(ImuAdmission::buildMode(),"bulk_four_node_adc_scan_unqualified")==0);
 for(unsigned nodes:{0U,4U}) {
  ImuAdmission::Demand d;d.nodes=nodes;d.loggerRateHz=500;
  d.adc[0]={2000,1000000,2};
  auto r=ImuAdmission::evaluateBulkMixedBench(d,false);
  assert(r.reason==ImuAdmission::Reason::None && r.benchOnly && !r.qualified && r.attempted==(nodes!=0));
  auto bad=d;bad.loggerRateHz=200;assert(ImuAdmission::evaluateBulkMixedBench(bad,false).reason!=ImuAdmission::Reason::None);
  bad=d;bad.adc[1]={1000,1000000,1};assert(ImuAdmission::evaluateBulkMixedBench(bad,false).reason!=ImuAdmission::Reason::None);
  bad=d;bad.adc[0].conversionsPerSecond=1000;assert(ImuAdmission::evaluateBulkMixedBench(bad,false).reason!=ImuAdmission::Reason::None);
  bad=d;bad.adc[0].spiHz=2000000;assert(ImuAdmission::evaluateBulkMixedBench(bad,false).reason!=ImuAdmission::Reason::None);
  assert(ImuAdmission::evaluateBulkMixedBench(d,true).reason!=ImuAdmission::Reason::None);
  d.adc[0]={1000,1000000,1};d.adc[1]={1000,1000000,1};
  assert(ImuAdmission::evaluateBulkMixedBench(d,false).reason==ImuAdmission::Reason::None);
 }
 for(unsigned nodes:{1U,2U,3U}) {ImuAdmission::Demand d;d.nodes=nodes;d.loggerRateHz=500;d.adc[0]={2000,1000000,2};assert(ImuAdmission::evaluateBulkMixedBench(d,false).reason!=ImuAdmission::Reason::None);}
 puts("PASS exact concentrated admission:0/4 IMUs at500Hz, ADC0twochannels2000SPS/1MHz, ADC1off; splitcontrol retained; unsupported loads rejected");
}
