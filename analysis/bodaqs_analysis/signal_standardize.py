# signal_standardize.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple, List

import numpy as np
import pandas as pd

from signalspec import SignalSpec, DEFAULT_SPEC, RAW_UNIT_DEFAULT
from signalname import parse_signal_name, format_signal_name, SignalNameError, SignalNameParts
from signal_registry import build_signals_registry
from model import validate_signals_registry_shape


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

    for col, info in signals.items():
        if col not in df.columns:
            errors.append(f"signals key not in df.columns: {col!r}")
            continue

        s = df[col]
        kind = info.get("kind", "")
        unit = info.get("unit", None)
        domain = info.get("domain", None)
        op_chain = info.get("op_chain", [])

        # Kind must be valid
        if kind not in ("", "raw", "qc"):
            errors.append(f"{col!r}: invalid kind {kind!r}")

        # Domain if present must be allowed
        if domain is not None and spec.strict_domains and domain not in spec.allowed_domains:
            errors.append(f"{col!r}: unknown domain {domain!r}")

        # Ops must be allowed
        if spec.strict_ops:
            bad_ops = [t for t in op_chain if t not in spec.allowed_ops]
            if bad_ops:
                errors.append(f"{col!r}: unknown op token(s) {bad_ops}")

        # Engineered: must have unit
        if kind == "":
            if unit is None or not isinstance(unit, str) or not unit.strip():
                errors.append(f"{col!r}: engineered signal missing unit")

        # Raw: should be counts
        if kind == "raw":
            if unit != RAW_UNIT_DEFAULT:
                errors.append(f"{col!r}: raw signal unit should be '{RAW_UNIT_DEFAULT}', got {unit!r}")

        # QC: should be boolish
        if kind == "qc":
            if not _is_boolish_series(s):
                errors.append(f"{col!r}: qc signal not bool/0-1 dtype={s.dtype}")

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
    Single canonical pass:
      1) legacy rename -> canonical
      2) build signals registry
      3) (optional) derive vel/acc signals (preferred separate signals)
      4) validate registry shape + semantics
      5) record QC report
    """
    from signal_legacy import normalize_legacy_columns  # local import to avoid cycles

    if "df" not in session:
        raise ValueError("session missing 'df'")
    if "meta" not in session:
        raise ValueError("session missing 'meta'")
    if "qc" not in session:
        session["qc"] = {}

    df: pd.DataFrame = session["df"]

    # 1) Normalize legacy names -> canonical
    df2, rename_report = normalize_legacy_columns(
        df,
        spec=spec,
        units_by_base=units_by_base,
        domain_by_base=domain_by_base,
    )
    session["df"] = df2

    # 2) Build registry (strict once legacy normaliser exists)
    session = build_signals_registry(session, spec=spec, strict=strict_registry_parse)
    validate_signals_registry_shape(session)

    derived_cols: List[str] = []
    notes: List[str] = []

    # 3) Optional: derive vel/acc as separate engineered signals
    if derive_va:
        df3, new_cols = derive_velocity_acceleration(
            session,
            spec=spec,
            bases=va_bases,
        )
        session["df"] = df3
        derived_cols.extend(new_cols)

        # registry must be refreshed because df changed
        session = build_signals_registry(session, spec=spec, strict=True)
        validate_signals_registry_shape(session)

    # 4) Enforce semantics
    validate_signals_semantics(session, spec=spec)

    # 5) Record report in QC
    qc = session.setdefault("qc", {})
    qc.setdefault("naming", {})
    qc.setdefault("signals", {})

    qc["naming"]["legacy_renames"] = [r.__dict__ for r in rename_report]
    qc["signals"]["derived_columns"] = derived_cols
    qc["signals"]["notes"] = notes

    return session


# ---------------------------
# Optional VA derivation helpers
# ---------------------------

def derive_velocity_acceleration(
    session: Dict[str, Any],
    *,
    spec: SignalSpec,
    bases: Optional[Sequence[str]] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Derive *_vel and *_acc from engineered position signals with unit [mm] by finite difference.

    This is deliberately simple; you can later swap to your Savitzky-Golay VA estimator.
    """
    df = session["df"].copy()
    sigs = session["meta"]["signals"]

    # Candidate engineered mm signals
    candidates = []
    for col, info in sigs.items():
        if info.get("kind", "") != "":
            continue
        if info.get("unit") != "mm":
            continue
        parts = parse_signal_name(col, spec=spec)
        if parts.ops:
            continue  # only base signals
        if bases is not None and parts.base not in set(bases):
            continue
        candidates.append((col, parts))

    if "time_s" not in df.columns:
        raise ValueError("derive_velocity_acceleration requires df['time_s']")

    t = df["time_s"].to_numpy(dtype=np.float64)
    dt = np.diff(t)
    if len(dt) == 0 or np.nanmin(dt) <= 0:
        raise ValueError("time_s must be strictly increasing for VA derivation")

    new_cols: List[str] = []
    for col, parts in candidates:
        x = df[col].to_numpy(dtype=np.float64)

        # vel: dx/dt (centered-ish using gradient)
        v = np.gradient(x, t)
        vel_name = format_signal_name(
            SignalNameParts(
                base=f"{parts.base}_vel",
                kind="",
                domain=parts.domain,
                unit="mm/s",
                ops=(),
            ),
            spec=spec,
        )
        df[vel_name] = v
        new_cols.append(vel_name)

        a = np.gradient(v, t)
        acc_name = format_signal_name(
            SignalNameParts(
                base=f"{parts.base}_acc",
                kind="",
                domain=parts.domain,
                unit="mm/s^2",
                ops=(),
            ),
            spec=spec,
        )
        df[acc_name] = a
        new_cols.append(acc_name)

    return df, new_cols
