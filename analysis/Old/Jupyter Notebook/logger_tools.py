
"""
Lightweight utilities for ESP32 data-logger CSVs.
- Auto-detects timestamp formats (ms epoch, us epoch, ISO8601, human-readable)
- Simple smoothing (EMA, moving average)
- Resampling to fixed rate
- Basic calibration via linear transform
- Segmenting by "mark" events if present
"""
from __future__ import annotations
import math
import re
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple, List

import numpy as np
import pandas as pd

_TIMESTAMP_COL_CANDIDATES = ["ts", "timestamp", "time", "Time", "Timestamp"]

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})?$")
HUMAN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$")

def _maybe_parse_timestamp(s: str) -> Optional[pd.Timestamp]:
    try:
        s = str(s).strip()
        if not s:
            return None
        if s.isdigit():
            x = int(s)
            # Heuristics: digits length => seconds/ms/us/ns since 1970-01-01 UTC
            if x > 1e17:  # ns
                return pd.to_datetime(x, unit="ns", utc=True)
            elif x > 1e14:  # us (common for microseconds)
                return pd.to_datetime(x, unit="us", utc=True)
            elif x > 1e12:  # ms
                return pd.to_datetime(x, unit="ms", utc=True)
            elif x > 1e9:   # s but future—assume seconds anyway
                return pd.to_datetime(x, unit="s", utc=True)
            else:           # seconds (1970-~2001)
                return pd.to_datetime(x, unit="s", utc=True)
        # Text formats
        if ISO_RE.match(s) or HUMAN_RE.match(s):
            return pd.to_datetime(s, utc=True, errors="coerce")
        # Fallback general parse (slower)
        return pd.to_datetime(s, utc=True, errors="coerce")
    except Exception:
        return None

def find_timestamp_column(df: pd.DataFrame) -> Optional[str]:
    for c in _TIMESTAMP_COL_CANDIDATES:
        if c in df.columns:
            return c
    # attempt heuristic on first column if it looks like time
    first = df.columns[0]
    sample = df[first].dropna().astype(str).head(10)
    parsed = sample.apply(_maybe_parse_timestamp)
    if parsed.notna().mean() > 0.8:
        return first
    return None

def ensure_datetime_index(df: pd.DataFrame, tz: Optional[str] = None) -> pd.DataFrame:
    col = find_timestamp_column(df)
    if col is None:
        raise ValueError("Could not find a timestamp column. Expected one of: "
                         f"{_TIMESTAMP_COL_CANDIDATES} or a parseable first column.")
    ts = df[col].apply(_maybe_parse_timestamp)
    if ts.isna().all():
        raise ValueError(f"Failed to parse timestamps in column '{col}'.")
    idx = pd.to_datetime(ts, utc=True)
    if tz:
        idx = idx.tz_convert(tz)
    df = df.drop(columns=[col])
    return df.set_index(idx).sort_index()

def ema(series: pd.Series, alpha: float) -> pd.Series:
    """Exponential moving average (0<alpha<=1)."""
    if not (0 < alpha <= 1):
        raise ValueError("alpha must be in (0,1].")
    return series.ewm(alpha=alpha, adjust=False).mean()

def moving_average(series: pd.Series, window: int) -> pd.Series:
    window = max(1, int(window))
    return series.rolling(window=window, min_periods=1, center=False).mean()

def resample_df(df: pd.DataFrame, rate_hz: float, how: str = "mean") -> pd.DataFrame:
    """Resample to a fixed rate. how: 'mean', 'median', 'ffill', 'bfill'."""
    if rate_hz <= 0:
        raise ValueError("rate_hz must be > 0")
    rule = pd.to_timedelta(1.0 / rate_hz, unit="s")
    if how in ("mean", "median"):
        return getattr(df.resample(rule), how)().interpolate()
    elif how in ("ffill", "bfill"):
        return getattr(df.resample(rule), how)()
    else:
        raise ValueError("Unsupported 'how'. Use 'mean', 'median', 'ffill', or 'bfill'.")

@dataclass
class LinearCal:
    """Simple linear calibration y = a*x + b."""
    a: float = 1.0
    b: float = 0.0
    units: Optional[str] = None

    def apply(self, s: pd.Series) -> pd.Series:
        out = self.a * s + self.b
        out.attrs["units"] = self.units or s.attrs.get("units")
        return out

def segment_by_marks(df: pd.DataFrame, mark_col: str = "mark") -> List[pd.DataFrame]:
    """Split dataframe on rising edges in a 'mark' column (0/1)."""
    if mark_col not in df.columns:
        return [df]
    marks = (df[mark_col].diff().fillna(0) > 0).cumsum()
    groups = []
    for _, g in df.groupby(marks):
        groups.append(g.drop(columns=[mark_col], errors="ignore"))
    return groups
