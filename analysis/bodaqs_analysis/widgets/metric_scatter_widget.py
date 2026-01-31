# -*- coding: utf-8 -*-
"""
Metric scatter browser widget.

NEW (consumer pattern) public API:
    make_metric_scatter_widget_for_loader(
        *,
        events_index_df,
        session_loader,
        key_to_ref=None,
        ...
    )

- Uses session_key identity (same selector output pattern as event_browser + histogram).
- Loads per-session events_df + metrics_df lazily via session_loader(session_key).
- Builds a joined viz_df with columns:
    session_key, session_id, event_id, <event_type_col>, <signal_col>, m_*
  plus an inferred "_sensor" column.

LEGACY API retained for compatibility:
    make_metric_scatter_widget(events_df, metrics_df, ...)
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import ipywidgets as W
from IPython.display import display, clear_output

from bodaqs_analysis.widgets.loaders import make_session_loader, load_all_metrics_for_selected, load_all_events_for_selected

logger = logging.getLogger(__name__)


# ----------------------------
# small utilities (shared-ish)
# ----------------------------

def _require_cols(df: pd.DataFrame, cols: Sequence[str], *, name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required column(s): {missing}")


def _metric_cols(metrics_df: pd.DataFrame) -> List[str]:
    return [c for c in metrics_df.columns if isinstance(c, str) and c.startswith("m_")]


def _infer_sensor_from_signal_col(col: Optional[str]) -> Optional[str]:
    """
    Best-effort sensor extraction from canonical column naming.

    Common patterns:
      - "{sensor}_dom_{...}"
      - "{sensor}_{...}" (fallback)

    Examples:
      "front_shock_dom_suspension [mm]" -> "front_shock"
      "rear_shock_dom_suspension [mm]"  -> "rear_shock"
    """
    if not isinstance(col, str):
        return None
    s = col.strip()
    if not s:
        return None

    # Strip trailing unit suffix like " [mm]" for parsing.
    s2 = re.sub(r"\s*\[[^\]]+\]\s*$", "", s)

    m = re.match(r"^(.+?)_dom_", s2)
    if m:
        return m.group(1)

    # Fallback: take up to first underscore, but only if that seems meaningful.
    if "_" in s2:
        return s2.split("_", 1)[0]

    return s2


def _add_sensor_col(viz_df: pd.DataFrame, *, signal_col: str) -> pd.DataFrame:
    out = viz_df.copy()
    out["_sensor"] = out[signal_col].map(_infer_sensor_from_signal_col)
    return out


# ----------------------------
# extracting tables from session
# ----------------------------

def _default_events_getter(session: dict) -> pd.DataFrame:
    """
    Try a few common places for events_df inside the session artifact.
    Adjust if your session contract differs.
    """
    if not isinstance(session, dict):
        raise ValueError("session_loader returned a non-dict session")

    # Most likely patterns (adapt as needed)
    if "events_df" in session and isinstance(session["events_df"], pd.DataFrame):
        return session["events_df"]
    if "events" in session and isinstance(session["events"], pd.DataFrame):
        return session["events"]
    if "tables" in session and isinstance(session["tables"], dict):
        t = session["tables"]
        if "events_df" in t and isinstance(t["events_df"], pd.DataFrame):
            return t["events_df"]
        if "events" in t and isinstance(t["events"], pd.DataFrame):
            return t["events"]

    raise ValueError(
        "Could not locate events_df in session. "
        "Provide events_getter=... or ensure session contains events_df."
    )


def _default_metrics_getter(session: dict) -> pd.DataFrame:
    """
    Try a few common places for metrics_df inside the session artifact.
    Adjust if your session contract differs.
    """
    if not isinstance(session, dict):
        raise ValueError("session_loader returned a non-dict session")

    if "metrics_df" in session and isinstance(session["metrics_df"], pd.DataFrame):
        return session["metrics_df"]
    if "metrics" in session and isinstance(session["metrics"], pd.DataFrame):
        return session["metrics"]
    if "tables" in session and isinstance(session["tables"], dict):
        t = session["tables"]
        if "metrics_df" in t and isinstance(t["metrics_df"], pd.DataFrame):
            return t["metrics_df"]
        if "metrics" in t and isinstance(t["metrics"], pd.DataFrame):
            return t["metrics"]

    raise ValueError(
        "Could not locate metrics_df in session. "
        "Provide metrics_getter=... or ensure session contains metrics_df."
    )


# ----------------------------
# NEW consumer-pattern widget
# ----------------------------

def make_metric_scatter_widget_for_loader(
    *,
    store,
    key_to_ref: Dict[str, Tuple[str, str]],
    events_index_df: pd.DataFrame,
    session_loader: Callable[[str], dict],  # kept for symmetry / future use
    session_key_col: str = "session_key",
    event_id_col: str = "event_id",
    schema_id_col: str = "schema_id",
    event_type_col: str = "schema_id",   # safest default with your on-disk partitioning
    signal_col: str = "signal_col",
    default_alpha: float = 0.6,
    default_size: int = 18,
) -> dict:

    """
    Consumer-pattern metric scatter widget.

    events_index_df:
        Selector-provided index containing at least session_key/run_id/session_id.
        Only session_key is strictly required by this widget; session_id is used for display/debug.

    session_loader(session_key) -> session dict:
        Must load session artifacts (events + metrics available inside, see getters above).

    Returns:
        {"viz_df": <joined df>, "out": <ipywidgets.Output>, "refresh": <callable>}
    """
    if events_index_df is None or len(events_index_df) == 0:
        raise ValueError("events_index_df is empty")

    _require_cols(events_index_df, (session_key_col,), name="events_index_df")

    # Session universe from selector scope
    all_session_keys = (
        events_index_df[session_key_col].dropna().astype(str).unique().tolist()
    )
    all_session_keys = sorted(all_session_keys)

    if not all_session_keys:
        raise ValueError("No session_key values found in events_index_df")

    # Load tables across *selected sessions* (selector scope)
    events_df_sel = load_all_events_for_selected(store, key_to_ref=key_to_ref)
    metrics_df_sel = load_all_metrics_for_selected(store, key_to_ref=key_to_ref)

    if events_df_sel is None or events_df_sel.empty:
        raise ValueError("No events found for selected sessions.")
    if metrics_df_sel is None or metrics_df_sel.empty:
        raise ValueError("No metrics found for selected sessions.")

    # Required columns
    _require_cols(events_df_sel, (session_key_col, event_id_col, schema_id_col, signal_col), name="events_df_sel")
    _require_cols(metrics_df_sel, (session_key_col, event_id_col, schema_id_col), name="metrics_df_sel")

    metric_cols = _metric_cols(metrics_df_sel)
    if not metric_cols:
        raise ValueError("No metric columns found in metrics_df_sel (expected 'm_' prefix)")

    # Join identity: safest is (session_key, schema_id, event_id)
    viz_df = events_df_sel[
        [session_key_col, "run_id", "session_id", schema_id_col, event_id_col, signal_col] +
        ([event_type_col] if event_type_col not in (schema_id_col,) and event_type_col in events_df_sel.columns else [])
    ].merge(
        metrics_df_sel[[session_key_col, schema_id_col, event_id_col] + metric_cols],
        on=[session_key_col, schema_id_col, event_id_col],
        how="inner",
        validate="one_to_one",
    )

    # Ensure event_type_col exists (default schema_id)
    if event_type_col not in viz_df.columns:
        viz_df[event_type_col] = viz_df[schema_id_col].astype(str)

    viz_df = _add_sensor_col(viz_df, signal_col=signal_col)


    if viz_df is None or len(viz_df) == 0:
        raise ValueError("No rows after building viz_df (events/metrics join produced nothing)")

    # ----------------------------
    # options from viz_df
    # ----------------------------
    sessions = sorted(viz_df[session_key_col].dropna().astype(str).unique().tolist())
    event_types = sorted(viz_df[event_type_col].dropna().astype(str).unique().tolist())
    signals = sorted(viz_df[signal_col].dropna().astype(str).unique().tolist())
    sensors = sorted([x for x in viz_df["_sensor"].dropna().astype(str).unique().tolist() if x])
    metrics = sorted(_metric_cols(viz_df))

    if not sessions:
        raise ValueError("No non-null session_key values after join")
    if not event_types:
        raise ValueError(f"No non-null values found in {event_type_col!r} after join")
    if not signals:
        raise ValueError(f"No non-null values found in {signal_col!r} after join")
    if len(metrics) == 0:
        raise ValueError("No metric columns found after join (expected 'm_' prefix)")

    # ----------------------------
    # UI
    # ----------------------------
    w_event = W.Dropdown(options=event_types, value=event_types[0], description="Event:")

    w_sessions_mode = W.RadioButtons(
        options=[("Aggregate sessions", False), ("Compare sessions", True)],
        value=False,
        description="Sessions:",
    )
    w_sessions = W.SelectMultiple(
        options=sessions,
        value=tuple(sessions),  # default-safe selection
        description="Pick:",
        rows=min(8, max(3, len(sessions))),
        layout=W.Layout(width="450px"),

    )

    w_sensor = W.Dropdown(
        options=(["(any)"] + sensors) if sensors else ["(any)"],
        value="(any)",
        description="Sensor:",
        layout=W.Layout(width="360px"),
    )

    w_signals_mode = W.RadioButtons(
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

    w_x = W.Dropdown(options=metrics, value=metrics[0], description="X:")
    w_y = W.Dropdown(options=metrics, value=metrics[1] if len(metrics) > 1 else metrics[0], description="Y:")

    w_alpha = W.BoundedFloatText(value=float(default_alpha), min=0.05, max=1.0, step=0.05, description="Alpha:")
    w_size = W.BoundedIntText(value=int(default_size), min=1, max=200, step=1, description="Size:")

    w_grid = W.Checkbox(value=True, description="Grid")
    w_equal = W.Checkbox(value=False, description="Equal axes")
    w_diag = W.Checkbox(value=False, description="y=x line")
    w_stats = W.Checkbox(value=True, description="Stats")
    w_regress = W.Checkbox(value=False, description="Regression")

    out = W.Output()

    def _filtered_base() -> pd.DataFrame:
        sel_sessions = list(map(str, w_sessions.value))
        sel_signals = list(map(str, w_signals.value))
        if not sel_sessions or not sel_signals:
            return viz_df.iloc[0:0]

        sub = viz_df[
            (viz_df[event_type_col].astype(str) == str(w_event.value))
            & (viz_df[session_key_col].astype(str).isin(sel_sessions))
            & (viz_df[signal_col].astype(str).isin(sel_signals))
        ].copy()

        if w_sensor.value and w_sensor.value != "(any)":
            sub = sub[sub["_sensor"].astype(str) == str(w_sensor.value)].copy()

        return sub

    def _rebuild_signals(*_):
        # Restrict signal options to those valid for the current event type (+ optional sensor)
        sub = viz_df.copy()

        # NEW: filter by current event type
        sub = sub[sub[event_type_col].astype(str) == str(w_event.value)]

        # existing: filter by sensor (if set)
        if w_sensor.value and w_sensor.value != "(any)":
            sub = sub[sub["_sensor"].astype(str) == str(w_sensor.value)]

        sigs = sorted(sub[signal_col].dropna().astype(str).unique().tolist())
        if not sigs:
            sigs = signals[:]  # fallback: keep full list

        prev = set(map(str, w_signals.value))
        w_signals.options = sigs
        keep = [s for s in sigs if s in prev]
        if keep:
            w_signals.value = tuple(keep)
        else:
            w_signals.value = tuple(sigs[:1]) if sigs else ()

    def _rebuild_sessions(*_):
        # sessions that actually have rows for the current event type (+ optional sensor)
        sub = viz_df[viz_df[event_type_col].astype(str) == str(w_event.value)]
        if w_sensor.value and w_sensor.value != "(any)":
            sub = sub[sub["_sensor"].astype(str) == str(w_sensor.value)]

        sess = sorted(sub[session_key_col].dropna().astype(str).unique().tolist())
        if not sess:
            sess = sessions[:]  # fallback

        prev = set(map(str, w_sessions.value))
        w_sessions.options = sess
        keep = [s for s in sess if s in prev]
        w_sessions.value = tuple(keep) if keep else tuple(sess)  # default to “all valid”

    def _coerce_xy(sub: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        x = pd.to_numeric(sub[w_x.value], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(sub[w_y.value], errors="coerce").to_numpy(dtype=float)
        m = np.isfinite(x) & np.isfinite(y)
        return x[m], y[m]

    def _series_summ(name: str, x: np.ndarray, y: np.ndarray) -> str:
        n = int(len(x))
        if n == 0:
            return f"- {name}: n=0"
        r = np.corrcoef(x, y)[0, 1] if n >= 2 else np.nan
        return (
            f"- {name}: n={n}  "
            f"x[min/mean/max]={np.nanmin(x):.6g}/{np.nanmean(x):.6g}/{np.nanmax(x):.6g}  "
            f"y[min/mean/max]={np.nanmin(y):.6g}/{np.nanmean(y):.6g}/{np.nanmax(y):.6g}  "
            f"r={r:.4g}"
        )

    def _fit_line(x: np.ndarray, y: np.ndarray) -> Optional[Tuple[float, float, float]]:
        n = int(len(x))
        if n < 2:
            return None

        m, b = np.polyfit(x, y, 1)
        y_hat = m * x + b
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))

        if ss_tot <= 0.0:
            r2 = float("nan")
        else:
            r2 = 1.0 - (ss_res / ss_tot)

        return float(m), float(b), float(r2)

    def _fmt_line(m: float, b: float) -> str:
        sign = "+" if b >= 0 else "-"
        return f"y = {m:.6g} x {sign} {abs(b):.6g}"

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

            base = _filtered_base()
            if len(base) == 0:
                print("No rows after filtering.")
                return

            compare_sessions = bool(w_sessions_mode.value)
            compare_signals = bool(w_signals_mode.value)

            # Build series list: (label, df_subset)
            series: List[Tuple[str, pd.DataFrame]] = []

            if compare_sessions and compare_signals:
                for sk in sel_sessions:
                    for sig in sel_signals:
                        sub = base[
                            (base[session_key_col].astype(str) == str(sk))
                            & (base[signal_col].astype(str) == str(sig))
                        ]
                        series.append((f"{sk} | {sig}", sub))

            elif compare_sessions and (not compare_signals):
                for sk in sel_sessions:
                    sub = base[base[session_key_col].astype(str) == str(sk)]
                    series.append((str(sk), sub))

            elif (not compare_sessions) and compare_signals:
                for sig in sel_signals:
                    sub = base[base[signal_col].astype(str) == str(sig)]
                    series.append((str(sig), sub))

            else:
                series.append(("aggregate", base))

            fig, ax = plt.subplots(figsize=(8.8, 5.2))

            any_points = False
            fit_results: List[Tuple[str, Optional[Tuple[float, float, float]], int]] = []

            for label, sub in series:
                x, y = _coerce_xy(sub)
                if len(x) == 0:
                    fit_results.append((label, None, 0))
                    continue

                any_points = True

                sc = ax.scatter(
                    x, y,
                    s=int(w_size.value),
                    alpha=float(w_alpha.value),
                    label=(label if (compare_sessions or compare_signals) else None),
                )

                fit = None
                if w_regress.value and len(x) >= 2:
                    fit = _fit_line(x, y)
                    if fit is not None:
                        m, b, r2 = fit
                        xlo, xhi = float(np.min(x)), float(np.max(x))
                        xs = np.array([xlo, xhi], dtype=float)
                        ys = m * xs + b

                        color = sc.get_facecolors()
                        c = color[0] if (color is not None and len(color) > 0) else None
                        ax.plot(xs, ys, linewidth=2.0, alpha=0.9, color=c)

                fit_results.append((label, fit, int(len(x))))

            mode_bits = [
                ("sessions=compare" if compare_sessions else "sessions=aggregate"),
                ("signals=compare" if compare_signals else "signals=aggregate"),
            ]
            sensor_bit = f"sensor={w_sensor.value}" if (w_sensor.value and w_sensor.value != "(any)") else "sensor=any"

            ax.set_title(
                f"{w_y.value} vs {w_x.value}\n"
                f"{event_type_col}={w_event.value} | {sensor_bit} | {', '.join(mode_bits)}"
            )
            ax.set_xlabel(w_x.value)
            ax.set_ylabel(w_y.value)

            if w_grid.value:
                ax.grid(True, which="major", axis="both", alpha=0.3)

            if w_equal.value:
                ax.set_aspect("equal", adjustable="datalim")

            if w_diag.value:
                xmin, xmax = ax.get_xlim()
                ymin, ymax = ax.get_ylim()
                lo = min(xmin, ymin)
                hi = max(xmax, ymax)
                ax.plot([lo, hi], [lo, hi], linestyle="--", linewidth=1.0)
                ax.set_xlim(xmin, xmax)
                ax.set_ylim(ymin, ymax)

            if (compare_sessions or compare_signals):
                ax.legend(title="series", fontsize=9)

            if not any_points:
                ax.text(
                    0.5, 0.5,
                    "No numeric x/y pairs after filtering",
                    ha="center", va="center",
                    transform=ax.transAxes
                )
                ax.set_axis_off()

            plt.show()

            if w_stats.value:
                print("Summary stats (finite x/y pairs only):")
                for label, sub in series:
                    x, y = _coerce_xy(sub)
                    print(_series_summ(label, x, y))

            if w_regress.value:
                print("\nLinear regression (per series):")
                for label, fit, n in fit_results:
                    if fit is None:
                        if n < 2:
                            print(f"- {label}: n={n} (need >=2 points)")
                        else:
                            print(f"- {label}: fit unavailable")
                        continue
                    m, b, r2 = fit
                    eq = _fmt_line(m, b)
                    print(f"- {label}: n={n}  {eq}  R²={r2:.6g}")

    def refresh() -> None:
        nonlocal viz_df
        # reload from disk for current selection snapshot
        events_df_sel = load_all_events_for_selected(store, key_to_ref=key_to_ref)
        metrics_df_sel = load_all_metrics_for_selected(store, key_to_ref=key_to_ref)
       # _rebuild_sessions()
        _rebuild_signals()
        _render()

    # Wire up
    for w in (
        w_event,
        w_sessions_mode,
        w_sessions,
        w_sensor,
        w_signals_mode,
        w_signals,
        w_x,
        w_y,
        w_alpha,
        w_size,
        w_grid,
        w_equal,
        w_diag,
        w_regress,
        w_stats,
    ):
        w.observe(_render, names="value")

    w_sensor.observe(_rebuild_signals, names="value")
    w_event.observe(_rebuild_signals, names="value")
 #   w_event.observe(_rebuild_sessions, names="value")
 #   w_sensor.observe(_rebuild_sessions, names="value")


    controls = W.VBox(
        [
            W.HBox([w_event, w_sensor]),
            W.HBox([w_x, w_y, w_alpha, w_size, w_grid, w_equal, w_diag, w_regress, w_stats]),
            W.HBox(
                [
                    W.VBox([w_sessions_mode, w_sessions]),
                    W.VBox([w_signals_mode, w_signals]),
                ]
            ),
        ]
    )

    display(W.VBox([controls, out]))
 #   _rebuild_sessions
    _rebuild_signals()
    _render()

    return {"viz_df": viz_df, "out": out, "refresh": refresh}


# ----------------------------
# LEGACY API (unchanged)
# ----------------------------

def make_metric_scatter_widget(
    events_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    *,
    event_type_col: str = "event_name",
    signal_col: str = "signal_col",
    default_alpha: float = 0.6,
    default_size: int = 18,
) -> dict:
    """
    Legacy (pre-consumer-pattern) widget.

    Retained so existing notebooks keep working.
    """
    if events_df is None or len(events_df) == 0:
        raise ValueError("events_df is empty")
    if metrics_df is None or len(metrics_df) == 0:
        raise ValueError("metrics_df is empty")

    _require_cols(events_df, ("session_id", "event_id", event_type_col, signal_col), name="events_df")
    _require_cols(metrics_df, ("session_id", "event_id"), name="metrics_df")

    metric_cols = _metric_cols(metrics_df)
    if not metric_cols:
        raise ValueError("No metric columns found in metrics_df (expected columns prefixed with 'm_')")

    viz_df = events_df[["session_id", "event_id", event_type_col, signal_col]].merge(
        metrics_df[["session_id", "event_id"] + metric_cols],
        on=["session_id", "event_id"],
        how="inner",
        validate="one_to_one",
    )
    viz_df = _add_sensor_col(viz_df, signal_col=signal_col)

    # Reuse the new widget machinery by fabricating a minimal loader-style index.
    # (This keeps behaviour identical without duplicating the full UI code.)
    idx = pd.DataFrame({"session_key": viz_df["session_id"].astype(str)})
    idx = idx.drop_duplicates(ignore_index=True)

    def _fake_loader(session_key: str) -> dict:
        sid = str(session_key)
        ev = events_df[events_df["session_id"].astype(str) == sid].copy()
        met = metrics_df[metrics_df["session_id"].astype(str) == sid].copy()
        # Expose in the simplest expected form for default getters:
        return {"events_df": ev, "metrics_df": met}

    return make_metric_scatter_widget_for_loader(
        events_index_df=idx,
        session_loader=_fake_loader,
        session_key_col="session_key",
        event_id_col="event_id",
        session_id_col="session_id",
        event_type_col=event_type_col,
        signal_col=signal_col,
        default_alpha=default_alpha,
        default_size=default_size,
    )

def make_metric_scatter_rebuilder(
    *,
    sel: Dict[str, Any],
    out: Optional[W.Output] = None,
    event_type_col: str = "schema_id",
    signal_col: str = "signal_col",
    **kwargs,
) -> Dict[str, Any]:
    """
    Create a self-contained rebuilder for the metric scatter widget.

    Usage:
        r = make_metric_scatter_rebuilder(sel=sel)
        display(r["out"])
        r["rebuild"]()
    """

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
            state["handles"] = make_metric_scatter_widget_for_loader(
                store=store,
                key_to_ref=key_to_ref,
                events_index_df=events_index_df,
                session_loader=session_loader,
                event_type_col=event_type_col,
                signal_col=signal_col,
                **kwargs,
            )

    # build once
    rebuild()

    return {"out": out, "rebuild": rebuild, "state": state}
