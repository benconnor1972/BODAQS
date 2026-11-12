"""Assess a finalized multi-node BDQ without accessing devices."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))
from bodaqs_analysis.multi_imu_recording import assess_multi_imu_recording


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--expected-nodes", required=True, help="Explicit addresses, e.g. 0,1,2,3")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = assess_multi_imu_recording(args.file, [int(n) for n in args.expected_nodes.split(",")])
    if args.output.exists():
        parser.error("output already exists; preserve prior evidence")
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report["file_outcome"])
    return 0 if report["file_outcome"] == "complete_delivery" else 1


if __name__ == "__main__":
    raise SystemExit(main())
