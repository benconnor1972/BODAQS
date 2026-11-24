import ipywidgets as W
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

pytest.importorskip("ipyleaflet")

from bodaqs_analysis.artifacts import ArtifactStore, save_session_artifacts
from bodaqs_analysis.dashboards.gps_browser import make_session_gps_dashboard
from bodaqs_analysis.widgets.contracts import RUN_ID_COL, SESSION_ID_COL, SESSION_KEY_COL
from bodaqs_analysis.widgets.gps_browser_widget import make_gps_browser_widget_for_loader
from bodaqs_analysis.widgets.gps_data import (
    build_line_runs_from_segments,
    build_route_segments,
    build_speed_color_bins,
    extract_gps_view_data,
    nearest_route_point,
    subset_segments_by_window,
)
from bodaqs_analysis.widgets.session_window_browser_widget import make_session_window_browser_rebuilder
from bodaqs_analysis.widgets.session_window_plot import init_session_window_figure
from bodaqs_analysis.widgets.time_selection import make_session_time_selection


def _make_session_with_gps() -> dict:
    primary_df = pd.DataFrame(
        {
            "time_s": np.array([0.0, 0.5, 1.0, 1.5, 2.0]),
            "gps_fit_altitude_dom_world [m]": np.array([100.0, 101.0, 102.0, 103.0, 104.0]),
            "gps_fit_speed_dom_world [m/s]": np.array([2.0, 2.5, 3.0, 3.5, 4.0]),
        }
    )
    gps_df = pd.DataFrame(
        {
            "time_s": np.array([0.25, 0.75, 1.25, 1.75]),
            "gps_fit_position_latitude_dom_world [deg]": np.array([-31.95, -31.951, -31.952, -31.953]),
            "gps_fit_position_longitude_dom_world [deg]": np.array([115.86, 115.861, 115.862, 115.863]),
        }
    )
    return {"df": primary_df, "stream_dfs": {"gps_fit": gps_df}, "meta": {}}


def test_extract_gps_view_data_fills_altitude_and_speed_from_primary():
    session = _make_session_with_gps()

    gps_view = extract_gps_view_data(session, session_key="sess_1")

    assert gps_view is not None
    assert gps_view.session_key == "sess_1"
    assert gps_view.source_stream_name == "gps_fit"
    assert np.allclose(gps_view.route_df["altitude_m"].to_numpy(), np.array([100.5, 101.5, 102.5, 103.5]))
    assert np.allclose(gps_view.route_df["speed_mps"].to_numpy(), np.array([2.25, 2.75, 3.25, 3.75]))


def test_extract_gps_view_data_clamps_fit_route_to_primary_session_bounds():
    session = _make_session_with_gps()
    session["stream_dfs"]["gps_fit"] = pd.DataFrame(
        {
            "time_s": np.array([-0.5, 0.25, 0.75, 1.25, 1.75, 2.5]),
            "gps_fit_position_latitude_dom_world [deg]": np.array(
                [-31.949, -31.95, -31.951, -31.952, -31.953, -31.954]
            ),
            "gps_fit_position_longitude_dom_world [deg]": np.array(
                [115.859, 115.86, 115.861, 115.862, 115.863, 115.864]
            ),
        }
    )

    gps_view = extract_gps_view_data(session, session_key="sess_1")

    assert gps_view is not None
    assert np.allclose(gps_view.route_df["time_s"].to_numpy(), np.array([0.25, 0.75, 1.25, 1.75]))
    assert np.allclose(
        gps_view.route_df["latitude_deg"].to_numpy(),
        np.array([-31.95, -31.951, -31.952, -31.953]),
    )


def test_route_segmentation_helpers_support_speed_coloring_and_window_queries():
    gps_view = extract_gps_view_data(_make_session_with_gps(), session_key="sess_1")
    assert gps_view is not None

    segment_df = build_route_segments(gps_view.route_df)
    runs, bins = build_line_runs_from_segments(segment_df, color_by_speed=True, n_bins=3)
    subset = subset_segments_by_window(segment_df, t0_s=0.8, t1_s=1.1)
    point = nearest_route_point(gps_view.route_df, time_s=1.1)

    assert len(segment_df.index) == 3
    assert len(runs) >= 1
    assert [item.label for item in bins] == [
        "0-10 km/h",
        "10-20 km/h",
        "20-30 km/h",
        "30-40 km/h",
        "40+ km/h",
    ]
    assert len(subset.index) == 1
    assert point is not None
    assert point["time_s"] == pytest.approx(1.25)


def test_build_speed_color_bins_uses_fixed_kmh_ranges():
    bins = build_speed_color_bins(np.array([0.5, 4.5, 7.5, 10.5, 13.5]))

    assert [item.label for item in bins] == [
        "0-10 km/h",
        "10-20 km/h",
        "20-30 km/h",
        "30-40 km/h",
        "40+ km/h",
    ]
    assert [item.color for item in bins] == [
        "#22c55e",
        "#84cc16",
        "#facc15",
        "#fb923c",
        "#ef4444",
    ]
    assert bins[0].lower_mps == pytest.approx(0.0)
    assert bins[0].upper_mps == pytest.approx(10.0 / 3.6)
    assert bins[-1].lower_mps == pytest.approx(40.0 / 3.6)
    assert np.isinf(bins[-1].upper_mps)


def test_session_window_figure_uses_compact_grey_rangeslider_and_white_background():
    fig = go.FigureWidget()

    init_session_window_figure(fig)

    assert fig.layout.xaxis.rangeslider.visible is True
    assert fig.layout.xaxis.rangeslider.thickness == pytest.approx(0.105)
    assert fig.layout.xaxis.rangeslider.bgcolor == "#d1d5db"
    assert fig.layout.xaxis.showline is True
    assert fig.layout.xaxis.mirror is True
    assert fig.layout.xaxis.linecolor == "#9ca3af"
    assert fig.layout.yaxis.showline is True
    assert fig.layout.yaxis.mirror is True
    assert fig.layout.yaxis.linecolor == "#9ca3af"
    assert fig.layout.plot_bgcolor == "#ffffff"
    assert fig.layout.paper_bgcolor == "#ffffff"


def test_gps_browser_widget_responds_to_shared_selection_updates():
    session = _make_session_with_gps()
    selection = make_session_time_selection()

    handle = make_gps_browser_widget_for_loader(
        session_keys=["sess_1"],
        session_loader=lambda session_key: session,
        selection_model=selection,
        auto_display=False,
    )

    selection.update_state(
        session_key="sess_1",
        window_t0_s=0.5,
        window_t1_s=1.5,
        selected_time_s=1.1,
        set_selected_time=True,
        source="test_case",
    )

    assert list(handle["fig"].layout.xaxis.range) == [0.5, 1.5]
    assert handle["state"]["point_marker"].radius == 7
    assert handle["state"]["window_layer"].layers
    assert any(getattr(shape, "type", None) == "rect" for shape in handle["fig"].layout.shapes)


def test_gps_browser_widget_initial_map_view_tracks_route_bounds_and_speed_toggle_rebuilds_layer():
    session = _make_session_with_gps()

    handle = make_gps_browser_widget_for_loader(
        session_keys=["sess_1"],
        session_loader=lambda session_key: session,
        auto_display=False,
    )

    route_layer_initial = handle["state"]["route_layer"]
    window_layer_initial = handle["state"]["window_layer"]
    route_colors_initial = {str(getattr(layer, "color", "")) for layer in route_layer_initial.layers}
    window_colors_initial = {str(getattr(layer, "color", "")) for layer in window_layer_initial.layers}
    assert handle["map"].center[0] == pytest.approx(-31.9515)
    assert handle["map"].center[1] == pytest.approx(115.8615)
    assert handle["map"].zoom > 2
    assert handle["controls"]["basemap"].value == "OpenStreetMap"
    assert handle["fig"].layout.xaxis.rangeslider.visible is False
    assert handle["fig"].layout.hovermode == "closest"
    assert handle["fig"].layout.plot_bgcolor == "#ffffff"
    assert handle["fig"].layout.paper_bgcolor == "#ffffff"
    assert handle["fig"].layout.xaxis.showline is True
    assert handle["fig"].layout.xaxis.mirror is True
    assert handle["fig"].layout.yaxis.showline is True
    assert handle["fig"].layout.yaxis.mirror is True
    assert not handle["fig"].layout.shapes
    assert handle["fig"].data[0].line.width == pytest.approx(2.8)
    assert handle["fig"].data[0].hovertemplate == "time: %{x:.1f}s<br>speed: %{customdata:.1f} km/h<extra></extra>"
    assert route_colors_initial == {"#9ca3af"}
    assert len(window_colors_initial) > 1

    handle["controls"]["color_by_speed"].value = False
    route_layer_plain = handle["state"]["route_layer"]
    window_layer_plain = handle["state"]["window_layer"]
    route_colors_plain = {str(getattr(layer, "color", "")) for layer in route_layer_plain.layers}
    window_colors_plain = {str(getattr(layer, "color", "")) for layer in window_layer_plain.layers}
    assert route_layer_plain is not route_layer_initial
    assert route_colors_plain == {"#9ca3af"}
    assert window_colors_plain == {"#2563eb"}

    handle["controls"]["color_by_speed"].value = True
    route_layer_color = handle["state"]["route_layer"]
    window_layer_color = handle["state"]["window_layer"]
    route_colors_color = {str(getattr(layer, "color", "")) for layer in route_layer_color.layers}
    window_colors_color = {str(getattr(layer, "color", "")) for layer in window_layer_color.layers}
    assert route_layer_color is not route_layer_plain
    assert route_colors_color == {"#9ca3af"}
    assert len(window_colors_color) > 1

    handle["controls"]["map_height"].value = 560
    assert handle["map"].layout.height == "560px"


def test_session_gps_dashboard_builds_for_selector_scope(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    session_key = "run_test::session_001"

    save_session_artifacts(
        store,
        run_id="run_test",
        session_id="session_001",
        session_df=pd.DataFrame(
            {
                "time_s": np.array([0.0, 0.5, 1.0, 1.5]),
                "gps_fit_altitude_dom_world [m]": np.array([100.0, 101.0, 102.0, 103.0]),
                "gps_fit_speed_dom_world [m/s]": np.array([2.0, 2.5, 3.0, 3.5]),
            }
        ),
        session_meta={"signals": {}, "streams": {"primary": {"time_col": "time_s"}}},
        secondary_stream_dfs={
            "gps_fit": pd.DataFrame(
                {
                    "time_s": np.array([0.25, 0.75, 1.25]),
                    "gps_fit_position_latitude_dom_world [deg]": np.array([-31.95, -31.951, -31.952]),
                    "gps_fit_position_longitude_dom_world [deg]": np.array([115.86, 115.861, 115.862]),
                    "gps_fit_altitude_dom_world [m]": np.array([100.5, 101.5, 102.5]),
                    "gps_fit_speed_dom_world [m/s]": np.array([2.25, 2.75, 3.25]),
                }
            )
        },
        secondary_stream_meta={"gps_fit": {"kind": "intermittent", "stream_name": "gps_fit"}},
    )

    selector_scope = pd.DataFrame(
        [{SESSION_KEY_COL: session_key, RUN_ID_COL: "run_test", SESSION_ID_COL: "session_001"}]
    )
    refresh_signal = W.Text(value="initial")
    sel = {
        "store": store,
        "refresh_signal": refresh_signal,
        "get_key_to_ref": lambda: {session_key: ("run_test", "session_001")},
        "get_events_index_df": lambda: selector_scope.copy(),
        "get_selected": lambda: [],
    }

    dashboard = make_session_gps_dashboard(sel, auto_display=False)

    assert dashboard["ui"] is not None
    assert len(dashboard["ui"].children) == 3
    assert dashboard["selection_model"].session_key == session_key
    assert dashboard["widgets"]["session_browser"]["state"]["handles"] is not None
    assert dashboard["widgets"]["gps_browser"]["state"]["handles"] is not None
    assert dashboard["widgets"]["gps_browser"]["state"]["handles"]["controls"]["session"].layout.display == "none"
    assert dashboard["widgets"]["gps_browser"]["state"]["handles"]["fig"].layout.xaxis.rangeslider.visible is False
    assert not dashboard["widgets"]["gps_browser"]["state"]["handles"]["fig"].layout.shapes

    dashboard["detach"]()


def test_session_window_browser_resets_to_full_range_on_session_change(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    session_key_a = "run_test::session_001"
    session_key_b = "run_test::session_002"

    save_session_artifacts(
        store,
        run_id="run_test",
        session_id="session_001",
        session_df=pd.DataFrame({"time_s": np.array([0.0, 1.0, 2.0]), "sig_a": np.array([1.0, 2.0, 3.0])}),
        session_meta={"signals": {}, "streams": {"primary": {"time_col": "time_s"}}},
    )
    save_session_artifacts(
        store,
        run_id="run_test",
        session_id="session_002",
        session_df=pd.DataFrame({"time_s": np.array([10.0, 12.0, 14.0]), "sig_a": np.array([4.0, 5.0, 6.0])}),
        session_meta={"signals": {}, "streams": {"primary": {"time_col": "time_s"}}},
    )

    selector_scope = pd.DataFrame(
        [
            {SESSION_KEY_COL: session_key_a, RUN_ID_COL: "run_test", SESSION_ID_COL: "session_001"},
            {SESSION_KEY_COL: session_key_b, RUN_ID_COL: "run_test", SESSION_ID_COL: "session_002"},
        ]
    )
    refresh_signal = W.Text(value="initial")
    sel = {
        "store": store,
        "refresh_signal": refresh_signal,
        "get_key_to_ref": lambda: {
            session_key_a: ("run_test", "session_001"),
            session_key_b: ("run_test", "session_002"),
        },
        "get_events_index_df": lambda: selector_scope.copy(),
        "get_selected": lambda: [],
    }

    rb = make_session_window_browser_rebuilder(sel=sel)
    handle = rb["state"]["handles"]
    assert handle is not None

    handle["fig"].layout.xaxis.range = [0.5, 1.5]
    handle["controls"]["session"].value = session_key_b

    assert list(handle["fig"].layout.xaxis.range) == [10.0, 14.0]


def test_session_gps_dashboard_formats_as_widget_mimebundle(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    session_key = "run_test::session_001"

    save_session_artifacts(
        store,
        run_id="run_test",
        session_id="session_001",
        session_df=pd.DataFrame(
            {
                "time_s": np.array([0.0, 0.5, 1.0]),
                "gps_fit_altitude_dom_world [m]": np.array([100.0, 101.0, 102.0]),
                "gps_fit_speed_dom_world [m/s]": np.array([2.0, 2.5, 3.0]),
            }
        ),
        session_meta={"signals": {}, "streams": {"primary": {"time_col": "time_s"}}},
        secondary_stream_dfs={
            "gps_fit": pd.DataFrame(
                {
                    "time_s": np.array([0.25, 0.75]),
                    "gps_fit_position_latitude_dom_world [deg]": np.array([-31.95, -31.951]),
                    "gps_fit_position_longitude_dom_world [deg]": np.array([115.86, 115.861]),
                    "gps_fit_altitude_dom_world [m]": np.array([100.5, 101.5]),
                    "gps_fit_speed_dom_world [m/s]": np.array([2.25, 2.75]),
                }
            )
        },
        secondary_stream_meta={"gps_fit": {"kind": "intermittent", "stream_name": "gps_fit"}},
    )

    selector_scope = pd.DataFrame(
        [{SESSION_KEY_COL: session_key, RUN_ID_COL: "run_test", SESSION_ID_COL: "session_001"}]
    )
    sel = {
        "store": store,
        "refresh_signal": W.Text(value="initial"),
        "get_key_to_ref": lambda: {session_key: ("run_test", "session_001")},
        "get_events_index_df": lambda: selector_scope.copy(),
        "get_selected": lambda: [],
    }

    dashboard = make_session_gps_dashboard(sel, auto_display=False)
    bundle, _metadata = dashboard._repr_mimebundle_()

    assert "application/vnd.jupyter.widget-view+json" in bundle

    dashboard["detach"]()
