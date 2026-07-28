"""Session video attachment access for the BODAQS Library API."""

from __future__ import annotations

import json
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from bodaqs_analysis.artifacts import ArtifactStore

from .errors import InvalidRequestError, SessionNotFoundError
from .ids import is_valid_object_id, make_session_key, make_session_ref_id, make_unique_object_id


SESSION_VIDEO_ATTACHMENTS_SCHEMA = "bodaqs.session_video_attachments"
SESSION_VIDEO_ATTACHMENTS_VERSION = 1
SESSION_VIDEO_ATTACHMENTS_API_SCHEMA = "bodaqs.library_api.session_video_attachments"
SESSION_VIDEO_ATTACHMENTS_API_VERSION = 1


def load_session_video_attachments(
    library_root: str | Path,
    session_ref: Mapping[str, Any],
) -> dict[str, Any]:
    """Load session video attachments, returning an empty document if none exists."""

    ref = _normalized_session_ref(session_ref)
    _require_session_dir(library_root, ref)
    path = _video_path(library_root, ref)
    if not path.exists():
        return _response(ref, _default_document(ref), present=False)
    doc = _normalized_document(_read_json_object(path), session_ref=ref, previous=None, now=None)
    return _response(ref, doc, present=True)


def save_session_video_attachments(
    library_root: str | Path,
    session_ref: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist session video attachments to the canonical session annotations path."""

    if not isinstance(payload, Mapping):
        raise InvalidRequestError("Session video attachment payload must be a JSON object.")

    ref = _normalized_session_ref(session_ref)
    _require_session_dir(library_root, ref)
    raw_doc = payload.get("video_attachments", payload.get("session_videos", payload))
    if not isinstance(raw_doc, Mapping):
        raise InvalidRequestError("Session video save request must include a JSON object.")

    path = _video_path(library_root, ref)
    previous = _read_json_object(path) if path.exists() else None
    doc = _normalized_document(raw_doc, session_ref=ref, previous=previous, now=_utcnow_iso())
    _write_json(path, doc)
    return _response(ref, doc, present=True)


def resolve_session_video_attachment(
    library_root: str | Path,
    session_ref: Mapping[str, Any],
    attachment_id: str,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve a declared session video attachment to a local file path."""

    ref = _normalized_session_ref(session_ref)
    response = load_session_video_attachments(library_root, ref)
    wanted_id = _required_text(attachment_id, field_name="attachment_id")
    attachments = response["video_attachments"]["attachments"]
    attachment = next((item for item in attachments if item.get("attachment_id") == wanted_id), None)
    if attachment is None:
        raise InvalidRequestError(
            "Session video attachment was not found.",
            details={"attachment_id": wanted_id, "session_ref": ref},
        )

    path = _resolve_attachment_path(
        Path(library_root).expanduser(),
        ref,
        attachment,
        workspace_root=Path(workspace_root).expanduser() if workspace_root is not None else None,
    )
    if not path.is_file():
        raise InvalidRequestError(
            "Session video attachment file was not found.",
            details={"attachment_id": wanted_id, "path": str(path), "session_ref": ref},
        )
    return {
        "attachment": attachment,
        "path": path,
        "media_type": _media_type(attachment, path),
    }


def _response(
    session_ref: Mapping[str, Any],
    doc: Mapping[str, Any],
    *,
    present: bool,
) -> dict[str, Any]:
    return {
        "schema": SESSION_VIDEO_ATTACHMENTS_API_SCHEMA,
        "version": SESSION_VIDEO_ATTACHMENTS_API_VERSION,
        "present": bool(present),
        "session_ref": dict(session_ref),
        "video_attachments": dict(doc),
    }


def _default_document(session_ref: Mapping[str, Any]) -> dict[str, Any]:
    now = _utcnow_iso()
    return {
        "schema": SESSION_VIDEO_ATTACHMENTS_SCHEMA,
        "version": SESSION_VIDEO_ATTACHMENTS_VERSION,
        "revision": 0,
        "run_id": session_ref["run_id"],
        "session_id": session_ref["session_id"],
        "session_key": session_ref["session_key"],
        "attachments": [],
        "created_at_utc": now,
        "updated_at_utc": now,
    }


def _normalized_document(
    payload: Mapping[str, Any],
    *,
    session_ref: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    now: str | None,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidRequestError("Session video attachment document must be a JSON object.")

    previous_revision = int(previous.get("revision") or 0) if isinstance(previous, Mapping) else 0
    previous_created = _optional_text(previous.get("created_at_utc")) if isinstance(previous, Mapping) else None
    doc = dict(payload)
    doc.pop("present", None)
    doc.pop("session_ref", None)
    doc.pop("video_attachments", None)
    doc.pop("session_videos", None)
    doc["schema"] = SESSION_VIDEO_ATTACHMENTS_SCHEMA
    doc["version"] = SESSION_VIDEO_ATTACHMENTS_VERSION
    doc["revision"] = previous_revision + 1 if now is not None else int(doc.get("revision") or previous_revision)
    doc["run_id"] = session_ref["run_id"]
    doc["session_id"] = session_ref["session_id"]
    doc["session_key"] = session_ref["session_key"]
    doc["attachments"] = _normalized_attachments(doc.get("attachments"), session_ref=session_ref)
    created = _optional_text(doc.get("created_at_utc")) or previous_created or now or _utcnow_iso()
    doc["created_at_utc"] = created
    doc["updated_at_utc"] = now or _optional_text(doc.get("updated_at_utc")) or created
    return doc


def _normalized_attachments(value: Any, *, session_ref: Mapping[str, Any]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InvalidRequestError("Session video attachments must be a list.")

    requested_ids = [
        _optional_text(item.get("attachment_id") if isinstance(item, Mapping) else None)
        for item in value
    ]
    existing_ids = [item for item in requested_ids if item]
    out: list[dict[str, Any]] = []
    used_ids: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise InvalidRequestError("Session video attachment entries must be JSON objects.")
        attachment = dict(item)
        display_name = _optional_text(
            attachment.get("display_name")
            or attachment.get("label")
            or attachment.get("camera_label")
            or attachment.get("camera")
        ) or f"Video {index + 1}"
        attachment_id = _optional_text(attachment.get("attachment_id"))
        if attachment_id is None:
            attachment_id = make_unique_object_id(display_name, [*existing_ids, *used_ids], fallback="video")
        if not is_valid_object_id(attachment_id):
            raise InvalidRequestError(
                "Session video attachment id is not filename-safe.",
                details={"attachment_id": attachment_id},
            )
        if attachment_id in used_ids:
            raise InvalidRequestError(
                "Session video attachment ids must be unique.",
                details={"attachment_id": attachment_id},
            )
        used_ids.append(attachment_id)

        attachment["attachment_id"] = attachment_id
        attachment["display_name"] = display_name
        attachment["camera_label"] = _optional_text(attachment.get("camera_label") or attachment.get("camera")) or ""
        attachment["path"] = _optional_text(attachment.get("path")) or ""
        attachment["workspace_relative_path"] = _optional_relative_path(attachment.get("workspace_relative_path"))
        attachment["library_relative_path"] = _optional_relative_path(attachment.get("library_relative_path"))
        attachment["session_relative_path"] = _optional_relative_path(attachment.get("session_relative_path"))
        attachment["uri"] = _optional_text(attachment.get("uri")) or ""
        attachment["media_type"] = _optional_text(attachment.get("media_type")) or ""
        attachment["enabled"] = attachment.get("enabled") is not False
        attachment["session_time_at_video_zero_s"] = _number_value(
            attachment.get("session_time_at_video_zero_s"),
            default=0.0,
            field_name=f"attachments[{index}].session_time_at_video_zero_s",
        )
        attachment["session_ref"] = dict(session_ref)
        out.append(attachment)
    return out


def _resolve_attachment_path(
    library_root: Path,
    session_ref: Mapping[str, Any],
    attachment: Mapping[str, Any],
    *,
    workspace_root: Path | None = None,
) -> Path:
    store = ArtifactStore(library_root)
    session_dir = store.session_dir(str(session_ref["run_id"]), str(session_ref["session_id"]))

    workspace_relative = _optional_text(attachment.get("workspace_relative_path"))
    if workspace_relative:
        root = workspace_root if workspace_root is not None else library_root
        return _resolve_within(root, workspace_relative, field_name="workspace_relative_path")

    session_relative = _optional_text(attachment.get("session_relative_path"))
    if session_relative:
        return _resolve_within(session_dir, session_relative, field_name="session_relative_path")

    library_relative = _optional_text(attachment.get("library_relative_path"))
    if library_relative:
        return _resolve_within(library_root, library_relative, field_name="library_relative_path")

    path_text = _optional_text(attachment.get("path"))
    if path_text:
        path = Path(path_text).expanduser()
        if not path.is_absolute():
            path = (library_root / path).resolve()
        return path.resolve()

    raise InvalidRequestError(
        "Session video attachment has no resolvable local path.",
        details={"attachment_id": attachment.get("attachment_id")},
    )


def _resolve_within(root: Path, relative_path: str, *, field_name: str) -> Path:
    candidate = (root.expanduser().resolve() / relative_path).resolve()
    try:
        candidate.relative_to(root.expanduser().resolve())
    except ValueError as exc:
        raise InvalidRequestError(
            f"Session video {field_name} resolves outside its allowed root.",
            details={field_name: relative_path, "root": str(root)},
        ) from exc
    return candidate


def _optional_relative_path(value: Any) -> str:
    text = _optional_text(value)
    if text is None:
        return ""
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise InvalidRequestError(
            "Session video relative paths must be relative and must not contain '..'.",
            details={"path": text},
        )
    return text.replace("\\", "/")


def _normalized_session_ref(session_ref: Mapping[str, Any]) -> dict[str, str]:
    run_id = _required_text(session_ref.get("run_id"), field_name="session_ref.run_id")
    session_id = _required_text(session_ref.get("session_id"), field_name="session_ref.session_id")
    library_id = _required_text(session_ref.get("library_id"), field_name="session_ref.library_id")
    session_key = _optional_text(session_ref.get("session_key")) or make_session_key(run_id, session_id)
    expected_key = make_session_key(run_id, session_id)
    if session_key != expected_key:
        raise InvalidRequestError(
            "Session video session_key does not match run_id/session_id.",
            details={"session_key": session_key, "expected_session_key": expected_key},
        )
    return {
        "library_id": library_id,
        "session_ref_id": _optional_text(session_ref.get("session_ref_id")) or make_session_ref_id(library_id, session_key),
        "session_key": session_key,
        "run_id": run_id,
        "session_id": session_id,
    }


def _require_session_dir(library_root: str | Path, session_ref: Mapping[str, Any]) -> None:
    store = ArtifactStore(Path(library_root).expanduser())
    session_dir = store.session_dir(str(session_ref["run_id"]), str(session_ref["session_id"]))
    if not session_dir.is_dir():
        raise SessionNotFoundError(
            "Session was not found.",
            details={"session_ref": dict(session_ref), "session_dir": str(session_dir)},
        )


def _video_path(library_root: str | Path, session_ref: Mapping[str, Any]) -> Path:
    store = ArtifactStore(Path(library_root).expanduser())
    return store.path_session_videos(str(session_ref["run_id"]), str(session_ref["session_id"]))


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidRequestError(
            "Session video attachment JSON could not be read.",
            details={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    if not isinstance(value, Mapping):
        raise InvalidRequestError("Session video attachment JSON must be an object.", details={"path": str(path)})
    return dict(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _media_type(attachment: Mapping[str, Any], path: Path) -> str:
    declared = _optional_text(attachment.get("media_type"))
    if declared:
        return declared
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "video/mp4"


def _number_value(value: Any, *, default: float, field_name: str) -> float:
    if value is None or value == "":
        return float(default)
    if isinstance(value, bool):
        raise InvalidRequestError(f"Session video {field_name} must be numeric.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(f"Session video {field_name} must be numeric.") from exc
    if not number == number or number in {float("inf"), float("-inf")}:
        raise InvalidRequestError(f"Session video {field_name} must be finite.")
    return number


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidRequestError(f"Session video missing non-empty {field_name}.")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
