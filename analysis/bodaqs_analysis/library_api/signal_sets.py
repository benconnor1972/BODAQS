"""Root-scoped Signal Inspector set definitions.

The user-editable ``signal_sets.json`` file keeps the Inspector's initial
signal taxonomy outside individual sessions and outside the frontend bundle.
Sets contain OR-ed rules; fields within a rule are AND-ed by the browser
against session-catalog signal metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .errors import InvalidRequestError


SIGNAL_SETS_FILENAME = "signal_sets.json"
SIGNAL_SETS_SCHEMA = "bodaqs.signal_sets"
SIGNAL_SETS_VERSION = 1


def load_signal_sets(libraries_root: str | Path) -> dict[str, Any]:
    """Load and minimally validate the root-scoped Signal Inspector sets."""

    path = Path(libraries_root) / SIGNAL_SETS_FILENAME
    if not path.exists():
        return {
            "schema": SIGNAL_SETS_SCHEMA,
            "version": SIGNAL_SETS_VERSION,
            "configured": False,
            "sets": [],
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidRequestError(
            "Signal-set configuration could not be read.",
            details={"path": str(path), "exception": str(exc)},
        ) from exc
    if not isinstance(raw, Mapping):
        raise _invalid_signal_sets(path, "Top-level JSON must be an object.")
    if raw.get("schema") != SIGNAL_SETS_SCHEMA:
        raise _invalid_signal_sets(path, f"schema must be {SIGNAL_SETS_SCHEMA!r}.")
    if raw.get("version") != SIGNAL_SETS_VERSION:
        raise _invalid_signal_sets(path, f"version must be {SIGNAL_SETS_VERSION}.")
    raw_sets = raw.get("sets")
    if not isinstance(raw_sets, list):
        raise _invalid_signal_sets(path, "sets must be an array.")

    seen_ids: set[str] = set()
    sets: list[dict[str, Any]] = []
    for index, raw_set in enumerate(raw_sets):
        if not isinstance(raw_set, Mapping):
            raise _invalid_signal_sets(path, f"sets[{index}] must be an object.")
        set_id = _required_text(raw_set.get("id"), f"sets[{index}].id", path)
        if set_id in seen_ids:
            raise _invalid_signal_sets(path, f"Duplicate set id {set_id!r}.")
        seen_ids.add(set_id)
        display_name = _required_text(raw_set.get("display_name"), f"sets[{index}].display_name", path)
        raw_rules = raw_set.get("rules")
        if not isinstance(raw_rules, list) or not raw_rules:
            raise _invalid_signal_sets(path, f"sets[{index}].rules must be a non-empty array.")
        rules: list[dict[str, Any]] = []
        for rule_index, rule in enumerate(raw_rules):
            if not isinstance(rule, Mapping):
                raise _invalid_signal_sets(path, f"sets[{index}].rules[{rule_index}] must be an object.")
            rules.append(dict(rule))
        raw_default_exclusions = raw_set.get("default_exclusion_rules", [])
        if not isinstance(raw_default_exclusions, list) or not all(isinstance(rule, Mapping) for rule in raw_default_exclusions):
            raise _invalid_signal_sets(path, f"sets[{index}].default_exclusion_rules must be an array of objects.")
        sets.append({
            "id": set_id,
            "display_name": display_name,
            "description": str(raw_set.get("description") or "").strip(),
            "default_selection_set": str(raw_set.get("default_selection_set") or "").strip(),
            "default_exclusion_rules": [dict(rule) for rule in raw_default_exclusions],
            "rules": rules,
        })
    known_ids = {str(signal_set["id"]) for signal_set in sets}
    for signal_set in sets:
        default_selection_set = str(signal_set.get("default_selection_set") or "")
        if default_selection_set and default_selection_set not in known_ids:
            raise _invalid_signal_sets(
                path,
                f"default_selection_set {default_selection_set!r} for {signal_set['id']!r} does not name a configured set.",
            )
    return {
        "schema": SIGNAL_SETS_SCHEMA,
        "version": SIGNAL_SETS_VERSION,
        "configured": True,
        "sets": sets,
    }


def _required_text(value: Any, field: str, path: Path) -> str:
    text = str(value or "").strip()
    if not text:
        raise _invalid_signal_sets(path, f"{field} must be a non-empty string.")
    return text


def _invalid_signal_sets(path: Path, message: str) -> InvalidRequestError:
    return InvalidRequestError(
        f"Invalid signal-set configuration: {message}",
        details={"path": str(path)},
    )
