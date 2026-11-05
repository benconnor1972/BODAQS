# IMU acquisition and transport software implementation

Specification: [#164](https://github.com/benconnor1972/BODAQS/issues/164).
Integration branch: `integration/imu-acquisition-transport`.
Integrated control baseline: `0139d69`; approved design baseline: `8e0c673`.
The [acquisition contract](CAN-FD_Acquisition_Transport_Contract.md), confirmed
network decisions Q71-Q147 and existing node control semantics remain binding.

## Software progress

Only locally merged and verified work satisfies a dependency here. GitHub issues
remain open by agreement. No push, PR, issue-state changes or device operations
are part of this implementation.

| Ticket | State | Integration evidence |
|---|---|---|
| #165 responsive storage worker | Merged and verified | `66ed1ab`, merged at `9c20ead`; [storage evidence](Storage_Worker_Implementation.md) |
| #166 measurement-mode negotiation | Merged and verified | `93ef410`, merged at `918fa87`; [mode evidence](CAN-FD_Measurement_Mode_Implementation.md) |
| #167 bounded fragmented transfer | Merged and verified | `a00e81b`, merged at `655bbcd`; [fragment evidence](CAN-FD_Fragment_Transport_Implementation.md) |
| #168 leased recording lifecycle | Merged and verified | `4411809`, merged at `6255dc2`; [lifecycle evidence](CAN-FD_Acquisition_Lifecycle_Implementation.md) |
| #169 one-node native BDQ recording | Merged and verified | `20ce5a9`, merged at `fbca8ba`; [native recording evidence](CAN-FD_Native_IMU_Recording_Implementation.md) |
| #170 synchronization and analysis timing | Merged and verified | `a1d4cba`, merged at `8d5dbc4`; [synchronization evidence](CAN-FD_Synchronization_Implementation.md) |
| #171 bounded loss and continuity recovery | Merged and verified | `6e64f66`, merged at `bd86b0d`; [bounded loss evidence](CAN-FD_Bounded_Loss_Recovery_Implementation.md) |
| #172 link/restart containment and cleanup | Merged and verified | `1113809`, merged at `647811a`; [link/restart evidence](CAN-FD_Link_Restart_Implementation.md) |
| #173 four-node resource admission | Merged and verified | `0628154`, merged at `e8c5123`; [admission evidence](CAN-FD_Four_Node_Admission_Implementation.md), [link profiles](CAN-FD_Link_Profile_Implementation.md) |
| #174 integrated software acceptance | Merged and verified; final review complete | `cbf2e67`, merged at `03ab248`; [combined acceptance and exact candidate evidence](CAN-FD_Integrated_Software_Acceptance.md), [reusable candidate runner](CAN-FD_Software_Candidate_Bundle.md) |

At `9c20ead`, the combined common CAN/control suite (nine binaries), full logger
host/runtime suite, asynchronous storage-controller fixtures and explicit A8
`bodaqs_s3_mini_n4r2` build pass. The #166 master production build also passes.
The unchanged baseline BDQ analysis suite passes 42 tests with `PYTHONPATH=analysis`.
Final software acceptance and independent Standards/Spec review remain pending.

At `655bbcd`, all ten common binaries and production measurement, recording,
recovery and mute runtime fixtures pass, including pipelined four-node traffic
interleaved with protected control. The merged source tree exactly matches the
tested child: master TI and A8 build evidence remains applicable. CAN receive
ticks are explicitly quantized to 1 ms until the acquisition-clock slice #170.

At `6255dc2`, all eleven common binaries and production acquisition, measurement,
recording, recovery, mute, apply and sensor-configuration runtime checks pass.
The merged source matches the child-tested node/master/A8 builds. Native-clock
deadline units and terminal staging cancellation are covered by independent
fixtures. Production acquisition backend and sample draining remain #169.

At `fbca8ba`, all twelve common binaries, three node adapter binaries, production
stream/coordinator and existing control/storage fixtures pass, including actual
node adapter output through master fragments and native BDQ into an independent
reader. The child full analysis suite passes 577 tests with one skip; merged
focused analysis passes 58 tests. Identical source trees preserve the passing
node/master/A8 build evidence. Broader timing, loss/restart recovery and four-node
resource admission remain the following software slices.

At `8d5dbc4`, the full logger host suite, thirteen common binaries and node
adapter scenarios 1-10 pass; focused timing/BDQ analysis passes 69 tests. The
child full analysis run passes 588 with one skip, and identical merged source
preserves passing node/master/A8 builds. Raw synchronization captures remain
available when absolute association and finite alignment bounds are unknown.

At `bd86b0d`, the full logger host/runtime suite, thirteen common binaries,
node capture/SPI and acquisition scenarios 1-11, and master timing pass. Native
reader/timing analysis passes 27 tests. Production ERROR diagnostics cross
AcquisitionControl into deduplicated companions; normal and recovered actual
node data reach the independent BDQ reader. The exact child tree preserves
passing explicit node/master/A8 build evidence. Physical qualification remains
deferred.

At `647811a`, the full firmware host/runtime suite, thirteen common binaries,
node capture/SPI and acquisition scenarios 1-11, and the additional control-apply
regression pass. Production fixtures cover short recovery, the exact 300 ms
cutoff, fatal 330 ms loss, restarted-logger cleanup with five seconds of lost
BIND results, node/master reboot, bus-off and lease expiry. Healthy locals
continue, and explicit fence/release and global exit wait for stopped-only
cleanup and physical retirement proof. Optional post-START health requests and
retries share the 4/s burst-four bucket; real loss diagnostics remain valid.
The complete merged tree equals the tested child tree, preserving passing
G3507 node, G3518 master and A8 target-build evidence. Physical qualification
remains deferred.

At `e8c5123`, the complete firmware host/runtime suite, fourteen common binaries,
node capture/SPI/acquisition scenarios 1-12 and master timing pass. Four real
lifecycle peers exercise allocation-before-PREPARE, startup, renewal, STOP,
tail/fence/release and healthy-peer isolation after bus-off. Admission fixtures
verify joint backlog coverage and explicit CAN/SPI/drain/qualification rejection.
The entire merged tree equals child `0628154`, preserving its full analysis
result (588 passed, one skipped) and explicit target-build evidence: TI node
FLASH 41456/SRAM 13169 bytes; master FLASH 41352/bank-0 SRAM 62139 bytes,
including reserved 2048-byte stack, with 3397 bank-0 bytes free and bank 1 unused;
A8 `bodaqs_s3_mini_n4r2` static RAM 260460/flash 2020553 bytes. Both TI bring-up
and acquisition link selectors pass. Target builds were not repeated.
Production has no qualified scheduling profile and explicitly rejects remote
admission before PREPARE; deterministic synthetic profiles establish software
behavior only. #174 integrated acceptance and final review remain pending.

At `144175e`, the complete #174 software candidate passes on committed tree
`73d9799c9d1401dfbb0709eaf1dab5b4f20a66e9`: all firmware host/runtime checks,
14 common binaries, node adapter scenarios 1–12, baseline control-apply,
independent combined four-node recording/ingress ledger/prefix recovery, full
analysis (588 passed, one skipped, seven warnings), all four TI node/master
bringup/acquisition builds and clean A8 production build. The source guard
confirms unchanged HEAD and tracked source. The retained local bundle is
`C:/Users/benco/dev/BODAQS-worktrees/imu-software-candidate-174-complete`;
its complete 70-file SHA-256 inventory was independently verified. Exact
source/archive/manifest/image identities, target allocation and reproduction
commands are recorded in the #174 evidence above. Later evidence-only docs do
not alter the tested firmware, analysis or tools. Conflict-free integration merge
`03ab248` exactly matches child tree `984e8422a44aa51087b0a71bb7410173927eb8ee`.
Fresh merged-tree combined runtime and independent file/ledger/prefix checks pass,
as do all fourteen common host binaries. All 70 candidate inventory hashes and
the recorded archive/manifest/inventory identities were rechecked. Full analysis
and target builds were reused because only the two evidence Markdown files differ
from the tested source. That pre-review checkpoint was followed by the final review below;
physical qualification remains deferred and production remote admission remains
unsupported/unqualified.

## Final reviewed software candidate

All ten software tickets #165 through #174 are locally implemented, merged and
verified. The [final Standards/Spec review](CAN-FD_Acquisition_Transport_Code_Review.md)
found two P1 standards defects, one phase-naming heuristic and one P2 spec defect.
One fresh implementer fixed all four in `d2ee18b`; two fresh independent reviewers
confirmed all findings resolved with no new concrete findings. Fix merge
`6128b99` exactly matches tested tree `20e04b017c134b334addc41bb2b4184d118af93c`.
See [resolution details](CAN-FD_IMU_Review_Resolutions.md).

The superseding final candidate is
`C:/Users/benco/dev/BODAQS-worktrees/imu-software-candidate-reviewed`, built from
clean unchanged source `d2ee18b97b108d45050a84c8a14e4f251b841376`. All 71 checksum
entries verified. Full firmware/common/master-adapter/node scenarios 1 through 13,
control, integrated recording and analysis checks passed (588 analysis tests,
one skipped), as did both TI profiles for node/master and clean A8. Final maps,
artifact identities and qualification gates are in the review report. Fresh
merged-tree master adapter and node exhaustion/turnover regressions also passed.
Standards: zero open findings. Spec: zero open findings. Production remote
admission remains explicitly unqualified; physical #175/#176 remains deferred.

## Deferred physical qualification

[#175](https://github.com/benconnor1972/BODAQS/issues/175) and
[#176](https://github.com/benconnor1972/BODAQS/issues/176) remain deferred and
unexecuted. Software fixtures and target compilation do not establish physical
FIFO/DRDY association, SPI/SYNC timing, electrical reliability, measured phase,
bandwidth, four-node throughput, stack watermarks or lease-service timing.
The 10 us alignment target is unverified and is not an admission gate.
CAN disconnect/reconnect, CCS halt/resume and node/master reset bench tests
remain deferred. No firmware was flashed. Existing operator-reported control
happy-path evidence and explained FRONT_FAULT bypass telemetry remain unchanged.
