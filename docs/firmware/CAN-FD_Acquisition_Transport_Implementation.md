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
| #167 bounded fragmented transfer | Implementing | Depends on verified #166 |
| #168 leased recording lifecycle | Pending | Depends on #167 |
| #169 one-node native BDQ recording | Pending | Depends on #165 and #168 |
| #170 synchronization and analysis timing | Pending | Depends on #169 |
| #171 bounded loss and continuity recovery | Pending | Depends on #169 |
| #172 link/restart containment and cleanup | Pending | Depends on #169 |
| #173 four-node resource admission | Pending | Depends on #170 |
| #174 integrated software acceptance | Pending | Depends on #171, #172 and #173 |

At `9c20ead`, the combined common CAN/control suite (nine binaries), full logger
host/runtime suite, asynchronous storage-controller fixtures and explicit A8
`bodaqs_s3_mini_n4r2` build pass. The #166 master production build also passes.
The unchanged baseline BDQ analysis suite passes 42 tests with `PYTHONPATH=analysis`.
Final software acceptance and independent Standards/Spec review remain pending.

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
