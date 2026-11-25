"""Offline evidence for the restricted first recording; never an admission policy."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .can_imu_packets import read_can_imu_packets, SCHEMA
from .io_bdq import read_bdq


def assess_first_imu_recording(path: str | Path) -> tuple[dict, dict]:
    """Return a report plus independently decoded readings/raw observations.

    Completion, delivery, identity and timing are separate results. This examines
    file evidence only: sustained queue health and physical configuration still
    need the operator's observations, and no sample time is reconstructed.
    """
    info = read_bdq(path)
    descriptors = info.stream_catalog.get("streams", [])
    samples = [d for d in descriptors if d.get("acquisition", {}).get("payload_schema") == SCHEMA]
    if len(samples) != 1:
        raise ValueError("requires exactly one compact CAN IMU stream")
    return _assess_imu_stream(path, info, samples[0])


def _assess_imu_stream(path, info, descriptor):
    """Shared strict per-source assessment; caller supplies a validated catalog entry."""
    decoded = read_can_imu_packets(path, descriptor["stream_key"])
    source = decoded["source"]
    required = ("provider_uid", "node_boot", "master_boot", "recording_id", "control_session", "measurement_context")
    def exact_identity(value,bits):
        if isinstance(value,str):
            if not value.isascii() or not value.isdecimal():return False
            value=int(value)
        elif type(value) is not int or bits==64 and value>2**53-1:return False
        return 0<value<2**bits
    identity = all(exact_identity(source.get(key),32 if key=="node_boot" else 64) for key in required)
    effective = source.get("effective_descriptor_hex", "")
    try:
        image = bytes.fromhex(effective)
        u32 = lambda offset: int.from_bytes(image[offset:offset+4], "little")
        configuration = (len(image)==192 and image[0]==3 and image[2]==1 and image[4]==2 and image[5]==3
                         and int.from_bytes(image[42:44],"little")==1
                         and (u32(48),u32(52),u32(56),u32(60),u32(64),u32(68))==
                         ({1:3333,2:1667,3:833}.get(int.from_bytes(image[40:42],"little"),0),1,
                          {1:3333,2:1667,3:833}.get(int.from_bytes(image[40:42],"little"),0),1,32000,2000000)
                         and int.from_bytes(image[40:42],"little") in (1,2,3))
    except ValueError:
        configuration = False
    evidence = decoded["raw_timing_observations"]
    boundaries = [r for r in evidence if r["boundary_event_kind"]]
    starts = [r for r in boundaries if r["boundary_event_kind"] == 2]
    stops = [r for r in boundaries if r["boundary_event_kind"] == 8 and r["boundary_validity_flags"] & 1]
    segments = sorted({r["source_segment_id"] for r in decoded["readings"]})
    terminal = {r["source_segment_id"]: r["related_sequence"] for r in stops}
    gaps = list(decoded["gaps"])
    # The shared decoder owns internal and source-bounded terminal gaps.
    sequence_known = bool(decoded["readings"]) and not decoded["ambiguous_packets"]
    started = {r["source_segment_id"] for r in starts if r["boundary_validity_flags"] & 1}
    complete_bounds = bool(segments) and all(segment in terminal and segment in started for segment in segments)
    summary = info.final_summary
    node = source.get("node_address")
    windows = [r for r in summary.get("remote_tail_windows", []) if r.get("node") == node]
    confirmed_tail = (len(windows) == 1 and windows[0].get("cessation_status") == "confirmed_stop"
                      and windows[0].get("drain_basis") == "stop_confirmation_observed_plus_5s"
                      and windows[0].get("source_final_observed") is True
                      and ((windows[0].get("drain_closed_ms", 0)-windows[0].get("stop_confirmed_ms", 0)) & 0xffffffff) >= 5000)
    if confirmed_tail:
        confirmed_tail = (len(terminal)==1 and windows[0].get("final_sequence") == next(iter(terminal.values()))
                          and windows[0].get("stream_epoch") == stops[-1]["stream_epoch"])
    clean_file = summary.get("clean_shutdown") is True and not info.detected_errors
    cleanup = summary.get("remote_cleanup_complete") is True
    sample_discard = summary.get("remote_sample_tail_discarded") is True
    lost_counts = {key: sum(r[key] for r in evidence) for key in
                   ("source_loss_delta", "evidence_loss_delta", "capture_loss_delta")}
    source_fault = lost_counts["source_loss_delta"]>5 or lost_counts["capture_loss_delta"]>5 or summary.get("remote_imu_excluded") is True or bool(summary.get("primary_samples_dropped", 0))
    integrity = identity and configuration and sequence_known and not info.detected_errors
    no_sample_loss = not lost_counts["source_loss_delta"] and not lost_counts["capture_loss_delta"]
    complete = no_sample_loss and integrity and complete_bounds and not gaps and confirmed_tail and clean_file and cleanup and not sample_discard and not source_fault
    isolated_gap = len(gaps) == 1 and gaps[0].get("extent") == "known" and gaps[0].get("count") == 5
    gap_loss_reconciled = all(lost_counts[key] in (0,5) for key in ("source_loss_delta","capture_loss_delta"))
    eligible_warning = gap_loss_reconciled and integrity and complete_bounds and isolated_gap and confirmed_tail and clean_file and cleanup and not sample_discard and not source_fault
    outcome = "complete_delivery" if complete else "isolated_five_sample_gap_warning" if eligible_warning else "incomplete_or_unresolved"
    raw = [r for r in evidence if r["kind"] == 1]
    required_raw = sum(1 << bit for bit in (0,1,2,4,5,6,21))
    final_raw = [r for r in raw
                 if terminal.get(r["source_segment_id"]) == r["related_sequence"]
                 and r["validity_mask"] & required_raw == required_raw
                 and r["snapshot_flags"] & 7 == 7
                 and r["snapshot_presence"] & 0xd8 == 0xd8
                 and r["node_boot"] == source.get("node_boot")
                 and r["sensor_clock_epoch"] and r["node_clock_epoch"]
                 and any(stop["source_segment_id"]==r["source_segment_id"] and stop["stream_epoch"]==r["stream_epoch"] for stop in stops)]
    report = {
        "schema": "bodaqs.first_imu_recording_report.v1", "file": str(path),
        "file_outcome": outcome, "file_cleanly_closed": clean_file,
        "cleanup_complete": cleanup, "confirmed_stop_and_drain": confirmed_tail,
        "full_sequence_identity": sequence_known, "source_identity_present": identity,
        "effective_configuration_present": configuration, "source": source,
        "sample_count": len(decoded["readings"]), "packet_count": decoded["packet_count"],
        "segments": segments, "terminal_sequences": terminal, "gaps": gaps,
        "duplicates": decoded["duplicates"], "ambiguous_packets": decoded["ambiguous_packets"],
        "sample_tail_discarded": sample_discard, "loss_observations": lost_counts,
        "sample_loss_reconciled": no_sample_loss if not gaps else isolated_gap and gap_loss_reconciled,
        "raw_snapshot_count": len(raw), "final_sample_raw_observation_present": bool(final_raw),
        "raw_kind_counts": dict(Counter(str(r["kind"]) for r in evidence)),
        "file_errors": list(info.detected_errors), "final_summary": summary,
        "timing_status": "unreconstructed", "capacity_qualification": "unqualified",
        "physical_capture_status": "operator_review_required",
        "operator_review": ["one IMU, ADC and unrelated sensors disabled", "matched candidate images/configuration",
                            "approximately 30 seconds acquired", "no persistent queue growth or repeated overload"],
    }
    # Independent verdicts retain the strict legacy outcome above. Footer closure
    # alone cannot prove source delivery; observed loss categories may overlap.
    starts_by_segment={r["source_segment_id"]:r["related_sequence"] for r in starts if r["boundary_validity_flags"]&1}
    metric_segments=set(segments)|set(starts_by_segment)|set(terminal)
    bounded=bool(metric_segments) and identity and sequence_known and not info.detected_errors and all(
        s in terminal and s in starts_by_segment and terminal[s]>=starts_by_segment[s] for s in metric_segments)
    # Include a source-bounded segment even when every sample in it was lost.
    expected=sum(terminal[s]-starts_by_segment[s]+1 for s in metric_segments) if bounded else None
    unique={(r["source_segment_id"],r["sequence"]) for r in decoded["readings"] if r["sequence"] is not None}
    if bounded and any(s not in terminal or not starts_by_segment[s]<=seq<=terminal[s] for s,seq in unique):
        bounded=False;expected=None
    missing=expected-len(unique) if bounded else None
    report["verdicts"]={
        "file_integrity":not bool(info.detected_errors),"footer_closed":clean_file,
        "control_stop":len(windows)==1 and windows[0].get("cessation_status")=="confirmed_stop",
        "cleanup":cleanup,"source_terminal_boundary":complete_bounds,
        "sample_identity":sequence_known and identity,"source_loss_observed":lost_counts["source_loss_delta"]>0,
        "capture_loss_observed":lost_counts["capture_loss_delta"]>0,
        "evidence_loss_observed":lost_counts["evidence_loss_delta"]>0,
        "physical_qualification":"unqualified",
    }
    report["metrics"]={"sample_delivery":{
        "unit":"samples","window":"source_START_to_inclusive_source_STOP" if bounded else "observed_prefix",
        "baseline":starts_by_segment,"endpoints":terminal,"denominator":expected,
        "unique_received":len(unique),"missing":missing,
        "whole_run_missing_percent":100*missing/expected if expected else None,
        "unresolved_readings":sum(r["sequence"] is None for r in decoded["readings"]),
    },"loss_observations":{
        "unit":"reported_loss_count","window":"stored_timing_observations",
        "baseline":None,"denominator":None,"categories":lost_counts,
        "additive_unique_sample_loss":False,
    }}
    return report, decoded
