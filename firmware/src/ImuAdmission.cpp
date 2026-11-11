#include "ImuAdmission.h"
#include <cmath>
#include <limits>
namespace ImuAdmission {
Report evaluate(const Demand& d,const Profile& p) {
 Report r;r.qualified=p.qualified;r.attempted=d.nodes!=0;
 if(!std::isfinite(p.maximumSourceSamplesPerSecond) || !std::isfinite(p.sampleMutexHoldUs) || !std::isfinite(p.auxiliaryMutexHoldUs) || !std::isfinite(p.sampleSlotUs) || !std::isfinite(p.auxiliarySlotUs) ||
    !std::isfinite(p.adcTransactionUs) || !std::isfinite(p.adcPollUsPerConversion) ||
    !std::isfinite(p.canFrameUs) || !std::isfinite(p.adcAttemptsPerConversion) ||
    p.adcTransactionUs<0 || p.adcPollUsPerConversion<0) {r.reason=Reason::Unqualified;return r;}
 if(!d.nodes) return r;
 if(d.nodes>4) {r.reason=Reason::Eligibility;return r;}
 if(p.nominalBitrate!=1000000 || p.dataBitrate!=4000000) {r.reason=Reason::Link;return r;}
 // 3333 samples/s; five samples/packet. Every auxiliary CAN frame is
 // conservatively charged as a full 64-byte frame. Diagnostics include the
 // actual OPEN + six READ + RELEASE chain: every page/retry consumes
 // the same global four-command/s budget (eight CAN frames/s), burst four.
 const double packetRate=p.maximumSourceSamplesPerSecond/5*d.nodes;
 const double canAuthorization=40*d.nodes; // challenge/renew request+reply
 const double canNormalEvidence=(10+10+10+10+1)*d.nodes+10; // snapshot/nodeSYNC/model/anchor/status + masterSYNC
 const double canFaultEvidence=(20+24)*d.nodes; // coalesced loss + bounded recovery
 const double canDiagnostics=8; // four commands, request+reply, retries share budget
 const double canAux=canAuthorization+canNormalEvidence+canFaultEvidence+canDiagnostics+p.canExceptionalFramesPerSecond;
 r.canOccupancy=(packetRate+canAux)*p.canFrameUs/1000000.;
 // Full 65-sample batches take 26 fragments plus selection/ACK pipeline.
 // A boundary/evidence reception seals a partial sample head. Up to94
 // evidence receptions/s/node (normal50 + loss20 + recovery24) each add
 // a conservative three slots beyond the full-batch per-packet allowance.
 const double sampleSlots=p.maximumSourceSamplesPerSecond*d.nodes*28./65.+94.*d.nodes*3;
 // Authorization 20/node/s*8 slots; timing snapshots/model/anchor/sync,
 // bridge and status. Empty polls 50/node/s. Optional diagnostics four
 // commands/s *8 slots include replies, selection and ACK, retries included.
 // Each node: authorization160, snapshot50, nodeSYNC50, model50,
 // anchor50, status5. Global masterSYNC50 and bridge20 are charged even
 // with only one participating node. Fault objects take five slots each.
 const double auxiliarySlots=(160+50+50+50+50+5+44*5+50+80)*d.nodes+
     50+100+32+p.spiExceptionalSlotsPerSecond;
 // Bridge retries are bounded to20ms (up to50request/response pairs/s).
 // Four management-loss stage/class lanes/node at10Hz each reserve a report
 // and retry slot; they use no new CAN frame. Local drops coalesce at10Hz.
 double adcUs=0;
 for(const auto& a:d.adc) if(a.conversionsPerSecond) {
  if(!a.spiHz || p.adcAttemptsPerConversion<1) {r.reason=Reason::Unqualified;return r;}
  adcUs+=a.conversionsPerSecond*p.adcAttemptsPerConversion*(80000000./a.spiHz+3*p.adcTransactionUs+p.adcPollUsPerConversion);
 }
 r.spiOccupancy=(sampleSlots*p.sampleSlotUs+auxiliarySlots*p.auxiliarySlotUs+adcUs)/1000000.;
 const double availableSlots=p.sampleSlotUs>0?(850000.-auxiliarySlots*p.auxiliarySlotUs-adcUs)/p.sampleSlotUs:0;
 const double drain=availableSlots<p.sampleDrainSlotsPerSecond?availableSlots:p.sampleDrainSlotsPerSecond;
 r.drainRatio=sampleSlots?drain/sampleSlots:0;
 // Reserve software pending packet, hardware inflight, partial packet and
 // protected recovery evidence independently of blackout arrivals.
 auto bounded=[](double value) -> uint32_t {
  if(!std::isfinite(value) || value>=UINT32_MAX) return UINT32_MAX;
  return value>0?static_cast<uint32_t>(std::ceil(value)):0;
 };
 const double nodeBacklog=std::ceil(p.maximumSourceSamplesPerSecond/5*p.nodeServiceBlackoutUs/1000000.);
 r.nodePackets=bounded(nodeBacklog+double(p.arrivalBurstPackets)+4+8);
 // The node can release its complete50ms backlog into an already stalled
 // master. That arrival burst must be charged in addition to100ms retention.
 r.masterPackets=bounded(std::ceil(p.maximumSourceSamplesPerSecond/5*p.masterServiceBlackoutUs/1000000.)+nodeBacklog+double(p.arrivalBurstPackets)+13+2);
 // Start the storage blackout with every independently resident upstream
 // queue full. All64 node and128 master records are conservatively samples;
 // selected master head13packets, logger-held sample and writer128 stay live.
 r.loggerSamples=bounded(std::ceil(p.maximumSourceSamplesPerSecond*p.storageBlackoutUs/1000000.)+double(p.arrivalBurstPackets)*5+64*5+128*5+65+1+128);
 r.loggerEvidence=bounded(std::ceil(160.*p.storageBlackoutUs/1000000.)+double(p.arrivalBurstEvidence)+64+128+13+1+128+8);
 r.loggerBytes=d.nodes*(8192u*32u+512u*224u+65u*32u+32u+128u*32u);
 r.masterBytes=4*(128u*92u+1024u);r.nodeBytes=64u*68u;
 if(!p.qualified || p.maximumSourceSamplesPerSecond<3333 || p.sampleMutexHoldUs<64 || p.sampleMutexHoldUs>100 ||
     p.auxiliaryMutexHoldUs<64 || p.auxiliaryMutexHoldUs>100 || p.sampleSlotUs<p.sampleMutexHoldUs || p.auxiliarySlotUs<p.auxiliaryMutexHoldUs || p.canFrameUs<196.25 || !p.sampleDrainSlotsPerSecond || !p.canBurstFrames || !p.spiBurstSlots ||
     p.nodeServiceBlackoutUs<50000 || p.masterServiceBlackoutUs<100000 || p.storageBlackoutUs<1000000) r.reason=Reason::Unqualified;
 else if(r.canOccupancy+p.canBurstFrames*p.canFrameUs/1000000.>.70) r.reason=Reason::CanCapacity;
 else if(r.spiOccupancy+p.spiBurstSlots*p.auxiliarySlotUs/1000000.>.85) r.reason=Reason::SpiCapacity;
 else if(r.drainRatio<1.25) r.reason=Reason::DrainCapacity;
 else if(p.canBurstFrames*p.canFrameUs>p.nodeServiceBlackoutUs ||
         p.spiBurstSlots*p.auxiliarySlotUs>p.masterServiceBlackoutUs || r.nodePackets>64 || r.masterPackets>128 || r.loggerSamples>8192 || r.loggerEvidence>512) r.reason=Reason::Coverage;
 return r;
}
Report evaluateSingleNodeSmoke(const Demand& d,bool otherActiveSensors) {
 Report r;r.attempted=d.nodes!=0;r.benchOnly=true;
 if(d.nodes!=1 || otherActiveSensors || d.adc[0].conversionsPerSecond || d.adc[1].conversionsPerSecond)
  r.reason=Reason::SmokeScope;
 return r;
}
Report evaluateSingleNodeAdcSmoke(const Demand& d,bool otherActiveSensors) {
 Report r;r.attempted=d.nodes!=0;r.benchOnly=true;
 if(channelRateBenchBuild()) {
  const auto& a=d.adc[0];const auto& b=d.adc[1];
  const bool split=d.loggerRateHz==500 && a.activeChannels==1 && b.activeChannels==1 &&
      a.conversionsPerSecond==1000 && b.conversionsPerSecond==1000 && a.spiHz==1000000 && b.spiHz==1000000;
  // loggerRateHz is the saved request. The unchanged local ADC cap reduces
  // a1000Hz request to700Hz for two channels; this is one explicit guard case.
  const bool concentrated=(d.loggerRateHz==500 || d.loggerRateHz==700 || d.loggerRateHz==1000) &&
      a.activeChannels==2 && a.conversionsPerSecond==2000 && a.spiHz==1000000 &&
      b.activeChannels==0 && b.conversionsPerSecond==0;
  if(d.nodes>1 || otherActiveSensors || (!split && !concentrated)) r.reason=Reason::MixedSmokeScope;
  return r;
 }
 if(d.nodes>1 || otherActiveSensors || d.loggerRateHz!=500) r.reason=Reason::MixedSmokeScope;
 for(const auto& a:d.adc) if(a.activeChannels!=1 || a.conversionsPerSecond!=1000 || a.spiHz!=1000000)
  r.reason=Reason::MixedSmokeScope;
 return r;
}
const char* reasonText(Reason r) {
 switch(r) {
 case Reason::None:return "admitted";case Reason::Unqualified:return "unqualified scheduling costs";
 case Reason::Link:return "incompatible CAN acquisition profile";case Reason::CanCapacity:return "CAN capacity";
 case Reason::SpiCapacity:return "shared SPI capacity";case Reason::DrainCapacity:return "sample drain headroom";
 case Reason::Coverage:return "burst/backlog coverage";case Reason::Allocation:return "remote allocation failed";
 case Reason::Eligibility:return "remote configuration unavailable";
 case Reason::SmokeScope:return "smoke build requires one CAN IMU; mute all other sensors";
 case Reason::MixedSmokeScope:return channelRateBenchBuild()
     ?"channel/rate bench requires ain0/4 at500Hz or ain0/1 at500/700Hz (1000Hz request capped), at most one CAN IMU"
     :"ADC smoke requires 500 Hz, ain0/4 only, and at most one CAN IMU";
 }return "unsupported";
}
}
