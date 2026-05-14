from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TimebaseInfo:
    kind: str                # "uniform" for v0
    time_col: str            # usually "time_s"
    sample_rate_hz: float
    dt_s: float
    jitter_frac: float       # std(dt) / median(dt)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "time_col": self.time_col,
            "sample_rate_hz": float(self.sample_rate_hz),
            "dt_s": float(self.dt_s),
            "jitter_frac": float(self.jitter_frac),
        }


def _as_time_vec(df: pd.DataFrame, time_col: str) -> np.ndarray:
    if time_col not in df.columns:
        raise ValueError(f"Missing time column: {time_col}")
    t = pd.to_numeric(df[time_col], errors="coerce").to_numpy(dtype=float)
    if t.size < 2:
        raise ValueError(f"{time_col} must contain at least two samples")
    if not np.isfinite(t).all():
        raise ValueError(f"{time_col} contains non-finite values")
    if np.any(np.diff(t) < 0):
        raise ValueError(f"{time_col} must be monotonic non-decreasing")
    return t


def estimate_uniform_timebase(
    df: pd.DataFrame,
    *,
    time_col: str = "time_s",
    sample_rate_hz: Optional[float] = None,
) -> TimebaseInfo:
    """
    Estimate per-stream dt for a *uniform* stream.
    Priority:
      - explicit sample_rate_hz if provided
      - median diff of time vector
    """
    t = _as_time_vec(df, time_col)

    if sample_rate_hz is not None:
        sr = float(sample_rate_hz)
        if sr <= 0 or not np.isfinite(sr):
            raise ValueError("sample_rate_hz must be finite and > 0")
        dt = 1.0 / sr
        return TimebaseInfo(kind="uniform", time_col=time_col, sample_rate_hz=sr, dt_s=dt, jitter_frac=0.0)

    dt_vec = np.diff(t)
    dt_pos = dt_vec[dt_vec > 0]
    if dt_pos.size == 0:
        raise ValueError("Unable to infer dt: no positive time deltas")
    dt_med = float(np.median(dt_pos))
    if dt_med <= 0 or not np.isfinite(dt_med):
        raise ValueError("Unable to infer dt: invalid median dt")

    jitter = float(np.std(dt_pos) / dt_med) if dt_med > 0 else float("inf")
    sr = 1.0 / dt_med
    return TimebaseInfo(kind="uniform", time_col=time_col, sample_rate_hz=sr, dt_s=dt_med, jitter_frac=jitter)


def ensure_session_streams_meta(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure session['meta']['streams'] exists and return it.
    """
    meta = session.setdefault("meta", {})
    return meta.setdefault("streams", {})


def register_stream_metadata(
    session: Dict[str, Any],
    *,
    stream_name: str,
    kind: str,
    time_col: str,
    sample_rate_hz: Optional[float] = None,
    dt_s: Optional[float] = None,
    jitter_frac: Optional[float] = None,
    notes: Optional[str] = None,
    jitter_tol_frac: float = 0.05,
) -> Dict[str, Any]:
    """
    Store generic per-stream metadata in session['meta']['streams'][stream_name].

    Supported kinds:
      - "uniform": requires sample_rate_hz, dt_s, jitter_frac
      - "intermittent": requires only kind + time_col
    """
    if kind not in {"uniform", "intermittent"}:
        raise ValueError(f"Unsupported stream kind: {kind}")
    if not isinstance(time_col, str) or not time_col.strip():
        raise ValueError("time_col must be a non-empty string")

    entry: Dict[str, Any] = {
        "kind": kind,
        "time_col": time_col,
    }

    if kind == "uniform":
        if sample_rate_hz is None or dt_s is None or jitter_frac is None:
            raise ValueError("Uniform streams require sample_rate_hz, dt_s, and jitter_frac")
        entry["sample_rate_hz"] = float(sample_rate_hz)
        entry["dt_s"] = float(dt_s)
        entry["jitter_frac"] = float(jitter_frac)

    if notes is not None:
        entry["notes"] = str(notes)

    streams = ensure_session_streams_meta(session)
    streams[stream_name] = entry

    if kind == "uniform" and float(entry["jitter_frac"]) > float(jitter_tol_frac):
        qc = session.setdefault("qc", {})
        time_qc = qc.setdefault("time", {})
        warnings = time_qc.setdefault("warnings", [])
        warnings.append({
            "stream": stream_name,
            "issue": "high_jitter",
            "jitter_frac": float(entry["jitter_frac"]),
            "tol_frac": float(jitter_tol_frac),
        })

    return entry


def register_stream_timebase(
    session: Dict[str, Any],
    *,
    stream_name: str,
    df_stream: pd.DataFrame,
    time_col: str = "time_s",
    sample_rate_hz: Optional[float] = None,
    jitter_tol_frac: float = 0.05,
) -> TimebaseInfo:
    """
    Compute + store per-stream timebase in session['meta']['streams'][stream_name].
    Also writes QC warning if jitter is high.
    """
    tb = estimate_uniform_timebase(df_stream, time_col=time_col, sample_rate_hz=sample_rate_hz)
    register_stream_metadata(
        session,
        stream_name=stream_name,
        kind=tb.kind,
        time_col=tb.time_col,
        sample_rate_hz=tb.sample_rate_hz,
        dt_s=tb.dt_s,
        jitter_frac=tb.jitter_frac,
        jitter_tol_frac=jitter_tol_frac,
    )
    return tb
