# Integrated IMU software acceptance (#174)

Software evidence, 5 November 2026. Based on verified integration
`1067258526a343bcfc10437e217a9b6d496c31ef` (#165–#173). The approved
[acquisition contract](CAN-FD_Acquisition_Transport_Contract.md), network Q71–Q147
and configuration baseline remain authoritative. No production behavior or public
interface changes were needed for this acceptance slice.

## Combined production path

`firmware/tools/test_integrated_imu_recording_runtime.py` compiles the existing
production master/control composition with actual `LoggingManager` start,
cancel, loop and stop functions, `AcquisitionControl`, four common node authority/
acquisition state machines, `RemoteImuRecording`, `RemoteImuStream`, native
catalog/writer and `RecordingStorageWorker`. It substitutes hardware register/
acquisition events, time, SPI delivery and filesystem I/O. It does not replace
the production lease, recording, transport or storage-owner state machines.

Real node SPI/capture/FIFO acquisition scenario 6 produces the source CAN trace.
The combined harness remaps that trace to four configured/present addresses;
these are four independent control/queue participants replaying known inputs,
not four physically independent sensors. The local producer uses a separate
native queue. The byte sink writes actual BDQ bytes and supports a deterministic
thread barrier and a returning one-byte-short write.

The five combined invocations cover:

| Scenario | Interaction and independently checked result |
|---|---|
| `good` | Actual operator preparation/START, four live streams, source recovery, one lost accepted-object ACK, and a 40 ms same-boot reply outage while receptions/retained fragments exist; normal STOP, fixed five-second tail, fence/release/exit and filesystem finalization. Each node retains exactly 794 rows: source segment 1 sequences 0–65 and segment 2 sequences 0–727, with known native origins and signed raw axes. |
| `stall` | Block the actual writer's byte sink on its sole storage-owner thread. Release a 500-row-per-node burst into real bounded master retention, continue lease/control service, queue another local row and issue actual operator STOP while I/O remains blocked. Nodes become terminal within 200 logical ms. Release I/O and independently verify every admitted row, no duplicate identities and exact loss-counter totals for every rejected input. Count-only management evidence remains explicit about unknown source ranges. |
| `short` | After real four-node traffic, return a one-byte-short storage write. The worker reports failure; actual controller stop/finalization preserves a readable CRC prefix without a successful footer and reports storage failure. A new start remains gated until ownership ends. |
| `cancel-open` | Cancel actual operator start while the owner is blocked opening storage. No PREPARE or START is authorized before the allocation/catalog barrier, acquisition never starts, and finalization waits for the outstanding owner. |
| `cancel-prepare` | Cancel actual operator start with storage already open and real remote preparation pending. No START reaches any node. Protected STOP, lease terminality, tail/fence/release and storage finalization complete. |

`good` and `short` then perform a second explicit operator start after production
idle reconciliation refreshes the acquisition-changed endpoint epochs. Storage
health is checked again, the recording ID advances to 2, and a fresh context is
required. Old START authorization and the retired context are rejected. The
second recording keeps a known local row and completes normal STOP/cleanup.
This does not claim an immediate restart can bypass configuration reconciliation.

## Independent oracles and retained evidence

`firmware/tools/verify_integrated_imu_recording.py` independently checks the
documented 32-byte file header, 20-byte chunk framing, 24-byte stream-data prefix
and payload CRCs against the analysis reader's public recovered records. A CAN
admission ledger is written at the ingress boundary, before downstream queues:
every admitted input identity must appear once, every rejected input contributes
to recorded loss totals. Literal known native origins, sequences, axes and source
recovery flags separately constrain that ledger. Before every committed sample
chunk, the prefix must contain its source BEGIN and applicable timing model,
including matching boot, clock epochs, origin, span and rational step.

Eight retained cut/corruption cases target essential and sample chunks. Every
case must recover exactly the complete records in the independently scanned
CRC-valid prefix, report damage, expose no dependent sample ahead of its
essential predecessor, and never advertise a successful final summary.

The retained directory includes generated CAN input, `*.bdq.input.tsv` ingress
ledgers, `*.bdq.control.tsv` actual CAN dispatch traces, good/failed/cancel/restart
BDQ files, damaged prefix/corrupt copies, runtime JSON and `results.json`.
Optional post-START snapshot OPEN/pages/RELEASE and retries share the actual
global four-request/second burst-four budget, checked from dispatch timestamps.
Runtime JSON records lease renewal gaps and terminal STOP checks. Unknown
physical timing/alignment remains unknown in catalogs and summaries; an expired
bridge never invents a master observation or bracket.

## Reproduction and scope of timing evidence

From the repository root, with host GCC/G++ and analysis dependencies available:

```powershell
$env:PATH = 'C:/msys64/ucrt64/bin;' + $env:PATH
python firmware/tools/test_integrated_imu_recording_runtime.py --output-dir C:/path/outside/source/acceptance
```

Without `--output-dir`, the fixture uses temporary files. The full logger host
Makefile also runs the combined fixture alongside all existing regression suites.

The fixture installs an explicitly synthetic admission profile through the
stopped-only host seam. Its time source advances one logical millisecond per
outer tick and per ten SPI slots, with twelve nonblocking control/coordinator
service turns per tick. No wall-clock timing assertion is used. The observed
bounded service is conditional on this injected envelope; it is not the
qualified 64 us slot cost, a throughput measurement or a physical lease-latency
result. An initially under-serviced host loop correctly saturated retention;
that fixture scheduling mismatch did not justify a production scheduler change.

Production still installs **no qualified remote scheduling profile** and rejects
remote admission as unsupported/unqualified before PREPARE. Desired rates,
configuration/effective-state, duplicate-address, no-op revision, migration,
mute and idle-recovery regressions are retained in the existing full suites.

## Reproducible candidate and remaining qualification

The [candidate runner](CAN-FD_Software_Candidate_Bundle.md) requires a clean
committed source tree and a fresh output directory outside the source worktree.
It records the exact source commit/tree and archive hash, commands, environment,
tool identities, logs, exit codes and artifact SHA-256 identities. It runs all
logger/common/node host suites, baseline apply regression, full analysis and
the retained combined fixture, then explicitly builds both G3507 node and G3518
master with `CAN_LINK_PROFILE=bringup` and `CAN_LINK_PROFILE=acquisition`, and
the production A8 `bodaqs_s3_mini_n4r2` image. Build artifacts are copied
immediately per target/profile; no stale successful image can mask a failed build.
The candidate's manifest/logs are the exact final-run evidence; a focused fixture
pass alone does not establish those full-suite or target-build results.

### Verified candidate

The complete runner passed on the clean committed source
`144175e07f1e614bbddff075016a48cf3b7ab19f`, tree
`73d9799c9d1401dfbb0709eaf1dab5b4f20a66e9`. The source guard confirmed the same
HEAD and no tracked changes after validation. The retained bundle is
`C:/Users/benco/dev/BODAQS-worktrees/imu-software-candidate-174-complete`.
The later evidence-only documentation commit does not change the tested firmware,
analysis, runner or verifier sources.

| Validation | Result |
|---|---|
| A8 dependencies | Explicit PlatformIO package installation succeeded before host fixtures consumed vendor headers. |
| Full firmware host/runtime target | Passed, including all original control/configuration/storage regressions and the combined acceptance fixture. |
| Common protocol/link host target | All 14 binaries passed. |
| Node adapter host target | SPI/capture binaries and acquisition scenarios 1–12 passed. |
| Control-apply runtime | Passed. |
| Retained combined recording | Five scenarios, two explicit restarts and eight cut/CRC cases passed; normal/recovery renewal gaps were 107/113/111/116 logical ms per node, and stalled-write gaps were 107/113/111/108 ms. |
| Full analysis `python -m pytest -q` | 588 passed, one skipped, seven warnings in 83.64 s. The retained log records the skip count and existing dependency/pandas warnings. |
| TI G3507 node / G3518 master | All four explicit target/profile builds passed with forced rebuilds. |
| A8 `bodaqs_s3_mini_n4r2` | Clean and production build passed; RAM 260460/327680 bytes, flash 2020553/4063232 bytes. |

The Windows run skips
`test_default_import_agent_app_config_path_uses_macos_convention`; its existing
`skipif(os.name == "nt")` reason explains that POSIX path resolution is anchored
to a drive letter on Windows. That reason remains in the archived test source.

Actual TI link-map allocation, including each reserved 2048-byte stack:

| Target/profile | FLASH bytes | SRAM bytes |
|---|---:|---:|
| G3507 node, bringup | 41504 | 13169 |
| G3507 node, acquisition | 41456 | 13169 |
| G3518 master, bringup | 41344 | 62139 in bank 0 |
| G3518 master, acquisition | 41352 | 62139 in bank 0 |

The master maps report 3397 unused bank-0 bytes and unused bank 1. These static
allocations establish neither stack watermarks nor runtime heap headroom.
Observed tool identities include GCC/G++ 16.2.0, Python 3.11.9, TI ARM Clang
5.1.1 LTS, SDK 2.11.00.07, SysConfig 1.28.1+4785, PlatformIO 6.2.0 and Espressif
32 platform 6.13.0. Complete compiler/framework/library identities and command
arguments are retained in `logs/` and `BUILD_MANIFEST.json`.

All 70 entries in the retained SHA-256 inventory were independently rechecked.
Key bundle identities are:

- `SOURCE.zip`: `ab2491c26d4f0c0c3c2f7f98b018f6246708d703ead5f382efe6a0165b5945ab`.
- `BUILD_MANIFEST.json`: `ebed5f638495a6fa612f8ae59eeb91b84f54162735ed322fe8d7ff6dd5900d62`.
- `SHA256SUMS.txt`: `478c51a5a6f809b8ec808121af0b2cd0cb4af88b3db7636f8352911486a5acce`.
- A8 application `firmware.bin`: `c5bd679fa7d876c102d89da8ac632a77eb2e13328d98364823575894a3a3e282`.

The manifest identifies each TI `.out`/map and A8 ELF/application/bootloader/
partition artifact by exact target, link profile, byte count and SHA-256. The
inventory additionally covers every log, input/dispatch ledger, BDQ result and
damaged prefix. Earlier interrupted/missing-dependency attempts have non-passing
manifests and are not this verified candidate. Integration merge and the final
independent Standards/Spec review are recorded separately in the implementation
index.

Physical qualification [#175](https://github.com/benconnor1972/BODAQS/issues/175)
and fault qualification [#176](https://github.com/benconnor1972/BODAQS/issues/176)
remain deferred and unexecuted: FIFO/DRDY/SYNC association, 25 us rearm, 100 us
shared-SPI occupancy, four-node throughput with mixed ADC traffic, measured
lease latency, timing/phase/drift and 10 us alignment, electrical reliability,
runtime stack/heap headroom, disconnect/reconnect, CCS halt/resume and node/master
reset bench scenarios. Static link maps are not runtime watermarks. No probe,
flash, bench-pass claim, readiness advertisement, remote publication or issue
state change follows from a software candidate.
