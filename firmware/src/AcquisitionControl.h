#pragma once
#include <stdint.h>
#include <stddef.h>
#include "CanControlProtocol.h"

// The control task is independent of sampling and storage. Requests are copied
// into bounded mailboxes; callers never run transport or lease progress.
namespace AcquisitionControl {
enum class Action : uint8_t { Prepare, Start, Stop, Snapshot, Fence, Release };
enum class Result : uint8_t { Idle, Pending, Succeeded, Rejected, Uncertain, Unavailable };
struct Request {
  Action action = Action::Snapshot;
  uint8_t node = 0, reason = 0;
  uint64_t recording = 0, revision = 0, epoch = 0;
};
struct Outcome {
  uint32_t serial = 0;
  Action action = Action::Snapshot;
  Result result = Result::Idle;
  uint8_t reason = 0;
  uint64_t revision = 0, epoch = 0;
  bool leaseAcknowledged = false, snapshotValid = false;
  bool tailDiscarded = false, localFenceComplete = false;
  bool sampleTailDiscarded = false;
  uint32_t tailObjectsDiscarded = 0; // Known local unaccepted objects; master backlog may be larger.
  bool excluded = false; // Terminal for this recording; local acquisition continues.
  bool terminal = false; // STOP intent also forbids rejoining without discarding a valid tail.
  uint8_t snapshot[128] = {};
};
// Observational only. Published by the transport owner every100ms and at fence/exit transitions;
// consumers copy under the existing outcome lock, never inspect live inboxes.
struct FenceDiagnostics {
  struct Retained {
    uint32_t object=0, ackObject=0;
    uint8_t flags=0; // bit0 complete, bit1 admitted, bit2 ACK pending
  } data[3][4]; // sample, evidence, shared (shared uses node0 only)
  uint32_t observedMs=0, inspections=0, observations=0;
  uint16_t modeFlags=0;
  uint8_t recordingMask=0, confirmedMask=0;
  uint8_t ordinaryMask=0, protectedMask=0, mutationMask=0, mailboxMask=0;
  bool allFenced=false, verified=false, recovering=false, failed=false;
};
void fenceDiagnostics(FenceDiagnostics&);
// Explicit main-task handoff, after the configuration handoff has drained.
// Entry/exit run in the owner task; failure retains ownership for inspection.
bool begin(uint64_t recording, uint64_t context);
bool enqueue(const Request&);
bool outcome(uint8_t node, Outcome&);
bool requestExit();
bool active();
size_t reservedBytes();
// Registered while stopped. Invoked only by the transport owner for complete
// immutable data objects; true means retained in downstream bounded RAM.
using DataConsumer = bool (*)(uint8_t cls,uint8_t node,uint32_t object,const uint8_t*,uint16_t);
bool setDataConsumer(DataConsumer,uint8_t nodeMask);
// One slot per control step; mode negotiation retains its bounded one-second
// entry/exit handshake. The lease-only task is not the #169 sample/data drain.
// Host fixtures call this same seam with physical SPI/time substituted.
void service();
}  // namespace AcquisitionControl
