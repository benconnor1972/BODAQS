# SPI CS-high reply publication experiment - round14

This bench prototype follows round13 source
`6fbbe1b818e6a4503809d9de3efdc6c15390a822`. Round13's recovered cases1310..1315
averaged about192 decimal kB/s with healthy two-sensor rows. Its32 bounded trace
records showed about255us ready-to-publication waiting and another678us to an
observed full exchange. This experiment tests the handoff, not a promised speedup.

## Controlled comparison

Build two acquisition-profile MSPM0 masters from the same revision, queue4,
table CRC and trace enabled. `BODAQS_SPI_PROBE_EARLY_PUBLISH=0` keeps the boundary
handoff; `=1` additionally attempts publication in the CS-high gap. Both observe
both GPIO CS edges. Run late/early/late blocks, two10s runs per block, with the
same new v14 logger. Keep requested16MHz,256-byte frames, four synthetic nodes,
four pending requests,500us minimum start interval,10ms/eight retries,25us guard
and800us row reserve fixed. Actual SCK is unmeasured.

ADC load remains one sensor on AIN0/ADC0 channel0 and one on AIN4/ADC1 channel0,
each500 fresh rows/s, configured1000SPS. Other six channels are unused. Synthetic
objects replace native CAN acquisition; CAN drops remain visible. Production
firmware does not compile the new handoff or change its CS polarity/retirement.

## Ownership and collision contract

Early publication requires a fully prepared inactive reply, no retirement or
quarantine in progress, and an active reply already observed in an exact full
physical exchange. This active-observed state is independent of optional trace.
Every swap clears it and records the prepared reply's physical size. Short and
excess transactions, including FIFO tails, cannot establish it. In early mode,
boundary publication also preserves an unobserved active reply and its queued
successor. A newly admitted BEGIN explicitly replaces the old case, including
its physical frame size; idempotent BEGIN does not reset this ownership state.

Under PRIMASK, the main owner checks CS high, untouched RX DMA and empty RX FIFO,
clears stale GPIO edge evidence, and checks again. It disables both DMA channels,
retains any new edge/RX evidence, and resets/reinitializes SPI to empty prefetched
old TX bytes. It selects the fully prepared reply and rearms the same RX slot.
No queue credit, receive-boundary ordinal, ACK or production retirement proof is
created by this gap operation. Both-edge raw GPIO status survives SPI reset and
is checked through the completed rearm; PRIMASK does not stop external CS/SCK.

An overlapping CS edge, low level or RX progress sets quarantine and increments
the collision counter. If trace is enabled, it invalidates that case's trace.
The next CS-high retirement discards the ambiguous reception, even if the reset
retained zero RX bytes. It never clocks that event into the full-exchange trace,
enqueues it, treats it as CLOCK, replaces the unobserved reply, or grants proof.
The prepared active reply remains available for a clean repeat; bounded logger
retry/recovery stays unchanged. Quarantine discards are explicit losses separate
from receive-queue-full losses. A collision is an experimental failure, even if
normal wire validation happens to see no error. This is fail-closed recovery,
not a guarantee that colliding transactions are electrically intact.

## Observations

Wire protocol1 adds optional STATS25; requests above25 remain errors. It uses
the existing ten-word observer snapshot, not an engine authority interface:

|Word|Meaning|
|---|---|
|0|schema1; generic peers may return0/unknown|
|1|early publication enabled0/1|
|2|eligible attempts|
|3|selected/rearmed replies, including detected collisions|
|4|busy deferrals after eligibility|
|5|detected reset/rearm collisions|
|6|quarantined receptions discarded|
|7|boot maximum reset/rearm software duration, us|
|8|master clock epoch|
|9|sticky timing invalid|

Attempts equal publications plus busy deferrals modulo2^32. Collisions minus
discards modulo2^32 is0 or1. Endpoint counters include entry/readout controls,
not just timed traffic; boot maxima are states, not deltas. At most one quarantine
can be outstanding. The logger queries25 before workload entry and after confirmed
worker stop. Failed optional queries stay unknown. STOP retries replace observer
results rather than accumulating them. Unsafe worker stop skips post-run observers.

Result schema becomes `bodaqs.spi-probe.v14`, with `master.early_measured`,
`early_before`, `early_after`; existing v13 trace payload stays unchanged. The
analyzer permits receive-to-publication distance0 only for v14 with recognized,
valid, enabled STATS25. Historical schemas retain their stricter rules and reports.
Collision/discard deltas fail candidate evidence even with clean wire counters.

Trace selection remains first8 successful POLL/ACK preparations after skipping256.
It is not a whole-run distribution and may sample different fragment types in the
two variants. Publication timestamp is software selection for rearm: boundary
entry in the late path, a fresh read immediately before selection in the gap path.
It is not the pad edge or the instant DMA is fully armed. Rearm maximum is separate.
Full-exchange observation still does not prove correct MISO or logger acceptance.
Never subtract absolute master/logger timestamps or add overlapping cost totals.

## Validation and acceptance

Use the extracted actual adapter with simulated GPIO/DMA/FIFO to establish next
exchange availability, retention under queued work, low/progress/FIFO refusal,
short/excess and zero-byte collision handling, pending IRQ after PRIMASK restore,
raw edge pulses across reset/arm, counter snapshots and clean recovery. Exercise
complete1008B objects/four nodes/all frame sizes, wrong/lost/repeated ACK and
ACK_FETCH, and changed frame size after admitted new BEGIN. Preserve legacy
lifecycle tests in the old-handoff matrix. Negative mutations must make the actual
ownership and raw-latch checks fail. Check positive/failed public observer readout,
modular analyzer counters, historical compatibility, explicit target builds and a
fresh boundary/whole-feature review before sealing.

Physical acceptance requires5000 fresh rows per ADC per10s, no reused/missing rows,
read failures/timeouts, wire/transfer/accept/command errors, collisions/quarantine,
invalid trace or exhausted retries. Retain all SPI/CAN losses. Compare ACK-confirmed
goodput, RAM acceptance, CLOCK/retry counts, queue wait, reply age and master-local
trace stages. Stop and retain the capture on failure; do not tune other parameters.

GPIO synchronizer timing, actual SCK, electrical integrity and rearm timing remain
bench questions. Native CAN/IMU plus SD/BDQ, long runs, overload/recovery, full-channel
ADC support and production capacity remain unqualified. Host passes and successful
links do not establish physical safety margin or a dependable200kB/s target.
