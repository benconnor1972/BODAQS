from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple
import pandas as pd
import numpy as np
import logging
import os
import re

from .io_logger import load_logger_csv, parse_run_stats_footer
from .normalize import normalize_and_scale
from .va import estimate_va
from .schema import load_event_schema
from .detect import detect_events_from_schema
from .metrics import extract_metrics_df, compute_metrics_from_segments
from .model import validate_metrics_df
from .model import validate_session
from .timebase import register_stream_timebase
from .signal_standardize import (
    canonicalize_signal_names,
    rebuild_and_validate_signal_registry,
)
from .segment import extract_segments, SegmentRequest

_UNIT_RE = re.compile(r"\[(.*?)\]")

logger = logging.getLogger(__name__)

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

    # ---------------- Signals: canonicalize base names early ----------------
    units_by_base = {k: "mm" for k in normalize_ranges.keys()}
    domain_by_base = {"front_shock": "suspension", "rear_shock": "suspension"}

    session["df"] = df  # ensure session df is current
    session = canonicalize_signal_names(
        session,
        units_by_base=units_by_base,
        domain_by_base=domain_by_base,
    )
    df = session["df"]  # refresh local df after rename

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

    # ---------------- Signals: rebuild registry + validate (final df) ----------------
    session = rebuild_and_validate_signal_registry(
        session,
        strict_registry_parse=True,
    )
    return session

     
def run_macro(csv_path: str,
              schema_path: str,
              *,
              normalize_ranges: Dict[str, float],
              sample_rate_hz: Optional[float] = None,
              timezone: Optional[str] = None) -> Dict[str, Any]:
    """Convenience macro pipeline: load -> preprocess -> detect -> segment -> metrics."""
    session = load_session(csv_path, timezone=timezone)    logger.info("Session load complete: %s", csv_path)

    session = preprocess_session(
        session,
        normalize_ranges=normalize_ranges,
        sample_rate_hz=sample_rate_hz,
    )    logger.info("Session pre-process complete")

    # debug
    t = session["df"]["time_s"].to_numpy()
    logger.debug("time_s start/end: %s .. %s", t[0], t[-1])
    logger.debug("dt median/min/max: %s / %s / %s", float(np.median(np.diff(t))), float(np.min(np.diff(t))), float(np.max(np.diff(t))))


    # debug: inspect signal registry shape
    sig = session.get("meta", {}).get("signals", {})
    logger.debug("signals entries: %d", len(sig))

    # show a few entries
    for col, info in list(sig.items())[:10]:
        logger.debug("%s -> %s", col, info)

    # show kind/unit distribution
    kinds = {}
    units = {}
    for info in sig.values():
        if isinstance(info, dict):
            kinds[info.get("kind")] = kinds.get(info.get("kind"), 0) + 1
            units[info.get("unit")] = units.get(info.get("unit"), 0) + 1
    logger.debug("kind counts: ", kinds)
    logger.debug("unit counts: ", units)

    #debug
    assert "df" in session
    assert "time_s" in session["df"].columns
    assert "signals" in session.get("meta", {})

    meta = session.setdefault("meta", {})
    if not isinstance(meta, dict):
        raise ValueError("session['meta'] must be a dict")

    # Standardized session_id: CSV filename stem (no extension)
    sid = os.path.splitext(os.path.basename(str(csv_path)))[0]
    session["session_id"] = sid
    meta["session_id"] = sid

    
    schema = load_event_schema(schema_path)
    
    logger.info("Schema load complete")

    events_df = detect_events_from_schema(
        session["df"],
        schema,
        meta=session["meta"],
    )

    #debug
    logger.info("Event detection complete")
    logger.info("events rows: %d", len(events_df))
    logger.debug("event_name unique: %s", sorted(events_df["event_name"].dropna().unique().tolist()))
    logger.debug("schema_id unique %s:", sorted(events_df["schema_id"].dropna().unique().tolist()))
    #debug

    # Segment extraction (one schema event per call in v0)
    detected_sids = sorted(events_df["schema_id"].dropna().astype(str).unique().tolist()) if (
        isinstance(events_df, pd.DataFrame) and ("schema_id" in events_df.columns)
    ) else []

    defined_sids = sorted([str(e.get("id")) for e in (schema.get("events") or []) if isinstance(e, dict) and e.get("id")])
    missing = [sid for sid in defined_sids if sid not in set(detected_sids)]
    if missing:
        logger.info("Schema events with zero detections this run: %s", missing)

    logger.info("Running segment extraction for detected schema events: %s", detected_sids)

    bundles_by_schema_id: dict[str, dict] = {}
    metrics_parts: list[pd.DataFrame] = []

    for sid in detected_sids:
        # (Optional but nice) pre-filter for clarity + earlier logging
        events_sel = events_df[events_df["schema_id"].astype(str) == str(sid)]
        if events_sel.empty:
            logger.info("No events for schema_id=%s; skipping.", sid)
            continue

        bundle = extract_segments(
            df=session["df"],
            events=events_df,  # extract_segments will select internally; keep as-is
            meta=session["meta"],
            schema=schema,
            request=SegmentRequest(schema_id=sid),
        )
        bundles_by_schema_id[sid] = bundle
        logger.info("Segment extraction complete (schema_id=%s)", sid)

        seg = bundle["segments"]
        valid_n = int(seg["valid"].sum()) if "valid" in seg.columns else 0
        total_n = len(seg)
        logger.info("segments valid (schema_id=%s): %d/%d", sid, valid_n, total_n)

        # debug
        logger.debug("segments head(3) (schema_id=%s):\n%s", sid, seg.head(3).to_string(index=False))

        if "reason" in seg.columns:
            logger.debug(
                "segments.reason value_counts head(10) (schema_id=%s):\n%s",
                sid,
                seg["reason"].value_counts().head(10).to_string(),
            )

        t = bundle.get("data", {}).get("t_rel_s", None)
        if isinstance(t, np.ndarray):
            logger.debug("t_rel_s shape=%s dtype=%s (schema_id=%s)", t.shape, t.dtype, sid)
            logger.debug("t_rel_s first10 (schema_id=%s): %s", sid, t.ravel()[:10])
        else:
            logger.debug("t_rel_s not ndarray (schema_id=%s): type=%s value=%r", sid, type(t), t)
        # debug

        # Metrics from SegmentBundle (per schema event)
        metrics_i = compute_metrics_from_segments(bundle, schema=schema)
        logger.info("Metrics calculation complete (schema_id=%s)", sid)

        # Ensure schema_id is present for grouping/faceting downstream
        if "schema_id" not in metrics_i.columns:
            metrics_i = metrics_i.copy()
            metrics_i["schema_id"] = sid

        metrics_parts.append(metrics_i)

    metrics_df = pd.concat(metrics_parts, ignore_index=True) if metrics_parts else pd.DataFrame()

    validate_metrics_df(metrics_df, events_df=events_df)
    logger.info("Metrics validation complete")

    return {
        "session": session,
        "schema": schema,
        "events": events_df,
        "segments": bundles_by_schema_id,
        "metrics": metrics_df,
    }

