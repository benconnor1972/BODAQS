"""User-owned session flags and tags, independent of generated GPS/QA data."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from bodaqs_analysis.artifacts import ArtifactStore
from .errors import InvalidRequestError, RevisionConflictError, SessionNotFoundError
from .ids import make_session_key, make_session_ref_id

SESSION_USER_ANNOTATIONS_SCHEMA = "bodaqs.session_user_annotations"
SESSION_USER_ANNOTATIONS_VERSION = 1
_WRITE_LOCKS = [RLock() for _ in range(64)]


def _annotation_lock(library_root: str | Path, session_ref: Mapping[str, Any]):
    # Derive the lock from the stable library root and lexical identifiers,
    # before resolving a file another writer may be atomically replacing.
    root = Path(library_root).expanduser().resolve()
    identity = (os.path.normcase(str(root)), str(session_ref.get("run_id", "")).strip(),
                str(session_ref.get("session_id", "")).strip())
    return _WRITE_LOCKS[hash(identity) % len(_WRITE_LOCKS)]


def _location(library_root: str | Path, session_ref: Mapping[str, Any]) -> tuple[Path, dict[str, str]]:
    ref = {}
    for key in ("library_id", "run_id", "session_id"):
        value = session_ref.get(key)
        if not isinstance(value, str) or not value.strip():
            raise InvalidRequestError(f"session_ref.{key} must be a non-empty string.")
        ref[key] = value.strip()
    for key in ("run_id", "session_id"):
        if ref[key] in {".", ".."} or any(char in ref[key] for char in "/\\:"):
            raise InvalidRequestError(f"session_ref.{key} must be a single path component.")
    ref["session_key"] = make_session_key(ref["run_id"], ref["session_id"])
    if session_ref.get("session_key", ref["session_key"]) != ref["session_key"]:
        raise InvalidRequestError("session_ref.session_key does not match run_id/session_id.")
    ref["session_ref_id"] = make_session_ref_id(ref["library_id"], ref["session_key"])
    root = Path(library_root).expanduser().resolve()
    store = ArtifactStore(root)
    path = store.path_session_user_annotations(ref["run_id"], ref["session_id"]).resolve()
    if not path.is_relative_to(root):
        raise InvalidRequestError("Session annotations path is outside the library.")
    if not store.session_dir(ref["run_id"], ref["session_id"]).is_dir():
        raise SessionNotFoundError("Session was not found.", details={"session_ref": ref})
    return path, ref


def _content(payload: Mapping[str, Any]) -> dict[str, Any]:
    if set(payload) - {"tags", "gps_issue", "qa_issue"}:
        raise InvalidRequestError("Annotations contain unsupported fields.")
    if set(payload) != {"tags", "gps_issue", "qa_issue"}:
        raise InvalidRequestError("Annotations require tags, gps_issue and qa_issue.")
    tags = payload["tags"]
    if not isinstance(tags, list) or len(tags) > 100:
        raise InvalidRequestError("tags must be a list of at most 100 strings.")
    normalized_tags = set()
    for tag in tags:
        if not isinstance(tag, str):
            raise InvalidRequestError("Each tag must be a string.")
        tag = tag.strip().casefold()
        if not tag or len(tag) > 80 or any(ord(char) < 32 for char in tag):
            raise InvalidRequestError("Tags must contain 1–80 characters without control characters.")
        normalized_tags.add(tag)
    out: dict[str, Any] = {"tags": sorted(normalized_tags)}
    for key in ("gps_issue", "qa_issue"):
        issue = payload[key]
        if not isinstance(issue, Mapping) or set(issue) - {"flagged", "explanation"}:
            raise InvalidRequestError(f"{key} must contain flagged and optional explanation.")
        if not isinstance(issue.get("flagged"), bool):
            raise InvalidRequestError(f"{key}.flagged must be boolean.")
        explanation = issue.get("explanation", "")
        if not isinstance(explanation, str) or len(explanation) > 4000:
            raise InvalidRequestError(f"{key}.explanation must be a string of at most 4000 characters.")
        out[key] = {"flagged": issue["flagged"], "explanation": explanation.strip()}
    return out


def _empty_document(ref: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema": SESSION_USER_ANNOTATIONS_SCHEMA, "version": SESSION_USER_ANNOTATIONS_VERSION,
        "run_id": ref["run_id"], "session_id": ref["session_id"], "session_key": ref["session_key"],
        "revision": 0, "tags": [],
        "gps_issue": {"flagged": False, "explanation": ""},
        "qa_issue": {"flagged": False, "explanation": ""},
        "created_at_utc": "", "updated_at_utc": "",
    }


def _read_document(path: Path, ref: Mapping[str, str]) -> dict[str, Any]:
    if not path.exists():
        return _empty_document(ref)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidRequestError("Session annotations are unreadable.") from exc
    if not isinstance(doc, dict) or doc.get("schema") != SESSION_USER_ANNOTATIONS_SCHEMA or doc.get("version") != 1:
        raise InvalidRequestError("Session annotations have an unsupported schema/version.")
    if any(doc.get(key) != ref[key] for key in ("run_id", "session_id", "session_key")):
        raise InvalidRequestError("Session annotations belong to another session.")
    if type(doc.get("revision")) is not int or doc["revision"] < 1:
        raise InvalidRequestError("Session annotations have an invalid revision.")
    for key in ("created_at_utc", "updated_at_utc"):
        if not isinstance(doc.get(key), str) or not doc[key]:
            raise InvalidRequestError("Session annotations have invalid timestamps.")
    doc.update(_content({key: doc.get(key) for key in ("tags", "gps_issue", "qa_issue")}))
    return doc


def _response(ref: Mapping[str, str], doc: Mapping[str, Any], *, present: bool) -> dict[str, Any]:
    return {"schema": "bodaqs.library_api.session_user_annotations", "version": 1,
            "session_ref": dict(ref), "present": present, "annotations": dict(doc)}


def load_session_user_annotations(library_root: str | Path, session_ref: Mapping[str, Any]) -> dict[str, Any]:
    with _annotation_lock(library_root, session_ref):
        path, ref = _location(library_root, session_ref)
        doc = _read_document(path, ref)
        return _response(ref, doc, present=doc["revision"] > 0)


def save_session_user_annotations(
    library_root: str | Path, session_ref: Mapping[str, Any], payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace editable contents using an expected revision; serialize writers in this process."""
    if not isinstance(payload, Mapping):
        raise InvalidRequestError("Session annotation payload must be an object.")
    with _annotation_lock(library_root, session_ref):
        path, ref = _location(library_root, session_ref)
        expected = payload.get("expected_revision")
        if type(expected) is not int or expected < 0:
            raise InvalidRequestError("expected_revision must be a non-negative integer.")
        raw = payload.get("annotations")
        if not isinstance(raw, Mapping):
            raise InvalidRequestError("annotations must be an object.")
        content = _content(raw)
        previous = _read_document(path, ref)
        if previous["revision"] != expected:
            raise RevisionConflictError("Session annotations were modified after loading.",
                                        details={"expected_revision": expected, "actual_revision": previous["revision"]})
        now = datetime.now(timezone.utc).isoformat()
        doc = {**previous, **content, "revision": expected + 1,
               "created_at_utc": previous["created_at_utc"] or now, "updated_at_utc": now}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(doc, handle, indent=2, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return _response(ref, doc, present=True)


def session_user_annotation_summary(store: ArtifactStore, run_id: str, session_id: str) -> dict[str, Any]:
    """Read only the small annotation document when building a catalog row."""
    ref = {"run_id": run_id, "session_id": session_id, "session_key": make_session_key(run_id, session_id)}
    path = store.path_session_user_annotations(run_id, session_id)
    try:
        doc = _read_document(path, ref)
    except InvalidRequestError:
        return {"present": True, "revision": None, "tags": [], "gps_issue": None, "qa_issue": None,
                "warnings": ["user_annotations_invalid"]}
    return {"present": doc["revision"] > 0, "revision": doc["revision"], "tags": doc["tags"],
            "gps_issue": doc["gps_issue"], "qa_issue": doc["qa_issue"], "warnings": []}
