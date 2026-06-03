# BODAQS BDQ v1 Compact Binary Log Format

BDQ v1 is the compact binary log format used by BODAQS firmware when
`log_format=bodaqs_compact_binary`.

## Purpose

BDQ is designed to reduce logger CPU work and SD write volume compared with CSV
while remaining simple to inspect and recover after power loss.

V1 is intentionally uncompressed and append-only:

- no compression;
- no bit-packing;
- no delta encoding;
- fixed channel layout within a file;
- fixed-size sample frames;
- little-endian only;
- metadata and channel schema stored as UTF-8 JSON chunks.

## File Identity

- Extension: `.bdq`
- Format name: `BDQLOG v1`
- File magic bytes: `42 44 51 4C 4F 47 00 01`
- File magic text: `BDQLOG\0\1`
- Endianness: little-endian for all numeric fields

## File Header

The file starts with a fixed 32-byte header.

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 8 | bytes | magic: `BDQLOG\0\1` |
| 8 | 2 | uint16 | format major, currently `1` |
| 10 | 2 | uint16 | format minor, currently `0` |
| 12 | 4 | uint32 | header length, currently `32` |
| 16 | 8 | uint64 | created Unix timestamp in microseconds, or `0` if unknown |
| 24 | 4 | uint32 | file flags, currently `0` |
| 28 | 4 | uint32 | header CRC32, currently `0` |

The header is serialized explicitly; it is not a compiler-packed struct.

## Chunk Header

All content after the file header is chunked. Each chunk has a 20-byte header.

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 4 | bytes | chunk magic: `BDQC` |
| 4 | 2 | uint16 | header version, currently `1` |
| 6 | 2 | uint16 | chunk type |
| 8 | 4 | uint32 | sequence number |
| 12 | 4 | uint32 | payload length in bytes |
| 16 | 4 | uint32 | IEEE CRC32 of payload |

Chunk types:

| Value | Name |
|---:|---|
| 1 | Metadata |
| 2 | Channel schema |
| 3 | Data |
| 4 | Event, reserved |
| 5 | Final summary |

Unknown future chunk types are skippable by reading `payload_length`.

## Required Chunk Order

The firmware writes:

1. metadata JSON chunk;
2. channel schema JSON chunk;
3. zero or more data chunks;
4. optional final summary JSON chunk on clean shutdown.

The final summary is not required for parsing. A reader should scan chunks until
it reaches a truncated chunk, bad magic, unsupported chunk header version, or CRC
mismatch, then use all complete chunks before that point.

## Metadata JSON

The metadata chunk contains a small UTF-8 JSON object. Required fields include:

```json
{
  "format": "bdq.v1",
  "format_name": "BDQLOG v1",
  "device_id": "Prototype_E",
  "firmware_name": "BODAQS",
  "firmware_version": "0.3.0",
  "hardware_version": "BODAQS 4F",
  "recording_id": "260516_201542",
  "created_unix_us": 1768998942000000,
  "sample_rate_hz": 500,
  "sample_period_us": 2000,
  "timezone": "Australia/Perth",
  "log_format": "bodaqs_compact_binary"
}
```

Missing device/RTC details are written as sensible placeholders rather than
omitting the field.

## Channel Schema JSON

The schema chunk describes the fixed frame layout.

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
    "timestamp_per_sample": false
  },
  "channels": [
    {
      "field": "sample_id",
      "quantity": "sample_index",
      "unit": "sample",
      "storage_type": "uint32",
      "byte_offset": 0
    },
    {
      "field": "front_raw",
      "quantity": "raw",
      "unit": "counts",
      "storage_type": "uint16",
      "byte_offset": 4,
      "sensor": "front_shock",
      "source": "raw_counts",
      "raw": true
    },
    {
      "field": "front_travel",
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
      "byte_offset": 10
    }
  ]
}
```

BDQ v1 stores all emitted sensor columns in the same logical order as the CSV
mode would emit them, plus `sample_id` at the start and `flags` at the end.

Storage types:

- `uint16`: wrapped/native raw count columns;
- `int32`: unwrapped raw count columns;
- `float32`: calibrated or engineered columns;
- `uint32`: `sample_id`;
- `uint16`: frame flags.

## Data Chunk Payload

Each data chunk payload begins with a 20-byte payload header:

| Offset | Size | Type | Field |
|---:|---:|---|---|
| 0 | 4 | uint32 | first sample ID |
| 4 | 4 | uint32 | sample count |
| 8 | 8 | uint64 | chunk start Unix timestamp in microseconds, or `0` |
| 16 | 2 | uint16 | frame size in bytes |
| 18 | 2 | uint16 | data chunk flags, currently `0` |

The payload header is followed by `sample_count` fixed-size sample frames.

## Sample Frame

The frame is fixed-size for the whole file. V1 layout:

1. `uint32 sample_id`;
2. each emitted sensor column, using the storage type and offset in the schema;
3. `uint16 flags`.

Flag bits:

| Bit | Mask | Meaning |
|---:|---:|---|
| 0 | `0x0001` | user mark |
| 1 | `0x0002` | SD busy, reserved |
| 2 | `0x0004` | overrun, reserved |
| 3 | `0x0008` | sensor/value packing error |

## Timestamp Reconstruction

There is no wall-clock timestamp in every frame. Reconstruct sample time from:

```text
sample_unix_us = created_unix_us + sample_id * sample_period_us
```

When RTC time is unknown, `created_unix_us` is `0`; consumers should still use
`sample_id` for ordering and continuity.

## Recovery Rules

A parser should:

1. validate the file header magic and version;
2. parse metadata and schema chunks before data chunks;
3. scan chunk-by-chunk using payload length;
4. validate payload CRC when present;
5. stop at the first incomplete or invalid chunk;
6. keep all complete data chunks before the failure.

No footer is required for basic parsing.

## Host Parser

The analysis package includes:

```bash
python -m bodaqs_analysis.io_bdq path/to/log.bdq
python -m bodaqs_analysis.io_bdq path/to/log.bdq --csv path/to/log.csv
```

The CSV conversion is intended for inspection and continuity checks, not as a
replacement for full import-agent support.
