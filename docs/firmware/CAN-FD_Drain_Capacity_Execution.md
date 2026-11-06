# Drain-capacity redesign execution

The user confirmed the design and approved publication/implementation on
6 November 2026. The implementation graph below follows the confirmed redesign;
GitHub issue state remains separate from local verified completion.

- Integration branch: `integration/drain-capacity-redesign`.
- Snapshot base: `1b6caad970ef734b25c361dce4a3dbb6b4ee6b46`.
- The snapshot captures inherited bench fixes and confirmed design documents;
  it does not claim new physical qualification. The original bench worktree is
  preserved. Per-file baseline hashes are retained in external execution evidence.
- Remote scope: approved new issues, initial labels and native dependencies only.
  No PR/push, closing or incidental changes to existing issues are authorized.
- Physical qualification remains deferred to the existing practical bench work.
  No device probing/flashing is part of this implementation run.

| Ticket | GitHub issue | Blocked by | Local status |
| --- | --- | --- | --- |
| T01 | [#177: Establish the redesign capacity and service gate](https://github.com/benconnor1972/BODAQS/issues/177) | None | Model verified; feasibility NO-GO |
| T02 | [#178: Record and decode compact IMU packets without timing-model dependencies](https://github.com/benconnor1972/BODAQS/issues/178) | T01 | Blocked by T01 no-go |
| T03 | [#179: Transfer retained batches with combined ACK/fetch and availability hints](https://github.com/benconnor1972/BODAQS/issues/179) | T01 | Blocked by T01 no-go |
| T04 | [#180: Keep acquisition authorized through bounded renewal failures](https://github.com/benconnor1972/BODAQS/issues/180) | T01 | Blocked by T01 no-go |
| T05 | [#181: Drain IMU data alongside ADC work using actual deadlines](https://github.com/benconnor1972/BODAQS/issues/181) | T03, T04 | Blocked by T01 no-go |
| T06 | [#182: Preserve native clock observations from acquisition through BDQ decoding](https://github.com/benconnor1972/BODAQS/issues/182) | T02 | Blocked by T01 no-go |
| T07 | [#183: Reconstruct native sample timing from recorded observations](https://github.com/benconnor1972/BODAQS/issues/183) | T06 | Blocked by T01 no-go |
| T08 | [#184: Continue after explicit gaps and isolate failed IMU streams](https://github.com/benconnor1972/BODAQS/issues/184) | T04, T06 | Blocked by T01 no-go |
| T09 | [#185: Stop acquisition, drain its tail and safely start the next recording](https://github.com/benconnor1972/BODAQS/issues/185) | T02, T03, T04 | Blocked by T01 no-go |
| T10 | [#186: Admit redesigned IMU and ADC workloads using complete measured budgets](https://github.com/benconnor1972/BODAQS/issues/186) | T05, T07, T08 | Blocked by T01 no-go |
| T11 | [#187: Produce a reviewed redesign candidate and physical qualification plan](https://github.com/benconnor1972/BODAQS/issues/187) | T09, T10 | Blocked by T01 no-go |

All 17 native blocking links were verified after publication. A ready-for-agent
label does not waive blockers. Local completion may satisfy a dependency while
its GitHub issue remains open; issue closure requires separate authorization.

T01 was the sole initial frontier. Its executable model is locally implemented
and reviewed, but the feasibility gate reports NO-GO. T02-T11 remain unstarted.
Conditional estimates and pending measurements do not justify advancement.

The existing [physical timing/capacity gate](https://github.com/benconnor1972/BODAQS/issues/175)
and [practical fault-harness gate](https://github.com/benconnor1972/BODAQS/issues/176)
remain unchanged. T11 supplies their updated candidate and procedures.

See the [confirmed design](CAN-FD_Drain_Capacity_Redesign.md) and ADRs 0002/0003
for behavior, interfaces, exclusions and qualification requirements.

## Verified T01 result

Code reviewed and merged: `7e97877674f22dfa3cb049a265e9b64f6e19b779`.
Fourteen public-interface tests pass. The CLI verifies 48 baseline source hashes
and evaluates 126 deterministic scenarios; repeated reports have SHA-256
`fca974adffecbf52880be9567dfdcc8b9ed228e2741fe10bbfb047cfed02bf8e`.

Four nodes need 6,666 sample-data fragments/s at the retained 1.25x catch-up
requirement. At the installed logger's measured mixed mean of 147.3376 us, those
fragments alone charge 982.152 ms/s before encoding, control or ADC work, already
above the 85% scheduling limit. This measured-cost scenario fails independently
of the report's conservative exceptional-burst assumptions. The installed logger
used bitwise CRC while canonical headers use LUT CRC; prospective redesigned
costs remain unqualified. Physical wire floors do not prove a feasible complete
service envelope, nor does this result prove the hardware universally incapable.

Independent Standards and Spec review each found one P2 model defect. A fresh
implementer fixed input/report aliasing and latency estimates that omitted
request/pacing constraints. Fresh verification found zero outstanding findings;
see the [review record](drain-capacity/CODE_REVIEW.md).

The next required step is to reopen the transaction-cost/batching/pipelining or
explicit rate/workload envelope and rerun T01 with defensible complete bounds.
No dependent implementation, production admission, new firmware candidate,
physical pass, PR/push, issue closure or existing-issue edits were performed.
The [capacity report](drain-capacity/REPORT.md) contains assumptions, sensitivity
thresholds and reproducible commands.
