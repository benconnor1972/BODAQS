from __future__ import annotations

import asyncio
from typing import Any, Dict, Mapping, Optional, Sequence

import ipywidgets as W
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import clear_output, display
from ipyleaflet import CircleMarker, LayerGroup, LayersControl, Map, Polyline, basemap_to_tiles, basemaps

from bodaqs_analysis.widgets.contracts import (
    RebuilderHandle,
    SESSION_KEY_COL,
    SessionLoader,
    SessionSelectorHandle,
    WidgetHandle,
    selection_snapshot_from_handle,
)
from bodaqs_analysis.widgets.gps_data import (
    GPSViewData,
    LineRun,
    SpeedColorBin,
    build_line_runs_from_segments,
    build_route_segments,
    extract_gps_view_data,
    nearest_route_point,
    route_bounds,
    subset_segments_by_window,
)
from bodaqs_analysis.widgets.time_selection import SessionTimeSelection, make_session_time_selection

_GPS_BROWSER_SOURCE = "gps_browser"
_DEFAULT_ROUTE_COLOR = "#2563eb"
_INACTIVE_ROUTE_COLOR = "#9ca3af"
_POINT_COLOR = "#111827"
_POINT_FILL_COLOR = "#f59e0b"

_BASEMAP_OPTIONS: dict[str, Any] = {
    "OpenStreetMap": basemaps.OpenStreetMap.Mapnik,
    "Humanitarian": basemaps.OpenStreetMap.HOT,
    "Topo": basemaps.OpenTopoMap,
    "Light": basemaps.CartoDB.Positron,
    "Satellite": basemaps.Esri.WorldImagery,
}


def _empty_geojson() -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": []}


def _speed_legend_html(bins: Sequence[SpeedColorBin]) -> str:
    if not bins:
        return "<span style='color:#666;'>Speed coloring unavailable for this session.</span>"
    bits = []
    for item in bins:
        bits.append(
            "<span style='display:inline-flex; align-items:center; margin-right:10px;'>"
            f"<span style='display:inline-block; width:12px; height:12px; background:{item.color}; margin-right:4px; border:1px solid #ddd;'></span>"
            f"{item.label}"
            "</span>"
        )
    return "".join(bits)


def _split_run_coordinates(run: LineRun) -> list[list[tuple[float, float]]]:
    lines: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for lat, lon in run.coordinates:
        if np.isfinite(lat) and np.isfinite(lon):
            current.append((float(lat), float(lon)))
            continue
        if len(current) >= 2:
            lines.append(current)
        current = []
    if len(current) >= 2:
        lines.append(current)
    return lines


def _make_polyline_group(
    runs: Sequence[LineRun],
    *,
    weight: int,
    opacity: float,
    default_color: str,
) -> LayerGroup:
    layers: list[Polyline] = []
    for run in runs:
        lines = _split_run_coordinates(run)
        if not lines:
            continue
        color = str(run.color or default_color)
        for line in lines:
            layers.append(
                Polyline(
                    locations=line,
                    color=color,
                    weight=int(weight),
                    opacity=float(opacity),
                    fill=False,
                )
            )
    return LayerGroup(layers=tuple(layers))


def _window_shapes(*, t0_s: Optional[float], t1_s: Optional[float], selected_time_s: Optional[float]) -> list[dict[str, Any]]:
    shapes: list[dict[str, Any]] = []
    if t0_s is not None and t1_s is not None and np.isfinite(float(t0_s)) and np.isfinite(float(t1_s)):
        a = float(min(t0_s, t1_s))
        b = float(max(t0_s, t1_s))
        shapes.append(
            {
                "type": "rect",
                "xref": "x",
                "yref": "paper",
                "x0": a,
                "x1": b,
                "y0": 0.0,
                "y1": 1.0,
                "fillcolor": "rgba(245, 158, 11, 0.12)",
                "line": {"width": 0},
                "layer": "below",
            }
        )
    if selected_time_s is not None and np.isfinite(float(selected_time_s)):
        x = float(selected_time_s)
        shapes.append(
            {
                "type": "line",
                "xref": "x",
                "yref": "paper",
                "x0": x,
                "x1": x,
                "y0": 0.0,
                "y1": 1.0,
                "line": {"color": _POINT_FILL_COLOR, "width": 2},
            }
        )
    return shapes


def _window_covers_full_extent(
    *,
    t0_s: Optional[float],
    t1_s: Optional[float],
    full_t0_s: Optional[float],
    full_t1_s: Optional[float],
) -> bool:
    if (
        t0_s is None
        or t1_s is None
        or full_t0_s is None
        or full_t1_s is None
    ):
        return False
    a = float(min(t0_s, t1_s))
    b = float(max(t0_s, t1_s))
    fa = float(min(full_t0_s, full_t1_s))
    fb = float(max(full_t0_s, full_t1_s))
    tol = max(1e-9, 1e-6 * max(1.0, abs(fb - fa)))
    return a <= (fa + tol) and b >= (fb - tol)


def _fallback_center_from_bounds(bounds: Sequence[Sequence[float]]) -> Optional[tuple[float, float]]:
    try:
        lat0, lon0 = bounds[0]
        lat1, lon1 = bounds[1]
        return ((float(lat0) + float(lat1)) / 2.0, (float(lon0) + float(lon1)) / 2.0)
    except Exception:
        return None


def _fallback_zoom_from_bounds(bounds: Sequence[Sequence[float]]) -> Optional[int]:
    try:
        lat0, lon0 = bounds[0]
        lat1, lon1 = bounds[1]
        lat0_f = float(lat0)
        lon0_f = float(lon0)
        lat1_f = float(lat1)
        lon1_f = float(lon1)
    except Exception:
        return None

    lat_span = abs(lat1_f - lat0_f)
    lon_span = abs(lon1_f - lon0_f)
    if lon_span > 180.0:
        lon_span = 360.0 - lon_span
    mean_lat_rad = np.deg2rad((lat0_f + lat1_f) / 2.0)
    lon_span = lon_span * max(0.1, float(np.cos(mean_lat_rad)))
    span = max(lat_span, lon_span, 1e-6)
    zoom = int(np.floor(np.log2(360.0 / span)) - 1.0)
    return int(np.clip(zoom, 2, 18))


def make_gps_browser_widget_for_loader(
    *,
    session_keys: Sequence[str],
    session_loader: SessionLoader,
    selection_model: Optional[SessionTimeSelection] = None,
    preferred_stream_name: str = "gps_fit",
    time_col: str = "time_s",
    show_session_control: bool = True,
    map_height_px: int = 420,
    chart_height_px: int = 300,
    auto_display: bool = False,
) -> WidgetHandle:
    keys = sorted(str(x) for x in session_keys if str(x).strip())
    if not keys:
        raise ValueError("session_keys is empty")

    selection = selection_model or make_session_time_selection()

    w_session = W.Dropdown(options=keys, value=keys[0], description="Session", layout=W.Layout(width="360px"))
    w_basemap = W.Dropdown(
        options=list(_BASEMAP_OPTIONS.keys()),
        value="OpenStreetMap",
        description="Basemap",
        layout=W.Layout(width="240px"),
    )
    w_map_height = W.IntSlider(
        value=int(map_height_px),
        min=240,
        max=900,
        step=20,
        description="Map height",
        readout=True,
        continuous_update=False,
        layout=W.Layout(width="260px"),
    )
    w_color_by_speed = W.Checkbox(value=True, description="Color by speed")
    if not show_session_control:
        w_session.layout.display = "none"
    w_status = W.HTML("")
    w_speed_legend = W.HTML("")
    w_source = W.HTML("")

    fig = go.FigureWidget()
    fig.layout = go.Layout(
        height=chart_height_px,
        margin=dict(l=55, r=20, t=20, b=70),
        xaxis=dict(
            title="time (s)",
            showgrid=True,
            rangeslider=dict(visible=False),
            showline=True,
            mirror=True,
            linecolor="#9ca3af",
            linewidth=1,
        ),
        yaxis=dict(
            title="altitude (m)",
            showgrid=True,
            showline=True,
            mirror=True,
            linecolor="#9ca3af",
            linewidth=1,
        ),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        template="none",
        hovermode="closest",
        showlegend=True,
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.25, yanchor="top"),
        uirevision="gps_browser_keep",
    )
    fig.layout.xaxis.uirevision = "gps_browser_keep"
    fig.layout.yaxis.uirevision = "gps_browser_keep"
    fig.update_xaxes(rangeslider_visible=False)

    map_widget = Map(center=(0.0, 0.0), zoom=2, scroll_wheel_zoom=True, layout=W.Layout(width="100%", height=f"{map_height_px}px"))
    base_layer = basemap_to_tiles(_BASEMAP_OPTIONS[str(w_basemap.value)])
    base_layer.base = True
    if getattr(map_widget, "layers", None):
        map_widget.substitute(map_widget.layers[0], base_layer)
    else:
        map_widget.add(base_layer)

    route_layer = _make_polyline_group((), weight=4, opacity=0.9, default_color=_DEFAULT_ROUTE_COLOR)
    window_layer = _make_polyline_group((), weight=6, opacity=1.0, default_color=_DEFAULT_ROUTE_COLOR)
    point_marker = CircleMarker(
        location=(0.0, 0.0),
        radius=0,
        color=_POINT_COLOR,
        fill_color=_POINT_FILL_COLOR,
        fill_opacity=1.0,
        weight=2,
    )
    map_widget.add(route_layer)
    map_widget.add(window_layer)
    map_widget.add(point_marker)
    map_widget.add(LayersControl(position="topright"))

    state: Dict[str, Any] = {
        "session": None,
        "gps_view": None,
        "segment_df": pd.DataFrame(),
        "selection_model": selection,
        "base_layer": base_layer,
        "route_layer": route_layer,
        "window_layer": window_layer,
        "point_marker": point_marker,
        "updating": False,
        "selection_sync_active": False,
        "show_session_control": bool(show_session_control),
    }

    def _selection_snapshot() -> dict[str, Any]:
        return selection.snapshot()

    def _set_selection(
        *,
        session_key: Optional[str] = None,
        window: Optional[tuple[Optional[float], Optional[float]]] = None,
        selected_time_s: Any = None,
        set_selected_time: bool = False,
    ) -> None:
        state["selection_sync_active"] = True
        try:
            selection.update_state(
                session_key=session_key,
                window_t0_s=None if window is None else window[0],
                window_t1_s=None if window is None else window[1],
                selected_time_s=selected_time_s,
                set_selected_time=set_selected_time,
                source=_GPS_BROWSER_SOURCE,
            )
        finally:
            state["selection_sync_active"] = False

    def _current_window_from_fig() -> Optional[tuple[float, float]]:
        route_df = (state.get("gps_view") or {}).route_df if isinstance(state.get("gps_view"), GPSViewData) else None
        if route_df is None or route_df.empty:
            return None
        try:
            xr = fig.layout.xaxis.range
            if xr is not None and len(xr) == 2 and xr[0] is not None and xr[1] is not None:
                return (float(xr[0]), float(xr[1]))
        except Exception:
            pass
        t = pd.to_numeric(route_df["time_s"], errors="coerce").to_numpy(dtype=float)
        t = t[np.isfinite(t)]
        if t.size == 0:
            return None
        return (float(np.min(t)), float(np.max(t)))

    def _set_status(msg: str) -> None:
        w_status.value = f"<span style='color:#666;'>{msg}</span>"

    def _replace_map_layer(
        key: str,
        *,
        layer: Any,
    ) -> Any:
        old_layer = state.get(key)
        if old_layer is None:
            map_widget.add(layer)
        else:
            map_widget.substitute(old_layer, layer)
        state[key] = layer
        return layer

    def _set_map_height(height_px: int) -> None:
        value = int(np.clip(int(height_px), int(w_map_height.min), int(w_map_height.max)))
        map_widget.layout.height = f"{value}px"

    def _replace_route_group(
        key: str,
        *,
        runs: Sequence[LineRun],
        color: str,
        weight: int,
        opacity: float,
    ) -> LayerGroup:
        new_layer = _make_polyline_group(
            runs,
            weight=weight,
            opacity=opacity,
            default_color=color,
        )
        return _replace_map_layer(key, layer=new_layer)

    def _clear_visuals(msg: str) -> None:
        with fig.batch_update():
            fig.data = ()
            fig.layout.shapes = ()
            state["selection_sync_active"] = True
            try:
                fig.layout.xaxis.range = None
            finally:
                state["selection_sync_active"] = False
        _replace_route_group(
            "route_layer",
            runs=(),
            color=_INACTIVE_ROUTE_COLOR,
            weight=4,
            opacity=0.9,
        )
        _replace_route_group(
            "window_layer",
            runs=(),
            color=_DEFAULT_ROUTE_COLOR,
            weight=6,
            opacity=1.0,
        )
        point_marker.radius = 0
        w_speed_legend.value = ""
        w_source.value = ""
        _set_status(msg)

    def _apply_basemap() -> None:
        new_layer = basemap_to_tiles(_BASEMAP_OPTIONS[str(w_basemap.value)])
        new_layer.base = True
        map_widget.substitute(state["base_layer"], new_layer)
        state["base_layer"] = new_layer

    def _attach_altitude_click(trace: go.Scatter) -> None:
        def _on_click(this_trace: go.Scatter, points: Any, _state: Any) -> None:
            if not points.point_inds:
                return
            idx = int(points.point_inds[0])
            if idx < 0 or idx >= len(this_trace.x):
                return
            try:
                x = float(this_trace.x[idx])
            except Exception:
                return
            _set_selection(session_key=str(w_session.value), selected_time_s=x, set_selected_time=True)
            _refresh_selection_overlays()

        trace.on_click(_on_click, append=False)

    def _refresh_altitude_plot() -> None:
        gps_view = state.get("gps_view")
        segment_df = state.get("segment_df")
        if not isinstance(gps_view, GPSViewData) or gps_view.route_df.empty:
            _clear_visuals("No GPS route is available for the selected session.")
            return

        route_df = gps_view.route_df
        color_by_speed = bool(w_color_by_speed.value)
        runs, bins = build_line_runs_from_segments(
            segment_df,
            color_by_speed=color_by_speed,
            default_color=_DEFAULT_ROUTE_COLOR,
        )
        current = _selection_snapshot()
        current_window = None
        if current.get("session_key") == str(w_session.value):
            t0 = current.get("window_t0_s")
            t1 = current.get("window_t1_s")
            if t0 is not None and t1 is not None:
                current_window = (float(t0), float(t1))

        has_altitude_trace = False
        full_window = None
        route_time = pd.to_numeric(route_df["time_s"], errors="coerce").to_numpy(dtype=float)
        route_time = route_time[np.isfinite(route_time)]
        if route_time.size:
            full_window = (float(np.min(route_time)), float(np.max(route_time)))
        with fig.batch_update():
            fig.data = ()
            shown_labels: set[str] = set()
            for run in runs:
                alt = np.asarray(run.altitudes_m, dtype=float)
                x = np.asarray(run.times_s, dtype=float)
                if int(np.isfinite(x).sum()) < 2 or int(np.isfinite(alt).sum()) < 2:
                    continue
                has_altitude_trace = True
                showlegend = str(run.label) not in shown_labels
                shown_labels.add(str(run.label))
                speed_mps = np.asarray(run.speeds_mps, dtype=float)
                speed_kph = speed_mps * 3.6
                trace = go.Scatter(
                    x=x,
                    y=alt,
                    mode="lines",
                    line=dict(color=str(run.color), width=2.8),
                    customdata=speed_kph,
                    hovertemplate="time: %{x:.1f}s<br>speed: %{customdata:.1f} km/h<extra></extra>",
                    name=str(run.label),
                    showlegend=bool(color_by_speed and showlegend),
                )
                fig.add_trace(trace)
                _attach_altitude_click(trace)

            selected_time = None
            if current.get("session_key") == str(w_session.value):
                selected_time = current.get("selected_time_s")
            point = nearest_route_point(route_df, time_s=selected_time)
            if point is not None and np.isfinite(float(point.get("altitude_m", np.nan))):
                fig.add_trace(
                    go.Scatter(
                        x=[float(point["time_s"])],
                        y=[float(point["altitude_m"])],
                        mode="markers",
                        marker=dict(size=9, color=_POINT_FILL_COLOR, line=dict(color=_POINT_COLOR, width=2)),
                        name="selected point",
                        showlegend=False,
                        hoverinfo="skip",
                    )
                )

            rect_window = current_window
            if current_window is not None and full_window is not None:
                if _window_covers_full_extent(
                    t0_s=current_window[0],
                    t1_s=current_window[1],
                    full_t0_s=full_window[0],
                    full_t1_s=full_window[1],
                ):
                    rect_window = None
            fig.layout.shapes = _window_shapes(
                t0_s=None if rect_window is None else rect_window[0],
                t1_s=None if rect_window is None else rect_window[1],
                selected_time_s=selected_time if current.get("session_key") == str(w_session.value) else None,
            )
            fig.layout.xaxis.rangeslider.visible = False
            fig.layout.plot_bgcolor = "#ffffff"
            fig.layout.paper_bgcolor = "#ffffff"

            state["selection_sync_active"] = True
            try:
                if current_window is not None:
                    fig.layout.xaxis.range = [float(current_window[0]), float(current_window[1])]
                else:
                    fig.layout.xaxis.range = None
            finally:
                state["selection_sync_active"] = False

        w_speed_legend.value = _speed_legend_html(bins) if color_by_speed else ""
        w_source.value = (
            f"<span style='color:#666;'>Source stream: <code>{gps_view.source_stream_name}</code></span>"
        )
        if has_altitude_trace:
            _set_status("GPS route and altitude loaded.")
        else:
            _set_status("GPS route loaded, but no altitude samples are available for plotting.")

    def _refresh_map(*, fit_bounds_to_route: bool = False) -> None:
        gps_view = state.get("gps_view")
        segment_df = state.get("segment_df")
        if not isinstance(gps_view, GPSViewData) or gps_view.route_df.empty:
            _replace_route_group(
                "route_layer",
                runs=(),
                color=_INACTIVE_ROUTE_COLOR,
                weight=4,
                opacity=0.9,
            )
            _replace_route_group(
                "window_layer",
                runs=(),
                color=_DEFAULT_ROUTE_COLOR,
                weight=6,
                opacity=1.0,
            )
            point_marker.radius = 0
            return

        route_runs, _ = build_line_runs_from_segments(
            segment_df,
            color_by_speed=False,
            default_color=_INACTIVE_ROUTE_COLOR,
        )
        _replace_route_group(
            "route_layer",
            runs=route_runs,
            color=_INACTIVE_ROUTE_COLOR,
            weight=4,
            opacity=0.75,
        )

        current = _selection_snapshot()
        active_segments = segment_df
        if current.get("session_key") == str(w_session.value):
            candidate = subset_segments_by_window(
                segment_df,
                t0_s=current.get("window_t0_s"),
                t1_s=current.get("window_t1_s"),
            )
            if not candidate.empty:
                active_segments = candidate

        if active_segments.empty:
            _replace_route_group(
                "window_layer",
                runs=(),
                color=_DEFAULT_ROUTE_COLOR,
                weight=6,
                opacity=1.0,
            )
        else:
            window_runs, _ = build_line_runs_from_segments(
                active_segments,
                color_by_speed=bool(w_color_by_speed.value),
                default_color=_DEFAULT_ROUTE_COLOR,
            )
            _replace_route_group(
                "window_layer",
                runs=window_runs,
                color=_DEFAULT_ROUTE_COLOR,
                weight=6,
                opacity=1.0,
            )

        selected_time = current.get("selected_time_s") if current.get("session_key") == str(w_session.value) else None
        point = nearest_route_point(gps_view.route_df, time_s=selected_time)
        if point is None:
            point_marker.radius = 0
        else:
            point_marker.location = (float(point["latitude_deg"]), float(point["longitude_deg"]))
            point_marker.radius = 7

        if fit_bounds_to_route:
            bounds = route_bounds(gps_view.route_df)
            if bounds is not None:
                center = _fallback_center_from_bounds(bounds)
                zoom = _fallback_zoom_from_bounds(bounds)
                if center is not None:
                    map_widget.center = center
                if zoom is not None:
                    map_widget.zoom = zoom
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    pass
                else:
                    map_widget.fit_bounds(bounds)

    def _refresh_selection_overlays() -> None:
        _refresh_map(fit_bounds_to_route=False)
        _refresh_altitude_plot()

    def _load_session(session_key: str, *, fit_bounds_to_route: bool = False) -> None:
        sess = session_loader(str(session_key))
        state["session"] = sess
        gps_view = extract_gps_view_data(
            sess,
            session_key=str(session_key),
            preferred_stream_name=preferred_stream_name,
            time_col=time_col,
        )
        state["gps_view"] = gps_view
        state["segment_df"] = build_route_segments(gps_view.route_df) if isinstance(gps_view, GPSViewData) else pd.DataFrame()

        if gps_view is None:
            _clear_visuals("This session does not contain GPS/FIT position data.")
            return

        snap = _selection_snapshot()
        route_t = pd.to_numeric(gps_view.route_df["time_s"], errors="coerce").to_numpy(dtype=float)
        route_t = route_t[np.isfinite(route_t)]
        default_window = None
        if route_t.size:
            default_window = (float(np.min(route_t)), float(np.max(route_t)))

        if snap.get("session_key") != str(session_key):
            _set_selection(
                session_key=str(session_key),
                window=default_window,
                selected_time_s=None,
                set_selected_time=True,
            )
        elif snap.get("window_t0_s") is None or snap.get("window_t1_s") is None:
            _set_selection(session_key=str(session_key), window=default_window)

        _refresh_map(fit_bounds_to_route=fit_bounds_to_route)
        _refresh_altitude_plot()

    def _on_session_change(*_args: Any) -> None:
        if state["updating"]:
            return
        state["updating"] = True
        try:
            _load_session(str(w_session.value), fit_bounds_to_route=True)
        finally:
            state["updating"] = False

    def _on_basemap_change(*_args: Any) -> None:
        _apply_basemap()

    def _on_map_height_change(change: Mapping[str, Any]) -> None:
        if change.get("new") is None:
            return
        _set_map_height(int(change["new"]))

    def _on_style_change(*_args: Any) -> None:
        _refresh_selection_overlays()

    def _on_altitude_range_change(_layout: Any, xrange: Any) -> None:
        if state["selection_sync_active"]:
            return
        if xrange is None or len(xrange) != 2 or xrange[0] is None or xrange[1] is None:
            window = _current_window_from_fig()
            if window is None:
                return
            _set_selection(session_key=str(w_session.value), window=window)
            return
        try:
            _set_selection(
                session_key=str(w_session.value),
                window=(float(xrange[0]), float(xrange[1])),
            )
        except Exception:
            return

    def _on_selection_model_change(change: Mapping[str, Any]) -> None:
        if state["selection_sync_active"]:
            return
        if str(change.get("owner").source or "") == _GPS_BROWSER_SOURCE:
            return

        current_session = str(w_session.value)
        target_session = selection.session_key
        if isinstance(target_session, str) and target_session in set(map(str, w_session.options)) and target_session != current_session:
            state["updating"] = True
            try:
                w_session.value = target_session
            finally:
                state["updating"] = False
            _load_session(str(w_session.value), fit_bounds_to_route=True)
            return

        if selection.session_key == current_session:
            _refresh_selection_overlays()

    w_session.observe(_on_session_change, names="value")
    w_basemap.observe(_on_basemap_change, names="value")
    w_map_height.observe(_on_map_height_change, names="value")
    w_color_by_speed.observe(_on_style_change, names="value")
    fig.layout.on_change(_on_altitude_range_change, ("xaxis", "range"))
    for trait_name in ("session_key", "window_t0_s", "window_t1_s", "selected_time_s"):
        selection.observe(_on_selection_model_change, names=trait_name)

    controls_children = [w_basemap, w_map_height, w_color_by_speed]
    if show_session_control:
        controls_children.insert(0, w_session)
    controls = W.HBox(controls_children)
    map_box = W.VBox([W.HTML("<b>Route map</b>"), map_widget], layout=W.Layout(width="50%"))
    chart_box = W.VBox([W.HTML("<b>Altitude over time</b>"), fig], layout=W.Layout(width="50%"))
    root = W.VBox(
        [
            controls,
            w_status,
            w_source,
            w_speed_legend,
            W.HBox([map_box, chart_box], layout=W.Layout(width="100%")),
        ],
        layout=W.Layout(width="100%"),
    )

    _load_session(str(w_session.value), fit_bounds_to_route=True)
    _set_map_height(int(w_map_height.value))

    if auto_display:
        display(root)

    return {
        "root": root,
        "state": state,
        "refresh": lambda: _load_session(str(w_session.value), fit_bounds_to_route=False),
        "controls": {
            "session": w_session,
            "basemap": w_basemap,
            "map_height": w_map_height,
            "color_by_speed": w_color_by_speed,
        },
        "selection_model": selection,
        "fig": fig,
        "map": map_widget,
    }


def make_gps_browser_rebuilder(
    *,
    sel: SessionSelectorHandle,
    out: Optional[W.Output] = None,
    selection_model: Optional[SessionTimeSelection] = None,
    preferred_stream_name: str = "gps_fit",
    time_col: str = "time_s",
    **kwargs: Any,
) -> RebuilderHandle:
    if out is None:
        out = W.Output()

    state: Dict[str, Any] = {
        "handles": None,
        "selection_model": selection_model or make_session_time_selection(),
    }

    def rebuild() -> None:
        from bodaqs_analysis.widgets.loaders import make_session_loader

        snapshot = selection_snapshot_from_handle(sel)
        key_to_ref = snapshot.key_to_ref
        if not key_to_ref:
            with out:
                clear_output(wait=True)
                print("No sessions available for the current selector scope.")
            state["handles"] = None
            return

        session_loader = make_session_loader(store=sel["store"], key_to_ref=key_to_ref)
        with out:
            clear_output(wait=True)
            state["handles"] = make_gps_browser_widget_for_loader(
                session_keys=sorted(map(str, key_to_ref.keys())),
                session_loader=session_loader,
                selection_model=state["selection_model"],
                preferred_stream_name=preferred_stream_name,
                time_col=time_col,
                auto_display=False,
                **kwargs,
            )
            root = state["handles"].get("root") or state["handles"].get("ui")
            if root is not None:
                display(root)

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}
