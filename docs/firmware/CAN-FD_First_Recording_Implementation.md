# First real recording implementation evidence

Integration base: `f0418b9d73627342e64d64f61e497169efda4bba`.
Separate throughput prototype: `e0b58bc9372d6a0263bf43470768573383b0fadd`.
Governing decisions: [first recording design](CAN-FD_First_Real_IMU_Recording_Design.md).

## S1 / #188: restricted entry scope

Reuse `bodaqs_s3_mini_n4r2_imu_smoke` and its existing
`BODAQS_SINGLE_NODE_IMU_SMOKE=1` guard. The actual recording preparation path
accepts one reconciled CAN IMU and rejects a second node, another active sensor,
and active external ADC channels before allocation or acquisition authorization.
The only supported effective IMU profile remains `imu6_3333_32g_2000dps_v1`;
this work does not introduce rate substitution. The report remains `benchOnly`
and `qualified=false`; ordinary builds still require a qualified admission
profile. #177 and its frozen four-node no-go remain in force.

At nominal 3333 six-axis samples/s, useful axes demand is 39,996 bytes/s.
Five-sample packets require approximately 666.6 CAN receptions/s. Their retained
76-byte records cost 50,661.6 bytes/s before batch headers. Full 13-reception
batches cost 1008 bytes, about 51,687 bytes/s; partial heads sealed by evidence
and the 20ms timer cost more. These are arithmetic estimates, not service bounds.
Start/periodic/final observations, node/master SYNC, models/anchors, loss records,
control replies and SPI bridge observations must also receive service. Changing
healthy renewals from ten to one per second reduces authorization CAN traffic
from about 40 to 4 frames/s/node; it does not remove other control traffic.

The selected future transport is 256 bytes at requested 16MHz, 25us inter-CS
guard, boundary-only publication, with logical objects at most 1024 bytes.
Raw wire time is 128us plus guard per exchange before software costs.
Round17's 223.773kB/s accepted synthetic logical bytes is a feasibility proxy
only: it omitted normal CAN service and SD persistence and is not a measured
real-path guarantee. One-node raw demand is comfortably below that proxy, which
justifies an experiment, not production admission or a storage guarantee.

Retain the existing independent 64-record node queue, 128-record per-node master
retention and immutable selected head (up to 13 receptions). Logger allocation
is performed before authorization and reports actual reserved bytes. Master
256-byte RX/TX/DMA placement has not yet been implemented: S4 must inspect the
actual per-bank linker map and 2048-byte stack reservation. Spare aggregate RAM
cannot substitute for available RAM in the correct bank. S7 must record final
target maps and logger allocation after all slices are integrated.

Validation: `test_remote_imu_lifecycle_runtime.py --smoke` passes the existing
production-owner lifecycle scenarios and three preparation rejection scenarios.
The ADC scenario supplies a board with an external ADC; a board with no ADC
cannot model this demand. No hardware was accessed. Existing admission math and
historical capacity reports are unchanged. Local verified slice completion
satisfies implementation dependencies; GitHub issues remain open pending separate
closure authorization.

## Pending implementation

S4 #179 real ACK/fetch boundary review; S6 #185 STOP/tail isolation;
S7 #189 reviewed candidate. S1/S2/S3/S5 are locally implemented and reviewed.
S8 #190 is the subsequent manual physical capture. No physical results are claimed.

## S2 / #180: authorization implementation

The separately committed numeric change uses shared 5000ms lease, 1000ms renewal
and unchanged 300ms challenge constants in the real node issuer/expiry and logger
validator/scheduler. Focused node and actual logger-owner regressions pass.
Retryable renewal failures keep the previous confirmed deadline; retries are
bounded to one fresh attempt per second, without catch-up bursts. Initial proof,
terminal errors and identity/integrity failures retain terminal behavior.

Actual-owner tests cover lost challenge, proof accepted remotely with lost
result, repeated failed renewals through confirmed expiry, STOP during retry,
late proof after STOP, and millisecond/native-tick rollover. The disabled bind
loss injector needs its deadline initialized in the past at rollover; otherwise
it injects unintended loss. Node protocol tests preserve the separate freshness
window and readiness timeout. Both ordinary and restricted lifecycle fixtures
pass, including four-peer host regressions (not physical qualification).

The changed cadence exposed a real predecessor-result starvation during STOP
over an optional snapshot. A successor ordinary request could occupy every TX
turn while its pinned predecessor still lacked a response fragment. Transport
now fetches partial control predecessors before sending that lane's successor;
other lanes and terminal STOP remain serviceable. Existing end-to-end production
lifecycle regression reproduces the failure before this correction. Deadlines
are unchanged. Fresh lifetime/transport review is required before S4 proceeds.

Fresh review of `d9498ad..38f423f` found a stranded predecessor could override
healthy polling indefinitely, and a stale-success STOP test only replayed the
node request. Fix `6c7c933` bounds that override to a live successor's original
300ms outbox lifetime and tests actual encoded master/MISO success fragments
after STOP (whole replay and split across STOP). The production transport test
keeps node0's second ordinary fragment permanently lost while node1 data/control
progress; restoring the old condition fails that regression. Follow-up review
accepted both fixes. Additional passing owner cases inject matched errors
7/10/20/26, proof rejection reason20, and stale success while a newer retry is
pending: none creates extra authority. The reviewer inspected sources and
supplied results; physical CAN adapter/timing qualification remains deferred.

## S3 / #178: compact packet observation recording

`6527790` adds the versioned 100-byte packet schema, selected only by the
restricted smoke build, plus independent untimed decoding. See the
[byte-level contract](CAN-FD_Compact_Packet_Observations.md). Existing formats
and ordinary builds keep the legacy sample schema. The real node/master/writer
tracer passes with timing models omitted and with raw clock snapshots absent;
START/STOP sequence identity remains sufficient for those cases. No nominal
acquisition times are invented. Legacy writer and 27 reader/timing regressions
pass. Offline tool/dependency/SDK preflight passes.

Fresh review found non-adjacent exact replay was rejected by the ordering solver.
Immutable master reception identity now resolves replays before ordering; a
production recording/writer regression fails before that correction and passes
afterward. Added cases cover 1000 readings with periodic floors, low16 wrap,
five-sample gaps, short packets, two-cycle ambiguous loss, contradictory STOP
bounds, compact recovery segments, interrupted prefixes, reserved input bits,
nonzero padding and 2048-record queue backpressure. Queue refusal is verified
before publication and consumer drain allows retry. Full retained-head/partial
progress testing remains mandatory at S4's real transport seam.

The legacy master still requires a full-sequence origin anchor (0x22); this is
source interpretation metadata, not an applicable model. Its older low16 loss
accounting must be reconciled explicitly with the new transport in S4. No
real-path throughput, target memory, timing or storage qualification is claimed.

Follow-up S3 review found that a replay after a newer snapshot carries a newer
logger floor despite having unchanged master reception identity. `ed1206c`
excludes this interpretation-state field from immutable-content comparison. The
new replay-after-floor300 writer/reader test fails before the correction and
passes after it. Fresh reviewer accepted the fix with no remaining concrete S3
source findings; S4's retained-head evidence remains outstanding.

## S5 / #182: final sample-associated raw observation

The node caches the last completely associated sample's sequence, sensor time,
capture tick/ordinal, sensor/stream epochs, FIFO slot/tags, model identity and
raw SYNC state when that sample is appended. Normal STOP flushes samples,
emits a raw snapshot from that cache, then emits the separate STOP-time boundary.
It never pairs a cached sensor timestamp with the later STOP tick. Start and
100ms-or500-sample periodic observation triggers remain unchanged. Optional
snapshot queue pressure retains its existing explicit-loss behavior; it does
not prevent retained axes from being decoded.

The actual node adapter -> master fragments -> stream -> BDQ writer -> independent
reader test verifies final sequence64, sensor timestamp7008, capture tick175600,
and capture/slot increments64 from the start observation. Full node capture,
SPI and acquisition host suite (including recovery, wrap/fault, queue pressure,
FIFO ordering and repeated recording turnovers) passes. These are deterministic
host clock values, not measured physical timing or a fitted timing model.

Fresh S5 reviewer found no source defect, but required STOP-specific boundary
evidence. Added production adapter scenarios17..19 now demonstrate STOP during
recovery retains the previous associated raw pair, sustained TX pressure skips
the optional final snapshot with evidence-loss accounting, and an empty successor
STOP emits no stale previous-recording snapshot. The full node suite passes.

Fresh reviewer independently reran modes17..19 and closed the S5 boundary
checkpoint at `5cf696a`, with no remaining source/evidence findings in scope.

## S4 / #179: real v2 ACK/fetch and adapter integration

Protocol commit `290a1f2` passed fresh wire/ownership review with no blocking
source findings. Additional requested hostile-proof/exhaustion/CRC cases now
pass. The selected candidate explicitly builds real measurement version2 at
256 bytes/requested16MHz/25us; legacy defaults are retained. See the
[wire, ownership and memory contract](CAN-FD_Measurement_v2.md).

The adapter adds four queued RX extents and explicit BANK1 wire storage. The
actual TI map and compiler stack reports are retained outside the source tree
under `drain-capacity-evidence/first-real-imu-implementation/s4-target`.
Compiler stack evidence required a4KB reservation for v2; both banks fit. Final
candidate builds will replace these interim working-source artifacts.

Actual logger/master tests keep an unadmitted real immutable batch pinned,
then admit it into RAM; lose its retirement reply; assemble a shorter successor
without confirmation; and withhold it until an exact proof arrives. Wrong proof
fields and a late predecessor proof cannot clear the pending ACK. Empty probes
stay bounded. The actual node/master/writer/reader path now runs at both wire
profiles, including v2 with optional models, clock snapshots and model-origin
anchors omitted. It preserves sample identity through START/STOP bounds.

V2 also removes legacy low16 inference from retained source sequencing and
keeps master loss reports count-known/interval-unknown. Raw ISR epoch extraction
and optional timing classification are covered by production adapter tests.
Full queue/partial consumer progress and final STOP/fence/restart remain S6
integration obligations. Fresh adapter/wire/lifetime review precedes S6.
