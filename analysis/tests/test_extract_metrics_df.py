import pandas as pd
import numpy as np
from bodaqs_analysis import extract_metrics_df


def test_extract_metrics_df_contract():
    events_contract = pd.DataFrame({
        "event_id": ["shock_rebound:0", "shock_rebound:1"],
        "schema_id": ["shock_rebound", "shock_rebound"],
        "schema_version": ["1.0", "1.0"],
        "event_name": ["Rear shock rebound", "Rear shock rebound"],
        "signal": ["rear_shock_vel", "rear_shock_vel"],
        "trigger_time_s": [1.20, 3.20],
        "m_peak_vel": [2.1, 2.4],
        "m_duration": [0.5, 0.5],
    })

    metrics = extract_metrics_df(events_contract)
    forbidden = {"start_idx", "end_idx", "start_time_s", "end_time_s"}
    assert forbidden.isdisjoint(metrics.columns), f"Forbidden window columns leaked into metrics_df: {forbidden & set(metrics.columns)}"

    required = {
        # Required join key
        "event_id",
    
        # Recommended identity bundle (no window indices)
        "schema_id", "schema_version", "event_name", "signal", "trigger_time_s",
    
        # Metrics
        "m_peak_vel", "m_duration",
    }

    assert required.issubset(metrics.columns), f"Missing: {required - set(metrics.columns)}"
    assert len(metrics) == 2
    assert metrics["m_peak_vel"].iloc[0] == 2.1


def test_extract_metrics_df_legacy_projection_only():
    events_legacy = pd.DataFrame({
        "event_id": ["shock_rebound", "shock_rebound"],
        "event_type": ["local_extrema", "local_extrema"],
        "sensor": ["rear", "rear"],
        "t0_index": [120, 320],
        "t0_time": [1.20, 3.20],
        "start_index": [100, 300],
        "end_index": [150, 350],
        "m_peak_vel": [2.1, 2.4],
    })

    metrics = extract_metrics_df(events_legacy)

    required = {
        "event_id", "event_type", "sensor",
        "t0_index", "t0_time", "start_index", "end_index",
        "m_peak_vel",
    }
    assert required.issubset(metrics.columns), f"Missing: {required - set(metrics.columns)}"
    assert len(metrics) == 2
    assert metrics["m_peak_vel"].iloc[1] == 2.4

def test_extract_metrics_df_excludes_secondary_trigger_columns():
    """Secondary trigger columns belong to events_df only and must not leak."""
    events = pd.DataFrame({
        "event_id": ["e0"],
        "schema_id": ["rebounds"],
        "schema_version": ["1.0"],
        "event_name": ["Rebound"],
        "signal": ["vel"],
        "trigger_time_s": [1.2],
        "rebound_start_time_s": [1.1],
        "rebound_end_time_s": [1.3],
        "m_peak_vel": [2.1],
    })

    metrics = extract_metrics_df(events)

    forbidden = {
        "rebound_start_time_s",
        "rebound_end_time_s",
    }
    assert forbidden.isdisjoint(metrics.columns), (
        f"Secondary trigger columns leaked into metrics_df: "
        f"{forbidden & set(metrics.columns)}"
    )


def test_extract_metrics_df_keeps_trigger_datetime_if_present():
    """Real-time anchoring should survive projection if present."""
    events = pd.DataFrame({
        "event_id": ["e0"],
        "schema_id": ["rebounds"],
        "schema_version": ["1.0"],
        "event_name": ["Rebound"],
        "signal": ["vel"],
        "trigger_time_s": [1.2],
        "trigger_datetime": pd.to_datetime(["2025-01-01T00:00:01.200"]),
        "m_peak_vel": [2.1],
    })

    metrics = extract_metrics_df(events)

    assert "trigger_datetime" in metrics.columns
    assert metrics["trigger_datetime"].iloc[0] == pd.Timestamp("2025-01-01T00:00:01.200")

def test_metrics_event_id_refs_exist_exactly_once_contract():
    # Contract-style events_df with unique event_id
    events = pd.DataFrame({
        "event_id": ["shock_rebound:0", "shock_rebound:1"],
        "schema_id": ["shock_rebound", "shock_rebound"],
        "schema_version": ["1.0", "1.0"],
        "event_name": ["Rear shock rebound", "Rear shock rebound"],
        "signal": ["rear_shock_vel", "rear_shock_vel"],
        "start_idx": [100, 300],
        "end_idx": [150, 350],
        "trigger_idx": [120, 320],
        "start_time_s": [1.00, 3.00],
        "end_time_s": [1.50, 3.50],
        "trigger_time_s": [1.20, 3.20],
        "m_peak_vel": [2.1, 2.4],
    })

    metrics = extract_metrics_df(events)

    # Join guarantee: metrics.event_id must map to exactly one events row
    counts = events["event_id"].value_counts()
    assert (counts == 1).all(), f"events_df has non-unique event_id(s): {counts[counts != 1].to_dict()}"

    missing = set(metrics["event_id"]) - set(events["event_id"])
    assert not missing, f"metrics_df references missing event_id(s): {missing}"
