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
SCHEMA_V4 = "bodaqs.spi-probe.v4"
SCHEMA_V5 = "bodaqs.spi-probe.v5"
SCHEMA_V6 = "bodaqs.spi-probe.v6"
SCHEMA_V7 = "bodaqs.spi-probe.v7"
SCHEMA_V8 = "bodaqs.spi-probe.v8"
SCHEMA_V9 = "bodaqs.spi-probe.v9"
SCHEMA_V10 = "bodaqs.spi-probe.v10"
SCHEMA_V11 = "bodaqs.spi-probe.v11"
SCHEMA_V13 = "bodaqs.spi-probe.v13"
RETRY_SCHEMAS = (SCHEMA_V11,SCHEMA_V13)
FLOW_SCHEMAS = (SCHEMA_V10,*RETRY_SCHEMAS)
RECEIVE_SCHEMAS = (SCHEMA_V9,*FLOW_SCHEMAS)
COST_SCHEMAS = (SCHEMA_V8, *RECEIVE_SCHEMAS)
PROCESSING_SCHEMAS = (SCHEMA_V7, *COST_SCHEMAS)
WINDOW_SCHEMAS = (SCHEMA_V6, *PROCESSING_SCHEMAS)
ROW_SCHEMAS = (SCHEMA_V5, *WINDOW_SCHEMAS)
EXECUTION_SCHEMAS = (SCHEMA_V4, *ROW_SCHEMAS)
ROW_OWNER_MODES = ("owner_adc", "owner_rows", "owner_pipe", "owner_flow")
ADC_ONLY_MODES = ("adc", "owner_adc")
INTEGRITY_SCHEMAS = (SCHEMA_V3, *EXECUTION_SCHEMAS)
DIAGNOSTIC_SCHEMAS = (SCHEMA_V2, *INTEGRITY_SCHEMAS)
NO_ROW_MODES = ("bulk", "switch", "shape", "selected", "owner", "workers")
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
    active = case["profile"]["mode"] in ("shape", "selected", "owner", *ROW_OWNER_MODES)
    require(type(sequence["active"]) is bool and sequence["active"] == active and
            type(sequence["worker_start_requested"]) is bool, "invalid sequence state")
    counts(sequence, "failures timeouts")
    ops = sequence["operations"]
    require(isinstance(ops, list) and len(ops) == 2 and all(
        isinstance(row, list) and len(row) == 3 and all(type(v) is int and v >= 0 for v in row)
        and row[0] >= row[1] >= row[2] and row[0] - row[2] <= 1 for row in ops), "invalid ADC step counts")
    if active:
        require(not sequence["worker_start_requested"] and
                (case["profile"]["mode"] in ROW_OWNER_MODES or case["rows"] == 0), "sequence started workers or rows")
        if case["outcome"] == "complete":
            mask = case["execution"]["adc_mask"] if case["schema"] in EXECUTION_SCHEMAS else 3
            require(all(row[2] > 0 for i, row in enumerate(ops) if mask & (1 << i)) and sequence["failures"] == sequence["timeouts"] == 0,
                    "complete sequence has missing reads or failures")
        if case["profile"]["mode"] == "shape":
            require(sum(sum(row) for row in ops) == sum(p["transfers"] for p in case["spi"] if p["cs"] == -2),
                    "unselected sequence transfer mismatch")
    else:
        require(sum(sum(row) for row in ops) == sequence["failures"] == sequence["timeouts"] == 0,
                "non-sequence case contains ADC steps")


def validate(case):
    v2 = case["schema"] in DIAGNOSTIC_SCHEMAS
    if case["schema"]==SCHEMA_V13:
        reply_trace_report(case)  # validate representation before interpreting it
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
    require(p["mode"] in (("adc", "bulk", "mixed", "switch", "shape", "selected", "owner", "workers", *ROW_OWNER_MODES) if case["schema"] in ROW_SCHEMAS else (("adc", "bulk", "mixed", "switch", "shape", "selected", "owner", "workers") if case["schema"] in EXECUTION_SCHEMAS else (("adc", "bulk", "mixed", "switch", "shape", "selected") if case["schema"] in INTEGRITY_SCHEMAS else (("adc", "bulk", "mixed", "switch") if v2 else ("adc", "bulk", "mixed"))))) and
            p["frame_bytes"] in (64, 128, 256) and
            p["requested_sck_hz"] in (8000000, 16000000) and
            p["guard_us"] == 25 and 1 <= p["nodes"] <= 4 and
            100 <= p["duration_ms"] <= 3600000 and p["row_hz"] == 500 and
            p["ain"] == [0, 4] and p["configured_sps"] == [1000, 1000],
            "unsupported profile")
    require(p["mode"]!="owner_flow" or case["schema"] in FLOW_SCHEMAS,"clock-only requires v10 or later")
    require(p["mode"] not in ("owner_pipe","owner_flow") or case["schema"] in WINDOW_SCHEMAS, "pipeline requires v6")
    if case["schema"] in RETRY_SCHEMAS:
        counts(p,"retry_us")
        require(p["retry_us"] in ((5000,10000,20000) if p["mode"] in ("owner_pipe","owner_flow") else (0,)),"unsupported retry profile")
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
    if p["mode"] in ADC_ONLY_MODES:
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
        if case["schema"] in PROCESSING_SCHEMAS:
            require(type(master["processing_measured"]) is bool,"invalid processing measured flag")
            for name in ("processing_before","processing_after","processing_meta_before","processing_meta_after"):
                require(isinstance(master[name],list) and len(master[name])==10 and all(type(v) is int and 0<=v<=4294967295 for v in master[name]),"invalid processing page")
            if p["mode"] in ADC_ONLY_MODES:
                require(not master["processing_measured"] and all(not any(master[n]) for n in ("processing_before","processing_after","processing_meta_before","processing_meta_after")),"ADC-only case has processing observations")
        if case["schema"] in RECEIVE_SCHEMAS:
            require(type(master["receive_measured"]) is bool,"invalid receive measured flag")
            for name in ("receive_before","receive_after","turnover_before","turnover_after"):
                require(isinstance(master[name],list) and len(master[name])==10 and all(type(v) is int and 0<=v<=4294967295 for v in master[name]),"invalid receive turnover page")
            if p["mode"] in ADC_ONLY_MODES:
                require(not master["receive_measured"] and all(not any(master[n]) for n in ("receive_before","receive_after","turnover_before","turnover_after")),"ADC-only receive observations")
        if case["schema"] in FLOW_SCHEMAS:
            require(type(master["flow_measured"]) is bool,"invalid flow measured flag")
            for name in ("flow_before","flow_after"):
                require(isinstance(master[name],list) and len(master[name])==10 and all(type(v) is int and 0<=v<=4294967295 for v in master[name]),"invalid flow page")
            if p["mode"] in ADC_ONLY_MODES:
                require(not master["flow_measured"] and not any(master["flow_before"]+master["flow_after"]),"ADC-only flow observations")
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
        if case["schema"] in INTEGRITY_SCHEMAS:
            integrity_counts(case)
        if case["schema"] in EXECUTION_SCHEMAS:
            execution_counts(case)
        if case["schema"] in ROW_SCHEMAS:
            row_counts(case)
        if case["schema"] in WINDOW_SCHEMAS:
            window_counts(case)
        if case["schema"] in COST_SCHEMAS:
            logger_cost_counts(case)


def logger_cost_counts(case):
    cost=case["logger_cost"]; c=cost["cadence"]
    require(cost["crc_algorithm"] in ("table","bitwise"),"unsupported logger CRC algorithm")
    require(case["artifacts"]["logger_build"].endswith("-crc"+str(int(cost["crc_algorithm"]=="table"))),"logger CRC identity mismatch")
    active=case["profile"]["mode"] in ROW_OWNER_MODES
    require(type(c["active"]) is bool and c["active"]==active,"invalid logger cadence mode")
    phase_names=("adc_ready_service","row_service","adc_start_service","transport_service")
    names=("adc_only","row_reserve","cs_guard","pacing","dispatch","other")
    require(set(c["decisions"])==set(names),"invalid cadence decisions")
    for name in ("cycle",*phase_names,"dispatch_headroom"):timing(c[name])
    for value in c["decisions"].values():timing(value)
    cycle=c["cycle"]; d=c["decisions"]
    require(not active or cycle["count"]>=max(0,case["rows"]-int(case["outcome"]=="failed")),"missing observed owner cycles")
    require(sum(v["count"] for v in d.values())==cycle["count"] and
            sum(v["total_us"] for v in d.values())==cycle["total_us"],"cadence outcomes do not partition cycles")
    require(sum(c[n]["total_us"] for n in phase_names)<=cycle["total_us"]<=case["elapsed_us"],"impossible cadence work totals")
    require(all(c[n]["count"]==cycle["count"] for n in phase_names[:3]),"cadence phase count mismatch")
    require(c["transport_service"]["count"]==sum(d[n]["count"] for n in ("cs_guard","pacing","dispatch","other")),"transport service count mismatch")
    require(c["dispatch_headroom"]["count"]==d["dispatch"]["count"] and
            (not c["dispatch_headroom"]["count"] or c["dispatch_headroom"]["min_us"]>800),"invalid dispatch headroom")
    require(d["row_reserve"]["count"]==case["row_publication"]["master_deferrals"],"row reserve count mismatch")
    if active:
        require(d["dispatch"]["count"]==case["slots"],"cadence dispatch count mismatch")
        require(d["cs_guard"]["count"]+d["pacing"]["count"]==case["diagnostics"]["pacing_deferred"],"pacing decision count mismatch")
        require(d["adc_only"]["count"]==(cycle["count"] if case["profile"]["mode"]=="owner_adc" else 0),"ADC-only cadence mismatch")
    else:
        require(not cycle["count"] and not c["dispatch_headroom"]["count"],"inactive cadence observations")
    obj=case["diagnostics"]["timing"]["object_crc"];timing(obj)
    expected=case["diagnostics"]["timing"]["expected_crc"]
    validate=case["diagnostics"]["timing"]["validate"]
    require(case["unique_objects"]<=obj["count"]<=case["unique_objects"]+case["errors"]["accept"],"object CRC count mismatch")
    require(obj["total_us"]+expected["total_us"]<=validate["total_us"],"impossible nested logger CRC totals")


def logger_cost_report(case):
    cost=case["logger_cost"];c=cost["cadence"]
    return {**cost,"cycle_coverage_us":c["cycle"]["total_us"],
            "outside_completed_cycles_us":case["elapsed_us"]-c["cycle"]["total_us"],
            "scope":"completed owner-loop bodies only; disjoint phase totals fit inside cycles; outcome buckets partition the SAME cycles and include ADC work, not causal blocking time; object/expected CRC nest inside validation; excludes startup/shutdown; interrupts included"}


def receive_report(case):
    result={"status":"unknown","capacity":None,"queue_endpoints":None,"counter_deltas":None,"turnover":None,
            "scope":"coherent STATS5 conservation and separate STATS6 software observations; endpoints include controls outside timed run; queue wait begins at CS retirement software entry; reply deferral is main observed; totals overlap processing/publication; boot maxima are endpoint states; no physical-ready or CPU-time claim"}
    if case["profile"]["mode"] in ADC_ONLY_MODES:
        result["status"]="not_applicable";return result
    m=case.get("master")
    if m is None or not m["receive_measured"]:return result
    a,b=m["receive_before"],m["receive_after"];u,v=m["turnover_before"],m["turnover_after"]
    result["raw_endpoints"]={n:m[n] for n in ("receive_before","receive_after","turnover_before","turnover_after")}
    if any(p[0]!=1 for p in (a,b,u,v)) or a[1] not in (1,4) or b[1] not in (1,4):return result
    invalid=a[1]!=b[1] or any(e==0 or e!=a[4] for e in (a[4],b[4],u[8],v[8])) or any((a[5],b[5],u[9],v[9]))
    invalid=invalid or any(not (0<=p[2]<=p[3]<=p[1]) or ((p[6]-p[7])&4294967295)!=p[2] for p in (a,b)) or b[3]<a[3]
    delta=lambda x,y:(y-x)&4294967295
    counters={name:delta(a[i],b[i]) for name,i in (("enqueued",6),("dequeued",7),("full_reply_ready",8),("full_other",9))}
    wait_calls,wait_total=delta(u[1],v[1]),delta(u[2],v[2])
    blocked_calls,blocked_total=delta(u[4],v[4]),delta(u[5],v[5])
    backlog=delta(u[7],v[7])
    invalid=invalid or v[3]<u[3] or v[6]<u[6] or wait_total>wait_calls*v[3] or blocked_total>blocked_calls*v[6] or backlog>wait_calls
    invalid=invalid or (a[1]==1 and (u[7]!=0 or v[7]!=0))
    invalid=invalid or any((p[8] or p[9]) and p[3]!=p[1] for p in (a,b))
    invalid=invalid or (case["outcome"]=="complete" and case["slots"]>0 and
        (not counters["enqueued"] or not counters["dequeued"] or not wait_calls))
    result.update(status="invalid" if invalid else "observed",capacity=a[1],counter_deltas=counters,
        queue_endpoints={"depth_before":a[2],"depth_after":b[2],"high_water_before":a[3],"high_water_after":b[3]})
    if not invalid:
        result["turnover"]={"queue_wait_calls":wait_calls,"queue_wait_total_us":wait_total,"queue_wait_mean_us":wait_total/wait_calls if wait_calls else None,
            "queue_wait_boot_max_before_us":u[3],"queue_wait_boot_max_after_us":v[3],"reply_deferred_episodes":blocked_calls,
            "reply_deferred_total_us":blocked_total,"reply_deferred_mean_us":blocked_total/blocked_calls if blocked_calls else None,
            "reply_deferred_boot_max_before_us":u[6],"reply_deferred_boot_max_after_us":v[6],"backlog_pops":backlog}
    return result


def reply_trace_report(case):
    """Master-local bounded sample; no clock alignment or delivery inference."""
    trace=case["master"]["reply_trace"]
    require(type(trace["measured"]) is bool and type(trace["read_complete"]) is bool,"invalid trace flags")
    header,records=trace["header"],trace["records"]
    require(isinstance(header,list) and len(header)==10 and
            all(type(v) is int and 0<=v<=0xffffffff for v in header),"invalid trace header")
    require(isinstance(records,list) and len(records)<=8 and all(isinstance(w,list) and len(w)==20 and
            all(type(v) is int and 0<=v<=0xffffffff for v in w) for w in records),"invalid trace records")
    result={"status":"unknown","sample_count":len(records),"header":header,
        "scope":"master clock only; first 8 successful POLL/ACK preparations after skipping 256; software CS-retirement entry, not pad edge; full exchange is not valid MISO or logger acceptance; no cross-clock subtraction"}
    if not trace["measured"]:
        require(not records and not trace["read_complete"],"unmeasured trace has records")
        if case["profile"]["mode"] in ADC_ONLY_MODES:result["status"]="not_applicable"
        return result
    invalid=header[0]!=1 or header[1] not in (0,1) or header[2:4]!=[8,256] or header[4]>8 or header[9]!=0
    invalid=invalid or header[6]!=case["case_id"] or not header[7] or header[8]!=0
    invalid=invalid or len(records)>header[4] or (trace["read_complete"] and len(records)!=header[4])
    invalid=invalid or (not header[1] and (header[4] or header[5]))
    if header[1]:invalid=invalid or header[4]!=min(8,max(0,header[5]-256))
    observations=[]
    stage_values={k:[] for k in ("arrival_to_process_us","processing_us","process_to_ready_us","ready_to_publication_us","publication_to_full_exchange_us","arrival_to_full_exchange_us")}
    code={64:0,128:1,256:2}[case["profile"]["frame_bytes"]]
    for i,w in enumerate(records):
        opcode,node,fragment,size_code=(w[2]>>(8*j)&255 for j in range(4))
        flags=w[4]
        invalid=invalid or w[0]!=257+i or not w[1] or opcode not in (2,3) or node>=case["profile"]["nodes"] or size_code!=code
        invalid=invalid or fragment>=((1008+case["profile"]["frame_bytes"]-25)//(case["profile"]["frame_bytes"]-24)) or (opcode==3 and fragment!=0)
        invalid=invalid or w[3]!=header[7] or flags not in (1,3,7) or not 1<=w[14]<=4 or w[15]!=case["case_id"] or any(w[16:])
        invalid=invalid or (not flags&2 and (w[9] or w[12])) or (not flags&4 and (w[10] or w[13]))
        durations={"arrival_to_process_us":(w[6]-w[5])&0xffffffff,"processing_us":(w[7]-w[6])&0xffffffff,
                   "process_to_ready_us":(w[8]-w[7])&0xffffffff}
        if flags&2:
            durations["ready_to_publication_us"]=(w[9]-w[8])&0xffffffff
            invalid=invalid or not 0<((w[12]-w[11])&0xffffffff)<0x80000000
        if flags&4:
            durations["publication_to_full_exchange_us"]=(w[10]-w[9])&0xffffffff
            durations["arrival_to_full_exchange_us"]=(w[10]-w[5])&0xffffffff
            invalid=invalid or not 0<((w[13]-w[12])&0xffffffff)<0x80000000
        invalid=invalid or any(v>=0x80000000 for v in durations.values())
        for k,v in durations.items():stage_values[k].append(v)
        observations.append({"ordinal":w[0],"object_id":w[1],"opcode":opcode,"node":node,"fragment":fragment,
            "flags":flags,"queue_depth_at_pop":w[14],"receive_boundary":w[11],"publish_boundary":w[12],"full_exchange_boundary":w[13],
            "kind":"ack" if opcode==3 else "poll_head" if fragment==0 else "poll_body",**durations})
    result["status"]="invalid" if invalid else "incomplete" if not trace["read_complete"] else "disabled" if not header[1] else "observed" if records else "empty"
    if not invalid:
        result["records"]=observations
        result["stages"]={k:{"count":len(v),"min_us":min(v) if v else None,"max_us":max(v) if v else None,
            "mean_us":sum(v)/len(v) if v else None} for k,v in stage_values.items()}
        result["full_exchange_count"]=len(stage_values["publication_to_full_exchange_us"])
    return result


def flow_report(case):
    result={"status":"not_applicable" if case["profile"]["mode"] in ADC_ONLY_MODES else "unknown",
            "clock_only":case["profile"]["mode"]=="owner_flow","bypassed":None,
            "scope":"STATS7 boot counter delta includes controls outside timed run; bypass is not response delivery/readiness or a work credit"}
    m=case["master"]
    if result["status"]=="not_applicable" or not m["flow_measured"]:return result
    a,b=m["flow_before"],m["flow_after"]
    if a[:2]!=[1,1] or b[:2]!=[1,1]:return result
    result["status"]="invalid" if any(a[3:]+b[3:]) else "observed"
    if result["status"]=="observed":
        result["bypassed"]=(b[2]-a[2])&0xffffffff
        # Endpoint scope encloses all successful timed clocks. Transfer failures
        # are uncertain delivery, not evidence that the master failed to bypass.
        w=case["request_window"]
        if result["clock_only"] and result["bypassed"]<max(0,w["clock_requests"]-case["errors"]["transfer"]):
            result["status"]="invalid";result["bypassed"]=None
    return result


def window_counts(case):
    w=case["request_window"]
    active=case["profile"]["mode"] in ("owner_pipe","owner_flow")
    require(type(w["active"]) is bool and w["active"]==active,"invalid request window mode")
    counts(w,"limit retry_us retry_limit new_requests retry_requests clock_requests retry_exhausted pending high_water")
    timing(w["reply_age"])
    if active:
        retry=case["profile"]["retry_us"] if case["schema"] in RETRY_SCHEMAS else 5000
        require((w["limit"],w["retry_us"],w["retry_limit"])==(4,retry,8),"invalid request window policy")
        require(0<=w["pending"]<=w["high_water"]<=4 and w["high_water"]<=w["new_requests"],"invalid pending window")
        require((w["high_water"]==0)==(w["new_requests"]==0) and
                (w["new_requests"]>0 or w["retry_requests"]==w["clock_requests"]==w["retry_exhausted"]==0),"request activity lacks window occupancy")
        require(w["retry_requests"]<=8*w["new_requests"] and
                (w["retry_exhausted"]==0 or w["retry_requests"]>=8),"invalid retry budget")
        require(w["new_requests"]+w["retry_requests"]+w["clock_requests"]==case["slots"],"request dispatch accounting mismatch")
        require(w["new_requests"]==w["reply_age"]["count"]+w["pending"],"request completion accounting mismatch")
        require(w["reply_age"]["count"]<=case["valid_responses"] and w["retry_exhausted"]<=1,"invalid reply accounting")
        require(w["retry_exhausted"]==0 or case["outcome"]=="failed","exhausted retry reported successful")
    else:
        require(all(w[k]==0 for k in ("limit","retry_us","retry_limit","new_requests","retry_requests","clock_requests","retry_exhausted","pending","high_water")) and w["reply_age"]["count"]==0,"inactive request window has observations")


def execution_counts(case):
    e = case["execution"]
    counts(e, "adc_mask adc_core cycle_us owner_core window_started_us window_ended_us")
    require(1 <= e["adc_mask"] <= 3 and e["adc_core"] in (0, 1) and e["owner_core"] in (0, 1) and
            (e["cycle_us"] == 0 or 1500 <= e["cycle_us"] <= 20000), "invalid execution profile")
    mode = case["profile"]["mode"]
    require(mode in ("owner", "workers", *ROW_OWNER_MODES) or (e["adc_mask"], e["adc_core"], e["cycle_us"]) == (3, 0, 0),
            "execution overrides require owner/workers mode")
    require(mode not in ("owner", *ROW_OWNER_MODES) or e["adc_core"] == e["owner_core"], "owner core mismatch")
    require(e["window_ended_us"] >= e["window_started_us"] and
            (e["window_started_us"] > 0 or e["window_ended_us"] == 0), "invalid traffic window")
    span=e["window_ended_us"]-e["window_started_us"]
    require(span >= case["elapsed_us"], "traffic window does not bracket elapsed time")
    if case["outcome"] == "complete":
        require(e["window_started_us"] > 0 and e["window_ended_us"] > e["window_started_us"], "missing traffic window")
    require(isinstance(e["traffic"], list) and len(e["traffic"]) <= 8, "invalid traffic entries")
    seen = set()
    bus = {p["cs"]:p for p in case["spi"]}
    for p in e["traffic"]:
        counts(p, "core_mask transfers lock_failures")
        require(type(p["cs"]) is int and p["cs"] in bus and p["cs"] not in seen and
                1 <= p["core_mask"] <= 3, "invalid traffic participant/core")
        seen.add(p["cs"])
        require(p["transfers"] <= bus[p["cs"]]["transfers"] and
                p["lock_failures"] <= bus[p["cs"]]["lock_failures"], "traffic exceeds all-scope counters")
        ops = p["operations"]
        require(isinstance(ops, list) and len(ops) == 3 and all(type(n) is int and n >= 0 for n in ops) and
                sum(ops) <= p["transfers"], "invalid traffic operations")
        if p["cs"] in (47, 21):
            adc = (47, 21).index(p["cs"])
            require(e["adc_mask"] & (1 << adc), "disabled ADC has timed traffic")
            core = e["adc_core"] if mode in ("adc", "mixed", "workers") else e["owner_core"]
            require(p["core_mask"] == 1 << core, "unexpected ADC execution core")
            if e["cycle_us"]:
                # Allow conversions already in progress at either window edge.
                require(ops[2] <= span // e["cycle_us"] + 2, "paced reads exceed minimum cycle interval")
        elif p["cs"] == 40:
            require(p["core_mask"] == 1 << e["owner_core"], "unexpected master execution core")
    if mode in ("owner", "workers", *ROW_OWNER_MODES) and case["outcome"] == "complete":
        by_cs = {p["cs"]:p for p in e["traffic"]}
        require(all(by_cs.get(cs, {}).get("operations", [0,0,0])[2] > 0
                    for adc,cs in enumerate((47,21)) if e["adc_mask"] & (1 << adc)), "missing timed ADC reads")
    require(case["diagnostics"]["sequence"]["worker_start_requested"] == (mode in ("adc", "mixed", "workers") and
            case["reason"] not in ("analog_rail_fault", "master_entry_failed")) or case["outcome"] == "failed",
            "execution worker-start mismatch")


def execution_report(case):
    e = case["execution"]
    seconds = (e["window_ended_us"] - e["window_started_us"]) / 1e6
    return {**e, "scope": "completion-counter observations between startup and STOP; boundary transactions may straddle window; core masks observed in caller tasks",
            "traffic_rates": [{**p, "transfers_per_second":p["transfers"] / seconds if seconds else None,
                               "reads_per_second":p["operations"][2] / seconds if seconds else None}
                              for p in e["traffic"]], "rate_matching": "compare observed rates; requested cycle_us is a minimum interval, not achieved-rate proof"}


def row_counts(case):
    p=case["row_publication"]
    active=case["profile"]["mode"] in ROW_OWNER_MODES
    require(type(p["active"]) is bool and p["active"] == active and p["sink"] == "bounded_ram", "invalid row sink")
    counts(p,"published valid_both fresh_both digest deadline_guard_us master_deferrals")
    require(p["digest"] <= 4294967295 and p["fresh_both"] <= p["valid_both"] <= p["published"], "invalid row publication counts")
    require(p["published"] == (case["rows"] if active else 0) and p["deadline_guard_us"] == (800 if active else 0), "row count/guard mismatch")
    timing(p["lag"])
    require(p["lag"]["count"] == p["published"], "row lag count mismatch")
    require(isinstance(p["read_gap"],list) and len(p["read_gap"])==2,"invalid owner read gaps")
    for t in p["read_gap"]:timing(t)
    require(isinstance(p["samples"],list) and len(p["samples"])==min(4,p["published"]),"missing row prefix")
    require((p["last"] is None) == (p["published"]==0),"missing last row")
    if active:
        e=case["execution"]
        require((e["adc_mask"],e["cycle_us"])==(3,0),"row owner requires both unpaced ADCs")
        for field, key in (("valid_both","no_sample"),("fresh_both","fresh")):
            n=[case["rows"]-a[key] if key=="no_sample" else a[key] for a in case["adc"]]
            require(max(0,sum(n)-case["rows"]) <= p[field] <= min(n),"row intersection counters inconsistent")
    elif p["published"] or p["valid_both"] or p["fresh_both"] or p["master_deferrals"] or any(t["count"] for t in p["read_gap"]):
        raise ValueError("inactive row publication contains observations")
    samples=p["samples"]+([p["last"]] if p["last"] is not None else [])
    for i,r in enumerate(samples):
        counts(r,"index scheduled_us published_us valid_mask fresh_mask")
        require(r["index"] == (i+1 if i<len(p["samples"]) else p["published"]),"invalid published row index")
        require(0 <= r["fresh_mask"] <= 3 and 0 <= r["valid_mask"] <= 3 and
                r["fresh_mask"] & ~r["valid_mask"] == 0,"invalid row validity/freshness")
        require(case["execution"]["window_started_us"] <= r["scheduled_us"] <= r["published_us"] <= case["execution"]["window_ended_us"],"row outside observed window")
        require(r["published_us"]-r["scheduled_us"] <= p["lag"]["max_us"],"row lag exceeds summary")
        require(isinstance(r["counts"],list) and len(r["counts"])==2 and all(type(v) is int and -2147483648<=v<=2147483647 for v in r["counts"]),"invalid published ADC values")
        require(isinstance(r["conversion"],list) and len(r["conversion"])==2 and all(type(v) is int and 0<=v<=4294967295 for v in r["conversion"]),"invalid row conversion identity")
        require(all(r["conversion"][j]>0 for j in range(2) if r["valid_mask"] & (1<<j)),"valid row lacks conversion identity")
        require(isinstance(r["acquired_us"],list) and len(r["acquired_us"])==2 and
                all(type(v) is int and 0<=v<=r["published_us"] for v in r["acquired_us"]),"invalid row acquisition timestamp")
    for previous,current in zip(p["samples"],p["samples"][1:]):
        require(current["scheduled_us"]>previous["scheduled_us"] and (current["scheduled_us"]-previous["scheduled_us"])%2000==0,"row schedule is not on 500Hz grid")
        for j in range(2):
            if previous["valid_mask"] & current["valid_mask"] & (1<<j):
                require(current["conversion"][j]>=previous["conversion"][j] and
                        bool(current["fresh_mask"] & (1<<j)) == (current["conversion"][j]!=previous["conversion"][j]),"fresh row reuses conversion identity")
    if p["published"] and p["published"]<=4:require(p["last"]==p["samples"][-1],"last row disagrees with prefix")
    if p["published"]>4:
        before,last=p["samples"][-1],p["last"]
        gap=last["scheduled_us"]-before["scheduled_us"]
        require(gap >= (last["index"]-before["index"])*2000 and gap%2000==0 and
                last["published_us"]>=before["published_us"],"last row breaks schedule/order")
        for j in range(2):
            if before["valid_mask"] & last["valid_mask"] & (1<<j):
                require(last["conversion"][j]>=before["conversion"][j] and
                        (not last["fresh_mask"] & (1<<j) or last["conversion"][j]>before["conversion"][j]),"last fresh row reuses earlier conversion")
                if last["conversion"][j]==before["conversion"][j]:
                    require(last["counts"][j]==before["counts"][j] and last["acquired_us"][j]==before["acquired_us"][j],"same conversion has different contents")
    audited=p["samples"]+([p["last"]] if p["published"]>4 else [])
    for mask,key in (("valid_mask","valid_both"),("fresh_mask","fresh_both")):
        good=sum(r[mask]==3 for r in audited)
        require(good <= p[key] and len(audited)-good <= p["published"]-p[key],"retained rows contradict totals")


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


def processing_report(case):
    result={"status":"unknown","crc_algorithm":None,"counter_deltas":None,"phases":None,
            "metadata_before":None,"metadata_after":None,
            "scope":"boot counter deltas span control snapshots, wider than the timed run; frame_crc nests in decode/encode and object_crc in command; software intervals include instrumentation/interrupts, not pure CPU or physical bounds"}
    if case["profile"]["mode"] in ADC_ONLY_MODES:
        result["status"]="not_applicable";return result
    m=case.get("master")
    if m is None or not m["processing_measured"]:return result
    a,b=m["processing_meta_before"],m["processing_meta_after"]
    result.update(metadata_before=a,metadata_after=b)
    if a[0]!=1 or b[0]!=1 or a[1] not in (0,1) or b[1] not in (0,1) or a[4]!=1 or b[4]!=1:return result
    if any(a[5:]) or any(b[5:]):return result
    if a[1]!=b[1] or not a[2] or a[2]!=b[2] or a[3] or b[3]:
        result["status"]="invalid";return result
    result["crc_algorithm"]=("bitwise","table")[a[1]]
    delta=[(y-x)&4294967295 for x,y in zip(m["processing_before"],m["processing_after"])]
    names=("decode","command","encode","frame_crc","object_crc")
    phases={name:{"calls":delta[2*i],"total_us":delta[2*i+1],
                  "mean_us":delta[2*i+1]/delta[2*i] if delta[2*i] else None} for i,name in enumerate(names)}
    result.update(counter_deltas=dict(zip((f"{n}_{suffix}" for n in names for suffix in ("calls","total_us")),delta)),phases=phases)
    result["status"]="observed" if all(phases[n]["calls"] for n in names[:4]) else "unknown"
    if any(not p["calls"] and p["total_us"] for p in phases.values()):result["status"]="invalid"
    if (phases["frame_crc"]["total_us"]>phases["decode"]["total_us"]+phases["encode"]["total_us"] or
        phases["frame_crc"]["calls"]>phases["decode"]["calls"]+phases["encode"]["calls"] or
        phases["object_crc"]["total_us"]>phases["command"]["total_us"] or
        phases["object_crc"]["calls"]>phases["command"]["calls"]):result["status"]="invalid"
    if result["status"]=="invalid":result["phases"]=None
    return result


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
    if case["profile"]["mode"] in ADC_ONLY_MODES:
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
        if not isinstance(item, dict) or item.get("schema") not in (SCHEMA, *DIAGNOSTIC_SCHEMAS):
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
        processing=processing_report(case) if case["schema"] in PROCESSING_SCHEMAS else None
        receive=receive_report(case) if case["schema"] in RECEIVE_SCHEMAS else None
        if receive and receive["status"]=="invalid":master="failed"
        elif receive and receive["status"]=="observed" and any(receive["counter_deltas"][n] for n in ("full_reply_ready","full_other")):master="failed"
        elif receive and receive["status"]=="unknown" and master=="clean":master="unknown"
        if processing and processing["status"] == "invalid":master="failed"
        elif processing and processing["status"] == "unknown" and master=="clean":master="unknown"
        flow=flow_report(case) if case["schema"] in FLOW_SCHEMAS else None
        trace=reply_trace_report(case) if case["schema"]==SCHEMA_V13 else None
        if trace and trace["status"]=="invalid":master="failed"
        if flow and flow["status"]=="invalid":master="failed"
        elif flow and flow["clock_only"] and flow["status"]!="observed" and master=="clean":master="unknown"
        observations = diagnostic_observations(case)
        if case["schema"] in DIAGNOSTIC_SCHEMAS and p["mode"] not in ADC_ONLY_MODES:
            if components["status"] == "invalid":
                master = "failed"
            elif master == "clean" and (components["status"] != "observed" or
                    case["slots"] == 0 or case["diagnostics"]["decode_counts"][0] == 0):
                master = "unknown"
        transport = "failed" if any(case["errors"][k] for k in ("transfer", "wire", "accept", "commands")) or (
            case["schema"] in DIAGNOSTIC_SCHEMAS and case["diagnostics"]["switch_failures"]) else "clean"
        if case["schema"] in INTEGRITY_SCHEMAS and any(case["diagnostics"]["sequence"][k] for k in ("failures", "timeouts")):
            transport = "failed"
        baseline_mode="owner_adc" if p["mode"] in ROW_OWNER_MODES else "adc"
        baselines = [c for c in cases if c["profile"]["mode"] == baseline_mode and
                     c["schema"] == case["schema"] and
                     c["artifacts"] == case["artifacts"] and
                     c["profile"]["nodes"] == p["nodes"] and
                     c["profile"]["duration_ms"] == p["duration_ms"]]
        baseline = baseline_status(baselines)
        duration_status = "incomplete" if case["outcome"] != "complete" else "late" if (
            case["elapsed_us"] > p["duration_ms"] * 1000 + 2000) else "short" if (
            case["elapsed_us"] < p["duration_ms"] * 1000 - 2000) else "observed"
        failed = case["outcome"] != "complete" or case.get("workers_stopped") is False or adc == "failed" or transport == "failed" or (
            p["mode"] not in ADC_ONLY_MODES and master == "failed") or (p["mode"] in ("mixed","owner_rows","owner_pipe","owner_flow") and baseline == "failed") or duration_status != "observed"
        clean_candidate = not failed and manifest is not None and case.get("workers_stopped") is True and (
            p["mode"] in ADC_ONLY_MODES or (master == "clean" and case["accepted_bytes"] > 0)) and (
            p["mode"] != "mixed" or baseline == "healthy") and (
            case["schema"] not in DIAGNOSTIC_SCHEMAS or observations in ("observed", "not_applicable"))
        control = case["schema"] in DIAGNOSTIC_SCHEMAS and (p["mode"] in ("switch", "shape", "selected", "owner", "workers", *ROW_OWNER_MODES) or
                  p["crc_mode"] == "cached" or p["start_interval_us"] > 0)
        result.append({"case_id": case["case_id"],
            **({"row_publication": case["row_publication"],
                "row_freshness_status": ("incomplete" if case["outcome"]=="stopped" else "failed" if case["outcome"]!="complete" else adc) if p["mode"] in ROW_OWNER_MODES else "not_applicable",
                "owner_adc_timing_scope": "config/start/wait/read/total summaries cover synchronous warmup only; acquire_ok includes timed reads; use traffic window/read_gap/cache_age/row_lag for active run" if p["mode"] in ROW_OWNER_MODES else "not_applicable",
                "master_receive_pressure": "not_applicable" if p["mode"] in ADC_ONLY_MODES else
                    "unknown" if adapter_delta is None else "drops_observed" if adapter_delta[1] else "no_spi_drops_observed"} if case["schema"] in ROW_SCHEMAS else {}),
            **({"master_processing_components":processing} if processing is not None else {}),
            **({"logger_cost":logger_cost_report(case)} if case["schema"] in COST_SCHEMAS else {}),
            **({"master_receive_turnover":receive} if receive is not None else {}),
            **({"master_flow_control":flow} if flow is not None else {}),
            **({"master_reply_trace":trace} if trace is not None else {}),
            **({"request_window": case["request_window"]} if case["schema"] in WINDOW_SCHEMAS else {}),
            **({"execution_control": execution_report(case)} if case["schema"] in EXECUTION_SCHEMAS else {}),
            "profile": p, "outcome": case["outcome"], "reason": case["reason"],
            "duration_status": duration_status,
            "scheduled_rows_target": min(case["elapsed_us"], p["duration_ms"] * 1000) * 500 / 1000000 if p["mode"] in ("adc", "mixed", *ROW_OWNER_MODES) else None,
            "accepted_bytes_per_second": case["accepted_bytes"] / seconds if seconds else None,
            "retired_bytes_per_second": case["retired_objects"] * 1008 / seconds if seconds else None,
            "pending_ack_objects": case["unique_objects"] - case["retired_objects"],
            "useful_data_status": "not_applicable" if p["mode"] in ADC_ONLY_MODES else "observed" if case["accepted_bytes"] else "none",
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
                "sequential_control": case["diagnostics"]["sequence"]} if case["schema"] in INTEGRITY_SCHEMAS else {}),
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
    return {"schema": "bodaqs.spi-probe-report.v13" if any(c["schema"]==SCHEMA_V13 for c in cases) else "bodaqs.spi-probe-report.v11" if any(c["schema"]==SCHEMA_V11 for c in cases) else "bodaqs.spi-probe-report.v10" if any(c["schema"]==SCHEMA_V10 for c in cases) else "bodaqs.spi-probe-report.v9" if any(c["schema"] == SCHEMA_V9 for c in cases) else "bodaqs.spi-probe-report.v8" if any(c["schema"] == SCHEMA_V8 for c in cases) else "bodaqs.spi-probe-report.v7" if any(c["schema"] == SCHEMA_V7 for c in cases) else "bodaqs.spi-probe-report.v6" if any(c["schema"] == SCHEMA_V6 for c in cases) else "bodaqs.spi-probe-report.v5" if any(c["schema"] == SCHEMA_V5 for c in cases) else "bodaqs.spi-probe-report.v4" if any(c["schema"] in EXECUTION_SCHEMAS for c in cases) else "bodaqs.spi-probe-report.v3" if any(c["schema"] in INTEGRITY_SCHEMAS for c in cases) else "bodaqs.spi-probe-report.v2" if any(c["schema"] in DIAGNOSTIC_SCHEMAS for c in cases) else "bodaqs.spi-probe-report.v1",
            "capture_sha256": digest,
            "run_identity": "declared_paired" if manifest else "unknown_without_manifest",
            "manifest": manifest, "serial_events": events,
            "comparison": comparisons(cases),
            "production_qualified": False,
            "t01_go": False, "admission_authorized": False,
            "baseline_status": baseline_status([c for c in cases if c["profile"]["mode"] in ADC_ONLY_MODES]),
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
