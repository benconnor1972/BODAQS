# r23: bounded investigation of batch formation, retirement and pipeline work

Base ff412622cddd6a3e5d93f9ef25495595d5c883b2 (r21). The user authorized design
and preparation after the synthetic/real comparison; this is an observation
round, not a protocol redesign or throughput tuning sweep. Device flashing is
not part of preparation. Preserve the installed logger and all node images.

## Questions and ranked predictions

1. If reception age/span or interleaved evidence limits batch filling, live seal
   reasons and record histograms will identify which mechanism dominates.
2. If selected-head retirement limits progress, sealed-to-ACK residence and time
   from all fragments prepared to ACK will be large relative to batch service.
   Preparation is a software event; it is not physical delivery/acceptance.
3. If repeated requests dominate, repeated fragment preparations will be large
   alongside the existing PIPE/FLOW replay and empty-reply observations. Multiple
   earlier identical requests remain ambiguous; never assign current MOSI as the
   cause of simultaneous MISO or add overlapping waste percentages.
4. If logger service is restrictive, primary drops, per-node consumer waits,
   accepted/persisted reconciliation and storage-call statistics will expose it.
   Wall-clock File.write duration includes preemption and is not card-only speed.

## First stage: actual-code host investigation

`firmware/tools/test_master_batch_diagnostics.py` compiles the production service,
actual wire codecs, CRC/reassembly and ACK paths with observation off/on. It
checks full batches, sparse live arrivals, queued arrival span, held evidence,
sample/evidence interleaving, unsigned timer wrap/node isolation and scope reset.
No fake DMA timing, CAN capacity or host execution speed becomes a hardware rate.
The encoded response hashes and retained populations must be identical off/on.
This prepares a fast replay seam for a subsequent small fix, without changing
today's 20-ms age rule, maximum batch size or ownership policy.

## First device stage: one four-node observation

Use the existing r22 four-node ADC-off configuration, unchanged r21 logger and
node firmware. Install only the supplied r23 diagnostic master on MSPM0G3518.
Retain mode0, requested16MHz,256-byte slots,5us CS setup,600us logger pacing,
RX depth2, boundary reserve2, block CRC0 and CAN-first0. No IRQ/wiring change.
Record about105seconds with all four sources. Require nine streams and actual
samples from every source, then normal STOP through file closure and PIPE end.
Save the same BDQ, serial, actual config and CCS inputs as r22, plus the exact
binary export of `gMasterBatchInfo` **before another recording resets it**.

New instrumentation is default-off and writes only main-owner diagnostic state
in a separate BANK1 block. It changes no public wire, BDQ or configuration format.
No allocations, logs, extra clocks, retries or scheduling decisions occur in the
hooks. Time is the existing service uint32 millisecond clock; captures must be
shorter than one wrap. No pure CPU or physical latency bounds are claimed.
The existing gMasterDrainInfo ABI is unchanged.

The block is reset with the exact transfer context/session/recording/master-boot
tuple and accumulates through cleanup. Per-node sample/evidence lanes record
seal causes, batch-size histograms, original reception span, age and queued depth
at sealing; sealed-head residence to first valid ACK; time from first preparation
of every fragment to ACK; unique/repeat fragment preparations; and separately
counted fence discards. Duplicate or wrong ACKs do not count a new retirement.
Retired-without-all-prepared is explicit uncertainty, not a fabricated latency.
No frozen first-loss-only snapshot is presented as a whole-run distribution.

Export occurs only after STOP/cleanup, with CCS temporarily suspending the master.
The exporter loads symbols only, reads RAM and resumes; it never programs/reset
devices. Its manifest/hash/layout checks precede file creation. Binary halves
preserve the 64-bit scope exactly. The operator's image selection plus markers
remain provenance; reading a symbol or recipe is not installed-image attestation.

## Acceptance and decision bounds

Observation success requires exact logger recipe/config, four START-backed source
identities, complete matching PIPE context and matching binary diagnostic scope,
valid histograms/count conservation and complete intake. Existing primary losses,
source loss, missing boundaries and ambiguous data stay failed in their own checks.
The strict reader must not waive primary loss to pass an overloaded capture.

Compare the same first100seconds and retain whole-source START/STOP denominators
separately. Reference r22:5852.90readings/s,54.02%missing IMU readings,4804primary
drops,all four final boundaries and accepted IMU data persisted. One observer run
is not an isolated throughput improvement; if the observer perturbs outcomes
materially, use one exact rollback control before attributing a mechanism.

After host replay and this one capture, choose at most one small policy fix when
a measured dominant mechanism and actual-code regression support it. A useful
candidate should plausibly improve payload by at least10%, remove primary loss,
or fix a correctness problem without weakening integrity/authority. Small changes
need a matched comparison; no open-ended parameter sweep. If none is supported,
stop local tuning and carry quantified constraints to protocol redesign.
Unknowns remain unknown; telemetry must not manufacture causality or guarantees.

Storage-stall injection, card comparisons, RAM-sink firmware, larger frames,
outstanding-batch redesign, node changes, ADC/mixed requalification and relaxed
clock-trust policy are outside this first stage. They are conditional follow-ups,
not a large matrix the operator must complete. No new qualification is asserted.
