# SPI transaction revision after the T01 no-go

Status: confirmed by the user, 6 November 2026. Q24-Q31 decisions and the
consolidated prototype/validation approach are accepted for implementation.
No probe firmware, new measurement profile or revised capacity pass is produced
by this document. Existing production contracts have not silently changed.

## Problem Statement

The initial capacity gate cannot justify the four-IMU design at the observed
64-byte/8 MHz exchange cost. Its sample-only 1.25x catch-up calculation already
charges 982.152 ms/s against an 850 ms/s scheduling limit. This is a measured-cost
scenario, not proof that every new geometry on the hardware is impossible.

The fixed 64-byte transactions and initial 100 us uninterrupted ownership limit
prevented comparing larger useful payloads. The 100 us limit was a conservative
design requirement, not a measured ADC deadline. Applying the old 147.3376 us mean
to larger transactions or a faster clock would not establish their costs.

## Solution

Compare larger physical transactions and a higher qualified clock before adding
multiple outstanding batches. Retain roughly 1 KiB logical batches and one
immutable selected batch per node initially. Replace the blanket 100 us ownership
limit with a bounded maximum blocking interval justified by supported ADC workloads.

First produce a small, isolated measurement prototype, establish useful transport
and ADC performance, then rerun T01 for the revised envelope. A prototype with
known data is allowed before the remaining production implementation; it does
not waive the no-go or qualify the production recording path.

## User Stories

1. As a user, I want four nominal 3.33 kHz IMUs to fit a defensible service budget
   so the recording does not rely on queue overflow or exclusion.
2. As a user, I want two analog channels logged at 500 Hz to contain fresh
   conversion results during qualified normal operation, rather than cached repeats.
3. As a user, I want supported mixed workloads admitted explicitly so a faster
   remote link cannot silently reduce analog capability.
4. As a maintainer, I want transaction length and clock compared together so
   fixed per-transaction work is amortized instead of assumed away.
5. As a maintainer, I want useful accepted/retired data measured so busy polling
   does not masquerade as drain capacity.
6. As a user, I want one profile selected before a recording so a fallback cannot
   silently invalidate the workload budget during acquisition.
7. As an analyst, I want fresh conversions distinguished from equal-valued cached
   readings so numerical equality cannot hide or falsely imply stale data.
8. As a maintainer, I want known-data tests with exact artifact identity so
   electrical/adapter failures can be separated from the full recording stack.
9. As a user, I want an honest no-go when a candidate fails, without automatic
   rate reduction or an unsupported physical-qualification claim.
10. As a maintainer, I want the original T01 report preserved so revised results
    remain traceable to changed geometry, measured costs and explicit assumptions.

## Implementation Decisions

### Candidate envelope

- Existing boards, wiring and shared SPI remain in scope. Retain the four-IMU
  goal, honest timing/data-quality rules and existing capacity margins.
- Evaluate 16 MHz as the preferred clock candidate, with 8 MHz as comparison and
  fallback. Use a lower intermediate candidate if required for timing margin.
  Requested clock, actual divider-produced SCK and duty cycle must be distinguished.
- Compare 128- and 256-byte transactions. Prefer 256 bytes only if useful service
  and ADC acceptance pass; larger frames are not automatically better.
- Retain a 64-byte/8 MHz comparison and initially a 25 us inter-CS guard. This
  preserves a known comparison while measuring changes to physical transaction
  length and clock. Do not silently shorten the guard to manufacture a pass.
- Initially retain about 1 KiB logical batches and one selected immutable batch
  per node. Physical transaction size and logical collection size are separate:
  larger physical frames need not wait for additional samples.
- Exact versioned frame layouts remain engineering work. With the current
  illustrative 24-byte physical overhead, a 1008-byte object needs 26, 10 or 5
  fragments at 64, 128 or 256 physical bytes respectively. Additional new header
  fields, padding, availability and acknowledgment semantics require recalculation.
- Preserve RAM-acceptance ownership, immutable identity, checksum/deduplication
  safety, delayed-reply handling and explicit errors. Availability is not hardware
  readiness. Increasing frame length does not fix one-request RX ownership by itself.

### ADC acceptance and operating profile

- First mixed target: four nominal 3.33 kHz IMUs, one active channel on each of
  two ADCs, requested logging at 500 Hz. The existing selector chooses 1000
  conversions/s per worker; this is a setting, not an achieved-rate measurement.
- Qualified normal operation must supply a fresh conversion for each channel's
  logged row. Track conversion identity rather than numerical changes: constant
  input can produce equal-valued fresh readings. Explicitly declared exceptions
  and gaps remain subject to the existing fault/data-quality policy.
- Establish an ADC-only baseline before attributing freshness/rate failures to
  remote SPI traffic. Report baseline shortcomings separately; do not silently
  weaken the accepted fresh-reading criterion.
- Measure achieved conversion/logging rates, fresh/repeated/missed row counts,
  sample age, DRDY-to-read service, mutex waits and maximum uninterrupted blocking.
  Distinguish actual observed events from timestamps assigned after readback.
- Derive a supported per-profile blocking/service bound from the workload budget
  and evidence. No replacement numerical limit is selected by this interview.
  Other channel/rate combinations get separate admission results. Any reduction
  in supported ADC capability requires an explicit decision.
- Select clock, format and turnaround requirements before acquisition; hold the
  SPI measurement profile fixed for the recording. A pre-start slower fallback
  must independently support the requested workload. During recording, use bounded
  retry/recovery or explicit termination under the agreed policy, not an automatic
  clock/format switch or silent rate reduction.

### Prototype and transition back to T01

- The immediate implementation deliverable is an isolated known-data transport
  probe and result analysis, not the complete compact-BDQ/offline-timing redesign.
- Reuse production SPI/DMA/shared-bus and ADC paths sufficiently to expose real
  ownership, rearm, publication and contention. Identify any synthetic data source
  or substituted work explicitly; a pure SPI throughput result cannot qualify
  concurrent four-node CAN processing.
- Compare bulk SPI alone, ADC alone and the target mixed demand. Preserve exact
  transmitted/accepted data and identities, not merely attempted transaction rate.
- Separate wire time, bus ownership, non-overlapped guard, encode/decode, request
  processing, retirement/rearm, publication latency, worker pacing and concurrent
  resource use. Label means, tails, observed maxima and defensible bounds distinctly.
- Record exact board, source/build/artifact, protocol, actual clock, frame/guard,
  workload, method and instrumentation for each run. Device flashing remains the
  user's manual step; no device action follows from this design document alone.
- Freeze the original T01 inputs/results. Create an explicitly versioned revised
  model/manifest for changed source and geometry; do not merely change a cost or
  evidence label until the old model returns go.
- Reconcile healthy mandatory work, retries within class ceilings, finite bursts
  and terminal-fault behavior for the new design. Keep adverse/legacy envelopes
  as named comparisons rather than silently remove reserves. Normal 100 ms
  delivery and exceptional simultaneous-burst sensitivities remain separate.
- Preserve 70% CAN and 85% shared-SPI limits, at least 1.25x concurrent useful
  drain, applicable burst/service-envelope proofs and existing coverage targets.
  A faster wire floor alone cannot unblock dependent production implementation.

## Testing Decisions

Use existing production SPI-adapter/lifecycle and shared-bus/ADC seams. Add only
the highest necessary public probe-command/result seam for controlled workloads
and analysis. This is the validation approach proposed for final confirmation.

Before any manual flashing, use host tests with independent known data and target
builds to check frame boundaries, CRCs, exact accepted bytes, duplicates/lost
requests, stale replies, DMA publication, aborted/short CS transactions and clean
profile entry/exit. Review changed ownership and wire boundaries independently.
Check freshness using conversion/row identities, including equal-valued results
and deliberately repeated cache entries. Existing regressions remain applicable.

Physical validation compares the same declared workloads and artifacts across
candidate profiles. Measure actual SCK/duty and endpoint timing margins, CS/rearm,
error/drop counts, accepted/retired useful data, service tails and ADC freshness.
Predeclare observation durations and pass/fail limits; qualify sustained service
rather than a short average or compiler success. A profile failing ADC acceptance
is not admitted even if remote throughput is higher. Failed candidates remain
explicit results, not reasons to change parameters automatically during a run.

The probe supplies feasibility evidence for revised T01. Full node capture,
recording/persistence, offline timing, STOP/authorization and multi-node/fault
qualification still require their own implementation and existing gates.

## Out of Scope

- Hardware/pin remapping, clocks outside component ratings or automatic flashing.
- Automatic live clock/format fallback and silent sensor-rate reduction.
- Multiple outstanding batches without a demonstrated budget benefit.
- Changing logical collection latency merely because physical frames grow.
- Weakening ADC freshness or claiming 1000 achieved conversions/s from its setting.
- Completing T02-T11, qualifying production or changing tracker state in this
  discussion/prototype specification.

## Further Notes

The TI component specification permits 16 MHz on the current signal pin types,
subject to complete endpoint timing. Rates above 16 MHz require HSIO conditions
not met by the existing pin assignment. The assembled link has no inspected
qualification evidence above 8 MHz. This is a candidate ceiling, not a safe-speed
guarantee: [TI MSPM0Gx51x datasheet](https://www.ti.com/lit/ds/symlink/mspm0g3519.pdf).

The S3 controller's headline capability does not qualify the peripheral or the
board: [SPI master routing and timing](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/spi_master.html).

The original T01 result is pinned to its verified source/report identities. This
revision adds glossary terms, so the old source-manifest check on a changed
checkout is expected to reject that checkout. Reproduce historical results at
their pinned revision; do not silently update historical hashes. No revised
numeric feasibility pass is claimed yet.

- [Accepted reopening decisions](../adr/0004-reopen-spi-transaction-envelope.md)
- [Original confirmed redesign](CAN-FD_Drain_Capacity_Redesign.md)
- [Original no-go and assumptions](drain-capacity/REPORT.md)
