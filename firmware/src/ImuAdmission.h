#pragma once
#include <stdint.h>
#include <stddef.h>
namespace ImuAdmission {
enum class Reason : uint8_t { None, Unqualified, Link, CanCapacity, SpiCapacity, DrainCapacity, Coverage, Allocation, Eligibility };
struct Adc { uint32_t conversionsPerSecond=0, spiHz=0; };
// Bounds include all software, CS, arbitration and non-overlapped rearm work.
// A profile is supplied only by qualification or a deterministic host fixture.
struct Profile {
 bool qualified=false;
 uint32_t nominalBitrate=1000000, dataBitrate=4000000;
 double sampleSlotUs=0, auxiliarySlotUs=0, adcTransactionUs=0, adcPollUsPerConversion=0;
 double canFrameUs=196.25;
 uint32_t canExceptionalFramesPerSecond=0, spiExceptionalSlotsPerSecond=0;
 uint32_t nodeServiceBlackoutUs=50000, masterServiceBlackoutUs=100000, storageBlackoutUs=1000000;
 uint32_t arrivalBurstPackets=0, arrivalBurstEvidence=0;
 uint32_t sampleDrainSlotsPerSecond=0;
};
struct Demand { uint8_t nodes=0; Adc adc[2]; };
struct Report {
 Reason reason=Reason::None; bool qualified=false;
 double canOccupancy=0, spiOccupancy=0, drainRatio=0;
 size_t loggerBytes=0, masterBytes=0, nodeBytes=0;
 uint32_t nodePackets=0, masterPackets=0, loggerSamples=0, loggerEvidence=0;
};
Report evaluate(const Demand&,const Profile&);
const char* reasonText(Reason);
}
