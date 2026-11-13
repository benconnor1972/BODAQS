# T10: Measure four-IMU mixed polling and its remaining bottleneck

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Extend the qualified polling configuration to four real native-rate IMUs with
the same two ADC channels and determine whether polling alone reaches the target.
Whether pass or no-go, produce bounded, comparable evidence identifying useful
service, remaining loss and the limiting stage before the IRQ comparison.

## Acceptance criteria

- [ ] Keep CAN nodes/profile, requested native rates, ADC workload, card and
  measurement scope controlled relative to the two-source result. Identify all
  four sources and preserve exact selected firmware/configuration.
- [ ] Assess the accepted per-source delivery/gap, native-timing, ADC freshness,
  normal latency, STOP/cleanup and inherited resource gates. A short or incomplete
  run is explicitly unqualified; aggregate throughput cannot hide an absent node.
- [ ] Measure new useful data versus replay/empty/repair/control work, bounded
  queue depth/age, source/CAN/master ingress losses, ADC interference and storage.
  Avoid treating overlapping wall intervals as additive CPU utilization.
- [ ] Use only profiles with applicable implementation/physical evidence;
  a 512-byte test requires T08. Compare sizes only where useful to distinguish
  a real bottleneck, rather than automatically launch a large tuning matrix.
- [ ] Produce a reproducible pass/no-go report and stage-specific service budget.
  A four-IMU polling no-go is an acceptable scoped outcome of this investigation;
  it does not pass the IRQ target or weaken the already-qualified minimum profile.
- [ ] Review material shortfalls before additional optimization, and identify
  the specific hypothesis that optional readiness can test. Do not assume IRQ
  repairs CAN ingress, storage or an unrelated CPU bottleneck.

## Blocked by

- T09: Qualify the two-IMU mixed polling profile.

Conditional prerequisite: complete T08 before using or claiming a 512-byte profile.
