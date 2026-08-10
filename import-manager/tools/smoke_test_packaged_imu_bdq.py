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
CHUNK_MAGIC = b"BDQC"
FILE_HEADER = struct.Struct("<8sHHIQII")
CHUNK_HEADER = struct.Struct("<4sHHIII")
DATA_HEADER = struct.Struct("<IIQHH")
IMU_FRAME = struct.Struct("<IhhhIIH")


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


def run_packaged_smoke_test(executable: str | Path, *, timeout_s: float = 120.0) -> None:
    executable_path = Path(executable).expanduser().resolve()
    if not executable_path.is_file():
        raise FileNotFoundError(f"Packaged Import Manager executable not found: {executable_path}")

    with tempfile.TemporaryDirectory(prefix="bodaqs_packaged_imu_smoke_") as temp_dir:
        fixture_path = Path(temp_dir) / "imu_int16_smoke.bdq"
        fixture_path.write_bytes(imu_int16_bdq_fixture_bytes())
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
                f"Packaged Import Manager IMU BDQ smoke test returned {result.returncode}{suffix}"
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
