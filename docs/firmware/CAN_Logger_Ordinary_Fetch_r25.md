# r25: reclaim ordinary control fetch targets

Continue the four-IMU, ADC-off r24 capture with its exact master
3ec65905715dbf4d973be1b5f190cecc184a7062, including hardware CRC and progress
diagnostics. Change only the logger's ordinary result-fetch policy. Retain P3
storage priority, acquisition priority2, 1200us start spacing,512-byte/16MHz SPI,
5us CS setup,25us rearm guard, nodes/configuration, queues and CRC/identity checks.

The r24 full30s window contains21953 valid requests:4269 empty non-sample replies
(3002 ordinary,588 protected,679 master evidence), each while sample units were
published. Sample fetches never returned empty;97.22% of units were full. This
supports investigating fetch selection, not assuming a19% gain or relaxing
integrity. Storage pressure is intermittent and remains a comparison confound.

## Bounded opt-in behavior

`BODAQS_ORDINARY_FETCH_INTERVAL_MS` defaults0; selected trial value20. Nonzero
requires window transport and existing idle-control reclamation; values outside
0..20 fail compilation. Existing environments stay unchanged.

For ordinary class3 during acquisition data service:

- A result ACK alone does not force another class3 fetch. The existing transport
  ACK priority still transmits/retries it, with its exact identity and proof.
  Its independent fetch half can request samples and advertise existing credits.
- A pending ordinary command with no known partial/unaccepted result is eligible
  for discovery when it has never been polled or20ms have elapsed since its last
  attempted wire fetch. Spare selector turns seek other real control work, then
  existing fair data selection. No physical drain exchange is removed.
- Known partial/unaccepted control results and queued outgoing commands bypass
  the pacing. Protected class4, STOP and authorization renewal keep their current
  priorities and timing. Master evidence and ordinary CAN request budgets remain
  unchanged. No delay, sleep, wire field or new IRQ mechanism is added.
- When no data fetch is eligible, retain the original control/drain opportunity.
  Thus20ms is a reclamation interval, not a hard ban on class3 traffic. Actual
  service also depends on worker/SPI scheduling; it is not a guaranteed latency.

The acquisition task owns four u32 last-attempt millisecond timestamps and one
validity bitmap in MeasurementTransport (17bytes plus target alignment, charged
by sizeof(transport)). Selection
reads them; CanMasterManager updates only actual kind1/14 ordinary fetch targets
before exchange. Outgoing fragments and sample fetches do not consume the budget.
A newly queued ordinary command clears its own validity bit after successful
seal; identical idempotent requeue returns without clearing. Transport reset at a
new recording/fence clears all timers. Existing modular unsigned elapsed-time
arithmetic handles wrap; the valid mask distinguishes never-polled from tick0.
These fields are scheduling hints, never readiness, receipt or retirement proof.
No public function signature, saved configuration, file format or wire change.

## Feedback loop and validation

The new real512-byte acquisition/transport/master test failed on the old code:
an ordinary ACK forced another control fetch, and a repeated not-ready result
poll failed to yield to samples. Those are reproduced selector symptoms, not a
host reproduction of the physical throughput limit. Command:
`python firmware/tools/test_ordinary_fetch_runtime.py --compiler g++`.

The harness uses actual wire encoding/decoding, full master retirement proof and
the production acquisition selector. It checks ACK retargeting, lost ACK retry,
pending poll interval/exact due time, wrap, independent node fairness, immediate
new command, partial/unaccepted-result priority, protected service and no-data
fallback. Peripheral/time substitution cannot establish physical timing.

Run existing default logger tests plus selected512 integrated acquisition with
`--ordinary-fetch-ms 20 --idle-control-fetch --bulk-bytes 512`. The latter includes real node capture,
four-source acquisition, lost data/ACK/proof, damaged origin-CRC unit, selective
recovery, lag, normal STOP, cancellation, failed writes, allocation and shared
metadata failures. Require fresh review of ACK ownership, finite identity scope
and timer reset before packaging. Build selected environment
`bodaqs_s3_mini_n4r2_imu_ordinary_fetch20`, audit its flattened recipe against
r14P3 flags (only new interval flag), and retain the exact prior logger image.

## Physical trial

Logger-only install under existing authorization, no full flash backup. Keep the
r24 master installed; do not rebuild/flash it using this logger source. Restart
all boards and repeat approximately60seconds with normal STOP/file close. Save
finalized BDQ, serial.txt (precreated empty), loggercfg.txt and the unchanged r24
seven-block master export into the new trial folder.

Compare delivery/readings per logger observation second, target-class/reply-kind
matrix, sample replies, ACK ages, all-source STOP/identities, duplicates/integrity,
control exclusions and storage/queue pressure against r24 (10459/s,80.227%) and
r23 clean-storage reference (10591/s,82.445%). Success requires useful delivery
gain with control/retirement intact, not just fewer polls or faster individual
requests. If storage fills more often, separate the pressure evidence from the
scheduling comparison. No controlled storage-stall injection is introduced.
