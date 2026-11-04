# IMU software review resolutions

Final review base: `b80fc5254299dddd0b4e6d4a762753b8e3f8392c`.
The changes below address both final Standards findings, its lifecycle phase
judgment call, and the final Spec finding. They preserve public protocol/wire
values, 224-byte companion records, 28-byte samples, and unknown-alignment
recordability. Production remote admission remains unqualified before PREPARE.

## Raw MCAN ISR overflow

The queue rejection path now uses the canonical TI standard-ID decoder
(`id >> 18`, eleven bits), as the normal RX path already did. Rejected sample
counts/ranges and essential evidence losses therefore reach stage-5 accounting.
The adapter regression fills the actual eight-entry queue with raw MCAN IDs,
then checks literal node-3 sample range 40?44, epoch 7, capture ordinal 9,
node-2 snapshot loss, and essential timing-definition loss. It failed against
the reviewed implementation before the decoder correction.

## SPI physical retirement ownership

Only the main-loop service owner changes retirement flags, ingress/reception
heads, retained objects and mode state. Every successful node fence advances a
main-owned retirement generation. A short interrupt-masked mailbox publication
pairs that generation with the measurement context. The hardware adapter captures
that pair, disables DMA at an idle high-CS boundary, retires only DMA-owned or
fully published TX buffers, resets the peripheral/FIFOs, and publishes matching
proof before rearming. The main owner commits service retirement only if both
identities still match. Generation saturation fails closed.

An unpublished inactive TX buffer remains owned by its main-loop writer. The
writer removes data responses before publishing while retirement is pending;
control responses survive both paths. ISR work retains the bounded hardware
reset/rearm path; service parsing and ring mutation never run in the ISR.

The native master adapter runner compiles function bodies directly from production
`main.c` and the service result handler against simulated TI hardware. It injects
CS preemption immediately after the real handler publishes pending retirement,
before its subsequent fenced-state store. This reproduced the original failure.
It also checks a newer node fence arriving before old proof consumption, changed
context, no-clock/low-CS/busy-peripheral cases, unpublished writer ownership,
control reply preservation, and main-only ring retirement. Hardware simulation
establishes software ownership/ordering, not electrical or timing qualification.

## Recording-scoped source epochs

A fresh recording may reuse the eight-bit source-epoch space only after verified
stopped state and completion of the hardware transmit-idle fence. PREPARE alone,
a different recording ID alone, or another segment within the same recording
cannot reclaim that space. Recovery and START retain their existing exhaustion
guards. No persisted data migration is required.

The real node register/FIFO/capture/DMA fixture now completes 260 recordings
without reinitialization. Each successor has first source epoch 1. Scenario 10
still requires exactly 254 recoveries and terminal exhaustion within one recording;
it additionally verifies STOP/FENCE followed by a valid fresh recording after that
failure. Both turnover regressions failed before their fixes.

## Lifecycle phase vocabulary and validation

`AcquisitionControl::Peer` now uses a private named phase enum, preserving values
0?6 and existing transitions. The existing acquisition-control runtime regression
covers preparation, renewal, pending START, STOP and immutable snapshot behavior.
The full node test target includes scenario 13. The master test target includes
timing plus the raw MCAN/CS adapter runner; the source-pinned candidate runner
now executes that master target alongside all prior host/analysis/target checks.

Focused checks passed: complete node native test target (scenarios 1?13), master
native target, and acquisition-control runtime regression. Final source/artifact
identities and full-suite/build results belong to the fresh external candidate's
`BUILD_MANIFEST.json` and `SHA256SUMS.txt`, using the documented
[candidate workflow](CAN-FD_Software_Candidate_Bundle.md).
Physical qualification #175/#176 remains deferred; no probe, upload or flash is
part of these checks.
