from __future__ import annotations

import binascii
import json
import struct
from pathlib import Path

import pytest

from bodaqs_analysis.io_bdq import CHUNK_MAGIC, FILE_MAGIC, iter_bdq_rows


FILE_HEADER = struct.Struct("<8sHHIQII")
CHUNK_HEADER = struct.Struct("<4sHHIII")
DATA_HEADER = struct.Struct("<IIQHH")
IMU_FRAME = struct.Struct("<IhhhIIH")
LEGACY_FRAME = struct.Struct("<IHifH")


def _crc32(payload: bytes) -> int:
    return binascii.crc32(payload) & 0xFFFFFFFF


def _chunk(chunk_type: int, sequence: int, payload: bytes) -> bytes:
    return CHUNK_HEADER.pack(CHUNK_MAGIC, 1, chunk_type, sequence, len(payload), _crc32(payload)) + payload


def _json_chunk(chunk_type: int, sequence: int, payload: dict) -> bytes:
    return _chunk(chunk_type, sequence, json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _schema(*, accel_storage_type: str = "int16") -> dict:
    return {
        "schema_format": "bdq.channel_schema.v1",
        "frame_layout": "fixed_mixed_v1",
        "endianness": "little",
        "frame_size_bytes": IMU_FRAME.size,
        "timebase": {
            "type": "fixed_rate",
            "sample_rate_hz": 500,
            "sample_period_us": 2000,
            "timestamp_per_sample": False,
        },
        "channels": [
            {
                "field": "sample_id",
                "quantity": "sample_index",
                "unit": "sample",
                "storage_type": "uint32",
                "byte_offset": 0,
            },
            {
                "field": "frame_imu_accel_x_raw",
                "quantity": "linear_acceleration_raw",
                "unit": "count",
                "storage_type": accel_storage_type,
                "byte_offset": 4,
            },
            {
                "field": "frame_imu_accel_y_raw",
                "quantity": "linear_acceleration_raw",
                "unit": "count",
                "storage_type": "int16",
                "byte_offset": 6,
            },
            {
                "field": "frame_imu_accel_z_raw",
                "quantity": "linear_acceleration_raw",
                "unit": "count",
                "storage_type": "int16",
                "byte_offset": 8,
            },
            {
                "field": "frame_imu_sensor_time_u24",
                "quantity": "sensor_time",
                "unit": "tick",
                "storage_type": "uint32",
                "byte_offset": 10,
            },
            {
                "field": "frame_imu_seq_u24",
                "quantity": "sample_sequence",
                "unit": "count",
                "storage_type": "uint32",
                "byte_offset": 14,
            },
            {
                "field": "flags",
                "quantity": "flags",
                "unit": "bitfield",
                "storage_type": "uint16",
                "byte_offset": 18,
            },
        ],
    }


def _bdq_bytes(*, accel_storage_type: str = "int16") -> bytes:
    metadata = {
        "format": "bdq.v1",
        "recording_id": "imu-storage-fixture",
        "created_unix_us": 0,
        "sample_rate_hz": 500,
        "sample_period_us": 2000,
        "timezone": "Australia/Perth",
        "log_format": "bodaqs_compact_binary",
    }
    frames = [
        IMU_FRAME.pack(0, -32768, -1, 0, 0, 0, 0),
        IMU_FRAME.pack(1, 32767, 1, 1234, 1, 1, 0),
        IMU_FRAME.pack(2, -123, 0, 1, 0xFFFFFE, 0xFFFFFE, 0),
        IMU_FRAME.pack(3, 0, 32767, -32768, 0xFFFFFF, 0xFFFFFF, 0),
    ]
    data = DATA_HEADER.pack(0, len(frames), 0, IMU_FRAME.size, 0) + b"".join(frames)
    header = FILE_HEADER.pack(FILE_MAGIC, 1, 0, FILE_HEADER.size, 0, 0, 0)
    return header + b"".join(
        [
            _json_chunk(1, 0, metadata),
            _json_chunk(2, 1, _schema(accel_storage_type=accel_storage_type)),
            _chunk(3, 2, data),
            _json_chunk(5, 3, {"summary_format": "bdq.final_summary.v1", "samples_written": len(frames)}),
        ]
    )


def _legacy_bdq_bytes() -> bytes:
    metadata = {
        "format": "bdq.v1",
        "recording_id": "legacy-storage-fixture",
        "sample_rate_hz": 500,
        "sample_period_us": 2000,
    }
    schema = {
        "schema_format": "bdq.channel_schema.v1",
        "frame_layout": "fixed_mixed_v1",
        "endianness": "little",
        "frame_size_bytes": LEGACY_FRAME.size,
        "channels": [
            {"field": "sample_id", "storage_type": "uint32", "byte_offset": 0},
            {"field": "wrapped_raw", "storage_type": "uint16", "byte_offset": 4},
            {"field": "unwrapped_raw", "storage_type": "int32", "byte_offset": 6},
            {"field": "travel", "storage_type": "float32", "byte_offset": 10},
            {"field": "flags", "storage_type": "uint16", "byte_offset": 14},
        ],
    }
    frame = LEGACY_FRAME.pack(7, 65535, -123456, 12.5, 1)
    data = DATA_HEADER.pack(7, 1, 0, LEGACY_FRAME.size, 0) + frame
    header = FILE_HEADER.pack(FILE_MAGIC, 1, 0, FILE_HEADER.size, 0, 0, 0)
    return header + b"".join(
        [
            _json_chunk(1, 0, metadata),
            _json_chunk(2, 1, schema),
            _chunk(3, 2, data),
        ]
    )


def test_iter_rows_decodes_int16_and_exact_u24_boundaries(tmp_path: Path) -> None:
    path = tmp_path / "typed_imu.bdq"
    path.write_bytes(_bdq_bytes())

    rows = list(iter_bdq_rows(path))

    assert [row["frame_imu_accel_x_raw"] for row in rows] == [-32768, 32767, -123, 0]
    assert [row["frame_imu_accel_y_raw"] for row in rows] == [-1, 1, 0, 32767]
    assert [row["frame_imu_accel_z_raw"] for row in rows] == [0, 1234, 1, -32768]
    assert [row["frame_imu_sensor_time_u24"] for row in rows] == [0, 1, 0xFFFFFE, 0xFFFFFF]
    assert [row["frame_imu_seq_u24"] for row in rows] == [0, 1, 0xFFFFFE, 0xFFFFFF]


def test_iter_rows_preserves_legacy_storage_types(tmp_path: Path) -> None:
    path = tmp_path / "legacy_storage.bdq"
    path.write_bytes(_legacy_bdq_bytes())

    [row] = list(iter_bdq_rows(path))

    assert row == {
        "sample_id": 7,
        "wrapped_raw": 65535,
        "unwrapped_raw": -123456,
        "travel": 12.5,
        "flags": 1,
    }


def test_iter_rows_rejects_unsupported_storage_type_clearly(tmp_path: Path) -> None:
    path = tmp_path / "unsupported_storage.bdq"
    path.write_bytes(_bdq_bytes(accel_storage_type="int24"))

    with pytest.raises(ValueError, match="unsupported BDQ storage type.*int24"):
        list(iter_bdq_rows(path))
