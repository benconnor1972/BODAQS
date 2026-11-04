# CAN-FD configuration implementation and validation

Updated: 4 November 2026. Integration branch:
`integration/can-fd-node-control`, based on `b840736`.

The [node control contract](CAN-FD_Node_Control_Contract.md) and network
protocol section 13 define the behavior. This index records implementation
and verification separately. No firmware upload or physical validation was
performed during this implementation.

## Implemented scope

| Tickets | Integrated behavior |
|---|---|
| #153 | Shared idle sensor validation/save/rebuild with rollback on invalid input or persistence failure |
| #154 | Bounded whole-record interrupt queues; transport processing in the main loop |
| #155 | Typed SPI/CAN control, bounded master retries and explicit transport uncertainty |
| #156 | Immutable paged capability/effective snapshots and current/history masks |
| #157 | Boot/session authority, challenge/bind/release and one mutation sequence owner |
| #158 | Staged complete requests, verified physical disabled configuration and fresh no-op readback |
| #159 | Canonical remote LSM type and profile 1/v1, saved desired versus verified effective evidence |
| #160 | Explicit legacy remote BMI migration preserving installation metadata |
| #161 | Bounded idle recovery, scoped counter preservation and historical provenance |
| #162 | Remote runtime mute, early recording locks and bounded logging-start handoff |

All ten software slices are integrated. GitHub issues remain open; local
implementation does not close them automatically. Physical acceptance remains
pending.

Final code integration: `d39891f2185fecb8f08a55927dae5875b65206f4`.
Both [review axes](CAN-FD_Control_Review.md) completed with no unresolved
findings after correction and independent verification.

The profile is configuration-only. Enabled-stopped runs sensing engines at
nominal 3333 Hz, +/-32 g and +/-2000 degrees/s, with the confirmed filter
policy. Explicit disable uses zero ODR. Neither mode collects, sequences,
batches or transports samples. Acquisition readiness remains false. Nominal
scale/rate metadata is distinct from measured timing and signal performance,
which remain unknown.

## Software evidence

The integrated slices pass the portable CAN/SPI/control host
suite, logger host suite and production configuration/API runtime fixtures.
Tests include independent wire vectors, lost replies, duplicate identities,
staging expiry, no-op revisions, hardware-boundary fault injection and
current versus historical evidence. Enabled and disabled exchanges run through
the real SPI/CAN codecs, master exchange, node authority/apply/backend and
snapshot observer with a deterministic register/time fake.

The full logger suite includes both complete production manager fixtures for
recovery and recording handoff, 128 logging start/stop/finalization checks,
remote runtime mute and configuration/migration entrypoints. Recovery scenarios
cover same-boot outages, node/master restarts, all lost COMMIT/query replies,
sensor faults, independent peers, malformed cached results, replacement
provenance, entropy failure and millisecond wrap. Recording tests cover every
apply phase, pending transport, uncertain admission, cancellation and immediate
desired edits after stopping.

Both MSPM0 production targets compile with MSPM0 SDK 2.11.00.07,
SysConfig 1.28.1 and TI Arm Clang 5.1.1 LTS. The A8 logger compiles with
PlatformIO environment `bodaqs_s3_mini_n4r2`. These checks establish software
and target integration; they do not establish electrical behavior or physical
timing. Both MSPM0 targets reserve 2048 bytes for stack; measured high-water
is still required.

Build commands are in the [CAN-FD firmware overview](../../firmware/can-fd/README.md)
and `skills/firmware-build/SKILL.md`. The portable host suite is
`firmware/can-fd/common/test`; the full logger suite is `firmware/test`.
Prefix the installed MinGW `ucrt64/bin` on `PATH` when using that compiler.
The additional production JSON projections are reproducible with
`firmware/tools/test_control_apply_runtime.py` and
`firmware/tools/test_control_authority_api.py`.

Remote temporary mute is a bounded runtime override separate from the saved
muted default. It survives unrelated rebuilds and clears on configured
identity/assignment/type/default changes or reboot. Starting/running/stopping
locks reject edits before saved or aliased parameter mutation. Logging-start
admission freezes new remote mutations and drains existing ownership with an
original 5500 ms local ceiling; the recovery watchdog can quarantine earlier.
An already accepted COMMIT cannot be cancelled. During transport failure its
hardware application may finish after local recording begins; uncertainty
stays explicit and remote acquisition remains excluded. These local deadlines
are not physical cancellation or timing guarantees.

## Physical acceptance still required

Record actual board revisions, firmware commits, logger/master/node boot
identities, instrument setup, observations and pass/fail results using:

- [Deferred transport verification](CAN-FD_Deferred_Transport_Verification.md)
- [Control inspection verification](CAN-FD_Control_Inspection_Verification.md)
- [Authority verification](CAN-FD_Control_Authority_Verification.md)
- [Disabled IMU verification](CAN-FD_Disabled_IMU_Verification.md)
- [Enabled-stopped IMU verification](CAN-FD_Stopped_IMU_Verification.md)
- [Legacy migration checks](CAN-FD_Legacy_IMU_Migration.md)
- [Idle recovery verification](CAN-FD_Idle_Recovery_Verification.md)
- [Remote mute and recording verification](CAN-FD_Remote_Mute_Recording_Verification.md)

Outstanding evidence includes GPIO/SPI/CS levels, actual sensor register
readback, reset/application deadlines, inspection responsiveness under load,
stack high-water and fault containment. Sample/FIFO acquisition, settling,
native-clock calibration, measured ODR and amplitude/phase/filter-delay
qualification belong to later work. Acquisition/start/stop/lease wire commands
remain reserved.

Different UIDs observed at one strap address during a master powered interval
remain a duplicate installation fault. Replacement qualification requires a
fresh master powered interval and unambiguous discovery; a stale timeout does
not clear the duplicate latch.
