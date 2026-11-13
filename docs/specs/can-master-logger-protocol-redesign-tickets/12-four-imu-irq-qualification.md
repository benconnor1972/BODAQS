# T12: Qualify four-IMU mixed acquisition with ready IRQ

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Demonstrate four real full-rate IMUs plus the two 500 Hz ADC channels on the
existing logger using optional ready IRQ, and measure what changes compared with
the four-source polling result. Publish a defensible profile result rather than
assuming readiness signaling supplies the missing capacity.

## Acceptance criteria

- [ ] Run a controlled comparison against T10 with all four expected sources,
  unchanged CAN sample/profile settings, same ADC workload/card and identified
  matched artifacts/configuration. A 512-byte profile requires completed T08 evidence.
- [ ] A ten-minute ordinary-load run meets at least 99.9% usable delivery per IMU,
  no ordinary sample gap over 20 ms, healthy native timing and explicit per-source
  verification/gap/tail results. Do not hide a participant behind aggregate counts.
- [ ] Both ADC channels meet at least 99.5% fresh readings and no ordinary interval
  without fresh data over 10 ms. Include conversion/age evidence and shared-bus
  blocking, not merely primary row production.
- [ ] Demonstrate bounded queues, normal acquisition-to-RAM latency evidence and
  STOP/drain/fence outcomes, including applicable IRQ fallback behavior and
  essential control under pressure. Separate recovery/fault trials from the
  ordinary quality window without hiding their losses.
- [ ] Complete the stage-specific service/memory/coverage and capacity-margin
  gates, including all mandatory metadata, retry/empty/control and recording costs.
  No lossless arbitrary-stall or unverified inter-IMU phase claim is made.
- [ ] Automate scoped evidence collection and assessment; compare useful progress,
  avoidable polling/replay, source ingress, ADC and storage behavior with T10.
  Attribute improvement only where the controlled evidence supports it.
- [ ] A material no-go triggers a quantified bottleneck/design review. The pass
  ticket remains unmet unless the target is demonstrated or the user explicitly
  changes scope; do not silently reduce rates or substitute a synthetic result.

## Blocked by

- T10: Measure four-IMU mixed polling and its remaining bottleneck.
- T11: Use optional ready IRQ with bounded polling fallback.

Conditional prerequisite: complete T08 before using or claiming a 512-byte profile.
