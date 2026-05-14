# -*- coding: utf-8 -*-
"""Scope/data helpers for the signal histogram widget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from bodaqs_analysis.widgets.contracts import RegistryPolicy
from bodaqs_analysis.widgets.registry_scope import compute_signal_universe


@dataclass(frozen=True)
class ScopeSignalResolution:
    options: list[str]
    by_session: dict[str, list[str]]


def registry_signal_cols(session: Mapping[str, Any]) -> list[str]:
    """
    Prefer session['meta']['signals'] keys as canonical signal names.
    Fallback to meta['channels'], then numeric df columns.
    """
    meta = session.get("meta") or {}
    df: pd.DataFrame = session["df"]

    signals = meta.get("signals")
    if isinstance(signals, dict) and signals:
        return [c for c in signals.keys() if c in df.columns]

    channels = meta.get("channels")
    if isinstance(channels, list):
        return [c for c in channels if c in df.columns]

    cols: list[str] = []
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        if np.isfinite(s.to_numpy()).any():
            cols.append(c)
    return cols


def _primary_analysis_signal_cols(session: Mapping[str, Any], cols: list[str]) -> list[str]:
    meta = session.get("meta") or {}
    signals = meta.get("signals")
    if not isinstance(signals, Mapping):
        return []
    return [
        c
        for c in cols
        if isinstance(signals.get(c), Mapping)
        and str(signals[c].get("processing_role") or "").strip().lower() == "primary_analysis"
    ]


def signal_values(
    df: pd.DataFrame,
    col: str,
    *,
    dropna: bool,
    include_inactive: bool,
) -> np.ndarray:
    if col not in df.columns:
        return np.array([], dtype=float)

    s = pd.to_numeric(df[col], errors="coerce")
    if (not include_inactive) and ("active_mask_qc" in df.columns):
        mask = df["active_mask_qc"].astype(bool)
        s = s[mask]

    v = s.to_numpy(dtype=float, copy=False)
    if dropna:
        v = v[np.isfinite(v)]
    return v


def resolve_scope_signal_options(
    *,
    scope_sessions: list[str],
    get_session: Callable[[str], Mapping[str, Any]],
    registry_policy: RegistryPolicy,
    primary_only: bool = False,
) -> ScopeSignalResolution:
    session_signal_cols: dict[str, list[str]] = {}
    registry_by_session: dict[str, Mapping[str, Mapping[str, Any]]] = {}

    for sid in scope_sessions:
        sess = get_session(str(sid))
        meta = sess.get("meta") or {}
        reg = meta.get("signals")
        reg = reg if isinstance(reg, dict) else {}
        registry_by_session[str(sid)] = reg
        cols = list(registry_signal_cols(sess))
        if primary_only:
            cols = _primary_analysis_signal_cols(sess, cols)
        session_signal_cols[str(sid)] = cols

    signals = compute_signal_universe(
        session_ids=scope_sessions,
        session_signal_cols=session_signal_cols,
        registry_by_session=registry_by_session,
        policy=registry_policy,
    )
    return ScopeSignalResolution(options=signals, by_session=session_signal_cols)

