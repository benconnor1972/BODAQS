# SPI integrity probe: round 3

User-authorized diagnostic continuation of round 2, 6 November 2026. This
changes the logger only. Keep the matching round-2 diagnostic master running;
wire protocol v1, mode 0 and requested master clocks are unchanged. No device
flashing is authorized for the agent. Preserve all old bundles and captures.

The question is which actual ADC operation precedes the isolated zero first
byte, and whether worker concurrency is required. This is not a throughput,
ADC freshness, physical timing, four-node CAN or production qualification.

## Changes

- Give one-byte ADC commands aligned four-byte backing storage and five-byte
  register writes aligned eight-byte storage. Keep logical wire lengths 1/5.
  The installed Arduino HAL reads rounded-up uint32 words. Four-byte ADC read
  buffers are explicitly aligned too. Normal and probe builds receive this fix;
  no third-party library or ADC command/register settings change.
- Under BODAQS_SPI_PROBE, retain preceding transfer length, first transmitted
  byte and TX/RX buffer presence with the existing CS/time context. Capture and
  advance this state under the real shared SPI mutex, including worker traffic.
  Aggregate successes/failures by complete preceding-operation key, not just CS.
  Fixed RAM: sixteen buckets plus an explicit omitted-observation count; four
  full failed replies plus omitted-sample counts remain unchanged. No hot prints.
- Add `shape` and `selected` modes at the existing nine-token command interface.
  Both reuse the normal ADC WREG(5), START(1), RDATA(4) code, alternate ADC0/ADC1
  after complete cycles, and run from the owner loop with no ADC worker tasks.
  One ADC operation runs immediately before each due master request. No row
  acquisition or cache publication runs in these controls.
- `shape` leaves all registered CS pins HIGH under the mutex, including ADC CS,
  and records participant -2. It uses the actual command bytes, lengths and
  null/non-null RX pattern. Readiness is a synthetic 1000 us after START.
- `selected` selects the actual ADC, polls its dedicated DRDY before RDATA and
  fails after a bounded 6000 us since START release. The wait owns no bus mutex
  and starts no ISR/worker. The conversion runs single-shot; stopping a case
  does not leave a background acquisition loop. Returned analog values are
  discarded. Record no fresh-row or ADC-rate claims for this control.
- Both controls pause master requests during the conversion wait. Their request
  timing therefore differs from mixed worker runs and is measured explicitly.
  They separate command shape/selection/concurrency; they are not matched load
  controls. No mode-1 master trial or CS-per-byte change is included.
- Source-derived logger build identity and output schema advance to v3. All
  old seven-/nine-token commands still work; input/analyzer supports v1/v2/v3.

## Result additions

`failure_samples[].bus.previous_operation` and
`diagnostics.by_previous_operation[].operation` contain:

```
{"bytes":5,"tx0":67,"has_tx":true,"has_rx":false}
```

`tx0` is the first transmitted byte, not an interpreted protocol opcode.
ADS signatures: WREG 5/0x43/no RX, START 1/0x08/no RX, RDATA 4/0x10/RX.
Master exchanges have first byte 0x53. Unknown history has zero length, byte
zero and both flags false. The full aggregation key includes preceding CS.
The separate `operation_buckets_omitted` count covers all observations that
could not fit, including successes. It is not a failure count. Buckets count
every timed decode only; entry/STATS/STOP remain outside timed diagnostics.

`diagnostics.sequence` records active, worker_start_requested, failures,
timeouts, and `operations[adc][step]` successful counts in WREG/START/RDATA
order. Inactive controls have zero step counters. Failed attempts do not count
as successful steps. Successful complete controls must have reads on both ADCs,
zero control failures/timeouts and no worker start requested. Rows remain zero.
All result types include the build identity. Master STATS pages are unchanged.

## Initial manual comparison

Use the same board, wiring, power, 128-byte/requested-8-MHz profile and 10-second
windows. Flash the new logger manually; retain the round-2 master. If the
master was reset/debug-loaded, resume it in CCS. Check `status` is ready and
not blocked between cases. Send one line, await its result, then inspect it.

```
case 300 adc 128 8000000 4 10000 legacy 0
case 301 bulk 128 8000000 4 10000 legacy 500
case 302 mixed 128 8000000 4 10000 legacy 500
case 303 shape 128 8000000 4 10000 legacy 500
case 304 selected 128 8000000 4 10000 legacy 500
```

Pause after each result. Case 302 tests whether the padded buffers and added
instrumentation change the reproduction; a clean single run is not proof of a
fix. If mixed still fails, preceding-operation buckets identify which ADC
commands correlate. Case 303 isolates the actual short-transfer pattern without
selection/workers. Case 304 adds real selection/MISO drive/conversion but keeps
workers absent. Differences also change timing; preserve all results.
No clock sweep, caching change, validation weakening or data repair is planned.

## Validation limits

Existing public runtime/serial and analyzer tests cover command shapes, CS
selection, preceding-operation identity, bounded failures/STOP, unchanged
known-data acceptance and backward compatibility. Physical peripherals are
simulated there. Target builds check normal/probe compile boundaries. None of
these checks can establish that the electrical first-byte issue is fixed.
