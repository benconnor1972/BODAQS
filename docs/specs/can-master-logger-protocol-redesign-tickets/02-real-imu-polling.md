# T02: Capture and finalize one real IMU with new-protocol polling

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

Bring the first walking skeleton onto the matched master/logger pair and record
one real native-rate IMU without IRQ. Produce a scoped finalized file and offline
result early, before scaling the new implementation or starting another synthetic
optimization campaign. Existing CAN nodes remain unchanged.

## Acceptance criteria

- [ ] A compatible new profile enters explicitly and remains fixed for the
  recording. An incompatible master/logger pair reports an error before remote
  acquisition rather than selecting the old measurement protocol.
- [ ] Real CAN input is carried as self-contained 256-byte units through the
  production SPI adapter, recording writer and independent decoder. Report exact
  artifacts/configuration and expected source membership.
- [ ] Preserve known first-byte priming, CS retirement, active-buffer ownership
  and safe rearm behavior. Exercise partial/aborted transfers in the existing
  hardware-adapter seam and inspect physical behavior where evidence requires it.
- [ ] START, useful samples, essential interpretation/timing evidence and source
  final boundaries survive the path. Missing timing or tails are reported honestly;
  file close alone cannot claim complete delivery.
- [ ] Operator STOP and cleanup produce a bounded result, preserve custody while
  draining and permit a subsequent session only after safe fence/release. Broader
  pipelined fault combinations remain owned by T07.
- [ ] The run captures useful data/empty/replay counts, stage service, ingress and
  queue observations, storage and cleanup outcome without resetting the evidence
  before export. Automate collection at the existing bench/result interfaces.
- [ ] Produce the first real recording, independent decode and short scoped
  assessment; do not promote a smoke recording to ten-minute capacity qualification.
  Review any material shortfall before expanding the physical workload.
- [ ] Device flashing is performed only under an applicable explicit authorization;
  preserve raw evidence and keep unrelated device/configuration changes out of scope.

## Blocked by

- T01: Record one known sample unit through the new protocol.
