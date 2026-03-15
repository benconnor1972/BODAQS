# bodaqs_analysis/widgets/session_selector.py

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import ipywidgets as W
import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore, list_runs, list_sessions
from bodaqs_analysis.widgets.contracts import (
    EntitySelectionSnapshot,
    MutableKeyToRef,
    PersistedEntityScopeLoadResult,
    PersistedEntityScopeSelection,
    RebuildFn,
    RefreshHandle,
    RUN_ID_COL,
    SESSION_ID_COL,
    SESSION_KEY_COL,
    SessionKey,
    SessionSelection,
    SessionSelectorHandle,
    ScopeEntity,
)
from bodaqs_analysis.widgets.entity_scope_store import (
    load_entity_scope_selection,
    save_entity_scope_selection,
)
from bodaqs_analysis.widgets.entity_scope import (
    expand_selected_entities,
    resolve_event_schema_sets_for_sessions,
    validate_registry_policy_for_sessions,
)
from bodaqs_analysis.widgets.loaders import make_session_loader
from bodaqs_analysis.widgets.session_aggregations import SessionAggregationStore


def make_session_key(run_id: str, session_id: str) -> SessionKey:
    return f"{run_id}::{session_id}"


def _events_index_df_from_key_to_ref(key_to_ref: Mapping[str, tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {SESSION_KEY_COL: k, RUN_ID_COL: rid, SESSION_ID_COL: sid}
            for k, (rid, sid) in key_to_ref.items()
        ]
    )


def _read_json_safe(store: ArtifactStore, path: Path) -> dict[str, Any]:
    try:
        return store.read_json(path)
    except Exception:
        return {}


def _get_run_meta(store: ArtifactStore, run_id: str) -> dict[str, str]:
    m = _read_json_safe(store, store.path_run_manifest(run_id))
    return {
        "created_at": str(m.get("created_at") or "").strip(),
        "description": str(m.get("description") or "").strip(),
    }


def _get_session_desc(store: ArtifactStore, run_id: str, session_id: str) -> str:
    m = _read_json_safe(store, store.path_session_manifest(run_id, session_id))
    return str(m.get("description") or "").strip()


def _all_key_to_ref(store: ArtifactStore) -> MutableKeyToRef:
    out: MutableKeyToRef = {}
    for rid in list_runs(store):
        for sid in list_sessions(store, rid):
            out[make_session_key(rid, sid)] = (rid, sid)
    return out


def _format_run_session_label(
    *,
    created_at: str,
    run_id: str,
    run_description: str,
    session_id: str,
    session_description: str,
    show_ids: bool,
) -> str:
    run_desc = run_description.strip()
    sess_desc = session_description.strip()

    if show_ids:
        run_part = f"run_id={run_id} | run_desc={run_desc or '(none)'}"
        sess_part = f"session_id={session_id} | session_desc={sess_desc or '(none)'}"
    else:
        run_part = run_desc or run_id
        sess_part = sess_desc or session_id

    parts = [p for p in [created_at, run_part, sess_part] if p]
    return " | ".join(parts)


def _format_run_label(
    *,
    run_id: str,
    run_description: str,
    show_ids: bool,
) -> str:
    run_desc = str(run_description or "").strip()
    if show_ids:
        return f"run_id={run_id} | run_desc={run_desc or '(none)'}"
    return run_desc or run_id


def _format_aggregation_label(
    *,
    aggregation_key: str,
    title: str,
    n_members: int,
    show_ids: bool,
) -> str:
    title_s = str(title or "").strip()
    if show_ids:
        return f"Aggregation | title={title_s or '(none)'} | key={aggregation_key} | n={n_members}"
    return f"Aggregation | {title_s or aggregation_key} ({n_members})"


def _build_run_options(
    *,
    store: ArtifactStore,
    show_ids: bool,
) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = [("__All runs__", "__ALL__")]
    for run_id in list_runs(store):
        run_meta = _get_run_meta(store, run_id)
        options.append(
            (
                _format_run_label(
                    run_id=str(run_id),
                    run_description=run_meta["description"],
                    show_ids=show_ids,
                ),
                str(run_id),
            )
        )
    return options


def _build_session_index(
    *,
    store: ArtifactStore,
    selected_run_id: str | None,
    show_ids: bool,
) -> tuple[list[str], dict[str, SessionSelection], dict[str, str]]:
    run_ids = list_runs(store) if selected_run_id in (None, "__ALL__") else [str(selected_run_id)]

    rows: list[tuple[str, str, str]] = []
    for rid in run_ids:
        run_meta = _get_run_meta(store, rid)
        created_at = run_meta["created_at"]
        run_desc = run_meta["description"]

        for sid in list_sessions(store, rid):
            session_desc = _get_session_desc(store, rid, sid)
            label = _format_run_session_label(
                created_at=created_at,
                run_id=rid,
                run_description=run_desc,
                session_id=sid,
                session_description=session_desc,
                show_ids=show_ids,
            )
            rows.append((label, rid, sid))

    label_counts: dict[str, int] = {}
    options: list[str] = []
    label_to_sel: dict[str, SessionSelection] = {}
    session_key_to_label: dict[str, str] = {}

    for label, rid, sid in rows:
        n = label_counts.get(label, 0) + 1
        label_counts[label] = n
        unique_label = label if n == 1 else f"{label} [#{n}]"
        options.append(unique_label)
        label_to_sel[unique_label] = {"run_id": rid, "session_id": sid}
        session_key_to_label[make_session_key(rid, sid)] = unique_label

    return options, label_to_sel, session_key_to_label


def make_session_aggregation_editor(
    *,
    artifacts_dir: str | Path = "artifacts",
    default_run_id: str = "__ALL__",
    rows: int = 12,
    show_ids_default: bool = False,
) -> dict[str, Any]:
    """
    Standalone aggregation editor UI.

    This widget can be run in a separate notebook cell to create/update/delete
    persisted aggregations. It is independent of `make_session_selector`.
    """
    store = ArtifactStore(Path(artifacts_dir))
    agg_store = SessionAggregationStore()
    try:
        agg_store.load()
    except Exception:
        pass

    run_options = _build_run_options(store=store, show_ids=bool(show_ids_default))
    run_dd = W.Dropdown(
        options=run_options,
        value=(
            default_run_id
            if default_run_id in dict(run_options).values() or default_run_id == "__ALL__"
            else "__ALL__"
        ),
        description="Run",
        layout=W.Layout(width="820px"),
    )

    show_ids_cb = W.Checkbox(
        value=bool(show_ids_default),
        description="Show run and session IDs",
        indent=False,
        layout=W.Layout(width="260px"),
    )

    sessions_sel = W.SelectMultiple(
        options=[],
        value=(),
        rows=rows,
        description="Sessions",
        layout=W.Layout(width="820px"),
    )

    w_agg_list = W.Dropdown(
        options=[("(No saved aggregations)", "")],
        value="",
        description="Saved agg",
        layout=W.Layout(width="420px"),
    )
    w_agg_title = W.Text(value="", description="Title", layout=W.Layout(width="420px"))
    w_agg_note = W.Text(value="", description="Note", layout=W.Layout(width="420px"))
    w_agg_registry_policy = W.Dropdown(
        options=[("union", "union"), ("intersection", "intersection"), ("strict", "strict")],
        value="union",
        description="Registry",
        layout=W.Layout(width="220px"),
    )
    w_agg_schema_policy = W.Dropdown(
        options=[("union", "union"), ("intersection", "intersection"), ("strict", "strict")],
        value="union",
        description="Schema",
        layout=W.Layout(width="220px"),
    )
    b_agg_create = W.Button(description="Create", tooltip="Create aggregation from selected sessions")
    b_agg_update = W.Button(description="Update", tooltip="Update selected aggregation")
    b_agg_delete = W.Button(description="Delete", tooltip="Delete selected aggregation")
    b_agg_load = W.Button(description="Load", tooltip="Load aggregation members into session list")
    b_refresh = W.Button(description="Refresh", tooltip="Reload sessions and aggregations")

    out = W.Output(layout=W.Layout(width="1240px"))

    _label_to_sel: dict[str, SessionSelection] = {}
    _session_key_to_label: dict[str, str] = {}
    _all_key_to_ref_cache: MutableKeyToRef = {}
    _state: Dict[str, Any] = {"updating": False}

    def _set_status(lines: Sequence[str]) -> None:
        with out:
            out.clear_output()
            for line in lines:
                print(line)

    def _refresh_aggregation_options(*_) -> None:
        try:
            agg_store.load()
        except Exception:
            pass

        aggs = agg_store.list()
        if not aggs:
            w_agg_list.options = [("(No saved aggregations)", "")]
            w_agg_list.value = ""
            return

        opts = [
            (
                _format_aggregation_label(
                    aggregation_key=str(a.aggregation_key),
                    title=str(a.title),
                    n_members=len(a.member_session_keys),
                    show_ids=bool(show_ids_cb.value),
                ),
                a.aggregation_key,
            )
            for a in aggs
        ]

        prev = str(w_agg_list.value or "")
        valid = {v for _, v in opts}
        w_agg_list.options = opts
        w_agg_list.value = prev if prev in valid else opts[0][1]

    def _refresh_sessions(*_) -> None:
        nonlocal _label_to_sel, _session_key_to_label, _all_key_to_ref_cache

        prev_run = str(run_dd.value or "__ALL__")
        run_options = _build_run_options(store=store, show_ids=bool(show_ids_cb.value))
        valid_run_values = {str(v) for _, v in run_options}
        run_dd.options = run_options
        run_dd.value = prev_run if prev_run in valid_run_values else "__ALL__"

        _all_key_to_ref_cache = _all_key_to_ref(store)

        options, _label_to_sel, _session_key_to_label = _build_session_index(
            store=store,
            selected_run_id=run_dd.value,
            show_ids=bool(show_ids_cb.value),
        )
        prev = tuple(map(str, sessions_sel.value or ()))
        sessions_sel.options = options
        kept = tuple([lbl for lbl in prev if lbl in _label_to_sel])
        sessions_sel.value = kept if kept else ()

        _refresh_aggregation_options()

    def _selected_session_keys_from_ui() -> list[str]:
        keys: list[str] = []
        for lbl in sessions_sel.value:
            s = _label_to_sel.get(str(lbl))
            if not s:
                continue
            keys.append(make_session_key(str(s["run_id"]), str(s["session_id"])))
        # de-dup preserving order
        seen: set[str] = set()
        out_keys: list[str] = []
        for sk in keys:
            if sk in seen:
                continue
            seen.add(sk)
            out_keys.append(sk)
        return out_keys

    def _validate_aggregation_members(
        *,
        member_session_keys: Sequence[str],
        registry_policy: str,
        event_schema_policy: str,
    ) -> None:
        if not member_session_keys:
            raise ValueError("Select at least one physical session before saving an aggregation.")

        missing = [sk for sk in member_session_keys if sk not in _all_key_to_ref_cache]
        if missing:
            raise ValueError(
                f"Aggregation includes unknown sessions: {', '.join(missing[:3])}"
            )

        session_loader = make_session_loader(store=store, key_to_ref=_all_key_to_ref_cache)
        validate_registry_policy_for_sessions(
            session_keys=member_session_keys,
            session_loader=session_loader,
            policy=registry_policy,
        )
        resolve_event_schema_sets_for_sessions(
            session_keys=member_session_keys,
            key_to_ref=_all_key_to_ref_cache,
            store=store,
            session_loader=session_loader,
            policy=event_schema_policy,
        )

    def _on_agg_select(change):
        if _state["updating"]:
            return
        key = str(change.get("new") or "")
        if not key:
            return

        agg = agg_store.get(key)
        if agg is None:
            return

        _state["updating"] = True
        try:
            w_agg_title.value = agg.title
            w_agg_note.value = agg.note or ""
            w_agg_registry_policy.value = agg.registry_policy
            w_agg_schema_policy.value = agg.event_schema_policy
        finally:
            _state["updating"] = False

    def _on_agg_create(_):
        members = _selected_session_keys_from_ui()
        title = str(w_agg_title.value or "").strip()
        note = str(w_agg_note.value or "").strip() or None
        reg_pol = str(w_agg_registry_policy.value or "union")
        sch_pol = str(w_agg_schema_policy.value or "union")

        try:
            _validate_aggregation_members(
                member_session_keys=members,
                registry_policy=reg_pol,
                event_schema_policy=sch_pol,
            )
            created = agg_store.create(
                title=(title or f"Aggregation ({len(members)} sessions)"),
                member_session_keys=members,
                registry_policy=reg_pol,
                event_schema_policy=sch_pol,
                note=note,
            )
            agg_store.save()
            _refresh_aggregation_options()
            _set_status([f"Created aggregation {created.aggregation_key}."])
        except Exception as exc:
            _set_status([f"Create failed: {exc}"])

    def _on_agg_update(_):
        key = str(w_agg_list.value or "")
        if not key:
            _set_status(["Select a saved aggregation to update."])
            return

        members = _selected_session_keys_from_ui()
        title = str(w_agg_title.value or "").strip()
        note = str(w_agg_note.value or "").strip() or None
        reg_pol = str(w_agg_registry_policy.value or "union")
        sch_pol = str(w_agg_schema_policy.value or "union")

        if not title:
            _set_status(["Aggregation title is required for update."])
            return

        try:
            _validate_aggregation_members(
                member_session_keys=members,
                registry_policy=reg_pol,
                event_schema_policy=sch_pol,
            )
            agg_store.update(
                key,
                patch={
                    "title": title,
                    "member_session_keys": members,
                    "registry_policy": reg_pol,
                    "event_schema_policy": sch_pol,
                    "note": note,
                },
            )
            agg_store.save()
            _refresh_aggregation_options()
            _set_status([f"Updated aggregation {key}."])
        except Exception as exc:
            _set_status([f"Update failed: {exc}"])

    def _on_agg_delete(_):
        key = str(w_agg_list.value or "")
        if not key:
            _set_status(["Select a saved aggregation to delete."])
            return

        try:
            ok = agg_store.delete(key)
            if ok:
                agg_store.save()
            _refresh_aggregation_options()
            _set_status([f"Deleted aggregation {key}." if ok else "Aggregation not found."])
        except Exception as exc:
            _set_status([f"Delete failed: {exc}"])

    def _on_agg_load(_):
        key = str(w_agg_list.value or "")
        if not key:
            _set_status(["Select a saved aggregation to load."])
            return

        agg = agg_store.get(key)
        if agg is None:
            _set_status([f"Aggregation not found: {key}"])
            return

        labels: list[str] = []
        for sk in agg.member_session_keys:
            lbl = _session_key_to_label.get(str(sk))
            if lbl:
                labels.append(lbl)
        sessions_sel.value = tuple(labels)
        _set_status([f"Loaded {len(labels)} sessions from {key}."])

    run_dd.observe(_refresh_sessions, names="value")
    show_ids_cb.observe(_refresh_sessions, names="value")
    w_agg_list.observe(_on_agg_select, names="value")

    b_refresh.on_click(_refresh_sessions)
    b_agg_create.on_click(_on_agg_create)
    b_agg_update.on_click(_on_agg_update)
    b_agg_delete.on_click(_on_agg_delete)
    b_agg_load.on_click(_on_agg_load)

    _refresh_sessions()

    ui = W.VBox(
        [
            W.HBox([run_dd, show_ids_cb, b_refresh]),
            sessions_sel,
            W.VBox(
                [
                    W.HTML("<b>Session Aggregations</b>"),
                    W.HBox([w_agg_list, b_agg_load]),
                    W.HBox([w_agg_title, w_agg_note]),
                    W.HBox([w_agg_registry_policy, w_agg_schema_policy]),
                    W.HBox([b_agg_create, b_agg_update, b_agg_delete]),
                ]
            ),
            out,
        ]
    )

    return {
        "ui": ui,
        "store": store,
        "run_dd": run_dd,
        "show_ids_cb": show_ids_cb,
        "sessions_sel": sessions_sel,
        "out": out,
        "refresh": _refresh_sessions,
    }


def make_session_selector(
    *,
    artifacts_dir: str | Path = "artifacts",
    default_run_id: str = "__ALL__",
    select_first_by_default: bool = True,
    rows: int = 12,
    show_ids_default: bool = False,
    autosave_default: bool = True,
) -> SessionSelectorHandle:
    """
    Selection-only entity selector.

    Aggregations are loaded from persisted local store and can be consumed even if
    the aggregation editor cell has not been run in the current notebook session.
    """
    store = ArtifactStore(Path(artifacts_dir))
    agg_store = SessionAggregationStore()
    try:
        agg_store.load()
    except Exception:
        pass

    run_options = _build_run_options(store=store, show_ids=bool(show_ids_default))
    run_dd = W.Dropdown(
        options=run_options,
        value=(
            default_run_id
            if default_run_id in dict(run_options).values() or default_run_id == "__ALL__"
            else "__ALL__"
        ),
        description="Run",
        layout=W.Layout(width="820px"),
    )

    show_ids_cb = W.Checkbox(
        value=bool(show_ids_default),
        description="Show run and session IDs",
        indent=False,
        layout=W.Layout(width="260px"),
    )
    autosave_cb = W.Checkbox(
        value=bool(autosave_default),
        description="Autosave selection",
        indent=False,
        layout=W.Layout(width="180px"),
    )
    b_refresh = W.Button(description="Refresh", tooltip="Reload sessions and aggregations")
    b_save_selection = W.Button(
        description="Save selection",
        tooltip="Persist current entity selection for reuse in other notebooks",
    )
    b_load_selection = W.Button(
        description="Load saved selection",
        tooltip="Restore the last persisted entity selection",
    )
    refresh_signal = W.IntText(value=0, layout=W.Layout(display="none"))

    entities_sel = W.SelectMultiple(
        options=[],
        value=(),
        rows=rows,
        description="Entities",
        layout=W.Layout(width="820px"),
    )

    out = W.Output(layout=W.Layout(width="1240px"))

    _entity_label_to_entity: dict[str, ScopeEntity] = {}
    _all_key_to_ref_cache: MutableKeyToRef = {}
    _events_index_df_all = pd.DataFrame(columns=[SESSION_KEY_COL, RUN_ID_COL, SESSION_ID_COL])

    _selected: list[SessionSelection] = []
    _selected_entities: list[ScopeEntity] = []
    _entity_snapshot = EntitySelectionSnapshot(
        selected_entities=[],
        entity_to_effective_members={},
        expanded_session_keys=[],
        key_to_ref={},
        events_index_df=pd.DataFrame(columns=[SESSION_KEY_COL, RUN_ID_COL, SESSION_ID_COL]),
    )
    _key_to_ref: MutableKeyToRef = {}
    _events_index_df = pd.DataFrame(columns=[SESSION_KEY_COL, RUN_ID_COL, SESSION_ID_COL])

    def _set_status(lines: Sequence[str]) -> None:
        with out:
            out.clear_output()
            for line in lines:
                print(line)

    def _refresh_scope_sources() -> None:
        nonlocal _all_key_to_ref_cache, _events_index_df_all
        _all_key_to_ref_cache = _all_key_to_ref(store)
        _events_index_df_all = _events_index_df_from_key_to_ref(_all_key_to_ref_cache)

    def _rebuild_entity_options(*_) -> None:
        nonlocal _entity_label_to_entity

        prev_run = str(run_dd.value or "__ALL__")
        run_options = _build_run_options(store=store, show_ids=bool(show_ids_cb.value))
        valid_run_values = {str(v) for _, v in run_options}
        run_dd.options = run_options
        run_dd.value = prev_run if prev_run in valid_run_values else "__ALL__"

        prev_keys = {str(e.entity_key) for e in _selected_entities}
        try:
            agg_store.load()
        except Exception:
            pass

        _, _, session_key_to_label = _build_session_index(
            store=store,
            selected_run_id=run_dd.value,
            show_ids=bool(show_ids_cb.value),
        )

        label_counts: dict[str, int] = {}
        options: list[str] = []
        mapping: dict[str, ScopeEntity] = {}

        for session_key in sorted(session_key_to_label.keys()):
            base = f"Session | {session_key_to_label[session_key]}"
            n = label_counts.get(base, 0) + 1
            label_counts[base] = n
            label = base if n == 1 else f"{base} [#{n}]"
            mapping[label] = ScopeEntity(
                entity_key=str(session_key),
                kind="session",
                label=label,
                member_session_keys=(str(session_key),),
            )
            options.append(label)

        for agg in agg_store.list():
            base = _format_aggregation_label(
                aggregation_key=str(agg.aggregation_key),
                title=str(agg.title),
                n_members=len(agg.member_session_keys),
                show_ids=bool(show_ids_cb.value),
            )
            n = label_counts.get(base, 0) + 1
            label_counts[base] = n
            label = base if n == 1 else f"{base} [#{n}]"
            mapping[label] = ScopeEntity(
                entity_key=str(agg.aggregation_key),
                kind="aggregation",
                label=label,
                member_session_keys=tuple(map(str, agg.member_session_keys)),
            )
            options.append(label)

        _entity_label_to_entity = mapping
        entities_sel.options = options

        kept = tuple(
            lbl
            for lbl, entity in _entity_label_to_entity.items()
            if str(entity.entity_key) in prev_keys
        )
        if kept:
            entities_sel.value = kept
        elif select_first_by_default and options:
            entities_sel.value = (options[0],)
        else:
            entities_sel.value = ()

    def _refresh_scope_state(*_) -> None:
        nonlocal _selected, _selected_entities, _entity_snapshot, _key_to_ref, _events_index_df

        labels = list(map(str, entities_sel.value or ()))
        selected_entities = [
            _entity_label_to_entity[lbl]
            for lbl in labels
            if lbl in _entity_label_to_entity
        ]
        _selected_entities = selected_entities

        expanded = expand_selected_entities(
            selected_entities=selected_entities,
            key_to_ref=_all_key_to_ref_cache,
        )

        expanded_keys = list(map(str, expanded.expanded_session_keys))
        expanded_set = set(expanded_keys)

        _key_to_ref = {
            sk: ref for sk, ref in _all_key_to_ref_cache.items() if str(sk) in expanded_set
        }
        _events_index_df = _events_index_df_all[
            _events_index_df_all[SESSION_KEY_COL].astype(str).isin(expanded_set)
        ].copy()

        _entity_snapshot = EntitySelectionSnapshot(
            selected_entities=list(_selected_entities),
            entity_to_effective_members={
                str(k): list(map(str, v))
                for k, v in expanded.entity_to_effective_members.items()
            },
            expanded_session_keys=expanded_keys,
            key_to_ref=dict(_key_to_ref),
            events_index_df=_events_index_df.copy(),
        )

        _selected = [
            {"run_id": rid, "session_id": sid}
            for sk in expanded_keys
            for (rid, sid) in [_all_key_to_ref_cache.get(sk, ("", ""))]
            if rid and sid
        ]

        warnings: list[str] = []
        for entity_key, reduced in expanded.reduced_members_by_entity.items():
            if reduced:
                warnings.append(
                    f"Aggregation {entity_key}: removed overlapping members due to explicit session selections: {', '.join(reduced)}"
                )

        if bool(autosave_cb.value) and _selected_entities:
            try:
                _persist_selection(silent=True)
            except Exception as exc:
                warnings.append(f"Autosave failed: {exc}")

        _set_status(warnings)

    def _selection_labels_from_entity_keys(entity_keys: Sequence[str]) -> tuple[list[str], list[str]]:
        labels: list[str] = []
        missing: list[str] = []
        for entity_key in entity_keys:
            match = next(
                (
                    label
                    for label, entity in _entity_label_to_entity.items()
                    if str(entity.entity_key) == str(entity_key)
                ),
                None,
            )
            if match is None:
                missing.append(str(entity_key))
                continue
            labels.append(match)
        return labels, missing

    def _persist_selection(*, silent: bool) -> PersistedEntityScopeSelection:
        selection = save_entity_scope_selection(
            sel={
                "get_selected_entities": get_selected_entities,
            },
            artifacts_root=store.root,
        )
        if not silent:
            _set_status(
                [
                    f"Saved selection at {selection.saved_at_utc}.",
                    f"Selected entities: {', '.join(selection.selected_entity_keys)}",
                ]
            )
        return selection

    def save_selection() -> PersistedEntityScopeSelection:
        return _persist_selection(silent=False)

    def load_selection() -> PersistedEntityScopeLoadResult:
        _refresh_scope_sources()
        _rebuild_entity_options()
        result = load_entity_scope_selection(artifacts_dir=store.root, strict=False)
        labels, missing = _selection_labels_from_entity_keys(result.source.selected_entity_keys)
        if not labels:
            raise ValueError("Saved selection contains no entities available in the current selector")
        prev_labels = tuple(map(str, entities_sel.value or ()))
        entities_sel.value = tuple(labels)

        status_lines = [
            f"Loaded saved selection from {result.source.saved_at_utc}.",
            f"Selected entities: {', '.join(result.source.selected_entity_keys)}",
        ]
        status_lines.extend(result.warnings)
        if missing:
            status_lines.append(
                "Selector could not map persisted entities into the current option list: "
                + ", ".join(missing[:6])
            )
        if status_lines:
            _set_status(status_lines)
        if tuple(labels) == prev_labels:
            refresh_signal.value = int(refresh_signal.value or 0) + 1
        return result

    def _refresh_all(*_):
        _refresh_scope_sources()
        _rebuild_entity_options()
        _refresh_scope_state()

    run_dd.observe(_refresh_all, names="value")
    show_ids_cb.observe(_refresh_all, names="value")
    entities_sel.observe(_refresh_scope_state, names="value")
    def _on_autosave_change(change):
        if bool(change.get("new")) and _selected_entities:
            try:
                _persist_selection(silent=True)
            except Exception as exc:
                _set_status([f"Autosave failed: {exc}"])

    autosave_cb.observe(_on_autosave_change, names="value")
    def _on_save_selection(_):
        try:
            save_selection()
        except Exception as exc:
            _set_status([f"Save selection failed: {exc}"])

    def _on_load_selection(_):
        try:
            load_selection()
        except Exception as exc:
            _set_status([f"Load selection failed: {exc}"])

    b_refresh.on_click(_refresh_all)
    b_save_selection.on_click(_on_save_selection)
    b_load_selection.on_click(_on_load_selection)

    _refresh_all()

    ui = W.VBox(
        [
            W.HBox([run_dd, show_ids_cb, autosave_cb, b_refresh, b_save_selection, b_load_selection]),
            entities_sel,
            out,
            refresh_signal,
        ]
    )

    def get_selected() -> list[SessionSelection]:
        return list(_selected)

    def get_selected_entities() -> list[ScopeEntity]:
        return list(_selected_entities)

    def get_entity_snapshot() -> EntitySelectionSnapshot:
        return EntitySelectionSnapshot(
            selected_entities=list(_entity_snapshot.selected_entities),
            entity_to_effective_members={
                str(k): list(map(str, v))
                for k, v in dict(_entity_snapshot.entity_to_effective_members).items()
            },
            expanded_session_keys=list(map(str, _entity_snapshot.expanded_session_keys)),
            key_to_ref=dict(_entity_snapshot.key_to_ref),
            events_index_df=_entity_snapshot.events_index_df.copy(),
        )

    def get_key_to_ref() -> MutableKeyToRef:
        return dict(_key_to_ref)

    def get_events_index_df() -> pd.DataFrame:
        return _events_index_df.copy()

    return {
        "ui": ui,
        "store": store,
        "run_dd": run_dd,
        "entities_sel": entities_sel,
        "show_ids_cb": show_ids_cb,
        "autosave_cb": autosave_cb,
        "refresh_signal": refresh_signal,
        "out": out,
        "get_selected": get_selected,
        "get_selected_entities": get_selected_entities,
        "get_entity_snapshot": get_entity_snapshot,
        "get_key_to_ref": get_key_to_ref,
        "get_events_index_df": get_events_index_df,
        "save_selection": save_selection,
        "load_selection": load_selection,
    }


def attach_refresh(
    sel: Mapping[str, Any],
    rebuild_fns: list[RebuildFn],
) -> RefreshHandle:
    """
    Attach selector observers and call rebuild functions immediately when selection changes.
    """
    run_dd = sel.get("run_dd")
    sessions_sel = sel.get("sessions_sel")
    entities_sel = sel.get("entities_sel")
    show_ids_cb = sel.get("show_ids_cb")
    refresh_signal = sel.get("refresh_signal")

    observed_widgets = [
        w for w in (run_dd, sessions_sel, entities_sel, show_ids_cb, refresh_signal) if w is not None
    ]
    if not observed_widgets:
        raise ValueError("selector handle must include at least one observable selector widget")

    in_fire = False  # re-entrancy guard

    def _fire(*_):
        nonlocal in_fire
        if in_fire:
            return
        in_fire = True
        try:
            for fn in rebuild_fns:
                try:
                    fn()
                except Exception as e:
                    print(f"[attach_refresh] rebuild failed: {e!r}")
        finally:
            in_fire = False

    for w in observed_widgets:
        w.observe(_fire, names="value")

    def detach():
        for w in observed_widgets:
            try:
                w.unobserve(_fire, names="value")
            except Exception:
                pass

    return {"detach": detach, "trigger": _fire}
