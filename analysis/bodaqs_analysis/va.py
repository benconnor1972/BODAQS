from __future__ import annotations
from typing import Iterable, Optional, Sequence, Tuple, List
import numpy as np
import pandas as pd

# Optional SciPy: used for Savitzky–Golay smoothing if available
try:
    from scipy.signal import savgol_filter  # type: ignore
    _HAVE_SCIPY = True
except Exception:
    _HAVE_SCIPY = False

def _infer_dt(df, sample_rate_hz=None, time_col="time_s"):
    """Infer dt (s) from explicit sample rate, a time column, or a DatetimeIndex."""
    if sample_rate_hz is not None:
        return 1.0 / float(sample_rate_hz)
    # try explicit time column
    if time_col and time_col in df.columns:
        t = pd.to_numeric(df[time_col], errors="coerce").to_numpy()
        dt = np.median(np.diff(t))
        if np.isfinite(dt) and dt > 0:
            return float(dt)
    # try a common alternative name
    if "t" in df.columns:
        t = pd.to_numeric(df["t"], errors="coerce").to_numpy()
        d = np.diff(t)
        d = d[(d > 0) & np.isfinite(d)]
        if d.size:
            return float(np.median(d))
    # try DatetimeIndex
    if isinstance(df.index, pd.DatetimeIndex):
        dt = pd.Series(df.index).diff().dt.total_seconds().median()
        if np.isfinite(dt) and dt > 0:
            return float(dt)
    raise ValueError("Cannot infer dt. Provide sample_rate_hz or a valid time column or DatetimeIndex.")

def _pick_cols(df, cols):
    """Pick numeric columns to process, excluding obvious time-like columns."""
    if cols is not None:
        return list(cols)
    drop_like = {"time", "timestamp", "date"}
    cands = []
    for c in df.select_dtypes(include=[np.number]).columns:
        lc = c.lower()
        if any(k in lc for k in drop_like):
            continue
        cands.append(c)
    if not cands:
        raise ValueError("No numeric columns found to process. Set 'cols' explicitly.")
    return cands

def _validate_params(window_points, poly_order):
    if window_points % 2 == 0:
        raise ValueError("window_points must be odd.")
    if poly_order >= window_points:
        raise ValueError("poly_order must be < window_points.")
    if poly_order < 1:
        raise ValueError("poly_order should be >= 1.")

def _savgol_numpy(y, window_points, poly_order, deriv, dt):
    """
    Minimal SG fallback using NumPy:
    - Build local polynomial basis (centered window),
    - Convolve with derivative coefficients,
    - Reflect-pad edges.
    """
    n = len(y)
    if n < window_points:
        # shrink to nearest odd <= n (keeps behaviour sane on very short slices)
        window_points = max(3, (n // 2) * 2 + 1)
        if poly_order >= window_points:
            poly_order = max(1, window_points - 1)

    half = window_points // 2
    x = np.arange(-half, half + 1, dtype=float)
    A = np.vander(x, N=poly_order + 1, increasing=True)  # columns: x^0..x^p
    pinv = np.linalg.pinv(A)
    coeff = pinv[deriv, :] * np.math.factorial(deriv)     # derivative at x=0
    scale = (dt ** (-deriv))

    # Reflect-pad
    left  = y[1:half+1][::-1] if n > 1 else np.array([y[0]] * half)
    right = y[-half-1:-1][::-1] if n > 1 else np.array([y[-1]] * half)
    ypad = np.r_[left, y, right]
    filt = np.convolve(ypad, coeff[::-1], mode="valid") * scale
    return filt

def estimate_va_from_zeroed(df,
                            cols=None,
                            sample_rate_hz=None,
                            time_col="time_s",
                            window_points=11,
                            poly_order=3,
                            vel_suffix="_vel",
                            acc_suffix="_acc",
                             strip_zeroed_suffix: bool = True):
    _validate_params(window_points, poly_order)
    dt = _infer_dt(df, sample_rate_hz=sample_rate_hz, time_col=time_col)
    target_cols = _pick_cols(df, cols)

    out = df.copy()
    # interpolate numeric gaps gently
    data = out[target_cols].apply(pd.to_numeric, errors="coerce").interpolate(limit_direction="both")

    for c in target_cols:
        y = data[c].to_numpy()
        if _HAVE_SCIPY:
            v = savgol_filter(y, window_points, poly_order, deriv=1, delta=dt, mode="interp")
            a = savgol_filter(y, window_points, poly_order, deriv=2, delta=dt, mode="interp")
        else:
            v = _savgol_numpy(y, window_points, poly_order, deriv=1, dt=dt)
            a = _savgol_numpy(y, window_points, poly_order, deriv=2, dt=dt)
        base = c[:-len('_zeroed')] if (strip_zeroed_suffix and c.endswith('_zeroed')) else c
        out[base + vel_suffix] = v
        out[base + acc_suffix] = a

    return out, {"dt": dt, "window_points": window_points, "poly_order": poly_order, "cols": target_cols}