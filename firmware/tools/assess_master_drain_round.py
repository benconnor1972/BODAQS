"""Read-only r19 intake. CCS is optional; absent master identity stays unverified."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from assess_imu_optimization import payload_window, serial_membership
from bodaqs_analysis.io_bdq import read_bdq
from bodaqs_analysis.multi_imu_recording import assess_multi_imu_recording

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def capture_active(assessment):
    """Descriptors alone cannot prove that PREPARE/START succeeded."""
    return (sorted(assessment["observed_nodes"]) == [0, 1] and not assessment["issues"]
        and len(assessment["nodes"]) == 2 and sorted(n["node"] for n in assessment["nodes"]) == [0, 1]
        and all(n.get("sample_count", 0) > 0 and n.get("source_identity_present")
            and n.get("effective_configuration_present") and n.get("companion_identity_matches")
            and n.get("metrics", {}).get("sample_delivery", {}).get("baseline")
            and not n.get("file_errors") for n in assessment["nodes"]))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=("crc-block", "can-first", "reference"), required=True)
    parser.add_argument("--seconds", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 1000:
        parser.error("Window must be 1..1000 seconds")
    if args.output.exists() or args.case.resolve() in args.output.resolve().parents or args.output.resolve() == args.case.resolve():
        parser.error("Use a fresh output directory outside the input case")
    bundle = args.bundle.resolve()
    for line in (bundle/"SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split(maxsplit=1)
        path = (bundle/name.lstrip("*")).resolve()
        if bundle not in path.parents or sha(path) != digest.lower():
            raise ValueError("Bundle checksum mismatch: "+name)
    manifest = json.loads((bundle/"BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest["status"] != "passed":
        raise ValueError("Bundle is not passed")
    bdqs = list(args.case.glob("*.bdq"))
    if len(bdqs) != 1:
        parser.error("Exactly one BDQ required")
    required = [bdqs[0], args.case/"serial.txt", args.case/"loggercfg.txt"]
    if not all(p.is_file() for p in required):
        parser.error("Finalized BDQ, serial.txt and loggercfg.txt required")
    optional = args.case/"ccs.txt"
    args.output.mkdir(parents=True)
    intake = []
    for source in [*required, *([optional] if optional.is_file() else [])]:
        data = source.read_bytes()
        owned = args.output/source.name
        owned.write_bytes(data)
        intake.append(dict(source=str(source.resolve()), owned_copy=source.name, sha256=sha(owned), bytes=len(data)))
    def save(name, value):
        (args.output/name).write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")
    save("INTAKE.json", dict(files=intake, missing_inputs=[] if optional.is_file() else ["ccs.txt"],
        bundle_manifest_sha256=sha(bundle/"BUILD_MANIFEST.json")))
    bdq = args.output/bdqs[0].name
    info = read_bdq(bdq)
    strict = assess_multi_imu_recording(bdq, [0, 1])
    summary = info.final_summary
    stop_ms = summary.get("stop", {}).get("uptime_ms")
    early_failures = [f for f in summary.get("remote_failures", [])
        if stop_ms is None or f["observed_ms"] < stop_ms]
    result = dict(schema="bodaqs.master_drain_assessment.v1", declared_variant=args.variant,
        master_image_verified=False, master_identity_note="BDQ recipe identifies logger, not installed master; review CCS optimization marker and operator image record",
        expected_optimization_info=(None if args.variant=="reference" else manifest["variants"][args.variant]["debugger_optimization_info"]),
        recipe_matches=info.metadata.get("firmware_recipe_id")==manifest["logger_recipe"],
        configuration_byte_exact=sha(args.output/"loggercfg.txt")==manifest["configuration_sha256"],
        active_expected_sources=bool(capture_active(strict)), early_failures=early_failures,
        serial_readiness=serial_membership((args.output/"serial.txt").read_text(encoding="utf-8-sig")),
        file_errors=info.detected_errors, strict_assessment=strict, payload=payload_window(bdq,args.seconds),
        qualification="unqualified; operator review required")
    result["comparison_precheck_passed"] = bool(result["recipe_matches"] and result["configuration_byte_exact"]
        and result["active_expected_sources"] and not early_failures and result["serial_readiness"]["ready"]
        and not info.detected_errors and summary.get("clean_shutdown") is True and result["payload"]["available"])
    save("assessment.json", result)
    files = sorted(args.output.iterdir())
    (args.output/"SHA256SUMS.txt").write_text("".join(sha(p)+"  "+p.name+"\n" for p in files), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("comparison_precheck_passed", "active_expected_sources", "master_image_verified", "payload", "qualification")},indent=2))
    return 0 if result["comparison_precheck_passed"] else 1

if __name__ == "__main__":
    sys.exit(main())
