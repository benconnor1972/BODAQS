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

from typing import Any, Dict, Callable, List, Tuple, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import ipywidgets as W
from IPython.display import display, clear_output
from bodaqs_analysis.widgets.loaders import make_session_loader

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

def _vals(df: pd.DataFrame, col: str, dropna: bool, *, include_inactive: bool) -> np.ndarray:
    s = pd.to_numeric(df[col], errors="coerce")

    # Apply activity mask unless the user explicitly includes inactive samples.
    if (not include_inactive) and ("active_mask_qc" in df.columns):
        mask = df["active_mask_qc"].astype(bool)
        s = s[mask]

    v = s.to_numpy(dtype=float, copy=False)
    if dropna:
        v = v[np.isfinite(v)]
    return v

def _sort_signals_by_unit(
    signal_cols: list[str],
    registry: dict,
) -> list[str]:
    """
    Sort signals by unit, then by signal name.
    Unknown units are grouped last.
    """
    def key(sig: str):
        info = registry.get(sig, {})
        unit = info.get("unit")
        unit = unit if isinstance(unit, str) and unit.strip() else "~"  # '~' sorts after letters
        return (unit, sig)

    return sorted(signal_cols, key=key)


def _compute_trimmed_metrics(values: np.ndarray, a: Optional[float]) -> Dict[str, Any]:
    vals = np.asarray(values, dtype=float)
    finite = vals[np.isfinite(vals)]
    n_total = int(len(finite))

    trimmed = finite if a is None else finite[finite >= float(a)]
    n_trim = int(len(trimmed))

    out: Dict[str, Any] = {
        "n_total": n_total,
        "n_trim": n_trim,
        "insufficient": n_trim < 5,
        "q25": np.nan,
        "q50": np.nan,
        "q75": np.nan,
        "q90": np.nan,
        "q95": np.nan,
        "iqr": np.nan,
        "skew_q": np.nan,
    }
    if out["insufficient"]:
        return out

    q25, q50, q75, q90, q95 = np.quantile(trimmed, [0.25, 0.5, 0.75, 0.9, 0.95])
    iqr = float(q75 - q25)
    skew_q = float("nan")
    if abs(iqr) > 1e-12:
        skew_q = float((q75 + q25 - (2.0 * q50)) / iqr)

    out.update(
        {
            "q25": float(q25),
            "q50": float(q50),
            "q75": float(q75),
            "q90": float(q90),
            "q95": float(q95),
            "iqr": iqr,
            "skew_q": skew_q,
        }
    )
    return out


def _parse_trim_cutoff(raw: str) -> Optional[float]:
    txt = str(raw).strip()
    if txt == "":
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _fmt_metric(value: float) -> str:
    v = float(value)
    if not np.isfinite(v):
        return "NaN"
    return f"{v:.4g}"


# -------------------------
# Widget
# -------------------------

def make_signal_histogram_widget_for_loader(
    events_df: pd.DataFrame,
    *,
    session_loader: Callable[[str], Dict[str, Any]],
    session_key_col: str = "session_id",
    default_bins: int = 50,
    max_bins: int = 500,
) -> dict:
    """
    Signal histogram / CDF widget using session_loader.

    Sessions are discovered from events_df[session_key_col].
    Signals are listed from each session's registry.
    """
    if session_key_col not in events_df.columns:
        raise ValueError(f"events_df must contain {session_key_col!r} column")

    session_ids = sorted(events_df[session_key_col].astype(str).unique())


    # Load ONE session to discover registry signals
    first_session = session_loader(session_ids[0])

    # Registry from the loaded session (canonical metadata)
    registry = (first_session.get("meta") or {}).get("signals") or {}
    if not isinstance(registry, dict):
        registry = {}

    signal_cols = list(_registry_signal_cols(first_session))
    signal_cols = _sort_signals_by_unit(signal_cols, registry)


    if not signal_cols:
        raise ValueError("No signal columns found in registry or df")

    # --- UI ---
    sessions_label = W.Label("Sessions:")
    w_sessions_mode = W.RadioButtons(
        options=[("Aggregate sessions", False), ("Compare sessions", True)],
        value=False,
        description="",
    )
    w_sessions = W.SelectMultiple(
        options=session_ids,
        value=tuple(session_ids[:1]),
        description="",
        rows=min(8, max(3, len(session_ids), len(signal_cols))),
        layout=W.Layout(width="450px"),
    )

    signals_label = W.Label("Signals:")
    w_signals_mode = W.RadioButtons(
        options=[("Aggregate signals", False), ("Compare signals", True)],
        value=True,
        description="",
    )
    w_signals = W.SelectMultiple(
        options=signal_cols,
        value=tuple(signal_cols[:1]),
        description="",
        rows=min(8, max(3, len(session_ids), len(signal_cols))),
        layout=W.Layout(width="450px"),

    )

    w_bins = W.BoundedIntText(value=default_bins, min=1, max=max_bins, description="Bins:", layout = W.Layout(width="150px"))
    w_cdf = W.Checkbox(value=False, description="CDF")
    w_norm = W.Checkbox(value=True, description="Normalize")
    w_dropna = W.Checkbox(value=True, description="Drop NaN/inf")
    w_include_inactive = W.Checkbox(value=False, description="Include inactive")
    w_show_metrics = W.Checkbox(value=False, description="Show metrics")
    w_trim_a = W.Text(
        value="",
        description="Trim cutoff (a):",
        placeholder="blank = no trimming",
        layout=W.Layout(width="240px"),
    )
    w_trim_help = W.HTML("<small>Exclude values &lt; a from metric computation.</small>")
    for w in (w_cdf, w_norm, w_dropna, w_include_inactive, w_show_metrics):
        w.layout = W.Layout(width="auto")

    def _toggle_trim_input(*_):
        enabled = bool(w_show_metrics.value)
        w_trim_a.disabled = not enabled
        w_trim_help.layout = W.Layout(display="block" if enabled else "none")

    _toggle_trim_input()

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
                return _vals(
                    session["df"],
                    sig,
                    dropna=bool(w_dropna.value),
                    include_inactive=bool(w_include_inactive.value),
                )

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

            if w_show_metrics.value:
                a = _parse_trim_cutoff(w_trim_a.value)
                rows: List[Dict[str, str]] = []

                for name, vals in series:
                    metrics = _compute_trimmed_metrics(vals, a)
                    row = {
                        "Group": str(name),
                        "n_trim / n_total": f"{metrics['n_trim']} / {metrics['n_total']}",
                    }

                    if metrics["insufficient"]:
                        row.update(
                            {
                                "Q25": "insufficient data",
                                "Q50": "insufficient data",
                                "Q75": "insufficient data",
                                "IQR": "insufficient data",
                                "Q90": "insufficient data",
                                "Q95": "insufficient data",
                                "skew_Q": "insufficient data",
                            }
                        )
                    else:
                        row.update(
                            {
                                "Q25": _fmt_metric(metrics["q25"]),
                                "Q50": _fmt_metric(metrics["q50"]),
                                "Q75": _fmt_metric(metrics["q75"]),
                                "IQR": _fmt_metric(metrics["iqr"]),
                                "Q90": _fmt_metric(metrics["q90"]),
                                "Q95": _fmt_metric(metrics["q95"]),
                                "skew_Q": _fmt_metric(metrics["skew_q"]),
                            }
                        )
                    rows.append(row)

                trim_label = "none" if a is None else _fmt_metric(a)
                print(f"Trimmed quantile metrics (a={trim_label})")
                display(pd.DataFrame(rows))

    for w in (
        w_sessions_mode, w_sessions,
        w_signals_mode, w_signals,
        w_bins, w_cdf, w_norm, w_dropna, w_include_inactive,
        w_show_metrics, w_trim_a,
    ):
        w.observe(_render, names="value")
    w_show_metrics.observe(_toggle_trim_input, names="value")

    controls = W.VBox([
        W.HBox(
            [w_bins, w_cdf, w_norm, w_dropna, w_include_inactive, w_show_metrics, w_trim_a],
            layout=W.Layout(
                justify_content="flex-start",
                align_items="center",
                gap="6px",
                flex_flow="row wrap",  
            ),
        ),
        w_trim_help,
        W.HBox([
            W.VBox([sessions_label, w_sessions_mode, w_sessions]),
            W.VBox([signals_label, w_signals_mode, w_signals]),
        ]),
    ])

    display(W.VBox([controls, out]))
    _render()

    return {
        "out": out,
        "session_ids": session_ids,
        "signal_cols": signal_cols,
    }

def make_signal_histogram_rebuilder(
    *,
    sel: Dict[str, Any],
    out: Optional[W.Output] = None,
    session_key_col: str = "session_key",
    **kwargs,
) -> Dict[str, Any]:
    """
    Rebuild helper for the signal histogram widget (recreates the widget on selector change).
    """


    if out is None:
        out = W.Output()

    state: Dict[str, Any] = {"handles": None}

    def rebuild() -> None:
        store = sel["store"]
        key_to_ref = sel["get_key_to_ref"]()
        session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)

        # The signal histogram only needs selected session identities.
        # Avoid loading all events parquet files here.
        if session_key_col == "session_key":
            session_values = [str(k) for k in key_to_ref.keys()]
        elif session_key_col == "session_id":
            session_values = [str(v[1]) for v in key_to_ref.values()]
        else:
            session_values = [str(k) for k in key_to_ref.keys()]
        events_df_sel = pd.DataFrame({session_key_col: session_values})

        with out:
            clear_output(wait=True)
            state["handles"] = make_signal_histogram_widget_for_loader(
                events_df_sel,
                session_loader=session_loader,
                session_key_col=session_key_col,
                **kwargs,
            )

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}

