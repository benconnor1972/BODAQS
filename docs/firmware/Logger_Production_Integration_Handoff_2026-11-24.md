# Production integration handoff and repository cleanup

The user confirmed on 2026-11-24 that the completed production-integration pass
must land on **feat-CAN-firmware** (the existing, case-sensitive branch name).
Use a dedicated integration branch/worktree for implementation, then integrate
the completed, validated work back onto that destination. This checkpoint does
not implement firmware, publish tickets, or declare a release qualified.

## Requirements and starting point

- [Confirmed integration decisions](Logger_Production_Integration_Decisions_2026-11-23.md),
  including Q25-Q32 on unified ADC timing and faster idle reconciliation.
- [Production-readiness review](Logger_Production_Readiness_Review_2026-11-23.md).
- Root GLOSSARY.md defines desired/effective configuration, reconciliation,
  acquisition and recording membership.
- Existing production destination before this documentation checkpoint:
  `b8407363a4b07e114e4b39dfd95fd5073a1c64c9`.
- `fix/a8-rtc-autodetect` and release tag `firmware-v0.6.2-beta` remain separate
  references. Review that release's RTC delta during integration; this housekeeping
  does not merge or discard it. Unrelated application/documentation branches stay
  outside this cleanup.

## Prototype provenance

Use selected behavior from sealed prototypes, not a wholesale merge of competing
experimental branches. Most recent selected timer candidate is
`BODAQS-worktrees/adc-timer-1x1000-3333-r133/SOURCE.zip`, SHA256
`e36bc97680b1b189ac23d49bcfe1c5f9ca6ad7faa775ec0aafbe0ed8c8f4b067`.
Its manifest, four-file delta, host checks and hardware assessment accompany it.
Its historical source_commit field is not a commit containing the final candidate.

Native-profile node candidate is in `imu-native-1667-r127`: source archive SHA256
`82e5dac97ea36b7592dd451e30e22195c9b627c2f10c410525555de4c515bf64`,
node image SHA256
`57fd4d49ead43016a1faacb8eef09bdee041dd576a4496ea68bf1239f6d767c8`.
It supports nominal833/1667/3333 profiles. The unchanged selected master image
SHA256 is `57cfec7268800f4ea28f7024c6bc4e2d4002cb69dfdd32f5a64d07cebc8a727b`.
Existing kits retain source, build recipes, images, tests and results separately.

R133 demonstrated a clean short run of two1000Hz ADC channels total plus four
3333Hz CAN IMUs: zero missed ADC slots/reused readings and complete source-bounded
IMU delivery. Admission, sustained validation, flexible channel planning and the
remaining production integration are still required. A selected bench candidate
is not a production release, and benchmark/runtime boot machinery is not a product
requirement to retain.

## Local cleanup preservation

Recovery archive is external to this repository:
`../BODAQS-worktrees/drain-capacity-evidence/production-integration-prep-2026-11-24/`.
It records original refs, worktree identities/status, binary working/index patches
and hash-verified copies of changed/untracked files. It is a **private local**
recovery artifact, not material to publish; source/configuration evidence can
contain private settings. Root hardware design history is excluded from that
snapshot and remains untouched in place.

Superseded local experiment branches may be removed only after their commits are
recoverable through archive refs/bundle and the original branch-to-commit map.
Old source worktrees remain at their existing paths, detached, because test and
handoff documents refer to those paths and some contain unique uncommitted work.
No source directory, recording, sealed kit or assessment is deleted by this pass.
Prune only the registration for the already-missing temporary build worktree.
No remote branches are deleted, no remote refs updated and nothing is pushed.

The archive's PLAN.json and cleanup receipts contain the exact local branch list
and actual outcome. Archive tags preserve the experimental history frontier;
the full branch map preserves individual round names. Keep working branches
focused on production, the new integration work and unrelated active features.
