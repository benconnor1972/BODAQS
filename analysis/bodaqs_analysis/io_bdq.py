from __future__ import annotations

import argparse
import binascii
import csv
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


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
        except ValueError as exc:
            errors.append(str(exc))
            break

    return BdqReadResult(
        path=input_path,
        header=header,
        metadata=metadata,
        channel_schema=channel_schema,
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
                if isinstance(value, float) and math.isnan(value):
                    row[field] = ""
                else:
                    row[field] = value
            row.setdefault("sample_id", first + i)
            yield row


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
