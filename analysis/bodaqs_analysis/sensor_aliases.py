"""Sensor-name alias helpers used across analysis widgets and pipelines."""

from __future__ import annotations

import re
from typing import Any


_SEP_RE = re.compile(r"[\s\-]+")
_UNDERSCORE_RE = re.compile(r"_+")

_SENSOR_ALIASES: dict[str, str] = {
    "front_shock": "front_shock",
    "front_fork": "front_shock",
    "fork": "front_shock",
    "rear_shock": "rear_shock",
    "rear_fork": "rear_shock",
    "shock": "rear_shock",
}
_ALIASES_BY_LENGTH = tuple(sorted(_SENSOR_ALIASES, key=len, reverse=True))


def normalize_sensor_token(value: Any) -> str:
    """Return a comparison key for sensor names and sensor-prefixed signal bases."""
    if value is None:
        return ""
    token = str(value).strip().lower()
    if not token:
        return ""
    token = _SEP_RE.sub("_", token)
    token = _UNDERSCORE_RE.sub("_", token)
    return token.strip("_")


def canonical_sensor_id(sensor: Any) -> str:
    """
    Canonicalize a sensor id.

    Suspension aliases intentionally collapse to the existing canonical ids:
    ``fork`` -> ``front_shock`` and ``shock`` -> ``rear_shock``.
    Unknown sensors are returned stripped and otherwise unchanged.
    """
    key = normalize_sensor_token(sensor)
    if not key:
        return ""
    return _SENSOR_ALIASES.get(key, str(sensor).strip())


def canonical_sensor_from_text(value: Any) -> str:
    """Infer a canonical sensor id from a sensor id or sensor-prefixed signal name."""
    key = normalize_sensor_token(value)
    if not key:
        return ""
    for alias in _ALIASES_BY_LENGTH:
        if key == alias or key.startswith(alias + "_"):
            return _SENSOR_ALIASES[alias]
    return ""


def canonicalize_signal_base(base: Any) -> str:
    """Replace a leading suspension sensor alias in a signal base with its canonical id."""
    if base is None:
        return ""
    key = normalize_sensor_token(base)
    if not key:
        return str(base).strip()
    for alias in _ALIASES_BY_LENGTH:
        if key == alias:
            return _SENSOR_ALIASES[alias]
        prefix = alias + "_"
        if key.startswith(prefix):
            return _SENSOR_ALIASES[alias] + key[len(alias):]
    return str(base).strip()


def sensors_match(left: Any, right: Any) -> bool:
    """Alias-aware equality for sensor ids."""
    left_key = canonical_sensor_id(left)
    right_key = canonical_sensor_id(right)
    return bool(left_key and right_key and normalize_sensor_token(left_key) == normalize_sensor_token(right_key))


def sensor_side(value: Any) -> str:
    """Return ``front``/``rear`` for known suspension sensor ids or signal names."""
    sensor = canonical_sensor_from_text(value) or canonical_sensor_id(value)
    if sensor.startswith("front_"):
        return "front"
    if sensor.startswith("rear_"):
        return "rear"
    return ""


def sensor_matches_side(value: Any, side: Any) -> bool:
    """Return True when a sensor id or signal name belongs to the requested side."""
    side_key = normalize_sensor_token(side)
    if side_key not in {"front", "rear"}:
        return False
    return sensor_side(value) == side_key
