#pragma once

#include <stdint.h>

#include "BoardProfile.h"
#include "SpiTransactionContext.h"
#include "CanMasterProtocol.h"
#include "../can-fd/common/protocol/bodaqs_fragment_transport.h"
#include "CanControlProtocol.h"
#include "../can-fd/common/protocol/bodaqs_measurement.h"
#include "ConfigManager.h"

#ifndef BODAQS_REQUEST_BUILD_FAST
#define BODAQS_REQUEST_BUILD_FAST 0
#endif
#if BODAQS_REQUEST_BUILD_FAST != 0 && BODAQS_REQUEST_BUILD_FAST != 1
#error "Request-build optimization must be0or1"
#endif
#if BODAQS_REQUEST_BUILD_FAST && BODAQS_MEASUREMENT_VERSION != 5
#error "Request-build optimization requires the selected bulk codec"
#endif

// Opt-in experiment: use the ordinary data-fragment request sweep for the
// fetch half of ACK_FETCH too. This is never receipt or retirement evidence.
#ifndef BODAQS_ACK_FETCH_FRAGMENT_SWEEP
#define BODAQS_ACK_FETCH_FRAGMENT_SWEEP 0
#endif
#if BODAQS_ACK_FETCH_FRAGMENT_SWEEP != 0 && BODAQS_ACK_FETCH_FRAGMENT_SWEEP != 1
#error "BODAQS_ACK_FETCH_FRAGMENT_SWEEP must be0or1"
#endif
#if BODAQS_ACK_FETCH_FRAGMENT_SWEEP && BODAQS_MEASUREMENT_VERSION != 2
#error "ACK-fetch fragment sweep requires measurement v2"
#endif

// Ordinary result discovery only. Protected control, known partial results and
// ACK transmission retain their existing service. Zero preserves old builds.
#ifndef BODAQS_ORDINARY_FETCH_INTERVAL_MS
#define BODAQS_ORDINARY_FETCH_INTERVAL_MS 0
#endif
#if BODAQS_ORDINARY_FETCH_INTERVAL_MS < 0 || BODAQS_ORDINARY_FETCH_INTERVAL_MS > 20
#error "Ordinary fetch interval must be 0..20ms"
#endif
#if BODAQS_ORDINARY_FETCH_INTERVAL_MS && (BODAQS_MEASUREMENT_VERSION < 4 || !BODAQS_RECLAIM_IDLE_CONTROL_FETCH)
#error "Ordinary fetch pacing requires window transport and idle fetch reclamation"
#endif

namespace CanMasterManager {

enum class State : uint8_t {
  Unsupported = 0,
  Disabled,
  Probing,
  Absent,
  Present,
  Incompatible,
  TransportFault,
};

struct MeasurementTiming {
  uint32_t slots=0,failedSlots=0,emptySlots=0,elapsedUs=0;
  uint32_t transferFailedSlots=0,decodeFailedSlots=0;
  uint32_t decodeReasons[BODAQS_MEASUREMENT_DECODE_COUNT]={};
  uint64_t exchangeUs=0;
  uint32_t maxExchangeUs=0,maxIdleUs=0;
  uint32_t polls[5]={},fragments[5]={},deferrals[2]={};
};
struct Diagnostics {
  State state = State::Unsupported;
  CanMasterMode mode = CanMasterMode::Auto;
  bool profileSupported = false;
  bool irqAvailable = false;
  bool compatible = false;
  uint32_t probeAttempts = 0;
  uint32_t probeSuccesses = 0;
  uint32_t transferFailures = 0;
  uint32_t invalidResponses = 0;
  uint32_t statusAttempts = 0;
  uint32_t statusSuccesses = 0;
  uint32_t statusFailures = 0;
  uint32_t lastProbeMs = 0;
  uint32_t lastSuccessMs = 0;
  uint32_t lastStatusMs = 0;
  uint8_t protocolVersion = 0;
  uint32_t firmwareVersion = 0;
  uint32_t capabilities = 0;
  uint64_t hardwareUid = 0;
  bool statusSupported = false;
  bool statusValid = false;
  uint16_t statusFlags = 0;
  uint32_t masterUptimeMs = 0;
  uint32_t masterResetCause = 0;
  uint32_t masterSlotsReceived = 0;
  uint32_t masterMalformedSlots = 0;
  uint32_t masterProbesReceived = 0;
  uint32_t masterStatusRequestsReceived = 0;
  uint32_t masterSpiRecoveries = 0;
  uint32_t canRxFrames = 0;
  uint32_t canTxFrames = 0;
  uint32_t canErrorEvents = 0;
  uint16_t canRxQueueDepth = 0;
  uint16_t canRxQueueHighWater = 0;
  uint16_t spiTxQueueDepth = 0;
  uint16_t spiTxQueueHighWater = 0;
  uint32_t measurementObjectsReceived = 0, measurementDuplicates = 0;
  uint32_t measurementTransferErrors = 0, measurementControlSubmitted = 0;
  uint32_t measurementTransferErrorMask = 0; // Bit N: transport error N seen in this context.
  MeasurementTiming measurementTiming;
  uint64_t measurementTimingContext=0;
  uint16_t measurementAssemblyBytes = 0;
  uint8_t measurementLastClass = 0, measurementLastNode = 255;
  uint32_t measurementLastObject = 0;
  BodaqsMeasurementMode measurement = {};
  bool measurementStatusValid = false;
  bool measurementConfirmed = false;
  bool measurementUnavailable = false;
  bool controlSupported = false;
  bool controlInfoValid = false;
  BodaqsControlObserver control = {};
  BodaqsControlAuthorityClient authority = {};
  BodaqsControlApplyClient apply = {};
  uint64_t desiredGeneration[4] = {};
  bool desiredDisabled[4] = {};
  bool desiredEnabled[4] = {};
  bool inventorySupported = false;
  bool inventoryValid = false;
  uint32_t inventoryAttempts = 0;
  uint32_t inventorySuccesses = 0;
  uint32_t inventoryFailures = 0;
  uint32_t inventorySnapshotRetries = 0;
  uint32_t lastInventoryMs = 0;
  uint32_t inventoryGeneration = 0;
  uint8_t inventoryNodeCount = 0;
  uint8_t inventoryPresentCount = 0;
  uint8_t inventoryStaleCount = 0;
  uint8_t inventoryDuplicateCount = 0;
  CanMasterProtocol::DiscoveryRecord
      inventory[CanMasterProtocol::kDiscoveryNodeCount];
};

// Stages legacy limits, confirms at 8 MHz/64 bytes, then requires correlated status.
// A false result is unavailable, even if the master may have switched.
bool enterMeasurementMode(uint64_t recording, uint64_t context);
bool exitMeasurementMode();
bool inspectMeasurementMode();
// After admission closes and local sampling stops, make bounded progress on
// observational restart cleanup. True only after explicit context retirement.
bool cleanupUnavailableMeasurement();
bool measurementReady();
// Transfer mutable mode/transport/allocator ownership after configuration drain.
// The callback identifies the task currently executing the lifecycle service.
bool claimMeasurementControl(bool (*isOwner)());
#if defined(BODAQS_PACKED_STARTUP_DIAGNOSTICS) && BODAQS_PACKED_STARTUP_DIAGNOSTICS
// Bits: existing owner, missing fence, missing handoff-ready, pending apply,
// pending authority, pending management/control request.
uint8_t measurementControlBlockers();
#if defined(BODAQS_PACKED_EARLY_RESERVE) && BODAQS_PACKED_EARLY_RESERVE
bool packedBuffersReserved();
#endif
#endif
void releaseMeasurementControl();
void retainMeasurementAllocators(uint32_t nextRead, const uint32_t nextMutation[4],
                                 uint64_t nextTransfer);
// One bounded physical exchange; caller demultiplexes by immutable identity.
bool exchangeMeasurementSlot(const BodaqsMeasurementSlot& request,
                             BodaqsMeasurementSlot& response);
#if BODAQS_SPI_BULK_BYTES
// A pending custody ACK contains eight meaningful body bytes, never a response
// payload. Keep its exact predecessor identity without reserving a bulk frame
// per inbox. Expand only when the acquisition owner selects it for transmission.
struct MeasurementAcknowledgement {
  uint64_t context=0;
  uint32_t object=0;
  uint16_t total=0;
  uint8_t node=0,body[8]={};
  MeasurementAcknowledgement& operator=(const BodaqsMeasurementSlot& slot) {
    context=slot.context;object=slot.object;total=slot.total;node=slot.node;
    memcpy(body,slot.body,sizeof body);return *this;
  }
  operator BodaqsMeasurementSlot() const {
    BodaqsMeasurementSlot slot={};slot.kind=5;slot.context=context;slot.object=object;
    slot.total=total;slot.node=node;memcpy(slot.body,body,sizeof body);return slot;
  }
};
#else
using MeasurementAcknowledgement=BodaqsMeasurementSlot;
#endif
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
bool preparePackedBuffers();
size_t packedReservedBytes();
#if defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
size_t packedLargestAllocation();
#endif
struct PackedUtilization {
 uint32_t exchanges=0,transferred=0,commands=0,new_commands=0,retries=0,confirmations=0;
 uint32_t reply_counts[5]={},class_items[5]={},repeat_items[5]={};
 uint64_t class_bytes[5]={},used_bytes=0,exchange_us=0,confirmation_us=0,spacing_us=0;
 uint32_t confirmation_max_us=0,spacing_max_us=0,spacing_count=0,credit_hist[17]={};
};
struct AckCapacityPhase {
 uint32_t batches[9]={},observations=0,backlog_hist[30]={},backlog_sum[5]={},backlog_max[5]={};
 uint32_t full_batches_with_waiting=0,nonempty_batches_with_waiting=0;
 uint32_t confirmations=0,delay_hist[6]={},delay_max_us=0;uint64_t delay_total_us=0;
};
struct PackedDiagnostics {bool progress_batch=false;uint32_t coalesced_commands=0,unchanged_commands=0,progress_hold_max_us=0;uint32_t protocol_version=2,sample_custody[4]={};uint64_t context=0;uint32_t packets=0,items=0,rejected=0,copies=0;bool pending=false,exhausted=false;PackedUtilization utilization;AckCapacityPhase ack_capacity[3];};
bool packedDiagnostics(PackedDiagnostics&);
#endif
struct MeasurementInbox {
  BodaqsFragmentState state = {};
  uint8_t bytes[1024] = {};
  bool ackPending = false;
  bool admitted = false;
  // Scheduling hint only: fragments requested in this sweep, never receipt.
  uint32_t requestedFragments = 0;
  MeasurementAcknowledgement pendingAck = {};
};
inline void rememberMeasurementAcknowledgement(MeasurementInbox& inbox) {
#if BODAQS_SPI_BULK_BYTES
  // Retain the compact identity/body directly; do not create a full output
  // frame only to discard its zero padding and unused response fields.
  const auto& state=inbox.state;auto& ack=inbox.pendingAck;
  ack.context=state.context;ack.object=state.object;ack.total=state.total;ack.node=state.node;
  bodaqs_fragment_ack_body(&state,1,ack.body);
#else
  bodaqs_fragment_ack(&inbox.state,1,&inbox.pendingAck);
#endif
}
inline bool measurementObjectReady(const MeasurementInbox& inbox) {
  return inbox.state.complete && !inbox.admitted &&
      !(inbox.ackPending && inbox.pendingAck.object!=inbox.state.object);
}
// Caller allocates this bank persistently (not on a task stack). It demultiplexes
// all pipelined traffic, including MISO received while sending another lane/ACK.
struct MeasurementOutbox {
  BodaqsFragmentState state = {};
  uint8_t bytes[68] = {};
  uint8_t nextFragment = 0;
  uint8_t error = 0;
  uint32_t startedMs = 0;
};
struct MeasurementTransport {
  MeasurementInbox inboxes[5][4];
#if BODAQS_ORDINARY_FETCH_INTERVAL_MS
  // Acquisition owner only; last attempted MOSI fetch, not response readiness.
  // Reset with transport scope and on each newly queued ordinary command.
  uint32_t ordinaryFetchMs[4] = {};
  uint8_t ordinaryFetchSeen = 0;
#endif
#if BODAQS_MEASUREMENT_VERSION >= 4
  MeasurementInbox sampleExtra[4][3];
  uint32_t sampleNext[4] = {1,1,1,1};
  uint8_t sampleNodes = 0;
  // Scheduling only, never custody: rotate pending sample ACK attempts across
  // all nodes/slots. Reset with this transport at a new recording context.
  uint8_t nextSampleAck = 0;
  uint8_t nextEvidenceAck = 0, sampleAckBurst = 0, evidenceAckRepeat = 0;
#endif
  MeasurementOutbox controls[2][4];
  uint64_t context = 0;
  uint64_t bridgeLower = 0, bridgeUpper = 0;
  uint32_t bridgeToken = 0, bridgeNext = 0, bridgeStarted = 0, bridgeRetry = 0, bridgeTick = 0, bridgeEpoch = 0;
  bool bridgePending = false, bridgeReady = false, bridgeExpired = false, timingEnabled = false;
  uint8_t nextControlNode[2] = {};
  // Empty sample/evidence probes must not suppress each other at one node.
  uint32_t nextHeadPollMs[2][5] = {};
  // Last MOSI poll observation, never received/accepted data.
  uint32_t previousPollObject = 0;
  uint8_t previousPollClass = 0,previousPollNode = 255,previousPollIndex = 0;
  uint8_t terminalNodes = 0;
  // Link recovery never resets this bank: accepted IDs, partial objects and
  // outstanding ACKs remain owned until an explicit recording fence.
  bool recovering = false, failed = false;
  uint32_t recoveryStarted = 0, recoveryToken = 0;
  BodaqsMeasurementMode recoveryBinding = {};
    BodaqsMeasurementSlot lossDiagnostic = {};
    bool lossReady=false;
};
#if BODAQS_MEASUREMENT_VERSION >= 4
inline MeasurementInbox& sampleWindowInbox(MeasurementTransport& transport,uint8_t node,uint8_t slot) {
  return slot?transport.sampleExtra[node][slot-1]:transport.inboxes[0][node];
}
inline MeasurementInbox& nextSampleInbox(MeasurementTransport& transport,uint8_t node) {
  return sampleWindowInbox(transport,node,(transport.sampleNext[node]-1)%4);
}
#endif
// Queue immutable control; repeated identical queueing is idempotent. STOP can
// replace a queued renewal. Service routes all concurrent MISO into the bank.
bool queueMeasurementControl(MeasurementTransport&, const BodaqsControlWrapped&,
                             uint32_t objectId, bool authorization = false);
int serviceMeasurementTransport(MeasurementTransport&, uint8_t pollClass,
                                uint8_t pollNode, MeasurementInbox*& completed);
// Call only after the whole validated object is retained in downstream bounded
// RAM. Until then the bank keeps it pinned and does not send its RAM ACK.
void releaseMeasurementObject(MeasurementInbox&);
// Single-lane convenience: repeat the same class/node until delivery/ACK.
// For interleaved lanes use serviceMeasurementTransport.
// One physical slot per call. 1 new complete RAM object, 2 duplicate, 0 pending,
// negative transport error. Consume/copy a complete object before calling again.
// Keep a distinct inbox per class/node; the master pins one data object per node.
int pollMeasurementObject(uint8_t cls, uint8_t node, MeasurementInbox& inbox);
bool acknowledgeMeasurementObject(MeasurementInbox& inbox);
// Shared logger-to-master ID allocator for classes 3/4. Zero means unavailable
// or exhausted. All callers, including lifecycle code, use this allocator.
uint32_t nextMeasurementObjectId(uint8_t cls, uint8_t node);
// Caller retains immutable ID/content across retries, never wraps/reuses IDs.
bool submitMeasurementControl(const BodaqsControlWrapped&, uint32_t objectId,
                              bool authorization = false);
bool queryMeasurementNodeState(uint8_t node, uint32_t boot, uint32_t operation,
                               BodaqsControlWrapped& result);
void scheduleConfigurationReconciliation();
// Freeze mutations before recording; the original deadline is never extended.
void beginRecordingHandoff();
bool recordingHandoffReady();
bool recordingHandoffActive();
void endRecordingHandoff();
void enableControlAuthority(uint64_t session);
// Idle-only release changes authority and preserves hardware configuration.
bool releaseControlAuthority(uint8_t address);
// Current epoch-checked hardware agreement; configuration-only, never readiness.
bool configurationReconciled(uint8_t address);
#if defined(BODAQS_PACKED_STARTUP_DIAGNOSTICS) && BODAQS_PACKED_STARTUP_DIAGNOSTICS
uint32_t configurationReadinessBlockers(uint8_t address);
void logConfigurationReadiness();
#endif
// Explicit selected-link capabilities; protocol compatibility alone is insufficient.
uint8_t acquisitionLinkProfile(uint8_t address);
bool acquisitionLinkCompatible(uint8_t address);
void begin(const board::BoardProfile& profile, const LoggerConfig& cfg);
void applyConfig(const LoggerConfig& cfg);
void loop();

// Performs a bounded probe immediately. Intended for boot, configuration, and
// explicit user scans; normal background probes are scheduled by loop().
bool probeNow();
void requestProbe();

const Diagnostics& diagnostics();
const char* stateKey(State state);
const char* shortStatus();
const char* controlShortStatus();
bool present();
bool requiredAndUnavailable();

}  // namespace CanMasterManager

