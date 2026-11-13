# T05: Preserve per-channel ADC freshness in mixed recordings

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Make the new mixed recording and offline result distinguish a fresh conversion
from a cached repeat independently for each ADC channel, including conversion
age. A 500 Hz row stream must no longer be enough to imply fresh analog data.

## Acceptance criteria

- [ ] Reuse existing conversion association/freshness evidence where sufficient;
  add only the explicitly versioned recorded information needed for per-channel
  assessment. Preserve historical primary/ADC schema interpretation.
- [ ] Independent fixtures prove equal-valued distinct conversions are fresh and
  reused conversions are repeats. Row timestamps or numeric equality are not
  substituted for conversion identity.
- [ ] A stale/missing conversion on one channel is marked for that channel while
  another channel's valid reading remains usable. Age units and sample association
  are explicit; missing evidence is unresolved rather than assumed fresh.
- [ ] The production primary-recording path and independent reader carry this
  information alongside new-protocol IMU units without changing requested sensor
  rates or inferring worker conversions from the row rate.
- [ ] Machine-readable assessment reports per-channel fresh fraction, reuse,
  age and longest interval without fresh data over an explicit scope, against
  99.5% fresh/ten minutes and no ordinary gap over 10 ms. Unknown scope cannot pass.
- [ ] Existing ADC-start/ready-wait behavior and setup-cost regressions remain
  protected. Hot-path evidence is bounded and allocation/blocking costs are
  included; floating inputs do not establish analog accuracy or channel isolation.
- [ ] Host results claim evidence/assessment correctness only. Actual selected
  worker rates and mixed-load freshness require the physical qualification tickets.

## Blocked by

- T01: Record one known sample unit through the new protocol.
