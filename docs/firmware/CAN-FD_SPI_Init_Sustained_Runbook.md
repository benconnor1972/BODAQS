# r10: longer mixed recording with r9 initialization

This candidate keeps the r9 disabled-initialization control and removes boundary
tracing on both logger and master. It retains strict packet/CRC validation,
bounded original rejected-reply capture, FLOW/loss/decode counters, ADC freshness,
master phase/queue timing and storage diagnostics. There is no frozen boundary
trace to export. Ordinary counters can be exported after STOP if needed.

Mode0, requested16MHz,256 physical bytes, priming1, RX2,500us logger start spacing,
5us CS setup, ADC command/rate behavior and node firmware remain as in r9. The
application name changes to `bodaqs_a8_imu_adc_sustained_r10`. No guard envelope,
packet repair or admission change is included. This is a physical experiment,
not reliability, voltage accuracy or admission qualification.

## Installed images

The passed manifest selects `variants.sustained`: master in
`artifacts/master-sustained/bodaqs_can_master.out` and logger application in
`artifacts/logger-sustained/firmware.bin`. Both require programming. Preserve the
logger partition table/NVS/settings; application offset is0x10000. Keep the IMU
node installed. `artifacts/fixed-rollback-master/` and `artifacts/fixed-logger/`
contain exact r9 master/r8 logger rollback images, not the selected test pair.
The separate flash record establishes what was actually installed.

## Acquire

1. After the matched pair is flashed, restart the IMU node and logger to give a
   repeatable start. Master programming already supplies a fresh boot. Keep the
   same saved configuration: one IMU and one500Hz analog channel on each ADC,
   multistream BDQ v2. Floating inputs may remain as before.
2. Capture complete serial output. Start with Enter. Check no sensor exclusion,
   three streams and two primary columns. If they differ, STOP and preserve the
   log rather than treating it as the intended mixed test.
3. Record5-10 minutes. Use the same SD card and hardware. Do not add scope probes,
   change rates or enable WiFi during recording. A periodic500 rows/s message
   describes logging rows, not fresh ADC conversions.
4. STOP normally with Enter; wait for `[Storage] Log file closed.` and cleanup.
   Copy the finalized BDQ and provide its path plus complete serial output.
   No boundary-trace freeze/export is expected. No recording is agent-started.

## Assess

Compare recording-window decode failures per slot separately from through-cleanup
counters. Keep original rejected bytes and exact image/recipe identities.
Compare source-bounded sample delivery, where gaps occur and whether loss remains
after startup; do not add overlapping loss categories. Check terminal samples,
STOP/cleanup, storage drops/queues, and ADC fresh/reused/no-sample rows, acquisition
failures/timeouts and row-age distributions. Freshness is not voltage accuracy.

The r9 reference had6/42171 rejected recording-window replies,9 through cleanup,
1471 early missing IMU samples plus4 at the end, and approximately16% ADC row
reuse. The longer run tests whether useful delivery and ADC freshness remain
acceptable with tracing removed. It does not predeclare a pass threshold or
automatically qualify this sensor configuration. Investigate the fixed-offset
guard fallback only if residual corruption materially limits useful delivery.
Controlled storage-stall testing remains deferred by user decision.
