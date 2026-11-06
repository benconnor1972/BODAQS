# SPI request window, round 6

Bench-only question: can distinct requests retrieve delayed replies with less
repeated work than the existing stop-and-wait client, while retaining fresh
500 Hz ADC rows? This is not production admission or a physical capacity result.

Round5 physical cases500..503 produced fresh rows throughout. Cases501..503
decoded30595 frames without error, but useful rates fell36.9 ->29.6 ->23.3 kB/s
as requested minimum spacing rose500 ->750 ->1000 us. Master receive drops
fell734 ->295 ->154. In503,4620/6930 prepared fragments were repeats and462 ACKs
were duplicates for231 retired objects. These are processing counters, not proof
of physical delivery. Raw captures and paired reports remain outside source in
`../drain-capacity-evidence/spi-prototype/round5/runs/first-physical`.

## Scope and comparison

Keep the round2 master binary, wire protocol1, pins, mode0,25 us guard, frame
CRC, exact payload check, whole-object CRC before ACK, and one immutable selected
object per node. No ready GPIO, new opcode, master DMA/publication change or
adaptive backpressure is introduced. Node and production firmware behavior stay
unchanged. The cached option still caches only the expected synthetic CRC.

New mode `owner_pipe` uses the identical ADC acquisition/cache/row scheduler and
800 us deadline reserve from [round5](SPI_Owner_Rows_Probe_Round5.md). It requires
mask3, owner core1, cycle0. `owner_rows` remains the stop-and-wait control, and
`owner_adc` remains the required matching freshness baseline.

## Request ownership

The logger retains at most4 distinct requests in fixed RAM. Each entry identifies
POLL/ACK, node, object and fragment, with first-dispatch and retry timestamps.
There is still only one current1008-byte object per node. No allocation occurs
in the active path. A request clocks an older response, not its own response.

For available capacity, choose nodes fairly, issuing the lowest fragment neither
received nor outstanding. After full exact acceptance, issue one ACK for that
node. Other nodes can make progress while its reply is pending. Object identity
advances only after a valid matching ACK response. Late responses for an earlier
object are stale, not permission to advance or release another object.

At5000 us without completion, retransmit the oldest retry-due entry. Allow8 such
retries; fail closed on its next deadline even if other nodes progress. Each
entry therefore has an independent finite retry budget. A failed transfer has
uncertain delivery and remains pending. Corrupt replies do not complete entries.
Payload/context validation and object CRC retain their existing failure rules.

Wire v1 has no harmless fetch/NOP. When capacity is full or all useful requests
are pending, repeat the oldest pending request to clock a reply. Count this as a
clock request, not a distinct request or timeout retry. It does not extend the
retry deadline. Such duplicate requests can remain necessary; the prototype
measures rather than claims to eliminate them. Physical loss and master queue
pressure may still limit useful throughput.

Entry completion occurs only after full reply validation. Window state resets
on a new successful begin attempt, not during control STATS/STOP. The final
snapshot retains outstanding entries at the end of the timed window; they need
not be drained. Confirmed STOP and monotonically increasing case IDs preserve
the existing restart scope. Unconfirmed STOP blocks new cases and requires reset.

## Evidence and interface

Result schema becomes `bodaqs.spi-probe.v6`; existing commands retain behavior.
The analyzer continues accepting v1..v5. Every v6 result adds `request_window`:

- active, limit4, retry_us5000, retry_limit8 (inactive policy fields are0).
- new_requests, retry_requests, clock_requests: timed dispatch attempts, including
  failed transfers. Their sum equals slots. Control exchanges are excluded.
- pending, high_water: bounded distinct entries, maximum4.
- retry_exhausted:0 or1, independent of transfer/wire/accept counters.
- reply_age: first software dispatch to fully validated completion, including
  encoding, pacing, transfers and retries; not a physical wire turnaround bound.

new_requests = reply_age.count + pending. `reply_age` excludes unmatched duplicate
and stale responses. Inactive window counters are0. Stop/failure results remain
incomplete/failed, even if their prefix has fresh rows. A matching failed ADC
baseline prevents combined evidence from passing. No admission flags become true.

Compare owner_rows and owner_pipe at the same frame/clock/pacing, inspecting
useful accepted and retired bytes, master receive drops, prepared/repeat fragments,
duplicate ACKs, pending/clock/retry counts, row lag and freshness. Reduced request
counts in host tests are algorithmic evidence only. The host client/engine seam
models a two-exchange reply delay, not MSPM0 DMA/CS timing or CPU cost.

Validation includes lost POLL requests, applied ACK with lost response, corrupted
frame and valid-frame bad payload, per-node exhaustion while peers progress,
all frame/clock profiles with1/4 nodes, STOP, rail fault, ADC reuse and restart.
Target builds and a fresh boundary review precede sealed packaging. Physical
master timing, SCK, SD/BDQ, native IMUs, CAN drain and production admission remain
unqualified. User performs flashing manually.
