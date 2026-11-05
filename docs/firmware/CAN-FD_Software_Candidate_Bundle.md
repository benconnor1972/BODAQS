# Local acquisition software candidate bundle

`firmware/tools/build_imu_software_candidate.py` runs software acceptance and
builds a local candidate for #174. It never uploads, probes, flashes, publishes
or updates GitHub. Physical qualification #175/#176 remains deferred.

Commit the source first, then run from the selected worktree:

```powershell
python firmware/tools/build_imu_software_candidate.py --output-dir C:/Users/benco/dev/BODAQS-worktrees/imu-software-candidate
```

For tool/SDK checks only, use `--mode preflight` without an output directory.
For host/native/analysis validation with working edits and no TI SDK, use
`--mode host --output-dir ../firmware-host-evidence`. Host mode produces logs,
scenarios and a host-validation manifest, without target images or source archive.
The default remains the full, clean-source candidate mode below.

Select a fresh output directory **outside** the source worktree. Existing output
is never overwritten. Tracked changes and untracked files outside `.scratch/`
prevent a run: a commit alone cannot identify uncommitted build inputs. Close
other writers to that worktree during acceptance. The final manifest also fails
the candidate if tracked source or HEAD changes during execution.

Default host tools are discovered on PATH, with local Windows fallbacks. TI
installation defaults remain explicit Windows paths. `--make`, `--cxx`,
`--cc`, `--sdk`, `--ti-compiler`, `--sysconfig`, `--pio` and `--jobs` select other
installed tools explicitly. `--list-commands` prints the plan without creating
files or running tools. No device-dependent `build.sh check` or `detect` runs.
Tool/SDK and required Python test dependency preflight runs before output creation.
A8 dependency bootstrap and all
validation/build commands run before archiving; a failed validation retains its
logs without paying for the large source archive.
If archiving itself fails or the final source guard rejects the run, the owned
complete/partial archive is removed while its failed manifest and logs remain.

The runner executes the full firmware host target, common protocol/link tests,
master timing and raw MCAN/CS-preemption adapter tests, all node adapter scenarios
(including recording turnover beyond 255 and within-recording exhaustion), the
control-apply regression, combined recording
acceptance with retained BDQ scenarios, and the full analysis suite. Host targets
are forced to rebuild. It builds node G3507 and master G3518 separately for both
`bringup` (500 kbit/s / 2 Mbit/s) and `acquisition` (1 Mbit/s / 4 Mbit/s), copying
each profile's `.out` and `.map` before switching. Finally it builds the explicit
logger environment `bodaqs_s3_mini_n4r2` and copies its ELF/application/bootloader/
partition files. These are separate images; the bundle is not a merged flash
image. Endpoints on the same bus must use the same link profile.

Outputs include:

- `BUILD_MANIFEST.json`: status, exact source commit/tree, board/profile settings,
  command arguments/working directories/exit codes, observed tool identity logs,
  copied artifact sizes/hashes and deferred physical gates.
- `SOURCE.zip`: the committed tree, and `MSPM0_SDK_PRODUCT.json`: selected SDK
  identity. Build logs retain PlatformIO platform/framework/dependency versions.
- `logs/`: every test/build and tool version command's complete combined output.
- `artifacts/`: profile-specific TI outputs and explicit A8 images/map.
- `scenarios/`: combined fixture files and independent interpretation results.
- `SHA256SUMS.txt`: SHA-256 of every other bundle file, including the manifest,
  source archive, logs and scenario evidence.

A nonzero command stops the run, leaves its log and a **failed** manifest, and
returns nonzero. Inspect `status`; the presence of artifacts alone never implies
success. Host executables live in ignored `.build/` directories or temporary
directories; no tracked executable is rewritten or restored by validation.

This is a software candidate only. Production remote admission remains explicitly
unqualified until real scheduling bounds are supplied. Synthetic host profiles
do not establish FIFO/DRDY association, SPI/SYNC timing, electrical behavior,
measured phase/alignment, sustained four-node throughput, lease latency or runtime
stack/heap headroom. The [implementation index](CAN-FD_Acquisition_Transport_Implementation.md)
and #174 evidence distinguish software acceptance from that physical debt.
