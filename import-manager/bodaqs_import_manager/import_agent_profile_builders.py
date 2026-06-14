from __future__ import annotations

import copy
import json
import math
import re
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from bodaqs_analysis.bike_profile import BIKE_PROFILE_SCHEMA, BIKE_PROFILE_VERSION, validate_bike_profile
from bodaqs_analysis.session_note_presets import (
    SESSION_NOTE_PRESET_SCHEMA,
    SESSION_NOTE_PRESET_VERSION,
    validate_bike_setup_preset,
)
from bodaqs_analysis.session_notes import TEMPLATE_SCHEMA, TEMPLATE_VERSION, validate_session_note_template


DEFAULT_BIKE_DIRNAME = "bike"
DEFAULT_NOTES_DIRNAME = "notes"
DEFAULT_BIKE_PROFILE_FILENAME = "bike_profile.json"
DEFAULT_SESSION_NOTE_TEMPLATE_FILENAME = "session_note_template.json"
DEFAULT_BIKE_SETUP_PRESET_FILENAME = "bike_setup_preset.json"
FRONT_VERTICAL_TRANSFORM_ID = "front_fork_to_front_vertical_wheel_travel"
FRONT_VERTICAL_TRANSFORM_SOURCE = "import_agent_head_angle"
FRONT_WHEEL_NORMALIZATION_RANGE_ID = "front_wheel_travel_range"
DEFAULT_REAR_SHOCK_LUT_INPUT_UNIT = "mm"
REAR_SHOCK_LUT_INPUT_UNITS = ("mm", "deg")

_ASSET_PACKAGE = "bodaqs_import_manager.import_agent_assets"
_FIELD_CATALOG_FILENAME = "session_note_field_catalog.json"


def _optional_text(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def _safe_slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return slug or fallback


def derive_profile_id(
    display_name: str,
    *,
    existing_ids: Sequence[str] = (),
    fallback: str = "bike-profile",
    max_length: int = 64,
) -> str:
    if max_length < 8:
        raise ValueError("max_length must be at least 8")
    base = _safe_slug(display_name, fallback=fallback)[:max_length].strip("-._") or fallback
    used = {str(item) for item in existing_ids}
    if base not in used:
        return base
    suffix = 2
    while True:
        suffix_text = f"-{suffix}"
        candidate = (base[: max_length - len(suffix_text)].strip("-._") or fallback) + suffix_text
        if candidate not in used:
            return candidate
        suffix += 1


def _profile_id_should_follow_display_name(profile_id: Any) -> bool:
    text = _optional_text(profile_id)
    return text is None or text in {"bike_profile", "default_import_agent_bike"}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _discover_single_valid_json_file(
    directory: str | Path,
    *,
    label: str,
    validator: Callable[[Mapping[str, Any]], None],
) -> tuple[Path, dict[str, Any]]:
    root = Path(directory).expanduser().resolve()
    matches: list[tuple[Path, dict[str, Any]]] = []
    rejected: list[str] = []
    if not root.exists():
        raise FileNotFoundError(f"{label} directory does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"{label} path must be a directory: {root}")

    for path in sorted(root.glob("*.json")):
        try:
            payload = _read_json(path)
            validator(payload)
        except Exception as exc:
            rejected.append(f"{path.name}: {exc}")
            continue
        matches.append((path, payload))

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(path.name for path, _payload in matches)
        raise ValueError(f"{label} directory must contain exactly one valid JSON file; found: {names}")
    if rejected:
        raise ValueError(f"{label} directory contains no valid JSON file. Rejected candidates: {'; '.join(rejected)}")
    raise ValueError(f"{label} directory contains no JSON files: {root}")


def source_bike_dir(source_root: str | Path) -> Path:
    return Path(source_root).expanduser().resolve() / DEFAULT_BIKE_DIRNAME


def source_notes_dir(source_root: str | Path) -> Path:
    return Path(source_root).expanduser().resolve() / DEFAULT_NOTES_DIRNAME


def load_source_bike_profile(source_root: str | Path) -> tuple[Path, dict[str, Any]]:
    return _discover_single_valid_json_file(
        source_bike_dir(source_root),
        label="Bike profile",
        validator=lambda payload: validate_bike_profile(payload),
    )


def save_source_bike_profile(
    source_root: str | Path,
    profile: Mapping[str, Any],
    *,
    filename: Optional[str] = None,
) -> Path:
    validate_bike_profile(profile)
    if filename is None:
        try:
            target, _existing = load_source_bike_profile(source_root)
        except Exception:
            target = source_bike_dir(source_root) / DEFAULT_BIKE_PROFILE_FILENAME
    else:
        target = source_bike_dir(source_root) / filename
    return _write_json(target, profile)


def load_source_session_note_template(source_root: str | Path) -> tuple[Path, dict[str, Any]]:
    return _discover_single_valid_json_file(
        source_notes_dir(source_root),
        label="Session note template",
        validator=lambda payload: validate_session_note_template(payload),
    )


def save_source_session_note_template(
    source_root: str | Path,
    template: Mapping[str, Any],
    *,
    filename: Optional[str] = None,
) -> Path:
    validate_session_note_template(template)
    if filename is None:
        try:
            target, _existing = load_source_session_note_template(source_root)
        except Exception:
            target = source_notes_dir(source_root) / DEFAULT_SESSION_NOTE_TEMPLATE_FILENAME
    else:
        target = source_notes_dir(source_root) / filename
    return _write_json(target, template)


def load_source_bike_setup_preset(source_root: str | Path) -> tuple[Path, dict[str, Any]]:
    return _discover_single_valid_json_file(
        source_notes_dir(source_root),
        label="Bike setup preset",
        validator=lambda payload: validate_bike_setup_preset(payload),
    )


def save_source_bike_setup_preset(
    source_root: str | Path,
    preset: Mapping[str, Any],
    *,
    filename: Optional[str] = None,
) -> Path:
    validate_bike_setup_preset(preset)
    if filename is None:
        try:
            target, _existing = load_source_bike_setup_preset(source_root)
        except Exception:
            target = source_notes_dir(source_root) / DEFAULT_BIKE_SETUP_PRESET_FILENAME
    else:
        target = source_notes_dir(source_root) / filename
    return _write_json(target, preset)


def _coerce_rear_shock_lut_input_unit(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    if not text:
        return DEFAULT_REAR_SHOCK_LUT_INPUT_UNIT
    aliases = {
        "degree": "deg",
        "degrees": "deg",
        "millimeter": "mm",
        "millimeters": "mm",
        "millimetre": "mm",
        "millimetres": "mm",
    }
    text = aliases.get(text, text)
    if text not in REAR_SHOCK_LUT_INPUT_UNITS:
        raise ValueError("rear_shock_lut_input_unit must be 'mm' or 'deg'")
    return text


def _front_suspension_selector() -> dict[str, str]:
    return {"end": "front", "quantity": "disp", "domain": "suspension", "unit": "mm"}


def _front_wheel_selector() -> dict[str, str]:
    return {"end": "front", "quantity": "disp", "domain": "wheel", "unit": "mm"}


def _rear_suspension_selector(unit: Any = DEFAULT_REAR_SHOCK_LUT_INPUT_UNIT) -> dict[str, str]:
    return {
        "end": "rear",
        "quantity": "disp",
        "domain": "suspension",
        "unit": _coerce_rear_shock_lut_input_unit(unit),
    }


def _rear_wheel_selector() -> dict[str, str]:
    return {"end": "rear", "quantity": "disp", "domain": "wheel", "unit": "mm"}


def _normalization_range_specs(
    *,
    rear_shock_lut_input_unit: Any = DEFAULT_REAR_SHOCK_LUT_INPUT_UNIT,
) -> dict[str, dict[str, Any]]:
    rear_shock_unit = _coerce_rear_shock_lut_input_unit(rear_shock_lut_input_unit)
    return {
        "front_fork_travel_mm": {
            "id": "front_fork_travel_range",
            "signal": _front_suspension_selector(),
        },
        "rear_shock_travel_mm": {
            "id": "rear_shock_travel_range",
            "signal": _rear_suspension_selector(rear_shock_unit),
        },
        "rear_wheel_travel_mm": {
            "id": "rear_wheel_travel_range",
            "signal": _rear_wheel_selector(),
        },
    }


def _matches_signal_selector(candidate: Any, selector: Mapping[str, Any]) -> bool:
    if not isinstance(candidate, Mapping):
        return False
    return all(candidate.get(key) == value for key, value in selector.items())


def _coerce_positive_float(value: Any, *, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be numeric") from None
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return result


def _coerce_optional_head_angle(value: Any) -> Optional[float]:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        angle = float(text)
    except (TypeError, ValueError):
        raise ValueError("front_head_angle_deg must be numeric") from None
    if not math.isfinite(angle) or angle <= 0.0 or angle >= 90.0:
        raise ValueError("front_head_angle_deg must be greater than 0 and less than 90 degrees")
    return angle


def _set_normalization_range_for_signal(
    profile: dict[str, Any],
    *,
    range_id: str,
    signal: Mapping[str, Any],
    full_range: Any,
    field_name: str,
    metadata: Optional[Mapping[str, Any]] = None,
) -> None:
    full_range_float = _coerce_positive_float(full_range, field_name=field_name)
    ranges = profile.setdefault("normalization_ranges", [])
    if not isinstance(ranges, list):
        ranges = []
        profile["normalization_ranges"] = ranges

    for item in ranges:
        if not isinstance(item, dict):
            continue
        if item.get("id") == range_id or _matches_signal_selector(item.get("signal"), signal):
            item["id"] = range_id
            item["signal"] = dict(signal)
            item["full_range"] = full_range_float
            if metadata is not None:
                item["metadata"] = dict(metadata)
            return

    payload = {"id": range_id, "signal": dict(signal), "full_range": full_range_float}
    if metadata is not None:
        payload["metadata"] = dict(metadata)
    ranges.append(payload)


def _set_normalization_range(
    profile: dict[str, Any],
    *,
    key: str,
    value: Any,
    rear_shock_lut_input_unit: Any = DEFAULT_REAR_SHOCK_LUT_INPUT_UNIT,
) -> None:
    spec = _normalization_range_specs(rear_shock_lut_input_unit=rear_shock_lut_input_unit)[key]
    _set_normalization_range_for_signal(
        profile,
        range_id=spec["id"],
        signal=spec["signal"],
        full_range=value,
        field_name=key,
    )


def _normalization_range_value(profile: Mapping[str, Any], selector: Mapping[str, Any]) -> Optional[float]:
    for item in profile.get("normalization_ranges", []) or []:
        if not isinstance(item, Mapping):
            continue
        if not _matches_signal_selector(item.get("signal"), selector):
            continue
        try:
            value = float(item.get("full_range"))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) and value > 0.0 else None
    return None


def _rear_shock_lut_input_unit_from_profile(profile: Mapping[str, Any]) -> str:
    for transform in profile.get("signal_transforms", []) or []:
        if not isinstance(transform, Mapping):
            continue
        input_selector = transform.get("input")
        output_selector = transform.get("output")
        if not isinstance(input_selector, Mapping) or not isinstance(output_selector, Mapping):
            continue
        if transform.get("id") != "rear_shock_to_rear_wheel_travel" and not _matches_signal_selector(
            output_selector,
            _rear_wheel_selector(),
        ):
            continue
        if not all(
            input_selector.get(key) == expected
            for key, expected in {"end": "rear", "quantity": "disp", "domain": "suspension"}.items()
        ):
            continue
        try:
            return _coerce_rear_shock_lut_input_unit(input_selector.get("unit"))
        except ValueError:
            continue

    for item in profile.get("normalization_ranges", []) or []:
        if not isinstance(item, Mapping):
            continue
        signal = item.get("signal")
        if not isinstance(signal, Mapping):
            continue
        if item.get("id") != "rear_shock_travel_range" and not all(
            signal.get(key) == expected
            for key, expected in {"end": "rear", "quantity": "disp", "domain": "suspension"}.items()
        ):
            continue
        try:
            return _coerce_rear_shock_lut_input_unit(signal.get("unit"))
        except ValueError:
            continue

    return DEFAULT_REAR_SHOCK_LUT_INPUT_UNIT


def _remove_managed_front_wheel_normalization_range(profile: dict[str, Any]) -> None:
    ranges = profile.get("normalization_ranges")
    if not isinstance(ranges, list):
        return
    retained: list[Any] = []
    for item in ranges:
        if isinstance(item, Mapping):
            metadata = item.get("metadata")
            if (
                item.get("id") == FRONT_WHEEL_NORMALIZATION_RANGE_ID
                and isinstance(metadata, Mapping)
                and metadata.get("source") == FRONT_VERTICAL_TRANSFORM_SOURCE
            ):
                continue
        retained.append(item)
    profile["normalization_ranges"] = retained


def _is_managed_front_vertical_transform(transform: Mapping[str, Any]) -> bool:
    metadata = transform.get("metadata")
    return transform.get("id") == FRONT_VERTICAL_TRANSFORM_ID or (
        isinstance(metadata, Mapping) and metadata.get("source") == FRONT_VERTICAL_TRANSFORM_SOURCE
    )


def front_vertical_transform_from_profile(profile: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    for transform in profile.get("signal_transforms", []) or []:
        if isinstance(transform, Mapping) and _is_managed_front_vertical_transform(transform):
            return copy.deepcopy(dict(transform))
    return None


def front_head_angle_from_profile(profile: Mapping[str, Any]) -> Optional[float]:
    transform = front_vertical_transform_from_profile(profile)
    if transform is not None:
        metadata = transform.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("head_angle_deg") is not None:
            try:
                angle = float(metadata.get("head_angle_deg"))
            except (TypeError, ValueError):
                return None
            return angle if math.isfinite(angle) else None
        polynomial = transform.get("polynomial")
        if not isinstance(polynomial, Mapping):
            return None
        coeffs = polynomial.get("coefficients")
        if not isinstance(coeffs, Sequence) or isinstance(coeffs, (str, bytes, bytearray)) or len(coeffs) < 2:
            return None
        try:
            coefficient = float(
                coeffs[1] if polynomial.get("coefficient_order", "ascending") == "ascending" else coeffs[-2]
            )
        except (TypeError, ValueError):
            return None
        if not math.isfinite(coefficient) or coefficient <= 0.0 or coefficient >= 1.0:
            return None
        return math.degrees(math.asin(coefficient))

    bike = profile.get("bike")
    if not isinstance(bike, Mapping):
        return None
    for key in ("steering_head_angle_deg", "front_head_angle_deg", "head_angle_deg"):
        if bike.get(key) is None:
            continue
        try:
            angle = float(bike.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(angle) and 0.0 < angle < 90.0:
            return angle
    return None


def set_front_vertical_wheel_transform(profile: Mapping[str, Any], head_angle_deg: Any) -> dict[str, Any]:
    angle = _coerce_optional_head_angle(head_angle_deg)
    updated = copy.deepcopy(dict(profile))
    transforms = updated.setdefault("signal_transforms", [])
    if not isinstance(transforms, list):
        transforms = []

    retained = [
        dict(transform)
        for transform in transforms
        if not (isinstance(transform, Mapping) and _is_managed_front_vertical_transform(transform))
    ]

    if angle is not None:
        coefficient = math.sin(math.radians(angle))
        retained.append(
            {
                "id": FRONT_VERTICAL_TRANSFORM_ID,
                "description": "Front suspension travel converted to vertical front wheel travel from steering head angle.",
                "enabled": True,
                "input": _front_suspension_selector(),
                "output": _front_wheel_selector(),
                "method": "polynomial",
                "polynomial": {
                    "coefficient_order": "ascending",
                    "coefficients": [0.0, coefficient],
                },
                "metadata": {
                    "source": FRONT_VERTICAL_TRANSFORM_SOURCE,
                    "head_angle_deg": angle,
                    "linear_coefficient": coefficient,
                },
            }
        )
        front_fork_travel = _normalization_range_value(updated, _front_suspension_selector())
        if front_fork_travel is not None:
            _set_normalization_range_for_signal(
                updated,
                range_id=FRONT_WHEEL_NORMALIZATION_RANGE_ID,
                signal=_front_wheel_selector(),
                full_range=front_fork_travel * coefficient,
                field_name="front_wheel_travel_mm",
                metadata={
                    "source": FRONT_VERTICAL_TRANSFORM_SOURCE,
                    "source_range_id": "front_fork_travel_range",
                    "head_angle_deg": angle,
                    "linear_coefficient": coefficient,
                },
            )
    else:
        _remove_managed_front_wheel_normalization_range(updated)

    updated["signal_transforms"] = retained
    validate_bike_profile(updated)
    return updated


def bike_profile_form_values(profile: Mapping[str, Any]) -> dict[str, Any]:
    bike = profile.get("bike") if isinstance(profile.get("bike"), Mapping) else {}
    rear_shock_lut_input_unit = _rear_shock_lut_input_unit_from_profile(profile)
    values: dict[str, Any] = {
        "bike_profile_id": profile.get("bike_profile_id", ""),
        "display_name": profile.get("display_name", ""),
        "description": profile.get("description", ""),
        "manufacturer": bike.get("manufacturer", ""),
        "model": bike.get("model", ""),
        "model_year": bike.get("model_year", ""),
        "wheel_size": bike.get("wheel_size", ""),
        "bike_notes": bike.get("notes", ""),
        "front_head_angle_deg": "",
        "rear_shock_lut_input_unit": rear_shock_lut_input_unit,
    }
    head_angle = front_head_angle_from_profile(profile)
    if head_angle is not None:
        values["front_head_angle_deg"] = f"{head_angle:g}"
    for key, spec in _normalization_range_specs(
        rear_shock_lut_input_unit=rear_shock_lut_input_unit,
    ).items():
        values[key] = ""
        for item in profile.get("normalization_ranges", []) or []:
            if isinstance(item, Mapping) and (
                item.get("id") == spec["id"] or _matches_signal_selector(item.get("signal"), spec["signal"])
            ):
                values[key] = item.get("full_range", "")
                break
    return values


def apply_bike_profile_form_values(
    profile: Mapping[str, Any],
    values: Mapping[str, Any],
) -> dict[str, Any]:
    updated = copy.deepcopy(dict(profile))
    updated.setdefault("schema", BIKE_PROFILE_SCHEMA)
    updated.setdefault("version", BIKE_PROFILE_VERSION)
    updated.pop("setup", None)

    if "display_name" in values:
        display_name = _optional_text(values.get("display_name"))
        if display_name is None:
            raise ValueError("display_name must be non-empty")
        previous_profile_id = updated.get("bike_profile_id")
        updated["display_name"] = display_name
        if _profile_id_should_follow_display_name(previous_profile_id):
            updated["bike_profile_id"] = derive_profile_id(display_name)

    if "bike_profile_id" in values:
        # Programmatic callers can still pass an explicit ID; the UI does not expose it.
        profile_id = _optional_text(values.get("bike_profile_id"))
        if profile_id is None:
            raise ValueError("bike_profile_id must be non-empty")
        updated["bike_profile_id"] = derive_profile_id(profile_id)

    if _profile_id_should_follow_display_name(updated.get("bike_profile_id")):
        updated["bike_profile_id"] = derive_profile_id(str(updated.get("display_name") or "Bike profile"))

    rear_shock_lut_input_unit = (
        _coerce_rear_shock_lut_input_unit(values.get("rear_shock_lut_input_unit"))
        if "rear_shock_lut_input_unit" in values
        else _rear_shock_lut_input_unit_from_profile(updated)
    )

    if "description" in values:
        updated["description"] = str(values.get("description") or "")

    bike = dict(updated.get("bike") if isinstance(updated.get("bike"), Mapping) else {})
    for value_key, bike_key in (
        ("manufacturer", "manufacturer"),
        ("model", "model"),
        ("model_year", "model_year"),
        ("wheel_size", "wheel_size"),
        ("bike_notes", "notes"),
    ):
        if value_key in values:
            bike[bike_key] = str(values.get(value_key) or "")
    if "front_head_angle_deg" in values:
        angle = _coerce_optional_head_angle(values.get("front_head_angle_deg"))
        if angle is None:
            for key in ("steering_head_angle_deg", "front_head_angle_deg", "head_angle_deg"):
                bike.pop(key, None)
        else:
            bike["steering_head_angle_deg"] = angle
    updated["bike"] = bike

    for key in _normalization_range_specs(rear_shock_lut_input_unit=rear_shock_lut_input_unit):
        if key in values:
            _set_normalization_range(
                updated,
                key=key,
                value=values[key],
                rear_shock_lut_input_unit=rear_shock_lut_input_unit,
            )

    if "front_head_angle_deg" in values:
        updated = set_front_vertical_wheel_transform(updated, values.get("front_head_angle_deg"))

    validate_bike_profile(updated)
    return updated


def build_bike_profile_from_form(
    values: Mapping[str, Any],
    *,
    base_profile: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    base = (
        copy.deepcopy(dict(base_profile))
        if base_profile is not None
        else {
            "schema": BIKE_PROFILE_SCHEMA,
            "version": BIKE_PROFILE_VERSION,
            "bike_profile_id": "bike_profile",
            "display_name": "Bike profile",
            "description": "",
            "bike": {},
            "normalization_ranges": [],
            "signal_transforms": [],
            "installed_sensors": [],
        }
    )
    return apply_bike_profile_form_values(base, values)


def normalize_lut_points(points: Sequence[Mapping[str, Any]]) -> list[dict[str, float]]:
    if len(points) < 2:
        raise ValueError("LUT must contain at least two points")
    normalized: list[dict[str, float]] = []
    for index, point in enumerate(points):
        try:
            x = float(point.get("input"))
            y = float(point.get("output"))
        except (TypeError, ValueError):
            raise ValueError(f"LUT point {index + 1} must contain numeric input and output") from None
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"LUT point {index + 1} must contain finite input and output")
        normalized.append({"input": x, "output": y})
    for previous, current in zip(normalized, normalized[1:]):
        if current["input"] <= previous["input"]:
            raise ValueError("LUT input values must be strictly increasing")
    return normalized


def normalize_rear_lut_with_endpoints(
    points: Sequence[Mapping[str, Any]],
    *,
    rear_shock_travel_mm: Any,
    rear_wheel_travel_mm: Any,
) -> list[dict[str, float]]:
    shock_travel = _coerce_positive_float(rear_shock_travel_mm, field_name="rear_shock_travel_mm")
    wheel_travel = _coerce_positive_float(rear_wheel_travel_mm, field_name="rear_wheel_travel_mm")
    interiors: list[dict[str, float]] = []
    for index, point in enumerate(points):
        try:
            x = float(point.get("input"))
            y = float(point.get("output"))
        except (TypeError, ValueError):
            raise ValueError(f"LUT point {index + 1} must contain numeric input and output") from None
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"LUT point {index + 1} must contain finite input and output")
        if math.isclose(x, 0.0, rel_tol=0.0, abs_tol=1e-9) or math.isclose(
            x,
            shock_travel,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            continue
        if x <= 0.0 or x >= shock_travel:
            raise ValueError("LUT interior shock-travel values must be between 0 and rear shock travel")
        interiors.append({"input": x, "output": y})

    interiors.sort(key=lambda item: item["input"])
    for previous, current in zip(interiors, interiors[1:]):
        if math.isclose(current["input"], previous["input"], rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("LUT interior shock-travel values must be unique")

    return [
        {"input": 0.0, "output": 0.0},
        *interiors,
        {"input": shock_travel, "output": wheel_travel},
    ]


def parse_lut_text(text: str) -> list[dict[str, float]]:
    points: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line_number == 1 and re.search(r"[A-Za-z]", line):
            continue
        parts = [part for part in re.split(r"[\s,;]+", line) if part]
        if len(parts) != 2:
            raise ValueError(f"LUT line {line_number} must contain exactly two values")
        points.append({"input": parts[0], "output": parts[1]})
    return normalize_lut_points(points)


def format_lut_text(points: Sequence[Mapping[str, Any]]) -> str:
    normalized = normalize_lut_points(points)
    return "\n".join(f"{point['input']:g}, {point['output']:g}" for point in normalized) + "\n"


def _is_rear_wheel_lut_transform(transform: Mapping[str, Any]) -> bool:
    if transform.get("method") != "lut":
        return False
    if transform.get("id") == "rear_shock_to_rear_wheel_travel":
        return True
    input_selector = transform.get("input")
    output_selector = transform.get("output")
    if not _matches_signal_selector(output_selector, _rear_wheel_selector()):
        return False
    return any(
        _matches_signal_selector(input_selector, _rear_suspension_selector(unit))
        for unit in REAR_SHOCK_LUT_INPUT_UNITS
    )


def rear_wheel_lut_from_profile(profile: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    for transform in profile.get("signal_transforms", []) or []:
        if isinstance(transform, Mapping) and _is_rear_wheel_lut_transform(transform):
            return copy.deepcopy(dict(transform))
    return None


def set_rear_wheel_lut_transform(
    profile: Mapping[str, Any],
    points: Sequence[Mapping[str, Any]],
    *,
    input_unit: Any = DEFAULT_REAR_SHOCK_LUT_INPUT_UNIT,
    enabled: bool = True,
    interpolation: str = "linear",
    extrapolation: str = "linear",
) -> dict[str, Any]:
    normalized_points = normalize_lut_points(points)
    rear_shock_lut_input_unit = _coerce_rear_shock_lut_input_unit(input_unit)
    if interpolation not in {"linear", "nearest"}:
        raise ValueError("interpolation must be 'linear' or 'nearest'")
    if extrapolation not in {"clamp", "linear", "error"}:
        raise ValueError("extrapolation must be 'clamp', 'linear', or 'error'")

    updated = copy.deepcopy(dict(profile))
    transforms = updated.setdefault("signal_transforms", [])
    if not isinstance(transforms, list):
        transforms = []
        updated["signal_transforms"] = transforms

    transform_payload = {
        "id": "rear_shock_to_rear_wheel_travel",
        "description": "Rear shock travel to rear wheel travel LUT.",
        "enabled": bool(enabled),
        "input": _rear_suspension_selector(rear_shock_lut_input_unit),
        "output": _rear_wheel_selector(),
        "method": "lut",
        "interpolation": interpolation,
        "extrapolation": extrapolation,
        "lut": normalized_points,
    }

    for index, transform in enumerate(transforms):
        if isinstance(transform, Mapping) and _is_rear_wheel_lut_transform(transform):
            replacement = dict(transform)
            replacement.update(transform_payload)
            transforms[index] = replacement
            break
    else:
        transforms.append(transform_payload)

    validate_bike_profile(updated)
    return updated


def copy_source_bike_profile(from_source_root: str | Path, to_source_root: str | Path) -> Path:
    source_path, profile = load_source_bike_profile(from_source_root)
    try:
        target_path, _existing = load_source_bike_profile(to_source_root)
        shutil.copy2(source_path, target_path)
        return target_path
    except Exception:
        return save_source_bike_profile(to_source_root, profile, filename=source_path.name)


def _asset_json(filename: str) -> dict[str, Any]:
    asset = files(_ASSET_PACKAGE).joinpath(filename)
    payload = json.loads(asset.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Asset JSON must be an object: {filename}")
    return payload


def load_session_note_field_catalog() -> list[dict[str, Any]]:
    payload = _asset_json(_FIELD_CATALOG_FILENAME)
    if payload.get("schema") != "bodaqs.session_note_field_catalog":
        raise ValueError("Invalid session note field catalog schema")
    fields_raw = payload.get("fields")
    if not isinstance(fields_raw, list) or not fields_raw:
        raise ValueError("Session note field catalog must contain a non-empty fields list")
    # Validate catalog fields by wrapping them as a temporary note template.
    validate_session_note_template(
        {
            "schema": TEMPLATE_SCHEMA,
            "version": TEMPLATE_VERSION,
            "template_id": "catalog_validation",
            "template_version": "1.0",
            "title": "Catalog validation",
            "fields": fields_raw,
        }
    )
    return [copy.deepcopy(dict(field)) for field in fields_raw if isinstance(field, Mapping)]


def build_session_note_template_from_field_ids(
    *,
    field_ids: Sequence[str],
    template_id: str,
    template_version: str = "1.0",
    title: str,
    description: str = "",
    allow_custom_fields: bool = True,
    custom_field_section: str = "Custom",
    field_defaults: Optional[Mapping[str, Any]] = None,
    catalog: Optional[Sequence[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    selected_ids = [str(item).strip() for item in field_ids if str(item).strip()]
    if not selected_ids:
        raise ValueError("Select at least one session note field")
    catalog_items = list(catalog or load_session_note_field_catalog())
    by_id = {str(item.get("field_id")): dict(item) for item in catalog_items if isinstance(item, Mapping)}
    missing = [field_id for field_id in selected_ids if field_id not in by_id]
    if missing:
        raise ValueError(f"Unknown session note field ids: {missing}")
    selected_set = set(selected_ids)
    fields = [copy.deepcopy(item) for item in catalog_items if str(item.get("field_id")) in selected_set]
    defaults = {str(key): value for key, value in dict(field_defaults or {}).items()}
    for field in fields:
        field_id = str(field.get("field_id"))
        if field_id not in defaults:
            continue
        default_value = coerce_session_note_default_value(field, defaults[field_id])
        if default_value is None:
            field.pop("default", None)
        else:
            field["default"] = default_value
    template = {
        "schema": TEMPLATE_SCHEMA,
        "version": TEMPLATE_VERSION,
        "template_id": _optional_text(template_id) or "source_bike_setup",
        "template_version": _optional_text(template_version) or "1.0",
        "title": _optional_text(title) or "Source bike setup",
        "description": str(description or ""),
        "allow_custom_fields": bool(allow_custom_fields),
        "custom_field_section": _optional_text(custom_field_section) or "Custom",
        "fields": fields,
    }
    validate_session_note_template(template)
    return template


def derive_session_note_field_id(
    display_name: str,
    *,
    existing_ids: Sequence[str] = (),
    fallback: str = "custom_field",
    max_length: int = 64,
) -> str:
    if max_length < 8:
        raise ValueError("max_length must be at least 8")
    base = re.sub(r"[^A-Za-z0-9]+", "_", str(display_name).strip()).strip("_").lower()
    base = (base or fallback)[:max_length].strip("_") or fallback
    used = {str(item) for item in existing_ids}
    if base not in used:
        return base
    suffix = 2
    while True:
        suffix_text = f"_{suffix}"
        candidate = (base[: max_length - len(suffix_text)].strip("_") or fallback) + suffix_text
        if candidate not in used:
            return candidate
        suffix += 1


def build_custom_session_note_field(
    *,
    field_name: str,
    default_value: Any = "",
    existing_ids: Sequence[str] = (),
    section: str = "Custom",
) -> dict[str, Any]:
    label = _optional_text(field_name)
    if label is None:
        raise ValueError("Custom field name must be non-empty")
    text_default = "" if default_value is None else str(default_value)
    field_type = "text" if "\n" in text_default or len(text_default) > 80 else "string"
    field = {
        "field_id": derive_session_note_field_id(label, existing_ids=existing_ids),
        "label": label,
        "field_type": field_type,
        "section": _optional_text(section) or "Custom",
        "project_to_catalog": field_type == "string",
        "sortable": field_type == "string",
        "filterable": field_type == "string",
    }
    default = coerce_session_note_default_value(field, text_default)
    if default is not None:
        field["default"] = default
    validate_session_note_template(
        {
            "schema": TEMPLATE_SCHEMA,
            "version": TEMPLATE_VERSION,
            "template_id": "custom_field_validation",
            "template_version": "1.0",
            "title": "Custom field validation",
            "fields": [field],
        }
    )
    return field


def coerce_session_note_default_value(field: Mapping[str, Any], value: Any) -> Any:
    field_id = str(field.get("field_id") or "field")
    field_type = str(field.get("field_type") or "string")
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return "" if field_type in {"string", "text", "date"} else None
    if field_type in {"string", "text", "date", "enum"}:
        return text
    if field_type == "int":
        try:
            result = int(text)
        except (TypeError, ValueError):
            raise ValueError(f"Default for {field_id!r} must be an integer") from None
        return result
    if field_type == "float":
        try:
            result = float(text)
        except (TypeError, ValueError):
            raise ValueError(f"Default for {field_id!r} must be numeric") from None
        if not math.isfinite(result):
            raise ValueError(f"Default for {field_id!r} must be finite")
        return result
    if field_type == "bool":
        lowered = text.lower()
        if lowered in {"true", "yes", "y", "1", "on"}:
            return True
        if lowered in {"false", "no", "n", "0", "off"}:
            return False
        raise ValueError(f"Default for {field_id!r} must be true or false")
    if field_type == "multi_enum":
        return [part.strip() for part in text.split(",") if part.strip()]
    return text


def _template_field_ids(template: Mapping[str, Any]) -> set[str]:
    return {
        str(field.get("field_id"))
        for field in template.get("fields", []) or []
        if isinstance(field, Mapping) and _optional_text(field.get("field_id"))
    }


def sync_bike_setup_preset_for_template(
    preset: Mapping[str, Any],
    template: Mapping[str, Any],
    *,
    bike_profile: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(dict(preset))
    updated.setdefault("schema", SESSION_NOTE_PRESET_SCHEMA)
    updated.setdefault("version", SESSION_NOTE_PRESET_VERSION)
    updated["template_id"] = str(template.get("template_id") or "")
    updated["template_version"] = str(template.get("template_version") or "1.0")

    if not _optional_text(updated.get("preset_id")):
        updated["preset_id"] = "default_bike_setup"
    if not _optional_text(updated.get("display_name")):
        updated["display_name"] = "Default bike setup"
    if not _optional_text(updated.get("title")):
        updated["title"] = "Imported bike setup"

    bike_display_name = None
    if bike_profile is not None:
        updated["bike_profile_id"] = _optional_text(bike_profile.get("bike_profile_id"))
        bike_display_name = _optional_text(bike_profile.get("display_name"))

    field_ids = _template_field_ids(template)
    values = updated.get("values") if isinstance(updated.get("values"), Mapping) else {}
    filtered_values = {str(key): value for key, value in dict(values).items() if str(key) in field_ids}
    if "bike" in field_ids and bike_display_name is not None:
        filtered_values["bike"] = bike_display_name
    updated["values"] = filtered_values

    custom_values = updated.get("custom_values") if isinstance(updated.get("custom_values"), Mapping) else {}
    updated["custom_values"] = {str(key): value for key, value in dict(custom_values).items()}
    validate_bike_setup_preset(updated)
    return updated


def sync_source_bike_setup_preset(source_root: str | Path) -> Path:
    _template_path, template = load_source_session_note_template(source_root)
    _preset_path, preset = load_source_bike_setup_preset(source_root)
    try:
        _bike_path, bike_profile = load_source_bike_profile(source_root)
    except Exception:
        bike_profile = None
    updated = sync_bike_setup_preset_for_template(preset, template, bike_profile=bike_profile)
    return save_source_bike_setup_preset(source_root, updated)


def save_source_session_note_assets(
    source_root: str | Path,
    template: Mapping[str, Any],
    *,
    preset: Optional[Mapping[str, Any]] = None,
) -> tuple[Path, Path]:
    validate_session_note_template(template)
    if preset is None:
        try:
            _preset_path, preset_payload = load_source_bike_setup_preset(source_root)
        except Exception:
            preset_payload = {
                "schema": SESSION_NOTE_PRESET_SCHEMA,
                "version": SESSION_NOTE_PRESET_VERSION,
                "preset_id": "default_bike_setup",
                "display_name": "Default bike setup",
                "template_id": template.get("template_id"),
                "template_version": template.get("template_version"),
                "bike_profile_id": None,
                "title": "Imported bike setup",
                "values": {},
                "custom_values": {},
                "free_text_notes": (
                    "Draft note created automatically by the BODAQS import manager. "
                    "Review and save it in the library manager when the setup details are confirmed."
                ),
            }
    else:
        preset_payload = copy.deepcopy(dict(preset))
    try:
        _bike_path, bike_profile = load_source_bike_profile(source_root)
    except Exception:
        bike_profile = None
    synced_preset = sync_bike_setup_preset_for_template(preset_payload, template, bike_profile=bike_profile)
    template_path = save_source_session_note_template(source_root, template)
    preset_path = save_source_bike_setup_preset(source_root, synced_preset)
    return template_path, preset_path


def copy_source_note_assets(from_source_root: str | Path, to_source_root: str | Path) -> tuple[Path, Path]:
    _template_path, template = load_source_session_note_template(from_source_root)
    _preset_path, preset = load_source_bike_setup_preset(from_source_root)
    return save_source_session_note_assets(to_source_root, template, preset=preset)
