# Link and restart containment (#172)

Software evidence, 5 November 2026. Requirements remain the
[acquisition contract](CAN-FD_Acquisition_Transport_Contract.md), particularly
Q106/Q109/Q119/Q140/Q144, and its existing control authorization rules.
Physical qualification #175/#176 remains deferred; no device was flashed.

## Production behavior

`CanMasterManager::serviceMeasurementTransport` starts a fixed 300 ms recovery
window on a failed measurement exchange or a foreign response context. It keeps
the caller's immutable outgoing objects, partial assemblies, accepted object
identities, downstream admission and pending ACKs. It requests 64-byte STATUS
with a fresh token, ignores preloaded replies, and resumes only after matching
master boot, owning session, recording and context, active phase and valid
flags. A changed identity, an object integrity conflict or the original deadline
excludes remote participants and stops lease renewal. A later good response
cannot reopen this recording. Valid capacity observations remain separate from
link corruption. Healthy local recording continues.

`AcquisitionControl::Outcome::excluded` is a per-node terminal result. The
ordinary/protected state machines correlate actual node replies, including a
stale expected boot rejection; they do not invent announce/status receptions.
Renewal rejection, timeout and local lease expiry exclude the participant.
Actual node bus-off invokes the existing node exclusion hook, so a recovered bus
cannot renew or join the old recording. A confirmed master change excludes all
remote participants. PREPARE/START cannot reopen an excluded peer.

Optional health observations supplement protected renewal: at most one immutable
acquisition snapshot starts every two seconds globally, fairly among started,
leased participants. Each costs OPEN + six READ_PAGE + RELEASE_SNAPSHOT = eight
CAN requests and eight replies before retries. All of these post-START requests,
including retries, share the existing **4 requests/s, burst four** diagnostic
bucket. They do not use the lifecycle 20/s bucket. Initial prepared-state
snapshots remain essential lifecycle work. Protected renewal/STOP takes priority.
Busy/aged optional reads do not replace the successful user operation result or
stop an otherwise healthy participant. Four-node admission must charge the
actual health request/reply and retry load, not a single timing-evidence frame.

## Administrative cleanup

Startup first uses nonce-correlated legacy MODE_INFO with expected master boot
zero. An active master therefore remains discoverable without a rejected legacy
identity probe or a cached control boot. Discovery is observational and does not
confirm acquisition. The stopped-only administrative client reads existing
retained inventory for current boot/UID; it performs no CAN discovery scan.
Duplicate/stale/unknown identities cannot advance cleanup.

For each present participant the client opens a fresh acquisition snapshot,
reads/releases it, verifies current boot, stopped acquisition, invalid lease and
the observed recording, obtains a fresh authority challenge and binds a new
session. It then explicitly fences old data and releases membership. Request
and result identities are checked throughout. A lost BIND result retains its
exact uncertain request rather than silently issuing a replacement challenge.
Cleanup cannot send APPLY, PREPARE, START or RENEW over the active-mode legacy
route; the master enforces that allowlist independently of the client.

A rebooted, empty, stopped node may accept an explicitly named old-record fence
under freshly bound authority. This creates only a bounded cleanup tombstone,
requires the real acquisition hardware owner to retire TX, and permits release
only for that named tombstone. Another/live membership is rejected. The terminal
recording identity includes its session, so a fresh session can later allocate
the same numeric recording ID without reviving an old command.

The master accepts a current-discovery-boot fence only after the node explicitly
reports successful completion. It retires selected/queued receptions and waits
for its existing physical SPI/DMA boundary proof. The client observes that proof
before explicitly closing the old context. Logger assemblies, deduplication and
ACK state retire after those fences. Master transfer retention is keyed by the
full boot/session/recording/context binding, including numeric-context reuse.
Missing nodes or unverified retirement remain unavailable rather than being
declared cleaned from silence.

Fault cleanup waits while healthy local recording runs. The original operator
STOP still owns the five-second tail deadline; repeated STOP does not extend it.
Tail cutoff and pending storage finalization remain distinct from membership
cleanup. The closed admission gate protects the file while conservative cleanup
continues. Existing discarded-tail counters and unknown/incomplete source-tail
summary coverage are preserved; successful file close is not complete-tail proof.

## Verification

Host fixtures exercise actual logger coordination, master/control state machines,
fragment codecs and node lifecycle, substituting only time/SPI/hardware events:

- `test_measurement_runtime.py`: same-boot short outage, exact 300 ms cutoff,
  confirmed master reboot, foreign context and fresh status correlation.
- `test_remote_imu_lifecycle_runtime.py`: normal prepare/start/STOP/tail/fence,
  node and master reboot, bus-off, lease expiry, failed-link exclusion while
  locals run, and explicit cleanup after stopping. Restart cleanup includes
  five seconds of lost successful BIND replies, stale boot/session commands and
  the independent physical-master retirement gate.
- Common fixtures check diagnostic burst/refill boundaries, session-scoped
  retirement of old retained data/ACKs, fragment conflict checks, terminal STOP
  and existing control authorization.
- Existing acquisition, configuration recovery and recording-handoff runtime
  fixtures remain regression checks.

Explicit target builds use G3507 node and G3518 master TI Arm Clang with SDK
2.11, plus PlatformIO `bodaqs_s3_mini_n4r2` for the A8 logger. Host tests/builds
do not qualify disconnect/reset/halt behavior, physical lease latency, bus
utilization, runtime stack headroom or the 25 us rearm/100 us mutex targets.

Final validation includes integration `c2fdbbd` (#170/#171): the complete firmware
host target, all thirteen common executables, and capture/SPI plus all eleven
node acquisition scenarios pass. Focused lifecycle, measurement and four-node
control ownership regressions also pass after the final unavailable-context
guard. Explicit target builds pass: G3518 master FLASH 40,320 bytes, SRAM bank 0
50,358 bytes; G3507 node FLASH 40,472 bytes, SRAM 10,984 bytes, including reserved
stacks. The A8 build reports 264,916 bytes static RAM and 2,018,341 bytes flash.
These map sizes do not establish measured runtime stack/heap headroom.
