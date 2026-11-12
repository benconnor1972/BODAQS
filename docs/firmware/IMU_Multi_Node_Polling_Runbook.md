# r16 multi-node polling baseline

This is an explicitly unqualified bench extension of r15. Establish real one-,
two- and four-node delivery before changing polling, pacing or IRQ behavior.
Production admission remains closed without qualified costs. No IRQ is used.

## Images and hardware

Install the selected `multi_node` logger from `BUILD_MANIFEST.json` only after
checking its passed status. Firmware name: `bodaqs_a8_imu_adc_multi_node_r16`;
environment: `bodaqs_s3_mini_n4r2_imu_adc_multi_node` (A8 ESP32-S3 N4R2).
The bundle contains the exact retained r10 master and node image and r15 logger
rollback. Do not substitute a newly rebuilt peer image. Node image source
provenance remains unknown; its retained SHA identifies the tested artifact.
Additional nodes need that same node image and distinct addresses 0,1,2,3.
Verify each actual hardware UID/address and CAN acquisition profile 2 in the
inventory before starting. Address provisioning follows the board's existing
procedure; this preparation does not invent new wiring or switch assignments.
Keep the existing CAN termination/power arrangement appropriate to the wired bus.

Fixed settings: mode0, measurement v2, 256-byte slots at16MHz, 500us CAN start
spacing, 5us CS setup, master RX depth2, CAN1M/4M profile2, ADC priority3 and storage
priority2. Retain complete ADC setup/START operations. IRQ, transport budgets,
retry policy, clock mapping, raw axes and packet schemas are unchanged.

The extension permits 1/2/4 selected IMUs with ADC-off at500Hz (a primary heartbeat)
or the retained r15 analog bench configurations. Three participants and unrelated
active sensors are rejected. The prepared cases deliberately use only the matrix
below. Admission means authorization to measure, not demonstrated capacity.

## Configurations and run order

Generate local private copies from the tested r15 four-channel500Hz export:

```powershell
python firmware/tools/prepare_multi_node_cases.py --config <r15-export.txt> --output-dir <fresh-private-directory>
```

Full configs retain Wi-Fi credentials; keep them local. The restore file is an
exact byte copy of the source. Extra IMUs have unique bench names, addresses and
sensor IDs; installation pose/calibration is cleared rather than copied from node0.

| Case | IMUs | Active analog inputs | Primary Hz |
| --- | --- | --- | --- |
| A | 0 | none | 500 |
| B | 0,1 | none | 500 |
| C | 0,1,2,3 | none | 500 |
| D | 0,1,2,3 | AIN0,4 | 500 |
| E | 0,1,2,3 | AIN0,1,4,5 | 200 |
| F | 0,1,2,3 | AIN0,1,4,5 | 500 |

1. Start with A, then B, then C. Use a fresh restart of all participating boards
   for each first capture, retaining boot/configuration serial output. Verify
   every expected node reconciles to the desired profile. A missing participant
   invalidates that case even if best-effort logging starts with the others.
2. Record about60 seconds per case; stop with the normal logging button and wait
   for `Log file closed.` Copy the finalized BDQ, complete serial output and the
   actual config export into a **new** `Results/<case>/<attempt>/` directory.
   Preserve unsuccessful cases. Do not reuse names or copy a still-open file.
3. Export `gMasterDrainInfo` and `gMasterRuntimeInfo` using the existing CCS JSON
   exporter before another capture resets evidence. Keep 64-bit identities exact:
   CCS JSON number rounding is not an identity match against BDQ decimal strings.
4. If C is viable, run D/E/F in order. If C has persistent backlog or substantial
   losses, preserve that evidence and assess it before spending time on heavier
   mixed cases. Do not change clocks or pacing between cases to rescue a result.
5. After the first complete four-node case, perform one ordinary STOP/start on
   the same powered setup to check identity reset and cleanup. Label this attempt
   separately from fresh-boot cases. A later sustained test is warranted only
   after short cases are understood. Controlled storage-stall testing stays deferred.

## Assessment

Use the source archive/checkout matching this candidate; the assessor imports the
analysis package from its repository. The copied entry point alone is not standalone.

```powershell
python firmware/tools/assess_multi_imu_recording.py Results/C/attempt1/capture.bdq --expected-nodes 0,1,2,3 --output Results/C/attempt1/assessment.json
```

The command requires explicit expected membership and refuses to overwrite a
report. Exit0 means strict complete delivery; exit1 means inspect the report,
including small STOP-tail gaps. Existing single-node assessment is preserved.

Compare every node's unique samples, internal/tail gaps, ambiguities, duplicates,
source identities, confirmed STOP and drain boundary. The aggregate percentage
is unknown when any expected stream/identity/source bound is missing. A healthy
node cannot hide a stalled node in the totals. Primary continuity/flags and all
file errors are checked too. Capture timing remains unreconstructed; no claim
of synchronized sample times is introduced.

The additive footer `remote_node_flow` and per-node final `[FLOW]` lines expose
RAM-accepted packet/sample/12-byte-axis totals, consumer waits and **sampled**
queue peaks/capacities through producer retirement. They do not prove SD writes,
unique source delivery or a true queue high-water bound. Reconcile them with
per-stream file results. The first-loss snapshot and transport totals may cover
different intervals; do not divide their counters by unrelated durations.

Also compare master ingress drops/depth, CAN software/hardware losses, valid
retained objects, empty/repeated replies, decoder failures and final queue state.
SPI request drops/retries are not automatically missing sensor samples.
CRC/header failures remain rejected, never repaired. Record storage write maxima
and queues alongside ADC reuse/ages; floating analog inputs establish scheduling
only, not voltage accuracy, channel association or analog settling.

Successful host tests and compilation do not demonstrate four-node throughput,
physical clock behavior or storage headroom. These captures locate the next
bottleneck and supply a baseline for a later ready/IRQ or polling improvement.
