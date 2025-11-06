# -*- coding: utf-8 -*-
"""
Rebound metrics using velocity zero-crossing with hysteresis and dwell.

Usage (in your events cell / notebook):
    from rebound_metrics import compute_rebound_metrics as _compute_rebound_metrics
"""

from __future__ import annotations
import numpy as np
import pandas as pd

__all__ = ["compute_rebound_metrics"]

def _to_seconds(t_like: pd.Series | np.ndarray) -> np.ndarray:
    """Robust seconds conversion from a 't' column that might be datetime or numeric."""
    if isinstance(t_like, pd.Series):
        t_like = t_like.to_numpy()
    t_like = np.asarray(t_like)
    if np.issubdtype(t_like.dtype, np.datetime64):
        # convert to seconds from the first timestamp
        t0 = t_like[0]
        return (t_like - t0).astype("timedelta64[ns]").astype(np.float64) * 1e-9
    return t_like.astype(np.float64, copy=False)

def _movavg_edge_safe(x: np.ndarray, win: int) -> np.ndarray:
    """Simple edge-safe moving average (uniform) for small-window smoothing."""
    if win <= 1:
        return x
    if win % 2 == 0:
        win += 1
    pad = win // 2
    xr = np.pad(x, (pad, pad), mode="edge")
    ker = np.ones(win, dtype=float) / float(win)
    return np.convolve(xr, ker, mode="valid")

def compute_rebound_metrics(
    t: np.ndarray,
    seg: pd.DataFrame,
    inputs: dict,
    t0_idx: int,
    start_idx: int,
    end_idx: int,
    *,
    dt: float,
    disp_signal: str = "disp",
    vel_signal: str = "vel",
    max_rebound_s: float = 1.0,
    smooth_ms: float | int | None = 10,
    fit_tau: bool = True,
    min_delay_s: float = 0.02,
    # --- Hysteresis & dwell (velocity units, e.g., mm/s) ---
    zero_band: float = 3.0,     # relaxed
    neg_band: float  = 2.0,     # relaxed
    pos_band: float  = 2.0,     # relaxed
    pre_neg_samples: int = 2,   # relaxed
    dwell_pos_samples: int = 2, # relaxed
    polarity: str = "neg_to_pos",     # 'neg_to_pos', 'pos_to_neg', or 'auto'
    return_debug: bool = False, # optional: include debug info in output
    **_deprecated,
) -> dict:
    out = {
        "m_rebound_found_min": False,
        "m_rebound_n_pts": 0,
        "m_rebound_v_max": np.nan,
        "m_rebound_v_min": np.nan,
        "m_rebound_v_mean": np.nan,
        "m_rebound_t_to_min": np.nan,
        "m_rebound_disp_drop": np.nan,
        "m_rebound_tau": None,
        "m_rebound_tau_r2": None,
        "m_rebound_method": "unknown",
    }
    if return_debug:
        out["m_rebound_debug"] = {"dead_idx": None, "win": None, "tried": []}

    disp_col = inputs.get(disp_signal)
    vel_col  = inputs.get(vel_signal)
    if (disp_col not in seg.columns) or (vel_col not in seg.columns):
        return out

    # Time & series
    t_seg = _to_seconds(seg["t"])
    x_seg = seg[disp_col].to_numpy(dtype=float)
    v_seg = seg[vel_col].to_numpy(dtype=float)

    t0_rel = t0_idx - start_idx
    if t0_rel < 0 or t0_rel >= len(seg):
        return out
    t0_time = t_seg[t0_rel]

    # search window
    if (max_rebound_s is None) or (not np.isfinite(max_rebound_s)) or (max_rebound_s <= 0):
        time_mask = (t_seg > t0_time)
    else:
        time_mask = (t_seg > t0_time) & (t_seg <= t0_time + float(max_rebound_s))

    idxs = np.nonzero(time_mask)[0]
    if idxs.size == 0:
        return out
    lo, hi = int(idxs.min()), int(idxs.max())

    x_search = x_seg[lo:hi+1].astype(float, copy=False)
    v_search = v_seg[lo:hi+1].astype(float, copy=False)
    t_search = t_seg[lo:hi+1]

    # smooth v if requested
    v_filt = v_search
    win = None
    if smooth_ms and np.isfinite(smooth_ms) and (smooth_ms > 0) and np.isfinite(dt) and (dt > 0):
        win = int(round((float(smooth_ms) / 1000.0) / float(dt)))
        if win > 1:
            v_filt = _movavg_edge_safe(v_search, win)

    # dead-time after t0
    dead_idx = 0
    if np.isfinite(min_delay_s) and (min_delay_s > 0) and np.isfinite(dt) and (dt > 0):
        dead_idx = max(dead_idx, int(np.floor(min_delay_s / dt)))
    dead_idx = max(1, dead_idx)

    if return_debug:
        out["m_rebound_debug"].update({"dead_idx": int(dead_idx), "win": int(win or 1)})

    def _find_crossing(v: np.ndarray, direction: str):
        # direction: 'neg_to_pos' or 'pos_to_neg'
        # Returns index k where |v[k]| <= zero_band and dwell satisfied, else None
        n = len(v)
        i = dead_idx
        tried_steps = 0
        if direction == "neg_to_pos":
            pre_band = -float(neg_band)
            post_band = +float(pos_band)
            pre_cmp = lambda arr: arr <= pre_band
            post_cmp = lambda arr: arr >= post_band
        else:  # 'pos_to_neg'
            pre_band = +float(pos_band)
            post_band = -float(neg_band)
            pre_cmp = lambda arr: arr >= pre_band
            post_cmp = lambda arr: arr <= post_band

        while i < n:
            j = i + pre_neg_samples - 1
            if j >= n:
                break
            if np.all(pre_cmp(v[i:j+1])):
                k = j + 1
                while k < n and abs(v[k]) > float(zero_band):
                    k += 1
                if k >= n:
                    break
                # linger-tolerant: allow staying in zero_band, then require dwell whenever it arrives
                m = k + 1
                pos_count = 0
                while m < n:
                    vm = v[m]
                    # if we regress strongly back to the pre side, abort this attempt and resume scanning
                    if (direction == "neg_to_pos" and vm <= -float(neg_band)) or \
                       (direction == "pos_to_neg" and vm >=  float(pos_band)):
                        i = m
                        break
                    # still in zero band → keep waiting
                    if abs(vm) <= float(zero_band):
                        m += 1
                        continue
                    # count dwell once we leave the zero band to the post side
                    if (direction == "neg_to_pos" and vm >= float(pos_band)) or \
                       (direction == "pos_to_neg" and vm <= -float(neg_band)):
                        pos_count += 1
                        if pos_count >= dwell_pos_samples:
                            return int(k)  # accept crossing at first zero-band index
                    else:
                        pos_count = 0
                    m += 1
                else:
                    i = k + 1

            else:
                i += 1
            tried_steps += 1
        return None

    tried_dirs = []
    dirs = ["neg_to_pos"] if polarity == "neg_to_pos" else \
           ["pos_to_neg"] if polarity == "pos_to_neg" else \
           ["neg_to_pos", "pos_to_neg"]

    cross_rel = None
    for d in dirs:
        tried_dirs.append(d)
        cross_rel = _find_crossing(v_filt, d)
        if cross_rel is not None:
            direction_used = d
            break

    if return_debug:
        out["m_rebound_debug"]["tried"] = tried_dirs

    if cross_rel is None:
        return out

    min_idx_seg = lo + int(cross_rel)
    if (min_idx_seg <= t0_rel) or (min_idx_seg >= len(seg)):
        return out

    # Metrics on [t0..min_idx_seg]
    y_v = v_seg[t0_rel:min_idx_seg+1]
    y_x = x_seg[t0_rel:min_idx_seg+1]
    t_r = t_seg[t0_rel:min_idx_seg+1] - t0_time

    out["m_rebound_found_min"] = True
    out["m_rebound_method"]    = f"vel_zero_cross[{direction_used}]"
    out["m_rebound_n_pts"]     = int(len(y_v))
    out["m_rebound_v_max"]     = float(np.nanmax(y_v)) if y_v.size else np.nan
    out["m_rebound_v_min"]     = float(np.nanmin(y_v)) if y_v.size else np.nan
    out["m_rebound_v_mean"]    = float(np.nanmean(y_v)) if y_v.size else np.nan
    out["m_rebound_t_to_min"]  = float(t_seg[min_idx_seg] - t0_time)
    out["m_rebound_disp_drop"] = float(y_x[0] - y_x[-1])

    # optional tau fit identical to your previous code…
    if fit_tau and y_x.size >= 3:
        x0   = float(y_x[0]); xMin = float(y_x[-1]); amp  = x0 - xMin
        if np.isfinite(amp) and amp > 0:
            mask = (y_x > xMin) & np.isfinite(y_x) & np.isfinite(t_r)
            if np.count_nonzero(mask) >= 3:
                y = np.log((y_x[mask] - xMin) / amp); x = t_r[mask]
                b, a = np.polyfit(x, y, 1)
                tau = -1.0 / b if np.isfinite(b) and (b != 0) else np.nan
                y_hat = a + b * x
                ss_res = float(np.nansum((y - y_hat) ** 2))
                ss_tot = float(np.nansum((y - np.nanmean(y)) ** 2))
                r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else np.nan
                out["m_rebound_tau"]    = float(tau) if np.isfinite(tau) else None
                out["m_rebound_tau_r2"] = float(r2)  if np.isfinite(r2)  else None

    return out

