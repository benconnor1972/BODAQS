"""Offline bench evidence only; never a production admission or T01 gate."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


SCHEMA = "bodaqs.spi-probe.v1"
ENGINE_NAMES = "requests malformed rejected prepared_fragments repeat_fragments selected_objects retired_objects duplicate_acks bad_acks cases".split()
ADAPTER_NAMES = "slots_received spi_rx_dropped malformed_slots spi_recoveries cs_release_timeouts can_rx_frames can_rx_dropped can_rx_hardware_losses clock_epoch timing_invalid".split()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def counts(obj, names):
    for name in names.split():
        require(type(obj[name]) is int and obj[name] >= 0,
                f"{name} must be a nonnegative integer")


def timing(obj):
    counts(obj, "count min_us max_us total_us")
    n, lo, hi, total = (obj[k] for k in ("count", "min_us", "max_us", "total_us"))
    require((n == 0 and lo == hi == total == 0) or
            (n > 0 and lo <= hi and n * lo <= total <= n * hi),
            "inconsistent timing summary")


def validate(case):
    counts(case, "case_id elapsed_us rows missed_rows slots valid_responses unique_objects accepted_bytes retired_objects")
    require(0 < case["case_id"] <= 4294967295, "invalid case ID")
    require(case["elapsed_us"] > 0 or (case["outcome"] != "complete" and case["rows"] == 0 and case["accepted_bytes"] == 0), "empty complete timed window")
    require(case["outcome"] in ("complete", "stopped", "failed"), "invalid outcome")
    require(isinstance(case["reason"], str), "missing reason")
    require(case["startup_included"] is True, "unsupported counter scope")
    require(type(case.get("workers_stopped", True)) is bool, "invalid stop flag")
    a = case["artifacts"]
    require(a["protocol"] == 1 and type(a["protocol"]) is int and
            isinstance(a["logger_build"], str) and a["logger_build"] and
            a["master_build"] == "external-manifest", "invalid artifact identity")
    p = case["profile"]
    counts(p, "frame_bytes requested_sck_hz guard_us nodes duration_ms row_hz")
    require(p["mode"] in ("adc", "bulk", "mixed") and
            p["frame_bytes"] in (64, 128, 256) and
            p["requested_sck_hz"] in (8000000, 16000000) and
            p["guard_us"] == 25 and 1 <= p["nodes"] <= 4 and
            100 <= p["duration_ms"] <= 3600000 and p["row_hz"] == 500 and
            p["ain"] == [0, 4] and p["configured_sps"] == [1000, 1000],
            "unsupported profile")
    require(all(type(v) is int for name in ("ain", "configured_sps") for v in p[name]),
            "profile channel/rate values must be integers")
    # Frozen v1 emits no measurement of actual clock, even when 16 MHz requested.
    require(p["actual_sck_hz"] is None and p["actual_sck_basis"] == "unmeasured",
            "v1 actual SCK must remain unmeasured")
    require(case["accepted_bytes"] == case["unique_objects"] * 1008,
            "accepted bytes do not match unique objects")
    require(case["retired_objects"] <= case["unique_objects"], "retired exceeds accepted")
    require(case["valid_responses"] <= case["slots"], "responses exceed slots")
    if p["mode"] == "adc":
        require(all(case[k] == 0 for k in ("slots", "valid_responses", "unique_objects", "accepted_bytes", "retired_objects")),
                "ADC-only case contains transport traffic")
    if p["mode"] == "bulk":
        require(case["rows"] == case["missed_rows"] == 0, "bulk case contains rows")
    else:
        target = min(case["elapsed_us"], p["duration_ms"] * 1000) * p["row_hz"] / 1000000
        require(abs(case["rows"] + case["missed_rows"] - target) <= 1,
                "scheduled rows plus missed rows do not match case window")
    counts(case["errors"], "transfer wire stale duplicate accept commands")
    for name in ("slot", "guard", "encode", "decode"):
        timing(case["timing"][name])
    require(isinstance(case["spi"], list), "invalid SPI diagnostics")
    seen = set()
    for spi in case["spi"]:
        counts(spi, "cs transfers bytes lock_failures")
        require(spi["cs"] not in seen, "duplicate CS diagnostics")
        seen.add(spi["cs"])
        timing(spi["lock_wait"])
        timing(spi["ownership"])
    require(isinstance(case["adc"], list) and len(case["adc"]) == 2,
            "expected two ADC diagnostics")
    seen = set()
    for adc in case["adc"]:
        counts(adc, "index acquire_ok acquire_fail fresh reused no_sample uses drdy_observed drdy_paired drdy_missing drdy_extra drdy_unpaired wait_timeouts")
        if "drdy_pre_start" in adc:
            counts(adc, "drdy_pre_start")
        require(adc["index"] in (0, 1) and adc["index"] not in seen, "invalid ADC index")
        seen.add(adc["index"])
        if p["mode"] != "bulk":
            require(adc["fresh"] + adc["reused"] + adc["no_sample"] ==
                    adc["uses"] == case["rows"], "inconsistent ADC row accounting")
        for name, value in adc.items():
            if isinstance(value, dict):
                timing(value)
        for name in ("after_read_cache_age", "drdy_to_read_end", "config", "start", "wait", "read", "total", "async_loop"):
            timing(adc[name])
        require("drdy_to_read_start" in adc or "drdy_to_read_attempt" in adc,
                "missing DRDY read-attempt timing")
    master = case.get("master")
    if master is not None:
        for measured, before, after in (("measured", "before", "after"),
                                        ("adapter_measured", "adapter_before", "adapter_after")):
            require(type(master[measured]) is bool, "invalid master measured flag")
            for name in (before, after):
                require(isinstance(master[name], list) and len(master[name]) == 10 and
                        all(type(v) is int and 0 <= v <= 4294967295 for v in master[name]),
                        "invalid master counter page")
        require(master["timing_measured"] is False and
                master["timing_scope"] == "unmeasured", "unsupported master timing scope")


def unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, f"duplicate JSON key {key}")
        obj[key] = value
    return obj


def adc_status(case):
    if case["profile"]["mode"] == "bulk":
        return "not_applicable"
    target = min(case["elapsed_us"], case["profile"]["duration_ms"] * 1000) * 500 / 1000000
    healthy = abs(case["rows"] - target) <= 1 and case["missed_rows"] == 0
    if case["outcome"] == "complete":
        healthy = healthy and abs(case["elapsed_us"] - case["profile"]["duration_ms"] * 1000) <= 2000
    healthy = healthy and all(a["fresh"] == case["rows"] and
        a["reused"] == a["no_sample"] == a["acquire_fail"] == a["wait_timeouts"] == 0
        for a in case["adc"])
    return "healthy" if healthy else "failed"


def master_diagnostics(case):
    m = case.get("master")
    if not m:
        return "unknown", None, None
    engine = [(end - start) % 4294967296 for start, end in zip(m["before"], m["after"])] if m["measured"] else None
    adapter = [(end - start) % 4294967296 for start, end in zip(m["adapter_before"], m["adapter_after"])] if m["adapter_measured"] else None
    # Repeat fragments and duplicate ACKs are normal pipeline/retry diagnostics.
    bad = (engine is not None and any(engine[i] for i in (1, 2, 8))) or (
        adapter is not None and any(adapter[i] for i in (1, 2, 3, 4, 6, 7, 9)))
    status = "failed" if bad else "clean" if engine is not None and adapter is not None else "unknown"
    return status, engine, adapter


def baseline_status(cases):
    if not cases:
        return "unknown"
    return "healthy" if all(adc_status(c) == "healthy" and c["outcome"] == "complete" and
        c.get("workers_stopped") is True and
        not any(c["errors"][k] for k in ("transfer", "wire", "accept", "commands"))
        for c in cases) else "failed"


def validate_manifest(manifest, digest, cases):
    counts(manifest, "protocol")
    require(manifest["schema"] == "bodaqs.spi-probe-manifest.v1" and
            manifest["capture_sha256"] == digest and manifest["protocol"] == 1,
            "manifest schema/protocol/capture digest mismatch")
    for name in ("capture_path", "wiring", "instrumentation"):
        require(isinstance(manifest[name], str) and manifest[name].strip(), "incomplete run manifest")
    for name in ("logger", "master"):
        endpoint = manifest[name]
        require(isinstance(endpoint["board"], str) and endpoint["board"].strip(), "missing board identity")
        require(re.fullmatch(r"[0-9a-f]{40}", endpoint["source_revision"]) is not None and
                re.fullmatch(r"[0-9a-f]{64}", endpoint["artifact_sha256"]) is not None,
                "manifest needs exact source revision and artifact SHA256")
    require(all(c["artifacts"]["logger_build"] == manifest["logger"]["build"] for c in cases),
            "manifest logger build does not match captured cases")


def comparisons(cases):
    result = []
    groups = sorted({(c["profile"]["nodes"], c["profile"]["duration_ms"], c["artifacts"]["logger_build"]) for c in cases})
    for nodes, duration, build in groups:
        for hz in (8000000, 16000000):
            for frame in (64, 128, 256):
                matching = [c for c in cases if c["profile"]["nodes"] == nodes and
                    c["profile"]["duration_ms"] == duration and c["artifacts"]["logger_build"] == build and
                    c["profile"]["requested_sck_hz"] == hz and c["profile"]["frame_bytes"] == frame]
                bulk = [c for c in matching if c["profile"]["mode"] == "bulk"]
                mixed = [c for c in matching if c["profile"]["mode"] == "mixed"]
                ratios = [(m["accepted_bytes"] / m["elapsed_us"]) / (b["accepted_bytes"] / b["elapsed_us"])
                          for b in bulk for m in mixed if b["accepted_bytes"] > 0 and b["elapsed_us"] > 0 and m["elapsed_us"] > 0]
                result.append({"nodes": nodes, "duration_ms": duration, "logger_build": build,
                    "requested_sck_hz": hz, "frame_bytes": frame,
                    "bulk_case_ids": [c["case_id"] for c in bulk], "mixed_case_ids": [c["case_id"] for c in mixed],
                    "coverage": "captured" if bulk and mixed else "missing",
                    "mixed_to_bulk_rate_ratios": ratios})
    return result


def analyze(data, manifest=None):
    """Build a deterministic report from newline JSON plus serial boot text."""
    cases = []
    events = []
    for number, line in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line.startswith(("{", "[")):
            continue
        try:
            item = json.loads(line, object_pairs_hook=unique_keys)
        except ValueError as error:
            if line.startswith("["):
                # Firmware boot diagnostics commonly start with [Storage]/[SPI].
                continue
            raise ValueError(f"line {number}: malformed JSON") from error
        if not isinstance(item, dict) or item.get("schema") != SCHEMA:
            raise ValueError(f"line {number}: unsupported schema")
        if item.get("type") == "case":
            validate(item)
            require(all(c["case_id"] != item["case_id"] for c in cases), "duplicate case ID")
            cases.append(item)
        else:
            require(item.get("type") in ("ready", "status", "error"), "unknown result type")
            events.append(item)
    if not cases:
        raise ValueError("capture contains no case results")
    digest = hashlib.sha256(data).hexdigest()
    if manifest is not None:
        validate_manifest(manifest, digest, cases)
    result = []
    for case in cases:
        seconds = case["elapsed_us"] / 1000000
        p = case["profile"]
        adc = adc_status(case)
        master, engine_delta, adapter_delta = master_diagnostics(case)
        transport = "failed" if any(case["errors"][k] for k in ("transfer", "wire", "accept", "commands")) else "clean"
        baselines = [c for c in cases if c["profile"]["mode"] == "adc" and
                     c["artifacts"] == case["artifacts"] and
                     c["profile"]["nodes"] == p["nodes"] and
                     c["profile"]["duration_ms"] == p["duration_ms"]]
        baseline = baseline_status(baselines)
        duration_status = "incomplete" if case["outcome"] != "complete" else "late" if (
            case["elapsed_us"] > p["duration_ms"] * 1000 + 2000) else "short" if (
            case["elapsed_us"] < p["duration_ms"] * 1000 - 2000) else "observed"
        failed = case["outcome"] != "complete" or case.get("workers_stopped") is False or adc == "failed" or transport == "failed" or (
            p["mode"] != "adc" and master == "failed") or (p["mode"] == "mixed" and baseline == "failed") or duration_status != "observed"
        clean_candidate = not failed and manifest is not None and case.get("workers_stopped") is True and (
            p["mode"] == "adc" or (master == "clean" and case["accepted_bytes"] > 0)) and (
            p["mode"] != "mixed" or baseline == "healthy")
        result.append({"case_id": case["case_id"],
            "profile": p, "outcome": case["outcome"], "reason": case["reason"],
            "duration_status": duration_status,
            "scheduled_rows_target": min(case["elapsed_us"], p["duration_ms"] * 1000) * 500 / 1000000 if p["mode"] != "bulk" else None,
            "accepted_bytes_per_second": case["accepted_bytes"] / seconds if seconds else None,
            "retired_bytes_per_second": case["retired_objects"] * 1008 / seconds if seconds else None,
            "pending_ack_objects": case["unique_objects"] - case["retired_objects"],
            "useful_data_status": "not_applicable" if p["mode"] == "adc" else "observed" if case["accepted_bytes"] else "none",
            "actual_sck_hz": case["profile"]["actual_sck_hz"],
            "rows_per_second": case["rows"] / seconds if seconds else None,
            "adc_status": adc, "transport_status": transport,
            "baseline_case_ids": [c["case_id"] for c in baselines], "baseline_status": baseline,
            "master_diagnostics_status": master,
            "master_engine_deltas": dict(zip(ENGINE_NAMES, engine_delta)) if engine_delta is not None else None,
            "master_adapter_deltas": dict(zip(ADAPTER_NAMES, adapter_delta)) if adapter_delta is not None else None,
            "transport_error_counts": case["errors"],
            "pipeline_diagnostics": {k: case["errors"][k] for k in ("stale", "duplicate")},
            "candidate_evidence": "failed" if failed else "clean_measurement_candidate" if clean_candidate else "unknown",
            "raw_measurements": case})
    return {"schema": "bodaqs.spi-probe-report.v1",
            "capture_sha256": digest,
            "run_identity": "declared_paired" if manifest else "unknown_without_manifest",
            "manifest": manifest, "serial_events": events,
            "comparison": comparisons(cases),
            "production_qualified": False,
            "t01_go": False, "admission_authorized": False,
            "baseline_status": baseline_status([c for c in cases if c["profile"]["mode"] == "adc"]),
            "scope": {"rows_elapsed_transport": "timed window excluding startup/shutdown",
                      "adc_counters": "include warm-up/startup/shutdown; acquisition Hz cannot be derived from elapsed_us",
                      "timing": "software observations; maxima are not certified bounds; cache age begins after RDATA publication",
                      "drdy": "observed ISR entry to read attempt before RDATA mutex; read end includes mutex wait and read",
                      "ownership": "mutex acquisition to immediately before give; excludes give/publication overhead and is not a physical blocking bound",
                      "master_deltas": "modulo uint32; wider than timed window; not useful-byte measurements",
                      "rx_drops": "software queue/acceptance pressure; does not establish electrical failure at the requested clock",
                      "physical_can_native_imu": "unqualified synthetic known-data SPI workload"},
            "cases": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path, help="external run manifest paired by capture SHA256")
    args = parser.parse_args()
    try:
        require(args.output is None or args.output.resolve() not in
                [p.resolve() for p in (args.capture, args.manifest) if p is not None],
                "output must not overwrite capture or manifest")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys) if args.manifest else None
        report = analyze(args.capture.read_bytes(), manifest)
        output = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"invalid capture: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
