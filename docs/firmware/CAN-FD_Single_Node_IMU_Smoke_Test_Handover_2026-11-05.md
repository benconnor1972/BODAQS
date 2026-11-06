# CAN-FD single-node IMU smoke-test handover — 5 November 2026

## Current outcome

**Sustained on-device IMU recording remains broken.** Authorization/START and
initial native sample persistence work. Recent runs persist a few hundred
consecutive IMU samples, then the master's stage-6 reception retention queue
overflows, loses essential interpretation metadata, and the logger correctly
excludes the IMU. Healthy/local scheduling continues.

The latest node change fixed a separately confirmed defect: old raw SYNC
observations and their idle loss count were carried into a new recording.
The latest physical run confirms that correction, but still fails at stage 6.
Do not describe the overall smoke test or throughput qualification as passed.

The user is moving to a new chat. No further bench run has been requested at
handover. Continue the investigation with the saved evidence before requesting
another firmware installation. No work continues automatically after a final
chat reply; do not imply a background investigation is running.

## Workspace and source state

- Actual working tree: `C:/Users/benco/dev/BODAQS-worktrees/can-control-integration`.
- Branch: `integration/imu-acquisition-transport`.
- HEAD: `f200b91a94dbc4d0785d5c753498d6ae6c6d14de`.
- The default IDE/root context may instead be `C:/Users/benco/dev/BODAQS`.
  Run commands in the actual worktree above.
- All bench fixes are **uncommitted**. Preserve the dirty tree; do not reset,
  clean, overwrite it with an older bundle patch, or commit without instruction.
- Preserve existing untracked `.scratch/imu-acquisition-transport/` and
  `.scratch/retro-improvements/`, as well as the diagnostic logs/base snapshots
  created during this investigation. Do not alter unrelated root worktree assets.
- `firmware/tools/test_master_irq_vector.py` is a new untracked source file.

Read the repository/user AGENTS instructions, `docs/agents/engineering.md`,
`docs/agents/firmware-validation.md`, `.agents/skills/diagnosing-bugs/SKILL.md`,
and `skills/firmware-build/SKILL.md`. Use the reproducer-first diagnosis loop.
The validation instructions require fresh review for changes crossing hardware,
ISR/owner, publication or finite-identity boundaries. Such reviews were performed
for the recent changes; each applicable bundle contains `REVIEW.md`.

No device has been accessed or flashed automatically. The user installs logger
images manually on COM9 and node/master images through CCS. No commits, issue
closures or remote publication were performed.

## Firmware currently installed

Bundle directories are siblings of the worktree, under
`C:/Users/benco/dev/BODAQS-worktrees/`.

| Target | Current bundle | Hardware/profile |
|---|---|---|
| Logger | `single-node-imu-smoke-partial-head-fix` | A8 ESP32-S3 Mini N4R2; `bodaqs_s3_mini_n4r2_imu_smoke` |
| Master | `single-node-imu-smoke-master-can-drain-fix` | MSPM0G3518; acquisition CAN link profile 2 |
| Node | `single-node-imu-smoke-node-sync-scope-fix` | MSPM0G3507; acquisition CAN link profile 2; incorporates FIFO-order fix |

Exactly one unmuted remote IMU is configured (`imu0`, provider `can:0`, endpoint
`imu`, profile `imu6_3333_32g_2000dps_v1`). Local sensors were removed. The logger
environment is explicitly an **unqualified single-node bench build**, not a
production admission or multi-node qualification result.

Each bundle has its own README, manifest, hashes and source patch. Preserve the
bundles. Earlier fixes are cumulative within the applicable current image.
Node/master image changes invalidate assumptions about old hardcoded debugger
addresses; use the replacement ELF/map and symbols. Use `gMasterRuntimeInfo` on
the master and `gNodeRuntimeInfo` on the node, with the correct CCS target selected.

## Evidence retained for the next chat

Local evidence directory, independent of the removable SD card:

`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-handover-2026-11-05/`

It contains the six BDQs below, full available serial captures for 172231,
175440 and 181608, a copy of this handover, a cumulative tracked-worktree patch,
the untracked IRQ-vector test, and `EVIDENCE_MANIFEST.json`. Original files on
`E:/` and the attachment directory were left unchanged. The live worktree is
canonical; the snapshot patch is a backup, not something to reapply to it.

| BDQ | Persisted IMU samples | Immediate loss evidence | Remote cleanup in summary |
|---|---:|---|---|
| `261105_164129.bdq` | 65, consecutive | stage 6: 10 source samples + 1 evidence record, essential loss | false |
| `261105_170122.bdq` | 0 | stage 5: 3 evidence records, essential loss | true |
| `261105_172231.bdq` | 150, consecutive | stage 6: 42 source samples + 1 evidence record, essential loss | true |
| `261105_173532.bdq` | 275, consecutive | stage 6: 37 source samples + 1 evidence record, essential loss | true |
| `261105_175440.bdq` | 382, consecutive | stage 6: 370 source samples + 2 evidence records; also stage-4 idle SYNC losses 236 | true |
| `261105_181608.bdq` | 317, consecutive | stage 6: 150 source samples + 1 evidence record, essential loss | false |

These files had no reader-detected integrity errors. Stage 5 is the master CAN
capture/ISR queue; stage 6 is the later master reception retention queue. Counts
of dropped CAN frames and lost six-axis source samples are different units.

`clean_shutdown=true` means the file closed cleanly. It does **not** prove remote
cleanup or complete IMU tail coverage. Summary `remote_cleanup_complete=false`
can precede later successful serial finalization. Do not infer a permanent Busy
regression from that field alone. The latest capture ends without demonstrating
later cleanup completion. Excluded runs report incomplete tail coverage.

The recurring `[PROD] samples/s=500` reports the local/primary scheduler, **not**
CAN IMU sample throughput. Primary rows with no local sensor columns are not
evidence of successful IMU acquisition. Native sample ticks are model-derived
and marked timing-degraded/estimated; they are not physical timing qualification.

## Latest run: 261105_181608

- File opened at logger uptime 27243 ms; local logging start returned at 28087 ms.
- START succeeded. First stream failure observed at 28445 ms:
  `phase=6 cause=3 action=1 result=2 reason=0`.
- 16887 primary rows, 317 IMU rows (sequences 0..316, no gaps), 36 timing rows.
- IMU native ticks 27880102..27979997.
- Only raw node SYNC observation in the file has tick 27979146: it belongs to
  this recording, unlike the old 0.079..0.679-second backlog.
- No stage-4 historical SYNC-loss report; the SYNC-scope correction is physically
  confirmed. Stage-6 loss remains: source deltas 10 and 140, evidence delta 1,
  followed by essential-metadata boundary reason 31.
- First-failure transfer error mask is 256 (Busy code 8), three transfer errors.
  Earlier runs with mask zero failed the same way, so Busy is not an established
  cause of the retention deficit.
- `clean_shutdown=true`, remote excluded, remote cleanup false, tail incomplete.

Retained `[DRAIN]` timing snapshot:

```text
window_us=1195983 slots=2480 failed=4 empty=1613
exchange_us=391299 max_exchange_us=505 max_idle_us=1741
polls sample=327 evidence=91 control=508 protected=775 shared=259
fragments=283,68,59,196,17 deferred=2368,1139
```

These counters cover the measurement context including entry/PREPARE, **not a
steady recording-only interval**. Empty replies during preparation are expected;
do not conclude that their percentage represents spare recording bandwidth.
Exchange duration includes guard, shared-bus wait, physical transfer and decode.
Fragment counts include duplicates. Four failed slots commonly appear during
entry/preloaded-format transitions; these are distinct from master RX drops and
from the retained transport-error counter. Timings wrap at 32-bit microseconds;
the short bench windows are well within that interval.

Earlier master snapshots confirmed ingress capacity/high-water 128/128 with
18 drops, then 3 drops in a later run. SPI RX queue capacity is 1 and cumulative
drops have been 1339, 1659 or much higher on older builds. CAN capture queue
capacity is 8; one run had hardware loss, another had zero CAN hardware/software
losses and high-water 6/8 despite stage-6 overflow. Cumulative counters do not
date each loss or establish active throughput. Do not calculate active rate
from a late uptime divided into boot-lifetime counts.

## Implemented corrections and important source locations

The detailed bench history is appended to
`docs/firmware/CAN-FD_Single_Node_IMU_Smoke_Test.md`.

1. **Master default IRQ handler:** GPIO exception 17 reached Default_Handler;
   TI vector uses `GROUP1_IRQHandler`, not the previous `GPIOA_IRQHandler`.
   Fixed in master `src/main.c`, with linked-ELF vector regression.
2. **Measurement mode entry/retirement:** TI SPI BUSY includes unsent TX FIFO
   bytes after a 64-byte transaction in an 84-byte DMA buffer. Removed the
   inappropriate BUSY retirement guard; inactive CS and actual RX progress
   govern boundary retirement. Failed logger mode entry now reaches explicit
   unavailable-context cleanup rather than holding ownership forever.
3. **Control retries and delayed status:** outgoing two-fragment order alternates
   0,1,1,0 to escape alternating physical RX loss; legacy exchange fetch budget
   is four. Mode-status inspection retains its correlated token across calls
   for up to 300 ms instead of abandoning every delayed reply.
4. **Lost control-result ACK:** Busy/8 preserves an immutable pending outgoing
   request and its original deadline; only an already-admitted same-context
   inbound result can have its RAM ACK replayed. Other errors are unchanged.
5. **Clock-boundary timeout:** request creation can occur after the service's
   `now` snapshot. Timeout comparison now samples `millis()` after creation,
   avoiding unsigned subtraction underflow and immediate START timeout.
6. **FIFO timestamp ordering:** captured sensor FIFO words were timestamp,
   gyro, accel with a common 2-bit slot counter. The parser incorrectly required
   timestamp last. It now stores the slot timestamp and accepts valid orderings
   while preserving tag/counter/duplicate guards (node scenarios 14/15).
7. **Independent empty-head timers:** sample/evidence polling shared one per-node
   timer, letting an empty evidence probe starve a waiting sample head. Timers
   are now per data class/node. Idle control selections repeat twice before
   rotating to avoid aliasing with alternating request loss.
8. **Master CAN batch draining:** `service_can_receive()` now pops up to eight
   records per turn, instead of one. A modeled eight-frame burst, one service
   turn, then four frames went from three essential drops to zero. Tests prove
   bounded work under ISR refill, IRQ-enabled decode and raw ID normalization.
9. **Fragment polling pipeline:** prior-MOSI hint avoids immediately repeating
   a missing data fragment whose response may be in flight. It never marks data
   received; final gaps are retried. Recovery clears the hint. CRC/admission/ACK
   rules remain unchanged.
10. **Continue partial head:** sample/evidence share one ordered master head per
    node. Seven lines in `CanMasterManager.cpp` redirect a data turn to the
    other class's incomplete object at the same node when appropriate. Header,
    control priority, received masks, CRC, ACK and idle backoff are unchanged.
11. **START-scoped SYNC observations:** node backend START calls the new internal
    `bodaqs_node_capture_sync_discard()` and clears `a.sync_present`. Under saved/
    restored PRIMASK the helper retires old SYNC ring entries/loss/latest-pending
    state and clears only pending timer CC3. It preserves clocks, ordinals,
    DRDY, rollover and faults; live subsequent losses still count. Latest run
    confirms the old SYNC backlog is gone.

Diagnostics also retain first remote failure through cleanup, add serial Busy
details, `transfer_error_mask`, and BDQ `remote_failures[].transport_timing`.
OLED active count includes unmuted remote endpoint assignments (not six axes).

Hotspots:

- `firmware/src/CanMasterManager.cpp/.h`: transport scheduling, timing counters,
  recovery, mode inspection, fragment/ACK handling.
- `firmware/src/AcquisitionControl.cpp`: owner task, eight service calls then
  `vTaskDelay(1)`, protected priority, data/control selection and timeouts.
- `firmware/src/RemoteImuRecording.cpp/.h`: participants, consumer admission,
  first failure, stop/tail/fence/release/exit and retained timing snapshot.
- `firmware/can-fd/master/src/main.c`: physical SPI retirement, one-slot SPI RX
  queue, eight-entry CAN queue and bounded CAN service.
- `firmware/can-fd/common/protocol/bodaqs_master_service.c`: shared ordered
  reception head, 128-entry ingress, loss stages and immutable batch ACKs.
- `firmware/can-fd/common/protocol/bodaqs_measurement.h` and
  `bodaqs_fragment_transport.h`: wire and object CRC/fragment algorithms.
- `firmware/can-fd/node/src/imu_acquisition.c`, `imu_capture.c/.h`: node FIFO,
  raw captures, START scope and source/evidence generation.

## Test evidence and limits

Relevant tests passed at their latest corresponding source changes:

- Node capture/SPI and acquisition scenarios 1..16; scenario16 injects 243
  pre-START SYNC captures (seven retained, 236 lost), checks a fresh capture,
  snapshot scope and subsequent recording turnovers.
- Node IRQ stubs now model PRIMASK. Tests check masked CC3 clear/restoration
  from incoming 0/1, preservation of pending/queued DRDY and clock distrust,
  capture ordinal continuity and continued live overflow counts.
- Master timing/adapter tests: bounded bursts, refill during decode, raw MCAN
  overflow, CS preemption and generation/context physical retirement.
- Measurement transport, normal/smoke lifecycle, ownership/control, both
  alternating physical RX-loss phases, delayed status, ACK loss, failed entry,
  reboot/bus-off/lease-expiry exclusion and verified cleanup.
- Integrated recording/native-ledger/storage tests with real node FIFO producer.
- Relevant TI acquisition builds, logger PlatformIO build and master linked
  GPIO vector check; fresh scoped independent reviews found no outstanding issues.

The strengthened measurement drain fixture injects two five-sample CAN packets
every 3 ms and four evidence records every 100 ms. At four service turns/ms,
the old code overflowed within three injected seconds. Current partial-head
scheduling passes ten seconds: 7041 CAN records before tail, high-water 39,
zero drops, all 7068 produced records after tail. Actual exchanges are 27243
(27244 with one lost fragment). Idle probes subsequently stay within
11/class/200 ms. This is **synthetic scheduling**, not hardware qualification.

An exploratory lower three-turn schedule still overflowed. An attempted activity
window that bypassed idle backoff passed that lower-budget test, but review
identified conflict with the documented empty-probe budget; it was removed.
Do not silently reintroduce it or increase a synthetic budget just to pass.

Some integrated tests feed CAN frames with deliberately generous pacing. They
prove protocol/ownership/persistence correctness, not sustained physical rate.
The master adapter test mocks downstream decode. The actual device still loses
essential metadata despite passing these host tests.

## Recommended continuation

1. Confirm source and installed image combination above; read saved latest logs.
2. Establish a timing/buffering model that distinguishes PREPARE from active
   acquisition. Current context-wide timing counters do not isolate steady
   data drain. Consider an active-phase baseline plus master service-cost/RX-loss
   measurements before changing clocks, pacing or queue sizes again.
3. Investigate why useful on-device drain is below the passing synthetic model:
   actual fragment duplicates, idle probes/head transitions, protected/control
   time, task yield, SPI queue overruns and master processing/interrupt cost.
4. One untested lead from the last source inspection: wire CRC and fragment CRC
   are bit-at-a-time implementations. Profile their target cost before claiming
   they cause the deficit or replacing them. The generated master configuration
   specifies **80 MHz CPUCLK_FREQ**, not 32 MHz. No CRC optimization was made.
5. Preserve fail-closed exclusion on essential metadata loss, authorization,
   finite IDs, RAM ACK/admission ownership and shared-SPI/ADC opportunities.
   Enlarging retention alone does not establish sustainable throughput.
6. Reproduce each new defect at an appropriate real boundary; run focused tests,
   target build and required fresh review. Package a concrete, separately named
   target-only bundle for the user's manual install; retain prior bundles.
7. Physical acceptance remains an entire motion recording with persisted IMU
   data, interpretable timing evidence, no essential-metadata exclusion, then
   completed cleanup and usable Wi-Fi. Multi-node and production qualification
   remain outside this bench task.

## Continuation after this handover (offline; no device update)

The stage-6 investigation continued in the same dirty worktree. Installed device
images and the physical outcome above are unchanged. The appended section
"Stage-6 drain investigation: offline continuation" in the smoke-test document
records the complete findings and diagnostic field semantics.

- `.scratch/stage6-drain-investigation/run_feedback_matrix.py` reproduces
  essential stage-6 loss at three synthetic turns/ms, and with alternating SPI
  request loss at eight turns/ms in either phase. The four-turn no-loss control
  still passes. This exposes a missing adapter/loss boundary in the passing host
  capacity model, not proof of the actual device's loss cadence.
- `profile_master_elf.py` executes the installed master ELF offline with Unicorn
  and derives offsets from DWARF. A steady empty sample poll uses 8444 executed
  instructions, 5940 in wire CRC source lines. The full-batch sealing ingress
  call uses 56706 instructions, 54676 in the logical checksum function. Counts
  are not physical cycles/times. Dependencies are isolated in the adjacent venv
  (Unicorn 2.1.4, pyelftools 0.33; capstone 5.0.9 is installed but not required).
- A master-only **diagnostic**, not a drain fix, is packaged in sibling
  `single-node-imu-smoke-master-drain-profile`. Its new `gMasterDrainInfo` captures
  START-admission-window service costs, accepted polls, produced replies and
  loss deltas, then freezes at the first retention drop/STOP/identity change.
  START admission is not physical START. Timings include instrumentation effects;
  sampled queue maxima are not guaranteed peaks. Keep the current logger/node.
- New tests cover diagnostic scope, reset, wrap, distrust, first-loss freezing,
  late CAN arrival and reply-buffer publication. Review found and resolved three
  diagnostic issues; isolated faulty variants are red. Existing master,
  measurement, integrated recording and target/vector checks pass.

No CRC, scheduling, clocks, queue capacities, wire formats or ACK/authorization
behavior changed. No device was accessed/flashed and no commit was made.
Next physical evidence is a normal motion run using the diagnostic master,
complete serial/BDQ, then both debugger structs after stop/cleanup. The existing
logger `[DRAIN]` counters still include PREPARE; do not derive steady throughput
from them. Sustained acquisition remains unresolved.

## Later physical evidence and pending CRC comparison

The user subsequently ran the diagnostic master and supplied
`261105_205838.bdq` plus `gMasterDrainInfo`. This supersedes the earlier statement
that no diagnostic bench run has occurred; the original installed-image table
describes the initial handover. The diagnostic snapshot and BDQ match context
8762878483939338580. Evidence is preserved under
`.scratch/stage6-drain-investigation/bench-205838/` and the adjacent context JSON.

The valid 258629us START-admission window ends at the first stage-6 drop:
150 new SPI RX drops, zero new CAN capture losses, 165 retained CAN records,
ingress 128/128. Mean status refresh is 87.5us and SPI processing 195.9us
(maximum 1465us), over 401 calls. This supports a master service-cost/request-loss
lead; it does not prove alternating physical loss or an exclusive CRC cause.
The BDQ persists 412 consecutive IMU samples, then reports 137 lost source
samples and one evidence record before essential-metadata exclusion. No integrity
errors or retained transport errors occur. Clean file closure does not prove
remote cleanup; its summary is false/incomplete and serial ends at file close.

A wire-compatible byte-table CRC change is now implemented in the two shared
measurement/fragment headers. It preserves all formats, integrity gates, ACKs,
status refresh, scheduling and capacities. Independent zlib checks pass under
C/C++, all focused host suites and both target builds pass, and fresh review
finds no outstanding issues. Target ELF instruction counts fall 61.1% for an
empty sample poll and 71.6% for full-batch sealing; these are not physical timings.
The master adds flash-only tables, with no RAM growth or constructor.

The next **uninstalled** master-only comparison bundle is the sibling
`single-node-imu-smoke-master-crc-table`. Keep the current partial-head logger and
SYNC-scope node. Repeat the same physical recording and collect both debugger
structs with expanded histograms after stop/cleanup, plus BDQ/serial. The full
semantics and results are in the smoke-test document's "Measured active deficit
and CRC comparison image" section. Sustained stage-6 drain remains unresolved
pending that comparison. No device was accessed/flashed by the agent; no source
commit or remote publication was performed.

## Latest physical run and next comparison: 261105_211914

The CRC master has now been physically exercised; the preceding "uninstalled"
CRC comparison statement describes the earlier handoff. The new BDQ/serial and
both debugger structs are saved in `.scratch/stage6-drain-investigation/bench-211914/`.
Context 11477279701755020739 matches. There are 784 consecutive IMU samples,
then stage-6 loss of 50 source samples and one evidence record, and essential
exclusion. Integrity checks pass; summary cleanup/tail remain incomplete and
serial ends at file close. No later cleanup completion is demonstrated.

The valid 363483us first-loss window has 117 new SPI RX drops, no new CAN capture
loss, 227 retained CAN records and ingress 128/128. Mean SPI processing falls
from 195.9 to 87.6us (maximum 1465 to 590us), confirming a physical benefit from
CRC work reduction. Status refresh remains 87.2us/request across 706 calls.
Do not claim sustained capacity from either improvement or persisted sample count.
Later lifetime bus-off/error counters and front-power-fault/buck-readback flags
are recorded but do not date an electrical event to this frozen active window.

The next **uninstalled** master-only image is in sibling
`single-node-imu-smoke-master-inventory-generation`. It adds only a generation
check after live status refresh, avoiding repeated copies/publication of an
unchanged main-owned inventory. All accepted relevant inventory changes still
advance generation and force publication. New real status/inventory/control
tests are red before the guard and green after, including same-dispatch duplicate
fencing, context reset, service reset and generation wrap. Fresh boundary review,
focused regressions, target build and actual linked vector check pass.
An offline target instruction probe reduces unchanged status work 4292 to 423;
this is not a physical latency or drain qualification result.

Keep the installed logger/node. Next evidence remains a normal motion recording,
complete serial and both debugger structs after stop/cleanup with expanded
histograms. Sustained stage-6 acquisition is still unresolved. Prior bundles,
source/evidence bases and dirty edits are preserved; the agent accessed/flashed
no device and made no source commit or remote publication.

## Latest physical run and logger comparison: 261105_213917

The inventory-generation master has now run physically. The next "uninstalled"
image statements above describe prior handoffs. Evidence including all supplied
histograms is in `.scratch/stage6-drain-investigation/bench-213917/`.
BDQ context 6988146453469253922 matches: 1206 consecutive IMU samples, then 80
source samples and one evidence record lost at stage 6 and essential exclusion.
Integrity checks pass. Remote cleanup is true, while IMU tail remains incomplete.
Serial shows later administrative finalization, not Wi-Fi enable qualification.

The valid 448031us first-loss window has 166 new SPI drops, zero new CAN capture
loss, 282 retained CAN records and ingress 128/128. Status refresh now averages
11.5us versus 87.2us, confirming the previous change worked physically. SPI
processing averages 88.4us/max590us. Its histogram is 0/851/147/12/0 for buckets
<=50/100/250/1000/>1000us. Sustained recording remains broken.

ACK-loss-only probes pass even at every-second data ACK loss. A new two-exchange
response-delay probe overflows with the old one-previous-poll hint at the unchanged
four-turn budget. A per-partial-object request-sweep bitmap removes that specific
failure: ten seconds, high-water 44, no drops, all 7068 records after tail,
including lost fragment 1/final fragment 25 and recovery/idle-budget cases.
It never marks requested data received or relaxes CRC/admission/ACK rules.
The three-exchange probe still overflows at this budget; that negative limit is
retained explicitly, and hardware response delay has not been directly measured.

Next **uninstalled** bundle:
`single-node-imu-smoke-logger-fragment-window` (logger only). Keep the current
inventory-generation master and SYNC-scope node. An isolated logger build uses
the installed logger's original bitwise CRC to preserve a single-variable trial;
canonical/master CRC-table code is not reverted. Source reconstruction proves
only the two manager files differ from installed logger src. Target disassembly
verifies bitwise CRC, and the request bitmap fits former padding with unchanged
inbox/bank sizes. Source/isolation/target review and focused tests/build pass.
Full details are in the smoke-test document's latest fragment-sweep section.
No agent device access/flash, source commit or remote publication occurred.

## Latest continuation: 6 November, 261106_073727

This supersedes the preceding "uninstalled" logger note. The user confirms
fragment-window logger installation, keeping inventory-generation master and
SYNC-scope node. Stage-6 drain still fails: 951 consecutive IMU samples,
37 source samples plus one evidence record lost, essential exclusion and
incomplete IMU tail. BDQ integrity, clean shutdown and remote cleanup are good;
Wi-Fi enable is not shown. Evidence lives in
`.scratch/stage6-drain-investigation/bench-073727/`.

The frozen first-loss window is 411445us, ingress 128/128, retained CAN records
265, SPI RX drops 36, no new CAN capture loss or malformed slot. Lower SPI drops
did not produce sustained recording. Existing fragment counters include repeated
prepared fragments; useful advancement and batch size are not yet measured.

Next **uninstalled master-only diagnostic**:
`single-node-imu-smoke-master-drain-efficiency`. Keep the current logger/node.
Version-2 drain fields add distinct/repeated prepared data fragments, distinct
object/record totals, actual ACK retirement versus replay, head/empty data polls,
and batch record-count histograms. These do not measure physical MISO delivery.
No polling/wire/admission/ACK/capacity changes. Instrumentation perturbs timing.
Target growth is 536 bytes flash and 240 bytes RAM; reserved stack unchanged.
Fresh independent source/artifact review, host/integrated checks, target build
and linked IRQ-vector check pass. Hardware throughput remains unresolved.

Use this new ELF's symbols in CCS: `gMasterDrainInfo` is version 2 (size 0x228,
linked at 0x2020E410), runtime info at 0x2020E8E8. Never use the old layout.
Capture the normal motion BDQ, complete serial, both structs, the new data arrays
and both 14-value batch-histogram rows. Histogram index is retained CAN-record
count, not source samples. The detailed smoke-test document describes semantics
and ranked diagnostic predictions. No agent device access/flash, source commit
or remote publication occurred.

## Local commands

PowerShell, working directory = the active worktree. These are offline commands.

```powershell
$env:PATH = 'C:/msys64/ucrt64/bin;' + $env:PATH
$gcc = 'C:/msys64/ucrt64/bin/gcc.exe'
$gxx = 'C:/msys64/ucrt64/bin/g++.exe'
$make = 'C:/ti/ccs2101/ccs/utils/bin/gmake.exe'

& $make -C firmware/can-fd/node/test test "CC=$gcc"
& $make -C firmware/can-fd/master/test test "CC=$gcc"
python firmware/tools/test_measurement_runtime.py --compiler $gxx
python firmware/tools/test_acquisition_control_runtime.py --compiler $gxx
python firmware/tools/test_remote_imu_lifecycle_runtime.py --compiler $gxx
python firmware/tools/test_remote_imu_lifecycle_runtime.py --compiler $gxx --smoke
python firmware/tools/test_integrated_imu_recording_runtime.py --compiler $gxx --cc $gcc

& $make -B -C firmware/can-fd/node/ticlang MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07 CAN_LINK_PROFILE=acquisition
& $make -B -C firmware/can-fd/master/ticlang MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07 CAN_LINK_PROFILE=acquisition
& C:/Users/benco/.platformio/penv/Scripts/pio.exe run -d firmware -e bodaqs_s3_mini_n4r2_imu_smoke -j 4

python firmware/tools/test_master_irq_vector.py firmware/can-fd/master/ticlang/bodaqs_can_master.out --readelf C:/ti/ccs2101/ccs/tools/compiler/ti-cgt-armllvm_5.1.1.LTS/bin/tiarmreadelf.exe
git diff --check
```

For expected-red native assertions on Windows, avoid a blocking crash dialog:
launch the test runner through Python with
`ctypes.windll.kernel32.SetErrorMode(2)` before `runpy.run_path(...)` or
`subprocess.run(...)`. Add `firmware/tools` to `sys.path` when using runpy for
runners importing sibling helpers. Check native exit codes explicitly in
PowerShell; a later successful command can otherwise hide a failed test.

Read BDQ without modifying it:

```powershell
$env:PYTHONPATH = "$PWD/analysis"
@'
from bodaqs_analysis.io_bdq import read_bdq, iter_bdq_stream_records
p = 'C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-handover-2026-11-05/261105_181608.bdq'
r = read_bdq(p)
print(r.detected_errors)
print(r.final_summary)
for s in r.stream_catalog['streams']:
    print(s['stream_key'], r.stream_record_count(s['stream_id']))
'@ | python -
```

Further target builds/uploads should follow existing bundle READMEs and the
firmware-build skill. Do not erase NVS/SD configuration or flash a different
target automatically. The logger's established manual esptool offsets are
0x0 bootloader, 0x8000 partitions, 0xE000 boot_app0, 0x10000 firmware, 4 MB flash.
