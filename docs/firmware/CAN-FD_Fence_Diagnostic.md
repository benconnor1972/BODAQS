# Logger fence diagnostic after the first recording

The r3 physical capture reached node0 Fence success but stayed in logger phase9
(Fence), localFence0, active SPI mode2, context available and zero reported
transfer errors. The master Memory Browser snapshot of the exact r3 image shows
`0x2020DE69=01` (fenced), `0x2020DE19=00` (retirement not pending), and
`0x2020DE18=01` (node0 fenced). These offsets were checked with TI ARM compiler
layout and the packaged map. This localizes the remaining stall to logger proof
recognition or retained-state retirement. It does not identify its cause.

The earlier copied BDQ is an in-progress prefix:120422 retained readings,
45831 known missing samples across2361 gap intervals,46078 reported source losses at
master software-retention stage6, and no STOP/footer in that copy. The user
confirmed it was copied before finalization. Do not infer a file-close failure
from that prefix alone. Its loss pattern is sustained, not an isolated packet.

A temporary production-owner host harness with status-response lags1,3,4,5,8
completed cleanup; it has not reproduced the physical stall. Artifacts are under
`drain-capacity-evidence/first-real-imu-implementation/fence-investigation`.

## Diagnostic change

Only the logger changes. AcquisitionControl publishes an observational snapshot
at100ms service cadence and fence/exit transitions; readers copy it under the
existing outcome lock. The same Wi-Fi-toggle rejection prints this snapshot.
It adds no SPI exchanges, allocations, periodic serial logging or changes to
retirement/ACK/authorization rules. Master/node images stay r3 acquisition images.

The output distinguishes pending control prerequisites, inspection attempts and
successful observations, cached mode flags, physical proof acceptance, and each
selected sample/evidence/shared inbox object/admission/pending ACK identity.
Flags for retained objects:bit0 complete, bit1 admitted, bit2 ACK pending.
The observation timestamp makes a stalled owner distinguishable from live retries.
These fields are diagnostic, never authority or data-completeness evidence.

Fresh ownership review caught a terminal snapshot after release race. Snapshots
now publish before releasing control ownership or exposing inactive status.
The final focused smoke/v2 lifecycle suite passes delayed physical-fence/queue
pressure snapshot assertions. Acquisition control retry/wrap/expiry and restricted
integrated storage/decoder tests also pass. The reviewer accepted final source
with no remaining findings. Target compilation and hashes are retained in the
new diagnostic bundle; physical reproduction is still an operator step.

## Asynchronous inspection proof fix

The diagnostic rerun showed allFence1, no pending control/mailbox masks,3792
inspection attempts and zero observations, while the shared timing inbox stayed
unadmitted. Master fencing was complete. The inspector only examined responses
inside its four-transfer burst; ordinary poll responses were not routed to it.
A matching status could therefore arrive between inspections and be discarded.

The new `tail-pressure-deferred-status` test preserves real master-produced
status bytes but delivers them on later ordinary SPI slots. Before the fix it
reproduces a fenced master and successful node Fence with a logger stuck awaiting
local retirement. After the fix it completes cleanup with the retained queue
records intact and explicit discard accounting.

The existing owner-only SPI receive path now routes matching status responses
through the unchanged inspection validator. A bounded latch retains the validated
observation until the inspector consumes it once. The initial/preloaded slot is
also considered when it matches the same live nonce. A new nonce,300ms expiry,
boot/context change, mode transition or manager restart clears the latch. Full
binding changes still revoke measurement readiness. Administrative cancellation
still requires confirmed readiness and the physical FENCED flag; RAM admission
and ACK rules are unchanged.

Nine hostile/positive cases cover ordinary-slot reception, wrong nonce/header
context, changed boot/session/record/body context, aged proof and replay after
consumption. Fresh boundary review independently ran these tests and found no
remaining findings. The physical DMA/FIFO proof mechanism is unchanged. This
software fix matches the observed failure, but still needs the operator to
confirm finalization on the hardware. Sustained sample loss remains separate.
