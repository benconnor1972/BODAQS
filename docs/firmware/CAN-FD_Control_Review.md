# CAN-FD configuration final review

Reviewed: 4 November 2026. Tickets #153-#162.

Initial range: `b8407363a4b07e114e4b39dfd95fd5073a1c64c9` through
`59cac6a37af838dd00db8156a2428d5eb5c56be3`. Fresh independent agents
reviewed Standards and Spec separately. One fresh implementer addressed both
findings in `5b1051bcbe6468c5edd77af9b0898555e2971829`, merged at
`d39891f2185fecb8f08a55927dae5875b65206f4`. Both reviewers subsequently
verified the correction. No unresolved findings remain.

## Standards

No definite documented-standard breaches were found against `agents.md`,
`firmware/AGENTS.md`, `docs/agents/engineering.md` and firmware build guidance.

One nonblocking judgment call, possible Feature Envy: logger timeout/handoff
logic directly changed portable apply/authority client phases, pending state,
outcomes and mutation sequences. Small owner transition APIs now handle
transport timeout, recording quarantine/fence and scoped monotonic sequence
reservation; the logger retains orchestration and deadline ownership.

The Standards reviewer confirmed that this concern is addressed and that the
patch introduces no hard standards breaches or remaining findings. Existing
explicit C structures and wire interfaces are retained.

## Spec

One P2 was confirmed: the master recorded a duplicate strap address but still
admitted and transmitted configuration commands, including retries, while the
logger's inventory cache could be stale. Network section 9 requires that a
duplicated address must not be configured; ticket #161 requires duplicate
protection never be bypassed.

The master now derives an exchange exclusion mask from its inventory and
refreshes it after CAN receive before dispatch. Excluded unsent work receives
the existing busy receipt; possibly transmitted work becomes transport-outcome
uncertain. Read-only inspection and independent addresses remain serviceable.
No new wire code or claim of hardware cancellation is introduced.

The Spec reviewer independently reran the original reproduction: duplicate
COMMIT transmission and retry are both blocked. The expanded production
transport suite also passes. No introduced spec defect was found in the fix
or owner API extraction. Deferred acquisition/sample/lease work was excluded
from this configuration-only review.

## Validation and limits

After the correction, the common suite, full logger suite, both complete
production manager fixtures, 128 logging checks and production API projections
pass. Both MSPM0 production targets and the A8 logger compile. The merged
production tree matches the tested correction tree.

The review does not establish physical behavior. Board-specific SPI/register,
reset/application/recovery timing, contention, stack watermark and logging-load
checks remain pending under the [implementation validation index](CAN-FD_Control_Implementation.md).
No firmware was flashed; GitHub issues remain open.

Standards: one nonblocking heuristic resolved. Spec: one P2 resolved. Neither
axis has unresolved findings.
