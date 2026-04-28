"""Sensor/source-name helpers used across analysis widgets and pipelines.

These helpers intentionally do not maintain semantic aliases.  If a logger uses
legacy names such as ``fork`` or ``shock``, map those to explicit semantics in
log metadata rather than relying on analysis-time alias collapse.
"""

from __future__ import annotations

import re
from typing import Any


_SEP_RE = re.compile(r"[\s\-]+")
_UNDERSCORE_RE = re.compile(r"_+")

_END_ALIASES: dict[str, str] = {
    "front": "front",
    "rear": "rear",
}


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
    """Return a normalized source/sensor id without applying semantic aliases."""
    key = normalize_sensor_token(sensor)
    if not key:
        return ""
    return key


def canonical_sensor_from_text(value: Any) -> str:
    """Infer a source/sensor id from a sensor-prefixed signal name."""
    key = normalize_sensor_token(value)
    if not key:
        return ""
    for prefix in ("front_shock", "rear_shock", "front_wheel", "rear_wheel", "gps_fit", "gps"):
        if key == prefix or key.startswith(prefix + "_"):
            return prefix
    return ""


def canonicalize_signal_base(base: Any) -> str:
    """Normalize whitespace/separators in a signal base without aliasing it."""
    if base is None:
        return ""
    return normalize_sensor_token(base) or str(base).strip()


def sensors_match(left: Any, right: Any) -> bool:
    """Normalized equality for source/sensor ids."""
    left_key = canonical_sensor_id(left)
    right_key = canonical_sensor_id(right)
    return bool(left_key and right_key and left_key == right_key)


def canonical_end(value: Any) -> str:
    """Accept only explicit bike-end/location tokens ``front`` or ``rear``."""
    key = normalize_sensor_token(value)
    if not key:
        return ""
    return _END_ALIASES.get(key, "")


def end_from_sensor(value: Any) -> str:
    """Return ``front``/``rear`` for known suspension sensor ids or signal names."""
    sensor = canonical_sensor_from_text(value) or canonical_sensor_id(value)
    if sensor.startswith("front_"):
        return "front"
    if sensor.startswith("rear_"):
        return "rear"
    return ""


def ends_match(left: Any, right: Any) -> bool:
    """Equality for explicit bike ends."""
    left_key = canonical_end(left) or end_from_sensor(left)
    right_key = canonical_end(right) or end_from_sensor(right)
    return bool(left_key and right_key and left_key == right_key)


def sensor_side(value: Any) -> str:
    """Return ``front``/``rear`` for known suspension sensor ids or signal names."""
    return end_from_sensor(value)


def sensor_matches_side(value: Any, side: Any) -> bool:
    """Return True when a source id or signal name has the requested explicit end."""
    return ends_match(value, side)
