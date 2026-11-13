# T13: Package qualified profiles and repeatable acceptance runs

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Make the completed new-protocol acquisition reproducible: matched artifacts,
explicitly supported profile/configuration templates, a concise operator runbook
and automated final assessment. A user can identify what is qualified and repeat
the recording without reconstructing a long bench conversation.

## Acceptance criteria

- [ ] Package exact master/logger builds, node provenance, profile/configuration
  identifiers, hashes and versioned recording/analysis compatibility. Preserve
  rollback artifacts and reject incompatible pairs explicitly.
- [ ] State the supported polling and IRQ workload/profile combinations with
  evidence links and limits. Both 256/512 options retain their applicable results;
  smaller/slower fallback does not imply admission of an unqualified workload.
- [ ] A repeatable command-driven workflow collects finalized serial/file/device
  evidence and produces the per-source integrity/delivery/timing, per-channel
  freshness, queue/service, resource-gate and STOP/tail report already exercised.
  Minimize manual debugger copying and distinguish missing evidence from a pass.
- [ ] Preserve historical BDQ readability and explicitly version the new schema
  and decoder; include upgrade/mismatch behavior and RAM-ACK versus SD-durability
  explanation in the operator material.
- [ ] Publish complete test/build/physical evidence provenance and remaining
  limitations, including deferred controlled storage-stall tests and separately
  unqualified high-frequency cross-IMU phase alignment.
- [ ] Keep generic admissions-policy development, broader channel/rate sweeps,
  node/CAN redesign, hardware revisions and old issue cleanup outside this slice.
  Do not turn a profile report into a general policy without separate work.
- [ ] Unmet required targets remain visibly open; partial/no-go results cannot
  mark the overall feature complete. Do not close or rewrite the parent or older
  issues as incidental packaging work.

## Blocked by

- T08: Carry 512-byte sample units through real polling recordings.
- T12: Qualify four-IMU mixed acquisition with ready IRQ.
