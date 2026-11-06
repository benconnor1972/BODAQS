# Single-node IMU happy-path smoke test

This is a short acquisition attempt, not physical qualification or fault testing.
The user explicitly authorized an unqualified single-node bench logger build.
Normal production admission remains guarded: it still rejects remote acquisition
without a qualified profile. No timing costs or bandwidth bounds are fabricated.

## Images and scope

Use the prepared bundle at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke`:

| Device | Image | Selection |
|---|---|---|
| A8 logger, ESP32-S3 Mini N4R2 | `logger/firmware.bin`, accompanying bootloader/partitions/boot_app0 | `bodaqs_s3_mini_n4r2_imu_smoke` |
| Master, MSPM0G3518 | `master/bodaqs_can_master.out` | acquisition: 1 Mbit/s arbitration, 4 Mbit/s data |
| IMU node, MSPM0G3507 | `node/bodaqs_can_node.out` | acquisition: same 1 Mbit/s / 4 Mbit/s profile |

The bundle manifest records exact source/build identities and hashes. The TI
images are reused from the verified candidate because their source/build inputs
are unchanged. Do not use the slower bringup images with these acquisition images.

The logger identifies as `bodaqs_a8_imu_smoke_unqualified`. Its sensor page shows
an unqualified-smoke banner. `/api/v1/device` identifies the firmware;
`/api/v1/sensor?id=N` reports `remote_control.recording_admission.mode` as
`single_node_smoke_unqualified`, `qualified=false`, and unknown/null occupancy
metrics. Admission may say `not evaluated` before the first attempt. The existing
`acquisition_ready=false` qualification flag is expected; it is not a sample count.

This build permits exactly **one unmuted CAN IMU**, no other active logical
sensors and no active ADC conversions. Persistently mute other sensors using
**Muted by default** in their sensor forms; temporary/runtime muting alone does
not necessarily remove ADC worker traffic. Multiple active IMUs are refused.
All link/configuration, memory-allocation, storage barrier and lease checks remain.
Keep the one-node cabling/power arrangement used for your successful control test.
The existing explained FRONT_FAULT telemetry with the agreed bench bypass does
not establish a new fault by itself; no telemetry is suppressed by this build.

## 1. Program the three devices

**Master GPIO interrupt correction (5 November 2026):** the original bundle's
master image names the SPI chip-select ISR `GPIOA_IRQHandler`, but the G3518
startup vector dispatches GPIOA through `GROUP1_IRQHandler`. A GPIO interrupt
therefore enters `Default_Handler`, freezing the heartbeat and SPI service.
The observed failure had PC `0x0000396A`, xPSR `0x21000011` (exception 17),
and runtime uptime stuck at 1600 ms.

For this bundle, replace only the master image with
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-master-irq-fix/bodaqs_can_master.out`.
Keep the original logger and node images. The replacement retains the acquisition
CAN profile and corrects the ISR name; the original bundle remains unchanged.
Its linked GPIO vector and master host tests pass; on-device recovery remains
to be checked. Load the replacement into the G3518 in CCS and Run/Resume.
Confirm the LED toggles every 500 ms, then reconnect using the existing bench
power/wiring procedure and confirm logger `probe_successes` increases and the
master reports `present=true` and `compatible=true` before testing the IMU.

Back up the SD configuration and existing logs first. Use your usual known-good
board power/debug connection; this procedure does not redefine wiring.

1. In CCS, select the **MSPM0G3518** master target, load
   `master/bodaqs_can_master.out`, then **Run/Resume** it.
2. Select the **MSPM0G3507** node target, load `node/bodaqs_can_node.out`, then
   **Run/Resume** it. Leave both firmware programs running, not debugger-halted.
3. Program the logger using the four supplied segments. On this machine, from
   the bundle directory in PowerShell, substitute the logger's actual COM port:

```powershell
$python = 'C:/Users/benco/.platformio/penv/Scripts/python.exe'
$esptool = 'C:/Users/benco/.platformio/packages/tool-esptoolpy/esptool.py'
& $python $esptool --chip esp32s3 --port COMx --baud 460800 write_flash --flash_size 4MB `
  0x0 logger/bootloader.bin 0x8000 logger/partitions.bin `
  0xE000 logger/boot_app0.bin 0x10000 logger/firmware.bin
```

These offsets follow the current A8 PlatformIO/framework configuration. They
preserve the NVS region at 0x9000 through 0xDFFF; OTA selection is initialized to
app0. Use the normal board bootloader-entry procedure if required by your setup.
Alternatively, from the integration worktree, PlatformIO can upload the same
explicit environment with `-t upload --upload-port COMx`; do not select a default
environment implicitly. No upload/probe was performed while preparing this bundle.

Reboot normally after programming. Update both CAN devices before judging
discovery: an old slower-profile peer will not communicate with this pair.

## 2. Configure only the test IMU

1. Connect to the logger's usual web UI while idle. Confirm its firmware name is
   the smoke name above. Use the existing Wi-Fi connection/address; no new SSID
   or credentials are assumed.
2. Open **Sensors** (`/config/sensors`). Set every other sensor's **Muted by
   default** checkbox and save. Leave exactly one IMU active.
3. Add **LSM6DSO32X IMU (CAN)** and choose the node's actual hardware strap
   address. For address 0, both node address jumpers are open. The form supplies
   `endpoint=imu` and `imu6_3333_32g_2000dps_v1` automatically. This is nominal
   3333 Hz, 32 g, 2000 degrees/s; do not reduce the profile to make the test pass.
4. If an old remote BMI placeholder exists, explicitly migrate it to the LSM
   type/profile or replace that assignment; BMI profiles are not translated.
5. On the IMU edit page, wait for **verified enabled** and **desired agreement
   verified**. A saved desired setting alone is insufficient. The master/node
   acquisition link profiles must both be compatible. Current inventory and
   reasons are available through `/api/v1/status` and the sensor API.
6. In **General** (`/config`), select **BODAQS multi-stream binary
   (experimental)** and save. The logger also selects BDQ v2 automatically when
   this sensor requires it. Confirm SD storage is available, then return home.

## 3. Make one short recording

1. Use the configured logging-toggle gesture. The default is **hold Mark**.
   Wait through preparation until the logger actually shows **Logging**.
2. Record about 15 seconds: hold the node still briefly, tilt/rotate it gently,
   then hold still again. Leave cabling and power unchanged during this attempt.
3. Use the same logging-toggle gesture to stop. Wait until finalization completes
   before removing power or the SD card. The normal stop includes a five-second
   tail window plus fence/release cleanup.
4. Wi-Fi/web access is deliberately suspended during logging. Reconnect after
   stopping, then use **Files** (`/files`) or the SD card to copy the new `.bdq`.

## 4. Check the result

Run from `C:/Users/benco/dev/BODAQS-worktrees/can-control-integration` with the
existing Python analysis dependencies. Set the downloaded file and correct
stream address below (`can0_imu6` for node 0):

```powershell
. ./tools/Enable-Utf8.ps1
$env:PYTHONPATH = "$PWD/analysis"
$file = 'C:/path/to/the/new-recording.bdq'
@'
import sys
from bodaqs_analysis.io_bdq import read_bdq, iter_bdq_stream_records
p, stream = sys.argv[1:]
info = read_bdq(p)
assert not info.detected_errors, info.detected_errors
assert info.metadata.get('acquisition_test_mode') == 'single_node_smoke_unqualified'
assert info.metadata.get('acquisition_qualified') is False
rows = list(iter_bdq_stream_records(p, stream))
assert rows, 'No node IMU samples; a primary/local-only file is not a pass'
assert info.final_summary.get('clean_shutdown') is True
assert info.final_summary.get('remote_imu_excluded') is False
print('SMOKE PASS:', len(rows), 'IMU samples')
for field in ('ax','ay','az','gx','gy','gz'):
    print(field, min(r[field] for r in rows), max(r[field] for r in rows))
print('First sample:', rows[0])
print('Unqualified single-node acquisition only; timing/alignment remain unknown.')
'@ | python - $file can0_imu6
```

A happy-path pass is a readable, cleanly closed BDQ file with nonempty native
IMU samples and six axes responding plausibly to your motion. The primary
stream alone is insufficient. The companion stream is `canN_timing`; records
remain 28-byte samples and 224-byte evidence. Unknown alignment, estimated native
ticks and unknown tail coverage are not physical timing qualification failures.

If preparation never reaches Logging, or the file check fails, retain the SD
file, serial output (115200 baud), `/api/v1/status`, and sensor JSON after returning
idle. Report the exact bundle/firmware name and observed stage. There is no need
to run the failure-injection matrix for this smoke attempt.

### Diagnostic logger for empty IMU streams and Busy after stop

The 5 November bench attempt declared both remote streams but wrote zero remote
records. Its file finalized with `remote_imu_excluded=true` and
`remote_cleanup_complete=false`; Wi-Fi remained blocked by recording cleanup.
The idle API showed reconciled configuration and compatible acquisition links.
The original serial trace did not include the failed lifecycle operation, so
the acquisition failure itself is not yet diagnosed.

A replacement logger bundle is at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-logger-diagnostics`.
Use its README programming command for the same A8 board; retain the corrected
master image and existing node image. This build preserves acquisition and
cleanup behavior. It prints one `[REMOTEIMU] first failure` line and prints
current cleanup state when a Wi-Fi request is refused. Capture serial at 115200
from before one recording attempt through stop and one refused Wi-Fi request.

The BDQ final summary adds optional `remote_failures` entries, retaining each
node's first observed failure through cleanup. Fields include logger uptime
`observed_ms`, coordinator `phase`, control `action`, `result`, `reason`,
measurement phase/reason/unavailability, received-object and transfer-error counts.
Cause values are control=1, startup timeout=2, stream=3, other local failure=4.
Coordinator phases are Idle=0, Allocated=1, Prepare=2, PreparedSnapshot=3,
Ready=4, Starting=5, Recording=6, Stop=7, Tail=8, Fence=9, Release=10, Exit=11,
Done=12. Control actions/results use `AcquisitionControl.h`; reasons use the
control contract. Empty entries mean no first failure was captured.

The HUD channel count now includes unmuted remote endpoint assignments as well
as local participants: one CAN IMU counts as one endpoint, not six axes. This
count describes configured participation and does not prove sample delivery.

### Measurement entry and cleanup correction

The diagnostic recording `261105_110102.bdq` retained a failure in Prepare
at logger uptime 27999 ms: result Unavailable (5), reason 26, measurement phase
0/unavailable, no objects and no measurement transfer errors. Serial showed
cleanup stuck at Fence (9). The default action value Snapshot (3) in this
entry-failure outcome does not mean a node snapshot request was rejected.

The master boundary adapter waited for `DL_SPI_isBusy()` to clear before
resetting SPI. The SDK's `SPI_STAT_BUSY_ACTIVE` definition includes a nonempty
TX FIFO. A 64-byte measurement confirmation leaves unsent prefetch from the
84-byte DMA capacity, so Busy does not prove an active physical transaction.
The corrected adapter uses inactive CS plus observed RX progress to retire the
slot, disables DMA and resets SPI before rearming. The regression models
inactive CS with pending TX bytes, requires the 64 received bytes to be queued,
and retains the active-CS/no-reception and retirement-generation checks.

Independently, failed measurement entry did not mark its transport failed.
Normal control could no longer run, but the unavailable-context recovery path
was never selected. The logger now marks that transport failed, allowing Fence
to request the existing explicit recovery path. Ownership remains retained until
node/master cleanup is verified. Lost entry confirmations and entry while SPI
is unavailable reproduce the stuck state before this fix and clean up afterward.

Use the replacement bundle at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-entry-fix`.
Program **both** its master and logger using its README, retain the existing
node, and keep exactly one CAN IMU unmuted. The logger retains the first-failure
diagnostics and remote endpoint count above. Target builds, master adapter/vector
checks, measurement/control tests and normal/smoke lifecycle regressions passed.
Physical acquisition and timing remain unverified: record a short motion test,
confirm nonempty IMU/evidence streams, then verify Wi-Fi can start after cleanup.

### Retry progress with SPI receive overruns

The next bench attempt, `261105_130615.bdq`, entered measurement mode but timed
out during PREPARE (action=0, result=4, reason=26). It wrote 73 timing records
and zero IMU samples. Cleanup remained at Fence. The master debugger snapshot
reported 83,354 SPI RX queue drops versus 56,306 processed slots, with no CAN RX
queue drops, no CAN malformed frames and no current bus-off/clock fault.
The drop counter covers master uptime, not just that recording.

A host fault model that drops every other received physical SPI request
reproduces that PREPARE timeout. The original control sender cycles fragments
0,1,0,1: periodic queue loss can repeatedly lose the same fragment. Retrying
rounds as 0,1,1,0 breaks that alignment without changing packet content, bus
speed or sample rate. A separate legacy-poll regression starts with its command
lost: three fetches produce a four-slot failed exchange that repeats at the same
loss alignment. Four fetches produce five slots and permit a subsequent command
to get through. Both regressions fail with their respective original behavior
and pass with the changes; verified cleanup passes under the alternating-loss
model. This does not establish the exact device loss pattern or fix the master's
service-rate deficit, and does not qualify loss-free acquisition.

The logger-only replacement is
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-rx-retry-fix`.
Keep the master from `single-node-imu-smoke-entry-fix` and existing node firmware.
Record a short motion test with serial capture, verify actual IMU rows and
post-stop Wi-Fi access, and retain the result even if another failure occurs.

For the exact entry-fix master image, the map places static `gService` at
`0x20200000`. If CCS cannot resolve its name, inspect
`((BodaqsMasterService *)0x20200000)->control.slots[0]` while suspended. This
address must be rechecked against the loaded image's map after any master rebuild.

### Cleanup after completed master retirement

With the RX retry logger installed, a later master capture showed a completed
RELEASE (opcode 0x29, exchange state 2, result completed/no error), measurement
phase 2, `quiescent=1`, `fenced=1`, `acquisition_retirement_pending=0`, retirement
generation 1 and node-0 fenced. Those values establish completed master
retirement at capture time; the remaining lock was not an outstanding physical
fence. The exact SPI response latency was not captured.

The mode inspector previously replaced its correlation token after each
four-slot call. A host model delaying valid status responses beyond that budget
reproduces an indefinitely locked coordinator after RELEASE and retirement.
Retaining the same inspection token across calls, for at most 300 ms, allows
the correlated response to arrive. Each call keeps its four-slot budget. Boot
or context changes, successful inspection, mode transitions and manager reset
invalidate the retained inspection. Expired-token and stale-preload rejection
tests pass. The full recovery regression fails with the old inspector and
passes with the fix; normal/smoke and fault lifecycle tests and the target build
also pass. This is a reproduced liveness defect, not a measurement of the exact
on-device delay or a remedy for the master's RX queue service-rate deficit.

The logger-only replacement is
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-status-poll-fix`.
Keep the existing entry-fix master and node. Resume the master in CCS after
debugger captures; it must not remain suspended during the next recording.
Follow the bundle README, capture serial and the BDQ file, and check post-stop
Wi-Fi access and actual IMU samples. Physical recovery remains unverified.

### Node FIFO timestamp ordering correction

The node breakpoint capture established that COMMIT and its lease succeeded,
then backend reason 27 terminated startup. A later lease challenge returned
authorization-terminal (30). No bus-off/recovery or capture-fault/clock-untrusted
state was observed, and the capture seed retry count was zero.

The retained FIFO buffer contained 51 words. Its first six words were:

```text
21 0a 00 00 00 00 99   timestamp 10, counter 0
09 1d 00 ff ff ec ff   gyro, counter 0
11 72 ff 4a 03 94 fd   accel, counter 0
22 16 00 00 00 00 99   timestamp 22, counter 1
0a 15 00 0c 00 16 00   gyro, counter 1
12 74 ff 43 03 95 fd   accel, counter 1
```

The old parser recognized tags/counters but required timestamp to be the final
word. It rejected this timestamp-first stream as soon as the accelerometer
completed a triple, producing startup reason 27. The corrected parser retains
the timestamp and completes a slot when all three distinct tags with the same
counter are present, regardless of timestamp position. Duplicate/mixed counters,
capture continuity, timestamp deltas and all existing fault checks remain.
Tag sensor/counter interpretation follows
[ST AN5640 sections 8.2.9 and 8.4–8.5](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3axis-accelerometer-and-3axis-gyroscope-stmicroelectronics.pdf).

Scenario 14 replays these exact two captured slots, then continues timestamp-first
synthetic data through READY/START/samples/STOP/FENCE and a new recording. It fails
on the old parser and passes with the fix. Scenario 15 covers timestamp between
axis words. Existing node scenarios, node-to-master/BDQ and integrated recording
checks pass. A fresh focused boundary review found no actionable defects;
physical throughput, timing and complete acquisition remain unqualified.

Load only the MSPM0G3507 node image from
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-node-fifo-order-fix`.
Keep the status-poll-fix logger and entry-fix master. Remove old diagnostic
breakpoints before loading, Run/Resume the node and master, and repeat the short
motion recording with serial capture. This image changes node memory layout:
all previous instruction and raw-data debug addresses must be checked against
the replacement image/map before reuse. Wire format, profile and rates are unchanged.

Debugger correction: the earlier source-line-563 stop at PC `0x000004C2`
followed a nonmatching identity comparison in optimized code; it did not prove
recording-ID reuse. The later instruction breakpoint captured the actual
terminal challenge rejection and the original backend reason above.

### Lost control-result ACK retry correction

Recording `261105_153415.bdq` with the timestamp-order node still timed out in
PREPARE (Uncertain/26): zero IMU rows, 73 master timing/bridge rows and five
transport errors. Its serial trace showed subsequent cleanup completing. The
old error counter alone does not establish which error codes occurred on device.

A separate production control-path regression drops one ordinary control-result
RAM ACK at the SPI boundary while MISO supplies a valid empty response from
another pipeline turn. The master correctly retains that result and returns
Busy (8) for the next request. The old logger discarded the next outgoing object
on Busy, producing the same PREPARE Uncertain/26 timeout. The fix retains that
immutable object and original deadline, replaying an ACK only for an inbound
result already admitted into RAM in the same context. It never acknowledges
unreceived data or extends the authorization deadline. The regression requires
observed Busy and successful PREPARE plus verified cleanup; it fails before the
fix and passes afterward. This models a plausible consequence of the measured
RX overruns, not proof of this recording's exact physical loss pattern.

Transport diagnostics now log the first occurrence of each error code per
measurement context, including source, class, node and object. The status API's
measurement object and BDQ `remote_failures` entries add `transfer_error_mask`:
bit N means transport error N was observed. Existing error counts remain.

Use the logger-only bundle at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-control-ack-fix`.
Retain the FIFO-order-fix node and entry-fix master. Capture the entire serial
trace, including `[CANMASTER] measurement error` lines, through a short motion
recording and cleanup. Physical acquisition and master service-rate sufficiency
remain unverified.

### Acquisition request clock-boundary correction

Recording `261105_155128.bdq` progresses beyond PREPARE but excludes the IMU
during START (phase 5, action 1, Uncertain/26). The first failure is observed at
106843 ms, less than a second after opening the file, rather than after the
ordinary control request's 3500 ms timeout. The file contains 4930 primary rows,
zero IMU rows and 14 timing/bridge rows; its retained transport error mask is
256 (Busy/8 only). Serial subsequently reports completed logger finalization.

A production lifecycle regression advances the clock by one millisecond while
START is queued. The service previously compared its earlier `now` snapshot
against the newer request timestamp: unsigned subtraction wrapped and expired
the request immediately. The regression fails before the correction and passes
after it, including START completion and verified cleanup. Timeout evaluation
now samples the clock after the request timestamp; actual deadlines and
authorization checks remain unchanged. This demonstrates a matching software
failure mechanism; its occurrence in this physical recording is inferred.

Use the logger-only bundle at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-control-clock-fix`.
Retain the FIFO-order-fix node and entry-fix master. Normal/smoke lifecycle,
fault recovery, acquisition control, measurement and integrated recording tests
and the target logger build pass. Repeat a short motion recording with full
serial capture through stop and Wi-Fi activation. Physical IMU acquisition and
master service-rate sufficiency still require bench confirmation.

### Sample/evidence head polling starvation correction

Recording `261105_161007.bdq` confirms START success (action 1, Succeeded/2)
before stream failure at 38281 ms (phase 6, cause 3). The readable file has
5278 primary rows, zero IMU rows and 32 timing/diagnostic rows. The timing stream
reports 87 lost source samples, one lost evidence record and a stage-6 essential
metadata loss (local boundary reason 31). The later master runtime snapshot
confirms node-0 ingress capacity/high-water 128/128 and 18 dropped CAN frames;
frame drops and affected sample counts are different units. SPI RX drops are
1659, and the CAN RX queue reached 8/8 with one hardware loss. These cumulative
runtime counters do not establish the exact timing of each physical loss.

A controlled production logger/master transport regression injects two
five-sample CAN packets every 3 ms and one evidence event every 100 ms, with
eight SPI service turns per injected millisecond. An empty evidence-head probe
previously consumed the same per-node 20 ms throttle as the sample-head probe.
With evidence polled first, it could repeatedly suppress samples even while a
sample head was pinned at the master. Before correction, the regression delivers
zero completed CAN records, reaches 128 retained frames and drops frames.
After separating sample/evidence empty-probe timers, it delivers 664 records
in one simulated second, reaches high-water 41 and drops none. Both classes
retain a 50 Hz empty-probe limit; active fragment draining remains immediate.
This is a controlled scheduling regression, not physical throughput qualification.

The changed polling schedule also exposed aliasing of ordinary control polls
with alternating physical RX loss. Idle control selections now repeat each
node/lane twice before rotating. The existing loss regression and an additional
opposite-phase measurement-loss scenario verify PREPARE and cleanup. Protected
requests retain their urgent selection and data keeps its existing slot share.
Normal/smoke lifecycle, protocol/control, integrated recording and target logger
build checks pass. Neither master capacity nor wire format changes.

Use the logger-only bundle at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-drain-poll-fix`.
Keep the FIFO-order-fix node and entry-fix master. Capture serial from before a
short motion recording through stop and Wi-Fi activation, retain the BDQ, and
capture the master's node-0 ingress high-water/drop values before reset. The
acceptance check is persisted IMU samples with no essential metadata exclusion
and completed cleanup. Real SPI/CAN service-rate qualification remains open.

### Remaining drain deficit: physical timing capture

With the drain-poll fix, `261105_164129.bdq` contains the first 65 consecutive
IMU records (sequences 0..64), plus 5555 primary and 36 timing records, with no
reader integrity errors. START succeeds; stream exclusion at 94738 ms follows
10 lost source samples, one lost evidence record and essential-metadata loss.
The master reaches ingress high-water 128/128 and drops three CAN frames. Its
snapshot reports 1339 SPI RX drops but no CAN hardware/software receive losses
and CAN RX high-water 6/8. These cumulative counts do not measure active drain
capacity or date the SPI drops. The host scheduling model is not a substitute
for this physical timing evidence.

The logger-only diagnostic bundle
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-drain-timing`
adds bounded counters to measurement exchanges and snapshots them at first
failure. Two `[DRAIN]` serial lines and optional BDQ failure field
`transport_timing` retain the context's elapsed window, slots, failed/empty
replies, accumulated/max exchange time, maximum gap between exchanges,
per-class polls/fragment responses and per-class empty-probe deferrals. Class
array order is samples, evidence, ordinary control, protected control, shared
evidence. Fragment counts include duplicate responses. Failed slots include
invalid preloaded replies during mode transitions; they are not SPI RX drop
counts. Exchange time includes guard, shared-bus wait, transfer and decode;
the full context window includes preparation and entry, not only acquisition.
Timing uses wrapping microsecond differences and should be captured in the
short smoke recording, well within one 32-bit microsecond wrap interval.

These diagnostics add no per-slot serial output and do not change pacing,
queue sizes or authorization. Measurement/smoke lifecycle and integrated
recording checks and the target build pass. Keep the current node/master and
repeat one short motion recording with serial through cleanup and Wi-Fi start.
Send the BDQ and full serial, including both `[DRAIN]` lines. This is evidence
collection for the remaining deficit, not a verified throughput fix.

### Master CAN capture burst service correction

Recording `261105_170122.bdq` reports stage-5 loss of three evidence frames,
then essential-metadata exclusion while START is still pending. It contains
8096 primary rows, zero IMU rows and 20 timing records, with no reader integrity
errors. Administrative cleanup completes. This differs from the earlier
stage-6 retention overflow. The first-failure timing window contains 1716 SPI
exchanges in 795454 us, 253952 us accumulated exchange duration, 1322 empty
replies, maximum exchange 244 us and maximum idle gap 1478 us. Its preparation
and entry traffic precludes treating these as steady recording measurements.

The master previously popped only one CAN capture record per main-loop turn.
A controlled adapter regression delivers eight metadata frames, one CAN service
turn, then four frames: the old code leaves seven queued and drops three
essential frames. The bounded batch correction pops up to eight records per
turn; the same regression reports four queued and zero drops. Another case
injects an ISR refill during decoding and proves the turn still returns after
eight records, leaving the added record for the next turn. Tests extract the
actual capture, IRQ-serialized pop and service functions, use shifted SDK-style
CAN identifiers, and assert decoding occurs outside the IRQ mask. The decoder
itself is mocked. The burst is a reproducer for the observed failure mechanism,
not a measured reconstruction of physical CAN arrival times.

Use the master-only bundle at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-master-can-drain-fix`.
Keep the drain-timing logger and FIFO-order-fix node. The queue remains eight
entries and ISR ownership, loss reporting, SPI retirement and wire formats are
unchanged. Master adapter/timing, measurement and integrated recording checks,
acquisition-profile target build and linked GPIO vector check pass. Fresh
boundary review found no actionable issues, including the IRQ-mask test model.
Physical processing latency and sustained capacity remain unqualified; this
correction does not establish resolution of the earlier retention deficit.
Load and Run/Resume the replacement master in CCS, then capture one short
recording's BDQ and complete serial through stop/Wi-Fi activation. Old hardcoded
instruction/data addresses must be rechecked against the replacement ELF/map.

### Avoid duplicate polls for a data fragment still in flight

With the master batch-drain image, `261105_172231.bdq` contains 150 consecutive
IMU records (0..149), 14560 primary rows and 40 timing rows, with no reader
integrity errors and completed administrative cleanup. No stage-5 loss is
recorded in this file. Stage-6 retention loss recurs: 42 source samples, one
evidence frame and essential-metadata exclusion at 42487 ms. The context's
timing window is 1177626 us with 2389 exchanges, 1605 empty replies, 371304 us
accumulated exchange time, maximum exchange 570 us and maximum idle 1590 us.
The preparation window is not a steady recording-rate measurement.

The earlier host drain test allowed eight service turns/ms. At four turns/ms,
the same production logger/master test overflows retention: 334 completed CAN
records, high-water 128 and six dropped frames. The one-exchange MISO pipeline
explains a preventable cost: selecting the first missing fragment before
decoding the current MISO repeatedly asks for the fragment already in flight.
The logger now remembers the previous MOSI poll only as a scheduling hint and
prefers another missing data fragment if available. It never marks the hinted
fragment received, admits data without checksum validation or sends an early
ACK. A lost hinted fragment remains missing and is retried. Recovery clears
the hint; context reset clears the transport bank.

The four-turn regression now completes 651 records with high-water 34 and no
drops, using 2506 actual SPI exchanges in the injected second. Replacing one
sample-fragment reply with a valid empty response still completes with the
same totals and verifies the missing fragment is retried. The original
eight-turn test, normal/smoke lifecycle, control and integrated native-record
checks and target logger compilation pass. These controlled timings do not
qualify physical service capacity.

Use the logger-only bundle at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-fragment-poll-fix`.
Keep the master CAN batch-drain image and FIFO-order-fix node. Timing diagnostics
remain enabled. Repeat a short motion recording and retain the BDQ plus full
serial through stop/Wi-Fi activation, including `[DRAIN]` lines. Physical
sustained acquisition and remaining retention pressure still require bench
verification. SPI speed, guard time, queue capacity and authorization do not
change in this update.

### Continue the master's partial data head across sample/evidence turns

Recording `261105_173532.bdq` has 275 consecutive IMU records (0..274), 8681
primary records and 41 timing records, with no reader integrity errors. START
succeeds, and administrative cleanup completes. Stage-6 loss remains: 37
source samples, one evidence frame and essential-metadata exclusion at 70474 ms.
The retained first failure has zero transport errors; the later protected-lane
Busy reply is not the initial trigger. No stage-5 loss is recorded in the file.

The prior host workload's single evidence record/100ms underrepresented the
recurring model/anchor/snapshot/sync traffic. A four-evidence-record burst per
100ms exposes retention overflow in the production transport test at four
service turns/ms over three seconds: 1771 completed records, high-water 128,
and a dropped essential frame. The current logger can request evidence while
a sample object is incomplete, even though the master retains a single
ordered sample/evidence head per node. Those turns cannot fetch the other
class until the existing head completes and its admitted-object ACK retires.

The seven-line correction redirects a data turn to the other class's partial
object only at the same node and only if the originally selected class has no
partial object. It preserves control/ACK priority, canonical identity/CRC,
admission, retries, idle backoff, queue capacities and SPI pacing. Extending the
four-turn burst test to ten seconds now completes 7041 CAN records before
the tail, high-water 39 and zero drops. Tail draining delivers all 7068 produced
records. A dropped-fragment case also passes, and idle probes subsequently
remain bounded to 11/class/200ms. Actual exchanges are 27243/ten injected
seconds (27244 with one dropped fragment). These are synthetic timings.

A tested alternative bypassing idle backoff during recent data activity was
removed after review identified its empty-poll budget impact. The retained
change does not include that bypass. An exploratory lower three-turn schedule
still overflowed; the passing schedule is not physical capacity qualification.
Normal/smoke lifecycle, acquisition control, integrated recording/native-ledger,
target logger build and the fresh scoped review pass without actionable findings.

Use the logger-only bundle at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-partial-head-fix`.
Keep the CAN batch-drain master and FIFO-order-fix node. Repeat a short motion
recording with the BDQ and full serial through cleanup/Wi-Fi activation,
including `[DRAIN]` lines. Sustained on-device acquisition remains unverified.

### Scope node raw SYNC observations to explicit START

Recording `261105_175440.bdq` contains 382 consecutive IMU records (0..381),
16434 primary and 47 timing records, with no reader integrity errors and
completed administrative cleanup. Stage-6 losses total 370 source samples and
two evidence records before essential-metadata exclusion at 24952 ms. No
transport error is retained at that first failure. The file also exposes a
separate node scope defect: seven raw SYNC observations at node ticks
0.079..0.679 seconds are forwarded after START, while the first sample is at
node tick 24.280 seconds in the same epoch. A stage-4 report then charges 236
lost evidence observations to this recording.

The ISR queues SYNC observations continuously, but the acquisition consumer
only drains them in STARTING/RECORDING. Idle captures fill its seven-usable-entry
ring and accumulate drops; these previously entered the next recording's
startup traffic and loss ledger. Node scenario 16 injects 243 pre-START captures
(seven retained, 236 dropped): the old backend emits stale captures and fails
the fresh-observation assertion. The corrected START discards only this SYNC
observation backlog/loss and clears the prior snapshot SYNC-presence flag.

The additive internal helper `bodaqs_node_capture_sync_discard()` atomically
advances the SYNC tail, clears its dropped/latest-pending state and clears
only the timer's pending CC3 event under saved/restored PRIMASK. It does not
reset clocks, epochs, ordinals, DRDY state or clock faults. Captures after this
boundary and their losses remain accountable. Capture tests model IRQ masking,
both incoming mask states, pending DRDY and stale CC3, continued ordinals and
live overflow. Acquisition tests retain a fresh post-START edge and reject stale
SYNC references across two recording turnovers. Node scenarios 1..16,
integrated recording/native-ledger checks and the acquisition-profile target
build pass; fresh boundary review found no actionable issues.

Use the node-only bundle at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-node-sync-scope-fix`.
Keep the partial-head-fix logger and CAN batch-drain master. Load and run the
node in CCS, allow normal logger startup/idle, then capture a short motion
recording with complete serial through cleanup/Wi-Fi activation. Send the BDQ
and serial including `[DRAIN]` lines. Old raw debugger addresses must be checked
against the replacement ELF/map. This removes a confirmed startup-scope defect;
it does not prove the remaining physical stage-6 drain deficit is resolved.

### Stage-6 drain investigation: offline continuation, 5 November 2026

The saved `261105_181608.bdq` still establishes stage-6 retention loss and
essential-metadata exclusion, with no reader integrity errors. No new physical
run has occurred. The installed logger/node/master combination in the handover
remains the last tested device state; sustained recording is still broken.

The continuation artifacts are under
`.scratch/stage6-drain-investigation/`. Run the repeatable sensitivity matrix:

```powershell
$env:PATH = 'C:/msys64/ucrt64/bin;' + $env:PATH
python .scratch/stage6-drain-investigation/run_feedback_matrix.py
```

This uses the production logger/master measurement fixture with the existing
two five-sample packets/3ms and four evidence records/100ms. The four-turn/ms
control still passes ten synthetic seconds (7041 records before tail, high-water
39, zero drops; all 7068 after tail). Three turns/ms first observes overflow at
1501ms. Enabling the fixture's existing alternating physical request-loss model
after mode entry overflows even at eight turns/ms: first observed at 184ms or
187ms for the two loss phases. Continuing both cases produces essential loss.
The first phase accepts evidence/control head probes but repeatedly drops the
sample head probe; the opposite phase also stalls. The matrix verifies these
expected failures explicitly, rather than treating an unrelated compile failure
as a reproduced retention deficit. These are sensitivity experiments, not a
measurement of the actual device's request-loss cadence or service rate.

The passing throughput fixture processes SPI requests synchronously. The actual
master has a one-entry RX queue, main-loop response generation and subsequent
CS-boundary publication. Existing lifecycle request-loss tests do not establish
sustained data drain through this adapter. The observed hardware SPI drops make
this missing boundary relevant, but cumulative counters cannot date the drops.

An offline Thumb instruction trace executes the **installed** master ELF from
`single-node-imu-smoke-master-can-drain-fix`, SHA-256
`4307c02320ec17f0f9a5e29fe32fe9e8710fcd2eb9f984258667670bf1f32ce1`.
It derives state offsets from DWARF and uses the real linked ingress/transport
functions, checking successful admission and output wire CRC. Results are in
`installed-master-instructions.json`:

| Operation | Executed instructions | CRC work |
|---|---:|---:|
| Steady empty authorization poll | 8265 | 5940 in wire CRC source lines |
| Steady empty sample poll | 8444 | 5940 in wire CRC source lines |
| Sealed sample-head fragment poll | 9003 | 5940 in wire CRC source lines |
| First sample packet into a batch | 1797 | no logical seal |
| Thirteenth packet, sealing a full batch | 56706 | 54676 in logical checksum function |

The first context-reset poll separately takes 283380 instructions; it is not a
steady poll. These are instruction counts, **not target cycles or measured
microseconds**. The emulator omits peripheral/interrupt timing, flash/RAM wait
states and physical response publication. Master CPUCLK is 80MHz. CRC service
cost is now a quantified software lead, not a demonstrated physical root cause.
No CRC algorithm, pacing, clock or queue-size change was made.

A new master-only diagnostic image is available at
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-master-drain-profile`.
Keep the partial-head logger and START-scoped-SYNC node. This image adds the
debugger symbol `gMasterDrainInfo`, version 1, without changing wire formats,
authorization, RAM ACK rules or scheduling. Its window starts when the master
admits START to its CAN control exchange; this does not prove CAN transmission,
node acceptance or physical START. It freezes at the first observed stage-6
drop (including sample-only loss), last active STOP admission, or identity change:

- `state`: 0 idle, 1 collecting, 2 frozen; `finish_reason`: 1 retention loss,
  2 STOP, 3 context/recording change. Same-context cleanup preserves the snapshot.
- `elapsed_us`, `clock_epoch`, `timing_invalid`: native master clock interval;
  distrust invalidates timing interpretation. Unsigned subtraction covers short
  windows crossing the 32-bit tick wrap, not arbitrarily long recordings.
- `spi_dropped`, `can_dropped`, `can_hardware_losses`, `retained_frames` and
  `ingress_dropped[]`: deltas from saved START-window baselines, excluding PREPARE.
- `calls[]`, `total_us[]`, `max_us[]`, `histogram[][]`: lanes 0 status refresh,
  1 SPI processing/response preparation, 2 CAN work from its first copied
  loss/record through the bounded drain's completion (first copy/pop excluded).
  Histogram buckets are <=50, <=100, <=250, <=1000, >1000us. Interrupt time and
  instrumentation effects are included; this image can perturb the deficit.
- `polls[]`, `acks[]`, `fragments[]`, `empty_replies`, `malformed_slots`: accepted
  SPI requests and produced replies during this window. Produced fragments can
  be duplicates or retired before transmission; they do not prove logger receipt.
- `ingress_sampled_high_water[]` and `can_queue_sampled_high_water` are sampled
  maxima, not guaranteed peaks. `ingress_depth[]` is the last sampled depth.

The adapter tests exercise historical-loss exclusion, short tick wrap, clock
distrust, first-drop freeze and new-context baselines. They also inject CAN
arrival after an empty entry observation and response retirement immediately
after publication. Faulty off-tree variants fail the corresponding assertions;
production files are never replaced for these checks. Fresh boundary review
resolved the missing late-arrival timing, post-publication buffer read and
overstated peak labels. Master timing/adapter tests, existing measurement and
integrated recording/native-ledger suites, acquisition-profile target build and
linked GPIO vector check pass. CAN decode remains mocked in the adapter fixture;
none of these checks qualifies physical drain capacity.

For the next manual run, use the bundle's ELF/map in the correct CCS master
target. Record normally, stop, and allow cleanup/Wi-Fi before halting the master
to export **all** of `gMasterDrainInfo` and `gMasterRuntimeInfo`. Preserve the BDQ
and full serial. Do not pause the master during acquisition to collect timing.
Compare active SPI processing costs/drops with retained CAN input and the first
retention-loss boundary before choosing CRC, scheduling or adapter changes.
The logger's existing `[DRAIN]` window still includes PREPARE.

### Measured active deficit and CRC comparison image: 261105_205838

The user supplied the diagnostic master snapshot and
`E:/261105_205838.bdq`. A local read-only evidence copy, selected supplied serial
lines and analysis are retained in
`.scratch/stage6-drain-investigation/bench-205838/`; the structured debugger
snapshot is `bench-context-8762878483939338580.json` beside it. The BDQ's context
matches the snapshot exactly. The supplied symbol address also matches the
diagnostic bundle map; no on-device image hash was read back.

The file has 9641 primary records, 412 consecutive IMU samples (0..411) and
37 timing records, with no reader integrity errors. Stage-6 reports account for
137 source samples (5 + 132) and one evidence record, then essential-metadata
boundary reason 31. The first stream failure is observed at logger uptime
61539ms with zero retained transport errors. File closure is clean, but remote
cleanup is false at summary time and tail coverage is incomplete. The supplied
serial ends at file closure; later cleanup completion is not demonstrated.

The master snapshot is frozen at the **first** retention drop, 258629us after
START admission, with trusted epoch 1 and `timing_invalid=0`. In that window:

- SPI RX drops increase by 150; CAN capture software/hardware losses increase by
  zero. The hardware-loss baseline of one belongs to earlier activity.
- 165 CAN reception records are retained; node 0's ingress reaches 128/128 and
  drops one record. CAN records and six-axis source samples are different units.
- There are 401 processed SPI requests, including 111 sample/evidence polls,
  224 control/protected/shared polls and 39 ACK requests. Produced responses
  include 140 fragments and 241 IDLE replies. Counts can include duplicates;
  IDLE on a selected lane does not demonstrate spare drain capacity.

| Timed service lane | Calls | Total ms | Mean us | Maximum us |
|---|---:|---:|---:|---:|
| Status refresh | 401 | 35.088 | 87.5 | 140 |
| SPI processing/response preparation | 401 | 78.564 | 195.9 | 1465 |
| Bounded CAN work | 122 | 6.230 | 51.1 | 375 |

Status and SPI processing together account for 43.94% of this window; all three
timed lanes account for 46.35%. These are elapsed service measurements including
interrupts and diagnostic effects, not exclusive CPU utilization. The remaining
time is not proven idle: retirement, other main-loop/interrupt work, instrumentation
and logger scheduling gaps are not separately accounted. Histogram values and
`gMasterRuntimeInfo` were not supplied. The frozen interval ends before later
draining/exclusion; do not divide all 412 persisted samples by its 258629us.
This establishes active SPI request loss accompanying a retention deficit,
without a new CAN capture loss in that interval. It does not establish an
alternating loss cadence or prove CRC is the sole physical cause.

The next comparison changes only measurement/logical CRC computation to an
immutable 256-word byte lookup. Existing initial/final XOR, canonical prefix,
wire bytes, signatures, corruption checks, ACK/admission ownership, status
refresh, scheduling and queue capacities are preserved. The installed logger
and node remain compatible and should remain unchanged for the comparison.
The common test target now runs an independent Python-zlib vector test under
both C11 and C++17: 8186 checks per compiler cover wire lengths 0..1024,
logical payload lengths 0..1020, four alignments and canonical identities.
A corrupted scratch table fails the expected vector assertion.

An otherwise equivalent target ELF instruction comparison gives:

| Operation | Diagnostic baseline | CRC-table image | Reduction |
|---|---:|---:|---:|
| Empty authorization poll | 8265 | 3102 | 62.5% |
| Empty sample poll | 8444 | 3285 | 61.1% |
| Sealed sample-head fragment poll | 9003 | 3839 | 57.4% |
| Thirteenth packet, sealing a full batch | 56706 | 16088 | 71.6% |

These remain **executed instructions, not measured target cycles or times**.
CRC source attribution now derives function ranges from each ELF's DWARF
declarations rather than fixed source line numbers. The master has two 1KiB
flash table copies, no new RAM allocation or initialization constructor, and a
net flash-load increase of 2296 bytes. The logger's shared-header build has one
1KiB table in flash DROM and no CRC initialization guard/constructor.

Common protocol/corruption/retention, master adapter/timing, measurement,
acquisition control, normal/smoke lifecycle and integrated recording/independent
ledger checks pass. Both explicit target builds and the master linked IRQ-vector
check pass. Fresh scoped review independently verifies table entries, unchanged
integrity/admission gates and target flash placement with no actionable findings.
The candidate runner forwards its selected C compiler/Python to the common suite;
its unit tests cover that new test dependency.

The master-only comparison bundle is
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-master-crc-table`.
Load its master ELF/map manually, keeping the partial-head logger and SYNC-scope
node. The logger rebuild was validation only. Repeat a normal motion recording,
stop and allow cleanup/Wi-Fi, then collect the full `gMasterDrainInfo` (including
expanded histograms), `gMasterRuntimeInfo`, BDQ and serial. Compare processing
costs and active SPI drops with the baseline above. Sustained physical recording
and complete cleanup remain acceptance criteria; the CRC image is unqualified.

### Physical CRC result and unchanged-inventory fast path: 261105_211914

The supplied `261105_211914.bdq`, serial capture and debugger structs are
preserved under `.scratch/stage6-drain-investigation/bench-211914/`.
The BDQ matches diagnostic context 11477279701755020739. It has no detected
integrity errors, 20535 primary rows, 784 consecutive IMU samples (0..783),
and 42 timing records. Stage-6 loss is 50 source samples (15 + 35) and one
evidence record, followed by essential-metadata boundary reason 31. The first
stream failure is observed at logger uptime 50520ms with zero retained transport
errors. Clean file closure again coexists with incomplete tail/cleanup at summary
time; serial ends at file close without demonstrating subsequent cleanup.

The CRC change has a measured service-cost benefit, but sustained drain fails:

| START-admission to first retention-drop snapshot | Before CRC | CRC table |
|---|---:|---:|
| Window us | 258629 | 363483 |
| Processed SPI requests | 401 | 706 |
| SPI RX drops in window | 150 | 117 |
| CAN software/hardware capture losses in window | 0 / 0 | 0 / 0 |
| Mean status refresh us/request | 87.5 | 87.2 |
| Mean SPI processing us/request | 195.9 | 87.6 |
| Maximum SPI processing us | 1465 | 590 |
| Retained CAN records | 165 | 227 |

Mean SPI processing falls 55.3%; status-refresh cost is effectively unchanged.
The new snapshot has valid epoch 1, sampled ingress 128/128, and two drops by
the end of its bounded CAN drain. It contains 289 sample/evidence polls,
319 control/protected/shared polls and 60 ACK requests; fragments/ACK counts
can include duplicates. All three timed lanes account for 36.29% of the window;
unaccounted time is not proven idle. Histogram values were not supplied.
The persisted sample total includes draining after this first-loss snapshot and
must not be divided by its elapsed interval to claim throughput.

The later runtime snapshot records 154 cumulative CAN error events and one
bus-off recovery, while currently reporting no bus-off or clock fault. It also
reports `front_power_fault=1` and low buck input/readback despite an enabled,
high output latch. These are retained observations requiring separate electrical
interpretation, not evidence dating a power/bus-off event to this active window.
No power/wiring behavior is changed by the software comparison below.

Status refresh was rebuilding and republishing all four discovery records on
every SPI request. Its publisher now returns after refreshing live status when
the already-published inventory generation matches the main-owned inventory.
Accepted announcements/status (including repeated status refreshing last-seen),
boot/duplicate observations and stale transitions advance that generation, so
the next refresh still publishes every relevant change. First publication,
service reset and actual generation wrap remain covered. No wire formats,
status freshness, CRC, capacities, polling budgets or ISR ownership change.

The new production-status fixture goes red before the guard with two unchanged
inventory publications instead of one. It links real inventory mutation and
publication/control code; GPIO inputs are mocked. Green checks cover fresh live
status on the fast path, all mutation/reset cases, duplicate cancellation of
already-pending ordinary and authorization requests before dispatch, and retained
exclusion across real measurement-context turnover. The raw CAN path remains
covered by the separate adapter/protocol tests. Fresh independent boundary review
found no actionable issues. Master timing/adapter/inventory, measurement and
integrated recording/ledger checks, target build and linked IRQ-vector check pass.

The linked target instruction probe, with synthetic zero GPIO inputs, reduces
unchanged-inventory status refresh from 4292 to 423 executed instructions (90.1%).
Initial/changed inventory refresh remains approximately the same cost; these
counts are not physical target timings. The measured bench mean of 87.2us is
the baseline for the next comparison, not the expected or measured new latency.

Use the new master-only bundle
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-master-inventory-generation`.
Keep the current partial-head logger and SYNC-scope node. Repeat the same normal
motion recording, stop/cleanup/Wi-Fi procedure and capture BDQ/serial plus both
debugger structs, including all five values of each histogram row. Persistent
IMU recording, interpretable evidence, no essential exclusion and completed
cleanup remain required; this new image has not yet run on the device.

### Physical inventory result and fragment-request sweeps: 261105_213917

The BDQ, serial, complete supplied runtime/drain fields and later expanded
histograms are preserved in `.scratch/stage6-drain-investigation/bench-213917/`.
Context 6988146453469253922 matches. There are 11279 primary records,
1206 consecutive IMU samples (0..1205), 45 timing records and no reader integrity
errors. Stage-6 losses total 80 source samples (5 + 75) and one evidence record,
then essential-metadata exclusion. Summary remote cleanup is **true** this time;
the excluded IMU tail remains incomplete. Serial demonstrates administrative
finalization/legacy probing, but not a later Wi-Fi enable or physical acceptance.
The late provider-absent message alone does not identify its cause or prove a
permanent recovery regression.

The valid first-loss window grows to 448031us. It retains 282 CAN records,
reaches 128/128 ingress, and records 166 SPI RX drops without new CAN capture
loss. Across 1010 SPI services, mean status refresh falls from 87.2 to 11.5us
(86.8%); mean SPI processing remains 88.4us. Mean CAN work is 44.1us across
237 calls. Timed service accounts for 24.85% of the window, not exclusive CPU
utilization or proof that the rest is idle. The supplied histograms are:

| Lane / duration bucket us | <=50 | <=100 | <=250 | <=1000 | >1000 |
|---|---:|---:|---:|---:|---:|
| Status refresh | 1009 | 1 | 0 | 0 | 0 |
| SPI processing | 0 | 851 | 147 | 12 | 0 |
| CAN work | 182 | 30 | 25 | 0 | 0 |

The SPI maximum is 590us. Later runtime error/power/readback fields remain
observations outside the frozen boundary, not proof of an electrical cause for
these active-window retention losses.

ACK-loss-only host probes at the unchanged four-turn/ms schedule pass with
every seventh, third and second data ACK dropped. ACK behavior is unchanged.
A separate probe exposes a scheduling weakness: the old scheduler assumes only
the immediately preceding poll can have an outstanding response. Delaying MISO
by one extra exchange (two-exchange responses) makes the same traffic/schedule
overflow stage 6 in about 1.1 synthetic seconds. The model delays responses;
it does not emulate the complete master adapter, measure the hardware response
lag distribution or establish this as the exclusive physical cause.

Each partial data inbox now has a scheduling-only requested-fragment bitmap.
It selects missing fragments not yet requested in this sweep, then starts a new
sweep when only previously requested gaps remain. Lost final fragments are
retried; requests never modify actual received masks. Object changes and recovery
clear hints, preserving retained data/identity/ACK state. Control/ACK priority,
CRC validation, downstream admission and empty-head probe budgets are unchanged.

At the same four-turn budget, two-exchange responses now pass ten synthetic
seconds: 7054 records before tail, high-water 44, no drops, all 7068 records after
tail. Lost early fragment and maximum-batch final fragment index 25 cases pass,
as do recovery-mask preservation and idle-probe bounds. A combined two-exchange
case dropping every seventh data ACK also passes (high-water 61, complete tail).
**Three-exchange responses
still overflow** at this budget (first observed around 1402ms after the change).
That negative capacity probe is retained in `fragment-window-lag3-limit.log/json`;
it is not claimed as passing coverage and the budget was not increased.

The next image is logger-only:
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-logger-fragment-window`.
For a single-variable trial it was built from an isolated copy retaining the
installed logger's original **bitwise CRC** headers. Canonical shared/master
CRC-table changes remain intact. Reconstructing the installed partial-head
bundle's source shows only `CanMasterManager.cpp/.h` differ in the isolated
logger's 196 source files; board/config/build inputs match. The target ELF's wire
CRC disassembly confirms the old bitwise loop. The new bitmap occupies existing
padding: inbox size 1136 and transport-bank size 23936 are unchanged. Bootloader
and partition images match the installed logger bundle.

Canonical and isolated measurement, independent C/C++ CRC, owner/control,
normal/smoke lifecycle, integrated storage/native-ledger tests and the explicit
logger build pass. Fresh source/isolation/target review finds no actionable
issues. Use this bundle's manual instructions; keep the inventory-generation
master and SYNC-scope node. Capture the next normal motion recording, complete
serial, BDQ and both master debugger structs after stop/cleanup. Persistent
recording without essential exclusion and usable Wi-Fi remain unverified.

### Physical fragment-window result and efficiency diagnostics: 261106_073727

The user confirms that only the logger changed to the fragment-window bundle;
the inventory-generation master and SYNC-scope node stayed installed. The BDQ,
supplied debugger fields and selected serial diagnostic lines are preserved in
`.scratch/stage6-drain-investigation/bench-073727/`. The serial excerpt explicitly
omits repetitive producer output; the supplied serial ends at a truncated line.
The copied BDQ SHA256 matches the SD source. Context 8310225787329353575 matches
the frozen master scope. Runtime ingress depth was not expanded and is unknown.

The file has no reader integrity errors, 18693 primary records, 951 consecutive
IMU samples (0..950) and 45 timing records. Stage-6 losses are 37 source samples
(15 + 22) and one evidence record, followed by reason-31 essential-metadata
exclusion. Clean shutdown and remote cleanup are true; the IMU tail is incomplete.
The producer's 500 samples/s remains the primary scheduler, not IMU throughput.
Later legacy probes demonstrate administrative finalization, not Wi-Fi enable.

The valid first-loss scope is 411445us, with 265 retained CAN records, 128/128
ingress and one retention drop, 36 SPI RX drops, no new CAN software/hardware
capture losses and no malformed SPI slots. Relative to the preceding run, SPI
drops fall from 166 to 36, but sample polls fall from 433 to 275 and prepared
sample fragments from 426 to 268. Persisted IMU samples fall from 1206 to 951.
This single comparison does not establish a timing regression or sustained
improvement. The first-loss window and later BDQ exclusion cover different ends;
do not divide all persisted samples by the frozen scope.

Mean status/SPI/CAN service costs are 11.27/85.99/41.61us across 821/821/218
calls. Maxima are 45/675/196us. Timed lanes account for 21.61% of the scope,
including interrupts and instrumentation; this does not identify the rest as
idle. Histogram rows are [821,0,0,0,0], [0,736,75,10,0], [168,38,12,0,0]. Later
runtime malformed_slots=1 and spi_recoveries=1 are cumulative observations;
the active frozen window has neither. The unchanged late power/readback flags
and historical CAN error/recovery counters still do not date an electrical cause.

Ranked follow-up predictions, before changing scheduling again:

1. If control/empty selections consume the useful data budget, distinct data
   fragments will be close to prepared data fragments, but too few CAN records
   will be retired by real ACKs within the scope.
2. If delayed replies provoke repeated data requests, prepared data fragments
   will substantially exceed distinct (node, class, object, index) fragments.
3. If small batches amplify fixed per-object overhead, the batch record-count
   histogram will concentrate below the maximum 13 records. The host's lag-only
   model is still not a complete physical adapter/timing model; its two-exchange
   success does not establish hardware capacity.

The next **master-only diagnostic** retains the inventory/CRC optimizations and
appends version-2 fields to `gMasterDrainInfo`. It does not alter polling,
admission, ACK behavior, wire formats, ISR ownership or queue capacities. Data
array lanes are [sample, evidence]. `data_objects`/`data_records` count each
distinct prepared object's CAN records once; `data_unique_fragments` and
`data_repeat_fragments` distinguish newly prepared indices from repeated indices
for that node/class/object within this scope. These are **prepared replies, not
physical MISO deliveries or logger receipts**. The helper reads the main-owned
output before publication and adds no CRC calculation. Its overhead is included
in SPI-processing timing and can perturb physical scheduling.

`data_acked_objects`/`data_acked_records` count actual retirement, using the real
service's objects_acked advance and the pre-call batch count. Accepted ACK replays
and rejected ACK checksums do not count. `data_head_polls` counts object-zero data
polls; `data_empty_polls` counts data polls producing IDLE, not transfer errors.
`data_batch_records[0..1][0..13]` is a distinct prepared-object histogram: index
is the number of retained CAN records, not source samples; index 0 is unused.
Bookkeeping IDs/masks reset with START scope and freeze with all other fields.

The production-owner regression observes distinct/repeated indices, an actual
ACK and replay, a rejected checksum, separate node/class IDs, maximum batch/index,
preemption immediately after publication, first-loss freeze and scope reset.
Disabling just the observation hook produces the expected runtime assertion;
this is not a compile-failure claim. Focused master, measurement and integrated
storage/ledger checks and the acquisition-profile target build pass. Physical
recording remains unresolved; this diagnostic is not a proposed capacity fix.
Fresh independent source/artifact review finds no actionable issues. Linked GPIO
vector selection passes. The target adds 536 bytes flash and 240 bytes RAM;
BANK0 has 2813 bytes unallocated and the reserved stack remains 2KiB. Runtime
stack margin has not been measured.

Use the new master-only bundle
`C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke-master-drain-efficiency`.
Keep the currently installed fragment-window logger and SYNC-scope node. Load
the new `.out` symbols in CCS: version 2 changes debugger layout/addresses.
Repeat the normal motion recording/stop/cleanup procedure, then retain the BDQ,
complete serial and both master structs. Expand the new data counter arrays and
both batch-histogram rows; the bookkeeping ID/mask arrays need not be pasted
unless requested. A later Wi-Fi enable remains a separate check.

## Later stages and rebuilds

This image intentionally rejects a second active IMU. Prepare a separately
authorized multi-node bench build before moving to that stage; cabling variations
can then follow the planned sequence. This run does not close qualification
#175/#176 or enable production admission.

To rebuild the logger locally without accessing a device:

```powershell
& C:/Users/benco/.platformio/penv/Scripts/pio.exe run -d firmware -e bodaqs_s3_mini_n4r2_imu_smoke
```

The normal `bodaqs_s3_mini_n4r2` environment remains the guarded production build.

After rebuilding the master, check the actual linked GPIO vector (TI readelf
path shown for this machine):

```powershell
python firmware/tools/test_master_irq_vector.py firmware/can-fd/master/ticlang/bodaqs_can_master.out `
  --readelf C:/ti/ccs2101/ccs/tools/compiler/ti-cgt-armllvm_5.1.1.LTS/bin/tiarmreadelf.exe
```
