# Master measurement service phase timing

This master-only diagnostic follows the LOG0003.bdq500us pacing run. Keep that
logger and the original first-recording acquisition node. LOG0003 closes cleanly
and resolves all saved sequences, but20.8% of source samples are missing.
The first-loss master snapshot reports1470 processed requests over1.228742s,
with mean process_transfer lane wall time403.46us. That lane includes more than
the protocol function, and repeated/empty prepared replies are not necessarily
removable work. The audit's naive idle-control-poll removal worsened backlog.

## Diagnostic build

Build the master with CAN_LINK_PROFILE=acquisition,
SPI_MEASUREMENT_PROFILE=first-recording and SPI_PHASE_TIMING=1. The latter
defaults to0 and is rejected for the legacy profile. Existing profile rebuild
dependencies force both consumers to rebuild when switching it.

Optional main-owner hooks bracket successful measurement-frame handling in
the common service. No wire fields, validation rules, retention decisions,
queue capacities, frame sizes, ISR/DMA publication or fence semantics change.
The common service has no dependency on the physical clock unless enabled.
The master supplies the clock and aggregates into gMasterDrainInfo version3.
The added counters occupy160 bytes in that debugger snapshot. No serial
output, allocations or new ISR work are introduced.

The version2 prefix remains in place. When enabled, version3 appends:

- phase_calls[4]: number of successful requests in each row.
- phase_total_us[4][3]: accumulated phase wall time.
- phase_max_us[4][3]: maximum single phase wall time.

Rows are mutually exclusive:0=ACK_FETCH input kind14 with any reply;
1=other input producing an empty reply;2=other input producing a fragment
(sample/evidence/control/protected/shared);3=other input/reply combination.
Columns are0=physical decode plus request proof validation,
1=dispatch including batch advancement/sealing and availability hints,
2=physical reply encoding including CRC. ACK_FETCH counts take precedence
over the reply category; row0 therefore includes empty and data responses.

The profiler reports only successful measurement requests. Malformed frames
and legacy84-byte administrative frames remain represented by the original
outer counters, not the phase table. Invalid frames still take the existing
rejection path; no success record is manufactured for a failed validation.
Common preamble, bookkeeping, aggregation and publication lie outside the
three phase intervals. Existing calls[1]/total_us[1]/max_us[1] retain the outer
timer. Interrupt time is included in all wall measurements. Clock discontinuity
marks timing_invalid as before. Unsigned subtraction handles one micros wrap.

Scope begins at START admission and freezes at first observed ingress loss,
STOP admission or identity change. A new recording resets the complete snapshot.
After freeze, hooks do not read the hardware clock or change the counters.
Instrumentation adds four clock observations and bounded aggregation per valid
measurement request while active, so delivery may shift slightly. Compare phase
fractions and outer residual rather than treating this image as a throughput fix.
Do not compare a phase maximum with a sum of maxima from different requests.

## Operator evidence

Record the same single IMU for approximately30seconds, request STOP normally,
and wait for file closure. Keep ADC and unrelated sensors disabled. Preserve
serial output and the finalized BDQ. Then expand gMasterDrainInfo in CCS and
copy version/state/finish_reason/context/recording/elapsed_us/timing_invalid,
calls/total_us/max_us, all three phase arrays, SPI/ingress/CAN drop counters,
fragments, data_unique_fragments and data_repeat_fragments. Do not start a second
recording before saving the snapshot. Do not halt the master during acquisition
or cleanup; resume after inspection before a new run.

Verify version3. If it is2, the diagnostic executable/symbols are not loaded.
SPI drop fields already subtract their saved baseline; do not subtract twice.
The linker may move private globals, so use the new executable's symbols,
not old hardcoded addresses. No new logger upload is required.

For each populated row, divide each phase_total_us cell by its phase_calls
to obtain mean wall cost. Weight across rows to obtain combined means. Match
the summed count to successful measurement handling in the outer snapshot;
legacy, malformed and scope-boundary events can explain small differences.
Keep current loss and ACK counter limitations in view. The decision is whether
cost lies in validating/encoding every slot or in dispatch/batch work, before
attempting caching or a scheduling change. This does not establish physical
timing accuracy, sustained storage capacity or a production admission policy.

## Software validation

The production v2 fixture runs with timing disabled/enabled and compares its
independent encoded wire vector; it exercises ACK_FETCH/empty/data responses
and validates phase intervals across a synthetic timer wrap. Production adapter
tests cover category accumulation, maxima, freeze and new-context reset, alongside
existing raw CS/DMA retirement and queue-ownership regressions. Full host and TI
target results, memory/stack evidence and a fresh boundary review accompany the
master-only bundle. Hardware cost distribution remains an operator measurement.
