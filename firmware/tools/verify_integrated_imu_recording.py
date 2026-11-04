"""Independent file/ledger oracles for the combined acquisition acceptance fixture."""
from __future__ import annotations

from collections import Counter
import binascii
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))
from bodaqs_analysis.io_bdq import iter_bdq_stream_records, read_bdq


AXES = [-32768, 32767, -1, -32768, 32767, -1]


def chunks(data: bytes) -> list[dict]:
    """Walk the documented 32/20-byte framing, stopping at the first bad CRC.

    This oracle deliberately does not use the analysis reader's private parser.
    Its result is compared against that reader's recovered complete records.
    """
    assert data[:8] == b"BDQLOG\x00\x02" and len(data) >= 32
    position = struct.unpack_from("<I", data, 12)[0]
    result = []
    while position + 20 <= len(data):
        magic, version, kind, sequence, length, crc = struct.unpack_from("<4sHHIII", data, position)
        end = position + 20 + length
        if magic != b"BDQC" or version != 1 or end > len(data):
            break
        payload = data[position + 20:end]
        if binascii.crc32(payload) & 0xFFFFFFFF != crc:
            break
        result.append({"start": position, "end": end, "payload_start": position + 20,
                       "kind": kind, "sequence": sequence, "payload": payload})
        position = end
    return result


def row_identity(row: dict) -> tuple[int, int]:
    return row["source_segment_id"], row["sequence"]


def input_ledger(path: Path) -> tuple[list[list[tuple[int, int]]], list[int]]:
    accepted = [[] for _ in range(4)]
    rejected = [0] * 4
    for line in path.read_text(encoding="utf-8").splitlines():
        node, epoch, first, count, admitted = map(int, line.split())
        assert 0 <= node < 4 and epoch in (1, 2) and 1 <= count <= 5 and admitted in (0, 1)
        if admitted:
            accepted[node].extend((epoch, sequence) for sequence in range(first, first + count))
        else:
            rejected[node] += count
    return accepted, rejected


def decoded(path: Path) -> dict[str, list[dict]]:
    info = read_bdq(path)
    return {descriptor["stream_key"]: list(iter_bdq_stream_records(path, descriptor["stream_key"]))
            for descriptor in info.stream_catalog["streams"]}


def assert_predecessors(path: Path) -> dict[str, int]:
    """Every committed sample must follow its actual source origin and model."""
    info = read_bdq(path)
    descriptors = {item["stream_id"]: item for item in info.stream_catalog["streams"]}
    begins: set[tuple[int, int]] = set()
    models: dict[tuple[int, int], list[tuple[int, int, int, int, int, int]]] = {}
    totals: Counter = Counter()
    for chunk in chunks(path.read_bytes()):
        if chunk["kind"] != 3:
            continue
        payload = chunk["payload"]
        stream_id, version, flags, first, count, size, observations, reserved = struct.unpack_from("<HHIIIHHI", payload)
        assert version == 1 and flags == reserved == 0
        assert len(payload) == 24 + count * size + observations * 32
        descriptor = descriptors[stream_id]
        key = descriptor["stream_key"]
        totals[key] += count
        acquisition = descriptor.get("acquisition", {})
        schema = acquisition.get("payload_schema")
        if schema not in ("bodaqs.can_imu6.v1", "bodaqs.can_timing_evidence.v1"):
            continue
        node = acquisition["node_address"]
        for index in range(count):
            row = payload[24 + index * size:24 + (index + 1) * size]
            if schema == "bodaqs.can_timing_evidence.v1":
                assert size == 224
                segment = struct.unpack_from("<I", row, 20)[0]
                if row[12] == 6 and row[200] == 2:  # actual BEGIN, not logger reception
                    assert struct.unpack_from("<III", row, 28) == (acquisition["node_boot"], 1, 1)
                    begins.add((node, segment))
                if row[12] == 2:
                    anchor, tick, numerator, denominator, uncertainty, span, duration = struct.unpack_from("<7I", row, 88)
                    assert denominator and 0 < span <= 500 and 0 < duration <= 150000
                    assert struct.unpack_from("<III", row, 28) == (acquisition["node_boot"], 1, 1)
                    assert not struct.unpack_from("<I", row, 16)[0] & (1 << 13)
                    models.setdefault((node, segment), []).append((anchor, tick, numerator, denominator, span, duration))
            else:
                assert size == 28
                sequence, tick = struct.unpack_from("<II", row)
                segment = struct.unpack_from("<I", row, 12)[0]
                assert (node, segment) in begins, (path.name, node, segment, "missing BEGIN")
                candidates = models.get((node, segment), ())
                assert any(0 <= sequence - anchor < span and
                           (sequence - anchor) * numerator // denominator <= duration and
                           (base + (sequence - anchor) * numerator // denominator) & 0xFFFFFFFF == tick
                           for anchor, base, numerator, denominator, span, duration in candidates), (
                               path.name, node, segment, sequence, "missing preceding applicable model")
    observed = decoded(path)
    assert {key: len(rows) for key, rows in observed.items()} == {
        descriptor["stream_key"]: totals[descriptor["stream_key"]] for descriptor in descriptors.values()}
    return dict(totals)


def verify_prefixes(output: Path, original: Path) -> list[dict]:
    data = original.read_bytes()
    valid = chunks(data)
    info = read_bdq(original)
    descriptors = {item["stream_id"]: item for item in info.stream_catalog["streams"]}
    full_rows = decoded(original)
    data_chunks = [chunk for chunk in valid if chunk["kind"] == 3]
    essential = next(chunk for chunk in data_chunks
                     if struct.unpack_from("<H", chunk["payload"], 16)[0] == 224
                     if any(chunk["payload"][24 + index * 224 + 12] == 2
                            for index in range(struct.unpack_from("<I", chunk["payload"], 12)[0])))
    sample_chunks = [chunk for chunk in data_chunks
                     if struct.unpack_from("<H", chunk["payload"], 16)[0] == 28]
    assert sample_chunks
    chosen = [essential, sample_chunks[0], sample_chunks[len(sample_chunks) // 2], sample_chunks[-1]]
    results = []
    for index, target in enumerate(chosen):
        for mode in ("cut", "crc"):
            path = output / f"prefix-{index}-{mode}.bdq"
            if mode == "cut":
                path.write_bytes(data[:target["end"] - 1])
            else:
                altered = bytearray(data)
                altered[target["end"] - 1] ^= 1
                path.write_bytes(altered)
            recovered = read_bdq(path)
            assert recovered.detected_errors and not recovered.final_summary
            if mode == "crc":
                assert any("crc" in error.lower() for error in recovered.detected_errors)
            counts: Counter = Counter()
            for chunk in valid:
                if chunk["start"] >= target["start"]:
                    break
                if chunk["kind"] == 3:
                    stream_id = struct.unpack_from("<H", chunk["payload"])[0]
                    count = struct.unpack_from("<I", chunk["payload"], 12)[0]
                    counts[descriptors[stream_id]["stream_key"]] += count
            prefix_rows = decoded(path)
            for key in full_rows:
                assert prefix_rows[key] == full_rows[key][:counts[key]], (path.name, key)
            assert_predecessors(path)
            results.append({"file": path.name, "recovered_records": sum(counts.values()),
                            "errors": recovered.detected_errors})
    return results


def verify(output: Path) -> dict:
    results = {"software_only": True, "physical_qualification": "deferred #175/#176", "scenarios": {}}
    for scenario in ("good", "stall", "short", "cancel-open", "cancel-prepare"):
        path = output / f"{scenario}.bdq"
        info = read_bdq(path)
        rows = decoded(path)
        expected, rejected = input_ledger(output / f"{scenario}.bdq.input.tsv")
        trace = [tuple(map(int, line.split())) for line in
                 (output / f"{scenario}.bdq.control.tsv").read_text(encoding="utf-8").splitlines()]
        optional = [clock for clock, node, opcode, operation, ordinary in trace if ordinary]
        # Independent interval envelope for a four-token bucket with globally
        # aligned 250ms replenishment ticks (the fixture's declared clock phase).
        for index, first in enumerate(optional):
            for last_index in range(index, len(optional)):
                assert last_index - index + 1 <= 4 + optional[last_index] // 250 - first // 250
        if scenario.startswith("cancel"):
            assert not any(opcode == 0x24 for clock, node, opcode, operation, ordinary in trace)
            assert not rows["primary"]
        else:
            runtime = json.loads((output / f"{scenario}.bdq.runtime.json").read_text(encoding="utf-8"))
            assert runtime["host_only_schedule"] is True
            assert runtime["service_turns_per_tick"] == 12 and runtime["spi_slots_per_injected_ms"] == 10
            assert all(0 < gap < 300 for gap in runtime["renewal_gap_ms"])
            assert runtime["stop_terminal_verified_within_ms"] == 200
            assert runtime["clean_close"] == (scenario != "short")
            assert runtime["rejected_source_samples"] == rejected
            assert [row["sequence"] for row in rows["primary"]] == ([0, 1] if scenario == "stall" else [0])
            for node in range(4):
                assert any(peer == node and opcode == 0x25 for clock, peer, opcode, operation, ordinary in trace)
                assert any(peer == node and opcode == 0x27 for clock, peer, opcode, operation, ordinary in trace)
        counts = []
        for node in range(4):
            samples = rows[f"can{node}_imu6"]
            evidence = rows[f"can{node}_timing"]
            identities = [row_identity(row) for row in samples]
            assert len(set(identities)) == len(identities), (scenario, node, "duplicate insertion")
            assert identities == expected[node], (scenario, node, len(identities), len(expected[node]))
            if scenario in ("good", "short"):
                assert identities == [(1, seq) for seq in range(66)] + [(2, seq) for seq in range(728)]
            for row in samples:
                assert [row[key] for key in ("ax", "ay", "az", "gx", "gy", "gz")] == AXES
                assert row["status_flags"] & 24 == 24
                origin = 156400 if row["source_segment_id"] == 1 else 186900
                assert row["native_tick"] == origin + row["sequence"] * 300
            if scenario in ("good", "short"):
                first_recovered = next(row for row in samples if row["source_segment_id"] == 2)
                assert first_recovered["status_flags"] & 7 == 5
            if scenario == "stall":
                losses = [row for row in evidence if row["kind"] == 7 and row["loss_stage"] == 6]
                assert rejected[node] > 0
                assert sum(row["source_loss_delta"] for row in losses) == rejected[node]
                assert all(row["count_validity"] == 4 for row in losses)
                assert all(not (row["validity_mask"] & (1 << 19)) for row in losses)
            for event in evidence:
                if event["kind"] == 5 and event["bridge_method"] == 2:
                    assert not event["validity_mask"] & ((1 << 3) | (1 << 14))
                    assert event["bridge_master_tick"] == event["master_clock_epoch"] == 0
            descriptor = next(item for item in info.stream_catalog["streams"] if item["stream_key"] == f"can{node}_imu6")
            assert descriptor["record_size_bytes"] == 28
            assert descriptor["acquisition"]["node_address"] == node
            assert descriptor["acquisition"]["inter_node_alignment"] == "unknown"
            counts.append(len(samples))
        if scenario == "short":
            assert info.detected_errors and not info.final_summary
        else:
            assert not info.detected_errors and info.final_summary
            assert info.final_summary["physical_timing_bounds"] == "unknown"
        assert_predecessors(path)
        results["scenarios"][scenario] = {"samples_per_node": counts, "rejected_input_samples": rejected,
                                           "errors": info.detected_errors, "final_summary_present": bool(info.final_summary),
                                           "optional_dispatches": len(optional)}
    results["restarts"] = []
    for scenario, expected_sequence in (("good", 1), ("short", 2)):
        restart = output / f"{scenario}.bdq.restart.bdq"
        restart_info = read_bdq(restart)
        assert not restart_info.detected_errors and restart_info.final_summary
        restart_rows = decoded(restart)
        assert [row["sequence"] for row in restart_rows["primary"]] == [expected_sequence]
        assert all(not restart_rows[f"can{node}_imu6"] for node in range(4))
        first_catalog = read_bdq(output / f"{scenario}.bdq").stream_catalog["streams"]
        old_context = next(item["acquisition"]["measurement_context"] for item in first_catalog
                           if item["stream_key"] == "can0_imu6")
        contexts = set()
        for descriptor in restart_info.stream_catalog["streams"]:
            if descriptor["stream_key"] == "primary":
                continue
            acquisition = descriptor["acquisition"]
            assert acquisition["recording_id"] == "2"
            assert acquisition["measurement_context"] != old_context
            contexts.add(acquisition["measurement_context"])
        assert len(contexts) == 1
        assert_predecessors(restart)
        results["restarts"].append({"file": restart.name, "local_sequences": [expected_sequence]})
    results["prefixes"] = verify_prefixes(output, output / "good.bdq")
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print("Independent four-node ledger, native values, essential predecessors and CRC-prefix checks passed")
    return results
