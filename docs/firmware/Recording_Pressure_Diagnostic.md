# Recording pressure diagnostic (r8)

## Question and unchanged reference

The r7 two-IMU recording retained 97.7% of source readings, with six bursty gaps
per source attributed to master ingress loss. The first master input overflow
occurred about34.4seconds after acquisition began. The logger's footer retained
SD duration totals and its sixteen longest operations, but no operation times
or per-source queue state. Those observations cannot distinguish logger/storage
backpressure from an independent master-service limit.

Prepare a **logger-only diagnostic**, based on5895fff9, using
`bodaqs_s3_mini_n4r2_imu_window_pressure`. Keep the r7 master, nodes, card,
configuration and wiring unchanged: two enabled IMUs, local ADCs muted,500Hz
primary rows, v4 windows,16MHz256-byte SPI,600us start spacing,5us CS setup,
RX2 master and storage task priority2. No IRQ or artificial storage stall is
introduced. This is observation, not a throughput optimization.

## Acceptance and observations

Add an opt-in `recording_pressure` object to the existing BDQ final summary.
The surrounding file, sensor records, checksums and custody protocol stay
unchanged. All serialization/allocation occurs during finalization, not in
acquisition callbacks or SD operations.

- At the first observed nonzero master sample/evidence loss diagnostic, retain
  node, class, reason, stage, counter and logger observation tick. Refresh both
  participating logger queues then freeze their depths, sampled peaks,
  capacities, accepted counts, blocked-consumer count and first/latest blocked
  ticks. Include gate/bridge/management waits and request/service totals.
- Retain the last96physical SD writes/File.flush operations in chronological
  order, with exact start tick, duration, attempted bytes and primary queue
  depth sampled **after** completion. Stop retaining after the first operation
  completing at least2seconds after the loss observation; include that crossing
  operation. If no loss is observed, retain the final rolling history.
- Retain the last32acquisition-service gaps of at least10ms, using start-to-start
  service-call intervals, with the same2second post-loss cutoff. A gap includes
  the preceding service work and scheduler delay; it is not a pure CPU metric.
- Export explicit capacities, overwritten counts and frozen flags. History is
  bounded:96operations do not guarantee a fixed number of seconds. Inspect its
  actual oldest timestamp before asserting that a pre-loss interval is covered.
- Export `available=false` if the producer has not retired in the matching
  recording context. Do not read live acquisition arrays during finalization.
  A clean loss-free run has `available=true, first_loss_observed=false`.

Times are logger monotonic microseconds modulo2^32, matching the stored raw
logger observation ticks. Use modulo differences within a run; keep this
diagnostic run below2^31us (about35minutes). The loss observation arrives after
the original overflow, and a full evidence queue can delay it further. A queue
peak alone has no timestamp. Consumer-wait counters and their first/latest ticks
cover the recording prefix, not exclusively the instant of first loss.

FLOW is enabled to supply its existing retirement barrier, per-node accepted
counts and first/final snapshots. Its legacy per-class ACK-wait serial counters
track only one outstanding object per node; **do not use them as a complete v4
window latency distribution**. This diagnostic uses the structured pressure
footer and queue/blocked-consumer fields instead.

## Ownership and interface

`RecordingPressureDiagnostics.h` owns two small fixed histories. Acquisition
alone writes service gaps and first-loss metadata. Storage alone writes SD
history. The sole live cross-owner message is a release/acquire atomic loss
trigger with its tick. Storage resets the trigger before a new file starts;
acquisition resets its own state before ownership publication. Existing recording
exclusion requires the preceding producer and storage finalization to finish
before restart. Footer reads acquire the existing inactive/matching-context
barrier; they never copy another owner's live history.

The internal `BdqV2FileSinkObserver` callback gains `startedUs` before duration;
its sole production consumer is updated. Capturing this timestamp at the actual
file boundary avoids misdating a write if the observer is scheduled later.
Scheduling, queue capacity, admission and ACK/CRC rules do not change. Added
instrumentation has bounded cost, but its physical timing overhead remains
unqualified and must be considered if the loss pattern changes markedly.

## Validation and interpretation

Host checks exercise the actual file-sink timing callback and production footer
adapter, wraparound, restart, history order/overwrite, a write crossing the loss
tick/cutoff, an operation completing just before a concurrent trigger, frozen
history, and unavailable-before-retirement output. Integrated v4 recording tests
exercise the real loss callback, both logger queues, producer retirement,
loss-free output, STOP, delayed replies and a host-injected buffer/I/O schedule;
the resulting BDQs retain their independent reading/CRC checks. Host pressure
injection is not the deferred physical storage-stall campaign.

Run the selected logger target build, complete offline host suite, and fresh
Standards/Spec plus ownership-boundary review before sealing the manual-flash
package. No devices are accessed during preparation.

For the physical round, record about60seconds and retain finalized BDQ, full
serial, unchanged configuration export and matching CCS snapshots. Check five
streams and both source STOP boundaries first. Then align first-loss observation,
SD intervals, consumer waits and service gaps. Full logger queues/consumer waits
preceding overflow support downstream pressure; low queues with no blocked
consumers weaken that explanation. A long service gap overlapping SD I/O suggests
scheduling interference. Coincidence alone proves neither causality nor an SD
card defect. If history does not cover the relevant interval, report that limit
instead of treating absent events as evidence.
