"""Session note document access for the BODAQS Library API."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from bodaqs_analysis.artifacts import ArtifactStore
from bodaqs_analysis.session_notes import make_session_note_template_store

from .errors import InvalidRequestError


SESSION_NOTE_DOCUMENT_SCHEMA = "bodaqs.session_notes.document"
SESSION_NOTE_DOCUMENT_VERSION = 1
SESSION_NOTE_API_SCHEMA = "bodaqs.library_api.session_note"
SESSION_NOTE_API_VERSION = 1


def load_session_note(library_root: str | Path, session_ref: Mapping[str, Any]) -> dict[str, Any]:
    """Load a session note document, returning a default editable document if none exists."""

    ref = _normalized_session_ref(session_ref)
    path = _note_path(library_root, ref)
    if not path.exists():
        return _response(library_root, ref, _default_note(ref), present=False)

    doc = _normalized_note_document(_read_json_object(path), session_ref=ref, previous=None, now=None)
    return _response(library_root, ref, doc, present=True)


def save_session_note(
    library_root: str | Path,
    session_ref: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist a session note document to the canonical session annotations path."""

    if not isinstance(payload, Mapping):
        raise InvalidRequestError("Session note payload must be a JSON object.")

    ref = _normalized_session_ref(session_ref)
    raw_note = payload.get("note", payload.get("session_note", payload))
    if not isinstance(raw_note, Mapping):
        raise InvalidRequestError("Session note save request must include a note object.")

    path = _note_path(library_root, ref)
    previous = _read_json_object(path) if path.exists() else None
    doc = _normalized_note_document(raw_note, session_ref=ref, previous=previous, now=_utcnow_iso())
    _write_json(path, doc)
    return _response(library_root, ref, doc, present=True)


def _response(
    library_root: str | Path,
    session_ref: Mapping[str, Any],
    note: Mapping[str, Any],
    *,
    present: bool,
) -> dict[str, Any]:
    return {
        "schema": SESSION_NOTE_API_SCHEMA,
        "version": SESSION_NOTE_API_VERSION,
        "present": bool(present),
        "session_ref": dict(session_ref),
        "note": dict(note),
        "template": _template_summary(library_root, note),
    }


def _template_summary(library_root: str | Path, note: Mapping[str, Any]) -> dict[str, Any]:
    template_id = _optional_text(note.get("template_id"))
    template_version = _optional_text(note.get("template_version"))
    if template_id is None or template_version is None:
        return {"status": "missing", "fields": []}

    try:
        store = make_session_note_template_store(artifacts_dir=library_root)
        template = store.get_template(template_id, template_version)
    except Exception as exc:
        return {
            "status": "missing",
            "template_id": template_id,
            "template_version": template_version,
            "fields": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "status": "ok",
        "template_id": template.template_id,
        "template_version": template.template_version,
        "title": template.title,
        "description": template.description,
        "allow_custom_fields": template.allow_custom_fields,
        "custom_field_section": template.custom_field_section,
        "fields": [asdict(field) for field in template.fields],
    }


def _default_note(session_ref: Mapping[str, Any]) -> dict[str, Any]:
    now = _utcnow_iso()
    return {
        "schema": SESSION_NOTE_DOCUMENT_SCHEMA,
        "version": SESSION_NOTE_DOCUMENT_VERSION,
        "run_id": session_ref["run_id"],
        "session_id": session_ref["session_id"],
        "session_key": session_ref["session_key"],
        "template_id": "web_session_note",
        "template_version": "1.0",
        "title": "Session note",
        "values": {},
        "custom_values": {},
        "free_text_notes": "",
        "created_at_utc": now,
        "updated_at_utc": now,
        "draft": True,
    }


def _normalized_note_document(
    payload: Mapping[str, Any],
    *,
    session_ref: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    now: str | None,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidRequestError("Session note document must be a JSON object.")

    doc = dict(payload)
    doc.pop("present", None)
    doc.pop("session_ref", None)
    doc["schema"] = SESSION_NOTE_DOCUMENT_SCHEMA
    doc["version"] = SESSION_NOTE_DOCUMENT_VERSION
    doc["run_id"] = session_ref["run_id"]
    doc["session_id"] = session_ref["session_id"]
    doc["session_key"] = session_ref["session_key"]

    doc["template_id"] = _optional_text(doc.get("template_id")) or _previous_text(previous, "template_id") or "web_session_note"
    doc["template_version"] = (
        _optional_text(doc.get("template_version")) or _previous_text(previous, "template_version") or "1.0"
    )
    doc["title"] = _optional_text(doc.get("title")) or _previous_text(previous, "title") or "Session note"
    doc["values"] = _json_mapping(doc.get("values"), field_name="values")
    doc["custom_values"] = _json_mapping(doc.get("custom_values"), field_name="custom_values")

    free_text = doc.get("free_text_notes")
    if free_text is not None and not isinstance(free_text, str):
        free_text = str(free_text)
    doc["free_text_notes"] = free_text or ""
    doc["draft"] = bool(doc.get("draft", True))

    previous_created = _previous_text(previous, "created_at_utc")
    created = _optional_text(doc.get("created_at_utc")) or previous_created or now or _utcnow_iso()
    doc["created_at_utc"] = created
    doc["updated_at_utc"] = now or _optional_text(doc.get("updated_at_utc")) or created
    return doc


def _normalized_session_ref(session_ref: Mapping[str, Any]) -> dict[str, str]:
    ref = {
        "library_id": _required_text(session_ref.get("library_id"), field_name="session_ref.library_id"),
        "session_ref_id": _optional_text(session_ref.get("session_ref_id")) or "",
        "session_key": _required_text(session_ref.get("session_key"), field_name="session_ref.session_key"),
        "run_id": _required_text(session_ref.get("run_id"), field_name="session_ref.run_id"),
        "session_id": _required_text(session_ref.get("session_id"), field_name="session_ref.session_id"),
    }
    return ref


def _note_path(library_root: str | Path, session_ref: Mapping[str, Any]) -> Path:
    store = ArtifactStore(Path(library_root).expanduser())
    return store.path_session_notes(str(session_ref["run_id"]), str(session_ref["session_id"]))


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidRequestError(
            "Session note JSON could not be read.",
            details={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    if not isinstance(value, Mapping):
        raise InvalidRequestError("Session note JSON must be an object.", details={"path": str(path)})
    return dict(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _json_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise InvalidRequestError(f"Session note {field_name} must be an object.")
    return dict(value)


def _previous_text(previous: Mapping[str, Any] | None, key: str) -> str | None:
    if not isinstance(previous, Mapping):
        return None
    return _optional_text(previous.get(key))


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidRequestError(f"Session note missing non-empty {field_name}.")
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
