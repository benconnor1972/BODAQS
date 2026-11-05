# IMU-session retrospective implementation

Implemented locally on 2026-11-05 (Australia/Perth), on
`integration/imu-acquisition-transport`. Review base:
`db88f93fce2d0c72d54306708e2fbb8e04d623e3`. Acquisition/runtime code and the
approved design remain unchanged; this follow-up changes validation tooling,
CI and agent guidance.

## Recommendations delivered

| Recommendation | Implementation |
|---|---|
| Firmware CI guardrail | `.github/workflows/firmware-ci.yml` runs existing logger/common/master/node/control/integrated/analysis suites, runner regressions and actionlint; Windows runs the UTF-8 smoke test. Target builds are a separate default-off manual job on a trusted SDK runner. |
| Earlier high-risk review | `implement-spec`, `implement` and engineering guidance point to the conditional firmware boundary checkpoint before dependents or packaging. Final whole-feature review remains. |
| Explicit operational scope | Build guidance separates offline builds, authorized device diagnostics and authorized flashing; implementation skills preserve the handoff's local/remote scope. Stale Arduino/CLI-later root guidance now points to current commands. Local upstream-skill adaptations are recorded. |
| Generated output isolation | All four host Makefiles use ignored `.build/` directories. The tracked logger executable is removed. Candidate validation no longer restores binaries in tracked paths. |
| Cheap preflight and late packaging | The runner provides preflight, host and full-candidate modes. Tool/SDK and 17 required test-import/version checks precede compilation/output; A8 vendor dependencies precede host compilation. Source archives are created after validation/source checks, and removed on archive/late-source failure. |
| Windows UTF-8 | `tools/Enable-Utf8.ps1` configures native text encoding in the calling process. `tools/Test-Utf8.ps1` checks independently constructed codepoints through PowerShell/Python stdin, stdout and a saved file. No user profile changes. |

Canonical commands, scope and runner provisioning are in
[firmware validation](firmware-validation.md). Candidate formats are documented
in [the candidate workflow](../firmware/CAN-FD_Software_Candidate_Bundle.md).

## Local validation

- Eleven public-runner/coverage regressions passed, including real temporary Git
  archives, partial archive failure, source mutation after archiving, missing
  dependencies and wrong versions in isolated virtual environments, and host
  validation with working edits and no SDK. The direct-analysis-import coverage
  check was also observed failing when Plotly was temporarily removed in memory.
- Windows PowerShell 5.1 UTF-8 roundtrip passed. Actual manual-workflow argument
  construction preserved a path containing spaces and skipped unset overrides.
- Actionlint 1.7.12 passed the workflow. Its downloaded release archive was
  checksum-verified; custom SDK-runner labels are declared in `.github/actionlint.yaml`.
- Full local host validation passed. Analysis: 588 passed, one skipped, seven
  warnings. Generated executables remained outside tracked paths.
- The final clean-source candidate passed all 14 recorded commands: A8 dependency
  bootstrap; full firmware/common/master/node host suites; control-apply and
  retained integrated-recording checks; analysis; four node/master profile builds;
  and clean A8. Analysis: 588 passed, one skipped, seven warnings in 72.73 seconds.
- A8 static RAM: 260460 bytes; flash: 2020561 bytes. Both TI targets built for
  bringup and acquisition. No device was accessed.

Exact tested source: `8871ae488ed374843efcae2da3e1024e633d86ff`, tree
`6d9516dd98c9e67d44be7c13890ba27022dff5de`. The manifest records clean tracked
source and unchanged HEAD after validation. This evidence document and its
navigation link were added afterward without changing executable/build inputs.

Retained local candidate:
`C:/Users/benco/dev/BODAQS-worktrees/retro-software-candidate-reviewed`.
All 72 SHA-256 inventory entries were independently verified.

- Manifest SHA-256: `4e40c7f4ceb2160f7658a84f579f962d92395d1d37bea27ce751a9140a0c3c8b`.
- Inventory SHA-256: `8738a77389f3465b9d6748903b0f75fab8c8c7c792700b18406bbe80d15b97fd`.

Two intermediate attempts were explicitly marked interrupted while review
findings were corrected. Neither created a source archive or is a passing
candidate. The reviewed candidate above supersedes them.

## Standards

Initial review found one P2: an archive failure or final source rejection could
leave `SOURCE.zip`, contrary to the documented failure contract. The final
failure path now removes only its owned archive while retaining diagnostics.
Both failure cases have regressions. Resolution review reports no open
standards findings or actionable smells.

## Spec

Initial review found one P2: enumerating Python distributions did not establish
dependency readiness. Preflight now validates required imports and canonical
versions. Follow-up identified omitted Plotly; it is included, with an independent
AST/distribution coverage check for pinned direct analysis/test imports. Linux
host CI also mirrors existing desktop analysis CI's Tk prerequisite. Resolution
review confirms all six recommendations and reports no open spec findings.

## External verification and retained debt

Workflow syntax and local equivalents were checked; GitHub Actions was not run.
Live CI requires later authorized publication. Full target CI additionally needs
the documented trusted `bodaqs-firmware` runner and its installed SDK/toolchains.
No push, PR, issue mutation, device probe, upload or flash was performed.
Physical qualification #175/#176 remains deferred, and production remote
admission remains unqualified pending measured bounds. Tooling validation does
not change those claims.
