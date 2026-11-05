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
