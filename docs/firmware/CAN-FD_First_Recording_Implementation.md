# First real recording implementation evidence

Integration base: `f0418b9d73627342e64d64f61e497169efda4bba`.
Separate throughput prototype: `e0b58bc9372d6a0263bf43470768573383b0fadd`.
Governing decisions: [first recording design](CAN-FD_First_Real_IMU_Recording_Design.md).

## S1 / #188: restricted entry scope

Reuse `bodaqs_s3_mini_n4r2_imu_smoke` and its existing
`BODAQS_SINGLE_NODE_IMU_SMOKE=1` guard. The actual recording preparation path
accepts one reconciled CAN IMU and rejects a second node, another active sensor,
and active external ADC channels before allocation or acquisition authorization.
The only supported effective IMU profile remains `imu6_3333_32g_2000dps_v1`;
this work does not introduce rate substitution. The report remains `benchOnly`
and `qualified=false`; ordinary builds still require a qualified admission
profile. #177 and its frozen four-node no-go remain in force.

At nominal 3333 six-axis samples/s, useful axes demand is 39,996 bytes/s.
Five-sample packets require approximately 666.6 CAN receptions/s. Their retained
76-byte records cost 50,661.6 bytes/s before batch headers. Full 13-reception
batches cost 1008 bytes, about 51,687 bytes/s; partial heads sealed by evidence
and the 20ms timer cost more. These are arithmetic estimates, not service bounds.
Start/periodic/final observations, node/master SYNC, models/anchors, loss records,
control replies and SPI bridge observations must also receive service. Changing
healthy renewals from ten to one per second reduces authorization CAN traffic
from about 40 to 4 frames/s/node; it does not remove other control traffic.

The selected future transport is 256 bytes at requested 16MHz, 25us inter-CS
guard, boundary-only publication, with logical objects at most 1024 bytes.
Raw wire time is 128us plus guard per exchange before software costs.
Round17's 223.773kB/s accepted synthetic logical bytes is a feasibility proxy
only: it omitted normal CAN service and SD persistence and is not a measured
real-path guarantee. One-node raw demand is comfortably below that proxy, which
justifies an experiment, not production admission or a storage guarantee.

Retain the existing independent 64-record node queue, 128-record per-node master
retention and immutable selected head (up to 13 receptions). Logger allocation
is performed before authorization and reports actual reserved bytes. Master
256-byte RX/TX/DMA placement has not yet been implemented: S4 must inspect the
actual per-bank linker map and 2048-byte stack reservation. Spare aggregate RAM
cannot substitute for available RAM in the correct bank. S7 must record final
target maps and logger allocation after all slices are integrated.

Validation: `test_remote_imu_lifecycle_runtime.py --smoke` passes the existing
production-owner lifecycle scenarios and three preparation rejection scenarios.
The ADC scenario supplies a board with an external ADC; a board with no ADC
cannot model this demand. No hardware was accessed. Existing admission math and
historical capacity reports are unchanged. Local verified slice completion
satisfies implementation dependencies; GitHub issues remain open pending separate
closure authorization.

## Pending implementation

S2 #180 authorization; S3 #178 compact recording; S4 #179 real ACK/fetch;
S5 #182 raw observations; S6 #185 STOP/tail isolation; S7 #189 reviewed candidate.
S8 #190 is the subsequent manual physical capture. No physical results are claimed.

## S2 / #180: authorization implementation

The separately committed numeric change uses shared 5000ms lease, 1000ms renewal
and unchanged 300ms challenge constants in the real node issuer/expiry and logger
validator/scheduler. Focused node and actual logger-owner regressions pass.
Retryable renewal failures keep the previous confirmed deadline; retries are
bounded to one fresh attempt per second, without catch-up bursts. Initial proof,
terminal errors and identity/integrity failures retain terminal behavior.

Actual-owner tests cover lost challenge, proof accepted remotely with lost
result, repeated failed renewals through confirmed expiry, STOP during retry,
late proof after STOP, and millisecond/native-tick rollover. The disabled bind
loss injector needs its deadline initialized in the past at rollover; otherwise
it injects unintended loss. Node protocol tests preserve the separate freshness
window and readiness timeout. Both ordinary and restricted lifecycle fixtures
pass, including four-peer host regressions (not physical qualification).

The changed cadence exposed a real predecessor-result starvation during STOP
over an optional snapshot. A successor ordinary request could occupy every TX
turn while its pinned predecessor still lacked a response fragment. Transport
now fetches partial control predecessors before sending that lane's successor;
other lanes and terminal STOP remain serviceable. Existing end-to-end production
lifecycle regression reproduces the failure before this correction. Deadlines
are unchanged. Fresh lifetime/transport review is required before S4 proceeds.

Fresh review of `d9498ad..38f423f` found a stranded predecessor could override
healthy polling indefinitely, and a stale-success STOP test only replayed the
node request. Fix `6c7c933` bounds that override to a live successor's original
300ms outbox lifetime and tests actual encoded master/MISO success fragments
after STOP (whole replay and split across STOP). The production transport test
keeps node0's second ordinary fragment permanently lost while node1 data/control
progress; restoring the old condition fails that regression. Follow-up review
accepted both fixes. Additional passing owner cases inject matched errors
7/10/20/26, proof rejection reason20, and stale success while a newer retry is
pending: none creates extra authority. The reviewer inspected sources and
supplied results; physical CAN adapter/timing qualification remains deferred.
