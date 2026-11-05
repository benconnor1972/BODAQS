# Acquisition and transport final software review

Specification: [#164](https://github.com/benconnor1972/BODAQS/issues/164), software
slices #165 through #174. Branch: `integration/imu-acquisition-transport`.

The independent initial review compared the complete implementation at
`b80fc5254299dddd0b4e6d4a762753b8e3f8392c` with preserved approved-design baseline
`8e0c6731af5ead2c2fa39def11047a3ccab3b50f` using `git diff 8e0c673...HEAD`:
127 changed files, 13,432 insertions and 196 deletions. The integrated control
baseline was `0139d69`; approved design artifacts were preserved before creating
child worktrees. All software slices used fresh implementers and isolated
worktrees, with separate mergers and local verification.

One fresh implementer addressed all four findings in
`d2ee18b97b108d45050a84c8a14e4f251b841376` (tree
`20e04b017c134b334addc41bb2b4184d118af93c`). Two further fresh, independent
read-only reviewers checked the actual fix diff against the prior reviewed tip.
Their reports below preserve the Standards and Spec axes separately. Final fix
integration merge: `6128b99fbc537611df2ae9e918e5f7a86158d7b7`.

| Axis | Initial findings | Resolution | Open |
|---|---|---|---:|
| Standards | Two P1 documented-standard breaches; one heuristic naming finding | All three resolved | 0 |
| Spec | One P2 epoch-lifetime requirement defect | Resolved | 0 |

## Standards

### Initial report

Documented-standard breaches

- **P1 — Decode the raw MCAN identifier before accounting for ISR loss.** `firmware/can-fd/master/src/main.c:313` introduces `uint16_t id=(uint16_t)record.message.id;`, although this file's canonical decoder (lines 186–188) shifts standard identifiers right by 18. Raw sample/evidence identifiers therefore truncate to zero, so the new overflow branch never accumulates their rejected receptions. Stage-5 exact loss reports and essential-metadata failure evidence disappear when the eight-record ISR queue fills. Reuse `can_standard_identifier(&record.message)` and exercise raw MCAN messages through queue exhaustion. This breaches the logging-integrity and fault-recovery review requirements in `docs/agents/engineering.md` (Firmware) and regression correctness in root `agents.md` §6.

- **P1 — Keep service retirement under one owner.** `firmware/can-fd/master/src/main.c:816–828,893` calls `bodaqs_master_service_measurement_fence(&gService,true,true)` from the GPIO ISR. That function clears main-owned ingress/reception heads and retirement state (`common/protocol/bodaqs_master_service.c:156–175`). A concrete interleaving at lines 416–417 is main publishing `acquisition_retirement_pending=true`, ISR clearing pending and setting `measurement.fenced=true`, then main resuming with `measurement.fenced=false`. No pending retirement remains to restore the fence, preventing clean mode exit. Other head/buffer mutations share the ownership problem. Have the ISR publish physical-boundary evidence and let the service owner commit retirement through an explicit synchronized handoff; merely swapping those two stores is insufficient. Add an injected CS-preemption regression at this adapter seam. This breaches root `agents.md` §4.1 (explicit interfaces; avoid hidden global coupling) and `docs/agents/engineering.md` Firmware requirements for buffering, integrity and fault recovery.

Judgment call

- **Possible Primitive Obsession:** `firmware/src/AcquisitionControl.cpp:31,185–246` represents six lifecycle phases as `uint8_t phase = 0` with only a comment mapping numbers, then branches on `p.phase==1`, `==3`, `==5`, `==6`. Use a small named phase enum so transitions and guards communicate their domain meaning; wire values can remain unchanged. This is a baseline heuristic, not a hard violation.

Reviewed the fixed-base production change, host fixtures and candidate runner without executing builds, accessing devices or editing source. Physical qualification remains deferred.


### Independent resolution report

Standards resolution review

Reviewed child `d2ee18b97b108d45050a84c8a14e4f251b841376` (tree `20e04b017c134b334addc41bb2b4184d118af93c`) with `git diff b80fc525...HEAD`; commit list contains only `d2ee18b`. Read all changed production code, tests, runner and documentation against root/firmware AGENTS instructions and `docs/agents/engineering.md`.

Initial findings

- **P1 raw MCAN overflow — resolved.** `firmware/can-fd/master/src/main.c:315` now uses `can_standard_identifier`, matching normal reception's TI standard-ID representation. The production-body adapter regression fills the eight-entry queue using raw shifted MCAN IDs and checks literal node/range/epoch/ordinal and essential-evidence loss (`master/test/adapter_fixture.c:65–78`). This addresses logging integrity/fault recovery and root AGENTS §6.
- **P1 ISR/main retirement ownership — resolved.** The ISR no longer calls the protocol service fence. `master/src/main.c:811–831` publishes a generation/context request and consumes matching proof in the main owner; `common/protocol/bodaqs_master_service.c:416–419` invalidates earlier proof for each node fence. `master/src/main.c:854–890` disables DMA, respects unpublished inactive-buffer ownership, resets peripheral/FIFOs and then publishes physical-boundary proof. The main writer strips data responses before publication while retirement remains pending (`:915–918`). Saturation fails closed. The injected preemption regression exercises the production result handler at the original vulnerable store boundary, checks stale generation/context rejection and leaves ring retirement to the main owner.
- **Possible Primitive Obsession — resolved.** `firmware/src/AcquisitionControl.cpp:22–25,35` introduces a private named phase enum; changed guards/transitions consistently use its names while preserving values and behavior.

No new concrete documented-standard breach or baseline smell warrants a finding. Recording epoch reuse is guarded by verified stopped state plus transmit-idle fencing and a changed recording; turnover/exhaustion tests exercise the real node adapter. Candidate runner coverage now includes the master adapter.

This was a read-only source review: no tests/builds, source edits, device or remote actions. The running candidate modified an existing test executable; I did not alter it. Hardware simulation and source review establish software ordering, not physical timing/electrical qualification; #175/#176 remain deferred.


## Spec

### Initial report

1. **[P2] Reclaim the eight-bit source-epoch space after completed recording turnover.** In `firmware/can-fd/node/src/imu_acquisition.c:358–362`, START rejects `a.epoch == 255` and otherwise increments it. Recovery also increments that same persistent field (`:274`, `:341`). Neither PREPARE (`:651–665`) nor acknowledged FENCE (`:677–687`) resets/rebases it, and initialization is boot-only. Consequently, 255 ordinary, fully stopped/fenced/released recordings exhaust this node for all later recordings until reboot; recoveries exhaust it sooner. A recording that reaches epoch 255 likewise cannot be followed by another valid recording despite successful turnover.

   Q95 explicitly says: “this does not impose a lifetime limit of 256 segments per node boot” (`docs/firmware/CAN-FD_Network_Protocol.md:1015`); it permits reuse across recordings after stopped-producer and end-to-end stale-data fencing (`:1011–1014`). Scope epoch exhaustion to the current recording, retaining its fail-closed behavior, and allow a fresh epoch allocation after verified turnover. Add a native node-adapter regression that repeatedly completes PREPARE/START/STOP/FENCE across the capacity boundary and still starts a successor, while preserving scenario 10's within-recording exhaustion and stale-data fence checks.

No additional concrete requirement defects identified. Production remote admission remains explicitly unqualified before PREPARE as authorized; physical #175/#176 qualification is deferred and is not treated as a software-review finding. Reviewed pinned `b80fc5254299dddd0b4e6d4a762753b8e3f8392c` against `8e0c6731af5ead2c2fa39def11047a3ccab3b50f`; no tracked source changes or test reruns.


### Independent resolution report

Reviewed `git diff b80fc525...HEAD` and `git log b80fc525..HEAD --oneline`: sole commit `d2ee18b97b108d45050a84c8a14e4f251b841376` (tree `20e04b017c134b334addc41bb2b4184d118af93c`).

**Initial Spec finding: resolved.** Q95 requires “Never reuse an eight-bit stream epoch within a recording” and explicitly rejects a boot-lifetime segment limit (`docs/firmware/CAN-FD_Network_Protocol.md:1008–1015`). `node/src/imu_acquisition.c:654–656,689–693` now rebases only for a different recording after verified IDLE plus the hardware transmit-idle fence, consuming that permission on PREPARE. START and recovery retain their epoch-255 failure guards (`:275,360`). The unchanged control owner validates stopped/fenced membership and recording identity; source/node/sensor clock identities remain distinct. Native adapter scenario 13 executes 260 recordings without initialization; scenario 10 retains exactly 254 recoveries and terminal exhaustion, then starts a fresh successor after STOP/FENCE (`node/test/test_acquisition.c:229–278,335–337,362–366`).

**Retirement cross-check: no new defect found.** The contract requires the master to retire “old CAN reception/retention and SPI/DMA objects” and permits reuse only after a completed fence (`docs/firmware/CAN-FD_Acquisition_Transport_Contract.md:275–282`). Each node fence advances a main-owned generation; the interrupt-masked request/proof mailbox matches generation and measurement context. Hardware proof follows DMA disable and peripheral/FIFO reset. Only the main owner commits service retirement. Published buffers and the active DMA buffer are retired; an unpublished writer strips data before publication while preserving control replies (`master/src/main.c:803–835,849–893,915–919`). The production-function fixture covers the original preemption, superseding generations, changed context, unsafe boundaries, writer ownership and control preservation.

**Loss cross-check: resolved.** Raw MCAN overflow now uses the canonical shifted standard identifier (`master/src/main.c:315`); literal fixture assertions verify rejected sample range/count/epoch/ordinal and ordinary versus essential evidence loss, consistent with stage-5 observed-loss accounting and Q132 metadata exclusion (`Acquisition_Transport_Contract.md:421–424,517–521`).

No new concrete missing, wrong or unrequested behavior identified. No source edits, tests/builds, remote operations or device actions performed. The concurrent candidate run owns validation evidence; physical #175/#176 and production remote qualification remain deferred as agreed.


## Final software verification and candidate identity

The final candidate was generated from clean committed source
`d2ee18b97b108d45050a84c8a14e4f251b841376`, tree
`20e04b017c134b334addc41bb2b4184d118af93c`. Its manifest records unchanged HEAD
and no tracked changes after validation. Subsequent final-report/index edits
are documentation only; artifact identity remains that exact tested source.

Local candidate directory:
`C:/Users/benco/dev/BODAQS-worktrees/imu-software-candidate-reviewed`.
The [candidate workflow](CAN-FD_Software_Candidate_Bundle.md) reproduces all
commands and retains source, observed tool/dependency versions, flags, command
arguments, logs, native/failed/damaged BDQ files and profile-specific artifacts.
All **71** entries in `SHA256SUMS.txt` were independently checked after completion.
Earlier bundles retain historical pre-review, interrupted or failed states;
this reviewed candidate supersedes them for final software evidence.

Passed on that fixed source:

- Full firmware host/runtime suite and all 14 common protocol/link binaries.
- Master timing plus production raw-MCAN overflow and injected-CS adapter
  regressions; node SPI/capture and acquisition scenarios 1 through 13.
- Existing configuration/effective-state, duplicate-address, no-op revision,
  migration, mute, idle-recovery and control/storage regressions.
- Five integrated operator/control/four-node/storage scenarios, two explicit
  restarts, exact admitted-input/loss ledgers and eight cut/CRC-prefix cases.
- Full analysis suite: **588 passed, one skipped, seven warnings**, 78.31 seconds.
  The existing Windows skip concerns a macOS-default import-agent config path.
- Forced G3507 node and G3518 master builds for **both** explicit link profiles,
  plus a clean A8 `bodaqs_s3_mini_n4r2` production build.

| Target/profile | Flash bytes | Static RAM bytes |
|---|---:|---:|
| G3507 node, bringup | 41528 | 13177 |
| G3507 node, acquisition | 41488 | 13177 |
| G3518 master, bringup | 41600 | 62171 in bank 0 |
| G3518 master, acquisition | 41656 | 62171 in bank 0 |
| A8 `bodaqs_s3_mini_n4r2` | 2020561 | 260460 |

TI SRAM figures include the reserved 2048-byte stacks. Master bank 0 has 3365
unallocated bytes; bank 1 is unused. These are static link-map observations,
not runtime watermarks. The A8 build reports limits of 327680 RAM and 4063232
application-flash bytes. Both link profiles have their own copied outputs and
maps; the manifest and inventory bind each image to its target and profile.

Key file hashes:

- `SOURCE.zip`: `9c47718299c7919a0d053c207f97e82e8793ac86f538497d2a0a3dab4c544142`.
- `BUILD_MANIFEST.json`: `27b0d1cbaf58212a6b0107fab1e7827f58d5b85419ed12b2795a7e69f73baa1b`.
- `SHA256SUMS.txt`: `f0bfafb718d45b7cf4d6c4ef068043fa4b042c09ceb6e68bee79c1f638b0f01a`.
- `artifacts/a8-bodaqs_s3_mini_n4r2/firmware.bin`: `a877632ce497b0218fb260ac26d1dddd2f99c75e47142f52ecbe27c0eb962ee3`.

## Deferred physical qualification and publication state

[#175](https://github.com/benconnor1972/BODAQS/issues/175) and
[#176](https://github.com/benconnor1972/BODAQS/issues/176) remain deferred and
unexecuted. Outstanding evidence includes FIFO/DRDY association, SPI/DMA/SYNC
and shared-bus timing, measured mixed-ADC/four-node throughput, lease latency,
clock phase/drift and the unverified 10 us alignment target, electrical faults,
runtime stack/heap headroom, disconnect/reconnect, CCS halt/resume and node/master
reset bench scenarios. Host simulations, review and compilation do not qualify
these properties. Unknown alignment remains recordable; production remote
admission remains explicitly unqualified until measured scheduling bounds are
supplied. No rates or timing bounds were invented to advertise readiness.

All ten software tickets are locally implemented, merged and verified; GitHub
issues remain open by agreement. No push, PR, remote issue change, device probe,
flash or physical qualification was performed. Only agent-created clean, merged
worktrees were removed; the original checkout, user worktrees and scratch files
were preserved. The [implementation index](CAN-FD_Acquisition_Transport_Implementation.md)
records each ticket's merge and evidence.

Standards: three findings resolved, worst initial severity P1, zero open.
Spec: one finding resolved, worst initial severity P2, zero open.
