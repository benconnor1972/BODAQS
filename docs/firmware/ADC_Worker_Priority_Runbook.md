# r12: ADC worker priority trial

Logger-only experiment against the actual mixed r11 recording
`261111_163249.bdq` (SHA-256 prefix `65a7cb5fbf49`). That run had approximately
17% row reuse on both ADCs; increased shared-SPI waiting and elapsed time outside
the measured phases dominated the extra setup/read cost. Scheduling is a
hypothesis, not a proven cause.

The sole acquisition behavior change is ADC worker priority 2 to 3. The ordinary
build default remains 2. Both ADC workers remain pinned to core 0; CAN acquisition
remains priority 2 with the existing bounded eight-service catch-up group.
Higher-priority ADC workers still block for DRDY and use the shared SPI mutex.
The existing 50 ms no-block safeguard remains. No bus transaction is interrupted
or allowed to overlap another device's CS span.

Full four-register WREG plus explicit START, single-shot mode, rate/gain/reference/
mux, readiness and cached-row semantics remain unchanged. SPI mode 0 for the CAN
master, clocks, pacing, strict packet validation and CRC checks remain unchanged.
The r11 ADC phase diagnostic remains enabled. The r10 master and existing node
are reused by exact hash; neither is to be flashed for this experiment.

## Installation

The passed manifest selects `variants.priority`, logger environment
`bodaqs_s3_mini_n4r2_imu_adc_priority`, firmware name
`bodaqs_a8_imu_adc_priority_r12`. Flash only that application at `0x10000`,
preserving the partition table, NVS and saved configuration. Separate flash
evidence records the observed device identity and verified upload. The sealed
r11 logger is retained as the rollback image. Do not use a different environment
or reflash the master/node.

## First recording

1. After logger installation, restart the IMU node before the comparison run.
   Keep the same wiring, basic SD card and configuration: one IMU plus one 500 Hz
   analog channel on each ADC, multistream BDQ v2. Floating analog inputs may
   remain; they do not validate accuracy or mux settling.
2. Start normally. Confirm three streams and two primary columns, with no IMU
   exclusion at admission. If the IMU is excluded, stop and supply the file and
   serial; an ADC-only recording cannot answer this mixed-load comparison.
3. Record about 60 seconds, then STOP normally. Wait for file closure and cleanup.
   Provide the finalized BDQ and full serial, including FLOW/STOP output. No CCS
   export or scope capture is needed. Do not begin another run before preserving
   the evidence.

## Assessment and decision

Compare each ADC's successful setup/start and read-data phase means, outer call
means/residuals, worker loop, row reuse and row age against the mixed r11 report.
Use completed counts consistently; do not add independent phase maxima. Check
failure, timeout and no-sample counters. The 500 Hz row rate alone does not prove
conversion freshness, and elapsed HAL calls are not independent wire timings.

Check IMU identity resolution, sequence gaps, source loss, terminal source boundary,
STOP cleanup, decode rejections and queue peaks alongside ADC results. Do not
accept an ADC improvement obtained by starving IMU/control service. The baseline
had incomplete source-tail/loss reconciliation, so preserve uncertainty rather
than reporting a spurious whole-run loss percentage or adding repeated cumulative
loss observations. One successful file close is not complete delivery proof.

Retain the trial only if freshness/age improves without a material delivery or
cleanup regression; otherwise return to the sealed r11 logger before pursuing
more intrusive scheduling changes. A short run selects the next action; it does
not expand production admission or establish sustained capacity. Controlled
storage-stall testing and known-input accuracy/channel-switch checks remain deferred.
