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
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Resample selected columns from df_src onto target_time_s.

    - Default method: linear interpolation on time.
    - Outside source time range -> NaN (unless allow_extrapolation=True).
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

    out = pd.DataFrame({"time_s": np.asarray(target_time_s, dtype=float)})

    # Range limits
    t_min = float(np.nanmin(t_src))
    t_max = float(np.nanmax(t_src))

    # Build mask where interpolation is allowed
    if allow_extrapolation:
        ok = np.isfinite(out["time_s"].to_numpy())
    else:
        tgt = out["time_s"].to_numpy()
        ok = (tgt >= t_min) & (tgt <= t_max) & np.isfinite(tgt)

    for c in columns:
        y = pd.to_numeric(df_src[c], errors="coerce").to_numpy(dtype=float)
        # interpolate only over finite samples
        good = np.isfinite(t_src) & np.isfinite(y)
        if good.sum() < 2:
            out[c] = np.nan
            continue

        t_g = t_src[good]
        y_g = y[good]

        tgt = out["time_s"].to_numpy()
        y_out = np.full_like(tgt, np.nan, dtype=float)
        if method == "linear":
            y_out[ok] = np.interp(tgt[ok], t_g, y_g)
        else:
            raise ValueError(f"Unsupported resample method: {method}")

        out[c] = y_out

    meta = {
        "method": method,
        "src_time_col": src_time_col,
        "target_time_col": "time_s",
        "allow_extrapolation": bool(allow_extrapolation),
        "src_time_min": t_min,
        "src_time_max": t_max,
        "n_target": int(len(target_time_s)),
        "columns": list(columns),
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
