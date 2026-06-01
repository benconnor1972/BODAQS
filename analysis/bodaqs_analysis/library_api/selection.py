"""Notebook compatibility bridge for Study Set selections."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore
from bodaqs_analysis.widgets.contracts import (
    RUN_ID_COL,
    SESSION_ID_COL,
    SESSION_KEY_COL,
    EntitySelectionSnapshot,
    ScopeEntity,
    SelectionSnapshot,
)
from bodaqs_analysis.widgets.entity_scope import build_entity_selection_snapshot

from .errors import InvalidStudySetError
from .ids import make_session_key
from .study_sets import load_study_set


SELECTION_BRIDGE_SCHEMA = "bodaqs.study_set_selection_snapshot"
SELECTION_BRIDGE_VERSION = 1


def study_set_to_selection_snapshot(
    library_root: str | Path,
    study_set_or_id: str | Mapping[str, Any],
    *,
    include_groupings: bool = True,
) -> dict[str, Any]:
    """Convert a persisted Study Set into notebook/widget selection objects."""

    root = Path(library_root)
    study_set = (
        dict(study_set_or_id)
        if isinstance(study_set_or_id, Mapping)
        else load_study_set(root, str(study_set_or_id))
    )
    store = ArtifactStore(root)
    key_to_ref = _key_to_ref_from_study_set(study_set)
    events_index_df = _events_index_df_from_key_to_ref(key_to_ref)
    selected_entities = _selected_entities_from_study_set(
        study_set,
        include_groupings=include_groupings,
    )
    entity_snapshot = build_entity_selection_snapshot(
        selected_entities=selected_entities,
        key_to_ref=key_to_ref,
        events_index_df=events_index_df,
    )
    selection_snapshot = SelectionSnapshot(
        key_to_ref=dict(entity_snapshot.key_to_ref),
        events_index_df=entity_snapshot.events_index_df.copy(),
    )
    selector_handle = _selector_handle(
        store=store,
        selection_snapshot=selection_snapshot,
        entity_snapshot=entity_snapshot,
    )

    return {
        "schema": SELECTION_BRIDGE_SCHEMA,
        "version": SELECTION_BRIDGE_VERSION,
        "study_set": dict(study_set),
        "study_set_id": str(study_set["study_set_id"]),
        "display_name": str(study_set.get("display_name") or study_set["study_set_id"]),
        "store": store,
        "key_to_ref": dict(selection_snapshot.key_to_ref),
        "events_index_df": selection_snapshot.events_index_df.copy(),
        "selection_snapshot": selection_snapshot,
        "entity_snapshot": entity_snapshot,
        "selector_handle": selector_handle,
    }


def _key_to_ref_from_study_set(study_set: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    sessions = study_set.get("sessions")
    if not isinstance(sessions, list):
        raise InvalidStudySetError("Study Set sessions must be a list.")

    out: dict[str, tuple[str, str]] = {}
    for index, session in enumerate(sessions):
        if not isinstance(session, Mapping):
            raise InvalidStudySetError(f"sessions[{index}] must be a session reference object.")
        run_id = _required_text(session.get("run_id"), field_name=f"sessions[{index}].run_id")
        session_id = _required_text(session.get("session_id"), field_name=f"sessions[{index}].session_id")
        session_key = _required_text(session.get("session_key"), field_name=f"sessions[{index}].session_key")
        expected = make_session_key(run_id, session_id)
        if session_key != expected:
            raise InvalidStudySetError(
                "Session reference session_key does not match run_id/session_id.",
                details={"session_key": session_key, "expected_session_key": expected},
            )
        out[session_key] = (run_id, session_id)
    return out


def _events_index_df_from_key_to_ref(key_to_ref: Mapping[str, tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {SESSION_KEY_COL: session_key, RUN_ID_COL: run_id, SESSION_ID_COL: session_id}
            for session_key, (run_id, session_id) in key_to_ref.items()
        ],
        columns=[SESSION_KEY_COL, RUN_ID_COL, SESSION_ID_COL],
    )


def _selected_entities_from_study_set(
    study_set: Mapping[str, Any],
    *,
    include_groupings: bool,
) -> list[ScopeEntity]:
    key_to_ref = _key_to_ref_from_study_set(study_set)
    session_labels = _session_labels(study_set)
    grouped_session_keys: set[str] = set()
    entities: list[ScopeEntity] = []

    if include_groupings:
        for grouping in _valid_groupings(study_set):
            grouping_id = _required_text(grouping.get("grouping_id"), field_name="grouping.grouping_id")
            display_name = _required_text(grouping.get("display_name"), field_name="grouping.display_name")
            member_keys = tuple(
                session_key
                for session_key in _grouping_session_keys(grouping)
                if session_key in key_to_ref
            )
            if not member_keys:
                continue
            grouped_session_keys.update(member_keys)
            entities.append(
                ScopeEntity(
                    entity_key=f"study_set:{study_set['study_set_id']}:grouping:{grouping_id}",
                    kind="aggregation",
                    label=str(display_name),
                    member_session_keys=member_keys,
                )
            )

    for session_key in key_to_ref.keys():
        if include_groupings and session_key in grouped_session_keys:
            continue
        entities.append(
            ScopeEntity(
                entity_key=session_key,
                kind="session",
                label=session_labels.get(session_key, session_key),
                member_session_keys=(session_key,),
            )
        )
    return entities


def _session_labels(study_set: Mapping[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    sessions = study_set.get("sessions")
    if not isinstance(sessions, list):
        return labels
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        session_key = session.get("session_key")
        if not isinstance(session_key, str):
            continue
        label = session.get("label") or session.get("display_label")
        labels[session_key] = str(label).strip() if isinstance(label, str) and label.strip() else session_key
    return labels


def _valid_groupings(study_set: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    groupings = study_set.get("groupings")
    if not isinstance(groupings, list):
        return []
    return [grouping for grouping in groupings if isinstance(grouping, Mapping)]


def _grouping_session_keys(grouping: Mapping[str, Any]) -> list[str]:
    session_refs = grouping.get("session_refs")
    if isinstance(session_refs, list):
        out: list[str] = []
        for session_ref in session_refs:
            if not isinstance(session_ref, str):
                continue
            for separator in ("|||",):
                if separator in session_ref:
                    out.append(session_ref.split(separator, 1)[1])
                    break
            else:
                out.append(session_ref)
        return out

    sessions = grouping.get("sessions")
    if not isinstance(sessions, list):
        return []
    out: list[str] = []
    for session in sessions:
        if isinstance(session, Mapping) and isinstance(session.get("session_key"), str):
            out.append(str(session["session_key"]))
    return out


def _selector_handle(
    *,
    store: ArtifactStore,
    selection_snapshot: SelectionSnapshot,
    entity_snapshot: EntitySelectionSnapshot,
) -> dict[str, Any]:
    def get_key_to_ref() -> dict[str, tuple[str, str]]:
        return dict(selection_snapshot.key_to_ref)

    def get_events_index_df() -> pd.DataFrame:
        return selection_snapshot.events_index_df.copy()

    def get_entity_snapshot() -> EntitySelectionSnapshot:
        return EntitySelectionSnapshot(
            selected_entities=list(entity_snapshot.selected_entities),
            entity_to_effective_members={
                str(key): list(map(str, value))
                for key, value in entity_snapshot.entity_to_effective_members.items()
            },
            expanded_session_keys=list(map(str, entity_snapshot.expanded_session_keys)),
            key_to_ref=dict(entity_snapshot.key_to_ref),
            events_index_df=entity_snapshot.events_index_df.copy(),
        )

    return {
        "ui": None,
        "store": store,
        "get_key_to_ref": get_key_to_ref,
        "get_events_index_df": get_events_index_df,
        "get_entity_snapshot": get_entity_snapshot,
    }


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidStudySetError(f"Study Set missing non-empty {field_name!r}.")
    return value.strip()
