# Rotary preservation in production integration (#222)

AS5600 and AS5048B use a bounded native count stream in the production candidate.
Their existing I2C workers, bus assignments and acquisition rates are retained.
The AS5600 preserves 12-bit counts; AS5048B preserves its existing 14-bit counts.
This changes new production recording layout, not device precision. Historical
AS5600 native records and legacy float recordings remain readable.

The stream key is `<sensor_id>_native`, with payload schema
`bodaqs.rotary_counts.v1` and a 32-byte record:

| Offset | Field | Type |
|---|---|---|
| 0 | scheduled acquisition sequence | uint32 |
| 4 | logger monotonic acquisition tick, microseconds | uint32 |
| 8 | status flags | uint16 |
| 10 | reserved | uint16 |
| 12 | RAW angle counts | uint16 |
| 14 | optional AS5600 ANGLE register counts | uint16 |
| 16 | device status / AS5048B diagnostic register | uint16 |
| 18 | AGC | uint8 |
| 19 | auxiliary validity | uint8 |
| 20 | magnitude | uint16 |
| 22 | reserved | uint16 |
| 24 | cumulative read failures | uint32 |
| 28 | cumulative diagnostic failures | uint32 |

Validity bits distinguish current RAW (1), current optional ANGLE (2), available
diagnostics (4), and reused RAW (8). Diagnostics retain their existing refresh
cadence; availability does not claim they were read simultaneously with RAW.
Invalid/reused measurements remain inspectable as raw evidence and do not produce
trusted engineering angles. Missed service slots and queue overflow carry explicit
discontinuity evidence; final diagnostics retain dropped counts and pending tails.

Each source reserves 512 records, preferably in PSRAM, before activation. There
are no per-read allocations. STOP stops production while preserving pending
records for storage. Only finalization releases an unpersisted old-session tail.
The former AS5600 embedded 2048-record queue remains only in nonproduction builds.

Idle acquisition publishes snapshots at up to 50 Hz. Preview, raw calibration
inspection and ordinary sample inspection consume those snapshots without another
I2C transaction, FIFO consumption or advancement of wrap state. During recording,
the worker owns publication; the idle publisher stays parked through finalization.
The START preparation sample does not enter the native recording.

The embedded source catalog records family, count modulus, configured zero and
polarity, validity meanings and sequence basis. Normal import preserves native
records and adds `<stream_key>_engineering`, exposing absolute device degrees and,
when the embedded settings are valid, configured relative degrees. A configured
zero is explicitly not proof of physical installation calibration. Missing or
ambiguous identity, schema or modulus prevents reconstruction. Exact positive and
negative half-turn choices match firmware. Unknown timestamps remain unknown.

Software validation covers both count domains, wrap/polarity, missing calibration,
invalid health/read evidence, malformed bindings, queue overflow and retirement.
Representative physical I2C and preview equivalence checks remain qualification
gates; the target build and host models do not establish physical accuracy or a
new I2C admission envelope.
