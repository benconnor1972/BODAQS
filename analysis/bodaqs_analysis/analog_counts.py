"""Reconstruct basic analog engineering values from a recording's own snapshot.

Raw frames remain unchanged. This does not align streams, fill missing rows,
apply external calibration files or interpret an unknown count domain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
import math
from typing import Any, Mapping

import pandas as pd


@dataclass
class AnalogReconstruction:
    frame: pd.DataFrame | None = None
    channels: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def reconstruct_recorded_analog(
    metadata: Mapping[str, Any],
    catalog: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
) -> AnalogReconstruction:
    """Use only explicitly supported, source-bound calibration snapshots."""
    result = AnalogReconstruction()
    snapshot = metadata.get("recording_configuration")
    if not isinstance(snapshot, Mapping):
        return result
    if snapshot.get("schema") != "bodaqs.recording_configuration.v1":
        result.warnings.append("analog_raw_only:unsupported_configuration_snapshot")
        return result
    sensors = snapshot.get("sensors")
    primary = frames.get("primary")
    streams = catalog.get("streams")
    if not isinstance(sensors, list) or not isinstance(primary, pd.DataFrame) or not isinstance(streams, list):
        result.warnings.append("analog_raw_only:missing_source_description")
        return result
    descriptors = [stream for stream in streams if isinstance(stream, Mapping) and stream.get("stream_key") == "primary"]
    if len(descriptors) != 1 or not isinstance(descriptors[0].get("channels"), list):
        result.warnings.append("analog_raw_only:ambiguous_primary_source")
        return result
    channels = descriptors[0]["channels"]
    acquisition = descriptors[0].get("acquisition")
    validity = acquisition.get("count_validity") if isinstance(acquisition, Mapping) else None
    per_field_validity = isinstance(validity, Mapping) and dict(validity) == {
        "schema": "bodaqs.adc_count_validity.v1", "valid_minimum": 0,
        "valid_maximum": 4095, "missing_count": 65535,
        "sensor_error_scope": "per_field_missing_count",
    }
    derived = primary.loc[:, [key for key in ("time_s", "sequence", "native_tick", "status_flags") if key in primary]].copy()
    identities = Counter(sensor.get("sensor_id") for sensor in sensors
                         if isinstance(sensor, Mapping) and isinstance(sensor.get("sensor_id"), str))
    for sensor in sensors:
        if not isinstance(sensor, Mapping) or sensor.get("sensor_type") != "analog_pot":
            continue
        identity = sensor.get("sensor_id")
        if not isinstance(identity, str) or not identity or identities[identity] != 1:
            result.warnings.append("analog_raw_only:ambiguous_sensor_identity")
            continue
        calibration = sensor.get("calibration")
        domain = sensor.get("count_domain")
        fields = sensor.get("raw_fields")
        if not isinstance(calibration, Mapping) or calibration.get("available") is not True:
            continue
        if (sensor.get("stream_key") != "primary" or not isinstance(domain, Mapping)
                or domain.get("id") != "adc_u12_clamped_v1"
                or domain.get("minimum") != 0 or domain.get("maximum") != 4095
                or not isinstance(fields, list) or len(fields) != 1 or not isinstance(fields[0], str)):
            result.warnings.append(f"analog_raw_only:{identity}:unsupported_count_domain")
            continue
        raw_field = fields[0]
        matching = [channel for channel in channels if isinstance(channel, Mapping) and channel.get("field") == raw_field]
        if (len(matching) != 1 or matching[0].get("storage_type") != "uint16"
                or matching[0].get("sensor") != identity or raw_field not in primary
                or "status_flags" not in primary):
            result.warnings.append(f"analog_raw_only:{identity}:source_mismatch")
            continue
        zero = _number(calibration.get("installed_zero_count"))
        low = _number(calibration.get("sensor_zero_count"))
        high = _number(calibration.get("sensor_full_count"))
        travel = _number(calibration.get("sensor_full_travel"))
        unit = calibration.get("output_unit")
        invert = calibration.get("invert")
        if (calibration.get("model") != "analog_geometry_v1" or None in (zero, low, high, travel)
                or high == low or travel <= 0 or not isinstance(unit, str) or not unit.strip()
                or not isinstance(invert, bool)):
            result.warnings.append(f"analog_raw_only:{identity}:invalid_calibration")
            continue
        raw = pd.to_numeric(primary[raw_field], errors="coerce")
        invalid = raw.isna() | (raw < 0) | (raw > 4095)
        if not per_field_validity:
            invalid |= (primary["status_flags"].astype("uint64") & 0x20) != 0
        field_name = f"{identity}_engineering [{unit}]"
        scale = travel / abs(high - low) * (-1 if invert else 1)
        derived[field_name] = ((raw - zero) * scale).mask(invalid)
        result.channels.append({
            "field": field_name, "sensor": identity, "unit": unit,
            "source_stream": "primary", "source_field": raw_field,
            "calibration_model": "analog_geometry_v1", "derived": True,
        })
    if result.channels:
        derived.attrs["recorded_calibration"] = result.channels
        result.frame = derived
    return result
