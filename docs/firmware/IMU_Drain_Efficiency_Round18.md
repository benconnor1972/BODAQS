# r18: useful drain efficiency, with separate software screens

The first physical test changes only minimum exchange-start spacing from 500 to
600 microseconds. Retain r17's ACK-fetch sweep. Test whether a lower issue rate
reduces request overruns/stale work enough to improve useful two-node delivery.
This is a hypothesis, not a predicted speedup or a qualified admission profile.

Use the passed `adc-ack-pacing` candidate bundle. Candidate logger is
`artifacts/logger-ack_pacing/firmware.bin`, environment
`bodaqs_s3_mini_n4r2_imu_adc_ack_pacing`, firmware name
`bodaqs_a8_imu_adc_ack_pacing_r18`. The exact sealed r17 logger is the reference
under `artifacts/fixed-logger/`; do not substitute a rebuilt baseline. Keep the
existing master and all node images. No master/node upload is required initially.

The r17 baseline retained roughly 8.8-10.1% more raw sample payload than r16 in
equal logger windows, but still lost about 15% of node 1 samples. Other runs had
unknown source coverage. More packet requests are not necessarily more useful
delivery. Four-node and mixed-ADC tests remain on hold.

## Fixed conditions

Keep the latest two-IMU ADC-off configuration: nodes 0/1 active, 2/3 muted, ADCs
muted, primary heartbeat 500 Hz. The preparation directory contains the exact
private configuration and its SHA256. Preserve SD card contents and storage
settings. Mode 0, measurement v2, 256-byte slots, requested 16 MHz, 5 us CS setup,
RX depth 2, CAN acquisition profile 2, worker priorities, control/health/evidence
quotas, lease and cleanup rules, buffers, CRC and ACK/retirement validation remain
unchanged. No IRQ or physical change is included.

The recipe is a source/build identifier, not proof of installed peer firmware.
The master/node provenance and hashes remain those of the retained sealed images.

## First physical capture

1. Install the r18 candidate logger using the normal upload procedure and the
   candidate's matching boot/partition files if doing a full flash. Application
   `firmware.bin` goes at **0x10000**, never 0x0. Preserve config/NVS.
2. Restart master/nodes first, then logger, and leave the logger idle at least
   60 seconds. Resume any debugger-halted master. Time alone does not prove
   readiness: use configuration_reconciled for both active nodes if API works.
   Do not wait for acquisition_ready=true; that field is always false here.
3. Start logging. Require `[Storage] BDQ v2 begin streams=5`. If `streams=1`,
   STOP immediately; it is a primary-only failure, not throughput evidence.
   Save it in a separate attempt. The stream count is only a precheck; finalized
   metadata must still prove both source identities.
4. Acquire about **105 seconds** after the running/LED indication, so the first
   100-second primary window is available. Normal STOP; wait for file closure
   and the full FLOW finished trailer. Do not halt during acquisition/cleanup.
5. Save finalized BDQ, complete `serial.txt`, actual `loggercfg.txt` export and
   `ccs.txt` with both master snapshots into `Results/01-pace600/attempt1`.
   Export before a new recording changes the diagnostic scope. Preserve rounded
   exports as such; the existing exact-string helper is in the preparation handoff.

No firmware was flashed by the preparation tools. Do not format the card, change
SPI clock/mode, enlarge queues or change node profiles during this comparison.
Controlled storage-stall testing remains deferred.

## Assessment and next decision

The bundle's ASSESS.ps1 wrapper uses the source checkout and local Python analysis
environment to run `firmware/tools/assess_imu_optimization.py`. It performs no
device access. Select a fresh output directory outside the input attempt. It
requires exactly one BDQ plus serial/config/CCS, checks expected nodes 0/1, recipe,
byte-exact reference configuration, file closure and source companion identities.
Originals remain untouched; owned copies and SHA256SUMS bind the assessment.

`preflight <serial.txt>` is a quick saved-log check: exactly one streams=5 START.
It does not read a serial port, prove configuration readiness or trigger logging.
The wrapper is an offline assessor, not an autonomous hardware controller.

Compare each node and the first 100 seconds of primary logger time. The payload
metric counts raw six-axis readings at packet observation time, not source sample
time or a whole-source missing fraction. Keep source-bounded delivery separate;
missing terminal or ambiguous high sequence bits remain unknown. Never repair
bytes, weaken CRCs or invent source sequence IDs to produce a percentage.

Inspect first-loss timing, actual master ingress drops, sample fragment repeats,
queued request age, per-node RAM accepted versus persisted readings, source STOP
boundaries, primary continuity, SD write stalls and per-node queues. Frozen drop
fields are already interval deltas. nodes_seen=3 means nodes 0 and 1. Runtime
ingress counters reset on transfer context; do not subtract older recordings.

If useful delivery improves, or if lower queue/drop pressure offers an ambiguous
trade-off, capture the exact r17 reference under the same conditions, then return
to the 600 us candidate if justified. If pacing simply lowers useful delivery
without a compensating benefit, roll back and stop this lane. Do not automatically
run a grid of spacing values or a longer endurance test.

## Software lanes and promotion gates

These lanes run without changing the physical baseline:

- `screen_imu_batching.py`: actual master codec, retained batches and validated
  ACK_FETCH/retirement over synthetic two-node arrivals and a simple reader.
  Temporary deadline mutations (0/40 ms), delayed ACKs, and profiling on/off.
  The current 20 ms baseline is retained. No DMA, RTOS, SD, arbitration or actual
  logger scheduler is modeled; simulated throughput is not hardware capacity.
- `diagnose_imu_sequence_evidence.py`: replay existing recorded packets/evidence
  to locate unresolved identity. Do not synthesize a STOP or high sequence bits.
- Master cost: inspect optimized target code, existing phase boundaries and
  host profiling equivalence before selecting a distinct master candidate.
  CRC is already table-based; phase/queue clocks are gated after first-loss freeze.
  Host timings cannot establish the MCU diagnostic tax or a device speedup.
  Target cost/diagnostic-ablation measurement remains a later, separate test.

Software screen results and limitations are in the local preparation report. No
master processing, scheduler or batch change is silently combined into the pacing
image. A promising host candidate needs real-path invariants, a target build and
its own source-bound review before physical use. If a master candidate and pacing
both help, evaluate reference, master-only, pacing-only and combined before
attributing their interaction. Build that matrix only for actual winners.

Neither a host pass nor more stored payload qualifies production admission or
establishes four-IMU headroom. Retain strict source identity, control/evidence
service, CRCs and immutable retirement proofs throughout.
