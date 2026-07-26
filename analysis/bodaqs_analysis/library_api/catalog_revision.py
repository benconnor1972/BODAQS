"""Small per-library revision marker for cheap catalog cache validation."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


CATALOG_REVISION_FILENAME = "library_catalog_revision.json"
CATALOG_REVISION_SCHEMA = "bodaqs.library_catalog_revision"
CATALOG_REVISION_VERSION = 1


def catalog_revision_path(library_root: str | Path) -> Path:
    return Path(library_root).expanduser() / CATALOG_REVISION_FILENAME


def load_catalog_revision(library_root: str | Path) -> dict[str, Any] | None:
    path = catalog_revision_path(library_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema") != CATALOG_REVISION_SCHEMA:
        return None
    if int(payload.get("version") or -1) != CATALOG_REVISION_VERSION:
        return None
    return dict(payload)


def ensure_catalog_revision(
    library_root: str | Path,
    *,
    reason: str = "catalog_revision_backfill",
    actor: str = "library_api",
) -> dict[str, Any] | None:
    current = load_catalog_revision(library_root)
    if current is not None:
        return current
    return touch_catalog_revision(library_root, reason=reason, actor=actor)


def touch_catalog_revision(
    library_root: str | Path,
    *,
    reason: str,
    actor: str,
    changed_sessions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    root = Path(library_root).expanduser()
    current = load_catalog_revision(root)
    current_revision = int(current.get("revision") or 0) if current is not None else 0
    payload = {
        "schema": CATALOG_REVISION_SCHEMA,
        "version": CATALOG_REVISION_VERSION,
        "revision": current_revision + 1,
        "updated_at_utc": _utcnow_iso(),
        "reason": str(reason),
        "actor": str(actor),
    }
    if changed_sessions:
        payload["changed_sessions"] = [dict(item) for item in changed_sessions]
    path = catalog_revision_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return None
    return payload


def catalog_revision_dependency(library_root: str | Path) -> dict[str, Any] | None:
    path = catalog_revision_path(library_root)
    revision = load_catalog_revision(library_root)
    if revision is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        stat = None
    return {
        "path": path.name,
        "schema": revision.get("schema"),
        "version": revision.get("version"),
        "revision": revision.get("revision"),
        "updated_at_utc": revision.get("updated_at_utc"),
        "reason": revision.get("reason"),
        "size": int(stat.st_size) if stat is not None else None,
        "mtime_ns": int(stat.st_mtime_ns) if stat is not None else None,
    }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
