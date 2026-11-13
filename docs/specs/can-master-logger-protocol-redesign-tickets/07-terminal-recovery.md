# T07: Finalize and restart safely after gaps, expiry and resets

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Stop, drain, fence and release a pipelined recording safely through loss and
exceptional faults, leaving a decodable result and preventing old units from
entering the next recording. Isolated failed streams end explicitly while healthy
independent sensors continue.

## Acceptance criteria

- [ ] With outstanding units and lost ACK/retirement messages, STOP gives bounded
  cessation/drain behavior and honest final boundaries. Confirmed normal loads
  target 300 ms cessation then up to five seconds drain; confirmation observation
  is not silently treated as exact acquisition cessation.
- [ ] Lost STOP/expired authority is reported uncertain and renewal ceases.
  Cleanup uses safe fencing/release rather than pretending a timeout proved
  success; no new session starts with unsafe retained ownership.
- [ ] Node/master/logger restart, expired authority, stale inspection and
  identity/sequence exhaustion cannot reattach old units, extend old authority
  or automatically rejoin the failed source in the same recording.
- [ ] An accounted sample-unit gap or lost optional timing observation alone
  does not terminate unrelated healthy sources. Untrustworthy identity/association
  ends the affected stream; unusable shared storage may end the recording.
- [ ] The complete production lifecycle/recording seam covers outstanding units,
  pending control, cancellation, bounded host storage failure and restart after
  finalization, with exact externally expected data/scope outcomes.
- [ ] Finalized diagnostics preserve terminal reason, unresolved tail, remaining
  custody and source membership without requiring a racing live debugger read.
  Missing evidence cannot be converted into a clean-complete report.
- [ ] Preserve existing node authority semantics and known first-byte/CS safety.
  No controlled physical storage-stall campaign is introduced by this ticket.

## Blocked by

- T03: Pipeline immutable units with selective retirement.
- T04: Preserve essential control and timing under sample backpressure.
