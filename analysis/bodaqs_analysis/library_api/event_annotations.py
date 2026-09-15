"""Root-scoped, revision-safe user tags for detected Events."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import EventAnnotationNotFoundError, InvalidEventAnnotationError, RevisionConflictError
from .ids import is_valid_object_id, make_session_key, make_session_ref_id, make_unique_object_id


EVENT_ANNOTATION_SCHEMA = "bodaqs.event_annotation"
EVENT_ANNOTATION_VERSION = 1
EVENT_ANNOTATIONS_DIR = Path("event_annotations")


def query_event_annotations(libraries_root: str | Path, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    if not isinstance(request, Mapping):
        raise InvalidEventAnnotationError("Event annotation query must be an object.")
    wanted_refs = {
        _session_ref_id(item)
        for item in request.get("sessions") or []
        if isinstance(item, Mapping)
    }
    wanted_tags = {_tag_key(tag) for tag in request.get("tags") or [] if _tag_key(tag)}
    annotations = []
    for path in sorted(_annotations_dir(libraries_root).glob("*.json"), key=lambda item: item.name.lower()):
        annotation = _normalized_annotation(_read(path), annotation_id=path.stem, revision=None)
        event_ref = annotation["event_ref"]
        if wanted_refs and str(event_ref.get("session_ref_id") or "") not in wanted_refs:
            continue
        if wanted_tags and not wanted_tags.intersection(_tag_key(tag) for tag in annotation["tags"]):
            continue
        annotations.append(annotation)
    return {
        "schema": "bodaqs.event_annotations",
        "version": 1,
        "annotations": annotations,
    }


def load_event_annotation(libraries_root: str | Path, annotation_id: str) -> dict[str, Any]:
    path = _annotation_path(libraries_root, annotation_id)
    if not path.exists():
        raise EventAnnotationNotFoundError(details={"annotation_id": annotation_id})
    return _normalized_annotation(_read(path), annotation_id=annotation_id, revision=None)


def create_event_annotation(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidEventAnnotationError("Event annotation must be an object.")
    existing = query_event_annotations(libraries_root)["annotations"]
    event_ref = _normalized_event_ref(payload.get("event_ref"))
    event_key = _event_key(event_ref)
    if any(_event_key(item["event_ref"]) == event_key for item in existing):
        raise InvalidEventAnnotationError(
            "An annotation already exists for this Event.", details={"event_key": event_key}
        )
    requested_id = _optional_text(payload.get("annotation_id"))
    annotation_id = requested_id or make_unique_object_id(
        f"event-{event_ref['event_id']}",
        [str(item["annotation_id"]) for item in existing],
        fallback="event-annotation",
    )
    if not is_valid_object_id(annotation_id):
        raise InvalidEventAnnotationError("annotation_id is not filename-safe.")
    now = _utcnow_iso()
    annotation = _normalized_annotation(
        {**dict(payload), "event_ref": event_ref},
        annotation_id=annotation_id,
        revision=1,
        now=now,
    )
    _write(libraries_root, annotation)
    return annotation


def update_event_annotation(
    libraries_root: str | Path,
    annotation_id: str,
    *,
    expected_revision: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidEventAnnotationError("Event annotation must be an object.")
    current = load_event_annotation(libraries_root, annotation_id)
    if int(expected_revision) != int(current["revision"]):
        raise RevisionConflictError(
            "Event annotation was modified after it was loaded.",
            details={
                "annotation_id": annotation_id,
                "expected_revision": int(expected_revision),
                "current_revision": int(current["revision"]),
            },
        )
    merged = {**current, **dict(payload), "event_ref": current["event_ref"]}
    annotation = _normalized_annotation(
        merged,
        annotation_id=annotation_id,
        revision=int(current["revision"]) + 1,
        now=_utcnow_iso(),
        previous=current,
    )
    _write(libraries_root, annotation)
    return annotation


def delete_event_annotation(libraries_root: str | Path, annotation_id: str) -> dict[str, Any]:
    path = _annotation_path(libraries_root, annotation_id)
    if not path.exists():
        raise EventAnnotationNotFoundError(details={"annotation_id": annotation_id})
    path.unlink()
    return {"deleted": True, "annotation_id": annotation_id}


def _normalized_annotation(
    payload: Mapping[str, Any],
    *,
    annotation_id: str,
    revision: int | None,
    now: str | None = None,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not is_valid_object_id(annotation_id):
        raise InvalidEventAnnotationError("annotation_id is not filename-safe.")
    stored_revision = revision if revision is not None else payload.get("revision")
    if isinstance(stored_revision, bool) or not isinstance(stored_revision, int):
        raise InvalidEventAnnotationError("revision must be an integer.")
    tags = _normalized_tags(payload.get("tags"))
    event_ref = _normalized_event_ref(payload.get("event_ref"))
    previous_created = previous.get("created_at_utc") if isinstance(previous, Mapping) else None
    created = str(previous_created or payload.get("created_at_utc") or now or "")
    updated = str(now or payload.get("updated_at_utc") or created)
    return {
        "schema": EVENT_ANNOTATION_SCHEMA,
        "version": EVENT_ANNOTATION_VERSION,
        "annotation_id": annotation_id,
        "revision": int(stored_revision),
        "event_ref": event_ref,
        "tags": tags,
        "created_at_utc": created,
        "updated_at_utc": updated,
    }


def _normalized_event_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidEventAnnotationError("event_ref must be an object.")
    library_id = _required_text(value.get("library_id"), "event_ref.library_id")
    run_id = _required_text(value.get("run_id"), "event_ref.run_id")
    session_id = _required_text(value.get("session_id"), "event_ref.session_id")
    event_set_id = _required_text(value.get("event_set_id") or value.get("set_id"), "event_ref.event_set_id")
    event_id = _required_text(value.get("event_id"), "event_ref.event_id")
    expected_key = make_session_key(run_id, session_id)
    session_key = _optional_text(value.get("session_key")) or expected_key
    if session_key != expected_key:
        raise InvalidEventAnnotationError("event_ref.session_key does not match run_id/session_id.")
    expected_ref_id = make_session_ref_id(library_id, session_key)
    session_ref_id = _optional_text(value.get("session_ref_id")) or expected_ref_id
    if session_ref_id != expected_ref_id:
        raise InvalidEventAnnotationError("event_ref.session_ref_id does not match library_id/session_key.")
    return {
        **dict(value),
        "library_id": library_id,
        "run_id": run_id,
        "session_id": session_id,
        "session_key": session_key,
        "session_ref_id": session_ref_id,
        "event_set_id": event_set_id,
        "event_id": event_id,
        "schema_id": str(value.get("schema_id") or ""),
        "schema_version": str(value.get("schema_version") or ""),
        "schema_digest": str(value.get("schema_digest") or ""),
        "params_hash": str(value.get("params_hash") or ""),
        "trigger_time_s": value.get("trigger_time_s"),
    }


def _normalized_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InvalidEventAnnotationError("tags must be a list.")
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        tag = str(raw).strip()
        key = _tag_key(tag)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def _event_key(event_ref: Mapping[str, Any]) -> str:
    return "|||".join(
        str(event_ref.get(key) or "")
        for key in ("library_id", "session_key", "event_set_id", "event_id")
    )


def _session_ref_id(value: Mapping[str, Any]) -> str:
    library_id = str(value.get("library_id") or "")
    session_key = str(value.get("session_key") or "")
    if not session_key and value.get("run_id") and value.get("session_id"):
        session_key = make_session_key(str(value["run_id"]), str(value["session_id"]))
    return str(value.get("session_ref_id") or make_session_ref_id(library_id, session_key))


def _tag_key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _annotations_dir(libraries_root: str | Path) -> Path:
    return Path(libraries_root) / EVENT_ANNOTATIONS_DIR


def _annotation_path(libraries_root: str | Path, annotation_id: str) -> Path:
    if not is_valid_object_id(annotation_id):
        raise InvalidEventAnnotationError("annotation_id is not filename-safe.")
    return _annotations_dir(libraries_root) / f"{annotation_id}.json"


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise EventAnnotationNotFoundError(details={"annotation_id": path.stem})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidEventAnnotationError(
            "Event annotation JSON could not be read.", details={"path": str(path), "error": str(exc)}
        ) from exc
    if not isinstance(value, Mapping):
        raise InvalidEventAnnotationError("Event annotation JSON must be an object.")
    return dict(value)


def _write(libraries_root: str | Path, payload: Mapping[str, Any]) -> None:
    path = _annotation_path(libraries_root, str(payload["annotation_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidEventAnnotationError(f"{field_name} is required.")
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
