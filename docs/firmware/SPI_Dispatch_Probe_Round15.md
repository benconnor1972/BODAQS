# Logger dispatch diagnostic - round15

Base: round14 `520f35cab1f438e40580a64cee90db4698bba0bd`. Round14 repeatedly
measured 13,497 versus 10,000 exchanges per ten seconds with late versus early
master handoff. This round observes the logger decision sequence; it makes no
scheduler, ADC, pacing, protocol or master ownership change.

## Experiment

Use the exact sealed round14 late/early acquisition masters (queue4, table CRC,
trace enabled), with a new v15 logger. One sensor on AIN0/ADC0 channel0 and one
on AIN4/ADC1 channel0 must each retain 500 fresh rows/s. Other six inputs remain
unused. Keep 256-byte frames, requested16MHz, four synthetic nodes/pending slots,
500us pacing, 10ms/eight retries, 25us guard and 800us row reserve fixed. Actual
SCK is unmeasured. CAN losses remain visible, including the known background
software drops; this is not concurrent native-CAN qualification.

First run a ten-second ADC baseline, then late trace-off/on and early trace-off/on.
Use one identical logger image. Restore the late master afterward. No six-case
round14 repeat or master rebuild is needed. Operator flashing/Run/F8 is manual.

The optional final argument extends the existing serial bench interface:

```text
case ID owner_flow 256 16000000 4 10000 cached 500 3 1 0 10000 TRACE
```

TRACE is0/off (also the omitted default) or1/on. Other modes reject this extra
argument. Existing command forms retain their defaults. Result/identity versions
become `bodaqs.spi-probe.v15` / `spi-probe-v15-...`; wire protocol remains1.
The analyzer retains v1-v14 support and their historical report representation.

## Three falsifiable leads

1. Pacing plus ADC work carries the next opportunity across the row reserve:
   trace a pacing deadline expiring during ADC service or inside the reserve.
2. Reply-dependent validation moves that opportunity: correlate first-fragment
   expected-CRC and final-fragment object-CRC costs with the following gates.
3. Master handoff/ownership changes the reply sequence that drives this feedback:
   correlate useful/stale/duplicate replies and pending state with those gates.
   A full pending window generates CLOCK; it does not directly suppress exchanges.

The record can distinguish logger gate sequences and reply effects. It cannot
identify every internal master ownership state; add a master probe only if this
trace leaves that specific ambiguity. Phase locking remains a hypothesis.

## Bounded observation

The nominal capture is [1,001,000,1,065,000)us relative to timed case start,
aligned with a scheduled row deadline after warm-up. Select consecutive cycles
whose start is in that window, retaining each selected cycle to completion.
First observation is the first owner-loop start at/after the nominal boundary;
the final cycle may extend past the cutoff. No serial printing or allocation
occurs in the timed window. A static 512x96-byte arena uses49,152bytes on the
logger only; the master image/RAM budget is unchanged.

Every cycle with ADC reads/starts, row publication or dispatch is retained individually.
Consecutive idle cycles with the same gate, row/deadline, pending/ADC state,
slot and pacing anchors coalesce. A span retains the first cycle's stage times,
last cycle's end and exact cycle count. It does NOT retain intermediate check
times or imply continuous CPU occupancy. Saturation retains a contiguous prefix,
counts every omitted cycle and makes the trace incomplete. No silent ring wrap.
Reset clears metadata/count, making old arena contents inaccessible without a
large stack temporary. Premature STOP, failed entry or a short case remains
explicitly incomplete when trace was requested. Existing worker/STOP safety
controls still determine workload completion.

Both trace settings collect lightweight window endpoints:
`[begin_us,end_us,slots_before,slots_after,rows_before,rows_after]`.
They count cycles admitted in the same nominal window, rather than CS edges in
an exact pad-level time interval. An unfinished endpoint remains zero/unknown.
This provides a local trace-off control: a64ms perturbation could disappear in
a ten-second average. Compare endpoint deltas AND whole-run cadence. A difference
over two exchanges in the local window or2% in whole-run rate is an observation
disturbance flag, not an optimization result. Smaller differences do not prove
zero disturbance; inspect phase patterns and endpoint alignment too.

## Record layout

`dispatch_trace.records` is an array of compact arrays, in this exact order:

```text
begin ready_end row_end start_end decision_at end span_end next_row
last_cs last_transfer_end cs release row slot request_object reply_object
validate_us expected_us object_us cycles decision pending_before pending_after
adc_before adc_after reads starts published clock_state
request_opcode request_node request_fragment reply_opcode reply_node reply_fragment
reply_status outcome_flags
```

Times are logger-local software observations in microseconds. Stage times and
deadlines are relative to case start. `last_cs` / `last_transfer_end` use modular
uint32 differences, so a pre-case anchor may appear near2^32. `clock_state` bits0/1
say which anchors exist. `last_transfer_end` is the transport-return anchor used
by the25us guard, NOT the physical CS release; `release` is the existing software
observation at CS deassertion. Never subtract absolute master/logger clocks.

Decision codes:1=row reserve,2=CS guard,3=pacing,4=dispatch,5=other.
ADC state packs ADC0 in bits0..1 and ADC1 in bits2..3:0=WREG,1=START,2=waiting
for data. Read/start masks use one bit per ADC. A start mask represents the
completed bounded WREG/START pair; DRDY is observed when the owner checks it,
not timestamped at its physical edge. `published` marks a row publication.

`reply_status`:0=no exchange,1=transfer failure,2=decode failure,3=decoded wrong
case/profile,4=decoded matching case/profile. Matching is not acceptance.
`outcome_flags` independently records increases in existing counters:
bit0=valid response,1=duplicate,2=stale,3=accept error,4=RAM object accepted,
5=ACK-confirmed object retirement. Object/fragment/node identity refers to the
outgoing request and incoming older reply separately. Zero identities are
meaningful only with the associated status/opcode. Expected/object CRC costs
nest within validation; never add them to validation again.

Existing per-cycle timing ends before summary/trace bookkeeping. Gaps between
records include that work and the outer loop. Trace-enabled bookkeeping can
alter the schedule; a valid trace with a changed rhythm is inconclusive about
the original mechanism. The analyzer validates ordering, counters, spans, nested
costs, pacing and window conservation, and exposes decoded records and intervals.
Incomplete requested traces fail candidate evidence independently of clean SPI.

## Validation and bench decision

Host tests exercise the actual collector and public logger/transport/ADC paths
against simulated peripherals, including on/off, partial/short STOP, arena
saturation/reset and32-bit Arduino clock wrap with an independent64-bit ESP
timer. Analyzer negative cases reject corrupted layouts/order/conservation.
They do not reproduce the physical cadence difference or prove a mechanism.

Bench success requires clean transport, all5000fresh rows per ADC, confirmed
worker/master stop, valid master trace/epoch and zero collision/quarantine or
SPI queue losses. Preserve CAN losses separately; known synthetic-mode CAN
drops still fail concurrent-CAN/candidate status. Require complete logger traces
without overflow. If off controls no longer reproduce roughly1350/1000exchanges/s,
or the trace changes the local cadence, report that before interpreting gates.

For each long exchange gap, follow the preceding reply/validation through ADC
service, pacing expiry and row-reserve admission. Explain the missing opportunity
with observed stages; leave unexplained intervals explicit. No profile tuning,
ownership weakening, speed claim or new firmware round is authorized by a bench
result. Native IMU/CAN plus SD/BDQ, sustained overload/recovery, electrical margin,
wider ADC loads and dependable200kB/s capacity remain unqualified.
