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

    - Metric columns are those prefixed with 'm_' (and 'd_' if present).
    - Preserves event identity columns if present.
    - Contract-aligned projection only (no inference, no synthesis).
    """
    if events_df is None or len(events_df) == 0:
        return pd.DataFrame()

    # Unified rule: session_id + event_id are required identity/join keys
    for k in ("session_id", "event_id"):
        if k not in events_df.columns:
            raise ValueError(f"events_df missing required column '{k}'")


    # Metric + debug columns
    metric_cols = [
        c for c in events_df.columns
        if isinstance(c, str) and (c.startswith("m_") or c.startswith("d_"))
    ]

    # Explicit forbidden columns (contract)
    forbidden = {"start_idx", "end_idx", "start_time_s", "end_time_s"}

    if id_cols is None:
        # All identity-like columns we are willing to preserve
        identity_candidates = (
            # Required join keys (unified rule)
            "session_id",
            "event_id",


            # Contract identity bundle
            "schema_id",
            "schema_version",
            "event_name",
            "signal",
            "signal_col",
            "segment_id",
            "trigger_time_s",
            "trigger_datetime",
            "tags",

            # Legacy identity
            "event_type",
            "sensor",
            "t0_time",
            "t0_index",
            "start_index",
            "end_index",
        )

        id_cols = [
            c for c in identity_candidates
            if c in events_df.columns and c not in forbidden
        ]
    else:
        id_cols = [c for c in id_cols if c in events_df.columns and c not in forbidden]

    keep = list(dict.fromkeys(id_cols + metric_cols))  # preserve order, de-dupe

    return events_df.loc[:, keep].copy()



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
        If True, missing triggers raise ValueError.
        If False, missing triggers yield NaNs (no legacy fallback sources are used).

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
        return pd.DataFrame()

    ev = events_all.iloc[seg_valid["event_row"].to_numpy()].reset_index(drop=True)
    # Unified rule: session_id must be present for identity/join semantics
    if "session_id" not in ev.columns:
        raise ValueError("bundle['events'] missing required column: session_id")


    # Validate data shapes
    t_rel_2d = data.get("t_rel_s", None)
    if not isinstance(t_rel_2d, np.ndarray) or t_rel_2d.ndim != 2:
        raise ValueError("bundle.data['t_rel_s'] must be a 2D numpy array")

    # Must match (n_seg, n_samp) shape contract
    n_seg = len(seg_valid)
    if t_rel_2d.shape[0] != n_seg:
        raise ValueError(
            f"bundle.data['t_rel_s'] has shape {t_rel_2d.shape}, expected first dim == n_valid_segments ({n_seg}). "
            "This often indicates a transposed t_rel_s array."
        )

    t_rel = t_rel_2d[0].astype(np.float64, copy=False)
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
                if strict:
                    raise ValueError(f"Metric implementation returned non-prefixed column: {name}")
                out_cols[f"m_{name}"] = values

    # Build output dataframe: identity bundle + m_* + optional debug
    id_cols = _preferred_identity_cols(ctx.events)
    # Force unified join key presence at the front (without duplicating)
    if "session_id" in ctx.events.columns:
        id_cols = ["session_id"] + [c for c in id_cols if c != "session_id"]
    metrics_df = ctx.events[id_cols].copy()

    for name, values in out_cols.items():
        metrics_df[name] = values

    for name, values in dbg_cols.items():
        metrics_df[name] = values

    if len(metrics_df) != n_seg:
        raise AssertionError("metrics_df row count must equal number of valid segments")

    return metrics_df


compute_metrics = compute_metrics_from_segments


# -------------------------
# Metric implementations
# -------------------------

def _metric_peak(ctx: MetricsContext, spec: Mapping[str, Any], *, strict: bool) -> Dict[str, np.ndarray]:
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

    # Trigger times in absolute session time (NO legacy fallbacks; NO meta fallbacks)
    t0_abs = _resolve_trigger_time_s(ctx.events, trigger_id=start_tr, strict=strict)
    t1_abs = _resolve_trigger_time_s(ctx.events, trigger_id=end_tr, strict=strict)

    if "trigger_time_s" not in ctx.segments.columns:
        raise ValueError("segments table must contain 'trigger_time_s' (alignment time)")

    align_abs = ctx.segments["trigger_time_s"].to_numpy(dtype=np.float64, copy=False)

    if min_delay_s > 0:
        t0_abs = np.maximum(t0_abs, align_abs + min_delay_s)

    t0_rel = t0_abs - align_abs
    t1_rel = t1_abs - align_abs

    swapped = t1_rel < t0_rel
    if np.any(swapped):
        tmp = t0_rel.copy()
        t0_rel[swapped] = t1_rel[swapped]
        t1_rel[swapped] = tmp[swapped]

    grid = ctx.t_rel_s
    i0 = np.searchsorted(grid, t0_rel, side="left")
    i1 = np.searchsorted(grid, t1_rel, side="right")

    i0 = np.clip(i0, 0, len(grid) - 1)
    i1 = np.clip(i1, 0, len(grid))

    if smooth_ms and smooth_ms > 0:
        win = max(1, int(round((smooth_ms / 1000.0) / ctx.dt_s)))
        y_smooth = _moving_average_2d(y, win) if win > 1 else y
    else:
        y_smooth = y

    base_id = _metric_id(spec, fallback=f"interval_{role}")
    out: Dict[str, np.ndarray] = {}

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
        "session_id",   # unified rule: primary identity / aggregation key
        "event_id",
        "schema_id",
        "schema_version",
        "event_name",
        "signal",
        "signal_col",
        "segment_id",
        "trigger_time_s",
        "trigger_datetime",
        "tags",
    ]
    return [c for c in preferred if c in events.columns]



def _get_t_rel_grid(data: Mapping[str, Any]) -> np.ndarray:
    if "t_rel_s" not in data:
        raise ValueError("bundle.data must include 't_rel_s' for metrics")
    arr = data["t_rel_s"]
    if not isinstance(arr, np.ndarray) or arr.ndim != 2 or arr.shape[0] < 1:
        raise ValueError("bundle.data['t_rel_s'] must be a 2D array with at least one segment")
    return arr[0].astype(np.float64, copy=False)


def _estimate_dt(t_rel: np.ndarray) -> float:
    if t_rel.ndim != 1 or len(t_rel) < 3:
        raise ValueError("t_rel_s grid must be 1D with >= 3 samples")

    d = np.diff(t_rel.astype(np.float64, copy=False))
    d_f = d[np.isfinite(d)]
    if len(d_f) == 0:
        raise ValueError("Non-finite dt estimated from t_rel_s (all diffs non-finite)")

    dt = float(np.median(d_f))
    if dt <= 0 or not np.isfinite(dt):
        raise ValueError(
            "Non-positive dt estimated from t_rel_s. "
            f"dt={dt}, "
            f"t0={float(t_rel[0])}, tN={float(t_rel[-1])}, "
            f"diff_min={float(np.nanmin(d_f))}, diff_med={float(np.nanmedian(d_f))}, diff_max={float(np.nanmax(d_f))}"
        )
    return dt



def _schema_event_def_for_bundle(events: pd.DataFrame, schema: Mapping[str, Any], *, strict: bool) -> Mapping[str, Any]:
    schema_id = ""
    if "schema_id" in events.columns:
        ids = sorted(set(events["schema_id"].dropna().astype(str).tolist()))
        if len(ids) == 1:
            schema_id = ids[0]
        elif strict:
            raise ValueError(f"Expected one schema_id in bundle.events; got: {ids}")
        else:
            schema_id = ids[0] if ids else ""

    events_def = schema.get("events")
    if isinstance(events_def, list) and schema_id:
        for ev in events_def:
            if isinstance(ev, dict) and str(ev.get("id", "")) == schema_id:
                return ev

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
    return fallback.replace(" ", "_").replace("/", "_")


def _get_role_array(ctx: MetricsContext, role: str, *, strict: bool) -> np.ndarray:
    if role not in ctx.data:
        raise ValueError(f"Role '{role}' not present in bundle.data")
    arr = ctx.data[role]
    if not isinstance(arr, np.ndarray) or arr.ndim != 2:
        raise ValueError(f"bundle.data['{role}'] must be a 2D numpy array")
    return arr.astype(np.float64, copy=False)


def _resolve_trigger_time_s(events: pd.DataFrame, trigger_id: str, strict: bool) -> np.ndarray:
    """Resolve per-event trigger time in absolute session seconds.

    Policy (no backward compatibility):
    - Use ONLY:
        (a) canonical 'trigger_time_s' when trigger_id is 'trigger' or 'trigger_time_s'
        (b) per-trigger column f"{trigger_id}_time_s"
    - Do NOT look in meta bags.
    - Do NOT infer *_start/_end from other canonical columns.
    """
    n = len(events)

    if trigger_id in ("trigger", "trigger_time_s"):
        if "trigger_time_s" not in events.columns:
            raise ValueError("events table missing canonical column 'trigger_time_s'")
        v = events["trigger_time_s"].to_numpy(dtype=np.float64, copy=False)
        if strict:
            bad = int(np.sum(~np.isfinite(v)))
            if bad:
                raise ValueError(f"Missing canonical trigger_time_s for {bad}/{n} events")
        return v

    col = f"{trigger_id}_time_s"
    if col not in events.columns:
        if strict:
            raise ValueError(f"Missing required trigger column: {col}")
        return np.full(n, np.nan, dtype=np.float64)

    v = events[col].to_numpy(dtype=np.float64, copy=False)
    if strict:
        bad = int(np.sum(~np.isfinite(v)))
        if bad:
            raise ValueError(f"Missing trigger '{trigger_id}' time_s for {bad}/{n} events ({col})")
    return v


def _moving_average_2d(y: np.ndarray, win: int) -> np.ndarray:
    if win <= 1:
        return y

    w = np.ones(win, dtype=np.float64)

    y0 = np.nan_to_num(y, nan=0.0)
    m = np.isfinite(y).astype(np.float64)

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
