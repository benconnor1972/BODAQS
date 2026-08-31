"""Detection and conservative repair of typed raw suspension-sensor dropouts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd


RAW_SIGNAL_DROPOUT_MODES = {"off", "detect", "detect_and_repair"}
RAW_SIGNAL_DROPOUT_BEHAVIOR_VERSION = "bodaqs.raw_signal_dropout_filter.v3"

DEFAULT_RAW_SIGNAL_DROPOUT_FILTER: dict[str, Any] = {
    "mode": "detect_and_repair",
    "max_repair_gap_ms": 100.0,
    "context_ms": 25.0,
    "max_boundary_extension_ms": 25.0,
    "detectors": {
        "bounded_analog": {
            "enabled": True,
            "rail_margin_fraction": 0.05,
            "minimum_excursion_fraction": 0.015,
            "innovation_sigma": 8.0,
            "transient_return_enabled": True,
            "transient_max_duration_ms": 25.0,
        },
        "wrapped_encoder": {
            "enabled": True,
            "modulus": 4096,
            "minimum_excursion_fraction": 0.015,
            "innovation_sigma": 8.0,
        },
    },
    "overrides": [],
}


@dataclass(frozen=True)
class RawSignalDropoutResult:
    report: dict[str, Any]
    repaired_source_columns: dict[str, str]


@dataclass(frozen=True)
class _DetectedSegment:
    start: int
    end: int
    confidence: float
    repair_eligible: bool
    core_intervals: tuple[tuple[int, int], ...]
    detection_kinds: tuple[str, ...]

    @property
    def core_start(self) -> int:
        return min(start for start, _end in self.core_intervals)

    @property
    def core_end(self) -> int:
        return max(end for _start, end in self.core_intervals)

    @property
    def core_sample_count(self) -> int:
        return sum(end - start + 1 for start, end in self.core_intervals)


def validate_raw_signal_dropout_config(value: Any, *, label: str = "") -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError(f"Preprocess config 'raw_signal_dropout_filter' must be object or null{label}")

    allowed = {
        "mode",
        "max_repair_gap_ms",
        "context_ms",
        "max_boundary_extension_ms",
        "detectors",
        "overrides",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(
            "Preprocess config 'raw_signal_dropout_filter' has unsupported field(s)"
            f"{label}: {', '.join(unknown)}"
        )

    mode = str(value.get("mode", "detect_and_repair")).strip().lower()
    if mode not in RAW_SIGNAL_DROPOUT_MODES:
        raise ValueError(
            "Preprocess config 'raw_signal_dropout_filter.mode' must be one of "
            f"{sorted(RAW_SIGNAL_DROPOUT_MODES)}{label}"
        )
    for key in ("max_repair_gap_ms", "context_ms"):
        try:
            numeric = float(value.get(key, DEFAULT_RAW_SIGNAL_DROPOUT_FILTER[key]))
        except (TypeError, ValueError):
            raise ValueError(f"Preprocess config 'raw_signal_dropout_filter.{key}' must be numeric{label}") from None
        if numeric <= 0:
            raise ValueError(f"Preprocess config 'raw_signal_dropout_filter.{key}' must be > 0{label}")
    try:
        boundary_extension_ms = float(
            value.get(
                "max_boundary_extension_ms",
                DEFAULT_RAW_SIGNAL_DROPOUT_FILTER["max_boundary_extension_ms"],
            )
        )
    except (TypeError, ValueError):
        raise ValueError(
            "Preprocess config 'raw_signal_dropout_filter.max_boundary_extension_ms' "
            f"must be numeric{label}"
        ) from None
    if boundary_extension_ms < 0:
        raise ValueError(
            "Preprocess config 'raw_signal_dropout_filter.max_boundary_extension_ms' "
            f"must be >= 0{label}"
        )

    detectors = value.get("detectors", {})
    if not isinstance(detectors, Mapping):
        raise ValueError(f"Preprocess config 'raw_signal_dropout_filter.detectors' must be an object{label}")
    unknown_detectors = sorted(set(detectors) - {"bounded_analog", "wrapped_encoder"})
    if unknown_detectors:
        raise ValueError(
            "Preprocess config 'raw_signal_dropout_filter.detectors' has unsupported detector(s)"
            f"{label}: {', '.join(unknown_detectors)}"
        )
    for detector_name, detector in detectors.items():
        if not isinstance(detector, Mapping):
            raise ValueError(
                f"Preprocess config 'raw_signal_dropout_filter.detectors.{detector_name}' must be an object{label}"
            )
        allowed_detector = {
            "enabled",
            "rail_margin_fraction",
            "minimum_excursion_fraction",
            "innovation_sigma",
            "modulus",
            "transient_return_enabled",
            "transient_max_duration_ms",
        }
        unknown_fields = sorted(set(detector) - allowed_detector)
        if unknown_fields:
            raise ValueError(
                f"Preprocess config 'raw_signal_dropout_filter.detectors.{detector_name}' "
                f"has unsupported field(s){label}: {', '.join(unknown_fields)}"
            )
        for field in ("enabled", "transient_return_enabled"):
            if field in detector and not isinstance(detector.get(field), bool):
                raise ValueError(
                    f"Preprocess config 'raw_signal_dropout_filter.detectors.{detector_name}.{field}' "
                    f"must be boolean{label}"
                )
        for field in (
            "rail_margin_fraction",
            "minimum_excursion_fraction",
            "innovation_sigma",
            "modulus",
            "transient_max_duration_ms",
        ):
            if field not in detector:
                continue
            try:
                numeric = float(detector[field])
            except (TypeError, ValueError):
                raise ValueError(
                    f"Preprocess config 'raw_signal_dropout_filter.detectors.{detector_name}.{field}' "
                    f"must be numeric{label}"
                ) from None
            if numeric <= 0:
                raise ValueError(
                    f"Preprocess config 'raw_signal_dropout_filter.detectors.{detector_name}.{field}' "
                    f"must be > 0{label}"
                )

    overrides = value.get("overrides", [])
    if not isinstance(overrides, list):
        raise ValueError(f"Preprocess config 'raw_signal_dropout_filter.overrides' must be a list{label}")
    allowed_override = {
        "sensor",
        "column",
        "detector",
        "enabled",
        "rail_margin_fraction",
        "minimum_excursion_fraction",
        "innovation_sigma",
        "modulus",
        "transient_return_enabled",
        "transient_max_duration_ms",
    }
    for index, override in enumerate(overrides):
        if not isinstance(override, Mapping):
            raise ValueError(
                f"Preprocess config 'raw_signal_dropout_filter.overrides[{index}]' must be an object{label}"
            )
        unknown_override = sorted(set(override) - allowed_override)
        if unknown_override:
            raise ValueError(
                f"Preprocess config 'raw_signal_dropout_filter.overrides[{index}]' has unsupported field(s)"
                f"{label}: {', '.join(unknown_override)}"
            )
        if not str(override.get("sensor") or override.get("column") or "").strip():
            raise ValueError(
                f"Preprocess config 'raw_signal_dropout_filter.overrides[{index}]' requires sensor or column{label}"
            )
        for field in ("enabled", "transient_return_enabled"):
            if field in override and not isinstance(override.get(field), bool):
                raise ValueError(
                    f"Preprocess config 'raw_signal_dropout_filter.overrides[{index}].{field}' "
                    f"must be boolean{label}"
                )
        for field in (
            "rail_margin_fraction",
            "minimum_excursion_fraction",
            "innovation_sigma",
            "modulus",
            "transient_max_duration_ms",
        ):
            if field not in override:
                continue
            try:
                numeric = float(override[field])
            except (TypeError, ValueError):
                raise ValueError(
                    f"Preprocess config 'raw_signal_dropout_filter.overrides[{index}].{field}' must be numeric{label}"
                ) from None
            if numeric <= 0:
                raise ValueError(
                    f"Preprocess config 'raw_signal_dropout_filter.overrides[{index}].{field}' must be > 0{label}"
                )


def apply_raw_signal_dropout_filter(
    session: dict[str, Any],
    config: Mapping[str, Any],
) -> RawSignalDropoutResult:
    validate_raw_signal_dropout_config(config)
    mode = str(config.get("mode", "detect_and_repair")).strip().lower()
    report: dict[str, Any] = {
        "schema": "bodaqs.raw_signal_dropout_filter.v1",
        "mode": mode,
        "applied": False,
        "detected_samples": 0,
        "detected_episodes": 0,
        "repaired_samples": 0,
        "repaired_episodes": 0,
        "unrepaired_episodes": 0,
        "signals": [],
        "warnings": [],
    }
    if mode == "off":
        return RawSignalDropoutResult(report=report, repaired_source_columns={})

    df = session.get("df")
    meta = session.get("meta")
    if not isinstance(df, pd.DataFrame) or not isinstance(meta, Mapping):
        report["warnings"].append("Session dataframe or metadata is unavailable")
        return RawSignalDropoutResult(report=report, repaired_source_columns={})

    sample_rate_hz = _sample_rate_hz(df, meta)
    max_gap_samples = max(1, int(round(float(config.get("max_repair_gap_ms", 100.0)) * sample_rate_hz / 1000.0)))
    context_samples = max(2, int(round(float(config.get("context_ms", 25.0)) * sample_rate_hz / 1000.0)))
    max_boundary_extension_samples = max(
        0,
        int(
            round(
                float(
                    config.get(
                        "max_boundary_extension_ms",
                        DEFAULT_RAW_SIGNAL_DROPOUT_FILTER["max_boundary_extension_ms"],
                    )
                )
                * sample_rate_hz
                / 1000.0
            )
        ),
    )
    report["sample_rate_hz"] = float(sample_rate_hz)
    report["max_repair_gap_ms"] = float(config.get("max_repair_gap_ms", 100.0))
    report["context_ms"] = float(config.get("context_ms", 25.0))
    report["max_boundary_extension_ms"] = float(
        config.get(
            "max_boundary_extension_ms",
            DEFAULT_RAW_SIGNAL_DROPOUT_FILTER["max_boundary_extension_ms"],
        )
    )

    channel_info = meta.get("channel_info")
    if not isinstance(channel_info, dict):
        channel_info = {}
        meta["channel_info"] = channel_info
    declared_sensors = meta.get("declared_sensors")
    sensors_by_name = {
        str(name).strip().lower(): value
        for name, value in (declared_sensors.items() if isinstance(declared_sensors, Mapping) else [])
        if isinstance(value, Mapping)
    }
    detectors = config.get("detectors") if isinstance(config.get("detectors"), Mapping) else {}
    overrides = config.get("overrides") if isinstance(config.get("overrides"), list) else []

    repaired_sources: dict[str, str] = {}
    original_columns = list(df.columns)
    for raw_col in original_columns:
        info = channel_info.get(str(raw_col))
        if not isinstance(info, Mapping) or str(info.get("quantity") or "").strip().lower() != "raw":
            continue
        if str(info.get("unit") or "").strip().lower() not in {"count", "counts"}:
            continue
        sensor_name = str(info.get("sensor") or info.get("motion_source_id") or "").strip()
        sensor_meta = sensors_by_name.get(sensor_name.lower(), {})
        sensor_type = str(sensor_meta.get("type") or "").strip().lower()
        detector_kind = _detector_kind(sensor_type, info)
        if detector_kind is None:
            continue
        detector_cfg = _merged_detector_config(
            detector_kind,
            detectors,
            overrides=overrides,
            sensor_name=sensor_name,
            column=str(raw_col),
        )
        if not bool(detector_cfg.get("enabled", True)):
            continue

        values = pd.to_numeric(df[raw_col], errors="coerce").to_numpy(dtype=float)
        if detector_kind == "bounded_analog":
            bounds = _electrical_bounds(info, sensor_meta, values)
            if bounds is None:
                report["warnings"].append(
                    f"Skipped bounded analogue dropout detection for {raw_col!r}: electrical bounds unavailable"
                )
                continue
            detected, segments, working_values = _detect_bounded_analog(
                values,
                lower=bounds[0],
                upper=bounds[1],
                max_gap_samples=max_gap_samples,
                context_samples=context_samples,
                max_boundary_extension_samples=max_boundary_extension_samples,
                sample_rate_hz=sample_rate_hz,
                config=detector_cfg,
            )
            modulus = None
        else:
            modulus = float(detector_cfg.get("modulus", 4096.0))
            detected, segments, working_values = _detect_wrapped_encoder(
                values,
                modulus=modulus,
                max_gap_samples=max_gap_samples,
                context_samples=context_samples,
                config=detector_cfg,
            )
            bounds = None

        repaired_mask = np.zeros(len(df), dtype=bool)
        repaired_values = values.copy()
        interval_records: list[dict[str, Any]] = []
        repaired_episode_count = 0
        for segment in segments:
            start = segment.start
            end = segment.end
            record = {
                "start_index": int(start),
                "end_index": int(end),
                "sample_count": int(end - start + 1),
                "core_start_index": int(segment.core_start),
                "core_end_index": int(segment.core_end),
                "core_sample_count": int(segment.core_sample_count),
                "core_intervals": [
                    {"start_index": int(core_start), "end_index": int(core_end)}
                    for core_start, core_end in segment.core_intervals
                ],
                "boundary_extension_before_samples": int(segment.core_start - start),
                "boundary_extension_after_samples": int(end - segment.core_end),
                "confidence": float(segment.confidence),
                "detection_kinds": list(segment.detection_kinds),
                "repaired": False,
            }
            if "time_s" in df.columns:
                record["start_time_s"] = float(df.iloc[start]["time_s"])
                record["end_time_s"] = float(df.iloc[end]["time_s"])
            if mode == "detect_and_repair" and segment.repair_eligible:
                bridge = _bridge_segment(working_values, start, end, context_samples=context_samples)
                if bridge is not None:
                    if modulus is not None:
                        bridge = np.mod(bridge, modulus)
                    elif bounds is not None:
                        bridge = np.clip(bridge, bounds[0], bounds[1])
                    repaired_values[start : end + 1] = bridge
                    repaired_mask[start : end + 1] = True
                    record["repaired"] = True
                    record["method"] = "constrained_cubic_hermite"
                    repaired_episode_count += 1
                else:
                    record["reason"] = "insufficient_valid_context"
            elif mode == "detect_and_repair":
                record["reason"] = "gap_exceeds_repair_limit"
            elif mode == "detect":
                record["reason"] = "detect_only"
            if len(interval_records) < 256:
                interval_records.append(record)

        detected_col = _unique_column_name(df, _derived_column_name(str(raw_col), "dropout_detected_qc", unit=None))
        repaired_col = _unique_column_name(df, _derived_column_name(str(raw_col), "dropout_repaired_qc", unit=None))
        df[detected_col] = detected
        df[repaired_col] = repaired_mask
        _register_qc_column(channel_info, detected_col, raw_col, info, "dropout_detected")
        _register_qc_column(channel_info, repaired_col, raw_col, info, "dropout_repaired")

        repaired_source_col: str | None = None
        if mode == "detect_and_repair" and repaired_mask.any():
            repaired_source_col = _unique_column_name(
                df,
                _derived_column_name(str(raw_col), "dropout_repaired", unit=str(info.get("unit") or "counts")),
            )
            if pd.api.types.is_integer_dtype(df[raw_col].dtype):
                df[repaired_source_col] = np.rint(repaired_values).astype(df[raw_col].dtype)
            else:
                df[repaired_source_col] = repaired_values
            _register_repaired_raw_column(channel_info, repaired_source_col, raw_col, info, detector_kind)
            repaired_sources[str(raw_col)] = repaired_source_col
            _repair_related_logger_signals(
                df,
                channel_info,
                raw_col=str(raw_col),
                raw_info=info,
                repaired_mask=repaired_mask,
                context_samples=context_samples,
                repaired_source_col=repaired_source_col,
            )

        episode_count = len(segments)
        signal_report = {
            "source_column": str(raw_col),
            "sensor": sensor_name or None,
            "sensor_type": sensor_type or None,
            "detector": detector_kind,
            "detected_column": detected_col,
            "repaired_column": repaired_col,
            "repaired_source_column": repaired_source_col,
            "detected_samples": int(detected.sum()),
            "detected_episodes": int(episode_count),
            "repaired_samples": int(repaired_mask.sum()),
            "repaired_episodes": int(repaired_episode_count),
            "unrepaired_episodes": int(episode_count - repaired_episode_count),
            "maximum_episode_samples": int(
                max((segment.end - segment.start + 1 for segment in segments), default=0)
            ),
            "intervals": interval_records,
        }
        if bounds is not None:
            signal_report["electrical_bounds"] = {"minimum": float(bounds[0]), "maximum": float(bounds[1])}
        if modulus is not None:
            signal_report["modulus"] = float(modulus)
        report["signals"].append(signal_report)
        report["detected_samples"] += signal_report["detected_samples"]
        report["detected_episodes"] += signal_report["detected_episodes"]
        report["repaired_samples"] += signal_report["repaired_samples"]
        report["repaired_episodes"] += signal_report["repaired_episodes"]
        report["unrepaired_episodes"] += signal_report["unrepaired_episodes"]

    report["applied"] = bool(report["signals"])
    session["df"] = df
    return RawSignalDropoutResult(report=report, repaired_source_columns=repaired_sources)


def _sample_rate_hz(df: pd.DataFrame, meta: Mapping[str, Any]) -> float:
    try:
        rate = float(meta.get("sample_rate_hz"))
        if np.isfinite(rate) and rate > 0:
            return rate
    except (TypeError, ValueError):
        pass
    if "time_s" in df.columns and len(df) > 1:
        time_s = pd.to_numeric(df["time_s"], errors="coerce").to_numpy(dtype=float)
        delta = np.diff(time_s)
        delta = delta[np.isfinite(delta) & (delta > 0)]
        if delta.size:
            return float(1.0 / np.median(delta))
    return 1.0


def _detector_kind(sensor_type: str, info: Mapping[str, Any]) -> str | None:
    if sensor_type in {"analog_pot", "analog_potentiometer", "as5600_string_pot_analog"}:
        return "bounded_analog"
    if sensor_type in {"as5600_angle_i2c", "as5048b_angle_i2c", "wrapped_absolute_encoder"}:
        return "wrapped_encoder"
    source = str(info.get("source") or "").strip().lower()
    if source == "absolute_angle_counts":
        return "wrapped_encoder"
    return None


def _merged_detector_config(
    kind: str,
    detectors: Mapping[str, Any],
    *,
    overrides: list[Any],
    sensor_name: str,
    column: str,
) -> dict[str, Any]:
    defaults = DEFAULT_RAW_SIGNAL_DROPOUT_FILTER["detectors"][kind]
    override = detectors.get(kind) if isinstance(detectors.get(kind), Mapping) else {}
    merged = {**defaults, **dict(override)}
    for item in overrides:
        if not isinstance(item, Mapping):
            continue
        sensor_match = str(item.get("sensor") or "").strip().lower() == sensor_name.strip().lower()
        column_match = str(item.get("column") or "").strip().lower() == column.strip().lower()
        detector_match = str(item.get("detector") or kind).strip().lower() == kind
        if detector_match and (sensor_match or column_match):
            merged.update(
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"sensor", "column", "detector"}
                }
            )
    return merged


def _electrical_bounds(
    info: Mapping[str, Any], sensor_meta: Mapping[str, Any], values: np.ndarray
) -> tuple[float, float] | None:
    calibration = info.get("calibration")
    if not isinstance(calibration, Mapping):
        calibration = sensor_meta.get("calibration")
    if isinstance(calibration, Mapping):
        try:
            a = float(calibration.get("sensor_zero_count"))
            b = float(calibration.get("sensor_full_count"))
            if np.isfinite(a) and np.isfinite(b) and a != b:
                return (min(a, b), max(a, b))
        except (TypeError, ValueError):
            pass
    finite = values[np.isfinite(values)]
    if finite.size and np.nanmin(finite) >= 0 and np.nanmax(finite) <= 4095:
        return (0.0, 4095.0)
    return None


def _detect_bounded_analog(
    values: np.ndarray,
    *,
    lower: float,
    upper: float,
    max_gap_samples: int,
    context_samples: int,
    max_boundary_extension_samples: int,
    sample_rate_hz: float,
    config: Mapping[str, Any],
) -> tuple[np.ndarray, list[_DetectedSegment], np.ndarray]:
    span = upper - lower
    rail_margin = float(config.get("rail_margin_fraction", 0.05)) * span
    minimum_excursion = float(config.get("minimum_excursion_fraction", 0.015)) * span
    innovation_sigma = float(config.get("innovation_sigma", 8.0))
    finite = np.isfinite(values)
    low_candidate = finite & (values <= lower + rail_margin)
    high_candidate = finite & (values >= upper - rail_margin)
    rail_segments: list[_DetectedSegment] = []
    for candidate, direction in ((low_candidate, -1), (high_candidate, 1)):
        for start, end in _true_runs(candidate):
            if start == 0 or end >= values.size - 1:
                rail_segments.append(
                    _DetectedSegment(
                        start=start,
                        end=end,
                        confidence=1.0,
                        repair_eligible=False,
                        core_intervals=((start, end),),
                        detection_kinds=("bounded_analog_rail",),
                    )
                )
                continue
            local = _context_values(values, start, end, context_samples)
            sigma = _robust_step_sigma(local)
            threshold = max(minimum_excursion, innovation_sigma * sigma)
            bridge = np.linspace(values[start - 1], values[end + 1], end - start + 3)[1:-1]
            residual = (bridge - values[start : end + 1]) if direction < 0 else (values[start : end + 1] - bridge)
            strength = float(np.nanmedian(residual)) if residual.size else 0.0
            if np.isfinite(strength) and strength > threshold:
                expanded_start, expanded_end = _expand_bounded_analog_boundaries(
                    values,
                    core_start=start,
                    core_end=end,
                    threshold=threshold,
                    max_extension_samples=max_boundary_extension_samples,
                )
                rail_segments.append(
                    _DetectedSegment(
                        start=expanded_start,
                        end=expanded_end,
                        confidence=float(strength / max(threshold, 1e-12)),
                        repair_eligible=expanded_end - expanded_start + 1 <= max_gap_samples,
                        core_intervals=((start, end),),
                        detection_kinds=("bounded_analog_rail",),
                    )
                )
    transient_segments: list[_DetectedSegment] = []
    if bool(config.get("transient_return_enabled", True)):
        max_duration_ms = float(config.get("transient_max_duration_ms", 25.0))
        max_duration_samples = max(1, int(round(max_duration_ms * sample_rate_hz / 1000.0)))
        transient_segments = _detect_bounded_analog_transient_returns(
            values,
            max_duration_samples=max_duration_samples,
            max_gap_samples=max_gap_samples,
            context_samples=context_samples,
            minimum_excursion=minimum_excursion,
            innovation_sigma=innovation_sigma,
        )

    segments = _merge_overlapping_segments(
        sorted((*rail_segments, *transient_segments), key=lambda item: item.start),
        max_gap_samples=max_gap_samples,
    )
    detected = np.zeros(values.size, dtype=bool)
    for segment in segments:
        detected[segment.start : segment.end + 1] = True
    return detected, segments, values.copy()


def _detect_bounded_analog_transient_returns(
    values: np.ndarray,
    *,
    max_duration_samples: int,
    max_gap_samples: int,
    context_samples: int,
    minimum_excursion: float,
    innovation_sigma: float,
) -> list[_DetectedSegment]:
    """Detect short non-rail excursions that abruptly return to the local trajectory.

    The entry and recovery steps are acceleration-like innovations in the raw-count
    domain. Requiring both edges, comparable magnitude, and a prompt return avoids
    treating a sustained high-speed suspension stroke as a dropout.
    """

    if values.size < 3 or max_duration_samples <= 0:
        return []
    steps = np.diff(values)
    finite_steps = steps[np.isfinite(steps)]
    if finite_steps.size < 2:
        return []
    global_threshold = max(
        minimum_excursion,
        innovation_sigma * _robust_sigma(finite_steps),
    )
    large_edges = np.flatnonzero(np.isfinite(steps) & (np.abs(steps) > global_threshold))
    candidates: list[tuple[float, _DetectedSegment]] = []
    for edge_index, enter in enumerate(large_edges):
        enter = int(enter)
        for leave_value in large_edges[edge_index + 1 :]:
            leave = int(leave_value)
            duration = leave - enter
            if duration > max_duration_samples:
                break
            if np.sign(steps[enter]) == np.sign(steps[leave]):
                continue

            enter_strength = abs(float(steps[enter]))
            leave_strength = abs(float(steps[leave]))
            edge_max = max(enter_strength, leave_strength)
            if min(enter_strength, leave_strength) / edge_max < 0.4:
                continue

            # Do not let two relatively small physical-motion edges enclose a much
            # larger transient. The larger inner edges will form their own candidate.
            inner_steps = np.abs(steps[enter + 1 : leave])
            if inner_steps.size and np.nanmax(inner_steps) > 1.25 * edge_max:
                continue

            start = enter + 1
            end = leave
            context_steps = _separate_context_steps(values, start, end, context_samples)
            context_median = float(np.median(context_steps)) if context_steps.size else 0.0
            context_sigma = _robust_sigma(context_steps) if context_steps.size else 0.0
            context_p90 = (
                float(np.quantile(np.abs(context_steps - context_median), 0.9))
                if context_steps.size
                else 0.0
            )
            local_threshold = max(
                minimum_excursion,
                innovation_sigma * context_sigma,
                2.0 * context_p90,
            )
            if min(enter_strength, leave_strength) <= local_threshold:
                continue

            expected_change = context_median * duration
            actual_change = float(values[leave + 1] - values[enter])
            if abs(actual_change - expected_change) > 2.0 * local_threshold:
                continue

            interior = values[start : end + 1]
            bridge = np.linspace(values[enter], values[leave + 1], interior.size + 2)[1:-1]
            residual = np.abs(interior - bridge)
            if residual.size == 0 or not np.isfinite(residual).any():
                continue
            max_residual = float(np.nanmax(residual))
            if max_residual <= local_threshold:
                continue

            confidence = min(enter_strength, leave_strength) / max(local_threshold, 1e-12)
            score = confidence + float(np.nanmedian(residual)) / max(local_threshold, 1e-12)
            candidates.append(
                (
                    score,
                    _DetectedSegment(
                        start=start,
                        end=end,
                        confidence=confidence,
                        repair_eligible=end - start + 1 <= max_gap_samples,
                        core_intervals=((start, end),),
                        detection_kinds=("bounded_analog_transient_return",),
                    ),
                )
            )

    # Prefer the strongest explanation for overlapping raw samples. Adjacent
    # candidates remain separate and are subsequently repaired independently.
    selected: list[_DetectedSegment] = []
    for _score, candidate in sorted(candidates, key=lambda item: item[0], reverse=True):
        if any(
            candidate.start <= existing.end and existing.start <= candidate.end
            for existing in selected
        ):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: item.start)


def _separate_context_steps(
    values: np.ndarray,
    start: int,
    end: int,
    context_samples: int,
) -> np.ndarray:
    """Return local steps without differencing across the excluded candidate."""

    left = values[max(0, start - context_samples) : start]
    right = values[end + 1 : min(values.size, end + 1 + context_samples)]
    steps = np.r_[np.diff(left), np.diff(right)]
    return steps[np.isfinite(steps)]


def _expand_bounded_analog_boundaries(
    values: np.ndarray,
    *,
    core_start: int,
    core_end: int,
    threshold: float,
    max_extension_samples: int,
) -> tuple[int, int]:
    """Include non-rail shoulder samples belonging to a rail dropout transient."""

    if max_extension_samples <= 0 or values.size < 2:
        return core_start, core_end
    steps = np.abs(np.diff(values))
    anomalous = np.isfinite(steps) & (steps > threshold)

    left_edges = [edge for edge in (core_start - 1, core_start - 2) if edge >= 0 and anomalous[edge]]
    expanded_start = core_start
    if left_edges:
        edge = max(left_edges)
        while edge - 1 >= 0 and anomalous[edge - 1]:
            edge -= 1
        expanded_start = max(core_start - max_extension_samples, edge + 1)

    right_edges = [
        edge
        for edge in (core_end, core_end + 1)
        if edge < anomalous.size and anomalous[edge]
    ]
    expanded_end = core_end
    if right_edges:
        edge = min(right_edges)
        while edge + 1 < anomalous.size and anomalous[edge + 1]:
            edge += 1
        expanded_end = min(core_end + max_extension_samples, edge)

    return expanded_start, expanded_end


def _merge_overlapping_segments(
    segments: list[_DetectedSegment],
    *,
    max_gap_samples: int,
) -> list[_DetectedSegment]:
    if not segments:
        return []
    merged: list[_DetectedSegment] = [segments[0]]
    for segment in segments[1:]:
        previous = merged[-1]
        if segment.start > previous.end:
            merged.append(segment)
            continue
        start = min(previous.start, segment.start)
        end = max(previous.end, segment.end)
        detection_kinds = tuple(sorted(set((*previous.detection_kinds, *segment.detection_kinds))))
        if "bounded_analog_rail" in detection_kinds:
            core_intervals = tuple(
                core
                for item in (previous, segment)
                if "bounded_analog_rail" in item.detection_kinds
                for core in item.core_intervals
            )
        else:
            core_intervals = tuple(sorted(set((*previous.core_intervals, *segment.core_intervals))))
        merged[-1] = _DetectedSegment(
            start=start,
            end=end,
            confidence=max(previous.confidence, segment.confidence),
            repair_eligible=(
                previous.repair_eligible
                and segment.repair_eligible
                and end - start + 1 <= max_gap_samples
            ),
            core_intervals=core_intervals,
            detection_kinds=detection_kinds,
        )
    return merged


def _detect_wrapped_encoder(
    values: np.ndarray,
    *,
    modulus: float,
    max_gap_samples: int,
    context_samples: int,
    config: Mapping[str, Any],
) -> tuple[np.ndarray, list[_DetectedSegment], np.ndarray]:
    working = _unwrap_counts(values, modulus)
    finite = np.isfinite(working)
    diffs = np.diff(working)
    global_sigma = _robust_sigma(diffs[np.isfinite(diffs)])
    threshold = max(
        float(config.get("minimum_excursion_fraction", 0.015)) * modulus,
        float(config.get("innovation_sigma", 8.0)) * global_sigma,
    )
    big = np.flatnonzero(np.isfinite(diffs) & (np.abs(diffs) > threshold))
    candidates = np.zeros(values.size, dtype=bool)
    cursor = 0
    while cursor < big.size:
        enter = int(big[cursor])
        matched = False
        for next_cursor in range(cursor + 1, big.size):
            leave = int(big[next_cursor])
            if leave - enter > max_gap_samples:
                break
            if np.sign(diffs[enter]) == np.sign(diffs[leave]):
                continue
            start = enter + 1
            end = leave
            if start <= end:
                candidates[start : end + 1] = True
                cursor = next_cursor
                matched = True
                break
        cursor += 1
        if not matched:
            continue

    detected = np.zeros(values.size, dtype=bool)
    accepted: list[_DetectedSegment] = []
    for start, end in _true_runs(candidates & finite):
        if end - start + 1 > max_gap_samples or start == 0 or end >= values.size - 1:
            continue
        local = _context_values(working, start, end, context_samples)
        local_threshold = max(
            float(config.get("minimum_excursion_fraction", 0.015)) * modulus,
            float(config.get("innovation_sigma", 8.0)) * _robust_step_sigma(local),
        )
        bridge = np.linspace(working[start - 1], working[end + 1], end - start + 3)[1:-1]
        residual = np.abs(working[start : end + 1] - bridge)
        strength = float(np.nanmedian(residual)) if residual.size else 0.0
        if np.isfinite(strength) and strength > local_threshold:
            detected[start : end + 1] = True
            accepted.append(
                _DetectedSegment(
                    start=start,
                    end=end,
                    confidence=float(strength / max(local_threshold, 1e-12)),
                    repair_eligible=end - start + 1 <= max_gap_samples,
                    core_intervals=((start, end),),
                    detection_kinds=("wrapped_encoder_jump_return",),
                )
            )
    return detected, accepted, working


def _unwrap_counts(values: np.ndarray, modulus: float) -> np.ndarray:
    out = values.astype(float, copy=True)
    finite_indices = np.flatnonzero(np.isfinite(out))
    if finite_indices.size < 2:
        return out
    radians = out[finite_indices] * (2.0 * np.pi / modulus)
    out[finite_indices] = np.unwrap(radians) * (modulus / (2.0 * np.pi))
    return out


def _bridge_segment(
    values: np.ndarray, start: int, end: int, *, context_samples: int
) -> np.ndarray | None:
    if start <= 0 or end >= values.size - 1:
        return None
    if not np.isfinite(values[start - 1]) or not np.isfinite(values[end + 1]):
        return None
    left_context = values[max(0, start - context_samples) : start]
    right_context = values[end + 1 : min(values.size, end + 1 + context_samples)]
    left_context = left_context[np.isfinite(left_context)]
    right_context = right_context[np.isfinite(right_context)]
    if left_context.size < 2 or right_context.size < 2:
        return None
    left_slope = float(np.median(np.diff(left_context)))
    right_slope = float(np.median(np.diff(right_context)))
    y0 = float(values[start - 1])
    y1 = float(values[end + 1])
    interval = float(end - start + 2)
    u = np.arange(1, end - start + 2, dtype=float) / interval
    h00 = 2 * u**3 - 3 * u**2 + 1
    h10 = u**3 - 2 * u**2 + u
    h01 = -2 * u**3 + 3 * u**2
    h11 = u**3 - u**2
    bridge = h00 * y0 + h10 * interval * left_slope + h01 * y1 + h11 * interval * right_slope
    linear = y0 + u * (y1 - y0)
    context_min = float(min(np.min(left_context), np.min(right_context), y0, y1))
    context_max = float(max(np.max(left_context), np.max(right_context), y0, y1))
    allowance = max(_robust_step_sigma(np.r_[left_context, right_context]) * interval * 3.0, abs(y1 - y0) * 0.25)
    if np.any(bridge < context_min - allowance) or np.any(bridge > context_max + allowance):
        bridge = linear
    return bridge


def _repair_related_logger_signals(
    df: pd.DataFrame,
    channel_info: dict[str, Any],
    *,
    raw_col: str,
    raw_info: Mapping[str, Any],
    repaired_mask: np.ndarray,
    context_samples: int,
    repaired_source_col: str,
) -> None:
    sensor = str(raw_info.get("sensor") or raw_info.get("motion_source_id") or "").strip().lower()
    for column in list(df.columns):
        if column in {raw_col, repaired_source_col}:
            continue
        info = channel_info.get(str(column))
        if not isinstance(info, dict):
            continue
        candidate_sensor = str(info.get("sensor") or info.get("motion_source_id") or "").strip().lower()
        if not sensor or candidate_sensor != sensor:
            continue
        if str(info.get("origin") or "").strip().lower() != "logger":
            continue
        if str(info.get("kind") or "").strip().lower() == "qc":
            continue
        values = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
        repaired = values.copy()
        any_repaired = False
        for start, end in _true_runs(repaired_mask):
            bridge = _bridge_segment(values, start, end, context_samples=context_samples)
            if bridge is None:
                continue
            repaired[start : end + 1] = bridge
            any_repaired = True
        if not any_repaired:
            continue
        df[column] = repaired
        info["origin"] = "analysis"
        info["processing_role"] = info.get("processing_role") or "primary_analysis"
        info["source"] = [raw_col]
        info["source_columns"] = [raw_col]
        info["op_chain"] = list(info.get("op_chain") or []) + ["fill"]
        info["dropout_repair"] = {
            "method": "constrained_cubic_hermite",
            "mask_source": raw_col,
            "repaired_source_column": repaired_source_col,
        }


def _register_qc_column(
    channel_info: dict[str, Any], column: str, source_col: str, source_info: Mapping[str, Any], quantity: str
) -> None:
    channel_info[column] = {
        "unit": None,
        "sensor": source_info.get("sensor"),
        "end": source_info.get("end"),
        "domain": source_info.get("domain"),
        "motion_source_id": source_info.get("motion_source_id"),
        "quantity": quantity,
        "role": quantity,
        "kind": "qc",
        "origin": "analysis",
        "processing_role": "qc_metric",
        "semantic_selection_excluded": True,
        "source": [source_col],
        "source_columns": [source_col],
        "op_chain": [],
    }


def _register_repaired_raw_column(
    channel_info: dict[str, Any], column: str, source_col: str, source_info: Mapping[str, Any], detector: str
) -> None:
    info = dict(source_info)
    info.update(
        {
            "quantity": "raw",
            "role": "raw",
            "kind": "raw",
            "origin": "analysis",
            "processing_role": "preprocessing_input",
            "inspection_visibility": "diagnostic",
            "semantic_selection_excluded": True,
            "source": [source_col],
            "source_columns": [source_col],
            "op_chain": list(source_info.get("op_chain") or []) + ["fill"],
            "derivation": {
                "method": "raw_signal_dropout_repair",
                "detector": detector,
                "source_col": source_col,
            },
        }
    )
    channel_info[column] = info


def _derived_column_name(column: str, suffix: str, *, unit: str | None) -> str:
    base = column
    if " [" in base and base.endswith("]"):
        base = base.rsplit(" [", 1)[0]
    return f"{base}_{suffix}" + (f" [{unit}]" if unit else "")


def _unique_column_name(df: pd.DataFrame, candidate: str) -> str:
    if candidate not in df.columns:
        return candidate
    index = 2
    while f"{candidate}_{index}" in df.columns:
        index += 1
    return f"{candidate}_{index}"


def _true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    if mask.size == 0:
        return []
    starts = np.flatnonzero(mask & ~np.r_[False, mask[:-1]])
    ends = np.flatnonzero(mask & ~np.r_[mask[1:], False])
    return [(int(start), int(end)) for start, end in zip(starts, ends)]


def _context_values(values: np.ndarray, start: int, end: int, context_samples: int) -> np.ndarray:
    return np.r_[
        values[max(0, start - context_samples) : start],
        values[end + 1 : min(values.size, end + 1 + context_samples)],
    ]


def _robust_step_sigma(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if finite.size < 3:
        return 0.0
    return _robust_sigma(np.diff(finite))


def _robust_sigma(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    median = float(np.median(finite))
    return float(1.4826 * np.median(np.abs(finite - median)))
