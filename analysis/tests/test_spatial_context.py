import copy
import copy
import json

import numpy as np
import pandas as pd
import pytest

from bodaqs_analysis.artifacts import ArtifactStore, save_session_artifacts
from bodaqs_analysis.dashboards.spatial_context import (
    make_spatial_context_figure,
    spatial_selection_to_time_ranges,
)
from bodaqs_analysis.pipeline import preprocess_resolved
from bodaqs_analysis.preprocess_profile import default_preprocess_config, validate_preprocess_config
from bodaqs_analysis.spatial_context import (
    DEFAULT_SPATIAL_CONTEXT_CONFIG,
    DEFAULT_SPATIAL_CONTEXT_TRACK_SCOPE_CONFIG,
    SPATIAL_CONTEXT_STREAM_NAME,
    derive_spatial_context,
    materialize_spatial_context,
    scope_spatial_context_to_track,
)
from bodaqs_analysis.track_traversal import match_track_traversals


def _gps_registry(*, include_distance: bool = True) -> dict:
    entries = {
        "latitude_deg": {
            "quantity": "position_latitude",
            "unit": "deg",
            "domain": "world",
            "sensor": "gps_fit",
            "source": "fit",
        },
        "longitude_deg": {
            "quantity": "position_longitude",
            "unit": "deg",
            "domain": "world",
            "sensor": "gps_fit",
            "source": "fit",
        },
        "altitude_m": {
            "quantity": "altitude",
            "unit": "m",
            "domain": "world",
            "sensor": "gps_fit",
            "source": "fit",
        },
    }
    if include_distance:
        entries["distance_m"] = {
            "quantity": "distance",
            "unit": "m",
            "domain": "world",
            "sensor": "gps_fit",
            "source": "fit",
        }
    return entries


def _spatial_config(**overrides) -> dict:
    config = copy.deepcopy(DEFAULT_SPATIAL_CONTEXT_CONFIG)
    config["enabled"] = True
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def _straight_session(
    *,
    speed_mps: float = 5.0,
    duration_s: float = 20.0,
    primary_rate_hz: float = 200.0,
    gps_rate_hz: float = 10.0,
    include_recorded_distance: bool = True,
    include_front: bool = True,
    include_rear_wheel: bool = True,
    include_rear_shock: bool = False,
) -> dict:
    primary_time = np.arange(0.0, duration_s + 0.5 / primary_rate_hz, 1.0 / primary_rate_hz)
    primary_distance = primary_time * speed_mps
    primary_data = {
        "time_s": primary_time,
        "active_mask_qc": np.ones(primary_time.shape, dtype=bool),
    }
    signals = {}
    if include_front:
        column = "front_wheel_disp_dom_wheel [mm]"
        primary_data[column] = 10.0 * np.sin(2.0 * np.pi * primary_distance / 1.0)
        signals[column] = {
            "end": "front",
            "quantity": "disp",
            "domain": "wheel",
            "unit": "mm",
            "processing_role": "primary_analysis",
            "derivation": {"method": "test_lowpass"},
        }
    if include_rear_wheel:
        column = "rear_wheel_disp_dom_wheel [mm]"
        primary_data[column] = 8.0 * np.sin(2.0 * np.pi * primary_distance / 1.0)
        signals[column] = {
            "end": "rear",
            "quantity": "disp",
            "domain": "wheel",
            "unit": "mm",
            "processing_role": "primary_analysis",
            "derivation": {"method": "test_lowpass"},
        }
    if include_rear_shock:
        column = "rear_shock_disp_dom_suspension [mm]"
        primary_data[column] = 4.0 * np.sin(2.0 * np.pi * primary_distance / 1.0)
        signals[column] = {
            "end": "rear",
            "quantity": "disp",
            "domain": "suspension",
            "unit": "mm",
            "processing_role": "primary_analysis",
        }

    gps_time = np.arange(0.0, duration_s + 0.5 / gps_rate_hz, 1.0 / gps_rate_hz)
    distance = gps_time * speed_mps
    latitude_origin = -31.95
    longitude_origin = 115.85
    latitude = np.full(gps_time.shape, latitude_origin)
    longitude = longitude_origin + np.degrees(
        distance / (6_371_000.0 * np.cos(np.radians(latitude_origin)))
    )
    gps_data = {
        "time_s": gps_time,
        "latitude_deg": latitude,
        "longitude_deg": longitude,
        "altitude_m": 200.0 + 0.1 * distance,
    }
    if include_recorded_distance:
        gps_data["distance_m"] = distance

    return {
        "session_id": "spatial-test",
        "source": {"type": "unit"},
        "df": pd.DataFrame(primary_data),
        "meta": {
            "signals": signals,
            "secondary_streams": {
                "gps_fit": {
                    "channel_info": _gps_registry(include_distance=include_recorded_distance),
                    "source_kind": "fit_enrichment",
                    "time_col": "time_s",
                }
            },
            "gps_sources": {"preferred_source": "gps_fit"},
        },
        "stream_dfs": {"gps_fit": pd.DataFrame(gps_data)},
        "qc": {"activity_mask": {"policy": "test_activity", "version": 1}},
    }


def test_spatial_context_derives_recorded_distance_gradient_and_native_rate_activity() -> None:
    result = derive_spatial_context(_straight_session(), _spatial_config())

    assert result.stream_meta["status"] == "succeeded"
    assert result.stream_meta["distance_source"]["selected"]["candidate_kind"] == "recorded_gps_or_fit_distance"
    assert result.stream_df["distance_m"].is_monotonic_increasing
    assert result.stream_df["distance_m"].is_unique
    assert np.nanmedian(result.stream_df["gradient_fraction"]) == pytest.approx(0.1, abs=1.0e-6)
    assert np.nanmedian(result.stream_df["front_suspension_activity"]) == pytest.approx(0.04, rel=0.03)
    assert np.nanmedian(result.stream_df["rear_suspension_activity"]) == pytest.approx(0.032, rel=0.03)
    provenance = result.stream_meta["metric_provenance"]["front_suspension_activity"]
    assert provenance["method"] == "native_rate_absolute_movement_per_ground_distance"
    assert provenance["activity_mask"]["policy"] == "test_activity"


def test_activity_per_distance_is_approximately_speed_invariant() -> None:
    slow = derive_spatial_context(
        _straight_session(speed_mps=5.0, duration_s=20.0),
        _spatial_config(gradient={"enabled": False}, twistiness={"enabled": False}),
    )
    fast = derive_spatial_context(
        _straight_session(speed_mps=10.0, duration_s=10.0),
        _spatial_config(gradient={"enabled": False}, twistiness={"enabled": False}),
    )

    slow_activity = float(np.nanmedian(slow.stream_df["front_suspension_activity"]))
    fast_activity = float(np.nanmedian(fast.stream_df["front_suspension_activity"]))
    assert fast_activity == pytest.approx(slow_activity, rel=0.03)


def test_activity_uses_native_rate_motion_before_spatial_grid_coarsening() -> None:
    fine = derive_spatial_context(
        _straight_session(),
        _spatial_config(
            distance={"grid_interval_m": 0.5},
            gradient={"enabled": False},
            twistiness={"enabled": False},
        ),
    )
    coarse = derive_spatial_context(
        _straight_session(),
        _spatial_config(
            distance={"grid_interval_m": 2.0},
            gradient={"enabled": False},
            twistiness={"enabled": False},
        ),
    )

    assert np.nanmedian(coarse.stream_df["front_suspension_activity"]) == pytest.approx(
        np.nanmedian(fine.stream_df["front_suspension_activity"]),
        rel=0.03,
    )


def test_gps_geometry_fallback_is_used_without_recorded_distance() -> None:
    result = derive_spatial_context(
        _straight_session(include_recorded_distance=False),
        _spatial_config(),
    )

    assert result.stream_meta["distance_source"]["selected"]["candidate_kind"] == "gps_geometry"
    evaluations = result.stream_meta["distance_source"]["evaluated_candidates"]
    assert evaluations[0]["reason"] == "recorded_distance_unavailable"
    assert np.nanmedian(result.stream_df["gradient_fraction"]) == pytest.approx(0.1, rel=0.01)


def test_gps_geometry_distance_is_measured_along_denoised_positions() -> None:
    session = _straight_session(include_recorded_distance=False)
    gps = session["stream_dfs"]["gps_fit"]
    lateral_noise_m = np.random.default_rng(42).normal(0.0, 0.5, len(gps.index))
    gps["latitude_deg"] += np.degrees(lateral_noise_m / 6_371_000.0)

    result = derive_spatial_context(
        session,
        _spatial_config(gradient={"enabled": False}, twistiness={"enabled": False}),
    )

    selected = result.stream_meta["distance_source"]["selected"]
    diagnostics = selected["diagnostics"]
    assert diagnostics["repairs"] == ["gps_geometry_denoised_before_stationing"]
    assert diagnostics["geometry_denoising"]["window_m"] == 20.0
    assert diagnostics["raw_geometry_distance_m"] > diagnostics["distance_m"] * 1.3
    assert diagnostics["distance_m"] == pytest.approx(100.0, abs=3.0)


def test_track_scope_defaults_to_last_forward_traversal_and_keeps_session_metrics() -> None:
    session = _straight_session(duration_s=60.0)
    gps = session["stream_dfs"]["gps_fit"]
    time_s = gps["time_s"].to_numpy(float)
    session_distance_m = time_s * 5.0
    track_station_m = np.where(
        time_s <= 20.0,
        session_distance_m,
        np.where(time_s <= 40.0, 100.0 - (time_s - 20.0) * 5.0, (time_s - 40.0) * 5.0),
    )
    gps["distance_m"] = session_distance_m
    gps["longitude_deg"] = 115.85 + np.degrees(
        track_station_m / (6_371_000.0 * np.cos(np.radians(-31.95)))
    )
    gps["altitude_m"] = 200.0 + 0.1 * session_distance_m
    track = {
        "track_id": "straight-track",
        "revision": 2,
        "path": {
            "type": "LineString",
            "length_m": 100.0,
            "coordinates": [
                [115.85, -31.95],
                [
                    115.85 + np.degrees(100.0 / (6_371_000.0 * np.cos(np.radians(-31.95)))),
                    -31.95,
                ],
            ],
        },
    }
    whole_session = derive_spatial_context(
        session,
        _spatial_config(twistiness={"enabled": False}, suspension_activity={"enabled": False}),
    )

    scoped = scope_spatial_context_to_track(whole_session, session, track)

    assert DEFAULT_SPATIAL_CONTEXT_TRACK_SCOPE_CONFIG["traversal_selection"] == "last_forward_traversal"
    assert scoped.stream_meta["track_scope"]["matching"]["forward_traversal_count"] == 2
    selected = scoped.stream_meta["track_scope"]["selected_traversal"]
    assert selected["start_time_s"] >= 40.0
    assert scoped.stream_df["session_distance_m"].min() > 200.0
    assert scoped.stream_df["distance_m"].min() >= 0.0
    assert scoped.stream_df["distance_m"].max() < 100.0
    assert scoped.stream_df["track_station_m"].notna().all()
    assert np.nanmedian(scoped.stream_df["gradient_fraction"]) == pytest.approx(0.1, abs=1.0e-6)
    assert scoped.stream_meta["track_scope"]["metric_source"] == "session"


def test_sequence_aware_track_projection_resolves_overlapping_return_leg() -> None:
    latitude = -31.95
    longitude = 115.85
    east_100_m = longitude + np.degrees(
        100.0 / (6_371_000.0 * np.cos(np.radians(latitude)))
    )
    track = {
        "track_id": "out-and-back",
        "path": {
            "type": "LineString",
            "length_m": 200.0,
            "coordinates": [
                [longitude, latitude],
                [east_100_m, latitude],
                [longitude, latitude],
            ],
        },
    }
    time_s = np.linspace(0.0, 40.0, 201)
    x_m = np.where(time_s <= 20.0, time_s * 5.0, (40.0 - time_s) * 5.0)
    longitude_deg = longitude + np.degrees(
        x_m / (6_371_000.0 * np.cos(np.radians(latitude)))
    )

    match = match_track_traversals(
        time_s,
        np.full(time_s.shape, latitude),
        longitude_deg,
        track,
        {
            "endpoint_tolerance_m": 3.0,
            "minimum_track_coverage_ratio": 0.95,
        },
    )

    assert np.min(np.diff(match.station_m)) > -5.0
    assert match.station_m[-1] > 195.0
    assert len(match.traversals) == 1
    assert match.traversals[0]["coverage_ratio"] >= 0.95


def test_repeated_logger_snapshots_are_collapsed_before_geometry_speed_qc() -> None:
    session = _straight_session(include_recorded_distance=False)
    gps = session["stream_dfs"]["gps_fit"]
    repeated = gps.loc[gps.index.repeat(10)].reset_index(drop=True)
    repeated["time_s"] = np.repeat(gps["time_s"].to_numpy(float), 10) + np.tile(
        np.arange(10, dtype=float) * 0.01,
        len(gps.index),
    )
    session["stream_dfs"]["gps_fit"] = repeated

    result = derive_spatial_context(session, _spatial_config())
    selected = result.stream_meta["distance_source"]["selected"]

    assert selected["candidate_kind"] == "gps_geometry"
    assert selected["diagnostics"]["observation_filter"] == "consecutive_snapshot_values_collapsed"
    assert selected["diagnostics"]["collapsed_snapshot_rows"] == 9 * len(gps.index)
    assert result.stream_meta["status"] == "succeeded"


def test_rear_activity_is_omitted_when_only_shock_motion_exists() -> None:
    result = derive_spatial_context(
        _straight_session(include_rear_wheel=False, include_rear_shock=True),
        _spatial_config(gradient={"enabled": False}, twistiness={"enabled": False}),
    )

    assert "front_suspension_activity" in result.stream_df.columns
    assert "rear_suspension_activity" not in result.stream_df.columns
    assert "combined_suspension_activity" not in result.stream_df.columns
    assert "spatial_context_rear_wheel_displacement_unavailable" in result.stream_meta["warnings"]


def test_deliberately_omitted_rear_selector_does_not_make_front_only_result_partial() -> None:
    result = derive_spatial_context(
        _straight_session(include_rear_wheel=False),
        _spatial_config(
            gradient={"enabled": False},
            twistiness={"enabled": False},
            suspension_activity={"rear_selector": None},
        ),
    )

    assert result.stream_meta["status"] == "succeeded"
    assert "front_suspension_activity" in result.stream_df.columns
    assert "rear_suspension_activity" not in result.stream_df.columns
    assert "spatial_context_rear_wheel_displacement_unavailable" not in result.stream_meta["warnings"]


def test_activity_is_omitted_when_required_preprocess_mask_is_missing() -> None:
    session = _straight_session()
    session["df"] = session["df"].drop(columns=["active_mask_qc"])
    result = derive_spatial_context(
        session,
        _spatial_config(gradient={"enabled": False}, twistiness={"enabled": False}),
    )

    assert result.stream_meta["status"] == "unavailable"
    assert "front_suspension_activity" not in result.stream_df.columns
    assert "rear_suspension_activity" not in result.stream_df.columns
    assert "spatial_context_activity_mask_unavailable" in result.stream_meta["warnings"]


def test_twistiness_matches_circle_curvature() -> None:
    radius_m = 20.0
    theta = np.linspace(0.0, np.pi, 127)
    x_m = radius_m * np.sin(theta)
    y_m = radius_m * (1.0 - np.cos(theta))
    distance_m = radius_m * theta
    latitude_origin = -31.95
    longitude_origin = 115.85
    latitude = latitude_origin + np.degrees(y_m / 6_371_000.0)
    longitude = longitude_origin + np.degrees(
        x_m / (6_371_000.0 * np.cos(np.radians(latitude_origin)))
    )
    gps_time = distance_m / 4.0
    session = {
        "df": pd.DataFrame(
            {
                "time_s": np.linspace(0.0, gps_time[-1], 1000),
                "active_mask_qc": True,
            }
        ),
        "meta": {
            "signals": {},
            "secondary_streams": {
                "gps_fit": {
                    "channel_info": _gps_registry(),
                    "source_kind": "fit_enrichment",
                    "time_col": "time_s",
                }
            },
            "gps_sources": {"preferred_source": "gps_fit"},
        },
        "stream_dfs": {
            "gps_fit": pd.DataFrame(
                {
                    "time_s": gps_time,
                    "latitude_deg": latitude,
                    "longitude_deg": longitude,
                    "altitude_m": 100.0,
                    "distance_m": distance_m,
                }
            )
        },
        "qc": {},
    }
    result = derive_spatial_context(
        session,
        _spatial_config(
            gradient={"enabled": False},
            suspension_activity={"enabled": False},
            distance={"minimum_nominal_gps_rate_hz": 0.1},
        ),
    )

    assert np.nanmedian(result.stream_df["twistiness_rad_per_m"]) == pytest.approx(1.0 / radius_m, rel=0.03)
    assert result.stream_df["curvature_abs_rad_per_m_local"].iloc[:20].isna().all()
    assert result.stream_df["curvature_abs_rad_per_m_local"].iloc[-20:].isna().all()
    provenance = result.stream_meta["metric_provenance"]["twistiness"]
    assert provenance["fit_input"] == "independent_source_position_observations"
    assert provenance["effective_geometry_window_samples"] == 41
    assert provenance["edge_exclusion_distance_m"] == 10.0


def test_source_position_fit_rejects_short_wavelength_gps_zigzag() -> None:
    session = _straight_session(duration_s=30.0)
    gps = session["stream_dfs"]["gps_fit"]
    lateral_error_m = np.where(np.arange(len(gps.index)) % 2 == 0, -1.5, 1.5)
    gps["latitude_deg"] += np.degrees(lateral_error_m / 6_371_000.0)

    result = derive_spatial_context(
        session,
        _spatial_config(
            gradient={"enabled": False},
            suspension_activity={"enabled": False},
        ),
    )

    interior = result.stream_df["distance_m"].between(30.0, 120.0)
    local = result.stream_df.loc[interior, "curvature_abs_rad_per_m_local"]
    assert local.notna().all()
    assert float(local.median()) < 1.0e-5


def test_short_geometry_run_is_not_used_for_twistiness() -> None:
    result = derive_spatial_context(
        _straight_session(duration_s=1.0, gps_rate_hz=10.0),
        _spatial_config(
            gradient={"enabled": False},
            suspension_activity={"enabled": False},
        ),
    )

    assert result.stream_meta["status"] == "unavailable"
    assert result.stream_df["twistiness_source_observation_count"].max() >= 5
    assert result.stream_df["curvature_abs_rad_per_m_local"].isna().all()
    assert result.stream_df["twistiness_rad_per_m"].isna().all()


def test_source_observation_threshold_does_not_create_new_full_window_boundaries() -> None:
    session = _straight_session(gps_rate_hz=10.0)
    gps = session["stream_dfs"]["gps_fit"]
    selected_rows = [0]
    step_index = 0
    while selected_rows[-1] < len(gps.index) - 1:
        next_row = min(
            len(gps.index) - 1,
            selected_rows[-1] + (2 if (step_index // 10) % 2 == 0 else 3),
        )
        if next_row == selected_rows[-1]:
            break
        selected_rows.append(next_row)
        step_index += 1
    session["stream_dfs"]["gps_fit"] = gps.iloc[selected_rows].reset_index(drop=True)

    minimum_three = derive_spatial_context(
        session,
        _spatial_config(
            gradient={"enabled": False},
            suspension_activity={"enabled": False},
            twistiness={
                "geometry_window_m": 5.0,
                "minimum_source_position_observations": 3,
            },
        ),
    )
    minimum_five = derive_spatial_context(
        session,
        _spatial_config(
            gradient={"enabled": False},
            suspension_activity={"enabled": False},
            twistiness={
                "geometry_window_m": 5.0,
                "minimum_source_position_observations": 5,
            },
        ),
    )

    base_valid = minimum_three.stream_df["curvature_abs_rad_per_m_local"].notna()
    observation_valid = (
        minimum_five.stream_df["twistiness_source_observation_count"] >= 5
    )
    expected = base_valid & observation_valid
    actual = minimum_five.stream_df["curvature_abs_rad_per_m_local"].notna()
    assert expected.any()
    assert (base_valid & ~observation_valid).any()
    assert actual.equals(expected)


def test_quality_thresholds_warn_without_omitting_exploratory_output() -> None:
    result = derive_spatial_context(
        _straight_session(gps_rate_hz=0.5),
        _spatial_config(distance={"quality_action": "warn"}),
    )

    assert not result.stream_df.empty
    assert result.stream_meta["status"] == "partial"
    assert "spatial_context_gps_rate_below_threshold" in result.stream_meta["warnings"]


def test_long_gps_gap_remains_unsupported_and_is_not_smoothed_across() -> None:
    session = _straight_session(duration_s=20.0)
    gps = session["stream_dfs"]["gps_fit"]
    session["stream_dfs"]["gps_fit"] = gps.loc[~gps["time_s"].between(8.0, 14.0)].reset_index(drop=True)

    result = derive_spatial_context(session, _spatial_config())
    gap = result.stream_df["distance_m"].between(40.0, 70.0)

    assert (result.stream_df.loc[gap, "distance_support_fraction"] == 0.0).all()
    assert result.stream_df.loc[gap, "representative_time_s"].isna().all()
    assert result.stream_df.loc[gap, "gradient_fraction"].isna().all()
    assert result.stream_df.loc[gap, "front_suspension_activity"].isna().all()


def test_materialized_stream_round_trips_through_artifact_writer(tmp_path) -> None:
    session = _straight_session()
    result = materialize_spatial_context(session, _spatial_config())
    assert not result.stream_df.empty

    store = ArtifactStore(tmp_path / "artifacts")
    save_session_artifacts(
        store,
        run_id="run-test",
        session_id="session-test",
        session_df=session["df"],
        session_meta=session["meta"],
        secondary_stream_dfs=session["stream_dfs"],
        secondary_stream_meta=session["meta"]["secondary_streams"],
    )

    persisted = pd.read_parquet(store.path_session_stream_df("run-test", "session-test", SPATIAL_CONTEXT_STREAM_NAME))
    persisted_meta = json.loads(
        store.path_session_stream_meta("run-test", "session-test", SPATIAL_CONTEXT_STREAM_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert len(persisted.index) == len(result.stream_df.index)
    assert persisted_meta["schema"] == "bodaqs.spatial_context_stream"
    assert persisted_meta["metric_provenance"]["rear_suspension_activity"]["resolved_column"].startswith(
        "rear_wheel_disp"
    )


def test_spatial_context_profile_validation_and_disabled_compatibility() -> None:
    config = default_preprocess_config()
    assert config["spatial_context"]["enabled"] is False
    validate_preprocess_config(config)

    invalid = copy.deepcopy(config)
    invalid["spatial_context"] = _spatial_config(
        suspension_activity={
            "rear_selector": {
                "end": "rear",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
            }
        }
    )
    with pytest.raises(ValueError, match="rear_selector.domain.*wheel"):
        validate_preprocess_config(invalid)

    insufficient_observations = copy.deepcopy(config)
    insufficient_observations["spatial_context"] = _spatial_config(
        twistiness={"minimum_source_position_observations": 2}
    )
    with pytest.raises(ValueError, match="minimum_source_position_observations.*at least 3"):
        validate_preprocess_config(insufficient_observations)


def test_pipeline_materializes_enabled_spatial_context_stream() -> None:
    session = _straight_session(primary_rate_hz=100.0)
    session["meta"]["channel_info"] = copy.deepcopy(session["meta"]["signals"])
    config = default_preprocess_config()
    config["spatial_context"] = _spatial_config()

    result = preprocess_resolved(
        session,
        preprocess_config=config,
        normalize_ranges={},
        include_events=False,
        include_metrics=False,
        strict=False,
    )

    processed = result["session"]
    assert SPATIAL_CONTEXT_STREAM_NAME in processed["stream_dfs"]
    assert processed["meta"]["secondary_streams"][SPATIAL_CONTEXT_STREAM_NAME]["status"] in {
        "succeeded",
        "partial",
    }
    assert processed["meta"]["streams"][SPATIAL_CONTEXT_STREAM_NAME]["kind"] == "spatial_uniform"
    assert "spatial_context" in result["timings"]["stages_s"]


def test_spatial_context_figure_shows_local_and_smoothed_metrics() -> None:
    result = derive_spatial_context(_straight_session(), _spatial_config())

    figure = make_spatial_context_figure(
        result.stream_df,
        metrics=["gradient_fraction", "front_suspension_activity"],
        show_local=True,
        selected_distance_range_m=(20.0, 40.0),
    )

    assert len(figure.data) == 4
    assert {trace.name for trace in figure.data} == {
        "Gradient (local)",
        "Gradient (smoothed)",
        "Front activity (local)",
        "Front activity (smoothed)",
    }
    assert figure.layout.shapes[0].x0 == 20.0
    assert figure.layout.shapes[0].x1 == 40.0


def test_spatial_context_figure_fixes_twistiness_scale_to_zero_point_five() -> None:
    result = derive_spatial_context(_straight_session(), _spatial_config())

    figure = make_spatial_context_figure(
        result.stream_df,
        metrics=["gradient_fraction", "twistiness_rad_per_m"],
    )

    assert tuple(figure.layout.yaxis2.range) == (0.0, 0.5)


def test_distance_selection_maps_to_separate_time_ranges_across_gap() -> None:
    stream = pd.DataFrame(
        {
            "distance_m": [0.25, 0.75, 1.25, 1.75, 2.25],
            "representative_time_s": [0.1, 0.2, np.nan, 0.3, 0.4],
            "distance_support_fraction": [1.0, 1.0, 0.0, 1.0, 1.0],
        }
    )

    ranges = spatial_selection_to_time_ranges(stream, 0.0, 3.0, max_time_gap_s=1.0)

    assert ranges == [
        {
            "start_time_s": 0.1,
            "end_time_s": 0.2,
            "start_distance_m": 0.25,
            "end_distance_m": 0.75,
            "representative_sample_count": 2,
        },
        {
            "start_time_s": 0.3,
            "end_time_s": 0.4,
            "start_distance_m": 1.75,
            "end_distance_m": 2.25,
            "representative_sample_count": 2,
        },
    ]
