"""Independent payload vectors from acquisition contract sections 6 and 9.1."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from bodaqs_analysis.io_bdq import (
    bdq_to_log_metadata, bdq_to_stream_dataframes, iter_bdq_stream_records, read_bdq,
)
from test_io_bdq_v2 import (
    FILE_HEADER, FILE_MAGIC_V2, _catalog, _chunk, _json_chunk, _metadata,
    _primary_record, _stream_data,
)


def _sample_descriptor() -> dict:
    descriptor = copy.deepcopy(_catalog()["streams"][1])
    descriptor.update(stream_key="remote_imu", clock_id="node:123:boot:7", transport="can_fd")
    descriptor["timebase"].update(native_tick_bits=32, native_tick_modulus=1 << 32,
                                   nominal_tick_period_us={"numerator": 1, "denominator": 1})
    descriptor["acquisition"] = {
        "payload_schema": "bodaqs.can_imu6.v1", "provider_uid": "123",
        "node_boot": 7, "measurement_context_id": "18446744073709551614",
        "clock_domains": {"node": "node:123:boot:7", "sensor": "sensor:123:7"},
    }
    descriptor["channels"] = descriptor["channels"][:3] + [
        {"field": "source_segment_id", "storage_type": "uint32", "byte_offset": 12},
        {"field": "accel_x_raw", "storage_type": "int16", "byte_offset": 16},
        {"field": "accel_y_raw", "storage_type": "int16", "byte_offset": 18},
        {"field": "accel_z_raw", "storage_type": "int16", "byte_offset": 20},
        {"field": "gyro_x_raw", "storage_type": "int16", "byte_offset": 22},
        {"field": "gyro_y_raw", "storage_type": "int16", "byte_offset": 24},
        {"field": "gyro_z_raw", "storage_type": "int16", "byte_offset": 26},
    ]
    return descriptor


def _file(tmp_path: Path, descriptor: dict, records: list[bytes]) -> Path:
    metadata = _metadata()
    metadata["stream_count"] = 2
    catalog = _catalog()
    catalog["streams"] = [catalog["streams"][0], descriptor]
    chunks = [
        _json_chunk(1, 0, metadata), _json_chunk(2, 1, catalog),
        _chunk(3, 2, _stream_data(1, 16, [_primary_record(0, 100, 20)], [])),
        _chunk(3, 3, _stream_data(2, descriptor["record_size_bytes"], records, [])),
    ]
    path = tmp_path / "can.bdq"
    path.write_bytes(FILE_HEADER.pack(FILE_MAGIC_V2, 2, 0, 32, 0, 0, 0) + b"".join(chunks))
    return path


# Prefix sequence=0, node tick=0xfffffff0, estimated flag=16, segment=0x10203040;
# six distinct signed axes. These literal bytes do not use a production encoder.
SAMPLE = bytes.fromhex("00000000 f0ffffff 1000 0000 40302010 0080 ffff ff7f 3412 ccff 0100")


def test_can_sample_catalog_rejects_overlapping_axis_channels(tmp_path: Path) -> None:
    descriptor = _sample_descriptor()
    descriptor["channels"][6]["byte_offset"] = 18
    path = _file(tmp_path, descriptor, [SAMPLE])
    assert any("payload schema" in error for error in read_bdq(path).detected_errors)


def test_can_sample_raw_values_do_not_infer_a_clock_epoch_or_logger_time(tmp_path: Path) -> None:
    path = _file(tmp_path, _sample_descriptor(), [SAMPLE])
    [record] = list(iter_bdq_stream_records(path, "remote_imu"))
    assert record == {
        "sequence": 0, "native_tick": 4294967280, "status_flags": 16,
        "source_segment_id": 270544960, "accel_x_raw": -32768,
        "accel_y_raw": -1, "accel_z_raw": 32767, "gyro_x_raw": 4660,
        "gyro_y_raw": -52, "gyro_z_raw": 1,
    }
    frame = bdq_to_stream_dataframes(path)["remote_imu"]
    assert frame["continuity_segment"].tolist() == [270544960]
    assert frame["clock_epoch"].isna().all()
    assert frame["native_time_s"].isna().all()
    assert "time_s" not in frame
    assert frame.attrs["bdq_clock_alignment"]["status"] == "unknown"


def test_can_source_sequence_can_restart_in_an_explicit_new_segment(tmp_path: Path) -> None:
    successor = bytes.fromhex("00000000 03000000 0100 0000 41302010 0100 0200 0300 0400 0500 0600")
    path = _file(tmp_path, _sample_descriptor(), [SAMPLE, successor])
    assert read_bdq(path).detected_errors == ()
    frame = bdq_to_stream_dataframes(path)["remote_imu"]
    assert frame["sequence"].tolist() == [0, 0]
    assert frame["continuity_segment"].tolist() == [270544960, 270544961]
    assert frame["clock_epoch"].isna().all()
    assert frame["native_tick_unwrapped"].isna().all()


def _evidence_descriptor() -> dict:
    descriptor = _sample_descriptor()
    descriptor.update(stream_key="node_evidence", stream_kind="intermittent",
                      clock_id="logger_monotonic", record_size_bytes=224)
    descriptor["acquisition"].update(payload_schema="bodaqs.can_timing_evidence.v1",
                                     related_sample_stream_id=3)
    # Every offset is written out independently of the decoder/firmware.
    fields = [
        ("kind", 12, "uint8"), ("endpoint", 13, "uint8"), ("stream_epoch", 14, "uint8"),
        ("validity_mask", 16, "uint32"), ("source_segment_id", 20, "uint32"),
        ("related_sequence", 24, "uint32"), ("node_boot", 28, "uint32"),
        ("sensor_clock_epoch", 32, "uint32"), ("node_clock_epoch", 36, "uint32"),
        ("master_clock_epoch", 40, "uint32"), ("model_id", 44, "uint32"),
        ("node_evidence_ordinal", 48, "uint32"), ("raw_sensor_timestamp", 52, "uint32"),
        ("drdy_node_tick", 56, "uint32"), ("capture_ordinal", 60, "uint32"),
        ("sync_sequence", 64, "uint32"), ("node_sync_tick", 68, "uint32"),
        ("master_sync_tick", 72, "uint32"), ("master_receive_tick", 76, "uint32"),
        ("master_receive_ordinal_low", 80, "uint32"),
        ("fifo_accel_tag", 84, "uint8"), ("fifo_gyro_tag", 85, "uint8"),
        ("fifo_timestamp_tag", 86, "uint8"), ("association_flags", 87, "uint8"),
        ("anchor_sequence", 88, "uint32"), ("anchor_node_tick", 92, "uint32"),
        ("step_numerator", 96, "uint32"), ("step_denominator", 100, "uint32"),
        ("uncertainty_us", 104, "uint32"), ("maximum_sample_span", 108, "uint32"),
        ("maximum_duration_us", 112, "uint32"), ("fifo_slot_ordinal", 116, "uint32"),
        ("logger_lower_low", 120, "uint32"), ("logger_lower_high", 124, "uint32"),
        ("logger_upper_low", 128, "uint32"), ("logger_upper_high", 132, "uint32"),
        ("bridge_master_tick", 136, "uint32"), ("bridge_method", 140, "uint16"),
        ("boundary_reason", 142, "uint16"), ("bridge_token", 144, "uint32"),
        ("source_loss_delta", 148, "uint32"), ("evidence_loss_delta", 152, "uint32"),
        ("capture_loss_delta", 156, "uint32"), ("first_affected", 160, "uint32"),
        ("last_affected", 164, "uint32"), ("loss_stage", 168, "uint8"),
        ("count_validity", 170, "uint16"), ("first_input_ordinal", 172, "uint32"),
        ("last_input_ordinal", 176, "uint32"), ("clock_bound_flags", 180, "uint32"),
        ("original_message_type", 184, "uint8"), ("original_message_version", 185, "uint8"),
        ("original_message_length", 186, "uint8"), ("master_receive_ordinal_high", 188, "uint32"),
        ("boundary_node_tick", 192, "uint32"), ("recovery_elapsed_us", 196, "uint32"),
        ("boundary_event_kind", 200, "uint8"), ("snapshot_presence", 201, "uint8"),
        ("model_kind", 202, "uint8"), ("snapshot_flags", 204, "uint16"),
        ("model_flags", 206, "uint16"), ("boundary_validity_flags", 208, "uint16"),
    ]
    descriptor["channels"] = descriptor["channels"][:3] + [
        {"field": name, "byte_offset": offset, "storage_type": storage}
        for name, offset, storage in fields
    ]
    return descriptor


EVIDENCE = bytes.fromhex("""
    09000000 e8030000 00000000 07000300
    ffff7f00 40302010 00000000 07000000
    02000000 03000000 04000000 05000000
    06000000 44332211 07000000 08000000
    09000000 0a000000 0b000000 0c000000
    ffffffff 01020301 0d000000 0e000000
    0a000000 03000000 00000000 f4010000
    f0490200 0f000000 ffffffff 01000000
    10000000 02000000 10000000 0100dcfe
    11000000 00000000 12000000 13000000
    14000000 15000000 0d000700 16000000
    17000000 78563412 e1093800 03000000
    18000000 19000000 fea5fe00 01011f00
    ff070000 00000000 00000000 00000000
""")


def test_can_companion_retains_raw_masks_boundaries_and_wide_pairs(tmp_path: Path) -> None:
    path = _file(tmp_path, _evidence_descriptor(), [EVIDENCE])
    assert read_bdq(path).detected_errors == ()
    [row] = list(iter_bdq_stream_records(path, "node_evidence"))
    assert row == {
        "sequence": 9, "native_tick": 1000, "status_flags": 0,
        "kind": 7, "endpoint": 0, "stream_epoch": 3,
        "validity_mask": 8388607, "source_segment_id": 270544960,
        "related_sequence": 0, "node_boot": 7, "sensor_clock_epoch": 2,
        "node_clock_epoch": 3, "master_clock_epoch": 4, "model_id": 5,
        "node_evidence_ordinal": 6, "raw_sensor_timestamp": 287454020,
        "drdy_node_tick": 7, "capture_ordinal": 8, "sync_sequence": 9,
        "node_sync_tick": 10, "master_sync_tick": 11, "master_receive_tick": 12,
        "master_receive_ordinal_low": 4294967295,
        "fifo_accel_tag": 1, "fifo_gyro_tag": 2, "fifo_timestamp_tag": 3,
        "association_flags": 1, "anchor_sequence": 13, "anchor_node_tick": 14,
        "step_numerator": 10, "step_denominator": 3, "uncertainty_us": 0,
        "maximum_sample_span": 500, "maximum_duration_us": 150000,
        "fifo_slot_ordinal": 15, "logger_lower_low": 4294967295,
        "logger_lower_high": 1, "logger_upper_low": 16, "logger_upper_high": 2,
        "bridge_master_tick": 16, "bridge_method": 1, "boundary_reason": 65244,
        "bridge_token": 17, "source_loss_delta": 0, "evidence_loss_delta": 18,
        "capture_loss_delta": 19, "first_affected": 20, "last_affected": 21,
        "loss_stage": 13, "count_validity": 7, "first_input_ordinal": 22,
        "last_input_ordinal": 23, "clock_bound_flags": 305419896,
        "original_message_type": 225, "original_message_version": 9,
        "original_message_length": 56, "master_receive_ordinal_high": 3,
        "boundary_node_tick": 24, "recovery_elapsed_us": 25,
        "boundary_event_kind": 254, "snapshot_presence": 165, "model_kind": 254,
        "snapshot_flags": 257, "model_flags": 31, "boundary_validity_flags": 2047,
    }
    assert (row["logger_lower_high"] << 32) | row["logger_lower_low"] == 8589934591
    assert (row["logger_upper_high"] << 32) | row["logger_upper_low"] == 8589934608
    assert (row["master_receive_ordinal_high"] << 32) | row["master_receive_ordinal_low"] == 17179869183
    metadata = bdq_to_log_metadata(read_bdq(path))
    assert metadata["secondary_streams"]["node_evidence"]["descriptor"] == _evidence_descriptor()


@pytest.mark.parametrize("offset", [15, 169, 187, 203, 210, 223])
def test_can_companion_rejects_nonzero_reserved_bytes(tmp_path: Path, offset: int) -> None:
    payload = bytearray(EVIDENCE)
    payload[offset] = 1
    path = _file(tmp_path, _evidence_descriptor(), [bytes(payload)])
    assert any("reserved" in error for error in read_bdq(path).detected_errors)


def test_can_evidence_artifact_roundtrip_keeps_numeric_masks_and_catalog(tmp_path: Path) -> None:
    from bodaqs_analysis.artifacts import ArtifactStore, load_session_artifacts, save_session_artifacts

    path = _file(tmp_path, _evidence_descriptor(), [EVIDENCE])
    frames = bdq_to_stream_dataframes(path)
    metadata = bdq_to_log_metadata(read_bdq(path))
    store = ArtifactStore(tmp_path / "artifacts")
    save_session_artifacts(
        store, run_id="raw", session_id="imu", session_df=frames["primary"],
        session_meta=metadata, secondary_stream_dfs={"node_evidence": frames["node_evidence"]},
        secondary_stream_meta=metadata["secondary_streams"],
    )
    restored = load_session_artifacts(store, run_id="raw", session_id="imu")
    frame = restored["stream_dfs"]["node_evidence"]
    assert frame["snapshot_flags"].tolist() == [257]
    assert frame["boundary_event_kind"].tolist() == [254]
    assert frame["master_receive_ordinal_low"].tolist() == [4294967295]
    assert frame["master_receive_ordinal_high"].tolist() == [3]
    assert frame["native_time_s"].isna().all()
    descriptor = restored["secondary_stream_meta"]["node_evidence"]["descriptor"]
    assert descriptor == _evidence_descriptor()


@pytest.mark.parametrize("validity", [0, 65536])
def test_can_raw_zero_loss_retains_whether_it_was_observed(tmp_path: Path, validity: int) -> None:
    payload = bytearray(EVIDENCE)
    payload[16:20] = validity.to_bytes(4, "little")
    path = _file(tmp_path, _evidence_descriptor(), [bytes(payload)])
    [row] = list(iter_bdq_stream_records(path, "node_evidence"))
    assert row["source_loss_delta"] == 0
    assert row["validity_mask"] == validity


def test_can_companion_catalog_cannot_omit_completion_fields(tmp_path: Path) -> None:
    descriptor = _evidence_descriptor()
    descriptor["channels"] = [channel for channel in descriptor["channels"]
                              if channel["byte_offset"] < 192]
    path = _file(tmp_path, descriptor, [EVIDENCE])
    assert any("payload schema" in error for error in read_bdq(path).detected_errors)


def test_can_sample_rejects_zero_segment_and_duplicate_sequence_within_segment(tmp_path: Path) -> None:
    payload = bytearray(SAMPLE)
    payload[12:16] = b"\0\0\0\0"
    path = _file(tmp_path, _sample_descriptor(), [bytes(payload)])
    assert any("zero source segment" in error for error in read_bdq(path).detected_errors)
    path = _file(tmp_path, _sample_descriptor(), [SAMPLE, SAMPLE])
    assert any("sequence order" in error for error in read_bdq(path).detected_errors)


def test_can_valid_prefix_cannot_expose_sample_after_incomplete_evidence(tmp_path: Path) -> None:
    metadata = _metadata()
    metadata["stream_count"] = 3
    catalog = _catalog()
    sample = _sample_descriptor()
    sample["stream_id"] = 3
    catalog["streams"] = [catalog["streams"][0], _evidence_descriptor(), sample]
    evidence = _chunk(3, 2, _stream_data(2, 224, [EVIDENCE], []))
    dependent = _chunk(3, 3, _stream_data(3, 28, [SAMPLE], []))
    path = tmp_path / "torn_evidence.bdq"
    path.write_bytes(
        FILE_HEADER.pack(FILE_MAGIC_V2, 2, 0, 32, 0, 0, 0)
        + _json_chunk(1, 0, metadata) + _json_chunk(2, 1, catalog)
        + evidence[:-24] + dependent
    )
    assert read_bdq(path).detected_errors
    assert list(iter_bdq_stream_records(path, "remote_imu")) == []
