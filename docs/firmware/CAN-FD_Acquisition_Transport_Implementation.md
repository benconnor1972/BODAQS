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
| #171 bounded loss and continuity recovery | Implementing | Depends on verified #169 |
| #172 link/restart containment and cleanup | Implementing | Depends on verified #169 |
| #173 four-node resource admission | Implementing | Depends on verified #170 |
| #174 integrated software acceptance | Pending | Depends on #171, #172 and #173 |

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
