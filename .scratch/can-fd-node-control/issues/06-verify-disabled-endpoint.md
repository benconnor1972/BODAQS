# 06: Reconcile an IMU endpoint to verified disabled state

## What to build

Deliver the first hardware-backed configuration transaction: the logger stages
and commits an explicit disabled IMU request, the node powers down and verifies
the sensor, and the logger reports the actual disabled state. Unassigned
supported endpoints can be reconciled safely without inventing an enabled
profile or collecting samples.

## Acceptance criteria

- [ ] Complete requests use immutable begin/page/commit metadata, one mutation context per node and the confirmed staging/application deadlines; only commit can begin hardware application.
- [ ] Abort, expiry, conflicting pages, stale revision and identity reuse have the specified terminal behavior; duplicate recognition precedes current-revision checks and returns cached outcomes without reapplying hardware.
- [ ] Production-node SPI initialization, identity, reset and masked readback verify both engines off, FIFO bypassed and acquisition interrupt routes disabled; failure leaves explicit unknown/fault evidence.
- [ ] Desired generation, accepting session, applied revision and state epoch reach the logger coherently; inspection remains responsive during apply and no-op handling follows fresh-verification rules.
- [ ] State-machine tests, affected builds and a documented board-level disabled/readback/failure procedure cover the complete path; physical results are recorded separately from simulated evidence.

## Blocked by

- Preview 04: Inspect coherent endpoint capabilities and effective state.
- Preview 05: Establish and release reset-safe node control authority.

## Publication preview

Repository: benconnor1972/BODAQS. Intended labels: enhancement, ready-for-agent,
when available. No source parent issue was supplied. Preview only; not published.
