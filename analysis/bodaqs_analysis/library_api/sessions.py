"""Session mutation helpers for the BODAQS Library API adapter."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Any

from bodaqs_analysis.artifacts import ArtifactStore

from .errors import (
    InvalidRequestError,
    SessionDeleteConflictError,
    SessionDeleteFailedError,
    SessionNotFoundError,
)
from .ids import make_session_key, make_session_ref_id
from .bookmarks import find_bookmark_session_references, remove_session_from_bookmarks
from .study_sets import find_study_set_session_references, remove_session_from_study_sets


def delete_session(
    libraries_root: str | Path,
    library_root: str | Path,
    *,
    library_id: str,
    run_id: str,
    session_id: str,
    cleanup_memberships: bool = False,
) -> dict[str, Any]:
    """Delete one processed session artifact, optionally cleaning saved memberships."""

    normalized_library_id = _required_text(library_id, field_name="library_id")
    normalized_run_id = _required_text(run_id, field_name="run_id")
    normalized_session_id = _required_text(session_id, field_name="session_id")
    session_key = make_session_key(normalized_run_id, normalized_session_id)
    session_ref_id = make_session_ref_id(normalized_library_id, session_key)
    store = ArtifactStore(Path(library_root))
    session_dir = _safe_session_dir(store.root, store.session_dir(normalized_run_id, normalized_session_id))
    if not session_dir.is_dir():
        raise SessionNotFoundError(
            "Session was not found.",
            details={
                "library_id": normalized_library_id,
                "run_id": normalized_run_id,
                "session_id": normalized_session_id,
                "session_ref_id": session_ref_id,
            },
        )

    references = [
        *find_study_set_session_references(libraries_root, session_ref_id),
        *find_bookmark_session_references(libraries_root, session_ref_id),
    ]
    if references and not cleanup_memberships:
        raise SessionDeleteConflictError(
            "Session is still referenced by saved library objects.",
            details={
                "library_id": normalized_library_id,
                "run_id": normalized_run_id,
                "session_id": normalized_session_id,
                "session_ref_id": session_ref_id,
                "references": references,
                "cleanup_hint": "Repeat the request with cleanup_memberships=true to remove saved memberships.",
            },
        )

    try:
        _remove_session_dir(session_dir)
    except OSError as exc:
        raise SessionDeleteFailedError(
            "Session artifact directory could not be removed.",
            details={
                "library_id": normalized_library_id,
                "run_id": normalized_run_id,
                "session_id": normalized_session_id,
                "session_ref_id": session_ref_id,
                "session_dir": str(session_dir),
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "cleanup_memberships": bool(cleanup_memberships),
                "updated_study_sets": [],
                "removed_bookmarks": [],
            },
        ) from exc
    updated_study_sets = remove_session_from_study_sets(libraries_root, session_ref_id) if cleanup_memberships else []
    removed_bookmarks = remove_session_from_bookmarks(libraries_root, session_ref_id) if cleanup_memberships else []
    return {
        "deleted": True,
        "library_id": normalized_library_id,
        "run_id": normalized_run_id,
        "session_id": normalized_session_id,
        "session_key": session_key,
        "session_ref_id": session_ref_id,
        "removed_paths": [str(session_dir)],
        "cleanup_memberships": bool(cleanup_memberships),
        "blocking_references": references if references and not cleanup_memberships else [],
        "updated_study_sets": updated_study_sets,
        "removed_bookmarks": removed_bookmarks,
    }


def _remove_session_dir(session_dir: Path) -> None:
    """Remove a session tree, retrying Windows read-only/OneDrive placeholders."""

    _make_tree_writable(session_dir)

    def handle_remove_error(func: Any, path_text: str, exc_info: Any) -> None:
        exc = exc_info[1]
        if not isinstance(exc, PermissionError):
            raise exc
        path = Path(path_text)
        _make_writable(path)
        try:
            func(path_text)
        except OSError as retry_exc:
            raise retry_exc from exc

    shutil.rmtree(session_dir, onerror=handle_remove_error)


def _make_tree_writable(path: Path) -> None:
    """Restore owner write/search permission throughout a session tree."""

    for root, directories, filenames in os.walk(path, topdown=True):
        root_path = Path(root)
        _make_writable(root_path)
        for name in [*directories, *filenames]:
            _make_writable(root_path / name)


def _make_writable(path: Path) -> None:
    try:
        mode = stat.S_IREAD | stat.S_IWRITE
        if path.is_dir():
            mode |= stat.S_IEXEC
        os.chmod(path, mode)
    except OSError:
        # Preserve the original delete error if permission repair also fails.
        return


def _safe_session_dir(library_root: Path, candidate: Path) -> Path:
    root = library_root.expanduser().resolve()
    session_dir = candidate.expanduser().resolve()
    try:
        session_dir.relative_to(root)
    except ValueError as exc:
        raise InvalidRequestError(
            "Session path resolves outside the library root.",
            details={"library_root": str(root), "session_dir": str(session_dir)},
        ) from exc
    return session_dir


def _required_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise InvalidRequestError(f"Session delete missing non-empty {field_name!r}.")
    return text
