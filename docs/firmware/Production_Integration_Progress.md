# Production integration progress

Destination: `feat-CAN-firmware`; work branch: `integration/logger-production`.
Requirements checkpoint: `c11cc31e`. Issues remain open on GitHub; this local
ledger records code dependencies without implicitly closing tracker items.

| Issue | State | Evidence / remaining work |
|---|---|---|
| #214 | Complete | Source-pinned r133 baseline and selected RTC release port; both A8 target builds pass. START harness: 133 checks; remote lifecycle/fault scenarios and RTC runtime tests pass. |
| #215 | Implemented; qualification pending | Atomic phase, control-task transitions and producer fault requests; nonblocking ADC/row retirement, retained-resource mutation/restart/sleep guards, phase API/UI. START/preflight 133 checks; asynchronous controller 36 checks; target candidate builds. Final fault/outcome checks continue in #226. |
| #216 | Implemented; qualification pending | Explicit adaptive drain; production ROM CRC and owner-only DMA batches; observers and mandatory console/benchmark gates disabled. Adapter, storage owner/recovery fixtures and candidate target build pass. Physical no-console/mixed-load gate remains. |
| #217 | Pending | Counts/calibration snapshots and normal analog import. |
| #218 | Pending | Unified timer and flexible per-ADC plans. |
| #219 | Pending | Native CAN profiles and normal import. |
| #220 | Pending | Fast, fair, safely cached reconciliation. |
| #221 | Pending | String-pot evidence and snapshot previews. |
| #222 | Pending | I2C rotary sensor preservation. |
| #223 | Pending | Local BMI270 native preservation. |
| #224 | Pending | UART GPS preservation. |
| #225 | Pending | Configuration migration and UI. |
| #226 | Pending | Bounded finalization and runtime faults. |
| #227 | Pending | Truthful admission and membership. |
| #228 | Pending | Retire superseded production paths. |
| #229 | Pending | Reproducible board-specific package. |
| #230 | Pending | Final verification and destination integration. |

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

Candidate environment: `bodaqs_a8_production`. It explicitly selects the tested
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
