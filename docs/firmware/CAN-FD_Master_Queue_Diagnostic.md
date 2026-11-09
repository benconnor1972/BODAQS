# Master SPI request queue diagnostic

This opt-in diagnostic measures whether request queue delay is already present
when the master first loses retained source data. It does not coalesce requests,
change readiness, or alter the [v2 wire contract](CAN-FD_Measurement_v2.md).
Keep the existing logger500us pacing, flow diagnostics and acquisition node.

Build the acquisition/first-recording master with `SPI_PHASE_TIMING=1` and
`SPI_QUEUE_TIMING=1`. Both default to0; queue timing requires the phase/v2 build.
The global `gMasterDrainInfo` becomes version4, appending queue fields after the
existing version3 phase arrays. Existing field offsets remain unchanged.

Each RX cell stores the native clock tick/epoch observed immediately before the
boundary adapter enqueues it. This is a software observation after CS detection,
DMA disable and FIFO drain, not an electrical CS-edge timestamp. Main copies
timestamp metadata with that cell's payload/length under the pop IRQ fence.
No ISR reads or writes the main-owned drain snapshot. Full-queue drops do not
overwrite the waiting cells' timestamps. No diagnostic field grants authority.

`spi_queue_wait_count`, `spi_queue_wait_total_us`, `spi_queue_wait_max_us` and
`spi_queue_wait_hist[6]` describe queue residence until the main pop, before
validation/dispatch. They are added only after successful physical/protocol
processing of a full current-context measurement slot. Explicit error replies
can count; malformed/short/excess input does not. Cells from before START and
stale contexts increment `spi_queue_wait_excluded` rather than entering the mean.
`spi_queue_time_invalid` counts clock-invalid observations for this cohort and
also sets the existing `timing_invalid` flag.

The six waiting-time buckets are <=250, <=500, <=1000, <=2000, <=4000 and >4000us.
`spi_queue_depth_hist[5]` counts the depth before those valid timed pops; index0
is unused, indices1..4 are the queue depth including the popped request.
Neither histogram includes the request already being processed outside the queue.

`spi_queue_depth`, `spi_queue_head_age_us` and `spi_queue_head_valid` are sampled
at each existing drain check, including the first-loss freeze. Head validity
means its timestamp/clock/START scope is usable. The raw queued head has not yet
been decoded: this flag does not establish its CRC, context or semantic validity.
Zero age can be valid; use the flag. An empty queue has flag0 and age0.
`spi_queue_peak` is the largest depth observed by the sampler or a valid timed
pop, not an exact ISR high-water mark. The existing all-boot RX high-water field
has a different scope and must not substitute for it.

The existing snapshot rules remain: START admission begins the scope; first
ingress loss freezes with finish_reason1, STOP admission with2, or identity
change with3. The SPI drop field is already a delta from its baseline. Snapshot
duration can be much shorter than the recorded session.

Use a bounded approximately40second run. Unsigned tick subtraction supports a
low32 wrap within the run, but does not distinguish intervals >=one full native
clock period (about71.6minutes). Zero/mismatched clock epochs invalidate timing.
Do not pause CCS during recording. Copy numeric array values after file closure
and before another run resets the snapshot.

Mean queue wait is total/count. Interpret it with the histogram and frozen
depth/head age, alongside the existing processing costs and first-loss time.
Persistent millisecond waits would support investigating stale request backlog;
small waits at first loss would weaken that explanation. A zero final depth does
not disprove earlier queue delay. Neither result alone establishes causality or
predicts the benefit of request coalescing.

Host adapter tests import actual production queue storage/functions. They cover
cell lengths/timestamps, overflow/ring wrap, stale/pre-START requests, clock
fault/wrap, freeze/reset, and real modeled SPI boundary arrival immediately before
the pop/sample mask. Target builds and stack reports are retained in the master
candidate manifest. These are software checks: added ISR/masked-section work,
runtime stack headroom and physical timing remain on-device qualification debt.
There is no acquisition-path serial output or extra wire validation pass.
