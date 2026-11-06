# Logger CRC and request cadence, round 8

Bench question: after removing the remaining probe-specific bitwise logger CRC,
what determines useful request cadence and receive pressure? Round7 table-master
cases704/705 both ACKed1428 objects in10s (~143.9kB/s). Requested16MHz reduced
mean exchange301 to174us but not ~1000 requests/s. Both retained5000 fresh rows
on each ADC with no decode/accept errors. They still dropped893/895 master SPI
requests. These captures establish the repeatable physical feedback loop; host
clocks cannot reproduce or establish the device's scheduling costs.

## Controlled change

Use the exact sealed round7 table master, SHA256
`09bbf46ec2ab177045877576e946a9f87ad25aa89bd898a712c756de17a25326`.
Do not rebuild it or change node firmware. Prepare two logger images from one
clean commit with identical instrumentation: bitwise comparison and table
candidate. Default probe environment selects table; the `_bitwise` environment
selects0 through `custom_probe_crc_table`. The pre-build identity script supplies
the explicit compile definition and appends `-crc0`/`-crc1` to the source identity.
The actual codec wrapper maps that selection onto the existing common probe
option. The fast path reuses `bodaqs_measurement_crc_step`. The production
measurement codec already uses this table: this removes a synthetic-probe cost,
not a missing production optimization. The command's `cached` field still only
controls caching of the expected synthetic object's checksum.

Keep byte order, polynomial/XOR, wirev1, mode0,25us guard, frame/clock choices,
1008-byte immutable objects, exact payload and all CRC checks. Keep4 pending
requests,5000us retries/8-retry limit,500us comparison spacing,800us row reserve,
ADC acquisition/cache/500Hz bounded-RAM row logic. No settings dynamically change.
Do not change shared SPI, GPIO/ISR, DMA, CS retirement, ownership or production
acquisition. New results are schema `bodaqs.spi-probe.v8`; old schemas still parse.

## Targeted instrumentation and hypotheses

1. If logger CRC is limiting cadence, changing only its implementation should
   lower encode/decode/validation time and increase useful throughput or free
   acquisition time. An unchanged rate with lower CRC costs points elsewhere.
2. If pacing or the row reserve removes opportunities, gate decisions will show
   those deferrals and the achieved intervals/headroom. Neither a deferral count
   nor an outcome bucket is by itself time spent causally blocked by that rule.
3. If master turnaround remains limiting, drops/retries/replays and master
   software phase observations will persist after faster logger CRC. Faster
   request issue can make that pressure worse. This round measures that effect
   before changing reserve, cadence policy, flow control or hardware handling.

`logger_cost.crc_algorithm` identifies the compiled logger option. Its `cadence`
is active only for owner_adc/owner_rows/owner_pipe and resets per case:

- `cycle`: time from owner body entry after rail checks through its completed
  service/decision. Excludes serial parsing, outer-loop work and partial cycles
  ending in an early ADC failure/window end. Does not claim whole-window coverage.
- `adc_ready_service`, `row_service`, `adc_start_service`: disjoint chronological
  phases in every completed cycle. They include no-op checks when nothing is due.
- `transport_service`: one interval per actual call to transport tick, including
  deferred calls; excludes row-reserve decisions, which never call tick.
- `decisions`: six mutually exclusive buckets of the SAME completed cycles:
  adc_only, row_reserve, cs_guard, pacing, dispatch, other. Existing checks keep
  their order: reserve first, then transport CS guard, then configured spacing.
  A dispatch includes an uncertain transfer/lock failure. Other includes stalled
  transport or exhausted requests without an exchange.
- `dispatch_headroom`: next row deadline minus pre-tick decision time for each
  dispatch; always greater than800us. Includes possible clock/read overhead;
  this is not measured CS-to-deadline time or a guaranteed service bound.

Outcome buckets partition cycle counts/totals but INCLUDE ADC work. Do not add
them to cycle or phase totals, and do not interpret a row_reserve bucket's total
as idle blocked time. Disjoint service totals fit inside cycle total; residual
elapsed time includes outer-loop/instrumentation/serial/partial-cycle overhead.
Interrupts are included. Per-cycle counters have uint32 counts/summary extrema
and uint64 total microseconds, as existing TimingSummary. Existing case duration
cap remains. No allocation/serial output is added in timed service paths.

`diagnostics.timing.object_crc` measures assembled1008-byte checksum separately
from expected synthetic-data CRC. Both nest inside validation; neither is additive
to validation time. A failed object CRC is recorded but not accepted/ACKed. These
timings exclude control exchanges. Existing master pages and their wider endpoint
scope remain unchanged. Missing/invalid observations never establish capacity.

Analyzer checks phase/outcome accounting, active/inactive scope, dispatch count,
reserve/pacing counts, headroom and nested CRC counts/totals. All owner controls
remain diagnostic; no production/admission flag becomes true. V1..v7 reports
must remain byte-for-byte equivalent when decoded as JSON.

## Validation and manual sequence

Exercise the actual logger C++ codec wrapper in both modes against independent
zlib vectors and complete engine wire traces, including repeats/ACKs. Run public
logger/ADC/cache/shared-SPI/engine tests for both compile options, including
malformed-frame provenance, corrupt object/payload rejection, loss/retry/ACK,
STOP/restart, partial cases, rail faults and slow ADC reuse. Validate emitted v8
cases through analyzer CLI and reject mutated accounting. Clock/peripheral and
reply-FIFO boundaries remain simulated. Compile normal A8 plus both probe images;
verify variant identities, instructions, immutable master hash and exact source
archive/checksums. Obtain the repository boundary review before sealing.

User flashes manually. Use the bitwise image for800 ADC baseline and801 pipeline
128B/8MHz,802 pipeline256B/8MHz. Then change only the logger to table for803 ADC
baseline,804 pipeline128B/8MHz,805 pipeline256B/8MHz and806 pipeline256B/16MHz.
All pipeline commands use cached500, mask3/core1/cycle0,4 nodes,10s. Baselines
are matched by artifact identity, so both images need their own baseline.
Review each capture before advancing. Preserve raw JSON, artifact hashes and
manual master identity. Require5000 fresh rows on each ADC, no misses/reuse,
acquisition failures/timeouts, wire/transfer/accept errors or retry exhaustion.
Compare accepted and ACK-confirmed bytes/s, request intervals, phase costs,
deferrals, master drops, retries/replays and lag. Deferrals alone are not failure.
Unconfirmed STOP requires reset. SD/BDQ, native CAN/IMU load, actual SCK, long-run
reliability and full four-node production admission remain unqualified.
