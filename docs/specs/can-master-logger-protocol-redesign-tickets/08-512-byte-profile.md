# T08: Carry 512-byte sample units through real polling recordings

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Make 512-byte transfers a genuine matched-profile option through acquisition,
safe physical transfer, compact recording and independent analysis. Compare its
measured useful progress and ADC interference against the retained 256-byte option
without assuming that larger transfers automatically improve capacity.

## Acceptance criteria

- [ ] Both sizes have explicit geometry, checksum/identity coverage, bounded
  window/copy/storage costs and a profile selected before acquisition. No silent
  size/clock switch occurs mid-recording and old-wire fallback is not added.
- [ ] Host end-to-end and adapter cases cover complete/partial/aborted 512-byte
  transfers, first-byte priming, CS retirement, active-buffer immutability and
  replay/ACK safety. Existing 256-byte behavior remains supported.
- [ ] A matched physical pair records one real IMU and the ADC baseline/mixed
  workload in bounded comparisons, producing independently decoded files and
  per-channel freshness/native-timing evidence.
- [ ] Measure physical bus ownership, preparation/rearm, useful units/readings,
  empty/replay work and ADC freshness/age. Do not reuse old 256-byte mean service
  or clock-only duration as a qualified 512-byte cost.
- [ ] Record actual selected ADC worker activity and comparison scope; include
  all checksum/header bytes and partial units in packing/service calculations.
  Treat an ADC regression or bad first-byte result as a failed candidate, not
  permission to silently reduce ADC capability.
- [ ] Produce applicable safe-profile/pass/no-go evidence for both sizes. This
  ticket enables 512-byte use but does not independently claim the two/four-IMU
  ten-minute target; those profiles are qualified in T09/T12.
- [ ] Keep 1,024-byte frames and node/CAN changes out of scope. Surface a material
  service deficit before further frame-size optimization.

## Blocked by

- T02: Capture and finalize one real IMU with new-protocol polling.
- T05: Preserve per-channel ADC freshness in mixed recordings.
- T06: Assess verified delivery and native timing for every source.
- T07: Finalize and restart safely after gaps, expiry and resets.
