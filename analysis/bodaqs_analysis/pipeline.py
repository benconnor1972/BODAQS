from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple
import pandas as pd

from .io_logger import load_logger_csv, parse_run_stats_footer
from .normalize import normalize_and_scale
from .va import estimate_va
from .schema import load_event_schema
from .detect import detect_events_from_schema
from .metrics import extract_metrics_df
from .model import validate_metrics_df
from .model import validate_session
from .timebase import register_stream_timebase
from .signal_standardize import standardize_signals



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
                       clip_0_1: bool = False,
                       va_cols: Optional[Sequence[str]] = None,
                       va_window_points: int = 11,
                       va_poly_order: int = 3) -> Dict[str, Any]:
    """Normalize, zero + compute velocity/acceleration."""
    df = session["df"].copy()

    # QC: ensure structure exists early
    qc = session.setdefault("qc", {})
    transforms = qc.setdefault("transforms", {})

    # ---------------- Normalize / zero / scale ----------------
    df2, norm_meta = normalize_and_scale(
        df,
        normalize_ranges,
        zeroing_enabled=zeroing_enabled,
        zero_window_s=zero_window_s,
        clip_0_1=clip_0_1,
        return_meta=True,        
    )
    per_column = norm_meta.get("per_column",[])
    session["df"] = df2

    # Update QC transforms from report
    # (report entries may be missing/empty depending on input columns)
    by_channel = {}
    methods = set()
    
    for r in per_column:
        if r.get("status") != "ok":
            continue
        z = r.get("zeroing") or {}
        if not z.get("enabled", False):
            continue
    
        col = r["column"]
        m = z.get("method")
        if m:
            methods.add(m)
    
        if "offset" in z and z["offset"] is not None:
            by_channel[col] = {"offset": float(z["offset"]), "method": m}
        elif "segment_offsets" in z and z["segment_offsets"]:
            by_channel[col] = {"segment_offsets": z["segment_offsets"], "method": m}
    
    transforms["zeroed"] = {
        "applied": bool(zeroing_enabled),
        "method": (next(iter(methods)) if len(methods) == 1 else ("mixed" if methods else None)),
        "window_s": float(zero_window_s),
        "by_channel": by_channel or None,
    }

    transforms["scaled"] = {
        "applied": True,
        "by_channel": {
            r["column"]: {"full_range": float(r.get("full_range"))}
            for r in per_column
            if r.get("status") == "ok" and r.get("full_range") is not None
        } or None,
    }

    # ---------------- Velocity/acceleration ----------------
    if va_cols is None:
        va_cols = list(normalize_ranges.keys())

    df3, va_meta = estimate_va(
        df2,
        cols=list(va_cols),
        sample_rate_hz=sample_rate_hz,
        window_points=va_window_points,
        poly_order=va_poly_order,
        return_meta=True,            # <-- opt-in diagnostics
    )
    session["df"] = df3

    transforms["va"] = {
        "applied": True,
        "by_channel": list(va_meta.get("cols", [])) if va_meta else list(va_cols),
        "dt": float(va_meta["dt"]) if va_meta and va_meta.get("dt") is not None else None,
        "window_points": int(va_window_points),
        "poly_order": int(va_poly_order),
    }

    # ---------------- Meta ----------------
    meta = session.setdefault("meta", {})
    if sample_rate_hz is not None:
        meta["sample_rate_hz"] = float(sample_rate_hz)

    # ---------------- Timebase / streams meta (v0) ----------------
    # For now, your analysis df is a single "primary" stream.
    # Later, you'll add additional streams (imu, etc.) and register each.
    register_stream_timebase(
        session,
        stream_name="primary",
        df_stream=session["df"],   # df3 (post normalize + VA) is now in session["df"]
        time_col="time_s",
        sample_rate_hz=meta.get("sample_rate_hz"),  # may be None; estimator will infer from time_s
        jitter_tol_frac=0.05,
    )
    validate_session(session)

    # ---------------- Signals: standardise + enforce (v0.2) ----------------
    # Units hint: keys you normalise are your engineered position bases.
    units_by_base = {k: "mm" for k in normalize_ranges.keys()}

    # Domain hint (optional but now that you want domain, this is a good start)
    domain_by_base = {
        "front_shock": "suspension",
        "rear_shock": "suspension",
    }

    session = standardize_signals(
        session,
        units_by_base=units_by_base,
        domain_by_base=domain_by_base,
        strict_registry_parse=True,  # Step 3 normaliser exists, so tighten
        derive_va=False,             # you already compute VA above
    )

    
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

    assert "df" in session, "preprocess_session() must set session['df']"
    assert isinstance(session["df"], pd.DataFrame), "session['df'] must be a DataFrame"
    assert "time_s" in session["df"].columns, "session['df'] must contain 'time_s'"

    schema = load_event_schema(schema_path)

    #debug
    assert "signals" in session.get("meta", {}), "meta.signals missing; did standardize_signals run?"
    assert isinstance(session.get("meta"), dict), "session['meta'] missing"
    assert isinstance(session["meta"].get("signals"), dict) and session["meta"]["signals"], \
    "meta.signals missing/empty: you must build the signals registry before detection"

    events_df = detect_events_from_schema(session["df"], schema, meta=session.get("meta"))

    metrics_df = extract_metrics_df(events_df)
    # Contract validation (always on for v0)
    validate_metrics_df(metrics_df, events_df=events_df)
    return {
        "session": session,
        "schema": schema,
        "events": events_df,
        "metrics": metrics_df,
    }
