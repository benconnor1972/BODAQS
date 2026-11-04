# Leased acquisition lifecycle implementation (#168)

Implemented on 4 November 2026 from verified integration `655bbcd`, with the
integration evidence update `3c30eec` merged before completion. The binding
specification remains [#164](https://github.com/benconnor1972/BODAQS/issues/164),
[acquisition contract section 3.1](CAN-FD_Acquisition_Transport_Contract.md), and
existing Q1-Q70 control semantics. This record describes software evidence.

## Node lifecycle and wire behavior

The production node dispatches acquisition operations through
`bodaqs_control_acquisition`, sharing the existing authority, effective state,
and immutable snapshot owner. Acquisition opcodes 0x20-0x2A validate their
accepted lengths, node-wide selector and reserved fields. PREPARE stages exactly
112 bytes in five immutable pages. Initial challenges require complete staging;
COMMIT rechecks boot/session/record/mask, revision, state epoch and current stopped
profile proof. The admitted operation retains its sequence through preparation.
Configuration support alone does not admit acquisition: the production node has
no acquisition backend until #169 and reports `native_not_ready`.

Challenges are bound to their completed stage or live membership and independent
renewal sequence. Issuance fixes the one-second authorization horizon and 300 ms
response deadline. Identical requests/proofs retain their original deadlines;
renewal does not consume ordinary mutation sequence or advance an unchanged
endpoint epoch. The service enforces expiry independently of receiving requests.
Preparation has a separate five-second deadline starting at accepted COMMIT.

START stays pending until an independent backend event supplies the first
complete validated post-acceptance slot, with source sequence zero and explicit
boundary validity. STOP invalidates permission before physical work, supersedes
pending acquisition, and sends cancellation through one main-loop backend owner.
Generation-tagged events cannot revive canceled work or overwrite newer ordinary
results. STOP can overtake a queued COMMIT and terminally cancel staging; a late
COMMIT cannot acquire membership. That canceled-stage tombstone permits explicit
fence/release without inventing acquisition or a hardware boundary.

First/final boundaries survive newer operation replies until membership cleanup.
Known-empty, pending and unknown boundaries remain distinct. Hardware stopped is
asserted only by a backend stopped-register proof. FENCE waits for independent
queue/CAN retirement; RELEASE requires stopped, invalid authorization and completed
fence. A newly bound authority can inspect and clean abandoned stopped membership;
binding does not clear the membership or relabel its original owner.

Runtime transitions preserve applied revision and desired generation, advance
endpoint eligibility epochs, and invalidate old register proof. Backend readiness
and stopped events supply current register images; historical proof never grants
native readiness. The generic node-wide reply keeps existing zero revision and
generation fields; acquisition state and renewal replies provide their specified
revision/epoch evidence instead.

Schema 5/v1 captures all 128 acquisition-state bytes through the existing single
snapshot pin, five-second lifetime, paged reads and release. Opens with reused
identity but changed recording request conflict. Pages remain immutable while
live state changes. Acquisition metadata reports the captured revision and epoch.

## Master and logger owners

The existing independent ordinary/protected lanes carry unchanged records.
COMMIT admission conservatively makes the master nonquiescent/unfenced even if
its eventual node result is lost. Completed node FENCE results, including fresh
GET_OPERATION recovery, retire retained CAN data; physical SPI/DMA/preloaded data
retirement occurs separately at a real CS boundary before mode exit. Retired CAN
tails are counted in `retired_tail_frames`; unknown node tails retain missing final
validity. Context exit cannot derive producer safety from stale initial defaults.
The Q144 legacy cleanup allowlist admits observational reads, fresh binding,
fencing and membership release while node authority/stop checks remain binding.
It cannot grant PREPARE/START/RENEW.

Ordinary diagnostics retain their global four/s, burst-four limit and Q70 retries.
Finite lifecycle staging, operation recovery and acquisition snapshot reads use
a separate bounded implementation scheduler: global twenty/s, burst four, with
round-robin node service. Protected attempts retain twenty/s/node, burst two,
with STOP priority. These lifecycle burst costs must be charged explicitly by
#173; this scheduler bound is neither an admission nor a bandwidth qualification.

`AcquisitionControl::begin` explicitly takes ownership after the existing
configuration recording handoff drains. A dedicated FreeRTOS task copies bounded
per-node intents and publishes typed copied outcomes; sampling/storage tasks do
not advance leases. Per-node ordinary and protected exchanges progress separately
through #167 bank APIs, with no blocking diagnostic API used as the lease
scheduler. The owner attempts renewal every 100 ms without catch-up bursts and
uses the local challenge-request start for conservative authorization deadlines;
it never compares node ticks to logger time. STOP is terminal locally before
transmission. Lost operation outcomes remain uncertain and cease authorization
or request terminal STOP, rather than infer rejection or collection absence.
A previous immutable result's RAM ACK retires before its same-lane successor,
preventing pinned-result deadlock while allowing urgent STOP priority.

## #169 integration seams and limits

- Install a real `BodaqsAcquisitionBackend` in the node main loop. It must own all
  preparation, FIFO/timestamp/interrupt changes, actual first/final events,
  cancellation and old-data queue/CAN retirement. Configuration and acquisition
  must never poll the existing single physical IMU SPI exchange concurrently.
- Bind `bodaqs_control_acquisition_set_clock` before staging to the same low32
  nominal-microsecond native capture clock and nonzero clock epoch used by sample
  boundaries. Issuance is captured once; wire deadlines add 300000/1000000 ticks.
  Captured state and preparation deadlines use that same phase. Changing a live
  clock epoch excludes acquisition. The unbound fallback is explicitly a
  millisecond counter multiplied by 1000, quantized to 1 ms, not qualified native
  timing. #169 supplies node capture; #170 supplies synchronization/bridge models.
- The logger recorder calls `begin`, enqueues Prepare with reconciled revision/
  epoch, observes readiness, reads a fresh immutable Snapshot for prepared epoch,
  then enqueues Start. Stop/tail drain, Fence, Release and successful mode exit
  precede returning manager ownership and ending the configuration handoff.
- The task currently runs one control slot per service turn with one RTOS tick
  between turns, priority two and a 4096-byte task stack. It is a lease/control
  implementation, not the sample drain scheduler. #169 must integrate bounded
  data draining; #173 must account for the full transport bank, task stack,
  producer queues and actual service costs. Current A8 unused-function linking
  may remove recorder-facing lifecycle storage until that client is connected.
- Normal five-second orderly tail drain belongs to the recorder before Fence;
  Fence must not silently replace it. Persistence, source pairing, native driver
  recovery and multi-node resource admission remain #169/#171/#172/#173 work.

## Validation

The common acquisition test sends real 68-byte logical control objects through
measurement fragments, production master dispatch, 64-byte CAN codecs, node
services and an independently driven backend, then reads immutable state pages.
It covers incomplete staging, duplicate fixed deadlines, stale initial proof,
pending preparation with protected renewal, five-second readiness expiry,
staging expiry, actual START/final boundaries, STOP before/during COMMIT,
delayed backend events, idle-traffic lease expiry, known-empty versus unknown,
revision preservation, shared immutable pins, explicit fencing/release and fresh
binding of abandoned membership. A native clock adapter fixture verifies a
nonzero phase offset and exact 300000/1000000 tick intervals independently.

`test_acquisition_control_runtime.py` runs the real production logger owner and
master over pipelined SPI with four independently driven node backends. Four-node
preparation/renewal, delayed START, protected STOP, snapshots and full
fence/release/physical-retirement/mode exit pass. A held CAN COMMIT overtaken by
STOP cannot acquire, and its tombstone still fences/releases/exits. Existing
measurement, authority/API, apply/API, recording handoff, recovery, remote mute,
storage-worker and logging-start runtime regressions pass. All eleven common
host binaries pass under MinGW with warnings as errors.

Explicit MSPM0 node/master TI Arm Clang builds use SDK 2.11.00.07; explicit A8
PlatformIO `bodaqs_s3_mini_n4r2` compiles the new owner/client and passes.
Node: FLASH 30064 bytes, SRAM 4989 bytes including reserved stack. Master:
FLASH 34776 bytes, SRAM bank 0 14185 bytes including reserved stack. A8:
static RAM 217148 bytes, flash 1953601 bytes.
A target build is not evidence of free runtime heap, task stack watermarks,
qualified service latency or sustainable sample throughput.

No firmware was flashed. Physical #175/#176, FIFO/DRDY association, native clock
capture precision, SPI/CS/DMA timing, SYNC phase, four-node load and electrical
fault qualification remain deferred. Existing configuration happy-path behavior
and explained FRONT_FAULT bench telemetry are preserved.
