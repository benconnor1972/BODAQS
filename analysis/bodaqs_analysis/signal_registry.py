# signal_registry.py
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional, Iterable, Set

import pandas as pd
import numpy as np

from .signalname import parse_signal_name, SignalNameError, SignalNameParts
from .signalspec import SignalSpec, DEFAULT_SPEC, RAW_UNIT_DEFAULT


# Columns that are not "signals" but may be numeric and should be tolerated.
DEFAULT_NON_SIGNAL_COLUMNS: Set[str] = {
    "mark",
    "sample_id",
    "event_id",
    "segment_id",
    "ts_ms",
    "t_ms",
    "t_s",
    "grid_idx",
}

TIMEBASE_COLUMNS = {"time_s", "time_ms", "timestamp", "timestamp_ms"}

def _is_numeric_series(s: pd.Series) -> bool:
    # Treat bool as numeric-ish but we typically want it to be QC or flags.
    return pd.api.types.is_numeric_dtype(s.dtype) or pd.api.types.is_bool_dtype(s.dtype)


def _is_boolish_series(s: pd.Series) -> bool:
    if pd.api.types.is_bool_dtype(s.dtype):
        return True
    if not pd.api.types.is_integer_dtype(s.dtype):
        return False
    # tolerate 0/1 with NA
    vals = s.dropna().unique()
    if len(vals) == 0:
        return True
    return set(vals.tolist()).issubset({0, 1})


def build_signals_registry(
    session: Dict[str, Any],
    *,
    spec: SignalSpec = DEFAULT_SPEC,
    strict: bool = False,
    non_signal_columns: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """
    Build/refresh session['meta']['signals'] from session['df'].

    - Adds an entry for every numeric column in df (excluding non-signal columns).
    - Parses canonical names when possible.
    - In strict=False mode, unparseable numeric columns are still registered with
      unit=None and a note (but sensor/quantity will be None), to be dealt with by
      the legacy normaliser / canonicalizer earlier in the pipeline.

    Adds semantic fields used by Option 1 resolution:
      - sensor: sensor_id such as 'rear_shock', 'front_shock' (or None)
      - quantity: 'disp' | 'vel' | 'acc' | 'disp_norm' | 'raw' (or None)
    """
    if "df" not in session:
        raise ValueError("session missing 'df'")
    if "meta" not in session:
        raise ValueError("session missing 'meta'")

    df: pd.DataFrame = session["df"]
    if not isinstance(df, pd.DataFrame):
        raise ValueError("session['df'] must be a pandas DataFrame")

    ns_cols = set(non_signal_columns or DEFAULT_NON_SIGNAL_COLUMNS)

    # ---- helpers -------------------------------------------------

    # Update this tuple as you add sensor bases. Keep it conservative.
    KNOWN_SENSOR_PREFIXES = (
        "front_shock",
        "rear_shock",
        "front_fork",
        "rear_fork",
    )

    def _infer_sensor_id_from_base(base: Optional[str]) -> Optional[str]:
        if not base or not isinstance(base, str):
            return None
        b = base.strip()
        for pref in KNOWN_SENSOR_PREFIXES:
            if b == pref or b.startswith(pref + "_"):
                return pref
        # Conservative fallback: first token only (better than nothing, but not magic)
        tok = b.split("_", 1)[0].strip()
        return tok or None

    def _infer_quantity_from_parts(base: Optional[str], kind: str, unit: Optional[str]) -> Optional[str]:
        """
        Infer a coarse semantic quantity for resolution:
          - raw -> 'raw'
          - *_vel -> 'vel'
          - *_acc -> 'acc'
          - *_norm -> 'disp_norm'
          - engineered mm -> 'disp'
          - unit fallbacks for vel/acc/norm
        """
        if not base or not isinstance(base, str):
            return None

        b = base.lower()
        k = (kind or "").lower()
        u = unit.lower() if isinstance(unit, str) else None

        # Raw wins
        if k == "raw" or b.startswith("raw_") or "_raw_" in b or u == "counts":
            return "raw"

        # Explicit derived suffixes
        if b.endswith("_vel"):
            return "vel"
        if b.endswith("_acc"):
            return "acc"
        if b.endswith("_norm"):
            return "disp_norm"

        # Unit-driven fallback (useful for canonical disp)
        if u == "mm":
            return "disp"
        if u == "mm/s":
            return "vel"
        if u == "mm/s^2":
            return "acc"
        if u == "1":
            return "disp"

        return None

    # ---- build ----------------------------------------------------

    signals: Dict[str, Dict[str, Any]] = {}

    for col in df.columns:
        if col in TIMEBASE_COLUMNS:
            continue

        # Skip obvious non-signal columns
        if col in ns_cols:
            continue

        s = df[col]

        # Only register numeric columns
        if not _is_numeric_series(s):
            continue

        try:
            parts: SignalNameParts = parse_signal_name(str(col), spec=spec)

            domain = parts.domain
            kind = parts.kind
            unit = parts.unit
            ops = list(parts.ops)  # adjust to list(parts.ops or []) if needed

            sensor_id = _infer_sensor_id_from_base(getattr(parts, "base", None))
            quantity = _infer_quantity_from_parts(getattr(parts, "base", None), kind, unit)

            info: Dict[str, Any] = {
                "kind": kind,                 # "" | "raw" | "qc"
                "unit": unit,                 # string or None
                "domain": domain,             # string or None
                "op_chain": ops,              # list[str]
                # NEW:
                "sensor": sensor_id,          # e.g. rear_shock
                "quantity": quantity,         # disp / vel / acc / disp_norm / raw
            }

            # Optional policy nudges:
            if kind == "qc":
                info["notes"] = "qc flag/quality column"

            # Raw default unit recommendation
            if kind == "raw" and (info["unit"] is None):
                info["unit"] = RAW_UNIT_DEFAULT
                info["notes"] = "raw column missing unit; defaulted to [counts]"

            signals[str(col)] = info

        except SignalNameError as e:
            if strict:
                raise

            # Permissive: register so downstream can see it exists, but mark as needing normalization.
            info: Dict[str, Any] = {
                "kind": "",
                "unit": None,
                "domain": None,
                "op_chain": [],
                # NEW: cannot safely infer without parse
                "sensor": None,
                "quantity": None,
                "notes": f"unparsed numeric column; needs normalization: {e}",
            }

            # If it looks boolish, treat as qc candidate
            if _is_boolish_series(s):
                info["kind"] = "qc"
                info["notes"] = "boolish numeric column; treated as qc (needs canonical naming)"

            signals[str(col)] = info

    session["meta"].setdefault("signals", {})
    session["meta"]["signals"] = signals
    return session


