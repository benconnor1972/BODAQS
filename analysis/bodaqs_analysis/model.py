from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TypedDict, Union, Sequence
import pandas as pd
import numpy as np
import re

_TRIGGER_TIME_RE = re.compile(r"^[A-Za-z0-9_]+_time_s$")
_TRIGGER_IDX_RE  = re.compile(r"^[A-Za-z0-9_]+_idx$")

_CANON_TIME = {"start_time_s", "end_time_s", "trigger_time_s"}
_CANON_IDX  = {"start_idx", "end_idx", "trigger_idx"}

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
        
        # Canonical time vector
        if "time_s" in df.columns:
            t = pd.to_numeric(df["time_s"], errors="coerce").to_numpy(dtype=float)
        else:
            # time_s index path
            t = pd.to_numeric(df.index.to_series(), errors="coerce").to_numpy(dtype=float)

        if t.size < 2:
            raise ValueError("time_s must contain at least two samples")
        if not np.isfinite(t).all():
            raise ValueError("time_s contains non-finite values")
        if np.any(np.diff(t) < 0):
            raise ValueError("time_s must be monotonic non-decreasing")

        # Time axis: either time_s col or index name time_s
        has_time_col = "time_s" in df.columns
        has_time_idx = getattr(df.index, "name", None) == "time_s"
        if not (has_time_col or has_time_idx):
            raise ValueError("session['df'] must have a 'time_s' column or a time_s index")

        # Optional but strongly recommended in v0+: stream timebase metadata
        meta = session.get("meta") or {}
        streams = meta.get("streams")

        if streams is None:
            raise ValueError("session['meta'] missing required key: streams")
        if not isinstance(streams, dict) or not streams:
            raise ValueError("session['meta']['streams'] must be a non-empty dict")

        # Require a 'primary' stream for now (your analysis df)
        if "primary" not in streams:
            raise ValueError("session['meta']['streams'] missing required stream: 'primary'")

        primary = streams["primary"]
        if not isinstance(primary, dict):
            raise ValueError("session['meta']['streams']['primary'] must be a dict")

        for k in ("kind", "time_col", "sample_rate_hz", "dt_s", "jitter_frac"):
            if k not in primary:
                raise ValueError(f"session['meta']['streams']['primary'] missing required key: {k}")

        # Basic sanity on timebase numbers
        dt_s = float(primary["dt_s"])
        sr_hz = float(primary["sample_rate_hz"])
        if not np.isfinite(dt_s) or dt_s <= 0:
            raise ValueError("primary stream dt_s must be finite and > 0")
        if not np.isfinite(sr_hz) or sr_hz <= 0:
            raise ValueError("primary stream sample_rate_hz must be finite and > 0")

def validate_signals_registry_shape(session: Dict[str, Any]) -> None:
    """
    Validate the *shape* of session['meta']['signals'] against the v0.2 signal-registry contract.

    This is intentionally structural only:
      - registry exists and is a dict
      - keys correspond to df columns
      - required fields exist with basic types

    Semantic enforcement (units/kind rules) comes later in Step 4.
    """
    if not isinstance(session, dict):
        raise ValueError("session must be a dict-like object")
    if "df" not in session or not isinstance(session["df"], pd.DataFrame):
        raise ValueError("session['df'] must be a pandas DataFrame")
    if "meta" not in session or not isinstance(session["meta"], dict):
        raise ValueError("session['meta'] must be a dict")

    df = session["df"]
    signals = session["meta"].get("signals")
    if signals is None:
        raise ValueError("session['meta'] missing required key: signals")
    if not isinstance(signals, dict):
        raise ValueError("session['meta']['signals'] must be a dict")

    # Every registry key must exist as a df column
    extra = [k for k in signals.keys() if k not in df.columns]
    if extra:
        raise ValueError(f"meta.signals contains keys not in df.columns: {extra[:20]}")

    # Minimal required fields per entry
    required = ("kind", "unit", "domain", "op_chain")
    for col, info in signals.items():
        if not isinstance(info, dict):
            raise ValueError(f"signals[{col!r}] must be a dict")
        missing = [k for k in required if k not in info]
        if missing:
            raise ValueError(f"signals[{col!r}] missing required key(s): {missing}")
        if not isinstance(info["kind"], str):
            raise ValueError(f"signals[{col!r}]['kind'] must be a str")
        if info["unit"] is not None and not isinstance(info["unit"], str):
            raise ValueError(f"signals[{col!r}]['unit'] must be str or None")
        if info["domain"] is not None and not isinstance(info["domain"], str):
            raise ValueError(f"signals[{col!r}]['domain'] must be str or None")
        if not isinstance(info["op_chain"], list) or not all(isinstance(x, str) for x in info["op_chain"]):
            raise ValueError(f"signals[{col!r}]['op_chain'] must be list[str]")

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
    "signal_col",
)

import re
from typing import Optional

import numpy as np
import pandas as pd

_TRIGGER_TIME_RE = re.compile(r"^[A-Za-z0-9_]+_time_s$")
_TRIGGER_IDX_RE  = re.compile(r"^[A-Za-z0-9_]+_idx$")

_CANON_TIME = {"start_time_s", "end_time_s", "trigger_time_s"}
_CANON_IDX  = {"start_idx", "end_idx", "trigger_idx"}

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

    # canonical type/coercion checks
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

    # optional trigger_datetime support (v0.1.2 draft)
    if "trigger_datetime" in events_df.columns:
        s = events_df["trigger_datetime"]

        # Accept datetime64 directly; if object dtype, require coercible values
        if pd.api.types.is_datetime64_any_dtype(s):
            pass
        elif pd.api.types.is_object_dtype(s):
            coerced = pd.to_datetime(s, errors="coerce")
            bad_mask = s.notna() & coerced.isna()
            if bad_mask.any():
                examples = s[bad_mask].astype(str).head(5).tolist()
                raise ValueError(
                    f"events_df.trigger_datetime has non-coercible values (examples): {examples}"
                )
        else:
            raise ValueError(
                "events_df.trigger_datetime must be datetime64 dtype or object convertible to datetime"
            )

    # additive per-trigger column validation (v0.1.2 draft)
    trigger_time_cols = [
        c for c in events_df.columns
        if isinstance(c, str) and c not in _CANON_TIME and _TRIGGER_TIME_RE.match(c)
    ]
    trigger_idx_cols = [
        c for c in events_df.columns
        if isinstance(c, str) and c not in _CANON_IDX and _TRIGGER_IDX_RE.match(c)
    ]

    # *_idx: integer-like OR NaN
    for c in trigger_idx_cols:
        s = events_df[c]
        if pd.api.types.is_integer_dtype(s):
            continue
        vals = pd.to_numeric(s, errors="coerce")
        nn = vals.dropna()
        if len(nn) and not (nn % 1 == 0).all():
            raise ValueError(f"events_df trigger index column '{c}' must be integer-like (or NaN)")

    # *_time_s: finite numeric OR NaN
    for c in trigger_time_cols:
        vals = pd.to_numeric(events_df[c], errors="coerce").to_numpy()
        ok = np.isfinite(vals) | np.isnan(vals)
        if not ok.all():
            raise ValueError(f"events_df trigger time column '{c}' must be finite numeric (or NaN)")

    # ordering invariants (canonical)
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
    strict: bool = True,
) -> None:
    """
    Validate metrics_df against the Metrics Table Contract (v0.1.2).

    Contract essentials:
      - metrics_df has 'event_id' and it is unique
      - metrics_df contains only:
          * identity columns (optional)
          * metric columns prefixed 'm_'
          * debug columns prefixed 'd_'
      - metrics_df must NOT contain window / trigger columns
      - if events_df provided:
          * events_df.event_id must be unique
          * every metrics_df.event_id exists in events_df
          * identity columns must match (strict mode only)
    """
    if metrics_df is None:
        raise ValueError("metrics_df is None")

    if len(metrics_df) == 0:
        return  # empty allowed

    # ------------------------------------------------------------------
    # Required join key
    # ------------------------------------------------------------------
    if "event_id" not in metrics_df.columns:
        raise ValueError("metrics_df missing required column: event_id")

    if metrics_df["event_id"].isna().any():
        raise ValueError("metrics_df.event_id contains NaN")

    dup = metrics_df["event_id"][metrics_df["event_id"].duplicated()].unique().tolist()
    if dup:
        raise ValueError(f"metrics_df has duplicate event_id(s): {dup[:10]}")

    cols = set(metrics_df.columns)

    # ------------------------------------------------------------------
    # Hard-forbidden columns (window / trigger semantics)
    # ------------------------------------------------------------------
    forbidden_exact = {
        "start_idx", "end_idx", "trigger_idx",
        "start_time_s", "end_time_s"
    } #later to include trigger_time_s
    # NOTE: trigger_time_s is allowed for now to support existing metrics projection.
# Future contract may remove it in favor of trigger_datetime only.

    leaked = forbidden_exact & cols
    if leaked:
        raise ValueError(
            "metrics_df contains forbidden window/trigger columns: "
            + ", ".join(sorted(leaked))
        )

    # ------------------------------------------------------------------
    # Allowed column classes
    # ------------------------------------------------------------------
    allowed_identity = {
        "event_id",
        "schema_id",
        "schema_version",
        "event_name",
        "signal",
        "signal_col",
        "segment_id",
        "trigger_datetime",
        "trigger_time_s",
        "tags",
    }

    unknown = []
    for c in cols:
        if c in allowed_identity:
            continue
        if isinstance(c, str) and (c.startswith("m_") or c.startswith("d_")):
            continue
        unknown.append(c)

    if unknown:
        raise ValueError(
            "metrics_df has columns not allowed by contract: "
            + ", ".join(sorted(unknown[:20]))
        )

    # ------------------------------------------------------------------
    # Metric presence (strict)
    # ------------------------------------------------------------------
    if strict:
        metric_cols = [c for c in cols if isinstance(c, str) and c.startswith("m_")]
        if not metric_cols:
            raise ValueError("metrics_df has no 'm_' metric columns")

    # ------------------------------------------------------------------
    # Cross-check vs events_df (if provided)
    # ------------------------------------------------------------------
    if events_df is not None and len(events_df) > 0:
        if "event_id" not in events_df.columns:
            raise ValueError("events_df missing required column for join: event_id")

        # events_df must be 1:1 on event_id
        e_counts = events_df["event_id"].value_counts()
        non_unique = e_counts[e_counts != 1]
        if not non_unique.empty:
            raise ValueError(
                "events_df has non-unique event_id(s); cannot enforce 1:1 join. Examples: "
                + ", ".join([f"{k}={int(v)}" for k, v in non_unique.head(10).items()])
            )

        # All metrics_df.event_id must exist in events_df
        missing = set(metrics_df["event_id"]) - set(events_df["event_id"])
        if missing:
            raise ValueError(
                f"metrics_df references missing event_id(s): {sorted(list(missing))[:20]}"
            )

        # ------------------------------------------------------------------
        # Identity consistency checks (strict mode only)
        # ------------------------------------------------------------------
        if strict:
            for col in (
                "schema_id",
                "schema_version",
                "event_name",
                "signal",
                "signal_col",
                "segment_id",
            ):
                if col in metrics_df.columns and col in events_df.columns:
                    merged = metrics_df[["event_id", col]].merge(
                        events_df[["event_id", col]],
                        on="event_id",
                        how="left",
                        suffixes=("_m", "_e"),
                    )
                    mism = merged[merged[f"{col}_m"] != merged[f"{col}_e"]]
                    if len(mism) > 0:
                        raise ValueError(
                            f"metrics_df identity column '{col}' does not match events_df for some rows"
                        )
