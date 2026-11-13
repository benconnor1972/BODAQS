# CAN-master/logger protocol redesign for mixed IMU and ADC acquisition

## Problem Statement

Users need useful, continuous IMU recordings alongside local analog measurements
on the existing logger. The current master-to-logger path spends too much work
requesting, preparing, repeating, assembling and retiring small pieces of data.
Per-reception wrappers and per-packet recording work add costs beyond the sensor
values themselves. Increasing polling frequency or queue depth has not reliably
increased useful throughput.

The latest four-node r23 recording delivered about 5,540 readings/s in its first
100 seconds against roughly 13,332 readings/s offered by four native-rate IMUs.
Whole-recording source-bounded missing readings were about 56.27%. Local primary
storage loss was zero in that recording. These are scoped observations, not proof
that a single stage explains every loss or that protocol changes will necessarily
meet the target. A bounded batching replay did not establish a sufficient live
gain to justify further isolated batching optimization.

The user wants a useful polling-only solution on existing logger hardware, a
better solution using the available optional interrupt connection, and evidence
that guides future hardware decisions. Occasional explicit sample loss is
acceptable; corrupted or misidentified readings presented as valid are not.
Repeated narrow prototype rounds must give way to early end-to-end evidence.

## Solution

Introduce an explicitly versioned, matched master/logger transport that delivers
master-prepared, self-contained sample units. Amortize stable identity, remove
ordinary sample fragmentation and unnecessary gateway wrappers, and use bounded
windows with selective recovery so one missing unit does not stop every source.
Protect essential control service independently of data queue occupancy.

Support polling without IRQ and optional level/latched readiness. Compare 256-
and 512-byte transfers against actual ADC freshness and control behavior. Keep
the existing CAN profile and node sample format for the first implementation
slice. Preserve existing logger hardware support and historical recording
readability while permitting a dedicated, versioned compact recording schema.

Validate transfers and safe custody live. Retain master-origin integrity evidence
through recording, then perform its verification and heavier timing/interpretation
work offline. Preserve useful readings with explicit timing limitations rather
than coupling every sample to successful delivery of optional metadata.

Prove one complete real recording path first, then scale to two IMUs plus local
ADCs and finally four IMUs. Use automated, source-specific assessment of actual
delivery, timing, freshness, control and queue behavior. Capacity remains a
qualification outcome, not an assumption of this specification.

## User Stories

1. As an owner of the existing logger, I want a polling-only profile with two
   full-rate IMUs and two 500 Hz ADC channels, so that useful mixed acquisition
   does not require a logger hardware revision or an IRQ connection.
2. As an owner with the optional IRQ connection, I want a four-IMU mixed profile,
   so that additional readiness information can improve useful acquisition.
3. As an operator, I want four-IMU polling evaluated too, so that a successful
   firmware-only result is not artificially restricted to the IRQ profile.
4. As an operator, I want requested native IMU rates preserved, so that a passing
   result does not conceal silent rate reductions.
5. As an operator, I want only supported workload/profile combinations admitted,
   so that requested settings have a defensible capacity basis.
6. As an analyst, I want delivery assessed independently for every expected IMU,
   so that totals cannot hide a missing or poorly served participant.
7. As an analyst, I want missing counts, gap duration and gap frequency reported,
   so that an average delivery percentage cannot hide long interruptions.
8. As an operator, I want bounded acquisition-to-RAM latency and recovery,
   so that adequate average throughput does not conceal growing backlog.
9. As an analyst, I want each ADC channel's fresh conversions distinguished from
   cached repeats, so that a 500 Hz row rate does not imply 500 fresh readings/s.
10. As an analyst, I want ADC age and affected channels identified, so that one
    stale channel does not invalidate another channel's useful reading.
11. As an operator, I want the master to prepare useful data without a request
    for every fragment, so that SPI exchanges spend more time moving readings.
12. As an operator, I want one ordinary sample unit to fit one physical transfer,
    so that incomplete larger objects do not pin the main sample path.
13. As an operator, I want bounded outstanding units and selective repair,
    so that a damaged unit does not block healthy sources.
14. As an analyst, I want retransmissions and duplicate acknowledgments handled
    safely, so that repair neither duplicates readings nor retires unrelated data.
15. As an analyst, I want restart-safe source and acquisition identity, so that
    a valid old packet cannot be mistaken for the current recording.
16. As an analyst, I want sequence wrap and unknown loss treated explicitly,
    so that tools never invent continuity or missing counts.
17. As an operator, I want bounded buffers and honest overflow behavior,
    so that overload cannot silently overwrite published history.
18. As an operator, I want STOP, authorization and acknowledgments serviced when
    sample queues are full, so that overload cannot prevent safe control.
19. As an operator, I want prompt acquisition cessation followed by bounded drain,
    so that pressing STOP preserves available tail data without indefinite waits.
20. As an analyst, I want source final boundaries and incomplete tails reported,
    so that closing a file is not mistaken for complete source delivery.
21. As an operator, I want isolated stream faults contained, so that healthy
    independent sensors continue without automatic rejoining of a failed source.
22. As an operator, I want nodes to stop after authorization expires,
    so that an absent logger cannot leave abandoned acquisition running forever.
23. As an operator, I want a lost optional timing observation distinguished from
    expired acquisition authority, so that useful acquisition is not excluded
    merely because a timing message was missed.
24. As an analyst, I want healthy recordings to support native sample timing,
    so that high delivery alone is not called successful acquisition.
25. As an analyst, I want timing observations preserved for offline reconstruction,
    so that timing models can improve without changing recorded sensor values.
26. As an analyst, I want estimated, unknown and cross-sensor timing quality
    distinguished, so that unavailable precision is never implied.
27. As an analyst, I want trustworthy readings accessible when timing degrades,
    so that useful values survive even when a timing-dependent analysis cannot run.
28. As an operator, I want optional diagnostics shed before readings,
    so that metadata traffic does not dominate useful acquisition under pressure.
29. As an analyst, I want essential stream definitions retained independently,
    so that compact references do not make sample identity or configuration ambiguous.
30. As an operator, I want damaged SPI transfers rejected before acknowledgment,
    so that live retry remains possible while the master retains the unit.
31. As an analyst, I want master-origin integrity evidence checked after recording,
    so that damage in intermediate buffering or copying remains detectable.
32. As an analyst, I want unverified blocks distinguished from verified readings,
    so that postponed validation does not overstate data integrity.
33. As an operator, I want acknowledgment semantics stated plainly,
    so that RAM acceptance is not confused with durable SD storage.
34. As an owner of historical BDQ recordings, I want them to remain readable,
    so that a coordinated upgrade does not invalidate existing data.
35. As an analyst, I want the new compact recording schema and decoder delivered
    together, so that transport gains produce immediately usable recordings.
36. As an operator, I want incompatible master/logger firmware rejected explicitly,
    so that a mismatch does not silently start a different wire protocol.
37. As an operator, I want missing, stuck or missed IRQ indications handled,
    so that optional readiness signaling is not a single point of failure.
38. As an operator, I want control exchanges possible without a data-ready signal,
    so that an idle or blocked sample source does not obstruct STOP or inspection.
39. As a developer, I want existing CAN nodes preserved initially,
    so that the first useful result does not require simultaneous node redesign.
40. As a developer, I want early real recordings through the production path,
    so that synthetic or host-only gains do not conceal integration costs.
41. As a developer, I want independently expected values and fault outcomes,
    so that tests can catch defects shared by the encoder and decoder.
42. As a developer, I want automated, reproducible run assessment with exact
    firmware and configuration identity, so that fewer manual bench cycles are needed.
43. As a developer, I want stage-specific service and memory budgets,
    so that backlog recovery and ADC compatibility are demonstrated rather than guessed.
44. As a project owner, I want a material capacity shortfall reviewed before
    implementation expands, so that effort follows measured bottlenecks.
45. As a hardware designer, I want remaining limits quantified on existing hardware,
    so that a future revision addresses measured constraints rather than conjecture.

## Implementation Decisions

### 1. Scope, compatibility and governing contracts

- Implement the master/logger transport, necessary recording/analysis changes and
  qualification tooling. Keep existing CAN link/profile and node sample encoding
  for the first slice. Do not make a node firmware redesign a prerequisite.
- Require matched new master/logger firmware with an explicit version/profile
  compatibility check before acquisition. Do not automatically fall back to the
  old measurement wire protocol on mismatch.
- Existing logger hardware remains the polling target. Optional IRQ support is
  additional; future logger revisions and master-local ADC acquisition are not
  prerequisites. The user reports an available IRQ connection; verify its actual
  pins, resource allocation and wiring before use.
- Explicitly version new wire and recorded payload representations. Preserve
  historical BDQ readability and established sensor interpretation contracts.
  Retain the existing BDQ container unless a separately justified change is needed;
  no container-wide replacement is selected here.
- This specification refines the earlier acquisition and drain redesigns: it
  reopens the single selected batch, reception-wrapper representation, ordinary
  fragmentation and old fixed transaction envelope, and accepts occasional
  explicitly reported ADC freshness loss. Preserve unaffected authority,
  source-association, cleanup and integrity requirements.

### 2. Workload and quality acceptance

| Area | Accepted provisional engineering target |
|---|---|
| Minimum useful polling profile | Two native-rate IMUs plus two local ADC channels at 500 Hz, one active channel on each ADC |
| Optional-IRQ target | Four native-rate IMUs plus the same ADC workload; also evaluate four-IMU polling |
| Native IMU rate | Approximately 3,333 associated six-axis readings/s per source; no silent reduction |
| Ordinary IMU quality | At least 99.9% usable delivery per expected node over a ten-minute qualification window; no individual ordinary sample gap longer than 20 ms |
| Ordinary ADC quality | At least 99.5% fresh readings per channel over ten minutes; no ordinary interval without a fresh reading longer than 10 ms |
| Normal latency | Provisional acquisition-to-logger-RAM target of at most 100 ms, requiring a feasible service/buffering budget |
| Recovery latency | Provisional 500 ms ceiling for recovery budgeting, requiring stage-specific feasibility; not a universal lossless-stall promise |
| Timing | Healthy qualification supports unambiguous native sample timing; assess timing reconstruction separately from delivery |
| Operator STOP | Target source acquisition cessation within 300 ms under admitted workloads, then up to five seconds of buffered drain after cessation |

- Assess each source and ADC channel independently. Use source boundaries and
  sequence evidence for delivery denominators; do not substitute nominal rate
  times elapsed wall time when authoritative scope is missing. Unknown counts or
  bounds remain unknown and cannot yield a false pass.
- Report received, verified, rejected, duplicate, missing and unresolved readings,
  gap frequency, largest gap and measurement scope. Offline rejection counts
  against delivery. Deduplicated valid retransmissions do not count as new loss.
- Cached ADC repeats are not fresh readings. Equal numeric values may be distinct
  conversions. Persist sufficient per-channel conversion association, freshness
  and age information for assessment; a row timestamp alone is insufficient.
- Timing degradation does not automatically invalidate trustworthy values. A
  healthy timing qualification must demonstrate native reconstruction supported
  by observations; a delivery pass alone is not an acquisition qualification.
- Keep normal-load qualification separate from identified fault trials without
  hiding fault losses. Routine overload must not be relabelled a fault to pass.
- Preserve existing capacity gates unless separately changed: at most 70% CAN
  and 85% steady shared-SPI scheduling occupancy, plus demonstrated useful sample
  drain of at least 1.25 times admitted ingress with mandatory concurrent traffic
  active. Include actual qualified software, arbitration, rearm and auxiliary
  costs; do not infer these gates from the new delivery percentages alone.
- These are engineering profile gates, not a final general sensor admissions
  policy. Unsupported configurations must not silently reduce requested rates.
- Retain inherited backlog-coverage targets of 50 ms at the node, 100 ms at the
  master and one second of logger remote buffering unless explicitly revised.
  Recalculate their actual storage costs for the new representation and stage
  placement; they are distinct from the provisional recovery-latency target.

### 3. Transport publication and physical profiles

- The logger supplies SPI clocks and initiates controls. The master selects and
  prepares useful next data without an explicit node/object/fragment request
  before every sample reply. Every reply identifies its own contents; pipelined
  replies must not be assumed to answer the current request.
- Fit each normal sample unit into one physical transfer. It must be independently
  identifiable, bounded and checkable. Larger configuration messages may use
  multi-transfer assembly outside the ordinary sample path.
- Initially compare 256- and 512-byte physical profiles. Retain 256 as a supported
  new-protocol option. Defer 1,024-byte transfers unless a revised budget shows need.
- Evaluate the existing requested 16 MHz candidate; inherited lower-clock fallback
  options remain subject to their own workload qualification. Select the profile
  before acquisition and keep clock, framing and turnaround requirements fixed
  throughout that recording. Live errors use bounded recovery, not silent profile
  switching. A smaller/slower profile is not automatically qualified.
- Nominal 16 MHz clock-only durations are 128/256 microseconds for 256/512 bytes.
  They are not bus-ownership or service guarantees. Measure physical exchange,
  HAL, arbitration, preparation, first-byte, CS retirement and rearm behavior.
- Preserve the demonstrated first-byte priming and safe CS/buffer-ownership
  principles. DMA completion alone does not authorize reusing or modifying a
  physically active transmit buffer. Distinguish prepared, published, physically
  retired, accepted and acknowledged states.

### 4. Identity, sample units and compact encoding

- Establish full stream definitions before interpreting compact references.
  Bind source, acquisition instance, configuration and source continuity to the
  current master/logger ownership scope, and retain definitions with the recording.
- Every sample unit must unambiguously establish its scoped identity, source
  sequence positions and payload interpretation. Do not rely on a valid CRC,
  queue position or a short identifier alone as freshness/ownership evidence.
- Define identifier exhaustion, wrap, reset and stale-reference behavior explicitly.
  Never reuse a live identity for different immutable content. Old valid replies
  and acknowledgments must not alias current data after reset or reuse.
- Prefer grouping existing compact CAN sample payloads without their repeated
  gateway reception wrappers. Further axis repacking is allowed only when its
  measured service/resource benefit justifies extra processing and complexity.
- Preserve exact axis values, source sequence, configuration, explicit gaps and
  necessary timing relationships. Byte-exact forwarding of every reception is not
  required for ordinary acquisition; keep diagnostic capture a separate concern.
- Define partial-unit flushing so low-rate or tail data cannot wait indefinitely
  for a full unit. Unit collection time is not acquisition-to-RAM latency.
- Illustrative counts such as 15/35 readings per 256/512-byte transfer are budget
  examples, not layouts. Identity, checksums, acknowledgments, padding and partial
  units must fit the final geometry; recalculate packing when they change.

### 5. Bounded windows, credits and selective recovery

- Use bounded windows of immutable published units rather than one pinned batch
  per node. Size windows from demonstrated useful progress and memory placement;
  larger buffers alone are not evidence of throughput.
- Keep credits, retained ownership and acknowledgments explicit and bounded.
  Accept a unit only when the logger has safe bounded RAM custody. Repeated
  delivery and acknowledgment are idempotent; a stale or conflicting ACK must
  never retire another unit.
- Retry missing or damaged units selectively while allowing healthy units and
  sources to progress. Bound repair service and abandonment; a failed unit becomes
  an explicit accounted-for gap, not indefinite global blocking.
- Define retirement confirmation and replay handling sufficiently to survive lost
  requests/replies without duplicate visible readings or reuse of still-owned
  storage. Do not implement ACK ownership by a mutable frame checksum alone.
- ACK means validated transport custody in logger RAM. It does not promise SD
  durability or completed offline semantic/upstream-integrity verification. A
  logger crash may lose accepted but unwritten data under this accepted contract.

### 6. Scheduling, backpressure and IRQ

- Give samples, routine timing evidence and essential control independent progress.
  Reserve bounded memory and service for STOP, authorization renewal, ACK and
  essential state when ordinary sample buffers are full or data credits are zero.
- Prioritize by actual deadlines, preserving bounded sample/ADC service rather
  than treating every pending control exchange as urgent. A physical transfer
  already in progress finishes before another transaction takes the shared bus.
- Shed diagnostics first, then optional alignment/timing detail. Protect essential
  definitions and observations required for agreed native timing quality. Loss
  of an optional observation grants no authority and need not end a useful stream.
- If finite storage still overflows, preserve queued/published history and drop
  newly arriving complete data units with explicit loss accounting. Do not silently
  overwrite unacknowledged data or expire useful readings merely because they are late.
- Optional IRQ is level/latched, indicating actually publishable new data or an
  explicitly requested retry. It is a scheduling guide, not authority or validation.
  Specify deassert/reassert behavior so retained old data does not cause an
  unbounded replay loop and new data cannot be lost through a missed edge.
- Permit control traffic without data-ready. Retain bounded polling/watchdog
  service for absent/stuck IRQ and polling-only hardware. Neither IRQ nor an
  availability hint excuses unsafe first-byte/publication behavior.

### 7. Integrity and offline verification

- Before RAM acceptance, validate physical-transfer CRC, length/bounds, routing
  identity, context and ACK safety. Invalid input must not mutate authority or
  retire data. Preserve the live retransmission opportunity for detected damage.
- Compute a master-origin checksum once over each immutable sample unit's canonical
  identity and content. Retain that checkable representation through recording
  for offline verification, alongside the live physical-transfer CRC.
- Keep storage integrity checks for their later boundary. A fresh logger-generated
  file checksum cannot expose a change that happened before it was calculated.
  New serialization or compression must preserve the ability to verify the
  upstream canonical unit; byte changes must not silently discard this guarantee.
- Define checksum coverage, byte order, padding, metadata dependencies and test
  vectors explicitly. Mutable ACK/control fields in a physical frame may vary
  while the published sample unit remains immutable.
- Preserve unverified sample blocks as such. Publish verified readings only after
  their required integrity, identity and association checks pass. Offline failures
  are reported as rejection/loss, not silently removed from the denominator.
- Checksums address accidental corruption, not malicious substitution or every
  software semantic error. Do not infer independent multiplicative reliability
  from layered CRCs. Exact algorithms/widths are specification work, not a
  pre-approved removal of either accepted integrity boundary.

### 8. Recording, timing and analysis interfaces

- Add explicitly versioned compact stream payload schemas and matching analysis
  dispatch. Preserve historical schemas and recording readability; unknown new
  schemas must fail explicitly rather than be misinterpreted as old records.
- Persist enough source/configuration/sequence definition with readings for safe
  interpretation. Timing companions may follow sample data, with relationships
  resolved offline; missing companions must not invent a definition or timestamp.
- Keep native sample timing, cross-sensor alignment, acquisition latency, RAM
  custody and SD persistence distinct. Packet observation time is not sensor
  acquisition time. Modeled/interpolated times must be labelled and supported by
  preserved observations; sparse anchors do not establish every actual sample time.
- Preserve useful clock observations and select their cadence using reconstruction
  quality and service measurements. High-frequency phase alignment between IMUs
  is separately qualified and is not implied by native reconstruction.
- Provide sequence-based access to trustworthy untimed readings. Operations needing
  unsupported timing must report the limitation, not silently assign nominal-rate
  times or omit the readings. Preserve uncertain extent across unknown-loss boundaries.
- Expose per-source decoded values, gaps, verification state and timing coverage
  to the existing assessment tools. Keep per-channel ADC freshness and age usable
  by the same run assessment. Do not mistake a successfully decoded file for
  proof of physical capacity.

### 9. Authority, faults and recording lifecycle

- Retain the initial five-second acquisition authorization horizon and normal
  once-per-second renewal, fresh challenge binding and explicit membership/fencing
  semantics, subject to the complete service budget. Sending or observing stale
  control traffic does not renew authority.
- A routine exchange timeout may be retried while confirmed authority remains
  valid. Expiry, explicit STOP, reset or untrustworthy identity/sample association
  ends the affected stream; do not automatically rejoin it within the recording.
- Keep healthy independent sensors running after an isolated source failure.
  Unusable shared infrastructure, including storage, may end the whole recording.
  Rejected ordinary corrupted transfers use bounded recovery; they do not by
  themselves imply that every source has lost identity.
- Protect prompt STOP, drain retained data and collect source final boundaries
  within the accepted deadlines. Missing confirmation or tail evidence remains
  explicitly uncertain/incomplete. File close alone is not proof of complete delivery.
- If STOP cannot be delivered, stop renewing and use authorization expiry as the
  fallback; do not promise the normal 300 ms cessation result. Bound cleanup,
  preserve safe old-data fencing and membership release before a new session,
  and do not claim success merely because a wait expired.

### 10. Resource budgets, instrumentation and delivery sequence

- Modify the master transport/service and hardware adapter, logger master-link
  manager/shared-SPI arbitration, acquisition coordinator, remote recording/queue
  modules, BDQ catalog/writer integration, offline reader/timing/assessment and
  existing bench evidence tooling as required by the agreed interfaces.
- Before freezing the new layouts, document complete frame geometry, window and
  credit invariants, retry/flush limits, essential metadata/control budgets and
  stage-specific backlog placement. Give all selected numeric parameters units,
  evidence and bounded failure behavior. Changes to agreed targets require an
  explicit decision; ordinary layout choices do not require another interview.
- Budget master bank placement, stack/runtime margin, active DMA copies, TX/RX
  queues, source ingress and control reserves, plus logger internal/PSRAM queues,
  primary rows, metadata and writer workspace. Static unused bytes alone are not
  runtime capacity proof. Avoid allocations and blocking storage work in fast paths.
- Keep optional byte-exact captures and verbose diagnostics outside normal-path
  performance qualification, and retain their cost when enabled in a test. Report
  monitoring overhead rather than assuming observations have no service cost.
- Four-source raw axes produce about 160 kB/s. A 500 ms backlog is about 80 kB
  before framing, exceeding the cited 62,280 unused bytes of master BANK1. Do not
  promise lossless 500 ms operation while SPI is blocked. A logger storage stall
  with SPI still draining uses different resources. Recovery needs excess service;
  buffering cannot cure sustained overload.
- Measure useful progress, repair/replay/empty transfers, physical bus ownership,
  wall service, queue depth/age, source ingress loss, ADC conversions/freshness,
  storage writes and control outcomes. Do not add overlapping timings as CPU
  utilization or substitute queue software age for physical acquisition latency.
- Preserve exact firmware/artifact, configuration, board/profile and run identity
  with raw evidence. Collect normal finalized counters without a racing recording
  or requiring manual expansion of opaque debugger arrays where tooling can export them.
- Deliver in order: (1) layouts/budgets and host fault checks; (2) one real IMU
  through transport, BDQ and independent decode; (3) two IMUs plus two 500 Hz ADC
  channels without IRQ; (4) four IMUs with polling then IRQ, comparing physical
  sizes where useful. Review a material measured shortfall before expanding scope.

## Testing Decisions

### Primary behavioral seam

Use the existing highest integration seam: known node/CAN input and recording
lifecycle commands through production master service, logger transport and
acquisition coordination, bounded RAM custody, BDQ writing and independent offline
decoding/assessment. Check externally visible readings, evidence, authority,
acknowledgments, gaps and finalization rather than mirroring queue internals.

Extend the existing node-to-master-to-BDQ and integrated recording fixtures;
they already compose production service/recording/writer logic and independent
analysis. Prefer substituting clocks, physical SPI delivery and filesystem I/O at
existing boundaries over adding a new transport framework. Preserve the known
limitation that existing host fixtures do not certify full physical STOP/tail
completion or device timing.

### Focused supporting checks

Use narrow tests only where the integration seam cannot efficiently establish an
invariant: independent codec/checksum vectors, wrap/identity bounds, publication/
CS hardware ordering, and data-preserving recording-schema dispatch. Existing
measurement transport, terminal-reserve, master-adapter/priming, lifecycle and
ADC-ready fixtures provide prior art. Existing BDQ, CAN timing and multi-IMU
assessment tests provide independent data-format and analysis prior art.

The old ACK-fetch differential fixture is useful regression precedent for an
unchanged component; byte-for-byte equivalence with the old protocol is not an
acceptance requirement for a deliberately versioned replacement.

### Required externally observable cases

| Case | Required evidence/outcome |
|---|---|
| Known one/two/four-source vectors | Exact signed axes, source/configuration association, sequence and expected gaps survive the complete writer/reader path |
| Corrupted/truncated/unsupported transfer | No invalid RAM acceptance, authority mutation or unrelated retirement; bounded repair where applicable |
| Valid CRC with stale/wrong identity | No acceptance as current data and no wrong unit retired |
| Lost data reply, lost ACK or lost retirement response | Bounded replay/recovery, no duplicate visible readings and no premature buffer reuse |
| Same identity with conflicting content | Explicit integrity failure and safe ownership; healthy independent sources remain protected |
| One delayed/bad unit among healthy sources | Selective recovery and bounded fairness/control progress; accounted gap after explicit abandonment |
| Zero credits/full queues | Essential STOP/renewal/ACK progress remains available; no silent overwrite of published data |
| Post-acceptance corruption with freshly valid storage CRC | Offline master-origin check rejects the affected unit; loss/verification state is explicit |
| Restart, exhaustion and wrap | No stale identity aliasing, fabricated sequence or unauthorized same-recording rejoin |
| Missing optional observations/definitions | Values retained only with honest interpretation/verification status; no invented native timing or authority |
| Native timing vectors | Reconstruction matches independently known sequence/clock observations; unknown-loss intervals and cross-sensor uncertainty stay explicit |
| ADC cached repeat/equal fresh values | Freshness follows conversion association, with per-channel age and independent channel validity |
| IRQ absent/stuck/missed/held for old data | Bounded fallback/control service; no work lost through edge dependence or unbounded replay loop |
| Partial/aborted physical transfer and CS retirement | No active-buffer mutation, prefix loss, unsafe rearm or stale publish accepted as fresh |
| STOP, cancellation, expiry and isolated reset | Correct terminal membership, bounded drain, honest source-tail result, safe restart and fault containment |
| Historical and new recordings, torn tails and malformed schema | Historical interpretation preserved; new verification state explicit; readable prefix does not imply complete acquisition |

### Physical qualification and automated assessment

- Build both target firmware images using the existing board-specific workflow.
  Compile/host passes establish integration behavior, not electrical/timing capacity.
- Run the accepted staged real-load sequence on identified hardware and the current
  high-endurance SD card. Each profile report includes actual duration, expected
  participant membership, source boundaries, per-node usable delivery/gaps, per-channel
  ADC freshness/age, timing reconstruction, latency evidence/limitations, queue and
  ingress behavior, control/STOP cleanup and inherited capacity-margin results.
- Assess ordinary ten-minute IMU and ADC targets automatically from authoritative
  scope and conversion identity. Reject incomplete denominators/participants as
  unresolved rather than passing from aggregate counters or surviving data alone.
- Exercise both supported frame sizes for compatibility and useful mixed-load
  profiles for capacity. Requested clock and uninterrupted wire arithmetic do not
  prove actual SCK timing, first-byte correctness or ADC compatibility.
- Preserve raw data and machine-readable assessment, exact artifacts/configuration
  and reproducible commands. Distinguish host synthetic, physical synthetic and
  real sensor evidence; they are not interchangeable capacity qualifications.
- Do not restart a lengthy standalone synthetic optimization campaign before the
  complete real recording path. Controlled on-device storage-stall qualification
  remains deferred; bounded host storage-failure checks remain appropriate.

## Out of Scope

- A final general admissions-policy formula or empirical sweep of all sensor
  combinations. This work produces qualified profiles and evidence for that policy.
- Silent sensor rate reduction, automatic failed-source rejoining, overwriting
  unacknowledged history, or claiming ACK means durable SD persistence.
- Node/CAN payload redesign, a separate CAN-FD-only network profile, new IMU
  acquisition hardware, or ADC acquisition/connector additions on the master in
  the first slice. These remain possible later decisions if evidence justifies them.
- Requiring a second logger SPI bus, local-sensor buffering hardware or a logger
  revision before producing the existing-hardware result.
- Automatic compatibility with every old master/logger firmware combination or
  a dual old/new measurement wire implementation. Historical BDQ compatibility
  and existing node support remain required.
- Initial 1,024-byte physical transfers, arbitrary larger logical sample objects,
  or fragment reassembly on the normal sample path without reopening the design.
- A high-frequency inter-IMU phase guarantee, an unverified 10 microsecond alignment
  claim, invented nominal-rate timestamps, or claims of exact acquisition times
  from sparse observations.
- Malicious-device authentication or cryptographic guarantees.
- Controlled physical storage-stall tests, qualification of every SD-card model,
  and universal lossless behavior under arbitrary faults/stalls.
- Remote issue cleanup, closing earlier work, bulk tracker changes or device
  flashing as part of drafting this specification.

## Further Notes

- The user confirmed shared understanding after accepting Q1-Q27 on 13 November
  2026. This is the synthesis of that agreement, not a new design interview.
- Working code baseline: `1ebd9b28f0f46bb8a578197ed96870b458467ed7`. The r23
  hardware observations and r24 bounded host counterfactual are motivation, not
  implemented new-protocol performance. The recently changed high-endurance card
  prevents treating every difference from earlier runs as a protocol-only effect.
- ADR0001-ADR0004 and the earlier acquisition/drain/SPI revision contracts provide
  the preserved boundaries; ADR0005 records the accepted new transport and
  verification trade-offs. Changes named in this specification take precedence
  for the new protocol; unaffected control and sample-integrity guarantees remain.
- This refines the transport/recording direction in
  [the earlier confirmed acquisition specification, #164](https://github.com/benconnor1972/BODAQS/issues/164).
  It does not close, rewrite or automatically declare completion of earlier issues.
- The primary test seam implements the end-to-end validation already accepted in
  Q27. Its concrete composition is presented with this specification for review;
  no new lower-level production seam is required solely for testing convenience.
- Exact wire fields, checksum encodings, sequence/reference scopes, window and
  credit sizes, retry/flush limits, scheduling, timing cadence, IRQ pin/polarity
  and memory placement must be documented and budgeted before the first candidate
  freezes those interfaces. They are engineering work within this agreed contract,
  not permission to weaken its targets or claim feasibility without measurement.
- Proposed tracker title: **Redesign master/logger transport for mixed IMU and ADC acquisition**.
  Proposed creation labels: **enhancement**, **ready-for-agent**. The latter
  denotes specified agent work, not proven capacity or completed hardware qualification.
