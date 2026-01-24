# -*- coding: utf-8 -*-
"""
Metric histogram / CDF browser widget.

Refactor of the notebook-cell widget into a reusable module function.

Public API:
    make_metric_histogram_widget(events_df, metrics_df, ...)

Notes:
- Expects metrics columns prefixed with "m_".
- Joins events_df and metrics_df on (session_id, event_id) with one_to_one validation.
- Supports comparing sessions and/or signals, or aggregating across them.
"""

from __future__ import annotations

import logging
from typing import List, Sequence, Tuple, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import ipywidgets as W
from IPython.display import display, clear_output


logger = logging.getLogger(__name__)


def _require_cols(df: pd.DataFrame, cols: Sequence[str], *, name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required column(s): {missing}")


def _metric_cols(metrics_df: pd.DataFrame) -> List[str]:
    cols: List[str] = []
    for c in metrics_df.columns:
        if isinstance(c, str) and c.startswith("m_"):
            cols.append(c)
    return cols


def _series_stats(name: str, vals: np.ndarray) -> str:
    vals = np.asarray(vals, dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return f"- {name}: count=0"
    vmin = float(np.min(vals))
    vmax = float(np.max(vals))
    mean = float(np.mean(vals))
    med = float(np.median(vals))
    return f"- {name}: count={len(vals)}  min={vmin:.6g}  max={vmax:.6g}  mean={mean:.6g}  median={med:.6g}"


def _plot_series(
    ax,
    vals: np.ndarray,
    bins: int,
    *,
    cdf: bool,
    norm: bool,
    label: Optional[str],
) -> None:
    vals = np.asarray(vals, dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return

    if cdf:
        x = np.sort(vals)
        y = np.arange(1, len(x) + 1, dtype=float)
        if norm:
            y = y / float(len(x))
        ax.step(x, y, where="post", label=label)
    else:
        weights = None
        if norm:
            weights = np.ones_like(vals, dtype=float) / float(len(vals))
        ax.hist(vals, bins=int(bins), weights=weights, histtype="step", label=label)


def make_metric_histogram_widget(
    events_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    *,
    event_type_col: str = "event_name",
    signal_col: str = "signal_col",
    default_bins: int = 10,
    max_bins: int = 200,
) -> dict:
    """
    Build and display an interactive histogram/CDF widget for metrics.

    Returns a small dict of handles (includes 'out' and 'viz_df').
    """
    logger.debug("events_df shape: %s", getattr(events_df, "shape", None))
    logger.debug("metrics_df shape: %s", getattr(metrics_df, "shape", None))

    if events_df is None or len(events_df) == 0:
        raise ValueError("events_df is empty")
    if metrics_df is None or len(metrics_df) == 0:
        raise ValueError("metrics_df is empty")

    _require_cols(events_df, ("session_id", "event_id", event_type_col, signal_col), name="events_df")
    _require_cols(metrics_df, ("session_id", "event_id"), name="metrics_df")

    metric_cols = _metric_cols(metrics_df)
    if not metric_cols:
        raise ValueError("No metric columns found in metrics_df (expected columns prefixed with 'm_')")

    # Join
    viz_df = events_df[["session_id", "event_id", event_type_col, signal_col]].merge(
        metrics_df[["session_id", "event_id"] + metric_cols],
        on=["session_id", "event_id"],
        how="inner",
        validate="one_to_one",
    )

    logger.info("metric_histogram: joined viz_df shape: %s", viz_df.shape)

    sessions = sorted([x for x in viz_df["session_id"].dropna().unique().tolist()])
    event_types = sorted([x for x in viz_df[event_type_col].dropna().unique().tolist()])
    signals = sorted([x for x in viz_df[signal_col].dropna().unique().tolist()])
    metrics = sorted(metric_cols)

    if not sessions:
        raise ValueError("No non-null session_id values after join")
    if not event_types:
        raise ValueError(f"No non-null values found in {event_type_col!r} after join")
    if not signals:
        raise ValueError(f"No non-null values found in {signal_col!r} after join")

    # --- widgets ---
    w_sess_mode = W.RadioButtons(
        options=[("Aggregate sessions", False), ("Compare sessions", True)],
        value=False,
        description="Sessions:",
    )
    w_sessions = W.SelectMultiple(
        options=sessions,
        value=tuple(sessions[:1]),
        description="Pick:",
        rows=min(8, max(3, len(sessions))),
    )

    w_sig_mode = W.RadioButtons(
        options=[("Aggregate signals", False), ("Compare signals", True)],
        value=False,
        description="Signals:",
    )
    w_signals = W.SelectMultiple(
        options=signals,
        value=tuple(signals[:1]),
        description="Pick:",
        rows=min(8, max(3, len(signals))),
    )

    w_event = W.Dropdown(options=event_types, value=event_types[0], description="Event:")
    w_metric = W.Dropdown(options=metrics, value=metrics[0], description="Metric:")
    w_bins = W.BoundedIntText(value=int(default_bins), min=1, max=int(max_bins), step=1, description="Bins:")
    w_cdf = W.Checkbox(value=False, description="CDF (cumulative)")
    w_norm = W.Checkbox(value=True, description="Normalize (proportion)")

    out = W.Output()

    def _render(*_):
        with out:
            clear_output(wait=True)

            sel_sessions = list(w_sessions.value)
            sel_signals = list(w_signals.value)

            if not sel_sessions:
                print("Select at least one session.")
                return
            if not sel_signals:
                print("Select at least one signal.")
                return

            base = viz_df[
                (viz_df[event_type_col] == w_event.value)
                & (viz_df["session_id"].isin(sel_sessions))
                & (viz_df[signal_col].isin(sel_signals))
            ]

            compare_sessions = bool(w_sess_mode.value)
            compare_signals = bool(w_sig_mode.value)

            series: List[Tuple[str, np.ndarray]] = []

            def _vals(sub: pd.DataFrame) -> np.ndarray:
                return pd.to_numeric(sub[w_metric.value], errors="coerce").dropna().to_numpy()

            if compare_sessions and compare_signals:
                for sid in sel_sessions:
                    for sig in sel_signals:
                        sub = base[(base["session_id"] == sid) & (base[signal_col] == sig)]
                        series.append((f"{sid} | {sig}", _vals(sub)))

            elif compare_sessions and (not compare_signals):
                for sid in sel_sessions:
                    sub = base[base["session_id"] == sid]
                    series.append((str(sid), _vals(sub)))

            elif (not compare_sessions) and compare_signals:
                for sig in sel_signals:
                    sub = base[base[signal_col] == sig]
                    series.append((str(sig), _vals(sub)))

            else:
                series.append(("aggregate", _vals(base)))

            fig, ax = plt.subplots(figsize=(8.3, 4.2))

            for name, vals in series:
                _plot_series(
                    ax,
                    vals,
                    int(w_bins.value),
                    cdf=bool(w_cdf.value),
                    norm=bool(w_norm.value),
                    label=(name if (compare_sessions or compare_signals) else None),
                )

            mode_bits = [
                ("sessions=compare" if compare_sessions else "sessions=aggregate"),
                ("signals=compare" if compare_signals else "signals=aggregate"),
            ]

            ax.set_title(
                f"{w_metric.value} distribution\n"
                f"{event_type_col}={w_event.value} | {', '.join(mode_bits)}"
            )
            ax.set_xlabel(w_metric.value)
            if w_cdf.value:
                ax.set_ylabel("Cumulative proportion" if w_norm.value else "Cumulative count")
            else:
                ax.set_ylabel("Proportion" if w_norm.value else "Count")

            ax.grid(True, which="major", axis="both", alpha=0.3)

            if (compare_sessions or compare_signals):
                ax.legend(title="series", fontsize=9)

            if all(len(v) == 0 for _, v in series):
                ax.text(
                    0.5,
                    0.5,
                    "No numeric values after filtering",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )
                ax.set_axis_off()

            plt.show()

            print("Summary stats:")
            for name, vals in series:
                print(_series_stats(name, vals))

    for w in (w_sess_mode, w_sessions, w_sig_mode, w_signals, w_event, w_metric, w_bins, w_cdf, w_norm):
        w.observe(_render, names="value")

    controls = W.VBox(
        [
            W.HBox([w_event, w_metric, w_bins, w_cdf, w_norm]),
            W.HBox(
                [
                    W.VBox([w_sess_mode, w_sessions]),
                    W.VBox([w_sig_mode, w_signals]),
                ]
            ),
        ]
    )

    display(W.VBox([controls, out]))
    _render()

    return {"viz_df": viz_df, "out": out}
