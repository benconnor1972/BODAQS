# -*- coding: utf-8 -*-
"""
Metric histogram / CDF browser widget.

Consumer-pattern implementation for the BODAQS JupyterLab artifacts pipeline.

Public APIs:
    - make_metric_histogram_widget(events_df, metrics_df, ...)            # legacy-friendly
    - make_metric_histogram_widget_for_loader(store, key_to_ref, ...)     # selector consumer pattern
    - make_metric_histogram_rebuilder(sel, ...)                           # rebuild-on-selector-change pattern

Notes:
- Expects metric columns prefixed with "m_".
- Joins events and metrics on a stable identity key:
    (session_key, schema_id, event_id) by default.
- Supports comparing sessions and/or signals, or aggregating across them.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Sequence, Tuple, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import ipywidgets as W
from IPython.display import display, clear_output

logger = logging.getLogger(__name__)


# -------------------------
# Helpers
# -------------------------

def _require_cols(df: pd.DataFrame, cols: Sequence[str], *, name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required column(s): {missing}")

def _uniq(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

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


def _build_viz_df(
    *,
    events_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    session_key_col: str,
    event_id_col: str,
    schema_id_col: str,
    event_type_col: str,
    signal_col: str,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Join events + metrics into a single viz_df and return (viz_df, metric_cols).
    """
    if events_df is None or len(events_df) == 0:
        raise ValueError("events_df is empty")
    if metrics_df is None or len(metrics_df) == 0:
        raise ValueError("metrics_df is empty")

    _require_cols(events_df, (session_key_col, event_id_col, schema_id_col, event_type_col, signal_col), name="events_df")
    _require_cols(metrics_df, (session_key_col, event_id_col, schema_id_col), name="metrics_df")

    metric_cols = _metric_cols(metrics_df)
    if not metric_cols:
        raise ValueError("No metric columns found in metrics_df (expected columns prefixed with 'm_')")

    left_cols = _uniq([session_key_col, schema_id_col, event_id_col, event_type_col, signal_col])
    right_cols = _uniq([session_key_col, schema_id_col, event_id_col] + metric_cols)

    viz_df = events_df[left_cols].merge(
        metrics_df[right_cols],
        on=[session_key_col, schema_id_col, event_id_col],
        how="inner",
        validate="one_to_one",
    )

    return viz_df, metric_cols


# -------------------------
# Widget constructors
# -------------------------

def make_metric_histogram_widget(
    events_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    *,
    # legacy defaults kept, but see for_loader below for consumer defaults
    session_key_col: str = "session_id",
    event_id_col: str = "event_id",
    schema_id_col: str = "schema_id",
    event_type_col: str = "event_name",
    signal_col: str = "signal_col",
    default_bins: int = 50,
    max_bins: int = 200,
) -> dict:
    """
    Legacy-friendly constructor.

    Prefer make_metric_histogram_widget_for_loader() in consumer notebooks.
    """
    viz_df, metric_cols = _build_viz_df(
        events_df=events_df,
        metrics_df=metrics_df,
        session_key_col=session_key_col,
        event_id_col=event_id_col,
        schema_id_col=schema_id_col,
        event_type_col=event_type_col,
        signal_col=signal_col,
    )
    return _make_widget_from_viz_df(
        viz_df=viz_df,
        metric_cols=metric_cols,
        session_key_col=session_key_col,
        event_type_col=event_type_col,
        signal_col=signal_col,
        default_bins=default_bins,
        max_bins=max_bins,
    )


def make_metric_histogram_widget_for_loader(
    *,
    store: Any,
    key_to_ref: Dict[str, Tuple[str, str]],
    events_index_df: pd.DataFrame,
    session_loader: Any = None,  # kept for symmetry / future per-session access
    session_key_col: str = "session_key",
    event_id_col: str = "event_id",
    schema_id_col: str = "schema_id",
    event_type_col: str = "schema_id",
    signal_col: str = "signal_col",
    default_bins: int = 10,
    max_bins: int = 200,
) -> dict:
    """
    Consumer-pattern metric histogram widget.

    Loads events/metrics for the selector scope via the store helpers, builds viz_df, and displays UI.
    """
    if events_index_df is None or len(events_index_df) == 0:
        raise ValueError("events_index_df is empty")
    if not key_to_ref:
        raise ValueError("key_to_ref is empty")

    # Import here to avoid circular imports in some notebook setups
    from bodaqs_analysis.widgets.loaders import load_all_events_for_selected, load_all_metrics_for_selected

    events_df_sel = load_all_events_for_selected(store, key_to_ref=key_to_ref)
    metrics_df_sel = load_all_metrics_for_selected(store, key_to_ref=key_to_ref)

    viz_df, metric_cols = _build_viz_df(
        events_df=events_df_sel,
        metrics_df=metrics_df_sel,
        session_key_col=session_key_col,
        event_id_col=event_id_col,
        schema_id_col=schema_id_col,
        event_type_col=event_type_col,
        signal_col=signal_col,
    )

    return _make_widget_from_viz_df(
        viz_df=viz_df,
        metric_cols=metric_cols,
        session_key_col=session_key_col,
        event_type_col=event_type_col,
        signal_col=signal_col,
        default_bins=default_bins,
        max_bins=max_bins,
    )


def _make_widget_from_viz_df(
    *,
    viz_df: pd.DataFrame,
    metric_cols: List[str],
    session_key_col: str,
    event_type_col: str,
    signal_col: str,
    default_bins: int,
    max_bins: int,
) -> dict:
    """Internal: builds the interactive UI from a prepared viz_df."""
    logger.info("metric_histogram: viz_df shape: %s", getattr(viz_df, "shape", None))

    sessions = sorted(viz_df[session_key_col].dropna().astype(str).unique().tolist())
    event_types = sorted(viz_df[event_type_col].dropna().astype(str).unique().tolist())
    signals = sorted(viz_df[signal_col].dropna().astype(str).unique().tolist())
    metrics = sorted(metric_cols)

    if not sessions:
        raise ValueError(f"No non-null {session_key_col!r} values after join")
    if not event_types:
        raise ValueError(f"No non-null values found in {event_type_col!r} after join")
    if not signals:
        raise ValueError(f"No non-null values found in {signal_col!r} after join")

    # --- widgets ---
    lbl_sessions = W.Label("Sessions")
    w_sess_mode = W.RadioButtons(
        options=[("Aggregate sessions", False), ("Compare sessions", True)],
        value=False,
        description="",
    )
    w_sessions = W.SelectMultiple(
        options=sessions,
        value=tuple(sessions),  # default: include all sessions to avoid empty intersections
        rows=min(8, max(3, len(sessions))),
    )

    lbl_signals = W.Label("Signals")
    w_sig_mode = W.RadioButtons(
        options=[("Aggregate signals", False), ("Compare signals", True)],
        value=False,
        description="",
    )
    w_signals = W.SelectMultiple(
        options=signals,
        value=tuple(signals[:1]),
        rows=min(8, max(3, len(signals))),
    )

    w_event = W.Dropdown(options=event_types, value=event_types[0], description="Event:")
    w_metric = W.Dropdown(options=metrics, value=metrics[0], description="Metric:")
    w_bins = W.BoundedIntText(value=int(default_bins), min=1, max=int(max_bins), step=1, description="Bins:")
    w_cdf = W.Checkbox(value=False, description="CDF")
    w_norm = W.Checkbox(value=True, description="Normalize")
    w_dropna = W.Checkbox(value=True, description="Drop NaNs")

    out = W.Output()

    def _render(*_):
        with out:
            clear_output(wait=True)

            sel_sessions = list(map(str, w_sessions.value or ()))
            sel_signals = list(map(str, w_signals.value or ()))

            if not sel_sessions:
                print("Select at least one session.")
                return
            if not sel_signals:
                print("Select at least one signal.")
                return

            base = viz_df[
                (viz_df[event_type_col].astype(str) == str(w_event.value))
                & (viz_df[session_key_col].astype(str).isin(sel_sessions))
                & (viz_df[signal_col].astype(str).isin(sel_signals))
            ]

            compare_sessions = bool(w_sess_mode.value)
            compare_signals = bool(w_sig_mode.value)

            series: List[Tuple[str, np.ndarray]] = []

            def _vals(sub: pd.DataFrame) -> np.ndarray:
                s = pd.to_numeric(sub[w_metric.value], errors="coerce")
                if w_dropna.value:
                    s = s.dropna()
                return s.to_numpy()

            if compare_sessions and compare_signals:
                for sk in sel_sessions:
                    for sig in sel_signals:
                        sub = base[(base[session_key_col].astype(str) == sk) & (base[signal_col].astype(str) == sig)]
                        series.append((f"{sk} | {sig}", _vals(sub)))

            elif compare_sessions and (not compare_signals):
                for sk in sel_sessions:
                    sub = base[base[session_key_col].astype(str) == sk]
                    series.append((str(sk), _vals(sub)))

            elif (not compare_sessions) and compare_signals:
                for sig in sel_signals:
                    sub = base[base[signal_col].astype(str) == sig]
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
            ax.set_ylabel(
                ("Cumulative proportion" if w_norm.value else "Cumulative count") if w_cdf.value
                else ("Proportion" if w_norm.value else "Count")
            )
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

    for w in (w_sess_mode, w_sessions, w_sig_mode, w_signals, w_event, w_metric, w_bins, w_cdf, w_norm, w_dropna):
        w.observe(_render, names="value")

    top_row = W.HBox(
        [w_event, w_metric, w_bins, w_cdf, w_norm, w_dropna],
        layout=W.Layout(
            justify_content="flex-start",
            align_items="center",
            gap="10px",
            flex_flow="row wrap",
        ),
    )

    sessions_col = W.VBox([lbl_sessions, w_sess_mode, w_sessions], layout=W.Layout(align_items="flex-start"))
    signals_col = W.VBox([lbl_signals, w_sig_mode, w_signals], layout=W.Layout(align_items="flex-start"))

    controls = W.VBox(
        [
            top_row,
            W.HBox([sessions_col, signals_col], layout=W.Layout(gap="12px", align_items="flex-start")),
        ]
    )

    display(W.VBox([controls, out]))
    _render()

    return {"viz_df": viz_df, "out": out}


def make_metric_histogram_rebuilder(
    *,
    sel: Dict[str, Any],
    out: Optional[W.Output] = None,
    session_key_col: str = "session_key",
    event_id_col: str = "event_id",
    schema_id_col: str = "schema_id",
    event_type_col: str = "schema_id",
    signal_col: str = "signal_col",
    default_bins: int = 10,
    max_bins: int = 200,
) -> Dict[str, Any]:
    """
    Rebuild-on-selector-change helper.

    Returns: {"out": out, "rebuild": rebuild, "state": {"handles": ...}}
    """
    from IPython.display import clear_output
    from bodaqs_analysis.widgets.loaders import make_session_loader

    if out is None:
        out = W.Output()

    state: Dict[str, Any] = {"handles": None}

    def rebuild() -> None:
        store = sel["store"]
        key_to_ref = sel["get_key_to_ref"]()
        events_index_df = sel["get_events_index_df"]()
        session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)

        with out:
            clear_output(wait=True)
            state["handles"] = make_metric_histogram_widget_for_loader(
                store=store,
                key_to_ref=key_to_ref,
                events_index_df=events_index_df,
                session_loader=session_loader,
                session_key_col=session_key_col,
                event_id_col=event_id_col,
                schema_id_col=schema_id_col,
                event_type_col=event_type_col,
                signal_col=signal_col,
                default_bins=default_bins,
                max_bins=max_bins,
            )

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}
