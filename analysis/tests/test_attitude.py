from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import bodaqs_analysis.attitude as attitude_module
from bodaqs_analysis.attitude import AttitudeConfig, build_attitude_streams, estimate_attitude
from bodaqs_analysis.gps_semantics import build_logger_gps_route_stream


def _level_imu(*, samples: int = 100, segments: np.ndarray | None = None) -> pd.DataFrame:
    time = np.arange(samples, dtype=float) * 0.01
    return pd.DataFrame(
        {
            "time_s": time,
            "continuity_segment": np.zeros(samples, dtype=int) if segments is None else segments,
            "body_accel_x_m_s2": np.zeros(samples),
            "body_accel_y_m_s2": np.zeros(samples),
            "body_accel_z_m_s2": np.full(samples, 9.80665),
            "body_gyro_x_rad_s": np.zeros(samples),
            "body_gyro_y_rad_s": np.zeros(samples),
            "body_gyro_z_rad_s": np.zeros(samples),
        }
    )


def _course_rows(*, include_accuracy: bool = True) -> pd.DataFrame:
    values: dict[str, list[float]] = {
        "time_s": [0.10, 0.30],
        "snapshot_received_time_s": [0.10, 0.30],
        "heading_deg": [0.0, 0.0],  # North; ENU yaw is +pi/2 from east.
        "speed_mps": [5.0, 5.0],
        "valid": [1.0, 1.0],
    }
    if include_accuracy:
        values["course_accuracy_deg"] = [2.0, 2.0]
        values["speed_accuracy_mps"] = [0.2, 0.2]
    return pd.DataFrame(values)


def test_attitude_initialises_level_and_uses_accepted_course_as_enu_yaw() -> None:
    output, report = estimate_attitude(_level_imu(), gps=_course_rows())

    row = output.iloc[10]
    assert row["roll_rad"] == pytest.approx(0.0)
    assert row["pitch_rad"] == pytest.approx(0.0)
    assert row["yaw_enu_rad"] == pytest.approx(math.pi / 2.0)
    assert row["attitude_state_code"] == 1
    assert row["course_update_weight"] == pytest.approx(1.0)
    assert report["course_updates_accepted"] == 2
    assert report["status"] == "ok"


def test_attitude_requires_logged_course_and_speed_accuracy_by_default() -> None:
    output, report = estimate_attitude(_level_imu(), gps=_course_rows(include_accuracy=False))

    assert set(output["attitude_state_code"]) == {0}
    assert report["course_observation_candidates"] == 0
    assert report["status"] == "gravity_only"


def test_fixed_interval_tilt_uses_qualified_gps_translational_acceleration() -> None:
    imu = _level_imu(samples=100)
    # Simulate steady eastward acceleration. GPS supplies the matching
    # horizontal acceleration, so it can be removed before gravity testing.
    imu["body_accel_x_m_s2"] = 1.0
    gps = pd.DataFrame(
        {
            "time_s": [0.10, 0.45, 0.80],
            "snapshot_received_time_s": [0.10, 0.45, 0.80],
            "heading_deg": [90.0, 90.0, 90.0],
            "speed_mps": [4.0, 4.35, 4.70],
            "valid": [1.0, 1.0, 1.0],
            "course_accuracy_deg": [2.0, 2.0, 2.0],
            "speed_accuracy_mps": [0.2, 0.2, 0.2],
        }
    )

    output, report = estimate_attitude(imu, gps=gps)

    assert output["gps_translational_compensation_used"].any()
    assert output["fixed_interval_gravity_observation_accepted"].any()
    assert report["gps_translational_acceleration"]["status"] == "ok"
    assert report["fixed_interval_tilt_smoother"]["gps_compensation_samples"] > 0


def test_fixed_interval_tilt_recovers_constant_residual_gyro_bias() -> None:
    samples = 2400
    imu = _level_imu(samples=samples)
    imu["time_s"] = np.arange(samples, dtype=float) / 200.0
    injected_bias_rad_s = math.radians(0.25)
    imu["body_gyro_y_rad_s"] = injected_bias_rad_s

    output, report = estimate_attitude(imu)

    assert np.degrees(output["pitch_rad"].median()) == pytest.approx(0.0, abs=0.1)
    assert np.degrees(output["pitch_rad"].iloc[-1]) == pytest.approx(0.0, abs=0.15)
    estimated_bias_deg_s = np.degrees(output["fixed_interval_gyro_bias_body_y_rad_s"].median())
    assert estimated_bias_deg_s == pytest.approx(0.25, abs=0.03)
    assert report["fixed_interval_tilt_smoother"]["method"] == "error_state_rts"


def test_fixed_interval_grid_preintegrates_native_rate_gyro() -> None:
    samples = 3600
    time = np.arange(samples, dtype=float) / 200.0
    imu = _level_imu(samples=samples)
    imu["time_s"] = time
    # Reject gravity during the first eight seconds, then provide a long level
    # reference. The 3 Hz rotation ensures a 25 Hz correction grid must
    # integrate intervening native samples rather than sampling its endpoints.
    imu.loc[:1599, "body_accel_x_m_s2"] = 10.0
    imu["body_gyro_y_rad_s"] = math.radians(0.25) + math.radians(15.0) * np.sin(2.0 * math.pi * 3.0 * time)

    grid_output, _ = estimate_attitude(imu, config=AttitudeConfig(fixed_interval_tilt_rate_hz=25.0))
    native_output, _ = estimate_attitude(imu, config=AttitudeConfig(fixed_interval_tilt_rate_hz=200.0))
    difference_deg = np.abs(np.degrees(grid_output["pitch_rad"] - native_output["pitch_rad"]))

    assert np.median(difference_deg) < 0.2
    assert np.max(difference_deg) < 0.5
    assert abs(np.degrees(grid_output["pitch_rad"].iloc[0])) < 1.5


def test_attitude_does_not_carry_yaw_observation_over_a_continuity_boundary() -> None:
    segments = np.zeros(100, dtype=int)
    segments[50:] = 1
    output, report = estimate_attitude(_level_imu(segments=segments), gps=_course_rows())

    assert output.iloc[30]["attitude_state_code"] == 1
    assert output.iloc[55]["attitude_state_code"] == 0
    assert report["continuity_segment_count"] == 2


def test_attitude_preserves_prior_orientation_across_short_gap_with_dynamic_acceleration() -> None:
    imu = _level_imu(samples=3, segments=np.array([0, 0, 1]))
    imu["body_gyro_x_rad_s"] = [0.0, 1.0, 1.0]
    # The first sample after the gap has a plausible magnitude but an
    # implausible short-gap jerk, so it must not reset attitude from accel.
    imu.loc[2, ["body_accel_x_m_s2", "body_accel_z_m_s2"]] = [9.80665, 0.0]

    output, _ = estimate_attitude(imu, config=AttitudeConfig(gravity_gain=0.0))

    # Fixed-interval propagation uses trapezoidal native-rate gyro
    # preintegration, so the 0 -> 1 rad/s ramp contributes 0.005 rad.
    assert output.iloc[1]["roll_rad"] == pytest.approx(0.005, abs=1.0e-6)
    assert output.iloc[2]["roll_rad"] == pytest.approx(0.02, abs=1.0e-6)
    assert output.iloc[2]["gravity_rejection_code"] == 4


def test_attitude_qc_is_copied_into_persisted_session_metadata(monkeypatch) -> None:
    imu = _level_imu()
    session = {
        "df": pd.DataFrame({"time_s": imu["time_s"]}),
        "stream_dfs": {"imu_frame_imu": imu},
        "meta": {
            "imu_configs": {"frame_imu": {"domain": "frame"}},
            "secondary_streams": {
                "imu_frame_imu": {
                    "schema": "bodaqs.imu_stream.v1",
                    "sensor": "frame_imu",
                    "domain": "frame",
                }
            },
        },
        "qc": {},
    }
    monkeypatch.setattr(attitude_module, "build_imu_streams", lambda value, strict=False: value)

    build_attitude_streams(session)

    assert session["qc"]["attitude"]["frame_imu"]["status"] == "gravity_only"
    assert session["meta"]["attitude_qc"] == session["qc"]["attitude"]


def test_inertial_vector_registry_labels_include_coordinate_direction(monkeypatch) -> None:
    imu = _level_imu()
    session = {
        "df": pd.DataFrame({"time_s": imu["time_s"]}),
        "stream_dfs": {"imu_frame_imu": imu},
        "meta": {
            "imu_configs": {"frame_imu": {"domain": "frame"}},
            "secondary_streams": {
                "imu_frame_imu": {
                    "schema": "bodaqs.imu_stream.v1",
                    "sensor": "frame_imu",
                    "domain": "frame",
                }
            },
        },
        "qc": {},
    }
    monkeypatch.setattr(attitude_module, "build_imu_streams", lambda value, strict=False: value)

    build_attitude_streams(session)

    signals = session["meta"]["secondary_streams"]["inertial_frame_imu"]["signals"]
    assert signals["linear_accel_body_x_m_s2"]["display_name"] == "Frame linear acceleration — forward"
    assert signals["angular_velocity_enu_y_rad_s"]["display_name"] == "World angular velocity — north"


def test_logger_gps_stream_exposes_course_quality_and_receiver_time() -> None:
    columns = {
        "gps0_lat [deg]": ["position_latitude", "deg"],
        "gps0_lon [deg]": ["position_longitude", "deg"],
        "gps0_speed [m/s]": ["speed", "m/s"],
        "gps0_heading [deg]": ["course_over_ground", "deg"],
        "gps0_valid": ["valid", ""],
        "gps0_age [ms]": ["age", "ms"],
        "gps0_seq": ["seq", "count"],
        "gps0_speed_acc [m/s]": ["speed_accuracy", "m/s"],
        "gps0_course_acc [deg]": ["course_accuracy", "deg"],
        "gps0_tow_cs [cs]": ["receiver_time_of_week", "cs"],
    }
    df = pd.DataFrame(
        {
            "time_s": [10.0, 10.1, 10.2],
            "gps0_lat [deg]": [-31.9, -31.9, -31.9],
            "gps0_lon [deg]": [115.8, 115.8, 115.8],
            "gps0_speed [m/s]": [5.0, 5.0, 5.0],
            "gps0_heading [deg]": [45.0, 45.0, 45.0],
            "gps0_valid": [1, 1, 1],
            "gps0_age [ms]": [100, 200, 100],
            "gps0_seq": [3, 3, 4],
            "gps0_speed_acc [m/s]": [0.3, 0.3, 0.2],
            "gps0_course_acc [deg]": [2.0, 2.0, 1.5],
            "gps0_tow_cs [cs]": [1234500, 1234500, 1234520],
        }
    )
    session = {
        "df": df,
        "meta": {
            "signals": {
                name: {"sensor": "gps0", "source": "async_snapshot", "quantity": quantity, "unit": unit}
                for name, (quantity, unit) in columns.items()
            }
        },
    }

    build_logger_gps_route_stream(session)
    route = session["stream_dfs"]["gps_logger"]

    assert len(route.index) == 2
    assert route["course_accuracy_deg"].tolist() == [2.0, 1.5]
    assert route["speed_accuracy_mps"].tolist() == [0.3, 0.2]
    assert route["receiver_time_of_week_s"].tolist() == [12345.0, 12345.2]
    assert route["snapshot_received_time_s"].tolist() == pytest.approx([9.9, 10.1])
    primary_speed = session["meta"]["signals"]["gps0_speed [m/s]"]
    route_speed = session["meta"]["secondary_streams"]["gps_logger"]["signals"]["speed_mps"]
    primary_course = session["meta"]["signals"]["gps0_heading [deg]"]

    assert primary_speed["inspection_visibility"] == "standard"
    assert primary_speed["analysis_variant"] == "logger_timebase_held"
    assert primary_speed["display_name"] == "GPS speed (logger timebase)"
    assert route_speed["inspection_visibility"] == "advanced"
    assert route_speed["analysis_variant"] == "reconstructed_observations"
    assert route_speed["display_name"] == "GPS speed (GPS snapshots)"
    assert primary_course["quantity"] == "course_over_ground"
