# BODAQS BDQ v1 Compact Binary Log Format

This document is the parser contract for BODAQS compact binary logs. It is
intended to be sufficient for an implementation agent to build a reader without
access to firmware source code.

BDQ v1 is written by firmware when:

```text
log_format=bodaqs_compact_binary
```

## 1. Format Summary

- File extension: `.bdq`
- Format name: `BDQLOG v1`
- File magic bytes: `42 44 51 4C 4F 47 00 01`
- File magic text: `BDQLOG\0\1`
- Numeric byte order: little-endian
- Encoding for metadata/schema chunks: UTF-8 JSON
- Record organization: fixed file header, then append-only chunks
- Data organization: data chunk header, then fixed-size sample frames
- Compression: none
- Bit packing: none
- Delta encoding: none
- Per-sample wall-clock timestamp: no

BDQ files are self-contained. Compact binary logs do not require a same-stem
JSON sidecar or ZIP archive.

## 2. Primitive Types

All numeric fields are little-endian.

| Type | Size | Notes |
|---|---:|---|
| `uint16` | 2 | Unsigned 16-bit integer |
| `int16` | 2 | Signed two's-complement 16-bit integer |
| `uint32` | 4 | Unsigned 32-bit integer |
| `uint64` | 8 | Unsigned 64-bit integer |
| `int32` | 4 | Signed two's-complement 32-bit integer |
| `float32` | 4 | IEEE-754 binary32 |
| `bytes[N]` | N | Raw bytes |

Equivalent Python `struct` prefixes:

```python
FILE_HEADER = struct.Struct("<8sHHIQII")
CHUNK_HEADER = struct.Struct("<4sHHIII")
DATA_PAYLOAD_HEADER = struct.Struct("<IIQHH")
```

## 3. File Layout

The top-level file layout is:

```text
FileHeader
ChunkHeader + MetadataJsonPayload
ChunkHeader + ChannelSchemaJsonPayload
ChunkHeader + DataPayload
ChunkHeader + DataPayload
...
ChunkHeader + FinalSummaryJsonPayload   # optional, clean shutdown only
```

Parsers must not require a final summary/footer. A power loss may leave the last
chunk incomplete.

## 4. File Header

The file starts with a fixed 32-byte header.

| Offset | Size | Type | Field | Required value / meaning |
|---:|---:|---|---|---|
| 0 | 8 | `bytes[8]` | `magic` | `BDQLOG\0\1` |
| 8 | 2 | `uint16` | `format_major` | `1` |
| 10 | 2 | `uint16` | `format_minor` | `0` for current writer |
| 12 | 4 | `uint32` | `header_length` | `32` for current writer |
| 16 | 8 | `uint64` | `created_unix_us` | Unix microseconds, or `0` if RTC unknown |
| 24 | 4 | `uint32` | `flags` | `0` for current writer |
| 28 | 4 | `uint32` | `header_crc32` | `0`; not implemented in v1 |

Validation:

1. File length must be at least 32 bytes.
2. `magic` must match exactly.
3. A v1 parser should reject unsupported `format_major` values.
4. `header_length` must be at least 32.
5. Start chunk scanning at byte offset `header_length`, not hard-coded offset 32.

## 5. Chunk Header

All content after the file header is a sequence of chunks. Each chunk begins with
a fixed 20-byte header.

| Offset | Size | Type | Field | Required value / meaning |
|---:|---:|---|---|---|
| 0 | 4 | `bytes[4]` | `magic` | `BDQC` |
| 4 | 2 | `uint16` | `header_version` | `1` |
| 6 | 2 | `uint16` | `chunk_type` | See chunk type table |
| 8 | 4 | `uint32` | `sequence_number` | Starts at 0; increments by 1 in current writer |
| 12 | 4 | `uint32` | `payload_length` | Payload length in bytes |
| 16 | 4 | `uint32` | `payload_crc32` | IEEE CRC32 of the payload |

Chunk types:

| Value | Name | Payload |
|---:|---|---|
| 1 | `Metadata` | UTF-8 JSON object |
| 2 | `ChannelSchema` | UTF-8 JSON object |
| 3 | `Data` | Binary data payload |
| 4 | `Event` | Reserved for future use |
| 5 | `FinalSummary` | UTF-8 JSON object |

CRC details:

- Polynomial: reflected IEEE CRC32, `0xEDB88320`
- Initial value: `0`
- Final value: standard `crc32(payload) & 0xffffffff`
- Python equivalent: `binascii.crc32(payload) & 0xffffffff`

Chunk scanning rules:

1. If fewer than 20 bytes remain for a chunk header, stop and report truncated
   final chunk/header.
2. If chunk magic is not `BDQC`, stop and report invalid chunk magic.
3. If `header_version` is unsupported, stop and report unsupported chunk header.
4. If `payload_offset + payload_length` exceeds file length, stop and report
   truncated final chunk/payload.
5. Validate payload CRC before decoding the payload. If CRC fails, stop and
   report invalid chunk.
6. Unknown future `chunk_type` values are skippable after CRC validation by
   advancing `20 + payload_length` bytes.

## 6. Required Chunk Order

Current firmware writes:

1. one metadata chunk;
2. one channel schema chunk;
3. zero or more data chunks;
4. one final summary chunk on clean shutdown.

A parser should require metadata and channel schema before decoding data frames.
If data chunks appear before schema, a parser may count chunks but cannot decode
frames safely.

## 7. Metadata JSON Chunk

The metadata chunk payload is a UTF-8 JSON object. Field order is not
significant.

Current writer fields:

```json
{
  "format": "bdq.v1",
  "format_name": "BDQLOG v1",
  "device_id": "Prototype_E",
  "firmware_name": "BODAQS",
  "firmware_version": "0.3.0",
  "firmware_build": "Jun  3 2026 12:07:43",
  "hardware_version": "BODAQS 4F",
  "recording_id": "260603_122104",
  "path": "/260603_122104.bdq",
  "created_unix_us": 1780460464000000,
  "sample_rate_hz": 500,
  "sample_period_us": 2000,
  "timezone": "Australia/Perth",
  "started_at_utc": "2026-06-03T04:21:04Z",
  "started_at_local": "2026-06-03T12:21:04",
  "log_format": "bodaqs_compact_binary"
}
```

Current firmware may additionally include:

- `sensors`: the same sensor identity, tracking, calibration, device
  configuration, and IMU configuration descriptors used by the CSV JSON
  sidecar;
- `device_configs`: the retained top-level device-configuration compatibility
  map; and
- `imu_configs`: the retained top-level IMU-configuration compatibility map.

These objects are optional for older BDQ v1 files. Readers should preserve them
when projecting BDQ into the common logger metadata model.

Minimum parser-relevant fields:

- `format`
- `recording_id`
- `created_unix_us`
- `sample_rate_hz`
- `sample_period_us`
- `timezone`
- `log_format`

If `created_unix_us` is `0`, RTC time was unavailable. Consumers should still
use `sample_id` for ordering and continuity.

## 8. Channel Schema JSON Chunk

The channel schema chunk payload is a UTF-8 JSON object describing the fixed
frame layout. Field order is not significant.

Example:

```json
{
  "schema_format": "bdq.channel_schema.v1",
  "frame_layout": "fixed_mixed_v1",
  "endianness": "little",
  "frame_size_bytes": 12,
  "timebase": {
    "type": "fixed_rate",
    "sample_rate_hz": 500,
    "sample_period_us": 2000,
    "timestamp_per_sample": false,
    "timestamp_reconstruction": "session_start_unix_us + sample_id * sample_period_us"
  },
  "channels": [
    {
      "field": "sample_id",
      "quantity": "sample_index",
      "unit": "sample",
      "storage_type": "uint32",
      "byte_offset": 0,
      "source": "frame",
      "raw": false
    },
    {
      "field": "front_wheel_raw",
      "quantity": "raw",
      "unit": "counts",
      "storage_type": "uint16",
      "byte_offset": 4,
      "sensor": "front_shock",
      "source": "raw_counts",
      "raw": true
    },
    {
      "field": "front_wheel_disp",
      "quantity": "disp",
      "unit": "mm",
      "storage_type": "float32",
      "byte_offset": 6,
      "sensor": "front_shock",
      "source": "linear_calibrated",
      "raw": false
    },
    {
      "field": "flags",
      "quantity": "flags",
      "unit": "bitfield",
      "storage_type": "uint16",
      "byte_offset": 10,
      "source": "frame",
      "raw": false
    }
  ],
  "sample_flags": {
    "mark": 1,
    "sd_busy": 2,
    "overrun": 4,
    "sensor_err": 8
  }
}
```

Schema validation:

1. `schema_format` should be `bdq.channel_schema.v1`.
2. `frame_layout` should be `fixed_mixed_v1`.
3. `endianness` must be `little`.
4. `frame_size_bytes` must be a positive integer.
5. `channels` must be an array of channel objects.
6. Each decodable channel must have `field`, `storage_type`, and `byte_offset`.
7. `byte_offset + sizeof(storage_type)` must be within `frame_size_bytes`.

Channel objects may also declare `"nan_allowed": true`. This is currently used
for the BMI270 sparse-row `sample_age_us` channel: a quiet logger row has no new
native IMU sample, so its contractual age placeholder is NaN. The writer
preserves that NaN without setting the frame-level `sensor_err` bit. A NaN in a
channel that does not opt in, or an infinity in any channel, remains a sensor
value error.

Signal and diagnostic channel objects may also carry the common logger column
semantics `calibration_ref`, `transform_chain`, `notes`, `required`, `primary`,
`calibrated`, and `transformed`. These fields describe interpretation and do not
change the binary storage layout.

Current firmware supports at most 64 emitted sensor columns and refuses to start
a standard CSV or BDQ session whose configured column count exceeds that limit.
Parsers should not rely on the limit; they should trust the schema and frame
size.

## 9. Storage Types In Frames

Supported `storage_type` values in v1:

| `storage_type` | Size | Decode as | Current writer usage |
|---|---:|---|---|
| `uint16` | 2 | Little-endian unsigned integer | Wrapped/native raw count columns and `flags` |
| `int16` | 2 | Little-endian signed integer | Explicit signed raw columns such as BMI270 axes |
| `int32` | 4 | Little-endian signed integer | Unwrapped raw count columns |
| `uint32` | 4 | Little-endian unsigned integer | `sample_id` and explicit 24-bit timing/sequence columns |
| `float32` | 4 | Little-endian IEEE-754 binary32 | Calibrated/engineered values |

Each emitted sensor column may explicitly request `int16`, `uint16`, `int32`,
`uint32`, or `float32`. Existing columns default to `Automatic`, which preserves
the legacy selection:

- raw unwrapped count columns: `int32`
- other raw/native count columns: `uint16`
- calibrated or transformed columns: `float32`

Sensor values currently pass through a `float32` row buffer before BDQ packing.
Integer-valued sensor columns are therefore guaranteed bit-exact only through
24 significant bits. The BMI270 contract uses signed 16-bit axes and modulo
2^24 sensor-time/sequence values for this reason. `sample_id` is written
directly as `uint32` and is not subject to the sensor-row limitation.

If the writer encounters NaN, infinity, range overflow, or a missing emitted
value while packing a frame, it sets `SAMPLE_FLAG_SENSOR_ERR` in that frame.

## 10. Data Chunk Payload

Each data chunk payload begins with a 20-byte data payload header.

| Offset | Size | Type | Field | Meaning |
|---:|---:|---|---|---|
| 0 | 4 | `uint32` | `first_sample_id` | First sample ID in this chunk |
| 4 | 4 | `uint32` | `sample_count` | Number of frames following this header |
| 8 | 8 | `uint64` | `chunk_start_unix_us` | Timestamp of first sample, or `0` |
| 16 | 2 | `uint16` | `frame_size_bytes` | Frame size used in this chunk |
| 18 | 2 | `uint16` | `flags` | Data chunk flags, currently `0` |

The payload header is immediately followed by:

```text
sample_count * frame_size_bytes
```

bytes of sample frame data.

Validation:

```text
len(payload) == 20 + sample_count * frame_size_bytes
```

For v1 files, every data chunk should have the same `frame_size_bytes` as the
schema `frame_size_bytes`. A mismatch is a parse error for frame decoding.

## 11. Sample Frame Decoding

Sample frames are fixed-size records. Decode each frame using the channel schema:

1. Let `frame_base = data_payload_offset + 20 + i * frame_size_bytes`.
2. For each channel in `schema.channels`:
   - read `storage_type`;
   - read `byte_offset`;
   - decode from `frame_base + byte_offset`;
   - emit the decoded value under `field`.

The current writer always includes:

- `sample_id` at byte offset `0`, `uint32`;
- one entry for each emitted sensor column;
- `flags` as the final `uint16` field.

Do not infer field positions from channel order. Use `byte_offset`.

Continuity validation:

- Data chunk header `first_sample_id` should equal the `sample_id` in the first
  frame.
- Frame `sample_id` values should normally increase by 1.
- Adjacent data chunks should normally be contiguous.
- If the final chunk is missing due to power loss, earlier chunks are still
  valid.

## 12. Sample Flags

The `flags` frame field is a `uint16` bitfield.

| Bit | Mask | Name | Meaning |
|---:|---:|---|---|
| 0 | `0x0001` | `SAMPLE_FLAG_MARK` | User mark button was active for this sample |
| 1 | `0x0002` | `SAMPLE_FLAG_SD_BUSY` | Reserved for SD busy diagnostics |
| 2 | `0x0004` | `SAMPLE_FLAG_OVERRUN` | Reserved for overrun diagnostics |
| 3 | `0x0008` | `SAMPLE_FLAG_SENSOR_ERR` | Sensor/value packing issue for this sample |

Unknown future bits should be preserved by tools that rewrite or convert data.

## 13. Timestamp Reconstruction

BDQ v1 uses an implicit fixed-rate timebase. It does not store a wall-clock
timestamp in every frame.

Preferred reconstruction:

```text
sample_unix_us = metadata.created_unix_us + sample_id * metadata.sample_period_us
```

If `metadata.created_unix_us == 0`, absolute time is unknown. A parser should
still expose:

```text
sample_time_s = sample_id / metadata.sample_rate_hz
```

Data chunk `chunk_start_unix_us` is redundant for fixed-rate files but useful
for recovery checks. It is the timestamp of the first frame in that chunk, or
`0` if unavailable.

## 14. Parser Algorithm

High-level parser pseudocode:

```text
read all bytes or stream from file
parse and validate FileHeader
offset = FileHeader.header_length
metadata = null
schema = null
data_chunks = []
errors = []

while offset < file_length:
    if file_length - offset < 20:
        errors.append("truncated chunk header")
        break

    parse ChunkHeader at offset
    if magic != "BDQC":
        errors.append("bad chunk magic")
        break
    if header_version != 1:
        errors.append("unsupported chunk header")
        break

    payload_start = offset + 20
    payload_end = payload_start + payload_length
    if payload_end > file_length:
        errors.append("truncated chunk payload")
        break

    payload = bytes[payload_start:payload_end]
    if crc32(payload) != payload_crc32:
        errors.append("payload CRC mismatch")
        break

    if chunk_type == 1:
        metadata = parse_utf8_json_object(payload)
    else if chunk_type == 2:
        schema = parse_utf8_json_object(payload)
    else if chunk_type == 3:
        parse data payload header
        validate payload length
        store data chunk reference for frame decoding
    else:
        skip unknown/reserved chunk

    offset = payload_end

require metadata and schema for frame decoding
decode frames using schema byte offsets and storage types
```

Recovery behavior:

- The first invalid or incomplete chunk terminates scanning.
- Complete chunks before the failure are valid.
- A missing final summary chunk is not an error for data recovery.

## 15. Final Summary Chunk

On clean shutdown, firmware writes a final summary JSON chunk. It is optional
and parser tooling must not require it.

Example fields:

```json
{
  "summary_format": "bdq.final_summary.v1",
  "session_id": "260603_122104",
  "path": "/260603_122104.bdq",
  "samples_written": 15000,
  "data_chunks_written": 30,
  "data_chunk_buffer_bytes": 16340,
  "data_chunk_frames": 146,
  "samples_dropped": 0,
  "queue_max": 12,
  "queue_depth": 256,
  "flush_count": 3,
  "flush_max_ms": 14,
  "flush_total_ms": 31
}
```

`data_chunk_buffer_bytes` and `data_chunk_frames` describe the effective
in-memory data-chunk capacity, which may be smaller than the board target when
the writer uses its allocation fallback. They are diagnostic only; data-chunk
payload lengths remain authoritative for parsing.

Current firmware may also append optional diagnostic objects. In particular,
`sensor_runtime_diagnostics` contains bounded, transition-only runtime evidence
for supported sensors such as the AS5600 and AS5048B:

- initialization probe/configuration status and failure stage;
- logging and scheduler boundary events;
- read/configuration failure-start and recovery events;
- session failure/recovery counts and maximum consecutive-failure streaks;
- I2C result codes and expected/received byte counts on failure;
- analog-rail enabled/fault state captured with each event; and
- `events_total`, `events_recorded`, and `events_dropped` so a full event ring is
  visible rather than silently truncated.

Each sensor event ring holds at most 32 entries and is serialized only after
sampling and the I2C scheduler have stopped. Repeated failures are coalesced;
normal samples do not create events. This object is additive, does not widen
data frames, and does not require parsers to understand it.

I2C scheduler client summaries may include:

- `acquire_fail_streak_max`;
- `row_reuse_streak_max`; and
- `row_no_sample_streak_max`.

As with all final-summary fields, these diagnostics can be absent after an
unclean shutdown.

Firmware serializes metadata, schema, and final-summary JSON in two passes: a
count/CRC pass followed by a buffered write pass. This avoids constructing a
contiguous JSON `String` while retaining the existing chunk framing and CRC
contract.

`storage_write_stalls` is a bounded recorder-write diagnostic object. It is
present when timing instrumentation is enabled and contains a threshold, total
event count, truncation indication, and up to 16 events. Each event identifies
the writing operation (`data_chunk`, `periodic_flush`, or `row_write`), its
duration, attempted byte count, queued-row depth, and, where applicable, the
sample ID and data-frame count. It is intended to correlate row loss with
storage latency without adding data-frame columns or per-row logging overhead.

## 16. Parser Acceptance Criteria

A minimal compliant parser should:

- reject files with wrong file magic;
- reject unsupported major versions;
- parse metadata and channel schema JSON;
- validate payload CRC32;
- count valid data chunks and samples;
- stop cleanly at a truncated final chunk;
- decode frames using schema `byte_offset` and `storage_type`;
- detect data chunk frame-size mismatches;
- expose first and last sample IDs;
- expose detected errors without discarding complete earlier chunks.

## 17. Python Reference Constants

```python
import binascii
import struct

FILE_MAGIC = b"BDQLOG\x00\x01"
CHUNK_MAGIC = b"BDQC"

FILE_HEADER = struct.Struct("<8sHHIQII")
CHUNK_HEADER = struct.Struct("<4sHHIII")
DATA_PAYLOAD_HEADER = struct.Struct("<IIQHH")

def crc32(payload: bytes) -> int:
    return binascii.crc32(payload) & 0xffffffff
```

Storage-type decode map:

```python
STORAGE_TYPES = {
    "uint16": ("<H", 2),
    "int16": ("<h", 2),
    "int32": ("<i", 4),
    "uint32": ("<I", 4),
    "float32": ("<f", 4),
}
```

## 18. Current Host Parser

The repository includes a parser/converter:

```bash
python -m bodaqs_analysis.io_bdq path/to/log.bdq
python -m bodaqs_analysis.io_bdq path/to/log.bdq --csv path/to/log.csv
```

The CSV conversion is intended for inspection and continuity checks. Full import
pipeline support can build on the same contract.

## 19. Known Limitations Of V1

- no compression;
- no bit-packing;
- no delta encoding;
- no variable-length sample frames;
- no per-sample wall-clock timestamp by default;
- fixed channel layout within a file;
- little-endian only;
- JSON metadata/schema;
- binary logs require a parser or conversion tool for human inspection.
