# r17: ACK-fetch fragment sweep optimization

This is a logger-only, opt-in experiment against the exact r16 polling baseline.
It tests whether avoiding repeated requests for a data fragment still in flight
improves useful two-node delivery. It does not qualify production admission.

## Why this change

Case B lost 25.77% of node 1's source-bounded samples. Its first-loss master
snapshot froze after 0.681533 seconds: retention depths 102/128 and 128/128,
zero CAN software/hardware loss, 44.77% empty prepared replies, and 33.43%
repeated sample fragments. The later 3.6816-second SD write stall is additional
pressure; it prevents treating that capture as a storage-independent ceiling.

Earlier synthetic round 17 found an 11.22% useful-throughput gain from combining
ACK and fetch, without increasing exchanges/s. Real acquisition already uses
ACK_FETCH. Earlier real-path work also established that requesting another missing
fragment while a reply is in flight improves the ordinary-poll path. The combined
request did not use that same scheduling hint: it always selected the first
missing fragment. This experiment closes that specific inconsistency.

Ranked alternatives remain hypotheses, not extra changes in this round:

1. **Missing-fragment request scheduling:** the production host regression
   reproduces `1,1,1,1,1` for delayed ACK_FETCH replies. Candidate requests
   `1,2,3,4,1`, sharing the existing ordinary-poll sweep. A lost fragment remains
   missing and is retried. Neither pattern marks receipt or authorizes retirement.
2. **Broader polling/ACK target allocation:** empty/repeated traffic and full
   master retention make this worth examining if the focused change is insufficient.
   Earlier naive removal of idle/control polls worsened backlog. Do not remove
   renewal, protected-control, evidence or health service to make a benchmark pass.
3. **Master per-request cost:** decode/proof validation, dispatch and encoding
   averaged about 122.54/120.05/106.84 microseconds in B's short snapshot. These
   wall measurements include interrupts. No CRC weakening, wire-format change,
   cached-proof shortcut, MCU clock change or master rewrite is included here.

No numerical speedup is promised from the request-pattern regression. Some
empty/repeated exchanges are required; physical timing, DMA, RTOS and SD are
simulated in host tests. The actual throughput question requires this capture.

## Images and configuration

Require `BUILD_MANIFEST.json` status `passed`. Select:

- Candidate: `variants.ack_sweep.logger`, firmware name
  `bodaqs_a8_imu_adc_ack_sweep_r17`, environment
  `bodaqs_s3_mini_n4r2_imu_adc_ack_sweep` (A8 ESP32-S3 N4R2).
- Reference/rollback: the **exact** r16 image under `artifacts/fixed-logger/`,
  SHA256 `72e3e9f05a58b351c2425ad5b4972d87892e1332684720c422c98adea42fc770`.
- Keep the included unchanged r10 master and acquisition node images installed.
  Do not rebuild peers or change their debugger symbols during the comparison.

`BODAQS_ACK_FETCH_FRAGMENT_SWEEP=1` is the sole functional experiment flag. It
defaults to zero in ordinary builds and requires measurement v2. Ordinary polling
uses the same missing-fragment scheduling helper. The new hint is per inbox,
cleared by the existing new-object/recovery/reset rules, and never changes receipt
masks, data acceptance, immutable ACK identity or retirement proof.

Keep the existing r16 `B_2imu_adc_off.txt` byte-for-byte: nodes 0 and 1 active,
other IMUs and all analog sensors muted, 500 Hz primary heartbeat. Keep the same
SD card and files; do not format it or change storage settings between comparisons.
Private configuration copies and exact hashes are in the local preparation handoff.

Fixed: SPI mode 0, 256-byte measurement v2 at requested 16 MHz, 500 microsecond
CAN exchange-start spacing, 5 microsecond CS setup, master RX depth 2, CAN profile
2 at 1M/4M, ADC priority 3, storage priority 2, worker cadence, class/node quotas,
health observations, bridge observations, acquisition leases and cleanup deadlines.
No IRQ, ADC, buffer-capacity, physical-retirement or protocol changes are made.

## Capture sequence

Only change the logger image. Use the existing manual flashing procedure; these
preparation tools do not access or flash devices. Fresh restart all participating
boards before each acquisition, then verify both desired profiles reconcile.

| Step | Logger | Configuration | Duration | Purpose |
| --- | --- | --- | --- | --- |
| 1 | r17 candidate | B: two IMUs, ADCs off | 30 seconds | First optimization result |
| 2 | exact r16 reference | same B | 30 seconds | Matched-duration reference |
| 3 | r17 candidate | same B | 30 seconds | Return candidate; check repeatability |

The existing 83-second B capture remains the initial failure baseline. Step 1
first gives the quickest signal. If the candidate causes new decode, identity,
cleanup or ordinary/protected control failures, preserve it and stop this round
before extra flashing. If the result merely remains overloaded, assess it before
spending time on later steps. Do not advance to four-node C or mixed ADC loads yet.

When the short comparison supports an improvement, one 60-second candidate run
is the next check. A single lucky card write is not an optimization result.
Controlled storage-stall tests remain deferred. Record actual write stall
durations/queues so card variation remains visible rather than silently excluded.

Use fresh `Results/<step>-<image>/<attempt>/` directories. Save finalized BDQ,
complete serial through `Log file closed.`, actual config export and both CCS
snapshots. Keep unsuccessful captures. Export CCS before a new run resets the
snapshot. If necessary keep debugger TCLK at the working 100 kHz; that does not
change the acquisition SPI clock. Do not halt a recording or its cleanup.

The local preparation handoff provides `export-master-snapshot.js`, generated
by the existing read-only exact-string exporter. Invoke it in an operator-selected halted CCS session with the exact
master boot string from the BDQ acquisition descriptor. It never connects,
halts, resets, resumes or programs a target itself. The r10 master layout is
version 5 with phase/queue timing; preserve that declaration in the output.

## Assessment and comparison

Use the matching source checkout/archive and the existing multi-node assessor:

```powershell
python firmware/tools/assess_multi_imu_recording.py <finalized.bdq> --expected-nodes 0,1 --output <fresh-assessment.json>
```

The copied entry point imports the repository analysis package; it is not a
standalone script. Exit 1 preserves an incomplete evidence verdict, including
terminal gaps. No repair, interpolation or waiver is introduced.

Compare in this order:

1. Same logger identity/recipe, config hash, two distinct source UIDs and both
   streams. No new conflicting data, CRC bypass, invented sequence IDs or cleanup
   regression. A missing source terminal makes its whole-run percentage unknown.
2. Each node's source-bounded missing fraction and internal gaps. A small final
   STOP-tail gap stays separate from sustained loss. Both nodes must improve;
   aggregate counts must not hide starvation. If one denominator is unknown,
   do not claim a whole-run percentage or a comparable aggregate speedup.
3. Master time to first ingress drop, retention drops/queues and CAN losses.
   A no-loss run freezes at STOP, so it has a different interval. `nodes_seen`
   is a bitmask: 3 means nodes 0 and 1. Drop fields in the frozen drain are
   already interval deltas; do not subtract their saved baselines again.
4. Fresh/repeated sample fragments and ACK_FETCH targets alongside exchanges.
   Lower duplicates or higher exchanges alone do not prove better useful delivery.
   Do not compare count ratios from different freeze windows as identical workloads.
5. Logger per-node RAM-accepted versus persisted records, sample consumer waits,
   sampled queues, primary continuity and physical SD write stalls. RAM acceptance
   is not unique source delivery. Card stalls can cause real loss even when the
   request-selection change is correct.

Retain the candidate only when repeated, comparable captures show a useful gain
without sacrificing either participant or validation/control behavior. A 10% or
greater relative gain is worthwhile, but only calculate it when the source
coverage/window supports that comparison. Losslessness is a separate verdict.
If gain is small or the two-node failure remains substantial, the next experiment
is broader scheduling/publication efficiency, not an assumption that four IMUs fit.
