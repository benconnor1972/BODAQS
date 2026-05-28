"""Study Set persistence for the BODAQS Library API adapter."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from bodaqs_analysis.artifacts import ArtifactStore, list_runs, list_sessions

from .errors import InvalidStudySetError, RevisionConflictError, StudySetNotFoundError
from .ids import is_valid_object_id, make_session_key, make_unique_object_id


STUDY_SET_SCHEMA = "bodaqs.study_set"
STUDY_SET_VERSION = 1
STUDY_SETS_DIR = Path("library") / "study_sets"


def list_study_sets(library_root: str | Path) -> list[dict[str, Any]]:
    """Return lightweight Study Set summaries for a library."""

    out: list[dict[str, Any]] = []
    for path in sorted(_study_sets_dir(library_root).glob("*.json"), key=lambda p: p.name.lower()):
        try:
            doc = _read_json_object(path)
        except StudySetNotFoundError:
            continue
        out.append(
            {
                "study_set_id": str(doc.get("study_set_id") or path.stem),
                "display_name": str(doc.get("display_name") or doc.get("study_set_id") or path.stem),
                "revision": int(doc.get("revision") or 0),
                "updated_at": _provenance_updated_at(doc),
                "session_count": len(doc.get("sessions") or []),
                "path": str(path),
            }
        )
    return out


def load_study_set(library_root: str | Path, study_set_id: str) -> dict[str, Any]:
    path = _study_set_path(library_root, study_set_id)
    return _read_json_object(path)


def create_study_set(library_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidStudySetError("Study Set payload must be a JSON object.")

    existing_ids = [row["study_set_id"] for row in list_study_sets(library_root)]
    display_name = _required_text(payload.get("display_name"), field_name="display_name")
    requested_id = _optional_text(payload.get("study_set_id"))
    study_set_id = requested_id or make_unique_object_id(
        display_name,
        existing_ids,
        fallback="study-set",
    )
    if study_set_id in set(existing_ids):
        raise InvalidStudySetError(
            "Study Set id already exists.",
            details={"study_set_id": study_set_id},
        )

    now = _utcnow_iso()
    doc = _normalized_study_set_payload(
        payload,
        study_set_id=study_set_id,
        revision=1,
        now=now,
        previous=None,
    )
    validate_study_set(library_root, doc)
    _write_study_set(library_root, doc)
    return doc


def update_study_set(
    library_root: str | Path,
    study_set_id: str,
    *,
    expected_revision: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    current = load_study_set(library_root, study_set_id)
    current_revision = int(current.get("revision") or 0)
    if int(expected_revision) != current_revision:
        raise RevisionConflictError(
            "Study Set was modified after it was loaded.",
            details={
                "study_set_id": str(study_set_id),
                "expected_revision": int(expected_revision),
                "current_revision": current_revision,
            },
        )

    now = _utcnow_iso()
    doc = _normalized_study_set_payload(
        payload,
        study_set_id=str(study_set_id),
        revision=current_revision + 1,
        now=now,
        previous=current,
    )
    validate_study_set(library_root, doc)
    _write_study_set(library_root, doc)
    return doc


def delete_study_set(library_root: str | Path, study_set_id: str) -> dict[str, Any]:
    path = _study_set_path(library_root, study_set_id)
    if not path.exists():
        raise StudySetNotFoundError(
            "Study Set was not found.",
            details={"study_set_id": str(study_set_id)},
        )
    path.unlink()
    return {"deleted": True, "study_set_id": str(study_set_id)}


def validate_study_set(library_root: str | Path, payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise InvalidStudySetError("Study Set payload must be a JSON object.")

    if payload.get("schema") != STUDY_SET_SCHEMA:
        raise InvalidStudySetError("Invalid Study Set schema.")
    if int(payload.get("version", -1)) != STUDY_SET_VERSION:
        raise InvalidStudySetError("Unsupported Study Set version.")

    study_set_id = _required_text(payload.get("study_set_id"), field_name="study_set_id")
    if not is_valid_object_id(study_set_id):
        raise InvalidStudySetError(
            "Study Set id is not filename-safe.",
            details={"study_set_id": study_set_id},
        )

    _required_text(payload.get("display_name"), field_name="display_name")
    if not isinstance(payload.get("revision"), int) or isinstance(payload.get("revision"), bool):
        raise InvalidStudySetError("Study Set revision must be an integer.")

    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        raise InvalidStudySetError("Study Set sessions must be a list.")

    known_sessions = _library_session_keys(library_root)
    top_level_sessions: set[str] = set()
    for index, session_ref in enumerate(sessions):
        session_key = _validate_session_ref(
            session_ref,
            known_sessions=known_sessions,
            context=f"sessions[{index}]",
        )
        if session_key in top_level_sessions:
            raise InvalidStudySetError(
                "Study Set contains duplicate session references.",
                details={"session_key": session_key},
            )
        top_level_sessions.add(session_key)

    _validate_groupings(payload.get("groupings"), known_top_level_sessions=top_level_sessions)
    _validate_bookmarks(payload.get("bookmarks"), known_top_level_sessions=top_level_sessions)
    _validate_tracks(payload.get("tracks"))

    provenance = payload.get("provenance")
    if not isinstance(provenance, Mapping):
        raise InvalidStudySetError("Study Set provenance must be an object.")
    display_state = payload.get("display_state")
    if display_state is not None and not isinstance(display_state, Mapping):
        raise InvalidStudySetError("Study Set display_state must be an object.")


def _normalized_study_set_payload(
    payload: Mapping[str, Any],
    *,
    study_set_id: str,
    revision: int,
    now: str,
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    doc = dict(payload)
    doc["schema"] = STUDY_SET_SCHEMA
    doc["version"] = STUDY_SET_VERSION
    doc["study_set_id"] = str(study_set_id)
    doc["display_name"] = _required_text(doc.get("display_name"), field_name="display_name")
    doc["revision"] = int(revision)
    doc["sessions"] = list(doc.get("sessions") or [])
    doc["groupings"] = list(doc.get("groupings") or [])
    doc["tracks"] = list(doc.get("tracks") or [])
    doc["bookmarks"] = list(doc.get("bookmarks") or [])

    previous_provenance = previous.get("provenance") if isinstance(previous, Mapping) else None
    provenance = doc.get("provenance")
    provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
    if isinstance(previous_provenance, Mapping):
        provenance.setdefault("created_at", previous_provenance.get("created_at"))
        provenance.setdefault("created_by", previous_provenance.get("created_by"))
        provenance.setdefault("created_from", previous_provenance.get("created_from"))
    provenance.setdefault("created_at", now)
    provenance.setdefault("created_by", "user")
    provenance.setdefault("created_from", {"kind": "manual_selection", "details": {}})
    provenance["updated_at"] = now
    doc["provenance"] = provenance

    display_state = doc.get("display_state")
    doc["display_state"] = dict(display_state) if isinstance(display_state, Mapping) else {"bodaqs_web_v1": {}}
    doc["display_state"].setdefault("bodaqs_web_v1", {})
    return doc


def _validate_groupings(value: Any, *, known_top_level_sessions: set[str]) -> None:
    if not isinstance(value, list):
        raise InvalidStudySetError("Study Set groupings must be a list.")
    seen_ids: set[str] = set()
    for index, grouping in enumerate(value):
        if not isinstance(grouping, Mapping):
            raise InvalidStudySetError(f"groupings[{index}] must be an object.")
        grouping_id = _required_text(grouping.get("grouping_id"), field_name=f"groupings[{index}].grouping_id")
        if grouping_id in seen_ids:
            raise InvalidStudySetError(
                "Study Set contains duplicate grouping ids.",
                details={"grouping_id": grouping_id},
            )
        seen_ids.add(grouping_id)
        _required_text(grouping.get("display_name"), field_name=f"groupings[{index}].display_name")
        sessions = grouping.get("sessions")
        if not isinstance(sessions, list):
            raise InvalidStudySetError(f"groupings[{index}].sessions must be a list.")
        for session_index, session_ref in enumerate(sessions):
            session_key = _validate_session_ref(
                session_ref,
                known_sessions=known_top_level_sessions,
                context=f"groupings[{index}].sessions[{session_index}]",
            )
            if session_key not in known_top_level_sessions:
                raise InvalidStudySetError(
                    "Grouping references a session outside top-level Study Set sessions.",
                    details={"session_key": session_key},
                )


def _validate_bookmarks(value: Any, *, known_top_level_sessions: set[str]) -> None:
    if not isinstance(value, list):
        raise InvalidStudySetError("Study Set bookmarks must be a list.")
    seen_ids: set[str] = set()
    for index, bookmark in enumerate(value):
        if not isinstance(bookmark, Mapping):
            raise InvalidStudySetError(f"bookmarks[{index}] must be an object.")
        bookmark_id = _required_text(bookmark.get("bookmark_id"), field_name=f"bookmarks[{index}].bookmark_id")
        if bookmark_id in seen_ids:
            raise InvalidStudySetError(
                "Study Set contains duplicate bookmark ids.",
                details={"bookmark_id": bookmark_id},
            )
        seen_ids.add(bookmark_id)
        _required_text(bookmark.get("display_name"), field_name=f"bookmarks[{index}].display_name")
        session_key = _validate_session_ref(
            bookmark.get("session"),
            known_sessions=known_top_level_sessions,
            context=f"bookmarks[{index}].session",
        )
        if session_key not in known_top_level_sessions:
            raise InvalidStudySetError(
                "Bookmark references a session outside top-level Study Set sessions.",
                details={"session_key": session_key},
            )

        has_time_s = bookmark.get("time_s") is not None
        has_window = bookmark.get("time_window") is not None
        if has_time_s == has_window:
            raise InvalidStudySetError(
                "Bookmark must define exactly one of time_s or time_window.",
                details={"bookmark_id": bookmark_id},
            )
        if has_time_s and not _is_number(bookmark.get("time_s")):
            raise InvalidStudySetError("Bookmark time_s must be numeric.")
        if has_window:
            window = bookmark.get("time_window")
            if not isinstance(window, Mapping):
                raise InvalidStudySetError("Bookmark time_window must be an object.")
            if not _is_number(window.get("start_s")) or not _is_number(window.get("end_s")):
                raise InvalidStudySetError("Bookmark time_window start_s/end_s must be numeric.")
            if float(window["end_s"]) < float(window["start_s"]):
                raise InvalidStudySetError("Bookmark time_window end_s must be >= start_s.")


def _validate_tracks(value: Any) -> None:
    if not isinstance(value, list):
        raise InvalidStudySetError("Study Set tracks must be a list.")
    for index, track_ref in enumerate(value):
        if not isinstance(track_ref, Mapping):
            raise InvalidStudySetError(f"tracks[{index}] must be an object.")
        _required_text(track_ref.get("track_id"), field_name=f"tracks[{index}].track_id")
        from_point = _optional_text(track_ref.get("from_point_id"))
        to_point = _optional_text(track_ref.get("to_point_id"))
        if (from_point is None) != (to_point is None):
            raise InvalidStudySetError(
                "Track interval references must include both from_point_id and to_point_id.",
                details={"track_id": track_ref.get("track_id")},
            )


def _validate_session_ref(
    value: Any,
    *,
    known_sessions: set[str],
    context: str,
) -> str:
    if not isinstance(value, Mapping):
        raise InvalidStudySetError(f"{context} must be a session reference object.")
    run_id = _required_text(value.get("run_id"), field_name=f"{context}.run_id")
    session_id = _required_text(value.get("session_id"), field_name=f"{context}.session_id")
    session_key = _required_text(value.get("session_key"), field_name=f"{context}.session_key")
    expected_key = make_session_key(run_id, session_id)
    if session_key != expected_key:
        raise InvalidStudySetError(
            "Session reference session_key does not match run_id/session_id.",
            details={"context": context, "session_key": session_key, "expected_session_key": expected_key},
        )
    if session_key not in known_sessions:
        raise InvalidStudySetError(
            "Session reference does not exist in this library.",
            details={"context": context, "session_key": session_key},
        )
    return session_key


def _library_session_keys(library_root: str | Path) -> set[str]:
    store = ArtifactStore(Path(library_root))
    out: set[str] = set()
    for run_id in list_runs(store):
        for session_id in list_sessions(store, run_id):
            out.add(make_session_key(run_id, session_id))
    return out


def _study_sets_dir(library_root: str | Path) -> Path:
    return Path(library_root) / STUDY_SETS_DIR


def _study_set_path(library_root: str | Path, study_set_id: str) -> Path:
    study_set_id = _required_text(study_set_id, field_name="study_set_id")
    if not is_valid_object_id(study_set_id):
        raise InvalidStudySetError(
            "Study Set id is not filename-safe.",
            details={"study_set_id": study_set_id},
        )
    return _study_sets_dir(library_root) / f"{study_set_id}.json"


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise StudySetNotFoundError(
            "Study Set was not found.",
            details={"study_set_id": path.stem},
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidStudySetError(
            "Study Set JSON could not be read.",
            details={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    if not isinstance(value, Mapping):
        raise InvalidStudySetError("Study Set JSON must be an object.", details={"path": str(path)})
    return dict(value)


def _write_study_set(library_root: str | Path, payload: Mapping[str, Any]) -> None:
    path = _study_set_path(library_root, str(payload["study_set_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidStudySetError(f"Study Set missing non-empty {field_name!r}.")
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _provenance_updated_at(doc: Mapping[str, Any]) -> str | None:
    provenance = doc.get("provenance")
    if not isinstance(provenance, Mapping):
        return None
    value = provenance.get("updated_at")
    return str(value) if isinstance(value, str) and value.strip() else None
