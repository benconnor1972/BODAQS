# Boundaries for the drain-capacity redesign

On 6 November 2026, repeated single-node retention overflows motivated a review
of the acquisition design's transport overhead and guarantees. The user accepted
these boundaries for the redesign interview:

- Preserve otherwise valid, identifiable sensor readings when timing evidence is
  incomplete, explicitly recording the affected interval's timing limitations.
  This extends ADR 0001's allowance for unknown alignment; it does not authorize
  invented timestamps or retention of readings with uncertain identity or
  integrity. The representation and analysis rules remain to be decided.
- Permit an explicit end to an affected sensor stream, followed by a deliberate
  restart, instead of automatic reconstruction after exceptional faults. Routine
  lost replies and agreed storage pauses still require normal handling; the
  precise fault boundaries remain to be decided.
- Retain the existing boards, wiring and shared SPI connection for this round,
  while allowing changes to scheduling, batching and the logger-master protocol.
  Revisit hardware if a defensible service budget cannot meet the agreed targets.
- Permit coordinated logger, master and node firmware updates with explicit
  protocol versioning. Existing BDQ recordings must remain readable; any change
  to newly recorded data requires a separate format and analysis decision.
- Retain four IMUs at approximately 3.33 kHz each as the design target, with one
  node as the first qualification milestone. Admit only explicitly budgeted and
  tested combinations of IMU and ADC workloads; do not silently reduce rates.
- Prioritize continuous readings and trustworthy timing within each sensor over
  the unverified 10 us inter-sensor alignment target. Treat precise cross-sensor
  alignment as a separately qualified capability; justify recurring evidence by
  its analytical benefit and preserve useful clock observations where their cost
  is reasonable.
- Permit deliberate sample batching, with a provisional normal-operation target
  of at most 100 ms from acquisition to acceptance into logger RAM. This is
  separate from timestamp accuracy, SD persistence and control deadlines, and
  requires a feasible buffering and scheduling budget before final acceptance.
- Use an initial five-second acquisition authorization horizon with renewal
  normally attempted once per second, subject to service-budget validation.
  Preserve prompt explicit STOP and protection against stale authorization.
  Redesign exchange deadlines and retries together with these timings; expiry
  does not permit automatic rejoining. Longer unattended acquisition and a
  potentially longer abandoned-session cleanup wait are accepted trade-offs.
- Continue an affected stream after an explicitly recorded sample gap when
  source identity, integrity and sample association remain trustworthy. Supported
  workloads must still avoid overflow within their qualified operating envelope;
  gap reporting is not a substitute for adequate capacity.
- End a failed participant's stream while healthy independent sensors continue.
  Do not automatically rejoin that participant during the recording. Failure of
  shared infrastructure, including unusable storage, may end the whole recording.
- Target cessation of remote acquisition within 300 ms of ordinary operator
  STOP under admitted workloads, then allow up to five seconds afterward for
  buffered-data drain. If STOP cannot be delivered, authorization expiry is the
  fallback and the outcome remains explicitly uncertain. Report incomplete tails
  instead of claiming complete delivery. This separates the new post-stop drain
  allowance from the previous contract's five seconds measured from operator STOP.
- Store compact readings and timing observations separately in a new, explicitly
  versioned recording representation, reconstructing per-sample timing in updated
  analysis tools. See [ADR 0003](0003-record-observations-reconstruct-timing-offline.md).
- Require source identity, configuration and sample association for retention.
  Missing timing observations limit available analyses instead of automatically
  discarding otherwise interpretable readings. End the affected stream if its
  identity, integrity or sample association becomes untrustworthy.
- Guarantee bounded sample and ADC service, with control priority determined by
  actual deadlines rather than merely pending exchanges. Concentrate normal
  polling on participants. Budget physical transactions and processing, including
  retries and empty replies, and validate useful drain throughput under concurrent
  mandatory traffic rather than counting attempted data turns.
- Preserve access to untimed readings by sample sequence. Standard analysis must
  report affected intervals and exclude them from operations requiring timing
  that cannot be established, without silently assigning timestamps or omitting
  readings. Any future nominal-rate approximation requires explicit selection
  and an estimate label.
- Permit timing observations to be persisted after related readings, resolving
  their relationships offline. An interrupted recording may therefore retain
  readings without sufficient timing evidence. Source identity, configuration
  and sample association must still survive with the readings.
- Initially retain 64-byte measurement SPI transactions at 8 MHz and release the
  bus between transactions for ADC work. Improve transaction usefulness before
  reopening the existing 100 us uninterrupted bus-ownership target; revisit size
  only if the complete capacity budget requires it.
- Introduce versioned requests that can acknowledge previously accepted data and
  fetch the next useful reply, with responses advertising available work. Treat
  availability as potentially stale scheduling information, not proof of hardware
  readiness or successful transfer. Preserve explicit identities, checksums,
  duplicate handling and bounded probing for newly available work.
- Evaluate the first transport design with one selected immutable batch per
  node awaiting logger acceptance. Reopen multiple outstanding batches before
  implementation if the capacity calculation cannot meet the four-node goal;
  extra buffering alone is not evidence of adequate throughput.
- Seek continuous reconstructable native timing during healthy acquisition;
  untimed readings are an exceptional fallback, not the normal recording mode.
  Explicitly identified estimates must be supported by observations. Select
  evidence frequency through reconstruction-quality measurements rather than
  inheriting the current 10 Hz model refresh and 150 ms software applicability.
- Retain fresh node-issued renewal challenges at the reduced cadence. A failed
  exchange may be retried while confirmed authorization remains valid, without
  immediate exclusion merely for a 300 ms exchange timeout. Bound retries by
  remaining confirmed authorization; expiry, explicit STOP and other terminal
  faults still end participation. No stale proof may extend authorization.
- Retain the BDQ container with a dedicated versioned schema for compact IMU
  packet observations. Its observation timestamp describes packet observation,
  not sensor acquisition; analysis expands readings and reconstructs sample
  timing separately. Existing sensor schemas remain intact, while new recordings
  require updated analysis tooling.
- Keep internal node checks for trustworthy sample association, but export raw
  timing observations instead of making repeated short-lived firmware-fitted
  timing models authoritative. Associate full sample sequences with sensor/node
  clock readings at recording boundaries and periodically during acquisition.
  Analysis fits timing between observations, labels estimates and leaves
  unsupported intervals unknown. Sparse observations cannot recover every
  sample's actual acquisition time. Select cadence through reconstruction-quality
  and capacity measurements within a bounded traffic budget.

These choices prioritize useful, honestly qualified recordings and a simpler
operating model over automatic recovery and compatibility with every bench
firmware combination. They establish design direction, not an implemented or
qualified replacement for the current
[acquisition contract](../firmware/CAN-FD_Acquisition_Transport_Contract.md).
The consolidated design and qualification gates are in the
[confirmed redesign](../firmware/CAN-FD_Drain_Capacity_Redesign.md).
The user confirmed shared understanding on 6 November 2026; ticket breakdown and
publication are separate planning steps.
