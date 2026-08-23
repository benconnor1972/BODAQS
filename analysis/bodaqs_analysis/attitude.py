"""Versioned offline frame-IMU fused inertial product.

This module deliberately consumes the valid-only IMU and logger-GPS secondary
streams.  It never changes raw evidence or the primary logger dataframe.
"""
from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from .gps_semantics import build_logger_gps_route_stream
from .imu import IMU_STREAM_SCHEMA, build_imu_streams
from .sensor_aliases import canonical_sensor_id
from .timebase import register_stream_metadata


INERTIAL_STREAM_SCHEMA = "bodaqs.inertial_stream.v1"
LEGACY_ATTITUDE_STREAM_SCHEMA = "bodaqs.attitude_stream.v1"
# Retained as a Python-level compatibility name for callers that imported it
# before the stream became the broader inertial product.
ATTITUDE_STREAM_SCHEMA = INERTIAL_STREAM_SCHEMA
ATTITUDE_QC_SCHEMA = "bodaqs.attitude_qc.v2"
STANDARD_GRAVITY_M_S2 = 9.80665

_STATE_GRAVITY_ALIGNED = 0
_STATE_WORLD_ENU_CONSTRAINED = 1
_STATE_WORLD_ENU_DEGRADED = 2
_STATE_NAMES = {
    _STATE_GRAVITY_ALIGNED: "gravity_aligned",
    _STATE_WORLD_ENU_CONSTRAINED: "world_enu_constrained",
    _STATE_WORLD_ENU_DEGRADED: "world_enu_degraded",
}

_WORLD_YAW_UNOBSERVED = 0
_WORLD_YAW_SMOOTHED = 1
_WORLD_YAW_BACKFILLED = 2
_WORLD_YAW_EXTRAPOLATED = 3
_WORLD_YAW_STATE_NAMES = {
    _WORLD_YAW_UNOBSERVED: "unobserved",
    _WORLD_YAW_SMOOTHED: "course_smoothed",
    _WORLD_YAW_BACKFILLED: "course_backfilled",
    _WORLD_YAW_EXTRAPOLATED: "course_extrapolated",
}


@dataclass(frozen=True)
class AttitudeConfig:
    """Offline frame-attitude estimation settings.

    The forward estimate remains an internal propagation pass.  Persisted
    orientation is the fixed-interval solution, so later gravity evidence can
    improve earlier samples without presenting a causal alternative as a
    competing engineering signal.
    """

    gravity_norm_tolerance_g: float = 0.12
    gravity_window_s: float = 0.5
    gravity_norm_std_max_g: float = 0.025
    gravity_jerk_max_m_s3: float = 6.0
    gravity_gain: float = 0.035
    course_min_speed_mps: float = 3.0
    course_max_accuracy_deg: float = 8.0
    course_max_speed_accuracy_mps: float = 1.0
    course_gain: float = 0.35
    course_max_innovation_deg: float = 45.0
    course_stale_after_s: float = 2.0
    gyro_noise_rad_s: float = math.radians(0.08)
    require_course_accuracy: bool = True
    require_speed_accuracy: bool = True
    world_yaw_smoother_enabled: bool = True
    world_yaw_max_bridge_gap_s: float = 0.25
    world_yaw_bridge_max_rotation_deg: float = 45.0
    world_yaw_drift_deg_s: float = 0.5
    fixed_interval_tilt_smoother_enabled: bool = True
    fixed_interval_tilt_rate_hz: float = 25.0
    fixed_interval_gravity_sigma_deg: float = 3.0
    fixed_interval_initial_tilt_sigma_deg: float = 20.0
    fixed_interval_initial_bias_sigma_deg_s: float = 0.20
    fixed_interval_bias_random_walk_deg_s_sqrt_s: float = 0.005
    fixed_interval_gravity_window_s: float = 0.5
    fixed_interval_gravity_norm_tolerance_g: float = 0.20
    fixed_interval_gravity_std_max_g: float = 0.12
    gps_translational_compensation_enabled: bool = True
    gps_acceleration_max_m_s2: float = 12.0
    gps_acceleration_max_gap_s: float = 0.75
    inertial_dynamics_enabled: bool = True
    inertial_dynamics_include_world_frame: bool = True
    inertial_dynamics_include_angular_kinematics: bool = True
    inertial_dynamics_include_magnitudes: bool = True


def _normalise_quaternion(q: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(q))
    return q / norm if norm > 0.0 and math.isfinite(norm) else np.array([1.0, 0.0, 0.0, 0.0])


def _quaternion_multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return np.array(
        [
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        ],
        dtype=float,
    )


def _quaternion_inverse(q: np.ndarray) -> np.ndarray:
    w, x, y, z = _normalise_quaternion(q)
    return np.array([w, -x, -y, -z], dtype=float)


def _quaternion_from_rotation_vector(rotation_vector: np.ndarray) -> np.ndarray:
    angle = float(np.linalg.norm(rotation_vector))
    if angle < 1.0e-12:
        return np.array([1.0, 0.0, 0.0, 0.0])
    axis = rotation_vector / angle
    half = angle * 0.5
    return np.array([math.cos(half), *(axis * math.sin(half))], dtype=float)


def _quaternion_from_two_vectors(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    source = source / np.linalg.norm(source)
    target = target / np.linalg.norm(target)
    dot = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if dot < -0.999999:
        axis = np.cross(source, np.array([1.0, 0.0, 0.0]))
        if np.linalg.norm(axis) < 1.0e-6:
            axis = np.cross(source, np.array([0.0, 1.0, 0.0]))
        return _quaternion_from_rotation_vector(axis / np.linalg.norm(axis) * math.pi)
    return _normalise_quaternion(np.array([1.0 + dot, *np.cross(source, target)], dtype=float))


def _rotation_matrix(q: np.ndarray) -> np.ndarray:
    w, x, y, z = _normalise_quaternion(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


def _wrap_pi(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _euler_zyx(q: np.ndarray) -> tuple[float, float, float]:
    rotation = _rotation_matrix(q)
    roll = math.atan2(rotation[2, 1], rotation[2, 2])
    pitch = math.asin(float(np.clip(-rotation[2, 0], -1.0, 1.0)))
    yaw = math.atan2(rotation[1, 0], rotation[0, 0])
    return roll, pitch, yaw


def _quaternion_from_euler_zyx(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """Return the body-to-world quaternion for the displayed ZYX convention."""
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    return _normalise_quaternion(
        np.array(
            [
                cy * cp * cr + sy * sp * sr,
                cy * cp * sr - sy * sp * cr,
                cy * sp * cr + sy * cp * sr,
                sy * cp * cr - cy * sp * sr,
            ],
            dtype=float,
        )
    )


def _rotation_vector_from_quaternion(q: np.ndarray) -> np.ndarray:
    q = _normalise_quaternion(q)
    if q[0] < 0.0:
        q = -q
    sin_half = float(np.linalg.norm(q[1:]))
    if sin_half < 1.0e-12:
        return np.zeros(3, dtype=float)
    return q[1:] * (2.0 * math.atan2(sin_half, float(q[0])) / sin_half)


def _numeric_column(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame.columns:
        return np.full(len(frame.index), np.nan)
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)


def _startup_bias_rad_s(session: Mapping[str, Any], sensor: str, imu: pd.DataFrame) -> np.ndarray:
    reports = session.get("qc", {}).get("imu", {}) if isinstance(session.get("qc"), Mapping) else {}
    report = reports.get(sensor, {}) if isinstance(reports, Mapping) else {}
    startup = report.get("startup_stationary_observation") if isinstance(report, Mapping) else None
    if not isinstance(startup, Mapping) or startup.get("state") != "accepted":
        return np.zeros(3, dtype=float)
    raw = startup.get("gyro_mean_raw")
    if not isinstance(raw, Mapping):
        return np.zeros(3, dtype=float)
    output = np.zeros(3, dtype=float)
    for index, axis in enumerate("xyz"):
        raw_col = f"gyro_{axis}_raw_count"
        si_col = f"gyro_{axis}_rad_s"
        if raw_col not in imu.columns or si_col not in imu.columns:
            continue
        counts = pd.to_numeric(imu[raw_col], errors="coerce").to_numpy(dtype=float)
        radians = pd.to_numeric(imu[si_col], errors="coerce").to_numpy(dtype=float)
        usable = np.isfinite(counts) & np.isfinite(radians) & (np.abs(counts) > 1.0)
        if usable.any():
            output[index] = float(raw.get(axis, 0.0)) * float(np.median(radians[usable] / counts[usable]))
    return output


def _course_observations(gps: Optional[pd.DataFrame], config: AttitudeConfig) -> list[dict[str, float]]:
    if not isinstance(gps, pd.DataFrame) or gps.empty:
        return []
    time = _numeric_column(gps, "snapshot_received_time_s")
    if not np.isfinite(time).any():
        time = _numeric_column(gps, "time_s")
    heading = _numeric_column(gps, "heading_deg")
    speed = _numeric_column(gps, "speed_mps")
    course_accuracy = _numeric_column(gps, "course_accuracy_deg")
    speed_accuracy = _numeric_column(gps, "speed_accuracy_mps")
    valid = _numeric_column(gps, "valid")
    rows: list[dict[str, float]] = []
    for index in range(len(gps.index)):
        if not (math.isfinite(time[index]) and math.isfinite(heading[index]) and math.isfinite(speed[index])):
            continue
        if np.isfinite(valid[index]) and valid[index] != 1.0:
            continue
        if speed[index] < config.course_min_speed_mps:
            continue
        if config.require_course_accuracy and not math.isfinite(course_accuracy[index]):
            continue
        if config.require_speed_accuracy and not math.isfinite(speed_accuracy[index]):
            continue
        if math.isfinite(course_accuracy[index]) and course_accuracy[index] > config.course_max_accuracy_deg:
            continue
        if math.isfinite(speed_accuracy[index]) and speed_accuracy[index] > config.course_max_speed_accuracy_mps:
            continue
        rows.append(
            {
                "time_s": float(time[index]),
                "course_enu_rad": math.pi * 0.5 - math.radians(float(heading[index])),
                "accuracy_rad": math.radians(float(course_accuracy[index]))
                if math.isfinite(course_accuracy[index])
                else math.radians(config.course_max_accuracy_deg),
            }
        )
    return sorted(rows, key=lambda row: row["time_s"])


def _gps_translational_acceleration(
    *,
    imu_time: np.ndarray,
    gps: Optional[pd.DataFrame],
    config: AttitudeConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Estimate low-frequency horizontal ENU acceleration from qualified GPS.

    Course-over-ground supplies a horizontal velocity vector, not bicycle
    heading.  This deliberately shares the yaw evidence quality gates and
    never differentiates GPS altitude.  The returned series is only populated
    near valid GPS observations; callers retain ordinary gravity evidence in
    the remaining samples.
    """
    output = np.full((len(imu_time), 3), np.nan)
    report: dict[str, Any] = {
        "enabled": bool(config.gps_translational_compensation_enabled),
        "gps_rows_qualified": 0,
        "gps_acceleration_rows": 0,
        "imu_samples_compensable": 0,
        "status": "unavailable",
    }
    if not config.gps_translational_compensation_enabled or not isinstance(gps, pd.DataFrame) or gps.empty:
        return output, report

    gps_time = _numeric_column(gps, "snapshot_received_time_s")
    if not np.isfinite(gps_time).any():
        gps_time = _numeric_column(gps, "time_s")
    heading = _numeric_column(gps, "heading_deg")
    speed = _numeric_column(gps, "speed_mps")
    valid = _numeric_column(gps, "valid")
    course_accuracy = _numeric_column(gps, "course_accuracy_deg")
    speed_accuracy = _numeric_column(gps, "speed_accuracy_mps")
    qualified = np.isfinite(gps_time) & np.isfinite(heading) & np.isfinite(speed)
    qualified &= speed >= config.course_min_speed_mps
    qualified &= ~np.isfinite(valid) | (valid == 1.0)
    if config.require_course_accuracy:
        qualified &= np.isfinite(course_accuracy)
    if config.require_speed_accuracy:
        qualified &= np.isfinite(speed_accuracy)
    qualified &= ~np.isfinite(course_accuracy) | (course_accuracy <= config.course_max_accuracy_deg)
    qualified &= ~np.isfinite(speed_accuracy) | (speed_accuracy <= config.course_max_speed_accuracy_mps)
    report["gps_rows_qualified"] = int(np.count_nonzero(qualified))
    if np.count_nonzero(qualified) < 3:
        report["status"] = "insufficient_qualified_gps"
        return output, report

    rows = np.flatnonzero(qualified)
    order = rows[np.argsort(gps_time[rows])]
    unique = np.r_[True, np.diff(gps_time[order]) > 1.0e-6]
    order = order[unique]
    if len(order) < 3:
        report["status"] = "insufficient_distinct_gps_times"
        return output, report
    times = gps_time[order]
    heading_rad = np.radians(heading[order])
    velocity = np.column_stack((speed[order] * np.sin(heading_rad), speed[order] * np.cos(heading_rad)))
    # A centred three-point mean is intentionally low bandwidth before the
    # finite-difference operation.  The fixed-interval attitude solution can
    # use future GPS evidence, whereas the causal estimate cannot.
    velocity_smooth = velocity.copy()
    velocity_smooth[1:-1] = (velocity[:-2] + velocity[1:-1] + velocity[2:]) / 3.0
    acceleration = np.column_stack(
        (np.gradient(velocity_smooth[:, 0], times), np.gradient(velocity_smooth[:, 1], times))
    )
    acceleration_norm = np.linalg.norm(acceleration, axis=1)
    usable = np.isfinite(acceleration).all(axis=1) & (acceleration_norm <= config.gps_acceleration_max_m_s2)
    if np.count_nonzero(usable) < 2:
        report["status"] = "gps_acceleration_rejected"
        return output, report
    times = times[usable]
    acceleration = acceleration[usable]
    report["gps_acceleration_rows"] = int(len(times))

    within = (imu_time >= times[0]) & (imu_time <= times[-1]) & np.isfinite(imu_time)
    if np.any(within):
        nearest_distance = np.minimum(
            np.abs(imu_time[within] - times[np.searchsorted(times, imu_time[within], side="left").clip(0, len(times) - 1)]),
            np.abs(imu_time[within] - times[(np.searchsorted(times, imu_time[within], side="left") - 1).clip(0, len(times) - 1)]),
        )
        eligible_indices = np.flatnonzero(within)[nearest_distance <= config.gps_acceleration_max_gap_s]
        for component in range(2):
            output[eligible_indices, component] = np.interp(imu_time[eligible_indices], times, acceleration[:, component])
        output[eligible_indices, 2] = 0.0
    report["imu_samples_compensable"] = int(np.count_nonzero(np.isfinite(output).all(axis=1)))
    report["status"] = "ok" if report["imu_samples_compensable"] else "gps_acceleration_not_time_aligned"
    return output, report


def _centred_vector_mean_and_norm_std(
    values: np.ndarray,
    segment: np.ndarray,
    time: np.ndarray,
    window_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return segment-local centred vector means and norm standard deviations."""
    mean = np.full_like(values, np.nan)
    norm_std = np.full(len(values), np.nan)
    for segment_id in np.unique(segment):
        indices = np.flatnonzero(segment == segment_id)
        if not len(indices):
            continue
        local_time = time[indices]
        finite_steps = np.diff(local_time)
        finite_steps = finite_steps[np.isfinite(finite_steps) & (finite_steps > 0.0)]
        sample_window = max(3, int(round(window_s / float(np.median(finite_steps)))) if len(finite_steps) else 3)
        local = pd.DataFrame(values[indices])
        mean[indices] = local.rolling(sample_window, center=True, min_periods=max(3, sample_window // 3)).mean().to_numpy()
        norm_std[indices] = (
            pd.Series(np.linalg.norm(values[indices], axis=1))
            .rolling(sample_window, center=True, min_periods=max(3, sample_window // 3))
            .std()
            .to_numpy()
        )
    return mean, norm_std


def _preintegrate_gyro_interval(
    *,
    time: np.ndarray,
    gyro_body: np.ndarray,
    start_index: int,
    end_index: int,
    bias_body_rad_s: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Integrate every native-rate gyro increment between two correction nodes."""
    delta_q = np.array([1.0, 0.0, 0.0, 0.0])
    total_dt = 0.0
    for index in range(start_index + 1, end_index + 1):
        dt = float(time[index] - time[index - 1])
        if not math.isfinite(dt) or dt <= 0.0 or dt > 0.5:
            continue
        previous = gyro_body[index - 1]
        current = gyro_body[index]
        if not (np.isfinite(previous).all() and np.isfinite(current).all()):
            continue
        omega = (previous + current) * 0.5 - bias_body_rad_s
        delta_q = _normalise_quaternion(
            _quaternion_multiply(delta_q, _quaternion_from_rotation_vector(omega * dt))
        )
        total_dt += dt
    return delta_q, total_dt


def _fixed_interval_tilt_smoother(
    *,
    time: np.ndarray,
    segment: np.ndarray,
    accel_body: np.ndarray,
    gyro_body: np.ndarray,
    reference_quaternions: np.ndarray,
    yaw: np.ndarray,
    gps_acceleration_enu: np.ndarray,
    config: AttitudeConfig,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Bias-aware manifold RTS smoother for fixed-interval pitch and roll."""
    count = len(time)
    compensated = accel_body.copy()
    compensation_used = np.zeros(count, dtype=bool)
    for index in range(count):
        if (
            np.isfinite(accel_body[index]).all()
            and np.isfinite(reference_quaternions[index]).all()
            and np.isfinite(yaw[index])
            and np.isfinite(gps_acceleration_enu[index]).all()
        ):
            compensated[index] -= _rotation_matrix(reference_quaternions[index]).T @ gps_acceleration_enu[index]
            compensation_used[index] = True

    observation, norm_std = _centred_vector_mean_and_norm_std(
        compensated, segment, time, config.fixed_interval_gravity_window_s
    )
    norm = np.linalg.norm(observation, axis=1)
    norm_error_g = np.abs(norm - STANDARD_GRAVITY_M_S2) / STANDARD_GRAVITY_M_S2
    accepted = (
        np.isfinite(observation).all(axis=1)
        & np.isfinite(norm_std)
        & (norm_error_g <= config.fixed_interval_gravity_norm_tolerance_g)
        & (norm_std / STANDARD_GRAVITY_M_S2 <= config.fixed_interval_gravity_std_max_g)
    )

    grid_parts: list[np.ndarray] = []
    for segment_id in np.unique(segment):
        indices = np.flatnonzero(segment == segment_id)
        if not len(indices):
            continue
        steps = np.diff(time[indices])
        steps = steps[np.isfinite(steps) & (steps > 0.0)]
        stride = max(
            1,
            int(round(1.0 / (config.fixed_interval_tilt_rate_hz * float(np.median(steps)))))
            if len(steps)
            else 1,
        )
        selected = indices[::stride]
        if selected[-1] != indices[-1]:
            selected = np.append(selected, indices[-1])
        grid_parts.append(selected)
    grid_indices = np.concatenate(grid_parts) if grid_parts else np.empty(0, dtype=int)
    grid_time = time[grid_indices]
    grid_segment = segment[grid_indices]
    node_observation = np.full((len(grid_indices), 3), np.nan)
    node_norm_error_g = np.full(len(grid_indices), np.nan)
    node_norm_std_g = np.full(len(grid_indices), np.nan)
    node_accepted = np.zeros(len(grid_indices), dtype=bool)

    # Pool all accepted native-rate observations into their nearest correction
    # node so short valid intervals are not missed by decimation.
    for segment_id in np.unique(grid_segment):
        positions = np.flatnonzero(grid_segment == segment_id)
        source_indices = np.flatnonzero(segment == segment_id)
        for local_position, position in enumerate(positions):
            left = source_indices[0] if local_position == 0 else (grid_indices[positions[local_position - 1]] + grid_indices[position]) // 2 + 1
            right = source_indices[-1] + 1 if local_position == len(positions) - 1 else (grid_indices[position] + grid_indices[positions[local_position + 1]]) // 2 + 1
            candidates = np.arange(left, right, dtype=int)
            candidates = candidates[accepted[candidates]]
            if not len(candidates):
                continue
            vectors = observation[candidates]
            vector = np.mean(vectors, axis=0)
            vector_norm = float(np.linalg.norm(vector))
            if vector_norm <= 0.0 or not math.isfinite(vector_norm):
                continue
            node_observation[position] = vector / vector_norm
            node_norm_error_g[position] = float(np.mean(norm_error_g[candidates]))
            node_norm_std_g[position] = float(np.mean(norm_std[candidates]) / STANDARD_GRAVITY_M_S2)
            node_accepted[position] = True

    node_count = len(grid_indices)
    filtered_q = np.full((node_count, 4), np.nan)
    filtered_bias = np.full((node_count, 3), np.nan)
    filtered_covariance = np.full((node_count, 6, 6), np.nan)
    predicted_q = np.full((node_count, 4), np.nan)
    predicted_bias = np.full((node_count, 3), np.nan)
    predicted_covariance = np.full((node_count, 6, 6), np.nan)
    transition = np.full((node_count, 6, 6), np.nan)
    node_innovation = np.full(node_count, np.nan)

    initial_tilt_sigma = math.radians(config.fixed_interval_initial_tilt_sigma_deg)
    initial_yaw_sigma = math.radians(180.0)
    initial_bias_sigma = math.radians(config.fixed_interval_initial_bias_sigma_deg_s)
    bias_random_walk = math.radians(config.fixed_interval_bias_random_walk_deg_s_sqrt_s)
    gravity_sigma = math.radians(config.fixed_interval_gravity_sigma_deg)
    identity6 = np.eye(6)
    measurement_matrix = np.zeros((2, 6))
    measurement_matrix[0, 0] = 1.0
    measurement_matrix[1, 1] = 1.0

    def measurement_update(
        q: np.ndarray,
        bias: np.ndarray,
        covariance: np.ndarray,
        position: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if not node_accepted[position]:
            return q, bias, covariance
        observed_world = _rotation_matrix(q) @ node_observation[position]
        correction_world = np.cross(observed_world, np.array([0.0, 0.0, 1.0]))
        node_innovation[position] = math.asin(min(1.0, float(np.linalg.norm(correction_world))))
        quality_scale = 1.0 + 4.0 * float(node_norm_error_g[position]) + 2.0 * float(node_norm_std_g[position])
        measurement_covariance = np.eye(2) * (gravity_sigma * quality_scale) ** 2
        innovation_covariance = measurement_matrix @ covariance @ measurement_matrix.T + measurement_covariance
        gain = covariance @ measurement_matrix.T @ np.linalg.pinv(innovation_covariance)
        correction = gain @ correction_world[:2]
        updated_q = _normalise_quaternion(
            _quaternion_multiply(_quaternion_from_rotation_vector(correction[:3]), q)
        )
        updated_bias = bias + correction[3:]
        residual = identity6 - gain @ measurement_matrix
        updated_covariance = (
            residual @ covariance @ residual.T + gain @ measurement_covariance @ gain.T
        )
        return updated_q, updated_bias, updated_covariance

    for segment_id in np.unique(grid_segment):
        positions = np.flatnonzero(grid_segment == segment_id)
        if not len(positions):
            continue
        first = int(positions[0])
        q = reference_quaternions[grid_indices[first]].copy()
        bias = np.zeros(3, dtype=float)
        covariance = np.diag(
            [initial_tilt_sigma**2, initial_tilt_sigma**2, initial_yaw_sigma**2]
            + [initial_bias_sigma**2] * 3
        )
        predicted_q[first] = q
        predicted_bias[first] = bias
        predicted_covariance[first] = covariance
        transition[first] = identity6
        q, bias, covariance = measurement_update(q, bias, covariance, first)
        filtered_q[first] = q
        filtered_bias[first] = bias
        filtered_covariance[first] = covariance

        for position in positions[1:]:
            position = int(position)
            previous = position - 1
            delta_q, dt = _preintegrate_gyro_interval(
                time=time,
                gyro_body=gyro_body,
                start_index=int(grid_indices[previous]),
                end_index=int(grid_indices[position]),
                bias_body_rad_s=bias,
            )
            q_pred = _normalise_quaternion(_quaternion_multiply(q, delta_q))
            bias_pred = bias.copy()
            state_transition = identity6.copy()
            state_transition[:3, 3:] = -_rotation_matrix(q_pred) * dt
            process_covariance = np.diag(
                [max(1.0e-12, config.gyro_noise_rad_s**2 * dt)] * 3
                + [max(1.0e-14, bias_random_walk**2 * dt)] * 3
            )
            covariance_pred = state_transition @ covariance @ state_transition.T + process_covariance
            predicted_q[position] = q_pred
            predicted_bias[position] = bias_pred
            predicted_covariance[position] = covariance_pred
            transition[position] = state_transition
            q, bias, covariance = measurement_update(q_pred, bias_pred, covariance_pred, position)
            filtered_q[position] = q
            filtered_bias[position] = bias
            filtered_covariance[position] = covariance

    smoothed_q = filtered_q.copy()
    smoothed_bias = filtered_bias.copy()
    smoothed_covariance = filtered_covariance.copy()
    if config.fixed_interval_tilt_smoother_enabled:
        for segment_id in np.unique(grid_segment):
            positions = np.flatnonzero(grid_segment == segment_id)
            for local_position in range(len(positions) - 2, -1, -1):
                position = int(positions[local_position])
                following = int(positions[local_position + 1])
                smoother_gain = (
                    filtered_covariance[position]
                    @ transition[following].T
                    @ np.linalg.pinv(predicted_covariance[following])
                )
                next_error = np.concatenate(
                    (
                        _rotation_vector_from_quaternion(
                            _quaternion_multiply(
                                smoothed_q[following], _quaternion_inverse(predicted_q[following])
                            )
                        ),
                        smoothed_bias[following] - predicted_bias[following],
                    )
                )
                correction = smoother_gain @ next_error
                smoothed_q[position] = _normalise_quaternion(
                    _quaternion_multiply(
                        _quaternion_from_rotation_vector(correction[:3]), filtered_q[position]
                    )
                )
                smoothed_bias[position] = filtered_bias[position] + correction[3:]
                smoothed_covariance[position] = (
                    filtered_covariance[position]
                    + smoother_gain
                    @ (smoothed_covariance[following] - predicted_covariance[following])
                    @ smoother_gain.T
                )

    final = reference_quaternions.copy()
    bias_full = np.zeros((count, 3), dtype=float)
    tilt_sigma_deg = np.full(count, np.nan)
    innovation = np.full(count, np.nan)
    innovation[grid_indices] = node_innovation
    for segment_id in np.unique(segment):
        local_indices = np.flatnonzero(segment == segment_id)
        positions = np.flatnonzero(grid_segment == segment_id)
        if not len(local_indices) or not len(positions):
            continue
        grid_times = grid_time[positions]
        corrections = np.array(
            [
                _rotation_vector_from_quaternion(
                    _quaternion_multiply(
                        smoothed_q[position],
                        _quaternion_inverse(reference_quaternions[grid_indices[position]]),
                    )
                )
                for position in positions
            ]
        )
        interpolated_correction = np.column_stack(
            [np.interp(time[local_indices], grid_times, corrections[:, axis]) for axis in range(3)]
        )
        for row, index in enumerate(local_indices):
            if np.isfinite(final[index]).all():
                final[index] = _normalise_quaternion(
                    _quaternion_multiply(
                        _quaternion_from_rotation_vector(interpolated_correction[row]),
                        reference_quaternions[index],
                    )
                )
        for axis in range(3):
            bias_full[local_indices, axis] = np.interp(
                time[local_indices], grid_times, smoothed_bias[positions, axis]
            )
        node_sigma = np.degrees(
            np.sqrt(
                np.maximum(
                    0.0,
                    smoothed_covariance[positions, 0, 0] + smoothed_covariance[positions, 1, 1],
                )
            )
        )
        tilt_sigma_deg[local_indices] = np.interp(time[local_indices], grid_times, node_sigma)

    for index in range(count):
        if np.isfinite(final[index]).all() and np.isfinite(yaw[index]):
            roll, pitch, _ = _euler_zyx(final[index])
            final[index] = _quaternion_from_euler_zyx(roll, pitch, yaw[index])
    euler = np.array(
        [_euler_zyx(q) if np.isfinite(q).all() else (np.nan, np.nan, np.nan) for q in final]
    )
    finite_bias = np.isfinite(bias_full).all(axis=1)
    report = {
        "enabled": bool(config.fixed_interval_tilt_smoother_enabled),
        "method": "error_state_rts",
        "correction_rate_hz": float(config.fixed_interval_tilt_rate_hz),
        "correction_nodes": int(node_count),
        "gravity_observations_accepted": int(np.count_nonzero(accepted)),
        "gravity_observation_nodes": int(np.count_nonzero(node_accepted)),
        "gps_compensation_samples": int(np.count_nonzero(compensation_used)),
        "output_samples": int(np.count_nonzero(np.isfinite(final).all(axis=1))),
        "estimated_residual_gyro_bias_median_rad_s": (
            np.median(bias_full[finite_bias], axis=0).tolist() if np.any(finite_bias) else [0.0, 0.0, 0.0]
        ),
    }
    return {
        "quaternions": final,
        "euler": euler,
        "gravity_observation": observation,
        "gravity_observation_accepted": accepted,
        "gravity_innovation_rad": innovation,
        "gps_compensation_used": compensation_used,
        "gyro_bias_body_rad_s": bias_full,
        "tilt_sigma_deg": tilt_sigma_deg,
    }, report


def _vector_display_name(subject: str, quantity: str, axis: str, coordinate_frame: str) -> str:
    """Return a human label while retaining component/frame semantics in metadata."""
    direction = {
        "body_local": {"x": "forward", "y": "left", "z": "up"},
        "bike_body": {"x": "forward", "y": "left", "z": "up"},
        "enu": {"x": "east", "y": "north", "z": "up"},
        "world_enu": {"x": "east", "y": "north", "z": "up"},
    }.get(coordinate_frame, {}).get(axis, axis.upper())
    return f"{subject} {quantity} — {direction}"


def _inertial_signal_registry(sensor_id: str, config: AttitudeConfig) -> dict[str, dict[str, Any]]:
    """Return registry entries for the fused inertial product.

    This product is a secondary stream, so it does not pass through the primary
    dataframe registry builder.  Supplying its registry here makes the world
    ENU product discoverable by registry-first clients such as Desktop.
    """
    world = {
        "sensor": sensor_id,
        "domain": "world",
        "source": "inertial_estimate",
        "coordinate_frame": "enu",
        "derivation": INERTIAL_STREAM_SCHEMA,
    }
    registry: dict[str, dict[str, Any]] = {
        "continuity_segment": {
            "sensor": sensor_id,
            "kind": "qc",
            "quantity": "continuity_segment",
            "unit": "count",
            "processing_role": "qc_metric",
            "semantic_selection_excluded": True,
            "source": "inertial_estimate",
        },
        "yaw_sigma_deg": {
            **world,
            "kind": "qc",
            "quantity": "orientation_yaw_uncertainty",
            "unit": "deg",
            "processing_role": "qc_metric",
        },
        "gravity_update_weight": {
            "sensor": sensor_id,
            "kind": "qc",
            "quantity": "gravity_correction_weight",
            "unit": "1",
            "processing_role": "qc_metric",
            "source": "inertial_estimate",
        },
        "gravity_rejection_code": {
            "sensor": sensor_id,
            "kind": "qc",
            "quantity": "gravity_correction_rejection",
            "unit": "count",
            "processing_role": "qc_metric",
            "source": "inertial_estimate",
        },
        "course_update_weight": {
            **world,
            "kind": "qc",
            "quantity": "course_over_ground_correction_weight",
            "unit": "1",
            "processing_role": "qc_metric",
        },
        "course_innovation_rad": {
            **world,
            "kind": "qc",
            "quantity": "course_over_ground_innovation",
            "unit": "rad",
            "processing_role": "qc_metric",
        },
        "course_rejection_code": {
            **world,
            "kind": "qc",
            "quantity": "course_over_ground_rejection",
            "unit": "count",
            "processing_role": "qc_metric",
        },
        "attitude_state_code": {
            **world,
            "kind": "qc",
            "quantity": "orientation_state",
            "unit": "count",
            "processing_role": "qc_metric",
        },
        "fixed_interval_gravity_observation_accepted": {
            **world, "kind": "qc", "quantity": "gravity_observation_accepted", "unit": "1",
            "processing_role": "qc_metric", "smoothing": "fixed_interval",
        },
        "fixed_interval_gravity_innovation_rad": {
            **world, "kind": "qc", "quantity": "gravity_innovation", "unit": "rad",
            "processing_role": "qc_metric", "smoothing": "fixed_interval",
        },
        "gps_translational_compensation_used": {
            **world, "kind": "qc", "quantity": "gps_translational_acceleration_compensation", "unit": "1",
            "processing_role": "qc_metric", "smoothing": "fixed_interval",
        },
        "fixed_interval_tilt_sigma_deg": {
            **world, "kind": "qc", "quantity": "orientation_tilt_uncertainty", "unit": "deg",
            "processing_role": "qc_metric", "smoothing": "fixed_interval",
        },
    }
    for axis in "xyz":
        registry[f"fixed_interval_gyro_bias_body_{axis}_rad_s"] = {
            "sensor": sensor_id,
            "domain": "frame",
            "coordinate_frame": "body_local",
            "source": "inertial_estimate",
            "kind": "qc",
            "quantity": "angular_velocity_bias",
            "unit": "rad/s",
            "component": axis,
            "vector_group": "fixed_interval_gyro_bias_body",
            "processing_role": "qc_metric",
            "smoothing": "fixed_interval",
        }
    for axis in "wxyz":
        registry[f"q_body_to_world_enu_{axis}"] = {
            **world,
            "quantity": "orientation_quaternion",
            "unit": "1",
            "component": axis,
            "vector_group": "body_to_world_enu_quaternion",
            "smoothing": "fixed_interval",
            "processing_role": "primary_analysis",
            "inspection_visibility": "advanced",
            "analysis_variant": "fixed_interval_smoothed",
        }
    for axis, column in (("roll", "roll_rad"), ("pitch", "pitch_rad"), ("yaw", "yaw_enu_rad")):
        registry[column] = {
            **world,
            "quantity": f"orientation_{axis}",
            "unit": "rad",
            "component": axis,
            "vector_group": "body_to_world_enu_euler_zyx",
            "smoothing": "fixed_interval",
            "processing_role": "primary_analysis",
            "inspection_visibility": "standard",
            "analysis_variant": "fixed_interval_smoothed",
            "display_name": f"World orientation {axis} — fixed interval",
        }
    if config.inertial_dynamics_enabled:
        for axis in "xyz":
            registry[f"specific_force_body_{axis}_m_s2"] = {
                "sensor": sensor_id, "domain": "frame", "coordinate_frame": "body_local",
                "source": "inertial_estimate", "quantity": "specific_force", "unit": "m/s^2",
                "component": axis, "vector_group": "specific_force_body",
                "display_name": _vector_display_name("Frame", "specific force", axis, "body_local"),
            }
            registry[f"gravity_body_{axis}_m_s2"] = {
                "sensor": sensor_id, "domain": "frame", "coordinate_frame": "body_local",
                "source": "inertial_estimate", "quantity": "gravity", "unit": "m/s^2",
                "component": axis, "vector_group": "gravity_body",
                "display_name": _vector_display_name("Frame", "gravity", axis, "body_local"),
            }
            registry[f"linear_accel_body_{axis}_m_s2"] = {
                "sensor": sensor_id, "domain": "frame", "coordinate_frame": "body_local",
                "source": "inertial_estimate", "quantity": "linear_acceleration", "unit": "m/s^2",
                "component": axis, "vector_group": "linear_acceleration_body",
                "display_name": _vector_display_name("Frame", "linear acceleration", axis, "body_local"),
            }
        if config.inertial_dynamics_include_magnitudes:
            for column, quantity in (
                ("specific_force_body_norm_g", "specific_force_magnitude"),
                ("linear_accel_body_norm_g", "linear_acceleration_magnitude"),
                ("linear_accel_body_horizontal_g", "linear_acceleration_horizontal_magnitude"),
            ):
                registry[column] = {
                    "sensor": sensor_id, "domain": "frame", "coordinate_frame": "body_local",
                    "source": "inertial_estimate", "quantity": quantity, "unit": "g",
                }
        if config.inertial_dynamics_include_world_frame:
            for axis in "xyz":
                for prefix, quantity in (
                    ("gravity_enu", "gravity"),
                    ("specific_force_enu", "specific_force"),
                    ("linear_accel_enu", "linear_acceleration"),
                ):
                    registry[f"{prefix}_{axis}_m_s2"] = {
                        **world, "source": "inertial_estimate", "quantity": quantity,
                        "unit": "m/s^2", "component": axis, "vector_group": prefix,
                        "display_name": _vector_display_name("World", quantity.replace("_", " "), axis, "enu"),
                    }
                if config.inertial_dynamics_include_angular_kinematics:
                    registry[f"angular_velocity_enu_{axis}_rad_s"] = {
                        **world, "source": "inertial_estimate", "quantity": "angular_velocity",
                        "unit": "rad/s", "component": axis, "vector_group": "angular_velocity_enu",
                        "display_name": _vector_display_name("World", "angular velocity", axis, "enu"),
                    }
            if config.inertial_dynamics_include_magnitudes:
                registry["linear_accel_enu_horizontal_g"] = {
                    **world, "source": "inertial_estimate", "quantity": "linear_acceleration_horizontal_magnitude", "unit": "g",
                }
            if config.inertial_dynamics_include_angular_kinematics:
                registry["turn_rate_world_up_rad_s"] = {
                    **world, "source": "inertial_estimate", "quantity": "turn_rate", "unit": "rad/s",
                }
        if config.inertial_dynamics_include_angular_kinematics:
            registry["angular_speed_body_rad_s"] = {
                "sensor": sensor_id, "domain": "frame", "coordinate_frame": "body_local",
                "source": "inertial_estimate", "quantity": "angular_speed", "unit": "rad/s",
            }
    return registry


def _world_yaw_smoother(
    *,
    time: np.ndarray,
    segment: np.ndarray,
    quaternions: np.ndarray,
    gyro: np.ndarray,
    cumulative_course_correction: np.ndarray,
    accepted_observations: list[dict[str, float]],
    config: AttitudeConfig,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Fixed-interval yaw smoother, with conservative continuity-gap bridges.

    The causal estimate applies each GPS correction as a world-Z quaternion.
    Removing the cumulative correction recovers a gravity/gyro-relative yaw
    trajectory.  GPS course observations then estimate the world-Z phase over
    the *whole* logical continuity group, including samples preceding its
    first observation.  A short physical IMU gap is joined only when its gyro
    implied rotation is bounded by the configured bridge policy.
    """
    count = len(time)
    yaw = np.full(count, np.nan)
    sigma_deg = np.full(count, np.nan)
    state = np.full(count, _WORLD_YAW_UNOBSERVED, dtype=np.uint8)
    group = np.full(count, -1, dtype=np.int32)
    bridged_before = np.zeros(count, dtype=bool)
    report: dict[str, Any] = {
        "enabled": bool(config.world_yaw_smoother_enabled),
        "logical_groups": 0,
        "groups_with_course": 0,
        "accepted_course_observations": int(len(accepted_observations)),
        "bridged_gaps": [],
        "unbridged_boundaries": 0,
        "output_samples": 0,
    }
    if not config.world_yaw_smoother_enabled or count == 0:
        return {
            "yaw": yaw,
            "sigma_deg": sigma_deg,
            "state": state,
            "group": group,
            "bridged_before": bridged_before,
        }, report

    finite = np.isfinite(time) & np.isfinite(quaternions).all(axis=1) & np.isfinite(cumulative_course_correction)
    relative_q = np.full_like(quaternions, np.nan)
    for index in np.flatnonzero(finite):
        correction = _quaternion_from_rotation_vector(
            np.array([0.0, 0.0, -cumulative_course_correction[index]], dtype=float)
        )
        relative_q[index] = _normalise_quaternion(_quaternion_multiply(correction, quaternions[index]))

    # Original IMU segments are ordered contiguous ranges.  Join adjacent
    # ranges only after using the nearby measured angular rate to predict a
    # bounded physical rotation across the missing interval.
    ranges: list[np.ndarray] = []
    start = 0
    for index in range(1, count + 1):
        if index == count or segment[index] != segment[start]:
            ranges.append(np.arange(start, index, dtype=int))
            start = index
    logical_ranges: list[np.ndarray] = []
    current_parts: list[np.ndarray] = []
    phase = 0.0
    previous: Optional[np.ndarray] = None
    for source_range in ranges:
        valid_range = source_range[finite[source_range]]
        bridge = False
        gap_s = math.nan
        if previous is not None and valid_range.size and previous.size:
            previous_last = int(previous[-1])
            current_first = int(valid_range[0])
            gap_s = float(time[current_first] - time[previous_last])
            gyro_pair = (gyro[previous_last] + gyro[current_first]) * 0.5
            rotation_deg = math.degrees(float(np.linalg.norm(gyro_pair)) * gap_s) if np.isfinite(gyro_pair).all() else math.inf
            bridge = (
                0.0 < gap_s <= config.world_yaw_max_bridge_gap_s
                and rotation_deg <= config.world_yaw_bridge_max_rotation_deg
            )
            if bridge:
                previous_q = _normalise_quaternion(
                    _quaternion_multiply(
                        _quaternion_from_rotation_vector(np.array([0.0, 0.0, phase])),
                        relative_q[previous_last],
                    )
                )
                predicted_q = _normalise_quaternion(
                    _quaternion_multiply(previous_q, _quaternion_from_rotation_vector(gyro_pair * gap_s))
                )
                adjustment = _quaternion_multiply(predicted_q, _quaternion_inverse(relative_q[current_first]))
                phase = _euler_zyx(adjustment)[2]
                bridged_before[current_first] = True
                report["bridged_gaps"].append(
                    {
                        "before_segment": int(segment[previous_last]),
                        "after_segment": int(segment[current_first]),
                        "gap_s": gap_s,
                        "predicted_rotation_deg": rotation_deg,
                    }
                )
            else:
                report["unbridged_boundaries"] += 1
        if not bridge and current_parts:
            logical_ranges.append(np.concatenate(current_parts))
            current_parts = []
            phase = 0.0
        current_parts.append(source_range)
        previous = valid_range
    if current_parts:
        logical_ranges.append(np.concatenate(current_parts))

    # Recreate the phase for every original range, in logical-range order.
    range_phase = np.zeros(len(ranges), dtype=float)
    phase = 0.0
    for range_index, source_range in enumerate(ranges):
        if range_index == 0:
            range_phase[range_index] = phase
            continue
        previous_range = ranges[range_index - 1]
        previous_valid = previous_range[finite[previous_range]]
        current_valid = source_range[finite[source_range]]
        if previous_valid.size and current_valid.size:
            previous_last = int(previous_valid[-1])
            current_first = int(current_valid[0])
            gap_s = float(time[current_first] - time[previous_last])
            gyro_pair = (gyro[previous_last] + gyro[current_first]) * 0.5
            rotation_deg = math.degrees(float(np.linalg.norm(gyro_pair)) * gap_s) if np.isfinite(gyro_pair).all() else math.inf
            if 0.0 < gap_s <= config.world_yaw_max_bridge_gap_s and rotation_deg <= config.world_yaw_bridge_max_rotation_deg:
                previous_q = _normalise_quaternion(
                    _quaternion_multiply(
                        _quaternion_from_rotation_vector(np.array([0.0, 0.0, phase])),
                        relative_q[previous_last],
                    )
                )
                predicted_q = _normalise_quaternion(
                    _quaternion_multiply(previous_q, _quaternion_from_rotation_vector(gyro_pair * gap_s))
                )
                phase = _euler_zyx(_quaternion_multiply(predicted_q, _quaternion_inverse(relative_q[current_first])))[2]
            else:
                phase = 0.0
        else:
            phase = 0.0
        range_phase[range_index] = phase

    relative_yaw = np.full(count, np.nan)
    for range_index, source_range in enumerate(ranges):
        for index in source_range[finite[source_range]]:
            relative_yaw[index] = _wrap_pi(_euler_zyx(relative_q[index])[2] + range_phase[range_index])

    observations_by_index: dict[int, list[dict[str, float]]] = {}
    for observation in accepted_observations:
        index = int(observation["index"])
        if 0 <= index < count and math.isfinite(relative_yaw[index]):
            observations_by_index.setdefault(index, []).append(observation)

    for group_index, indices in enumerate(logical_ranges):
        valid_indices = indices[np.isfinite(relative_yaw[indices])]
        if not valid_indices.size:
            continue
        group[valid_indices] = group_index
        relative_unwrapped = np.unwrap(relative_yaw[valid_indices])
        position_by_index = {int(index): position for position, index in enumerate(valid_indices)}
        anchors: list[tuple[int, float, float]] = []
        for index, observations in observations_by_index.items():
            position = position_by_index.get(index)
            if position is None:
                continue
            weights = np.array([1.0 / max(item["accuracy_rad"], math.radians(0.5)) ** 2 for item in observations])
            courses = np.array([item["course_enu_rad"] for item in observations])
            course = math.atan2(float(np.sum(weights * np.sin(courses))), float(np.sum(weights * np.cos(courses))))
            accuracy = math.sqrt(1.0 / float(np.sum(weights)))
            anchors.append((position, _wrap_pi(course - relative_unwrapped[position]), accuracy))
        if not anchors:
            continue
        report["groups_with_course"] += 1
        anchors.sort(key=lambda item: item[0])
        anchor_position = np.array([item[0] for item in anchors], dtype=float)
        anchor_offset = np.unwrap(np.array([item[1] for item in anchors], dtype=float))
        anchor_variance = np.array([item[2] ** 2 for item in anchors], dtype=float)
        positions = np.arange(len(valid_indices), dtype=float)
        offsets = np.interp(positions, anchor_position, anchor_offset)
        variances = np.interp(positions, anchor_position, anchor_variance)
        anchor_times = time[valid_indices[anchor_position.astype(int)]]
        distance_to_anchor = np.min(np.abs(time[valid_indices, None] - anchor_times[None, :]), axis=1)
        drift_sigma_rad = math.radians(config.world_yaw_drift_deg_s) * distance_to_anchor
        yaw[valid_indices] = np.array([_wrap_pi(value) for value in relative_unwrapped + offsets])
        sigma_deg[valid_indices] = np.degrees(np.sqrt(variances + drift_sigma_rad**2))
        first_anchor = int(anchor_position[0])
        last_anchor = int(anchor_position[-1])
        local_state = np.full(len(valid_indices), _WORLD_YAW_SMOOTHED, dtype=np.uint8)
        local_state[:first_anchor] = _WORLD_YAW_BACKFILLED
        local_state[last_anchor + 1 :] = _WORLD_YAW_EXTRAPOLATED
        state[valid_indices] = local_state

    report["logical_groups"] = int(len(logical_ranges))
    report["output_samples"] = int(np.count_nonzero(np.isfinite(yaw)))
    report["output_fraction"] = float(np.mean(np.isfinite(yaw))) if count else 0.0
    report["state_names"] = dict(_WORLD_YAW_STATE_NAMES)
    return {
        "yaw": yaw,
        "sigma_deg": sigma_deg,
        "state": state,
        "group": group,
        "bridged_before": bridged_before,
    }, report


def _inertial_dynamics(
    *,
    accel_body: np.ndarray,
    gyro_body: np.ndarray,
    quaternions: np.ndarray,
    config: AttitudeConfig,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Materialise attitude-dependent inertial vectors without changing evidence."""
    count = len(accel_body)
    output: dict[str, np.ndarray] = {}
    orientation_valid = np.isfinite(quaternions).all(axis=1)
    report: dict[str, Any] = {
        "enabled": bool(config.inertial_dynamics_enabled),
        "world_frame_enabled": bool(config.inertial_dynamics_include_world_frame),
        "angular_kinematics_enabled": bool(config.inertial_dynamics_include_angular_kinematics),
        "magnitudes_enabled": bool(config.inertial_dynamics_include_magnitudes),
        "fixed_interval_orientation_samples": int(np.count_nonzero(orientation_valid)),
        "world_frame_samples": 0,
    }
    if not config.inertial_dynamics_enabled:
        return output, report

    causal_valid = orientation_valid & np.isfinite(accel_body).all(axis=1)
    gravity_body = np.full((count, 3), np.nan)
    for index in np.flatnonzero(causal_valid):
        gravity_body[index] = _rotation_matrix(quaternions[index]).T @ np.array(
            [0.0, 0.0, STANDARD_GRAVITY_M_S2]
        )
    linear_body = accel_body - gravity_body
    for component, axis in enumerate("xyz"):
        output[f"specific_force_body_{axis}_m_s2"] = accel_body[:, component]
        output[f"gravity_body_{axis}_m_s2"] = gravity_body[:, component]
        output[f"linear_accel_body_{axis}_m_s2"] = linear_body[:, component]

    if config.inertial_dynamics_include_magnitudes:
        output["specific_force_body_norm_g"] = np.linalg.norm(accel_body, axis=1) / STANDARD_GRAVITY_M_S2
        output["linear_accel_body_norm_g"] = np.linalg.norm(linear_body, axis=1) / STANDARD_GRAVITY_M_S2
        output["linear_accel_body_horizontal_g"] = np.linalg.norm(linear_body[:, :2], axis=1) / STANDARD_GRAVITY_M_S2

    if config.inertial_dynamics_include_world_frame:
        specific_force_enu = np.full((count, 3), np.nan)
        linear_enu = np.full((count, 3), np.nan)
        angular_velocity_enu = np.full((count, 3), np.nan)
        for index in np.flatnonzero(orientation_valid):
            rotation = _rotation_matrix(quaternions[index])
            specific_force_enu[index] = rotation @ accel_body[index]
            linear_enu[index] = specific_force_enu[index] - np.array([0.0, 0.0, STANDARD_GRAVITY_M_S2])
            if config.inertial_dynamics_include_angular_kinematics and np.isfinite(gyro_body[index]).all():
                angular_velocity_enu[index] = rotation @ gyro_body[index]
        for component, axis in enumerate("xyz"):
            output[f"gravity_enu_{axis}_m_s2"] = np.full(count, STANDARD_GRAVITY_M_S2 if axis == "z" else 0.0)
            output[f"specific_force_enu_{axis}_m_s2"] = specific_force_enu[:, component]
            output[f"linear_accel_enu_{axis}_m_s2"] = linear_enu[:, component]
            if config.inertial_dynamics_include_angular_kinematics:
                output[f"angular_velocity_enu_{axis}_rad_s"] = angular_velocity_enu[:, component]
        if config.inertial_dynamics_include_magnitudes:
            output["linear_accel_enu_horizontal_g"] = np.linalg.norm(linear_enu[:, :2], axis=1) / STANDARD_GRAVITY_M_S2
        if config.inertial_dynamics_include_angular_kinematics:
            output["turn_rate_world_up_rad_s"] = angular_velocity_enu[:, 2]
            output["angular_speed_body_rad_s"] = np.linalg.norm(gyro_body, axis=1)
        report["world_frame_samples"] = int(np.count_nonzero(orientation_valid))
    elif config.inertial_dynamics_include_angular_kinematics:
        output["angular_speed_body_rad_s"] = np.linalg.norm(gyro_body, axis=1)

    return output, report


def estimate_attitude(
    imu: pd.DataFrame,
    *,
    gps: Optional[pd.DataFrame] = None,
    startup_bias_rad_s: Optional[np.ndarray] = None,
    config: Optional[AttitudeConfig] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Estimate a gravity- and course-corrected body-to-ENU attitude stream."""
    if not isinstance(imu, pd.DataFrame) or imu.empty:
        raise ValueError("attitude estimation requires a non-empty IMU stream")
    required = ["time_s", "continuity_segment"] + [f"body_{vector}_{axis}_{unit}" for vector, unit in (("accel", "m_s2"), ("gyro", "rad_s")) for axis in "xyz"]
    missing = [column for column in required if column not in imu.columns]
    if missing:
        raise ValueError("IMU stream is missing body-frame attitude inputs: " + ", ".join(missing))
    settings = config or AttitudeConfig()
    time = _numeric_column(imu, "time_s")
    segment = pd.to_numeric(imu["continuity_segment"], errors="coerce").fillna(-1).to_numpy(dtype=np.int64)
    accel = np.column_stack([_numeric_column(imu, f"body_accel_{axis}_m_s2") for axis in "xyz"])
    gyro = np.column_stack([_numeric_column(imu, f"body_gyro_{axis}_rad_s") for axis in "xyz"])
    bias = np.asarray(startup_bias_rad_s if startup_bias_rad_s is not None else np.zeros(3), dtype=float)
    observations = _course_observations(gps, settings)
    observation_index = 0
    q = np.array([1.0, 0.0, 0.0, 0.0])
    last_time = math.nan
    last_segment = -1
    last_accel = np.full(3, np.nan)
    accel_norm_history: list[tuple[float, float]] = []
    yaw_variance = math.radians(180.0) ** 2
    last_course_time = math.nan
    yaw_observed = False

    result = np.full((len(imu.index), 4), np.nan)
    roll_pitch_yaw = np.full((len(imu.index), 3), np.nan)
    gravity_weight = np.zeros(len(imu.index), dtype=float)
    gravity_rejection = np.zeros(len(imu.index), dtype=np.uint8)
    course_weight = np.zeros(len(imu.index), dtype=float)
    course_innovation = np.full(len(imu.index), np.nan)
    course_rejection = np.zeros(len(imu.index), dtype=np.uint8)
    yaw_sigma = np.full(len(imu.index), np.nan)
    state = np.full(len(imu.index), _STATE_GRAVITY_ALIGNED, dtype=np.uint8)
    cumulative_course_correction = np.zeros(len(imu.index), dtype=float)
    accepted_course_observations: list[dict[str, float]] = []
    cumulative_correction = 0.0

    for index in range(len(imu.index)):
        if not math.isfinite(time[index]) or not np.isfinite(accel[index]).all() or not np.isfinite(gyro[index]).all():
            gravity_rejection[index] = 1
            course_rejection[index] = 1
            continue
        boundary = index == 0 or segment[index] != last_segment
        accel_norm = float(np.linalg.norm(accel[index]))
        norm_error_g = abs(accel_norm - STANDARD_GRAVITY_M_S2) / STANDARD_GRAVITY_M_S2
        boundary_dt = float(time[index] - last_time) if index > 0 else math.nan
        short_boundary_gap = boundary and math.isfinite(boundary_dt) and 0.0 < boundary_dt <= 0.5
        # Preserve short-gap history so the first post-gap sample is assessed
        # by the normal gravity gate, including variance and jerk. A long gap
        # has no meaningful acceleration continuity and starts afresh.
        if boundary and not short_boundary_gap:
            accel_norm_history = []
        accel_norm_history.append((float(time[index]), accel_norm))
        while accel_norm_history and time[index] - accel_norm_history[0][0] > settings.gravity_window_s:
            accel_norm_history.pop(0)
        norm_std_g = float(np.std([value for _, value in accel_norm_history]) / STANDARD_GRAVITY_M_S2)
        jerk = 0.0
        if index > 0 and (not boundary or short_boundary_gap):
            dt_for_jerk = max(float(time[index] - time[index - 1]), 1.0e-3)
            jerk = float(np.linalg.norm(accel[index] - last_accel) / dt_for_jerk)
        if norm_error_g > settings.gravity_norm_tolerance_g:
            gravity_rejection[index] = 2
        elif norm_std_g > settings.gravity_norm_std_max_g:
            gravity_rejection[index] = 3
        elif jerk > settings.gravity_jerk_max_m_s3:
            gravity_rejection[index] = 4
        accel_initialisation_valid = gravity_rejection[index] == 0
        if boundary:
            # A discontinuity marks missing evidence, not necessarily a new
            # physical attitude.  Do not turn a dynamic first sample after a
            # short gap into a new attitude reference: propagate the prior
            # state when possible and reserve accelerometer initialisation for
            # samples that pass the same magnitude gate as gravity correction.
            if accel_initialisation_valid:
                q = _quaternion_from_two_vectors(accel[index], np.array([0.0, 0.0, STANDARD_GRAVITY_M_S2]))
            elif index > 0:
                dt = float(time[index] - last_time)
                if math.isfinite(dt) and 0.0 < dt <= 0.5:
                    q = _normalise_quaternion(
                        _quaternion_multiply(q, _quaternion_from_rotation_vector((gyro[index] - bias) * dt))
                    )
            last_time = time[index]
            last_segment = segment[index]
            last_accel = accel[index]
            yaw_variance = math.radians(180.0) ** 2
            yaw_observed = False
            last_course_time = math.nan
            cumulative_correction = 0.0
        else:
            dt = float(time[index] - last_time)
            if not math.isfinite(dt) or dt <= 0.0 or dt > 0.5:
                if accel_initialisation_valid:
                    q = _quaternion_from_two_vectors(accel[index], np.array([0.0, 0.0, STANDARD_GRAVITY_M_S2]))
                yaw_variance = math.radians(180.0) ** 2
                yaw_observed = False
                cumulative_correction = 0.0
            else:
                q = _normalise_quaternion(_quaternion_multiply(q, _quaternion_from_rotation_vector((gyro[index] - bias) * dt)))
                yaw_variance += (settings.gyro_noise_rad_s * dt) ** 2
            last_time = time[index]

        if gravity_rejection[index] == 0:
            weight = settings.gravity_gain * (1.0 - norm_error_g / settings.gravity_norm_tolerance_g)
            observed_world = _rotation_matrix(q) @ (accel[index] / accel_norm)
            error_world = np.cross(observed_world, np.array([0.0, 0.0, 1.0]))
            q = _normalise_quaternion(_quaternion_multiply(_quaternion_from_rotation_vector(error_world * weight), q))
            gravity_weight[index] = weight
        last_accel = accel[index]

        while observation_index < len(observations) and observations[observation_index]["time_s"] <= time[index]:
            observation = observations[observation_index]
            forward_world = _rotation_matrix(q)[:, 0]
            predicted_course = math.atan2(float(forward_world[1]), float(forward_world[0]))
            innovation = _wrap_pi(observation["course_enu_rad"] - predicted_course)
            course_innovation[index] = innovation
            if abs(innovation) > math.radians(settings.course_max_innovation_deg) and yaw_observed:
                course_rejection[index] = 2
            else:
                observation_variance = max(observation["accuracy_rad"], math.radians(0.5)) ** 2
                gain = yaw_variance / (yaw_variance + observation_variance)
                if not yaw_observed:
                    gain = 1.0
                gain = min(1.0, max(0.0, gain * settings.course_gain if yaw_observed else gain))
                q = _normalise_quaternion(
                    _quaternion_multiply(_quaternion_from_rotation_vector(np.array([0.0, 0.0, innovation * gain])), q)
                )
                correction = innovation * gain
                cumulative_correction += correction
                yaw_variance = max(1.0e-12, (1.0 - gain) * yaw_variance)
                course_weight[index] = gain
                yaw_observed = True
                last_course_time = observation["time_s"]
                accepted_course_observations.append(
                    {
                        "index": float(index),
                        "time_s": float(time[index]),
                        "course_enu_rad": float(observation["course_enu_rad"]),
                        "accuracy_rad": float(observation["accuracy_rad"]),
                    }
                )
            observation_index += 1

        result[index] = q
        roll_pitch_yaw[index] = _euler_zyx(q)
        yaw_sigma[index] = math.degrees(math.sqrt(yaw_variance))
        if yaw_observed:
            state[index] = (
                _STATE_WORLD_ENU_CONSTRAINED
                if time[index] - last_course_time <= settings.course_stale_after_s
                else _STATE_WORLD_ENU_DEGRADED
            )
        cumulative_course_correction[index] = cumulative_correction

    smoother, smoother_report = _world_yaw_smoother(
        time=time,
        segment=segment,
        quaternions=result,
        gyro=gyro,
        cumulative_course_correction=cumulative_course_correction,
        accepted_observations=accepted_course_observations,
        config=settings,
    )
    yaw_for_tilt = np.where(np.isfinite(smoother["yaw"]), smoother["yaw"], roll_pitch_yaw[:, 2])
    reference_quaternions = result.copy()
    for index in np.flatnonzero(np.isfinite(result).all(axis=1) & np.isfinite(yaw_for_tilt)):
        roll, pitch, _ = _euler_zyx(result[index])
        reference_quaternions[index] = _quaternion_from_euler_zyx(roll, pitch, yaw_for_tilt[index])
    gps_acceleration_enu, gps_acceleration_report = _gps_translational_acceleration(
        imu_time=time,
        gps=gps,
        config=settings,
    )
    tilt, tilt_report = _fixed_interval_tilt_smoother(
        time=time,
        segment=segment,
        accel_body=accel,
        gyro_body=gyro - bias,
        reference_quaternions=reference_quaternions,
        yaw=yaw_for_tilt,
        gps_acceleration_enu=gps_acceleration_enu,
        config=settings,
    )

    dynamics, dynamics_report = _inertial_dynamics(
        accel_body=accel,
        gyro_body=gyro - bias - tilt["gyro_bias_body_rad_s"],
        quaternions=tilt["quaternions"],
        config=settings,
    )

    output_columns: dict[str, np.ndarray] = {
            "time_s": time,
            "continuity_segment": segment,
            "q_body_to_world_enu_w": tilt["quaternions"][:, 0],
            "q_body_to_world_enu_x": tilt["quaternions"][:, 1],
            "q_body_to_world_enu_y": tilt["quaternions"][:, 2],
            "q_body_to_world_enu_z": tilt["quaternions"][:, 3],
            "roll_rad": tilt["euler"][:, 0],
            "pitch_rad": tilt["euler"][:, 1],
            "yaw_enu_rad": tilt["euler"][:, 2],
            "yaw_sigma_deg": yaw_sigma,
            "gravity_update_weight": gravity_weight,
            "gravity_rejection_code": gravity_rejection,
            "course_update_weight": course_weight,
            "course_innovation_rad": course_innovation,
            "course_rejection_code": course_rejection,
            "attitude_state_code": state,
            "fixed_interval_gravity_observation_accepted": tilt["gravity_observation_accepted"],
            "fixed_interval_gravity_innovation_rad": tilt["gravity_innovation_rad"],
            "gps_translational_compensation_used": tilt["gps_compensation_used"],
            "fixed_interval_tilt_sigma_deg": tilt["tilt_sigma_deg"],
            "fixed_interval_gyro_bias_body_x_rad_s": tilt["gyro_bias_body_rad_s"][:, 0],
            "fixed_interval_gyro_bias_body_y_rad_s": tilt["gyro_bias_body_rad_s"][:, 1],
            "fixed_interval_gyro_bias_body_z_rad_s": tilt["gyro_bias_body_rad_s"][:, 2],
    }
    output_columns.update(dynamics)
    output = pd.DataFrame(output_columns)
    report = {
        "schema": ATTITUDE_QC_SCHEMA,
        "status": "ok" if np.any(state != _STATE_GRAVITY_ALIGNED) else "gravity_only",
        "sample_count": int(len(output.index)),
        "continuity_segment_count": int(len(np.unique(segment))),
        "course_observation_candidates": int(len(observations)),
        "course_updates_accepted": int(np.count_nonzero(course_weight)),
        "course_updates_rejected": int(np.count_nonzero(course_rejection == 2)),
        "gravity_updates_accepted": int(np.count_nonzero(gravity_weight)),
        "gravity_rejections": {
            "missing_input": int(np.count_nonzero(gravity_rejection == 1)),
            "magnitude": int(np.count_nonzero(gravity_rejection == 2)),
            "variance": int(np.count_nonzero(gravity_rejection == 3)),
            "jerk": int(np.count_nonzero(gravity_rejection == 4)),
        },
        "yaw_observed_fraction": float(np.mean(state != _STATE_GRAVITY_ALIGNED)),
        "startup_bias_rad_s": bias.tolist(),
        "state_names": dict(_STATE_NAMES),
        "config": asdict(settings),
        "world_yaw_smoother": smoother_report,
        "fixed_interval_tilt_smoother": tilt_report,
        "gps_translational_acceleration": gps_acceleration_report,
        "inertial_dynamics": dynamics_report,
    }
    return output, report


def build_attitude_stream(
    session: dict[str, Any],
    sensor: str,
    *,
    gps_stream_name: str = "gps_logger",
    config: Optional[AttitudeConfig] = None,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Build the fused inertial stream for one accepted, frame-mounted IMU."""
    build_imu_streams(session, strict=False)
    build_logger_gps_route_stream(session)
    sensor_id = canonical_sensor_id(sensor)
    streams = session.get("stream_dfs") if isinstance(session.get("stream_dfs"), Mapping) else {}
    secondary = session.get("meta", {}).get("secondary_streams", {}) if isinstance(session.get("meta"), Mapping) else {}
    imu_name = next(
        (
            str(name)
            for name, metadata in secondary.items()
            if isinstance(metadata, Mapping)
            and metadata.get("schema") == IMU_STREAM_SCHEMA
            and canonical_sensor_id(metadata.get("sensor")) == sensor_id
        ),
        None,
    )
    if not imu_name or not isinstance(streams.get(imu_name), pd.DataFrame):
        raise ValueError(f"No extracted IMU stream is available for sensor {sensor!r}")
    imu_meta = secondary.get(imu_name, {})
    if not isinstance(imu_meta, Mapping) or imu_meta.get("domain") != "frame":
        raise ValueError("world-frame attitude currently requires a frame-mounted IMU")
    gps = streams.get(gps_stream_name)
    output, report = estimate_attitude(
        streams[imu_name], gps=gps if isinstance(gps, pd.DataFrame) else None, startup_bias_rad_s=_startup_bias_rad_s(session, sensor_id, streams[imu_name]), config=config
    )
    metadata = {
        "schema": INERTIAL_STREAM_SCHEMA,
        "kind": "inertial",
        "sensor": sensor_id,
        "imu_stream_name": imu_name,
        "gps_stream_name": gps_stream_name if isinstance(gps, pd.DataFrame) else None,
        "coordinate_transform": "body_local_to_world_enu",
        "quaternion_order": "wxyz",
        "quaternion_direction": "body_local_to_world_enu",
        "euler_convention": "intrinsic_zyx_rad",
        "state_names": dict(_STATE_NAMES),
        "report_ref": f"qc.attitude.{sensor_id}",
        "config": report["config"],
        "signals": _inertial_signal_registry(sensor_id, config or AttitudeConfig()),
    }
    return output, report, metadata


def build_attitude_streams(
    session: dict[str, Any],
    *,
    sensors: Optional[list[str]] = None,
    gps_stream_name: str = "gps_logger",
    config: Optional[AttitudeConfig] = None,
) -> dict[str, Any]:
    """Opt-in registration of first-slice fused inertial streams in a session."""
    build_imu_streams(session, strict=False)
    selected = {canonical_sensor_id(sensor) for sensor in sensors} if sensors else None
    configs = session.get("meta", {}).get("imu_configs", {}) if isinstance(session.get("meta"), Mapping) else {}
    for sensor, imu_config in configs.items() if isinstance(configs, Mapping) else []:
        sensor_id = canonical_sensor_id(sensor)
        if selected is not None and sensor_id not in selected:
            continue
        if not isinstance(imu_config, Mapping) or imu_config.get("domain") != "frame":
            continue
        try:
            output, report, metadata = build_attitude_stream(session, sensor_id, gps_stream_name=gps_stream_name, config=config)
        except ValueError as exc:
            session.setdefault("qc", {}).setdefault("attitude", {})[sensor_id] = {
                "schema": ATTITUDE_QC_SCHEMA,
                "status": "failed",
                "errors": [str(exc)],
            }
            continue
        stream_name = f"inertial_{sensor_id}"
        session.setdefault("stream_dfs", {})[stream_name] = output
        register_stream_metadata(session, stream_name=stream_name, kind="intermittent", time_col="time_s", notes="Offline fused inertial orientation and dynamics product")
        metadata["stream_name"] = stream_name
        session.setdefault("meta", {}).setdefault("secondary_streams", {})[stream_name] = metadata
        session.setdefault("qc", {}).setdefault("attitude", {})[sensor_id] = copy.deepcopy(report)
    meta = session.setdefault("meta", {})
    qc = session.get("qc")
    if isinstance(meta, dict) and isinstance(qc, Mapping):
        attitude_qc = qc.get("attitude")
        if isinstance(attitude_qc, Mapping):
            meta["attitude_qc"] = copy.deepcopy(dict(attitude_qc))
    return session
