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
| T01 | [#177: Establish the redesign capacity and service gate](https://github.com/benconnor1972/BODAQS/issues/177) | None | In progress; capacity gate pending |
| T02 | [#178: Record and decode compact IMU packets without timing-model dependencies](https://github.com/benconnor1972/BODAQS/issues/178) | T01 | Not started |
| T03 | [#179: Transfer retained batches with combined ACK/fetch and availability hints](https://github.com/benconnor1972/BODAQS/issues/179) | T01 | Not started |
| T04 | [#180: Keep acquisition authorized through bounded renewal failures](https://github.com/benconnor1972/BODAQS/issues/180) | T01 | Not started |
| T05 | [#181: Drain IMU data alongside ADC work using actual deadlines](https://github.com/benconnor1972/BODAQS/issues/181) | T03, T04 | Not started |
| T06 | [#182: Preserve native clock observations from acquisition through BDQ decoding](https://github.com/benconnor1972/BODAQS/issues/182) | T02 | Not started |
| T07 | [#183: Reconstruct native sample timing from recorded observations](https://github.com/benconnor1972/BODAQS/issues/183) | T06 | Not started |
| T08 | [#184: Continue after explicit gaps and isolate failed IMU streams](https://github.com/benconnor1972/BODAQS/issues/184) | T04, T06 | Not started |
| T09 | [#185: Stop acquisition, drain its tail and safely start the next recording](https://github.com/benconnor1972/BODAQS/issues/185) | T02, T03, T04 | Not started |
| T10 | [#186: Admit redesigned IMU and ADC workloads using complete measured budgets](https://github.com/benconnor1972/BODAQS/issues/186) | T05, T07, T08 | Not started |
| T11 | [#187: Produce a reviewed redesign candidate and physical qualification plan](https://github.com/benconnor1972/BODAQS/issues/187) | T09, T10 | Not started |

All 17 native blocking links were verified after publication. A ready-for-agent
label does not waive blockers. Local completion may satisfy a dependency while
its GitHub issue remains open; issue closure requires separate authorization.

T01 is the sole initial frontier. Do not advance dependent firmware work if its
budget reports a no-go. Conditional estimates and pending measurements must not
be relabelled as qualified costs.

The existing [physical timing/capacity gate](https://github.com/benconnor1972/BODAQS/issues/175)
and [practical fault-harness gate](https://github.com/benconnor1972/BODAQS/issues/176)
remain unchanged. T11 supplies their updated candidate and procedures.

See the [confirmed design](CAN-FD_Drain_Capacity_Redesign.md) and ADRs 0002/0003
for behavior, interfaces, exclusions and qualification requirements.

