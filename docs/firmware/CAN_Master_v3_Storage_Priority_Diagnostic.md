# v3 storage-service diagnostic

The second physical v3 recording used the same SD card and logger configuration
as the first. The corrected node retained the final partial packet and source
boundary, but 47,463 of 113,938 IMU readings were missing (41.6569%). Primary
storage reached 4096/4096 rows and dropped 4,934 rows. Its physical write calls
averaged 270.6 ms, versus 130.8 ms in the preceding run. These are elapsed times
around `file_.write`, not card-only or CPU execution times.

## Smallest useful intervention

The v3 reference environment inherits the production storage-task default,
priority 1. The earlier v2 bench profiles explicitly selected priority 2.
Storage runs on core 1, alongside the main Arduino loop; priority 1 provides
less protection against runnable work on that core. This configuration difference
predates both v3 recordings and cannot alone explain their variation. It is a
plausible amplifier of blocking-write latency, not an established root cause.

The explicit `bodaqs_s3_mini_n4r2_imu_units_storage_priority` environment inherits
the v3 reference flags and adds only `BODAQS_STORAGE_TASK_PRIORITY=2`. The reference
environment and production defaults remain unchanged. No task is moved between
cores. ADC configuration, driver, SPI pacing, packet processing, SD buffer sizes,
record formats, CRC/identity checks and task stack sizes remain unchanged.
The build-recipe identity distinguishes the diagnostic, despite the shared
firmware name. Master and corrected node images remain the installed r2 peers.

## Physical feedback loop

Use the same card, one-IMU ADC-off config and approximately 30-second recording
with normal STOP. Preserve finalized BDQ, complete serial, actual config and
stopped-master diagnostics if available. Compare to the fixed-node r2 attempt 2:

- Mean/max elapsed physical-write time, primary queue peak and dropped rows.
- Source-bounded IMU loss and evidence loss, retaining the final source boundary.
- No new corrupt units, unresolved identity, cleanup failure or sample-tail loss.

If scheduling dominates, increased priority should materially reduce elapsed
write time and queue pressure. If card/driver waits dominate, write time should
remain high. If writes improve but the queue still fills, inspect storage drain
service separately. A single improvement cannot prove scheduling was the cause:
same-card latency may vary. A return to the exact priority-1 reference is the
next discriminating check only if the first comparison is materially different.
No formatting, card replacement, artificial stall injection or broad workload
matrix is required. Controlled storage-stall testing remains deferred.

## Validation limits

Audit PlatformIO's resolved build options and build recipe: flags differ only
by the storage-priority define; all firmware source inputs match the reference
recipe. Compile the selected logger target and preserve the installed peers and
configuration hashes. Existing logic suites passed on the unchanged firmware
sources in r2; repeating them cannot validate this scheduler setting. Physical
testing is the acceptance seam. This diagnostic does not claim measured task CPU
time, isolate every source of blocking latency, or qualify aggregate throughput.
