#pragma once
#include "RecordingFeatures.h"
#include "BdqV2Catalog.h"
#include "DynamicSpscQueue.h"

struct RemoteImuBinding {
  uint8_t node=0;
  uint8_t profileId=1; // explicit requested profile; reconciled before acquisition
  uint32_t boot=0;
  uint64_t uid=0, masterUid=0, masterBoot=0, session=0, recording=0, context=0;
  uint8_t effective[192]={};
  char sensorId[32]={}, mountPoint[32]={}, calibrationRef[32]={};
  char domain[24]={}, end[16]={};
  bool orientationValid=false;
  bool compactPackets=false; // additive observation schema; legacy remains default
  bool sampleUnits=false; // v3 immutable units, retaining master-origin integrity
  double mountingQuaternion[4]={1,0,0,0};
};

// One ingress producer (acquisition owner), one storage consumer. Definitions
// are expanded while still pinned in transport; bounded queues retain exact
// native records and their evidence dependency until a successful chunk write.
class RemoteImuStream {
public:
  ~RemoteImuStream() {release();}
  enum Acceptance { Invalid=-1, Blocked=0, Accepted=1 };
  bool configure(const RemoteImuBinding&,uint16_t sampleId,uint16_t evidenceId);
  Acceptance acceptSampleUnit(uint64_t context,uint32_t object,const uint8_t*,uint16_t total,uint32_t loggerTick);
  static size_t allocatedBufferBytes(bool compactPackets=false,bool sampleUnits=false);
  void release(); // only after both producer and storage owner stop
  Acceptance accept(uint16_t identifier,const uint8_t*,size_t length,
                    uint32_t masterTick,uint64_t masterOrder,uint32_t loggerTick,uint8_t receptionFlags=0);
  Acceptance acceptSharedSync(uint32_t sequence,uint32_t edgeTick,uint32_t masterEpoch,uint32_t loggerTick);
  Acceptance acceptBridge(uint32_t token,uint32_t masterTick,uint32_t masterEpoch,uint64_t lower,uint64_t upper,uint32_t loggerTick);
  Acceptance acceptMissingBridge(uint32_t token,uint32_t loggerTick);
  Acceptance acceptLocalLoss(const uint8_t body[56],uint32_t masterTick,uint64_t order,uint32_t loggerTick);
  Acceptance acceptManagementLoss(uint8_t cls,uint8_t reason,uint16_t stage,uint32_t counter,uint32_t loggerTick);
  bool finish(uint32_t loggerTick); // producer quiescent; flush the final coalesced losses
  // Caller has closed ingress and acquired producer retirement.
  bool terminalBoundary(uint32_t& sequence,uint8_t& epoch) const;
  BdqV2StreamSource sampleSource();
  BdqV2StreamSource evidenceSource();
  BdqV2StreamDescriptor descriptor(bool evidence);
  bool failed() const { return failed_.load(std::memory_order_acquire); }
  // Source line in this build's RemoteImuStream.cpp; diagnostic, not a wire reason.
  uint16_t failureSite() const { return failureSite_.load(std::memory_order_acquire); }
  bool empty() const { return !holding_ && samples_.empty() && packets_.empty() && evidence_.empty(); }
#if BODAQS_ADAPTIVE_DRAIN_OWNER || (defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS)
  struct QueueState {size_t samples,evidence,sampleCapacity,evidenceCapacity;uint32_t packetsAccepted;uint64_t samplesAccepted;};
  // Producer only (or after retirement): acceptance counts are producer-owned.
  // Queue indices are atomic; allocations/capacities stay fixed while owned.
  QueueState queueState() const {
    return {binding_.compactPackets?packets_.size():samples_.size(),evidence_.size(),
      binding_.compactPackets?packets_.capacity():samples_.capacity(),evidence_.capacity(),nextPacket_,compactSamplesAccepted_};
  }
#endif
private:
  std::atomic<uint16_t> failureSite_{0};
  void markFailed(uint16_t site) {
    uint16_t empty=0;
    failureSite_.compare_exchange_strong(empty,site,std::memory_order_relaxed);
    failed_.store(true,std::memory_order_release);
  }
  struct Sample { uint8_t bytes[28]; uint32_t dependency; };
  struct Model {
    uint32_t id=0, anchor=0,tick=0,numerator=0,span=0,duration=0;
    uint32_t nodeEpoch=0,sensorEpoch=0,dependency=0;
    uint16_t denominator=0, flags=0;
    uint8_t epoch=0;
    bool anchored=false;
    uint8_t canonical[56]={};
  };
  struct Anchor {
    uint32_t sequence=0,tick=0,numerator=0;
    uint16_t denominator=0;
    uint8_t epoch=0;
  };
  RemoteImuBinding binding_;
  char* provenance_=nullptr;
  DynamicSpscQueue<Sample> samples_;
  DynamicSpscRecordQueue packets_;
  DynamicSpscRecordQueue evidence_;
  uint16_t sampleId_=0,evidenceId_=0;
  uint32_t segment_=0,nextSequence_=0,nextEvidence_=1,stagedEvidence_=0;
  std::atomic<uint32_t> persistedEvidence_{0};
  Model* models_=nullptr;
  Anchor* anchors_=nullptr;
  uint8_t anchorCount_=0;
  uint8_t modelCount_=0,epoch_=0;
  bool haveSequence_=false,haveBoundary_=false;
  bool terminalObserved_=false;
  uint32_t terminalSequence_=0;
  uint8_t terminalEpoch_=0;
  std::atomic<bool> failed_{false};
  Acceptance evidence(uint8_t type,const uint8_t* body,uint32_t,uint64_t,uint32_t,bool local=false,uint8_t receptionFlags=0);
  Acceptance pushShared(uint8_t out[224]);
  Acceptance samples(const uint8_t*,size_t,uint32_t);
  struct Loss {uint32_t source=0,evidence=0,first=0,last=0;};
  Loss losses_[2];
  uint32_t lastLossReport_=0;
  unsigned nextLossLane_=0;
  uint32_t lossDependency_=0;
  uint32_t nextPacket_=0,sequenceFloor_=0;
  uint32_t lastUnit_=0,lastUnitChecksum_=0;
  uint32_t unitSequenceFloor_=0;
  uint64_t compactSamplesAccepted_=0;
  bool producerGap_=false,alignmentDegraded_=false;
  uint32_t managementLoss_[2][2]={};
  bool flushLoss(uint32_t logger);
  Acceptance packet(const uint8_t*,size_t,uint32_t,uint64_t,uint32_t,uint8_t);
  bool drop(unsigned lane,uint32_t count,uint32_t first,uint32_t logger);
  static size_t pendingSamples(const void*);
  static size_t pendingEvidence(const void*);
  static size_t noObservations(const void*) { return 0; }
  static bool noObservation(void*,BdqV2Format::TimeObservation&) { return false; }
  static bool popSample(void*,uint8_t*,size_t);
  static bool popEvidence(void*,uint8_t*,size_t);
  static void writtenEvidence(void*);
  // Consumer keeps one queue head; it cannot be released before its evidence.
  Sample held_={};
  bool holding_=false;
};
