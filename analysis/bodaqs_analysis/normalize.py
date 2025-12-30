from __future__ import annotations
from typing import Dict, Any, List, Optional, Sequence, Tuple
import numpy as np
import pandas as pd

TIME_COL_CANDIDATES_DEFAULT = ("time_s","t","time","timestamp","ts_ms","ts","Time","Timestamp")

def _find_time_col(frame: pd.DataFrame):
    for c in TIME_COL_CANDIDATES:
        if c in frame.columns:
            return c
    if isinstance(frame.index, (pd.DatetimeIndex, pd.TimedeltaIndex)):
        return None
    return None

def _ensure_time_seconds(frame: pd.DataFrame, tcol: str | None):
    if tcol and tcol in frame.columns:
        s = frame[tcol]
        if np.issubdtype(s.dtype, np.number):
            return s.to_numpy(dtype=float)
        try:
            dt = pd.to_datetime(s, errors="coerce")
            if not dt.isna().all():
                t0 = dt.iloc[0]
                return (dt - t0).dt.total_seconds().to_numpy()
        except Exception:
            pass
    idx = frame.index
    if isinstance(idx, pd.DatetimeIndex):
        return (idx - idx[0]).total_seconds()
    if isinstance(idx, pd.TimedeltaIndex):
        return (idx - idx[0]).total_seconds()
    n = len(frame)
    return np.arange(n, dtype=float) if n > 1 else np.array([0.0])

def _median_dt_seconds(t: np.ndarray):
    dt = np.diff(t)
    dt = dt[(dt > 0) & np.isfinite(dt)]
    return float(np.median(dt)) if dt.size else np.nan

def _min_window_avg_offset(seg_df: pd.DataFrame, value_col: str, t_s: np.ndarray,
                           window_s: float, use_median: bool, min_samples: int):
    y = pd.to_numeric(seg_df[value_col], errors="coerce").to_numpy()
    ok = np.isfinite(t_s) & np.isfinite(y)
    t = t_s[ok]; y = y[ok]
    if t.size == 0:
        return None
    order = np.argsort(t)
    t = t[order]; y = y[order]
    i = 0
    best_val, best_i, best_j = np.inf, None, None
    for j in range(len(t)):
        while t[j] - t[i] > window_s and i < j:
            i += 1
        count = j - i + 1
        if count >= min_samples:
            w = y[i:j+1]
            val = float(np.median(w)) if use_median else float(np.mean(w))
            if val < best_val:
                best_val, best_i, best_j = val, i, j
    if best_i is None:
        return None
    return {
        "offset": best_val,
        "t_start": float(t[best_i]),
        "t_end": float(t[best_j]),
        "n_samples": int(best_j - best_i + 1),
    }

def normalize_and_scale(
    df: pd.DataFrame,
    ranges: Dict[str, float],
    *,
    time_col_candidates: Sequence[str] = TIME_COL_CANDIDATES_DEFAULT,
    zeroing_enabled: bool = True,
    zero_window_s: float = 1.0,
    zero_per_segment: bool = False,
    segment_col: str = "segment_id",
    min_samples_abs_min: int = 10,
    clip_0_1: bool = False,
    add_zeroed_column: bool = True,
    in_place_zero: bool = False,
    output_suffix_norm: str = "_norm",
    output_suffix_zeroed: str = "_zeroed",
    use_median_window: bool = True,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Zero (optionally) and scale selected columns.

    Contract:
    - Always produces <col>_norm for cols in `ranges` (when col exists and is numeric).
    - If in_place_zero=True: writes zeroed data back into the base column <col>.
      Otherwise, if add_zeroed_column=True: writes <col>_zeroed.
    - Returns (new_df, report) where report contains offsets and method metadata.
    """
    frame = df.copy()

    # Configure time candidates for helper (your _find_time_col uses a global)
    global TIME_COL_CANDIDATES
    TIME_COL_CANDIDATES = list(time_col_candidates)

    # Time base for windowing
    tcol = _find_time_col(frame)
    t_s = _ensure_time_seconds(frame, tcol)
    dt_est = _median_dt_seconds(np.asarray(t_s, dtype=float))
    dt_fallback = 0.01
    dt_use = dt_est if np.isfinite(dt_est) and dt_est > 0 else dt_fallback
    min_samples = max(int(min_samples_abs_min), int(np.ceil(zero_window_s / dt_use)))

    report: List[Dict[str, Any]] = []

    use_segments = bool(zero_per_segment and segment_col in frame.columns)
    segments = frame[segment_col].unique().tolist() if use_segments else [None]

    for col, full_range in ranges.items():
        if col not in frame.columns:
            report.append({"column": col, "status": "missing"})
            continue

        s = pd.to_numeric(frame[col], errors="coerce")
        if s.dropna().empty:
            report.append({"column": col, "status": "non_numeric_or_empty"})
            continue

        # --- Compute zeroed series + metadata ---
        meta: Dict[str, Any] = {}
        offset: float = 0.0
        segment_offsets: Optional[Dict[Any, float]] = None

        if not zeroing_enabled:
            # No zeroing: treat as offset=0
            zeroed = s.astype(float)
            meta = {"method": "zeroing_disabled"}
        else:
            if not use_segments:
                info = _min_window_avg_offset(frame, col, np.asarray(t_s, dtype=float), zero_window_s,
                                              use_median_window, min_samples)
                if info is None:
                    offset = float(s.dropna().iloc[0])
                    meta = {"method": "fallback_first_value", "offset": offset}
                else:
                    offset = float(info["offset"])
                    meta = {"method": "min_window_avg", **info}

                zeroed = (s - offset).astype(float)

            else:
                # Per-segment offsets
                segment_offsets = {}
                zeroed = pd.Series(np.nan, index=frame.index, dtype=float)

                for seg in segments:
                    mask = frame[segment_col] == seg
                    seg_df = frame.loc[mask]
                    seg_t = np.asarray(t_s, dtype=float)[mask.to_numpy()]

                    info = _min_window_avg_offset(seg_df, col, seg_t, zero_window_s,
                                                  use_median_window, min_samples)
                    if info is None:
                        off = float(s.loc[mask].dropna().iloc[0]) if s.loc[mask].dropna().size else 0.0
                    else:
                        off = float(info["offset"])
                    segment_offsets[seg] = off
                    zeroed.loc[mask] = s.loc[mask] - off

                meta = {"method": "per_segment"}

        # --- Compute norm ---
        norm = zeroed / float(full_range)
        if clip_0_1:
            norm = norm.clip(0.0, 1.0)

        # --- Write outputs ---
        if in_place_zero:
            frame.loc[:, col] = zeroed
        elif add_zeroed_column:
            frame.loc[:, col + output_suffix_zeroed] = zeroed

        frame.loc[:, col + output_suffix_norm] = norm

        # --- Report ---
        rec: Dict[str, Any] = {
            "column": col,
            "status": "ok",
            "full_range": float(full_range),
            "zeroing_enabled": bool(zeroing_enabled),
            "clip_0_1": bool(clip_0_1),
            "in_place_zero": bool(in_place_zero),
            "add_zeroed_column": bool(add_zeroed_column),
            "meta": meta,
        }
        if not use_segments:
            rec["offset"] = float(offset) if zeroing_enabled else 0.0
        else:
            rec["segment_offsets"] = segment_offsets

        report.append(rec)

    return frame, report

