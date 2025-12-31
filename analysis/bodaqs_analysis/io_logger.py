from __future__ import annotations
import re
from typing import Optional
import numpy as np
import pandas as pd

# --- Load (robust clock parsing, no float math, per-file offset optional) ---
def parse_clock_column_to_datetime(s: pd.Series) -> pd.Series:
    """
    Parse 'HH:MM:SS.mmm' or 'MM:SS.mmm' (commas or dots) to pandas datetime64[ns]
    on a dummy date, vectorized and without float arithmetic.
    """
    s = s.astype(str).str.strip().str.replace(",", ".", regex=False)

    # Identify 2-part vs 3-part times
    parts = s.str.split(":", n=2, expand=True)
    n_parts = parts.shape[1]

    # Build a normalized 'HH:MM:SS.mmm' string
    if n_parts == 2:
        # MM:SS(.mmm)
        mm = parts[0].str.zfill(2)
        ss = parts[1]
        norm = "00:" + mm + ":" + ss
    elif n_parts == 3:
        # HH:MM:SS(.mmm)
        hh = parts[0].str.zfill(2)
        mm = parts[1].str.zfill(2)
        ss = parts[2]
        norm = hh + ":" + mm + ":" + ss
    else:
        raise ValueError("Unexpected clock format; expected MM:SS(.ms) or HH:MM:SS(.ms)")

    # Ensure milliseconds have at least 3 digits if present
    # e.g. '12:34:56.7' -> '12:34:56.700'
    has_frac = norm.str.contains(r"\.")
    def pad_ms(x: str) -> str:
        if "." not in x: return x
        hms, frac = x.split(".", 1)
        # keep up to microseconds to be safe, pad to 3-6
        frac = (frac + "000000")[:6]
        return hms + "." + frac

    norm = pd.Series(np.where(has_frac, norm.map(pad_ms), norm), index=norm.index)

    # Use a dummy date so we can take accurate timedeltas (no float)
    dt = pd.to_datetime("1970-01-01 " + norm, format="%Y-%m-%d %H:%M:%S.%f", errors="raise")
    return dt

def ensure_time_index(df: pd.DataFrame) -> pd.DataFrame:
    import pandas as pd

    out = df.copy()
    if isinstance(out.index, (pd.DatetimeIndex, pd.TimedeltaIndex)):
        pass
    elif "t" in out.columns:
        out.index = pd.to_timedelta(out["t"].astype(float), unit="s")
        out.index.name = "t"
        out = out.drop(columns=["t"])     # ✅ remove duplicate column
    elif "timestamp" in out.columns:
        dt = pd.to_datetime(out["timestamp"], errors="coerce")
        out = out.loc[dt.notna()]
        out.index = dt
    else:
        raise TypeError("No 't' or 'timestamp' column to build a time index from.")

    # make sure index is clean
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out

def load_logger_csv(path: str) -> pd.DataFrame:
    # Read raw text and clean (kept for delimiter detection and robustness)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.replace("\0", "").strip() for ln in f if ln.strip()]

    # Detect delimiter
    sample = "".join(lines[:5])
    delim = "," if sample.count(",") > sample.count(";") else ";"

    df = pd.read_csv(
        path,
        sep=delim,
        comment="#",
        engine="python",
        on_bad_lines="skip",
    )

    # ---- Canonicalise time to 'time_s' ----
    # Supported:
    #  - clock string: "HH:MM:SS.sss" in column 'timestamp'
    #  - numeric: seconds/ms/us in common columns
    time_s = None

    if "timestamp" in df.columns:
        # Try clock string first
        t_clock = pd.to_datetime(df["timestamp"], format="%H:%M:%S.%f", errors="coerce")

        if t_clock.notna().any():
            df = df.loc[t_clock.notna()].copy()
            time_s = (t_clock.loc[t_clock.notna()] - t_clock.loc[t_clock.notna()].iloc[0]).dt.total_seconds()
        else:
            # Fallback: numeric in timestamp column
            t_num = pd.to_numeric(df["timestamp"], errors="coerce")
            df = df.loc[t_num.notna()].copy()
            t_num = t_num.loc[t_num.notna()]
            # Heuristic scale: us / ms / s
            tmax = float(t_num.max()) if len(t_num) else 0.0
            if tmax > 1e12:       # likely microseconds since boot/epoch
                t_num = t_num * 1e-6
            elif tmax > 1e9:      # could be epoch seconds (too big) or ms
                # treat as ms (common for loggers); adjust if needed later
                t_num = t_num * 1e-3
            elif tmax > 1e6:      # likely milliseconds
                t_num = t_num * 1e-3
            # else already seconds
            time_s = (t_num - float(t_num.iloc[0])).astype(np.float64)

    else:
        # Try common numeric time columns if 'timestamp' absent
        for cand in ("time_s", "t", "time", "ts", "ts_ms", "time_ms"):
            if cand in df.columns:
                t_num = pd.to_numeric(df[cand], errors="coerce")
                df = df.loc[t_num.notna()].copy()
                t_num = t_num.loc[t_num.notna()]

                tmax = float(t_num.max()) if len(t_num) else 0.0
                if cand.endswith("_ms") or tmax > 1e6:
                    t_num = t_num * 1e-3
                time_s = (t_num - float(t_num.iloc[0])).astype(np.float64)
                break

    if time_s is None:
        raise ValueError("No usable time column found (expected 'timestamp' or a numeric time column).")

    df["time_s"] = np.asarray(time_s, dtype=np.float64)

    # ---- Clean numeric columns (leave timestamp as-is) ----
    for c in df.columns:
        if c in ("timestamp",):
            continue
        df[c] = (
            df[c]
            .astype(str)
            .str.replace(r"[^0-9eE+\-\.]", "", regex=True)
            .replace("", np.nan)
            .astype(float)
        )

    # Drop NaNs and deduplicate by canonical time
    df = df.dropna().drop_duplicates(subset="time_s", keep="first").reset_index(drop=True)
    df = df[df["time_s"].diff().fillna(0) >= 0]  # keep monotonic time

    return df


# --- Footer stats parsing (logger-provided QC) ---
_RUN_STATS_BEGIN_RE = re.compile(r"^\s*#\s*run_stats_begin\s*$", re.IGNORECASE)
_RUN_STATS_END_RE   = re.compile(r"^\s*#\s*run_stats_end\s*$", re.IGNORECASE)
_KV_RE = re.compile(r"^\s*#\s*([A-Za-z0-9_\-]+)\s*=\s*(.*?)\s*$")

def parse_run_stats_footer(path: str) -> dict:
    """Parse optional end-of-file run stats emitted by the logger.

    Expected format (example):
        # run_stats_begin
        # samples_dropped=0
        # flush_count=5
        # run_stats_end

    Returns a dict of parsed key/value pairs. Values are converted to int/float where sensible.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return {}

    # search near end for markers
    start_idx = None
    end_idx = None
    for i in range(len(lines)-1, max(-1, len(lines)-300), -1):
        ln = lines[i].rstrip("\n")
        if end_idx is None and _RUN_STATS_END_RE.match(ln):
            end_idx = i
            continue
        if end_idx is not None and _RUN_STATS_BEGIN_RE.match(ln):
            start_idx = i
            break

    if start_idx is None or end_idx is None or end_idx <= start_idx:
        return {}

    stats: dict = {}
    for ln in lines[start_idx+1:end_idx]:
        m = _KV_RE.match(ln)
        if not m:
            continue
        key = m.group(1)
        val = m.group(2)
        # coerce basic numeric types
        if re.fullmatch(r"[-+]?\d+", val or ""):
            try: stats[key] = int(val)
            except Exception: stats[key] = val
        elif re.fullmatch(r"[-+]?\d*\.\d+(?:[eE][-+]?\d+)?", val or "") or re.fullmatch(r"[-+]?\d+\.\d*(?:[eE][-+]?\d+)?", val or ""):
            try: stats[key] = float(val)
            except Exception: stats[key] = val
        else:
            stats[key] = val
    return stats
