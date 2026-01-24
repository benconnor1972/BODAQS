# -*- coding: utf-8 -*-
"""
Metric scatter browser widget.

Public API:
    make_metric_scatter_widget(events_df, metrics_df, ...)

Notes:
- Expects metrics columns prefixed with "m_".
- Joins events_df and metrics_df on (session_id, event_id) with one_to_one validation.
- Filters by event type, session(s), and sensor (inferred from signal_col).
- Supports aggregating sessions or comparing them (multi-series scatter).
- Optional compare-signals mode (same idea as histogram widget).
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

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

    # Strip any trailing unit suffix like " [mm]" for parsing.
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
    Build and display an interactive scatter plot widget for metrics.

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

    # Join (same identity contract as histogram widget)
    viz_df = events_df[["session_id", "event_id", event_type_col, signal_col]].merge(
        metrics_df[["session_id", "event_id"] + metric_cols],
        on=["session_id", "event_id"],
        how="inner",
        validate="one_to_one",
    )
    viz_df = _add_sensor_col(viz_df, signal_col=signal_col)

    logger.info("metric_scatter: joined viz_df shape: %s", viz_df.shape)

    # Options
    sessions = sorted([x for x in viz_df["session_id"].dropna().astype(str).unique().tolist()])
    event_types = sorted([x for x in viz_df[event_type_col].dropna().astype(str).unique().tolist()])
    signals = sorted([x for x in viz_df[signal_col].dropna().astype(str).unique().tolist()])
    sensors = sorted([x for x in viz_df["_sensor"].dropna().astype(str).unique().tolist() if x])
    metrics = sorted(metric_cols)

    if not sessions:
        raise ValueError("No non-null session_id values after join")
    if not event_types:
        raise ValueError(f"No non-null values found in {event_type_col!r} after join")
    if not signals:
        raise ValueError(f"No non-null values found in {signal_col!r} after join")

    # --- widgets ---
    w_event = W.Dropdown(options=event_types, value=event_types[0], description="Event:")

    w_sessions_mode = W.RadioButtons(
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

    # Sensor + signal filtering
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
            & (viz_df["session_id"].astype(str).isin(sel_sessions))
            & (viz_df[signal_col].astype(str).isin(sel_signals))
        ].copy()

        if w_sensor.value and w_sensor.value != "(any)":
            sub = sub[sub["_sensor"].astype(str) == str(w_sensor.value)].copy()

        return sub

    def _rebuild_signals(*_):
        # When sensor changes, restrict signal options to those seen with that sensor (best-effort)
        sub = viz_df.copy()
        if w_sensor.value and w_sensor.value != "(any)":
            sub = sub[sub["_sensor"].astype(str) == str(w_sensor.value)]

        sigs = sorted(sub[signal_col].dropna().astype(str).unique().tolist())
        if not sigs:
            sigs = signals[:]  # fallback: keep full list

        # Preserve previous selections if possible
        prev = set(map(str, w_signals.value))
        w_signals.options = sigs
        keep = [s for s in sigs if s in prev]
        if keep:
            w_signals.value = tuple(keep)
        else:
            w_signals.value = tuple(sigs[:1]) if sigs else ()

    def _coerce_xy(sub: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        x = pd.to_numeric(sub[w_x.value], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(sub[w_y.value], errors="coerce").to_numpy(dtype=float)
        m = np.isfinite(x) & np.isfinite(y)
        return x[m], y[m]

    def _series_summ(name: str, x: np.ndarray, y: np.ndarray) -> str:
        n = int(len(x))
        if n == 0:
            return f"- {name}: n=0"
        # Pearson r (guard)
        r = np.corrcoef(x, y)[0, 1] if n >= 2 else np.nan
        return (
            f"- {name}: n={n}  "
            f"x[min/mean/max]={np.nanmin(x):.6g}/{np.nanmean(x):.6g}/{np.nanmax(x):.6g}  "
            f"y[min/mean/max]={np.nanmin(y):.6g}/{np.nanmean(y):.6g}/{np.nanmax(y):.6g}  "
            f"r={r:.4g}"
        )

    def _fit_line(x: np.ndarray, y: np.ndarray) -> Optional[Tuple[float, float, float]]:
        """
        Fit y = m x + b and return (m, b, r2).
        Uses finite x/y pairs only (callers already do this).
        """
        n = int(len(x))
        if n < 2:
            return None

        m, b = np.polyfit(x, y, 1)

        y_hat = m * x + b
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))

        # R^2 is undefined if variance is ~0
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
                for sid in sel_sessions:
                    for sig in sel_signals:
                        sub = base[(base["session_id"].astype(str) == str(sid)) & (base[signal_col].astype(str) == str(sig))]
                        series.append((f"{sid} | {sig}", sub))

            elif compare_sessions and (not compare_signals):
                for sid in sel_sessions:
                    sub = base[base["session_id"].astype(str) == str(sid)]
                    series.append((str(sid), sub))

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

                # Scatter (capture PathCollection so we can reuse its color for the regression line)
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

                        # Plot regression line over current x span for this series
                        xlo, xhi = float(np.min(x)), float(np.max(x))
                        xs = np.array([xlo, xhi], dtype=float)
                        ys = m * xs + b

                        # Use the scatter series color
                        color = sc.get_facecolors()
                        # facecolors can be empty in some mpl backends; fallback to None
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
                # Draw y=x based on current view limits
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
                ax.text(0.5, 0.5, "No numeric x/y pairs after filtering", ha="center", va="center", transform=ax.transAxes)
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
    _rebuild_signals()
    _render()

    return {"viz_df": viz_df, "out": out}
