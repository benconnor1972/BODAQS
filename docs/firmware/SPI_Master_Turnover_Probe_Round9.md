# Master receive backlog and reply turnover, round 9

Question: are recoverable requests lost mainly because the one-entry receive
queue cannot absorb service/publication bursts, and can a bounded backlog improve
useful throughput without changing wire, reply ownership or ADC freshness?

Round8 table-CRC256B cases805/806 ACKed167.7/183.1kB/s. Requested16MHz shortened
exchange303 to176us and raised cadence1042 to1318/s, but SPI receive drops rose
423 to1365. Retries/clock replays used17.3% of806 transactions. All5000 rows stayed
fresh per ADC and all frames decoded cleanly. These physical runs are the timing
feedback loop; host clocks cannot establish device capacity.

## Controlled experiment and predictions

1. If a one-entry backlog loses short bursts while a reply awaits publication,
   four entries should reduce drops and retries; high water/backlog pops and
   full-while-reply-ready counts will distinguish that pressure.
2. If variable processing costs dominate, full-while-no-prepared-reply drops and
   queue waits should persist or grow. Existing command/CRC/encode timings retain
   their software scope; this classification alone cannot prove CPU saturation.
3. If sustained service capacity is insufficient, a deeper queue may increase
   latency/full occupancy without improving ACKed throughput. It is bounded
   buffering, not explicit credit/readiness signalling and not a production fix.

Use one table-CRC logger and two otherwise identical table-CRC master builds:
`BODAQS_SPI_PROBE_RX_QUEUE_CAPACITY=1` control and4 candidate. Explicit acquisition
CAN profile, mode0,25us guard,500us spacing,800us row reserve,4 outstanding requests,
5000us retries/8-retry limit,1008-byte immutable objects, exact payload/frame/object
CRC and ACK rules remain. No new wire opcode or physical pin is required.

The old adapter explicitly admitted only when queue depth==0. Merely enlarging
the allocated array does not change that rule: a deterministic actual-adapter
four-frame burst failed its depth4/no-drop assertion before this change. The
probe now admits while depth<configured capacity. Each ring cell retains its
own length, observed retirement-entry tick and epoch beside its byte copy.
DMA buffer reuse cannot overwrite queued records; invalid lengths are retained
and rejected in main. FIFO is drop-newest, never overwrite-oldest. Main copies
metadata and bytes and advances the queue under the same IRQ fence. The exact
existing CS retirement/rearm and double-buffer reply publication order remains.

The normal production adapter retains one cell and its single-length field.
New adapter code and instrumentation are probe-guarded. No production capacity,
ISR authority, selected-object retention, ACK retirement or normal acquisition
behavior is changed. Queue depth is a build choice, never live switched. BEGIN/
STOP do not clear the hardware receive queue or boot counters. Ordered old-scope
requests are processed with the existing context guards; DMA retirement proof
is not inferred from enqueue/dequeue or receipt of a control reply.

## Additive STATS5/6 and logger schema v9

STATS5 is a coherent IRQ-fenced snapshot of:

|Index|Meaning|
|---|---|
|0|schema1|
|1|configured queue capacity1/4|
|2,3|current depth, boot high water|
|4,5|epoch, sticky timing invalid|
|6,7|enqueued, dequeued counters|
|8,9|full drops while prepared reply flag true, full drops otherwise|

For each page5 endpoint, uint32(enqueued-dequeued)==depth. Counter deltas wrap;
depth/capacity/high-water/epoch/invalid are endpoint states. Classification reads
the existing prepared-reply flag at software retirement before swapping it; it
is not a physical ready signal. Full-other can include processing/main scheduling
and does not identify an exclusive cause.

STATS6: schema1, dequeue wait calls, wait totalus, boot wait maxus, observed
reply-deferred episodes, deferred totalus, boot deferred maxus, pops with more than
one record queued, epoch, sticky invalid. Queue wait begins at the existing CS
retirement software-entry timestamp and ends after the fenced metadata/byte pop;
it includes retirement overhead. Main deferral episodes begin/end on observed
prepared-reply state transitions; no clock read or counter increment occurs on
repeated busy-loop observations. These are software observations, can overlap
other phase/publication intervals and include interrupts; never add them as CPU
cost or interpret them as physical-ready timing bounds.

All shared epoch/invalid updates and snapshots are IRQ-serialized. Epoch0 or a
changed epoch excludes invalid elapsed observations and leaves sticky invalid
until reboot. A uint32 tick wrap in a stable epoch is supported; multiple wraps
cannot be reconstructed. Boot counters persist through STOP/new BEGIN. Snapshot
processing closes observed deferral episodes before copying. Maxima never reset
per case. STATS5 and6, and old STATS1/2, have separate wider-than-timed-run scopes;
do not require drop/dequeue delta equality across different snapshot pages.

Engine pages5/6 hold adapter-owned copies; stateless host codec tests leave their
schema zero. Public result v9 adds master.receive_measured and four10-value pages
receive_before/after,turnover_before/after. Receipt means pages were received,
not validated. ADC-only pages/flag remain zero/false. Old masters promptly reject
unsupported pages; the reader marks observations unavailable.

Analyzer keeps v1..v8 reports unchanged. New master_receive_turnover is observed,
unknown, invalid or not_applicable. Unknown/unsupported metadata cannot establish
clean master evidence; invalid epoch/capacity/conservation/maxima/nested counts
fail candidate evidence. Only valid observations get derived means. All owner
modes remain diagnostic, all production/admission flags false. Native CAN drops
from the deliberately bypassed bench CAN consumer retain the analyzer's existing
failure status; do not suppress them to manufacture a clean admission result.

## Validation and manual work

Use actual extracted CS/DMA/main functions and the common codec for both queue
capacities and both CRC implementations. Exercise burst overflow/drop-newest,
mixed lengths/bytes/FIFO and DMA buffer reuse, delayed main, boundaries before/
after publication, wrong/repeated ACK, partial/oversize/FIFO-tail frames, tick and
counter wrap, nonzero epoch change, STOP/new BEGIN and new page snapshots.
Production adapter/lifecycle tests and normal logger/master builds must pass.
Clock/peripheral/IRQ boundaries are simulated; keep physical debt explicit.

Public logger runtime tests retain real acquisition/cache/shared-SPI logic but
their synthetic peer does not implement adapter pages, so these new measurements
are unknown there. Test recognized observations and malformed/missing/invalid/
wrapped pages independently through analyzer CLI. Obtain a fresh boundary review
and final archive/artifact audit before packaging.

Manual sequence: new logger and queue1 master first,900 ADC-only baseline,
901128B8MHz,902256B8MHz,903256B16MHz. After review, change only master to queue4
and Run/F8 in CCS;904128B8MHz,905256B8MHz,906256B16MHz. Every transport case uses
cached500,mask3/core1/cycle0,4 nodes,10s. Require recognized capacity and observed
timing,5000 fresh rows per ADC,zero misses/reuse/timeout/wire/accept errors and no
exhausted retries. Compare ACKed bytes/s, drops/retries/replays, queue occupancy,
waits and row lag. Failures remain visible. User performs all flashing manually.
Logger is an application image for0x10000; provide complete flash-offset table
and boot components for recovery. Old bundles remain sealed.

Actual SCK, native four-node CAN/IMU load, SD/BDQ, long-run reliability and full
production qualification remain outside this synthetic bounded-RAM experiment.
