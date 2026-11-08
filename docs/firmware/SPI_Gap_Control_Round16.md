# SPI ownership-only control - round16

Verified base: round15 `0118e1dca50a45ff15753520c8269262945eb2c1`.
This diagnostic separates CS-high gap publication from its active-reply ownership
gate. It is not a fix for the first-byte corruption or a throughput optimization.

## Evidence and question

Round15 early/off case1504 recorded189bad-magic replies and188retries, while
late/off1502 and return-late/off1505 recorded no wire errors/retries. All four
saved failures were incoming fragment0 replies; replay through the real codec
rejects them, and a regenerated complete known-data frame differs only at byte0
(00 instead of53). This does not characterize the185unretained failed frames or
prove a physical mechanism. Case1505also recorded one control-inclusive SPI RX
queue loss. All transport cases had ten background CAN software drops. Fresh
rows remained healthy. Current cadence is near1300/s in both variants, so the
original1350/1000split is not reproduced with the round15 logger.

Hypothesis: removing gap reset/rearm, while retaining ownership protections,
removes the observed corruption. A clean ownership-only run supports further
investigation of the gap path and changed scheduling; it does not identify a FIFO,
DMA, electrical or RAM defect. A failed ownership-only run keeps those alternatives
open. A same-source full-gap reference can test whether the failing condition is
reproduced; if all modes are clean, the physical fault remains intermittent.

## Fixed scope and variants

Reuse the exact sealed round15 logger binary, identity
`spi-probe-v15-0118e1dca50a-b2a7d6a700dce85ffa8d-crc1`, environment
`bodaqs_s3_mini_n4r2_spi_probe` on ESP32-S3 A8/N4R2. Do not rebuild/reflash the
logger for this round. Result schema remains `bodaqs.spi-probe.v15`, protocol1.
The new analyzer understands independent master flags; the old analyzer does
not interpret the new metadata. Production logger/ADC/SPI code remains unchanged.

Build three MSPM0G3518 acquisition masters from the same round16 source, queue4,
table CRC, trace enabled and both-edge CS observation:

|Mode|EARLY_PUBLISH (ownership gate)|GAP_PUBLISH|STATS25 schema2 flags|
|---|---:|---:|---:|
|Late reference|0|0|0|
|Ownership-only control|1|0|1|
|Full-gap reference|1|1|3|

`BODAQS_SPI_PROBE_GAP_PUBLISH` defaults to the existing EARLY_PUBLISH flag, so
omitting it preserves the former coupled selection. Values other than0/1 and
gap1with ownership0 fail compilation. Only the `probe_early_publish()` body is
conditioned on GAP_PUBLISH. The existing boundary ownership condition, exact
physical-length observation, publication clearing, new-admitted-BEGIN exception,
quarantine and RX/ACK authority remain unchanged. No new RAM arena or stack
reduction. Normal production excludes these bench flags and keeps its behavior.

The ownership-only gap function must perform no DMA/reset/rearm, swap, queue work
or counter/timestamp update even with an eligible prepared successor. Short and
excess exchanges still retain both an unobserved active reply and its successor;
an exact full exchange permits boundary publication. Active observation remains
independent of trace0/1. All data/ACK integrity checks remain strict; no repairs.

## Observer extension

STATS25 remains a ten-word payload but its format discriminator becomes2:

```text
[2, flags, attempts, publications, busy, collisions, discarded, max_rearm_us,
 epoch, timing_invalid]
```

flags bit0=active-reply ownership gate, bit1=CS-high gap publication. Legal values
are0,1,3. When bit1is zero, words2..7must all be zero. Enabled gap counters retain
their modular conservation and quarantine meaning. The v15 logger already copies
these opaque words before/after the workload; no logger interpretation changes.
New analyzer fields `configuration_schema`, `ownership_gate`, `gap_enabled` are
emitted for recognized schema2 only. Existing `enabled` means gap publication is
enabled; ownership alone never permits same-boundary arrival/publication in trace
validation. Schema1 reports retain their previous representation exactly. Mixed
schema/flags/epochs and disabled-gap activity are invalid; unknown formats remain
unknown. Endpoint deltas include entry/readout controls, not just timed traffic.

## Bench sequence and constraints

Keep256-byte frames, requested16MHz (actual SCK unmeasured), four synthetic nodes,
four pending requests,500us pacing,10ms/eight retries,25us guard and800us row
reserve. Logger dispatch trace remains OFF. One sensor on AIN0/ADC0 channel0 and
one on AIN4/ADC1 channel0 each require500fresh rows/s; other six inputs unused.
The configured1000SPS is not achieved read cadence. Node firmware/wiring unchanged.

Use new increasing IDs1600late,1601ownership-only; review each capture separately.
The full-gap1602reference is a follow-up only after the first two results are
reviewed, not an automatic sweep. On any SPI/ADC/STOP/queue/collision/epoch failure,
retain the result and stop. Known background CAN drops remain visible/failed
candidate evidence; they do not invalidate reading the separate SPI/ADC diagnosis.
Restore the exact sealed round14 late master afterward. All flashing remains manual.

This is a fixed256-byte diagnostic. Reset/reload the master and reboot the logger
between images; do not switch physical sizes on a live ownership-only case. A
boundary-only owner can retain an unobserved duplicate STOP plus a ready successor.
An immediate different-size BEGIN cannot establish the old reply's full-exchange
observation and may be blocked behind that successor. No ownership bypass is
added for this diagnostic. Host size-transition coverage explicitly drains old-size
CLOCKs before testing a newly admitted BEGIN at a new size. That is simulated
peer coverage, not a new capability of the unchanged logger. Production promotion
would need an explicit profile-transition design/qualification.

## Offline evidence and limits

Actual adapter extraction tests cover queue1/4 x CRC bitwise/table x trace0/1 x
the three legal configurations (24configurations), plus inherited flag defaults
and illegal compile selections. They exercise no-gap inactivity, boundary ownership
on short/excess/full exchanges, complete1008-byte objects, ACK/retry/STOP and new
admitted BEGIN after old-size drain. Negative mutants re-enable the gap in the
control or bypass unobserved ownership and must fail the intended assertions.
Public logger runtime tests exercise schema2 opaque metadata collection without
changing deployed logger code. Analyzer tests distinguish independent flags and
same-boundary permissions, reject contradictions, and preserve historical reports.

Fresh review is required at the ownership/DMA/metadata boundary before sealing,
with source/build fingerprints and target RAM/stack evidence retained. Master
normal/late/gate/full builds are offline only. Tests simulate DMA/GPIO/FIFO and
copy RAM as MISO; they do not model the serial shift register or reproduce the
physical corruption event. A pass is not evidence of physical TX readiness.

Neither this synthetic short test nor a higher goodput qualifies native CAN/IMU
plus SD/BDQ, sustained overload/recovery, electrical timing, broader ADC workloads
or dependable200kB/s capacity. A zero gap count proves only that software reported
no gap activity under its selected build, not physical binary attestation.
