# SPI measurement probe: manual capture and offline comparison

This bench-only procedure implements the evidence collection in the
[confirmed SPI revision](CAN-FD_SPI_Transaction_Revision.md) and
[ADR 0004](../adr/0004-reopen-spi-transaction-envelope.md). It does not qualify
production, authorize workload admission, or change the historical
[T01 no-go](drain-capacity/REPORT.md). Keep the original T01 files untouched.

The user flashes the reviewed probe artifacts manually. This procedure does
not authorize an agent to flash, probe devices, push changes, or update issues.
Use the packaged source/artifact manifest to select the logger A8
ESP32-S3MiniN4R2 probe image and the corresponding MSPM0 master acquisition-CAN
probe image. Both must be built with `BODAQS_SPI_PROBE=1`; production images do
not provide these commands. Preserve board revisions, wiring and supply details
in the external run manifest. The payload is deterministic synthetic data for
up to four simulated nodes, with one immutable 1008-byte selected object per
node. This does not exercise physical four-node CAN or native IMU acquisition.

## Prepare and capture

1. Preserve the artifact manifest and exact logger/master source revisions,
   binary SHA256 hashes, build identifiers, board variants/revisions and wiring.
   Select an external evidence directory, for example
   `C:/Users/benco/dev/BODAQS-worktrees/drain-capacity-evidence/spi-prototype/runs/run01/`.
   Store the raw serial capture and run manifest together there, outside the repo.
2. After manual flashing, open the logger serial terminal at **115200 baud**,
   newline terminated ASCII. Enable raw file capture before resetting the logger.
   Keep boot text and every JSON result. Do not use a terminal mode that prefixes
   JSON lines with timestamps or echoed commands. Ensure the master is running
   the matching probe image. Wait for `type:"ready",ready:true`.
3. Send `status` only while idle. Require `ready:true,blocked:false` before each
   new case. The first fixed profile is 64 bytes at a **requested** 8 MHz,
   four simulated nodes, 25 us inter-CS guard. No statement about actual SCK is
   implied. ADC-only uses one channel per ADC, AIN0 and AIN4, 500 logged rows/s;
   each worker is configured for 1000 conversions/s.

## Fixed cases

Predeclare **10 seconds per case** for this comparison. That is a comparison
window, not sustained-service qualification. Longer, repeated and instrumented
observations require their own declared durations and acceptance limits.
Use these unique IDs once; subsequent runs must use new IDs, including after a
stopped/failed case. Do not paste the block as a batch. Send one line, wait for
its result, verify idle, then send the next line.

```text
case 100 adc 64 8000000 4 10000
case 101 bulk 64 8000000 4 10000
case 102 mixed 64 8000000 4 10000
case 103 bulk 128 8000000 4 10000
case 104 mixed 128 8000000 4 10000
case 105 bulk 256 8000000 4 10000
case 106 mixed 256 8000000 4 10000
case 107 bulk 64 16000000 4 10000
case 108 mixed 64 16000000 4 10000
case 109 bulk 128 16000000 4 10000
case 110 mixed 128 16000000 4 10000
case 111 bulk 256 16000000 4 10000
case 112 mixed 256 16000000 4 10000
```

Each duration completion stops the workers and confirms the master's STOP
before reporting completion for bulk/mixed. Require the matching case ID,
`outcome:"complete"` and `workers_stopped:true`, then send `status` and require
idle readiness before changing the profile. Do not send `status` during a case:
commands during acquisition are counted as errors and produce no immediate output.
The profile cannot change while active. A completed case is already stopped;
an additional `stop` while idle emits an `idle` error.

To abort early, send **`stop`** and wait for the stopped/failed result before any
new command. A stopped case remains incomplete evidence. If a master STOP or
worker shutdown is unconfirmed, preserve the capture, stop the sequence and
reset/reboot manually before trying a new case ID. Do not switch clocks to hide
errors. Preserve failed cases, diagnose them, and record any intentional retry
as another unique ID. If the ADC-only baseline is unhealthy, retain its failure
separately; do not attribute it to mixed SPI traffic or weaken freshness limits.

## Pair the external manifest

Stop file capture after the final result. Keep the capture bytes unchanged.
Use PowerShell `Get-FileHash -Algorithm SHA256 -LiteralPath <capture>` to obtain
the exact digest. Create an external JSON manifest in this form, replacing every
placeholder with the packaged identity or actual run observation:

```json
{
  "schema": "bodaqs.spi-probe-manifest.v1",
  "protocol": 1,
  "capture_path": "C:/external/run01/serial.txt",
  "capture_sha256": "<64 lowercase hex characters>",
  "logger": {
    "board": "A8 ESP32-S3MiniN4R2; exact revision and serial",
    "source_revision": "<40 lowercase hex characters>",
    "artifact_sha256": "<64 lowercase hex characters>",
    "build": "<exact artifacts.logger_build in capture>"
  },
  "master": {
    "board": "MSPM0G3518; exact board revision and serial",
    "source_revision": "<40 lowercase hex characters>",
    "artifact_sha256": "<64 lowercase hex characters>"
  },
  "wiring": "<shared SPI wiring, supplies, load and any changes>",
  "instrumentation": "<instruments/settings and files, or SCK/duty/endpoint timing unmeasured>"
}
```

Retain the packaged artifact/source manifest alongside this run manifest. The
analyzer checks the capture digest and logger build pairing; it cannot attest
which firmware was physically flashed. The master reports `external-manifest`
for its build, so its exact identity must come from that manual pairing. Use one
manifest per unchanged logger/master artifact pair; do not combine captures from
different builds or resets with reused IDs. Add instrument files and measured
SCK/duty/timing evidence to the external manifest when available. Schema v1's
`actual_sck_hz:null` remains unmeasured; requested 16 MHz is never an actual-clock
measurement. The analyzer does not qualify external instrumentation evidence.

## Analyze offline

From the repo root, using any Python 3.9+ interpreter (stdlib only):

```powershell
python firmware/tools/analyze_spi_probe.py C:/external/run01/serial.txt --manifest C:/external/run01/manifest.json --output C:/external/run01/report.json
python -m unittest discover -s firmware/tools -p test_spi_probe_analysis.py
```

Omit `--manifest` for preliminary analysis; the capture is retained and
provenance/candidate eligibility remains unknown. Exit **0** means the capture
was parsed consistently, including valid failed cases; it is not a pass. Exit
**2** rejects malformed JSON, schema/profile mismatch, negative/noninteger counts,
duplicate IDs, invalid timing summaries, manifest mismatches or inconsistent
ADC/object accounting. Ordinary boot text is ignored. Keep one JSON object per
line without terminal prefixes. Reports have no generation timestamp and are
deterministic for the same capture and manifest.

## Interpret the evidence

- Useful accepted bytes are exactly `unique_objects * 1008`; useful retired bytes
  count confirmed retirements. Pending ACK objects are shown separately. Frame
  bytes, polling, retries and prepared responses are not useful drain. Both
  accepted and retired rates remain visible for failed candidates.
- The comparison lists bulk and mixed IDs for each 64/128/256-byte, 8/16 MHz
  requested profile, grouped by node count, duration and logger build. Missing
  combinations stay missing. It shows mixed/bulk useful-rate ratios without
  choosing a production winner. Artifact provenance is the paired manifest.
- ADC modes require `fresh + reused + no_sample = uses = rows` per channel.
  Scheduled `rows + missed_rows` is checked against the nominal duration,
  capped by actual elapsed time for early stops, within one row. Late completion
  does not extend the scheduled window; rates still use actual elapsed time.
  Healthy evidence requires 500 fresh logged rows/s/channel, zero missed rows,
  reused readings, no-sample rows, acquisition failures and wait timeouts; only
  one row of duration quantization is tolerated. A 10 s run targets 5000 rows
  per channel. Freshness comes from conversion identity, not changing values.
  Baseline failures and missing baselines are reported separately.
- `elapsed_us`, rows and transport cover the timed window. Acquisition counters
  include warm-up/startup/shutdown; dividing `acquire_ok` by `elapsed_us` would
  invent an acquisition rate. The configured 1000 sps is not an achieved rate.
- Timing summaries are software observations, with observed maxima rather than
  certified bounds. Cache age starts after RDATA publication. DRDY timestamps
  record ISR observation, not the physical edge. DRDY-to-read-attempt precedes
  the RDATA mutex; read-end includes the mutex wait and read. Preserve raw timing
  scope labels. Ownership ends immediately before mutex give and excludes
  give/instrumentation publication overhead. `drdy_pre_start` observations cannot
  become paired conversion observations and do not claim physical pad-edge timing.
  Master processing/rearm timing remains unmeasured.
- Transfer, wire-integrity and object-acceptance errors fail a clean candidate.
  Stale/duplicate pipeline replies remain diagnostics and do not automatically
  imply a CRC failure. Master engine/adapter pages are boot-cumulative and their
  modulo-uint32 deltas cover a wider window than useful drain. Missing/unsupported
  pages are unknown, even when their arrays contain zeros. Queue drops/recovery
  and CAN losses fail a clean candidate but are distinct from electrical errors;
  RX queue drops alone do not prove 16 MHz electrically unreliable.
- `clean_measurement_candidate` means only this capture's declared measurement
  checks are clean and paired. `unknown` retains missing evidence; `failed`
  retains observed failures. No value authorizes production, complete T01 go,
  four-node physical CAN, native IMU timing, persistence, workload admission,
  sustained electrical reliability, bounded service tails or burst/retry proofs.
  Those remain separate gates under the confirmed revision.
