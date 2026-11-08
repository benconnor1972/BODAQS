# SPI reply wait trace, round13

## Question and fixed conditions

Round12 found 500 us pacing best on both passes, with the repeated control near
192 kB/s ACK-confirmed, rather than a dependable 200 kB/s margin. Locate waits
within a reply's journey before changing circulation policy. This is a bench
measurement, not a throughput fix or production admission.

Use the owner, CLOCK, queue4, table-CRC profile:256-byte exchanges, requested16 MHz,
four synthetic nodes, four outstanding requests,10 ms retry deadline/eight retries,
25 us guard,800 us row reserve. Keep wiring and node firmware unchanged. Two
sensors are modeled:AIN0 (ADC0 channel0) and AIN4 (ADC1 channel0), each requiring
500 fresh rows/s; the other six channels are unused. Actual SCK remains unmeasured.

One new logger emits schema `bodaqs.spi-probe.v13` (wire protocol1 unchanged).
Two newly built master images differ only in `BODAQS_SPI_PROBE_TRACE=0/1`.
Neither is the previous round10 master. Run tracing enabled, disabled, enabled,
with two transport repeats per block, to expose overhead and order variation.

## Observation contract

Tracing captures the first8 successful POLL/ACK reply preparations after skipping
256 preparations in each newly admitted case. This is an early bounded sample,
not a distribution of the whole10 s run, and retries can repeat identities.
Ordinal counts preparations, not logger requests, objects or accepted readings.
Successful engine responses supply normalized identity; malformed or rejected
requests and controls never create records. The trace does not change dispatch,
retry, ACK, DMA, selected-object or retirement authority.

The master records these stages in its own1 MHz clock:

1. Software entry to CS retirement for the received request, after establishing
   CS high and DMA progress. This is not a pad-edge timestamp.
2. Start/end of the existing main-owner process observation (includes coherent
   status snapshots, decode/command/encode and IRQ time).
3. Fully prepared reply publication tuple, after observer bookkeeping.
4. Later boundary selecting that inactive reply as the active TX buffer.
5. First subsequent exact-length exchange observed while that buffer is active.

Stage5 establishes a full exchange observation only. RX physical length includes
FIFO tail/excess checking. It does not prove correct TX bytes, electrical timing,
logger decoding or acceptance. The logger's existing reply-age measurement remains
the independent end-to-end observation. Never subtract master timestamps from
logger timestamps or treat an unobserved stage as zero latency.

The IRQ updates only fixed indices published with `gSpiTransmitReady`; it never
parses identity, computes a CRC or retains a DMA pointer. Observation of the old
active buffer occurs before publication swaps indices. Main fills records and
publishes index/timestamp/ready together under PRIMASK. Every prepared control or
uncaptured reply clears its inactive buffer's trace index. Accepted new BEGIN
clears the arena, both indices and counters together; repeated BEGIN and STOP
retain it. No index can outlive that arena reset. Trace fields never feed actual
retirement proof.8 records consume640 bytes; queue metadata grows12 to16 bytes
per cell in both bench variants. The original32-record arena failed BANK0 placement with the unchanged2 KiB stack; eight records retain that stack and buffer budget. Normal firmware is excluded by probe guards.

Counter/tick subtraction is modulo uint32, only within one nonzero clock epoch
and spans below2^31 us/boundaries. Changed or zero epochs mark observations invalid.
The logger reads trace pages only after stopping the timed window/ADC workers.
Normal10 s captures saturate early and mature before readout; short/failed runs
can contain missing stages or incomplete retrieval. Split-page inconsistencies
must be rejected, never silently repaired or interpreted as delivered replies.

## Additive STATS pages

Original pages0..7 and all identity checks retain their semantics. STATS8..24 are
optional observer pages, each ten little-endian uint32 words. Uninstrumented
generic engines return zeros (unknown); the trace-off adapter advertises disabled.
Pages above24 remain argument errors. Snapshot selection before decode reads only
a bounded page selector; malformed input still cannot obtain a valid response.

Page8: schema1, enabled0/1, capacity8, skip256, captured count, preparation count,
case ID, capture epoch, invalid flag, reserved0. Pages9+2*i and10+2*i expose the
twenty words for record i (0..7); unused entries read zero.

|Word|Meaning|
|---|---|
|0|Successful POLL/ACK preparation ordinal,257..264|
|1|Object ID|
|2|Packed request opcode,node,fragment,frame-size code (one byte each)|
|3|Master clock epoch|
|4|Flags:1 prepared,2 published,4 full exchange observed,8 invalid timing|
|5,6,7,8|Request retirement entry,process start,process end,ready ticks|
|9,10|Publication,first full exchange retirement-entry ticks|
|11,12,13|Receive,publication,full-exchange boundary ordinals|
|14|Queue depth before main popped the request|
|15|Case ID|
|16..19|Reserved0|

After8 records, allocation stops; the at-most-two active/prepared indices may
finish their observations. No wrapping arena or identifier reuse occurs. The
analyzer exposes raw records and per-stage count/min/mean/max, labels unknown,
disabled, empty, incomplete and invalid, and preserves historical report output.
Missing/invalid trace data cannot establish a wait-stage conclusion. An incomplete
record may still establish its earlier stages; no later-stage duration is inferred.

## Validation and acceptance

Exercise real adapter bodies with fake DMA/FIFO/CS and PRIMASK delivery: queue1/4,
CRC bitwise/table, trace off/on; skip/capacity, both publication interleavings,
short/excess/full bursts, FIFO tails, split-page export, STOP/new-BEGIN reset,
epoch invalidation and tick/boundary wrap. Retain all existing engine, adapter,
logger public runtime and analyzer cases. Negative mutations must detect marking
the publication boundary as collection and bypassing physical length checks.
Compile probe/normal A8 and trace off/on/normal master. Independent boundary review
is required before packaging; record revision and source fingerprints.

On hardware require5000 fresh rows per ADC per case, clean wire/transfer/accept/
command results, valid trace metadata and8 coherent records in trace-on transport
runs, disabled/empty capture in trace-off runs, no timing invalidity or exhausted
retries. Preserve all receive losses, retries, repeated work and background CAN
drops. Compare ACK-confirmed throughput, CLOCKs, reply age and ADC read cadence
across all three blocks. If enabling the small trace materially changes behavior,
treat the stage observations as intrusive and revise measurement before optimizing.

Native CAN IMU traffic, SD/BDQ, sustained operation, all-channel ADC load, physical
SCK/electrical margins and production capacity remain outside this qualification.
Do not claim a hardware ceiling or200 kB/s capacity from this trace.
