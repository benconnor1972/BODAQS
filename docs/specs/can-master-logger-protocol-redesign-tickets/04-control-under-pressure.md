# T04: Preserve essential control and timing under sample backpressure

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Keep useful sampling, essential timing and deadline-driven control progressing
independently through the new transport when sample custody is blocked. A
recording under pressure can renew authority, stop and retain interpretable data
while shedding dispensable diagnostic traffic first.

## Acceptance criteria

- [ ] Reserve bounded memory/service for STOP, renewal, ACK and essential state
  even with zero ordinary data credits/full buffers. Specify the reserve and
  bounded competing work, including actual pending-frame retirement behavior.
- [ ] A pending nonurgent exchange does not monopolize the link. Bounded sample,
  ADC and essential timing opportunities follow actual deadlines, without
  treating every metadata request as urgent.
- [ ] Retain the initial five-second authority horizon/normal once-per-second
  renewal and fresh challenges. A routine exchange timeout may be retried only
  while confirmed authority remains valid; stale observations grant no renewal.
- [ ] Classify required interpretation/native-timing evidence separately from
  optional alignment detail and diagnostics. Under pressure shed/coalesce in the
  accepted order and record limitations/loss, rather than pinning every sample
  behind an optional predecessor message.
- [ ] Known recordings remain independently interpretable with companions delayed
  or optional observations missing; absent essential definitions never become
  invented identity, timing or a false verified result.
- [ ] Host stress at the production recording seam demonstrates STOP/renewal/ACK
  and healthy-source progress with sample backpressure and diagnostic traffic.
  Assert externally visible scope/data/control outcomes, not private queue shape.
- [ ] Account for retry/empty/control/timing costs in the budget and diagnostics;
  keep instrumentation bounded and distinguish host scheduling from hardware proof.

## Blocked by

- T01: Record one known sample unit through the new protocol.
