#include "ImuAdmission.h"
#include <cmath>
namespace ImuAdmission {
Report evaluate(const Demand& d,const Profile& p) {
 Report r;r.qualified=p.qualified;
 if(!d.nodes) return r;
 if(d.nodes>4) {r.reason=Reason::Eligibility;return r;}
 if(p.nominalBitrate!=1000000 || p.dataBitrate!=4000000) {r.reason=Reason::Link;return r;}
 // 3333 samples/s; five samples/packet. Every auxiliary CAN frame is
 // conservatively charged as a full 64-byte frame. Diagnostics include the
 // actual OPEN + six READ + RELEASE chain (4 requests/s globally), both ways.
 const double packetRate=666.6*d.nodes;
 const double canAux=128*d.nodes+64+p.canExceptionalFramesPerSecond;
 r.canOccupancy=(packetRate+canAux)*p.canFrameUs/1000000.;
 // Full 65-sample batches take 26 fragments plus selection/ACK pipeline.
 const double sampleSlots=3333.*d.nodes*28./65.;
 // Authorization 20/node/s*8 slots; timing snapshots/model/anchor/sync,
 // bridge and status. Empty polls 50/node/s. Optional diagnostics 32 request
 // operations/s *8 slots include replies, selection and ACK, retries included.
 const double auxiliarySlots=382.5*d.nodes+50.*d.nodes+256+p.spiExceptionalSlotsPerSecond;
 double adcUs=0;
 for(const auto& a:d.adc) if(a.conversionsPerSecond) {
  if(!a.spiHz) {r.reason=Reason::Unqualified;return r;}
  adcUs+=a.conversionsPerSecond*(80000000./a.spiHz+3*p.adcTransactionUs+p.adcPollUsPerConversion);
 }
 r.spiOccupancy=(sampleSlots*p.sampleSlotUs+auxiliarySlots*p.auxiliarySlotUs+adcUs)/1000000.;
 const double availableSlots=p.sampleSlotUs>0?(850000.-auxiliarySlots*p.auxiliarySlotUs-adcUs)/p.sampleSlotUs:0;
 const double drain=availableSlots<p.sampleDrainSlotsPerSecond?availableSlots:p.sampleDrainSlotsPerSecond;
 r.drainRatio=sampleSlots?drain/sampleSlots:0;
 // Reserve software pending packet, hardware inflight, partial packet and
 // protected recovery evidence independently of blackout arrivals.
 r.nodePackets=uint32_t(std::ceil(666.6*p.nodeServiceBlackoutUs/1000000.))+p.arrivalBurstPackets+4+8;
 r.masterPackets=uint32_t(std::ceil(666.6*p.masterServiceBlackoutUs/1000000.))+p.arrivalBurstPackets+13+2;
 // Queued entries are32 bytes including dependency; expanded selected batch,
 // held consumer and128-record writer workspace are separate residents.
 r.loggerSamples=uint32_t(std::ceil(3333.*p.storageBlackoutUs/1000000.))+p.arrivalBurstPackets*5+65+1+128;
 r.loggerEvidence=uint32_t(std::ceil(94.*p.storageBlackoutUs/1000000.))+p.arrivalBurstEvidence+8+2;
 r.loggerBytes=d.nodes*(4096u*32u+128u*224u+65u*32u+32u+128u*32u);
 r.masterBytes=4*(96u*92u+1024u);r.nodeBytes=64u*72u;
 if(!p.qualified || p.sampleSlotUs<64 || p.sampleSlotUs>100 || p.auxiliarySlotUs<64 || p.auxiliarySlotUs>100 || p.canFrameUs<196.25 || !p.sampleDrainSlotsPerSecond) r.reason=Reason::Unqualified;
 else if(r.canOccupancy>.70) r.reason=Reason::CanCapacity;
 else if(r.spiOccupancy>.85) r.reason=Reason::SpiCapacity;
 else if(r.drainRatio<1.25) r.reason=Reason::DrainCapacity;
 else if(r.nodePackets>64 || r.masterPackets>96 || r.loggerSamples>4096 || r.loggerEvidence>128) r.reason=Reason::Coverage;
 return r;
}
const char* reasonText(Reason r) {
 switch(r) {
 case Reason::None:return "admitted";case Reason::Unqualified:return "unqualified scheduling costs";
 case Reason::Link:return "incompatible CAN acquisition profile";case Reason::CanCapacity:return "CAN capacity";
 case Reason::SpiCapacity:return "shared SPI capacity";case Reason::DrainCapacity:return "sample drain headroom";
 case Reason::Coverage:return "burst/backlog coverage";case Reason::Allocation:return "remote allocation failed";
 case Reason::Eligibility:return "remote configuration unavailable";
 }return "unsupported";
}
}
