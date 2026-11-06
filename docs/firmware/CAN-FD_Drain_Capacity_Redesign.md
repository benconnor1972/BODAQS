# CAN-FD drain-capacity redesign

Status: design confirmed by the user, 6 November 2026. Synthesizes the accepted
Q1-Q23 interview and the final confirmation of shared understanding. No replacement firmware,
wire format or recording schema has been implemented or qualified by this work.

## Problem Statement

Single-node IMU recording still exhausts master retention and then loses
interpretation evidence, causing endpoint exclusion. Useful draining competes
with repeated control/evidence polling, and retaining readings is unnecessarily
coupled to live timing-model availability. Short shared-SPI transactions and
ADC service remain real throughput constraints.

The 08:06:10 bench recording, context 10547103591045405970, has 1,236 consecutive
IMU readings before exclusion. Its frozen master window admitted 269 CAN records
and retired 140 in 430,963 us, leaving 129 retained: 128 queued and one selected
evidence record. Twelve sample batches held 128 CAN records, averaging 10.67 of
13; sample replies included 17 repeated fragments out of 273. Of 900 accepted
requests, 422 polled non-data classes. These are short-window observations, not
qualified steady rates. An idle response is not automatically unnecessary work.

The evidence supports improving service allocation and polling efficiency;
small batches and repeated sample fragments alone do not explain the deficit.
It does not establish that the hardware can meet the four-node target.

## Solution

Preserve compact, interpretable IMU readings and raw timing observations without
requiring online per-sample timing reconstruction. Reconstruct timing in updated
analysis tools, explicitly distinguishing native sample timing, cross-sensor
alignment, estimates and unavailable timing.

Retain the current hardware and short SPI transactions. Introduce versioned
combined acknowledgment/fetch requests, availability hints and service allocation
based on backlog and actual deadlines. Reduce recurring authorization work and
allow bounded retries while authorization remains valid. Simplify exceptional
fault handling to explicit gaps or ending the affected stream.

Four IMUs at approximately 3.33 kHz each remain the design target; one node is
the first physical qualification milestone. Admit only budgeted and tested
combinations of remote and ADC workloads, without silent rate reduction.

## User Stories

1. As a rider, I want supported sensor combinations to record continuously so
   routine scheduling does not discard measurements.
2. As a user, I want unsupported combinations rejected before acquisition so
   my requested rates are not silently reduced.
3. As an analyst, I want intact readings retained when timing evidence is lost
   so I can still inspect their values and ordering.
4. As an analyst, I want missing readings and uncertain gap sizes reported so
   apparent continuity cannot hide loss.
5. As an analyst, I want timing reconstructed from preserved observations so
   models can improve without changing the recorded measurements.
6. As an analyst, I want estimated and unavailable timing distinguished so
   tools do not imply measurement precision that has not been established.
7. As an analyst, I want untimed readings accessible by sequence and limitations
   reported when an operation requires timing that cannot be established.
8. As a user, I want healthy sensors to keep recording after another sensor
   fails so a local fault does not discard the remainder of the ride.
9. As a user, I want Stop to cease acquisition promptly while buffered data
   drains afterward, with an honest indication of uncertain or incomplete results.
10. As a user, I want nodes to stop after the logger disappears without requiring
    frequent exchanges that undermine sample delivery.
11. As a user, I want local ADC acquisition to receive bounded bus service while
    remote IMUs drain, within explicitly supported workload combinations.
12. As an owner of existing recordings, I want them to remain readable after a
    coordinated firmware and analysis-tool upgrade.

## Implementation Decisions

### Hardware and transport ownership

- Retain boards, wiring and shared SPI. Initially retain 64-byte measurement
  transactions at 8 MHz, releasing the bus between transactions. Retain the
  existing 100 us uninterrupted ownership target and rearm/gap qualification
  requirements; no faster readiness is assumed from wire speed alone.
- Existing logger wiring has no usable master IRQ. Discover work through bounded
  SPI probing and availability information in replies. Availability is a
  potentially stale scheduling hint, not hardware-ready or acceptance proof.
- Requests can acknowledge a previously accepted batch and request a useful next
  reply. Preserve recording/context, object and checksum identities, duplicate
  handling and immutable retained contents. Stale prepared replies must be safe.
- Initially retain one selected immutable batch per node until complete logger-RAM
  acceptance. RAM acceptance is not SD persistence. A logger failure can lose
  accepted but unwritten data; do not introduce a durable-write ACK requirement.
- Evaluate multiple outstanding batches before implementation if the first
  design cannot meet the capacity gate. Larger buffers do not repair a sustained
  throughput deficit.
- Physical SPI retirement, DMA rearm, request processing and reply publication
  must be represented separately in the service model. Current one-request RX
  capacity and multi-transaction reply latency must be measured and addressed;
  faster polling must not merely increase rejected requests.

### Service and authorization

- Guarantee bounded sample and ADC service. Prioritize control by actual deadline,
  not simply because an exchange is pending. Normal polling concentrates on
  participants; budget retries, empty replies, event bursts and ordinary diagnostics.
- Use a five-second authorization horizon, normally renewed once per second.
  These are initial design values subject to the complete service budget.
- Retain fresh node-issued challenges bound to the current authorization and
  recording. Replayed, duplicate or late proofs must not create fresh permission;
  STOP and expiry remain terminal.
- A failed renewal exchange may be retried while confirmed authorization remains
  valid. An isolated 300 ms exchange timeout no longer independently excludes a
  participant. Retry opportunities are bounded by remaining confirmed authority;
  sending a request does not prove that the node accepted a renewal.
- Preserve explicit membership release and old-data fencing before a new
  recording. Longer expiry may delay abandoned-session cleanup; it does not
  implicitly release membership or authorize mid-recording rejoining.

### Observations, persistence and analysis

- Nodes retain internal checks for trustworthy accel/gyro association and source
  ordering. Move timing fitting offline, not the checks needed to know which
  readings constitute an associated sample.
- Export raw observations relating full sample sequence to sensor/node clock
  readings, at recording boundaries and periodically. Do not make repeated
  short-lived firmware timing models authoritative.
- Choose periodic cadence through reconstruction-quality and capacity measurements
  within a bounded traffic budget. No particular new cadence, including 1 Hz,
  has been accepted or qualified. Simply slowing existing models while retaining
  their 150 ms applicability would leave normal samples uncovered.
- Keep source/provider identity, recording/boot/segment identity, effective
  configuration, integrity and trustworthy sample association essential.
  Preserve sufficient source-sequence references independently of timing fits.
  Counter wraps or resets must not silently alias identities. If only timing is
  ambiguous, retain readings as untimed; if source interpretation or association
  is untrustworthy, end the affected stream under the agreed fault policy.
- Introduce a dedicated versioned compact packet-observation schema in the BDQ
  container. Its observation timestamp is not a sample-acquisition timestamp.
  Preserve the original readings and their interpretation information; do not
  silently reuse the current per-sample schema with invented native ticks.
- Permit timing observations to follow related readings in the file. Essential
  identity/configuration/association information must survive with the readings;
  timing loss may leave readable but untimed data after interruption.
- Healthy acquisition should normally have continuous reconstructable native
  timing. Sparse observations yield estimates between observations, not each
  sample's actual acquisition time. State model assumptions and unknown bounds;
  small fit residuals alone do not qualify absolute timing uncertainty.
- Keep unknown cross-sensor alignment explicit. Precise inter-sensor alignment,
  including the unverified 10 us target, is a separately qualified capability.
  Retain useful alignment observations where their cost is reasonable.
- Expose untimed readings by sample sequence. Operations requiring unavailable
  timing explicitly report affected intervals. Any future nominal-rate fallback
  requires explicit selection and estimate labelling, rather than silent filling.
- Existing recordings and existing sensor schemas remain readable. Updated
  firmware and analysis tools may be required together for the new representation;
  compatibility with every previous bench firmware combination is not required.

### Fault and lifecycle boundaries

| Situation | Required behavior |
| --- | --- |
| Timing observation missing | Preserve interpretable readings; report reduced timing coverage/quality. |
| Temporary sample overflow | Record an explicit gap and continue if source interpretation remains trustworthy. |
| Reset, expired authorization or untrustworthy sample association | End the affected stream; no automatic rejoining in this recording. |
| Independent node failure | Continue healthy participants. |
| Unusable shared storage or infrastructure | Stop the whole recording when continued recording is impossible. |
| Ordinary operator Stop | Target acquisition cessation within 300 ms under admitted workloads. |
| Buffered tail after acquisition stops | Allow up to five seconds afterward to drain; report incomplete tails. |
| Stop cannot be delivered | Report uncertainty; authorization expiry is the fallback. |

The 300 ms Stop target, post-stop drain allowance, five-second authorization
horizon and provisional 100 ms sample-delivery target are different clocks and
must not be conflated. The sample-delivery target ends at logger-RAM acceptance,
not physical SD persistence or file closure.

## Testing Decisions

Use the highest existing integration seam that can check node observations,
master retention, logger acceptance, BDQ persistence and decoded analysis output.
Check external behavior and independently specified data/clock traces rather
than mirroring the implementation. Supplement this with production SPI-adapter
tests and physical timing measurements where the integration model cannot
establish hardware behavior.

Existing acquisition, transport, adapter, recording/storage lifecycle and Python
BDQ/timing suites provide the prior art. Extend those seams instead of creating
a parallel simulator that omits physical retirement and reply-publication delay.

Required evidence:

1. Exact raw readings, source identity and ordering survive compact recording and
   decoding. Existing recording fixtures and other sensor schemas still decode.
2. Missing/delayed timing observations do not reject valid readings or block
   persistence. Interrupted files preserve an honest readable prefix and expose
   untimed data where applicable.
3. Known synthetic acquisition/clock traces independently test reconstruction,
   discontinuities, drift changes, boundaries and unsupported intervals. Check
   estimate labels and coverage, not just fit residuals or encoder round trips.
4. Lost requests/replies, duplicate ACKs, stale prepared replies and delayed
   publication cannot retire unaccepted data or alias a recording/object.
   Include actual request-capacity pressure and ISR/main-loop interleavings.
5. Failed renewals remain retryable within confirmed authority. Delayed proofs,
   duplicates and retries after STOP/expiry cannot extend authorization.
6. Overflow reports gaps and resumes only where interpretation remains trustworthy;
   node faults stay isolated, and stopped participants do not rejoin automatically.
7. STOP cessation, tail drain, abandoned-session fencing and next-recording startup
   meet their distinct rules, including uncertain outcomes and identifier wrap.
8. Host checks and target builds pass before manual physical qualification. Fresh
   boundary review covers changed ownership, wire identities and finite lifetimes.

### Capacity and physical qualification gates

- Produce a complete service and memory budget before committing to the first
  transport design. Include actual selected ADC worker rates, all mandatory
  control/time traffic, encoding/decoding, arbitration, rearm gaps, pipeline delay,
  partial batches, bounded retry/empty traffic and burst reserves.
- Retain current admission gates unless separately changed: at most 85% steady
  shared-SPI scheduling occupancy; demonstrate at least 1.25 times admitted
  sample ingress drain with mandatory concurrent traffic active; meet the CAN
  occupancy target and burst/service-envelope constraints. Apply the stricter
  bound. Wire occupancy alone is insufficient.
- Retain the existing buffer-coverage requirements unless separately changed:
  50 ms node sample backlog, 100 ms master retention and one second logger remote
  buffering, accounting for actual representations, local streams and reserves.
  A five-second authorization does not imply five-second lossless buffering.
- First qualify sustained single-node recording, then supported mixed ADC and
  multi-node workloads. Queue growth, ACK-retired useful records, source losses,
  latency tails and control deadlines must be observable. Supported normal loads
  must not rely on overflow or exclusion to remain bounded.
- Demonstrate the provisional 100 ms acquisition-to-RAM delivery target and
  bounded ADC service under admitted normal loads. Qualify the short-transaction
  ownership/rearm requirements and actual runtime stack/RAM margins.
- Select timing cadence using measured reconstruction coverage and error against
  independent observations. Include boundaries, gaps and clock/sequence wraps;
  unqualified absolute or cross-sensor uncertainty remains unknown.
- A host pass, larger queue or a short recording does not establish sustained
  physical capacity. Exact soak durations and fault-injection procedures belong
  in the executable qualification plan, not an implicit claim of success here.

## Out of Scope

- Hardware/wiring changes in this round, unless the capacity gate forces a new
  explicit trade-off.
- Guaranteed simultaneous maximum rates for every possible IMU/ADC combination.
- Automatic rejoining after exceptional participant failure.
- Achieving or advertising the unverified 10 us cross-sensor alignment target.
- Lossless recording through unbounded outages or every simultaneous fault.
- Nominal-rate timestamp filling as an automatic analysis behavior.
- Device flashing, tracker publication and release qualification by this document.

## Further Notes

### Capacity risk that remains open

Compact BDQ storage does not itself reduce the already compact SPI sample traffic.
With the current reception-batch geometry, four nominal IMUs need about 5,333
sample-data fragments/s even at full 13-record batches, before other traffic.
The latest logger scope reports roughly 147 us average measured exchange time
across mixed traffic. Applying that cost illustratively to the fragment count
already consumes about 0.78 s/s, before separately accounting for ADC work and
the complete service costs. This is not a qualified prediction for the new
protocol, but it shows why fewer ACKs alone cannot justify a four-node claim.

If the first budget fails, revisit batching/pipelining, transaction costs and the
explicit hardware/rate trade-off before dependent implementation. Evidence cadence,
exact message/schema layouts, freshness/exchange deadlines, scheduler parameters,
buffer placement and reconstruction acceptance measurements remain engineering
work to resolve against the agreed boundaries. None is silently selected here.

### Relationship to existing contracts

The interview revises online model dependence, the logger-expansion choice,
authorization timing/failure handling, SPI request semantics and post-stop drain
timing. Existing production contracts are not silently rewritten by this draft.
Approved implementation must reconcile the affected contracts and versioned
interfaces together. Preserve unrelated guarantees, explicit gaps, corruption
detection and honest time quality.

- [Design boundaries and interview decisions](../adr/0002-drain-capacity-redesign-boundaries.md)
- [Offline reconstruction decision](../adr/0003-record-observations-reconstruct-timing-offline.md)
- [Acquisition transport contract](CAN-FD_Acquisition_Transport_Contract.md)
- [Network protocol decisions](CAN-FD_Network_Protocol.md)
- [BDQ multi-stream contract](BDQ_v2_Multi_Stream_Contract.md)
