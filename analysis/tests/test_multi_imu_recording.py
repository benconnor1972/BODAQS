"""Independent CRC-framed multi-stream vectors, including missing participants."""
import json
import struct

import pytest

from bodaqs_analysis.multi_imu_recording import assess_multi_imu_recording
from bodaqs_analysis.io_bdq import STREAM_DATA_HEADER_STRUCT
from test_first_imu_recording import recording
from test_io_bdq_v2 import CHUNK_HEADER, FILE_HEADER, _catalog, _chunk, _json_chunk, _primary_record, _stream_data


def multi_recording(tmp_path, count=2, *, gap_node=None, omit=None, no_primary=False,
                    no_footer=False, source_override=None, duplicate_key=False, prefix_gap=False, lost_segment=False, replay=False,
                    foreign_companion=False):
    catalog = _catalog();catalog["streams"] = catalog["streams"][:1]
    payloads, windows = [], []
    metadata = None;header = None
    for node in range(count):
        folder = tmp_path / str(node);folder.mkdir()
        override = {"node_address": node, "provider_uid": str(123+node),
                    "master_uid": "18446744073709551614", "measurement_context": "18446744073709551613"}
        if source_override and node == count-1:
            override.update(source_override)
        data = recording(folder, gap=node==gap_node or prefix_gap, source_overrides=override,
                         lost_segment=lost_segment and node==count-1).read_bytes()
        header = data[:FILE_HEADER.size];offset = FILE_HEADER.size
        while offset < len(data):
            _, _, kind, _, length, _ = CHUNK_HEADER.unpack_from(data, offset)
            payload = data[offset+CHUNK_HEADER.size:offset+CHUNK_HEADER.size+length]
            offset += CHUNK_HEADER.size+length
            if kind == 1:
                metadata = json.loads(payload)
            elif kind == 2 and node != omit:
                entries = json.loads(payload)["streams"][1:]
                for lane, entry in enumerate(entries):
                    entry.update(stream_id=2+2*node+lane, stream_key=f"node{0 if duplicate_key else node}_{lane}")
                    if lane:
                        entry["acquisition"].update({k: entries[0]["acquisition"][k] for k in ("provider_uid", "node_address", "node_boot", "master_uid", "master_boot", "recording_id", "control_session", "measurement_context")})
                        entry["acquisition"]["related_sample_stream_id"] = 2+2*node
                        if foreign_companion and node == count-1:
                            entry["acquisition"].update(provider_uid="999", node_address=3, node_boot=99, measurement_context="999")
                    catalog["streams"].append(entry)
            elif kind == 3 and node != omit:
                body = bytearray(payload)
                if struct.unpack_from("<H", body)[0] == 2:
                    if prefix_gap:
                        struct.pack_into("<H", body, STREAM_DATA_HEADER_STRUCT.size+32, 5)
                    if replay:
                        row = body[-100:];struct.pack_into("<I", row, 0, 2)
                        header_values = list(STREAM_DATA_HEADER_STRUCT.unpack_from(body));header_values[4] = 3
                        body[:STREAM_DATA_HEADER_STRUCT.size] = STREAM_DATA_HEADER_STRUCT.pack(*header_values)
                        body += row
                struct.pack_into("<H", body, 0, struct.unpack_from("<H", body)[0]+2*node)
                payloads.append(bytes(body))
            elif kind == 5 and node != omit:
                window = json.loads(payload)["remote_tail_windows"][0];window["node"] = node;windows.append(window)
    metadata["stream_count"] = len(catalog["streams"])
    chunks = [_json_chunk(1, 0, metadata), _json_chunk(2, 1, catalog)]
    if not no_primary:
        payloads.insert(0, _stream_data(1, 16, [_primary_record(i, 1000+5000*i, 0) for i in range(3)], []))
    for payload in payloads:
        chunks.append(_chunk(3, len(chunks), payload))
    if not no_footer:
        chunks.append(_json_chunk(5, len(chunks), {"clean_shutdown": True, "remote_cleanup_complete": True,
            "remote_tail_windows": windows, "remote_sample_tail_discarded": False}))
    path = tmp_path / "multi.bdq";path.write_bytes(header+b"".join(chunks));return path


@pytest.mark.parametrize("count", [1, 2, 4])
def test_every_expected_node_has_independent_complete_delivery(tmp_path, count):
    report = assess_multi_imu_recording(multi_recording(tmp_path, count), range(count))
    assert report["file_outcome"] == "complete_delivery"
    assert len(report["nodes"]) == count
    assert report["sample_delivery"] == {"denominator": 10*count, "missing": 0, "whole_run_missing_percent": 0}
    assert report["capacity_qualification"] == "unqualified"


def test_one_node_gap_cannot_be_hidden_by_totals(tmp_path):
    report = assess_multi_imu_recording(multi_recording(tmp_path, 4, gap_node=2), range(4))
    assert report["file_outcome"] == "incomplete_or_unresolved"
    assert report["sample_delivery"]["missing"] == 5
    assert [r["node"] for r in report["nodes"] if r["gaps"]] == [2]


@pytest.mark.parametrize("kwargs,issue", [({"omit": 1}, "expected_node_membership_mismatch"),
    ({"no_primary": True}, "primary_stream_incomplete_or_flagged"),
    ({"duplicate_key": True}, "duplicate_stream_key"),
    ({"source_override": {"provider_uid": "123"}}, "duplicate_provider_uid"),
    ({"source_override": {"provider_uid": "0123"}}, "duplicate_provider_uid"),
    ({"foreign_companion": True}, "node_1_companion_identity_mismatch"),
    ({"source_override": {"measurement_context": "18446744073709551612"}}, "shared_acquisition_identity_mismatch"),
    ({"source_override": {"master_uid": 18446744073709551614}}, "invalid_master_uid")])
def test_ambiguous_or_incomplete_run_never_claims_whole_run_coverage(tmp_path, kwargs, issue):
    report = assess_multi_imu_recording(multi_recording(tmp_path, **kwargs), [0, 1])
    assert issue in report["issues"]
    assert report["file_outcome"] == "incomplete_or_unresolved"
    assert report["sample_delivery"]["denominator"] is None


def test_missing_footer_retains_each_source_result(tmp_path):
    report = assess_multi_imu_recording(multi_recording(tmp_path, no_footer=True), [0, 1])
    assert report["file_outcome"] == "incomplete_or_unresolved"
    assert all(not r["file_cleanly_closed"] for r in report["nodes"])


def test_expected_membership_is_explicit(tmp_path):
    with pytest.raises(ValueError):
        assess_multi_imu_recording(tmp_path / "not_read.bdq", [0, 0])


@pytest.mark.parametrize("kwargs", [{"prefix_gap": True}, {"lost_segment": True}, {"replay": True}])
def test_missing_prefix_or_segment_and_replays_preclude_complete_verdict(tmp_path, kwargs):
    report = assess_multi_imu_recording(multi_recording(tmp_path, **kwargs), [0, 1])
    assert report["file_outcome"] == "incomplete_or_unresolved"
