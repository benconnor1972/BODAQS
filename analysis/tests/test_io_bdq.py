from __future__ import annotations

import binascii
import csv
import json
import math
import struct
from pathlib import Path

import pandas as pd
import pytest

from bodaqs_analysis.io_bdq import (
    CHUNK_MAGIC,
    FILE_MAGIC,
    BDQ_SUFFIX,
    bdq_to_dataframe,
    bdq_to_csv,
    bdq_to_log_metadata,
    is_bdq_path,
    iter_bdq_rows,
    read_bdq,
)
from bodaqs_analysis.pipeline import load_bdq_session
from bodaqs_analysis.signal_registry import build_signals_registry
from bodaqs_analysis.signal_standardize import validate_signals_semantics


FILE_HEADER = struct.Struct("<8sHHIQII")
CHUNK_HEADER = struct.Struct("<4sHHIII")
DATA_HEADER = struct.Struct("<IIQHH")


def _crc32(payload: bytes) -> int:
    return binascii.crc32(payload) & 0xFFFFFFFF


def _chunk(chunk_type: int, sequence: int, payload: bytes) -> bytes:
    return CHUNK_HEADER.pack(CHUNK_MAGIC, 1, chunk_type, sequence, len(payload), _crc32(payload)) + payload


def _json_chunk(chunk_type: int, sequence: int, payload: dict) -> bytes:
    return _chunk(chunk_type, sequence, json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _metadata() -> dict:
    return {
        "format": "bdq.v1",
        "device_id": "Prototype_E",
        "firmware_version": "0.3.0",
        "recording_id": "260516_201542",
        "created_unix_us": 1_768_998_942_000_000,
        "sample_rate_hz": 500,
        "sample_period_us": 2000,
        "timezone": "Australia/Perth",
        "log_format": "bodaqs_compact_binary",
    }


def _schema(frame_size: int = 12) -> dict:
    return {
        "schema_format": "bdq.channel_schema.v1",
        "frame_layout": "fixed_mixed_v1",
        "endianness": "little",
        "frame_size_bytes": frame_size,
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
                "field": "front_raw",
                "quantity": "raw",
                "unit": "counts",
                "storage_type": "uint16",
                "byte_offset": 4,
                "sensor": "front",
                "source": "raw_counts",
            },
            {
                "field": "front_travel",
                "quantity": "disp",
                "unit": "mm",
                "storage_type": "float32",
                "byte_offset": 6,
                "sensor": "front",
                "source": "linear_calibrated",
            },
            {
                "field": "flags",
                "quantity": "flags",
                "unit": "bitfield",
                "storage_type": "uint16",
                "byte_offset": 10,
            },
        ],
    }


def _frame(sample_id: int, raw: int, travel: float, flags: int = 0) -> bytes:
    return struct.pack("<IHfH", sample_id, raw, travel, flags)


def _data_chunk(first_sample_id: int, rows: list[tuple[int, int, float, int]], *, frame_size: int = 12) -> bytes:
    payload = DATA_HEADER.pack(first_sample_id, len(rows), 0, frame_size, 0)
    payload += b"".join(_frame(*row) for row in rows)
    return payload


def _bdq_bytes(*, schema_frame_size: int = 12, data_frame_size: int = 12, include_second_chunk: bool = True) -> bytes:
    header = FILE_HEADER.pack(FILE_MAGIC, 1, 0, FILE_HEADER.size, 1_768_998_942_000_000, 0, 0)
    chunks = [
        _json_chunk(1, 0, _metadata()),
        _json_chunk(2, 1, _schema(schema_frame_size)),
        _chunk(3, 2, _data_chunk(0, [(0, 100, 1.5, 0), (1, 101, 1.75, 1)], frame_size=data_frame_size)),
    ]
    if include_second_chunk:
        chunks.append(_chunk(3, 3, _data_chunk(2, [(2, 102, 2.0, 0)], frame_size=data_frame_size)))
    chunks.append(_json_chunk(5, 4, {"summary_format": "bdq.final_summary.v1", "samples_written": 3}))
    return header + b"".join(chunks)


def _schema_with_diagnostic() -> dict:
    schema = _schema(frame_size=14)
    schema["channels"].insert(
        3,
        {
            "field": "front_agc",
            "class": "diagnostic",
            "quantity": "agc",
            "unit": "counts",
            "storage_type": "uint16",
            "byte_offset": 10,
            "sensor": "front",
            "source": "as5600_diagnostic",
            "raw": True,
            "kind": "raw",
        },
    )
    schema["channels"][4]["byte_offset"] = 12
    return schema


def _diagnostic_frame(sample_id: int, raw: int, travel: float, agc: int, flags: int = 0) -> bytes:
    return struct.pack("<IHfHH", sample_id, raw, travel, agc, flags)


def _diagnostic_data_chunk(first_sample_id: int, rows: list[tuple[int, int, float, int, int]]) -> bytes:
    payload = DATA_HEADER.pack(first_sample_id, len(rows), 0, 14, 0)
    payload += b"".join(_diagnostic_frame(*row) for row in rows)
    return payload


def _bdq_bytes_with_diagnostic() -> bytes:
    header = FILE_HEADER.pack(FILE_MAGIC, 1, 0, FILE_HEADER.size, 1_768_998_942_000_000, 0, 0)
    chunks = [
        _json_chunk(1, 0, _metadata()),
        _json_chunk(2, 1, _schema_with_diagnostic()),
        _chunk(3, 2, _diagnostic_data_chunk(0, [(0, 100, 1.5, 59, 0), (1, 101, 1.75, 60, 1)])),
        _json_chunk(5, 3, {"summary_format": "bdq.final_summary.v1", "samples_written": 2}),
    ]
    return header + b"".join(chunks)


def test_is_bdq_path() -> None:
    assert is_bdq_path("ride.BDQ")
    assert Path("ride.bdq").suffix == BDQ_SUFFIX
    assert not is_bdq_path("ride.csv")


def test_read_bdq_counts_chunks_and_samples(tmp_path: Path) -> None:
    path = tmp_path / "ride.bdq"
    path.write_bytes(_bdq_bytes())

    info = read_bdq(path)

    assert info.header.format_major == 1
    assert info.metadata["format"] == "bdq.v1"
    assert info.channel_schema["frame_size_bytes"] == 12
    assert len(info.data_chunks) == 2
    assert info.final_summary["samples_written"] == 3
    assert info.sample_count == 3
    assert info.first_sample_id == 0
    assert info.last_sample_id == 2
    assert info.detected_errors == ()


def test_rejects_wrong_magic(tmp_path: Path) -> None:
    path = tmp_path / "bad.bdq"
    path.write_bytes(FILE_HEADER.pack(b"NOTBDQ!!", 1, 0, FILE_HEADER.size, 0, 0, 0))

    with pytest.raises(ValueError, match="wrong magic"):
        read_bdq(path)


def test_truncated_final_chunk_keeps_prior_data(tmp_path: Path) -> None:
    path = tmp_path / "truncated.bdq"
    valid = _bdq_bytes(include_second_chunk=False)
    broken_header = CHUNK_HEADER.pack(CHUNK_MAGIC, 1, 3, 9, 100, 0)
    path.write_bytes(valid + broken_header + b"partial")

    info = read_bdq(path)

    assert info.sample_count == 2
    assert len(info.data_chunks) == 1
    assert info.detected_errors
    assert "truncated chunk payload" in info.detected_errors[0]


def test_iter_rows_detects_frame_size_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "mismatch.bdq"
    path.write_bytes(_bdq_bytes(schema_frame_size=12, data_frame_size=10, include_second_chunk=False))

    with pytest.raises(ValueError, match="frame size"):
        list(iter_bdq_rows(path))


def test_bdq_to_csv(tmp_path: Path) -> None:
    path = tmp_path / "ride.bdq"
    out = tmp_path / "ride.csv"
    path.write_bytes(_bdq_bytes())

    bdq_to_csv(path, out)

    rows = list(csv.DictReader(out.open(newline="", encoding="utf-8")))
    assert [row["sample_id"] for row in rows] == ["0", "1", "2"]
    assert [row["front_raw"] for row in rows] == ["100", "101", "102"]
    assert rows[0]["front_travel"].startswith("1.5")
    assert rows[1]["flags"] == "1"


def test_bdq_to_dataframe_adds_time_and_mark(tmp_path: Path) -> None:
    path = tmp_path / "ride.bdq"
    path.write_bytes(_bdq_bytes())

    df = bdq_to_dataframe(path)

    assert df["time_s"].tolist() == pytest.approx([0.0, 0.002, 0.004])
    assert df["sample_id"].tolist() == [0, 1, 2]
    assert df["mark"].tolist() == [False, True, False]


def test_bdq_to_dataframe_preserves_float_nan_as_numeric(tmp_path: Path) -> None:
    path = tmp_path / "ride.bdq"
    header = FILE_HEADER.pack(FILE_MAGIC, 1, 0, FILE_HEADER.size, 1_768_998_942_000_000, 0, 0)
    chunks = [
        _json_chunk(1, 0, _metadata()),
        _json_chunk(2, 1, _schema()),
        _chunk(3, 2, _data_chunk(0, [(0, 100, 1.5, 0), (1, 101, math.nan, 1)])),
    ]
    path.write_bytes(header + b"".join(chunks))

    df = bdq_to_dataframe(path)

    assert pd.api.types.is_float_dtype(df["front_travel [mm]"])
    assert math.isnan(df["front_travel [mm]"].iloc[1])


def test_bdq_to_log_metadata_maps_schema_for_pipeline(tmp_path: Path) -> None:
    path = tmp_path / "ride.bdq"
    path.write_bytes(_bdq_bytes())
    info = read_bdq(path)

    metadata = bdq_to_log_metadata(info)

    assert metadata["contract"]["name"] == "bdq.v1"
    assert metadata["session"]["session_id"] == "260516_201542"
    assert metadata["streams"]["primary"]["sample_rate_hz"] == pytest.approx(500)
    assert metadata["columns"]["time_s"]["class"] == "time"
    assert metadata["columns"]["front_travel [mm]"]["class"] == "signal"
    assert metadata["columns"]["front_travel [mm]"]["end"] == "front"
    assert metadata["columns"]["front_travel [mm]"]["quantity"] == "disp"
    assert metadata["columns"]["front_travel [mm]"]["unit"] == "mm"
    assert metadata["columns"]["front_travel [mm]"]["bdq_field"] == "front_travel"
    assert metadata["columns"]["flags"]["class"] == "event_flag"
    assert metadata["columns"]["mark"]["class"] == "event_flag"
    assert metadata["qc"]["run_stats"]["samples_written"] == 3


def test_bdq_to_log_metadata_preserves_diagnostic_channels(tmp_path: Path) -> None:
    path = tmp_path / "ride.bdq"
    path.write_bytes(_bdq_bytes_with_diagnostic())

    info = read_bdq(path)
    df = bdq_to_dataframe(path)
    metadata = bdq_to_log_metadata(info)

    assert "front_agc" in df.columns
    assert "front_agc [counts]" not in df.columns

    diagnostic = metadata["columns"]["front_agc"]
    assert diagnostic["class"] == "diagnostic"
    assert diagnostic["metric"] == "agc"
    assert "quantity" not in diagnostic
    assert diagnostic["unit"] == "counts"
    assert diagnostic["sensor"] == "front"
    assert diagnostic["source"] == "as5600_diagnostic"
    assert diagnostic["raw"] is False
    assert "kind" not in diagnostic


def test_bdq_diagnostic_channels_do_not_enter_signal_registry(tmp_path: Path) -> None:
    path = tmp_path / "ride.bdq"
    path.write_bytes(_bdq_bytes_with_diagnostic())

    session = load_bdq_session(path)
    session = build_signals_registry(session, strict=False)
    validate_signals_semantics(session)

    assert "front_agc" in session["df"].columns
    assert session["meta"]["channel_info"]["front_agc"]["class"] == "diagnostic"
    assert session["meta"]["channel_info"]["front_agc"]["metric"] == "agc"
    assert "front_agc" not in session["meta"]["signals"]
