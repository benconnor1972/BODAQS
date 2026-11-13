# T09: Qualify the two-IMU mixed polling profile

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Demonstrate the minimum useful existing-logger profile: two native-rate IMUs plus
one 500 Hz channel on each ADC, without IRQ. Deliver a reproducible physical
qualification and automated report rather than a passing row/exchange counter.

## Acceptance criteria

- [ ] Use identified matched firmware, unchanged CAN nodes/profile, explicit
  participating sources, fixed SPI profile and the current high-endurance card.
  Two IMUs remain approximately 3,333 six-axis readings/s each, without rate cuts.
- [ ] A ten-minute ordinary-load window meets at least 99.9% usable delivery for
  each source and no individual ordinary sample gap longer than 20 ms, reconciled
  against authoritative source scope and upstream integrity results.
- [ ] Each ADC channel is at least 99.5% fresh with no ordinary interval without
  fresh data over 10 ms. Report repeats/age and actual conversions separately
  from the 500 Hz row rate; preserve valid data from the unaffected channel.
- [ ] Demonstrate healthy native timing and report latency evidence/limitations,
  target 100 ms normal acquisition-to-RAM behavior, bounded queues and STOP/tail
  cleanup. Unreconstructed timing or missing source membership cannot be hidden.
- [ ] Complete the qualified service/memory/burst budget, including inherited
  70% CAN/85% shared-SPI occupancy, at least 1.25x concurrent useful drain and
  applicable node/master/logger backlog coverage. Use stage-specific measurements;
  do not promise lossless 500 ms master retention from these results.
- [ ] Use 256 bytes if it qualifies. Testing/claiming 512 bytes requires T08's
  applicable profile evidence; T08 is not an artificial blocker to a successful
  256-byte minimum result. A slower/smaller fallback needs its own workload result.
- [ ] Automatically collect raw/finalized evidence and assess per-source quality,
  ADC freshness, timing, queues, control and storage. Preserve commands, configs
  and artifact hashes so the result is reproducible.
- [ ] A shortfall yields a scoped no-go/bottleneck report and review before
  physical workload expansion. A failing report does not complete the pass
  criteria or silently weaken targets; controlled storage stalls stay deferred.

## Blocked by

- T02: Capture and finalize one real IMU with new-protocol polling.
- T05: Preserve per-channel ADC freshness in mixed recordings.
- T06: Assess verified delivery and native timing for every source.
- T07: Finalize and restart safely after gaps, expiry and resets.

Conditional prerequisite: complete T08 before using or claiming a 512-byte profile.
