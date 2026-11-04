# Sensor lifecycle and deferred recovery

Firmware sensor lifecycle callbacks are ordered around a logging session as
follows:

1. `prepareLoggingStart()` / `validateLoggingStart()`
2. `onLoggingStart()`
3. acquisition
4. `onLoggingStop()` after the sampler has stopped
5. queued sensor rows and the BDQ final summary are written
6. the log file is closed
7. `onLoggingFinalized()`

`onLoggingStop()` must leave session diagnostics intact because the BDQ writer
collects them while finalizing the file. `onLoggingFinalized()` is the safe
place for recovery work that resets diagnostics or sensor state.

## I2C recovery policy

I2C sensors may continue ordinary acquisition attempts during logging so a
transient communication failure can recover without intervention. They must
not reset a bus, reinitialize a sensor, or retry volatile configuration writes
while logging. This keeps potentially disruptive control transactions out of
the acquisition path and avoids disturbing other devices on a shared bus.

The AS5600 rotary-angle and I2C string-pot implementations detect an unresolved
run of at least three read failures, or an unresolved configuration failure,
at session stop. The AS5048B angle implementation applies the same read-failure
policy without AS5600-specific configuration writes.
It records the original failure diagnostics in the completed BDQ, then uses
`onLoggingFinalized()` to:

- probe the configured address;
- reapply the configured volatile slow-filter setting;
- acquire a fresh raw sample;
- read back the device configuration and diagnostics; and
- reset its asynchronous sample snapshot.

If recovery is incomplete, another attempt remains pending for the next safe
post-session boundary. Logging remains resilient: a missing AS5600 or AS5048B
does not block starting or completing a session.

This first implementation is deliberately sensor-level. It does not reset or
recreate the shared I2C bus. Whole-bus recovery should be added only if field
evidence shows that sensor-level recovery is insufficient, with explicit
coordination for every device on that bus.

## Idle configuration edits

Web sensor forms and JSON sensor create/update/delete requests share
`SensorConfigEdit`: validate, save, then rebuild the local sensor runtime and
analog sample-rate configuration. Successful edits do not require a restart.
Requests are rejected while recording or in upload mode. Invalid requests and
failed saves restore the previous in-memory sensor settings, headers and
calibration caches; file replacement uses the storage layer's temporary file and
backup mechanism.

JSON results report `saved`, `runtime_rebuilt`, and `restart_recommended`.
A runtime teardown failure reports `saved=true`, `runtime_rebuilt=false` and a
specific error; desired settings remain saved. These fields describe logger
configuration, not remote hardware readiness. Sensor JSON includes saved
provider/endpoint assignments and generic saved parameters outside the driver's
parameter schema. Hidden driver fields remain hidden.

Unchanged local sensor identities retain runtime mute across a rebuild; an
explicit saved mute change takes precedence. Menu runtime mute and assisted
calibration retain their existing live behavior;
there is currently no menu action that edits the persisted sensor list/type.
Remote configuration reconciliation is separate work under the node-control
contract.

Run `python firmware/tools/test_sensor_config_runtime.py --compiler g++` after
installing the A8 PlatformIO dependencies (`pio pkg install -d firmware -e
bodaqs_s3_mini_n4r2`). The host fixture compiles production configuration storage,
the transaction, and web/JSON mutation handlers with storage and hardware at
controlled boundaries. On A8 hardware, still verify a sensor edit, calibration
and runtime mute through the browser/menu, failed SD persistence, and recording
locks; host tests and target compilation do not establish physical timing.
