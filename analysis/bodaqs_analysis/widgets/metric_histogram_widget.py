# -*- coding: utf-8 -*-
"""
Metric histogram / CDF browser widget.

Consumer-pattern implementation for the BODAQS JupyterLab artifacts pipeline.

Public APIs:
    - make_metric_histogram_widget_for_loader(...)
    - make_metric_histogram_rebuilder(...)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

import ipywidgets as W
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import clear_output, display

from bodaqs_analysis.widgets.contracts import (
    ArtifactStoreLike,
    ENTITY_KEY_COL,
    EVENT_ID_COL,
    EntitySelectionSnapshot,
    KeyToRef,
    RegistryPolicy,
    RebuilderHandle,
    SCHEMA_ID_COL,
    SESSION_KEY_COL,
    SIGNAL_COL,
    SessionLoader,
    SessionSelectorHandle,
    WidgetHandle,
    entity_snapshot_from_handle,
    selection_snapshot_from_handle,
)
from bodaqs_analysis.widgets.histogram_core import plot_hist_or_cdf, series_stats_line
from bodaqs_analysis.widgets.loaders import (
    load_all_events_for_entities,
    load_all_events_for_selected,
    load_all_metrics_for_entities,
    load_all_metrics_for_selected,
    make_session_loader,
)
from bodaqs_analysis.widgets.metric_widget_data import (
    assign_sensor_column,
    build_metric_viz_df,
    registry_maps_for_sessions,
    require_cols,
)
from bodaqs_analysis.widgets.registry_scope import validate_registry_policy

logger = logging.getLogger(__name__)


# -------------------------
# Widget constructors
# -------------------------


def make_metric_histogram_widget_for_loader(
    *,
    store: ArtifactStoreLike,
    schema: Mapping[str, Any],
    key_to_ref: KeyToRef,
    events_index_df: pd.DataFrame,
    session_loader: SessionLoader,
    entity_snapshot: Optional[EntitySelectionSnapshot] = None,
    session_key_col: str = SESSION_KEY_COL,
    event_id_col: str = EVENT_ID_COL,
    schema_id_col: str = SCHEMA_ID_COL,
    event_type_col: str = SCHEMA_ID_COL,
    signal_col: str = SIGNAL_COL,
    registry_policy: RegistryPolicy = "union",
    default_bins: int = 10,
    max_bins: int = 200,
    auto_display: bool = False,
) -> WidgetHandle:
    """
    Consumer-pattern metric histogram widget (sensor-driven).

    Sensor resolution is schema-mediated:
        event row -> (schema_id, token in signal_col) -> schema triggers -> canonical signal_col -> registry -> sensor
    """
    if events_index_df is None or len(events_index_df) == 0:
        raise ValueError("events_index_df is empty")
    if not key_to_ref:
        raise ValueError("key_to_ref is empty")
    if not isinstance(schema, Mapping) or not schema:
        raise ValueError("schema is missing/empty (required for schema-mediated sensor resolution)")
    if session_loader is None:
        raise ValueError("session_loader is required")
    validate_registry_policy(registry_policy)

    require_cols(events_index_df, (session_key_col,), name="events_index_df")

    if entity_snapshot is None:
        events_df_sel = load_all_events_for_selected(store, key_to_ref=key_to_ref)
        metrics_df_sel = load_all_metrics_for_selected(store, key_to_ref=key_to_ref)
    else:
        events_df_sel = load_all_events_for_entities(store, snapshot=entity_snapshot)
        metrics_df_sel = load_all_metrics_for_entities(store, snapshot=entity_snapshot)

    viz_df, metric_cols = build_metric_viz_df(
        events_df=events_df_sel,
        metrics_df=metrics_df_sel,
        session_key_col=session_key_col,
        event_id_col=event_id_col,
        schema_id_col=schema_id_col,
        event_type_col=event_type_col,
        signal_col=signal_col,
        include_optional_event_cols=("run_id", "session_id", "entity_key", "entity_kind", "source_session_key"),
        require_event_type_col=True,
    )

    all_session_keys = sorted(
        events_index_df[session_key_col].dropna().astype(str).unique().tolist()
    )
    if not all_session_keys:
        raise ValueError("No session_key values found in events_index_df")

    registries_by_session, schema_maps_by_session = registry_maps_for_sessions(
        session_keys=all_session_keys,
        session_loader=session_loader,
        schema=schema,
        registry_policy=registry_policy,
    )
    viz_df["_sensor"] = assign_sensor_column(
        viz_df=viz_df,
        session_key_col=session_key_col,
        schema_id_col=schema_id_col,
        signal_col=signal_col,
        registries_by_session=registries_by_session,
        schema_maps_by_session=schema_maps_by_session,
    )

    if viz_df["_sensor"].astype(str).str.len().sum() == 0:
        ex = viz_df[[session_key_col, schema_id_col, signal_col]].drop_duplicates().head(8)
        logger.warning(
            "metric_histogram: Could not resolve any sensors via schema+registry. "
            "Sample (session_key, schema_id, %s):\n%s",
            signal_col,
            ex.to_string(index=False),
        )

    return _make_widget_from_viz_df_consumer(
        viz_df=viz_df,
        metric_cols=metric_cols,
        session_key_col=session_key_col,
        event_type_col=event_type_col,
        scope_entity_col=(ENTITY_KEY_COL if ENTITY_KEY_COL in viz_df.columns else session_key_col),
        default_bins=default_bins,
        max_bins=max_bins,
        auto_display=auto_display,
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
    scope_entity_col: str,
    default_bins: int,
    max_bins: int,
    auto_display: bool,
) -> WidgetHandle:
    """Internal: consumer UI from prepared viz_df (expects viz_df['_sensor'])."""
    logger.info("metric_histogram (consumer): viz_df shape: %s", getattr(viz_df, "shape", None))

    if "_sensor" not in viz_df.columns:
        raise ValueError("viz_df missing required '_sensor' column (consumer path)")

    entities = sorted(viz_df[scope_entity_col].dropna().astype(str).unique().tolist())
    event_types = sorted(viz_df[event_type_col].dropna().astype(str).unique().tolist())
    sensors = sorted([x for x in viz_df["_sensor"].dropna().astype(str).unique().tolist() if x])
    metrics = sorted(metric_cols)

    if not entities:
        raise ValueError(f"No non-null {scope_entity_col!r} values after join")
    if not event_types:
        raise ValueError(f"No non-null values found in {event_type_col!r} after join")
    if not sensors:
        raise ValueError(
            "No sensors could be resolved via schema+registry (viz_df['_sensor'] is empty). "
            "Check that schema triggers and session registries are compatible."
        )

    lbl_sessions = W.Label("Entities")
    w_sessions = W.SelectMultiple(
        options=entities,
        value=tuple(entities),
        rows=min(8, max(3, len(sensors), len(entities))),
        layout=W.Layout(width="450px"),
    )

    lbl_sensors = W.Label("Sensors")
    w_sensors = W.SelectMultiple(
        options=sensors,
        value=tuple(sensors[:1]),
        rows=min(8, max(3, len(sensors), len(entities))),
        layout=W.Layout(width="450px"),
    )

    event_label = W.Label("Event:")
    metric_label = W.Label("Metric:")
    w_event = W.Dropdown(options=event_types, value=event_types[0], description="")
    w_metric = W.Dropdown(options=metrics, value=metrics[0], description="")
    w_bins = W.BoundedIntText(
        value=int(default_bins),
        min=1,
        max=int(max_bins),
        step=1,
        description="Bins:",
        layout=W.Layout(width="150px"),
    )
    w_cdf = W.Checkbox(value=False, description="CDF")
    w_norm = W.Checkbox(value=True, description="Normalize")
    w_dropna = W.Checkbox(value=True, description="Drop NaNs")
    w_show_stats = W.Checkbox(value=True, description="Show stats")

    out = W.Output()

    def _rebuild_metrics(*_):
        sub = viz_df[viz_df[event_type_col].astype(str) == str(w_event.value)]
        if sub is None or len(sub) == 0:
            mcols = metrics[:]
        else:
            mcols = []
            for c in metrics:
                v = pd.to_numeric(sub[c], errors="coerce").to_numpy(dtype=float)
                if np.isfinite(v).any():
                    mcols.append(c)
            if not mcols:
                mcols = metrics[:]

        prev = str(w_metric.value) if w_metric.value is not None else ""
        w_metric.options = mcols
        w_metric.value = prev if prev in mcols else (mcols[0] if mcols else None)

    def _vals(sub: pd.DataFrame) -> np.ndarray:
        if w_metric.value is None:
            return np.array([], dtype=float)
        s = pd.to_numeric(sub[w_metric.value], errors="coerce")
        if w_dropna.value:
            s = s.dropna()
        return s.to_numpy(dtype=float)

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
                & (viz_df[scope_entity_col].astype(str).isin(sel_sessions))
                & (viz_df["_sensor"].astype(str).isin(sel_sensors))
            ]

            series: List[Tuple[str, np.ndarray]] = []

            for sk in sel_sessions:
                for s in sel_sensors:
                    sub = base[
                        (base[scope_entity_col].astype(str) == sk)
                        & (base["_sensor"].astype(str) == s)
                    ]
                    series.append((f"{sk} | {s}", _vals(sub)))

            fig, ax = plt.subplots(figsize=(8.3, 4.2))
            show_series_labels = len(series) > 1
            for name, vals in series:
                plot_hist_or_cdf(
                    ax,
                    vals,
                    int(w_bins.value),
                    cdf=bool(w_cdf.value),
                    norm=bool(w_norm.value),
                    label=(name if show_series_labels else None),
                )

            ax.set_title(
                f"{w_metric.value} distribution\n"
                f"{event_type_col}={w_event.value} | entities=compare, sensors=compare"
            )
            ax.set_xlabel(str(w_metric.value))
            ax.set_ylabel(
                ("Cumulative proportion" if w_norm.value else "Cumulative count")
                if w_cdf.value
                else ("Proportion" if w_norm.value else "Count")
            )
            ax.grid(True, which="major", axis="both", alpha=0.3)

            if show_series_labels:
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
                    print(series_stats_line(name, vals))

    def _on_controls_change(*_):
        _rebuild_metrics()
        _render()

    for w in (
        w_sessions,
        w_sensors,
        w_event,
        w_metric,
        w_bins,
        w_cdf,
        w_norm,
        w_dropna,
        w_show_stats,
    ):
        w.observe(_on_controls_change, names="value")

    top_row = W.VBox([W.HBox([W.VBox([event_label, w_event]), W.VBox([metric_label, w_metric])])])
    sessions_col = W.VBox([lbl_sessions, w_sessions], layout=W.Layout(align_items="flex-start"))
    sensors_col = W.VBox([lbl_sensors, w_sensors], layout=W.Layout(align_items="flex-start"))
    controls = W.VBox(
        [
            top_row,
            W.HBox([sessions_col, sensors_col], layout=W.Layout(gap="12px", align_items="flex-start")),
            W.HBox([w_bins, w_cdf, w_norm, w_dropna, w_show_stats]),
        ]
    )
    root = W.VBox([controls, out])

    def refresh() -> None:
        _rebuild_metrics()
        _render()

    refresh()
    if auto_display:
        display(root)

    return {
        "root": root,
        "out": out,
        "viz_df": viz_df,
        "controls": {
            "sessions": w_sessions,
            "sensors": w_sensors,
            "event": w_event,
            "metric": w_metric,
            "bins": w_bins,
            "cdf": w_cdf,
            "normalize": w_norm,
            "dropna": w_dropna,
            "show_stats": w_show_stats,
        },
        "refresh": refresh,
    }


def make_metric_histogram_rebuilder(
    *,
    sel: SessionSelectorHandle,
    schema: Mapping[str, Any],
    out: Optional[W.Output] = None,
    session_key_col: str = SESSION_KEY_COL,
    event_id_col: str = EVENT_ID_COL,
    schema_id_col: str = SCHEMA_ID_COL,
    event_type_col: str = SCHEMA_ID_COL,
    signal_col: str = SIGNAL_COL,
    registry_policy: RegistryPolicy = "union",
    default_bins: int = 10,
    max_bins: int = 200,
) -> RebuilderHandle:
    """
    Rebuild-on-selector-change helper.

    Returns: {"out": out, "rebuild": rebuild, "state": {"handles": ...}}
    """
    if out is None:
        out = W.Output()

    state: Dict[str, Any] = {"handles": None}

    def rebuild() -> None:
        snapshot = selection_snapshot_from_handle(sel)
        entity_snapshot = entity_snapshot_from_handle(sel)
        store = sel["store"]
        key_to_ref = snapshot.key_to_ref
        events_index_df = snapshot.events_index_df
        session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)

        with out:
            clear_output(wait=True)
            state["handles"] = make_metric_histogram_widget_for_loader(
                store=store,
                schema=schema,
                key_to_ref=key_to_ref,
                events_index_df=events_index_df,
                session_loader=session_loader,
                entity_snapshot=entity_snapshot,
                session_key_col=session_key_col,
                event_id_col=event_id_col,
                schema_id_col=schema_id_col,
                event_type_col=event_type_col,
                signal_col=signal_col,
                registry_policy=registry_policy,
                default_bins=default_bins,
                max_bins=max_bins,
                auto_display=False,
            )
            h = state["handles"]
            root = h.get("root") or h.get("ui")
            if root is not None:
                display(root)

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}
