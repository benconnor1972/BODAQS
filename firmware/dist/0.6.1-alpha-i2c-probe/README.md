# RC3 BMI270 startup I2C diagnostic

Firmware version: `0.6.1-alpha-i2c-probe`  
PlatformIO environment: `bodaqs_s3_mini_n4r2_rc3_i2c_probe`  
Board profile: `BODAQS_V1RC3`

This special build runs normal startup, then performs a controlled CHIP_ID
read test after `[BOOT] SETUP: ALL DONE`. The production build environments
do not enable this test. Existing SD configuration files are used unchanged.

## Flash and capture

For an application update, flash `bodaqs_v1RC3-i2c-probe.bin` at `0x10000`.
For a blank logger, the matching `bodaqs_v1RC3-i2c-probe-full.bin` goes at
`0x00000`. Separate bootloader and partition images use `0x00000` and
`0x08000`. SHA-256 hashes are in `SHA256SUMS.txt`.

Capture the serial output at 115200 baud through `[IMU-PROBE] DONE`. There are
progress messages every 100 reads. Run once after a full power cycle, then
use the normal Restart command and capture the warm-start run with the same
wiring, pull-ups, LTC4311 and sensor configuration. Repeat warm restarts to
catch the intermittent initialization failure. Keep the normal startup lines
alongside the probe results so each sensor's initialization status is known.

The test blocks the normal UI/logging loop until complete. With four responsive
IMUs it takes roughly one minute; repeated 50 ms transaction timeouts can
extend it to roughly eleven minutes. Wait for `DONE` before using the logger.

## Test performed

Each phase tests every distinct configured BMI270 bus/address, including muted
sensors and sensors whose normal initialization failed:

1. 1,000 reads of register `0x00` at 400 kHz.
2. 1,000 reads of register `0x00` at 100 kHz.
3. 1,000 reads of register `0x00` at 400 kHz again.

Each read uses a register-pointer write, repeated START, one-byte read and STOP,
with a 5 ms delay after each attempt. The expected reply is `0x24`.
The test uses the same Arduino ESP32 HAL combined-transfer function as the
production BMI270 repeated-START reads. Calling the HAL directly retains the
underlying ESP error code without thousands of individual Wire error messages.

The bus mutex is held throughout each device's block, so other users cannot
change its clock during the test. Each block restores the previous clock.
There is no sensor reset, initialization retry, power cycle or bus recovery
between phases. Normal startup still performs its existing initialization and
recovery attempts before the probe starts. The acquisition scheduler must be
idle; otherwise the probe aborts. Normal operation resumes after the test;
probe success does not change the sensor's recorded initialization status.

## Reading the results

Each `summary` includes phase, bus, address, clock, total reads and:

| Field | Meaning |
| --- | --- |
| `correct` | Successful one-byte transfers returning `0x24`. |
| `wrong` | Successful one-byte transfers returning another value. |
| `transfer_failed` | HAL transfer errors; no valid returned byte is counted. |
| `timeout` | Subset of transfer failures reported as `ESP_ERR_TIMEOUT`. |
| `short_read` | HAL reported success but did not supply exactly one byte. |
| `max_bad_run` | Longest consecutive sequence of incorrect or failed reads. |
| `restore_ok` | Whether restoring the original bus clock succeeded. |

The first eight abnormal reads per device/phase are printed with their attempt
number. `wrong_value` lines give the full histogram of incorrect replies.
An ESP transfer failure does not identify which byte was NACKed; use the scope
to distinguish address NACKs from other transaction failures. A normal master
NACK terminating the one-byte read is not a transfer failure.

Errors at 400 kHz, clean reads at 100 kHz, and errors again at 400 kHz support
a rate-sensitive communication problem. Wrong bytes demonstrate that completed
transfers returned incorrect IDs, but do not alone prove a wiring cause.
Failure at both speeds which clears only after a power cycle also leaves
retained device state, interface selection and power issues in consideration.
Clean reads at both speeds do not rule out intermittent glitches or problems
with the much larger initialization/configuration transfers.

## Rebuild and validation

```powershell
pio run -e bodaqs_s3_mini_n4r2_rc3_i2c_probe
```

The diagnostic and ordinary RC3 builds were compiled. The rebuilt host suite
passed. A separate simulated-bus check exercised the actual diagnostic source
with correct replies, wrong IDs, generic errors and timeouts; it checked rate
order, counters, wrong-value histograms, clock restoration, duplicate and
unavailable devices, and refusal to run with an active acquisition scheduler.
These checks cannot establish behavior on the physical bus.
