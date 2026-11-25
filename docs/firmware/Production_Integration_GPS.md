# Production DAN-F10N GPS integration (#224)

The production recorder keeps the existing UART/UBX NAV-PVT acquisition owner.
Each received PVT observation enters a separate `<sensor>_native` BDQ v2 stream;
GPS no longer relies on float primary rows. The catalog binds the stream to its
configured sensor identity, UART port, baud, requested update rate, validity and
staleness policies, quality selection, and enabled position/altitude/motion outputs.
The existing sensor assignment and configuration UI remain the configuration source.

`bodaqs.gps_nav_pvt.v1` uses 64-byte little-endian records:

| Offset | Field | Representation |
| --- | --- | --- |
| 0/4/8 | sequence / receive tick / status | uint32 / uint32 microseconds / uint16 |
| 12/16 | latitude / longitude | signed int32, degrees times 10^7 |
| 20/24/28 | MSL altitude / ground speed / course over ground | signed int32 mm / mm per second / degrees times 10^5 |
| 32/36/40/44 | horizontal / vertical / speed / course accuracy | uint32 in the corresponding native units |
| 48/52/56 | receiver iTOW / receiver UTC / local receive time | uint32 ms / Unix seconds / monotonic ms |
| 60/62/63 | receiver evidence / fix type / satellite count | uint16 / uint8 / uint8 |

Receiver evidence bits are have=1, fixOK=2, invalidLLH=4, dateValid=8,
timeValid=16. Unknown UTC is stored as zero with absent validity bits; it must not
be interpreted as an epoch reference. No RTC is set, no receiver UTC alignment is
claimed, and local receive time is explicitly **not receiver measurement time**.
Course is course over ground, not a direct bicycle heading measurement.

The queue reserves 128 records before recording, preferring PSRAM through
`DynamicSpscQueue`. Acquisition allocates no per-observation memory. Full queues
count drops, preserve sequence gaps, and mark the next retained row with
`discontinuity_before` and `producer_queue_drop_before`. Final diagnostics retain
enqueue/dequeue/drop/high-water/final-depth evidence, including a loss at the tail
with no following row. STOP fences publication under the sensor mutex and advances
a generation so an in-flight pre-boundary observation cannot enter a later session.
The queue remains drainable until finalization; abandoned rows are discarded only
after final diagnostics. Mutation stays blocked until finalization. Restart clears
published session data and cannot replay the prior session's native queue.

Previews use the coherent published snapshot. They do not read UART, pop native
records, or advance recording freshness. Missing GPS produces no fabricated row;
no-fix observations retain all native evidence with sensor-error status. Stale
published previews retain the existing configured invalidation behavior. Receiver
silence appears as missing observations and receive-time gaps, without repeating
last-known coordinates into the stream or invalidating independent healthy sources.

The ordinary `load_bdq_session` importer retains the integer stream and produces
`<sensor>_native_engineering` using float64 scaling. It publishes the established
GPS signal registry for normal source discovery. Default/fresh policies suppress
no-fix coordinates, altitude and motion; time-only/unknown fix types, source
errors and impossible coordinate ranges never establish a valid position. Ambiguous
sensor identities remain raw. latest-with-status preserves the requested
receiver values alongside validity. Quality evidence remains available. No samples
are held, interpolated or extrapolated across missing/stale intervals. UTC values
are exposed only with receiver date/time validity and never prove cross-source UTC
alignment. Unsupported representation/configuration stays raw with a warning.

Validation: `firmware/tools/test_gps_native_runtime.py` compiles the actual GPS
sensor implementation against an independent receiver/UART model, exercises
missing/no-fix/stale data, repeated previews, mutation guards, STOP/restart,
queue overflow and tail counters, and sends its real catalog and native bytes
through the ordinary importer. `analysis/tests/test_gps_native.py` checks native
coordinate precision, signed altitude, motion, iTOW, unknown representation and
GPS source discovery. The `bodaqs_a8_production` target compiled successfully.
These checks do not qualify electrical wiring, satellite reception, UART overload,
physical receive latency or sustained mixed-load performance. Bench verification
with the actual A8 and DAN-F10N, including disconnect/reconnect and STOP/restart,
remains required before claiming hardware qualification.
