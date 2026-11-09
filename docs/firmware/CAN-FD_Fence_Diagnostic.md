# Logger fence diagnostic after the first recording

The r3 physical capture reached node0 Fence success but stayed in logger phase9
(Fence), localFence0, active SPI mode2, context available and zero reported
transfer errors. The master Memory Browser snapshot of the exact r3 image shows
`0x2020DE69=01` (fenced), `0x2020DE19=00` (retirement not pending), and
`0x2020DE18=01` (node0 fenced). These offsets were checked with TI ARM compiler
layout and the packaged map. This localizes the remaining stall to logger proof
recognition or retained-state retirement. It does not identify its cause.

The earlier copied BDQ is an in-progress prefix:120422 retained readings,
45831 known sequence gaps across2361 intervals,46078 reported source losses at
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
