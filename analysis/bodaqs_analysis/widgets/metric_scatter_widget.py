# -*- coding: utf-8 -*-
"""
Metric scatter browser widget.

Public APIs:
    - make_metric_scatter_widget_for_loader(...)
    - make_metric_scatter_rebuilder(...)
    - prepare_metric_scatter_consumer_data(...)
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import ipywidgets as W
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import clear_output, display

from bodaqs_analysis.sensor_aliases import canonical_sensor_id
from bodaqs_analysis.widgets.contracts import (
    ArtifactStoreLike,
    ENTITY_KEY_COL,
    EVENT_ID_COL,
    KeyToRef,
    RegistryPolicy,
    RebuilderHandle,
    SCHEMA_ID_COL,
    SESSION_KEY_COL,
    SIGNAL_COL,
    EntitySelectionSnapshot,
    SessionLoader,
    SessionSelectorHandle,
    WidgetHandle,
    entity_snapshot_from_handle,
    selection_snapshot_from_handle,
)
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


# ----------------------------
# Shared helpers
# ----------------------------


@dataclass(frozen=True)
class MetricScatterFit:
    slope: float
    intercept: float
    r_squared: float


@dataclass(frozen=True)
class MetricScatterSeries:
    label: str
    x: np.ndarray
    y: np.ndarray


@dataclass(frozen=True)
class MetricScatterSeriesResult:
    label: str
    n: int
    fit: MetricScatterFit | None


def prepare_metric_scatter_consumer_data(
    *,
    events_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    session_keys: Sequence[str],
    session_loader: SessionLoader,
    schema: Optional[Mapping[str, Any]] = None,
    session_key_col: str = SESSION_KEY_COL,
    event_id_col: str = EVENT_ID_COL,
    schema_id_col: str = SCHEMA_ID_COL,
    event_type_col: str = SCHEMA_ID_COL,
    signal_col: str = SIGNAL_COL,
    registry_policy: RegistryPolicy = "union",
    require_schema: bool = True,
) -> Dict[str, Any]:
    """Build prepared scatter-consumer data from preloaded events/metrics."""
    if events_df is None or len(events_df) == 0:
        raise ValueError("No events found for selected sessions.")
    if metrics_df is None or len(metrics_df) == 0:
        raise ValueError("No metrics found for selected sessions.")
    if session_loader is None:
        raise ValueError("session_loader is required")
    if require_schema and (not isinstance(schema, Mapping) or not schema):
        raise ValueError("schema is missing/empty (required for schema-mediated sensor resolution)")
    validate_registry_policy(registry_policy)
    schema_obj = schema if isinstance(schema, Mapping) else {}
    viz_df, metric_cols = build_metric_viz_df(
        events_df=events_df,
        metrics_df=metrics_df,
        session_key_col=session_key_col,
        event_id_col=event_id_col,
        schema_id_col=schema_id_col,
        event_type_col=event_type_col,
        signal_col=signal_col,
        include_optional_event_cols=("run_id", "session_id", "entity_key", "entity_kind", "source_session_key"),
        require_event_type_col=False,
    )
    all_session_keys = sorted({str(sk) for sk in session_keys if str(sk).strip()})
    if not all_session_keys:
        all_session_keys = sorted(viz_df[session_key_col].dropna().astype(str).unique().tolist())
    if not all_session_keys:
        raise ValueError("No session_key values found in metric scatter inputs")
    registries_by_session, schema_maps_by_session = registry_maps_for_sessions(
        session_keys=all_session_keys,
        session_loader=session_loader,
        schema=schema_obj,
        registry_policy=registry_policy,
    )
    viz_df = viz_df.copy()
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
            "metric_scatter: Could not resolve any sensors via schema+registry. "
            "Sample (session_key, schema_id, %s):\n%s",
            signal_col,
            ex.to_string(index=False),
        )

    scope_entity_col = ENTITY_KEY_COL if ENTITY_KEY_COL in viz_df.columns else session_key_col
    entities = sorted(viz_df[scope_entity_col].dropna().astype(str).unique().tolist())
    event_types = sorted(viz_df[event_type_col].dropna().astype(str).unique().tolist())
    sensors = sorted([x for x in viz_df["_sensor"].dropna().astype(str).unique().tolist() if x])
    metrics = sorted(metric_cols)

    if not entities:
        raise ValueError("No non-null scope entity values after join")
    if not event_types:
        raise ValueError(f"No non-null values found in {event_type_col!r} after join")
    if not metrics:
        raise ValueError("No metric columns found after join (expected 'm_' prefix)")
    if not sensors:
        raise ValueError(
            "No sensors could be resolved via schema+registry (viz_df['_sensor'] is empty). "
            "Check that schema triggers and selected-session registries are compatible."
        )

    return {
        "viz_df": viz_df,
        "metric_cols": metric_cols,
        "scope_entity_col": scope_entity_col,
        "entities": entities,
        "event_types": event_types,
        "sensors": sensors,
        "metrics": metrics,
        "registries_by_session": registries_by_session,
        "schema_maps_by_session": schema_maps_by_session,
    }


def filter_metric_scatter_base_df(
    *,
    viz_df: pd.DataFrame,
    event_type_col: str,
    scope_entity_col: str,
    event_value: object,
    entity_values: Sequence[str],
    sensor_values: Sequence[str],
) -> pd.DataFrame:
    sel_entities = [str(v) for v in entity_values if str(v).strip()]
    sel_sensors = [canonical_sensor_id(v) for v in sensor_values if canonical_sensor_id(v)]
    if not sel_entities or not sel_sensors or event_value is None:
        return viz_df.iloc[0:0].copy()
    return viz_df[
        (viz_df[event_type_col].astype(str) == str(event_value))
        & (viz_df[scope_entity_col].astype(str).isin(sel_entities))
        & (viz_df["_sensor"].map(canonical_sensor_id).isin(sel_sensors))
    ].copy()


def metric_scatter_sensor_options(
    *,
    viz_df: pd.DataFrame,
    event_type_col: str,
    event_value: object,
    fallback_options: Sequence[str] | None = None,
) -> list[str]:
    if event_value is None:
        return [str(x) for x in (fallback_options or []) if str(x).strip()]
    sub = viz_df[viz_df[event_type_col].astype(str) == str(event_value)]
    sens = sorted([x for x in sub["_sensor"].dropna().astype(str).unique().tolist() if x])
    if sens:
        return sens
    return [str(x) for x in (fallback_options or []) if str(x).strip()]


def metric_scatter_metric_options(
    *,
    viz_df: pd.DataFrame,
    metric_cols: Sequence[str],
    event_type_col: str,
    event_value: object,
) -> list[str]:
    if event_value is None:
        return [str(c) for c in metric_cols]
    sub = viz_df[viz_df[event_type_col].astype(str) == str(event_value)]
    if sub is None or len(sub) == 0:
        return [str(c) for c in metric_cols]

    mcols: list[str] = []
    for col in metric_cols:
        v = pd.to_numeric(sub[col], errors="coerce").to_numpy(dtype=float)
        if np.isfinite(v).any():
            mcols.append(str(col))
    return mcols or [str(c) for c in metric_cols]


def coerce_metric_scatter_xy(
    sub: pd.DataFrame,
    *,
    x_metric: object,
    y_metric: object,
) -> Tuple[np.ndarray, np.ndarray]:
    if x_metric is None or y_metric is None:
        return np.array([], dtype=float), np.array([], dtype=float)
    x_col = str(x_metric)
    y_col = str(y_metric)
    if x_col not in sub.columns or y_col not in sub.columns:
        return np.array([], dtype=float), np.array([], dtype=float)

    x = pd.to_numeric(sub[x_col], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(sub[y_col], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


def metric_scatter_series_summary(name: str, x: np.ndarray, y: np.ndarray) -> str:
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


def build_metric_scatter_series(
    *,
    viz_df: pd.DataFrame,
    event_type_col: str,
    scope_entity_col: str,
    event_value: object,
    entity_values: Sequence[str],
    sensor_values: Sequence[str],
    x_metric: object,
    y_metric: object,
    series_labeler: Callable[[str, str], str] | None = None,
) -> list[MetricScatterSeries]:
    base = filter_metric_scatter_base_df(
        viz_df=viz_df,
        event_type_col=event_type_col,
        scope_entity_col=scope_entity_col,
        event_value=event_value,
        entity_values=entity_values,
        sensor_values=sensor_values,
    )
    sel_entities = [str(v) for v in entity_values if str(v).strip()]
    sel_sensors = [canonical_sensor_id(v) for v in sensor_values if canonical_sensor_id(v)]

    series: list[MetricScatterSeries] = []
    for entity in sel_entities:
        for sensor in sel_sensors:
            sub = base[
                (base[scope_entity_col].astype(str) == entity)
                & (base["_sensor"].map(canonical_sensor_id) == sensor)
            ]
            x, y = coerce_metric_scatter_xy(sub, x_metric=x_metric, y_metric=y_metric)
            label = series_labeler(entity, sensor) if callable(series_labeler) else f"{entity} | {sensor}"
            series.append(MetricScatterSeries(label=label, x=x, y=y))
    return series


def fit_metric_scatter_line(x: np.ndarray, y: np.ndarray) -> MetricScatterFit | None:
    n = int(len(x))
    if n < 2:
        return None

    slope, intercept = np.polyfit(x, y, 1)
    y_hat = slope * x + intercept
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))
    r_squared = float("nan") if ss_tot <= 0.0 else (1.0 - (ss_res / ss_tot))
    return MetricScatterFit(
        slope=float(slope),
        intercept=float(intercept),
        r_squared=float(r_squared),
    )


def format_metric_scatter_line(fit: MetricScatterFit) -> str:
    sign = "+" if fit.intercept >= 0 else "-"
    return f"y = {fit.slope:.6g} x {sign} {abs(fit.intercept):.6g}"


def plot_metric_scatter_series(
    ax: Any,
    series: Sequence[MetricScatterSeries],
    *,
    alpha: float,
    size: int,
    grid: bool,
    equal_axes: bool,
    diag_line: bool,
    regression: bool,
) -> list[MetricScatterSeriesResult]:
    show_series_labels = len(series) > 1
    any_points = False
    results: list[MetricScatterSeriesResult] = []

    for item in series:
        x = np.asarray(item.x, dtype=float)
        y = np.asarray(item.y, dtype=float)
        n = int(len(x))
        if n == 0:
            results.append(MetricScatterSeriesResult(label=item.label, n=0, fit=None))
            continue

        any_points = True
        sc = ax.scatter(
            x,
            y,
            s=int(size),
            alpha=float(alpha),
            label=(item.label if show_series_labels else None),
        )

        fit = None
        if regression and n >= 2:
            fit = fit_metric_scatter_line(x, y)
            if fit is not None:
                xlo, xhi = float(np.min(x)), float(np.max(x))
                xs = np.array([xlo, xhi], dtype=float)
                ys = fit.slope * xs + fit.intercept
                color = sc.get_facecolors()
                series_color = color[0] if (color is not None and len(color) > 0) else None
                ax.plot(xs, ys, linewidth=2.0, alpha=0.9, color=series_color)

        results.append(MetricScatterSeriesResult(label=item.label, n=n, fit=fit))

    if grid:
        ax.grid(True, which="major", axis="both", alpha=0.3)

    if equal_axes:
        ax.set_aspect("equal", adjustable="datalim")

    if diag_line:
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        lo = min(xmin, ymin)
        hi = max(xmax, ymax)
        ax.plot([lo, hi], [lo, hi], linestyle="--", linewidth=1.0)
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)

    if show_series_labels:
        ax.legend(title="series", fontsize=9)

    if not any_points:
        ax.text(
            0.5,
            0.5,
            "No numeric x/y pairs after filtering",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()

    return results


# ----------------------------
# Consumer-pattern widget
# ----------------------------


def make_metric_scatter_widget_for_loader(
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
    default_alpha: float = 0.6,
    default_size: int = 18,
    auto_display: bool = False,
) -> WidgetHandle:
    """
    Consumer-pattern metric scatter widget.

    Sensor resolution is schema-mediated:
        event row -> (schema_id, signal_col token) -> schema triggers -> registry -> sensor
    """
    if events_index_df is None or len(events_index_df) == 0:
        raise ValueError("events_index_df is empty")
    if not key_to_ref:
        raise ValueError("key_to_ref is empty")
    if not isinstance(schema, Mapping) or not schema:
        raise ValueError("schema is missing/empty (required for schema-mediated sensor resolution)")
    validate_registry_policy(registry_policy)

    require_cols(events_index_df, (session_key_col,), name="events_index_df")
    all_session_keys = sorted(events_index_df[session_key_col].dropna().astype(str).unique().tolist())
    if not all_session_keys:
        raise ValueError("No session_key values found in events_index_df")

    def _load_data_bundle() -> Dict[str, Any]:
        if entity_snapshot is None:
            events_df_sel = load_all_events_for_selected(store, key_to_ref=key_to_ref)
            metrics_df_sel = load_all_metrics_for_selected(store, key_to_ref=key_to_ref)
        else:
            events_df_sel = load_all_events_for_entities(store, snapshot=entity_snapshot)
            metrics_df_sel = load_all_metrics_for_entities(store, snapshot=entity_snapshot)

        return prepare_metric_scatter_consumer_data(
            events_df=events_df_sel,
            metrics_df=metrics_df_sel,
            session_keys=all_session_keys,
            session_loader=session_loader,
            schema=schema,
            session_key_col=session_key_col,
            event_id_col=event_id_col,
            schema_id_col=schema_id_col,
            event_type_col=event_type_col,
            signal_col=signal_col,
            registry_policy=registry_policy,
            require_schema=True,
        )

    return _make_widget_from_viz_df_consumer(
        data_bundle=_load_data_bundle(),
        event_type_col=event_type_col,
        default_alpha=default_alpha,
        default_size=default_size,
        auto_display=auto_display,
        refresh_data_getter=_load_data_bundle,
    )


def _make_widget_from_viz_df_consumer(
    *,
    data_bundle: Mapping[str, Any],
    event_type_col: str,
    default_alpha: float,
    default_size: int,
    auto_display: bool,
    refresh_data_getter: Optional[Callable[[], Dict[str, Any]]] = None,
) -> WidgetHandle:
    viz_df = pd.DataFrame()
    metric_cols: list[str] = []
    scope_entity_col = ENTITY_KEY_COL
    entities: list[str] = []
    event_types: list[str] = []
    sensors: list[str] = []
    metrics: list[str] = []

    state: Dict[str, Any] = {}

    def _apply_data_bundle(bundle: Mapping[str, Any]) -> None:
        nonlocal viz_df, metric_cols, scope_entity_col, entities, event_types, sensors, metrics
        viz_df = bundle["viz_df"]
        metric_cols = list(bundle["metric_cols"])
        scope_entity_col = str(bundle["scope_entity_col"])
        entities = list(map(str, bundle["entities"]))
        event_types = list(map(str, bundle["event_types"]))
        sensors = list(map(str, bundle["sensors"]))
        metrics = list(map(str, bundle["metrics"]))
        state["viz_df"] = viz_df
        state["scope_entity_col"] = scope_entity_col
        state["registries_by_session"] = bundle["registries_by_session"]
        state["schema_maps_by_session"] = bundle["schema_maps_by_session"]

    _apply_data_bundle(data_bundle)

    dummy_label = W.Label(" ")
    event_label = W.Label("Event:")
    w_event = W.Dropdown(options=event_types, value=event_types[0], description="")

    entities_label = W.Label("Entities:")
    w_sessions = W.SelectMultiple(
        options=entities,
        value=tuple(entities),
        description="",
        rows=min(8, max(3, len(entities), len(sensors))),
        layout=W.Layout(width="450px"),
    )

    sensors_label = W.Label("Sensors:")
    w_sensors = W.SelectMultiple(
        options=sensors,
        value=tuple(sensors[:1]),
        description="",
        rows=min(8, max(3, len(entities), len(sensors))),
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

    def _filtered_base() -> pd.DataFrame:
        return filter_metric_scatter_base_df(
            viz_df=viz_df,
            event_type_col=event_type_col,
            scope_entity_col=scope_entity_col,
            event_value=w_event.value,
            entity_values=list(map(str, w_sessions.value)),
            sensor_values=list(map(str, w_sensors.value)),
        )

    def _rebuild_sensors(*_):
        sens = metric_scatter_sensor_options(
            viz_df=viz_df,
            event_type_col=event_type_col,
            event_value=w_event.value,
            fallback_options=sensors,
        )
        prev = set(map(str, w_sensors.value))
        w_sensors.options = sens
        keep = [s for s in sens if s in prev]
        if keep:
            w_sensors.value = tuple(keep)
        else:
            w_sensors.value = tuple(sens[:1]) if sens else ()

    def _rebuild_metrics(*_):
        mcols = metric_scatter_metric_options(
            viz_df=viz_df,
            metric_cols=metrics,
            event_type_col=event_type_col,
            event_value=w_event.value,
        )
        prev_x = str(w_x.value) if w_x.value is not None else ""
        prev_y = str(w_y.value) if w_y.value is not None else ""

        w_x.options = mcols
        w_y.options = mcols

        w_x.value = prev_x if prev_x in mcols else (mcols[0] if mcols else None)
        if prev_y in mcols:
            w_y.value = prev_y
        else:
            w_y.value = mcols[1] if (mcols and len(mcols) > 1 and mcols[1] != w_x.value) else (mcols[0] if mcols else None)

    out = W.Output()

    def _render(*_):
        with out:
            clear_output(wait=True)

            sel_entities = list(w_sessions.value)
            sel_sensors = list(w_sensors.value)
            if not sel_entities:
                print("Select at least one entity.")
                return
            if not sel_sensors:
                print("Select at least one sensor.")
                return

            base = _filtered_base()
            if len(base) == 0:
                print("No rows after filtering.")
                return

            fig, ax = plt.subplots(figsize=(8.8, 5.2))
            series = build_metric_scatter_series(
                viz_df=viz_df,
                event_type_col=event_type_col,
                scope_entity_col=scope_entity_col,
                event_value=w_event.value,
                entity_values=sel_entities,
                sensor_values=sel_sensors,
                x_metric=w_x.value,
                y_metric=w_y.value,
            )
            fit_results = plot_metric_scatter_series(
                ax,
                series,
                alpha=float(w_alpha.value),
                size=int(w_size.value),
                grid=bool(w_grid.value),
                equal_axes=bool(w_equal.value),
                diag_line=bool(w_diag.value),
                regression=bool(w_regress.value),
            )

            ax.set_title(
                f"{w_y.value} vs {w_x.value}\n"
                f"{event_type_col}={w_event.value} | entities=compare, sensors=compare"
            )
            ax.set_xlabel(str(w_x.value))
            ax.set_ylabel(str(w_y.value))

            plt.show()

            if w_stats.value:
                print("Summary stats (finite x/y pairs only):")
                for item in series:
                    print(metric_scatter_series_summary(item.label, item.x, item.y))

            if w_regress.value:
                print("\nLinear regression (per series):")
                for result in fit_results:
                    if result.fit is None:
                        if result.n < 2:
                            print(f"- {result.label}: n={result.n} (need >=2 points)")
                        else:
                            print(f"- {result.label}: fit unavailable")
                        continue
                    eq = format_metric_scatter_line(result.fit)
                    print(f"- {result.label}: n={result.n}  {eq}  R^2={result.fit.r_squared:.6g}")

    def refresh() -> None:
        if refresh_data_getter is not None:
            _apply_data_bundle(refresh_data_getter())

        w_sessions.options = entities
        kept_entities = tuple([s for s in map(str, w_sessions.value) if s in entities])
        w_sessions.value = kept_entities if kept_entities else tuple(entities)

        w_event.options = event_types
        if str(w_event.value) not in set(event_types):
            w_event.value = event_types[0] if event_types else None

        _rebuild_sensors()
        _rebuild_metrics()
        _render()

    def _on_event_change(*_):
        _rebuild_sensors()
        _rebuild_metrics()
        _render()

    for w in (
        w_sessions,
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

    w_event.observe(_on_event_change, names="value")

    controls = W.VBox(
        [
            W.HBox([W.VBox([event_label, w_event])]),
            W.HBox([W.VBox([metrics_label, w_x]), W.VBox([dummy_label, w_y])]),
            W.HBox(
                [
                    W.VBox([entities_label, w_sessions]),
                    W.VBox([sensors_label, w_sensors]),
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
    root = W.VBox([controls, out])

    _rebuild_sensors()
    _rebuild_metrics()
    _render()

    if auto_display:
        display(root)

    return {
        "root": root,
        "out": out,
        "viz_df": viz_df,
        "refresh": refresh,
        "state": state,
        "controls": {
            "event": w_event,
            "sessions": w_sessions,
            "sensors": w_sensors,
            "x": w_x,
            "y": w_y,
            "alpha": w_alpha,
            "size": w_size,
            "grid": w_grid,
            "equal": w_equal,
            "diag": w_diag,
            "stats": w_stats,
            "regress": w_regress,
        },
    }


def make_metric_scatter_rebuilder(
    *,
    sel: SessionSelectorHandle,
    schema: Mapping[str, Any],
    out: Optional[W.Output] = None,
    event_type_col: str = SCHEMA_ID_COL,
    signal_col: str = SIGNAL_COL,
    registry_policy: RegistryPolicy = "union",
    **kwargs: Any,
) -> RebuilderHandle:
    """
    Create a self-contained rebuilder for the metric scatter widget.
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
            state["handles"] = make_metric_scatter_widget_for_loader(
                store=store,
                schema=schema,
                key_to_ref=key_to_ref,
                events_index_df=events_index_df,
                session_loader=session_loader,
                entity_snapshot=entity_snapshot,
                event_type_col=event_type_col,
                signal_col=signal_col,
                registry_policy=registry_policy,
                auto_display=False,
                **kwargs,
            )
            h = state["handles"]
            root = h.get("root") or h.get("ui")
            if root is not None:
                display(root)

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}
