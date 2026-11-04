# Remote mute and recording transition verification

The configuration-only control scope is defined by
[Node Control Contract section 10](CAN-FD_Node_Control_Contract.md#10-agreed-logger-interfaces-and-compatibility-q67-q69)
and [Network Protocol section 13](CAN-FD_Network_Protocol.md#13-configuration-semantics-reserved-for-version-1).

## User behavior

Menu mute remains a temporary runtime action for local and remote configured
slots. CAN slots have no acquisition object: a bounded `MAX_SENSORS` overlay
supplies their runtime mute state to the same desired-descriptor reconciliation
used after a successful saved edit. It does not alter the flat-file `muted`
default, profile, assignment, calibration, or mounting parameters. JSON `muted`
is the saved default; `runtime_muted` reports the current runtime choice.

The remote overlay survives unrelated runtime rebuilds. It resets on logger
initialization or a change to its configured slot/name/type/normalized endpoint
assignment/saved mute default. Deletion clears the slot during rebuild; it does
not transfer an override to a subsequently added owner. An unchanged saved mute
default preserves an existing temporary override, matching local menu behavior.
A changed saved mute default takes precedence. Explicit saved form/API mute edits
continue through validation, persistence, rebuild, and desired reconciliation.

An idle remote mute requests an explicit disabled descriptor. An unmute requests
the validated enabled LSM profile. Neither action claims hardware success until
the staged transaction completes and fresh effective readback agrees. Muted
owners keep their assignments and installation data. Unassigned supported IMUs
receive explicit disable. Valid desired settings remain when hardware is absent.

Forms and JSON edits are rejected before parsing into shared parameter storage
while a recording starts, runs, or finalizes. The editor constructor and commit
also enforce that boundary. The response tells the user to stop and retry; the
rejected edit creates no pending desired change. HTML returns 423; HTMX returns
an actionable alert with HTTP 200 for its existing swap behavior. Remote menu
mute shows a recording-lock explanation and leaves the overlay unchanged. Local
runtime mute remains allowed without persistence or remote mutation.

## Start handoff and its limits

`LoggingManager::requestStart()` explicitly returns Failed, Pending, or Started.
`start()` returns true only after acquisition starts. The button entrypoint uses
the explicit result; the normal loop completes a pending start once. Repeated
requests retain the original handoff deadline. Failure releases admission;
`cancelStart()`/stop cancel a pending start. Sleep and analog-rail shutdown also
cancel pending starts. Configuration remains locked through final log drain and
metadata writing.

Before starting local acquisition, the CAN owner freezes new BIND/BEGIN/pages/
COMMIT. Already issued exchanges continue through the existing sole SPI owner.
Precommit local continuations are abandoned after their owned exchange settles;
no later page/COMMIT is queued. Uncommitted node staging expires under its
existing five-second bound. A possibly accepted COMMIT retains its immutable
identity and can be inspected using GET_OPERATION; it is never resent as a new
mutation. Uncertain operations reserve their sequence so later reconciliation
cannot reuse that identity with different data.

The logger handoff has a fixed original 5500 ms limit. The control client already
has a five-second knowledge deadline; 100 ms service cadence plus 400 ms scheduler
allowance gives this local upper bound under regularly serviced host-loop time.
The master independently allows three one-second CAN attempts, the node allows
two seconds after accepted COMMIT, and staging expires after five seconds. These
budgets overlap; 5500 ms is a bound on logger admission waiting, not a proof that
all physical work finished. Scheduler/transport outages can prevent observing an
accepted COMMIT. At the limit the continuation is quarantined, current proof is
invalidated, diagnostics report an uncertain outcome, and healthy local recording
can proceed. A previously accepted hardware application cannot be remotely
cancelled by this configuration-only protocol and could finish after fallback.

During recording no new configuration or authority work is submitted and remote
endpoints remain excluded from acquisition. After stop, idle recovery can inspect
and reconcile the valid prior desired settings. This is separate from rejected
recording-time user edits, which never changed desired state.

## Automated evidence

- `test_remote_mute_runtime.py`: production configured-slot get/set mute, missing
  remote acquisition object, assignment/default reset, metadata preservation,
  rejection before overlay changes, and local runtime mute while locked.
- `test_sensor_config_runtime.py`: production storage/editor and actual JSON and
  HTML handlers, including starting/running admission, aliased parameters,
  add/delete, persisted bytes, rebuild count, and HTMX actionable feedback.
- `test_logging_start_runtime.py`: production start/request/loop and button
  entrypoint; pending, repeated request, cancellation, preflight/start/file
  failures, and acquisition only after handoff.
- `test_control_recording_runtime.py`: complete production CanMasterManager over
  real SPI slot/master exchange/CAN/node/backend code, all observable apply
  phases and pending boundaries, pending apply as sole owner, SPI outage,
  repeated deadline, and no new mutating submissions during recording.
- Common `test_apply.cpp`: enabled/disabled recording/lease/acquisition guard
  injections before BEGIN and before COMMIT through real SPI/CAN, reason/field
  evidence, zero hardware writes, independent healthy backend, existing retry
  idempotence and verified enabled/disabled paths.

Production node recording/lease/acquisition flags remain clear in this stage.
Injected flags establish defensive admission behavior only. No reserved
acquisition/lease/recording command, sample transport, or readiness claim is added.
Host fake clocks and target compilation do not establish physical timing.

## Manual bench checks still required

Record exact logger A8, master MSPM0G3518, node MSPM0G3507 revisions and firmware
commits. Exercise mute/unmute with actual LSM register readback, retained metadata
and endpoint ownership. Start local recording at each transaction phase, unplug
SPI/CAN, lose COMMIT replies, reconnect during recording, and stop/recover. Measure
handoff/application timing, local recording continuity, scoped diagnostics and
current/historical provenance. Confirm no new mutation while recording and no
rejected edit appearing after stop. No flash or physical test was performed for
this implementation.
