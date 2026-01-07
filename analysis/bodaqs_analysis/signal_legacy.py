# signal_legacy.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, List, Iterable

import pandas as pd

from signalname import parse_signal_name, format_signal_name, SignalNameError, SignalNameParts
from signalspec import SignalSpec, DEFAULT_SPEC, RAW_UNIT_DEFAULT


# Legacy suffix -> op token
LEGACY_OP_SUFFIXES = {
    "_zeroed": "zeroed",
    "_norm": "norm",
    "_filtered": "filt",
    "_filter": "filt",
    "_smoothed": "smooth",
    "_resampled": "resamp",
    "_scaled": "cal",   # use "cal" if you consider scaling a calibration-like op; adjust if you prefer "scale"
}

# Common units for “engineered default” signals you already know (extend later).
# Step 3 should NOT guess; you can pass overrides via units_by_base.
DEFAULT_UNITS_BY_BASE: Dict[str, str] = {
    # e.g. "rear_shock": "mm",
    # e.g. "front_shock": "mm",
    # e.g. "battery_v": "V",
}

# Columns that should not be renamed by this normaliser.
DEFAULT_EXEMPT_COLUMNS = {"time_s", "time_ms", "ts_ms", "timestamp", "timestamp_ms" "sample_id", "mark"}


@dataclass
class RenameRecord:
    old: str
    new: str
    status: str  # "ok" | "skipped" | "warn"
    reason: str


def _split_unit_and_suffix(col: str) -> Tuple[str, Optional[str], str]:
    """
    Split a column like:
      'rear_shock [mm]_zeroed' -> ('rear_shock', 'mm', '_zeroed')
      'rear_shock [mm]'        -> ('rear_shock', 'mm', '')
      'rear_shock_zeroed'      -> ('rear_shock_zeroed', None, '')
    """
    s = col.strip()
    unit = None
    suffix = ""

    unit_start = s.find(" [")
    if unit_start != -1:
        unit_end = s.find("]", unit_start)
        if unit_end != -1:
            unit = s[unit_start + 2 : unit_end].strip() or None
            base = s[:unit_start]
            suffix = s[unit_end + 1 :]
            return base, unit, suffix

    return s, None, ""


def normalize_legacy_columns(
    df: pd.DataFrame,
    *,
    spec: SignalSpec = DEFAULT_SPEC,
    units_by_base: Optional[Dict[str, str]] = None,
    domain_by_base: Optional[Dict[str, str]] = None,
    exempt_columns: Optional[Iterable[str]] = None,
) -> Tuple[pd.DataFrame, List[RenameRecord]]:
    """
    Rename legacy columns to match the v0.2 canonical signal naming spec.

    Strategy:
      1) If a column already parses under canonical rules: keep it.
      2) Otherwise apply safe rewrites:
         - legacy suffixes like '_zeroed' -> '_op_zeroed' (requires unit present)
         - raw columns missing unit: '<base>_raw' -> '<base>_raw [counts]'
         - engineered columns missing unit: only if units_by_base provides it
         - optional domain injection: only if domain_by_base provides it

    Returns: (df_renamed, rename_report)
    """
    if not isinstance(df, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")

    units_by_base = {**DEFAULT_UNITS_BY_BASE, **(units_by_base or {})}
    domain_by_base = domain_by_base or {}
    exempt = set(exempt_columns or DEFAULT_EXEMPT_COLUMNS)

    report: List[RenameRecord] = []
    rename_map: Dict[str, str] = {}

    for col in df.columns:
        col_str = str(col)

        if col_str in exempt:
            report.append(RenameRecord(col_str, col_str, "skipped", "exempt column"))
            continue

        # 1) Already canonical?
        try:
            parts = parse_signal_name(col_str, spec=spec)
            # Optionally inject domain/unit if missing (conservative: only if explicitly provided)
            updated = parts

            if updated.domain is None and parts.base in domain_by_base:
                updated = SignalNameParts(
                    base=updated.base,
                    kind=updated.kind,
                    domain=domain_by_base[updated.base],
                    unit=updated.unit,
                    ops=updated.ops,
                )

            if updated.unit is None and updated.kind == "" and updated.base in units_by_base:
                updated = SignalNameParts(
                    base=updated.base,
                    kind=updated.kind,
                    domain=updated.domain,
                    unit=units_by_base[updated.base],
                    ops=updated.ops,
                )

            new_name = format_signal_name(updated, spec=spec)
            if new_name != col_str:
                rename_map[col_str] = new_name
                report.append(RenameRecord(col_str, new_name, "ok", "canonical parsed; enriched from hints"))
            else:
                report.append(RenameRecord(col_str, col_str, "skipped", "already canonical"))
            continue
        except SignalNameError:
            pass

        # 2) Legacy rewrites

        # 2a) Handle raw columns missing unit: '<base>_raw' -> '<base>_raw [counts]'
        if col_str.endswith("_raw"):
            base = col_str[:-4]
            parts = SignalNameParts(base=base, kind="raw", domain=domain_by_base.get(base), unit=RAW_UNIT_DEFAULT, ops=())
            new_name = format_signal_name(parts, spec=spec)
            rename_map[col_str] = new_name
            report.append(RenameRecord(col_str, new_name, "ok", "raw missing unit -> add [counts]"))
            continue

        # 2b) Handle engineered with legacy suffix after unit: 'X [u]_zeroed' -> 'X [u]_op_zeroed'
        base, unit, suffix = _split_unit_and_suffix(col_str)
        if unit is not None and suffix:
            # if suffix matches a legacy op suffix, translate it into ops
            # also support chained legacy like '_zeroed_norm' by iterative peeling
            ops: List[str] = []
            remain = suffix

            progressed = True
            while progressed and remain:
                progressed = False
                for legacy_sfx, op_token in LEGACY_OP_SUFFIXES.items():
                    if remain.startswith(legacy_sfx):
                        ops.append(op_token)
                        remain = remain[len(legacy_sfx):]
                        progressed = True
                        break

            if ops and remain == "":
                dom = domain_by_base.get(base)
                parts = SignalNameParts(base=base, kind="", domain=dom, unit=unit, ops=tuple(ops))
                new_name = format_signal_name(parts, spec=spec)
                rename_map[col_str] = new_name
                report.append(RenameRecord(col_str, new_name, "ok", "legacy suffix -> canonical _op_ chain"))
                continue

        # 2c) Engineered missing unit: only if units_by_base provides it.
        # Example: 'rear_shock' -> 'rear_shock [mm]'
        if col_str in units_by_base:
            base = col_str
            unit = units_by_base[base]
            dom = domain_by_base.get(base)
            parts = SignalNameParts(base=base, kind="", domain=dom, unit=unit, ops=())
            new_name = format_signal_name(parts, spec=spec)
            rename_map[col_str] = new_name
            report.append(RenameRecord(col_str, new_name, "ok", "added unit from units_by_base hint"))
            continue

        # 2d) Nothing we can do safely
        report.append(RenameRecord(col_str, col_str, "warn", "unrecognized legacy pattern (left unchanged)"))

    # Detect collisions before applying
    new_names = list(rename_map.values())
    if len(new_names) != len(set(new_names)):
        # Find which collide (simple approach)
        seen = {}
        collisions = []
        for old, new in rename_map.items():
            if new in seen:
                collisions.append((seen[new], old, new))
            else:
                seen[new] = old
        msg = "; ".join([f"{a!r} and {b!r} -> {n!r}" for a, b, n in collisions[:5]])
        raise ValueError(f"legacy normalization would create duplicate columns: {msg}")

    df2 = df.rename(columns=rename_map, copy=True)
    return df2, report
