from __future__ import annotations

import argparse
import binascii
import json
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence


FILE_MAGIC = b"BDQLOG\x00\x01"
FILE_MAGIC_V2 = b"BDQLOG\x00\x02"
CHUNK_MAGIC = b"BDQC"
FILE_HEADER = struct.Struct("<8sHHIQII")
CHUNK_HEADER = struct.Struct("<4sHHIII")
DATA_HEADER = struct.Struct("<IIQHH")
IMU_FRAME = struct.Struct("<IhhhIIH")
STREAM_DATA_HEADER = struct.Struct("<HHIIIHHI")
STREAM_RECORD_PREFIX = struct.Struct("<IIHH")


def _crc32(payload: bytes) -> int:
    return binascii.crc32(payload) & 0xFFFFFFFF


def _chunk(chunk_type: int, sequence: int, payload: bytes) -> bytes:
    header = CHUNK_HEADER.pack(CHUNK_MAGIC, 1, chunk_type, sequence, len(payload), _crc32(payload))
    return header + payload


def _json_chunk(chunk_type: int, sequence: int, payload: dict[str, object]) -> bytes:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _chunk(chunk_type, sequence, encoded)


def imu_int16_bdq_fixture_bytes() -> bytes:
    metadata = {
        "format": "bdq.v1",
        "recording_id": "packaged-imu-int16-smoke",
        "created_unix_us": 0,
        "sample_rate_hz": 500,
        "sample_period_us": 2000,
        "timezone": "Australia/Perth",
        "log_format": "bodaqs_compact_binary",
    }
    channel_schema = {
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
            {"field": "sample_id", "storage_type": "uint32", "byte_offset": 0},
        ] + [
            {
                "field": f"frame_imu_accel_{component}_raw",
                "class": "signal",
                "sensor": "frame_imu",
                "domain": "frame",
                "end": "rear",
                "kind": "raw",
                "raw": True,
                "processing_role": "raw_evidence",
                "quantity": "linear_acceleration_raw",
                "component": component,
                "coordinate_frame": "sensor_native",
                "vector_group": "accel_raw",
                "unit": "count",
                "storage_type": "int16",
                "byte_offset": offset,
            }
            for component, offset in (("x", 4), ("y", 6), ("z", 8))
        ] + [
            {
                "field": "frame_imu_sensor_time_u24",
                "class": "diagnostic",
                "storage_type": "uint32",
                "byte_offset": 10,
            },
            {
                "field": "frame_imu_seq_u24",
                "class": "diagnostic",
                "storage_type": "uint32",
                "byte_offset": 14,
            },
            {"field": "flags", "class": "event_flag", "storage_type": "uint16", "byte_offset": 18},
        ],
    }
    frames = [
        IMU_FRAME.pack(0, -32768, -1, 0, 0, 0, 0),
        IMU_FRAME.pack(1, 32767, 1, 1234, 1, 1, 0),
        IMU_FRAME.pack(2, -123, 0, 1, 0xFFFFFE, 0xFFFFFE, 0),
        IMU_FRAME.pack(3, 0, 32767, -32768, 0xFFFFFF, 0xFFFFFF, 0),
    ]
    data_payload = DATA_HEADER.pack(0, len(frames), 0, IMU_FRAME.size, 0) + b"".join(frames)
    file_header = FILE_HEADER.pack(FILE_MAGIC, 1, 0, FILE_HEADER.size, 0, 0, 0)
    return file_header + b"".join(
        [
            _json_chunk(1, 0, metadata),
            _json_chunk(2, 1, channel_schema),
            _chunk(3, 2, data_payload),
            _json_chunk(
                5,
                3,
                {"summary_format": "bdq.final_summary.v1", "samples_written": len(frames)},
            ),
        ]
    )


def imu_multi_stream_bdq_fixture_bytes() -> bytes:
    """Small v2 fixture with one logger stream and four independent IMU streams."""
    def prefix_channels() -> list[dict[str, object]]:
        return [
            {"field": field, "storage_type": storage, "byte_offset": offset, "class": "diagnostic"}
            for field, storage, offset in (
                ("sequence", "uint32", 0),
                ("native_tick", "uint32", 4),
                ("status_flags", "uint16", 8),
            )
        ]

    primary = {
        "stream_id": 1,
        "stream_key": "primary",
        "clock_id": "logger_monotonic",
        "record_size_bytes": 16,
        "timebase": {
            "native_tick_modulus": 1 << 32,
            "nominal_tick_period_us": {"numerator": 1, "denominator": 1},
            "expected_sequence_step": 1,
        },
        "channels": prefix_channels() + [
            {"field": "front_suspension_disp", "storage_type": "float32", "byte_offset": 12,
             "class": "signal", "quantity": "disp", "unit": "mm", "domain": "suspension",
             "sensor": "front_shock", "end": "front", "source": "linear_calibrated"}
        ],
    }
    streams = [primary]
    for index in range(1, 5):
        channels = prefix_channels()
        for axis, offset in zip("xyz", (12, 14, 16)):
            channels.append({
                "field": f"accel_{axis}_raw", "storage_type": "int16", "byte_offset": offset,
                "class": "signal", "quantity": "linear_acceleration_raw", "unit": "count",
                "sensor": f"imu_{index}", "component": axis, "domain": "frame",
                "coordinate_frame": "sensor_native", "vector_group": "accel_raw",
            })
        streams.append({
            "stream_id": index + 1,
            "stream_key": f"imu_{index}",
            "sensor_id": f"imu_{index}",
            "clock_id": f"bmi270:imu_{index}",
            "record_size_bytes": 20,
            "timebase": {
                "native_tick_modulus": 1 << 24,
                "nominal_tick_period_us": {"numerator": 625, "denominator": 16},
                "expected_sequence_step": 1,
            },
            "channels": channels,
        })

    metadata = {
        "format": "bdq.v2", "format_name": "BDQLOG v2",
        "recording_id": "packaged-imu-v2-smoke", "device_id": "A8_001",
        "firmware_name": "BODAQS", "firmware_version": "0.6.0",
        "hardware_version": "BODAQS A8", "created_unix_us": 0,
        "timezone": "Australia/Perth", "log_format": "bodaqs_multi_stream_binary",
        "native_stream_contract": "bodaqs.native_stream.v1", "stream_count": 5,
        "logger_monotonic_clock": {
            "clock_id": "logger_monotonic", "unit": "us", "nondecreasing": True,
        },
    }
    catalog = {
        "schema_format": "bdq.stream_catalog.v1", "endianness": "little",
        "record_prefix": {"format": "bdq.stream_record_prefix.v1", "size_bytes": 12},
        "streams": streams,
    }

    def stream_chunk(stream_id: int, records: list[bytes]) -> bytes:
        record_size = len(records[0])
        return STREAM_DATA_HEADER.pack(stream_id, 1, 0, 0, len(records), record_size, 0, 0) + b"".join(records)

    primary_records = [
        STREAM_RECORD_PREFIX.pack(i, i * 5000, 0, 0) + struct.pack("<f", 10.0 + i)
        for i in range(3)
    ]
    chunks = [_json_chunk(1, 0, metadata), _json_chunk(2, 1, catalog)]
    chunks.append(_chunk(3, 2, stream_chunk(1, primary_records)))
    for index in range(1, 5):
        records = [
            STREAM_RECORD_PREFIX.pack(i, i * 16, 0, 0)
            + struct.pack("<hhhH", -index * 100 - i, index * 100 + i, 0, 0)
            for i in range(2)
        ]
        chunks.append(_chunk(3, index + 2, stream_chunk(index + 1, records)))
    chunks.append(_json_chunk(5, 7, {
        "summary_format": "bdq.final_summary.v2",
        "streams": [{"stream_id": i, "records_written": 3 if i == 1 else 2} for i in range(1, 6)],
    }))
    header = FILE_HEADER.pack(FILE_MAGIC_V2, 2, 0, FILE_HEADER.size, 0, 0, 0)
    return header + b"".join(chunks)


def run_packaged_smoke_test(executable: str | Path, *, timeout_s: float = 120.0) -> None:
    executable_path = Path(executable).expanduser().resolve()
    if not executable_path.is_file():
        raise FileNotFoundError(f"Packaged Import Manager executable not found: {executable_path}")

    with tempfile.TemporaryDirectory(prefix="bodaqs_packaged_imu_smoke_") as temp_dir:
        for fixture_name, fixture_bytes in (
            ("imu_int16_v1_smoke.bdq", imu_int16_bdq_fixture_bytes()),
            ("imu_multi_stream_v2_smoke.bdq", imu_multi_stream_bdq_fixture_bytes()),
        ):
            fixture_path = Path(temp_dir) / fixture_name
            fixture_path.write_bytes(fixture_bytes)
            result = subprocess.run(
                [str(executable_path), "--smoke-test-imu-bdq", str(fixture_path)],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            if result.returncode != 0:
                details = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
                suffix = f"\n{details}" if details else ""
                raise RuntimeError(
                    f"Packaged Import Manager IMU BDQ smoke test failed for {fixture_name}: "
                    f"exit code {result.returncode}{suffix}"
                )


def run_packaged_workbench_layout_smoke_test(
    executable: str | Path,
    *,
    timeout_s: float = 120.0,
) -> None:
    executable_path = Path(executable).expanduser().resolve()
    if not executable_path.is_file():
        raise FileNotFoundError(f"Packaged Import Manager executable not found: {executable_path}")

    result = subprocess.run(
        [str(executable_path), "--smoke-test-workbench-layout"],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if result.returncode != 0:
        details = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        suffix = f"\n{details}" if details else ""
        raise RuntimeError(
            f"Packaged Import Manager Workbench layout smoke test returned {result.returncode}{suffix}"
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test packaged Import Manager IMU BDQ decoding.")
    parser.add_argument("executable", help="Path to the packaged bodaqs-import-setup executable.")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--check-workbench-layout", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.check_workbench_layout:
            run_packaged_workbench_layout_smoke_test(
                args.executable,
                timeout_s=args.timeout_seconds,
            )
        else:
            run_packaged_smoke_test(args.executable, timeout_s=args.timeout_seconds)
    except Exception as exc:
        print(f"Packaged smoke test failed: {type(exc).__name__}: {exc}")
        return 1
    smoke_name = "Workbench layout" if args.check_workbench_layout else "IMU BDQ"
    print(f"Packaged {smoke_name} smoke test passed: {Path(args.executable).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
