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
ACTIVE_MASK_COL = "active_mask_qc"  # stored in session["df"] (not in registry)

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

def _build_active_mask_from_time_s(
    df: pd.DataFrame,
    *,
    disp_col: str,
    vel_col: str,
    disp_thresh: float,
    vel_thresh: float,
    window: str,
    padding: str,
    min_segment: str,
) -> pd.Series:
    """
    Return boolean mask aligned to df.index. Uses time_s to build a TimedeltaIndex internally.
    Non-destructive: does not modify df.
    """
    if "time_s" not in df.columns:
        raise ValueError("Expected 'time_s' in df for activity mask")

    if disp_col not in df.columns or vel_col not in df.columns:
        # soft-fail: return all True so downstream behaves identically to "no masking"
        return pd.Series(True, index=df.index, name=ACTIVE_MASK_COL)

    # build a time index locally (do NOT mutate df index)
    t = pd.to_numeric(df["time_s"], errors="coerce").to_numpy(dtype=float, copy=False)
    td = pd.to_timedelta(t, unit="s")

    disp_active = pd.Series(pd.to_numeric(df[disp_col], errors="coerce").to_numpy(), index=td).abs() > disp_thresh
    vel_active  = pd.Series(pd.to_numeric(df[vel_col],  errors="coerce").to_numpy(), index=td).abs() > vel_thresh

    active = disp_active & vel_active   # keep your current AND policy (change to | if desired)

    # rolling soften
    active = active.rolling(window, min_periods=1).max().astype(bool)

    pad = pd.to_timedelta(padding)
    minseg = pd.to_timedelta(min_segment)

    # contiguous blocks (time-indexed series)
    merged: list[list[pd.Timedelta]] = []
    if active.any():
        block_id = (active != active.shift(fill_value=False)).cumsum()
        segments = []
        for _, g in active.groupby(block_id):
            if not bool(g.iloc[0]):
                continue
            s = g.index[0] - pad
            e = g.index[-1] + pad
            segments.append([s, e])

        segments.sort(key=lambda x: x[0])
        for s, e in segments:
            if not merged or s > merged[-1][1]:
                merged.append([s, e])
            else:
                merged[-1][1] = max(merged[-1][1], e)

        merged = [[s, e] for s, e in merged if (e - s) >= minseg]

    # apply merged blocks to td index
    keep_td = pd.Series(False, index=td)
    for s, e in merged:
        keep_td |= (keep_td.index >= s) & (keep_td.index <= e)

    # return aligned to df rows (original df index)
    keep = pd.Series(keep_td.to_numpy(dtype=bool), index=df.index, name=ACTIVE_MASK_COL)
    return keep

def preprocess_session(session: Dict[str, Any],
                       *,
                       normalize_ranges: Dict[str, float],
                       sample_rate_hz: Optional[float] = None,
                       zeroing_enabled: bool = True,
                       zero_window_s: float = 1.0,
                       zero_min_samples: int = 10,
                       clip_0_1: bool = False,
                       active_signal_disp_col: Optional[bool] = None,
                       active_signal_vel_col: Optional[bool] = None,
                       active_disp_thresh: float = 20,
                       active_vel_thresh: float = 50,
                       active_window: str = "500ms",
                       active_padding: str = "1s",
                       active_min_seg: str = "3s",
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

    # ---------------- Activity mask (QC; non-destructive) ----------------
    # Derive companion columns from ACTIVE_SIGNAL_BASE
    # Assumes your VA naming convention appends "_vel" to the signal column name.
    # Adjust vel_col derivation if your VA uses a different convention.

    active_mask = _build_active_mask_from_time_s(
        session["df"],
        disp_col=active_signal_disp_col,
        vel_col=active_signal_vel_col,
        disp_thresh=active_disp_thresh,
        vel_thresh=active_vel_thresh,
        window=active_window,
        padding=active_padding,
        min_segment=active_min_seg,
    )

    # Store as QC column (won't be in registry signals)
    session["df"][ACTIVE_MASK_COL] = active_mask

    # Record provenance in qc/meta
    qc = session.setdefault("qc", {})
    qc.setdefault("activity_mask", {})
    qc["activity_mask"] = {
        "applied": True,
        "mask_col": ACTIVE_MASK_COL,
        "disp_col": active_signal_disp_col,
        "vel_col": active_signal_vel_col,
        "disp_thresh": float(active_disp_thresh),
        "vel_thresh": float(active_vel_thresh),
        "window": str(active_window),
        "padding": str(active_padding),
        "min_segment": str(active_min_seg),
        "logic": "disp&vel",
        "version": "v0",
    }

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

     
def run_macro(
    csv_path: str,
    schema_path: str,
    *,
    zeroing_enabled: bool = True,
    zero_window_s: float = 1,
    zero_min_samples: int = 10,
    clip_0_1: bool = False,
    active_signal_disp_col: [bool] = None,
    active_signal_vel_col: [bool] = None,
    active_disp_thresh: float = 20,
    active_vel_thresh: float = 50,
    active_window: str = "500ms",
    active_padding: str = "1s",
    active_min_seg: str = "3s",
    normalize_ranges: Dict[str, float],
    sample_rate_hz: Optional[float] = None,
    timezone: Optional[str] = None,
    strict: bool = True,
) -> Dict[str, Any]:
    """Convenience macro pipeline: load -> preprocess -> detect -> segment -> metrics.

    strict:
        When True, metrics computation enforces strict trigger/spec requirements (may raise).
        When False, missing trigger times (etc.) should propagate as NaN where supported.
    """
    session = load_session(csv_path, timezone=timezone)
    logger.info("Session load complete: %s", csv_path)

    session = preprocess_session(
        session,
        normalize_ranges=normalize_ranges,
        sample_rate_hz=sample_rate_hz,
        zeroing_enabled=zeroing_enabled,
        zero_window_s=zero_window_s,
        zero_min_samples=zero_min_samples,
        clip_0_1=clip_0_1,
        active_signal_disp_col=active_signal_disp_col,
        active_signal_vel_col=active_signal_vel_col,
        active_disp_thresh=active_disp_thresh,
        active_vel_thresh=active_vel_thresh,
        active_window=active_window,
        active_padding=active_padding,
        active_min_seg=active_min_seg,
    )
    logger.info("Session pre-process complete")

    # debug
    t = session["df"]["time_s"].to_numpy()
    logger.debug("time_s start/end: %s .. %s", t[0], t[-1])
    logger.debug(
        "dt median/min/max: %s / %s / %s",
        float(np.median(np.diff(t))),
        float(np.min(np.diff(t))),
        float(np.max(np.diff(t))),
    )

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
    logger.debug("kind counts: %s", kinds)
    logger.debug("unit counts: %s", units)

    # debug
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

    # debug
    logger.info("Event detection complete")
    logger.info("events rows: %d", len(events_df))

    if isinstance(events_df, pd.DataFrame):
        if "event_name" in events_df.columns:
            logger.debug(
                "event_name unique: %s",
                sorted(events_df["event_name"].dropna().unique().tolist()),
            )
        else:
            logger.debug("events_df has no 'event_name' column; columns=%s", list(events_df.columns))

        if "schema_id" in events_df.columns:
            logger.debug(
                "schema_id unique: %s",
                sorted(events_df["schema_id"].dropna().astype(str).unique().tolist()),
            )
        else:
            logger.debug("events_df has no 'schema_id' column; columns=%s", list(events_df.columns))


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
        t2 = bundle["data"].get("t_rel_s")
        logger.debug("t_rel_s type=%s shape=%s", type(t2), getattr(t2, "shape", None))
        if isinstance(t2, np.ndarray):
            logger.debug("t_rel_s[0][:10]=%s", t2[0][:10])
            logger.debug("t_rel_s[0][-10:]=%s", t2[0][-10:])
            d = np.diff(t2[0].astype(float))
            logger.debug("diff stats: min=%s med=%s max=%s", np.nanmin(d), np.nanmedian(d), np.nanmax(d))
            logger.debug("nonpositive diffs=%d", int(np.sum(d <= 0)))
        # debug

        # Metrics from SegmentBundle (per schema event)
        metrics_i = compute_metrics_from_segments(bundle, schema=schema, strict=strict)
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

