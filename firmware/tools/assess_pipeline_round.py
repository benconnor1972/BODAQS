"""Owned, offline r20 intake. Missing boundaries remain missing; no capacity claim."""
import argparse
import json
from pathlib import Path
import sys
from analyze_pipeline_trace import analyze
from assess_master_drain_round import capture_active, sha
from assess_imu_optimization import payload_window, serial_membership
from bodaqs_analysis.io_bdq import read_bdq
from bodaqs_analysis.multi_imu_recording import assess_multi_imu_recording


def trace_matches_sources(trace, nodes):
    context = trace.get("summary", {}).get("context")
    return bool(trace.get("complete") and len(nodes) == 2 and
        {n.get("node") for n in nodes} == {0, 1} and
        all(str(n.get("source", {}).get("measurement_context")) == context for n in nodes))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seconds", default=100, type=int)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 1000:
        parser.error("Window must be 1..1000 seconds")
    case, out, bundle = args.case.resolve(), args.output.resolve(), args.bundle.resolve()
    if out.exists() or out == case or case in out.parents:
        parser.error("Use fresh output outside the input case")
    for line in (bundle / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split(maxsplit=1)
        path = (bundle / name.lstrip("*")).resolve()
        if bundle not in path.parents or sha(path) != digest.lower():
            raise ValueError("Bundle checksum mismatch: " + name)
    manifest = json.loads((bundle / "BUILD_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "passed" or manifest.get("schema") != "bodaqs.pipeline_round.v1":
        raise ValueError("Requires passed r20 bundle")
    bdqs = list(case.glob("*.bdq"))
    if len(bdqs) != 1:
        parser.error("Exactly one finalized BDQ required")
    required = [bdqs[0], case / "serial.txt", case / "loggercfg.txt"]
    if not all(p.is_file() for p in required):
        parser.error("Finalized BDQ, serial.txt and loggercfg.txt required")
    optional = case / "ccs.txt"
    out.mkdir(parents=True)
    intake = []
    for source in [*required, *([optional] if optional.is_file() else [])]:
        owned = out / source.name
        owned.write_bytes(source.read_bytes())
        intake.append(dict(source=str(source), owned_copy=source.name,
                           sha256=sha(owned), bytes=owned.stat().st_size))
    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    save("INTAKE.json", dict(files=intake, missing_inputs=[] if optional.is_file() else ["ccs.txt"],
        bundle_manifest_sha256=sha(bundle / "BUILD_MANIFEST.json")))
    path = out / bdqs[0].name
    info = read_bdq(path)
    strict = assess_multi_imu_recording(path, [0, 1])
    serial = (out / "serial.txt").read_text(encoding="utf-8-sig")
    trace = analyze(serial)
    save("pipeline.json", trace)
    stop_ms = info.final_summary.get("stop", {}).get("uptime_ms")
    early = [f for f in info.final_summary.get("remote_failures", [])
             if stop_ms is None or f["observed_ms"] < stop_ms]
    result = dict(schema="bodaqs.pipeline_assessment.v1", recipe_matches=
        info.metadata.get("firmware_recipe_id") == manifest["logger_recipe"],
        configuration_byte_exact=sha(out / "loggercfg.txt") == manifest["configuration_sha256"],
        active_expected_sources=capture_active(strict), early_failures=early,
        serial_readiness=serial_membership(serial), strict_assessment=strict,
        file_errors=info.detected_errors, payload=payload_window(path, args.seconds),
        trace_complete=trace["complete"], trace_context_matches_sources=trace_matches_sources(trace, strict["nodes"]),
        master_image_verified=False,
        master_identity_note="Recipe identifies logger only; operator/CCS must confirm reserve master. CCS text is retained, not automatically authenticated.",
        expected_master_markers=dict(gMasterOptimizationInfo=[1, 0, 0], gMasterBoundaryReserve=2),
        qualification="diagnostic capture; capacity and hardware timing unqualified")
    result["diagnostic_precheck_passed"] = bool(result["recipe_matches"] and result["configuration_byte_exact"]
        and result["active_expected_sources"] and not early and result["serial_readiness"]["ready"]
        and not info.detected_errors and info.final_summary.get("clean_shutdown") is True
        and result["payload"]["available"] and result["trace_context_matches_sources"])
    # The strict per-source report retains terminal/missing/unresolved coverage;
    # neither a clean file nor a complete trace proves final source delivery.
    save("assessment.json", result)
    (out / "SHA256SUMS.txt").write_text("".join(sha(p) + "  " + p.name + "\n"
        for p in sorted(out.iterdir()) if p.is_file()), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("diagnostic_precheck_passed", "trace_complete",
        "trace_context_matches_sources", "payload", "qualification")}, indent=2))
    return 0 if result["diagnostic_precheck_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
