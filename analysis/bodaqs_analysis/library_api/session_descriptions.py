"""Run/session description writes for the BODAQS Library API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from bodaqs_analysis.artifacts import ArtifactStore, set_run_description, set_session_description

from .errors import InvalidRequestError


SESSION_DESCRIPTIONS_API_SCHEMA = "bodaqs.library_api.session_descriptions"
SESSION_DESCRIPTIONS_API_VERSION = 1


def update_session_descriptions(
    library_root: str | Path,
    session_ref: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist short run/session descriptions for an existing session."""

    if not isinstance(payload, Mapping):
        raise InvalidRequestError("Description payload must be a JSON object.")

    descriptions = payload.get("descriptions", payload)
    if not isinstance(descriptions, Mapping):
        raise InvalidRequestError("Description payload must include a JSON object.")

    has_run = "run_description" in descriptions
    has_session = "session_description" in descriptions
    if not has_run and not has_session:
        raise InvalidRequestError(
            "Description update must include run_description and/or session_description."
        )

    store = ArtifactStore(Path(library_root).expanduser())
    run_id = _required_text(session_ref.get("run_id"), field_name="session_ref.run_id")
    session_id = _required_text(session_ref.get("session_id"), field_name="session_ref.session_id")

    if has_run:
        set_run_description(
            store,
            run_id=run_id,
            description=_nullable_text(descriptions.get("run_description")),
        )
    if has_session:
        set_session_description(
            store,
            run_id=run_id,
            session_id=session_id,
            description=_nullable_text(descriptions.get("session_description")),
        )

    run_manifest = store.read_json(store.path_run_manifest(run_id))
    session_manifest = store.read_json(store.path_session_manifest(run_id, session_id))
    updated_fields = []
    if has_run:
        updated_fields.append("run_description")
    if has_session:
        updated_fields.append("session_description")

    return {
        "schema": SESSION_DESCRIPTIONS_API_SCHEMA,
        "version": SESSION_DESCRIPTIONS_API_VERSION,
        "updated": True,
        "updated_fields": updated_fields,
        "session_ref": dict(session_ref),
        "run_description": _nullable_text(run_manifest.get("description")),
        "session_description": _nullable_text(session_manifest.get("description")),
    }


def _required_text(value: Any, *, field_name: str) -> str:
    text = _nullable_text(value)
    if text is None:
        raise InvalidRequestError(f"Description update missing non-empty {field_name}.")
    return text


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
