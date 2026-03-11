# -*- coding: utf-8 -*-
"""Shared histogram/stat helpers for widget consumers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


def finite_numeric(values: Any) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return arr[np.isfinite(arr)]


def plot_hist_or_cdf(
    ax: Any,
    values: Any,
    bins: int,
    *,
    cdf: bool,
    norm: bool,
    label: str | None,
) -> None:
    vals = finite_numeric(values)
    if vals.size == 0:
        return

    if cdf:
        x = np.sort(vals)
        y = np.arange(1, len(x) + 1, dtype=float)
        if norm:
            y = y / float(len(x))
        ax.step(x, y, where="post", label=label)
        return

    weights = None
    if norm:
        weights = np.ones_like(vals, dtype=float) / float(len(vals))
    ax.hist(vals, bins=int(bins), weights=weights, histtype="step", label=label)


def series_stats_line(name: str, values: Any) -> str:
    vals = finite_numeric(values)
    if vals.size == 0:
        return f"- {name}: count=0"
    vmin = float(np.min(vals))
    vmax = float(np.max(vals))
    mean = float(np.mean(vals))
    med = float(np.median(vals))
    return f"- {name}: count={len(vals)}  min={vmin:.6g}  max={vmax:.6g}  mean={mean:.6g}  median={med:.6g}"


def parse_optional_float(raw: str) -> float | None:
    txt = str(raw).strip()
    if txt == "":
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def format_metric(value: float) -> str:
    v = float(value)
    if not np.isfinite(v):
        return "NaN"
    return f"{v:.4g}"


@dataclass(frozen=True)
class TrimmedQuantileMetrics:
    n_total: int
    n_trim: int
    insufficient: bool
    q25: float
    q50: float
    q75: float
    q90: float
    q95: float
    iqr: float
    skew_q: float


def compute_trimmed_quantile_metrics(
    values: Any,
    cutoff: float | None,
    *,
    min_count: int = 5,
) -> TrimmedQuantileMetrics:
    finite = finite_numeric(values)
    n_total = int(len(finite))

    trimmed = finite if cutoff is None else finite[finite >= float(cutoff)]
    n_trim = int(len(trimmed))
    if n_trim < int(min_count):
        return TrimmedQuantileMetrics(
            n_total=n_total,
            n_trim=n_trim,
            insufficient=True,
            q25=np.nan,
            q50=np.nan,
            q75=np.nan,
            q90=np.nan,
            q95=np.nan,
            iqr=np.nan,
            skew_q=np.nan,
        )

    q25, q50, q75, q90, q95 = np.quantile(trimmed, [0.25, 0.5, 0.75, 0.9, 0.95])
    iqr = float(q75 - q25)
    skew_q = float("nan")
    if abs(iqr) > 1e-12:
        skew_q = float((q75 + q25 - (2.0 * q50)) / iqr)

    return TrimmedQuantileMetrics(
        n_total=n_total,
        n_trim=n_trim,
        insufficient=False,
        q25=float(q25),
        q50=float(q50),
        q75=float(q75),
        q90=float(q90),
        q95=float(q95),
        iqr=iqr,
        skew_q=skew_q,
    )

