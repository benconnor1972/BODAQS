# T11: Use optional ready IRQ with bounded polling fallback

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Deliver a real sample-to-recording path using optional master-ready signaling,
while preserving polling-only operation and safe control when the signal is
absent, stuck or missed. Readiness must mean a safely publishable new/requested
retry unit, not merely that some unacknowledged data exists.

## Acceptance criteria

- [ ] Verify actual master/logger pin routing, polarity and resource availability
  on the user's hardware before enabling the feature. Retain explicit per-profile
  IRQ configuration and polling-only operation; do not infer wiring from old docs.
- [ ] Define and implement level/latched assertion, deassertion and retry semantics
  tied to immutable safe physical publication. A missed edge loses no work; old
  retained units or zero credits do not cause an unbounded replay/busy loop.
- [ ] IRQ guides scheduling only. Live CRC/identity/custody checks remain required,
  and control/renewal/STOP can obtain service without data-ready.
- [ ] A bounded watchdog/polling path handles absent/stuck indications while
  preserving deadlines. Fault cases demonstrate continued healthy-source/control
  progress or explicit bounded failure rather than an indefinite wait.
- [ ] Exercise ready/rearm/CS races in the existing adapter seam and record one
  real IMU through BDQ and independent decoding with IRQ enabled. Preserve known
  first-byte priming and inactive/active buffer ownership safety.
- [ ] Record readiness-triggered versus watchdog/control/empty exchanges,
  useful data, queue age and observation overhead. A functional IRQ capture is
  not a four-source capacity claim; that belongs to T12.
- [ ] If wiring/resources do not support the reported connection, return the
  specific evidence and retain polling operation instead of inventing a pin or
  silently changing boards. Hardware modification needs its own authorized scope.

## Blocked by

- T02: Capture and finalize one real IMU with new-protocol polling.
- T07: Finalize and restart safely after gaps, expiry and resets.
