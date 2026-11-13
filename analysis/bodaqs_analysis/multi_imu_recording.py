"""Strict offline multi-node polling evidence; never a capacity qualification."""
from __future__ import annotations

from pathlib import Path

from .can_imu_packets import SCHEMA
from .first_imu_recording import _assess_imu_stream
from .io_bdq import iter_bdq_stream_records, read_bdq


def assess_multi_imu_recording(path: str | Path, expected_nodes) -> dict:
    """Assess every expected source independently, retaining unknown coverage.

    Explicit membership prevents a missing stream from becoming a successful
    smaller test. Decode one source at a time to bound peak memory. Original
    sequence, CRC, STOP and identity checks are shared with the single-node tool.
    """
    nodes = tuple(expected_nodes)
    if len(nodes) not in (1, 2, 4) or len(set(nodes)) != len(nodes) or any(type(n) is not int or not 0 <= n < 4 for n in nodes):
        raise ValueError("expected nodes must be 1, 2 or 4 distinct addresses in 0..3")
    info = read_bdq(path)
    descriptors = info.stream_catalog.get("streams", [])
    samples = [d for d in descriptors if d.get("acquisition", {}).get("payload_schema")
               in (SCHEMA, "bodaqs.can_imu_units.v1")]
    issues, reports = [], []
    addresses = [d["acquisition"].get("node_address") for d in samples]
    if sorted(addresses, key=str) != sorted(nodes, key=str):
        issues.append("expected_node_membership_mismatch")
    # Ambiguous descriptors cannot be resolved by a dictionary lookup.
    for field in ("stream_id", "stream_key"):
        values = [d.get(field) for d in descriptors]
        if len(set(values)) != len(values):
            issues.append("duplicate_" + field)
    provider_uids, shared = set(), set()
    def identity_key(value):
        return str(int(value)) if isinstance(value, str) and value.isascii() and value.isdecimal() else str(value)
    for descriptor in samples:
        node = descriptor["acquisition"].get("node_address")
        companions = [d for d in descriptors if d.get("acquisition", {}).get("payload_schema") == "bodaqs.can_timing_evidence.v1"
                      and d["acquisition"].get("related_sample_stream_id") == descriptor["stream_id"]]
        if len(companions) != 1:
            issues.append(f"node_{node}_companion_count")
        identity_fields = ("provider_uid", "node_address", "node_boot", "master_uid", "master_boot",
                           "recording_id", "control_session", "measurement_context")
        companion_matches = len(companions) == 1 and all(
            k in descriptor["acquisition"] and k in companions[0]["acquisition"]
            and identity_key(descriptor["acquisition"][k]) == identity_key(companions[0]["acquisition"][k])
            for k in identity_fields)
        if not companion_matches:
            issues.append(f"node_{node}_companion_identity_mismatch")
        try:
            if any(i.startswith("duplicate_stream_") for i in issues):
                raise ValueError("ambiguous catalog identity")
            report, decoded = _assess_imu_stream(path, info, descriptor)
            del decoded
        except (ValueError, KeyError) as error:
            reports.append({"node": node, "stream_key": descriptor["stream_key"],
                            "file_outcome": "incomplete_or_unresolved", "error": str(error)})
            continue
        report.pop("final_summary", None)
        report.pop("operator_review", None)
        report.update(node=node, stream_key=descriptor["stream_key"], companion_identity_matches=companion_matches)
        source = report["source"]
        master_uid = source.get("master_uid")
        if not (isinstance(master_uid, str) and master_uid.isascii() and master_uid.isdecimal()
                and 0 < int(master_uid) < 2**64 or type(master_uid) is int and 0 < master_uid <= 2**53-1):
            issues.append("invalid_master_uid")
        uid = identity_key(source.get("provider_uid"))
        if uid in provider_uids:
            issues.append("duplicate_provider_uid")
        provider_uids.add(uid)
        # Decimal strings preserve full 64-bit identity. Invalid representations
        # still fail the existing per-source identity checks.
        shared.add(tuple(identity_key(source.get(k)) for k in ("master_uid", "master_boot", "recording_id", "control_session", "measurement_context")))
        reports.append(report)
    if len(shared) != 1:
        issues.append("shared_acquisition_identity_mismatch")
    primary = {"records": 0, "sequence_discontinuities": 0, "flagged_records": 0}
    previous = None
    try:
        for row in iter_bdq_stream_records(path, "primary"):
            seq = row["sequence"]
            primary["records"] += 1
            primary["flagged_records"] += bool(row["status_flags"])
            if previous is not None and seq != previous + 1:
                primary["sequence_discontinuities"] += 1
            previous = seq
    except (ValueError, KeyError) as error:
        primary["error"] = str(error)
    if not primary["records"] or primary["sequence_discontinuities"] or primary["flagged_records"] or "error" in primary:
        issues.append("primary_stream_incomplete_or_flagged")
    bounded = not issues and len(reports) == len(nodes) and all(r.get("metrics", {}).get("sample_delivery", {}).get("denominator") is not None for r in reports)
    expected = sum(r["metrics"]["sample_delivery"]["denominator"] for r in reports) if bounded else None
    missing = sum(r["metrics"]["sample_delivery"]["missing"] for r in reports) if bounded else None
    complete = bounded and missing == 0 and all(r["file_outcome"] == "complete_delivery"
        and not r["duplicates"] and not r["metrics"]["sample_delivery"]["unresolved_readings"] for r in reports)
    return {"schema": "bodaqs.multi_imu_recording_report.v1", "file": str(path),
            "expected_nodes": sorted(nodes), "observed_nodes": addresses, "issues": issues,
            "file_outcome": "complete_delivery" if complete else "incomplete_or_unresolved",
            "capacity_qualification": "unqualified", "timing_status": "unreconstructed",
            "nodes": reports, "primary": primary, "final_summary": info.final_summary,
            "sample_delivery": {"denominator": expected, "missing": missing,
                                "whole_run_missing_percent": 100 * missing / expected if expected else None},
            "operator_review": ["matched images and explicit expected node addresses",
                                "compare per-node queues and delivery; totals do not establish fairness",
                                "physical timing, electrical behavior and sustained capacity remain unqualified"]}
