from __future__ import annotations

import argparse
import binascii
import csv
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence

import pandas as pd


FILE_MAGIC = b"BDQLOG\x00\x01"
CHUNK_MAGIC = b"BDQC"
FILE_HEADER_STRUCT = struct.Struct("<8sHHIQII")
CHUNK_HEADER_STRUCT = struct.Struct("<4sHHIII")
DATA_PAYLOAD_HEADER_STRUCT = struct.Struct("<IIQHH")
BDQ_SUFFIX = ".bdq"

CHUNK_TYPE_METADATA = 1
CHUNK_TYPE_CHANNEL_SCHEMA = 2
CHUNK_TYPE_DATA = 3
CHUNK_TYPE_EVENT = 4
CHUNK_TYPE_FINAL_SUMMARY = 5


@dataclass(frozen=True)
class BdqFileHeader:
    format_major: int
    format_minor: int
    header_length: int
    created_unix_us: int
    flags: int
    header_crc32: int


@dataclass(frozen=True)
class BdqChunk:
    chunk_type: int
    sequence_number: int
    payload_length: int
    payload_crc32: int
    payload_offset: int
    payload: bytes


@dataclass(frozen=True)
class BdqDataChunkSummary:
    sequence_number: int
    first_sample_id: int
    sample_count: int
    chunk_start_unix_us: int
    frame_size_bytes: int
    flags: int

    @property
    def last_sample_id(self) -> int | None:
        if self.sample_count <= 0:
            return None
        return self.first_sample_id + self.sample_count - 1


@dataclass(frozen=True)
class BdqReadResult:
    path: Path
    header: BdqFileHeader
    metadata: dict[str, Any] = field(default_factory=dict)
    channel_schema: dict[str, Any] = field(default_factory=dict)
    final_summary: dict[str, Any] = field(default_factory=dict)
    data_chunks: tuple[BdqDataChunkSummary, ...] = ()
    detected_errors: tuple[str, ...] = ()
    valid_chunk_count: int = 0

    @property
    def sample_count(self) -> int:
        return sum(chunk.sample_count for chunk in self.data_chunks)

    @property
    def first_sample_id(self) -> int | None:
        for chunk in self.data_chunks:
            if chunk.sample_count:
                return chunk.first_sample_id
        return None

    @property
    def last_sample_id(self) -> int | None:
        for chunk in reversed(self.data_chunks):
            last = chunk.last_sample_id
            if last is not None:
                return last
        return None


def is_bdq_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() == BDQ_SUFFIX


def _crc32(payload: bytes) -> int:
    return binascii.crc32(payload) & 0xFFFFFFFF


def _read_file_header(data: bytes) -> BdqFileHeader:
    if len(data) < FILE_HEADER_STRUCT.size:
        raise ValueError("BDQ file is shorter than the file header")
    magic, major, minor, header_length, created_us, flags, header_crc = FILE_HEADER_STRUCT.unpack_from(data, 0)
    if magic != FILE_MAGIC:
        raise ValueError("BDQ file has the wrong magic bytes")
    if header_length < FILE_HEADER_STRUCT.size:
        raise ValueError(f"BDQ header length is too small: {header_length}")
    if len(data) < header_length:
        raise ValueError("BDQ file is shorter than its declared header length")
    return BdqFileHeader(
        format_major=major,
        format_minor=minor,
        header_length=header_length,
        created_unix_us=created_us,
        flags=flags,
        header_crc32=header_crc,
    )


def _iter_chunks(data: bytes, offset: int) -> Iterator[tuple[BdqChunk | None, str | None]]:
    cursor = offset
    while cursor < len(data):
        remaining = len(data) - cursor
        if remaining < CHUNK_HEADER_STRUCT.size:
            yield None, f"truncated chunk header at offset {cursor}"
            return

        magic, version, chunk_type, sequence, payload_length, payload_crc = CHUNK_HEADER_STRUCT.unpack_from(data, cursor)
        if magic != CHUNK_MAGIC:
            yield None, f"bad chunk magic at offset {cursor}"
            return
        if version != 1:
            yield None, f"unsupported chunk header version {version} at offset {cursor}"
            return

        payload_offset = cursor + CHUNK_HEADER_STRUCT.size
        payload_end = payload_offset + payload_length
        if payload_end > len(data):
            yield None, f"truncated chunk payload at offset {cursor}"
            return

        payload = data[payload_offset:payload_end]
        if _crc32(payload) != payload_crc:
            yield None, f"crc mismatch in chunk sequence {sequence}"
            return

        yield (
            BdqChunk(
                chunk_type=chunk_type,
                sequence_number=sequence,
                payload_length=payload_length,
                payload_crc32=payload_crc,
                payload_offset=payload_offset,
                payload=payload,
            ),
            None,
        )
        cursor = payload_end


def _decode_json_payload(chunk: BdqChunk) -> dict[str, Any]:
    try:
        value = json.loads(chunk.payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"chunk {chunk.sequence_number} is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"chunk {chunk.sequence_number} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"chunk {chunk.sequence_number} JSON payload is not an object")
    return value


def _summarize_data_chunk(chunk: BdqChunk) -> BdqDataChunkSummary:
    if len(chunk.payload) < DATA_PAYLOAD_HEADER_STRUCT.size:
        raise ValueError(f"data chunk {chunk.sequence_number} is shorter than its payload header")
    first, count, start_us, frame_size, flags = DATA_PAYLOAD_HEADER_STRUCT.unpack_from(chunk.payload, 0)
    expected = DATA_PAYLOAD_HEADER_STRUCT.size + count * frame_size
    if expected != len(chunk.payload):
        raise ValueError(
            f"data chunk {chunk.sequence_number} payload length mismatch: expected {expected}, got {len(chunk.payload)}"
        )
    return BdqDataChunkSummary(
        sequence_number=chunk.sequence_number,
        first_sample_id=first,
        sample_count=count,
        chunk_start_unix_us=start_us,
        frame_size_bytes=frame_size,
        flags=flags,
    )


def read_bdq(path: str | Path) -> BdqReadResult:
    input_path = Path(path)
    data = input_path.read_bytes()
    header = _read_file_header(data)

    metadata: dict[str, Any] = {}
    channel_schema: dict[str, Any] = {}
    final_summary: dict[str, Any] = {}
    data_chunks: list[BdqDataChunkSummary] = []
    errors: list[str] = []
    valid_chunk_count = 0

    for chunk, error in _iter_chunks(data, header.header_length):
        if error:
            errors.append(error)
            break
        assert chunk is not None
        valid_chunk_count += 1
        try:
            if chunk.chunk_type == CHUNK_TYPE_METADATA and not metadata:
                metadata = _decode_json_payload(chunk)
            elif chunk.chunk_type == CHUNK_TYPE_CHANNEL_SCHEMA and not channel_schema:
                channel_schema = _decode_json_payload(chunk)
            elif chunk.chunk_type == CHUNK_TYPE_DATA:
                data_chunks.append(_summarize_data_chunk(chunk))
            elif chunk.chunk_type == CHUNK_TYPE_FINAL_SUMMARY and not final_summary:
                final_summary = _decode_json_payload(chunk)
        except ValueError as exc:
            errors.append(str(exc))
            break

    return BdqReadResult(
        path=input_path,
        header=header,
        metadata=metadata,
        channel_schema=channel_schema,
        final_summary=final_summary,
        data_chunks=tuple(data_chunks),
        detected_errors=tuple(errors),
        valid_chunk_count=valid_chunk_count,
    )


def _storage_format(storage_type: str) -> str:
    normalized = str(storage_type).lower()
    if normalized == "uint16":
        return "<H"
    if normalized == "int32":
        return "<i"
    if normalized == "uint32":
        return "<I"
    if normalized == "float32":
        return "<f"
    raise ValueError(f"unsupported BDQ storage type: {storage_type!r}")


def _schema_channels(schema: dict[str, Any]) -> list[dict[str, Any]]:
    channels = schema.get("channels")
    if not isinstance(channels, list):
        raise ValueError("BDQ channel schema does not contain a channels array")
    out: list[dict[str, Any]] = []
    for channel in channels:
        if isinstance(channel, dict):
            out.append(channel)
    if not out:
        raise ValueError("BDQ channel schema has no channels")
    return out


def _frame_size_from_schema(schema: dict[str, Any]) -> int:
    frame_size = schema.get("frame_size_bytes")
    if not isinstance(frame_size, int) or frame_size <= 0:
        raise ValueError("BDQ channel schema has an invalid frame_size_bytes")
    return frame_size


def _iter_valid_data_payloads(data: bytes, header: BdqFileHeader) -> Iterator[BdqChunk]:
    for chunk, error in _iter_chunks(data, header.header_length):
        if error:
            return
        assert chunk is not None
        if chunk.chunk_type == CHUNK_TYPE_DATA:
            yield chunk


def iter_bdq_rows(path: str | Path) -> Iterator[dict[str, Any]]:
    input_path = Path(path)
    data = input_path.read_bytes()
    header = _read_file_header(data)
    info = read_bdq(input_path)
    schema = info.channel_schema
    channels = _schema_channels(schema)
    schema_frame_size = _frame_size_from_schema(schema)

    fields: list[tuple[str, int, str]] = []
    for channel in channels:
        field = channel.get("field")
        storage_type = channel.get("storage_type")
        offset = channel.get("byte_offset")
        if not isinstance(field, str) or not field:
            continue
        if not isinstance(storage_type, str):
            continue
        if not isinstance(offset, int):
            continue
        fields.append((field, offset, _storage_format(storage_type)))

    for chunk in _iter_valid_data_payloads(data, header):
        first, count, _start_us, frame_size, _flags = DATA_PAYLOAD_HEADER_STRUCT.unpack_from(chunk.payload, 0)
        if frame_size != schema_frame_size:
            raise ValueError(
                f"data chunk {chunk.sequence_number} frame size {frame_size} does not match schema {schema_frame_size}"
            )
        expected = DATA_PAYLOAD_HEADER_STRUCT.size + count * frame_size
        if expected != len(chunk.payload):
            raise ValueError(
                f"data chunk {chunk.sequence_number} payload length mismatch: expected {expected}, got {len(chunk.payload)}"
            )

        for i in range(count):
            frame_offset = DATA_PAYLOAD_HEADER_STRUCT.size + i * frame_size
            row: dict[str, Any] = {}
            for field, offset, fmt in fields:
                value = struct.unpack_from(fmt, chunk.payload, frame_offset + offset)[0]
                row[field] = value
            row.setdefault("sample_id", first + i)
            yield row


def _numeric_value(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _bdq_sample_rate_hz(metadata: Mapping[str, Any], schema: Mapping[str, Any]) -> Optional[float]:
    direct = _numeric_value(metadata.get("sample_rate_hz"))
    if direct is not None and direct > 0:
        return direct

    timebase = schema.get("timebase")
    if isinstance(timebase, Mapping):
        from_schema = _numeric_value(timebase.get("sample_rate_hz"))
        if from_schema is not None and from_schema > 0:
            return from_schema

    period_us = _bdq_sample_period_us(metadata, schema)
    if period_us is not None and period_us > 0:
        return 1_000_000.0 / period_us
    return None


def _bdq_sample_period_us(metadata: Mapping[str, Any], schema: Mapping[str, Any]) -> Optional[float]:
    direct = _numeric_value(metadata.get("sample_period_us"))
    if direct is not None and direct > 0:
        return direct

    timebase = schema.get("timebase")
    if isinstance(timebase, Mapping):
        from_schema = _numeric_value(timebase.get("sample_period_us"))
        if from_schema is not None and from_schema > 0:
            return from_schema

    sample_rate_hz = _numeric_value(metadata.get("sample_rate_hz"))
    if sample_rate_hz is not None and sample_rate_hz > 0:
        return 1_000_000.0 / sample_rate_hz
    return None


def bdq_to_dataframe(input_path: str | Path) -> pd.DataFrame:
    """Decode a BDQ file into a dataframe suitable for the preprocessing pipeline."""
    info = read_bdq(input_path)
    if not info.metadata:
        raise ValueError(f"BDQ file has no metadata chunk: {Path(input_path).name}")
    if not info.channel_schema:
        raise ValueError(f"BDQ file has no channel schema chunk: {Path(input_path).name}")
    if info.sample_count <= 0:
        raise ValueError(f"BDQ file has no decodable samples: {Path(input_path).name}")

    rows = list(iter_bdq_rows(input_path))
    if not rows:
        raise ValueError(f"BDQ file yielded no decoded rows: {Path(input_path).name}")

    df = pd.DataFrame.from_records(rows)
    if "sample_id" not in df.columns:
        df.insert(0, "sample_id", range(len(df)))

    period_us = _bdq_sample_period_us(info.metadata, info.channel_schema)
    if period_us is None or period_us <= 0:
        raise ValueError(f"BDQ file has no usable sample period: {Path(input_path).name}")

    first_sample_id = info.first_sample_id
    if first_sample_id is None:
        first_sample_id = int(df["sample_id"].iloc[0])
    df["time_s"] = (pd.to_numeric(df["sample_id"], errors="coerce") - int(first_sample_id)) * (float(period_us) / 1_000_000.0)

    sample_flags = info.channel_schema.get("sample_flags")
    mark_mask = 1
    if isinstance(sample_flags, Mapping):
        maybe_mask = sample_flags.get("mark")
        try:
            mark_mask = int(maybe_mask)
        except (TypeError, ValueError):
            mark_mask = 1

    if "mark" not in df.columns and "flags" in df.columns:
        flags = pd.to_numeric(df["flags"], errors="coerce").fillna(0).astype("int64")
        df["mark"] = (flags & mark_mask) != 0

    column_map = _bdq_dataframe_column_map(info.channel_schema)
    df = df.rename(columns={field: column for field, column in column_map.items() if field in df.columns})

    ordered = ["time_s", "sample_id"] + [c for c in df.columns if c not in {"time_s", "sample_id"}]
    return df.loc[:, ordered]


def _text_or_none(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def _infer_end_from_text(*values: Any) -> Optional[str]:
    for value in values:
        text = _text_or_none(value)
        if text is None:
            continue
        lower = text.lower()
        if lower.startswith("front") or "_front" in lower or "front_" in lower:
            return "front"
        if lower.startswith("rear") or "_rear" in lower or "rear_" in lower:
            return "rear"
    return None


def _infer_domain_from_field(field: str) -> Optional[str]:
    parts = [part for part in str(field).lower().split("_") if part]
    for domain in ("wheel", "suspension", "brake", "drivetrain", "frame", "steering"):
        if domain in parts:
            return domain
    return None


def _bdq_column_class(channel: Mapping[str, Any]) -> str:
    explicit_class = _text_or_none(channel.get("class"))
    if explicit_class is not None:
        normalized = explicit_class.strip().lower()
        if normalized in {"signal", "diagnostic", "index", "event_flag", "qc_flag"}:
            return normalized

    quantity = _text_or_none(channel.get("quantity"))
    field = _text_or_none(channel.get("field"))
    if quantity == "sample_index" or field == "sample_id":
        return "index"
    if quantity == "flags" or field == "flags" or field == "mark":
        return "event_flag"
    return "signal"


def _bdq_dataframe_column_map(schema: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    used: set[str] = set()
    for channel in _schema_channels(dict(schema)):
        field = _text_or_none(channel.get("field"))
        if field is None:
            continue
        name = field
        if _bdq_column_class(channel) == "signal":
            domain = _text_or_none(channel.get("domain")) or _infer_domain_from_field(field)
            unit = _text_or_none(channel.get("unit"))
            if domain is not None and "_dom_" not in name:
                name = f"{name}_dom_{domain}"
            if unit is not None and " [" not in name:
                name = f"{name} [{unit}]"

        candidate = name
        suffix = 2
        while candidate in used:
            candidate = f"{name}_{suffix}"
            suffix += 1
        used.add(candidate)
        out[field] = candidate
    return out


def bdq_to_log_metadata(info: BdqReadResult) -> dict[str, Any]:
    """Map BDQ embedded metadata/schema into the existing logger metadata shape."""
    metadata = info.metadata
    schema = info.channel_schema
    sample_rate_hz = _bdq_sample_rate_hz(metadata, schema)
    sample_period_us = _bdq_sample_period_us(metadata, schema)
    session_id = _text_or_none(metadata.get("recording_id")) or info.path.stem

    columns: dict[str, Any] = {
        "time_s": {
            "class": "time",
            "dtype": "float64",
            "stream": "primary",
            "unit": "s",
        }
    }
    column_map = _bdq_dataframe_column_map(schema)

    for channel in _schema_channels(schema):
        field = _text_or_none(channel.get("field"))
        if field is None:
            continue
        dataframe_column = column_map.get(field, field)
        column_class = _bdq_column_class(channel)
        entry: dict[str, Any] = {
            "class": column_class,
            "stream": "primary",
            "unit": _text_or_none(channel.get("unit")) or "",
            "storage_type": _text_or_none(channel.get("storage_type")),
            "source": _text_or_none(channel.get("source")),
            "source_columns": [field],
            "bdq_field": field,
            "raw": False if column_class == "diagnostic" else bool(channel.get("raw", False)),
        }
        for key in (
            "kind",
            "processing_role",
            "semantic_selection_excluded",
            "semantic_selection_exclusion_reason",
        ):
            if column_class == "diagnostic" and key == "kind":
                continue
            if key in channel:
                entry[key] = channel.get(key)
        metric = _text_or_none(channel.get("metric"))
        if column_class == "diagnostic" and metric is not None:
            entry["metric"] = metric
        quantity = _text_or_none(channel.get("quantity"))
        if quantity is not None:
            if column_class == "diagnostic":
                entry.setdefault("metric", quantity)
            else:
                entry["quantity"] = quantity
        sensor = _text_or_none(channel.get("sensor"))
        if sensor is not None:
            entry["sensor"] = sensor
        end = _text_or_none(channel.get("end")) or _infer_end_from_text(field, sensor)
        if end is not None:
            entry["end"] = end
        domain = _text_or_none(channel.get("domain")) or _infer_domain_from_field(field)
        if domain is not None:
            entry["domain"] = domain
        columns[dataframe_column] = entry

    if "flags" in columns and "mark" not in columns:
        columns["mark"] = {
            "class": "event_flag",
            "dtype": "bool",
            "stream": "primary",
            "source": "bdq.sample_flags.mark",
        }

    run_stats = dict(info.final_summary) if isinstance(info.final_summary, Mapping) else {}
    if info.detected_errors:
        run_stats["bdq_parser_errors"] = list(info.detected_errors)

    return {
        "contract": {
            "name": "bdq.v1",
            "version": f"{info.header.format_major}.{info.header.format_minor}",
            "sidecar_kind": "embedded",
        },
        "session": {
            "session_id": session_id,
            "started_at_utc": _text_or_none(metadata.get("started_at_utc")),
            "started_at_local": _text_or_none(metadata.get("started_at_local")),
            "timezone": _text_or_none(metadata.get("timezone")),
        },
        "data_file": {
            "format": "bdq",
            "path": str(info.path),
        },
        "streams": {
            "primary": {
                "type": "uniform",
                "time_column": "time_s",
                "time_encoding": "elapsed_s",
                "time_unit": "s",
                "sample_rate_hz": sample_rate_hz,
                "sample_period_us": sample_period_us,
            }
        },
        "columns": columns,
        "provenance": {
            "logger_family": "BODAQS",
            "firmware_version": _text_or_none(metadata.get("firmware_version")),
            "firmware_build": _text_or_none(metadata.get("firmware_build")),
            "generator": "bdq.v1",
            "metadata_generated_at": _text_or_none(metadata.get("started_at_utc")),
            "device_id": _text_or_none(metadata.get("device_id")),
            "hardware_version": _text_or_none(metadata.get("hardware_version")),
        },
        "qc": {
            "run_stats": run_stats,
        },
        "bdq": {
            "metadata": dict(metadata),
            "channel_schema": dict(schema),
            "detected_errors": list(info.detected_errors),
            "sample_count": info.sample_count,
            "first_sample_id": info.first_sample_id,
            "last_sample_id": info.last_sample_id,
        },
    }


def bdq_to_csv(input_path: str | Path, output_path: str | Path) -> None:
    info = read_bdq(input_path)
    channels = _schema_channels(info.channel_schema)
    fieldnames = [channel["field"] for channel in channels if isinstance(channel, dict) and isinstance(channel.get("field"), str)]
    rows = iter_bdq_rows(input_path)

    with Path(output_path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summary_lines(info: BdqReadResult) -> list[str]:
    errors = ", ".join(info.detected_errors) if info.detected_errors else "none"
    return [
        f"format version: {info.header.format_major}.{info.header.format_minor}",
        f"metadata: {json.dumps(info.metadata, sort_keys=True)}",
        f"channel schema: {json.dumps(info.channel_schema, sort_keys=True)}",
        f"final summary: {json.dumps(info.final_summary, sort_keys=True)}",
        f"valid chunks: {info.valid_chunk_count}",
        f"valid data chunks: {len(info.data_chunks)}",
        f"samples: {info.sample_count}",
        f"first sample ID: {info.first_sample_id if info.first_sample_id is not None else ''}",
        f"last sample ID: {info.last_sample_id if info.last_sample_id is not None else ''}",
        f"detected errors: {errors}",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or convert a BODAQS .bdq log file.")
    parser.add_argument("input", help="Path to a .bdq file")
    parser.add_argument("--csv", dest="csv_output", help="Optional output CSV path")
    args = parser.parse_args(argv)

    info = read_bdq(args.input)
    for line in summary_lines(info):
        print(line)
    if args.csv_output:
        bdq_to_csv(args.input, args.csv_output)
        print(f"csv written: {args.csv_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
