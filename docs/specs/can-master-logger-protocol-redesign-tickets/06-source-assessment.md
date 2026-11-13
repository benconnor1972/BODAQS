# T06: Assess verified delivery and native timing for every source

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Extend the independent recording assessment so the new units produce honest
per-source usable delivery, integrity, source-tail and native-timing results.
An aggregate rate or a readable file must not hide an absent participant,
rejected unit, unresolved sample scope or unavailable timing.

## Acceptance criteria

- [ ] For known one/two/four-source recordings, verify master-origin integrity
  before exposing verified readings, preserve exact axes and reconcile source
  definitions, continuity, boundaries, duplicates and known/unknown gaps.
- [ ] Retain full-width identities without lossy numeric conversion. Wrong-source
  companions, stale acquisitions, conflicting unit identities, wrap and missing
  definitions cannot create false association or a complete-delivery verdict.
- [ ] Compute delivery denominators from authoritative source scope. Count
  offline-rejected readings as loss where scope supports the count; preserve
  uncertainty otherwise. Report each expected source, not just successful ones.
- [ ] Report received/verified/rejected/unresolved readings, missing fraction,
  longest gap and gap frequency against 99.9% per-source usable delivery over ten
  minutes and no ordinary gap over 20 ms. Unknown bounds cannot yield a pass.
- [ ] Reuse the existing raw-observation/offline timing approach for the new
  schema. Independently known clock/sequence vectors reconstruct expected native
  timing, distinguish modeled from observed times and preserve unsupported intervals.
- [ ] Healthy native-timing coverage is assessed separately from delivery;
  high-frequency inter-IMU phase accuracy remains unqualified unless separately
  demonstrated. Untimed trustworthy readings stay accessible by sequence.
- [ ] Missing STOP/raw final observation, unknown-loss boundaries, torn files and
  absent footer preserve readable data but do not claim complete source tails or
  physical timing qualification. No nominal-rate timestamps are invented.
- [ ] Provide stable machine-readable verdicts consumable by bench tooling and
  retain historical recording/assessment regressions. A host fixture is not an
  admissions-policy or hardware capacity pass.

## Blocked by

- T01: Record one known sample unit through the new protocol.
