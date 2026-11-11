# r11: ADC shared-SPI cost split

Logger-only diagnostic, retaining the exact r10 master and existing IMU node.
The default-off `BODAQS_ADC_SPI_PHASE_TIMING=1` is selected only by this logger
environment. Full four-register WREG plus explicit START, the six-byte CS span,
RDATA, single-shot mode, gain/reference/rate/mux, readiness handling and cached
row semantics remain unchanged. No SPI clock, pacing or admission change.

## Timing contract

Each ADC transfer supplies an optional caller-owned `SpiTransferTiming` output
to SharedSpiBus. Existing callers omit it. Timestamps partition wall-clock cost:

- `lock_wait_us`: request to successful mutex acquisition, including any pacing
  retry/wait. ADC transfers remain unpaced.
- `prepare_us`: acquisition to just before the HAL call, including Arduino SPI
  transaction setup, CS assertion, context bookkeeping and any CS setup delay.
- `transfer_us`: elapsed HAL transfer call, including HAL work and preemption.
  This is not an independent measurement of physical clocking time.
- `finish_us`: after HAL return through CS release, endTransaction and bus
  diagnostic bookkeeping, ending before mutex release.

Per-transfer output is filled after unlock. The ADC owner aggregates setup/start
and read-data calls separately; no allocation or per-transfer serial logging.
The footer's existing stopped-worker publication gate also covers these new
64-bit aggregates. Counters reset with existing ADC session timing statistics.
Failed calls count separately; their lock wait is stored in
`failed_wait_total_us`, not included in successful phase means. Invalid calls
clear the caller's output and do not reuse earlier timing values. Unsigned
microsecond subtraction handles one clock wrap within an individual call.

Each ADC footer entry adds optional `shared_spi_phases` version1, containing
`setup_start` and `read_data`, each with completed/failed counts and per-phase
total, maximum and mean. This is additive diagnostic JSON; sample records and
protocol formats are unchanged. Default builds omit this key and request no
phase timestamps. Observations add overhead and do not prove electrical timing.

## First recording

1. Flash only the selected r11 logger application at0x10000, preserving matching
   partitions/NVS/settings. Retain r10 master and node. Exact images, hashes and
   recipe are in the passed manifest; separate flash evidence records installation.
2. Restart logger and IMU node. Keep the same configuration/card/hardware: one
   IMU plus one500Hz analog channel on each ADC, multistream BDQv2. Confirm three
   streams, two primary columns and no exclusion. Floating inputs may remain.
3. Record30-60 seconds, then STOP normally. Wait for file closure and cleanup;
   provide finalized BDQ and full serial. No master trace/export is needed.
4. Compare setup/start and read-data phase totals/means against r10's elapsed
   setup/read costs. Use completed counts consistently; do not sum independent
   phase maxima. Inspect ADC freshness/age, failures, source loss and strict decode
   counters alongside timing. No need to repeat the long r10 baseline first.

Choose the next optimization from measured dominant cost: bus waiting suggests
contention/scheduling; preparation or HAL overhead suggests a short-transfer path.
Do not skip full configuration restoration, explicit START or validation to make
the counters faster. Controlled storage-stall and known-input mux/accuracy checks
remain deferred. This run is diagnostic, not an expanded admission qualification.
