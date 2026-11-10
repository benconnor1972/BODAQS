# r8: correlate the first rejected reply with the master's TX source

Flash both matched r8 mode0 images manually, retain the existing node, and run
the same mixed IMU/ADC configuration. This is a diagnostic, not a throughput or
admission qualification. No scope capture or additional analog wiring is needed.

## Images

Use the `trace` variant in `BUILD_MANIFEST.json`; check `status` is `passed`.

| Target | Image relative to this bundle |
| --- | --- |
| Logger | `artifacts/logger-trace/firmware.bin` |
| Master | `artifacts/master-trace/bodaqs_can_master.out` |
| Node | Keep installed; exact reference in `artifacts/fixed-node/` |

Logger application offset is `0x10000`, using the existing compatible partition
table and saved configuration. Use the existing manual upload procedure. The
logger's firmware name must be `bodaqs_a8_imu_adc_trace_r8`. Master settings are
acquisition CAN, measurement v2, RX2, priming enabled, mode0 and boundary trace.
The logger retains 16MHz,256 bytes,500us start spacing and5us CS setup. Normal
builds keep their existing defaults. Both r8 endpoints are required.

For rollback use **both** exact r7 mode0 references in `artifacts/fixed-logger/`
and `artifacts/fixed-rollback-master/`, retaining the same node. Do not mix the
r8 trace logger with an older master and expect correlation.

## Acquire once

1. After flashing, restart all three boards. The master trace freezes only once
   per boot. Preserve the current mixed configuration: one IMU plus one500Hz
   analog channel on each ADC, multistream BDQ v2. Inputs may remain floating;
   this does not qualify voltage accuracy or channel switching.
2. Start normally using Enter. Check no sensor exclusion and that the BDQ v2
   header has the IMU/evidence streams as well as the primary ADC stream. If the
   IMU is excluded, stop and report that run rather than starting repeatedly.
3. Record for approximately30–45 seconds. The first confirmed rejected reply
   automatically triggers one tagged freeze request. There is no live print or
   button to operate. A malformed reply remains rejected; no data is repaired.
4. Stop using Enter. Wait for `[Storage] Log file closed.` and completed cleanup
   before copying the BDQ. Save START/STOP/DRAIN/FLOW output. Do not reset any
   board or start another recording before exporting the frozen master trace.

The logger preserves its original MOSI and rejected MISO, plus an adjacent
per-CS sequence. The master preserves eight physical transactions, even those
lost at the receive queue. It freezes before processing the tagged marker.
Observation copies can perturb timing. No captured fault means inconclusive.

## Export after STOP

The supplied `export_spi_trace.js` uses the r8 image as **symbols only** and reads
`gMasterSpiTrace`. It does not program or reset the target. It briefly halts the
master and resumes it afterwards. Run only with logging stopped. Ensure CCS is
not simultaneously holding the XDS110 session; do not click Load Program or
Restart. The supplied target configuration selects the master XDS110 connection.
If your CCS attach settings run reset/initialization actions, disable those
before attaching: a reset destroys this evidence.

From PowerShell, replace `$bundle` with this bundle's absolute directory:

```powershell
$bundle = 'C:\Users\benco\dev\BODAQS-worktrees\imu-adc-spi-trace-r8'
& 'C:\ti\ccs2101\ccs\scripting\run.bat' "$bundle\export_spi_trace.js"
```

Success creates `Evidence/master-trace.bin` (7328 bytes). The exporter refuses an
existing output, an incompatible layout, or an unfrozen/saturated trace, and
reports debugger read/resume failures. If resume fails, resume the master in CCS
before further use. Keep the export with the finalized BDQ and serial output.
An unfrozen trace is inconclusive: do not interpret its latest live ring as the
failed exchange. Preserve the failed run before retrying with a fresh boot.

## Return and interpretation

Provide the finalized BDQ path, complete serial output and `master-trace.bin`.
Keep their bundle identity. The offline join runs from the source checkout
recorded in the manifest (or extract `SOURCE.zip` first):

```powershell
python firmware/tools/join_spi_trace.py '<finalized.bdq>' '<master-trace.bin>' --output '<join.json>'
```

Use the existing analysis Python environment with the repository requirements.
The join requires exact master boot/context, unique logger exchange identity,
adjacent nonsaturated CAN-CS sequences, the immediate master predecessor's full
256-byte MOSI, and matching fingerprints. Missing or conflicting evidence is
inconclusive; marker transfer completion alone does not prove master freeze.

The join checks source header/CRC; canonical protocol acceptance is a separate
check using the existing production-decoder replay tool. If the selected source
changed, investigate its lifecycle. If both source copies are header/CRC-valid
and equal and received byte0 alone is zero, the fault occurred after the
observed staging; this still does not distinguish peripheral/on-wire behavior
from the logger receive path or prove readiness at the exact first clock.
SPI status/address fields are raw observations; DMA sizes use the SDK's masked
DMASZ.SIZE getter. Observation costs are included in the export. Source-final
delivery, admission bounds, known-input ADC checks and controlled storage-stall
testing remain separate.
