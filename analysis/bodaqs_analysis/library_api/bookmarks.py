"""Root-scoped persisted session bookmarks for the BODAQS Library API."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import BookmarkNotFoundError, InvalidBookmarkError, RevisionConflictError
from .ids import is_valid_object_id, make_session_key, make_session_ref_id, make_unique_object_id


BOOKMARK_SCHEMA = "bodaqs.session_bookmark"
BOOKMARK_VERSION = 1
BOOKMARKS_DIR = Path("bookmarks")


def list_bookmarks(
    libraries_root: str | Path,
    *,
    library_id: str | None = None,
    session_key: str | None = None,
    session_ref_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return root-scoped persisted session bookmarks."""

    out: list[dict[str, Any]] = []
    for path in sorted(_bookmarks_dir(libraries_root).glob("*.json"), key=lambda p: p.name.lower()):
        doc = _normalized_bookmark_payload(_read_json_object(path), bookmark_id=str(path.stem), revision=None)
        if _bookmark_matches(doc, library_id=library_id, session_key=session_key, session_ref_id=session_ref_id):
            out.append(doc)
    return sorted(out, key=lambda item: (str(item.get("display_name") or "").lower(), str(item.get("bookmark_id") or "")))


def load_bookmark(libraries_root: str | Path, bookmark_id: str) -> dict[str, Any]:
    """Load one root-scoped persisted session bookmark."""

    path = _bookmark_path(libraries_root, bookmark_id)
    if not path.exists():
        raise BookmarkNotFoundError("Bookmark was not found.", details={"bookmark_id": str(bookmark_id)})
    return _normalized_bookmark_payload(_read_json_object(path), bookmark_id=str(bookmark_id), revision=None)


def create_bookmark(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create a root-scoped persisted session bookmark."""

    if not isinstance(payload, Mapping):
        raise InvalidBookmarkError("Bookmark payload must be a JSON object.")
    existing_ids = [bookmark["bookmark_id"] for bookmark in list_bookmarks(libraries_root)]
    display_name = _required_text(payload.get("display_name") or payload.get("title"), field_name="display_name")
    requested_id = _optional_text(payload.get("bookmark_id"))
    bookmark_id = requested_id or make_unique_object_id(display_name, existing_ids, fallback="bookmark")
    if bookmark_id in set(existing_ids):
        raise InvalidBookmarkError("Bookmark id already exists.", details={"bookmark_id": bookmark_id})
    if not is_valid_object_id(bookmark_id):
        raise InvalidBookmarkError("Bookmark id is not filename-safe.", details={"bookmark_id": bookmark_id})

    now = _utcnow_iso()
    doc = _normalized_bookmark_payload(
        payload,
        bookmark_id=bookmark_id,
        revision=1,
        now=now,
        previous=None,
    )
    _write_bookmark(libraries_root, doc)
    return doc


def update_bookmark(
    libraries_root: str | Path,
    bookmark_id: str,
    *,
    expected_revision: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Update one root-scoped persisted session bookmark."""

    if not isinstance(payload, Mapping):
        raise InvalidBookmarkError("Bookmark payload must be a JSON object.")
    current = load_bookmark(libraries_root, bookmark_id)
    current_revision = int(current.get("revision") or 0)
    if int(expected_revision) != current_revision:
        raise RevisionConflictError(
            "Bookmark was modified after it was loaded.",
            details={
                "bookmark_id": str(bookmark_id),
                "expected_revision": int(expected_revision),
                "current_revision": current_revision,
            },
        )

    now = _utcnow_iso()
    doc = _normalized_bookmark_payload(
        payload,
        bookmark_id=str(bookmark_id),
        revision=current_revision + 1,
        now=now,
        previous=current,
    )
    _write_bookmark(libraries_root, doc)
    return doc


def delete_bookmark(libraries_root: str | Path, bookmark_id: str) -> dict[str, Any]:
    """Delete one root-scoped persisted session bookmark."""

    path = _bookmark_path(libraries_root, bookmark_id)
    if not path.exists():
        raise BookmarkNotFoundError("Bookmark was not found.", details={"bookmark_id": str(bookmark_id)})
    path.unlink()
    return {"deleted": True, "bookmark_id": str(bookmark_id)}


def find_bookmark_session_references(libraries_root: str | Path, session_ref_id: str) -> list[dict[str, Any]]:
    """Return bookmark references to a session_ref_id for delete conflict reporting."""

    wanted = str(session_ref_id or "").strip()
    if not wanted:
        return []
    return [
        {
            "kind": "bookmark",
            "bookmark_id": bookmark["bookmark_id"],
            "display_name": bookmark.get("display_name") or bookmark["bookmark_id"],
        }
        for bookmark in list_bookmarks(libraries_root, session_ref_id=wanted)
    ]


def remove_session_from_bookmarks(libraries_root: str | Path, session_ref_id: str) -> list[dict[str, Any]]:
    """Delete root-scoped bookmarks that reference a deleted session."""

    removed: list[dict[str, Any]] = []
    for bookmark in list_bookmarks(libraries_root, session_ref_id=session_ref_id):
        delete_bookmark(libraries_root, str(bookmark["bookmark_id"]))
        removed.append(
            {
                "bookmark_id": bookmark["bookmark_id"],
                "display_name": bookmark.get("display_name") or bookmark["bookmark_id"],
            }
        )
    return removed


def _normalized_bookmark_payload(
    payload: Mapping[str, Any],
    *,
    bookmark_id: str,
    revision: int | None,
    now: str | None = None,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    doc = dict(payload)
    doc["schema"] = BOOKMARK_SCHEMA
    doc["version"] = BOOKMARK_VERSION
    doc["bookmark_id"] = str(bookmark_id)
    if not is_valid_object_id(doc["bookmark_id"]):
        raise InvalidBookmarkError("Bookmark id is not filename-safe.", details={"bookmark_id": doc["bookmark_id"]})
    doc["display_name"] = _required_text(doc.get("display_name") or doc.get("title"), field_name="display_name")
    doc.pop("title", None)
    doc["description"] = _optional_text(doc.get("description") or doc.get("note")) or ""
    doc.pop("note", None)
    if revision is not None:
        doc["revision"] = int(revision)
    elif not isinstance(doc.get("revision"), int) or isinstance(doc.get("revision"), bool):
        raise InvalidBookmarkError("Bookmark revision must be an integer.")

    doc["session"] = _normalized_session_ref(doc.get("session"), context="session")
    doc["session_ref_id"] = doc["session"]["session_ref_id"]
    doc["window"] = _normalized_window(doc.get("window"))

    view_state = doc.get("view_state")
    if view_state is None:
        view_state = doc.get("view")
    doc["view_state"] = dict(view_state) if isinstance(view_state, Mapping) else {"bodaqs_web_signal_inspector_v1": {}}
    doc["view_state"].setdefault("bodaqs_web_signal_inspector_v1", {})
    doc.pop("view", None)

    tags = doc.get("tags")
    doc["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()] if isinstance(tags, list) else []
    doc["private"] = bool(doc.get("private", True))

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
    return doc


def _normalized_session_ref(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidBookmarkError(f"{context} must be a session reference object.")
    library_id = _required_text(value.get("library_id"), field_name=f"{context}.library_id")
    run_id = _required_text(value.get("run_id"), field_name=f"{context}.run_id")
    session_id = _required_text(value.get("session_id"), field_name=f"{context}.session_id")
    expected_key = make_session_key(run_id, session_id)
    session_key = _optional_text(value.get("session_key")) or expected_key
    if session_key != expected_key:
        raise InvalidBookmarkError(
            "Session reference session_key does not match run_id/session_id.",
            details={"context": context, "session_key": session_key, "expected_session_key": expected_key},
        )
    expected_ref_id = make_session_ref_id(library_id, session_key)
    session_ref_id = _optional_text(value.get("session_ref_id")) or expected_ref_id
    if session_ref_id != expected_ref_id:
        raise InvalidBookmarkError(
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


def _normalized_window(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise InvalidBookmarkError("window must be an object.")
    start_s = _number_or_none(value.get("start_s"))
    if start_s is None:
        start_s = _number_or_none(value.get("startS"))
    if start_s is None:
        start_s = _number_or_none(value.get("t0"))
    end_s = _number_or_none(value.get("end_s"))
    if end_s is None:
        end_s = _number_or_none(value.get("endS"))
    if end_s is None:
        end_s = _number_or_none(value.get("t1"))
    if start_s is None or end_s is None:
        raise InvalidBookmarkError("window.start_s and window.end_s are required.")
    if end_s < start_s:
        raise InvalidBookmarkError("window.end_s must be >= window.start_s.")
    return {"start_s": float(start_s), "end_s": float(end_s)}


def _bookmark_matches(
    bookmark: Mapping[str, Any],
    *,
    library_id: str | None,
    session_key: str | None,
    session_ref_id: str | None,
) -> bool:
    session = bookmark.get("session")
    if not isinstance(session, Mapping):
        return False
    if library_id is not None and str(session.get("library_id") or "") != str(library_id):
        return False
    if session_key is not None and str(session.get("session_key") or "") != str(session_key):
        return False
    if session_ref_id is not None and str(bookmark.get("session_ref_id") or "") != str(session_ref_id):
        return False
    return True


def _bookmarks_dir(libraries_root: str | Path) -> Path:
    return Path(libraries_root) / BOOKMARKS_DIR


def _bookmark_path(libraries_root: str | Path, bookmark_id: str) -> Path:
    bookmark_id = _required_text(bookmark_id, field_name="bookmark_id")
    if not is_valid_object_id(bookmark_id):
        raise InvalidBookmarkError("Bookmark id is not filename-safe.", details={"bookmark_id": bookmark_id})
    return _bookmarks_dir(libraries_root) / f"{bookmark_id}.json"


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BookmarkNotFoundError("Bookmark was not found.", details={"bookmark_id": path.stem})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidBookmarkError(
            "Bookmark JSON could not be read.",
            details={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    if not isinstance(value, Mapping):
        raise InvalidBookmarkError("Bookmark JSON must be an object.", details={"path": str(path)})
    return dict(value)


def _write_bookmark(libraries_root: str | Path, payload: Mapping[str, Any]) -> None:
    bookmark_id = str(payload["bookmark_id"])
    path = _bookmark_path(libraries_root, bookmark_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidBookmarkError(f"Bookmark missing non-empty {field_name!r}.")
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
