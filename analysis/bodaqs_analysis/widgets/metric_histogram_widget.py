# -*- coding: utf-8 -*-
"""
Metric histogram / CDF browser widget.

Consumer-pattern implementation for the BODAQS JupyterLab artifacts pipeline.

Public APIs:
    - make_metric_histogram_widget(events_df, metrics_df, ...)            # legacy-friendly (UNCHANGED)
    - make_metric_histogram_widget_for_loader(store, schema, key_to_ref, ...)  # selector consumer pattern (UPDATED)
    - make_metric_histogram_rebuilder(sel, schema, ...)                   # rebuild-on-selector-change pattern (UPDATED)

Notes:
- Expects metric columns prefixed with "m_".
- Joins events and metrics on a stable identity key:
    (session_key, schema_id, event_id) by default.
- Consumer path resolves sensors via:
    event row -> (schema_id, token in signal_col) -> schema triggers -> canonical signal_col -> registry -> sensor
- Legacy path remains signal-driven for backward compatibility.
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
# Schema-mediated sensor resolution (consumer path)
# -------------------------

def _build_schema_sensor_maps(schema_obj: dict, registry_obj: dict) -> Dict[str, Dict[str, str]]:
    """
    Build per-schema_id lookup: token -> sensor

    token can be:
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


def _resolve_sensor(
    *,
    schema_sensor_map_by_schema: Dict[str, Dict[str, str]],
    registry: dict,
    schema_id_val: object,
    token_val: object,
) -> str:
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


# -------------------------
# Widget constructors
# -------------------------

def make_metric_histogram_widget_for_loader(
    *,
    store: Any,
    schema: dict,
    key_to_ref: Dict[str, Tuple[str, str]],
    events_index_df: pd.DataFrame,
    session_loader: Any,  # required (used to get registry snapshot)
    session_key_col: str = "session_key",
    event_id_col: str = "event_id",
    schema_id_col: str = "schema_id",
    event_type_col: str = "schema_id",
    signal_col: str = "signal_col",
    default_bins: int = 10,
    max_bins: int = 200,
) -> dict:
    """
    Consumer-pattern metric histogram widget (SENSOR-driven).

    Sensor resolution is schema-mediated:
        event row -> (schema_id, token in signal_col) -> schema triggers -> canonical signal_col -> registry -> sensor
    """
    if events_index_df is None or len(events_index_df) == 0:
        raise ValueError("events_index_df is empty")
    if not key_to_ref:
        raise ValueError("key_to_ref is empty")
    if not isinstance(schema, dict) or not schema:
        raise ValueError("schema is missing/empty (required for schema-mediated sensor resolution)")
    if session_loader is None:
        raise ValueError("session_loader is required (used to load registry snapshot)")

    _require_cols(events_index_df, (session_key_col,), name="events_index_df")

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

    # ---- load registry once from any selected session ----
    all_session_keys = (
        events_index_df[session_key_col].dropna().astype(str).unique().tolist()
    )
    all_session_keys = sorted(all_session_keys)
    if not all_session_keys:
        raise ValueError("No session_key values found in events_index_df")

    sk0 = all_session_keys[0]
    sess0 = session_loader(sk0)
    meta0 = (sess0 or {}).get("meta") or {}
    registry = meta0.get("signals") or {}
    if not isinstance(registry, dict) or not registry:
        raise ValueError(
            "Signal registry not found or empty in session_loader(session_key)['meta']['signals']"
        )

    schema_sensor_map_by_schema = _build_schema_sensor_maps(schema, registry)

    viz_df["_sensor"] = [
        _resolve_sensor(
            schema_sensor_map_by_schema=schema_sensor_map_by_schema,
            registry=registry,
            schema_id_val=sid,
            token_val=tok,
        )
        for sid, tok in zip(viz_df[schema_id_col].astype(str), viz_df[signal_col].astype(str))
    ]

    if viz_df["_sensor"].astype(str).str.len().sum() == 0:
        ex = viz_df[[schema_id_col, signal_col]].drop_duplicates().head(8)
        logger.warning(
            "metric_histogram: Could not resolve any sensors via schema+registry. "
            "Sample (schema_id, %s):\n%s",
            signal_col,
            ex.to_string(index=False),
        )

    return _make_widget_from_viz_df_consumer(
        viz_df=viz_df,
        metric_cols=metric_cols,
        session_key_col=session_key_col,
        event_type_col=event_type_col,
        default_bins=default_bins,
        max_bins=max_bins,
    )


# -------------------------
# UI builders
# -------------------------

def _make_widget_from_viz_df_consumer(
    *,
    viz_df: pd.DataFrame,
    metric_cols: List[str],
    session_key_col: str,
    event_type_col: str,
    default_bins: int,
    max_bins: int,
) -> dict:
    """Internal: consumer UI from prepared viz_df (expects viz_df['_sensor'])."""
    logger.info("metric_histogram (consumer): viz_df shape: %s", getattr(viz_df, "shape", None))

    if "_sensor" not in viz_df.columns:
        raise ValueError("viz_df missing required '_sensor' column (consumer path)")

    sessions = sorted(viz_df[session_key_col].dropna().astype(str).unique().tolist())
    event_types = sorted(viz_df[event_type_col].dropna().astype(str).unique().tolist())
    sensors = sorted([x for x in viz_df["_sensor"].dropna().astype(str).unique().tolist() if x])
    metrics = sorted(metric_cols)

    if not sessions:
        raise ValueError(f"No non-null {session_key_col!r} values after join")
    if not event_types:
        raise ValueError(f"No non-null values found in {event_type_col!r} after join")
    if not sensors:
        raise ValueError(
            "No sensors could be resolved via schema+registry (viz_df['_sensor'] is empty). "
            "Check that schema['<schema_id>']['triggers'][<role>]['signal_col'] matches registry keys."
        )

    # --- widgets ---
    lbl_sessions = W.Label("Sessions")
    w_sess_mode = W.RadioButtons(
        options=[("Aggregate sessions", False), ("Compare sessions", True)],
        value=False,
        description="",
    )
    w_sessions = W.SelectMultiple(
        options=sessions,
        value=tuple(sessions),  # default-safe selection
        rows=min(8, max(3, len(sensors), len(sessions))),
        layout=W.Layout(width="450px"),
    )

    lbl_sensors = W.Label("Sensors")
    w_sens_mode = W.RadioButtons(
        options=[("Aggregate sensors", False), ("Compare sensors", True)],
        value=True,
        description="",
    )
    w_sensors = W.SelectMultiple(
        options=sensors,
        value=tuple(sensors[:1]),
        rows=min(8, max(3, len(sensors), len (sessions))),
        layout=W.Layout(width="450px"),

    )

    event_label = W.Label("Event:")
    metric_label = W.Label("Metric:")
    w_event = W.Dropdown(options=event_types, value=event_types[0], description="")
    w_metric = W.Dropdown(options=metrics, value=metrics[0], description="")
    w_bins = W.BoundedIntText(value=int(default_bins), min=1, max=int(max_bins), step=1, description="Bins:", layout=W.Layout(width="150px"),)
    w_cdf = W.Checkbox(value=False, description="CDF")
    w_norm = W.Checkbox(value=True, description="Normalize")
    w_dropna = W.Checkbox(value=True, description="Drop NaNs")
    w_show_stats = W.Checkbox(value=True, description="Show stats")


    out = W.Output()

    def _rebuild_metrics(*_):
        # Restrict metric dropdown to metrics that have at least one finite value for the selected event type
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

        prev = str(w_metric.value) if w_metric.value is not None else ""
        w_metric.options = mcols
        w_metric.value = prev if prev in mcols else (mcols[0] if mcols else None)

    def _vals(sub: pd.DataFrame) -> np.ndarray:
        s = pd.to_numeric(sub[w_metric.value], errors="coerce")
        if w_dropna.value:
            s = s.dropna()
        return s.to_numpy()

    def _render(*_):
        with out:
            clear_output(wait=True)

            sel_sessions = list(map(str, w_sessions.value or ()))
            sel_sensors = list(map(str, w_sensors.value or ()))

            if not sel_sessions:
                print("Select at least one session.")
                return
            if not sel_sensors:
                print("Select at least one sensor.")
                return

            base = viz_df[
                (viz_df[event_type_col].astype(str) == str(w_event.value))
                & (viz_df[session_key_col].astype(str).isin(sel_sessions))
                & (viz_df["_sensor"].astype(str).isin(sel_sensors))
            ]

            compare_sessions = bool(w_sess_mode.value)
            compare_sensors = bool(w_sens_mode.value)

            series: List[Tuple[str, np.ndarray]] = []

            if compare_sessions and compare_sensors:
                for sk in sel_sessions:
                    for s in sel_sensors:
                        sub = base[
                            (base[session_key_col].astype(str) == sk)
                            & (base["_sensor"].astype(str) == s)
                        ]
                        series.append((f"{sk} | {s}", _vals(sub)))

            elif compare_sessions and (not compare_sensors):
                for sk in sel_sessions:
                    sub = base[base[session_key_col].astype(str) == sk]
                    series.append((str(sk), _vals(sub)))

            elif (not compare_sessions) and compare_sensors:
                for s in sel_sensors:
                    sub = base[base["_sensor"].astype(str) == s]
                    series.append((str(s), _vals(sub)))

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
                    label=(name if (compare_sessions or compare_sensors) else None),
                )

            mode_bits = [
                ("sessions=compare" if compare_sessions else "sessions=aggregate"),
                ("sensors=compare" if compare_sensors else "sensors=aggregate"),
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

            if (compare_sessions or compare_sensors):
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

            if w_show_stats.value:
                print("Summary stats:")
                for name, vals in series:
                    print(_series_stats(name, vals))


    def _on_event_change(*_):
        _rebuild_metrics()
        _render()
    
    for w in (w_sess_mode, w_sessions, w_sens_mode, w_sensors, w_event, w_metric, w_bins, w_cdf, w_norm, w_dropna, w_show_stats):
        w.observe(_on_event_change, names="value")

    top_row = W.VBox([W.HBox([W.VBox([event_label, w_event]), W.VBox([metric_label, w_metric])])])

    sessions_col = W.VBox([lbl_sessions, w_sess_mode, w_sessions], layout=W.Layout(align_items="flex-start"))
    sensors_col = W.VBox([lbl_sensors, w_sens_mode, w_sensors], layout=W.Layout(align_items="flex-start"))

    controls = W.VBox(
        [
            top_row,
            W.HBox([sessions_col, sensors_col], layout=W.Layout(gap="12px", align_items="flex-start")),
            W.HBox([w_bins, w_cdf, w_norm, w_dropna, w_show_stats])
        ]
    )

    display(W.VBox([controls, out]))
    _rebuild_metrics()
    _render()

    return {"viz_df": viz_df, "out": out}

def make_metric_histogram_rebuilder(
    *,
    sel: Dict[str, Any],
    schema: dict,
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
                schema=schema,
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
