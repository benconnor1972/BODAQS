"""Read-only readiness check and owned offline intake for an IMU bench capture."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))
from bodaqs_analysis.io_bdq import iter_bdq_stream_records, read_bdq
from bodaqs_analysis.multi_imu_recording import assess_multi_imu_recording


def serial_membership(text: str, expected_streams: int = 5) -> dict:
    counts = [int(n) for n in re.findall(r"BDQ v2 begin streams=(\d+)", text)]
    # Multiple STARTs are not a valid single-capture readiness signal.
    return {"stream_counts": counts, "expected_streams": expected_streams,
            "ready": counts == [expected_streams],
            "note": "stream count is a precheck; finalized source identity remains required"}


def payload_window(path: Path, seconds: int) -> dict:
    info = read_bdq(path)
    primary = list(iter_bdq_stream_records(path, "primary"))
    if not primary:
        return {"available": False, "reason": "empty primary"}
    start = primary[0]["native_tick"]
    span = sum((right["native_tick"] - left["native_tick"]) & 0xffffffff
               for left, right in zip(primary, primary[1:]))
    if span >= 2**32:
        raise ValueError("capture spans a native tick wrap period; select a shorter capture")
    if span < seconds * 1_000_000:
        return {"available": False, "reason": "primary shorter than requested window",
                "primary_span_us": span}
    nodes = []
    for descriptor in info.stream_catalog.get("streams", []):
        source = descriptor.get("acquisition", {})
        if source.get("payload_schema") != "bodaqs.can_imu_packets.v1":
            continue
        readings = packets = 0
        orders = set()
        for row in iter_bdq_stream_records(path, descriptor["stream_id"]):
            count = row["packet_flags"] & 7
            if not 1 <= count <= 5 or not 4 + 12 * count <= row["packet_length"] <= 64:
                raise ValueError("invalid packet geometry")
            if ((row["native_tick"] - start) & 0xffffffff) < seconds * 1_000_000:
                order = (row["master_receive_ordinal_high"] << 32) | row["master_receive_ordinal_low"]
                if not order or order in orders:
                    raise ValueError("duplicate or missing reception identity in payload window")
                orders.add(order)
                readings += count
                packets += 1
        nodes.append({"node": source["node_address"], "stored_readings": readings,
                      "packets": packets, "raw_axis_bytes": readings * 12,
                      "stored_payload_readings_per_s": readings / seconds})
    return {"available": True, "seconds": seconds, "start_tick": start,
            "method": "half-open logger packet-observation window from first primary tick; not source delivery",
            "nodes": nodes, "stored_payload_readings_per_s": sum(
                n["stored_payload_readings_per_s"] for n in nodes)}


def ingest(case: Path, output: Path, nodes: list[int], recipe: str, config: Path,
           seconds: int) -> dict:
    files = list(case.glob("*.bdq"))
    if len(files) != 1:
        raise ValueError("case must contain exactly one finalized BDQ")
    required = [files[0], *[case / name for name in ("serial.txt", "ccs.txt", "loggercfg.txt")]]
    for path in [*required, config]:
        if not path.is_file():
            raise ValueError("missing input: " + str(path))
    if output.resolve() == case.resolve() or case.resolve() in output.resolve().parents:
        raise ValueError("output must be outside the input case")
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for path in required:
        data = path.read_bytes()
        (output / path.name).write_bytes(data)
        entries.append({"source": str(path.resolve()), "owned_copy": path.name,
                        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    (output / "INTAKE.json").write_text(json.dumps({"files": entries}, indent=2) + "\n", encoding="utf-8")
    owned = output / files[0].name
    info = read_bdq(owned)
    assessment = assess_multi_imu_recording(owned, nodes)
    readiness = serial_membership((output / "serial.txt").read_text(encoding="utf-8-sig"), 1 + 2 * len(nodes))
    recipe_match = info.metadata.get("firmware_recipe_id") == recipe
    config_match = (output / "loggercfg.txt").read_bytes() == config.read_bytes()
    sources_valid = len(assessment["nodes"]) == len(nodes) and all(
        not n.get("error") and n.get("source_identity_present") is True
        and n.get("effective_configuration_present") is True
        and n.get("companion_identity_matches") is True and not n.get("file_errors")
        for n in assessment["nodes"])
    result = {"schema": "bodaqs.imu_optimization_capture.v1", "expected_nodes": nodes,
              "recipe_matches": recipe_match, "configuration_byte_exact": config_match,
              "source_descriptors_valid": sources_valid,
              "reference_configuration_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
              "serial_readiness": readiness, "strict_assessment": assessment,
              "payload": payload_window(owned, seconds),
              "qualification": "unqualified; operator review required"}
    result["capture_matches_plan"] = bool(recipe_match and config_match and sources_valid and readiness["ready"]
        and sorted(assessment["observed_nodes"]) == sorted(nodes) and not info.detected_errors
        and not assessment["issues"] and info.final_summary.get("clean_shutdown") is True)
    (output / "assessment.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    artifacts = sorted(p for p in output.iterdir() if p.is_file())
    (output / "SHA256SUMS.txt").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest()
        + "  " + p.name + "\n" for p in artifacts), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ready = sub.add_parser("preflight")
    ready.add_argument("serial", type=Path)
    ready.add_argument("--expected-streams", type=int, default=5)
    assess = sub.add_parser("assess")
    assess.add_argument("case", type=Path)
    assess.add_argument("--output", required=True, type=Path)
    assess.add_argument("--expected-nodes", required=True)
    assess.add_argument("--recipe", required=True)
    assess.add_argument("--config-reference", required=True, type=Path)
    assess.add_argument("--seconds", type=int, default=100)
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            result = serial_membership(args.serial.read_text(encoding="utf-8-sig"), args.expected_streams)
            print(json.dumps(result, indent=2))
            return 0 if result["ready"] else 1
        if not 1 <= args.seconds <= 1000:
            raise ValueError("window must be 1..1000 seconds (less than one native tick wrap)")
        nodes = [int(n) for n in args.expected_nodes.split(",")]
        if len(nodes) not in (1, 2, 4) or len(set(nodes)) != len(nodes) or any(n not in range(4) for n in nodes):
            raise ValueError("explicit expected membership must contain 1, 2 or 4 distinct addresses in 0..3")
        result = ingest(args.case, args.output, nodes, args.recipe, args.config_reference, args.seconds)
        print(json.dumps({k: result[k] for k in ("capture_matches_plan", "payload", "qualification")}, indent=2))
        # A matching overloaded capture is usable evidence; never label it qualified.
        return 0 if result["capture_matches_plan"] and result["payload"]["available"] else 1
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
