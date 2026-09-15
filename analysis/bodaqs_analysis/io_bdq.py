from __future__ import annotations

import argparse
import binascii
import copy
import csv
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence

import pandas as pd


FILE_MAGIC_V1 = b"BDQLOG\x00\x01"
FILE_MAGIC_V2 = b"BDQLOG\x00\x02"
# Backwards-compatible public name used by existing v1 fixtures and callers.
FILE_MAGIC = FILE_MAGIC_V1
CHUNK_MAGIC = b"BDQC"
FILE_HEADER_STRUCT = struct.Struct("<8sHHIQII")
CHUNK_HEADER_STRUCT = struct.Struct("<4sHHIII")
DATA_PAYLOAD_HEADER_STRUCT = struct.Struct("<IIQHH")
STREAM_DATA_HEADER_STRUCT = struct.Struct("<HHIIIHHI")
STREAM_RECORD_PREFIX_STRUCT = struct.Struct("<IIHH")
TIME_OBSERVATION_STRUCT = struct.Struct("<IIQQHHI")
BDQ_SUFFIX = ".bdq"

CHUNK_TYPE_METADATA = 1
CHUNK_TYPE_CHANNEL_SCHEMA = 2
CHUNK_TYPE_DATA = 3
CHUNK_TYPE_EVENT = 4
CHUNK_TYPE_FINAL_SUMMARY = 5

STREAM_STATUS_DISCONTINUITY_BEFORE = 0x0001
STREAM_STATUS_PRODUCER_QUEUE_DROP_BEFORE = 0x0002
STREAM_STATUS_SOURCE_RECOVERY_BEFORE = 0x0004
STREAM_STATUS_TIMING_DEGRADED = 0x0008
STREAM_STATUS_NATIVE_TICK_ESTIMATED = 0x0010


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
class BdqTimeObservation:
    native_tick: int
    related_sequence: int
    host_min_us: int
    host_max_us: int
    kind: int
    flags: int


@dataclass(frozen=True)
class BdqStreamDataChunkSummary:
    sequence_number: int
    stream_id: int
    first_sequence: int
    record_count: int
    record_size_bytes: int
    flags: int
    last_record_sequence: int | None = None
    observations: tuple[BdqTimeObservation, ...] = ()

    @property
    def last_sequence(self) -> int | None:
        return self.last_record_sequence


@dataclass(frozen=True)
class BdqReadResult:
    path: Path
    header: BdqFileHeader
    metadata: dict[str, Any] = field(default_factory=dict)
    channel_schema: dict[str, Any] = field(default_factory=dict)
    stream_catalog: dict[str, Any] = field(default_factory=dict)
    final_summary: dict[str, Any] = field(default_factory=dict)
    data_chunks: tuple[BdqDataChunkSummary, ...] = ()
    stream_data_chunks: tuple[BdqStreamDataChunkSummary, ...] = ()
    events: tuple[dict[str, Any], ...] = ()
    detected_errors: tuple[str, ...] = ()
    valid_chunk_count: int = 0

    @property
    def sample_count(self) -> int:
        if self.header.format_major == 2:
            return sum(chunk.record_count for chunk in self.stream_data_chunks)
        return sum(chunk.sample_count for chunk in self.data_chunks)

    @property
    def stream_count(self) -> int:
        streams = self.stream_catalog.get("streams")
        return len(streams) if isinstance(streams, list) else 0

    def stream_record_count(self, stream_id: int) -> int:
        return sum(
            chunk.record_count
            for chunk in self.stream_data_chunks
            if chunk.stream_id == stream_id
        )

    def _primary_stream_id(self) -> int | None:
        streams = self.stream_catalog.get("streams")
        if not isinstance(streams, list):
            return None
        for stream in streams:
            if isinstance(stream, Mapping) and stream.get("stream_key") == "primary":
                stream_id = stream.get("stream_id")
                if isinstance(stream_id, int):
                    return stream_id
        return None

    @property
    def first_sample_id(self) -> int | None:
        if self.header.format_major == 2:
            primary_id = self._primary_stream_id()
            for chunk in self.stream_data_chunks:
                if chunk.stream_id == primary_id and chunk.record_count:
                    return chunk.first_sequence
            return None
        for chunk in self.data_chunks:
            if chunk.sample_count:
                return chunk.first_sample_id
        return None

    @property
    def last_sample_id(self) -> int | None:
        if self.header.format_major == 2:
            primary_id = self._primary_stream_id()
            for chunk in reversed(self.stream_data_chunks):
                if chunk.stream_id == primary_id:
                    return chunk.last_sequence
            return None
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
    if magic not in {FILE_MAGIC_V1, FILE_MAGIC_V2}:
        raise ValueError("BDQ file has the wrong magic bytes")
    expected_major = 1 if magic == FILE_MAGIC_V1 else 2
    if major != expected_major:
        raise ValueError(
            f"BDQ file magic identifies v{expected_major} but format_major is {major}"
        )
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


def _stream_descriptors(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    streams = catalog.get("streams")
    if not isinstance(streams, list):
        raise ValueError("BDQ v2 stream catalog does not contain a streams array")
    return [dict(stream) for stream in streams if isinstance(stream, Mapping)]


def _storage_size(storage_type: str) -> int:
    return struct.calcsize(_storage_format(storage_type))


def _validate_v2_metadata(metadata: Mapping[str, Any]) -> None:
    required_text = (
        "format_name",
        "recording_id",
        "device_id",
        "firmware_name",
        "firmware_version",
        "hardware_version",
        "timezone",
    )
    if metadata.get("format") != "bdq.v2":
        raise ValueError("BDQ v2 metadata has the wrong format")
    for field_name in required_text:
        if not isinstance(metadata.get(field_name), str) or not metadata[field_name]:
            raise ValueError(f"BDQ v2 metadata has an invalid {field_name}")
    if metadata.get("log_format") != "bodaqs_multi_stream_binary":
        raise ValueError("BDQ v2 metadata has the wrong log_format")
    if metadata.get("native_stream_contract") != "bodaqs.native_stream.v1":
        raise ValueError("BDQ v2 metadata has an unsupported native_stream_contract")
    created_unix_us = metadata.get("created_unix_us")
    if not isinstance(created_unix_us, int) or created_unix_us < 0:
        raise ValueError("BDQ v2 metadata has an invalid created_unix_us")
    stream_count = metadata.get("stream_count")
    if not isinstance(stream_count, int) or stream_count <= 0:
        raise ValueError("BDQ v2 metadata has an invalid stream_count")
    logger_clock = metadata.get("logger_monotonic_clock")
    if not isinstance(logger_clock, Mapping):
        raise ValueError("BDQ v2 metadata has no logger_monotonic_clock declaration")
    if (
        logger_clock.get("clock_id") != "logger_monotonic"
        or logger_clock.get("unit") != "us"
        or logger_clock.get("nondecreasing") is not True
    ):
        raise ValueError("BDQ v2 metadata has an invalid logger_monotonic_clock")


def _validate_stream_catalog(catalog: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    if catalog.get("schema_format") != "bdq.stream_catalog.v1":
        raise ValueError("BDQ v2 stream catalog has an unsupported schema_format")
    if catalog.get("endianness") != "little":
        raise ValueError("BDQ v2 stream catalog is not little-endian")
    record_prefix = catalog.get("record_prefix")
    if not isinstance(record_prefix, Mapping):
        raise ValueError("BDQ v2 stream catalog has no record_prefix declaration")
    if record_prefix.get("format") != "bdq.stream_record_prefix.v1":
        raise ValueError("BDQ v2 stream catalog has an unsupported record_prefix format")
    if record_prefix.get("size_bytes") != STREAM_RECORD_PREFIX_STRUCT.size:
        raise ValueError("BDQ v2 stream catalog has the wrong record_prefix size")

    descriptors = _stream_descriptors(catalog)
    if not descriptors:
        raise ValueError("BDQ v2 stream catalog has no stream descriptors")

    by_id: dict[int, dict[str, Any]] = {}
    keys: set[str] = set()
    for descriptor in descriptors:
        stream_id = descriptor.get("stream_id")
        stream_key = descriptor.get("stream_key")
        record_size = descriptor.get("record_size_bytes")
        if not isinstance(stream_id, int) or not 0 < stream_id <= 0xFFFF:
            raise ValueError("BDQ v2 stream descriptor has an invalid stream_id")
        if stream_id in by_id:
            raise ValueError(f"BDQ v2 stream catalog repeats stream_id {stream_id}")
        if not isinstance(stream_key, str) or not stream_key:
            raise ValueError(f"BDQ v2 stream {stream_id} has an invalid stream_key")
        if stream_key in keys:
            raise ValueError(f"BDQ v2 stream catalog repeats stream_key {stream_key!r}")
        if not isinstance(record_size, int) or not 0 < record_size <= 0xFFFF:
            raise ValueError(f"BDQ v2 stream {stream_id} has an invalid record_size_bytes")

        timebase = descriptor.get("timebase")
        if not isinstance(timebase, Mapping):
            raise ValueError(f"BDQ v2 stream {stream_id} has no timebase")
        tick_modulus = timebase.get("native_tick_modulus")
        if not isinstance(tick_modulus, int) or not 0 < tick_modulus <= (1 << 32):
            raise ValueError(f"BDQ v2 stream {stream_id} has an invalid native_tick_modulus")
        sequence_step = timebase.get("expected_sequence_step")
        if not isinstance(sequence_step, int) or sequence_step <= 0:
            raise ValueError(f"BDQ v2 stream {stream_id} has an invalid expected_sequence_step")

        channels = _schema_channels(descriptor)
        fields: set[str] = set()
        channel_lookup: dict[str, tuple[str, int]] = {}
        for channel in channels:
            field_name = channel.get("field")
            storage_type = channel.get("storage_type")
            byte_offset = channel.get("byte_offset")
            if not isinstance(field_name, str) or not field_name:
                raise ValueError(f"BDQ v2 stream {stream_id} has a channel without a field")
            if field_name in fields:
                raise ValueError(f"BDQ v2 stream {stream_id} repeats field {field_name!r}")
            if not isinstance(storage_type, str) or not isinstance(byte_offset, int) or byte_offset < 0:
                raise ValueError(f"BDQ v2 stream {stream_id} field {field_name!r} is incomplete")
            try:
                field_size = _storage_size(storage_type)
            except ValueError as exc:
                raise ValueError(
                    f"BDQ v2 stream {stream_id} field {field_name!r}: {exc}"
                ) from exc
            if byte_offset + field_size > record_size:
                raise ValueError(
                    f"BDQ v2 stream {stream_id} field {field_name!r} exceeds record size"
                )
            fields.add(field_name)
            channel_lookup[field_name] = (storage_type.lower(), byte_offset)

        required_prefix = {
            "sequence": ("uint32", 0),
            "native_tick": ("uint32", 4),
            "status_flags": ("uint16", 8),
        }
        for field_name, expected in required_prefix.items():
            if channel_lookup.get(field_name) != expected:
                raise ValueError(
                    f"BDQ v2 stream {stream_id} has an invalid {field_name} prefix field"
                )

        by_id[stream_id] = descriptor
        keys.add(stream_key)
    return by_id


def _decode_time_observations(
    chunk: BdqChunk,
    *,
    start: int,
    count: int,
    tick_modulus: int,
) -> tuple[BdqTimeObservation, ...]:
    observations: list[BdqTimeObservation] = []
    for index in range(count):
        offset = start + index * TIME_OBSERVATION_STRUCT.size
        native_tick, related_sequence, host_min_us, host_max_us, kind, flags, reserved = (
            TIME_OBSERVATION_STRUCT.unpack_from(chunk.payload, offset)
        )
        if host_min_us > host_max_us:
            raise ValueError(
                f"stream-data chunk {chunk.sequence_number} has reversed timing bounds"
            )
        if native_tick >= tick_modulus:
            raise ValueError(
                f"stream-data chunk {chunk.sequence_number} observation native tick exceeds modulus"
            )
        if kind not in {1, 2, 3, 4, 5}:
            raise ValueError(
                f"stream-data chunk {chunk.sequence_number} has unsupported observation kind {kind}"
            )
        if reserved != 0:
            raise ValueError(
                f"stream-data chunk {chunk.sequence_number} has nonzero observation reserved field"
            )
        observations.append(
            BdqTimeObservation(
                native_tick=native_tick,
                related_sequence=related_sequence,
                host_min_us=host_min_us,
                host_max_us=host_max_us,
                kind=kind,
                flags=flags,
            )
        )
    return tuple(observations)


def _summarize_stream_data_chunk(
    chunk: BdqChunk,
    descriptors: Mapping[int, Mapping[str, Any]],
) -> BdqStreamDataChunkSummary:
    if len(chunk.payload) < STREAM_DATA_HEADER_STRUCT.size:
        raise ValueError(f"stream-data chunk {chunk.sequence_number} is shorter than its payload header")
    stream_id, version, flags, first, count, record_size, observation_count, reserved = (
        STREAM_DATA_HEADER_STRUCT.unpack_from(chunk.payload, 0)
    )
    if version != 1:
        raise ValueError(
            f"stream-data chunk {chunk.sequence_number} has unsupported payload version {version}"
        )
    if flags != 0:
        raise ValueError(
            f"stream-data chunk {chunk.sequence_number} has unsupported flags 0x{flags:08x}"
        )
    descriptor = descriptors.get(stream_id)
    if descriptor is None:
        raise ValueError(
            f"stream-data chunk {chunk.sequence_number} references undeclared stream_id {stream_id}"
        )
    schema_record_size = descriptor.get("record_size_bytes")
    if record_size != schema_record_size:
        raise ValueError(
            f"stream-data chunk {chunk.sequence_number} record size {record_size} "
            f"does not match stream schema {schema_record_size}"
        )
    if reserved != 0:
        raise ValueError(f"stream-data chunk {chunk.sequence_number} has nonzero reserved field")
    if count == 0 and observation_count == 0:
        raise ValueError(f"stream-data chunk {chunk.sequence_number} is empty")

    records_bytes = count * record_size
    observations_start = STREAM_DATA_HEADER_STRUCT.size + records_bytes
    expected = observations_start + observation_count * TIME_OBSERVATION_STRUCT.size
    if expected != len(chunk.payload):
        raise ValueError(
            f"stream-data chunk {chunk.sequence_number} payload length mismatch: "
            f"expected {expected}, got {len(chunk.payload)}"
        )
    tick_modulus = int(descriptor["timebase"]["native_tick_modulus"])
    last_record_sequence: int | None = None
    for index in range(count):
        record_offset = STREAM_DATA_HEADER_STRUCT.size + index * record_size
        sequence, native_tick, _status, prefix_reserved = STREAM_RECORD_PREFIX_STRUCT.unpack_from(
            chunk.payload, record_offset
        )
        if index == 0 and sequence != first:
            raise ValueError(
                f"stream-data chunk {chunk.sequence_number} first sequence does not match first record"
            )
        if last_record_sequence is not None:
            sequence_delta = (sequence - last_record_sequence) & 0xFFFFFFFF
            if sequence_delta == 0 or sequence_delta >= 0x80000000:
                raise ValueError(
                    f"stream-data chunk {chunk.sequence_number} records are not in ascending modulo sequence order"
                )
        if native_tick >= tick_modulus:
            raise ValueError(
                f"stream-data chunk {chunk.sequence_number} record {index} native tick exceeds modulus"
            )
        if prefix_reserved != 0:
            raise ValueError(
                f"stream-data chunk {chunk.sequence_number} record {index} has nonzero record-prefix reserved field"
            )
        last_record_sequence = sequence

    observations = _decode_time_observations(
        chunk,
        start=observations_start,
        count=observation_count,
        tick_modulus=tick_modulus,
    )
    return BdqStreamDataChunkSummary(
        sequence_number=chunk.sequence_number,
        stream_id=stream_id,
        first_sequence=first,
        record_count=count,
        record_size_bytes=record_size,
        flags=flags,
        last_record_sequence=last_record_sequence,
        observations=observations,
    )


def _decode_events(chunk: BdqChunk) -> list[dict[str, Any]]:
    payload = _decode_json_payload(chunk)
    if payload.get("event_format") != "bdq.events.v1":
        raise ValueError(f"event chunk {chunk.sequence_number} has an unsupported event_format")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError(f"event chunk {chunk.sequence_number} has no events")
    decoded: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            raise ValueError(f"event chunk {chunk.sequence_number} contains a non-object event")
        event_id = event.get("event_id")
        event_type = event.get("event_type")
        host_us = event.get("host_monotonic_us")
        if not isinstance(event_id, int) or event_id < 0:
            raise ValueError(f"event chunk {chunk.sequence_number} has an invalid event_id")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError(f"event chunk {chunk.sequence_number} has an invalid event_type")
        if not isinstance(host_us, int) or host_us < 0:
            raise ValueError(f"event chunk {chunk.sequence_number} has an invalid host_monotonic_us")
        decoded.append(dict(event))
    return decoded


def _read_bdq_bytes(input_path: Path, data: bytes) -> BdqReadResult:
    header = _read_file_header(data)

    metadata: dict[str, Any] = {}
    channel_schema: dict[str, Any] = {}
    stream_catalog: dict[str, Any] = {}
    stream_descriptors: dict[int, dict[str, Any]] = {}
    final_summary: dict[str, Any] = {}
    data_chunks: list[BdqDataChunkSummary] = []
    stream_data_chunks: list[BdqStreamDataChunkSummary] = []
    events: list[dict[str, Any]] = []
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
                if header.format_major == 2:
                    _validate_v2_metadata(metadata)
            elif chunk.chunk_type == CHUNK_TYPE_CHANNEL_SCHEMA:
                if header.format_major == 1 and not channel_schema:
                    channel_schema = _decode_json_payload(chunk)
                elif header.format_major == 2 and not stream_catalog:
                    stream_catalog = _decode_json_payload(chunk)
                    stream_descriptors = _validate_stream_catalog(stream_catalog)
                    if metadata and metadata.get("stream_count") != len(stream_descriptors):
                        raise ValueError(
                            "BDQ v2 metadata stream_count does not match the stream catalog"
                        )
            elif chunk.chunk_type == CHUNK_TYPE_DATA:
                if header.format_major == 1:
                    data_chunks.append(_summarize_data_chunk(chunk))
                else:
                    if not stream_descriptors:
                        raise ValueError(
                            f"stream-data chunk {chunk.sequence_number} appears before the stream catalog"
                        )
                    stream_data_chunks.append(
                        _summarize_stream_data_chunk(chunk, stream_descriptors)
                    )
            elif chunk.chunk_type == CHUNK_TYPE_EVENT and header.format_major == 2:
                events.extend(_decode_events(chunk))
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
        stream_catalog=stream_catalog,
        final_summary=final_summary,
        data_chunks=tuple(data_chunks),
        stream_data_chunks=tuple(stream_data_chunks),
        events=tuple(events),
        detected_errors=tuple(errors),
        valid_chunk_count=valid_chunk_count,
    )


def read_bdq(path: str | Path) -> BdqReadResult:
    input_path = Path(path)
    return _read_bdq_bytes(input_path, input_path.read_bytes())


def _storage_format(storage_type: str) -> str:
    normalized = str(storage_type).lower()
    if normalized == "uint8":
        return "<B"
    if normalized == "int8":
        return "<b"
    if normalized == "uint16":
        return "<H"
    if normalized == "int16":
        return "<h"
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


def _stream_descriptor(
    info: BdqReadResult,
    stream: int | str,
) -> dict[str, Any]:
    descriptors = _stream_descriptors(info.stream_catalog)
    for descriptor in descriptors:
        if isinstance(stream, int) and descriptor.get("stream_id") == stream:
            return descriptor
        if isinstance(stream, str) and descriptor.get("stream_key") == stream:
            return descriptor
    raise ValueError(f"BDQ v2 stream is not declared: {stream!r}")


def _stream_fields(descriptor: Mapping[str, Any]) -> list[tuple[str, int, str]]:
    record_size = descriptor.get("record_size_bytes")
    if not isinstance(record_size, int) or record_size <= 0:
        raise ValueError("BDQ v2 stream descriptor has an invalid record size")
    fields: list[tuple[str, int, str]] = []
    for channel in _schema_channels(dict(descriptor)):
        field_name = channel.get("field")
        storage_type = channel.get("storage_type")
        offset = channel.get("byte_offset")
        if not isinstance(field_name, str) or not isinstance(storage_type, str) or not isinstance(offset, int):
            continue
        fmt = _storage_format(storage_type)
        if offset < 0 or offset + struct.calcsize(fmt) > record_size:
            raise ValueError(f"BDQ v2 stream field {field_name!r} exceeds record size")
        fields.append((field_name, offset, fmt))
    return fields


def _decode_stream_chunk_records(
    chunk: BdqChunk,
    parsed: BdqStreamDataChunkSummary,
    descriptor: Mapping[str, Any],
) -> list[dict[str, Any]]:
    record_size = int(descriptor["record_size_bytes"])
    fields = _stream_fields(descriptor)
    tick_modulus = int(descriptor["timebase"]["native_tick_modulus"])
    records: list[dict[str, Any]] = []
    for index in range(parsed.record_count):
        record_offset = STREAM_DATA_HEADER_STRUCT.size + index * record_size
        prefix = STREAM_RECORD_PREFIX_STRUCT.unpack_from(chunk.payload, record_offset)
        if prefix[3] != 0:
            raise ValueError(
                f"stream-data chunk {chunk.sequence_number} record {index} has nonzero reserved prefix"
            )
        if prefix[1] >= tick_modulus:
            raise ValueError(
                f"stream-data chunk {chunk.sequence_number} record {index} native tick exceeds modulus"
            )
        record: dict[str, Any] = {}
        for field_name, offset, fmt in fields:
            record[field_name] = struct.unpack_from(fmt, chunk.payload, record_offset + offset)[0]
        records.append(record)
    return records


def iter_bdq_stream_records(
    path: str | Path,
    stream: int | str,
) -> Iterator[dict[str, Any]]:
    """Yield native records for one BDQ v2 stream without resampling."""
    input_path = Path(path)
    data = input_path.read_bytes()
    header = _read_file_header(data)
    if header.format_major != 2:
        raise ValueError("native stream iteration requires a BDQ v2 file")
    info = _read_bdq_bytes(input_path, data)
    if not info.stream_catalog:
        raise ValueError(f"BDQ v2 file has no stream catalog: {input_path.name}")
    descriptor = _stream_descriptor(info, stream)
    stream_id = int(descriptor["stream_id"])
    descriptors_by_id = _validate_stream_catalog(info.stream_catalog)

    for chunk in _iter_valid_data_payloads(data, header):
        parsed = _summarize_stream_data_chunk(chunk, descriptors_by_id)
        if parsed.stream_id != stream_id:
            continue
        yield from _decode_stream_chunk_records(chunk, parsed, descriptor)


def iter_bdq_time_observations(
    path: str | Path,
    stream: int | str,
) -> Iterator[BdqTimeObservation]:
    """Yield timing evidence for one BDQ v2 stream in file order."""
    info = read_bdq(path)
    if info.header.format_major != 2:
        raise ValueError("timing observations require a BDQ v2 file")
    descriptor = _stream_descriptor(info, stream)
    stream_id = int(descriptor["stream_id"])
    for chunk in info.stream_data_chunks:
        if chunk.stream_id == stream_id:
            yield from chunk.observations


def _rational_value(value: Any) -> Optional[float]:
    if isinstance(value, Mapping):
        numerator = _numeric_value(value.get("numerator"))
        denominator = _numeric_value(value.get("denominator"))
        if numerator is not None and denominator is not None and denominator != 0:
            return numerator / denominator
    return _numeric_value(value)


def _decorate_native_time(
    df: pd.DataFrame,
    descriptor: Mapping[str, Any],
) -> pd.DataFrame:
    if df.empty:
        return df
    timebase = descriptor.get("timebase")
    if not isinstance(timebase, Mapping):
        raise ValueError("BDQ v2 stream descriptor has no timebase")
    modulus = int(timebase["native_tick_modulus"])
    expected_step = int(timebase["expected_sequence_step"])
    tick_period_us = _rational_value(timebase.get("nominal_tick_period_us"))
    if tick_period_us is None or tick_period_us <= 0:
        raise ValueError("BDQ v2 stream has no usable nominal tick period")

    sequences = pd.to_numeric(df["sequence"], errors="raise").astype("uint64").tolist()
    ticks = pd.to_numeric(df["native_tick"], errors="raise").astype("uint64").tolist()
    statuses = pd.to_numeric(df["status_flags"], errors="raise").astype("uint64").tolist()

    unwrapped: list[int] = []
    segments: list[int] = []
    segment = 0
    wrap_offset = 0
    previous_tick = int(ticks[0])
    previous_sequence = int(sequences[0])
    for index, (sequence, tick, status) in enumerate(zip(sequences, ticks, statuses)):
        sequence = int(sequence)
        tick = int(tick)
        status = int(status)
        if index:
            sequence_delta = (sequence - previous_sequence) & 0xFFFFFFFF
            explicit_boundary = bool(status & STREAM_STATUS_DISCONTINUITY_BEFORE)
            if explicit_boundary or sequence_delta != expected_step:
                segment += 1
                wrap_offset = 0
            elif tick < previous_tick and previous_tick - tick > modulus // 2:
                wrap_offset += modulus
        unwrapped_tick = tick + wrap_offset
        unwrapped.append(unwrapped_tick)
        segments.append(segment)
        previous_tick = tick
        previous_sequence = sequence

    df = df.copy()
    df["continuity_segment"] = segments
    df["native_tick_unwrapped"] = unwrapped
    native_time_s: list[float] = []
    first_by_segment: dict[int, int] = {}
    for segment_id, tick in zip(segments, unwrapped):
        first_by_segment.setdefault(segment_id, tick)
        native_time_s.append((tick - first_by_segment[segment_id]) * tick_period_us / 1_000_000.0)
    df["native_time_s"] = native_time_s
    return df


def bdq_to_stream_dataframes(input_path: str | Path) -> dict[str, pd.DataFrame]:
    """Decode every BDQ v2 stream onto its native clock without merging grids."""
    path = Path(input_path)
    data = path.read_bytes()
    info = _read_bdq_bytes(path, data)
    if info.header.format_major != 2:
        raise ValueError("stream dataframe decoding requires a BDQ v2 file")
    descriptors_by_id = _validate_stream_catalog(info.stream_catalog)
    records_by_id: dict[int, list[dict[str, Any]]] = {
        stream_id: [] for stream_id in descriptors_by_id
    }
    for chunk in _iter_valid_data_payloads(data, info.header):
        parsed = _summarize_stream_data_chunk(chunk, descriptors_by_id)
        records_by_id[parsed.stream_id].extend(
            _decode_stream_chunk_records(
                chunk,
                parsed,
                descriptors_by_id[parsed.stream_id],
            )
        )
    frames: dict[str, pd.DataFrame] = {}
    for stream_id, descriptor in descriptors_by_id.items():
        stream_key = str(descriptor["stream_key"])
        df = pd.DataFrame.from_records(records_by_id[stream_id])
        if not df.empty:
            df = _decorate_native_time(df, descriptor)
            if descriptor.get("clock_id") == "logger_monotonic":
                df["time_s"] = df["native_time_s"]
        frames[stream_key] = df
    return frames


def iter_bdq_rows(path: str | Path) -> Iterator[dict[str, Any]]:
    input_path = Path(path)
    data = input_path.read_bytes()
    header = _read_file_header(data)
    if header.format_major == 2:
        yield from iter_bdq_stream_records(input_path, "primary")
        return
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


def bdq_primary_dataframe_from_streams(
    info: BdqReadResult,
    frames: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Project the native v2 primary stream into the legacy primary dataframe shape."""
    if info.header.format_major != 2:
        raise ValueError("primary stream projection requires BDQ v2 metadata")
    primary = frames.get("primary")
    if not isinstance(primary, pd.DataFrame) or primary.empty:
        raise ValueError(f"BDQ v2 file has no decodable primary stream: {info.path.name}")
    descriptor = _stream_descriptor(info, "primary")
    column_map = _bdq_dataframe_column_map(descriptor)
    primary = primary.rename(
        columns={field: column for field, column in column_map.items() if field in primary.columns}
    )
    ordered = [
        column
        for column in ("time_s", "sequence", "native_tick", "status_flags")
        if column in primary.columns
    ]
    ordered.extend(column for column in primary.columns if column not in ordered)
    return primary.loc[:, ordered]


def bdq_to_dataframe(input_path: str | Path) -> pd.DataFrame:
    """Decode a BDQ file into a dataframe suitable for the preprocessing pipeline."""
    info = read_bdq(input_path)
    if not info.metadata:
        raise ValueError(f"BDQ file has no metadata chunk: {Path(input_path).name}")
    if info.header.format_major == 2:
        if not info.stream_catalog:
            raise ValueError(f"BDQ v2 file has no stream catalog: {Path(input_path).name}")
        frames = bdq_to_stream_dataframes(input_path)
        return bdq_primary_dataframe_from_streams(info, frames)
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


def _stream_sample_rate_hz(descriptor: Mapping[str, Any]) -> Optional[float]:
    timebase = descriptor.get("timebase")
    if not isinstance(timebase, Mapping):
        return None
    value = _rational_value(timebase.get("nominal_sample_rate_hz"))
    return value if value is not None and value > 0 else None


def _bdq_v2_to_log_metadata(info: BdqReadResult) -> dict[str, Any]:
    metadata = info.metadata
    descriptors = _stream_descriptors(info.stream_catalog)
    session_id = _text_or_none(metadata.get("recording_id")) or info.path.stem

    declared_streams: dict[str, Any] = {}
    secondary_streams: dict[str, Any] = {}
    primary_descriptor: Optional[dict[str, Any]] = None
    for descriptor in descriptors:
        stream_key = str(descriptor["stream_key"])
        sample_rate_hz = _stream_sample_rate_hz(descriptor)
        is_primary = stream_key == "primary"
        if is_primary:
            primary_descriptor = descriptor
        declared_streams[stream_key] = {
            "type": "uniform" if descriptor.get("stream_kind") == "regular" else "intermittent",
            "time_column": "time_s" if is_primary else "native_time_s",
            "time_encoding": "elapsed_s",
            "time_unit": "s",
            "sample_rate_hz": sample_rate_hz,
            "stream_id": descriptor.get("stream_id"),
            "clock_id": descriptor.get("clock_id"),
            "transport": descriptor.get("transport"),
        }
        if not is_primary:
            signals: dict[str, Any] = {}
            for channel in _schema_channels(descriptor):
                if _bdq_column_class(channel) != "signal":
                    continue
                field_name = _text_or_none(channel.get("field"))
                if field_name is not None:
                    signals[field_name] = {
                        key: copy.deepcopy(channel[key])
                        for key in (
                            "quantity",
                            "component",
                            "coordinate_frame",
                            "vector_group",
                            "unit",
                            "domain",
                            "end",
                            "sensor",
                        )
                        if key in channel
                    }
            secondary_streams[stream_key] = {
                "schema": "bdq.native_stream.v1",
                "stream_id": descriptor.get("stream_id"),
                "stream_key": stream_key,
                "sensor": descriptor.get("sensor_id"),
                "source_device_id": descriptor.get("source_device_id"),
                "clock_id": descriptor.get("clock_id"),
                "transport": descriptor.get("transport"),
                "timebase": copy.deepcopy(descriptor.get("timebase")),
                "acquisition": copy.deepcopy(descriptor.get("acquisition")),
                "signals": signals,
            }

    columns: dict[str, Any] = {}
    if primary_descriptor is not None:
        columns["time_s"] = {
            "class": "time",
            "dtype": "float64",
            "stream": "primary",
            "unit": "s",
        }
        column_map = _bdq_dataframe_column_map(primary_descriptor)
        for channel in _schema_channels(primary_descriptor):
            field_name = _text_or_none(channel.get("field"))
            if field_name is None:
                continue
            dataframe_column = column_map.get(field_name, field_name)
            channel_class = _bdq_column_class(channel)
            entry: dict[str, Any] = {
                "class": channel_class,
                "stream": "primary",
                "unit": _text_or_none(channel.get("unit")) or "",
                "storage_type": _text_or_none(channel.get("storage_type")),
                "source_columns": [field_name],
                "bdq_field": field_name,
                "raw": False if channel_class == "diagnostic" else bool(channel.get("raw", False)),
            }
            for key in (
                "quantity",
                "metric",
                "sensor",
                "domain",
                "end",
                "component",
                "coordinate_frame",
                "vector_group",
                "source",
            ):
                if key in channel:
                    entry[key] = copy.deepcopy(channel[key])
            columns[dataframe_column] = entry

    run_stats = dict(info.final_summary) if isinstance(info.final_summary, Mapping) else {}
    if info.detected_errors:
        run_stats["bdq_parser_errors"] = list(info.detected_errors)

    log_metadata: dict[str, Any] = {
        "contract": {
            "name": "bdq.v2",
            "version": f"{info.header.format_major}.{info.header.format_minor}",
            "sidecar_kind": "embedded",
        },
        "session": {
            "session_id": session_id,
            "started_at_utc": _text_or_none(metadata.get("started_at_utc")),
            "started_at_local": _text_or_none(metadata.get("started_at_local")),
            "timezone": _text_or_none(metadata.get("timezone")),
        },
        "data_file": {"format": "bdq", "path": str(info.path)},
        "streams": declared_streams,
        "columns": columns,
        "secondary_streams": secondary_streams,
        "provenance": {
            "logger_family": "BODAQS",
            "firmware_version": _text_or_none(metadata.get("firmware_version")),
            "firmware_build": _text_or_none(metadata.get("firmware_build")),
            "generator": "bdq.v2",
            "metadata_generated_at": _text_or_none(metadata.get("started_at_utc")),
            "device_id": _text_or_none(metadata.get("device_id")),
            "hardware_version": _text_or_none(metadata.get("hardware_version")),
        },
        "qc": {"run_stats": run_stats},
        "bdq": {
            "metadata": dict(metadata),
            "stream_catalog": copy.deepcopy(info.stream_catalog),
            "detected_errors": list(info.detected_errors),
            "record_count": info.sample_count,
            "stream_count": info.stream_count,
            "event_count": len(info.events),
        },
    }
    for key in ("imu_configs", "device_configs", "sensors"):
        value = metadata.get(key)
        if isinstance(value, Mapping):
            log_metadata[key] = copy.deepcopy(dict(value))
    return log_metadata


def bdq_to_log_metadata(info: BdqReadResult) -> dict[str, Any]:
    """Map BDQ embedded metadata/schema into the existing logger metadata shape."""
    if info.header.format_major == 2:
        return _bdq_v2_to_log_metadata(info)
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
            "mount_point",
            "component",
            "coordinate_frame",
            "vector_group",
            "processing_role",
            "calibration_ref",
            "transform_chain",
            "notes",
            "required",
            "primary",
            "calibrated",
            "transformed",
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

    qc: dict[str, Any] = {
        "run_stats": run_stats,
    }
    sensor_runtime_diagnostics = run_stats.get("sensor_runtime_diagnostics")
    if isinstance(sensor_runtime_diagnostics, Mapping):
        qc["sensor_runtime_diagnostics"] = copy.deepcopy(dict(sensor_runtime_diagnostics))

    log_metadata = {
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
        "qc": qc,
        "bdq": {
            "metadata": dict(metadata),
            "channel_schema": dict(schema),
            "detected_errors": list(info.detected_errors),
            "sample_count": info.sample_count,
            "first_sample_id": info.first_sample_id,
            "last_sample_id": info.last_sample_id,
        },
    }
    imu_configs = metadata.get("imu_configs")
    if isinstance(imu_configs, Mapping):
        log_metadata["imu_configs"] = copy.deepcopy(dict(imu_configs))
    device_configs = metadata.get("device_configs")
    if isinstance(device_configs, Mapping):
        log_metadata["device_configs"] = copy.deepcopy(dict(device_configs))
    sensors = metadata.get("sensors")
    if isinstance(sensors, Mapping):
        log_metadata["sensors"] = copy.deepcopy(dict(sensors))
    return log_metadata


def bdq_to_csv(input_path: str | Path, output_path: str | Path) -> None:
    info = read_bdq(input_path)
    schema = info.channel_schema
    if info.header.format_major == 2:
        schema = _stream_descriptor(info, "primary")
    channels = _schema_channels(schema)
    fieldnames = [channel["field"] for channel in channels if isinstance(channel, dict) and isinstance(channel.get("field"), str)]
    rows = iter_bdq_rows(input_path)

    with Path(output_path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summary_lines(info: BdqReadResult) -> list[str]:
    errors = ", ".join(info.detected_errors) if info.detected_errors else "none"
    if info.header.format_major == 2:
        return [
            f"format version: {info.header.format_major}.{info.header.format_minor}",
            f"metadata: {json.dumps(info.metadata, sort_keys=True)}",
            f"stream catalog: {json.dumps(info.stream_catalog, sort_keys=True)}",
            f"final summary: {json.dumps(info.final_summary, sort_keys=True)}",
            f"valid chunks: {info.valid_chunk_count}",
            f"valid stream-data chunks: {len(info.stream_data_chunks)}",
            f"streams: {info.stream_count}",
            f"records: {info.sample_count}",
            f"events: {len(info.events)}",
            f"detected errors: {errors}",
        ]
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
