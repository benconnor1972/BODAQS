# Production integration progress

Destination: `feat-CAN-firmware`; work branch: `integration/logger-production`.
Requirements checkpoint: `c11cc31e`. Issues remain open on GitHub; this local
ledger records code dependencies without implicitly closing tracker items.

| Issue | State | Evidence / remaining work |
|---|---|---|
| #214 | Complete | Source-pinned r133 baseline and selected RTC release port; both A8 target builds pass. START harness: 133 checks; remote lifecycle/fault scenarios and RTC runtime tests pass. |
| #215 | Implemented; qualification pending | Atomic phase, control-task transitions and producer fault requests; nonblocking ADC/row retirement, retained-resource mutation/restart/sleep guards, phase API/UI. START/preflight 133 checks; asynchronous controller 39 checks; target candidate builds. Final fault/outcome checks continue in #226. |
| #216 | Implemented; qualification pending | Explicit adaptive drain; production ROM CRC and owner-only DMA batches; observers and mandatory console/benchmark gates disabled. Adapter, storage owner/recovery fixtures and candidate target build pass. Physical no-console/mixed-load gate remains. |
| #217 | Implemented; qualification pending | Embedded sensor/config/calibration snapshot, typed raw/basic-engineering normal import and read-only analog preview/calibration publication implemented. Flexible/direct acquisition is in #218; serializer, normal-import and adapter checks pass; target builds. Physical qualification remains. |
| #218 | Implemented; qualification pending | START plan binds sensor identities, sparse/unequal/idle external ADCs and direct GPIOs to typed count fields. One rational absolute timer; independent device appointments, skipped-row evidence, no dummy conversions. Actual ADC-manager/SPI/DRDY/timer model and dynamic queue tests pass; candidate build passes. Focused physical comparison remains. |
| #219 | Implemented; qualification pending | Existing native 833/1667/3333 node profiles retained and exercised; normal import exposes independently verified six-axis counts/scaling while preserving unit/timing streams. Source-bounded completeness, uncertain timing and corrupt-source isolation tested. Four-node real recording composition imports normally. Physical profile/UI qualification remains. |
| #220 | Implemented core; qualification/UI pending | Bounded 5ms idle control progress while configured nodes are unreconciled; priority/fair cursors, faster inventory discovery, scoped snapshot reuse and explicit invalidation. API preparation/blockers added. Actual manager/model cold/change/late/failing-peer checks and target build pass; broader migration/UI #225 and physical before/after remain. |
| #221 | Implemented; qualification pending | Analog/I2C string-pot typed native counts, signed tracking estimate, quality/reset/epoch and auxiliary I2C evidence; owner-only acquisition and snapshot previews. Normal calibrated/raw-only import, direction/hold/timeout/gap/loss/overflow/restart and preview-equivalence checks pass. Reviewed A8 build and 69 focused import tests pass; physical qualification remains. |
| #222 | Implemented; qualification pending | Both rotary families record native counts, optional register evidence, validity and configured zero/polarity; bounded PSRAM-first queues and snapshot-only previews. Actual adapters, atomic calibration persistence/epoch fencing, normal import and queue fault fixtures pass. |
| #223 | Implemented; qualification pending | Native FIFO recording and scale/orientation import preserved; previews now read coherent published snapshots without consuming sample/evidence queues. Actual adapter/retirement checks, focused imports and A8 target build pass. |
| #224 | Implemented; qualification pending | Native fixed-point UART observations, fix/time/accuracy evidence and embedded settings; bounded queue, lifecycle fencing and normal derived import. Actual sensor/catalog/import fixture and A8 build pass. Physical receiver/mixed-load qualification remains. |
| #225 | Implemented; qualification pending | One-time exact migration review, byte-preserved original, persistent acceptance, supported raw/native UI and canonical mutation guards. Calibration anchors and unknown source tokens survive save/reload. Mixed-case preference and shared-application review fixes tested; A8 build passes. Physical migration/UI gate remains. |
| #226 | Implemented; qualification pending | Bounded operational footer, I2C producer retirement barrier, cancellation ordering, shared-fault containment and late ownership recovery. Actual lifecycle/fault/allocator and normal-prefix import checks pass; A8 build passes. Physical fault gates remain. |
| #227 | Implemented; qualification pending | Shared strict/best-effort membership, supplied qualification and actual reservations drive START/API/UI and bounded metadata. Independent review fixes enforce admission before local preparation and use observational BMI readiness. Worker-allocation failure aborts admission. Focused lifecycle and normal-import checks pass; no general admission thresholds invented. |
| #228 | Implemented; physical impact pending | Explicit ordinary-board production and separately named candidate environments; legacy writer/transform/profile roots removed while functional DMA batching, adaptive policy and native families remain. Three target builds and independent two-axis review pass. Static DRAM falls by 49,392 bytes against the recorded intermediate baseline; runtime heap/timing qualification remains. |
| #229 | In progress | Source-pinned board-specific package/audit tooling implemented; fixed compiler timestamp and two clean strict builds produce identical image/ELF/map/recipe artifacts. Final integrated candidate package and peer provenance checks remain. |
| #230 | In progress; hardware gates pending | Full analysis suite: 615 passed, 1 skipped. Full firmware regression sweep and final review underway; review fixes and representative device checks remain before destination integration. See the qualification checklist. |

## Baseline provenance

Mechanical firmware/ADR import from the sealed r133 source archive, SHA256
`e36bc97680b1b189ac23d49bcfe1c5f9ca6ad7faa775ec0aafbe0ed8c8f4b067`.
Initial logger recipe before any source changes:
`recipe-sha256:b6f2dc637a5bc9fb5643228a189f9f3aae598b391fd9d0e5ab8fde326a6e062b`.
Current repository instructions, confirmed glossary and requirements are retained;
old archived instruction/skill documents were not imported over them. Historical
ADRs are retained for context, not a blanket requirement to keep superseded designs.

The selected baseline still has mandatory bench boot gates and fixed-layout RAW
guards. It is not production-ready; those are explicit later slices. Test-source
adaptation adds the newer handoff-active observation to a stale fake; it does not
change production behavior. Local command logs and exact imported-file inventory
are retained under the integration scratch workspace.

## Validation rules

Use the agreed real lifecycle/acquisition adapters, recorded BDQ contracts, normal
import and configuration/UI behavior as test seams. Apply red/green for new
behavior, retain independent hardware/time/transport models, and do not claim
hardware results from host tests. Full suite runs after integration; focused
regressions/builds run per meaningful change. Final code review is against
`c11cc31e`, with standards and issue-spec axes kept separate.

General admission-policy development and deferred physical qualification remain
release gates. No hardware flashing or new bench measurement occurs merely as
part of software integration. Finalization faults must preserve uncertainty rather
than fabricate complete recordings or reuse resources still owned by I/O.

## Lifecycle and operational boot slices (#215 / #216)

The control-loop task owns lifecycle transitions. Producer STOP calls publish
bounded fault requests, rather than retiring themselves. State is published as
one atomic phase; configuration/restart/sleep guards include retained CAN and
storage ownership. ADC row-producer retirement now reports progress without
waiting in the UI/control loop. The status API adds `recording_phase`,
`recording_ownership_retained` and `stop_reason`; existing fields remain.

The initial candidate environment was `bodaqs_a8_production`. After #228,
`bodaqs_a8_integration_candidate` is the explicit unqualified measurement build;
ordinary `bodaqs_a8_production` requires separately supplied qualification coverage.
Both explicitly select the tested
adaptive drain policy, ROM file-payload CRC and synchronous 4096-byte owner-only
DMA staging, with optional CPU/cost observers disabled. Ordinary boot requires
no serial selection or calibration benchmark. Required storage reservations may
fail and be retried at an explicit START; they no longer stop boot indefinitely.
The benchmark environment exceeded static DRAM by 8 bytes after lifecycle
integration; removing its observers in the candidate restores a successful
285964-byte static-RAM build (target report). This is not a free-heap estimate.

Runtime fixtures verify blocked open/write/close, cancellation, producer faults,
allocation recovery, CRC known vectors, exclusive staging ownership, ordered
8-sector batching and immediate write-error propagation. Real remote lifecycle
and four-node failure fixtures pass. No new physical timing or throughput
qualification is claimed. The initial candidate still has fixed ADC geometry;
that is the next acquisition-plan work, not a production admission envelope.

## Acquisition plan (#218)

Production ADC field order follows configured sensor identity, not diagnostic
AIN ordering. One ADC owner retains its P4/core0 placement and captures inline;
CAN/storage priorities and placements remain unchanged. Each device advances
only through its own configured mask. Idle devices have no conversion work.
All local rows use absolute rational timer deadlines, including rates whose
period is not an integer number of microseconds. Late wakes skip appointments
without changing the MUX identity in flight or issuing catch-up rows.

The typed queue copies the declared variable-width prefix, with no acquisition
engineering transformation or float round trip. Analog engineering output
settings remain available outside recording; the recording schema is raw and
sensor-bound. Direct GPIO inputs explicitly select the 12-bit ADC resolution
and validate that the selected pin has an ADC channel.

The actual ADC manager is exercised against independent register, DRDY, timer
and conversion models: sparse/unequal layouts, an idle ADC, direct-only input,
negative-result clamping, fractional cadence, stale/late wakes, mismatched
register readback, timer-arm failure and repeated sessions. A separate actual
queue-adapter fixture covers zero through 32 fields, exact byte boundaries,
marks, overflow gap flags and malformed records. Legacy ADC setup and async
lifecycle fixtures still pass. These are correctness checks, not measured
physical settling, CPU capacity or an expanded admission envelope.

## Native CAN recording/import (#219)

Normal import expands retained units into `<source_stream>_samples`, preserving
original units and timing evidence. Upstream unit CRC, immutable identity, boot,
epoch, geometry, source-sequence constraints and duplicate consistency precede
sample exposure. A corrupt source is left as raw evidence with an explicit QC
warning; it does not discard independently valid local/other-source data.
Signed native six-axis counts remain available when scaling/profile evidence is
unknown. Engineering axes require matching recorded profile, rate and rational
sensitivity evidence. Observation timestamps are not acquisition timestamps;
sample time and inter-node alignment remain unknown until reconstructed.

Completeness is distinct from retained row count and successful file finalization:
an expected denominator requires source identities, consistent START/STOP bounds
for every observed segment, unambiguous sequences and no file decode errors.
Terminal missing samples are included. This is not a load admission policy.

Focused import regression: 60 tests pass. Independent fixtures cover all three
profiles, missing STOP, tail loss, mismatched profiles, epoch/boot mismatch and
upstream corruption behind a valid BDQ chunk CRC. Real node/master/coordinator/
storage/writer composition passes four-node custody, pressure, selective loss,
partial STOP and corruption cases; its good recording imports four 64-sample
streams through the normal pipeline. Node SPI/capture/acquisition tests and
native 1667/833 acquisition variants pass. No new physical qualification claimed.

## Idle reconciliation (#220)

Production idle preparation services one bounded control exchange at a time,
using 5ms dispatch spacing while configured participants need reconciliation.
The ready-state 100ms background cadence and recording-time dispatch are
unchanged. Unready configured nodes get observer preference with round-robin
selection; mutation scheduling rotates after each admitted apply. Discovery is
revisited at most once per second during preparation. Existing challenge,
snapshot, transfer and mutation uncertainty deadlines remain in force.

A coherent endpoint snapshot can be reused only after a fresh endpoint-state
response agrees on epoch, boot, identity and observed authority session. A
changed/invalid scope takes the complete snapshot and final epoch check again.
Discovery hardware-identity changes invalidate observation/authority/apply state
and renew the control scope. Failed observations retain deliberate retry backoff.
API configuration preparation and blocker fields describe agreement only; they
do not assert general recording admission or timing qualification.

Independent host composition models four healthy peers becoming reconciled in
1974ms and a saved profile change in 1333ms. These are simulated service times,
not hardware latency promises. An absent/returning peer is handled, and healthy
peers eventually reconcile with one continuously nonresponding peer (37595ms in
this model, including unchanged protocol retry/timeout behavior). This still has
failure latency; it does not freeze controls or declare the failed node ready.
Cache/session/epoch/reboot invalidation, actual profile/register application,
authority and snapshot suites pass; existing remote recording/fault lifecycle
regressions pass. A8 target build passes. Physical preparation measurements and
complete menu/web readiness presentation remain pending.

## Read-only count snapshots (#221, partial)

The ADC owner publishes each analog count and its own source status while
capturing the row. Analog-pot preview/calibration readers use an atomic,
generation-checked snapshot and never request another hardware conversion.
An overlapping publication returns unavailable instead of waiting. Independent
idle acquisition publishes at 50Hz; it is parked from session start through
finalization. Failed idle reads are unavailable, rather than valid zero values.
Reconfiguration invalidates the old snapshot.

Concurrent publication/coherent-read checks and the actual analog preview
adapter exercise no-observation, raw/engineering preview, repeated reads,
acquisition-owner publication, recording/idle transitions and invalid reads.
The actual ADC-manager model verifies configured sensor identity/count/tick
publication. The target builds. String-pot tracking/native records and the
remaining sensor families are still unimplemented in this slice.

## Interim independent review

Standards review found no confirmed documented-standard breach and noted the
imported timing decoder's opaque numeric evidence offsets as a maintainability
issue for later cleanup. Specification review identified omitted known CAN
terminal gap intervals and a zero-based START assumption. Both are corrected
with normal-import regressions: missing interval 2..3 is explicit; a source
starting at 3 does not invent losses 0..2. Missing STOP retains an uncertain tail.
The old assessment helper no longer duplicates terminal-gap construction.
The reviewer rechecked and confirmed the finding resolved. This interim review
does not replace the final review/qualification of the complete integration.

## String-pot integration (#221)

Analog string-pot inputs participate in the same per-ADC appointment plan, while
their typed native stream retains signed tracking and quality. Capture-only
inputs do not create duplicate primary fields. I2C string-pots keep their existing
worker/bus policy and retain raw, ANGLE and diagnostic observations with validity.
Engineering displacement is reconstructed offline from the embedded geometry.
See [the count-stream contract](../analysis/String_Pot_Count_Recording_Contract.md).

Preview/no-preview runs of the real sensor adapter produce identical records;
the actual I2C acquire/sampling adapters perform no extra reads for previews.
The independent ADC model covers native-only and mixed primary/native plans.
Queue loss and nonempty final depth are available to the existing BDQ footer;
failed-session rows can be cleared only after finalization has retired I/O.
The normal importer preserves raw values and suppresses unsupported derived
values, including uncertainty after an observation gap or settling timeout.

Independent review identified those last two uncertainty cases; both were fixed
and the reviewer confirmed them resolved. The standards review reported no
documented breach and one repeated configuration-builder heuristic, now factored
into one helper. Host checks include directions, settling timeout, ambiguous
tracking, queue loss, integer overflow, actual I2C diagnostics, missing calibration
and restart. No physical sensor/mixed-load qualification is claimed.

The I2C scheduler now has an optional owner-side missed-slot notification. Its
default is a no-op; only the string-pot adapter consumes it in this slice, so
task priorities, placements and dispatch choices remain unchanged. Native
sequence semantics are scheduled acquisition slots. Missing appointments are
visible even when every executed bus read succeeds. Saturating queue counters
and nonempty final depth retain loss evidence through the existing footer path.
