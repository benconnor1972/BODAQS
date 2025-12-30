from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TypedDict, Union
import pandas as pd

# NOTE: v0 contract uses plain dicts; these TypedDicts are for documentation & editor hints only.

class SessionSource(TypedDict, total=False):
    path: str
    filename: str
    created_local: object  # datetime-like
    timezone: str

class ChannelInfo(TypedDict, total=False):
    unit: str
    sensor: str
    role: str
    nominal_rate_hz: float
    source_columns: List[str]

class SessionMeta(TypedDict, total=False):
    channels: List[str]
    channel_info: Dict[str, ChannelInfo]
    sample_rate_hz: float
    sample_rate_by_channel_hz: Dict[str, float]
    device: Dict[str, Any]
    notes: str

class SessionQC(TypedDict, total=False):
    time_monotonic: bool
    time_repaired: bool
    n_time_gaps: int
    gap_total_s: float
    warnings: List[str]
    transforms: Dict[str, Any]
    firmware_stats: Dict[str, Any]
    parse: Dict[str, Any]

class Session(TypedDict, total=False):
    session_id: str
    source: SessionSource
    meta: SessionMeta
    qc: SessionQC
    df_raw: pd.DataFrame
    df: pd.DataFrame

def validate_session(session: Dict[str, Any], *, require_df: bool = True) -> None:
    """Lightweight validation for the Session contract (v0).

    Raises ValueError with a human-readable message if something essential is missing.
    """
    if not isinstance(session, dict):
        raise ValueError("session must be a dict-like object")

    for k in ("session_id", "source", "meta", "qc"):
        if k not in session:
            raise ValueError(f"session missing required key: {k}")

    if require_df:
        if "df" not in session or not isinstance(session["df"], pd.DataFrame):
            raise ValueError("session['df'] must be a pandas DataFrame")
        df = session["df"]
        # Time axis: either time_s col or index name time_s
        has_time_col = "time_s" in df.columns
        has_time_idx = getattr(df.index, "name", None) == "time_s"
        if not (has_time_col or has_time_idx):
            raise ValueError("session['df'] must have a 'time_s' column or a time_s index")

def validate_segments(segments_df: pd.DataFrame) -> None:
    req = {"segment_id","t0_s","t1_s","label","source","session_id"}
    missing = req - set(segments_df.columns)
    if missing:
        raise ValueError(f"segments_df missing columns: {sorted(missing)}")
    if (segments_df["t1_s"] <= segments_df["t0_s"]).any():
        raise ValueError("segments_df has segment(s) with t1_s <= t0_s")

def validate_events(events_df: pd.DataFrame) -> None:
    req = {"event_id","event_type","sensor","t0_s","t_peak_s","t1_s","session_id"}
    missing = req - set(events_df.columns)
    if missing:
        raise ValueError(f"events_df missing columns: {sorted(missing)}")
    bad = (events_df["t_peak_s"] < events_df["t0_s"]) | (events_df["t_peak_s"] > events_df["t1_s"])
    if bad.any():
        raise ValueError("events_df has event(s) with t_peak_s outside [t0_s, t1_s]")
