from __future__ import annotations

import numpy as np
import pandas as pd

from bodaqs_analysis.widgets.metric_scatter_widget import (
    build_metric_scatter_series,
    fit_metric_scatter_line,
    format_metric_scatter_line,
    filter_metric_scatter_base_df,
    prepare_metric_scatter_consumer_data,
)


def test_prepare_metric_scatter_consumer_data_uses_registry_sensor_fallback() -> None:
    events_df = pd.DataFrame(
        [
            {
                "session_key": "run_a::sess_1",
                "event_id": "compressions_all>25:front_shock:0",
                "schema_id": "compressions_all>25",
                "signal_col": "front_shock_vel_dom_suspension [mm/s]",
                "entity_key": "entity_a",
            },
            {
                "session_key": "run_a::sess_1",
                "event_id": "compressions_all>25:rear_shock:0",
                "schema_id": "compressions_all>25",
                "signal_col": "rear_shock_vel_dom_suspension [mm/s]",
                "entity_key": "entity_a",
            },
        ]
    )
    metrics_df = pd.DataFrame(
        [
            {
                "session_key": "run_a::sess_1",
                "event_id": "compressions_all>25:front_shock:0",
                "schema_id": "compressions_all>25",
                "m_peak_disp_max": 31.5,
                "m_interval_vel_min": -128.0,
            },
            {
                "session_key": "run_a::sess_1",
                "event_id": "compressions_all>25:rear_shock:0",
                "schema_id": "compressions_all>25",
                "m_peak_disp_max": 24.0,
                "m_interval_vel_min": -91.0,
            },
        ]
    )

    def session_loader(session_key: str) -> dict[str, object]:
        assert session_key == "run_a::sess_1"
        return {
            "df": pd.DataFrame(),
            "meta": {
                "signals": {
                    "front_shock_vel_dom_suspension [mm/s]": {"end": "front"},
                    "rear_shock_vel_dom_suspension [mm/s]": {"end": "rear"},
                }
            },
        }

    data = prepare_metric_scatter_consumer_data(
        events_df=events_df,
        metrics_df=metrics_df,
        session_keys=["run_a::sess_1"],
        session_loader=session_loader,
        schema=None,
        require_schema=False,
    )

    assert data["scope_entity_col"] == "entity_key"
    assert data["event_types"] == ["compressions_all>25"]
    assert data["sensors"] == ["front", "rear"]

    front_series = build_metric_scatter_series(
        viz_df=data["viz_df"],
        event_type_col="schema_id",
        scope_entity_col=data["scope_entity_col"],
        event_value="compressions_all>25",
        entity_values=["entity_a"],
        sensor_values=["front"],
        x_metric="m_peak_disp_max",
        y_metric="m_interval_vel_min",
    )
    assert len(front_series) == 1
    assert np.array_equal(front_series[0].x, np.array([31.5]))
    assert np.array_equal(front_series[0].y, np.array([-128.0]))


def test_metric_scatter_filters_by_signal_semantics() -> None:
    events_df = pd.DataFrame(
        [
            {
                "session_key": "run_a::sess_1",
                "event_id": "compressions_all>25:front_shock:0",
                "schema_id": "compressions_all>25",
                "signal_col": "front_shock_vel_dom_suspension [mm/s]",
                "entity_key": "entity_a",
            },
            {
                "session_key": "run_a::sess_1",
                "event_id": "compressions_all>25:rear_shock:0",
                "schema_id": "compressions_all>25",
                "signal_col": "rear_shock_vel_dom_suspension [mm/s]",
                "entity_key": "entity_a",
            },
        ]
    )
    metrics_df = pd.DataFrame(
        [
            {
                "session_key": "run_a::sess_1",
                "event_id": "compressions_all>25:front_shock:0",
                "schema_id": "compressions_all>25",
                "m_peak_disp_max": 31.5,
                "m_interval_vel_max": 128.0,
            },
            {
                "session_key": "run_a::sess_1",
                "event_id": "compressions_all>25:rear_shock:0",
                "schema_id": "compressions_all>25",
                "m_peak_disp_max": 24.0,
                "m_interval_vel_max": 91.0,
            },
        ]
    )

    def session_loader(session_key: str) -> dict[str, object]:
        assert session_key == "run_a::sess_1"
        return {
            "df": pd.DataFrame(),
            "meta": {
                "signals": {
                    "front_shock_vel_dom_suspension [mm/s]": {
                        "sensor": "front_shock",
                        "end": "front",
                        "domain": "suspension",
                        "quantity": "vel",
                        "unit": "mm/s",
                    },
                    "rear_shock_vel_dom_suspension [mm/s]": {
                        "sensor": "rear_shock",
                        "end": "rear",
                        "domain": "suspension",
                        "quantity": "vel",
                        "unit": "mm/s",
                    },
                }
            },
        }

    data = prepare_metric_scatter_consumer_data(
        events_df=events_df,
        metrics_df=metrics_df,
        session_keys=["run_a::sess_1"],
        session_loader=session_loader,
        schema=None,
        require_schema=False,
    )

    rear_selector = {"end": "rear", "domain": "suspension"}
    base = filter_metric_scatter_base_df(
        viz_df=data["viz_df"],
        event_type_col="schema_id",
        scope_entity_col=data["scope_entity_col"],
        event_value="compressions_all>25",
        entity_values=["entity_a"],
        signal_selectors=[rear_selector],
    )
    assert base["event_id"].tolist() == ["compressions_all>25:rear_shock:0"]

    series = build_metric_scatter_series(
        viz_df=data["viz_df"],
        event_type_col="schema_id",
        scope_entity_col=data["scope_entity_col"],
        event_value="compressions_all>25",
        entity_values=["entity_a"],
        signal_selectors=[rear_selector],
        x_metric="m_peak_disp_max",
        y_metric="m_interval_vel_max",
    )
    assert len(series) == 1
    assert np.array_equal(series[0].x, np.array([24.0]))
    assert np.array_equal(series[0].y, np.array([91.0]))


def test_fit_metric_scatter_line_and_format() -> None:
    fit = fit_metric_scatter_line(
        np.array([1.0, 2.0, 3.0], dtype=float),
        np.array([3.0, 5.0, 7.0], dtype=float),
    )

    assert fit is not None
    assert np.isclose(fit.slope, 2.0)
    assert np.isclose(fit.intercept, 1.0)
    assert np.isclose(fit.r_squared, 1.0)
    assert format_metric_scatter_line(fit) == "y = 2 x + 1"
