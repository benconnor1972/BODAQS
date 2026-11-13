# T03: Pipeline immutable units with selective retirement

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Let multiple immutable units remain outstanding while useful units from the same
and other sources continue into recorded, independently decoded data. Repair only
the missing/damaged units and release retained storage through exact, replay-safe
RAM acknowledgment. Demonstrate behavior at the complete recording seam.

## Acceptance criteria

- [ ] Select a small bounded window and credits using the layout/memory/service
  budget. Show actual bank/copy/state/control costs; do not infer recovery from
  nominal unused RAM or equate window size to the entire backlog allowance.
- [ ] Demonstrate more than one unit in flight with exact source/acquisition/unit
  identity and immutable published content. Do not reuse an active SPI buffer or
  mutable queue position as the retained identity.
- [ ] Drop/delay a unit, ACK and retirement reply independently. Other eligible
  units/sources progress, duplicates decode once and no wrong unit is retired.
- [ ] Scope ACK/replay history safely across window advancement, exhaustion and
  wrap. A CRC-valid stale ACK or conflicting same-identity content cannot free
  another unit. Preserve safe RAM custody semantics without a durable-write ACK.
- [ ] Bound selective repair and explicitly account for abandonment; the decoded
  result contains the expected gap rather than fabricated continuity or a global
  indefinite wait. Healthy other sources retain correct association.
- [ ] Zero credits/full queues prevent unsafe acceptance; unavoidable overflow
  drops new complete units after optional shedding and preserves published history.
- [ ] Independent expected-value/fault cases cover two/four source identities,
  partial units and tail data. Report useful unit progress, repeats and repair,
  not merely attempted exchanges. No physical throughput claim follows from host timing.

## Blocked by

- T01: Record one known sample unit through the new protocol.
