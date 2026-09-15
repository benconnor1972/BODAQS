from __future__ import annotations

import binascii
import json
import struct
from pathlib import Path

import pandas as pd
import pytest

from bodaqs_analysis.io_bdq import (
    CHUNK_MAGIC,
    FILE_MAGIC_V2,
    STREAM_DATA_HEADER_STRUCT,
    STREAM_RECORD_PREFIX_STRUCT,
    TIME_OBSERVATION_STRUCT,
    bdq_to_dataframe,
    bdq_to_log_metadata,
    bdq_to_stream_dataframes,
    iter_bdq_stream_records,
    iter_bdq_time_observations,
    read_bdq,
)
from bodaqs_analysis.pipeline import load_bdq_session


FILE_HEADER = struct.Struct("<8sHHIQII")
CHUNK_HEADER = struct.Struct("<4sHHIII")


def _crc32(payload: bytes) -> int:
    return binascii.crc32(payload) & 0xFFFFFFFF


def _chunk(chunk_type: int, sequence: int, payload: bytes) -> bytes:
    return CHUNK_HEADER.pack(
        CHUNK_MAGIC, 1, chunk_type, sequence, len(payload), _crc32(payload)
    ) + payload


def _json_chunk(chunk_type: int, sequence: int, payload: dict) -> bytes:
    return _chunk(
        chunk_type,
        sequence,
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )


def _prefix_channels() -> list[dict]:
    return [
        {
            "field": "sequence",
            "quantity": "sample_sequence",
            "unit": "count",
            "storage_type": "uint32",
            "byte_offset": 0,
            "class": "diagnostic",
        },
        {
            "field": "native_tick",
            "quantity": "sensor_time",
            "unit": "tick",
            "storage_type": "uint32",
            "byte_offset": 4,
            "class": "diagnostic",
        },
        {
            "field": "status_flags",
            "quantity": "status",
            "unit": "bitfield",
            "storage_type": "uint16",
            "byte_offset": 8,
            "class": "diagnostic",
        },
    ]


def _primary_descriptor() -> dict:
    return {
        "stream_id": 1,
        "stream_key": "primary",
        "stream_kind": "regular",
        "sensor_id": None,
        "source_device_id": "A8_001",
        "transport": "local",
        "clock_id": "logger_monotonic",
        "record_format": "fixed_mixed_v2",
        "record_size_bytes": 16,
        "timebase": {
            "type": "native_ticks",
            "native_tick_field": "native_tick",
            "native_tick_bits": 32,
            "native_tick_modulus": 1 << 32,
            "nominal_tick_period_us": {"numerator": 1, "denominator": 1},
            "nominal_sample_rate_hz": {"numerator": 200, "denominator": 1},
            "expected_sequence_step": 1,
            "clock_relation": "logger_monotonic",
        },
        "channels": _prefix_channels()
        + [
            {
                "field": "suspension_raw",
                "quantity": "raw",
                "unit": "count",
                "storage_type": "int16",
                "byte_offset": 12,
                "class": "signal",
                "domain": "suspension",
            }
        ],
        "status_flags": {"discontinuity_before": 1},
    }


def _imu_descriptor(stream_id: int) -> dict:
    sensor_id = f"imu_{stream_id - 1}"
    signal_channels: list[dict] = []
    offset = 12
    for group, quantity in (
        ("accel", "linear_acceleration_raw"),
        ("gyro", "angular_velocity_raw"),
    ):
        for component in "xyz":
            signal_channels.append(
                {
                    "field": f"{group}_{component}_raw",
                    "quantity": quantity,
                    "component": component,
                    "coordinate_frame": "sensor_native",
                    "vector_group": f"{group}_raw",
                    "unit": "count",
                    "storage_type": "int16",
                    "byte_offset": offset,
                    "class": "signal",
                    "sensor": sensor_id,
                }
            )
            offset += 2
    return {
        "stream_id": stream_id,
        "stream_key": sensor_id,
        "stream_kind": "regular",
        "sensor_id": sensor_id,
        "source_device_id": "A8_001",
        "transport": "i2c_direct",
        "clock_id": f"bmi270:{sensor_id}",
        "record_format": "fixed_mixed_v2",
        "record_size_bytes": 28,
        "timebase": {
            "type": "native_ticks",
            "native_tick_field": "native_tick",
            "native_tick_bits": 24,
            "native_tick_modulus": 1 << 24,
            "nominal_tick_period_us": {"numerator": 625, "denominator": 16},
            "nominal_sample_rate_hz": {"numerator": 1600, "denominator": 1},
            "expected_sequence_step": 1,
            "clock_relation": "independent",
        },
        "acquisition": {
            "effective_accel_rate_hz": 1600,
            "effective_gyro_rate_hz": 1600,
        },
        "channels": _prefix_channels()
        + signal_channels
        + [
            {
                "field": "temperature_raw",
                "quantity": "temperature_raw",
                "unit": "count",
                "storage_type": "int16",
                "byte_offset": 24,
                "class": "diagnostic",
            }
        ],
        "status_flags": {
            "discontinuity_before": 1,
            "producer_queue_drop_before": 2,
            "source_recovery_before": 4,
            "timing_degraded": 8,
            "native_tick_estimated": 16,
        },
    }


def _metadata() -> dict:
    return {
        "format": "bdq.v2",
        "format_name": "BDQLOG v2",
        "recording_id": "260913_120000",
        "device_id": "A8_001",
        "firmware_name": "BODAQS",
        "firmware_version": "0.6.0",
        "hardware_version": "BODAQS A8",
        "created_unix_us": 1_789_272_000_000_000,
        "timezone": "Australia/Perth",
        "log_format": "bodaqs_multi_stream_binary",
        "native_stream_contract": "bodaqs.native_stream.v1",
        "stream_count": 5,
        "logger_monotonic_clock": {
            "clock_id": "logger_monotonic",
            "unit": "us",
            "nondecreasing": True,
        },
    }


def _catalog() -> dict:
    return {
        "schema_format": "bdq.stream_catalog.v1",
        "endianness": "little",
        "record_prefix": {
            "format": "bdq.stream_record_prefix.v1",
            "size_bytes": STREAM_RECORD_PREFIX_STRUCT.size,
        },
        "streams": [_primary_descriptor()] + [_imu_descriptor(i) for i in range(2, 6)],
    }


def _primary_record(sequence: int, tick: int, value: int, status: int = 0) -> bytes:
    return STREAM_RECORD_PREFIX_STRUCT.pack(sequence, tick, status, 0) + struct.pack(
        "<hH", value, 0
    )


def _imu_record(sequence: int, tick: int, base: int, status: int = 0) -> bytes:
    axes = (base, base + 1, base + 2, -base, -base - 1, -base - 2)
    return (
        STREAM_RECORD_PREFIX_STRUCT.pack(sequence, tick, status, 0)
        + struct.pack("<hhhhhhh", *axes, 512)
        + b"\x00\x00"
    )


def _observation(tick: int, sequence: int, host_min: int, host_max: int) -> bytes:
    return TIME_OBSERVATION_STRUCT.pack(tick, sequence, host_min, host_max, 1, 2, 0)


def _stream_data(
    stream_id: int,
    record_size: int,
    records: list[bytes],
    observations: list[bytes],
    *,
    first_sequence: int | None = None,
) -> bytes:
    first = first_sequence
    if first is None:
        first = struct.unpack_from("<I", records[0], 0)[0] if records else 0
    return (
        STREAM_DATA_HEADER_STRUCT.pack(
            stream_id, 1, 0, first, len(records), record_size, len(observations), 0
        )
        + b"".join(records)
        + b"".join(observations)
    )


def _bdq_v2_bytes(*, bad_stream_id: int | None = None) -> bytes:
    header = FILE_HEADER.pack(
        FILE_MAGIC_V2, 2, 0, FILE_HEADER.size, 1_789_272_000_000_000, 0, 0
    )
    chunks = [
        _json_chunk(1, 0, _metadata()),
        _json_chunk(2, 1, _catalog()),
        _chunk(
            3,
            2,
            _stream_data(
                2 if bad_stream_id is None else bad_stream_id,
                28,
                [
                    _imu_record(10, 0xFFFFF8, 100),
                    _imu_record(11, 0x000008, 110),
                ],
                [_observation(0x000008, 11, 1_000_000, 1_000_120)],
            ),
        ),
        _chunk(
            3,
            3,
            _stream_data(
                1,
                16,
                [_primary_record(0, 100_000, 200), _primary_record(1, 105_000, 201)],
                [_observation(105_000, 1, 105_000, 105_000)],
            ),
        ),
    ]
    for stream_id in range(3, 6):
        chunks.append(
            _chunk(
                3,
                stream_id + 1,
                _stream_data(
                    stream_id,
                    28,
                    [
                        _imu_record(20, 1000, stream_id * 100),
                        _imu_record(21, 1016, stream_id * 100 + 10),
                    ],
                    [_observation(1016, 21, stream_id * 1_000_000, stream_id * 1_000_000 + 80)],
                ),
            )
        )
    chunks.append(
        _json_chunk(
            4,
            7,
            {
                "event_format": "bdq.events.v1",
                "events": [
                    {
                        "event_id": 1,
                        "event_type": "user_mark",
                        "host_monotonic_us": 103_000,
                        "unix_us": None,
                        "stream_id": None,
                        "payload": {},
                    }
                ],
            },
        )
    )
    chunks.append(
        _json_chunk(
            5,
            8,
            {
                "summary_format": "bdq.final_summary.v2",
                "streams": [{"stream_id": i, "records_written": 2} for i in range(1, 6)],
            },
        )
    )
    return header + b"".join(chunks)


def test_read_v2_counts_streams_records_observations_and_events(tmp_path: Path) -> None:
    path = tmp_path / "multi.bdq"
    path.write_bytes(_bdq_v2_bytes())

    info = read_bdq(path)

    assert info.header.format_major == 2
    assert info.metadata["native_stream_contract"] == "bodaqs.native_stream.v1"
    assert info.stream_count == 5
    assert info.sample_count == 10
    assert info.stream_record_count(2) == 2
    assert len(info.stream_data_chunks) == 5
    assert len(info.events) == 1
    assert info.events[0]["event_type"] == "user_mark"
    assert info.detected_errors == ()

    [observation] = list(iter_bdq_time_observations(path, "imu_1"))
    assert observation.native_tick == 0x000008
    assert observation.host_max_us - observation.host_min_us == 120


def test_v2_native_stream_decode_preserves_signed_values_and_tick_wrap(tmp_path: Path) -> None:
    path = tmp_path / "multi.bdq"
    path.write_bytes(_bdq_v2_bytes())

    rows = list(iter_bdq_stream_records(path, "imu_1"))
    assert [row["sequence"] for row in rows] == [10, 11]
    assert rows[0]["accel_x_raw"] == 100
    assert rows[0]["gyro_x_raw"] == -100

    frames = bdq_to_stream_dataframes(path)
    imu = frames["imu_1"]
    assert imu["native_tick_unwrapped"].tolist() == [0xFFFFF8, 0x1000008]
    assert imu["native_time_s"].tolist() == pytest.approx([0.0, 0.000625])
    assert imu["continuity_segment"].tolist() == [0, 0]
    assert "time_s" not in imu.columns


def test_v2_primary_dataframe_uses_logger_monotonic_clock(tmp_path: Path) -> None:
    path = tmp_path / "multi.bdq"
    path.write_bytes(_bdq_v2_bytes())

    df = bdq_to_dataframe(path)

    assert isinstance(df, pd.DataFrame)
    assert df["sequence"].tolist() == [0, 1]
    assert df["time_s"].tolist() == pytest.approx([0.0, 0.005])
    assert df["suspension_raw_dom_suspension [count]"].tolist() == [200, 201]


def test_v2_metadata_and_pipeline_expose_native_secondary_streams(tmp_path: Path) -> None:
    path = tmp_path / "multi.bdq"
    path.write_bytes(_bdq_v2_bytes())

    info = read_bdq(path)
    metadata = bdq_to_log_metadata(info)
    session = load_bdq_session(path)

    assert metadata["contract"]["name"] == "bdq.v2"
    assert metadata["streams"]["imu_1"]["clock_id"] == "bmi270:imu_1"
    assert metadata["secondary_streams"]["imu_1"]["schema"] == "bdq.native_stream.v1"
    assert set(session["stream_dfs"]) == {"imu_1", "imu_2", "imu_3", "imu_4"}
    assert session["meta"]["bdq_events"][0]["event_type"] == "user_mark"
    assert session["meta"]["bdq_timing_observations"]["imu_1"][0]["kind"] == 1


def test_v2_rejects_undeclared_stream_id_without_discarding_prior_chunks(tmp_path: Path) -> None:
    path = tmp_path / "bad_stream.bdq"
    path.write_bytes(_bdq_v2_bytes(bad_stream_id=99))

    info = read_bdq(path)

    assert info.sample_count == 0
    assert info.detected_errors
    assert "undeclared stream_id 99" in info.detected_errors[0]
    assert info.valid_chunk_count == 3


def test_v2_accepts_observation_only_stream_data_chunk(tmp_path: Path) -> None:
    raw = _bdq_v2_bytes()
    info_path = tmp_path / "base.bdq"
    info_path.write_bytes(raw)
    base_info = read_bdq(info_path)
    assert not base_info.detected_errors

    header = FILE_HEADER.pack(FILE_MAGIC_V2, 2, 0, FILE_HEADER.size, 0, 0, 0)
    chunks = [
        _json_chunk(1, 0, _metadata()),
        _json_chunk(2, 1, _catalog()),
        _chunk(
            3,
            2,
            _stream_data(
                2,
                28,
                [],
                [_observation(1234, 0xFFFFFFFF, 5000, 5100)],
                first_sequence=0xFFFFFFFF,
            ),
        ),
    ]
    path = tmp_path / "observation_only.bdq"
    path.write_bytes(header + b"".join(chunks))

    info = read_bdq(path)
    assert info.sample_count == 0
    assert len(info.stream_data_chunks) == 1
    assert info.stream_data_chunks[0].record_count == 0
    assert info.stream_data_chunks[0].observations[0].related_sequence == 0xFFFFFFFF
    assert info.detected_errors == ()
