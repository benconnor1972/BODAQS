from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


SESSION_NOTE_PRESET_SCHEMA = "bodaqs.session_note_preset"
SESSION_NOTE_PRESET_VERSION = 1


@dataclass(frozen=True)
class BikeSetupPreset:
    preset_id: str
    display_name: str
    template_id: str
    template_version: str | None
    bike_profile_id: str | None
    title: str | None
    values: Dict[str, Any]
    custom_values: Dict[str, Any]
    free_text_notes: str | None


def _optional_text(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def parse_bike_setup_preset(value: Mapping[str, Any] | str | bytes | Path) -> BikeSetupPreset:
    if isinstance(value, Mapping):
        obj = copy.deepcopy(dict(value))
    else:
        if isinstance(value, Path):
            text = value.read_text(encoding="utf-8")
        elif isinstance(value, bytes):
            text = value.decode("utf-8")
        elif isinstance(value, str):
            candidate = Path(value)
            text = candidate.read_text(encoding="utf-8") if candidate.exists() else value
        else:
            raise TypeError("bike setup preset must be a mapping, JSON text/bytes, or a path")
        obj = json.loads(text)

    if not isinstance(obj, Mapping):
        raise ValueError("Bike setup preset must be a JSON object")
    if obj.get("schema") != SESSION_NOTE_PRESET_SCHEMA:
        raise ValueError(
            f"Unexpected bike setup preset schema: {obj.get('schema')!r} "
            f"(expected {SESSION_NOTE_PRESET_SCHEMA!r})"
        )
    if int(obj.get("version", -1)) != SESSION_NOTE_PRESET_VERSION:
        raise ValueError(
            f"Unexpected bike setup preset version: {obj.get('version')!r} "
            f"(expected {SESSION_NOTE_PRESET_VERSION})"
        )

    preset_id = _optional_text(obj.get("preset_id"))
    display_name = _optional_text(obj.get("display_name"))
    template_id = _optional_text(obj.get("template_id"))
    if preset_id is None:
        raise ValueError("Bike setup preset missing non-empty 'preset_id'")
    if display_name is None:
        raise ValueError("Bike setup preset missing non-empty 'display_name'")
    if template_id is None:
        raise ValueError("Bike setup preset missing non-empty 'template_id'")

    values = obj.get("values", {})
    custom_values = obj.get("custom_values", {})
    if not isinstance(values, Mapping):
        raise ValueError("Bike setup preset 'values' must be an object")
    if not isinstance(custom_values, Mapping):
        raise ValueError("Bike setup preset 'custom_values' must be an object")

    return BikeSetupPreset(
        preset_id=preset_id,
        display_name=display_name,
        template_id=template_id,
        template_version=_optional_text(obj.get("template_version")),
        bike_profile_id=_optional_text(obj.get("bike_profile_id")),
        title=_optional_text(obj.get("title")),
        values={str(k): v for k, v in dict(values).items()},
        custom_values={str(k): v for k, v in dict(custom_values).items()},
        free_text_notes=(
            None if obj.get("free_text_notes") is None else str(obj.get("free_text_notes"))
        ),
    )


def validate_bike_setup_preset(
    value: Mapping[str, Any] | str | bytes | Path,
    *,
    path: Optional[str | Path] = None,
) -> None:
    parse_bike_setup_preset(value)


def load_bike_setup_preset(path: str | Path) -> BikeSetupPreset:
    return parse_bike_setup_preset(Path(path))
