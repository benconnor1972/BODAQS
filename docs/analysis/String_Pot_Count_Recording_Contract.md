# String-pot count recording

Production A8 recordings retain AS5600 analog and I2C string-pot observations
in a sensor-bound `<sensor_id>_counts` BDQ v2 native stream. ADC acquisition still
uses the existing unsigned twelve-bit count domain. The signed unwrapped count
represents firmware turn tracking; it does not add ADC measurement precision.
The ADC owner publishes analog observations, and the existing I2C worker owns
digital observations. Neither preview nor calibration reads acquire hardware.

## Representation

The acquisition payload schema is `bodaqs.string_pot_counts.v1`; its profile is
`string_pot_counts_v1`. Integers use little endian. Analog records are 24 bytes;
I2C records are 40 bytes, adding receiver angle/diagnostic evidence.

| Offset | Type | Field |
|---|---|---|
| 0 | uint32 | scheduled acquisition-slot sequence |
| 4 | uint32 | logger monotonic observation tick, microseconds |
| 8 | uint16 | common BDQ status flags |
| 10 | uint16 | reserved, zero |
| 12 | uint16 | wrapped count |
| 14 | uint16 | tracking quality |
| 16 | int32 | firmware unwrapped-count estimate |
| 20 | uint32 | tracking epoch |
| 24 | uint16 | I2C ANGLE register count |
| 26 | uint8 | I2C device status |
| 27 | uint8 | I2C AGC |
| 28 | uint16 | I2C magnitude |
| 30 | uint16 | I2C auxiliary validity |
| 32 | uint32 | I2C raw-read failure count |
| 36 | uint32 | I2C diagnostic-read failure count |

Auxiliary validity bits are 1 for a current raw read, 2 for a current ANGLE
read, 4 for available diagnostics and 8 for reused raw data. Available diagnostics
may be older than the raw read; the bit does not assert a simultaneous sample.
Unknown auxiliary values remain unavailable even when their numeric slot is zero.

## Tracking evidence

| Quality bit | Meaning |
|---|---|
| 1 | Origin is assumed; absolute physical turns were not observed. |
| 2 | Analog settling hold; unwrapped count is held. |
| 4 | Missing observation or skipped scheduled acquisition slots. |
| 8 | Unresolved tracking uncertainty, retained until a new tracking epoch. |
| 16 | Invalid input; do not advance tracking from this observation. |
| 32 | First valid observation establishes the tracking epoch. |
| 64 | Signed tracking range exceeded; estimate is bounded and uncertain. |

The catalog embeds the actual modulus, wrap threshold and turn-zero assumption.
The recording configuration embeds source assignment, polarity, calibration
geometry, units and missing-calibration state. Settling timeout, an ambiguous
threshold-sized jump, invalid/missing observations and overflow preserve
uncertainty. A later apparently ordinary count does not prove a lost turn.

Skipped ADC rows and I2C service appointments produce source-sequence gaps and
tracking evidence. Queue overflow is a separate event: the next retained record
has BDQ discontinuity/producer-drop flags. Footer producer-drop counts and final
queue depth retain tail-loss evidence even when there is no subsequent record.
Saturated counters do not claim an exact known loss count. A file without its
final summary cannot establish a complete tail from retained counts alone.

START cannot erase an old pending queue. Once I/O has retired and final-depth
diagnostics have been taken, finalization may discard old unpersisted rows from a
failed session. A new session begins under a new tracking epoch.

## Normal import

Normal import preserves the integer stream and quality/epoch fields. A separate
`<stream_key>_engineering` frame uses the embedded `string_pot_geometry_v1`
snapshot to derive displacement from unwrapped counts. It does not consult the
current SD calibration. Unknown domains/identities/geometry remain raw-only.
Held, invalid, uncertain or unknown-quality observations have missing derived
displacement; a missing reset remains uncertain for that epoch. The importer
never presents firmware unwrapping as proof of physically unobserved turns.

Host tests cover real count-stream/queue/catalog and sensor/I2C adapters through
normal import, including preview equivalence, directions, holds/timeouts, gaps,
overflow, missing calibration, failure and restart. These checks do not qualify
physical settling, wiring, I2C capacity or a mixed-load performance envelope.
