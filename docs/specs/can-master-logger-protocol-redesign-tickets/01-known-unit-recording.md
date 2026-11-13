# T01: Record one known sample unit through the new protocol

## Parent

[Specification #200](https://github.com/benconnor1972/BODAQS/issues/200).

## What to build

A narrow host walking skeleton: known sample input from one unchanged CAN source
passes through a versioned master-prepared 256-byte sample unit, logger RAM
custody, compact BDQ writing and independent offline verification/decoding.
It uses production components at the existing integration seam, not a second
simulated protocol implementation. One bounded outstanding unit is sufficient
here; pipelining, physical acquisition and full quality assessment follow.

## Acceptance criteria

- [ ] Document the initial wire/recording version, full stream binding, compact
  unit identity, canonical upstream checksum coverage and ACK custody contract.
  Account for both intended frame sizes, control reserve, memory placement and
  inherited capacity/coverage gates before freezing layout choices. This is a
  feasibility budget, not reused old-frame timing or a hardware capacity pass.
- [ ] Known signed axes and source/sequence/configuration identity reach the
  new explicitly versioned BDQ payload and independent decoder exactly, with
  stream definitions retained and historical BDQ fixtures unchanged.
- [ ] The normal sample unit fits one 256-byte transfer; the master prepares the
  next useful reply without a fragment request for every piece. Never assume a
  pipelined reply answers the current request.
- [ ] Length, physical CRC, scope and ACK safety are checked before bounded RAM
  custody. Corrupt/truncated/stale-context inputs do not retire unrelated data.
  A basic lost reply/ACK is retryable without duplicate decoded readings.
- [ ] A master-origin checksum survives recording and verifies offline. Inject
  post-acceptance damage with a freshly valid storage checksum and demonstrate
  upstream verification failure and explicit unverified/rejected status.
- [ ] The initial sample path has bounded credit/ownership and safe profile entry;
  a mismatched pair cannot silently use the old measurement wire protocol.
  Single-unit repair here does not claim selective window behavior is complete.
- [ ] Carry normal essential control and raw timing through the new profile using
  the existing logical payload/authority semantics, sufficient for the first real
  START/sample/STOP path. Independent progress under pressure is added by T04;
  do not make T02 secretly depend on an unimplemented control transport.
- [ ] Reuse the existing production recording fixture with independent expected
  values. Any necessary small test-support prefactor lands first and keeps
  existing control/recording regressions green; do not build a new general harness.
- [ ] Candidate master/logger builds compile. Host results explicitly claim no
  physical throughput, electrical timing, full native timing or STOP qualification.

## Blocked by

None (can start immediately).
