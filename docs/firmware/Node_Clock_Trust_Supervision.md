# Node clock-trust supervision

This implements the foreground-clock-conservatism follow-up recorded during r18,
without relaxing sample identity, CRC or timestamp-association validation.

## Behavior

Previously, a foreground supervision gap of at least 65 ms permanently latched
`clock_untrusted`. A busy foreground does not establish that timer rollover
interrupts were lost. The new foreground call records its maximum gap only.

The 1 ms SysTick handler now observes progress of the native capture timer's
software high word, which only the serviced ZERO interrupt advances. A pending
ZERO bit does not count as progress. The nominal timer period is 65.536 ms;
the deadline is 68 ms from initialization or the last observed high-word change.
This allows rounded SysTick observation and IRQ ordering margin, while detecting
missing service before two timer periods can pass. Healthy foreground stalls
longer than one timer period are permitted when the interrupts keep working.

The supervision call performs bounded integer loads/stores/comparisons. It does
not read captures, consume interrupt status, allocate, log, or infer native ticks
from milliseconds. The fault latch writes its first diagnosis in a short
interrupt-masked section. Capture loss-counter exhaustion remains a trust fault.

STOP, capture-buffer discard and PREPARE do not clear an actual trust failure.
The existing node initialization clears it; automatic recovery with a new native
clock epoch is deliberately deferred. Other reason-35 producers, including IMU
timestamp-consistency and clock-epoch checks, remain unchanged.

## Diagnostic observation

The debugger-visible `gNodeCaptureClockInfo` has version 1 and these uint32 fields:

| Field | Meaning |
|---|---|
| `first_fault_reason` | 0: none; 1: rollover-service deadline; 2: capture loss counter exhausted |
| `first_fault_ms` | SysTick observation time of the first fault; zero is a valid time |
| `maximum_foreground_gap_ms` | Largest main-loop supervision interval since initialization |
| `maximum_rollover_age_ms` | Largest observed interval since rollover progress, including completed observation intervals |
| `rollovers_serviced` | Saturating diagnostic count of serviced ZERO interrupts |
| `supervisor_ticks` | Saturating diagnostic count of interrupt supervision calls |

First-fault fields remain unchanged after subsequent faults or buffer discard.
Read with the target halted or accept that a live multi-field read is not an
atomic snapshot. The diagnostic adds no CAN payload, BDQ field or logger API.

## Limits and validation

SysTick and capture interrupts must both execute. A debugger halt or global
interrupt blackout can coalesce SysTicks as well as timer events. This change
does not prove continuity across those conditions, reconstruct lost rollover
counts, or qualify inter-device clock alignment. Do not treat a restored trust
flag or a passing host fixture as physical timing qualification.

The actual capture source is tested with independent register inputs for a
500 ms foreground stall with continuing rollover IRQs, missing rollover service
with SysTick continuing, pending ZERO/ISR ordering, millisecond wrap, sticky
first-fault information, and unchanged capture/SYNC admission. The acquisition
fault fixture still verifies reason 35 and failed re-PREPARE after a true trust
failure. The ordinary node acquisition, SPI, STOP/fence and profile fixtures must
also pass, followed by an MSPM0G3507 acquisition-link target build.

Install the same new node image on all four IMU nodes, retaining their hardware
address selections. Keep the current logger/master/configuration unchanged.
After restarting all six boards together, wait for actual readiness, record a
short session, STOP normally and preserve the finalized BDQ and full serial log.
Then repeat START/STOP without restarting the nodes. Capture the failing node's
`gNodeCaptureClockInfo` before resetting if reason 35 recurs. A zero diagnostic
fault reason would point toward another reason-35 producer. USB enumeration
reliability remains a separate unresolved issue.

## Software verification

The previous foreground-gap behavior failed the new 140 ms healthy-delay
regression before the correction. Afterward, the complete node hardware-boundary
suite passed: capture, SPI and acquisition scenarios 1 through 19. Additional
native-profile 1667/833 fixtures passed normal cold/warm acquisition and persistent
clock-fault rejection. The target built successfully for MSPM0G3507 with
`CAN_LINK_PROFILE=acquisition` using MSPM0 SDK 2.11.00.07, TI Arm Clang 5.1.1.LTS
and SysConfig 1.28.1. Independent specification and standards reviews found no
blocking issue; their two minor diagnostic/test suggestions were incorporated.

The target map reports 42,608 bytes of FLASH and 13,265 bytes of SRAM including
the reserved 2,048-byte stack. `gNodeCaptureClockInfo` is present in the image at
`0x20202b1c`; use symbols rather than assuming that address in later builds.
These are build measurements. Physical IRQ latency and the combined-device
START/STOP tests remain pending; no node was flashed during implementation.
