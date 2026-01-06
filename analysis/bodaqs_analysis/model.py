from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TypedDict, Union, Sequence
import pandas as pd
import numpy as np


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

EVENTS_REQUIRED_COLS_V0 = (
    "event_id",
    "schema_id",
    "schema_version",
    "event_name",
    "signal",
    "start_idx",
    "end_idx",
    "trigger_idx",
    "start_time_s",
    "end_time_s",
    "trigger_time_s",
    "detector_version",
    "params_hash",
)

def validate_events_df(events_df: pd.DataFrame, *, df: Optional[pd.DataFrame] = None) -> None:
    if events_df is None:
        raise ValueError("events_df is None")

    if len(events_df) == 0:
        return  # empty is allowed

    missing_cols = [c for c in EVENTS_REQUIRED_COLS_V0 if c not in events_df.columns]
    if missing_cols:
        raise ValueError(f"events_df missing required columns: {missing_cols}")

    # event_id uniqueness
    dup = events_df["event_id"][events_df["event_id"].duplicated()].unique().tolist()
    if dup:
        raise ValueError(f"events_df has duplicate event_id(s): {dup[:10]}")

    # type/coercion checks
    for c in ("start_idx", "end_idx", "trigger_idx"):
        if not pd.api.types.is_integer_dtype(events_df[c]):
            # allow ints stored as floats if they are whole numbers
            bad = events_df[c].dropna()
            if not (bad.astype(float) % 1 == 0).all():
                raise ValueError(f"events_df column '{c}' must be integer-like")

    for c in ("start_time_s", "end_time_s", "trigger_time_s"):
        vals = pd.to_numeric(events_df[c], errors="coerce")
        if not np.isfinite(vals.to_numpy()).all():
            raise ValueError(f"events_df column '{c}' must be finite numeric")

    # ordering invariants
    if not (events_df["start_idx"] <= events_df["trigger_idx"]).all():
        raise ValueError("events_df invariant violated: start_idx <= trigger_idx")
    if not (events_df["trigger_idx"] <= events_df["end_idx"]).all():
        raise ValueError("events_df invariant violated: trigger_idx <= end_idx")

    if not (events_df["start_time_s"] <= events_df["trigger_time_s"]).all():
        raise ValueError("events_df invariant violated: start_time_s <= trigger_time_s")
    if not (events_df["trigger_time_s"] <= events_df["end_time_s"]).all():
        raise ValueError("events_df invariant violated: trigger_time_s <= end_time_s")

    # bounds checks if raw df provided
    if df is not None:
        n = len(df)
        if not ((events_df["start_idx"] >= 0) & (events_df["end_idx"] < n)).all():
            raise ValueError("events_df index bounds violated (start/end outside df length)")

def validate_metrics_df(
    metrics_df: pd.DataFrame,
    *,
    events_df: Optional[pd.DataFrame] = None,
    require_all_metric_cols_prefixed: bool = True,
) -> None:
    """
    Validate metrics_df against Metrics Table Contract v0.

    Contract essentials:
      - metrics_df has 'event_id' and it is unique
      - if events_df provided: every metrics_df.event_id exists exactly once in events_df.event_id
      - metric columns are prefixed with 'm_'
      - metrics_df must NOT contain window/index columns (those belong to events_df)
    """
    if metrics_df is None:
        raise ValueError("metrics_df is None")

    if len(metrics_df) == 0:
        return  # empty allowed

    if "event_id" not in metrics_df.columns:
        raise ValueError("metrics_df missing required column: event_id")

    # event_id uniqueness
    dup = metrics_df["event_id"][metrics_df["event_id"].duplicated()].unique().tolist()
    if dup:
        raise ValueError(f"metrics_df has duplicate event_id(s): {dup[:10]}")

    # Must not contain event-window/index columns
    forbidden = {"start_idx", "end_idx", "start_time_s", "end_time_s"}
    present_forbidden = sorted(forbidden.intersection(set(metrics_df.columns)))
    if present_forbidden:
        raise ValueError(
            "metrics_df contains forbidden columns (belong in events_df): "
            + ", ".join(present_forbidden)
        )

    # Metric columns convention
    non_id_cols = [c for c in metrics_df.columns if c != "event_id"]
    if require_all_metric_cols_prefixed:
        # Allow “identity bundle” columns (recommended by contract)
        allowed_identity = {
            "schema_id",
            "schema_version",
            "event_name",
            "signal",
            "segment_id",
            "trigger_time_s",
            "tags",
        }
        bad = [
            c for c in non_id_cols
            if (c not in allowed_identity) and (not str(c).startswith("m_"))
        ]
        if bad:
            raise ValueError(
                "metrics_df has non-metric columns not in identity bundle and not prefixed 'm_': "
                + ", ".join(bad[:20])
            )

    # Join guarantees vs events_df (if provided)
    if events_df is not None and len(events_df) > 0:
        if "event_id" not in events_df.columns:
            raise ValueError("events_df missing required column for join: event_id")

        # events_df event_id must be unique for a strict 1:1 join
        e_counts = events_df["event_id"].value_counts()
        non_unique = e_counts[e_counts != 1]
        if not non_unique.empty:
            raise ValueError(
                "events_df has non-unique event_id(s); cannot enforce 1:1 join. Examples: "
                + ", ".join([f"{k}={int(v)}" for k, v in non_unique.head(10).items()])
            )

        missing = set(metrics_df["event_id"]) - set(events_df["event_id"])
        if missing:
            raise ValueError(f"metrics_df references missing event_id(s): {sorted(list(missing))[:20]}")

        # Optional: identity bundle consistency if present in both
        for col in ("schema_id", "schema_version", "event_name", "signal", "segment_id", "trigger_time_s"):
            if col in metrics_df.columns and col in events_df.columns:
                merged = metrics_df[["event_id", col]].merge(
                    events_df[["event_id", col]],
                    on="event_id",
                    how="left",
                    suffixes=("_m", "_e"),
                )
                mism = merged[merged[f"{col}_m"] != merged[f"{col}_e"]]
                if len(mism) > 0:
                    raise ValueError(f"metrics_df identity column '{col}' does not match events_df for some rows")
