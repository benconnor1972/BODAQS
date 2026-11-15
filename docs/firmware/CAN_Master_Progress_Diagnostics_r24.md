# r24: distinguish empty replies, batch formation and retirement

Diagnostic-only continuation of r23 hardware CRC (322e7159), four IMUs, ADC off.
Keep the exact r14 P3 logger at 1200us/512 bytes/16MHz, nodes and configuration.
No scheduling, credit, packet identity, CRC, retention or physical SPI ownership
change is intended. No IRQ protocol or queue enlargement. The compile-time
`BODAQS_MASTER_PROGRESS_DIAGNOSTICS` flag defaults to zero and requires window
transport plus phase timing when enabled.

The physical feedback loop is the existing roughly 60-second four-IMU recording,
normal STOP/finalized BDQ plus read-only raw master export. Existing low-pressure
r17/r23 runs plateau around 10.3-10.6k retained readings/s, with explicit loss.
No host test or synthetic counter proves the cause of that physical plateau.
The new deterministic host feedback loop exercises the real encoded service:
`python firmware/tools/test_master_progress_runtime.py --compiler g++`. It asserts
independent expected reasons for held/zero/outside credit, partial formation,
window pinning, first/repeat preparation, exact ACK retirement and frozen counts;
enabled/disabled outputs and terminal service/window state must be identical.
Adapter tests exercise the production steady scope and drain synchronization.

## Falsifiable questions

1. If non-sample lanes consume empty replies while sample units are published,
   the target-class/reply-kind matrix and empty-with-published count show it.
   This is opportunity evidence, not permission to change STOP service or assume
   every published sample is credit-eligible for that request.
2. If a delayed ACK/credit pipeline prevents progress, empty sample fetches show
   units already marked held, units outside advertised credit or zero credit,
   and/or the oldest unretired unit pinning allocation with queued ingress.
3. If filling/deadlines limit publication, empty sample fetches show partial units,
   and seal payload-count/reason/age counters quantify incomplete batches.
4. If samples are simply not available at those instants, empty fetches show no
   complete, partial or queued sample work. That is an observation, not a claim
   about upstream CAN utilization or all times between requests.

## Snapshot contract

`gMasterProgressInfo` is main-owner debugger-only BANK1 storage. No ISR writes,
DMA aliases, interrupt masking, allocation or new clock reads. Its 1184-byte
little-endian ABI is statically asserted: four u32 (version=1, size, state,
reserved=0); two u64 (context, recording); 8x16 u32 replies; 8 u32 empty replies
with any published samples; four 152-byte node records. States mirror steady
0 idle /1 warmup /2 collecting /3 frozen. It resets with each new steady scope;
STOP, clock failure and identity changes freeze exactly as the existing steady
capture does. The exporter must compare context, recording, state and complete
steady counts, preserving full-width identities in raw binaries.

Request target rows: idle, sample, evidence, control, protected, master evidence,
ACK only, other. Kind14 uses its fetch target; kind15 is sample; kind1 uses poll
class. The column is actual reply kind 0..15, not a guessed loss category.
This matrix is recorded for the same successfully processed requests as steady.
Instrumentation is bounded but nonzero overhead; compare useful throughput and
verify the matrix sum against the steady request count rather than ignoring it.

Per-node record consists of u32 fields, in order:

- sealed_payloads[16] (index is count of CAN sample payloads, not readings)
- seal_reasons[3] (full, boundary with queued next reception, age deadline)
- seal_age_total_ms, seal_age_max_ms (oldest included reception to seal)
- retired, receive_to_ack_total_ms, receive_to_ack_max_ms
- prepared_acked, first_prepare_to_ack_total_ms, first_prepare_to_ack_max_ms
- first_preparations, repeat_preparations
- empty_states[9]

The empty states are **overlapping**, per node, only on empty kind14-sample or
kind15 fetch replies, read after the production selection attempt: credit zero,
failed source, complete eligible unit, complete held unit, complete outside-credit
unit, partial unit, queued ingress, oldest unit pins allocation, no sample work.
Eligibility here means complete/in-credit/not-held; source failure is a separate
flag. Present bits and base are those in that request, not current logger state.
An empty eligible observation without a failed-source flag deserves code review.
Do not add these counters as exclusive partitions or infer duration from their
frequency. Non-sample empty counts only observe raw complete sample objects.

Seal/preparation/retirement counters capture events within the window, so their
populations can differ at the boundaries. A pre-window object may retire inside
the window. Age arithmetic is modulo u32 milliseconds; sums are u32 diagnostics
for short trials and must not be extrapolated across a clock wrap. Preparation
is not physical delivery and a valid RAM ACK is not SD durability. Duplicate
ACKs must not increment retirement twice. No diagnostic feeds authority state.

## Acceptance

Keep r23 behavior. Compile/tests prove counter semantics and wire/state
equivalence, not physical non-interference. Target build/map verifies BANK1 and
exact ABI; fresh boundary review checks main-only ownership, counter scope,
raw decoding and the enabled production call sites. Trial acceptance requires
matching kit/config, all four source identities/bounds, integrity and cleanup,
plus consistent raw counts. Higher request rate without more retained readings
is not an improvement. If diagnostics materially depress the baseline, classify
their overhead before using them to select a scheduling change.
