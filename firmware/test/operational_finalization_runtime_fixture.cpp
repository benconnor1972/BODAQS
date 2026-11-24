#include "BoundedJsonAllocator.h"
#include "RecordingReadiness.h"
#include "BdqV2Catalog.h"
#include "SensorRuntimeDiagnostics.h"
#include <cassert>
#include <cstring>
#include <strings.h>
#include <cstdio>
#include <string>
struct BdqLogEndInfo {
 const char* stopReason="user_request"; const char* stopTriggerEvent="operator";
 uint32_t stopUptimeMs=5000,samplesDropped=3,missedSampleSlots=7;
};
struct Stats {uint32_t recordsWritten=10,firstSequence=4,lastSequence=13;bool hasSequence=true;};
struct Writer {
 bool pending=false;Stats stats;
 bool hasPendingData() {return pending;}
 const Stats* streamStats(uint16_t) {return &stats;}
} s_bdqV2Writer;
uint8_t workspace[8192];
uint8_t* s_bdqV2Workspace=workspace;
size_t s_bdqV2WorkspaceBytes=sizeof workspace;
std::string s_currentSessionId="fixture";
uint32_t s_bdqV2MarkEventsDropped=2;
BdqV2StreamDescriptor s_bdqV2Descriptors[37];
uint16_t s_bdqV2DescriptorCount=9;
constexpr unsigned MAX_SENSORS=8;
namespace BdqV2PrimaryStreamSchema {constexpr unsigned kStreamId=1;}
namespace AcquisitionControl {
 struct Outcome {bool sampleTailDiscarded=true;};
 bool outcome(uint8_t,Outcome&) {return true;}
}
namespace RemoteImuRecording {
 struct Completion {
  bool stopConfirmed=false,sourceFinalObserved=false,uncertain=true;
  uint32_t stopRequestedMs=100,stopConfirmedMs=0,drainClosedMs=30000,finalSequence=0;
  uint8_t streamEpoch=0;
 };
 struct Failure {uint32_t observedMs=99;uint8_t cause=3,phase=7,reason=1;uint16_t streamFailureSite=123;};
 bool stopped() {return false;}
 bool configured() {return true;}
 uint32_t discardedTailObjects() {return 4;}
 bool completion(uint8_t,Completion&) {return true;}
 bool failure(uint8_t,Failure&) {return true;}
}
namespace SensorManager {
 bool describeRuntimeDiagnosticsAt(uint8_t index,SensorRuntimeDiagnostics& out) {
  if(index) return false;
  out={};std::strcpy(out.sensorName,"local");out.hasBdqV2Stream=true;
  out.bdqV2RecordsDropped=2;out.bdqV2RecordsRejected=1;return true;
 }
}
namespace RecordingReadiness {
 Observation declared;
 const Observation& session() {return declared;}
 const char* reason(const Observation& value) {return RecordingAdmission::blockerText(value.decision.blocker);}
}
// PRODUCTION
int main() {
 RecordingReadiness::declared.decision.requested=3;
 RecordingReadiness::declared.decision.selected=1;
 RecordingReadiness::declared.decision.excluded=2;
 RecordingReadiness::declared.decision.candidate=true;
 RecordingReadiness::declared.reservation=RecordingAdmission::Reservation::Acquired;
 for(unsigned i=0;i<37;++i) {
  auto& d=s_bdqV2Descriptors[i];d.source.streamId=i+1;
  std::strcpy(d.sensorId,"local");
  if(i && i%2) std::strcpy(d.payloadSchema,"bodaqs.can_imu_units.v2");
 }
 const auto bytes=buildOperationalSummary_({});assert(bytes && bytes<sizeof workspace);
 JsonDocument summary;assert(!deserializeJson(summary,workspace,bytes));
 assert(summary["streams"].size()==9);
 assert(summary["recording_membership"]["excluded_mask"]==2);
 assert(summary["recording_membership"]["resources_reserved"]==true);
 assert(summary["recording_membership"]["qualified"]==false);
 assert(summary["remote_failures"].size()==4);
 assert(summary["remote_tail_windows"].size()==4);
 assert(summary["remote_tail_status"]=="incomplete");
 assert(summary["streams"][0]["producer_drop_count"]==3);
 assert(summary["streams"][1]["producer_drop_count"]==2);
 // The footer cannot overwrite data still waiting to use this workspace.
 s_bdqV2Writer.pending=true;assert(!buildOperationalSummary_({}));s_bdqV2Writer.pending=false;
 // A reduced/fragmented START allocation fails honestly, without partial JSON.
 s_bdqV2WorkspaceBytes=1024;assert(!buildOperationalSummary_({}));
 s_bdqV2WorkspaceBytes=sizeof workspace;
 s_bdqV2DescriptorCount=37;
 const size_t maximum=buildOperationalSummary_({});
 if(maximum) {assert(!deserializeJson(summary,workspace,maximum));assert(summary["streams"].size()==37);}
 // Failed growth preserves the existing allocation and its bytes.
 BoundedJsonAllocator allocator(256);
 auto* kept=static_cast<unsigned char*>(allocator.allocate(64));assert(kept);kept[0]=42;
 assert(!allocator.allocate(256));assert(!allocator.reallocate(kept,512));assert(kept[0]==42);
 allocator.deallocate(kept);assert((kept=static_cast<unsigned char*>(allocator.allocate(128))));allocator.deallocate(kept);
 {BoundedJsonAllocator tiny(64);JsonDocument exhausted(&tiny);exhausted["required"]="value";assert(exhausted.overflowed());}
 std::printf("Operational footer: four failures=%zu bytes; 37 streams=%zu bytes; bounded workspace/allocation failures passed\n",bytes,maximum);
}
