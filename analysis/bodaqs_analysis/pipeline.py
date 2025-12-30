from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple
import pandas as pd

from .io_logger import load_logger_csv, parse_run_stats_footer
from .normalize import normalize_and_scale
from .va import estimate_va_from_zeroed
from .schema import load_event_schema
from .detect import detect_events_from_schema, extract_metrics_df
from .model import validate_session

def load_session(csv_path: str, *, timezone: Optional[str] = None) -> Dict[str, Any]:
    """Load a CSV into a v0 Session dict (df_raw + initial qc/meta)."""
    p = Path(csv_path)
    df_raw = load_logger_csv(str(p))

    stats = parse_run_stats_footer(str(p))
    session: Dict[str, Any] = {
        "session_id": p.stem,
        "source": {
            "path": str(p),
            "filename": p.name,
            "timezone": timezone,
        },
        "meta": {
            "channels": [c for c in df_raw.columns if c not in ("sample_id","time_s","clock","Clock","Time")],
            "channel_info": {},  # can be enriched later
            "sample_rate_hz": None,
            "sample_rate_by_channel_hz": None,
            "device": None,
            "notes": None,
        },
        "qc": {
            "warnings": [],
            "transforms": {
                "zeroed": {"applied": False, "method": None, "by_channel": None},
                "scaled": {"applied": False, "by_channel": None},
                "filtered": {"applied": False, "method": None, "params": None},
                "resampled": {"applied": False, "target_rate_hz": None, "method": None},
            },
            "firmware_stats": stats or None,
            "parse": {
                "rows_read": int(len(df_raw)),
                "rows_ignored": None,
                "clock_column_used": None,
            },
            "time_monotonic": True,
            "time_repaired": False,
            "n_time_gaps": 0,
            "gap_total_s": 0.0,
        },
        "df_raw": df_raw,
        "df": df_raw.copy(),
    }
    return session

def preprocess_session(session: Dict[str, Any],
                       *,
                       normalize_ranges: Dict[str, float],
                       sample_rate_hz: Optional[float] = None,
                       zeroing_enabled: bool = True,
                       zero_window_s: float = 1.0,
                       zero_method: str = "lowest_1s_mean",
                       clip_0_1: bool = False,
                       va_cols: Optional[Sequence[str]] = None,
                       va_window_points: int = 11,
                       va_poly_order: int = 3) -> Dict[str, Any]:
    """Normalize (in-place zeroing) + compute velocity/acceleration."""
    df = session["df"].copy()

    # Normalize / zero / scale
    df2, report = normalize_and_scale(
        df,
        normalize_ranges,
        zeroing_enabled=zeroing_enabled,
        zero_window_s=zero_window_s,
        clip_0_1=clip_0_1,
        add_zeroed_column=False,
        in_place_zero=True,
    )
    session["df"] = df2

    # QC: ensure structure exists
    qc = session.setdefault("qc", {})
    transforms = qc.setdefault("transforms", {})

    # Update qc transforms
    zeroed_offsets = {r["column"]: r.get("offset") for r in report if r.get("status") == "ok" and "offset" in r}
    transforms["zeroed"] = {
        "applied": bool(zeroing_enabled),
        "method": zero_method,
        "by_channel": {k: {"offset": float(v)} for k, v in zeroed_offsets.items()} if zeroed_offsets else None,
    }
    transforms["scaled"] = {
        "applied": True,
        "by_channel": {r["column"]: {"full_range": r.get("full_range")} for r in report if r.get("status") == "ok"},
    }

    # Velocity/acceleration on selected base columns (or all normalized range keys)
    if va_cols is None:
        va_cols = list(normalize_ranges.keys())

    va_result = estimate_va_from_zeroed(
        df2,
        cols=list(va_cols),
        sample_rate_hz=sample_rate_hz,
        window_points=va_window_points,
        poly_order=va_poly_order,
    )
    df3 = va_result[0] if isinstance(va_result, tuple) else va_result
    session["df"] = df3

    # best-effort sample rate
    session.setdefault("meta", {})
    if sample_rate_hz is not None:
        session["meta"]["sample_rate_hz"] = float(sample_rate_hz)

    validate_session(session)
    return session


def run_macro(csv_path: str,
              schema_path: str,
              *,
              normalize_ranges: Dict[str, float],
              sample_rate_hz: Optional[float] = None,
              timezone: Optional[str] = None) -> Dict[str, Any]:
    """Convenience macro pipeline: load -> preprocess -> detect -> metrics."""
    session = load_session(csv_path, timezone=timezone)
    session = preprocess_session(session, normalize_ranges=normalize_ranges, sample_rate_hz=sample_rate_hz)

    schema = load_event_schema(schema_path)
    events_df = detect_events_from_schema(session["df"], schema)

    metrics_df = extract_metrics_df(events_df)

    return {
        "session": session,
        "schema": schema,
        "events": events_df,
        "metrics": metrics_df,
    }
