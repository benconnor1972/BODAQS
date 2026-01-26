# -*- coding: utf-8 -*-
"""
BODAQS signal-sample histogram widget (loader-based).

Public API:
    make_signal_histogram_widget_for_loader(
        events_df,
        *,
        session_loader,
        default_bins=50,
    )
"""

from __future__ import annotations

from typing import Any, Dict, Callable, List, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import ipywidgets as W
from IPython.display import display, clear_output


# -------------------------
# Registry helpers
# -------------------------

def _registry_signal_cols(session: Dict[str, Any]) -> List[str]:
    """
    Prefer session["meta"]["signals"] keys as canonical signal names.
    Fallback to meta["channels"], then numeric df columns.
    """
    meta = session.get("meta") or {}
    df: pd.DataFrame = session["df"]

    signals = meta.get("signals")
    if isinstance(signals, dict) and signals:
        return [c for c in signals.keys() if c in df.columns]

    channels = meta.get("channels")
    if isinstance(channels, list):
        return [c for c in channels if c in df.columns]

    cols: List[str] = []
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        if np.isfinite(s.to_numpy()).any():
            cols.append(c)
    return cols


def _vals(df: pd.DataFrame, col: str, dropna: bool) -> np.ndarray:
    s = pd.to_numeric(df[col], errors="coerce")
    v = s.to_numpy(dtype=float, copy=False)
    if dropna:
        v = v[np.isfinite(v)]
    return v


# -------------------------
# Widget
# -------------------------

def make_signal_histogram_widget_for_loader(
    events_df: pd.DataFrame,
    *,
    session_loader: Callable[[str], Dict[str, Any]],
    default_bins: int = 50,
    max_bins: int = 500,
) -> dict:
    """
    Signal histogram / CDF widget using session_loader.

    Sessions are discovered from events_df["session_id"].
    Signals are listed from each session's registry.
    """

    if "session_id" not in events_df.columns:
        raise ValueError("events_df must contain 'session_id' column")

    session_ids = sorted(events_df["session_id"].astype(str).unique())

    # Load ONE session to discover registry signals
    first_session = session_loader(session_ids[0])
    signal_cols = sorted(_registry_signal_cols(first_session))

    if not signal_cols:
        raise ValueError("No signal columns found in registry or df")

    # --- UI ---
    w_sessions_mode = W.RadioButtons(
        options=[("Aggregate sessions", False), ("Compare sessions", True)],
        value=False,
        description="Sessions:",
    )
    w_sessions = W.SelectMultiple(
        options=session_ids,
        value=tuple(session_ids[:1]),
        description="Pick:",
    )

    w_signals_mode = W.RadioButtons(
        options=[("Aggregate signals", False), ("Compare signals", True)],
        value=False,
        description="Signals:",
    )
    w_signals = W.SelectMultiple(
        options=signal_cols,
        value=tuple(signal_cols[:1]),
        description="Pick:",
        rows=8,
    )

    w_bins = W.BoundedIntText(value=default_bins, min=1, max=max_bins, description="Bins:")
    w_cdf = W.Checkbox(value=False, description="CDF")
    w_norm = W.Checkbox(value=True, description="Normalize")
    w_dropna = W.Checkbox(value=True, description="Drop NaN/inf")

    out = W.Output()

    # --- render ---
    def _render(*_):
        with out:
            clear_output(wait=True)

            sel_sessions = list(w_sessions.value)
            sel_signals = list(w_signals.value)

            if not sel_sessions or not sel_signals:
                print("Select at least one session and one signal.")
                return

            compare_sessions = bool(w_sessions_mode.value)
            compare_signals = bool(w_signals_mode.value)

            series: List[Tuple[str, np.ndarray]] = []

            def get_vals(sid: str, sig: str) -> np.ndarray:
                session = session_loader(str(sid))
                return _vals(session["df"], sig, dropna=w_dropna.value)

            if compare_sessions and compare_signals:
                for sid in sel_sessions:
                    for sig in sel_signals:
                        series.append((f"{sid} | {sig}", get_vals(sid, sig)))

            elif compare_sessions:
                for sid in sel_sessions:
                    vals = np.concatenate([get_vals(sid, sig) for sig in sel_signals])
                    series.append((sid, vals))

            elif compare_signals:
                for sig in sel_signals:
                    vals = np.concatenate([get_vals(sid, sig) for sid in sel_sessions])
                    series.append((sig, vals))

            else:
                vals = np.concatenate(
                    [get_vals(sid, sig) for sid in sel_sessions for sig in sel_signals]
                )
                series.append(("aggregate", vals))

            fig, ax = plt.subplots(figsize=(8.3, 4.2))

            for name, vals in series:
                if w_cdf.value:
                    x = np.sort(vals)
                    y = np.arange(1, len(x) + 1)
                    if w_norm.value:
                        y = y / len(x)
                    ax.step(x, y, where="post", label=name)
                else:
                    weights = None
                    if w_norm.value:
                        weights = np.ones_like(vals) / len(vals)
                    ax.hist(vals, bins=w_bins.value, histtype="step", weights=weights, label=name)

            ax.set_title("Signal sample distribution")
            ax.set_xlabel("Signal value")
            ax.set_ylabel("Cumulative proportion" if w_cdf.value else "Proportion" if w_norm.value else "Count")
            ax.grid(True, alpha=0.3)

            if compare_sessions or compare_signals:
                ax.legend(fontsize=9)

            plt.show()

    for w in (
        w_sessions_mode, w_sessions,
        w_signals_mode, w_signals,
        w_bins, w_cdf, w_norm, w_dropna,
    ):
        w.observe(_render, names="value")

    controls = W.VBox([
        W.HBox([w_bins, w_cdf, w_norm, w_dropna]),
        W.HBox([
            W.VBox([w_sessions_mode, w_sessions]),
            W.VBox([w_signals_mode, w_signals]),
        ]),
    ])

    display(W.VBox([controls, out]))
    _render()

    return {
        "out": out,
        "session_ids": session_ids,
        "signal_cols": signal_cols,
    }
