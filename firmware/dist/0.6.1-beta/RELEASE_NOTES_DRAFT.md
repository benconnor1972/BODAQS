# BODAQS Firmware 0.6.1-beta Release Notes Draft

Status: draft for beta testing  
Build date: 11 October 2026  
Release date: TBD

Firmware `0.6.1-beta` provides builds for RC3, A8 and Prototype F. It improves
feedback when configuration changes prevent recording, adds optional startup
reports on SD, and includes the logging stability and buffering work tested
during the 0.6.1 alpha series. These notes describe changes from the packaged
0.6.0 images, including fixes documented after those images were generated.

## Highlights

- The home screen identifies configuration conflicts and changes that require
  restart. A fresh Enter press on the restart prompt restarts the logger.
- Log start automatically selects and saves BDQ v2 when multiple active BMI270s
  or mixed accelerometer/gyroscope rates require it.
- The General page can enable startup diagnostic reports on SD, retaining the
  latest 32 saved reports. The option defaults to off.
- The Sensors page includes an Input column, such as `I2C1 [0x68]`, `AIN4` or
  `UART0`.
- Larger BDQ v2 primary and AS5600 angle queues provide more room for SD write
  stalls. ADC waiting and log finalization include fixes for observed resets.
- All three beta images retain whole-FIFO acquisition and the simple
  two-deferral scheduling policy, with the latest startup recovery diagnostics.

## Configuration and log start

While idle, the home screen displays persistent prompts when the saved
configuration cannot safely start a recording:

| Prompt | Meaning and action |
| --- | --- |
| `Restart required` / `Press Enter` | Saved sensor configuration differs from the running instances and cannot be applied live. Press and release Enter on the home screen to restart. |
| `Config conflict` / `Please review` | Active sensors share an input or another assignment conflicts. Correct the configuration in the Web UI. |
| `Sensor config` / `Please review` | A sensor type, input or BMI270 setting is invalid. Correct it before starting. |

Conflict checks include I2C bus/address, analog GPIO, external ADC channels
(including differential negative channels), UART assignments, duplicate sensor
names, active IMU identifiers and addresses reserved by configured board devices.
Muted sensors do not reserve inputs or require a format upgrade; names must
remain unique. Muting cannot resolve an electrical address collision between
physically connected I2C devices.

Conflict warnings take precedence over restart warnings. Successful live edits,
or edits reverted to match the running configuration, clear the restart warning.
General, Sensors and individual sensor pages show the specific reason and
refresh the notice after saving. Serial also records the reason for a refused
start. The Enter shortcut applies on the idle home screen; a restart does not
automatically begin recording.

When CSV or BDQ v1 is selected, multiple active BMI270s or a mixed-rate BMI270
profile trigger automatic selection of `bodaqs_multi_stream_binary` (BDQ v2).
Firmware saves that selection before preparing sensors or creating the log.
A failed save refuses the start. Compatible CSV and BDQ v1 configurations keep
their selection, and there is no automatic downgrade from BDQ v2. The actual
format appears on the logging screen.

Power, upload-mode, SD/file-open, column-count and sensor/session checks still
apply. An IMU that fails initialization may remain unavailable while other
sensors record; this alone does not produce the configuration restart prompt.

## Startup diagnostics and recovery

Enable **Save startup diagnostics to SD** on the General page, save, and restart.
The configuration key is `startup_log_to_sd=true`; omitted or false means off.
Changing the option takes effect on the next restart.

Reports include firmware/board identity, reset reason, acquisition configuration,
I2C initialization attempts, recovery stages and final device readiness. They
capture successful boots as well as failures. Files rotate through
`/startup/boot-00.txt` to `boot-31.txt`; the sequence in each header gives their
order even when RTC time is unavailable.

Capture uses a temporary 32 KiB RAM buffer, released after the deferred SD save.
It records selected startup diagnostics rather than the entire serial log.
Overflow is marked and final readiness is retained. Missing SD or insufficient
RAM is reported on serial and startup continues. No startup reports are written
during acquisition. A crash or loss of power before saving can leave no report
for that boot.

All three beta images enable the recovery diagnostics used in the latest RC3
alpha build: failed devices receive bounded delayed retries, controller recovery
and, if needed, a temporary 100 kHz retry stage. The normal bus clock is restored
afterwards. Healthy devices are not deliberately reinitialized. BMI270 identity
probes use the Arduino HAL path to retain the underlying ESP error code; normal
sensor transfers continue through Wire. Controller recovery does not power-cycle
the sensors. The earlier long startup speed-comparison probe is disabled.

## Acquisition and storage

The BDQ v2 primary queue targets 5.12 seconds of configured primary cadence,
rounded up to a power of two and capped at 4,096 records. At 200 Hz it holds
1,024 records; at 500 Hz it holds 4,096. The AS5600 angle native-stream queue
holds 2,048 records. Larger queues absorb longer storage stalls but cannot
compensate for sustained inadequate SD throughput or missing acquisitions.

External ADC workers with a DRDY pin wait on GPIO notifications rather than
continuously polling conversions, with ready-level checks and bounded timeout
handling. Log finalization uses separate helpers and moves large diagnostics
scratch objects off the loop stack. The loop task has 16 KiB of stack. These
changes address the CPU idle-starvation and final-summary stack-overflow resets
observed during alpha testing.

The scheduler uses whole-FIFO reads and at most two deadline-based deferrals
before servicing a buffered client. Experimental model-based extra deferrals
and interruptible FIFO reads are excluded. Saved `fifo_service_mode` and
`fifo_slice_bytes` settings are ignored; existing profile, FIFO poll-rate and
AS5600 rate settings still apply. A temporary transfer priority of 2 is enabled
for scheduler I2C transactions, as in the latest RC3 test image.

## Compatibility and migration

- Install the image for the matching board. RC3 and A8 images are distinct even
  though they share pin mapping. RC3 and Prototype F retain Sleep as user
  power-off; A8 keeps its existing behavior without a default Sleep control.
- Existing configurations remain readable. Startup SD capture defaults to off,
  and the Input column requires no new setting.
- Automatic BDQ v2 selection is persisted. Use current BODAQS import and
  analysis tooling for recordings that are promoted to BDQ v2.
- After editing sensor acquisition settings, follow any restart prompt before
  recording. Correct conflicts rather than repeatedly attempting to start.

## Validation and remaining limitations

- The complete host suite passed, including 24 checks of the production
  two-deferral scheduler, 46 startup recovery checks, 70 startup report checks,
  and 116 log-start checks.
- All three PlatformIO board builds passed. Their application and bootloader
  images passed ESP checksum and validation-hash checks.
- Embedded firmware version/name, factory application offset and partition
  capacity were checked for each target. Combined-image component bytes and
  erased gaps were verified; hashes cover all 12 images.

| Board | Static RAM used / available | Application flash used / available |
| --- | --- | --- |
| RC3 | 176,140 / 327,680 bytes | 1,851,413 / 2,097,152 bytes |
| A8 | 176,140 / 327,680 bytes | 1,851,413 / 2,097,152 bytes |
| Prototype F | 175,880 / 327,680 bytes | 1,849,253 / 2,097,152 bytes |

Physical beta acceptance should include cold boots and warm restarts, the
configuration prompts and Enter shortcut, automatic format selection, the Input
column, startup report rotation, and repeated recording start/stop cycles on
each board. For A8, include ADC freshness and missing-slot checks at the intended
rate. Host checks cannot establish physical interrupt timing, stack headroom or
shared-bus sample cadence.

Intermittent BMI270 initialization failures are still under investigation.
The added diagnostics and recovery are not evidence that their underlying cause
has been fixed. AS5600 has no FIFO: shared-bus IMU service can delay its reads,
so matching its configured rate to the primary rate does not guarantee that
achieved cadence. High-rate IMU/AS5600 combinations need data-quality checks.
SD stall tolerance remains dependent on the card and enabled streams. The
64-column primary-stream limit remains in effect.

## Images and flashing

The package is in `firmware/dist/0.6.1-beta/`. Each board has an application,
bootloader, partition table and combined full-flash image. `SHA256SUMS.txt`
covers all 12 binaries; `BUILD_MANIFEST.json` records build targets, settings,
image sizes and hashes.

| Board | Application update at 0x10000 | Full image at 0x00000 |
| --- | --- | --- |
| RC3 | [bodaqs_v1RC3-0.6.1-beta.bin](bodaqs_v1RC3-0.6.1-beta.bin) | [bodaqs_v1RC3-0.6.1-beta-full.bin](bodaqs_v1RC3-0.6.1-beta-full.bin) |
| A8 | [bodaqs_a8-0.6.1-beta.bin](bodaqs_a8-0.6.1-beta.bin) | [bodaqs_a8-0.6.1-beta-full.bin](bodaqs_a8-0.6.1-beta-full.bin) |
| Prototype F | [bodaqs_4f-0.6.1-beta.bin](bodaqs_4f-0.6.1-beta.bin) | [bodaqs_4f-0.6.1-beta-full.bin](bodaqs_4f-0.6.1-beta-full.bin) |

[SHA-256 checksums](SHA256SUMS.txt) cover
all application, bootloader, partition and combined images.

For an application update, flash the matching application `.bin` at `0x10000`.
For a blank or erased logger, flash its matching `-full.bin` at `0x00000`.
Separate component offsets are:

```text
0x00000  <board>-0.6.1-beta-bootloader.bin
0x08000  <board>-0.6.1-beta-partitions.bin
0x10000  <board>-0.6.1-beta.bin
```

Do not mix components from different board targets.
