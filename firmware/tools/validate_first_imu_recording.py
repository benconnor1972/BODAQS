"""Export the first restricted IMU recording without inventing sample timestamps."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))
from bodaqs_analysis.first_imu_recording import assess_first_imu_recording


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bdq", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("select a fresh output directory")
    args.output_dir.mkdir(parents=True)
    report = {"schema": "bodaqs.first_imu_recording_report.v1", "file_outcome": "invalid",
              "timing_status": "unreconstructed", "capacity_qualification": "unqualified"}
    try:
        report, decoded = assess_first_imu_recording(args.bdq)
        report["bdq_sha256"] = hashlib.sha256(args.bdq.read_bytes()).hexdigest()
        for name, rows in (("readings", decoded["readings"]), ("raw_timing_observations", decoded["raw_timing_observations"])):
            with (args.output_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as stream:
                if rows:
                    writer=csv.DictWriter(stream, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    except (ValueError, KeyError, OSError) as error:
        report["error"] = str(error)
    (args.output_dir / "report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(report["file_outcome"])
    return 0 if report["file_outcome"] in ("complete_delivery", "isolated_five_sample_gap_warning") else 1


if __name__ == "__main__":
    raise SystemExit(main())
