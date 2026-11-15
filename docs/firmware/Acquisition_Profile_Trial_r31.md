# r31 acquisition profile

The selected `bodaqs_s3_mini_n4r2_imu_acquisition_profile` environment extends
r30 health4000 with `BODAQS_ACQUISITION_PROFILE=1`. Other profiles retain zero.
The compile-time option requires the existing control polling observer and is
restricted to 0/1. The separate sample-selector correction is described in the
kit's runbook and regression evidence; it is not an instrumentation side effect.

## Ownership and capacity

Profile state is embedded in each existing 20-second acquisition-owner bin,
within the persistent PSRAM control bank. Allocation still occurs once before
ownership publication; there is no per-slot or per-recording allocation, and no
storage-task access to live acquisition counters. Existing null-allocation
behavior explicitly makes the entire observer unavailable. Storage and
acquisition continue to reset their separate banks, with the same release/acquire
pointer publication and final retired-context serialization gate. The optional
total-bank upper bound is 18,000 bytes, versus 10,100 without profiling. Actual
target layout and aggregate reservation must be recorded in kit validation.

Service timing is finished before either ownership-release path. Its destructor
does not write again after that finish. Burst/sleep observations require active
ownership acquired before reading the context and a matching context after the
interval; terminal groups and sleeps crossing retirement/new scope are omitted.
This intentionally leaves an incomplete final group rather than updating a
retired bank. Serialization remains under `control_poll_timeline` with the
existing version1 fields plus `profile_version=1`, stage names and optional bin
`profile` objects. No sample or protocol identity/format is changed.

## Stage interpretation

Each profile has arrays `calls`, `total_us` (64-bit), and `max_us` in this order:

| Stage | Scope |
| --- | --- |
| service | Actual acquisition service after owned admission, including nested work |
| selection | Lifecycle and scheduling work before transport call |
| transport | Complete manager transport call, including nested exchange processing |
| consumers | Posttransport control acceptance, downstream data callbacks and fence bookkeeping; before final fence publication |
| encode | Request buffer clearing/encoding before existing exchange timer |
| spi_wait | Shared bus lock plus minimum-start-spacing wait |
| spi_prepare | Bus transaction/CS/setup preparation |
| spi_transfer | CPU-serviced HAL transfer and any preemption |
| spi_finish | CS release/end-transaction work before unlock |
| decode | Response validation and measurement rejection bookkeeping |
| burst | Up to eight service calls and loop overhead, only if scope remains active |
| sleep | `vTaskDelay(1)` plus time to be scheduled again, only within same active context |

These are **wall intervals**, not CPU time. Service/transport/burst are nested;
do not sum them with their children. Counter updates have cost and outer scopes
include nested instrumentation overhead. SPI child counters are updated after
the decode endpoint so their update cost is not charged as decoder work.
SPI children are grouped by exchange-start bin; they do not individually record
the physical start of each phase. Other intervals are charged to their own
start bin, including a sleep that ends in the next bin. Unsigned subtraction
supports microsecond wrap for these short intervals. Capacity remains 36 bins
(12 minutes); overflow retains the existing explicit observer overflow status.

`cores` counts service entry on core0, core1, or host/unknown. This is not a
CPU-utilization measurement or proof that no migration/preemption occurs within
the service call. `reclaimed` counts selected sample, selected evidence, and no
data selection at otherwise idle control turns. `legacy_blocked_window_open`
counts such opportunities with at least one active node's old slot0 complete
and unadmitted while its current expected window entry is incomplete. It is a
candidate-state incidence count, not proof the master has data ready, or that
every such opportunity would have selected a different result with the old code.

## Validation and physical debt

The profile-bank test exercises target PSRAM allocation through SDK spies,
failure/retry/reuse, unsigned wrap, counts/totals/maxima/core serialization,
retired-context gating and independent owner resets. Native protocol fixtures
execute actual manager/acquisition scheduling but replace SPI with a synchronous
host stand-in. Their phase timing is explicitly zero and core is unknown; they
do not run the ESP32 task loop. The ordinary-fetch runtime's
`--control-state --acquisition-profile` mode checks complete MOSI bytes/order
equivalence with both observers disabled/enabled, including periodic request
loss. The selected integrated fixture supports `--acquisition-profile` to test
recording/cleanup and ensure diagnostic JSON remains compatible.

Target compilation covers the real HAL timing pointer and task core/sleep hooks.
Only hardware recording establishes real timing, core distribution, effect on
throughput and whether the proposed causes hold. Keep the r30 wire timing,
health4000, priorities, buffers, master and configuration for that comparison.
No changing priorities, affinity, ACK fairness or CRC guarantees in this trial.
