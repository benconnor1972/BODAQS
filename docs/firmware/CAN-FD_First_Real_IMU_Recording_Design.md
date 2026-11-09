# First real IMU recording - design interview

Status: Q1-Q9 settled and shared understanding confirmed by the user on
9 November 2026. The user then invoked `to-tickets` to prepare the implementation
breakdown. This is a decision record, not yet a byte-level implementation
specification. Implementation and the approved ticket publication began after
the user confirmed the ticket preview. Historical bundles and production
admission remain unchanged.

Design worktree: `imu-first-recording-design`, branch
`design/imu-first-recording-step1`, based on integration revision
`f0418b9`. Round17 evidence/prototype revision is `e0b58bc`. The prototype and
integration are distinct sources; the former is not a production transport
upgrade that can simply be enabled.

## Existing direction carried forward

- Existing boards, wiring and shared SPI. User performs device uploads manually.
- Four nominal3.33kHz IMUs remain the eventual design goal; one node is the first
  qualification milestone. No automatic live sensor-rate reduction.
- Source identity, effective configuration, trustworthy association, explicit
  sequence/segment identity and integrity remain essential. Occasional CAN/ADC
  sample gaps may be acceptable under the user's latest direction if the retained
  data stays trustworthy; final admission/loss thresholds are deferred.
- Preserve the BDQ container and readability of existing recordings. New compact
  packet observations use an explicit new schema; an observation timestamp is not
  a sample acquisition timestamp. Retain raw timing evidence independently.
- Keep the proven no-gap ACK/fetch direction. ADC setup optimization, sustained
  capacity/storage qualification and general admission-policy development follow
  the first real recording; this milestone is not further throughput maximization.
- Historical test failures and original capacity no-go remain historical facts.
  A restricted integration candidate does not silently pass the four-node gate.

Governing direction: [ADR0002](../adr/0002-drain-capacity-redesign-boundaries.md),
[ADR0003](../adr/0003-record-observations-reconstruct-timing-offline.md),
[ADR0004](../adr/0004-reopen-spi-transaction-envelope.md),
[drain redesign](CAN-FD_Drain_Capacity_Redesign.md) and
[execution record](CAN-FD_Drain_Capacity_Execution.md).

## Settled interview decisions

The agreed outcome is a restricted real one-node acquisition candidate and an
approximately30second nominal3.33kHz recording, with ADCs/unrelated sensors off.
Real CAN readings travel through retained batch ACK/fetch, logger RAM, SD/BDQ and
independent offline decode. Output comprises sequence-addressable six-axis readings,
raw timing evidence and a validation report. Full timing reconstruction, broader
admission and four-node qualification remain later work. Isolated correctly
reported sample loss is a functional-success-with-warning outcome, not complete
delivery or a loss-free/admission pass.

### Q1 - restricted real integration milestone

User answered yes. Step1 produces a restricted one-node integration candidate
that records real IMU data through CAN, retained batch transfer/ACK-fetch, logger
RAM acceptance, SD/BDQ and independent offline decoding. General production
admission and four-node qualification remain later milestones. Reuse the real
acquisition and recording path; another synthetic-only probe does not fulfill
this outcome.

### Q2 - sequence-addressable first output

User answered yes. The first milestone can complete with correctly decoded
six-axis readings identified by full sample sequence, preserved raw timing
observations, and explicit marking of timing not yet reconstructed. Full native
timing reconstruction/quality qualification can follow using the saved evidence.
No nominal-rate or packet-observation timestamps are silently promoted to sample
acquisition time. Full sequence includes the essential source/recording/segment
scope; its exact representation remains design work.

### Q3 - include the revised authorization timings

User accepted the revised recommendation. Step1 includes a coordinated5second
acquisition lease and approximately1second renewal cadence, as a separately
reviewable/tested change before transport integration. Node-generated deadlines,
node expiry, logger duration validation, conservative confirmed local deadlines
and renewal scheduling must agree. The300ms challenge-freshness window is
separate and is not enlarged by this decision. Q6 subsequently included retrying
retryable failed renewals within remaining confirmed authority.

The original recommendation to retain old timings was scope isolation, not an
established high technical risk. Fresh inspection showed the numeric change is
bounded; the named header macros are currently unused, so changing only them
would not implement the decision. Routine healthy renewal attempts should fall
from roughly10to1per second per node; this is not a90%reduction in all controls.

### Q4 - first physical workload

User answered yes. First physical recording: one real IMU at nominal3.33kHz for
approximately30seconds, with ADCs and unrelated sensor streams disabled. This
exercises the native source rate and crosses a low16-bit sample-sequence wrap.
It is a controlled workload, not a general admission profile or sustained test.

### Q5 - decoded data plus validation report

User answered yes. Deliver both decoded readings and a machine-readable report
covering source/effective configuration identity, full sample sequences, observed
gaps and their known/unknown extents, retained timing observations, decoded record
counts and STOP/tail completion. Explicitly distinguish valid partial recording
from complete delivery and unreconstructed timing from established timing.

### Q6 - retry while confirmed authorization remains

User answered yes. A lost or delayed renewal response may trigger another bounded
attempt while the last confirmed lease remains valid. A single retryable protected
exchange failure must not independently exclude the participant. Sending a request
does not extend confirmed authority. STOP, actual expiry and identity faults remain
terminal; stale responses must not revive an ended recording or participant.
Exercise lost/late replies, expiry and STOP overtaking pending retries through
the existing production host fixtures. This is a tested state-machine change in
addition to Q3's coordinated numeric updates.

### Q7 - preserve initial timing evidence and close its tail

User answered yes. Preserve the existing periodic raw observations at approximately
100ms cadence for the first recording and add a final normal-STOP observation
pairing the last sample's sensor timestamp with its corresponding node capture
tick. Do not pair a cached sensor timestamp with an unrelated later STOP tick.
Retain source sequence and clock epoch association. Reduced evidence cadence and
full offline timing reconstruction remain later work. The initial cadence is
first-capture scaffolding, not a final qualified timing-evidence policy.

### Q8 - carry forward the tested physical profile

User answered yes. Use256-byte physical frames, requested16MHz clock and25us
inter-CS guard with boundary-only publication/no CS-high gap path. Keep logical
batches around1KiB. Real transport needs an explicitly versioned contract and
coordinated integration checks; the synthetic protocol is not silently reused as
a production recording contract. Larger logical batches and further throughput
tuning are outside step1. Distinguish requested clock from any measured actual SCK.

### Q9 - isolated accounted loss does not invalidate the milestone

User answered yes. An otherwise healthy30second recording with an isolated lost
five-sample CAN packet can complete the functional integration milestone with a
quality warning if the gap is correctly identified, all retained readings have
trustworthy identity/full sequence and normal STOP/tail handling completes.
Preserve/report the loss; do not label complete delivery, zero-loss operation or
general admission. Persistent queue growth, repeated overload, corruption or
ambiguous sample identity prevents claiming this functional outcome and needs
investigation. No general numeric occasional-loss threshold is selected here.

## Verified source facts affecting scope

- Canonical real transport still uses64-byte frames/40-byte fragment bodies and
  separate polling/ACK. Real batches contain up to13CAN receptions,1008logical
  bytes, backed by independently retained ingress and an immutable selected head.
- Round17 uses a separate compile-time bench engine with synthetic known bytes,
  case identities and benchmark BEGIN/STOP. Its256-byte/requested16MHz/ACK_FETCH
  results do not cover real acquisition authorization, CAN service or SD writing.
- Existing `RemoteImuStream` expands compact packets to28-byte `can_imu6.v1`
  samples only after finding an anchored/applicable firmware timing model.
  Evidence-dependent persistence also exists. Q2 requires changing this seam,
  rather than relabeling the existing schema or supplying invented timing.
- Existing node snapshots already contain raw sequence/clock observations, but
  the current node/logger still use firmware models. New model-independent
  recording/decoding is not implemented. Exact recording layout remains engineering
  work; Q7 settles preservation of the initial emission cadence. Current periodic
  raw snapshots carry full32-bit sample sequence,
  sensor/node clock epochs, sensor timestamp, node capture tick and capture/slot
  association. They are emitted with model/anchor records approximately every
  100ms or500samples, whichever occurs first. This cadence is first-capture
  scaffolding, not a qualified final timing-evidence policy.
- START emits a matched raw sensor/node snapshot; normal STOP emits a full-sequence
  boundary and node tick but no final matched sensor-timestamp snapshot. Adding
  a last-sample-associated raw observation would be a node change. Existing
  snapshots may be skipped under evidence-queue pressure; resulting gaps and any
  ambiguous low16 sequence association must remain explicit rather than guessed.
- Actual control code currently uses1second acquisition leases, approximately
  100ms renewals and300ms challenge validity. Q3 now puts the coordinated5second/
  1second numeric change into step1; Q6 also includes the confirmed-authority
  retry behavior. Source behavior has not yet changed.
- Existing storage/catalog/writer and Python readers are reusable. The public
  host seam `firmware/tools/test_node_master_bdq_runtime.py` already exercises
  node capture through real master/remote stream/writer and independent reader.

## Engineering obligations for the implementation specification

Current code immediately excludes on a protected300ms timeout. Numeric Q3 alone
does not implement retry-until-confirmed-expiry. Longer abandoned-session
acquisition also interacts with failed STOP/tail/fence handling: current tail
timing begins at operator STOP and must not be mistaken for proof that the node
stopped earlier or that all late data was drained. Host tests must distinguish
stale proofs, lost responses, actual expiry, STOP, clock wrap and mixed-duration
expectations. Those checks do not require a new general admission policy.

Other engineering obligations follow from the settled scope: preserve full source/
recording/segment identity across low16 sample sequence wraps without guessing
ambiguous gaps; define real variable-length/empty-next ACK_FETCH confirmation;
version stream metadata/record layouts and maintain old recording readers; preserve
STOP/tail/fence/restart distinctions and readable-prefix handling on storage
failure. Resolve implementation facts and layout choices from governing contracts
and tests; ask only remaining product trade-offs rather than requiring the user
to choose byte offsets or routine coding details.

In particular, real ACK_FETCH may have no next object or a shorter next object.
Retirement confirmation must remain explicit without fabricating data, requiring
an unnecessary replay, or clearing an unrelated pending request. Loss/duplicate
handling must retain the old immutable identity until correctly confirmed.

SD failure must preserve an honest readable prefix and terminate acquisition as
appropriate; RAM ACK is not a promise of physical SD durability. Missing timing
evidence must not by itself discard otherwise interpretable readings. Missing
essential identity/association must not be guessed. Normal completion, an explicit
sample gap, an unreconstructed timing interval and an incomplete tail are separate
report outcomes.

Review how the longer lease affects failed STOP and abandoned-session cleanup.
An early conservative local authorization deadline is not, by itself, proof that
the remote node has physically ceased acquisition. Preserve the accepted
distinction between prompt explicit STOP and subsequent buffered-tail drain;
if cessation/tail completion cannot be proved, report the uncertainty. No stale
proof or delayed response may restart an ended recording or grant fresh authority.

Use the existing node/master/BDQ/independent-reader host seams with known packet
values, sign/extreme cases, sequence wraps, loss/duplicates, raw clock association,
renewal expiry/retries, STOP/fence/restart and storage-prefix cases. Target builds
and the required fresh ownership/wire/lifetime boundary review precede packaging.
Manual physical verification then performs the agreed one-node capture. A host
pass is not physical qualification, and this capture is not a sustained soak.

Reconcile the restricted workload and revised geometry with the original capacity
gate explicitly. Preserve frozen historical reports and keep general production
admission disabled/unqualified; no implicit broad override follows from a working
one-node diagnostic candidate. Existing BDQ schemas/readers remain readable.

## Interview completion

Q1-Q9 were individually accepted, including the revised Q3 recommendation. The
user explicitly confirmed the consolidated summary and requested `to-tickets`.
The shared-understanding checkpoint is complete; do not ask for it again. Prepare
reviewable vertical implementation slices, acceptance evidence and blockers within
this scope. Ticket publication follows the separate tracker preview/write rules;
invoking the planning skill alone does not authorize GitHub writes. No further
product question is currently pending.

No new glossary entry is needed yet: the settled decisions use existing domain
terms. An ADR will be added only if a new costly architectural trade-off warrants
one; this working milestone note does not duplicate the accepted ADRs.
