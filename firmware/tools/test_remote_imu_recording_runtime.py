"""Compile production remote stream/catalog/writer and independently read its BDQ."""
from __future__ import annotations

import argparse
import binascii
from pathlib import Path
import subprocess
import struct
import sys
import tempfile


def verify_recording(path: Path, repo: Path) -> None:
    sys.path.insert(0, str(repo / "analysis"))
    from bodaqs_analysis.io_bdq import (
        bdq_to_stream_dataframes, iter_bdq_stream_records, read_bdq,
    )

    info = read_bdq(path)
    assert info.detected_errors == (), info.detected_errors
    assert info.stream_count == 3
    descriptors = {item["stream_key"]: item for item in info.stream_catalog["streams"]}
    sample = descriptors["can0_imu6"]
    evidence = descriptors["can0_timing"]
    assert sample["record_size_bytes"] == 28
    assert evidence["record_size_bytes"] == 224
    assert sample["acquisition"]["payload_schema"] == "bodaqs.can_imu6.v1"
    assert evidence["acquisition"]["payload_schema"] == "bodaqs.can_timing_evidence.v1"
    assert evidence["acquisition"]["related_sample_stream_id"] == 2
    for descriptor in (sample, evidence):
        acquisition = descriptor["acquisition"]
        assert acquisition["provider_uid"] == "123"
        assert acquisition["node_boot"] == 7
        assert acquisition["master_boot"] == "456"
        assert acquisition["control_session"] == "789"
        assert acquisition["recording_id"] == "100"
        assert acquisition["measurement_context"] == "999"
        assert descriptor["timebase"]["native_tick_modulus"] == 4294967296
    assert sample["clock_id"] != evidence["clock_id"]
    offsets = {item["field"]: item["byte_offset"] for item in sample["channels"]}
    assert {name: offsets[name] for name in ("source_segment_id", "ax", "ay", "az", "gx", "gy", "gz")} == {
        "source_segment_id": 12, "ax": 16, "ay": 18, "az": 20, "gx": 22, "gy": 24, "gz": 26,
    }
    [record] = list(iter_bdq_stream_records(path, "can0_imu6"))
    assert record == {
        "sequence": 0, "native_tick": 1000, "status_flags": 25, "source_segment_id": 1,
        "ax": -1, "ay": 2, "az": 3, "gx": 4, "gy": 5, "gz": 6,
    }
    rows = list(iter_bdq_stream_records(path, "can0_timing"))
    assert [row["kind"] for row in rows] == [6, 2, 1, 3, 4, 5, 5]
    boundary, model, snapshot = rows[:3]
    assert [row["sequence"] for row in rows] == [1, 2, 3, 4, 5, 6, 7]
    assert [row["native_tick"] for row in rows] == [100, 101, 104, 105, 106, 107, 108]
    assert [row["source_segment_id"] for row in rows] == [1, 1, 1, 1, 0, 0, 0]
    assert [row["node_boot"] for row in rows] == [7, 7, 7, 7, 0, 0, 0]
    assert boundary["boundary_event_kind"] == 2
    assert boundary["boundary_validity_flags"] == 353
    assert boundary["boundary_node_tick"] == 0  # Valid zero, not absent evidence.
    assert boundary["node_evidence_ordinal"] == 1
    assert model["model_id"] == 1
    assert model["anchor_sequence"] == 0 and model["anchor_node_tick"] == 1000
    assert model["step_numerator"] == 300 and model["step_denominator"] == 1
    assert model["maximum_sample_span"] == 500 and model["maximum_duration_us"] == 150000
    assert model["model_flags"] == 1
    assert not model["validity_mask"] & (1 << 13)  # No invented finite uncertainty.
    assert snapshot["snapshot_flags"] == 273  # Full bit8 survives.
    assert snapshot["association_flags"] == 17
    assert snapshot["snapshot_presence"] == 255
    assert snapshot["node_evidence_ordinal"] == 9
    assert snapshot["raw_sensor_timestamp"] == 25
    assert snapshot["drdy_node_tick"] == 1000 and snapshot["capture_ordinal"] == 40
    assert snapshot["sync_sequence"] == 2 and snapshot["node_sync_tick"] == 900
    assert [snapshot[name] for name in ("fifo_accel_tag", "fifo_gyro_tag", "fifo_timestamp_tag")] == [1, 2, 3]
    assert snapshot["master_receive_ordinal_low"] == 5 and snapshot["master_receive_ordinal_high"] == 1
    assert snapshot["validity_mask"] == 2100983
    node_sync, master_sync, bridge, missing = rows[3:]
    assert node_sync['kind'] == 3 and node_sync['stream_epoch'] == 1
    assert node_sync['node_sync_tick'] == 900 and node_sync['master_clock_epoch'] == 1
    assert node_sync['original_message_type'] == 33 and node_sync['original_message_length'] == 24
    assert node_sync['master_receive_ordinal_high'] == 1 and node_sync['master_receive_ordinal_low'] == 6
    assert master_sync['validity_mask'] == 4194568  # epoch3, masterSYNC8, method22
    assert master_sync['sync_sequence'] == 2 and master_sync['master_sync_tick'] == 50000
    assert bridge['validity_mask'] == 4243464  # epoch3, interval14, bridge15, method22
    assert bridge['logger_lower_high'] == bridge['logger_upper_high'] == 1
    assert bridge['logger_lower_low'] == 16 and bridge['logger_upper_low'] == 66
    assert bridge['bridge_master_tick'] == 50100 and bridge['bridge_token'] == 42
    assert bridge['bridge_method'] == 1 and bridge['clock_bound_flags'] == 0
    assert missing['bridge_method'] == 2 and missing['bridge_token'] == 43
    assert missing['validity_mask'] == 4227072  # token-only, no clock observation/bracket
    assert missing['master_clock_epoch'] == missing['bridge_master_tick'] == 0
    chunks = list(info.stream_data_chunks)
    evidence_sequence = next(chunk.sequence_number for chunk in chunks if chunk.stream_id == 3)
    sample_sequence = next(chunk.sequence_number for chunk in chunks if chunk.stream_id == 2)
    assert evidence_sequence < sample_sequence
    frames = bdq_to_stream_dataframes(path)
    assert frames["can0_imu6"]["native_time_s"].isna().all()
    assert "time_s" not in frames["can0_imu6"]
    assert frames["can0_imu6"].attrs["bdq_clock_alignment"]["status"] == "unknown"

    # A torn essential predecessor must stop valid-prefix recovery before any
    # otherwise intact dependent sample can become visible.
    data = path.read_bytes()
    cursor = 32
    evidence_end = None
    while cursor < len(data):
        magic, version, kind, sequence, length, checksum = struct.unpack_from("<4sHHIII", data, cursor)
        assert magic == b"BDQC" and version == 1
        payload_start = cursor + 20
        payload_end = payload_start + length
        assert binascii.crc32(data[payload_start:payload_end]) & 0xffffffff == checksum
        if kind == 3 and sequence == evidence_sequence:
            evidence_end = payload_end
        if kind == 3 and sequence == sample_sequence:
            # Independent expected bytes include reserved prefix zeros and
            # the new segment offset; no production offset constants used.
            assert data[payload_start + 24:payload_end] == bytes.fromhex(
                "00000000 e8030000 19000000 01000000 ffff0200 03000400 05000600"
            )
        cursor = payload_end
    assert evidence_end is not None
    with tempfile.TemporaryDirectory(prefix="bodaqs-torn-evidence-") as temporary:
        torn = Path(temporary) / "torn-evidence.bdq"
        torn.write_bytes(data[:evidence_end - 1])
        assert read_bdq(torn).detected_errors
        assert list(iter_bdq_stream_records(torn, "can0_imu6")) == []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--output", type=Path, help="Retain the generated fixture BDQ at this path")
    args = parser.parse_args()
    firmware = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-remote-imu-") as temporary:
        executable = Path(temporary) / "remote_imu.exe"
        sources = [firmware / "test/remote_imu_recording_fixture.cpp"] + [
            firmware / "src" / name for name in ("RemoteImuStream.cpp", "BdqV2Catalog.cpp", "BdqV2Writer.cpp")
        ]
        subprocess.run([
            args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I", str(firmware / "src"), *map(str, sources), "-o", str(executable),
        ], check=True)
        output = args.output.resolve() if args.output else Path(temporary) / "remote-imu.bdq"
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(executable), str(output)], check=True)
        verify_recording(output, firmware.parent)
    print("Remote IMU production writer/independent BDQ reader checks passed")


if __name__ == "__main__":
    main()
