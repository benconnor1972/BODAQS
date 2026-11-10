# Restricted IMU and ADC servicing candidate

This bench candidate follows the physical r2 ADC setup check. That check saved
16.9%/20.5% in setup/start cost but only about0.7-0.9% in worker-loop time. Further
ADC tuning is deferred. The next question is whether the tested IMU path and two
ADC workers can coexist without sustained sensor loss or unacceptable cached-row
reuse. This is evidence gathering for future admission work, not an admission
policy or a qualified capacity profile.

## Scope and implementation

Environment `bodaqs_s3_mini_n4r2_imu_adc_smoke` sets both the existing single-node
smoke flag and new `BODAQS_SINGLE_NODE_IMU_ADC_SMOKE=1`. Its distinct firmware name
is `bodaqs_a8_imu_adc_bench`; metadata admission mode is
`single_node_adc_smoke_unqualified`. The existing production and IMU-only smoke
environments retain their previous admission behavior.

Remote admission in this image requires requested500Hz, exactly two unmuted
AnalogPot sensors on A8 ain0 and ain4, one channel per ADC, each configured1000SPS
at1MHz SPI. RAW or LINEAR output is allowed, with `include_raw=false`; extra
sensors, duplicate inputs, other channels, transformations and rates are outside
scope. Zero remote IMUs is allowed for an ADC-only control using the same image.
At most one CAN IMU is allowed, retaining the existing configuration
reconciliation, link-profile and allocation-before-PREPARE checks. A rejected
remote scope can still use the existing local-only logging fallback: a file
being created is not proof that the IMU participated. Check the saved admission
report and streams. No measured scheduling costs are installed as qualified.

The ADC conversion commands remain the physically checked r2 full WREG followed
by explicit START in one six-byte CS span, then RDATA after readiness. IMU
transport remains256-byte measurement v2, requested16MHz,25us guard and500us
minimum start spacing with FLOW diagnostics. Keep the tested two-cell master
image and original acquisition node unchanged.

## Saved ADC diagnostics

The v2 final summary adds optional `external_adc_timing` with the same ADC/channel
keys and timing/freshness fields as compact binary. `config_us` includes WREG
and START; `start_us.count=0` means no separate START transaction. Values are
aggregate counters and durations, not per-reading native ADC timestamps.

The row producer stops before finalization. An atomic worker bitset is set before
task creation and release-cleared only after each worker's last statistics write.
Finalization acquire-loads this proof before exposing the statistics pointer.
If the existing100ms stop wait expires with a worker outstanding, the v2 footer
omits ADC totals and sets `external_adc_timing_status=worker_not_retired`.
Otherwise it records `complete`. This status describes diagnostic availability,
not successful acquisition or complete data delivery. Finalization remains
bounded; task creation failure also clears its bit. No allocations or counter
locks are added to each conversion; the bitset changes only at worker lifecycle
boundaries. Existing live preview/v1 diagnostic APIs are unchanged.

## Small physical comparison

Use the new image for both recordings,500Hz and multistream binary throughout:

1. ADC-only control, roughly30seconds: ain0/4 active, IMU muted.
2. Mixed recording, roughly30seconds: unmute exactly one nominal3333Hz IMU;
   retain all ADC/output/format/rate settings. CAN master must be enabled.

Use unique primary field IDs (clear `end` or assign correct distinct tags).
No sensors are connected: retain the current LINEAR settings for comparison, or
choose RAW before both recordings. All-zero scaled values and floating RAW values
cannot qualify analog accuracy, source settling or mux/channel association.
Those tests remain deferred until suitable known inputs are available.

Stop normally and await `[Storage] Log file closed.` Preserve each finalized BDQ
and serial start/STOP/FLOW output. Compare ADC success/timeouts, fresh/reused/
no-sample counts and row-age distributions against the same-image control. Check
primary sequence coverage, effective500Hz cadence, storage errors/queue peaks,
independently decoded IMU axes/sequence/loss, control progress, source terminal
boundary and cleanup/restart. Do not use retryable SPI request drops as a sensor
loss count. Aggregate reuse counters cannot identify which individual rows were
reused. The control has fewer remote queues/streams, so its memory load differs
despite sharing an image and format.

Earlier single-IMU tests retained STOP-time failure/terminal-tail evidence debt;
do not label that complete delivery if it recurs. Stop after a few seconds if
repeated DRDY timeouts return. Do not increase rates, add sensors, force storage
stalls or extend the test matrix before assessing these two files.

## Offline evidence and limits

The host suite runs exact mixed admission/lifecycle rejections before remote
authorization, successful mixed lifecycle and ADC-only control, allocation,
STOP/fence/retry regressions, the real ADC manager against both conversion-trigger
models, delayed-worker diagnostic unavailability and actual v2 ADC footer adapter
serialization with64-bit totals. Existing integrated IMU node-to-BDQ tests remain
in the suite. Hardware SPI/DRDY and ADC demand are simulated in lifecycle tests;
these tests do not establish shared-SPI timing or a physically integrated mixed
recording. Target compilation checks integration only. The external test bundle
records source/artifact hashes, build logs and fresh boundary review.

Controlled storage-stall testing remains deferred to the intended SD card. General
admission development, multiple IMUs, analog accuracy/mux settling and per-reading
ADC timing/freshness representation are not qualified by this candidate.
