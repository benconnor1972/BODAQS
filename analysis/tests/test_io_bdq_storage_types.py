from __future__ import annotations

import binascii
import json
import struct
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bodaqs_analysis.imu import build_imu_streams, extract_imu_stream, imu_qc_report
from bodaqs_analysis.io_bdq import (
    CHUNK_MAGIC,
    FILE_MAGIC,
    bdq_to_log_metadata,
    iter_bdq_rows,
    read_bdq,
)
from bodaqs_analysis.pipeline import load_bdq_session
from bodaqs_analysis.signalname import parse_signal_name
from bodaqs_analysis.signal_standardize import (
    canonicalize_signal_names,
    rebuild_and_validate_signal_registry,
)


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
                "sensor": "frame_imu",
                "end": "rear",
                "domain": "frame",
                "mount_point": "seat_tube",
                "quantity": "linear_acceleration_raw",
                "component": "x",
                "coordinate_frame": "sensor_native",
                "vector_group": "accel_raw",
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
        "imu_configs": {
            "frame_imu": {
                "contract_id": "bodaqs.bmi270_imu_mvp.v1",
                "imu_rate_hz": 200,
            }
        },
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


def test_bdq_metadata_preserves_vector_and_mount_semantics(tmp_path: Path) -> None:
    path = tmp_path / "typed_imu.bdq"
    path.write_bytes(_bdq_bytes())

    metadata = bdq_to_log_metadata(read_bdq(path))
    accel_x = next(
        info
        for info in metadata["columns"].values()
        if info.get("bdq_field") == "frame_imu_accel_x_raw"
    )

    assert accel_x["sensor"] == "frame_imu"
    assert accel_x["domain"] == "frame"
    assert accel_x["end"] == "rear"
    assert accel_x["mount_point"] == "seat_tube"
    assert accel_x["component"] == "x"
    assert accel_x["coordinate_frame"] == "sensor_native"
    assert accel_x["vector_group"] == "accel_raw"
    assert metadata["imu_configs"]["frame_imu"]["imu_rate_hz"] == 200

    session = load_bdq_session(path)
    assert session["meta"]["imu_configs"]["frame_imu"]["contract_id"] == "bodaqs.bmi270_imu_mvp.v1"


def test_phase_4_5_frame_domain_passes_strict_signal_validation(tmp_path: Path) -> None:
    path = tmp_path / "typed_imu.bdq"
    path.write_bytes(_bdq_bytes())

    session = canonicalize_signal_names(load_bdq_session(path))
    validated = rebuild_and_validate_signal_registry(session, strict_registry_parse=True)

    column = "frame_imu_accel_x_raw_dom_frame [count]"
    assert column in validated["df"].columns
    assert validated["meta"]["signals"][column]["kind"] == "raw"
    assert validated["meta"]["signals"][column]["quantity"] == "linear_acceleration_raw"


@pytest.mark.parametrize("domain", ["unsprung", "frame", "steering"])
def test_phase_4_5_imu_domains_are_in_the_canonical_vocabulary(domain: str) -> None:
    parts = parse_signal_name(f"imu0_accel_x_raw_dom_{domain} [count]")

    assert parts.domain == domain


def test_iter_rows_rejects_unsupported_storage_type_clearly(tmp_path: Path) -> None:
    path = tmp_path / "unsupported_storage.bdq"
    path.write_bytes(_bdq_bytes(accel_storage_type="int24"))

    with pytest.raises(ValueError, match="unsupported BDQ storage type.*int24"):
        list(iter_bdq_rows(path))


def _phase6_imu_session(*, include_config: bool = True) -> dict:
    valid_positions = np.array([1, 3, 5, 8])
    row_count = 9

    def sparse(values, *, fill=0.0):
        out = np.full(row_count, fill, dtype=float)
        out[valid_positions] = values
        return out

    columns = {
        "frame_imu_accel_x_raw_dom_frame [count]": sparse([2048, 2048, 2048, 32760]),
        "frame_imu_accel_y_raw_dom_frame [count]": sparse([0, 0, 0, 0]),
        "frame_imu_accel_z_raw_dom_frame [count]": sparse([0, 0, 0, 0]),
        "frame_imu_gyro_x_raw_dom_frame [count]": sparse([16384, 16384, 16384, 16384]),
        "frame_imu_gyro_y_raw_dom_frame [count]": sparse([0, 0, 0, 0]),
        "frame_imu_gyro_z_raw_dom_frame [count]": sparse([0, 0, 0, 0]),
        "frame_imu_sensor_time_u24": sparse([0xFFFF00, 0xFFFF80, 0x000080, 0x000100]),
        "frame_imu_seq_u24": sparse([0xFFFFFE, 0xFFFFFF, 0x000001, 0x000002]),
        "frame_imu_temperature_raw": sparse([512, 512, 512, 512]),
        "frame_imu_sample_age_us": sparse([2000, 2000, 2000, 2000], fill=np.nan),
        "frame_imu_status_flags": sparse([0x0010, 0x0010, 0x0014, 0x0050]),
        "frame_imu_sample_valid": sparse([1, 1, 1, 1]),
    }
    df = pd.DataFrame({
        "time_s": [0.0, 0.002, 0.004, 0.007, 0.010, 0.017, 0.018, 0.020, 0.022],
        **columns,
    })

    channel_info = {}
    for vector, quantity in (("accel", "linear_acceleration_raw"), ("gyro", "angular_velocity_raw")):
        for axis in "xyz":
            column = f"frame_imu_{vector}_{axis}_raw_dom_frame [count]"
            channel_info[column] = {
                "sensor": "frame_imu",
                "domain": "frame",
                "end": "rear",
                "mount_point": "seat_tube",
                "quantity": quantity,
                "component": axis,
                "coordinate_frame": "sensor_native",
                "vector_group": f"{vector}_raw",
            }
    for suffix, metric in (
        ("sensor_time_u24", "sensor_time"),
        ("seq_u24", "sample_sequence"),
        ("temperature_raw", "temperature_raw"),
        ("sample_age_us", "sample_age"),
        ("status_flags", "status"),
        ("sample_valid", "sample_valid"),
    ):
        channel_info[f"frame_imu_{suffix}"] = {
            "class": "diagnostic",
            "sensor": "frame_imu",
            "metric": metric,
        }

    meta = {"channel_info": channel_info, "streams": {}}
    if include_config:
        meta["imu_configs"] = {
            "frame_imu": {
                "contract_id": "bodaqs.bmi270_imu_mvp.v1",
                "imu_id": "frame_imu_001",
                "imu_rate_hz": 200,
                "effective_config": {
                    "accel_odr_hz": 200,
                    "gyro_odr_hz": 200,
                    "accel_range_g": 16,
                    "gyro_range_dps": 2000,
                },
                "sensor_time": {
                    "tick_numerator_us": 625,
                    "tick_denominator": 16,
                    "modulus_ticks": 1 << 24,
                },
                "mount_transform": {
                    "from": "sensor_native",
                    "to": "body_local",
                    "representation": "signed_axis_permutation",
                    "body_x": "+y",
                    "body_y": "-x",
                    "body_z": "+z",
                },
            }
        }
    return {
        "session_id": "imu_fixture",
        "source": {},
        "meta": meta,
        "qc": {
            "firmware_stats": {
                "imu_runtime_diagnostics": {
                    "sensors": {
                        "frame_imu": {
                            "queue_drops": 0,
                            "startup_stationary_observation": {
                                "state": "accepted",
                                "gyro_mean_raw": {"x": 2.0, "y": -3.0, "z": 1.0},
                            },
                        }
                    }
                }
            }
        },
        "df": df,
        "df_raw": df.copy(),
    }


def test_phase6_extracts_unwraps_scales_transforms_and_reports_qc() -> None:
    stream, qc, metadata = extract_imu_stream(_phase6_imu_session(), "frame_imu")

    assert len(stream.index) == 4
    assert stream["sequence_unwrapped"].tolist() == [0xFFFFFE, 0xFFFFFF, 0x1000001, 0x1000002]
    assert stream["sensor_time_unwrapped"].tolist() == [0xFFFF00, 0xFFFF80, 0x1000080, 0x1000100]
    assert stream["time_s"].tolist() == pytest.approx([0.0, 0.005, 0.015, 0.020])
    assert stream["continuity_segment"].tolist() == [0, 0, 1, 1]
    assert stream["accel_x_raw_count"].tolist() == [2048, 2048, 2048, 32760]
    assert stream["accel_x_m_s2"].iloc[0] == pytest.approx(9.80665)
    assert stream["body_accel_x_m_s2"].iloc[0] == pytest.approx(0.0)
    assert stream["body_accel_y_m_s2"].iloc[0] == pytest.approx(-9.80665)
    assert stream["gyro_x_rad_s"].iloc[0] == pytest.approx(np.deg2rad(1000.0))
    assert stream["temperature_c"].tolist() == [24.0] * 4
    assert qc["sequence"]["gap_events"] == 1
    assert qc["sequence"]["missing_samples"] == 1
    assert qc["sequence"]["coverage_fraction"] == pytest.approx(0.8)
    assert qc["sensor_time"]["discontinuity_events"] == 0
    assert qc["effective_odr_hz"] == pytest.approx(200.0)
    assert qc["continuous_segments"]["count"] == 2
    assert qc["sensor_time"]["clock_fit_to_logger"]["drift_ppm"] == pytest.approx(0.0, abs=1e-6)
    assert qc["status_flags"]["sensor_recovery_before"]["sample_count"] == 1
    assert qc["saturation"]["axes"]["accel_x"]["sample_count"] == 1
    assert qc["startup_stationary_observation"]["state"] == "accepted"
    assert metadata["coordinate_frames"] == ["sensor_native", "body_local"]


def test_phase6_applies_assisted_rotation_matrix_to_body_local_channels() -> None:
    session = _phase6_imu_session()
    angle = np.deg2rad(30.0)
    rotation = [
        [float(np.cos(angle)), 0.0, float(np.sin(angle))],
        [0.0, 1.0, 0.0],
        [-float(np.sin(angle)), 0.0, float(np.cos(angle))],
    ]
    config = session["meta"]["imu_configs"]["frame_imu"]
    config["contract_id"] = "bodaqs.bmi270_imu_mvp.v2"
    config["orientation_status"] = "accepted"
    config["mount_transform"] = {
        "from": "sensor_native",
        "to": "body_local",
        "representation": "rotation_matrix",
        "matrix": rotation,
    }

    stream, qc, metadata = extract_imu_stream(session, "frame_imu")

    assert "missing_or_invalid_mount_transform" not in qc["warnings"]
    assert stream["body_accel_x_m_s2"].iloc[0] == pytest.approx(np.cos(angle) * 9.80665)
    assert stream["body_accel_y_m_s2"].iloc[0] == pytest.approx(0.0)
    assert stream["body_accel_z_m_s2"].iloc[0] == pytest.approx(-np.sin(angle) * 9.80665)
    assert metadata["mount_transform"]["representation"] == "rotation_matrix"
    assert metadata["coordinate_frames"] == ["sensor_native", "body_local"]


def test_phase6_registers_one_idempotent_persisted_secondary_stream() -> None:
    session = _phase6_imu_session()

    build_imu_streams(session)
    build_imu_streams(session)

    assert list(session["stream_dfs"]) == ["imu_frame_imu"]
    assert session["meta"]["streams"]["imu_frame_imu"]["kind"] == "intermittent"
    assert session["meta"]["secondary_streams"]["imu_frame_imu"]["schema"] == "bodaqs.imu_stream.v1"
    report = imu_qc_report(session)
    assert report["frame_imu"]["stream_name"] == "imu_frame_imu"
    assert session["meta"]["imu_qc"] == report
    json.dumps(report, sort_keys=True, allow_nan=False)


def test_phase6_aligns_canonical_time_to_logger_clock_and_preserves_native_time() -> None:
    session = _phase6_imu_session()
    valid_positions = np.array([1, 3, 5, 8])
    native_time_s = np.array([0.0, 0.005, 0.015, 0.020])
    clock_scale = 0.9929
    session["df"].loc[valid_positions, "time_s"] = 0.002 + native_time_s * clock_scale

    stream, qc, metadata = extract_imu_stream(session, "frame_imu")

    assert stream["native_time_s"].tolist() == pytest.approx(native_time_s)
    assert stream["time_s"].tolist() == pytest.approx(native_time_s * clock_scale)
    assert stream["clock_epoch"].tolist() == [0, 0, 1, 1]
    assert qc["native_grid_odr_hz"] == pytest.approx(200.0)
    assert qc["logger_relative_odr_hz"] == pytest.approx(200.0 / clock_scale)
    assert qc["effective_odr_hz"] == pytest.approx(200.0 / clock_scale)
    assert qc["sensor_time"]["clock_fit_to_logger"]["scale"] == pytest.approx(clock_scale)
    assert metadata["timebase_source"] == "logger_aligned_affine_clock_fit"
    assert metadata["time_columns"]["native_nominal"] == "native_time_s"


def test_phase6_keeps_canonical_time_monotonic_across_overlapping_clock_epochs() -> None:
    session = _phase6_imu_session()
    valid_positions = np.array([1, 3, 5, 8])
    session["df"].loc[valid_positions, "time_s"] = [0.010, 0.015, 0.014, 0.019]

    stream, qc, metadata = extract_imu_stream(session, "frame_imu")

    assert np.all(np.diff(stream["time_s"].to_numpy(dtype=float)) > 0)
    assert stream["time_s"].tolist() == pytest.approx([0.0, 0.005, 0.010, 0.015])
    assert qc["sensor_time"]["clock_epochs"][1]["alignment_adjustment_s"] == pytest.approx(0.006)
    assert metadata["timebase_source"] == "logger_aligned_affine_clock_fit"


def test_phase6_masks_invalid_sparse_imu_placeholders_but_preserves_raw_dataframe() -> None:
    session = _phase6_imu_session()
    invalid = session["df"]["frame_imu_sample_valid"].eq(0)

    build_imu_streams(session)

    dependent = [
        "frame_imu_accel_x_raw_dom_frame [count]",
        "frame_imu_gyro_z_raw_dom_frame [count]",
        "frame_imu_sensor_time_u24",
        "frame_imu_status_flags",
    ]
    assert session["df"].loc[invalid, dependent].isna().all().all()
    assert session["df_raw"].loc[invalid, dependent].eq(0).all().all()
    assert session["df"]["frame_imu_sample_valid"].tolist() == session["df_raw"]["frame_imu_sample_valid"].tolist()
    info = session["meta"]["channel_info"][dependent[0]]
    assert info["validity_column"] == "frame_imu_sample_valid"
    assert info["invalid_sample_policy"] == "null_when_sample_valid_is_not_one"


def test_phase6_missing_config_is_degraded_or_strictly_rejected() -> None:
    session = _phase6_imu_session(include_config=False)

    stream, qc, metadata = extract_imu_stream(session, "frame_imu", strict=False)

    assert qc["status"] == "degraded"
    assert "missing_imu_config" in qc["warnings"]
    assert "accel_x_m_s2" not in stream.columns
    assert metadata["coordinate_frames"] == ["sensor_native"]

    with pytest.raises(ValueError, match="metadata is incomplete.*missing_imu_config"):
        extract_imu_stream(session, "frame_imu", strict=True)
