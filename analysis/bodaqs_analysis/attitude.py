"""Versioned offline frame-IMU attitude product.

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


ATTITUDE_STREAM_SCHEMA = "bodaqs.attitude_stream.v1"
ATTITUDE_QC_SCHEMA = "bodaqs.attitude_qc.v1"
STANDARD_GRAVITY_M_S2 = 9.80665

_STATE_GRAVITY_ALIGNED = 0
_STATE_WORLD_ENU_CONSTRAINED = 1
_STATE_WORLD_ENU_DEGRADED = 2
_STATE_NAMES = {
    _STATE_GRAVITY_ALIGNED: "gravity_aligned",
    _STATE_WORLD_ENU_CONSTRAINED: "world_enu_constrained",
    _STATE_WORLD_ENU_DEGRADED: "world_enu_degraded",
}


@dataclass(frozen=True)
class AttitudeConfig:
    """First-slice, deliberately conservative correction settings."""

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

    for index in range(len(imu.index)):
        if not math.isfinite(time[index]) or not np.isfinite(accel[index]).all() or not np.isfinite(gyro[index]).all():
            gravity_rejection[index] = 1
            course_rejection[index] = 1
            continue
        boundary = index == 0 or segment[index] != last_segment
        accel_norm = float(np.linalg.norm(accel[index]))
        if boundary:
            q = _quaternion_from_two_vectors(accel[index], np.array([0.0, 0.0, STANDARD_GRAVITY_M_S2]))
            last_time = time[index]
            last_segment = segment[index]
            last_accel = accel[index]
            accel_norm_history = []
            yaw_variance = math.radians(180.0) ** 2
            yaw_observed = False
            last_course_time = math.nan
        else:
            dt = float(time[index] - last_time)
            if not math.isfinite(dt) or dt <= 0.0 or dt > 0.5:
                q = _quaternion_from_two_vectors(accel[index], np.array([0.0, 0.0, STANDARD_GRAVITY_M_S2]))
                yaw_variance = math.radians(180.0) ** 2
                yaw_observed = False
            else:
                q = _normalise_quaternion(_quaternion_multiply(q, _quaternion_from_rotation_vector((gyro[index] - bias) * dt)))
                yaw_variance += (settings.gyro_noise_rad_s * dt) ** 2
            last_time = time[index]

        norm_error_g = abs(accel_norm - STANDARD_GRAVITY_M_S2) / STANDARD_GRAVITY_M_S2
        accel_norm_history.append((float(time[index]), accel_norm))
        while accel_norm_history and time[index] - accel_norm_history[0][0] > settings.gravity_window_s:
            accel_norm_history.pop(0)
        norm_std_g = float(np.std([value for _, value in accel_norm_history]) / STANDARD_GRAVITY_M_S2)
        jerk = 0.0
        if index > 0 and segment[index] == segment[index - 1]:
            dt_for_jerk = max(float(time[index] - time[index - 1]), 1.0e-3)
            jerk = float(np.linalg.norm(accel[index] - last_accel) / dt_for_jerk)
        if norm_error_g > settings.gravity_norm_tolerance_g:
            gravity_rejection[index] = 2
        elif norm_std_g > settings.gravity_norm_std_max_g:
            gravity_rejection[index] = 3
        elif jerk > settings.gravity_jerk_max_m_s3:
            gravity_rejection[index] = 4
        else:
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
                yaw_variance = max(1.0e-12, (1.0 - gain) * yaw_variance)
                course_weight[index] = gain
                yaw_observed = True
                last_course_time = observation["time_s"]
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

    output = pd.DataFrame(
        {
            "time_s": time,
            "continuity_segment": segment,
            "q_body_to_world_enu_w": result[:, 0],
            "q_body_to_world_enu_x": result[:, 1],
            "q_body_to_world_enu_y": result[:, 2],
            "q_body_to_world_enu_z": result[:, 3],
            "roll_rad": roll_pitch_yaw[:, 0],
            "pitch_rad": roll_pitch_yaw[:, 1],
            "yaw_enu_rad": roll_pitch_yaw[:, 2],
            "yaw_sigma_deg": yaw_sigma,
            "gravity_update_weight": gravity_weight,
            "gravity_rejection_code": gravity_rejection,
            "course_update_weight": course_weight,
            "course_innovation_rad": course_innovation,
            "course_rejection_code": course_rejection,
            "attitude_state_code": state,
        }
    )
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
    }
    return output, report


def build_attitude_stream(
    session: dict[str, Any],
    sensor: str,
    *,
    gps_stream_name: str = "gps_logger",
    config: Optional[AttitudeConfig] = None,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Build an attitude stream for one accepted, frame-mounted IMU."""
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
        "schema": ATTITUDE_STREAM_SCHEMA,
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
    }
    return output, report, metadata


def build_attitude_streams(
    session: dict[str, Any],
    *,
    sensors: Optional[list[str]] = None,
    gps_stream_name: str = "gps_logger",
    config: Optional[AttitudeConfig] = None,
) -> dict[str, Any]:
    """Opt-in registration of first-slice attitude streams in a session."""
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
        stream_name = f"attitude_{sensor_id}"
        session.setdefault("stream_dfs", {})[stream_name] = output
        register_stream_metadata(session, stream_name=stream_name, kind="intermittent", time_col="time_s", notes="Offline gravity/course-corrected attitude product")
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
