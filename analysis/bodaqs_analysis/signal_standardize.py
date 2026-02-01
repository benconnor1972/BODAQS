# signal_standardize.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple, List

import numpy as np
import pandas as pd

from .signalspec import SignalSpec, DEFAULT_SPEC, RAW_UNIT_DEFAULT
from .signalname import parse_signal_name, format_signal_name, SignalNameError, SignalNameParts
from .signal_registry import build_signals_registry
from .model import validate_signals_registry_shape
from .signal_legacy import normalize_legacy_columns  # local import to avoid cycles


# ---------------------------
# Semantic validation (Step 4)
# ---------------------------



class SignalSemanticsError(ValueError):
    pass


def _is_boolish_series(s: pd.Series) -> bool:
    if pd.api.types.is_bool_dtype(s.dtype):
        return True
    if pd.api.types.is_integer_dtype(s.dtype):
        vals = s.dropna().unique()
        if len(vals) == 0:
            return True
        return set(vals.tolist()).issubset({0, 1})
    return False


def validate_signals_semantics(session: Dict[str, Any], *, spec: SignalSpec = DEFAULT_SPEC) -> None:
    """Enforce v0.2 signal semantics against session['df'] and session['meta']['signals']."""
    df: pd.DataFrame = session["df"]
    signals: Dict[str, Dict[str, Any]] = session["meta"]["signals"]

    errors: List[str] = []

    # Units where we expect a real per-sensor physical quantity (engineered signals)
    _PHYSICAL_UNITS = {"mm", "mm/s", "mm/s^2", "1"}

    # Coarse quantity vocabulary (v0.1 for Option 1 resolution)
    _ALLOWED_QUANTITIES = {"disp", "vel", "acc", "disp_norm", "raw"}

    for col, info in signals.items():
        if col not in df.columns:
            errors.append(f"signals key not in df.columns: {col!r}")
            continue

        s = df[col]
        kind = info.get("kind", "")
        unit = info.get("unit", None)
        domain = info.get("domain", None)
        op_chain = info.get("op_chain", [])

        # NEW fields (may be absent in older registries)
        sensor = info.get("sensor", None)
        quantity = info.get("quantity", None)

        # Kind must be valid
        if kind not in ("", "raw", "qc"):
            errors.append(f"{col!r}: invalid kind {kind!r}")

        # Domain if present must be allowed
        if domain is not None and spec.strict_domains and domain not in spec.allowed_domains:
            errors.append(f"{col!r}: unknown domain {domain!r}")

        # Ops must be allowed
        if spec.strict_ops:
            bad_ops = [t for t in (op_chain or []) if t not in spec.allowed_ops]
            if bad_ops:
                errors.append(f"{col!r}: unknown op token(s) {bad_ops}")

        # Engineered: must have unit
        if kind == "":
            if unit is None or not isinstance(unit, str) or not unit.strip():
                errors.append(f"{col!r}: engineered signal missing unit")

        # Raw: should be counts
        if kind == "raw":
            if unit != RAW_UNIT_DEFAULT:
                errors.append(
                    f"{col!r}: raw signal unit should be '{RAW_UNIT_DEFAULT}', got {unit!r}"
                )

        # QC: should be boolish
        if kind == "qc":
            if not _is_boolish_series(s):
                errors.append(f"{col!r}: qc signal not bool/0-1 dtype={s.dtype}")

        # ------------------------------------------------------------------
        # NEW: Option 1 registry semantics checks (sensor + quantity)
        # ------------------------------------------------------------------

        # Helper: non-empty string
        def _is_nonempty_str(x) -> bool:
            return isinstance(x, str) and bool(x.strip())

        # For engineered physical quantities, require sensor + quantity.
        # (Skip enforcement if unit is missing, since that's already an error above.)
        if kind == "" and isinstance(unit, str) and unit.strip() in _PHYSICAL_UNITS:
            if not _is_nonempty_str(sensor):
                errors.append(f"{col!r}: engineered physical signal missing sensor")
            if not _is_nonempty_str(quantity):
                errors.append(f"{col!r}: engineered physical signal missing quantity")
            elif quantity not in _ALLOWED_QUANTITIES:
                errors.append(
                    f"{col!r}: unknown quantity {quantity!r} (allowed: {sorted(_ALLOWED_QUANTITIES)})"
                )

            # Additional unit↔quantity consistency checks (lightweight, catches obvious bugs)
            if _is_nonempty_str(quantity):
                if quantity == "disp" and unit.strip() != "mm" and unit.strip() != "1":
                    errors.append(f"{col!r}: quantity 'disp' should have unit 'mm' or '1', got {unit!r}")
                if quantity == "vel" and unit.strip() != "mm/s":
                    errors.append(f"{col!r}: quantity 'vel' should have unit 'mm/s', got {unit!r}")
                if quantity == "acc" and unit.strip() != "mm/s^2":
                    errors.append(f"{col!r}: quantity 'acc' should have unit 'mm/s^2', got {unit!r}")
                   # errors.append(f"{col!r}: quantity 'disp_norm' should have unit '1', got {unit!r}")

        # For raw signals, we also want sensor + quantity='raw'
        if kind == "raw":
            if not _is_nonempty_str(sensor):
                errors.append(f"{col!r}: raw signal missing sensor")
            if quantity != "raw":
                errors.append(f"{col!r}: raw signal quantity should be 'raw', got {quantity!r}")

        # QC signals: do not require sensor/quantity (can be global flags)

    if errors:
        raise SignalSemanticsError("Signal semantics validation failed:\n- " + "\n- ".join(errors))

# ---------------------------
# Standardisation pass
# ---------------------------

@dataclass
class StandardizeReport:
    renamed: List[Dict[str, Any]]
    derived: List[str]
    notes: List[str]

def canonicalize_signal_names(
    session: Dict[str, Any],
    *,
    spec: SignalSpec = DEFAULT_SPEC,
    units_by_base: Optional[Dict[str, str]] = None,
    domain_by_base: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Rename-only pass:
      - Normalize legacy names -> canonical names (df columns only)
      - Record rename report in session['qc']
      - Does NOT build signals registry
      - Does NOT validate signals semantics
    """
    if "qc" not in session or not isinstance(session["qc"], dict):
        session["qc"] = {}
    qc = session["qc"]
    qc.setdefault("naming", {})
    qc.setdefault("signals", {})

    df: pd.DataFrame = session["df"]

    df2, rename_report = normalize_legacy_columns(
        df,
        spec=spec,
        units_by_base=units_by_base,
        domain_by_base=domain_by_base,
    )
    session["df"] = df2

    qc["naming"]["legacy_renames"] = [r.__dict__ for r in rename_report]
    return session


def rebuild_and_validate_signal_registry(
    session: Dict[str, Any],
    *,
    spec: SignalSpec = DEFAULT_SPEC,
    strict_registry_parse: bool = True,
) -> Dict[str, Any]:
    """
    Final-pass registry rebuild + validation:
      - build_signals_registry()
      - validate_signals_registry_shape()
      - validate_signals_semantics()
    """
    session = build_signals_registry(session, spec=spec, strict=strict_registry_parse)
    validate_signals_registry_shape(session)
    validate_signals_semantics(session, spec=spec)
    return session


def standardize_signals(
    session: Dict[str, Any],
    *,
    spec: SignalSpec = DEFAULT_SPEC,
    units_by_base: Optional[Dict[str, str]] = None,
    domain_by_base: Optional[Dict[str, str]] = None,
    strict_registry_parse: bool = True,
    derive_va: bool = False,
    va_bases: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Backward-compatible wrapper.

    NOTE: VA derivation is now owned by va.py (estimate_va). This wrapper no longer
    supports derive_va=True.
    """
    if derive_va:
        raise ValueError(
            "standardize_signals(derive_va=True) is deprecated/removed; "
            "compute vel/acc in va.py (estimate_va) before rebuilding the registry."
        )

    session = canonicalize_signal_names(
        session,
        spec=spec,
        units_by_base=units_by_base,
        domain_by_base=domain_by_base,
    )
    session = rebuild_and_validate_signal_registry(
        session,
        spec=spec,
        strict_registry_parse=strict_registry_parse,
    )
    return session



