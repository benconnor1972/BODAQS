# Master/logger protocol redesign: ticket publication preview

Parent specification: [#200](https://github.com/benconnor1972/BODAQS/issues/200).
The approved specification is published. The child tickets below are local drafts;
their creation, sub-issue links and blocking relationships await approval.

## Slices and genuine blockers

| ID | Ticket | Blocked by | Demonstrable result |
|---|---|---|---|
| [T01](01-known-unit-recording.md) | Record one known sample unit through the new protocol | None | Known CAN input produces an independently verified compact BDQ recording through production components |
| [T02](02-real-imu-polling.md) | Capture and finalize one real IMU with new-protocol polling | T01 | A matched physical pair produces a readable, scoped one-IMU recording with honest tail/cleanup evidence |
| [T03](03-selective-retirement.md) | Pipeline immutable units with selective retirement | T01 | A lost unit or ACK no longer pins all useful progress or duplicates visible readings |
| [T04](04-control-under-pressure.md) | Preserve essential control and timing under sample backpressure | T01 | STOP/renewal/ACK and essential timing progress with full sample buffers; optional diagnostics shed first |
| [T05](05-adc-freshness.md) | Preserve per-channel ADC freshness in mixed recordings | T01 | Recorded conversion association distinguishes a cached repeat from an equal-valued fresh conversion |
| [T06](06-source-assessment.md) | Assess verified delivery and native timing for every source | T01 | Offline reports independently reconcile source scope, integrity, gaps, native timing and uncertainty |
| [T07](07-terminal-recovery.md) | Finalize and restart safely after gaps, expiry and resets | T03, T04 | Pipelined recordings stop/drain/fence without stale-data reuse, and isolated faults spare healthy sensors |
| [T08](08-512-byte-profile.md) | Carry 512-byte sample units through real polling recordings | T02, T05, T06, T07 | Both physical sizes have complete record/decode paths with measured ADC/blocking evidence |
| [T09](09-two-imu-polling-qualification.md) | Qualify the two-IMU mixed polling profile | T02, T05, T06, T07 | Ten-minute minimum useful profile meets delivery, freshness, timing, control and capacity gates |
| [T10](10-four-imu-polling-comparison.md) | Measure four-IMU mixed polling and its remaining bottleneck | T09 | A bounded real four-source comparison reports pass/no-go and the limiting stage |
| [T11](11-ready-irq.md) | Use optional ready IRQ with bounded polling fallback | T02, T07 | Real data-ready service works end to end and remains safe for absent/stuck/missed indications |
| [T12](12-four-imu-irq-qualification.md) | Qualify four-IMU mixed acquisition with ready IRQ | T10, T11 | Four full-rate IMUs plus both ADC channels meet the same quality/control/resource gates |
| [T13](13-qualified-package.md) | Package qualified profiles and repeatable acceptance runs | T08, T12 | Reproducible matched artifacts, configuration templates and one run assessment identify supported profiles |

Every ticket has its own body and acceptance criteria. T01 is a narrow host
walking skeleton, not the entire transport implementation: one bounded unit,
one known source and the complete recording/independent decoding path. T02
gets physical evidence early; it is not a ten-minute capacity claim. T03-T07
extend observable behavior rather than form horizontal module work packages.

No standalone broad prefactor is justified. Reuse the existing integration seam;
perform only a necessary small test-support/interface adjustment at the start of
T01, keeping the old regression suite green. Feature-gated candidate builds are
acceptable staging, but runtime old-wire fallback is not introduced.

T03-T06 can start after T01. T11 can start after the first physical slice and
terminal/control safety, without waiting for mixed-load qualification. Physical
bench runs and flashing share equipment and must be scheduled serially; that is
a resource constraint, not an artificial implementation dependency.

T08 is not a blanket blocker for T09-T12: a qualifying 256-byte profile can be
used without it. Any claim/test using 512 bytes requires T08 complete. If 256
cannot meet T09's target, finishing T08 becomes a genuine prerequisite to trying
512 there; do not mark the target achieved from the failing result. T13 requires
both supported sizes to have completed their applicable evidence.

T10 deliberately accepts a scoped no-go result because four-IMU polling is an
opportunity to measure, not a mandatory performance promise. T09 and T12 own
the accepted quality targets: a shortfall report does not complete their pass
criteria. Review material deficits before expanding scope or changing targets.

## Proposed tracker changes after approval

- Create these 13 issues in dependency order, each labelled `enhancement` and
  `ready-for-agent`. Hardware evidence still requires board access/operator help;
  the label is not a physical qualification or flashing authorization.
- Link all 13 as sub-issues of #200; retain a Parent reference in each body.
- Add native blocking edges exactly as listed above, replacing local ticket IDs
  with actual issue numbers. Do not add redundant transitive edges.
- Keep the conditional 512-byte prerequisite explicit in affected ticket bodies.
- Do not rewrite/close #200, update older tickets, or close/reopen any issue.
- When a native link operation is unavailable, retain explicit parent/blocker
  references and report the limitation rather than silently lose the dependency.

## Review requested

Does this granularity fit a fresh context per ticket? Are these only genuine
blocking edges? Should any tickets be merged or split before publication?
