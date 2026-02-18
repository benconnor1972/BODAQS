from __future__ import annotations
from typing import Dict, Any, List, Optional, Sequence, Tuple, Union
import numpy as np
import pandas as pd
from .signalname import parse_signal_name, format_signal_name, SignalNameParts
from .signalspec import DEFAULT_SPEC
import re

TIME_COL_CANDIDATES_DEFAULT = ("time_s","t","time","timestamp","ts_ms","ts","Time","Timestamp")
_UNIT_RE = re.compile(r"\s*\[(.*?)\]\s*$")

def _set_unit(col: str, unit: str) -> str:
    # Replace trailing " [..]" if present; else append.
    if _UNIT_RE.search(col):
        return _UNIT_RE.sub(f" [{unit}]", col)
    return f"{col} [{unit}]"

def _name_zeroed_norm(col: str) -> str:
    # Unitless result, and encode both ops explicitly
    base_u1 = _set_unit(col, "1")
    return f"{base_u1}_op_zeroed_op_norm"

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

def _name_zeroed(col: str) -> str:
    """Given an engineered signal like 'front_shock [mm]', return 'front_shock [mm]_op_zeroed'."""
    parts = parse_signal_name(col, spec=DEFAULT_SPEC)
    if parts.kind != "":
        raise ValueError(f"zeroing expects engineered signal (kind=''), got {col!r}")
    if parts.unit is None:
        raise ValueError(f"zeroing expects engineered signal with unit, got {col!r}")

    return format_signal_name(
        SignalNameParts(
            base=parts.base,
            kind="",
            domain=parts.domain,
            unit=parts.unit,
            ops=tuple(list(parts.ops) + ["zeroed"]),
        ),
        spec=DEFAULT_SPEC,
    )


def _name_norm(col: str) -> str:
    """
    Given an engineered signal like:
      - 'front_shock_dom_suspension [mm]'
      - 'front_shock_dom_suspension [mm]_op_zeroed'
    return a dimensionless normalised signal that keeps the SAME base (so quantity stays 'disp'),
    changes unit to '1', and appends op 'norm'.

    Examples:
      - base -> 'front_shock_dom_suspension [1]_op_norm'
      - zeroed -> 'front_shock_dom_suspension [1]_op_zeroed_op_norm'   (encodes both ops)
    """
    parts = parse_signal_name(col, spec=DEFAULT_SPEC)
    if parts.kind != "":
        raise ValueError(f"norm expects engineered signal (kind=''), got {col!r}")

    # Keep base unchanged -> quantity remains 'disp'
    # Append 'norm' to ops (preserving any existing ops like 'zeroed')
    return format_signal_name(
        SignalNameParts(
            base=parts.base,
            kind="",
            domain=parts.domain,
            unit="1",  # dimensionless
            ops=tuple(list(parts.ops) + ["norm"]),
        ),
        spec=DEFAULT_SPEC,
    )


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
    zero_window_s: float = 0.002,
    zero_per_segment: bool = False,
    segment_col: str = "segment_id",
    min_samples_abs_min: int =1,
    clip_0_1: bool = False,
    output_suffix_norm: str = "_norm",
    use_median_window: bool = True,
    return_meta: bool = False,
) -> Union[pd.DataFrame, Tuple[pd.DataFrame, Dict[str, Any]]]:
    """
    Zero (in-place, optional) and scale selected columns.

    Public contract:
    - Returns a DataFrame by default.
    - If return_report=True, returns (new_df, meta).
    - meta contains per-column zeroing/scaling details and timebase info used for windowing.
    - For each col in `ranges` (if present & numeric):
        - If zeroing_enabled: writes <col>_op_zeroed
        - Writes <base>_norm [1]
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

    per_column: List[Dict[str, Any]] = []

    use_segments = bool(zero_per_segment and segment_col in frame.columns)
    segments = frame[segment_col].unique().tolist() if use_segments else [None]

    for col, full_range in ranges.items():
        if col not in frame.columns:
            per_column.append({"column": col, "status": "missing"})
            continue

        s = pd.to_numeric(frame[col], errors="coerce")
        if s.dropna().empty:
            per_column.append({"column": col, "status": "non_numeric_or_empty"})
            continue

        meta: Dict[str, Any] = {}
        offset: float = 0.0
        segment_offsets: Optional[Dict[Any, float]] = None

        if not zeroing_enabled:
            zeroed = s.astype(float)
            meta = {"method": "zeroing_disabled"}
        else:
            if not use_segments:
                info = _min_window_avg_offset(
                    frame, col, np.asarray(t_s, dtype=float), zero_window_s,
                    use_median_window, min_samples
                )
                if info is None:
                    offset = float(s.dropna().iloc[0])
                    meta = {"method": "fallback_first_value", "offset": offset}
                else:
                    offset = float(info["offset"])
                    meta = {"method": "min_window_avg", **info}

                zeroed = (s - offset).astype(float)

            else:
                segment_offsets = {}
                zeroed = pd.Series(np.nan, index=frame.index, dtype=float)

                for seg in segments:
                    mask = frame[segment_col] == seg
                    seg_df = frame.loc[mask]
                    seg_t = np.asarray(t_s, dtype=float)[mask.to_numpy()]

                    info = _min_window_avg_offset(
                        seg_df, col, seg_t, zero_window_s,
                        use_median_window, min_samples
                    )
                    if info is None:
                        off = float(s.loc[mask].dropna().iloc[0]) if s.loc[mask].dropna().size else 0.0
                    else:
                        off = float(info["offset"])
                    segment_offsets[seg] = off
                    zeroed.loc[mask] = s.loc[mask] - off

                meta = {"method": "per_segment"}
        print(offset)
        # Always write zeroed back into base col if zeroing_enabled (in-place zeroing policy)
        zeroed_col = None
        if zeroing_enabled:
            # --- Create explicit zeroed column (no in-place overwrite) ---
            zeroed_col = _name_zeroed(col)
            frame.loc[:, zeroed_col] = zeroed

            # --- Create dimensionless norm column (encode both ops) ---
            # choose source for normalization (zeroed if enabled, else base)
            norm_source = zeroed_col if (zeroed_col is not None) else col

            # Name reflects the transform chain applied to the source.
            # If source is zeroed, output becomes ...[1]_op_zeroed_op_norm (both ops encoded).
            norm_col = _name_norm(norm_source)

            rng = float(full_range) if full_range else np.nan
            if np.isfinite(rng) and rng > 0:
                normed = frame[norm_source] / rng
            else:
                normed = np.nan

            if clip_0_1:
                normed = normed.clip(0.0, 1.0)

            frame.loc[:, norm_col] = normed



        rec: Dict[str, Any] = {
            "column": col,
            "status": "ok",
            "full_range": float(full_range),
            "clip_0_1": bool(clip_0_1),
            "zeroing": {
                "enabled": bool(zeroing_enabled),
                "per_segment": bool(use_segments),
                "method": meta.get("method") if isinstance(meta, dict) else None,
                "window_s": float(zero_window_s),
                "use_median_window": bool(use_median_window),
                "min_samples": int(min_samples),
            },
            "meta": meta,
        }

        if not zeroing_enabled:
            rec["zeroing"]["offset"] = 0.0
        elif not use_segments:
            rec["zeroing"]["offset"] = float(offset)
        else:
            rec["zeroing"]["segment_offsets"] = segment_offsets

        per_column.append(rec)
    
    if not return_meta:
        return frame

    meta_out: Dict[str, Any] = {
        "per_column": per_column,
        "time_col": tcol,
        "dt_s": float(dt_use),
        "zero_window_s": float(zero_window_s),
        "zero_per_segment": bool(use_segments),
        "segment_col": segment_col if use_segments else None,
        "min_samples": int(min_samples),
    }
    return frame, meta_out



