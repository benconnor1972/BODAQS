# Firmware validation and agent workflow

Run from the worktree/branch in the active handoff. These validation commands
never discover, probe or flash a device.

## Offline checks and builds

Use Python 3.11+, GNU make, GCC/G++, PlatformIO and `requirements.txt`. Tool
options accept explicit installation paths; defaults look on PATH first, with
Windows TI defaults for full candidates. The runner installs explicit A8 vendor
dependencies before host tests consume their headers, using
[PlatformIO package installation](https://docs.platformio.org/en/latest/core/userguide/pkg/cmd_install.html).

```powershell
# Tools, test dependency imports/versions and selected TI SDK; no output/builds/downloads.
python firmware/tools/build_imu_software_candidate.py --mode preflight

# All existing host/native/analysis suites; working edits are allowed, no TI SDK needed.
python firmware/tools/build_imu_software_candidate.py --mode host --output-dir ../firmware-host-evidence

# Commit first; use a fresh directory outside the source worktree.
python firmware/tools/build_imu_software_candidate.py --output-dir ../firmware-candidate
```

Host mode produces test evidence, not target firmware or a release candidate.
Preflight imports the test/analysis dependencies listed in the runner and checks
their installed versions against `requirements.txt`. This catches missing
packages and broken imports before compiling; optional desktop/notebook
applications are outside this test-environment check.
Candidate mode requires the SDK, TI compiler and SysConfig, builds node/master
with both CAN profiles and clean A8, then archives source only after validation
and the source guard succeed. Preflight failure creates no output. Later failure
retains logs and a failed manifest without a source archive. See
[candidate evidence](../firmware/CAN-FD_Software_Candidate_Bundle.md).

For focused work use existing targets with compiler paths when needed:

For real-acquisition run specs, mixed/RX2 candidate profiles, immutable evidence
intake, exact snapshots and workspace status, use
[bench automation](../firmware/Bench_Automation.md).

```text
make -C firmware/test test
make -C firmware/can-fd/common/test test
make -C firmware/can-fd/master/test test
make -C firmware/can-fd/node/test test
python -m unittest discover -s firmware/tools -p test_candidate_runner.py
```

Makefile executables live in ignored `.build/` directories beside their
Makefiles. Runtime runners use temporary directories. Tests never rewrite a
tracked executable. Preserve unrelated work when preparing a clean run.
For a build only, select the environment explicitly, for example
`pio run -d firmware -e bodaqs_s3_mini_n4r2`.

## Boundary review checkpoint

Reach this checkpoint when changed code crosses any of these boundaries:

- ISR/task ownership, DMA buffers, publication or physical retirement proof.
- SDK/raw hardware representation versus normalized protocol identity/data.
- Finite identifier capacity across STOP, fence, release, restart or a new scope.

Before advancing dependent tickets or producing the final candidate, have a fresh
reviewer inspect that ticket's diff against its verified base. Give the reviewer
the governing contract and evidence showing which side of each boundary is real
in the tests. Confirm raw input representation, ownership/interleavings and
capacity/reset scope. Missing evidence is a finding to resolve, not an inference
from a passing adjacent suite. Add production adapter/lifecycle regressions for
concrete defects. Record the reviewed commit, findings and resolution in ticket
evidence, then retain the final whole-feature Standards/Spec review. Routine
changes do not need an additional checkpoint.

## CI and configured target runner

`.github/workflows/firmware-ci.yml` runs existing host/native/analysis checks for
firmware, analysis and configuration changes, plus Windows text roundtrips. Logs
and scenarios upload even after test failure. Existing desktop CI remains.

Full target builds use the separate manual, default-off `target_builds` input.
Provision a trusted Windows x64 runner with label `bodaqs-firmware`, GNU make/GCC,
MSPM0 SDK, TI ARM Clang and SysConfig. Repository variables `BODAQS_MSPM0_SDK`,
`BODAQS_TI_COMPILER`, `BODAQS_SYSCONFIG` and `BODAQS_MAKE` override local defaults;
PATH supplies other tools. The job uses the same candidate runner and accesses
no devices. It never runs on untrusted pull requests. A live GitHub run requires
later authorized publication. Runner labels follow
[GitHub's self-hosted runner selection](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow).

## Windows UTF-8 bridge

Prefer `apply_patch` for Unicode edits. For PowerShell native stdin/stdout,
dot-source the helper in the same process before the pipeline:

```powershell
. ./tools/Enable-Utf8.ps1
# Python file operations should specify encoding='utf-8'.
./tools/Test-Utf8.ps1
```

The helper configures this PowerShell process and inherited Python environment;
it never edits user profiles. The smoke test sends independently constructed
non-ASCII codepoints through native stdin, stdout and an actual saved file. It
catches question-mark substitution that valid-UTF-8 decoding alone misses.

## Device and publication scope

Build-only work ends at local artifacts. Probe only for an authorized device
diagnostic; flash an explicitly selected target/port under existing authorization.
See `skills/firmware-build/SKILL.md` for those conditional branches. Remote PR/issue
operations follow `docs/agents/issue-tracker.md` and the active user scope.
Compilation and host tests never satisfy physical qualification debt.

The [2026-11-05 retrospective validation record](retro-imu-validation.md) records
the local implementation, independent review resolutions and tested candidate.
