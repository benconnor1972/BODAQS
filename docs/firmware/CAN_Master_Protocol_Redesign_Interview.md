# CAN-master protocol redesign: interview decisions

13 November2026. The user accepted Q1-Q27 and confirmed shared understanding of
the consolidated [design proposal](CAN_Master_Protocol_Redesign_Proposal.md),
then invoked to-spec. The interview is closed; this record is not firmware
qualification. Working baseline1ebd9b28f0f46bb8a578197ed96870b458467ed7.
The [specification](../specs/can-master-logger-protocol-redesign.md) synthesizes
the agreement. Byte layouts and measured capacity are not settled by this record.

## Accepted first-round decisions (all provisional engineering targets)

| ID | Accepted recommendation | Limits |
|---|---|---|
| Q1 | Minimum useful polling-only design target: two full-rate IMUs plus two ADC channels at500Hz. With IRQ available, target four full-rate IMUs plus those ADCs. | Four-IMU polling remains an opportunity, not an artificial restriction. Neither tier is a demonstrated capability. User reports an available interrupt connection; exact wiring/resources are to be checked when specifying it. |
| Q2 | Permit an explicitly versioned new BDQ stream representation when justified by material processing/storage/metadata savings. | Preserve readability of existing recordings; update analysis with new schemas. Preserve auditability of identity, gaps and timing. No gratuitous format change. |
| Q3 | Retain100ms acquisition-to-logger-RAM acceptance as a provisional normal target; use500ms as a provisional recovery ceiling for budgeting. | Validate feasible buffers and service; do not automatically invalidate otherwise trustworthy readings. Acquisition timing, RAM acceptance, persistence and STOP deadlines remain distinct. |
| Q4 | Initial ordinary-load IMU qualification target: at least99.9% delivery per node over10minutes, with no individual gap longer than20ms. | Product proposal accepted provisionally, not established performance or final admissions policy. Report percentage, longest gap and frequency separately. Fault/stall trials remain separately identified without hiding losses. ADC freshness/reuse limits are settled later in Q12. |

## Carried-forward boundaries

- Native IMU design rate remains approximately3333six-axis readings/s per node;
  no silent rate reduction. Polling compatibility refers to existing hardware,
  with coordinated firmware updates and explicit protocol versions permitted.
- Existing target for ordinary operator STOP is acquisition cessation within300ms
  under admitted workloads, followed by buffered drain. Existing accepted drain
  allowance is up to5seconds after cessation; control-confirmation observation
  is not automatically an exact cessation timestamp.
- Historical BDQ files remain readable. Source identity, sample association,
  explicit gaps, timing limitations and integrity remain required while their
  implementation/cost is being examined. Q5 below preserves those protections
  while permitting justified implementation changes.
- The first implementation slice should exercise the production-shaped path
  early. Host models, physical synthetic traffic and real recordings are different
  evidence classes; none silently qualifies the others.
- Controlled storage-stall testing remains deferred. New high-endurance card is
  the current test baseline, not a proven universal storage guarantee.

## Current evidence informing the design

Four-node r23:5539.52readings/s in first100seconds;56.27%source-bounded missing
readings; no primary loss; all four final boundaries; accepted IMU records saved.
Source backlog-age/fragment-preparation measurements are software observations,
not physical acquisition latency or pure CPU utilization. r24 host counterfactual
does not establish a10% live gain from backlog batching alone; it remains research
evidence, not installed firmware. See the owned reports under
`C:/Users/benco/dev/BODAQS-worktrees/drain-capacity-evidence/first-real-imu-implementation/`:
`imu-batch-investigation-r23-01-261113_145726-report/ASSESSMENT.md` and
`batch-backlog-host-r24/ASSESSMENT.md`.

## Q5 accepted: integrity requirements and implementation freedom

Retain strong accidental-corruption detection, unambiguous source/session ownership
and safe acknowledgment. Permit checksum layers and identity encoding to change
when their coverage and failure behavior are explicitly justified and tested.
Today's exact fields, duplicate checks and two-checksum arrangement are not fixed
requirements. No particular removal, checksum width or new layout is selected.

Current code has per-SPI-frame CRC32 over header/body/retirement fields and a
logical-object checksum binding scope, object, source/class/direction, size and
content. Frame corruption checks and identity checks address different faults:
an old/wrong-source packet can have a perfectly valid CRC. ACK ownership must
refer to the exact batch allowed to be retired. Acceptance into RAM is not an
SD durability guarantee. CRCs detect accidental corruption, not every software
semantic error or malicious substitution.

Implementation freedom worth considering: amortize stable identity over an
explicitly bound session/stream, use compact per-transfer identities that cannot
alias while live, checksum immutable content once and reuse it, and reconsider
overlapping integrity layers only after defining and testing their coverage.
Q5 permits evaluating these candidates; it does not approve particular removals
or select layouts. ACK remains validated logger-RAM acceptance, not durable SD
persistence, under the previously accepted contract. This distinction is retained.

## Accepted second-round directions: Q6-Q9

- **Q6:** Cover accidental corrupted transfers, delayed/duplicate replies, resets,
  stale acknowledgments and bounded overload. Malicious-device authentication is
  outside this redesign. User qualification: failures may be handled in post
  processing when that is more efficient. No particular live check has yet been
  approved for removal; safe ownership/control versus deferred interpretation
  must be distinguished, including any lost retransmission opportunity.
- **Q7:** Permit a bounded window of immutable batches rather than requiring one
  selected batch per node. Require demonstrated service benefit, a deliberate
  memory/placement budget, bounded backpressure and exact ACK ownership. Window
  size and recovery protocol remain open; ACK is RAM acceptance, not SD durability.
- **Q8:** Samples, routine timing evidence and urgent control should make progress
  independently, preserving essential interpretation dependencies, ordering and
  protected STOP/authorization deadlines. The user strongly agrees and permits
  liberal metadata dropping in principle, but asks to challenge which metadata
  and control are actually necessary. Drop/coalescing rules and resulting analysis
  quality remain unresolved; do not infer permission to discard essential identity.
- **Q9:** Permit sensor-oriented compact blocks with shared identity/timing instead
  of preserving every original CAN reception wrapper. Retain readings, source
  sequence positions, configuration, necessary timing observations and explicit
  losses. Byte-exact CAN capture can be a separate diagnostic capability. Extra
  repacking/decoding must demonstrate a worthwhile resource/service benefit.

## Facts clarifying the user's Q6/Q8 qualifications

Current authority settings are5000msleases,1000msnormal renewal attempts and
300mschallenge validity. Renewal is necessary live service even though traffic
volume is small. Ordinary snapshots/status grant no authority; optional snapshots
are currently requested once per2seconds globally and rotate among participants.
These implementation timings are facts, not immutable redesign selections.

START/STOP/fence/retirement govern acquisition scope and reusable resources;
postprocessing cannot substitute for them. Offline fitting of clocks, gap/duplicate
reconciliation and interpretation checks can be cheaper than online decisions.
Moving a check that currently enables retransmission offline forfeits that
opportunity; acceptable loss/verification-state semantics need explicit treatment.

Existing representation/acceptance code depends on some essential model/anchor
metadata. Liberal dropping is not just a scheduler tweak: the new block format
must preserve identity/sequence/configuration dependencies independently, or
record affected blocks as unverified/uninterpretable. Timing quality and control
authority must remain distinct. A missing optional observation must not be allowed
to renew authority, invent sample timing, or silently attach the wrong definition.
Metadata classes, quality priorities and deferred-check rules remain to be settled.

## Accepted third-round refinements: Q10-Q11

- **Q10:** Shed diagnostics first, then optional alignment/timing detail under
  pressure. Protect essential interpretation information and the observations
  required for the agreed analytical quality. Preserve useful readings with
  explicitly degraded timing rather than excluding a participant for every lost
  metadata message. The minimum timing quality/budget still needs definition.
- **Q11:** Permit offline checks even when a defect discovered after retirement
  can only cause rejection rather than retransmission. The defect must remain
  detectable; ownership/control must remain safe; resulting missing readings count
  against the agreed loss budget. Stored-but-unverified blocks are distinct from
  verified readings. No particular checksum has yet been selected for deferral.

## Accepted fourth-round quality and overload choices: Q12-Q14

- **Q12:** Initial two-channel 500 Hz ADC profile: provisionally at least 99.5%
  fresh readings per channel over ten minutes, with no ordinary interval without
  a fresh reading longer than 10 ms. Mark affected channels explicitly; preserve
  other channels' valid readings. Cached repeats do not count as fresh readings.
  This accepted occasional-gap target updates the strict fresh-every-row target
  for this redesign; it is not measured qualification or a final admissions rule.
- **Q13:** First throughput-qualified profile need not promise high-frequency
  vibration-phase accuracy between IMUs. Healthy acquisition should support native
  timing reconstruction; preserve useful clock observations and qualify inter-IMU
  alignment separately. The existing local 500 Hz sensor alignment tolerance of
  about 2-4 ms is not a numerical inter-IMU phase/timing guarantee.
- **Q14:** After optional metadata shedding, preserve already-queued history and
  drop newly arriving complete data units under unavoidable finite-buffer overflow.
  Record explicit gaps; never silently overwrite published unacknowledged data.
  Delivery-latency targets are qualification criteria, not an automatic reason to
  declare a trustworthy older reading invalid. Sustained deficits still fail
  capacity qualification and must not be excused by gap reporting.

## Accepted fifth-round transport directions: Q15-Q18

- **Q15:** Let the CAN master select and prepare available useful data without
  requiring the logger to request each node/object/fragment before every reply.
  The logger still supplies SPI clocks and directs control operations. Replies
  identify their contents; bounded credits and acknowledgments preserve fairness,
  ownership and backpressure. This does not authorize unsolicited SPI clocks.
- **Q16:** Compare 256-byte and 512-byte physical transfers, retaining 256 bytes
  as a supported fallback. At the requested 16 MHz, their nominal clock-only floors
  are 128 and 256 microseconds. Qualify real ADC freshness and control deadlines;
  larger transfers also hold the shared bus longer. Defer 1024-byte transfers
  unless a revised budget establishes a need. No frame size is yet qualified.
- **Q17:** Use an optional level or latched ready indication for new data or an
  explicitly requested retry that is ready for transfer, rather than relying on
  catching a pulse. Readiness guides scheduling; it grants no authority and
  replaces no packet validation. Control can proceed without data readiness.
  Retain bounded polling/watchdog behavior for absent or stuck IRQ. Physical
  publication readiness and actual wiring must be verified in implementation.
- **Q18:** Keep the existing CAN profile and node sample format for the first
  implementation slice. Change the master/logger path and necessary recording
  and analysis support first. Grouping existing compact CAN payloads is a possible
  low-repacking representation; revisit node/CAN changes only when justified by
  the budget or measurements. No new node-side work is selected by this decision.

## Accepted sixth-round recovery choices: Q19-Q21

- **Q19:** Prefer normal sample units that each fit in one physical SPI transfer
  and are independently identifiable and checkable. Remove fragment reassembly
  from the ordinary sample path, subject to the capacity budget. Larger
  configuration messages may still require multiple transfers. The illustrative
  35-reading, roughly 10.5 ms unit at 512 bytes is not a selected header layout.
- **Q20:** Use bounded selective recovery: retry damaged or missing units while
  allowing other units and sources to progress. Bound retries; an unrecoverable
  unit becomes an explicit, accounted-for gap rather than indefinitely blocking
  healthy sources. Any abandonment must be explicit. This does not authorize
  silently overwriting published units or disguising sustained overload.
- **Q21:** Reserve bounded memory and service for essential control even when
  ordinary sample buffers are full. Protect STOP, authorization renewal,
  acknowledgments and essential state reporting; optional diagnostics remain
  expendable. An already-running physical transfer completes before urgent
  control uses the shared bus. Exact reserves and scheduling remain to be sized.

## Accepted seventh-round verification and compatibility choices: Q22-Q24

- **Q22:** Check each physical transfer's CRC, length, identity and acknowledgment
  safety before RAM acceptance. Defer heavier interpretation, including clock
  fitting and deeper sample analysis, where sufficient evidence is retained.
  Preserve the live retry opportunity for detected transfer damage. This does
  not yet select integrity coverage at later memory/recording boundaries.
- **Q23:** Establish full stream identity explicitly, then use compact scoped
  references in subsequent units. Every unit must still unambiguously identify
  source, acquisition instance and sequence position. Prevent stale-reference
  aliasing after restart or wrap; retain stream definitions in the recording.
  Exact field widths, negotiation and definition dependencies remain to be sized.
- **Q24:** Require a compatible new master/logger firmware pair initially, with
  an explicit incompatibility error rather than automatic fallback to the old
  wire protocol. Existing logger hardware remains a target, existing CAN node
  support is retained, and historical recordings remain readable. The new
  protocol still compares 256/512-byte profiles; this decision does not promise
  that either profile is already qualified.

## Accepted eighth-round integrity, timing and validation choices: Q25-Q27

- **Q25:** Retain a master-origin checksum of each immutable sample unit through
  recording for offline verification, in addition to live physical-transfer CRC.
  Calculate it once per unit. Include its bytes, processing and recording support
  in the budget; it can expose damage during later buffering/copying before a
  logger-generated storage checksum. Exact canonical coverage and encoding need
  specification; this is not protection against all semantic software faults.
- **Q26:** Report delivery and timing reconstruction separately. Healthy
  qualification must support unambiguous native sample timing; high delivery
  alone is insufficient. Preserve useful readings with explicitly degraded
  timing. Accurate phase alignment between IMUs remains separately qualified.
- **Q27:** Implement and validate in order: host identity/corruption/retry/reset/
  overload checks; one real IMU through transport, recording and offline decoder;
  two IMUs plus two 500 Hz ADC channels without IRQ; four IMUs with polling then
  IRQ, comparing 256/512-byte transfers where useful. Automatically assess
  delivery, freshness, timing evidence, queues and STOP cleanup. Review a material
  capacity shortfall before expanding implementation. Controlled storage-stall
  testing remains deferred. This sequence does not authorize flashing during
  the design interview.

## Integrity facts informing the design

The current v2 physical CRC covers the first 252 bytes, including routing and ACK
fields; the logical checksum instead binds canonical object identity and complete
assembled content (`bodaqs_measurement.h:163-215`,
`bodaqs_fragment_transport.h:19-131`). Single-transfer sample units remove the
multi-fragment assembly boundary, but do not by themselves settle integrity at
later memory/recording boundaries. No checksum layer is removed by Q19.

BDQ v2 generates a fresh checksum of the stored chunk payload
(`BdqV2Writer.cpp:236-252`); it cannot detect corruption that occurred before that
checksum was computed. Deferring a master-origin integrity check therefore needs
the upstream checksum and its covered identity/content retained, or an equivalent
verifiable representation. Offline semantic checks need their own sufficient
evidence, not necessarily another checksum. Existing valid-CRC replies can still
be stale: binding includes master boot, logger control session, recording and
measurement context, with separately correlated freshness inspections. Compact
identity must preserve those distinctions rather than use CRC as freshness proof.

## Design tree: agreement and engineering work remaining

The [first analytical budget](CAN_Master_Protocol_Redesign_Budget.md) and
`Protocol_Redesign_Budget.py` now distinguish measured anchors from illustrative
compact encodings/frame geometries. They do not yet demonstrate full profile
feasibility. The accepted transport direction now permits master-prepared replies,
256/512-byte comparisons and optional ready IRQ while keeping node/CAN traffic
stable initially. Normal sample units should fit one physical transfer, with
bounded selective recovery and reserved control progress. Live transport
validation, compact session/source binding, matched firmware, offline upstream
integrity verification, native timing qualification and staged end-to-end
validation are also accepted. The user confirmed the consolidated understanding
and requested specification. The following are explicit specification/measurement
tasks, not
unstated product decisions or claims of demonstrated feasibility:

- Canonical upstream-checksum coverage, algorithm/encoding, recording preservation
  and corruption-injection coverage. Retain both accepted integrity boundaries;
  do not silently remove the master-origin check as redundant with storage CRC.
- Identity scopes, restarts/wrap and duplicate/ACK semantics; compact encoding
  depends on the accepted scope/lifetime guarantees.
- Exact representation of per-channel ADC freshness/age and deferred verification.
- Achievable service/resource budget, headroom and overload/burst envelope.
- Queue separation details, in-flight data ownership, publication/retirement,
  protected control deadlines and backpressure.
- Polling/optional IRQ details and actual physical connection. Matched new
  master/logger firmware is required initially; old-wire fallback is out of scope.
- Timing evidence required for useful analyses; cadence and failure handling.
- Recording layout and analysis implications if Q2's permission is exercised.
- Detailed milestone pass/fail instrumentation and budgets. The milestone order
  and shared understanding are confirmed; capacity still needs evidence.

No implementation, device flashing, remote publication or ticket changes are
implied by closing this interview. The current authorized task is specification;
tracker publication follows the repository's preview/write rules.
