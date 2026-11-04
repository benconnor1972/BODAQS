# Node control inspection verification (#155)

Implemented subset: `ControlInfoRequest`, typed submit/receipt/poll and
`GET_NODE_STATE`, including node-wide and fitted endpoint observations. The
layouts and semantics remain those in `CAN-FD_Node_Control_Contract.md`.
Other well-formed commands return `CONTROL_ERROR` with unsupported opcode;
malformed records are discarded. Session binding, descriptors, configuration
application and acquisition are deferred. Bootstrap identity/status/discovery
layouts and versions are unchanged. Master identity capability bit 2 advertises
the typed extension; ControlInfo features bits 0 and 1 advertise typed control
and observational reads only.

The portable codec, master exchange, node inspector and logger observer live in
`firmware/can-fd/common/protocol/bodaqs_control*`. Both TI targets compile the
canonical source; the ESP32 compiles it through `src/CanControlProtocol.c`.
The master uses TRNG for a fresh nonzero 64-bit boot ID. Exchange tick/transmit
runs outside interrupts. At most one pending exchange per address gets three
one-second attempts with identical request/transaction; duplicate SPI submissions
do not restart the timer. Exhaustion caches receipt state 5/reason 26/field 1
and frees the pending slot. A late reply cannot complete a replacement exchange.

The logger sends one submit/poll step per 100 ms while idle, inspecting each
available node and its fitted endpoints in rotation. It reads ControlInfo on
compatible probes. Master/node boot changes invalidate prior observations;
stale/duplicate/absent inventory entries are unavailable for inspection. The
Health screen adds `C:ok`, `C:...`, `C:!` or `C:--`; Enter retains its existing
fresh probe/discovery behavior. `/api/v1/status` adds `can_fd_master.control` with
support, info validity, feature bits, master boot and four node observations.
`master_boot_id`, `active_session_id` and endpoint `state_epoch` are unsigned
64-bit **decimal strings**. Existing bootstrap JSON representations are unchanged.
Node boot remains an existing 32-bit numeric identity. Numeric reason/field codes
are retained; unknown reasons have `reason_key: "unknown"`. `valid` and endpoint
`valid` distinguish current observations from retained values. Configuration
support and acquisition readiness are explicitly false in this subset. Fitted
endpoint masks report type/presence without implying stream or SYNC support.

Host commands (prefix PATH with `C:/msys64/ucrt64/bin` on Windows):

- `gmake -C firmware/can-fd/common/test test CXX=C:/msys64/ucrt64/bin/g++.exe`
- `gmake -C firmware/test test CXX=C:/msys64/ucrt64/bin/g++.exe`

Use the existing TI production makefiles with SDK 2.11.00.07 for both boards,
and `pio run -d firmware -e bodaqs_s3_mini_n4r2` for the A8 logger.

The production TI makefiles and CCS import specs reserve 2048 bytes of stack
on both targets. The generated SDK defaults (master 256/node 512) cannot cover
nested full CAN/SPI records and interrupt receive capture. Fixed service state
remains static; the larger explicit reservation covers bounded nested record
copies with margin. The linker maps must retain RAM headroom; final dynamic
stack high-water checks under CAN/SPI load remain a bench requirement.

## Manual bench checks (no upload performed)

Record A8, master and node hardware revisions and firmware commit IDs. Compile
success and host tests do not prove physical latency, TRNG freshness or wiring.

1. Cold boot and debugger-reset master several times. Confirm decimal master
   boot strings change and old control observations immediately become invalid
   when the next response or ControlInfo reports the new boot. Bootstrap probes,
   discovery and healthy local logging must continue to work with old masters
   that do not advertise bit 2.
2. With one node, confirm node-wide state has zero epoch and endpoint 0 has a
   nonzero boot-scoped epoch, zero session/pending operation and clear acquisition,
   lease, recording and application flags. GET_NODE_STATE must not change state.
   Node reset must invalidate observations until discovery/read refreshes them.
3. Disconnect the node after submission, or suppress its results in a bench
   transport harness. Confirm three attempts at one-second intervals, then poll
   receipt state 5/reason 26/field 1. A repeated identical submission must retain
   that terminal result; a fresh read must be accepted and succeed after reconnect.
   Delayed old results must not change the new result.
4. Send unknown well-formed commands and READ_PAGE without an implemented
   snapshot backend. Confirm correlated opcode 0x7F/reason 1, never page-shaped
   error bytes. Wrong versions/lengths/reserved bytes and nonzero unused GET_STATE
   fields must cause no structured node reply. Confirm bootstrap Health remains
   responsive under these faults, CAN load and handoff queue saturation.
5. Measure CAN retry spacing, SPI CS spacing/rearm, foreground latency and Health
   responsiveness on actual boards. No acquisition traffic or IMU configuration
   is enabled by this change; its physical application tests belong to #156/#157.
