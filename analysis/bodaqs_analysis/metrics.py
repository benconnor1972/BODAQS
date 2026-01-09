"""
BODAQS Analysis - Metrics (v0.1+)

This module supports two usage modes:

1) Legacy/compatibility:
   - extract_metrics_df(events_df): selects existing 'm_*' columns from an events table.

2) Recommended path with SegmentBundle (Recommendation #5):
   - compute_metrics_from_segments(bundle, schema): computes schema-defined metrics
     from a SegmentBundle (wide/matrix arrays) and returns a metrics dataframe.

Design notes
------------
- Metric columns are prefixed 'm_'.
- Optional debug columns are prefixed 'd_'.
- Metrics are computed per *valid* segment in the SegmentBundle.
- Identity columns are copied from the Event Table Contract identity bundle where present.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


# -------------------------
# Public: legacy projection
# -------------------------

def extract_metrics_df(
    events_df: pd.DataFrame,
    *,
    id_cols: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Return a wide metrics dataframe from an events_df.

    - Metric columns are those prefixed with 'm_'.
    - By default, keeps the Metrics identity bundle if present.
    - Contract-aligned: does NOT add or require start/end window columns.

    This is a *projection* helper. It does not compute metrics.
    """
    if events_df is None or len(events_df) == 0:
        return pd.DataFrame()

    metric_cols = [c for c in events_df.columns if isinstance(c, str) and c.startswith("m_")]

    if id_cols is None:
        # Preferred identity bundle (Event Table Contract v0.1.1)
        preferred = (
            "event_id",
            "schema_id",
            "schema_version",
            "event_name",
            "signal",
            "signal_col",
            "segment_id",
            "trigger_time_s",
            "tags",
        )

        # Legacy-ish (older notebooks / transitions)
        legacy = (
            "event_type",
            "sensor",
            "t0_time",
            "t0_index",
            "start_index",
            "end_index",
        )

        looks_contract = all(
            c in events_df.columns
            for c in ("event_id", "schema_id", "schema_version", "event_name", "signal", "trigger_time_s")
        )
        id_cols = preferred if looks_contract else legacy

    keep = [c for c in id_cols if c in events_df.columns]
    return events_df[keep + metric_cols].copy()


def validate_metrics_df(
    metrics_df: pd.DataFrame,
    *,
    events_df: Optional[pd.DataFrame] = None,
    strict: bool = True,
) -> None:
    """Lightweight validation for a wide metrics dataframe.

    - Ensures metric columns are prefixed with 'm_'.
    - Ensures identity columns (if present) are sane.
    - If events_df is provided and both contain 'event_id', checks joinability.
    """
    if metrics_df is None:
        raise ValueError("metrics_df is None")

    if len(metrics_df) == 0:
        return

    # Metric columns
    metric_cols = [c for c in metrics_df.columns if isinstance(c, str) and c.startswith("m_")]
    if strict and not metric_cols:
        raise ValueError("metrics_df has no 'm_' metric columns")

    # event_id uniqueness if present
    if "event_id" in metrics_df.columns:
        if metrics_df["event_id"].isna().any() and strict:
            raise ValueError("metrics_df.event_id contains NaN")
        if metrics_df["event_id"].duplicated().any() and strict:
            raise ValueError("metrics_df.event_id must be unique")

    # Optional cross-check with events_df
    if events_df is not None and "event_id" in metrics_df.columns and "event_id" in events_df.columns:
        missing = set(metrics_df["event_id"]) - set(events_df["event_id"])
        if missing and strict:
            raise ValueError(f"metrics_df contains event_id not present in events_df: {sorted(list(missing))[:5]} ...")


# -------------------------
# SegmentBundle metrics path
# -------------------------

@dataclass(frozen=True)
class MetricsContext:
    events: pd.DataFrame              # aligned to data rows (valid segments only)
    segments: pd.DataFrame            # valid-only, aligned
    data: Mapping[str, np.ndarray]    # role arrays, shape (n_seg, n_samp)
    t_rel_s: np.ndarray               # 1D grid, shape (n_samp,)
    dt_s: float                       # estimated dt from t_rel_s


def compute_metrics_from_segments(
    bundle: Mapping[str, Any],
    *,
    schema: Mapping[str, Any],
    strict: bool = True,
) -> pd.DataFrame:
    """Compute schema-defined metrics for the SegmentBundle.

    Parameters
    ----------
    bundle:
        SegmentBundle produced by extract_segments().
        Expected keys: 'events', 'segments', 'data', 'spec'.
    schema:
        Concrete event schema (your YAML loaded to dict).
    strict:
        If True, missing triggers or spec inconsistencies raise ValueError.
        If False, best-effort fallbacks are used.

    Returns
    -------
    metrics_df:
        Wide dataframe containing identity columns + m_* + optional d_* columns.
        Row order matches the SegmentBundle valid segment order.
    """
    events_all = bundle.get("events")
    seg_all = bundle.get("segments")
    data = bundle.get("data")

    if not isinstance(events_all, pd.DataFrame) or not isinstance(seg_all, pd.DataFrame) or not isinstance(data, dict):
        raise ValueError("bundle must contain 'events' (DataFrame), 'segments' (DataFrame), and 'data' (dict)")

    if len(events_all) == 0:
        return pd.DataFrame()

    # Filter to valid segments and align event rows to data order
    if "valid" not in seg_all.columns or "event_row" not in seg_all.columns:
        raise ValueError("bundle['segments'] must contain columns: 'valid', 'event_row'")

    seg_valid = seg_all[seg_all["valid"]].reset_index(drop=True)
    if len(seg_valid) == 0:
        # no valid segments → return empty but with identity cols (optional)
        return pd.DataFrame()

    ev = events_all.iloc[seg_valid["event_row"].to_numpy()].reset_index(drop=True)

    # Validate data shapes
    t_rel = _get_t_rel_grid(data)
    dt_s = _estimate_dt(t_rel)

    # Ensure all role arrays have correct shape
    n_seg = len(seg_valid)
    n_samp = len(t_rel)
    for k, arr in data.items():
        if not isinstance(arr, np.ndarray):
            continue
        if arr.ndim != 2:
            continue
        if arr.shape != (n_seg, n_samp):
            raise ValueError(f"bundle.data['{k}'] has shape {arr.shape}, expected {(n_seg, n_samp)}")

    ctx = MetricsContext(events=ev, segments=seg_valid, data=data, t_rel_s=t_rel, dt_s=dt_s)

    # Determine event schema block
    event_def = _schema_event_def_for_bundle(ctx.events, schema, strict=strict)

    metric_specs = event_def.get("metrics") or []
    if not isinstance(metric_specs, list):
        raise ValueError("schema event 'metrics' must be a list")

    # Compute all metrics
    out_cols: Dict[str, np.ndarray] = {}
    dbg_cols: Dict[str, np.ndarray] = {}

    for spec in metric_specs:
        if not isinstance(spec, dict) or "type" not in spec:
            if strict:
                raise ValueError(f"Invalid metric spec: {spec!r}")
            continue

        mtype = str(spec["type"]).strip()
        if mtype == "peak":
            cols = _metric_peak(ctx, spec, strict=strict)
        elif mtype == "interval_stats":
            cols = _metric_interval_stats(ctx, spec, strict=strict)
        else:
            if strict:
                raise ValueError(f"Unsupported metric type: {mtype}")
            continue

        # Split m_* and d_* columns
        for name, values in cols.items():
            if name.startswith("m_"):
                out_cols[name] = values
            elif name.startswith("d_"):
                dbg_cols[name] = values
            else:
                # enforce naming
                if strict:
                    raise ValueError(f"Metric implementation returned non-prefixed column: {name}")
                out_cols[f"m_{name}"] = values

    # Build output dataframe: identity bundle + m_* + optional debug
    id_cols = _preferred_identity_cols(ctx.events)
    metrics_df = ctx.events[id_cols].copy()

    for name, values in out_cols.items():
        metrics_df[name] = values

    # Add debug columns if any
    for name, values in dbg_cols.items():
        metrics_df[name] = values

    # Validate basic shape
    if len(metrics_df) != n_seg:
        raise AssertionError("metrics_df row count must equal number of valid segments")

    return metrics_df


# Alias for convenience / future naming
compute_metrics = compute_metrics_from_segments


# -------------------------
# Metric implementations
# -------------------------

def _metric_peak(ctx: MetricsContext, spec: Mapping[str, Any], *, strict: bool) -> Dict[str, np.ndarray]:
    """
    Schema example:
      - type: peak
        signal: disp
        kind: max   # or min
        return_time: true (optional)
        id: my_metric_id (optional)
    """
    role = str(spec.get("signal", "")).strip()
    if not role:
        raise ValueError("peak metric requires 'signal' role")

    y = _get_role_array(ctx, role, strict=strict)

    kind = str(spec.get("kind", "max")).strip().lower()
    return_time = bool(spec.get("return_time", False))

    base_id = _metric_id(spec, fallback=f"peak_{role}_{kind}")
    col_val = f"m_{base_id}"

    if kind == "max":
        idx = np.nanargmax(y, axis=1)
        val = np.nanmax(y, axis=1)
    elif kind == "min":
        idx = np.nanargmin(y, axis=1)
        val = np.nanmin(y, axis=1)
    else:
        raise ValueError(f"peak.kind must be 'max' or 'min', got: {kind}")

    out: Dict[str, np.ndarray] = {col_val: val.astype(np.float64, copy=False)}

    if return_time:
        t = ctx.t_rel_s
        t_at = t[idx]
        out[f"{col_val}_t_rel_s"] = t_at.astype(np.float64, copy=False)

    return out


def _metric_interval_stats(ctx: MetricsContext, spec: Mapping[str, Any], *, strict: bool) -> Dict[str, np.ndarray]:
    """
    Schema example:
      - type: interval_stats
        signal: vel
        start_trigger: rebound_start
        end_trigger: rebound_end
        ops: [mean, max, min, delta]
        smooth_ms: 20 (optional)
        min_delay_s: 0.02 (optional)
        return_debug: true (optional)
    """
    role = str(spec.get("signal", "")).strip()
    if not role:
        raise ValueError("interval_stats metric requires 'signal' role")

    start_tr = str(spec.get("start_trigger", "")).strip()
    end_tr = str(spec.get("end_trigger", "")).strip()
    if not start_tr or not end_tr:
        raise ValueError("interval_stats requires 'start_trigger' and 'end_trigger'")

    ops = spec.get("ops") or []
    if isinstance(ops, str):
        ops = [ops]
    if not isinstance(ops, list) or not ops:
        raise ValueError("interval_stats requires non-empty 'ops' list")

    smooth_ms = spec.get("smooth_ms", None)
    smooth_ms = float(smooth_ms) if smooth_ms is not None else 0.0

    min_delay_s = spec.get("min_delay_s", None)
    min_delay_s = float(min_delay_s) if min_delay_s is not None else 0.0

    return_debug = bool(spec.get("return_debug", False))

    y = _get_role_array(ctx, role, strict=strict)

    # Trigger times in absolute session time
    t0_abs = _resolve_trigger_time_s(ctx.events, trigger_id=start_tr, strict=strict)
    t1_abs = _resolve_trigger_time_s(ctx.events, trigger_id=end_tr, strict=strict)

    # Alignment time for the segment is stored on segments as trigger_time_s (standardised)
    if "trigger_time_s" not in ctx.segments.columns:
        raise ValueError("segments table must contain 'trigger_time_s' (alignment time)")

    align_abs = ctx.segments["trigger_time_s"].to_numpy(dtype=np.float64, copy=False)

    # Enforce min_delay if requested
    if min_delay_s > 0:
        t0_abs = np.maximum(t0_abs, align_abs + min_delay_s)

    # Convert to relative times
    t0_rel = t0_abs - align_abs
    t1_rel = t1_abs - align_abs

    # Ensure ordering (swap if inverted)
    swapped = t1_rel < t0_rel
    if np.any(swapped):
        tmp = t0_rel.copy()
        t0_rel[swapped] = t1_rel[swapped]
        t1_rel[swapped] = tmp[swapped]

    # Convert rel times to indices on shared grid
    grid = ctx.t_rel_s
    i0 = np.searchsorted(grid, t0_rel, side="left")
    i1 = np.searchsorted(grid, t1_rel, side="right")

    # Clamp to bounds
    i0 = np.clip(i0, 0, len(grid) - 1)
    i1 = np.clip(i1, 0, len(grid))

    # Optional smoothing (simple moving average)
    if smooth_ms and smooth_ms > 0:
        win = max(1, int(round((smooth_ms / 1000.0) / ctx.dt_s)))
        if win > 1:
            y_smooth = _moving_average_2d(y, win)
        else:
            y_smooth = y
    else:
        y_smooth = y

    base_id = _metric_id(spec, fallback=f"interval_{role}")

    out: Dict[str, np.ndarray] = {}

    # Compute each op per segment (vectorised with per-row slicing loop where needed)
    for op in ops:
        op = str(op).strip().lower()
        col = f"m_{base_id}_{op}"

        if op in ("mean", "avg"):
            out[col] = _reduce_interval(y_smooth, i0, i1, np.nanmean)
        elif op == "max":
            out[col] = _reduce_interval(y_smooth, i0, i1, np.nanmax)
        elif op == "min":
            out[col] = _reduce_interval(y_smooth, i0, i1, np.nanmin)
        elif op == "delta":
            out[col] = _delta_interval(y_smooth, i0, i1)
        elif op == "integral":
            out[col] = _integral_interval(y_smooth, i0, i1, grid)
        else:
            if strict:
                raise ValueError(f"Unsupported interval op: {op}")

    # Optional debug columns
    if return_debug:
        out[f"d_{base_id}_t0_rel_s"] = t0_rel.astype(np.float64, copy=False)
        out[f"d_{base_id}_t1_rel_s"] = t1_rel.astype(np.float64, copy=False)
        out[f"d_{base_id}_i0"] = i0.astype(np.int32, copy=False)
        out[f"d_{base_id}_i1"] = i1.astype(np.int32, copy=False)
        out[f"d_{base_id}_swapped"] = swapped.astype(np.int8, copy=False)

    return out


# -------------------------
# Helpers
# -------------------------

def _preferred_identity_cols(events: pd.DataFrame) -> List[str]:
    preferred = [
        "event_id",
        "schema_id",
        "schema_version",
        "event_name",
        "signal",
        "signal_col",
        "segment_id",
        "trigger_time_s",
        "tags",
    ]
    return [c for c in preferred if c in events.columns]


def _get_t_rel_grid(data: Mapping[str, Any]) -> np.ndarray:
    if "t_rel_s" not in data:
        raise ValueError("bundle.data must include 't_rel_s' for metrics")
    arr = data["t_rel_s"]
    if not isinstance(arr, np.ndarray) or arr.ndim != 2 or arr.shape[0] < 1:
        raise ValueError("bundle.data['t_rel_s'] must be a 2D array with at least one segment")
    grid = arr[0].astype(np.float64, copy=False)
    return grid


def _estimate_dt(t_rel: np.ndarray) -> float:
    if t_rel.ndim != 1 or len(t_rel) < 3:
        raise ValueError("t_rel_s grid must be 1D with >= 3 samples")
    dt = float(np.median(np.diff(t_rel)))
    if dt <= 0 or not np.isfinite(dt):
        raise ValueError("Non-positive dt estimated from t_rel_s")
    return dt


def _schema_event_def_for_bundle(events: pd.DataFrame, schema: Mapping[str, Any], *, strict: bool) -> Mapping[str, Any]:
    # Prefer schema_id from events table (Event Table Contract)
    if "schema_id" in events.columns:
        ids = sorted(set(events["schema_id"].dropna().astype(str).tolist()))
        if len(ids) == 1:
            schema_id = ids[0]
        elif strict:
            raise ValueError(f"Expected one schema_id in bundle.events; got: {ids}")
        else:
            schema_id = ids[0] if ids else ""
    else:
        schema_id = ""

    # Find schema event by id
    events_def = schema.get("events")
    if isinstance(events_def, list) and schema_id:
        for ev in events_def:
            if isinstance(ev, dict) and str(ev.get("id", "")) == schema_id:
                return ev

    # Fallback: try event_name match
    if isinstance(events_def, list) and "event_name" in events.columns:
        names = sorted(set(events["event_name"].dropna().astype(str).tolist()))
        if len(names) == 1:
            name = names[0].lower()
            for ev in events_def:
                if isinstance(ev, dict) and str(ev.get("label", "")).lower() == name:
                    return ev

    if strict:
        raise ValueError("Could not resolve schema event definition for this bundle")
    return {"metrics": []}


def _metric_id(spec: Mapping[str, Any], *, fallback: str) -> str:
    mid = spec.get("id")
    if isinstance(mid, str) and mid.strip():
        return mid.strip()
    # Normalize fallback to a safe id
    return fallback.replace(" ", "_").replace("/", "_")


def _get_role_array(ctx: MetricsContext, role: str, *, strict: bool) -> np.ndarray:
    if role not in ctx.data:
        if strict:
            raise ValueError(f"Role '{role}' not present in bundle.data")
        # best effort: allow primary
        if role == "disp" and "primary" in ctx.data:
            return ctx.data["primary"]
        raise ValueError(f"Role '{role}' not present in bundle.data")
    arr = ctx.data[role]
    if not isinstance(arr, np.ndarray) or arr.ndim != 2:
        raise ValueError(f"bundle.data['{role}'] must be a 2D numpy array")
    return arr.astype(np.float64, copy=False)


def _resolve_trigger_time_s(events: pd.DataFrame, *, trigger_id: str, strict: bool) -> np.ndarray:
    """
    Resolve a trigger_id to absolute session time for each event row.

    Resolution order (v0):
      1) If trigger_id matches the primary trigger concept (common convention):
         - 'rebound_start' is treated as primary trigger for rebounds.
      2) If events has a flat column '{trigger_id}_time_s', use it.
      3) If events.meta contains triggers: meta['triggers'][trigger_id]['time_s'].
      4) If strict=False, fall back:
         - '*_start' -> start_time_s
         - '*_end'   -> end_time_s
         - else      -> trigger_time_s
    """
    n = len(events)

    # (1) Common convention: rebound_start == primary trigger (your schema uses it this way)
    if trigger_id == "rebound_start" and "trigger_time_s" in events.columns:
        return events["trigger_time_s"].to_numpy(dtype=np.float64, copy=False)

    # (2) Flat column naming
    flat = f"{trigger_id}_time_s"
    if flat in events.columns:
        return events[flat].to_numpy(dtype=np.float64, copy=False)

    # (3) meta.triggers bag
    if "meta" in events.columns:
        out = np.full(n, np.nan, dtype=np.float64)
        for i, meta in enumerate(events["meta"].tolist()):
            if isinstance(meta, dict):
                tr = meta.get("triggers")
                if isinstance(tr, dict):
                    tinfo = tr.get(trigger_id)
                    if isinstance(tinfo, dict) and "time_s" in tinfo:
                        out[i] = float(tinfo["time_s"])
        if np.isfinite(out).all():
            return out
        if strict:
            bad = int(np.sum(~np.isfinite(out)))
            raise ValueError(f"Missing trigger '{trigger_id}' time_s for {bad}/{n} events (meta.triggers)")

    # (4) Fallbacks
    if not strict:
        if trigger_id.endswith("_start") and "start_time_s" in events.columns:
            return events["start_time_s"].to_numpy(dtype=np.float64, copy=False)
        if trigger_id.endswith("_end") and "end_time_s" in events.columns:
            return events["end_time_s"].to_numpy(dtype=np.float64, copy=False)
        if "trigger_time_s" in events.columns:
            return events["trigger_time_s"].to_numpy(dtype=np.float64, copy=False)

    raise ValueError(f"Could not resolve trigger_id='{trigger_id}' to per-event time_s")


def _moving_average_2d(y: np.ndarray, win: int) -> np.ndarray:
    """Simple moving average along axis=1, NaN-aware-ish (fills NaN as 0 with weights)."""
    if win <= 1:
        return y

    # weights
    w = np.ones(win, dtype=np.float64)

    y0 = np.nan_to_num(y, nan=0.0)
    m = np.isfinite(y).astype(np.float64)

    # Convolve each row
    out = np.empty_like(y0, dtype=np.float64)
    out_m = np.empty_like(m, dtype=np.float64)

    for i in range(y0.shape[0]):
        out[i] = np.convolve(y0[i], w, mode="same")
        out_m[i] = np.convolve(m[i], w, mode="same")

    with np.errstate(invalid="ignore", divide="ignore"):
        out = out / np.where(out_m == 0, np.nan, out_m)

    return out


def _reduce_interval(y: np.ndarray, i0: np.ndarray, i1: np.ndarray, reducer) -> np.ndarray:
    n = y.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    for r in range(n):
        a = int(i0[r]); b = int(i1[r])
        if b <= a:
            continue
        out[r] = float(reducer(y[r, a:b]))
    return out


def _delta_interval(y: np.ndarray, i0: np.ndarray, i1: np.ndarray) -> np.ndarray:
    n = y.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    for r in range(n):
        a = int(i0[r]); b = int(i1[r])
        if b <= a:
            continue
        # Use last included sample as end
        end_idx = max(a, b - 1)
        out[r] = float(y[r, end_idx] - y[r, a])
    return out


def _integral_interval(y: np.ndarray, i0: np.ndarray, i1: np.ndarray, grid: np.ndarray) -> np.ndarray:
    n = y.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    for r in range(n):
        a = int(i0[r]); b = int(i1[r])
        if b <= a:
            continue
        out[r] = float(np.trapz(y[r, a:b], grid[a:b]))
    return out
