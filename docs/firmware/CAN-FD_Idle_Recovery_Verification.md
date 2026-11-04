# Idle configuration recovery

This implementation reconciles saved desired IMU settings while idle. It does
not implement measurement collection, FIFO/sample transport or the reserved
recording/start/stop/lease wire commands. Configuration agreement is separate
from acquisition readiness. See [the control contract](CAN-FD_Node_Control_Contract.md)
and [network section 13](CAN-FD_Network_Protocol.md#13-node-configuration-and-effective-state-contract).

## Identity and fault behavior

A temporary probe/control-info/SPI outage invalidates current agreement without
forgetting the last confirmed master boot or the original endpoint observation.
Returning the same master boot preserves the logger session, scoped mutation and
transfer counters, and the exact BIND identity. Retrying that BIND cannot rewind
a later mutation counter, including its exhausted state. Node boot changes
invalidate that node's authority and require new binding/application/readback.
Saved names, profiles, calibration and installation transforms stay on the logger.

A confirmed different master boot requests one distinct nonzero random logger
session while idle. Returning the same boot on subsequent polls does not renew
it again. Failed/zero/repeated entropy fails closed. New binding preserves the
node's old accepted session; an explicit apply, including fresh verified no-op,
plus a coherent effective snapshot and endpoint epoch establishes new agreement.
No-op verification does not reset the sensor or advance its applied revision.
Mutation/transfer exhaustion renews the session while idle; counters never wrap
or restart under the same session/node boot. An exhausted observational snapshot
read allocator remains excluded, rather than wrapping its session-zero read IDs.

The existing master permits three identical CAN attempts one second apart.
Logger exchanges also have a 3500 ms local ownership limit, so missing SPI or a
cached malformed reply cannot pin the arbiter forever. Releasing that ownership
does not cancel admitted node hardware work or report rejection. Apply uncertainty
uses bounded operation inspection, then fresh snapshot/epoch readback. Agreement
can recover from effective proof even when the original outcome stays unknown.
Unknown admission without matching effective proof requests a distinct session
before another mutation; it never guesses the node high-water sequence.

A failed apply has a 30-second retry interval, with fresh readback and current
binding required before resubmission. Rediscovery after availability/boot change
and an explicit saved edit are recovery triggers. Bind transport/busy/challenge
failures retry at a bounded five-second interval; an expired unconsumed challenge
gets a new read identity. Healthy independent addresses can make progress without
waiting for every other fitted endpoint's snapshot. No worker, unbounded queue,
second SPI owner or second node mutation cache is introduced.

Unavailable or stale observations retain bytes with current=false and their
original observed node boot and hardware UID. Snapshot invalidation also cancels
between page exchanges. JSON includes the attempted operation session/boot and
one previous operation diagnostic, separate from desired generation and current
agreement. A fresh successful operation does not silently relabel old fault
proof or replace saved settings with observed values.

## Replacement qualification

Network section 9's duplicate-address latch remains strict for the entire master
powered interval. A second UID at the same address stays a duplicate after either
node disappears or remains silent indefinitely. No quiet interval clears it.
Compatible replacement qualification therefore requires removal of the old node,
a fresh master powered interval and unambiguous fresh discovery. The replacement
inherits saved address/endpoint settings with its own UID/boot provenance, a new
logger session, fresh application and verified readback. If both nodes remain
fitted across master restart, discovery latches the duplicate again and excludes
configuration. This does not promise automatic hot replacement within one master
powered interval.

## Host and target evidence

Run the normal common and firmware host suites. The firmware suite includes
`tools/test_control_recovery_runtime.py`, which compiles the entire production
CanMasterManager with deterministic time/random/GPIO/SPI boundaries and real
master SPI service, CAN codecs, authority, staged apply, register backend and
snapshot observer. It does not premark logger authority bound. The public manager
fixture checks same-boot SPI/stale-inventory recovery, changed desired payload
with increasing mutation sequence, exactly one distinct session on master reboot,
verified no-op, node resets during staging/commit and after acceptance, all three
lost COMMIT replies plus lost GET_OPERATION replies, repeated SPI failure,
malformed CAN replies, persistent sensor fault/recovery, independent silent peers,
replacement provenance/retained metadata and zero-entropy exclusion. The complete
scenario runs again across uint32 uptime wrap. Common tests additionally check
exact BIND retry after later mutations/exhaustion, snapshot cancellation between
exchanges, strict duplicate latch after long silence and relatching after reset.

Compile both production MSPM0 targets and A8 `bodaqs_s3_mini_n4r2`; host fake-clock
bounds and target compilation are not physical timing/electrical evidence.
Recording transition exclusion and local logging continuity use the separate
recording handoff guard and its production tests; no recovery mutation may bypass
that guard. After merging, run both production recovery and recording fixtures.

## Bench record (pending)

No device was flashed and no physical recovery measurements were taken for this
change. Use the wiring/equipment checks in
[disabled IMU verification](CAN-FD_Disabled_IMU_Verification.md). Before testing,
record master/node/logger board revisions, their firmware commit/build identities,
master and node boot IDs, node UID, logger control session and saved profile.

| Check | Expected observation | Measured evidence |
| --- | --- | --- |
| Unplug/replug CAN and master SPI separately | Current agreement false during outage; history retains original provenance; idle recovery without logger restart | Pending |
| Reset node before BEGIN, during staging/COMMIT, after acceptance | Old boot replies excluded; fresh authority/application/epoch; desired settings retained | Pending |
| Reset master while nodes stay powered | One distinct session; new acceptance; no-op preserves revision and sensor reset count | Pending |
| Lose COMMIT and inspection results | Bounded uncertainty/readback; no inferred rejection or duplicate hardware reset | Pending |
| Sensor bus/reset/readback fault, then restore | Current unknown plus historical proof; bounded retry; eventual idle agreement; healthy local logging continues | Pending |
| Two UIDs at one strap, then long silence | Duplicate remains latched; no configuration | Pending |
| Compatible replacement after master power cycle | Unambiguous UID discovery; saved settings/metadata retained; new provenance and fresh proof | Pending |
| Both UIDs still fitted after master restart | Duplicate relatches before configuration | Pending |
| Start/stop local recording while recovering | No new bind/apply during locked interval; bounded handoff; reconciliation resumes after finalized stop | Pending |

Measure actual SPI/CS levels, reset/apply/readback elapsed times, recovery delay,
main-loop responsiveness and stack watermark under fault/load. Record reason
codes and current/historical JSON before, during and after recovery. No sample,
lease-budget, measured-rate, phase-response or production acquisition claim follows
from these tests.
