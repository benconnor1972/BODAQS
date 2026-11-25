"""Locate unresolved packet identities without repairing or guessing source sequences."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))
from bodaqs_analysis.can_imu_packets import read_can_imu_packets
from bodaqs_analysis.io_bdq import iter_bdq_stream_records, read_bdq


def diagnose(path):
    info = read_bdq(path)
    nodes = []
    for descriptor in info.stream_catalog.get("streams", []):
        if descriptor.get("acquisition", {}).get("payload_schema") != "bodaqs.can_imu_packets.v1":
            continue
        decoded = read_can_imu_packets(path, descriptor["stream_key"])
        unknown = sorted({r["packet_observation"] for r in decoded["readings"] if r["sequence"] is None})
        packets = list(iter_bdq_stream_records(path, descriptor["stream_key"]))
        suffix = bool(unknown) and unknown == list(range(unknown[0], len(packets)))
        nodes.append({"node": descriptor["acquisition"]["node_address"],
            "packets": len(packets), "unresolved_readings": sum(r["sequence"] is None for r in decoded["readings"]),
            "ambiguous_packets": len(unknown), "all_ambiguity_in_final_suffix": suffix,
            "first_ambiguous_packet": unknown[0] if unknown else None,
            "last_ambiguous_packet": unknown[-1] if unknown else None,
            "last_packet_sequence_floor": packets[-1]["sequence_floor"] if packets else None,
            "source_final_observed": next((w.get("source_final_observed") for w in
                info.final_summary.get("remote_tail_windows", []) if w["node"] == descriptor["acquisition"]["node_address"]), None),
            "interpretation": "missing final upper bound is consistent with suffix ambiguity; no repair authorized"
                if suffix else "no unresolved suffix" if not unknown else "ambiguity also needs interior evidence review"})
    return {"file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "nodes": nodes,
            "qualification": "offline evidence localization only; raw readings and unresolved identity preserved"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; preserve prior evidence")
    report = {"schema": "bodaqs.imu_sequence_evidence_screen.v1", "cases": [diagnose(p) for p in args.files]}
    args.output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
