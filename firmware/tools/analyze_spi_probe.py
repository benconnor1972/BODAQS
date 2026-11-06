"""Offline bench evidence only; never a production admission or T01 gate."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


SCHEMA = "bodaqs.spi-probe.v1"
SCHEMA_V2 = "bodaqs.spi-probe.v2"
SCHEMA_V3 = "bodaqs.spi-probe.v3"
DIAGNOSTIC_SCHEMAS = (SCHEMA_V2, SCHEMA_V3)
NO_ROW_MODES = ("bulk", "switch", "shape", "selected")
DECODE_NAMES = "ok argument frame_size magic version profile payload_length crc padding".split()
COMPONENT_COUNTERS = {0: "process_calls", 1: "process_total_us", 3: "boundary_calls",
                      4: "retire_total_us", 6: "publish_calls", 7: "publish_wait_total_us"}
COMPONENT_MAXIMA = {2: "process_max_us", 5: "retire_max_us", 8: "publish_wait_max_us"}
ENGINE_NAMES = "requests malformed rejected prepared_fragments repeat_fragments selected_objects retired_objects duplicate_acks bad_acks cases".split()
ADAPTER_COUNTER_NAMES = "slots_received spi_rx_dropped malformed_slots spi_recoveries cs_release_timeouts can_rx_frames can_rx_dropped can_rx_hardware_losses".split()
ADAPTER_STATE_NAMES = ("clock_epoch", "timing_invalid")


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


def diagnostic_counts(case):
    d = case["diagnostics"]
    decoded = d["decode_counts"]
    require(isinstance(decoded, list) and len(decoded) == 9 and
            all(type(v) is int and v >= 0 for v in decoded), "invalid decoder counts")
    require(sum(decoded[1:]) == case["errors"]["wire"] and
            sum(decoded) + case["errors"]["transfer"] == case["slots"] and
            case["valid_responses"] <= decoded[0] and
            case["timing"]["decode"]["count"] == sum(decoded), "inconsistent decoder accounting")
    participants = d["by_previous_cs"]
    require(isinstance(participants, list), "invalid preceding participant distribution")
    seen = set()
    for entry in participants:
        counts(entry, "responses decode_failures")
        require(type(entry["cs"]) is int and -2 <= entry["cs"] <= 255 and
                entry["cs"] not in seen, "invalid preceding participant")
        seen.add(entry["cs"])
    require(sum(e["responses"] for e in participants) == decoded[0] and
            sum(e["decode_failures"] for e in participants) == sum(decoded[1:]),
            "inconsistent preceding participant distribution")
    samples = d["failure_samples"]
    require(isinstance(samples, list) and len(samples) <= 4 and
            len(samples) + d["failure_samples_omitted"] == sum(decoded[1:]),
            "inconsistent failure sample accounting")
    # Successful bursts and failed attempts are independent counters.
    require(case["profile"]["mode"] == "switch" or
            d["switch_transfers"] == d["switch_failures"] == 0, "inconsistent switch control counts")
    slots = set()
    reasons = [0] * 9
    previous = {}
    profile = case["profile"]
    wire_profile = ({64: 0, 128: 1, 256: 2}[profile["frame_bytes"]] |
                    (4 if profile["requested_sck_hz"] == 16000000 else 0) |
                    ((profile["nodes"] - 1) << 3))
    for sample in samples:
        counts(sample, "reason slot frame_bytes")
        require(1 <= sample["reason"] <= 8 and 1 <= sample["slot"] <= case["slots"] and
                sample["slot"] not in slots, "invalid failure sample reason/slot")
        slots.add(sample["slot"])
        reasons[sample["reason"]] += 1
        require(sample["frame_bytes"] == profile["frame_bytes"] and
                isinstance(sample["rx_hex"], str) and
                re.fullmatch(r"[0-9a-fA-F]{%d}" % (sample["frame_bytes"] * 2), sample["rx_hex"]) is not None,
                "failure sample must contain complete frame hex")
        request = sample["request"]
        counts(request, "opcode case_id profile node fragment object_id logical_crc")
        require(request["opcode"] in (2, 3) and request["case_id"] == case["case_id"] and
                request["profile"] == wire_profile and request["node"] < profile["nodes"] and
                0 < request["object_id"] <= 4294967295 and request["logical_crc"] <= 4294967295 and
                request["fragment"] < (1008 + profile["frame_bytes"] - 25) // (profile["frame_bytes"] - 24) and
                (request["opcode"] != 3 or request["fragment"] == 0),
                "invalid failure sample request identity")
        bus = sample["bus"]
        counts(bus, "sequence cs previous_release_us cs_assert_us cs_release_us")
        require(all(bus[name] <= 4294967295 for name in (
                    "sequence", "previous_release_us", "cs_assert_us", "cs_release_us")) and
                bus["cs"] <= 255 and type(bus["previous_valid"]) is bool and
                type(bus["previous_cs"]) is int and -2 <= bus["previous_cs"] <= 255,
                "invalid failure sample bus context")
        cs = bus["previous_cs"] if bus["previous_valid"] else -1
        previous[cs] = previous.get(cs, 0) + 1
    require(all(retained <= total for retained, total in zip(reasons[1:], decoded[1:])),
            "sample reasons exceed decoder failure counts")
    distribution = {e["cs"]: e["decode_failures"] for e in participants}
    require(all(n <= distribution.get(cs, 0) for cs, n in previous.items()),
            "samples exceed preceding participant failures")


def operation_key(cs, operation):
    counts(operation, "bytes tx0")
    require(operation["bytes"] <= 256 and operation["tx0"] <= 255 and
            type(operation["has_tx"]) is bool and type(operation["has_rx"]) is bool and
            (operation["has_tx"] or operation["tx0"] == 0), "invalid previous operation")
    return (cs, operation["bytes"], operation["tx0"], operation["has_tx"], operation["has_rx"])


def integrity_counts(case):
    d = case["diagnostics"]
    counts(d, "operation_buckets_omitted")
    buckets = d["by_previous_operation"]
    require(isinstance(buckets, list) and len(buckets) <= 16, "invalid operation buckets")
    seen, totals = {}, {}
    for entry in buckets:
        counts(entry, "responses decode_failures")
        require(type(entry["cs"]) is int and -2 <= entry["cs"] <= 255, "invalid operation participant")
        key = operation_key(entry["cs"], entry["operation"])
        require(key not in seen, "duplicate operation bucket")
        seen[key] = entry["decode_failures"]
        pair = totals.setdefault(entry["cs"], [0, 0])
        pair[0] += entry["responses"]
        pair[1] += entry["decode_failures"]
    missing, missing_failures = 0, {}
    for entry in d["by_previous_cs"]:
        pair = totals.pop(entry["cs"], [0, 0])
        require(pair[0] <= entry["responses"] and pair[1] <= entry["decode_failures"],
                "operation buckets exceed participant totals")
        missing += entry["responses"] + entry["decode_failures"] - sum(pair)
        missing_failures[entry["cs"]] = entry["decode_failures"] - pair[1]
    require(not totals and missing == d["operation_buckets_omitted"], "inconsistent operation accounting")
    retained = {}
    for sample in d["failure_samples"]:
        bus = sample["bus"]
        key = operation_key(bus["previous_cs"] if bus["previous_valid"] else -1, bus["previous_operation"])
        require(bus["previous_valid"] or key[1:] == (0, 0, False, False), "unknown operation has data")
        retained[key] = retained.get(key, 0) + 1
    unbucketed = {}
    for key, n in retained.items():
        if key in seen:
            require(n <= seen[key], "failure samples exceed known operation failures")
        else:
            unbucketed[key[0]] = unbucketed.get(key[0], 0) + n
    require(all(n <= missing_failures.get(cs, 0) for cs, n in unbucketed.items()),
            "failure samples exceed omitted operation failures")
    sequence = d["sequence"]
    active = case["profile"]["mode"] in ("shape", "selected")
    require(type(sequence["active"]) is bool and sequence["active"] == active and
            type(sequence["worker_start_requested"]) is bool, "invalid sequence state")
    counts(sequence, "failures timeouts")
    ops = sequence["operations"]
    require(isinstance(ops, list) and len(ops) == 2 and all(
        isinstance(row, list) and len(row) == 3 and all(type(v) is int and v >= 0 for v in row)
        and row[0] >= row[1] >= row[2] and row[0] - row[2] <= 1 for row in ops), "invalid ADC step counts")
    if active:
        require(not sequence["worker_start_requested"] and case["rows"] == 0, "sequence started workers or rows")
        if case["outcome"] == "complete":
            require(all(row[2] > 0 for row in ops) and sequence["failures"] == sequence["timeouts"] == 0,
                    "complete sequence has missing reads or failures")
        if case["profile"]["mode"] == "shape":
            require(sum(sum(row) for row in ops) == sum(p["transfers"] for p in case["spi"] if p["cs"] == -2),
                    "unselected sequence transfer mismatch")
    else:
        require(sum(sum(row) for row in ops) == sequence["failures"] == sequence["timeouts"] == 0,
                "non-sequence case contains ADC steps")


def validate(case):
    v2 = case["schema"] in DIAGNOSTIC_SCHEMAS
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
    require(p["mode"] in (("adc", "bulk", "mixed", "switch", "shape", "selected") if case["schema"] == SCHEMA_V3 else (("adc", "bulk", "mixed", "switch") if v2 else ("adc", "bulk", "mixed"))) and
            p["frame_bytes"] in (64, 128, 256) and
            p["requested_sck_hz"] in (8000000, 16000000) and
            p["guard_us"] == 25 and 1 <= p["nodes"] <= 4 and
            100 <= p["duration_ms"] <= 3600000 and p["row_hz"] == 500 and
            p["ain"] == [0, 4] and p["configured_sps"] == [1000, 1000],
            "unsupported profile")
    if v2:
        counts(p, "start_interval_us")
        require(p["crc_mode"] in ("legacy", "cached") and p["start_interval_us"] <= 5000,
                "unsupported diagnostic profile")
    require(all(type(v) is int for name in ("ain", "configured_sps") for v in p[name]),
            "profile channel/rate values must be integers")
    # Both capture versions leave actual clock unmeasured, even at requested16 MHz.
    require(p["actual_sck_hz"] is None and p["actual_sck_basis"] == "unmeasured",
            "actual SCK must remain unmeasured")
    require(case["accepted_bytes"] == case["unique_objects"] * 1008,
            "accepted bytes do not match unique objects")
    require(case["retired_objects"] <= case["unique_objects"], "retired exceeds accepted")
    require(case["valid_responses"] <= case["slots"], "responses exceed slots")
    if p["mode"] == "adc":
        require(all(case[k] == 0 for k in ("slots", "valid_responses", "unique_objects", "accepted_bytes", "retired_objects")),
                "ADC-only case contains transport traffic")
    if p["mode"] in NO_ROW_MODES:
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
        counts(spi, "transfers bytes lock_failures")
        require(type(spi["cs"]) is int and (spi["cs"] >= 0 or (v2 and spi["cs"] == -2)),
                "invalid SPI participant")
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
        if p["mode"] not in NO_ROW_MODES:
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
        if v2:
            require(type(master["diagnostic_measured"]) is bool, "invalid diagnostic measured flag")
            for name in ("diagnostic_before", "diagnostic_after"):
                require(isinstance(master[name], list) and len(master[name]) == 10 and
                        all(type(v) is int and 0 <= v <= 4294967295 for v in master[name]),
                        "invalid master diagnostic page")
            require(master["timing_measured"] is master["diagnostic_measured"] and
                    master["timing_scope"] == ("software_observations" if master["diagnostic_measured"] else "unmeasured"),
                    "unsupported master timing scope")
        else:
            require(master["timing_measured"] is False and
                    master["timing_scope"] == "unmeasured", "unsupported master timing scope")
    if v2:
        diagnostic = case["diagnostics"]
        for name in ("validate", "expected_crc", "iteration", "request_interval"):
            timing(diagnostic["timing"][name])
        counts(diagnostic, "expected_crc_calls pacing_deferred switch_transfers switch_failures failure_samples_omitted")
        require(diagnostic["expected_crc_calls"] == diagnostic["timing"]["expected_crc"]["count"],
                "expected CRC call count mismatch")
        diagnostic_counts(case)
        if case["schema"] == SCHEMA_V3:
            integrity_counts(case)


def unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, f"duplicate JSON key {key}")
        obj[key] = value
    return obj


def adc_status(case):
    if case["profile"]["mode"] in NO_ROW_MODES:
        return "not_applicable"
    target = min(case["elapsed_us"], case["profile"]["duration_ms"] * 1000) * 500 / 1000000
    healthy = case["elapsed_us"] > 0 and case["rows"] > 0 and abs(case["rows"] - target) <= 1 and case["missed_rows"] == 0
    if case["outcome"] == "complete":
        healthy = healthy and abs(case["elapsed_us"] - case["profile"]["duration_ms"] * 1000) <= 2000
    healthy = healthy and all(a["fresh"] == case["rows"] and
        a["reused"] == a["no_sample"] == a["acquire_fail"] == a["wait_timeouts"] == 0
        for a in case["adc"])
    return "healthy" if healthy else "failed"


def master_diagnostics(case):
    m = case.get("master")
    if not m:
        return "unknown", None, None, None
    engine = [(end - start) % 4294967296 for start, end in zip(m["before"], m["after"])] if m["measured"] else None
    adapter = [(end - start) % 4294967296 for start, end in zip(m["adapter_before"][:8], m["adapter_after"][:8])] if m["adapter_measured"] else None
    states = {name: {"before": m["adapter_before"][i], "after": m["adapter_after"][i]}
              for i, name in enumerate(ADAPTER_STATE_NAMES, 8)} if m["adapter_measured"] else None
    # Epoch and sticky invalidity are endpoint states, never modulo counters.
    clock_bad = states is not None and (
        states["clock_epoch"]["before"] == 0 or
        states["clock_epoch"]["before"] != states["clock_epoch"]["after"] or
        any(states["timing_invalid"].values()))
    # Repeat fragments and duplicate ACKs are normal pipeline/retry diagnostics.
    bad = (engine is not None and any(engine[i] for i in (1, 2, 8))) or (
        adapter is not None and any(adapter[i] for i in (1, 2, 3, 4, 6, 7))) or clock_bad
    status = "failed" if bad else "clean" if engine is not None and adapter is not None else "unknown"
    return status, engine, adapter, states


def component_timing(case):
    master = case.get("master")
    result = {"status": "unknown", "scope": "software observations; process, retirement and publication wait may overlap; not a physical rearm bound",
              "counter_deltas": None, "boot_maxima": None, "timing_invalid": None}
    if case["schema"] not in DIAGNOSTIC_SCHEMAS or not master or not master["diagnostic_measured"]:
        return result
    before, after = master["diagnostic_before"], master["diagnostic_after"]
    result.update(
        status="invalid" if before[9] or after[9] else "observed" if any(
            (after[i] - before[i]) % 4294967296 for i in (0, 3, 6)) else "no_observations",
        counter_deltas={name: (after[i] - before[i]) % 4294967296 for i, name in COMPONENT_COUNTERS.items()},
        boot_maxima={name: {"before": before[i], "after": after[i]} for i, name in COMPONENT_MAXIMA.items()},
        timing_invalid={"before": before[9], "after": after[9]})
    return result


def failure_samples(case):
    if case["schema"] not in DIAGNOSTIC_SCHEMAS:
        return None
    result = []
    for sample in case["diagnostics"]["failure_samples"]:
        bus = sample["bus"]
        result.append({**sample, "reason_name": DECODE_NAMES[sample["reason"]],
                       "bus_intervals_us": {
                           "cs_ownership": (bus["cs_release_us"] - bus["cs_assert_us"]) % 4294967296,
                           "since_previous_release": (bus["cs_assert_us"] - bus["previous_release_us"]) % 4294967296
                           if bus["previous_valid"] else None}})
    return result


def diagnostic_observations(case):
    if case["schema"] not in DIAGNOSTIC_SCHEMAS:
        return "unknown"
    if case["profile"]["mode"] == "adc":
        return "not_applicable"
    d = case["diagnostics"]
    observed = d["decode_counts"][0] > 0 and d["timing"]["iteration"]["count"] > 0
    if case["slots"] > 1:
        observed = observed and d["timing"]["request_interval"]["count"] > 0
    if case["accepted_bytes"]:
        observed = observed and d["timing"]["validate"]["count"] > 0 and d["expected_crc_calls"] > 0
    return "observed" if observed else "unknown"


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
    def group(case):
        profile = {k: v for k, v in case["profile"].items() if k not in ("mode", "frame_bytes", "requested_sck_hz")}
        return json.dumps({"schema": case["schema"], "artifacts": case["artifacts"], "profile": profile}, sort_keys=True)
    groups = sorted({group(c) for c in cases})
    for key in groups:
        identity = json.loads(key)
        p = identity["profile"]
        for hz in (8000000, 16000000):
            for frame in (64, 128, 256):
                matching = [c for c in cases if group(c) == key and
                    c["profile"]["requested_sck_hz"] == hz and c["profile"]["frame_bytes"] == frame]
                bulk = [c for c in matching if c["profile"]["mode"] == "bulk"]
                mixed = [c for c in matching if c["profile"]["mode"] == "mixed"]
                ratios = [(m["accepted_bytes"] / m["elapsed_us"]) / (b["accepted_bytes"] / b["elapsed_us"])
                          for b in bulk for m in mixed if b["accepted_bytes"] > 0 and b["elapsed_us"] > 0 and m["elapsed_us"] > 0]
                result.append({"nodes": p["nodes"], "duration_ms": p["duration_ms"], "logger_build": identity["artifacts"]["logger_build"],
                    "schema": identity["schema"], "artifacts": identity["artifacts"],
                    "declared_profile": {**p, "frame_bytes": frame, "requested_sck_hz": hz},
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
        if not isinstance(item, dict) or item.get("schema") not in (SCHEMA, SCHEMA_V2, SCHEMA_V3):
            raise ValueError(f"line {number}: unsupported schema")
        if item.get("type") == "case":
            validate(item)
            require(all(c["case_id"] != item["case_id"] for c in cases), "duplicate case ID")
            cases.append(item)
        else:
            require(item.get("type") in ("ready", "status", "error"), "unknown result type")
            if item["schema"] in DIAGNOSTIC_SCHEMAS and item["type"] in ("ready", "status"):
                require(isinstance(item["logger_build"], str) and item["logger_build"].strip(),
                        "missing source build identity")
                require(type(item["ready"]) is bool, "invalid ready state")
                if item["type"] == "status":
                    require(type(item["blocked"]) is bool, "invalid blocked state")
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
        master, engine_delta, adapter_delta, adapter_states = master_diagnostics(case)
        components = component_timing(case)
        observations = diagnostic_observations(case)
        if case["schema"] in DIAGNOSTIC_SCHEMAS and p["mode"] != "adc":
            if components["status"] == "invalid":
                master = "failed"
            elif master == "clean" and (components["status"] != "observed" or
                    case["slots"] == 0 or case["diagnostics"]["decode_counts"][0] == 0):
                master = "unknown"
        transport = "failed" if any(case["errors"][k] for k in ("transfer", "wire", "accept", "commands")) or (
            case["schema"] in DIAGNOSTIC_SCHEMAS and case["diagnostics"]["switch_failures"]) else "clean"
        if case["schema"] == SCHEMA_V3 and any(case["diagnostics"]["sequence"][k] for k in ("failures", "timeouts")):
            transport = "failed"
        baselines = [c for c in cases if c["profile"]["mode"] == "adc" and
                     c["schema"] == case["schema"] and
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
            p["mode"] != "mixed" or baseline == "healthy") and (
            case["schema"] not in DIAGNOSTIC_SCHEMAS or observations in ("observed", "not_applicable"))
        control = case["schema"] in DIAGNOSTIC_SCHEMAS and (p["mode"] in ("switch", "shape", "selected") or
                  p["crc_mode"] == "cached" or p["start_interval_us"] > 0)
        result.append({"case_id": case["case_id"],
            "profile": p, "outcome": case["outcome"], "reason": case["reason"],
            "duration_status": duration_status,
            "scheduled_rows_target": min(case["elapsed_us"], p["duration_ms"] * 1000) * 500 / 1000000 if p["mode"] in ("adc", "mixed") else None,
            "accepted_bytes_per_second": case["accepted_bytes"] / seconds if seconds else None,
            "retired_bytes_per_second": case["retired_objects"] * 1008 / seconds if seconds else None,
            "pending_ack_objects": case["unique_objects"] - case["retired_objects"],
            "useful_data_status": "not_applicable" if p["mode"] == "adc" else "observed" if case["accepted_bytes"] else "none",
            "actual_sck_hz": case["profile"]["actual_sck_hz"],
            "rows_per_second": case["rows"] / seconds if seconds else None,
            "adc_status": adc, "transport_status": transport,
            "baseline_case_ids": [c["case_id"] for c in baselines], "baseline_status": baseline,
            "baseline_matching_scope": "same schema, artifacts, nodes and duration; transport frame/clock/CRC/pacing are inactive in ADC-only mode",
            "master_diagnostics_status": master,
            "master_engine_deltas": dict(zip(ENGINE_NAMES, engine_delta)) if engine_delta is not None else None,
            "master_adapter_deltas": dict(zip(ADAPTER_COUNTER_NAMES, adapter_delta)) if adapter_delta is not None else None,
            "master_adapter_states": adapter_states,
            "master_component_timing": components,
            "decoder_counts": dict(zip(DECODE_NAMES, case["diagnostics"]["decode_counts"])) if case["schema"] in DIAGNOSTIC_SCHEMAS else None,
            "failure_samples": failure_samples(case),
            "failure_samples_omitted": case["diagnostics"]["failure_samples_omitted"] if case["schema"] in DIAGNOSTIC_SCHEMAS else None,
            **({"decode_by_previous_operation": case["diagnostics"]["by_previous_operation"],
                "operation_buckets_omitted": case["diagnostics"]["operation_buckets_omitted"],
                "sequential_control": case["diagnostics"]["sequence"]} if case["schema"] == SCHEMA_V3 else {}),
            "decode_by_previous_cs": case["diagnostics"]["by_previous_cs"] if case["schema"] in DIAGNOSTIC_SCHEMAS else None,
            "decode_previous_cs_distribution": [
                {**entry, "decode_calls": entry["responses"] + entry["decode_failures"],
                 "failure_fraction_of_decode_calls": entry["decode_failures"] / (entry["responses"] + entry["decode_failures"])
                 if entry["responses"] + entry["decode_failures"] else None}
                for entry in case["diagnostics"]["by_previous_cs"]] if case["schema"] in DIAGNOSTIC_SCHEMAS else None,
            "diagnostic_observation_status": observations,
            "transport_diagnostic_timing": case["diagnostics"]["timing"] if case["schema"] in DIAGNOSTIC_SCHEMAS else None,
            "expected_crc_calls": case["diagnostics"]["expected_crc_calls"] if case["schema"] in DIAGNOSTIC_SCHEMAS else None,
            "experimental_control": {"crc_mode": p.get("crc_mode", "legacy"),
                                     "start_interval_us": p.get("start_interval_us", 0),
                                     "synthetic_switch": p["mode"] == "switch"},
            "transport_error_counts": case["errors"],
            "pipeline_diagnostics": {k: case["errors"][k] for k in ("stale", "duplicate")},
            "candidate_evidence": "failed" if failed else "diagnostic_control" if control else "clean_measurement_candidate" if clean_candidate else "unknown",
            "raw_measurements": case})
    return {"schema": "bodaqs.spi-probe-report.v3" if any(c["schema"] == SCHEMA_V3 for c in cases) else "bodaqs.spi-probe-report.v2" if any(c["schema"] in DIAGNOSTIC_SCHEMAS for c in cases) else "bodaqs.spi-probe-report.v1",
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
                      "master_deltas": "counters only, modulo uint32; wider than timed window; not useful-byte measurements",
                      "master_adapter_states": "raw endpoint states; clock_epoch must be stable and nonzero, timing_invalid zero at both endpoints",
                      "master_component_timing": "software process/retirement/publication wait may overlap; cumulative counter deltas, boot maxima and sticky flag endpoints are separate; not a physical rearm bound",
                      "can_servicing": "excluded from this synthetic workload; observed CAN software drops and hardware losses remain visible; no concurrent CAN pass",
                      "diagnostic_controls": "CRC caching, added request pacing and unselected mode-switch clocks change experimental conditions; never a capacity/admission pass",
                      "decoder_distribution": "responses are decode OK; decode_calls = responses + decode_failures; failure fractions use decode_calls, excluding transfer failures",
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
