"""Root-scoped persisted session filters for the BODAQS Library API."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import InvalidSessionFilterError, RevisionConflictError, SessionFilterNotFoundError
from .ids import is_valid_object_id, make_unique_object_id


SESSION_FILTER_SCHEMA = "bodaqs.session_filter"
SESSION_FILTER_VERSION = 1
SESSION_FILTERS_DIR = Path("session_filters")

_GROUP_OPS = {"and", "or"}
_LEAF_OPS = {"eq", "in", "contains", "present", "gte", "lt"}
_TRACKPOINT_OPS = {"matches"}
_FIELDS = {
    "bike",
    "event.schema",
    "firmware",
    "gps.present",
    "gps.quality",
    "gps.source",
    "note.status",
    "preprocessing.profile",
    "qc.level",
    "rider",
    "signals",
    "source.archive",
    "started",
    "trackpoint.crossing",
}


def list_session_filters(libraries_root: str | Path) -> list[dict[str, Any]]:
    """Return all root-scoped persisted Session Filter objects."""

    out: list[dict[str, Any]] = []
    for path in sorted(_session_filters_dir(libraries_root).glob("*.json"), key=lambda p: p.name.lower()):
        doc = _read_json_object(path)
        out.append(_normalized_session_filter_payload(doc, filter_id=str(doc.get("filter_id") or path.stem), revision=None))
    return out


def load_session_filter(libraries_root: str | Path, filter_id: str) -> dict[str, Any]:
    """Load one root-scoped persisted Session Filter object."""

    path = _session_filter_path(libraries_root, filter_id)
    if not path.exists():
        raise SessionFilterNotFoundError("Session filter was not found.", details={"filter_id": str(filter_id)})
    return _normalized_session_filter_payload(_read_json_object(path), filter_id=str(filter_id), revision=None)


def create_session_filter(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create a root-scoped persisted Session Filter object."""

    if not isinstance(payload, Mapping):
        raise InvalidSessionFilterError("Session filter payload must be a JSON object.")
    existing_ids = [filter_doc["filter_id"] for filter_doc in list_session_filters(libraries_root)]
    display_name = _required_text(payload.get("display_name"), field_name="display_name")
    requested_id = _optional_text(payload.get("filter_id"))
    filter_id = requested_id or make_unique_object_id(display_name, existing_ids, fallback="session-filter")
    if filter_id in set(existing_ids):
        raise InvalidSessionFilterError("Session filter id already exists.", details={"filter_id": filter_id})
    if not is_valid_object_id(filter_id):
        raise InvalidSessionFilterError("Session filter id is not filename-safe.", details={"filter_id": filter_id})

    now = _utcnow_iso()
    doc = _normalized_session_filter_payload(
        payload,
        filter_id=filter_id,
        revision=1,
        now=now,
        previous=None,
    )
    _write_session_filter(libraries_root, doc)
    return doc


def update_session_filter(
    libraries_root: str | Path,
    filter_id: str,
    *,
    expected_revision: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Update one root-scoped persisted Session Filter object."""

    if not isinstance(payload, Mapping):
        raise InvalidSessionFilterError("Session filter payload must be a JSON object.")
    current = load_session_filter(libraries_root, filter_id)
    current_revision = int(current.get("revision") or 0)
    if int(expected_revision) != current_revision:
        raise RevisionConflictError(
            "Session filter was modified after it was loaded.",
            details={
                "filter_id": str(filter_id),
                "expected_revision": int(expected_revision),
                "current_revision": current_revision,
            },
        )

    now = _utcnow_iso()
    doc = _normalized_session_filter_payload(
        payload,
        filter_id=str(filter_id),
        revision=current_revision + 1,
        now=now,
        previous=current,
    )
    _write_session_filter(libraries_root, doc)
    return doc


def delete_session_filter(libraries_root: str | Path, filter_id: str) -> dict[str, Any]:
    """Delete one root-scoped persisted Session Filter object."""

    path = _session_filter_path(libraries_root, filter_id)
    if not path.exists():
        raise SessionFilterNotFoundError("Session filter was not found.", details={"filter_id": str(filter_id)})
    path.unlink()
    return {"deleted": True, "filter_id": str(filter_id)}


def _normalized_session_filter_payload(
    payload: Mapping[str, Any],
    *,
    filter_id: str,
    revision: int | None,
    now: str | None = None,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    doc = dict(payload)
    doc["schema"] = SESSION_FILTER_SCHEMA
    doc["version"] = SESSION_FILTER_VERSION
    doc["filter_id"] = str(filter_id)
    if not is_valid_object_id(doc["filter_id"]):
        raise InvalidSessionFilterError("Session filter id is not filename-safe.", details={"filter_id": doc["filter_id"]})
    doc["display_name"] = _required_text(doc.get("display_name"), field_name="display_name")
    doc["description"] = _optional_text(doc.get("description")) or ""
    doc["category"] = _optional_text(doc.get("category")) or ""
    if revision is not None:
        doc["revision"] = int(revision)
    elif not isinstance(doc.get("revision"), int) or isinstance(doc.get("revision"), bool):
        raise InvalidSessionFilterError("Session filter revision must be an integer.")
    doc["predicate"] = _normalized_predicate(doc.get("predicate"), context="predicate")

    scope = doc.get("scope")
    if scope is not None and not isinstance(scope, Mapping):
        raise InvalidSessionFilterError("Session filter scope must be an object when present.")
    if scope is not None:
        doc["scope"] = dict(scope)

    previous_provenance = previous.get("provenance") if isinstance(previous, Mapping) else None
    provenance = doc.get("provenance")
    provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
    if isinstance(previous_provenance, Mapping):
        provenance.setdefault("created_at", previous_provenance.get("created_at"))
        provenance.setdefault("created_by", previous_provenance.get("created_by"))
    if now is not None:
        provenance.setdefault("created_at", now)
        provenance.setdefault("created_by", "user")
        provenance["updated_at"] = now
    doc["provenance"] = provenance

    display_state = doc.get("display_state")
    doc["display_state"] = dict(display_state) if isinstance(display_state, Mapping) else {"bodaqs_web_v1": {}}
    doc["display_state"].setdefault("bodaqs_web_v1", {})
    return doc


def _normalized_predicate(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidSessionFilterError(f"{context} must be a predicate object.")
    op = _required_text(value.get("op"), field_name=f"{context}.op")
    if op in _GROUP_OPS:
        children = value.get("children")
        if not isinstance(children, list):
            raise InvalidSessionFilterError(f"{context}.children must be a list.")
        return {
            "op": op,
            "children": [
                _normalized_predicate(child, context=f"{context}.children[{index}]")
                for index, child in enumerate(children)
            ],
        }
    field = _required_text(value.get("field"), field_name=f"{context}.field")
    if field not in _FIELDS:
        raise InvalidSessionFilterError(f"{context}.field is not supported.", details={"field": field})
    if op in _TRACKPOINT_OPS:
        if field != "trackpoint.crossing":
            raise InvalidSessionFilterError(
                f"{context}.op is only supported for trackpoint crossing predicates.",
                details={"field": field, "op": op},
            )
        if "value" not in value:
            raise InvalidSessionFilterError(f"{context}.value is required for {op!r}.")
        return {
            "field": field,
            "op": op,
            "value": _normalized_trackpoint_match_value(value.get("value"), context=f"{context}.value"),
        }
    if op not in _LEAF_OPS:
        raise InvalidSessionFilterError(f"{context}.op is not supported.", details={"op": op})
    if field == "trackpoint.crossing":
        raise InvalidSessionFilterError(
            f"{context}.field requires a trackpoint match operator.",
            details={"field": field, "op": op},
        )

    out: dict[str, Any] = {"field": field, "op": op}
    if op == "present":
        if "value" in value:
            out["value"] = bool(value.get("value"))
        return out
    if op in {"gte", "lt"}:
        if field != "started":
            raise InvalidSessionFilterError(
                f"{context}.op is only supported for started predicates.",
                details={"field": field, "op": op},
            )
        if "value" not in value:
            raise InvalidSessionFilterError(f"{context}.value is required for {op!r}.")
        out["value"] = _normalized_datetime_value(value.get("value"), context=f"{context}.value")
        return out
    if "value" not in value:
        raise InvalidSessionFilterError(f"{context}.value is required for {op!r}.")
    raw_value = value.get("value")
    if op == "in":
        if not isinstance(raw_value, list):
            raise InvalidSessionFilterError(f"{context}.value must be a list for 'in'.")
        out["value"] = [str(item).strip() for item in raw_value if str(item).strip()]
    elif isinstance(raw_value, bool):
        out["value"] = raw_value
    else:
        out["value"] = str(raw_value).strip()
    return out


def _normalized_trackpoint_match_value(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidSessionFilterError(f"{context} must be an object for trackpoint matching.")

    track_id = _optional_text(value.get("track_id")) or _optional_text(value.get("trackId"))
    if track_id is None:
        raise InvalidSessionFilterError(f"{context}.track_id is required.")

    raw_trackpoint_ids = value.get("trackpoint_ids")
    if raw_trackpoint_ids is None:
        raw_trackpoint_ids = value.get("trackpointIds")
    if raw_trackpoint_ids is None:
        raw_trackpoint_id = _optional_text(value.get("trackpoint_id")) or _optional_text(value.get("trackpointId"))
        raw_trackpoint_ids = [raw_trackpoint_id] if raw_trackpoint_id is not None else []
    if not isinstance(raw_trackpoint_ids, list):
        raise InvalidSessionFilterError(f"{context}.trackpoint_ids must be a list.")
    trackpoint_ids = [str(item).strip() for item in raw_trackpoint_ids if str(item).strip()]
    if not trackpoint_ids:
        raise InvalidSessionFilterError(f"{context}.trackpoint_ids must contain at least one trackpoint id.")

    match_mode = _optional_text(value.get("match_mode")) or _optional_text(value.get("matchMode")) or "all"
    if match_mode not in {"any", "all", "min_count"}:
        raise InvalidSessionFilterError(
            f"{context}.match_mode is not supported.",
            details={"match_mode": match_mode},
        )

    tolerance_m = _number_or_none(value.get("tolerance_m"))
    if tolerance_m is None:
        tolerance_m = _number_or_none(value.get("toleranceM"))
    if tolerance_m is None:
        tolerance_m = 5.0
    if tolerance_m < 0:
        raise InvalidSessionFilterError(f"{context}.tolerance_m must be non-negative.")

    out: dict[str, Any] = {
        "track_id": track_id,
        "trackpoint_ids": trackpoint_ids,
        "match_mode": match_mode,
        "tolerance_m": tolerance_m,
    }
    if match_mode == "min_count" or "min_count" in value or "minCount" in value:
        min_count = _number_or_none(value.get("min_count"))
        if min_count is None:
            min_count = _number_or_none(value.get("minCount"))
        if min_count is None or min_count < 1 or int(min_count) != min_count:
            raise InvalidSessionFilterError(f"{context}.min_count must be a positive integer.")
        out["min_count"] = int(min_count)

    policy_ref = value.get("policy_ref") or value.get("policyRef")
    if policy_ref is not None:
        if not isinstance(policy_ref, Mapping):
            raise InvalidSessionFilterError(f"{context}.policy_ref must be an object when present.")
        out["policy_ref"] = dict(policy_ref)
    return out


def _session_filters_dir(libraries_root: str | Path) -> Path:
    return Path(libraries_root) / SESSION_FILTERS_DIR


def _session_filter_path(libraries_root: str | Path, filter_id: str) -> Path:
    filter_id = _required_text(filter_id, field_name="filter_id")
    if not is_valid_object_id(filter_id):
        raise InvalidSessionFilterError("Session filter id is not filename-safe.", details={"filter_id": filter_id})
    return _session_filters_dir(libraries_root) / f"{filter_id}.json"


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SessionFilterNotFoundError("Session filter was not found.", details={"filter_id": path.stem})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidSessionFilterError(
            "Session filter JSON could not be read.",
            details={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    if not isinstance(value, Mapping):
        raise InvalidSessionFilterError("Session filter JSON must be an object.", details={"path": str(path)})
    return dict(value)


def _write_session_filter(libraries_root: str | Path, payload: Mapping[str, Any]) -> None:
    filter_id = str(payload["filter_id"])
    path = _session_filter_path(libraries_root, filter_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidSessionFilterError(f"Session filter missing non-empty {field_name!r}.")
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _normalized_datetime_value(value: Any, *, context: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidSessionFilterError(f"{context} must be a non-empty ISO date/time string.")
    parseable_text = text.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(parseable_text)
    except ValueError as exc:
        raise InvalidSessionFilterError(f"{context} must be a parseable ISO date/time string.") from exc
    return text


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
