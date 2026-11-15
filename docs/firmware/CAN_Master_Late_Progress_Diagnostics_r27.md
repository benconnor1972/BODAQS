# r27: late master observation window

Bench-only continuation of master3ec65905715dbf4d973be1b5f190cecc184a7062.
The sole executable source change moves the existing main-owner diagnostic
warmup from5s to300s. The collection duration remains30s. No new counters,
memory, scheduling decisions, queues, wire changes or public interfaces.
Steady, dispatch and progress snapshots retain their existing shared collection
state and binary layouts. Drain diagnostics still freeze at their first loss.

Keep the installed r26 diagnostic logger d9fc96c8dc0fb7e067d48b5fb1b7d3215bab1951,
all four existing IMU nodes, current SD card and four-IMU ADC-off configuration.
Restart all boards together, wait for normal reconciliation, record approximately
six minutes, then STOP normally and wait for file closure and completed cleanup.
Capture the unchanged seven raw master blocks before another START or reset.
The master window is relative to admission of acquisition, not a wall-clock
button timestamp. Its warmup begins at the existing first active observation.
The exporter must verify frozen state, full30s coverage, exact context and
cross-counter accounting. Normal STOP before330s is not a usable late capture.

The r26 timeline showed four storage-pressure intervals but also declining
sample admissions between them. Compare the late master reply mix, source-loss
replies, sealing rate and receive-to-ACK age against the existing early r26
snapshot. Check the logger timeline for pressure overlapping the late window;
a late snapshot within a stall is a different condition from a quiet interval.
Do not treat repeated loss callbacks as unique readings or snapshot wall-time
costs as CPU utilization. Source sequences and final boundaries still define
delivery. A single late snapshot cannot prove every loss cause.

Predictions: competing traffic changes late reply distribution; slow retirement
raises batch age; a lower offered load changes formation rate without slower
retirement. Reboot/run-state and diagnostic overhead remain possible confounders.
This is an observation round, not a throughput optimization or ADC qualification.
