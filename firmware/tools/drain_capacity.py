"""Offline feasibility model; never supplies a production admission profile.

Public seams: bench_accounting(snapshot), evaluate(workload, costs), and the
JSON command line. Units are explicit in keys. No device or network access.
"""
from __future__ import annotations

import math
import argparse
import hashlib
import json
from pathlib import Path


WORKLOAD_DEFAULTS = {
    "batch_records": 13, "publication_turns": 2,
    "observation_hz": 1, "observation_bytes": 32, "adc_workers_sps": [],
    "adc_spi_hz": 1000000, "spi_burst_slots": 128, "can_burst_frames": 64,
    "packet_record_bytes": 112, "observation_record_bytes": 128,
    "local_bytes_s": 6000, "storage_bytes_s": 500000,
    "logger_free_bytes": 1600000, "master_bank0_extra_bytes": 2048,
    "master_bank1_extra_bytes": 0, "node_extra_bytes": 1024,
    "primary_queue_bytes": 49152,
    "packet_formation_us": 1500, "node_fifo_service_us": 10000,
    "batch_seal_us": 20000, "normal_scheduler_gap_us": 10000,
}
COST_DEFAULTS = {
    "encode_us": 5, "master_request_us": 100, "retirement_us": 5,
    "publication_us": 5, "adc_software_us_per_transaction": 5,
    "adc_attempts_per_conversion": 1.05, "retry_fraction": .05,
    "guard_nonoverlap_us": 0, "master_can_us": 40,
    "master_batch_us": 30, "storage_encode_us_per_byte": .05,
    "logger_background_fraction": .02, "mutex_hold_us": 64,
    "worker_pause_us_per_eight_services": 0,
}


def evaluate(workload: dict, costs: dict) -> dict:
    """Return a design report. A numeric pass is conditional, never admission."""
    if set(workload) - ({"nodes"} | set(WORKLOAD_DEFAULTS)):
        raise ValueError("unknown workload field")
    if set(costs) - ({"exchange_us"} | set(COST_DEFAULTS)):
        raise ValueError("unknown cost field")
    workload = WORKLOAD_DEFAULTS | workload
    workload["adc_workers_sps"] = list(workload["adc_workers_sps"])
    costs = COST_DEFAULTS | costs
    for key, value in (workload | costs).items():
        values = value if key == "adc_workers_sps" else [value]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
            raise ValueError(f"{key} must contain finite nonnegative numbers")
    if workload["nodes"] not in range(1, 5) or workload["batch_records"] not in range(1, 14):
        raise ValueError("one to four nodes and one to thirteen records required")
    if costs["exchange_us"] < 64 or workload["adc_spi_hz"] <= 0:
        raise ValueError("64us minimum wire exchange; positive ADC clock required")
    if len(workload["adc_workers_sps"]) > 2 or any(v > 2000 for v in workload["adc_workers_sps"]):
        raise ValueError("at most two ADC workers, each at most2000sps")
    if workload["publication_turns"] < 1 or workload["observation_hz"] <= 0 or workload["observation_bytes"] <= 0:
        raise ValueError("publication and periodic observations cannot be omitted")
    if workload["packet_record_bytes"] < 80 or workload["observation_record_bytes"] < workload["observation_bytes"]:
        raise ValueError("record allocation cannot discard payload or identity")
    if costs["adc_attempts_per_conversion"] < 1:
        raise ValueError("each conversion requires at least one attempt")
    if costs["mutex_hold_us"] < 64 or costs["mutex_hold_us"] > costs["exchange_us"]:
        raise ValueError("mutex hold must cover wire time and fit exchange")
    nodes = workload["nodes"]
    samples_s = nodes * 3333
    records = workload.get("batch_records", 13)
    fragments = math.ceil((20 + 76 * records) / 40)
    batches_s = samples_s / (5 * records)
    fragments_s = batches_s * fragments
    catchup = fragments_s * 1.25
    exchange_us = costs["exchange_us"]
    encode_us = costs.get("encode_us", 5)
    request_interval = 64 + costs.get("master_request_us", 100) + costs.get("retirement_us", 5) + costs.get("publication_us", 5)
    observation_hz = workload.get("observation_hz", 1)
    observation_frames = math.ceil(workload.get("observation_bytes", 32) / 64)
    authorization_frames = nodes * 4  # fresh challenge and renew request/reply
    # Explicit conservative recurring ceilings; raw observations replace the
    # old snapshot/model/anchor set, while clock bridge and SYNC are retained.
    traffic = {
        "authorization": nodes * 16,
        "raw_observations": nodes * observation_hz * observation_frames * 4,
        "node_sync": nodes * 10 * 4,
        "master_sync": 10 * 4,
        "status": nodes * 4,
        "clock_bridge_with_retries": 50 * 2,
        "loss_and_recovery": nodes * 44 * 4,
        "management_loss_reports": nodes * 80,
        "empty_probes": nodes * 50,
        "diagnostics": 32,
    }
    auxiliary = sum(traffic.values())
    # One selected head/node: ACK may fetch the successor but cannot make its
    # immutable contents physically available in the transaction carrying ACK.
    # Additional publication turns are explicit, not hidden in useful fragments.
    publication_turns = workload.get("publication_turns", 2)
    partial_seals_s = nodes * (observation_hz * observation_frames + 10 + 1 + 44)
    partial_slots = partial_seals_s * 3  # conservative extra rounding/selection
    sample_slots = fragments_s + batches_s * publication_turns + partial_slots
    adc_conversions = sum(workload["adc_workers_sps"])
    adc_wire = adc_conversions * 80 / workload["adc_spi_hz"]
    adc_scheduling = adc_conversions * costs["adc_attempts_per_conversion"] * (80 / workload["adc_spi_hz"] + 3 * costs["adc_software_us_per_transaction"] / 1e6)
    retry = 1 + costs["retry_fraction"]
    catchup_slots = ((fragments_s + batches_s * publication_turns) * 1.25 + partial_slots + auxiliary) * retry
    steady_slots = (sample_slots + auxiliary) * retry
    slot_cost = exchange_us + encode_us + costs["guard_nonoverlap_us"]
    steady_spi = steady_slots * slot_cost / 1e6 + adc_scheduling
    catchup_spi = catchup_slots * slot_cost / 1e6 + adc_scheduling
    request_fraction = catchup_slots * request_interval / 1e6
    worker_interval = slot_cost + costs["worker_pause_us_per_eight_services"] / 8
    worker_fraction = catchup_slots * worker_interval / 1e6
    failed = []
    if costs["mutex_hold_us"] > 100:
        failed.append("mutex_hold")
    if catchup_spi > .85:
        failed.append("catchup_spi")
    if request_fraction > 1:
        failed.append("request_capacity")
    if worker_fraction > 1:
        failed.append("worker_pacing")
    if steady_spi + workload["spi_burst_slots"] * slot_cost / 1e6 > .85:
        failed.append("steady_spi_and_burst")
    can_frames = samples_s / 5 + nodes * (4 + 10 + 1 + observation_hz * observation_frames + 44) + 10 + 8
    can_fraction = can_frames * 196.25 / 1e6
    # Conditional fluid-service envelope: available shared SPI and serial-safe
    # request acceptance and paced worker each constrain useful turns. This
    # assumes schedulable service, not a measured latency bound. An exceptional
    # backlog drains after steady traffic; fixed mandatory/partial traffic also
    # competes with the selected batches used in the delivery sensitivity.
    service_slots_s = min(max(0, 1 - adc_scheduling) * 1e6 / slot_cost,
                          1e6 / request_interval, 1e6 / worker_interval)
    fixed_turns = (partial_slots + auxiliary) * retry
    batch_service_slots_s = max(0, service_slots_s - fixed_turns)
    burst_service_slots_s = max(0, service_slots_s - steady_slots)
    spi_burst = (workload["spi_burst_slots"] * 1e6 / burst_service_slots_s
                 if burst_service_slots_s else None)
    can_burst = workload.get("can_burst_frames", 64) * 196.25
    # Candidate compact packet records retain complete CAN contents and identity;
    # payload layout is not implemented. 112/128-byte allocations are assumptions.
    packet_bytes = workload.get("packet_record_bytes", 112)
    observation_record_bytes = workload.get("observation_record_bytes", 128)
    evidence_s = nodes * (observation_hz * observation_frames + 10 + 1 + 44 + 4) + 10 + 50 + 8
    local_bytes_s = workload.get("local_bytes_s", 6000)
    persistence = (samples_s / 5 * packet_bytes + evidence_s * observation_record_bytes + local_bytes_s) * 1.02
    node_backlog = math.ceil(3333 / 5 * .05)
    node_packets = node_backlog + 4 + 8 + 4
    master_packets = math.ceil(3333 / 5 * .1) + node_backlog + 13 + 2 + 4
    logger_packets = math.ceil(3333 / 5) + 64 + 128 + 13 + 1 + 128 + 4
    logger_evidence = math.ceil(evidence_s / nodes) + 64 + 128 + 13 + 1 + 128 + 8
    logger_bytes = nodes * (1024 * packet_bytes + 512 * observation_record_bytes) + math.ceil(local_bytes_s) + 32768 + workload["primary_queue_bytes"] + 8192 + 16384 + 23936
    bank0_extra = workload.get("master_bank0_extra_bytes", 2048)
    bank1_extra = workload.get("master_bank1_extra_bytes", 0)
    memory = {
        "node_packets_required": node_packets,
        "node_packets_allocated": 64,
        "node_sample_queue_bytes": 64 * 68,
        "node_banks": {"SRAM": {"capacity": 32768, "baseline_used": 13185,
                                   "candidate_extra": workload.get("node_extra_bytes", 1024)}},
        "master_packets_per_node_required": master_packets,
        "master_packets_per_node_allocated": 128,
        "master_fixed_retention_bytes": 4 * (128 * 92 + 1024),
        "master_banks": {
            "BANK0": {"capacity": 65536, "baseline_used": 62723, "candidate_extra": bank0_extra},
            "BANK1": {"capacity": 65536, "baseline_used": 0, "candidate_extra": bank1_extra},
        },
        "logger_packets_per_node_required": logger_packets,
        "logger_packets_per_node_allocated": 1024,
        "logger_evidence_per_node_required": logger_evidence,
        "logger_evidence_per_node_allocated": 512,
        "logger_existing_transport_bytes": 23936,
        "logger_required_bytes": logger_bytes,
        "logger_available_bytes": workload.get("logger_free_bytes", 1600000),
        "placement_and_stack_qualified": False,
    }
    for banks in (memory["master_banks"], memory["node_banks"]):
        for bank in banks.values():
            bank["remaining"] = bank["capacity"] - bank["baseline_used"] - bank["candidate_extra"]
    if can_fraction + can_burst / 1e6 > .70:
        failed.append("can")
    if logger_bytes > memory["logger_available_bytes"]:
        failed.append("logger_memory")
    if any(b["remaining"] < 0 for b in memory["master_banks"].values()):
        failed.append("master_memory")
    if any(b["remaining"] < 0 for b in memory["node_banks"].values()):
        failed.append("node_memory")
    if node_packets > 64 or master_packets > 128 or logger_packets > 1024 or logger_evidence > 512:
        failed.append("buffer_coverage")
    if persistence > workload.get("storage_bytes_s", 500000):
        failed.append("persistence")
    master_cpu = catchup_slots * costs["master_request_us"] / 1e6 + can_frames * costs["master_can_us"] / 1e6 + batches_s * 1.25 * costs["master_batch_us"] / 1e6
    logger_cpu = catchup_spi + persistence * costs["storage_encode_us_per_byte"] / 1e6 + costs["logger_background_fraction"]
    if master_cpu > 1:
        failed.append("master_cpu")
    if logger_cpu > 1:
        failed.append("logger_cpu")
    delivery = (sum(workload[k] for k in ("packet_formation_us", "node_fifo_service_us", "batch_seal_us", "normal_scheduler_gap_us"))
                + nodes * (fragments + publication_turns) * retry * 1e6 / batch_service_slots_s
                + spi_burst + can_burst
                if batch_service_slots_s and spi_burst is not None else None)
    if delivery is None or delivery > 100000:
        failed.append("delivery")
    if can_burst > 50000 or spi_burst is None or spi_burst > 100000:
        failed.append("burst_service_coverage")
    data_turns = (fragments_s + batches_s * publication_turns) * retry
    spi_ratio = max(0, (850000 - adc_scheduling * 1e6) / slot_cost - fixed_turns) / data_turns
    request_ratio = max(0, 1e6 / request_interval - fixed_turns) / data_turns
    master_data_cpu = data_turns * costs["master_request_us"] + batches_s * costs["master_batch_us"]
    master_ratio = max(0, 1e6 - fixed_turns * costs["master_request_us"] - can_frames * costs["master_can_us"]) / master_data_cpu if master_data_cpu else math.inf
    drain_ratio = min(spi_ratio, request_ratio, master_ratio)
    worker_ratio = max(0, 1e6 / worker_interval - fixed_turns) / data_turns
    drain_ratio = min(drain_ratio, worker_ratio)
    return {
        "sample_fragments_s": fragments_s,
        "sample_only_catchup_wire_fraction": catchup * 64 / 1e6,
        "catchup_sample_fragments_s": catchup,
        "catchup_sample_exchange_fraction": catchup * exchange_us / 1e6,
        "adc_wire_fraction": adc_wire,
        "adc_scheduling_fraction": adc_scheduling,
        "authorization_frames_s": authorization_frames,
        "authorization_horizon_s": 5,
        "auxiliary_slots_s": auxiliary,
        "traffic_slots_s": traffic,
        "sample_slots_s": sample_slots,
        "selected_batches_s": batches_s,
        "selected_batches_per_node": 1,
        "partial_seal_reserve_slots_s": partial_slots,
        "delivery_estimate_us": delivery if not failed else None,
        "delivery_estimate_applicable": not failed,
        "delivery_qualified": False,
        "delivery_interpretation": "conditional serialized envelope including simultaneous exceptional bursts; not a normal-operation or physical guarantee",
        "catchup_spi_fraction": catchup_spi,
        "request_interval_us": request_interval,
        "request_capacity_fraction": request_fraction,
        "request_capacity_interpretation": "serial-safe one-RX planning envelope; actual overlap/publication unmeasured",
        "worker_service_fraction": worker_fraction,
        "worker_service_interval_us": worker_interval,
        "steady_spi_fraction": steady_spi,
        "scheduled_slots_s": steady_slots,
        "catchup_scheduled_slots_s": catchup_slots,
        "master_cpu_fraction": master_cpu,
        "logger_cpu_fraction": logger_cpu,
        "slot_cost_us": slot_cost,
        "concurrent_drain_ratio": drain_ratio,
        "maximum_total_slot_us_for_catchup": max(0, .85 - adc_scheduling) * 1e6 / catchup_slots,
        "maximum_serial_request_interval_us": 1e6 / catchup_slots,
        "maximum_adc_conversions_s_for_catchup": max(0, .85 - catchup_slots * slot_cost / 1e6) / (costs["adc_attempts_per_conversion"] * (80 / workload["adc_spi_hz"] + 3 * costs["adc_software_us_per_transaction"] / 1e6)),
        "can_fraction": can_fraction,
        "can_frames_s": can_frames,
        "can_burst_recovery_us": can_burst,
        "spi_burst_recovery_us": spi_burst,
        "spi_burst_interpretation": "conditional recovery after steady traffic; null when no spare service; not a physical guarantee",
        "service_capacity_slots_s": service_slots_s,
        "batch_service_available_slots_s": batch_service_slots_s,
        "burst_service_available_slots_s": burst_service_slots_s,
        "persistence_bytes_s": persistence,
        "memory": memory,
        "effective_workload": workload,
        "effective_costs": costs,
        "evidence_class": "unqualified_planning_scenario",
        "failed_gates": failed,
        "decision": "no-go" if failed else "conditional",
        "production_admitted": False,
    }


def bench_accounting(snapshot: dict) -> dict:
    retired = sum(snapshot["data_acked_records"])
    retained = snapshot["retained_frames"] - retired
    return {
        "window_us": snapshot["elapsed_us"],
        "admitted_records": snapshot["retained_frames"],
        "retired_records": retired,
        "retained_records": retained,
        "selected_records": retained - sum(snapshot["ingress_depth"]),
        "mean_sample_batch_records": snapshot["data_records"][0] / snapshot["data_objects"][0],
        "non_data_polls": sum(snapshot["polls"][2:]),
        "unclassified_requests": snapshot["calls"][1] - sum(snapshot["polls"]) - sum(snapshot["acks"]),
        "repeated_sample_fragments": snapshot["fragments"][0] - snapshot["data_unique_fragments"][0],
        "steady_state_evidence": False,
    }


def build_report(config: dict, source_root: Path) -> dict:
    """Verify immutable source inputs and evaluate every named workload/cost pair."""
    for relative, expected in config["baseline"]["files"].items():
        path = (source_root / relative).resolve()
        if not path.is_relative_to(source_root.resolve()):
            raise ValueError(f"baseline path outside source root: {relative}")
        if not path.is_file():
            raise ValueError(f"baseline mismatch: {relative}")
        data = path.read_bytes()
        # Snapshot files and Git checkouts may differ only in text newlines.
        # Artifact hashes remain byte-exact metadata and are never normalized.
        hashes = {hashlib.sha256(data).hexdigest()}
        if config["baseline"].get("allow_crlf_to_lf", False):
            hashes.add(hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest())
        if expected not in hashes:
            raise ValueError(f"baseline mismatch: {relative}")
    cases = {
        f"{scenario}/{name}": evaluate(workload, costs)
        for scenario, costs in config["scenarios"].items()
        for name, workload in config["workloads"].items()
    }
    for name, case in cases.items():
        scenario = name.split("/", 1)[0]
        case["evidence_class"] = config.get("scenario_evidence", {}).get(scenario, "unverified_assumption")
    # Design progression needs a passing four-node case with defensible bounds;
    # physical admission still needs the later device qualification gates.
    covered_four = [name for name, case in cases.items()
                    if case["effective_workload"]["nodes"] == 4
                    and case["decision"] == "conditional"
                    and case["evidence_class"] == "defensible_feasibility_bounds"]
    frontier_go = bool(covered_four)
    return {
        "format": "bodaqs.drain_capacity.v1",
        "source_baseline_verified": True,
        "baseline": config["baseline"],
        "bench": bench_accounting(config["bench_snapshot"]) if "bench_snapshot" in config else None,
        "cases": cases,
        "frontier_decision": "go-for-dependent-design" if frontier_go else "no-go",
        "dependents_may_start": frontier_go,
        "four_node_cases_with_defensible_bounds": covered_four,
        "required_tradeoff": "reopen batching/pipelining or transaction/hardware/rate envelope, then rerun T01 before dependent implementation",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=Path("docs/firmware/drain-capacity/inputs.json"))
    parser.add_argument("--baseline", type=Path, default=Path("docs/firmware/drain-capacity/baseline.json"))
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, help="write deterministic JSON; otherwise stdout")
    args = parser.parse_args()
    config = json.loads(args.inputs.read_text(encoding="utf-8"))
    config["baseline"] = json.loads(args.baseline.read_text(encoding="utf-8"))
    encoded = json.dumps(build_report(config, args.source_root), indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
