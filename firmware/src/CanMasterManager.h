#pragma once

#include <stdint.h>

#include "BoardProfile.h"
#include "CanMasterProtocol.h"
#include "../can-fd/common/protocol/bodaqs_fragment_transport.h"
#include "CanControlProtocol.h"
#include "../can-fd/common/protocol/bodaqs_measurement.h"
#include "ConfigManager.h"

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
bool measurementReady();
// Transfer mutable mode/transport/allocator ownership after configuration drain.
// The callback identifies the task currently executing the lifecycle service.
bool claimMeasurementControl(bool (*isOwner)());
void releaseMeasurementControl();
void retainMeasurementAllocators(uint32_t nextRead, const uint32_t nextMutation[4],
                                 uint64_t nextTransfer);
// One bounded physical exchange; caller demultiplexes by immutable identity.
bool exchangeMeasurementSlot(const BodaqsMeasurementSlot& request,
                             BodaqsMeasurementSlot& response);
struct MeasurementInbox {
  BodaqsFragmentState state = {};
  uint8_t bytes[1024] = {};
  bool ackPending = false;
  bool admitted = false;
  BodaqsMeasurementSlot pendingAck = {};
};
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
  MeasurementOutbox controls[2][4];
  uint64_t context = 0;
  uint8_t nextControlNode[2] = {};
  uint32_t nextHeadPollMs[5] = {};
  uint8_t terminalNodes = 0;
};
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
