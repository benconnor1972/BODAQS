from __future__ import annotations

import copy
import math
from pathlib import Path
import re
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from .sensor_aliases import canonical_sensor_id
from .timebase import register_stream_metadata


IMU_QC_SCHEMA = "bodaqs.imu_qc.v1"
IMU_STREAM_SCHEMA = "bodaqs.imu_stream.v1"
STANDARD_GRAVITY_M_S2 = 9.80665
SEQUENCE_MODULUS = 1 << 24
NEAR_RAIL_COUNT = 32760
MAX_EVENT_RANGES = 64

STATUS_FLAGS: dict[str, int] = {
    "fifo_discontinuity_before": 0x0001,
    "queue_drop_before": 0x0002,
    "sensor_recovery_before": 0x0004,
    "timing_degraded": 0x0008,
    "sensor_time_estimated": 0x0010,
    "temperature_stale": 0x0020,
    "accel_near_rail": 0x0040,
    "gyro_near_rail": 0x0080,
}

_REQUIRED_SCALARS = {
    "sensor_time",
    "sample_sequence",
    "temperature_raw",
    "sample_age",
    "status",
    "sample_valid",
}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _finite_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _component_from_column(column: str, vector: str) -> str:
    match = re.search(rf"(?:^|_){vector}_([xyz])(?:_|$)", str(column).lower())
    return match.group(1) if match is not None else ""


def _semantic_name(info: Mapping[str, Any]) -> str:
    for key in ("quantity", "metric", "role"):
        value = _text(info.get(key)).lower()
        if value:
            return value
    return ""


def _discover_layouts(session: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    meta = session.get("meta") if isinstance(session, Mapping) else None
    channel_info = meta.get("channel_info") if isinstance(meta, Mapping) else None
    if not isinstance(channel_info, Mapping):
        return {}

    layouts: dict[str, dict[str, Any]] = {}
    for column, raw_info in channel_info.items():
        if not isinstance(column, str) or not isinstance(raw_info, Mapping):
            continue
        sensor = canonical_sensor_id(raw_info.get("sensor"))
        if not sensor:
            continue
        semantic = _semantic_name(raw_info)
        component = _text(raw_info.get("component")).lower()
        if semantic == "linear_acceleration_raw":
            component = component or _component_from_column(column, "accel")
            if component in {"x", "y", "z"}:
                layouts.setdefault(sensor, {"accel": {}, "gyro": {}, "scalar": {}})["accel"][component] = column
        elif semantic == "angular_velocity_raw":
            component = component or _component_from_column(column, "gyro")
            if component in {"x", "y", "z"}:
                layouts.setdefault(sensor, {"accel": {}, "gyro": {}, "scalar": {}})["gyro"][component] = column
        elif semantic in _REQUIRED_SCALARS:
            layouts.setdefault(sensor, {"accel": {}, "gyro": {}, "scalar": {}})["scalar"][semantic] = column

        if sensor in layouts:
            layout = layouts[sensor]
            layout.setdefault("domain", raw_info.get("domain"))
            layout.setdefault("end", raw_info.get("end"))
            layout.setdefault("mount_point", raw_info.get("mount_point"))

    return {
        sensor: layout
        for sensor, layout in layouts.items()
        if layout.get("accel") or layout.get("gyro") or "sample_valid" in layout.get("scalar", {})
    }


def _find_imu_config(session: Mapping[str, Any], sensor: str) -> Optional[dict[str, Any]]:
    meta = session.get("meta") if isinstance(session, Mapping) else None
    configs = meta.get("imu_configs") if isinstance(meta, Mapping) else None
    if not isinstance(configs, Mapping):
        return None
    direct = configs.get(sensor)
    if isinstance(direct, Mapping):
        return dict(direct)
    for key, value in configs.items():
        if canonical_sensor_id(key) == sensor and isinstance(value, Mapping):
            return dict(value)
    return None


def _signed_axis_matrix(transform: Any) -> Optional[np.ndarray]:
    if not isinstance(transform, Mapping):
        return None
    axes = [transform.get("body_x"), transform.get("body_y"), transform.get("body_z")]
    matrix = np.zeros((3, 3), dtype=float)
    used: set[int] = set()
    for row, token_value in enumerate(axes):
        token = _text(token_value).lower()
        if len(token) != 2 or token[0] not in "+-" or token[1] not in "xyz":
            return None
        source_axis = "xyz".index(token[1])
        if source_axis in used:
            return None
        used.add(source_axis)
        matrix[row, source_axis] = 1.0 if token[0] == "+" else -1.0
    if not np.isclose(np.linalg.det(matrix), 1.0):
        return None
    return matrix


def _config_values(config: Optional[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if not isinstance(config, Mapping):
        return {}, ["missing_imu_config"]

    effective = config.get("effective_config")
    effective = effective if isinstance(effective, Mapping) else {}
    sensor_time = config.get("sensor_time")
    sensor_time = sensor_time if isinstance(sensor_time, Mapping) else {}

    rate_hz = _finite_float(config.get("imu_rate_hz"))
    if rate_hz is None:
        accel_rate = _finite_float(effective.get("accel_odr_hz"))
        gyro_rate = _finite_float(effective.get("gyro_odr_hz"))
        if accel_rate is not None and gyro_rate is not None and np.isclose(accel_rate, gyro_rate):
            rate_hz = accel_rate
    accel_range_g = _finite_float(effective.get("accel_range_g"))
    gyro_range_dps = _finite_float(effective.get("gyro_range_dps"))
    tick_numerator_us = _finite_float(sensor_time.get("tick_numerator_us"))
    tick_denominator = _finite_float(sensor_time.get("tick_denominator"))
    tick_modulus = _finite_float(sensor_time.get("modulus_ticks"))
    mount_matrix = _signed_axis_matrix(config.get("mount_transform"))

    required = {
        "imu_rate_hz": rate_hz,
        "accel_range_g": accel_range_g,
        "gyro_range_dps": gyro_range_dps,
        "sensor_time_tick_numerator_us": tick_numerator_us,
        "sensor_time_tick_denominator": tick_denominator,
        "sensor_time_modulus_ticks": tick_modulus,
    }
    for key, value in required.items():
        if value is None or value <= 0:
            warnings.append(f"missing_or_invalid_{key}")
    if mount_matrix is None:
        warnings.append("missing_or_invalid_mount_transform")

    tick_period_s = None
    if tick_numerator_us is not None and tick_denominator is not None and tick_denominator > 0:
        tick_period_s = (tick_numerator_us / tick_denominator) / 1_000_000.0

    return {
        "rate_hz": rate_hz,
        "accel_range_g": accel_range_g,
        "gyro_range_dps": gyro_range_dps,
        "tick_period_s": tick_period_s,
        "tick_modulus": int(tick_modulus) if tick_modulus is not None and tick_modulus > 0 else None,
        "mount_matrix": mount_matrix,
    }, warnings


def _unwrap_modulo(values: np.ndarray, modulus: int) -> tuple[np.ndarray, np.ndarray]:
    raw = np.asarray(values, dtype=np.int64) % int(modulus)
    if raw.size == 0:
        return raw.copy(), np.asarray([], dtype=np.int64)
    raw_delta = np.diff(raw)
    half = int(modulus) // 2
    delta = raw_delta.copy()
    delta[raw_delta < -half] += int(modulus)
    delta[raw_delta > half] -= int(modulus)
    unwrapped = np.empty(raw.size, dtype=np.int64)
    unwrapped[0] = raw[0]
    if delta.size:
        unwrapped[1:] = raw[0] + np.cumsum(delta, dtype=np.int64)
    return unwrapped, delta


def _percentiles(values: np.ndarray) -> dict[str, Optional[float]]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return {"count": 0, "minimum": None, "median": None, "p95": None, "p99": None, "maximum": None}
    return {
        "count": int(finite.size),
        "minimum": float(np.min(finite)),
        "median": float(np.percentile(finite, 50)),
        "p95": float(np.percentile(finite, 95)),
        "p99": float(np.percentile(finite, 99)),
        "maximum": float(np.max(finite)),
    }


def _event_ranges(mask: np.ndarray, time_s: np.ndarray, sequence: np.ndarray) -> dict[str, Any]:
    selected = np.flatnonzero(np.asarray(mask, dtype=bool))
    if selected.size == 0:
        return {"sample_count": 0, "event_count": 0, "events": [], "events_truncated": False}
    breaks = np.flatnonzero(np.diff(selected) > 1) + 1
    groups = np.split(selected, breaks)
    events: list[dict[str, Any]] = []
    for group in groups[:MAX_EVENT_RANGES]:
        start = int(group[0])
        end = int(group[-1])
        events.append({
            "start_index": start,
            "end_index": end,
            "start_sequence": int(sequence[start]),
            "end_sequence": int(sequence[end]),
            "start_time_s": float(time_s[start]),
            "end_time_s": float(time_s[end]),
        })
    return {
        "sample_count": int(selected.size),
        "event_count": int(len(groups)),
        "events": events,
        "events_truncated": len(groups) > MAX_EVENT_RANGES,
    }


def _clock_fit(native_time_s: np.ndarray, host_sample_time_s: np.ndarray) -> dict[str, Any]:
    mask = np.isfinite(native_time_s) & np.isfinite(host_sample_time_s)
    x = np.asarray(native_time_s[mask], dtype=float)
    y = np.asarray(host_sample_time_s[mask], dtype=float)
    if x.size < 2 or float(np.ptp(x)) <= 0:
        return {"available": False, "sample_count": int(x.size)}
    x0 = x - x[0]
    y0 = y - y[0]
    variance = float(np.dot(x0 - np.mean(x0), x0 - np.mean(x0)))
    if variance <= 0:
        return {"available": False, "sample_count": int(x.size)}
    slope = float(np.dot(x0 - np.mean(x0), y0 - np.mean(y0)) / variance)
    intercept = float(np.mean(y0) - slope * np.mean(x0))
    residual_us = (y0 - (intercept + slope * x0)) * 1_000_000.0
    absolute = np.abs(residual_us)
    return {
        "available": True,
        "sample_count": int(x.size),
        "scale": slope,
        "drift_ppm": float((slope - 1.0) * 1_000_000.0),
        "residual_rms_us": float(np.sqrt(np.mean(residual_us * residual_us))),
        "residual_p95_abs_us": float(np.percentile(absolute, 95)),
        "residual_max_abs_us": float(np.max(absolute)),
    }


def _firmware_imu_diagnostics(session: Mapping[str, Any], sensor: str) -> Optional[dict[str, Any]]:
    qc = session.get("qc") if isinstance(session, Mapping) else None
    stats = qc.get("firmware_stats") if isinstance(qc, Mapping) else None
    if not isinstance(stats, Mapping):
        return None
    roots = [stats.get("imu_runtime_diagnostics"), stats.get("sensor_runtime_diagnostics")]
    for root in roots:
        sensors = root.get("sensors") if isinstance(root, Mapping) else None
        if not isinstance(sensors, Mapping):
            continue
        for key, raw in sensors.items():
            if canonical_sensor_id(key) != sensor or not isinstance(raw, Mapping):
                continue
            imu_session = raw.get("imu_session")
            return dict(imu_session) if isinstance(imu_session, Mapping) else dict(raw)
    return None


def _source_file_stats(session: Mapping[str, Any], duration_s: float) -> dict[str, Any]:
    source = session.get("source") if isinstance(session, Mapping) else None
    path_value = source.get("path") if isinstance(source, Mapping) else None
    size: Optional[int] = None
    if isinstance(path_value, str) and path_value:
        try:
            size = int(Path(path_value).stat().st_size)
        except OSError:
            size = None
    return {
        "duration_s": float(duration_s),
        "file_size_bytes": size,
        "file_bytes_per_second": float(size / duration_s) if size is not None and duration_s > 0 else None,
    }


def _required_columns(layout: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    columns: dict[str, str] = {}
    missing: list[str] = []
    for vector in ("accel", "gyro"):
        axes = layout.get(vector)
        axes = axes if isinstance(axes, Mapping) else {}
        for axis in "xyz":
            column = axes.get(axis)
            key = f"{vector}_{axis}"
            if isinstance(column, str):
                columns[key] = column
            else:
                missing.append(key)
    scalars = layout.get("scalar")
    scalars = scalars if isinstance(scalars, Mapping) else {}
    for semantic in sorted(_REQUIRED_SCALARS):
        column = scalars.get(semantic)
        if isinstance(column, str):
            columns[semantic] = column
        else:
            missing.append(semantic)
    return columns, missing


def extract_imu_stream(
    session: Mapping[str, Any],
    sensor: str,
    *,
    strict: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Extract one sparse logger IMU into a dense native-sample stream and QC report."""
    if not isinstance(session, Mapping) or not isinstance(session.get("df"), pd.DataFrame):
        raise ValueError("session must contain a primary pandas DataFrame in session['df']")
    sensor_id = canonical_sensor_id(sensor)
    layouts = _discover_layouts(session)
    layout = layouts.get(sensor_id)
    if not isinstance(layout, Mapping):
        raise ValueError(f"IMU sensor {sensor!r} was not found in channel metadata")

    columns, missing_columns = _required_columns(layout)
    if missing_columns:
        raise ValueError(f"IMU sensor {sensor_id!r} is missing required columns: {', '.join(missing_columns)}")

    config = _find_imu_config(session, sensor_id)
    config_values, metadata_warnings = _config_values(config)
    if strict and metadata_warnings:
        raise ValueError(f"IMU sensor {sensor_id!r} metadata is incomplete: {', '.join(metadata_warnings)}")

    primary = session["df"]
    valid_numeric = pd.to_numeric(primary[columns["sample_valid"]], errors="coerce").fillna(0)
    valid_mask = valid_numeric.to_numpy(dtype=float) == 1.0
    valid_positions = np.flatnonzero(valid_mask)
    if valid_positions.size == 0:
        raise ValueError(f"IMU sensor {sensor_id!r} has no rows with sample_valid=1")

    selected = primary.iloc[valid_positions]
    logger_time = pd.to_numeric(selected["time_s"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(logger_time).all():
        raise ValueError(f"IMU sensor {sensor_id!r} valid rows contain non-finite logger time")

    numeric: dict[str, np.ndarray] = {}
    for key, column in columns.items():
        if key == "sample_valid":
            continue
        values = pd.to_numeric(selected[column], errors="coerce").to_numpy(dtype=float)
        if key != "sample_age" and not np.isfinite(values).all():
            raise ValueError(f"IMU sensor {sensor_id!r} column {column!r} contains non-finite valid samples")
        numeric[key] = values

    sequence_u24 = numeric["sample_sequence"].astype(np.int64) % SEQUENCE_MODULUS
    sequence_unwrapped, sequence_delta = _unwrap_modulo(sequence_u24, SEQUENCE_MODULUS)
    tick_modulus = config_values.get("tick_modulus") or SEQUENCE_MODULUS
    sensor_time_u24 = numeric["sensor_time"].astype(np.int64) % int(tick_modulus)
    sensor_time_unwrapped, sensor_time_delta = _unwrap_modulo(sensor_time_u24, int(tick_modulus))

    rate_hz = config_values.get("rate_hz")
    tick_period_s = config_values.get("tick_period_s")
    repaired_sequence = np.empty(sequence_unwrapped.size, dtype=np.int64)
    repaired_sequence[0] = sequence_unwrapped[0]
    if sequence_delta.size:
        repaired_sequence[1:] = sequence_unwrapped[0] + np.cumsum(np.maximum(sequence_delta, 0), dtype=np.int64)

    age_us = numeric["sample_age"].astype(float)
    host_sample_time = logger_time - age_us / 1_000_000.0
    if rate_hz is not None and rate_hz > 0:
        time_s = (repaired_sequence - repaired_sequence[0]).astype(float) / float(rate_hz)
        timebase_source = "firmware_sequence_and_effective_rate"
    elif tick_period_s is not None and tick_period_s > 0:
        repaired_tick = np.empty(sensor_time_unwrapped.size, dtype=np.int64)
        repaired_tick[0] = sensor_time_unwrapped[0]
        repaired_tick[1:] = sensor_time_unwrapped[0] + np.cumsum(np.maximum(sensor_time_delta, 0), dtype=np.int64)
        time_s = (repaired_tick - repaired_tick[0]).astype(float) * float(tick_period_s)
        timebase_source = "sensor_time_without_effective_rate"
    else:
        finite_host = np.isfinite(host_sample_time)
        reference = float(host_sample_time[finite_host][0]) if finite_host.any() else float(logger_time[0])
        time_s = np.where(finite_host, host_sample_time, logger_time) - reference
        time_s = np.maximum.accumulate(time_s)
        timebase_source = "degraded_host_observation"

    native_time_s = (
        (sensor_time_unwrapped - sensor_time_unwrapped[0]).astype(float) * float(tick_period_s)
        if tick_period_s is not None and tick_period_s > 0
        else np.full(sensor_time_unwrapped.size, np.nan, dtype=float)
    )

    stream = pd.DataFrame({
        "time_s": time_s,
        "logger_time_s": logger_time,
        "host_sample_time_s": host_sample_time,
        "logger_row_index": valid_positions.astype(np.int64),
        "sequence_u24": sequence_u24.astype(np.uint32),
        "sequence_unwrapped": sequence_unwrapped,
        "sensor_time_u24": sensor_time_u24.astype(np.uint32),
        "sensor_time_unwrapped": sensor_time_unwrapped,
        "native_time_s": native_time_s,
        "sample_age_us": age_us,
        "status_flags": numeric["status"].astype(np.uint16),
        "temperature_raw_count": numeric["temperature_raw"].astype(np.int16),
        "temperature_c": numeric["temperature_raw"].astype(float) / 512.0 + 23.0,
    })
    if "sample_id" in selected.columns:
        stream.insert(4, "logger_sample_id", pd.to_numeric(selected["sample_id"], errors="coerce").to_numpy())

    for vector in ("accel", "gyro"):
        for axis in "xyz":
            stream[f"{vector}_{axis}_raw_count"] = numeric[f"{vector}_{axis}"].astype(np.int16)

    accel_range_g = config_values.get("accel_range_g")
    gyro_range_dps = config_values.get("gyro_range_dps")
    if accel_range_g is not None and accel_range_g > 0:
        accel_scale = float(accel_range_g) / 32768.0 * STANDARD_GRAVITY_M_S2
        for axis in "xyz":
            stream[f"accel_{axis}_m_s2"] = stream[f"accel_{axis}_raw_count"].astype(float) * accel_scale
    if gyro_range_dps is not None and gyro_range_dps > 0:
        gyro_scale = float(gyro_range_dps) / 32768.0 * math.pi / 180.0
        for axis in "xyz":
            stream[f"gyro_{axis}_rad_s"] = stream[f"gyro_{axis}_raw_count"].astype(float) * gyro_scale

    mount_matrix = config_values.get("mount_matrix")
    if isinstance(mount_matrix, np.ndarray):
        for vector, unit_suffix in (("accel", "m_s2"), ("gyro", "rad_s")):
            source_columns = [f"{vector}_{axis}_{unit_suffix}" for axis in "xyz"]
            if all(column in stream.columns for column in source_columns):
                body = stream[source_columns].to_numpy(dtype=float) @ mount_matrix.T
                for axis_index, axis in enumerate("xyz"):
                    stream[f"body_{vector}_{axis}_{unit_suffix}"] = body[:, axis_index]

    sequence_gap_mask = sequence_delta > 1
    sequence_duplicate_mask = sequence_delta == 0
    sequence_reverse_mask = sequence_delta < 0
    sequence_span = int(np.max(sequence_unwrapped) - np.min(sequence_unwrapped) + 1)
    coverage = float(len(stream.index) / sequence_span) if sequence_span > 0 else None

    expected_tick_delta: Optional[float] = None
    tick_residual = np.full(sensor_time_delta.size, np.nan, dtype=float)
    if rate_hz is not None and rate_hz > 0 and tick_period_s is not None and tick_period_s > 0:
        expected_tick_delta = 1.0 / (float(rate_hz) * float(tick_period_s))
        tick_residual = sensor_time_delta.astype(float) - sequence_delta.astype(float) * expected_tick_delta
    tick_discontinuity_mask = np.isfinite(tick_residual) & (np.abs(tick_residual) > 0.5)

    positive_native_delta = sensor_time_delta[sensor_time_delta > 0]
    effective_odr_hz: Optional[float] = None
    if tick_period_s is not None and positive_native_delta.size:
        per_sample_tick = positive_native_delta.astype(float)
        positive_sequence_delta = sequence_delta[sensor_time_delta > 0]
        usable = positive_sequence_delta > 0
        if usable.any():
            per_sample_tick = per_sample_tick[usable] / positive_sequence_delta[usable].astype(float)
        median_tick = float(np.median(per_sample_tick)) if per_sample_tick.size else 0.0
        if median_tick > 0:
            effective_odr_hz = 1.0 / (median_tick * float(tick_period_s))

    flags = stream["status_flags"].to_numpy(dtype=np.uint16)
    continuity_boundary = np.zeros(len(stream.index), dtype=bool)
    if len(stream.index) > 1:
        continuity_boundary[1:] = (sequence_delta != 1) | tick_discontinuity_mask
        incident_mask = (
            STATUS_FLAGS["fifo_discontinuity_before"]
            | STATUS_FLAGS["queue_drop_before"]
            | STATUS_FLAGS["sensor_recovery_before"]
            | STATUS_FLAGS["timing_degraded"]
        )
        continuity_boundary[1:] |= (flags[1:] & incident_mask) != 0
    continuity_segment = np.cumsum(continuity_boundary, dtype=np.int64)
    stream["continuity_segment"] = continuity_segment
    segment_counts = np.bincount(continuity_segment)
    segment_durations = [
        float(time_s[continuity_segment == segment][-1] - time_s[continuity_segment == segment][0])
        for segment in range(len(segment_counts))
    ]
    flag_qc: dict[str, Any] = {}
    for name, mask_value in STATUS_FLAGS.items():
        mask = (flags & mask_value) != 0
        detail = _event_ranges(mask, time_s, sequence_unwrapped)
        detail["fraction"] = float(detail["sample_count"] / len(stream.index))
        flag_qc[name] = detail

    saturation: dict[str, Any] = {"threshold_count": NEAR_RAIL_COUNT, "axes": {}}
    for vector in ("accel", "gyro"):
        for axis in "xyz":
            raw = stream[f"{vector}_{axis}_raw_count"].to_numpy(dtype=np.int64)
            mask = np.abs(raw) >= NEAR_RAIL_COUNT
            detail = _event_ranges(mask, time_s, sequence_unwrapped)
            detail["fraction"] = float(detail["sample_count"] / len(stream.index))
            saturation["axes"][f"{vector}_{axis}"] = detail

    stale_temperature = (flags & STATUS_FLAGS["temperature_stale"]) != 0
    temperature = stream["temperature_c"].to_numpy(dtype=float)
    fresh_temperature = temperature[~stale_temperature]
    firmware = _firmware_imu_diagnostics(session, sensor_id)
    startup = firmware.get("startup_stationary_observation") if isinstance(firmware, Mapping) else None
    firmware_counter_names = (
        "fifo_overflow_events",
        "hardware_skipped_frames",
        "partial_frames",
        "invalid_headers",
        "parser_output_drops",
        "queue_drops",
        "i2c_failures",
        "recovery_attempts",
        "recovery_failures",
        "timing_degraded_samples",
        "sequence_discontinuity_events",
        "native_time_discontinuity_events",
        "terminal_fault_events",
    )
    firmware_counters = {
        name: firmware.get(name)
        for name in firmware_counter_names
        if isinstance(firmware, Mapping) and name in firmware
    }

    duration_s = float(time_s[-1] - time_s[0]) if len(time_s) > 1 else 0.0
    warnings = list(metadata_warnings)
    if sequence_gap_mask.any():
        warnings.append("sequence_gaps")
    if sequence_duplicate_mask.any():
        warnings.append("duplicate_sequence_values")
    if sequence_reverse_mask.any():
        warnings.append("out_of_order_sequence_values")
    if tick_discontinuity_mask.any():
        warnings.append("sensor_time_discontinuities")
    for name in ("fifo_discontinuity_before", "queue_drop_before", "sensor_recovery_before", "timing_degraded"):
        if flag_qc[name]["sample_count"]:
            warnings.append(name)
    if any(detail["sample_count"] for detail in saturation["axes"].values()):
        warnings.append("near_rail_samples")

    qc_report: dict[str, Any] = {
        "schema": IMU_QC_SCHEMA,
        "status": "ok" if not warnings else ("degraded" if metadata_warnings or sequence_reverse_mask.any() else "warning"),
        "sensor_id": sensor_id,
        "domain": layout.get("domain"),
        "end": layout.get("end"),
        "mount_point": layout.get("mount_point"),
        "warnings": list(dict.fromkeys(warnings)),
        "sample_count": int(len(stream.index)),
        "nominal_odr_hz": float(rate_hz) if rate_hz is not None else None,
        "effective_odr_hz": effective_odr_hz,
        "sequence": {
            "gap_events": int(np.count_nonzero(sequence_gap_mask)),
            "missing_samples": int(np.sum(sequence_delta[sequence_gap_mask] - 1, dtype=np.int64)),
            "duplicates": int(np.count_nonzero(sequence_duplicate_mask)),
            "out_of_order": int(np.count_nonzero(sequence_reverse_mask)),
            "coverage_fraction": coverage,
            "first": int(sequence_unwrapped[0]),
            "last": int(sequence_unwrapped[-1]),
        },
        "sensor_time": {
            "expected_ticks_per_sample": expected_tick_delta,
            "discontinuity_events": int(np.count_nonzero(tick_discontinuity_mask)),
            "duplicates": int(np.count_nonzero(sensor_time_delta == 0)),
            "out_of_order": int(np.count_nonzero(sensor_time_delta < 0)),
            "clock_fit_to_logger": _clock_fit(native_time_s, host_sample_time),
        },
        "continuous_segments": {
            "count": int(len(segment_counts)),
            "largest_sample_count": int(np.max(segment_counts)),
            "largest_duration_s": float(max(segment_durations)),
        },
        "status_flags": flag_qc,
        "acquisition_age_us": _percentiles(age_us),
        "saturation": saturation,
        "temperature_c": {
            "minimum": float(np.min(temperature)),
            "maximum": float(np.max(temperature)),
            "fresh_minimum": float(np.min(fresh_temperature)) if fresh_temperature.size else None,
            "fresh_maximum": float(np.max(fresh_temperature)) if fresh_temperature.size else None,
        },
        "startup_stationary_observation": copy.deepcopy(dict(startup)) if isinstance(startup, Mapping) else None,
        "firmware_counters": firmware_counters,
        "storage": _source_file_stats(session, duration_s),
        "timebase_source": timebase_source,
    }

    stream_metadata = {
        "schema": IMU_STREAM_SCHEMA,
        "source_kind": "logger_sensor",
        "sensor": sensor_id,
        "imu_id": config.get("imu_id") if isinstance(config, Mapping) else None,
        "domain": layout.get("domain"),
        "end": layout.get("end"),
        "mount_point": layout.get("mount_point"),
        "nominal_sample_rate_hz": float(rate_hz) if rate_hz is not None else None,
        "timebase_source": timebase_source,
        "raw_samples_preserved": True,
        "coordinate_frames": ["sensor_native"] + (["body_local"] if isinstance(mount_matrix, np.ndarray) else []),
        "mount_transform": copy.deepcopy(config.get("mount_transform")) if isinstance(config, Mapping) else None,
        "source_columns": dict(columns),
        "qc_ref": f"meta.imu_qc.{sensor_id}",
    }
    return stream, qc_report, stream_metadata


def _stream_name(sensor: str, existing: set[str]) -> str:
    base = f"imu_{canonical_sensor_id(sensor) or 'sensor'}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def build_imu_streams(session: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    """Build and register dense secondary streams for every IMU described by logger metadata."""
    if not isinstance(session, dict):
        raise TypeError("session must be a dict")
    layouts = _discover_layouts(session)
    if not layouts:
        return session

    stream_dfs = session.setdefault("stream_dfs", {})
    if not isinstance(stream_dfs, dict):
        stream_dfs = {}
        session["stream_dfs"] = stream_dfs
    meta = session.setdefault("meta", {})
    secondary = meta.setdefault("secondary_streams", {})
    if not isinstance(secondary, dict):
        secondary = {}
        meta["secondary_streams"] = secondary
    qc_imu = session.setdefault("qc", {}).setdefault("imu", {})
    if not isinstance(qc_imu, dict):
        qc_imu = {}
        session["qc"]["imu"] = qc_imu

    existing_names = set(map(str, stream_dfs.keys()))
    for sensor in sorted(layouts):
        try:
            stream, report, stream_meta = extract_imu_stream(session, sensor, strict=strict)
        except ValueError as exc:
            if strict:
                raise
            qc_imu[sensor] = {
                "schema": IMU_QC_SCHEMA,
                "status": "failed",
                "sensor_id": sensor,
                "errors": [str(exc)],
                "warnings": [],
            }
            continue

        name = next(
            (
                str(stream_name)
                for stream_name, raw_meta in secondary.items()
                if isinstance(raw_meta, Mapping)
                and raw_meta.get("schema") == IMU_STREAM_SCHEMA
                and canonical_sensor_id(raw_meta.get("sensor")) == sensor
            ),
            "",
        )
        if not name:
            name = _stream_name(sensor, existing_names)
        existing_names.add(name)
        stream_dfs[name] = stream
        has_discontinuity = report["continuous_segments"]["count"] > 1
        nominal_rate = report.get("nominal_odr_hz")
        if not has_discontinuity and nominal_rate is not None:
            register_stream_metadata(
                session,
                stream_name=name,
                kind="uniform",
                time_col="time_s",
                sample_rate_hz=float(nominal_rate),
                dt_s=1.0 / float(nominal_rate),
                jitter_frac=0.0,
                notes="Dense valid-only IMU native stream reconstructed from sparse logger rows",
            )
        else:
            register_stream_metadata(
                session,
                stream_name=name,
                kind="intermittent",
                time_col="time_s",
                notes="Valid-only IMU stream with explicit native sequence/timing discontinuities",
            )
        stream_meta["stream_name"] = name
        stream_meta["timebase_kind"] = "intermittent" if has_discontinuity else "uniform"
        secondary[name] = stream_meta
        report["stream_name"] = name
        qc_imu[sensor] = report
    meta["imu_qc"] = copy.deepcopy(qc_imu)
    return session


def imu_qc_report(session: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable copy of the session's deterministic IMU QC report."""
    qc = session.get("qc") if isinstance(session, Mapping) else None
    reports = qc.get("imu") if isinstance(qc, Mapping) else None
    if not isinstance(reports, Mapping):
        meta = session.get("meta") if isinstance(session, Mapping) else None
        reports = meta.get("imu_qc") if isinstance(meta, Mapping) else None
    return copy.deepcopy(dict(reports)) if isinstance(reports, Mapping) else {}
