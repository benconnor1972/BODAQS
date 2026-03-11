# -*- coding: utf-8 -*-
"""Entity selection expansion and policy validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

import pandas as pd

from bodaqs_analysis.artifacts import list_event_types
from bodaqs_analysis.widgets.contracts import (
    EntityKey,
    EntitySelectionSnapshot,
    EventSchemaPolicy,
    KeyToRef,
    RegistryPolicy,
    ScopeEntity,
    SessionKey,
    SessionLoader,
)
from bodaqs_analysis.widgets.registry_scope import (
    apply_registry_policy_to_registries,
    load_signal_registries_for_sessions,
)


@dataclass(frozen=True)
class ExpandedEntityScope:
    entity_to_effective_members: Dict[EntityKey, list[SessionKey]]
    expanded_session_keys: list[SessionKey]
    reduced_members_by_entity: Dict[EntityKey, list[SessionKey]]


def _unique_in_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        s = str(v)
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def expand_selected_entities(
    *,
    selected_entities: Sequence[ScopeEntity],
    key_to_ref: KeyToRef,
) -> ExpandedEntityScope:
    """
    Expand selected entities to physical sessions.

    Overlap policy:
    - explicit session entities take precedence
    - overlapping members are removed from aggregation effective members
    """
    valid_keys = {str(k) for k in key_to_ref.keys()}

    explicit_sessions: set[str] = set()
    for entity in selected_entities:
        if entity.kind != "session":
            continue
        explicit_sessions.update(
            sk for sk in [str(x) for x in entity.member_session_keys] if sk in valid_keys
        )

    entity_to_effective_members: Dict[EntityKey, list[SessionKey]] = {}
    reduced_members_by_entity: Dict[EntityKey, list[SessionKey]] = {}

    for entity in selected_entities:
        entity_key = str(entity.entity_key)
        members = [sk for sk in _unique_in_order(entity.member_session_keys) if sk in valid_keys]

        if entity.kind == "aggregation":
            reduced = [sk for sk in members if sk in explicit_sessions]
            if reduced:
                reduced_members_by_entity[entity_key] = reduced
            members = [sk for sk in members if sk not in explicit_sessions]

        entity_to_effective_members[entity_key] = members

    expanded = _unique_in_order(
        [
            sk
            for entity in selected_entities
            for sk in entity_to_effective_members.get(str(entity.entity_key), [])
        ]
    )

    return ExpandedEntityScope(
        entity_to_effective_members=entity_to_effective_members,
        expanded_session_keys=expanded,
        reduced_members_by_entity=reduced_members_by_entity,
    )


def build_entity_selection_snapshot(
    *,
    selected_entities: Sequence[ScopeEntity],
    key_to_ref: KeyToRef,
    events_index_df: pd.DataFrame,
) -> EntitySelectionSnapshot:
    expanded = expand_selected_entities(selected_entities=selected_entities, key_to_ref=key_to_ref)
    expanded_keys = set(expanded.expanded_session_keys)

    events_df = events_index_df.copy()
    if "session_key" in events_df.columns:
        events_df = events_df[events_df["session_key"].astype(str).isin(expanded_keys)].copy()

    return EntitySelectionSnapshot(
        selected_entities=list(selected_entities),
        entity_to_effective_members={
            str(k): list(map(str, v)) for k, v in expanded.entity_to_effective_members.items()
        },
        expanded_session_keys=list(map(str, expanded.expanded_session_keys)),
        key_to_ref={k: v for k, v in key_to_ref.items() if str(k) in expanded_keys},
        events_index_df=events_df,
    )


def validate_registry_policy_for_sessions(
    *,
    session_keys: Sequence[str],
    session_loader: SessionLoader,
    policy: RegistryPolicy,
) -> dict[str, dict[str, Mapping[str, Any]]]:
    registries = load_signal_registries_for_sessions(
        session_keys=list(map(str, session_keys)),
        session_loader=session_loader,
    )
    return apply_registry_policy_to_registries(
        registries_by_session=registries,
        policy=policy,
        session_order=list(map(str, session_keys)),
    )


def _as_hash_map(value: Any) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    if not isinstance(value, Mapping):
        return out

    for schema_id, info in value.items():
        sid = str(schema_id).strip()
        if not sid:
            continue

        if isinstance(info, str):
            h = info.strip()
            out[sid] = h if h else None
            continue

        if isinstance(info, Mapping):
            for key in ("schema_hash", "hash", "sha256"):
                if key in info and info.get(key) is not None:
                    h = str(info.get(key)).strip()
                    out[sid] = h if h else None
                    break
            else:
                out[sid] = None
    return out


def extract_event_schema_hashes_from_meta(session_meta: Mapping[str, Any]) -> dict[str, str | None]:
    """
    Best-effort schema hash extraction from session metadata.

    Supported shapes include:
    - meta['event_schema_hashes'][schema_id] = hash
    - meta['schema_hash_by_id'][schema_id] = hash
    - meta['event_schemas'][schema_id] = {'schema_hash': ...}
    - meta['event_schema'] = {'schema_id': ..., 'schema_hash': ...}
    """
    if not isinstance(session_meta, Mapping):
        return {}

    for key in ("event_schema_hashes", "schema_hash_by_id", "event_schemas"):
        hashes = _as_hash_map(session_meta.get(key))
        if hashes:
            return hashes

    event_schema = session_meta.get("event_schema")
    if isinstance(event_schema, Mapping):
        sid = str(event_schema.get("schema_id") or "").strip()
        if sid:
            h = (
                event_schema.get("schema_hash")
                or event_schema.get("hash")
                or event_schema.get("sha256")
            )
            hs = str(h).strip() if h is not None else ""
            return {sid: (hs if hs else None)}

    sid = str(session_meta.get("schema_id") or "").strip()
    if sid:
        h = session_meta.get("schema_hash") or session_meta.get("event_schema_hash")
        hs = str(h).strip() if h is not None else ""
        return {sid: (hs if hs else None)}

    return {}


def resolve_event_schema_sets_for_sessions(
    *,
    session_keys: Sequence[str],
    key_to_ref: KeyToRef,
    store: Any,
    session_loader: SessionLoader,
    policy: EventSchemaPolicy,
) -> list[str]:
    """Resolve and validate event schema scope for a session set."""
    ordered = [str(sk) for sk in session_keys]
    schema_ids_by_session: dict[str, set[str]] = {}

    for sk in ordered:
        if sk not in key_to_ref:
            schema_ids_by_session[sk] = set()
            continue
        run_id, session_id = key_to_ref[sk]
        ids = set(map(str, list_event_types(store, run_id=str(run_id), session_id=str(session_id))))
        schema_ids_by_session[sk] = ids

    sets = list(schema_ids_by_session.values())
    if not sets:
        return []

    if policy == "intersection":
        resolved = set.intersection(*sets) if sets else set()
    elif policy == "strict":
        first = sets[0]
        mismatched = [sk for sk, sid_set in schema_ids_by_session.items() if sid_set != first]
        if mismatched:
            sample = ", ".join(mismatched[:3])
            raise ValueError(
                "event_schema_policy='strict' requires identical schema-id sets across members; "
                f"mismatched sessions include: {sample}"
            )
        resolved = set(first)
    else:
        resolved = set.union(*sets)

    if policy != "strict":
        return sorted(resolved)

    hashes_by_session: dict[str, dict[str, str | None]] = {}
    for sk in ordered:
        sess = session_loader(sk)
        meta = (sess or {}).get("meta") or {}
        hashes_by_session[sk] = extract_event_schema_hashes_from_meta(meta)

    for schema_id in sorted(resolved):
        observed: set[str] = set()
        missing: list[str] = []

        for sk in ordered:
            hs = hashes_by_session.get(sk, {}).get(schema_id)
            if not hs:
                missing.append(sk)
                continue
            observed.add(str(hs))

        if missing:
            sample = ", ".join(missing[:3])
            raise ValueError(
                "event_schema_policy='strict' requires schema hash metadata for every member/session schema_id. "
                f"Missing hash for schema_id={schema_id!r} in sessions: {sample}. "
                "Persist schema hashes in session metadata and rebuild artifacts."
            )

        if len(observed) > 1:
            raise ValueError(
                "event_schema_policy='strict' requires matching schema hashes per schema_id across members; "
                f"schema_id={schema_id!r} has differing hashes."
            )

    return sorted(resolved)
