# Single-owner rows and master pacing, round 5

This logger-only bench prototype follows [round 4](SPI_Execution_Probe_Round4.md).
Case411 was clean for17606 replies with624.4/624.3 ADC reads/s, but discarded ADC
values. Worker controls failed with either ADC alone, either worker core, no row
reads and low-rate pacing. Root cause remains unproven. This round measures actual
500Hz row freshness and fixed request pacing, not production admission.

Normal firmware, master/common protocol and node firmware stay unchanged. Manual
logger flashing remains the user's responsibility. Schema/build identity advance
to v5; analyzer accepts v1..v5 and preserves old reports.

## Commands and scope

New twelve-token modes use the existing owner parameter layout:

```text
case ID owner_adc  FRAME HZ NODES MS cached START_INTERVAL 3 1 0
case ID owner_rows FRAME HZ NODES MS cached START_INTERVAL 3 1 0
```

Both require mask3, actual owner core (1 on this A8 build), no added ADC pacing.
`owner_adc` has no master traffic. `owner_rows` uses the unchanged synthetic master
transport. Requested128bytes/8MHz, cached expected CRC and500us initial master
interval follow case411. Fixed750/1000/1500us intervals are separate controls;
no live profile switching or adaptive backpressure is introduced. Cached mode
retains frame CRC, exact known-payload checks and whole-object validation before ACK.
Old modes retain their behavior; original owner still discards analog data.

ADC values are published to a bounded RAM ledger. SD/BDQ output, storage stalls,
physical CAN/native IMU traffic and production row-queue integration are excluded.
Do not describe this RAM publication as a successful storage write.

## Owner acquisition and publication

No ADC worker or new ISR registration starts. Before the observation window,
both ADCs complete real warmup conversions through the existing acquisition/cache
publisher. Warmup failure aborts startup. Warmup samples can supply the first row;
their actual cache publication timestamps remain visible.

Inside the timed window, the owner holds separate conversion states for each ADC.
It polls both real DRDYs, reads completed conversions first, publishes the due row,
then starts each idle ADC with the normal bounded WREG/START pair. Commands,
1000SPS settings and1/5/4-byte transfer shapes stay unchanged. RDATA values use the
same negative-value clamp and configured effective-bit scaling as the normal ADC
path before publication. Conversion identities increment only on successful reads.
The ordinary readCounts cache/freshness path consumes these samples without any
implicit synchronous ADC transactions. Normal firmware compiles this hook out.

The row schedule is the existing2ms midpoint grid. Each due row consumes both
AIN0/4 once, including invalid/reused observations. Late deadlines are counted;
no catch-up conversions or rows are invented after the finite window. Freshness
means conversion identity was not previously used by that channel's row; equal
numeric values do not mean reuse. Row counts remain effective-bit counts, not raw
24-bit ADC codes. Scheduled, cache-publication and row-publication times are
different observations, not claims about physical conversion alignment.

Master tick remains available while ADCs convert. New row modes defer master tick
within800us of the next row deadline. This fixed software reserve follows observed
cached validation costs; it is not a certified worst-case bound. Actual lag,
missed rows, cache age and read-gap observations determine the outcome. No timing
claim is inferred just from the reserve or requested clock. No allocation or
serial output occurs in the active publication path.

Rail fault checks and6000us owner readiness timeout remain. Serial STOP ends
cache ownership before master shutdown. Confirmed STOP and reboot-required state
after incomplete shutdown are inherited. A physical single-shot conversion may
finish after STOP; no acquisition loop is left running. New starts clear cache,
ledger, row identities, counts and deadline state. Original worker modes restore
their own default configuration as before.

## Evidence and acceptance

`row_publication` exists on every v5 result, inactive/empty for older modes. Active
results identify sink `bounded_ram`, published/valid_both/fresh_both counts,
publication lag,800us guard, master deferrals, per-ADC read gaps, first four rows
and the last row. Each retained row has index, scheduled/published times, two
scaled count values, conversion identities, cache-publication times, validity and
freshness masks. All rows feed a diagnostic FNV-1a digest with canonical
little-endian fields; this is not a wire CRC or durable storage checksum.

Existing ADC fresh/reused/no_sample/acquire_fail counters are the authoritative
full-window row observations. The prefix is a bounded audit, not a complete log.
Read gaps begin after the first timed RDATA; warmup gaps are excluded. Timing
counters outside the new traffic window still include startup/shutdown.
For owner-row modes, ADC config/start/wait/read/total timing summaries describe
only synchronous warmup; the split timed owner steps do not populate them.
acquire_ok includes warmup plus successful timed publication. Use the timed
shared-SPI observations, read_gap, cache age and row lag for active-run timing;
do not present warmup acquisition maxima/means as full-run owner measurements.

An ADC freshness pass requires every scheduled row, no missed rows, fresh valid
conversions for both channels on each row, no acquisition failures/timeouts and
complete worker shutdown. Mean acquisition rate alone is insufficient. A complete
duration result can still fail freshness. Analyzer keeps row freshness, wire
integrity, master receive pressure and useful throughput separate. Master drop
counter deltas include control endpoint scope, as before; zero observed drops is
not proof against all physical loss. Every new mode remains a diagnostic control,
never a production/T01/admission pass.

## Validation and manual capture

Host runtime tests execute real controller, cache, scaled ADC value path, row
ledger, shared bus, codec and master engine with simulated GPIO/SPI/RTOS. They
use independent signed24bit ADC wire values, constant values across distinct
conversions, delayed DRDY causing reuse, never-ready DRDY, rail fault, STOP during
wait, failed ADC transfer, late finite window and restart. Hardware timing,
electrical reliability and per-row freshness remain manual evidence debt.

Build both A8 normal and SPI-probe targets; preserve a source/hash identified
bundle. Keep the round2 master running. Check idle ready/unblocked between cases
and return each result before continuing:

| ID | Mode | Interval us | Purpose |
|---|---|---:|---|
| 500 | owner_adc | 0 | Owner-only500Hz freshness baseline |
| 501 | owner_rows | 500 | Freshness plus original master pacing |
| 502 | owner_rows | 750 | Controlled receive-pressure comparison |
| 503 | owner_rows | 1000 | Further pacing comparison |

Use mask3/core1/cycle0 and cached CRC for all four. Stop and diagnose a failed
baseline before changing transport conditions. Choose any later control from the
measured results rather than automatically sweeping clocks/frame sizes. Longer
combined validation and production integration require a separate implementation.
