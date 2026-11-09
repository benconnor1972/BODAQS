# Real IMU exchange-start pacing diagnostic

This logger-only experiment follows the completed `261109_160153.bdq` capture
with logger commit6718cf6 and the original r3 acquisition master/node images.
The file closes cleanly, but its resolved sequence prefix contains32135 missing
samples (31.10%). The matching master snapshot freezes on its first ingress loss
after767541us: ingress depth128, three ingress drops,426 new SPI request drops
(raw561 minus baseline135),
843 processed requests and no CAN software/hardware loss. Prepared sample replies
include246 repeated fragments out of385. Those counts suggest excessive request
pressure/replay amplification; they do not establish a physical root cause.

The prior synthetic round17 benchmark used500us minimum exchange-start spacing,
25us completion-to-next-start guard and an ADC500Hz workload. Real acquisition
retained the25us guard but omitted the500us start limiter, and runs up to eight
owner service calls before a one-tick yield. This diagnostic restores the500us
minimum while preserving that task loop. It does not reproduce the synthetic
ADC workload or establish that its earlier capacity applies to live acquisition.

## Implementation and scope

Only `bodaqs_s3_mini_n4r2_imu_pace500` defines
`BODAQS_MEASUREMENT_START_SPACING_US=500`. Existing production and smoke
environments default to zero additional start spacing. All measurement exchanges,
including status/control/ACK-fetch and cleanup, receive the limiter. Legacy
84-byte administrative transfers retain their existing guard and zero limiter.

`SharedSpiBus::transfer` gains an optional final argument, default0. After taking
the bus mutex and setting up the transaction, it delays only the remainder of
the requested interval since the previous bus CS assertion. Its timestamp is
recorded immediately after asserting CS, under the same lock. Existing callers
remain source-compatible and unpaced. After a slow exchange or task delay there
is no additional500us sleep. With another shared-SPI client enabled, spacing from
that client's preceding transaction can be more restrictive; keep ADC disabled
for this controlled diagnostic. SD uses SD_MMC, not this SPI mutex.

The existing25us inter-CS guard remains. Physical256-byte frames, requested16MHz,
ACK_FETCH, master/node firmware, queue sizes, sensor configuration and file format
are unchanged. This is a diagnostic profile, not a qualified scheduling policy.
No changes are made to loss accounting or master ACK instrumentation in this
experiment, so the following limitations continue to apply.

## Measurement and decision

Record the same single nominal3333Hz IMU for about30seconds, with ADC and unrelated
sensors off. Request STOP with the logging button, retain serial output, wait
for finalization and copy the completed BDQ. If cleanup is pending after15seconds,
use the working Wi-Fi toggle for REMOTEIMU diagnostics. No Mark button is needed.
Preserve the global `gMasterDrainInfo` snapshot before another recording resets it.
It freezes on first ingress loss; a no-loss run instead freezes at STOP, so elapsed
time and finish_reason must be compared with the counters. Read expanded arrays,
not their debugger addresses. Useful fields are elapsed_us, finish_reason,
spi_dropped/base, ingress_dropped/base/depth/high_water, can_dropped,
can_hardware_losses, calls, total_us, fragments, data_unique_fragments and empty_replies.

Compare decoded unique sequence coverage/gaps, unresolved tail, final source
boundary and clean closure against the previous capture. Also compare time to
first master ingress loss and repeated/empty reply fractions. More raw exchanges
are not the goal. Improvement supports the pacing-pressure hypothesis; persistent
loss leaves master service cost, live traffic prioritization and storage/consumer
backpressure as candidates. A single successful30second run is functional evidence,
not sustained storage or production admission qualification.

Known instrumentation limits: master ACK counters omit active kind14 ACK_FETCH;
zero is not evidence of absent retirement. Logger loss totals can repeatedly add
the same cumulative counter after terminal management evidence resets the local
baseline. Keep raw counts, but use independently decoded sequence gaps and unique
source evidence for delivery conclusions. Storage write wall time includes waiting
and preemption and is not proof of an SPI blackout.

## Software evidence

The deterministic production `SharedSpiBus` test fails before the limiter exists
and passes with it. It observes CS starts through GPIO and covers first exchange,
short/slow transfer, mutex/setup delay, unpaced callers, failed locking and micros
wrap. The real owner/master lifecycle fixture checks propagation of500 only to
measurement slots, and retains STOP, asynchronous fence, uncertain exit and fresh
recording regressions. Its synthetic clock is not physical timing evidence.
Target compilation and host suite results belong in the diagnostic bundle.
The operator's completed recording is the actual test of the loss hypothesis.
