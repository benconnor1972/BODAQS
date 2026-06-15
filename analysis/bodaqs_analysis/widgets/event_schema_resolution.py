# -*- coding: utf-8 -*-
"""Resolve the event schema that should be used for selected artifact sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from bodaqs_analysis.artifacts import ArtifactStore, list_event_types
from bodaqs_analysis.schema import parse_event_schema
from bodaqs_analysis.widgets.contracts import KeyToRef
from bodaqs_analysis.widgets.contracts import SessionSelectorHandle
from bodaqs_analysis.widgets.contracts import selection_snapshot_from_handle


class EventSchemaResolutionError(ValueError):
    """Raised when a selected scope cannot be resolved to one event schema."""


@dataclass(frozen=True)
class EventSchemaResolution:
    """Resolved single-schema result for current v0 notebook widgets."""

    schema: dict[str, Any]
    source: str
    sha256: str | None
    source_paths: tuple[str, ...]
    event_schema_dirs: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _SchemaCandidate:
    schema: dict[str, Any]
    sha256: str
    path: Path
    session_key: str
    run_id: str
    session_id: str
    event_schema_dir: str


def resolve_event_schema_for_selection(
    sel: SessionSelectorHandle | Mapping[str, Any],
    *,
    fallback_schema_path: str | Path | None = None,
) -> EventSchemaResolution:
    """Resolve the event schema for a selector-like notebook handle."""

    snapshot = selection_snapshot_from_handle(sel)
    store = sel.get("store") if isinstance(sel, Mapping) else None
    if store is None:
        raise EventSchemaResolutionError("Selector handle must include an artifact store under 'store'.")
    return resolve_event_schema_for_sessions(
        store=store,
        key_to_ref=snapshot.key_to_ref,
        fallback_schema_path=fallback_schema_path,
    )


def resolve_event_schema_for_sessions(
    *,
    store: ArtifactStore,
    key_to_ref: KeyToRef,
    fallback_schema_path: str | Path | None = None,
) -> EventSchemaResolution:
    """Resolve one event schema for selected sessions.

    Frozen per-session schemas are authoritative. A configured fallback is used
    only when no frozen schema is available in the selected scope.
    """

    if not key_to_ref:
        raise EventSchemaResolutionError("Cannot resolve an event schema for an empty session scope.")

    candidates: list[_SchemaCandidate] = []
    missing: list[str] = []
    event_schema_dirs: set[str] = set()

    for session_key, (run_id, session_id) in key_to_ref.items():
        for event_schema_dir in list_event_types(store, str(run_id), str(session_id)):
            event_schema_dirs.add(str(event_schema_dir))
            schema_path = _path_events_schema(store, str(run_id), str(session_id), str(event_schema_dir))
            if not schema_path.exists():
                missing.append(f"{session_key}/{event_schema_dir}")
                continue
            candidates.append(
                _load_schema_candidate(
                    schema_path,
                    session_key=str(session_key),
                    run_id=str(run_id),
                    session_id=str(session_id),
                    event_schema_dir=str(event_schema_dir),
                )
            )

    warnings: list[str] = []
    if not candidates:
        if fallback_schema_path is None:
            raise EventSchemaResolutionError(
                "No frozen event schema artifacts were found in the selected sessions, "
                "and no fallback schema path was supplied."
            )
        schema, sha256, path = _load_fallback_schema(fallback_schema_path)
        warnings.append(
            "No frozen event schema artifacts were found for the selected sessions; "
            f"using fallback schema: {path}"
        )
        if event_schema_dirs:
            warnings.append(
                "Selected event partitions without frozen schemas: "
                + ", ".join(sorted(event_schema_dirs)[:12])
            )
        return EventSchemaResolution(
            schema=schema,
            source="fallback",
            sha256=sha256,
            source_paths=(str(path),),
            event_schema_dirs=tuple(sorted(event_schema_dirs)),
            warnings=tuple(warnings),
        )

    by_hash: dict[str, list[_SchemaCandidate]] = {}
    for candidate in candidates:
        by_hash.setdefault(candidate.sha256, []).append(candidate)

    if len(by_hash) > 1:
        detail = []
        for sha256, items in sorted(by_hash.items()):
            sample_paths = ", ".join(str(item.path) for item in items[:3])
            detail.append(f"{sha256}: {sample_paths}")
        raise EventSchemaResolutionError(
            "Selected sessions contain multiple frozen event schema versions; "
            "current notebook widgets support one schema at a time. "
            + " | ".join(detail)
        )

    selected_hash = next(iter(by_hash))
    selected_candidates = by_hash[selected_hash]
    if missing:
        warnings.append(
            "Some selected event partitions do not contain frozen schema.yaml files; "
            "using the frozen schema found elsewhere in the selected scope. Missing: "
            + ", ".join(missing[:12])
        )

    return EventSchemaResolution(
        schema=dict(selected_candidates[0].schema),
        source="frozen_artifacts",
        sha256=selected_hash,
        source_paths=tuple(sorted({str(candidate.path) for candidate in selected_candidates})),
        event_schema_dirs=tuple(sorted(event_schema_dirs)),
        warnings=tuple(warnings),
    )


def _path_events_schema(store: Any, run_id: str, session_id: str, event_schema_dir: str) -> Path:
    path_fn = getattr(store, "path_events_schema", None)
    if callable(path_fn):
        return Path(path_fn(run_id, session_id, event_schema_dir))
    return Path(store.session_dir(run_id, session_id)) / "events" / event_schema_dir / "schema.yaml"


def _load_schema_candidate(
    path: Path,
    *,
    session_key: str,
    run_id: str,
    session_id: str,
    event_schema_dir: str,
) -> _SchemaCandidate:
    try:
        schema, meta = parse_event_schema(path, return_meta=True)
    except Exception as exc:
        raise EventSchemaResolutionError(f"Failed to load frozen event schema {path}: {exc}") from exc
    return _SchemaCandidate(
        schema=dict(schema),
        sha256=str(meta.get("sha256") or ""),
        path=path,
        session_key=session_key,
        run_id=run_id,
        session_id=session_id,
        event_schema_dir=event_schema_dir,
    )


def _load_fallback_schema(path: str | Path) -> tuple[dict[str, Any], str, Path]:
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise EventSchemaResolutionError(f"Fallback event schema path does not exist: {resolved}")
    try:
        schema, meta = parse_event_schema(resolved, return_meta=True)
    except Exception as exc:
        raise EventSchemaResolutionError(f"Failed to load fallback event schema {resolved}: {exc}") from exc
    return dict(schema), str(meta.get("sha256") or ""), resolved
