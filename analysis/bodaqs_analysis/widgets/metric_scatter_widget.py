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
from pathlib import Path

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

# ----------------------------
# NEW consumer-pattern widget
# ----------------------------

def make_metric_scatter_widget_for_loader(
    *,
    store,
    schema: dict,
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

    IMPORTANT:
    Sensor resolution is schema-mediated:
        event row -> (schema_id, signal_col) -> schema triggers -> canonical signal_col -> registry -> sensor

    Robustness:
    - If events_df_sel[signal_col] is a ROLE (e.g. "disp"), it is resolved via schema triggers.
    - If events_df_sel[signal_col] is already a canonical df column, it is resolved directly via registry.
    - No parsing/normalization of column names.
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
    _require_cols(
        events_df_sel,
        (session_key_col, event_id_col, schema_id_col, signal_col),
        name="events_df_sel",
    )
    _require_cols(
        metrics_df_sel,
        (session_key_col, event_id_col, schema_id_col),
        name="metrics_df_sel",
    )

    metric_cols = _metric_cols(metrics_df_sel)
    if not metric_cols:
        raise ValueError("No metric columns found in metrics_df_sel (expected 'm_' prefix)")

    # Join identity: safest is (session_key, schema_id, event_id)
    viz_df = events_df_sel[
        [session_key_col, "run_id", "session_id", schema_id_col, event_id_col, signal_col]
        + (
            [event_type_col]
            if event_type_col not in (schema_id_col,) and event_type_col in events_df_sel.columns
            else []
        )
    ].merge(
        metrics_df_sel[[session_key_col, schema_id_col, event_id_col] + metric_cols],
        on=[session_key_col, schema_id_col, event_id_col],
        how="inner",
        validate="one_to_one",
    )

    # Ensure event_type_col exists (default schema_id)
    if event_type_col not in viz_df.columns:
        viz_df[event_type_col] = viz_df[schema_id_col].astype(str)

    if viz_df is None or len(viz_df) == 0:
        raise ValueError("No rows after building viz_df (events/metrics join produced nothing)")

    # ----------------------------
    # Registry + schema mediated sensor resolution
    # ----------------------------

    # Get a registry dict from any loaded session.
    # (Assumes registry is stable across sessions; that's the intent of your registry snapshot contract.)
    # Prefer meta['signals'] (your pipeline uses this), otherwise fail fast.
    _sk0 = next(iter(key_to_ref.keys()))
    _sess0 = session_loader(_sk0)
    _meta0 = (_sess0 or {}).get("meta") or {}
    registry = _meta0.get("signals") or {}
    if not isinstance(registry, dict) or not registry:
        raise ValueError(
            "Signal registry not found or empty in session_loader(session_key)['meta']['signals']"
        )

    def _build_schema_sensor_maps(schema_obj: dict, registry_obj: dict) -> Dict[str, Dict[str, str]]:
        """
        Build per-schema_id lookup: token -> sensor
        Where token can be:
          - trigger ROLE key (e.g. 'disp')
          - trigger canonical signal_col (e.g. 'rear_shock_dom_suspension [mm]')
        """
        out: Dict[str, Dict[str, str]] = {}

        if not isinstance(schema_obj, dict):
            return out

        for sid, sch in schema_obj.items():
            if not isinstance(sid, str):
                continue
            if not isinstance(sch, dict):
                continue

            triggers = sch.get("triggers") or {}
            if not isinstance(triggers, dict):
                continue

            m: Dict[str, str] = {}
            for role, trig in triggers.items():
                if not isinstance(trig, dict):
                    continue

                sigcol = trig.get("signal_col")
                if not isinstance(sigcol, str) or not sigcol.strip():
                    continue
                sigcol = sigcol.strip()

                info = registry_obj.get(sigcol)
                if not isinstance(info, dict):
                    continue
                sensor = info.get("sensor")
                if not isinstance(sensor, str) or not sensor.strip():
                    continue
                sensor = sensor.strip()

                # allow lookup by role as well as by canonical signal column
                if isinstance(role, str) and role.strip():
                    m[role.strip()] = sensor
                m[sigcol] = sensor

            if m:
                out[sid] = m

        return out

    schema_sensor_map_by_schema = _build_schema_sensor_maps(schema, registry)

    def _resolve_sensor(schema_id_val: object, token_val: object) -> str:
        """
        Resolve sensor for a row using schema + registry only.
        token_val is whatever is stored in viz_df[signal_col] (role or resolved column).
        """
        sid = str(schema_id_val) if schema_id_val is not None else ""
        tok = str(token_val) if token_val is not None else ""
        sid = sid.strip()
        tok = tok.strip()
        if not sid or not tok:
            return ""

        # 1) Schema-mediated lookup (role or canonical col)
        m = schema_sensor_map_by_schema.get(sid)
        if isinstance(m, dict):
            s = m.get(tok)
            if isinstance(s, str) and s.strip():
                return s.strip()

        # 2) If token is already canonical df column, allow direct registry lookup
        info = registry.get(tok)
        if isinstance(info, dict):
            s2 = info.get("sensor")
            if isinstance(s2, str) and s2.strip():
                return s2.strip()

        return ""

    viz_df["_sensor"] = [
        _resolve_sensor(sid, tok)
        for sid, tok in zip(viz_df[schema_id_col].astype(str), viz_df[signal_col].astype(str))
    ]

    if viz_df["_sensor"].astype(str).str.len().sum() == 0:
        # Helpful debug: show a small sample of schema_id + token values
        ex = viz_df[[schema_id_col, signal_col]].drop_duplicates().head(8)
        logger.warning(
            "Could not resolve any sensors via schema+registry. "
            "This likely means your schema triggers don't map to registry signal_col keys. "
            "Sample (schema_id, %s):\n%s",
            signal_col,
            ex.to_string(index=False),
        )

    # ----------------------------
    # options from viz_df
    # ----------------------------
    sessions = sorted(viz_df[session_key_col].dropna().astype(str).unique().tolist())
    event_types = sorted(viz_df[event_type_col].dropna().astype(str).unique().tolist())

    sensors = sorted([x for x in viz_df["_sensor"].dropna().astype(str).unique().tolist() if x])
    if not sensors:
        raise ValueError(
            "No sensors could be resolved via schema+registry (viz_df['_sensor'] is empty). "
            "Check that schema['<schema_id>']['triggers'][<role>]['signal_col'] matches registry keys."
        )

    metrics = sorted(_metric_cols(viz_df))

    if not sessions:
        raise ValueError("No non-null session_key values after join")
    if not event_types:
        raise ValueError(f"No non-null values found in {event_type_col!r} after join")
    if len(metrics) == 0:
        raise ValueError("No metric columns found after join (expected 'm_' prefix)")

    # ----------------------------
    # UI
    # ----------------------------
    dummy_label = W.Label(" ")
    event_label = W.Label("Event:")
    w_event = W.Dropdown(options=event_types, value=event_types[0], description="")

    w_sessions_mode = W.RadioButtons(
        options=[("Aggregate sessions", False), ("Compare sessions", True)],
        value=False,
        description="Sessions:",
    )
    w_sessions = W.SelectMultiple(
        options=sessions,
        value=tuple(sessions),  # default-safe selection
        description="",
        rows=min(8, max(3, len(sessions), len(sensors))),
        layout=W.Layout(width="450px"),
    )

    w_sensors_mode = W.RadioButtons(
        options=[("Aggregate sensors", False), ("Compare sensors", True)],
        value=True,
        description="Sensors:",
    )
    w_sensors = W.SelectMultiple(
        options=sensors,
        value=tuple(sensors[:1]),
        description="",
        rows=min(8, max(3, len(sessions), len(sensors))),
        layout=W.Layout(width="450px"),
    )

    metrics_label = W.Label("Metrics to chart:")
    w_x = W.Dropdown(options=metrics, value=metrics[0], description="X:")
    w_x.style = {"description_width": "initial"}

    w_y = W.Dropdown(options=metrics, value=metrics[1] if len(metrics) > 1 else metrics[0], description="Y:")
    w_y.style = {"description_width": "initial"}

    w_alpha = W.BoundedFloatText(
        value=float(default_alpha),
        min=0.05,
        max=1.0,
        step=0.05,
        description="Alpha:",
        layout=W.Layout(width="150px"),
    )
    w_size = W.BoundedIntText(
        value=int(default_size),
        min=1,
        max=200,
        step=1,
        description="Size:",
        layout=W.Layout(width="150px"),
    )

    w_grid = W.Checkbox(value=True, description="Grid")
    w_equal = W.Checkbox(value=False, description="Equal axes")
    w_diag = W.Checkbox(value=False, description="y=x line")
    w_stats = W.Checkbox(value=False, description="Stats")
    w_regress = W.Checkbox(value=True, description="Regression")

    out = W.Output()

    def _filtered_base() -> pd.DataFrame:
        sel_sessions = list(map(str, w_sessions.value))
        sel_sensors  = list(map(str, w_sensors.value))

        if not sel_sessions or not sel_sensors:
            return viz_df.iloc[0:0]

        sub = viz_df[
            (viz_df[event_type_col].astype(str) == str(w_event.value))
            & (viz_df[session_key_col].astype(str).isin(sel_sessions))
            & (viz_df["_sensor"].astype(str).isin(sel_sensors))
        ].copy()

        return sub

    def _rebuild_sensors(*_):
        # Restrict sensor options to those valid for the current event type
        sub = viz_df[viz_df[event_type_col].astype(str) == str(w_event.value)]
        sens = sorted([x for x in sub["_sensor"].dropna().astype(str).unique().tolist() if x])
        if not sens:
            sens = sensors[:]  # fallback

        prev = set(map(str, w_sensors.value))
        w_sensors.options = sens
        keep = [s for s in sens if s in prev]
        if keep:
            w_sensors.value = tuple(keep)
        else:
            w_sensors.value = tuple(sens[:1]) if sens else ()

    def _rebuild_metrics(*_):
        # Restrict metric options to those that actually exist (non-all-NaN) for the current event type
        sub = viz_df[viz_df[event_type_col].astype(str) == str(w_event.value)]
        if sub is None or len(sub) == 0:
            mcols = metrics[:]  # fallback
        else:
            mcols = []
            for c in metrics:
                v = pd.to_numeric(sub[c], errors="coerce").to_numpy(dtype=float)
                if np.isfinite(v).any():
                    mcols.append(c)

            if not mcols:
                mcols = metrics[:]  # fallback

        # Preserve prior selections if still valid
        prev_x = str(w_x.value) if w_x.value is not None else ""
        prev_y = str(w_y.value) if w_y.value is not None else ""

        w_x.options = mcols
        w_y.options = mcols

        if prev_x in mcols:
            w_x.value = prev_x
        else:
            w_x.value = mcols[0] if mcols else None

        if prev_y in mcols:
            w_y.value = prev_y
        else:
            # pick a different default if possible
            w_y.value = mcols[1] if (mcols and len(mcols) > 1 and mcols[1] != w_x.value) else (mcols[0] if mcols else None)

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
            sel_sensors = list(w_sensors.value)

            if not sel_sessions:
                print("Select at least one session.")
                return
            if not sel_sensors:
                print("Select at least one sensor.")
                return

            base = _filtered_base()
            if len(base) == 0:
                print("No rows after filtering.")
                return

            compare_sessions = bool(w_sessions_mode.value)
            compare_sensors = bool(w_sensors_mode.value)

            # Build series list: (label, df_subset)
            series: List[Tuple[str, pd.DataFrame]] = []

            if compare_sessions and compare_sensors:
                for sk in sel_sessions:
                    for s in sel_sensors:
                        sub = base[
                            (base[session_key_col].astype(str) == str(sk))
                            & (base["_sensor"].astype(str) == str(s))
                        ]
                        series.append((f"{sk} | {s}", sub))

            elif compare_sessions and (not compare_sensors):
                for sk in sel_sessions:
                    sub = base[base[session_key_col].astype(str) == str(sk)]
                    series.append((str(sk), sub))

            elif (not compare_sessions) and compare_sensors:
                for s in sel_sensors:
                    sub = base[base["_sensor"].astype(str) == str(s)]
                    series.append((str(s), sub))

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
                    label=(label if (compare_sessions or compare_sensors) else None),
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
                ("sensors=compare" if compare_sensors else "sensors=aggregate"),
            ]

            ax.set_title(
                f"{w_y.value} vs {w_x.value}\n"
                f"{event_type_col}={w_event.value} | {', '.join(mode_bits)}"
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

            if (compare_sessions or compare_sensors):
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

        events_df_sel2 = load_all_events_for_selected(store, key_to_ref=key_to_ref)
        metrics_df_sel2 = load_all_metrics_for_selected(store, key_to_ref=key_to_ref)

        if events_df_sel2 is None or events_df_sel2.empty:
            raise ValueError("No events found for selected sessions (refresh).")
        if metrics_df_sel2 is None or metrics_df_sel2.empty:
            raise ValueError("No metrics found for selected sessions (refresh).")

        metric_cols2 = _metric_cols(metrics_df_sel2)
        viz_df2 = events_df_sel2[
            [session_key_col, "run_id", "session_id", schema_id_col, event_id_col, signal_col]
            + (
                [event_type_col]
                if event_type_col not in (schema_id_col,) and event_type_col in events_df_sel2.columns
                else []
            )
        ].merge(
            metrics_df_sel2[[session_key_col, schema_id_col, event_id_col] + metric_cols2],
            on=[session_key_col, schema_id_col, event_id_col],
            how="inner",
            validate="one_to_one",
        )
        if event_type_col not in viz_df2.columns:
            viz_df2[event_type_col] = viz_df2[schema_id_col].astype(str)

        # Recompute sensors from schema+registry
        viz_df2["_sensor"] = [
            _resolve_sensor(sid, tok)
            for sid, tok in zip(viz_df2[schema_id_col].astype(str), viz_df2[signal_col].astype(str))
        ]

        viz_df = viz_df2
        _rebuild_sensors()
        _rebuild_metrics()
        _render()

    # Wire up
    for w in (
        w_event,
        w_sessions_mode,
        w_sessions,
        w_sensors_mode,
        w_sensors,
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

    def _on_event_change(*_):
        _rebuild_sensors()
        _rebuild_metrics()
        _render()

    w_event.observe(_on_event_change, names="value")
    
    controls = W.VBox(
        [
            W.HBox([W.VBox([event_label, w_event])]),
            W.HBox([W.VBox([metrics_label, w_x]), W.VBox([dummy_label, w_y])]),
            W.HBox(
                [
                    W.VBox([w_sessions_mode, w_sessions]),
                    W.VBox([w_sensors_mode, w_sensors]),
                ]
            ),
            W.HBox(
                [
                    W.VBox([w_alpha, w_size]),
                    W.VBox([W.HBox([w_regress, w_stats, w_grid]), W.HBox([w_equal, w_diag])]),
                ]
            ),
        ]
    )

    display(W.VBox([controls, out]))
    _rebuild_sensors()
    _rebuild_metrics()
    _render()

    return {"viz_df": viz_df, "out": out, "refresh": refresh}


def make_metric_scatter_rebuilder(
    *,
    sel: Dict[str, Any],
    schema: dict,
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
                schema=schema,
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
