# Logger useful-drain flow diagnostic

ACK_FETCH optimization fde7afe reduced measured dispatch from245.52us to141.54us,
and outer request cost by12.5%, but early sample drain hardly increased and the
new capture still lost22.6% over the same first98904 source positions. Keep that
master and the existing node while observing the logger flow.

## What the existing software evidence establishes

The production transport/master mixed-source host fixture, with immediate RAM
admission, handles the configured667 sample CAN records/s plus40 evidence records/s
at two service opportunities/ms and fixed response lags1..8 slots without ingress
loss. High-water ranges21..46 of128. The fixture omits target instruction costs,
native evidence cadence details, ISR losses, real task timing and SD. It therefore
does not reproduce or disprove the physical failure. The earlier naive removal of
idle control exchanges made host backlog worse because exchanges clock replies.
Neither observation justifies a speculative scheduling change.

## Selected diagnostic image

Only environment bodaqs_s3_mini_n4r2_imu_flow defines BODAQS_IMU_FLOW_DIAGNOSTICS=1.
It inherits the500us exchange-start limiter,25us inter-CS guard and all smoke/v2
settings. Other environments compile without the diagnostic state or hooks.
No request selection, retry rules, CRC, retirement matching, buffers, rates,
file schemas or hardware configuration change. The master remains the optimized
version3 image, and the node remains the original acquisition image.

The acquisition owner records aggregate transport and downstream-admission data.
It retains a snapshot on the first reason9, class1 source-loss management report,
then a final snapshot before releasing measurement ownership. No hot-path logging
occurs. The main logger prints the immutable snapshots with the FLOW tag only
after acquiring inactive ownership during normal recording release, after file
finalization. The context is printed to bind the observations to the BDQ.

## Counters and interpretation

Services count acquisition-owner service calls. Request counters cover attempts
inside serviceMeasurementTransport, excluding administrative mode-entry/inspection
bursts and its separate recovery-query branch. Polls and ACK_FETCH fetch targets
are counted by class. Deferred counters identify head probes suppressed by the
existing20ms limiter. These are not interchangeable with full-session master
requests or the previous DRAIN snapshot, which has another scope.

Validated received fragments count as new or replayed per current identity/mask;
old accepted-object replay is replay, not new data. Invalid fragments are excluded.
Admitted counts mark the first RAM acceptance of each complete retained object.
They do not mean SD durability. A matched retirement proof ends that object's
wait; retries do not reset it, and wrong/stale proof does not end another wait.
The wait runs from the first ACK_FETCH call attempt to validated proof reception,
including pacing, mutex wait, pipeline and task delays. It is not a physical CS
latency measurement. Total wait uses64-bit accumulation. Counts/maxima for waits
still pending at snapshot prevent silently excluding an indefinitely delayed proof.
Unsigned subtraction handles a micros wrap while each bounded request is pending.

Consumer calls/waits cover the actual RemoteImuRecording callback. A false result
can be a closed admission gate or a blocked native queue; gate_wait is counted
separately. Sample/evidence queue sizes are sampled through atomic SPSC indices
after callbacks, with fixed capacities. The compact sample capacity2048 is CAN
packets, not individual six-axis readings; evidence capacity is512 records.
Peaks are sampled values, not exact continuous high-water. Concurrent consumer
pops can reduce a sampled peak. Invalid accepted-as-error callbacks are not
classified as queue stalls. Optional evidence may be shed before the queue is
full; low occupancy does not prove zero evidence loss.

The first-loss snapshot includes startup and runs until the logger observes the
master loss report; it is later than the exact master first-overflow time. Its
nonzero counter is management evidence, not independently reconstructed loss.
The final snapshot includes STOP/tail/fence/exit. Gate waits late in cleanup must
not be mistaken for the initial overload cause. If no source loss is observed,
only the final snapshot prints. Persistent cleanup blockage can prevent final
printing; existing Wi-Fi-toggle fence diagnostics remain applicable.

## Ownership and lifetime

Diagnostic state is acquisition-owner-written. Reset occurs after successful
control claim and before publishing owned=true. Final capture precedes control
release and the locked owned=false publication, on both normal exit and unavailable
cleanup. The main thread reads only after stopped() has acquired inactive owner
state; producer callback gate ownership is unchanged. Queue accessors read atomic
indices; allocation/capacity changes remain outside acquisition ownership.
Main-thread stream.finish does not mutate these owner-only counters. Reserved
diagnostic storage is included in AcquisitionControl::reservedBytes.
Printing also requires the snapshot's context to match the current allocation.
A recording canceled before resourcesReady cannot print a previous recording's
observations, even though no new diagnostic owner reset has occurred.

Only concise bounded lines are emitted, respecting the existing256-byte log
formatting buffer. The hooks add counters, sampled atomic reads and a few clock
reads, so timing may shift slightly. Physical overhead and the failure cause
remain unqualified. No firmware scheduling fix is claimed.

## Validation and next observation

Host lifecycle tests run with diagnostics enabled and unchanged pacing. A full
2048-packet consumer queue produces waits and the correct queue peak. A real
master management-loss report traverses the production wire/consumer and freezes
the first-loss snapshot; cleanup still retains and fences unaccepted data.
Existing delayed-fence and lost-exit cases remain. A focused deterministic check
tests correlated proof/retry timing across wrap, pending waits, first-loss/final
immutability and a new scope reset. Integrated real node-to-BDQ/independent decode
and cancellation tests also run with diagnostics enabled. Target build, full host
suite and fresh ownership review accompany the logger-only bundle.

Record one approximately30second run and save the completed BDQ plus serial
output through all FLOW lines. No new CCS array capture is required. At first
loss, full queues/consumer waits support downstream backpressure; low queues with
few waits but substantial proof delays/replay support a transport/polling stall.
Both may coexist. Make the next change only after distinguishing them.
