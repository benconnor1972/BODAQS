from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


def resample_to_time_grid(
    df_src: pd.DataFrame,
    *,
    src_time_col: str,
    target_time_s: np.ndarray,
    columns: Optional[Sequence[str]] = None,
    method: str = "linear",
    allow_extrapolation: bool = False,
    max_gap_s: Optional[float] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Resample selected columns from df_src onto target_time_s.

    - Default method: linear interpolation on time.
    - Outside source time range -> NaN (unless allow_extrapolation=True).
    - If max_gap_s is set, interpolation is suppressed across larger source gaps.
    - Returns (df_out, meta)
    """
    if src_time_col not in df_src.columns:
        raise ValueError(f"df_src missing time column: {src_time_col}")

    t_src = pd.to_numeric(df_src[src_time_col], errors="coerce").to_numpy(dtype=float)
    if t_src.size < 2:
        raise ValueError("Source time vector too short")
    if not np.isfinite(t_src).all():
        raise ValueError("Source time contains non-finite values")

    # ensure monotonic non-decreasing
    if np.any(np.diff(t_src) < 0):
        # stable approach: sort
        order = np.argsort(t_src)
        t_src = t_src[order]
        df_src = df_src.iloc[order].reset_index(drop=True)

    if columns is None:
        # numeric-ish columns excluding time
        columns = [c for c in df_src.columns if c != src_time_col]

    gap_limit: Optional[float] = None
    if max_gap_s is not None:
        gap_limit = float(max_gap_s)
        if not np.isfinite(gap_limit) or gap_limit <= 0:
            raise ValueError("max_gap_s must be a positive finite value when provided")

    out = pd.DataFrame({"time_s": np.asarray(target_time_s, dtype=float)})

    # Range limits
    t_min = float(np.nanmin(t_src))
    t_max = float(np.nanmax(t_src))

    tgt = out["time_s"].to_numpy()
    finite_target = np.isfinite(tgt)
    column_meta: Dict[str, Any] = {}

    for c in columns:
        y = pd.to_numeric(df_src[c], errors="coerce").to_numpy(dtype=float)
        # interpolate only over finite samples
        good = np.isfinite(t_src) & np.isfinite(y)
        stats: Dict[str, Any] = {"n_source": int(good.sum())}
        if good.sum() < 2:
            out[c] = np.nan
            stats["n_output"] = 0
            column_meta[c] = stats
            continue

        t_g = t_src[good]
        y_g = y[good]

        y_out = np.full_like(tgt, np.nan, dtype=float)
        if allow_extrapolation:
            ok = finite_target.copy()
        else:
            # Use the finite time range for this column. This avoids clamping a
            # sparse column just because another source column has wider bounds.
            ok = (tgt >= t_g[0]) & (tgt <= t_g[-1]) & finite_target
        if gap_limit is not None:
            insertion = np.searchsorted(t_g, tgt, side="left")
            within_gap = np.zeros_like(tgt, dtype=bool)

            exact_candidates = insertion < len(t_g)
            exact = np.zeros_like(tgt, dtype=bool)
            exact[exact_candidates] = np.isclose(
                t_g[insertion[exact_candidates]],
                tgt[exact_candidates],
                rtol=0.0,
                atol=1e-9,
            )

            has_pair = (insertion > 0) & (insertion < len(t_g))
            pair_gap = np.full_like(tgt, np.inf, dtype=float)
            pair_gap[has_pair] = t_g[insertion[has_pair]] - t_g[insertion[has_pair] - 1]
            within_gap = exact | (has_pair & (pair_gap <= gap_limit))

            stats["n_gap_rejected"] = int(np.count_nonzero(ok & ~within_gap))
            ok &= within_gap

        if method == "linear":
            y_out[ok] = np.interp(tgt[ok], t_g, y_g)
        else:
            raise ValueError(f"Unsupported resample method: {method}")

        out[c] = y_out
        stats["n_output"] = int(np.count_nonzero(np.isfinite(y_out)))
        column_meta[c] = stats

    meta = {
        "method": method,
        "src_time_col": src_time_col,
        "target_time_col": "time_s",
        "allow_extrapolation": bool(allow_extrapolation),
        "max_gap_s": gap_limit,
        "src_time_min": t_min,
        "src_time_max": t_max,
        "n_target": int(len(target_time_s)),
        "columns": list(columns),
        "column_stats": column_meta,
    }
    return out, meta


def resample_stream_onto_trigger_grid(
    session: Dict[str, Any],
    *,
    stream_name: str,
    df_stream: pd.DataFrame,
    trigger_time_s: np.ndarray,
    stream_time_col: str = "time_s",
    columns: Optional[Sequence[str]] = None,
    method: str = "linear",
) -> pd.DataFrame:
    """
    Convenience wrapper that also records QC provenance in session['qc']['resampling'].
    Returns a df with 'time_s' plus resampled columns.
    """
    df_rs, meta = resample_to_time_grid(
        df_stream,
        src_time_col=stream_time_col,
        target_time_s=trigger_time_s,
        columns=columns,
        method=method,
        allow_extrapolation=False,
    )

    qc = session.setdefault("qc", {})
    rs = qc.setdefault("resampling", [])
    rs.append({"stream": stream_name, **meta})
    return df_rs
