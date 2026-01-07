# signal_registry.py
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional, Iterable, Set

import pandas as pd
import numpy as np

from signalname import parse_signal_name, SignalNameError, SignalNameParts
from signalspec import SignalSpec, DEFAULT_SPEC, RAW_UNIT_DEFAULT


# Columns that are not "signals" but may be numeric and should be tolerated.
# Adjust to match your session schema / trigger-grid fields.
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
      unit=None and a note, to be dealt with by Step 3 (legacy normaliser).
    """
    if "df" not in session:
        raise ValueError("session missing 'df'")
    if "meta" not in session:
        raise ValueError("session missing 'meta'")

    df: pd.DataFrame = session["df"]
    if not isinstance(df, pd.DataFrame):
        raise ValueError("session['df'] must be a pandas DataFrame")

    ns_cols = set(non_signal_columns or DEFAULT_NON_SIGNAL_COLUMNS)

    signals: Dict[str, Dict[str, Any]] = {}

    for col in df.columns:
        s = df[col]

        # Skip obvious non-signal columns
        if col in ns_cols:
            continue

        # Only register numeric columns
        if not _is_numeric_series(s):
            continue

        try:
            parts: SignalNameParts = parse_signal_name(str(col), spec=spec)

            # Derive domain stored without prefix
            domain = parts.domain

            # Registry entry
            info: Dict[str, Any] = {
                "kind": parts.kind,                   # "" | "raw" | "qc"
                "unit": parts.unit,                   # string or None
                "domain": domain,                     # string or None
                "op_chain": list(parts.ops),          # list[str]
            }

            # Optional policy nudges:
            # If a column name indicates qc kind, encourage boolish
            if parts.kind == "qc":
                info["notes"] = "qc flag/quality column"

            # Raw default unit recommendation (do not enforce here; validator will)
            if parts.kind == "raw" and (parts.unit is None):
                info["unit"] = RAW_UNIT_DEFAULT
                info["notes"] = "raw column missing unit; defaulted to [counts]"

            signals[str(col)] = info

        except SignalNameError as e:
            if strict:
                raise

            # Permissive: still register so downstream code can see it exists,
            # but mark it as needing normalization.
            info = {
                "kind": "",
                "unit": None,
                "domain": None,
                "op_chain": [],
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


