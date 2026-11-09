# First real IMU recording: operator runbook

This candidate records one nominal3.33kHz CAN IMU for approximately30seconds,
including a low16 sequence wrap. ADCs and unrelated sensors must be disabled.
It uses real acquisition control, retained CAN batches, logger RAM and SD/BDQ.
General admission, sustained storage capacity and reconstructed timing remain
unqualified. Historical round17 and the original four-node no-go are unchanged.

## Candidate selection

Use the new `first-real-imu-recording-bundle-r2` directory. Require
`BUILD_MANIFEST.json` status `passed`, profile `first-recording`, a clean pinned
source commit, and matching SHA256SUMS. Preserve the manifest with the recording.
The two CAN profiles are alternatives: use the **acquisition** pair below.
Never combine a new master/logger with old measurement firmware.

| Device | Bundle image | Selected configuration |
|---|---|---|
| G3507 node | `artifacts/node-acquisition/bodaqs_can_node.out` | CAN1Mbit/s nominal,4Mbit/s data |
| G3518 master | `artifacts/master-acquisition/bodaqs_can_master.out` | Same CAN; measurement v2 |
| A8 ESP32-S3 Mini N4R2 | `artifacts/a8-bodaqs_s3_mini_n4r2_imu_smoke/firmware.bin` | One-node unqualified guard; v2 |

Measurement v2 requests256B at16MHz with25us inter-CS guard and boundary-only
publication; actual SCK has not been measured. Lease5s, renewal1s, freshness300ms.
The bundle includes maps and master compiler stack reports; runtime watermarks
remain an operator observation. Use existing boards, wiring and known-good power
procedures. Back up SD configuration and logs before programming.

## Program and configure (manual)

1. In CCS load the acquisition master and node images above into the corresponding
   targets and Run/Resume both. Keep them running through recording and cleanup.
2. Program the logger using your established application update procedure or the
   supplied four segments. For a full segmented upload, from the bundle directory,
   substitute the actual logger port in this established A8 command:

```powershell
$flashPython = 'C:/Users/benco/.platformio/penv/Scripts/python.exe'
$flashTool = 'C:/Users/benco/.platformio/packages/tool-esptoolpy/esptool.py'
& $flashPython $flashTool --chip esp32s3 --port COMx --baud 460800 write_flash --flash_size 4MB `
  0x0 artifacts/a8-bodaqs_s3_mini_n4r2_imu_smoke/bootloader.bin `
  0x8000 artifacts/a8-bodaqs_s3_mini_n4r2_imu_smoke/partitions.bin `
  0xe000 artifacts/a8-bodaqs_s3_mini_n4r2_imu_smoke/boot_app0.bin `
  0x10000 artifacts/a8-bodaqs_s3_mini_n4r2_imu_smoke/firmware.bin
```

3. Select one CAN IMU, endpoint `imu`, profile `imu6_3333_32g_2000dps_v1`.
   Persistently mute every other logical sensor using **Muted by default**;
   disable external ADC channels and verify no ADC conversions are running.
   Use the reconciled sensor's existing node address; no address/wiring change.
4. Confirm master present/compatible and stopped IMU configuration reconciled.
   The sensor API `/api/v1/sensor?id=N` should show recording admission mode
   `single_node_smoke_unqualified`, `qualified=false`; `not evaluated` before an
   attempt is expected. `acquisition_ready=false` is a qualification flag.
   Record `/api/v1/device`, sensor JSON, SD configuration, image hashes and serial
   output alongside the capture. Existing explained bench FRONT_FAULT telemetry
   has the same meaning as before; this candidate adds no fault bypass.

## Capture and normal STOP

1. Start using the existing recording control. Wait for **Recording**, rather
   than counting configuration/preparation time. Note the wall-clock start.
2. Acquire for approximately30seconds. Gentle movement is useful to confirm six
   axes respond. Preserve serial/API diagnostics; note resets, repeated overload,
   persistent backlog growth, storage faults or configuration changes.
3. Request STOP once. Leave all boards powered and running: normal tail drain is
   five seconds **after confirmed remote STOP**, followed by fence/release/exit
   and SD finalization. Wait for **Recording finalized** before removing SD or
   starting another recording. Do not use SD activity cessation as cleanup proof.
4. Copy the BDQ and supporting observations into a fresh evidence directory.
   Preserve the original file; run the validator on a copy if moving media.

## Independent decode

From the pinned source worktree with the analysis dependencies installed:

```powershell
& C:/Users/benco/dev/BODAQS-worktrees/drain-capacity-evidence/spi-prototype/tool-venv/Scripts/python.exe -B `
  firmware/tools/validate_first_imu_recording.py C:/path/capture.bdq `
  --output-dir C:/path/new-capture-report
```

Outputs: `report.json`, `readings.csv` and `raw_timing_observations.csv`.
Readings use segment/full sequence and exact signed six-axis counts. Source,
recording/session/context, effective register/configuration provenance and file
hash are in the report. Sample timestamps are not reconstructed. Raw sensor,
node capture/SYNC and master observations are retained for later timing work.
CSV blank full sequence means unresolved identity; never fill it from nominal ODR.

`complete_delivery` requires clean file closure, full identity and START/STOP
bounds, confirmed drain, completed cleanup and no known sample gap/discard.
`isolated_five_sample_gap_warning` is a distinct functional-warning candidate;
it is neither complete delivery nor an admission pass. Any other result needs
review; exit1 still leaves readable-prefix outputs where possible. Invalid input
produces an explicit invalid report. Missing raw clock snapshots are reported
separately from axis coverage. Inspect gaps, loss stages/counts, final observation,
configuration, and the per-node tail window, rather than relying on the headline.

The file result does not prove30seconds of physical operation, electrical timing
or absence of persistent queue growth. Reconcile the operator notes, exact flashed
images, configuration and serial evidence before accepting the functional run.
Repeated overload/corruption/ambiguous identity does not meet this milestone.
Save all evidence for review before proceeding to ADC work or sustained tests.

## Interrupted or failed run

If STOP cannot be confirmed, the file may close as an explicitly uncertain prefix
after the bounded ten-second fallback. That is not proof the remote physically
stopped. Cleanup ownership remains locked until current node/master physical
fencing, administrative release and mode exit are verified. Do not force a new
recording, reset only the logger to rejoin, or assume a local lease deadline proves
cessation. Keep boards running and preserve diagnostics; if cleanup cannot recover,
use the established coordinated power/debug recovery procedure before retrying.

An SD failure may leave a CRC-valid prefix without a footer. RAM ACK never promised
SD durability. Preserve the file and report incomplete/unknown tail; do not repair
it into an apparent clean recording. No unattended upload or device probing is
performed by the build/validation tools.
