# -*- coding: utf-8 -*-
"""Data/service helpers for the session window browser widget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SessionWindowColumnsConfig:
    session_id_col: str
    event_id_col: str
    event_type_col: str
    event_signal_col: str
    time_col: str


@dataclass(frozen=True)
class SignalOptionsResult:
    registry: dict[str, Mapping[str, Any]]
    registry_cols: list[str]
    numeric_cols_sorted: list[str]
    selected_detail: tuple[str, ...]
    detail_y_range: tuple[float, float] | None


def require_session(
    *,
    session_loader: Callable[[str], Mapping[str, Any]],
    session_key: str,
    time_col: str,
) -> Mapping[str, Any]:
    sess = session_loader(str(session_key))
    if not isinstance(sess, Mapping):
        raise ValueError("session_loader must return a dict-like session")
    if "df" not in sess:
        raise ValueError("session missing required key 'df'")
    df_ = sess["df"]
    if not isinstance(df_, pd.DataFrame):
        raise ValueError("session['df'] must be a pandas DataFrame")
    if time_col not in df_.columns:
        raise ValueError(f"session['df'] must contain {time_col!r} column")
    return sess


def load_optional_df(
    *,
    loader: Callable[[str], pd.DataFrame] | None,
    session_key: str,
) -> pd.DataFrame:
    if loader is None:
        return pd.DataFrame()
    df_ = loader(str(session_key))
    return df_.copy() if isinstance(df_, pd.DataFrame) else pd.DataFrame()


def merge_events_metrics(
    *,
    events_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    session_id_col: str,
    event_id_col: str,
) -> pd.DataFrame:
    if events_df is None or events_df.empty:
        return pd.DataFrame()
    if metrics_df is None or metrics_df.empty:
        return events_df.copy()

    if session_id_col not in events_df.columns or event_id_col not in events_df.columns:
        return events_df.copy()
    if session_id_col not in metrics_df.columns or event_id_col not in metrics_df.columns:
        return events_df.copy()

    join_keys = [session_id_col, event_id_col]
    metric_cols = [c for c in metrics_df.columns if c not in join_keys]
    return events_df.merge(
        metrics_df[join_keys + metric_cols],
        on=join_keys,
        how="left",
        suffixes=("", "_m"),
    )


def _to_numeric_series(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


def _infer_signal_cols_from_registry(session: Mapping[str, Any]) -> list[str]:
    meta = (session or {}).get("meta") or {}
    reg = meta.get("signals") or {}
    if not isinstance(reg, dict):
        return []
    cols = []
    for k in reg.keys():
        if isinstance(k, str) and k.strip():
            cols.append(k.strip())
    return cols


def _filter_primary_analysis_cols(cols: Sequence[str], registry: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return [
        str(c)
        for c in cols
        if isinstance(registry.get(str(c)), Mapping)
        and str(registry[str(c)].get("processing_role") or "").strip().lower() == "primary_analysis"
    ]


def _filter_numeric_cols(df: pd.DataFrame, cols: Sequence[str], *, time_col: str) -> list[str]:
    out = []
    for c in cols:
        if c == time_col:
            continue
        if c not in df.columns:
            continue
        v = _to_numeric_series(df, c).to_numpy(dtype=float)
        if np.isfinite(v).any():
            out.append(c)
    return out


def _sort_cols_by_unit(cols: Sequence[str], registry: Mapping[str, Mapping[str, Any]]) -> list[str]:
    def key(c: str) -> tuple[str, str]:
        info = registry.get(c, {}) if isinstance(registry, Mapping) else {}
        unit = info.get("unit")
        unit = unit.strip() if isinstance(unit, str) else ""
        unit_sort = unit if unit else "~"
        return (unit_sort, c)

    return sorted(list(cols), key=key)


def compute_detail_y_range(df: pd.DataFrame, cols: Sequence[str]) -> tuple[float, float] | None:
    vals = []
    for c in cols:
        if c not in df.columns:
            continue
        v = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        if v.size:
            vals.append(v)
    if not vals:
        return None
    lo = float(np.min([v.min() for v in vals]))
    hi = float(np.max([v.max() for v in vals]))
    if lo == hi:
        lo -= 1.0
        hi += 1.0
    span = hi - lo
    pad = 0.03 * span
    return (lo - pad, hi + pad)


def derive_signal_options(
    *,
    session: Mapping[str, Any],
    prev_detail: Sequence[str],
    time_col: str,
    preferred_unit: str = "mm",
    primary_only: bool = False,
) -> SignalOptionsResult:
    df_ = session["df"]
    meta = (session or {}).get("meta") or {}
    registry = meta.get("signals") or {}
    registry = registry if isinstance(registry, dict) else {}

    registry_cols = _infer_signal_cols_from_registry(session)
    if not registry_cols:
        registry_cols = [c for c in df_.columns if isinstance(c, str)]
    if primary_only:
        registry_cols = _filter_primary_analysis_cols(registry_cols, registry)

    numeric_cols = _filter_numeric_cols(df_, registry_cols, time_col=time_col)
    if not numeric_cols:
        numeric_cols = [c for c in df_.columns if c != time_col and pd.api.types.is_numeric_dtype(df_[c])]

    numeric_cols_sorted = _sort_cols_by_unit(numeric_cols, registry)
    opts = list(map(str, numeric_cols_sorted))
    kept = tuple([c for c in map(str, prev_detail) if c in opts])

    if kept:
        selected = kept
    else:
        unit_cols = [
            c
            for c in opts
            if (
                isinstance(registry, Mapping)
                and isinstance(registry.get(c, {}), Mapping)
                and str(registry.get(c, {}).get("unit", "")).strip() == preferred_unit
            )
        ]
        chosen = unit_cols[0] if unit_cols else (opts[0] if opts else None)
        selected = (chosen,) if chosen else ()

    detail_y_range = compute_detail_y_range(df_, selected)
    return SignalOptionsResult(
        registry=dict(registry),
        registry_cols=registry_cols,
        numeric_cols_sorted=numeric_cols_sorted,
        selected_detail=selected,
        detail_y_range=detail_y_range,
    )


def build_event_type_pair_options(
    *,
    merged: pd.DataFrame,
    event_type_col: str,
    event_signal_col: str,
    key_builder: Callable[[str, str], str],
) -> list[tuple[str, str]]:
    if (
        merged is None
        or merged.empty
        or event_type_col not in merged.columns
        or event_signal_col not in merged.columns
    ):
        return []

    m = merged[[event_type_col, event_signal_col]].copy()
    m[event_type_col] = m[event_type_col].astype(str)
    m[event_signal_col] = m[event_signal_col].astype(str)

    pairs = (
        m.dropna()
        .drop_duplicates()
        .sort_values([event_type_col, event_signal_col])
    )

    opts: list[tuple[str, str]] = []
    for _, r in pairs.iterrows():
        et = str(r[event_type_col])
        sig = str(r[event_signal_col])
        label = f"{et} - {sig}"
        key = key_builder(et, sig)
        opts.append((label, key))
    return opts

