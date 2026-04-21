from __future__ import annotations
import json
from pathlib import Path
import re
from typing import Any, Optional, Sequence
import numpy as np
import pandas as pd


def infer_sidecar_path(path: str) -> Optional[str]:
    """
    Return a same-stem JSON sidecar path when present.
    """
    candidate = Path(path).with_suffix(".json")
    return str(candidate) if candidate.exists() else None


def load_logger_sidecar(path: str) -> dict[str, Any]:
    """
    Load and lightly validate a logger sidecar JSON document.
    """
    p = Path(path)
    obj = json.loads(p.read_text(encoding="utf-8"))

    if not isinstance(obj, dict):
        raise ValueError(f"Logger sidecar must contain a JSON object: {path}")

    contract = obj.get("contract")
    if not isinstance(contract, dict):
        raise ValueError(f"Logger sidecar missing required object 'contract': {path}")

    if not isinstance(contract.get("name"), str) or not contract["name"].strip():
        raise ValueError(f"Logger sidecar missing required string 'contract.name': {path}")
    if not isinstance(contract.get("version"), str) or not contract["version"].strip():
        raise ValueError(f"Logger sidecar missing required string 'contract.version': {path}")

    streams = obj.get("streams")
    if not isinstance(streams, dict) or not streams:
        raise ValueError(f"Logger sidecar missing required non-empty object 'streams': {path}")

    columns = obj.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise ValueError(f"Logger sidecar missing required non-empty object 'columns': {path}")

    return obj


def _select_primary_stream(sidecar: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    streams = sidecar.get("streams")
    if not isinstance(streams, dict) or not streams:
        raise ValueError("Logger sidecar missing required non-empty object 'streams'")

    if "primary" in streams and isinstance(streams["primary"], dict):
        return "primary", streams["primary"]

    for stream_name, stream_info in streams.items():
        if isinstance(stream_info, dict):
            return str(stream_name), stream_info

    raise ValueError("Logger sidecar does not contain a usable stream definition")

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

def load_logger_csv(
    path: str,
    *,
    delimiter: Optional[str] = None,
    preferred_time_cols: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    # Read raw text and clean (kept for delimiter detection and robustness)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.replace("\0", "").strip() for ln in f if ln.strip()]

    # Detect delimiter
    sample = "".join(lines[:5])
    delim = delimiter if isinstance(delimiter, str) and len(delimiter) == 1 else (
        "," if sample.count(",") > sample.count(";") else ";"
    )

    df = pd.read_csv(
        path,
        sep=delim,
        comment="#",
        engine="python",
        on_bad_lines="skip",
    )

    # ---- Canonicalise time to 'time_s' ----
    # Preferred time sources (most stable -> least):
    #  - timestamp_ms (numeric, ms)
    #  - ts_ms / time_ms (numeric, ms)
    #  - time_s / t / time / ts (numeric, seconds-ish; heuristics applied)
    #  - timestamp (clock string "HH:MM:SS.mmm" or "MM:SS.mmm") fallback
    time_s = None
    preferred = [str(c) for c in (preferred_time_cols or []) if isinstance(c, str) and c.strip()]
    tried_preferred: set[str] = set()

    def _use_numeric(col: str, *, assume_ms: bool) -> None:
        nonlocal df, time_s
        t_num = pd.to_numeric(df[col], errors="coerce")
        mask = t_num.notna()
        if not mask.any():
            return

        df = df.loc[mask].copy()
        t_num = t_num.loc[mask].astype(np.float64)

        if assume_ms:
            t_sec = t_num * 1e-3
        else:
            # Heuristic scale: us / ms / s
            tmax = float(t_num.max()) if len(t_num) else 0.0
            if tmax > 1e12:        # likely microseconds
                t_sec = t_num * 1e-6
            elif tmax > 1e6:       # likely milliseconds (or larger)
                t_sec = t_num * 1e-3
            else:
                t_sec = t_num       # seconds
        time_s = (t_sec - float(t_sec.iloc[0])).to_numpy(dtype=np.float64)

    def _use_clock_string(col: str) -> None:
        nonlocal df, time_s
        # Use your robust parser (handles MM:SS(.mmm), commas, etc.)
        t_dt = parse_clock_column_to_datetime(df[col])
        mask = t_dt.notna()
        if not mask.any():
            return

        df = df.loc[mask].copy()
        t_dt_f = t_dt.loc[mask]
        # Dummy-date datetime deltas handle midnight rollovers correctly (adds 24h)
        time_s = (t_dt_f - t_dt_f.iloc[0]).dt.total_seconds().to_numpy(dtype=np.float64)

    def _use_preferred(col: str) -> None:
        nonlocal time_s
        if col not in df.columns or time_s is not None:
            return

        series = df[col]
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().any():
            _use_numeric(col, assume_ms=col.lower().endswith("_ms"))
            return

        _use_clock_string(col)

    if time_s is None:
        for cand in preferred:
            tried_preferred.add(cand)
            _use_preferred(cand)
            if time_s is not None:
                break

    # 1) Strong preference: explicit ms column from logger
    if time_s is None and "timestamp_ms" in df.columns and "timestamp_ms" not in tried_preferred:
        _use_numeric("timestamp_ms", assume_ms=True)

    # 2) Next: other common numeric ms columns
    if time_s is None:
        for cand in ("ts_ms", "time_ms"):
            if cand in df.columns and cand not in tried_preferred:
                _use_numeric(cand, assume_ms=True)
                if time_s is not None:
                    break

    # 3) Next: other numeric time columns (seconds-ish)
    if time_s is None:
        for cand in ("time_s", "t", "time", "ts"):
            if cand in df.columns and cand not in tried_preferred:
                _use_numeric(cand, assume_ms=False)
                if time_s is not None:
                    break

    # 4) Fallback: human-readable timestamp
    if time_s is None and "timestamp" in df.columns and "timestamp" not in tried_preferred:
        _use_clock_string("timestamp")

        # If that failed, last-resort: treat timestamp as numeric
        if time_s is None:
            _use_numeric("timestamp", assume_ms=False)

    if time_s is None:
        raise ValueError(
            "No usable time column found (expected 'timestamp_ms', 'timestamp', or a numeric time column)."
        )

    df["time_s"] = np.asarray(time_s, dtype=np.float64)

    # ---- Clean numeric columns (leave timestamp as-is) ----
    for c in df.columns:
        if c in ("timestamp","timestamp_ms"):
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
    df = df[df["time_s"].diff().fillna(0) > 0]  # keep monotonic time

    return df


def load_logger_csv_with_sidecar(
    path: str,
    *,
    sidecar_path: Optional[str] = None,
) -> tuple[pd.DataFrame, Optional[dict[str, Any]], Optional[str]]:
    """
    Load a logger CSV and, when available, a same-stem or explicitly supplied
    JSON sidecar that can provide delimiter/time-column hints and session metadata.
    """
    resolved_sidecar = sidecar_path if sidecar_path is not None else infer_sidecar_path(path)
    sidecar: Optional[dict[str, Any]] = None
    preferred_time_cols: list[str] = []
    delimiter: Optional[str] = None

    if resolved_sidecar is not None:
        sidecar = load_logger_sidecar(resolved_sidecar)

        data_file = sidecar.get("data_file")
        if isinstance(data_file, dict):
            delim = data_file.get("delimiter")
            if isinstance(delim, str) and len(delim) == 1:
                delimiter = delim

        _, primary_stream = _select_primary_stream(sidecar)
        time_col = primary_stream.get("time_col")
        if isinstance(time_col, str) and time_col.strip():
            preferred_time_cols.append(time_col)

    df = load_logger_csv(
        path,
        delimiter=delimiter,
        preferred_time_cols=preferred_time_cols,
    )
    return df, sidecar, resolved_sidecar


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
