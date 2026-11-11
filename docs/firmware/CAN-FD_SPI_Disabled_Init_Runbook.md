# r9: one master-only initialization control

This test removes the generated initializer's early empty-FIFO SPI enable.
Configuration remains disabled until the existing arming code has written byte0,
prepared RX/TX DMA and executed its barrier. Startup and every physical CS
retirement use the same generated configuration through a scoped application
wrapper. No generated output or installed SDK is hand-edited. Other SPI instances
and the default0 build retain normal initialization.

This is a falsifiable initialization/shifter hypothesis, not a confirmed fix.
The prior prototype used similar initialization ordering. Do not add more phase,
delay, clock or preload-count trials to this control. A four-byte physical guard
remains the next recommendation if it fails; that guard is not in this image.

## Installed images

| Role | Selection |
| --- | --- |
| Test master | `artifacts/master-init-disabled/bodaqs_can_master.out` |
| Logger | Retain exact r8 `bodaqs_a8_imu_adc_trace_r8` |
| IMU node | Retain existing node |
| Master rollback | Exact r8 image in `artifacts/fixed-rollback-master/` |

`artifacts/master-init-reference/` is a default0 build for offline compatibility
checking; it is not an additional requested physical trial. The manifest's
`variants.trace` selects the revised master and exact reused logger for export.
Check bundle `status: passed`; consult the separate flash record for installed
image hash and whether programming completed. Flashing was explicitly authorized
for this first test. No recording is started by the build or flash scripts.

Retained logger SHA256:
`838be24948847181ad5b1da5fbbeb20fcfe927cd0a272b0c8c003058aa83034f`.
Retained logger recipe:
`recipe-sha256:f11a0e48ec97f44f9b6d9fb064db8e9067a8cc6f467e3e2051929e71fe0bac8c`.
Master settings remain v2,256 physical bytes, priming1, mode0, RX2,
phase/queue diagnostics and boundary trace1. Logger retains requested16MHz,
500us start spacing,5us CS setup and its current ADC command/rate behavior.

## Acquire the first control

1. After master programming succeeds, restart the logger and IMU node. The
   master must also be on a fresh boot with no prior recording; programming/run
   provides that fresh boot. Do not reload the older r8 master.
2. Keep the same saved mixed configuration: one IMU, one500Hz analog channel on
   each ADC, multistream BDQ v2. Floating inputs may remain as before.
3. Start using Enter. Check no sensor exclusion, three streams and two primary
   columns. Record approximately30-45 seconds.
4. STOP with Enter. Wait for `[Storage] Log file closed.` and completed cleanup.
   Preserve the finalized BDQ and complete START/STOP/DRAIN/FLOW serial output.
5. Keep the master running/connected and do not reset or start another recording
   until any frozen trace is exported. Provide the BDQ path and serial output;
   the agent can export through the existing CCS session as in r8.

The initial discriminator is the unchanged logger's decode-failure counter and
original rejected bytes. If no rejection occurs, the trace will be unfrozen:
that is expected, and an unfrozen live ring must not be joined as a failed slot.
Absence of a fault in one short run is encouraging evidence, not qualification.

## Export and interpretation

The trace layout remains1/7328 bytes. The supplied `export_spi_trace.js` uses this
bundle's new master symbols and hash; do not use the r8 image's addresses/symbols.
For a standalone export, CCS must release the probe first. An already-connected
CCS session can instead be reused by the agent; no reset/programming is required
for export. Do not unplug or power-cycle to release the probe.

After normal STOP, with CCS not holding the probe, the manual standalone command is:

```powershell
& 'C:\ti\ccs2101\ccs\scripting\run.bat' 'C:\Users\benco\dev\BODAQS-worktrees\imu-adc-disabled-init-r9\export_spi_trace.js'
```

Successful frozen export creates `Evidence/master-trace.bin`. The existing r8
join tool can read this unchanged layout using the new finalized BDQ. It still
requires exact boot/context, first failure, adjacent per-CS sequence and full
MOSI equality. Marker completion is not a freeze acknowledgement. If no fault
was recorded, retain the counter/file evidence rather than trying to force freeze.

If the first-byte signature disappears or collapses, next confirm useful IMU
delivery, ADC freshness and cleanup over a longer run with heavyweight tracing
removed. If it remains comparable, reject this ordering as a useful standalone
solution and proceed to the explicit guard-envelope fallback. CRC, original bytes,
source-final delivery and general admission criteria are unchanged. This run
does not qualify ADC voltage accuracy/mux behavior or controlled storage stalls.

## Software evidence

Host tests execute the production wrapper as a separate translation unit, prove
default/selected-only behavior and macro isolation, and combine it with the
actual arm and trace observer bodies through startup and short/full reset/rearm.
Removing the exact gate fails on the early empty-FIFO enable. Hardware and generated
configuration are stand-ins there. Target builds use the real unmodified generated
configuration; reference/control generated sources must match. Existing adapter
tests cover queue/retirement/STOP/fence behavior separately. These checks establish
the intended ordering, not reproduction or elimination of the physical fault.
