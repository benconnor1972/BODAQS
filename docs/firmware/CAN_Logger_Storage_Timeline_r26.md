# r26: bounded whole-run storage and acquisition timeline

Diagnostic-only continuation of r25 (9f9c903a), keeping ordinary-fetch20, P3
storage priority, acquisition priority2,512-byte/16MHz SPI,1200us pacing, same
four IMUs, ADC-off config and retained r24 master3ec65905. No buffer, queue,
priority, core-placement, batching or wire behavior change is selected.

The r25 sustained run delivered94.573%, with148 >100ms storage operations,
all sample queues full and35716 consumer waits. Its first-loss recorder froze
near startup and master steady counters cover only30seconds. Thus neither
captures the later deterioration. The physical feedback loop remains a normal
10-minute recording, finalized BDQ/serial/config plus the unchanged master
export. This diagnostic does not inject stalls or claim a host reproduction of
the physical loss. Deterministic tests instead prove late-event coverage,
ownership, timing attribution and preservation of existing storage behavior.

## Predictions

1. If repeated SD writes constrain service, bins with more physical-write wall
   time/slow calls should coincide with growing primary/sample peaks and waits.
2. If serialization or other storage work dominates, non-I/O storage-service
   wall time rises without a matching rise in nested File.write/flush time.
3. If acquisition scheduling stalls independently, acquisition gaps/queues rise
   without corresponding storage activity. Coarse temporal overlap distinguishes
   candidates; it does not prove causality or locate every missing reading.

## Capture and owners

New default-off BODAQS_STORAGE_TIMELINE=1 requires pressure and FLOW diagnostics.
Selected environment bodaqs_s3_mini_n4r2_imu_storage_timeline extends exact r25.
Two fixed owner banks,36 x20seconds each, cover12minutes. Reserved RAM is charged
through sizeof via the existing diagnostic reservation; static assertion limits
additional state to6000bytes. There are no new live logs, allocations, locks,
queue ownership changes or sampling clock reads. Storage service adds one ending
clock observation; acquisition reuses existing pressure/consumer observations.

Storage resets only its bank before opening a session and release-publishes one
atomic32-bit logger clock origin. Acquisition initializes its bank before owner
publication and acquire-loads that origin once. Each writes only its own bank;
neither reads the other's live arrays. Normal recording lifecycle must retire
both prior owners before another reset. Footer serialization uses the existing
matching completed FLOW/RemoteImuRecording retirement barrier. It never borrows
acquisition counters on an unavailable/mismatched recording. Storage freezes its
own timeline before serializing the summary, excluding that summary's own I/O.

All new observations continue after the old first-loss capture freezes. They
never feed scheduling, credits, ACK, authorization, source identity or integrity.
Producer/consumer count methods retain their existing queue synchronization.
Existing default environments, footer fields and public function signatures stay
unchanged. This adds optional `recording_timeline` JSON to BDQ v2 final summary;
older readers may ignore it. No live data/wire/file-version change.

## Fields and interpretation

Header: version1,available, exact64-bit context,origin_us,bin_us20000000,
capacity36, owner used-bin counts, last elapsed ticks, owner overflow-event
counts and scope string. Bins are consecutive indices0..max(used)-1. Tick
differences use unsigned32-bit microseconds; intended runs are shorter than one
wrap. Reaching capacity latches overflow, stops array updates (never overwrites
old bins), and reports omitted events until a new session reset. Expected trial
duration is10minutes plus normal startup/cleanup, under12minutes.

Storage fields: writes,attempted bytes,write_us,write_max_us,slow_writes (>=100ms),
flushes,flush_us,flush_max_us,regular service_calls/service_us/non_io_service_us,
service_max_us,primary_peak,service_gap_max_us and service_time_invalid. The latter
flags nested I/O exceeding its enclosing span, rather than pretending that is
valid zero non-I/O work. Actual BdqV2FileSink callbacks time File.write/flush. The real storageService_ BDQ branch measures its existing
regular drain/flush work; non_io_service_us subtracts nested sink wall time from
that service span. Startup and final drain/flush physical I/O are counted but are
outside regular service spans. Service gaps are end-of-prior-service to next
start. Whole operations are assigned to their start bin; long operations are
not split, so summed time need not equal bin utilization. All time is wall time,
including preemption/blocking, never asserted to be CPU-only formatting cost.

Acquisition fields: services,maximum start-to-start service gap,gaps_over_10ms,
sample/evidence consumer calls and waits,per-node sampled queue peaks and source/
evidence loss-report counts. Service gaps belong to the completion/end bin;
consumer/loss observations to their observation bin. Loss-report counts are
callback observations, potentially repeated while admission is blocked; they are
not distinct notifications or unique lost readings. Sample custody is not SD durability;
queue peaks are sampled, not proof of every occupancy transition. Detailed
sample loss still comes from source START/STOP and sequence gaps in the BDQ.

## Validation and trial

`test_storage_timeline_runtime.py` compiles the real SD observer and actual BDQ
storage pump branch. It checks a slow operation at350seconds after first-loss
freeze, exact nested-I/O subtraction, queue/loss counters, retired/mismatched
footer guards,64-bit context, JSON values, wrap/restart, overflow and concurrent
owners. Existing pressure/sink tests protect the legacy path. The selected
four-node integration compiles the real coordinator/consumer/retirement paths
with timeline and ordinary-fetch20 enabled, retains its loss/ACK/proof/CRC/STOP/
storage-failure tests, and checks independent final BDQ timeline decoding.

Run default host tests, selected integrated tests and the target build. A fresh
boundary review must inspect cross-owner publication/reset/retirement and the
source-to-JSON/decoder units before packaging. Target memory/flattened recipe
audit must show the only added feature flag is timeline1. Instrumentation is
bounded, not free; reject physical conclusions if it materially perturbs r25.

Flash logger only under existing authorization, no full flash backup. Keep the
r24 master/nodes/card/config. Restart all boards, record about10minutes and STOP
normally. Save finalized BDQ, full serial.txt (precreated), loggercfg.txt and the
unchanged seven-block master export in a fresh results directory. Compare
source-bounded delivery and integrity with r25; inspect the timeline before
choosing a storage/buffering/scheduling remedy. No controlled artificial stalls
or ADC load are introduced.
