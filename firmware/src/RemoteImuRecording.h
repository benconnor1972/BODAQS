#pragma once
#include <stdint.h>
#include "ImuAdmission.h"
#include "ImuFlowDiagnostics.h"
#include "CanMasterManager.h"
#include "MeasurementReplyCapture.h"
struct LoggerConfig;
struct BdqV2StreamDescriptor;
namespace RemoteImuRecording {
// First observed failure is retained through cleanup and file finalization.
// Phase: Idle=0 through Done=12 in the coordinator; action/result use
// AcquisitionControl enums. Cause: control=1, startup timeout=2, stream=3,
// other local failure=4. All observations are made by the main-loop owner.
struct Failure {
  uint32_t observedMs=0;
  uint8_t phase=0,action=0,result=0,reason=0,cause=0;
  uint8_t measurementPhase=0,measurementReason=0;
  bool measurementUnavailable=false;
  uint32_t objectsReceived=0,transferErrors=0;
  uint32_t transferErrorMask=0;
  uint16_t streamFailureSite=0; // Source line in pinned RemoteImuStream.cpp; zero if not a stream failure.
  bool timingAvailable=false; // Matching scope only; the live first-failure copy is not atomic.
    CanMasterManager::MeasurementTiming timing;
};
bool failure(uint8_t node,Failure& out);
struct Completion {
  uint32_t stopRequestedMs=0,stopConfirmedMs=0,drainClosedMs=0,finalSequence=0;
  uint8_t streamEpoch=0;
  bool stopConfirmed=false,sourceFinalObserved=false,uncertain=false;
};
// Published once after producer quiescence; immutable until storage finalizes.
bool completion(uint8_t node,Completion& out);
bool readyForFileFinalization();
void logDiagnostics(); // Explicit user-requested snapshot; never a fast-path log.
// Allocation, reconciliation and lifecycle startup run while local acquisition
// is stopped. All selected remote resources precede PREPARE.
bool configure(const LoggerConfig&);
const ImuAdmission::Report& admission();
bool setAdmissionProfile(const ImuAdmission::Profile&);
// Called only after the storage owner has allocated all buffers and written
// the frozen candidate catalog. It is the barrier before any PREPARE.
bool resourcesReady(size_t storageReservedBytes=0);
bool configured();
bool prepared();
bool recording();
bool failed();
const char* failureReason();
void start();
void stop();
void service(); // main-loop orchestration, never transport/storage progress
bool stopped();
// Immutable completed measurement-scope counters; false until owner retirement
// or when this build has no FLOW snapshot. Never reads live transport totals.
bool finalMeasurementFailures(uint32_t& transfer,uint32_t& decode);
bool finalNodeDiagnostics(uint8_t node,ImuFlowDiagnostics::NodeStats& out);
struct SharedMetadataRetirements {
    uint32_t syncObjects=0,bridgeObservations=0,managementReports=0;
};
// Omitted optional fan-out contributions, not accepted sensor records. Available
// only after all participants and the acquisition owner retire in this scope.
bool finalSharedMetadataRetirements(uint8_t node,SharedMetadataRetirements& out);
// Same retirement/context barrier; firstLoss=true returns null in a loss-free run.
const ImuFlowDiagnostics::Snapshot* finalFlowSnapshot(bool firstLoss);
const uint32_t* finalMeasurementDecodeReasons(); // Same retired/matching-context lifetime.
// Same retirement/scope barrier as final counters. Borrowed immutable storage;
// consume before release or configure starts another recording. Null if unavailable.
const MeasurementReplyCapture* finalRejectedMeasurementReplies();
bool tailDrained();
uint32_t discardedTailObjects();
void release(); // after transport exit and storage finalization
uint16_t describe(BdqV2StreamDescriptor*,uint16_t capacity,uint16_t firstId);
}
