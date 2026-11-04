# Bounded native IMU loss and recovery (#171)

Software evidence, 5 November 2026. Requirements remain in the
[acquisition contract](CAN-FD_Acquisition_Transport_Contract.md), particularly
Q130–Q134 and Q146. This extends the production path described in
[the native recording implementation](CAN-FD_Native_IMU_Recording_Implementation.md).

## Native association

During recording, FIFO overrun, invalid slot association and capture-queue
faults enter bounded recovery. The node retains already queued frames, flushes
the known partial sample packet, and reserves eight essential frame positions
before attempting recovery. It publishes old-source end/recovery-start evidence,
bypasses the FIFO to discard ambiguous words, observes the running sensor
timestamp, discards ambiguous captures and fences FIFO enable against an edge.
Thirty-three newly validated slots establish the measured rational cadence.
The new source epoch starts at sequence zero, with begin/recovery-complete,
model, matching anchor and snapshot preceding its samples. Sensor and node clock
epochs remain unchanged. Unknown FIFO/hardware capture loss has no invented
count. Known software capture rejects retain their own exact count.

The original recovery deadline is 100 ms; retries do not move it. At most three
attempts are admitted in a rolling second. A successful attempt emits seven
essential frames, or eight when it also reports prior known queue loss. That
report uses the recovery's matching anchor instead of adding another anchor.
Exhausted capacity, epoch IDs, model/evidence IDs or recovery budget exclude the
endpoint. A clock extension blackout remains untrusted after capture discard;
an unexplained sensor timestamp jump is not silently declared a wrap/reset.
Explicit timestamp-reset writes during preparation retain separate clock-reset
evidence and increment only the sensor clock epoch.

## Software queues and evidence

Source sequence and capture ordinal assignment precede software admission.
The node keeps eight CAN queue slots unavailable to sample data, drops newest
complete packets, and records exact source-loss counts/ranges. Its next accepted
packet carries the queue-gap flag. Ordinary periodic snapshots/SYNC observations
may be omitted under pressure while native interpretation metadata remains
protected. Known-loss reports and additional anchors are coalesced to 10 Hz;
normal model/anchor refresh continues independently. STOP flushes pending known
loss before reporting its stopped state.

The master preserves its immutable selected head and all 96 admitted ingress
records. ISR queue rejection is accumulated separately under the hardware IRQ
fence; retention rejection is recorded by the main owner. Loss from those two
observed stages stays separate. No locally generated event is represented as a
CAN reception. Unknown hardware FIFO loss fails closed without claiming an
exact count or affected node.

The approved management ERROR encoding carries these observations: kind 7,
capacity reason 9, field 5/6 for the observed ISR/retention stage, and detail as a
monotonic context/node/referenced-class counter (samples for class 1, evidence
records for class 2). Untrusted-state reason 14 excludes after essential or
unclassifiable loss. Reports echo the poll identity, recur at bounded cadence
so a lost reply cannot erase the final count, and never mutate a selected head.
The logger deduplicates cumulative counters and persists their deltas. These
diagnostics do not identify a source epoch, native tick or CAN receive ordinal;
those companion fields remain absent/zero. Compact reception schema 1, the
16-byte shared SYNC event format, CAN messages, 28-byte samples and 224-byte
companions are unchanged.
The actual retained CAN bytes and reception flags are preserved. The next
sample's source-sequence gap supplies its discontinuity flag; the separate
management observation identifies the known master queue loss.

The logger sample queue similarly drops the newest whole packet when its full
batch will not fit, advances observed source sequence, retains exact counters,
and marks the next admitted sample. Periodic evidence cannot consume the eight
slots reserved for interpretation/loss metadata. Its loss counter degrades
alignment while established native samples remain recordable. Essential
metadata exhaustion fails the endpoint. Sample and evidence queue losses share
one 10 Hz coalescing budget. Final producer quiescence flushes remaining reports;
a terminal essential failure retains the existing conservative tail policy.

Native rows contain their expanded exact values and the serial of their
essential evidence dependency. Model-table retirement cannot change already
expanded rows. Queued rows, the consumer-held head and writer-staged rows retain
their interpretation through complete evidence chunks on storage. Dequeueing
evidence does not acknowledge persistence: the actual writer does so only after
the complete chunk reaches the sink. A torn essential predecessor therefore
cannot expose dependent samples during valid-prefix recovery.

## Validation and limits

The production TI-boundary acquisition fixtures exercise successful post-drain
overrun recovery, the 100 ms deadline, rolling attempt limit, prolonged CAN
backpressure with exact gap accounting, partial packets, all 254 available
recovery epochs followed by safe exhaustion, malformed FIFO words, missing
captures, timestamp progression and cold/warm preparation. Capture tests cover
both wrap orders, exact ring rejects, ordinals assigned before rejection and
irrecoverable clock-extension ambiguity.

The real common master codec tests cover pinned-head preservation, all 96
retention slots, repeated cumulative capacity diagnostics and unknown-count
untrusted-state exclusion. The complete production logger/master/coordinator
fixture carries an observed ISR-stage loss through the pipelined ERROR path
into a companion and verifies deduplication. The stream fixture fills 4,095
old sample rows, rejects the next five-sample packet despite one free slot,
checks the exact count/range and next accepted gap, and retains old native ticks
across more than 32 model revisions. It also checks periodic evidence pressure.
Existing real-writer/independent-reader fixtures cover essential chunk ordering
and a torn essential predecessor; the node-to-master-to-BDQ fixture remains part
of regression validation.

Target compilation and host checks establish software behavior only. Physical
FIFO/DRDY association, interrupt latency, SPI/DMA/CAN service deadlines, actual
recovery timing, SD behavior and resource headroom remain for #175/#176; resource
admission belongs to #173 and comprehensive restart containment to #172. No
device was probed or flashed for this work.
