"""Study Set persistence for the BODAQS Library API adapter."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from bodaqs_analysis.artifacts import ArtifactStore, list_runs, list_sessions

from .catalog import discover_libraries
from .errors import InvalidStudySetError, RevisionConflictError, StudySetNotFoundError
from .ids import is_valid_object_id, make_session_key, make_session_ref_id, make_unique_object_id


STUDY_SET_SCHEMA = "bodaqs.study_set"
STUDY_SET_VERSION = 1
STUDY_SETS_DIR = Path("study_sets")
LEGACY_STUDY_SETS_DIR = Path("library") / "study_sets"


def list_study_sets(libraries_root: str | Path) -> list[dict[str, Any]]:
    """Return lightweight Study Set summaries for a libraries root."""

    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for directory in _study_set_dirs(libraries_root):
        for path in sorted(directory.glob("*.json"), key=lambda p: p.name.lower()):
            try:
                doc = _read_json_object(path)
            except StudySetNotFoundError:
                continue
            study_set_id = str(doc.get("study_set_id") or path.stem)
            if study_set_id in seen_ids:
                continue
            seen_ids.add(study_set_id)
            out.append(
                {
                    "study_set_id": study_set_id,
                    "display_name": str(doc.get("display_name") or doc.get("study_set_id") or path.stem),
                    "revision": int(doc.get("revision") or 0),
                    "updated_at": _provenance_updated_at(doc),
                    "session_count": len(doc.get("sessions") or []),
                    "library_count": len(
                        {
                            str(session.get("library_id"))
                            for session in doc.get("sessions") or []
                            if isinstance(session, Mapping) and session.get("library_id") is not None
                        }
                    ),
                    "grouping_count": len(doc.get("groupings") or []),
                    "track_count": len(doc.get("tracks") or []),
                    "path": str(path),
                }
            )
    return out


def load_study_set(libraries_root: str | Path, study_set_id: str) -> dict[str, Any]:
    path = _existing_study_set_path(libraries_root, study_set_id)
    return _read_json_object(path)


def create_study_set(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidStudySetError("Study Set payload must be a JSON object.")

    existing_ids = [row["study_set_id"] for row in list_study_sets(libraries_root)]
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
    validate_study_set(libraries_root, doc)
    _write_study_set(libraries_root, doc)
    return doc


def update_study_set(
    libraries_root: str | Path,
    study_set_id: str,
    *,
    expected_revision: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    current = load_study_set(libraries_root, study_set_id)
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
    validate_study_set(libraries_root, doc)
    _write_study_set(libraries_root, doc)
    return doc


def delete_study_set(libraries_root: str | Path, study_set_id: str) -> dict[str, Any]:
    paths = [path for path in _study_set_paths(libraries_root, study_set_id) if path.exists()]
    if not paths:
        raise StudySetNotFoundError(
            "Study Set was not found.",
            details={"study_set_id": str(study_set_id)},
        )
    for path in paths:
        path.unlink()
    return {"deleted": True, "study_set_id": str(study_set_id)}


def find_study_set_session_references(
    libraries_root: str | Path,
    session_ref_id: str,
) -> list[dict[str, Any]]:
    """Return saved Study Set references to ``session_ref_id``."""

    wanted = str(session_ref_id or "").strip()
    if not wanted:
        return []

    references: list[dict[str, Any]] = []
    for summary in list_study_sets(libraries_root):
        study_set_id = str(summary.get("study_set_id") or "").strip()
        if not study_set_id:
            continue
        doc = load_study_set(libraries_root, study_set_id)
        session_refs = [
            session
            for session in doc.get("sessions") or []
            if isinstance(session, Mapping) and session.get("session_ref_id") == wanted
        ]
        groupings = [
            {
                "grouping_id": str(grouping.get("grouping_id") or ""),
                "display_name": str(grouping.get("display_name") or grouping.get("grouping_id") or ""),
            }
            for grouping in doc.get("groupings") or []
            if isinstance(grouping, Mapping) and wanted in set(grouping.get("session_refs") or [])
        ]
        bookmarks = [
            {
                "bookmark_id": str(bookmark.get("bookmark_id") or ""),
                "display_name": str(bookmark.get("display_name") or bookmark.get("bookmark_id") or ""),
            }
            for bookmark in doc.get("bookmarks") or []
            if isinstance(bookmark, Mapping) and bookmark.get("session_ref") == wanted
        ]
        if session_refs or groupings or bookmarks:
            references.append(
                {
                    "study_set_id": study_set_id,
                    "display_name": str(doc.get("display_name") or study_set_id),
                    "session_member": bool(session_refs),
                    "groupings": groupings,
                    "bookmarks": bookmarks,
                }
            )
    return references


def remove_session_from_study_sets(
    libraries_root: str | Path,
    session_ref_id: str,
) -> list[dict[str, Any]]:
    """Remove ``session_ref_id`` from saved Study Sets and return update summaries."""

    wanted = str(session_ref_id or "").strip()
    if not wanted:
        return []

    updates: list[dict[str, Any]] = []
    now = _utcnow_iso()
    for reference in find_study_set_session_references(libraries_root, wanted):
        study_set_id = str(reference["study_set_id"])
        doc = load_study_set(libraries_root, study_set_id)
        previous_revision = int(doc.get("revision") or 0)

        before_sessions = list(doc.get("sessions") or [])
        doc["sessions"] = [
            session
            for session in before_sessions
            if not (isinstance(session, Mapping) and session.get("session_ref_id") == wanted)
        ]

        removed_groupings: list[dict[str, str]] = []
        kept_groupings: list[dict[str, Any]] = []
        for grouping in doc.get("groupings") or []:
            if not isinstance(grouping, Mapping):
                continue
            updated_grouping = dict(grouping)
            updated_grouping["session_refs"] = [
                session_ref for session_ref in list(grouping.get("session_refs") or []) if session_ref != wanted
            ]
            if updated_grouping["session_refs"]:
                kept_groupings.append(updated_grouping)
            else:
                removed_groupings.append(
                    {
                        "grouping_id": str(grouping.get("grouping_id") or ""),
                        "display_name": str(grouping.get("display_name") or grouping.get("grouping_id") or ""),
                    }
                )
        doc["groupings"] = kept_groupings

        before_bookmarks = list(doc.get("bookmarks") or [])
        doc["bookmarks"] = [
            bookmark
            for bookmark in before_bookmarks
            if not (isinstance(bookmark, Mapping) and bookmark.get("session_ref") == wanted)
        ]
        removed_bookmark_count = len(before_bookmarks) - len(doc["bookmarks"])

        doc["revision"] = previous_revision + 1
        provenance = doc.get("provenance")
        doc["provenance"] = dict(provenance) if isinstance(provenance, Mapping) else {}
        doc["provenance"]["updated_at"] = now
        doc["provenance"]["updated_by"] = "library_api_session_delete_cleanup"

        validate_study_set(libraries_root, doc)
        _write_study_set(libraries_root, doc)
        updates.append(
            {
                "study_set_id": study_set_id,
                "display_name": str(doc.get("display_name") or study_set_id),
                "previous_revision": previous_revision,
                "revision": doc["revision"],
                "removed_session": len(before_sessions) != len(doc["sessions"]),
                "removed_groupings": removed_groupings,
                "removed_bookmark_count": removed_bookmark_count,
            }
        )
    return updates


def validate_study_set(libraries_root: str | Path, payload: Mapping[str, Any]) -> None:
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

    known_sessions = _libraries_session_ref_ids(libraries_root)
    top_level_sessions: set[str] = set()
    for index, session_ref in enumerate(sessions):
        session_ref_id = _validate_session_ref(
            session_ref,
            known_sessions=known_sessions,
            context=f"sessions[{index}]",
        )
        if session_ref_id in top_level_sessions:
            raise InvalidStudySetError(
                "Study Set contains duplicate session references.",
                details={"session_ref_id": session_ref_id},
            )
        top_level_sessions.add(session_ref_id)

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
    doc["sessions"] = [
        _normalized_session_ref(session, context=f"sessions[{index}]")
        for index, session in enumerate(list(doc.get("sessions") or []))
    ]
    doc["groupings"] = [
        _normalized_grouping(grouping, index=index)
        for index, grouping in enumerate(list(doc.get("groupings") or []))
    ]
    doc["tracks"] = [
        _normalized_track_ref(track_ref, index=index)
        for index, track_ref in enumerate(list(doc.get("tracks") or []))
    ]
    doc["bookmarks"] = [
        _normalized_bookmark(bookmark, index=index)
        for index, bookmark in enumerate(list(doc.get("bookmarks") or []))
    ]

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


def _normalized_session_ref(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidStudySetError(f"{context} must be a session reference object.")
    library_id = _required_text(value.get("library_id"), field_name=f"{context}.library_id")
    run_id = _required_text(value.get("run_id"), field_name=f"{context}.run_id")
    session_id = _required_text(value.get("session_id"), field_name=f"{context}.session_id")
    expected_key = make_session_key(run_id, session_id)
    session_key = _optional_text(value.get("session_key")) or expected_key
    if session_key != expected_key:
        raise InvalidStudySetError(
            "Session reference session_key does not match run_id/session_id.",
            details={"context": context, "session_key": session_key, "expected_session_key": expected_key},
        )
    expected_ref_id = make_session_ref_id(library_id, session_key)
    session_ref_id = _optional_text(value.get("session_ref_id")) or expected_ref_id
    if session_ref_id != expected_ref_id:
        raise InvalidStudySetError(
            "Session reference session_ref_id does not match library_id/session_key.",
            details={"context": context, "session_ref_id": session_ref_id, "expected_session_ref_id": expected_ref_id},
        )

    out = dict(value)
    out["library_id"] = library_id
    out["session_ref_id"] = session_ref_id
    out["session_key"] = session_key
    out["run_id"] = run_id
    out["session_id"] = session_id
    label = _optional_text(out.get("label") or out.get("display_label"))
    if label is not None:
        out["label"] = label
    return out


def _normalized_grouping(value: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidStudySetError(f"groupings[{index}] must be an object.")
    out = dict(value)
    out["grouping_id"] = _required_text(value.get("grouping_id"), field_name=f"groupings[{index}].grouping_id")
    out["display_name"] = _required_text(value.get("display_name"), field_name=f"groupings[{index}].display_name")
    out["session_refs"] = _normalized_session_ref_id_list(
        value.get("session_refs"),
        legacy_session_refs=value.get("sessions"),
        context=f"groupings[{index}].session_refs",
    )
    out.pop("sessions", None)
    return out


def _normalized_bookmark(value: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidStudySetError(f"bookmarks[{index}] must be an object.")
    out = dict(value)
    out["bookmark_id"] = _required_text(value.get("bookmark_id"), field_name=f"bookmarks[{index}].bookmark_id")
    out["display_name"] = _required_text(value.get("display_name"), field_name=f"bookmarks[{index}].display_name")
    session_ref = _optional_text(value.get("session_ref"))
    if session_ref is None:
        session = _normalized_session_ref(value.get("session"), context=f"bookmarks[{index}].session")
        session_ref = session["session_ref_id"]
    out["session_ref"] = session_ref
    out.pop("session", None)
    return out


def _normalized_track_ref(value: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidStudySetError(f"tracks[{index}] must be an object.")
    out = dict(value)
    out["track_id"] = _required_text(value.get("track_id"), field_name=f"tracks[{index}].track_id")
    from_trackpoint = _optional_text(value.get("from_trackpoint_id")) or _optional_text(value.get("from_point_id"))
    to_trackpoint = _optional_text(value.get("to_trackpoint_id")) or _optional_text(value.get("to_point_id"))
    if from_trackpoint is not None:
        out["from_trackpoint_id"] = from_trackpoint
    if to_trackpoint is not None:
        out["to_trackpoint_id"] = to_trackpoint
    out.pop("from_point_id", None)
    out.pop("to_point_id", None)
    return out


def _normalized_session_ref_id_list(
    value: Any,
    *,
    legacy_session_refs: Any,
    context: str,
) -> list[str]:
    if value is None and isinstance(legacy_session_refs, list):
        return [
            _normalized_session_ref(session_ref, context=f"{context}[{index}]")["session_ref_id"]
            for index, session_ref in enumerate(legacy_session_refs)
        ]
    if not isinstance(value, list):
        raise InvalidStudySetError(f"{context} must be a list.")
    out: list[str] = []
    for index, item in enumerate(value):
        item_text = _required_text(item, field_name=f"{context}[{index}]")
        out.append(item_text)
    return out


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
        session_refs = grouping.get("session_refs")
        if not isinstance(session_refs, list):
            raise InvalidStudySetError(f"groupings[{index}].session_refs must be a list.")
        for session_index, session_ref_id in enumerate(session_refs):
            session_ref_id = _required_text(
                session_ref_id,
                field_name=f"groupings[{index}].session_refs[{session_index}]",
            )
            if session_ref_id not in known_top_level_sessions:
                raise InvalidStudySetError(
                    "Grouping references a session outside top-level Study Set sessions.",
                    details={"session_ref_id": session_ref_id},
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
        session_ref = _required_text(bookmark.get("session_ref"), field_name=f"bookmarks[{index}].session_ref")
        if session_ref not in known_top_level_sessions:
            raise InvalidStudySetError(
                "Bookmark references a session outside top-level Study Set sessions.",
                details={"session_ref_id": session_ref},
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
        from_trackpoint = _optional_text(track_ref.get("from_trackpoint_id")) or _optional_text(
            track_ref.get("from_point_id")
        )
        to_trackpoint = _optional_text(track_ref.get("to_trackpoint_id")) or _optional_text(track_ref.get("to_point_id"))
        if (from_trackpoint is None) != (to_trackpoint is None):
            raise InvalidStudySetError(
                "Track interval references must include both from_trackpoint_id and to_trackpoint_id.",
                details={"track_id": track_ref.get("track_id")},
            )


def _validate_session_ref(
    value: Any,
    *,
    known_sessions: set[str],
    context: str,
) -> str:
    session_ref = _normalized_session_ref(value, context=context)
    session_ref_id = session_ref["session_ref_id"]
    if session_ref_id not in known_sessions:
        raise InvalidStudySetError(
            "Session reference does not exist in any configured library.",
            details={
                "context": context,
                "library_id": session_ref["library_id"],
                "session_key": session_ref["session_key"],
                "session_ref_id": session_ref_id,
            },
        )
    return session_ref_id


def _libraries_session_ref_ids(libraries_root: str | Path) -> set[str]:
    out: set[str] = set()
    for library in discover_libraries(libraries_root):
        library_id = _required_text(library.get("library_id"), field_name="library.library_id")
        store = ArtifactStore(Path(str(library["root"])))
        for run_id in list_runs(store):
            for session_id in list_sessions(store, run_id):
                out.add(make_session_ref_id(library_id, make_session_key(run_id, session_id)))
    return out


def _study_sets_dir(libraries_root: str | Path) -> Path:
    return Path(libraries_root) / STUDY_SETS_DIR


def _legacy_study_sets_dir(libraries_root: str | Path) -> Path:
    return Path(libraries_root) / LEGACY_STUDY_SETS_DIR


def _study_set_dirs(libraries_root: str | Path) -> list[Path]:
    return [_study_sets_dir(libraries_root), _legacy_study_sets_dir(libraries_root)]


def _study_set_path(libraries_root: str | Path, study_set_id: str) -> Path:
    return _study_set_path_in_dir(_study_sets_dir(libraries_root), study_set_id)


def _legacy_study_set_path(libraries_root: str | Path, study_set_id: str) -> Path:
    return _study_set_path_in_dir(_legacy_study_sets_dir(libraries_root), study_set_id)


def _study_set_paths(libraries_root: str | Path, study_set_id: str) -> list[Path]:
    return [_study_set_path(libraries_root, study_set_id), _legacy_study_set_path(libraries_root, study_set_id)]


def _existing_study_set_path(libraries_root: str | Path, study_set_id: str) -> Path:
    for path in _study_set_paths(libraries_root, study_set_id):
        if path.exists():
            return path
    return _study_set_path(libraries_root, study_set_id)


def _study_set_path_in_dir(directory: Path, study_set_id: str) -> Path:
    study_set_id = _required_text(study_set_id, field_name="study_set_id")
    if not is_valid_object_id(study_set_id):
        raise InvalidStudySetError(
            "Study Set id is not filename-safe.",
            details={"study_set_id": study_set_id},
        )
    return directory / f"{study_set_id}.json"


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


def _write_study_set(libraries_root: str | Path, payload: Mapping[str, Any]) -> None:
    study_set_id = str(payload["study_set_id"])
    path = _study_set_path(libraries_root, study_set_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    legacy_path = _legacy_study_set_path(libraries_root, study_set_id)
    if legacy_path.exists():
        legacy_path.unlink()


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
