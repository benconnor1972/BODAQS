# Four-IMU v4 capacity probe (r9)

## Purpose and scope

Run all four configured IMUs for about60seconds, with local ADCs muted, to test
the next capacity step. The r8 reference delivered every one of376242source
readings from two IMUs in about59seconds. That establishes a working point,
not twice the headroom. Preserve its pressure diagnostics to distinguish master
ingress pressure, logger buffering and storage service if the larger load loses
data. Longer two-node confirmation is superseded by this capacity probe.

**Leave ingress queues at128receptions per node.** No queue enlargement or RAM
bank relocation is part of this round. No master/node firmware, wire protocol,
bus speed,600us start spacing,5us CS setup, RX2 setting, storage priority,
custody/checksum rule, or IRQ behavior changes. Controlled physical storage-stall
testing remains deferred. Flashing is manual; preparation accesses no devices.

## Bench admission extension

Add a separate logger environment, `bodaqs_s3_mini_n4r2_imu_window_four_node`,
extending the r8 pressure environment with `BODAQS_V4_FOUR_NODE_BENCH=1`.
This opt-in requires v4 and the existing compact sample-unit bench. Its accepted
cases are1,2or4CAN IMUs,500Hz primary, no active ADC or unrelated sensor.
Three nodes and invalid build-flag combinations remain rejected. Retaining the
one/two-source cases permits a reference run on the same image if later needed.
The r8 environment retains its original one/two-source limit; production admission
and qualification are unchanged. Report the explicit mode
`sample_unit_four_node_unqualified` and accurate scope text in diagnostics.

The existing transport, coordinator, master windows and diagnostics already have
four source positions. Reuse them. Each logger source retains its existing
256sample-unit records of260bytes and512evidence records of224bytes. Four sets
require724992bytes for those queue payloads, plus existing definitions, queue
metadata and storage allocations; those buffers prefer PSRAM. Target compilation
alone does not establish successful physical allocation. A failure must roll back
partial allocation before any remote authorization, preserving the existing
lifecycle. No larger per-source queue is authorized.

The acquisition task's stack and all static four-source transport slots already
exist. Recheck target static memory and the exact unchanged43928byte transport
allocation. Keep the existing master image and its documented BANK0/BANK1 and
stack reservations. Runtime stack watermarks remain unqualified.

## Configuration and evidence

Derive the supplied configuration from the exact r8 file by unmuting only
sensor6/provider`can:2` and sensor7/provider`can:3`. Existing sensor IDs,
profiles, node addresses, connection settings, all ADC mute flags,500Hz primary
and multistream BDQ remain unchanged. Provide the original two-source config
as a reference. Keep private config contents local.

All four nodes must use the previously supplied corrected acquisition firmware
and their distinct saved addresses0..3. The image itself is unchanged; retain
an exact reference for manual use if any node has not yet received that correction.
The agent does not probe, flash or reset any device.

The physical round must show `streams=9 primaryColumns=0` (primary plus four
sample/evidence pairs). Stop and preserve a separate attempt if membership is
different. Record about60seconds on the same card, request normal STOP and wait
for file closure/cleanup. Save finalized BDQ, full serial, exported config and
matching post-cleanup CCS snapshot in a fresh four-source results directory.
The pinned assessor must require exactly nodes0..3 and nine streams, validate the
new recipe/config hashes, retain `PRESSURE.json`, and reject incomplete membership
as a capacity result. Losses and unknown source bounds remain explicit; no missing
or corrupted readings are invented or silently repaired.

Interpret a brief queue rise followed by recovery differently from persistent
growth/full queues. Only strong evidence for a finite interruption supports
subsequent ingress expansion; sustained overload requires drain/storage work.
The prior44.5seconds in write calls per59seconds of recording warns of storage
pressure at twice the sensor load, but includes scheduling and is not a pure
SD-card benchmark. This round establishes neither mixed-ADC admission nor a
production four-IMU qualification.

## Offline acceptance

- Public admission tests prove the new bounded scope, legacy rejection,
  unqualified status, ADC/other-sensor exclusions and invalid flag rejection.
- The complete v4 recording fixture operates four real coordinator/control/master
  sources with distinct known axes, not a relabelled two-source result. Both
  ordinary and delayed-reply cases independently decode64readings per source,
  each with terminal sequence63, correct axes and no gaps/duplicates/ambiguity.
- Existing data/ACK/proof loss and origin-CRC repair injections remain. Under
  host-injected storage blockage, compare each decoded source against the
  independent CAN input-admission ledger, including explicit known rejections.
  Preserve renewal/STOP progress, partial final units, short-write behavior,
  cancellation and stale-authorization rejection across a new recording.
- Exercise partial four-source allocation failure and complete rollback before
  remote authorization. Retain all four queues in the pressure footer and
  validate membership rejection in the offline assessor.
- Build the selected logger, run the full offline suite and fresh independent
  Standards/Spec plus lifecycle/capacity review before sealing. Pin source,
  recipe, unchanged master/node references, config changes and artifact hashes.
  Host scheduling/filesystem injection is not physical throughput evidence.
