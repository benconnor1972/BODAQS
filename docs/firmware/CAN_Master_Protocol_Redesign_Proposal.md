# CAN-master protocol redesign: consolidated proposal

13 November 2026. Q1-Q27 and this consolidated shared understanding are confirmed
by the user, who subsequently invoked to-spec. This is not a finished wire layout,
implementation authorization or demonstrated capacity claim. The
[specification](../specs/can-master-logger-protocol-redesign.md) synthesizes the
confirmed requirements, implementation boundaries and testing decisions.
Baseline: `1ebd9b28f0f46bb8a578197ed96870b458467ed7`.

The [interview](CAN_Master_Protocol_Redesign_Interview.md) retains the decisions
and qualifications; the [budget](CAN_Master_Protocol_Redesign_Budget.md) separates
arithmetic from measurements. [ADR0005](../adr/0005-decouple-sensor-transport-progress-and-verification.md)
records the architectural trade-offs. Existing acquisition contracts remain the
baseline except for the changes explicitly identified here.

## Intended result and provisional qualification targets

Reduce repeated requests, fragment handling, gateway wrappers, replay and
per-packet recording work sufficiently to make useful mixed acquisition viable
on the existing logger. Do not silently lower the native IMU rate.

| Area | Accepted target or boundary |
|---|---|
| Polling-only minimum useful profile | Two full-rate IMUs plus two local ADC channels at500Hz, one channel per ADC |
| Optional-IRQ profile | Four full-rate IMUs plus those ADC channels; also evaluate four-IMU polling |
| IMU ordinary-load quality | At least99.9% usable delivery per node over10minutes; no ordinary individual sample gap longer than20ms |
| ADC ordinary-load quality | At least99.5% fresh readings per channel over10minutes; no ordinary interval without a fresh reading longer than10ms; cached repeats do not count |
| Latency | Provisional100ms acquisition-to-logger-RAM normal target;500ms recovery target for budgeting, subject to feasibility |
| Timing | Healthy qualification supports unambiguous native sample timing; report delivery and timing reconstruction separately |
| Cross-sensor phase | Accurate high-frequency inter-IMU phase alignment is separately qualified |
| Operator STOP | Target acquisition cessation within300ms under admitted workloads, followed by up to5s buffered drain; observed confirmation is not an exact cessation timestamp |

These are engineering qualification targets, not a completed admissions policy.
Unchanged resource gates from the earlier acquisition/SPI revision contracts
remain: at most70%CAN and85%steady shared-SPI scheduling occupancy, plus at least
1.25times admitted useful sample drain with mandatory concurrent traffic active.
The new quality targets do not silently replace those gates.
Report percentage, longest gap, gap frequency, per-source results and invalid or
unverified data separately. Later-rejected readings count as loss. Fault trials
remain identifiable and their losses remain visible. No tier is yet proven.

## Transport and ownership

- The logger supplies SPI clocks and directs control; the master prepares the
  next useful reply without a per-node/object/fragment fetch before every reply.
- Each ordinary sample unit fits one physical transfer and carries sufficient
  scoped identity for independent checking, selective acknowledgment and repair.
  Larger configuration messages may span transfers off the ordinary sample path.
- Establish full stream definitions explicitly and retain them in the recording.
  Compact references must distinguish source, acquisition instance and sequence
  position without aliasing after restart or wrap.
- Published sample units are immutable. A bounded window permits progress while
  other units await acknowledgment; retries must not repeatedly block every source.
  Explicit, accounted-for abandonment terminates unrecoverable units.
- ACK transfers custody into bounded logger RAM after live transport safety
  checks. It promises neither SD durability nor completion of offline verification.
  Duplicate receipt/ACK is idempotent; stale or mismatched acknowledgment must
  never retire another unit. Exact credit and retirement rules need specification.
- Preserve established CS retirement, DMA/buffer ownership and first-byte safety
  requirements while replacing the old response-publication pipeline. DMA
  completion alone is not proof that a transfer has physically retired.

## Scheduling, metadata and overload

Samples, timing evidence and essential control can make progress independently.
Reserve bounded memory and service for STOP, authorization renewal, acknowledgments
and essential state even when ordinary data queues are full. An ongoing physical
transfer completes before urgent control takes the shared bus.

Shed diagnostics first, then optional alignment/timing detail. Protect definitions
and evidence necessary for safe interpretation and the agreed native timing
quality. After shedding, unavoidable overflow drops newly arriving complete data
units and records gaps; it does not silently overwrite queued published history.
Trustworthy late readings remain useful, but a sustained service deficit fails
capacity qualification. Reset, expired authority or untrustworthy sample identity
ends the affected stream; healthy sources continue, without automatic same-session
rejoining of an excluded source. Missing optional timing evidence alone must not
be treated as lost acquisition authority.

## Integrity and recorded representation

Perform physical-transfer CRC, bounds, identity and ACK-safety checks live before
RAM acceptance. Retain a master-origin checksum over immutable unit identity and
content through recording for offline verification. Storage checks protect their
own later boundary; a fresh logger-generated checksum cannot detect an earlier
undetected change. Canonical checksum coverage and serialization need explicit
test vectors. Checksums detect accidental corruption, not malicious substitution
or all semantic software errors; do not multiply nominal CRC probabilities into
an unsupported system reliability claim.

Move heavier clock fitting and interpretation offline where sufficient evidence
is retained. Stored unverified blocks must be distinguishable from verified
readings; valid readings with degraded timing remain available with limitations.
Distinguish reconstructed/modelled timestamps from observed clock captures, and
preserve uncertainty where source loss prevents exact sequence reconstruction.
Do not invent missing counts or exact sample times across unknown-loss boundaries.

Use compact sensor units and amortized identity instead of preserving every CAN
reception wrapper. Initially retain the existing CAN profile and node sample
payloads; grouping them is a low-repacking candidate, not a frozen byte layout.
Version any new BDQ stream representation explicitly, preserve historical file
readability, and implement the offline decoder alongside the writer. Account for
per-channel ADC freshness/age explicitly; equal values do not imply reused data.

## Physical profiles and compatibility

Compare256/512-byte transfers; retain256as a supported new-protocol option and
defer1024unless a revised budget establishes need. Requested16MHz gives nominal
clock-only durations128/256us, not measured bus-ownership bounds. Qualify ADC
freshness and control deadlines on hardware for each useful profile.

Optional ready IRQ is level/latched and indicates new or explicitly requested
retry data ready for a safe transfer. It is neither authority nor validation.
Control can operate without data-ready. Retain bounded polling/watchdog behavior
for absent or stuck IRQ; verify actual pin availability, wiring and readiness
publication before using it.

Require matched new master/logger firmware, with explicit incompatibility errors
and no automatic old-wire fallback. Existing logger hardware and CAN nodes remain
targets. Node/CAN changes and master-local ADC acquisition are outside the first
slice; future logger hardware changes are not prerequisites for this work.

## Implementation and evidence sequence

1. Specify canonical wire/storage layouts and ownership rules; check geometry,
   stage-specific memory, control reserve and service budgets. Exercise identity,
   corruption, retries, duplicates, stale ACK, wrap/reset and bounded overload in
   host tests using explicit expected outcomes.
2. Run one real IMU through transport, recorded file and offline decoding. Prove
   safe ownership, integrity evidence, source boundaries and STOP cleanup before
   scaling. Host throughput alone is not this evidence.
3. Qualify two IMUs plus the two500HzADC channels without IRQ against the ordinary
   ten-minute targets, measuring timing reconstruction and latency where evidence
   permits. Do not substitute software queue age for physical acquisition latency.
4. Evaluate four IMUs with polling, then IRQ; compare256/512where useful. Measure
   useful samples, empty/replayed transfers, repair, service/bus ownership, queue
   depth/age, ADC freshness, storage behavior and control progress.

Automate result collection and assessment, preserving raw evidence, firmware and
configuration identity. A material capacity shortfall triggers bottleneck review
before scope expansion. Controlled storage-stall testing stays deferred; results
on the present high-endurance card do not qualify every card or arbitrary stalls.

## Engineering work explicitly left to specification and measurement

Field widths, stream binding and sequence extension, checksum encoding, partial
unit flush age, window/credit sizes, retry limits, scheduling/fairness, timing
observation cadence, IRQ wiring, recording schemas and exact buffer placement
are not silently fixed by the interview. Select the smallest design that meets
the agreed targets, document invariants and budgets, and surface any choice that
changes those targets or integrity/compatibility boundaries before implementation.

In particular, four-source500msraw backlog is about80kB, exceeding currently
reported unused master BANK1 space before overhead. A500msrecovery target is not
a promise of lossless operation while SPI is blocked. Logger storage backlog and
master transport backlog occupy different resources. Budget both and require
positive excess service for recovery; buffering cannot fix a sustained deficit.
