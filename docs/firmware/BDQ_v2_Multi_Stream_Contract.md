# BDQ v2 Multi-Stream Data Contract

- Status: Accepted
- File format: `BDQLOG v2.0`
- Native stream contract ID: `bodaqs.native_stream.v1`
- Stream catalog schema: `bdq.stream_catalog.v1`
- Related formats: [BDQ v1 Format](BDQ_v1_format.md), [BMI270 IMU MVP Data Contract](BMI270_IMU_MVP_Data_Contract.md)

Firmware activation is explicit through
`log_format=bodaqs_multi_stream_binary`. The established CSV and BDQ v1
selections remain unchanged. In the current direct-I2C implementation,
stream 1 contains conventional logger-cadence channels using the logger
microsecond clock, while each BMI270 is emitted as a separate native stream.

## 1. Purpose

This contract defines the firmware-to-storage boundary and on-disk format for
recording multiple independently clocked data streams in one BODAQS session.
It supports both directly connected sensors, including several BMI270 IMUs on
I2C, and remote sensor nodes received over CAN-FD.

The contract separates three concepts which BDQ v1 combines in one logger row:

1. a session, which supplies common identity and wall-clock context;
2. a stream, which has its own schema, sequence and native clock; and
3. a timing observation, which relates a stream clock to the logger monotonic
   clock with explicit uncertainty.

The primary logger cadence no longer determines IMU acquisition or storage
rate. Conventional analogue and low-rate sensors may continue in a regular
primary stream while each IMU is stored at its native rate.

Raw sensor evidence remains authoritative. Clock fitting, resampling,
calibration, mounting transforms, filter-delay correction and coherence
analysis are host-side derived operations.

The key words **must**, **must not**, **required**, **should**, **should not**
and **may** describe normative requirements.

## 2. Scope and non-goals

BDQ v2.0 provides:

- multiple fixed-record streams in one append-only file;
- independent stream schemas and native timebases;
- loss and discontinuity evidence at sample boundaries;
- sparse timing observations with bounded host-clock intervals;
- interleaved chunks without requiring streams to share a rate or phase;
- power-loss recovery at the last complete CRC-valid chunk;
- uncommon session events such as user marks; and
- clean-shutdown summaries and diagnostics.

BDQ v2.0 does not define:

- the CAN-FD wire protocol;
- an I2C scheduling algorithm;
- on-device resampling or sensor fusion;
- compression, delta encoding or bit packing;
- variable-size records within a stream;
- dynamic stream creation or schema changes after recording starts; or
- a guarantee that independently clocked streams meet a particular phase
  accuracy.

Those mechanisms may evolve independently provided they preserve this
contract at the stream-ingest boundary.

## 3. Logical session and stream model

### 3.1 Session

A session is one recording file and has:

- a stable `recording_id`;
- a logger identity and firmware/hardware provenance;
- a logger monotonic clock;
- zero or one usable mapping from logger monotonic time to Unix time;
- a static catalog of one or more streams; and
- optional events and a clean-shutdown summary.

The logger monotonic clock must not step during a session. Wall-clock time may
be unavailable. Loss of wall-clock time must not prevent native stream capture.

### 3.2 Stream identity

Every stream has both:

- `stream_id`: an unsigned 16-bit identifier unique within the file; and
- `stream_key`: a non-empty UTF-8 string unique within the file and stable in
  the session model, for example `primary`, `imu_frame_001` or
  `imu_fork_001`.

`stream_id` is the compact on-disk reference. `stream_key` is the semantic
identity exposed to analysis. Consumers must not infer sensor type, mounting
position or transport by parsing `stream_key`.

Each physical clock must have a distinct `clock_id`. Two streams may share a
`clock_id` only when their native ticks are derived from the same oscillator
and counter domain.

### 3.3 Stream immutability

All stream descriptors must be registered before the first data chunk. A
stream's schema, record size, clock definition, sample-rate profile and sensor
configuration must not change during a session.

An ODR, range or filter change requires a new session. A source reset within a
session is permitted only when it is marked as a discontinuity and starts a new
clock-fit segment.

An unavailable configured sensor remains in the stream catalog and may produce
zero records. Firmware must not create synthetic invalid samples merely to fill
another stream's cadence.

## 4. Native stream-ingest contract

The logical firmware boundary consists of an immutable stream descriptor and a
sequence of record batches. A batch belongs to exactly one `stream_id` and
contains:

- zero or more fixed-size records in ascending stream sequence order;
- zero or more timing observations for the same stream; and
- batch-level producer diagnostics used for accounting.

A batch with no records is valid only when it contains at least one timing
observation. A batch must not mix streams.

### 4.1 Submission and ownership

Submission from an acquisition producer to the stream sink must be bounded and
must not perform an SD write. The production implementation should avoid heap
allocation on this path.

The sink must either:

- accept ownership or copy all records and observations in the submitted
  batch; or
- reject the batch without accepting a silent prefix.

If an implementation later supports partial acceptance, the accepted record
and observation counts must be returned explicitly and the rejected records
must be accounted as loss. Boolean success must never mean partial acceptance.

### 4.2 Backpressure and loss

Acquisition must not block indefinitely behind storage. When backpressure
causes records to be discarded:

- the producer or sink must count the discarded records when the count is
  known;
- the next persisted record must carry `DISCONTINUITY_BEFORE` and
  `PRODUCER_QUEUE_DROP_BEFORE` as applicable;
- the final summary must include the cumulative drop count; and
- an unknown loss count must be represented as a discontinuity with an
  explicit `loss_count_known=false` diagnostic.

There must be no silent loss.

### 4.3 Sequence semantics

The mandatory `sequence` field is a source-sample sequence, not a logger-row
number and not a file record number.

- It is an unsigned 32-bit modulo counter.
- It normally advances by the descriptor's `expected_sequence_step`.
- It advances for source samples before intentional storage decimation.
- A non-expected positive delta is loss unless explained by a declared reset.
- Duplicate or backwards observations are errors unless a reset boundary is
  present.

An intentionally decimated stream must declare its sequence step and mark
stored records using its stream-specific status flag. High-rate raw IMU
profiles should normally store every acquired native sample.

## 5. File and chunk envelope

All multibyte numbers are little-endian.

### 5.1 File summary

- File extension: `.bdq`
- Magic bytes: `42 44 51 4C 4F 47 00 02`
- Magic text: `BDQLOG\0\2`
- Format major: `2`
- Format minor: `0`
- File header length: 32 bytes
- Chunk magic: `BDQC`
- Chunk header version: `1`
- Payload CRC: reflected IEEE CRC32

BDQ v2 retains the BDQ v1 file-header and chunk-header layouts. The distinct
magic and major version make v1 readers reject v2 files visibly rather than
misinterpreting stream data as global rows.

Equivalent Python definitions are:

```python
import struct

FILE_MAGIC_V2 = b"BDQLOG\x00\x02"
CHUNK_MAGIC = b"BDQC"
FILE_HEADER = struct.Struct("<8sHHIQII")
CHUNK_HEADER = struct.Struct("<4sHHIII")
STREAM_DATA_HEADER = struct.Struct("<HHIIIHHI")
STREAM_RECORD_PREFIX = struct.Struct("<IIHH")
TIME_OBSERVATION = struct.Struct("<IIQQHHI")
```

### 5.2 File header

The 32-byte file header is:

| Offset | Size | Type | Field | Required value or meaning |
|---:|---:|---|---|---|
| 0 | 8 | bytes | `magic` | `BDQLOG\0\2` |
| 8 | 2 | uint16 | `format_major` | `2` |
| 10 | 2 | uint16 | `format_minor` | `0` |
| 12 | 4 | uint32 | `header_length` | At least `32`; `32` in v2.0 |
| 16 | 8 | uint64 | `created_unix_us` | Unix microseconds, or `0` if unknown |
| 24 | 4 | uint32 | `flags` | `0` in v2.0 |
| 28 | 4 | uint32 | `header_crc32` | `0` in v2.0 |

### 5.3 Chunk header

Each chunk begins with the unchanged 20-byte header:

| Offset | Size | Type | Field | Meaning |
|---:|---:|---|---|---|
| 0 | 4 | bytes | `magic` | `BDQC` |
| 4 | 2 | uint16 | `header_version` | `1` |
| 6 | 2 | uint16 | `chunk_type` | See below |
| 8 | 4 | uint32 | `sequence_number` | Global file-chunk sequence |
| 12 | 4 | uint32 | `payload_length` | Payload bytes |
| 16 | 4 | uint32 | `payload_crc32` | IEEE CRC32 of payload |

Chunk types are:

| Value | Name | Payload |
|---:|---|---|
| 1 | `Metadata` | UTF-8 JSON object |
| 2 | `StreamCatalog` | UTF-8 JSON object |
| 3 | `StreamData` | Binary stream-data payload |
| 4 | `Event` | UTF-8 JSON event collection |
| 5 | `FinalSummary` | UTF-8 JSON object |

Unknown future chunk types must be skipped after validating their header,
length and CRC.

### 5.4 Required ordering

A normal writer emits:

1. one metadata chunk;
2. one stream catalog chunk;
3. zero or more stream-data and event chunks in any interleaving; and
4. one final-summary chunk on clean shutdown.

Metadata and the stream catalog must precede stream data. The final summary is
optional and must not be required for recovery.

Chunk `sequence_number` starts at zero and normally increments by one across
all chunk types. It is independent of every stream sequence.

## 6. Metadata chunk

The metadata payload uses `format="bdq.v2"` and retains the compatible BODAQS
session, sensor, configuration and provenance objects used by BDQ v1.

Minimum fields are:

```json
{
  "format": "bdq.v2",
  "format_name": "BDQLOG v2",
  "recording_id": "260913_120000",
  "device_id": "A8_001",
  "firmware_name": "BODAQS",
  "firmware_version": "0.6.0",
  "hardware_version": "BODAQS A8",
  "created_unix_us": 1789272000000000,
  "timezone": "Australia/Perth",
  "log_format": "bodaqs_multi_stream_binary",
  "native_stream_contract": "bodaqs.native_stream.v1",
  "stream_count": 5,
  "logger_monotonic_clock": {
    "clock_id": "logger_monotonic",
    "unit": "us",
    "nondecreasing": true
  },
  "wall_clock_anchor": {
    "available": true,
    "host_monotonic_us": 481230000,
    "unix_us": 1789272000000000,
    "uncertainty_us": 1000000,
    "source": "rtc"
  }
}
```

`wall_clock_anchor` may be absent or have `available=false`. Its uncertainty
describes absolute UTC confidence and does not determine relative alignment
between streams.

The existing `sensors`, `device_configs`, `imu_configs`, mounting,
calibration and transform metadata should be retained. Every sensor-backed
stream descriptor must refer to a sensor identity present in those objects.

## 7. Stream catalog chunk

The catalog payload is one JSON object:

```json
{
  "schema_format": "bdq.stream_catalog.v1",
  "endianness": "little",
  "record_prefix": {
    "format": "bdq.stream_record_prefix.v1",
    "size_bytes": 12
  },
  "streams": []
}
```

Each stream descriptor contains:

- `stream_id` and `stream_key`;
- `stream_kind`, such as `regular`, `intermittent` or `event_derived`;
- `sensor_id`, or `null` for a logger-generated stream;
- `source_device_id` and `transport`;
- `clock_id` and a native timebase definition;
- `record_format`, `record_size_bytes` and channel definitions;
- common and stream-specific status flag meanings;
- signal, mounting and acquisition metadata; and
- requested and effective sample/filter configuration where applicable.

Example BMI270 descriptor:

```json
{
  "stream_id": 2,
  "stream_key": "imu_frame_001",
  "stream_kind": "regular",
  "sensor_id": "frame_imu",
  "source_device_id": "A8_001",
  "transport": "i2c_direct",
  "clock_id": "bmi270:frame_imu_001",
  "record_format": "fixed_mixed_v2",
  "record_size_bytes": 28,
  "timebase": {
    "type": "native_ticks",
    "native_tick_field": "native_tick",
    "native_tick_bits": 24,
    "native_tick_modulus": 16777216,
    "nominal_tick_period_us": {"numerator": 625, "denominator": 16},
    "nominal_sample_rate_hz": {"numerator": 1600, "denominator": 1},
    "expected_sequence_step": 1,
    "clock_relation": "independent"
  },
  "acquisition": {
    "requested_profile": "high_rate_1600",
    "effective_accel_rate_hz": 1600,
    "effective_gyro_rate_hz": 1600,
    "effective_accel_bandwidth_hz": 740,
    "effective_gyro_bandwidth_hz": 557,
    "filter_group_delay_us": null,
    "filter_characterization": "datasheet_bandwidth_only"
  },
  "channels": [
    {"field": "sequence", "quantity": "sample_sequence", "unit": "count", "storage_type": "uint32", "byte_offset": 0, "class": "diagnostic"},
    {"field": "native_tick", "quantity": "sensor_time", "unit": "tick", "storage_type": "uint32", "byte_offset": 4, "class": "diagnostic"},
    {"field": "status_flags", "quantity": "status", "unit": "bitfield", "storage_type": "uint16", "byte_offset": 8, "class": "diagnostic"},
    {"field": "accel_x_raw", "quantity": "linear_acceleration_raw", "component": "x", "coordinate_frame": "sensor_native", "vector_group": "accel_raw", "unit": "count", "storage_type": "int16", "byte_offset": 12, "class": "signal"},
    {"field": "accel_y_raw", "quantity": "linear_acceleration_raw", "component": "y", "coordinate_frame": "sensor_native", "vector_group": "accel_raw", "unit": "count", "storage_type": "int16", "byte_offset": 14, "class": "signal"},
    {"field": "accel_z_raw", "quantity": "linear_acceleration_raw", "component": "z", "coordinate_frame": "sensor_native", "vector_group": "accel_raw", "unit": "count", "storage_type": "int16", "byte_offset": 16, "class": "signal"},
    {"field": "gyro_x_raw", "quantity": "angular_velocity_raw", "component": "x", "coordinate_frame": "sensor_native", "vector_group": "gyro_raw", "unit": "count", "storage_type": "int16", "byte_offset": 18, "class": "signal"},
    {"field": "gyro_y_raw", "quantity": "angular_velocity_raw", "component": "y", "coordinate_frame": "sensor_native", "vector_group": "gyro_raw", "unit": "count", "storage_type": "int16", "byte_offset": 20, "class": "signal"},
    {"field": "gyro_z_raw", "quantity": "angular_velocity_raw", "component": "z", "coordinate_frame": "sensor_native", "vector_group": "gyro_raw", "unit": "count", "storage_type": "int16", "byte_offset": 22, "class": "signal"},
    {"field": "temperature_raw", "quantity": "temperature_raw", "unit": "count", "storage_type": "int16", "byte_offset": 24, "class": "diagnostic"}
  ],
  "status_flags": {
    "discontinuity_before": 1,
    "producer_queue_drop_before": 2,
    "source_recovery_before": 4,
    "timing_degraded": 8,
    "native_tick_estimated": 16,
    "temperature_stale": 32,
    "accel_near_rail": 64,
    "gyro_near_rail": 128,
    "output_decimated": 256
  }
}
```

The numeric bandwidth values in this example describe the selected BMI270
filter profile; they are not a promise that all streams have known bandwidth.
Unknown bandwidth or group delay must be represented as `null`, not zero.

### 7.1 Required record prefix

Every v2.0 stream record starts with the same 12-byte prefix:

| Offset | Size | Type | Field | Meaning |
|---:|---:|---|---|---|
| 0 | 4 | uint32 | `sequence` | Source-sample sequence modulo 2^32 |
| 4 | 4 | uint32 | `native_tick` | Native clock tick modulo the declared modulus |
| 8 | 2 | uint16 | `status_flags` | Common low-bit flags plus stream-specific flags |
| 10 | 2 | uint16 | `reserved` | Must be zero |

All payload channels begin at offset 12 or later. Padding bytes not described
as channels must be zero when written and ignored when read.

The following status bits have common meaning in every stream:

| Bit | Mask | Name | Meaning |
|---:|---:|---|---|
| 0 | `0x0001` | `DISCONTINUITY_BEFORE` | Continuity with the preceding persisted record is not established |
| 1 | `0x0002` | `PRODUCER_QUEUE_DROP_BEFORE` | Producer/sink backpressure discarded preceding records |
| 2 | `0x0004` | `SOURCE_RECOVERY_BEFORE` | Sensor, node or transport recovery occurred before this record |
| 3 | `0x0008` | `TIMING_DEGRADED` | Native or host-time evidence does not meet the normal quality rule |
| 4 | `0x0010` | `NATIVE_TICK_ESTIMATED` | The stored native tick was inferred rather than directly observed |

Bits 5 through 15 are declared by each stream schema. Unknown bits must be
preserved by tools that rewrite data.

### 7.2 Channel storage types

Required v2.0 readers support:

| Type | Size |
|---|---:|
| `uint8` | 1 |
| `int8` | 1 |
| `uint16` | 2 |
| `int16` | 2 |
| `uint32` | 4 |
| `int32` | 4 |
| `float32` | 4 |

All fields are decoded using schema byte offsets. Readers must not infer field
position from channel order.

Catalog validation requires:

1. unique nonzero `stream_id` values;
2. unique non-empty `stream_key` values;
3. a positive `record_size_bytes` no greater than 65535;
4. the exact mandatory prefix at offsets 0, 4 and 8;
5. unique channel field names within a stream;
6. every channel fully contained within the record; and
7. a positive tick modulus no greater than 2^32.

## 8. Stream-data chunk

Each stream-data chunk contains records and timing observations for exactly one
stream. Its payload begins with this 24-byte header:

| Offset | Size | Type | Field | Meaning |
|---:|---:|---|---|---|
| 0 | 2 | uint16 | `stream_id` | Catalog stream identifier |
| 2 | 2 | uint16 | `payload_version` | `1` |
| 4 | 4 | uint32 | `flags` | `0` in v2.0 |
| 8 | 4 | uint32 | `first_sequence` | First record sequence, or related sequence for an observation-only chunk |
| 12 | 4 | uint32 | `record_count` | Number of records |
| 16 | 2 | uint16 | `record_size_bytes` | Must match catalog |
| 18 | 2 | uint16 | `observation_count` | Number of timing observations |
| 20 | 4 | uint32 | `reserved` | Must be zero |

The payload is:

```text
StreamDataHeader
record_count * record_size_bytes
observation_count * 32-byte TimeObservation
```

Validation is:

```text
len(payload) == 24
              + record_count * record_size_bytes
              + observation_count * 32
```

At least one of `record_count` and `observation_count` must be nonzero.

For a chunk containing records, `first_sequence` must equal the first record's
`sequence`. Records must be in ascending modulo sequence order. Adjacent chunks
for one stream need not be adjacent in the file, but continuity is evaluated
between that stream's records after filtering by `stream_id`.

Writers should keep acquisition batches and their timing observations in the
same CRC-protected stream-data chunk where practical.

## 9. Timing observation contract

A timing observation relates one native clock value to a bounded interval in
the logger monotonic clock. It is evidence used to estimate clock offset and
drift; it is not a precomputed per-sample wall-clock timestamp.

Each observation is 32 bytes:

| Offset | Size | Type | Field | Meaning |
|---:|---:|---|---|---|
| 0 | 4 | uint32 | `native_tick` | Observed native tick modulo the stream modulus |
| 4 | 4 | uint32 | `related_sequence` | Associated record sequence, or `0xFFFFFFFF` if none |
| 8 | 8 | uint64 | `host_min_us` | Earliest logger monotonic time consistent with the observation |
| 16 | 8 | uint64 | `host_max_us` | Latest logger monotonic time consistent with the observation |
| 24 | 2 | uint16 | `kind` | Observation method |
| 26 | 2 | uint16 | `flags` | Observation quality flags |
| 28 | 4 | uint32 | `reserved` | Must be zero |

`host_min_us` must be less than or equal to `host_max_us`. The interval must
include known transaction, capture and timestamp-placement uncertainty. A
single host timestamp is represented by equal bounds only when the same clock
edge was captured directly and its quantization is negligible or separately
accounted.

Observation kinds are:

| Value | Name | Meaning |
|---:|---|---|
| 1 | `ACQUISITION_WINDOW` | The source clock was observed during a bounded host transaction, such as a BMI270 FIFO drain |
| 2 | `CLOCK_SYNC_WINDOW` | A transport synchronization exchange produced conservative host bounds |
| 3 | `TRANSPORT_RECEIVE_WINDOW` | Packet reception time only; transport latency is not bounded by this observation |
| 4 | `HARDWARE_CAPTURE` | Native and host clocks observed from the same captured event |
| 5 | `DERIVED_MAPPING_POINT` | Firmware-derived estimate rather than raw timing evidence |

Observation flags are:

| Bit | Mask | Name | Meaning |
|---:|---:|---|---|
| 0 | `0x0001` | `NATIVE_TICK_ESTIMATED` | Native tick was inferred |
| 1 | `0x0002` | `HOST_BOUNDS_CONSERVATIVE` | Bounds deliberately include additional guard time |
| 2 | `0x0004` | `TIMING_DEGRADED` | Normal timing-quality criteria were not met |
| 3 | `0x0008` | `PRE_SESSION` | Observation predates the accepted recording boundary |
| 4 | `0x0010` | `POST_RECOVERY` | Observation follows a source or transport recovery |

`TRANSPORT_RECEIVE_WINDOW` must not be treated as a bound on sample time unless
a separately declared latency model justifies that interpretation.

### 9.1 BMI270 mapping

For a direct BMI270 stream:

- `native_tick` is the low 24-bit BMI270 sensor-time value;
- the nominal tick period is 625/16 microseconds;
- FIFO samples retain their source sequences and reconstructed ticks;
- an observation normally spans the host transaction interval in which the
  sensor-time frame was read; and
- a periodic direct read of the three-byte sensor-time register produces a
  `CLOCK_SYNC_WINDOW` observation bounded by that I2C transaction. Its
  `related_sequence` is the latest emitted sample, not an assertion that the
  register was latched on that sample boundary; and
- the corresponding record and observation carry the estimated/degraded flags
  when the tick was inferred or the anchor failed validation.

The firmware should retain the narrowest defensible host interval. Storage
enqueue and SD write times are not acquisition-time observations.

### 9.2 CAN-FD mapping

For a CAN-FD node stream:

- `native_tick` belongs to the node clock, not the CAN controller receive
  clock;
- source sample sequence must survive CAN batching;
- CAN packet loss, node queue loss and source reset must remain distinguishable
  in diagnostics even if they all create a continuity boundary; and
- a synchronization exchange should produce `CLOCK_SYNC_WINDOW` observations
  with conservative bounds.

Merely timestamping packet arrival produces `TRANSPORT_RECEIVE_WINDOW` and is
not sufficient evidence for tight cross-node phase alignment.

## 10. Time reconstruction and alignment

For each `clock_id`, a consumer must:

1. order records by sequence within continuity segments;
2. unwrap native ticks using the declared modulus;
3. split segments at reset and discontinuity boundaries;
4. fit native clock time to logger monotonic time using eligible timing
   observations and their intervals;
5. retain fit residuals, drift and uncertainty as derived quality evidence;
6. map to Unix time only through the session wall-clock anchor when available;
   and
7. avoid interpolation across an unbridged discontinuity.

Nominal ODR and tick period are priors and scale definitions. Consumers must
not assume nominal sensor seconds equal logger seconds.

Cross-stream comparison occurs only after every participating stream has been
mapped into the logger monotonic domain. Resampling must be an explicit derived
operation. It must preserve gaps and record the interpolation and anti-alias
policy.

Sensor filter group delay is separate from clock alignment. Analysis intended
to preserve phase must use the recorded effective filter configuration and a
declared or measured group-delay model. Unknown group delay must remain
unknown rather than being treated as zero.

For context, a 10-degree phase allowance corresponds to approximately 27.8
microseconds at 1 kHz, 55.6 microseconds at 500 Hz and 277.8 microseconds at
100 Hz. The format preserves the evidence required to evaluate those targets;
it does not claim that every transport or sensor meets them.

## 11. Event chunks

Rare session-level events are stored as UTF-8 JSON rather than being copied
into every stream. The payload shape is:

```json
{
  "event_format": "bdq.events.v1",
  "events": [
    {
      "event_id": 1,
      "event_type": "user_mark",
      "host_monotonic_us": 482500000,
      "unix_us": 1789272001270000,
      "stream_id": null,
      "payload": {}
    }
  ]
}
```

`event_id` is a session-local unsigned integer. `host_monotonic_us` is
required. `unix_us` and `stream_id` may be null. Event types are extensible;
unknown event types must be preserved or ignored without invalidating stream
data.

User marks must use event chunks in multi-stream sessions. They must not be
assigned to whichever stream happened to produce the next sample.

## 12. Final summary

On clean shutdown the writer emits `summary_format="bdq.final_summary.v2"`.
The summary contains existing recorder/storage diagnostics plus a per-stream
array. Each stream entry should include:

- `stream_id` and `stream_key`;
- `records_written` and `data_chunks_written`;
- first and last persisted sequences when present;
- producer, sink and transport drop counts;
- whether each loss count is exact;
- discontinuity and source-recovery counts;
- timing-observation count and degraded-observation count;
- producer queue capacity and high-water mark; and
- sensor/transport-specific diagnostic objects.

The summary is diagnostic and must not override record or chunk contents. A
missing summary indicates an unclean or interrupted close, not invalid earlier
data.

## 13. Parser and recovery rules

A compliant parser must:

1. select v1 or v2 handling from file magic and major version;
2. validate every chunk length and CRC before decoding its payload;
3. stop at the first invalid or incomplete chunk while retaining all preceding
   complete chunks;
4. require metadata and a valid stream catalog before decoding stream data;
5. reject data referencing an undeclared `stream_id`;
6. reject payload/header record-size disagreement;
7. group records and observations by stream without assuming chunk adjacency;
8. expose sequence, tick and status discontinuities rather than silently
   repairing them; and
9. preserve unknown chunk types, event types and status bits when rewriting a
   file where practical.

A parser must not merge streams onto a common sample grid as part of raw file
decoding.

## 14. BDQ v1 compatibility and migration

BDQ v1 remains supported and unchanged. Firmware may continue to emit it for
legacy single-row logging profiles. BDQ v2 is required when a session contains
native independent streams.

A common host session model may project BDQ v1 as follows:

- the v1 global row table becomes a synthesized `primary` stream;
- `sample_id` becomes its sequence;
- its implicit fixed-rate period becomes the synthesized native timebase; and
- existing sparse BMI270 columns may be extracted into the current
  `imu_<sensor>` secondary stream using the accepted MVP rules.

For BDQ v2:

- the stream named `primary` becomes the primary dataframe when present; and
- every other raw stream is exposed directly through `stream_dfs` and
  `secondary_streams` using its `stream_key` and semantic metadata.

There is no general lossless BDQ v2-to-v1 conversion because v1 has only one
implicit timebase. A CSV export must either export one native stream per file
or explicitly resample selected streams and describe that derived operation.

## 15. Resource and scheduling implications

The contract intentionally does not prescribe queue sizes, but an
implementation must publish capacities and high-water marks. Memory budgeting
must include all simultaneously active stream queues, acquisition buffers,
stream-data staging buffers and storage-stall margin.

Writers should store packed records directly. They must not route integer
native records through the legacy float32 row buffer.

Chunk interleaving should be fair enough that one high-rate stream cannot
indefinitely prevent another stream's complete batches from reaching durable
storage. Fairness policy is an implementation detail; sequence and drop
accounting are contractual.

## 16. Acceptance criteria

Before BDQ v2 is accepted for production, automated tests must cover:

- exact file, chunk, stream-data header and timing-observation sizes;
- round-trip decoding of every required storage type;
- at least four independent IMU streams plus one primary stream;
- arbitrary interleaving of chunks from different streams;
- native tick wrap and 32-bit sequence wrap;
- expected and unexpected sequence deltas;
- source reset, queue loss and timing-degraded flags;
- record batches with multiple, one and zero timing observations;
- observation-only stream-data chunks;
- malformed stream IDs and record sizes;
- CRC failure and truncated final chunks;
- absent sensors producing zero records;
- user-mark events independent of stream sample times;
- clean and missing final summaries; and
- unchanged parsing of existing BDQ v1 fixtures.

A synthetic ten-minute four-IMU test must demonstrate that the writer and
reader preserve every generated record, sequence boundary and timing
observation without requiring a common row cadence.

## 17. Deferred extensions

The following require a new compatible minor extension or a later major
format, and are not part of v2.0:

- compressed stream-data payloads;
- variable-length records;
- schema replacement during a session;
- native ticks wider than 32 bits in stream records;
- multiple files linked into one logical session;
- encrypted or authenticated chunks; and
- embedded derived/resampled streams with full processing provenance.
