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

The AS5600 rotary-angle implementation detects an unresolved run of at least
three read failures, or an unresolved configuration failure, at session stop.
It records the original failure diagnostics in the completed BDQ, then uses
`onLoggingFinalized()` to:

- probe the configured address;
- reapply the configured volatile slow-filter setting;
- acquire a fresh raw sample;
- read back the device configuration and diagnostics; and
- reset its asynchronous sample snapshot.

If recovery is incomplete, another attempt remains pending for the next safe
post-session boundary. Logging remains resilient: a missing AS5600 does not
block starting or completing a session.

This first implementation is deliberately sensor-level. It does not reset or
recreate the shared I2C bus. Whole-bus recovery should be added only if field
evidence shows that sensor-level recovery is insufficient, with explicit
coordination for every device on that bus.
