# Stopped LSM6DSO32X profile verification

Implementation: ticket #159. Physical checks below have **not been run**.
Configuration readback does not establish sample production, FIFO operation,
settling, measured ODR, signal response, filter delay or recording readiness.

## Configuration and observation

The appended sensor type `lsm6dso32x_imu` (numeric type 8) accepts
`provider=can:N` (`canN` remains an input alias), `endpoint=imu`, and
`profile=imu6_3333_32g_2000dps_v1`. Profile maps to wire 1/version 1.
Logical identity, domain/end, mount point, host calibration reference and saved
mounting quaternion use the shared parameter store. No BMI270 profile decoder,
FIFO validation or assisted sample capture is used for this type. Local BMI270
and legacy remote BMI270 entries retain their existing meanings.

Web and JSON edits use the shared idle validation/save/rebuild path. A successful
save requests asynchronous reconciliation, including fresh verification on a
same-settings save. Persistence or validation failure restores the prior desired
configuration. Remote rejection/failure leaves valid desired settings saved.
The sensor editor distinguishes saved desired profile, pending/accepted/adjusted/
rejected/uncertain outcome, current effective state, health and historical proof.
The control API exposes matching observations and decimal-string 64-bit identities.
After the original five-second COMMIT result deadline, knowledge is uncertain;
an outstanding transport exchange is drained without extending that deadline.

Profile 1 runs accel and gyro while stopped: CTRL1_XL=94h, CTRL2_G=9Ch.
Both use nominal 3333/1 Hz, +/-32g and +/-2000 degrees/s. Sensitivities are
122/125000 g/count and 7/100 degrees/s/count. High performance operation and
BDU/address increment are enabled; optional accel LPF2/HP and gyro LPF1/HP
are bypassed. Internal accel LPF1/gyro LPF2 remain described by filter model 1.
FIFO, batching, interrupt routes, sensor timestamp and auxiliary engines remain
disabled. No samples are read, sequenced, batched or transported. Acquisition
readiness remains false. Enabled applicable groups are 07FFh, known groups 047Fh;
native timing, measured rates and filter delay are explicitly unknown. Disabled
acquisition groups remain not applicable (known/applicable 0441h).

## Bench acceptance record (pending)

Use the production node/master wiring and equipment checklist in
[disabled IMU verification](CAN-FD_Disabled_IMU_Verification.md). Record board
revision, sensor marking, firmware commits, power supply, instrument model,
probe positions and raw traces/register captures. Do not flash without operator
authorization. Run while the logger is idle:

1. Confirm safe CS/interrupt levels and mode-3 1 MHz SPI transactions. Capture CS
   continuously across address/data; verify no FIFO/data-output register reads.
2. Save the canonical type/profile via web and JSON without restarting. Record
   desired generation, accepting session, pending result, effective revision and
   epoch. Verify owned register image (including banked auxiliary enables),
   CTRL1_XL=94h and CTRL2_G=9Ch, FIFO bypass and zero interrupt routes.
3. Save the same configuration again. Capture fresh complete readback, no reset,
   stable applied revision, updated accepting generation and corresponding epoch.
   Read immutable snapshots during verification. Contradicted proof must become
   historical/current-unknown immediately, before any reset submission.
4. Mute/disable idle endpoint: verify CTRL1_XL=04h, CTRL2_G=0Ch, engine bits zero,
   still no acquisition. Reenable and verify running engine bits separately from
   acquisition-active (zero). Current known proof must match each state.
5. Inject SPI/identity/readback failures. Keep saved desired settings; report
   rejection/fault, current-unknown and historical prior proof. Measure bounded
   reset (100 ms) and application (2 s) behavior, with inspection responsive.
6. Record pass/fail for each check and attach raw evidence. Leave sample timing,
   settling, FIFO servicing and amplitude/phase validation explicitly untested.
