from __future__ import annotations
from typing import Optional, Tuple
import numpy as np
import pandas as pd

def _derive_time_seconds(df: pd.DataFrame) -> np.ndarray:
    # Prefer numeric time column if present
    for c in ("t", "time_s"):
        if c in df.columns and np.issubdtype(df[c].dtype, np.number):
            return df[c].to_numpy(dtype=float)
    # Otherwise try common timestamp names
    for c in ("timestamp", "time"):
        if c in df.columns:
            s = df[c]
            if np.issubdtype(s.dtype, np.datetime64) or s.dtype == object:
                dt = pd.to_datetime(s, utc=False, errors="coerce")
                if dt.isna().all():
                    continue
                t0 = dt.iloc[0]
                return (dt - t0).dt.total_seconds().to_numpy()
    # Fallback: datetime-like index
    idx = df.index
    if isinstance(idx, (pd.DatetimeIndex, pd.TimedeltaIndex)):
        return (idx - idx[0]).total_seconds()
    # Last resort: unit steps (we'll still compute dt)
    n = len(df)
    if n > 1:
        return np.arange(n, dtype=float)
    raise RuntimeError("Could not infer time base: provide a 't' or 'time_s' column, or a datetime index.")

def _repair_monotonic(t: np.ndarray, dt_hint=None, min_step_factor=0.5):
    t = np.asarray(t, dtype=float).copy()
    diffs = np.diff(t)
    if dt_hint is None:
        finite = diffs[np.isfinite(diffs)]
        if finite.size:
            finite_pos = finite[(finite > 0) & (finite < np.nanpercentile(finite, 95))]
            median_dt = float(np.nanmedian(finite_pos)) if finite_pos.size else 0.0
        else:
            median_dt = 0.0
    else:
        median_dt = float(dt_hint)
    min_step = median_dt * float(min_step_factor) if median_dt > 0 else 0.0

    bumps = 0
    total_added = 0.0
    for i in range(1, len(t)):
        if t[i] + 1e-12 < t[i-1]:
            bump = (t[i-1] - t[i]) + (min_step if min_step > 0 else 0.0)
            t[i:] += bump
            total_added += bump
            bumps += 1
    return t, bumps, total_added, median_dt

def _mark_gaps(t: np.ndarray, gap_factor=10.0, gap_min_s=None):
    dt = np.diff(t, prepend=t[0])
    finite = dt[np.isfinite(dt)]
    med = float(np.nanmedian(finite[finite > 0])) if np.any(finite > 0) else 0.0
    thr = max(gap_min_s or 0.0, (gap_factor * med) if med > 0 else 0.0)
    gap_mask = (dt > thr) if thr > 0 else np.zeros_like(dt, dtype=bool)
    gap_mask[0] = False
    segment_id = np.cumsum(gap_mask).astype(int)
    return gap_mask, segment_id, thr

def _insert_plot_breaks(df: pd.DataFrame, gap_mask: np.ndarray, value_cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    if value_cols:
        num_cols = [c for c in value_cols if not pd.api.types.is_bool_dtype(out[c])]
        out.loc[gap_mask, num_cols] = np.nan
    return out