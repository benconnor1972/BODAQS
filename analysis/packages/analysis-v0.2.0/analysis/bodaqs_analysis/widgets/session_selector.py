# bodaqs_analysis/widgets/session_selector.py

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import ipywidgets as W
import pandas as pd
from ipydatagrid import DataGrid, TextRenderer

from bodaqs_analysis.artifacts import ArtifactStore, list_runs, list_sessions
from bodaqs_analysis.library.aggregations import AggregationStore, make_default_aggregation_store
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


def make_session_key(run_id: str, session_id: str) -> SessionKey:
    return f"{run_id}::{session_id}"


def _events_index_df_from_key_to_ref(key_to_ref: Mapping[str, tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {SESSION_KEY_COL: k, RUN_ID_COL: rid, SESSION_ID_COL: sid}
            for k, (rid, sid) in key_to_ref.items()
        ],
        columns=[SESSION_KEY_COL, RUN_ID_COL, SESSION_ID_COL],
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
    return run_desc


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
    aggregation_store: AggregationStore | None = None,
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
    agg_store = aggregation_store or make_default_aggregation_store(artifact_store=store)
    try:
        agg_store.load()
    except Exception:
        pass

    run_options = _build_run_options(store=store, show_ids=True)
    run_dd = W.Dropdown(
        options=run_options,
        value="__ALL__",
        description="Run",
        layout=W.Layout(display="none"),
    )

    sessions_sel = W.SelectMultiple(
        options=[],
        value=(),
        layout=W.Layout(display="none"),
    )
    session_grid = DataGrid(
        pd.DataFrame(
            columns=[
                "Created",
                "Run description",
                "Session description",
                "Run ID",
                "Session ID",
            ]
        ),
        selection_mode="row",
        header_visibility="column",
        base_column_size=150,
        base_row_size=30,
        layout=W.Layout(width="100%", height=f"{max(8, rows) * 28 + 36}px"),
        auto_fit_columns=False,
        column_widths={
            "Created": 165,
            "Run description": 240,
            "Session description": 280,
            "Run ID": 180,
            "Session ID": 220,
        },
        default_renderer=TextRenderer(
            font="13px Segoe UI, Tahoma, Arial, sans-serif",
            vertical_alignment="center",
            background_color="#ffffff",
        ),
        header_renderer=TextRenderer(
            font="600 12px Segoe UI, Tahoma, Arial, sans-serif",
            vertical_alignment="center",
            background_color="#f5f7fa",
        ),
        grid_style={
            "background_color": "#ffffff",
            "grid_line_color": "#e5e7eb",
            "header_background_color": "#f5f7fa",
            "header_grid_line_color": "#d9dde3",
            "selection_fill_color": "rgba(156, 163, 175, 0.18)",
            "selection_border_color": "#9ca3af",
            "header_selection_fill_color": "rgba(156, 163, 175, 0.18)",
            "header_selection_border_color": "#9ca3af",
        },
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
    _grid_index_to_label: dict[int, str] = {}
    _state: Dict[str, Any] = {"updating": False, "syncing_grid": False, "syncing_hidden": False}

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
                    show_ids=True,
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
        nonlocal _label_to_sel, _session_key_to_label, _all_key_to_ref_cache, _grid_index_to_label

        run_dd.options = _build_run_options(store=store, show_ids=True)
        run_dd.value = "__ALL__"

        _all_key_to_ref_cache = _all_key_to_ref(store)

        options, _label_to_sel, _session_key_to_label = _build_session_index(
            store=store,
            selected_run_id="__ALL__",
            show_ids=True,
        )
        prev = tuple(map(str, sessions_sel.value or ()))
        sessions_sel.options = options
        kept = tuple([lbl for lbl in prev if lbl in _label_to_sel])
        sessions_sel.value = kept if kept else ()
        _grid_index_to_label = {idx: label for idx, label in enumerate(options)}

        rows_data: list[dict[str, Any]] = []
        for label in options:
            selected = _label_to_sel.get(label)
            if not selected:
                continue
            run_id = str(selected["run_id"])
            session_id = str(selected["session_id"])
            run_meta = _get_run_meta(store, run_id)
            session_desc = _get_session_desc(store, run_id, session_id)
            rows_data.append(
                {
                    "Created": run_meta["created_at"],
                    "Run description": run_meta["description"],
                    "Session description": session_desc,
                    "Run ID": run_id,
                    "Session ID": session_id,
                }
            )
        grid_df = pd.DataFrame.from_records(
            rows_data,
            columns=["Created", "Run description", "Session description", "Run ID", "Session ID"],
        )
        grid_df.index = pd.RangeIndex(start=0, stop=len(grid_df), step=1)
        session_grid.data = grid_df
        _sync_grid_from_hidden()

        _refresh_aggregation_options()

    def _selected_labels_from_grid() -> tuple[str, ...]:
        labels: list[str] = []
        seen: set[str] = set()
        visible_df = session_grid.get_visible_data()
        for rect in list(session_grid.selections or []):
            row_start = int(rect.get("r1", -1))
            row_end = int(rect.get("r2", -1))
            if row_start < 0 or row_end < row_start:
                continue
            for row_pos in range(row_start, row_end + 1):
                if row_pos < 0 or row_pos >= len(visible_df.index):
                    continue
                label = _grid_index_to_label.get(int(visible_df.index[row_pos]))
                if not label or label in seen:
                    continue
                seen.add(label)
                labels.append(label)
        return tuple(labels)

    def _sync_hidden_from_grid(*_) -> None:
        if _state["syncing_grid"]:
            return
        labels = _selected_labels_from_grid()
        _state["syncing_hidden"] = True
        try:
            sessions_sel.value = labels
        finally:
            _state["syncing_hidden"] = False

    def _sync_grid_from_hidden(*_) -> None:
        if _state["syncing_hidden"]:
            return
        label_set = set(map(str, sessions_sel.value or ()))
        visible_df = session_grid.get_visible_data()
        _state["syncing_grid"] = True
        try:
            session_grid.clear_selection()
            if visible_df.empty or not label_set:
                return
            last_col = max(0, len(visible_df.columns) - 1)
            for row_pos in range(len(visible_df.index)):
                label = _grid_index_to_label.get(int(visible_df.index[row_pos]))
                if label in label_set:
                    session_grid.select(row_pos, 0, row_pos, last_col, clear_mode="none")
        finally:
            _state["syncing_grid"] = False

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

    session_grid.observe(_sync_hidden_from_grid, names="selections")
    sessions_sel.observe(_sync_grid_from_hidden, names="value")
    w_agg_list.observe(_on_agg_select, names="value")

    b_refresh.on_click(_refresh_sessions)
    b_agg_create.on_click(_on_agg_create)
    b_agg_update.on_click(_on_agg_update)
    b_agg_delete.on_click(_on_agg_delete)
    b_agg_load.on_click(_on_agg_load)

    _refresh_sessions()

    ui = W.VBox(
        [
            W.HBox([b_refresh]),
            session_grid,
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
        "aggregation_store": agg_store,
        "run_dd": run_dd,
        "show_ids_cb": None,
        "session_grid": session_grid,
        "sessions_sel": sessions_sel,
        "out": out,
        "refresh": _refresh_sessions,
    }


def make_session_selector(
    *,
    artifacts_dir: str | Path = "artifacts",
    aggregation_store: AggregationStore | None = None,
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
    agg_store = aggregation_store or make_default_aggregation_store(artifact_store=store)
    try:
        agg_store.load()
    except Exception:
        pass

    run_options = _build_run_options(store=store, show_ids=True)
    run_dd = W.Dropdown(
        options=run_options,
        value="__ALL__",
        description="Run",
        layout=W.Layout(display="none"),
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
        layout=W.Layout(display="none"),
    )
    entity_grid = DataGrid(
        pd.DataFrame(
            columns=[
                "Type",
                "Created",
                "Run description",
                "Session / aggregation",
                "Run ID",
                "Session ID / key",
                "Members",
            ]
        ),
        selection_mode="row",
        header_visibility="column",
        base_column_size=140,
        base_row_size=30,
        layout=W.Layout(width="100%", height=f"{max(8, rows) * 28 + 36}px"),
        auto_fit_columns=False,
        column_widths={
            "Type": 110,
            "Created": 165,
            "Run description": 220,
            "Session / aggregation": 280,
            "Run ID": 180,
            "Session ID / key": 220,
            "Members": 90,
        },
        default_renderer=TextRenderer(
            font="13px Segoe UI, Tahoma, Arial, sans-serif",
            vertical_alignment="center",
            background_color="#ffffff",
        ),
        header_renderer=TextRenderer(
            font="600 12px Segoe UI, Tahoma, Arial, sans-serif",
            vertical_alignment="center",
            background_color="#f5f7fa",
        ),
        grid_style={
            "background_color": "#ffffff",
            "grid_line_color": "#e5e7eb",
            "header_background_color": "#f5f7fa",
            "header_grid_line_color": "#d9dde3",
            "selection_fill_color": "rgba(156, 163, 175, 0.18)",
            "selection_border_color": "#9ca3af",
            "header_selection_fill_color": "rgba(156, 163, 175, 0.18)",
            "header_selection_border_color": "#9ca3af",
        },
    )

    out = W.Output(layout=W.Layout(width="1240px"))

    _entity_label_to_entity: dict[str, ScopeEntity] = {}
    _entity_key_to_label: dict[str, str] = {}
    _grid_index_to_label: dict[int, str] = {}
    _grid_df = pd.DataFrame()
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
    _ui_state: dict[str, bool] = {"syncing_grid": False, "syncing_hidden": False}

    def _set_status(lines: Sequence[str]) -> None:
        with out:
            out.clear_output()
            for line in lines:
                print(line)

    def _refresh_scope_sources() -> None:
        nonlocal _all_key_to_ref_cache, _events_index_df_all
        _all_key_to_ref_cache = _all_key_to_ref(store)
        _events_index_df_all = _events_index_df_from_key_to_ref(_all_key_to_ref_cache)

    def _selected_labels_from_grid() -> tuple[str, ...]:
        labels: list[str] = []
        seen: set[str] = set()
        visible_df = entity_grid.get_visible_data()
        for rect in list(entity_grid.selections or []):
            row_start = int(rect.get("r1", -1))
            row_end = int(rect.get("r2", -1))
            if row_start < 0 or row_end < row_start:
                continue
            for row_pos in range(row_start, row_end + 1):
                if row_pos < 0 or row_pos >= len(visible_df.index):
                    continue
                label = _grid_index_to_label.get(int(visible_df.index[row_pos]))
                if not label or label in seen:
                    continue
                seen.add(label)
                labels.append(label)
        return tuple(labels)

    def _sync_hidden_from_grid(*_) -> None:
        if _ui_state["syncing_grid"]:
            return
        labels = _selected_labels_from_grid()
        _ui_state["syncing_hidden"] = True
        try:
            entities_sel.value = labels
        finally:
            _ui_state["syncing_hidden"] = False

    def _sync_grid_from_hidden(*_) -> None:
        if _ui_state["syncing_hidden"]:
            return
        label_set = set(map(str, entities_sel.value or ()))
        visible_df = entity_grid.get_visible_data()
        _ui_state["syncing_grid"] = True
        try:
            entity_grid.clear_selection()
            if visible_df.empty or not label_set:
                return
            last_col = max(0, len(visible_df.columns) - 1)
            for row_pos in range(len(visible_df.index)):
                label = _grid_index_to_label.get(int(visible_df.index[row_pos]))
                if label in label_set:
                    entity_grid.select(row_pos, 0, row_pos, last_col, clear_mode="none")
        finally:
            _ui_state["syncing_grid"] = False

    def _rebuild_entity_options(*_) -> None:
        nonlocal _entity_label_to_entity, _entity_key_to_label, _grid_index_to_label, _grid_df

        run_dd.options = _build_run_options(store=store, show_ids=True)
        run_dd.value = "__ALL__"

        prev_keys = {str(e.entity_key) for e in _selected_entities}
        try:
            agg_store.load()
        except Exception:
            pass

        _, _, session_key_to_label = _build_session_index(
            store=store,
            selected_run_id="__ALL__",
            show_ids=True,
        )

        label_counts: dict[str, int] = {}
        options: list[str] = []
        mapping: dict[str, ScopeEntity] = {}
        rows_data: list[dict[str, Any]] = []

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
            run_id, session_id = _all_key_to_ref_cache.get(str(session_key), ("", ""))
            run_meta = _get_run_meta(store, str(run_id)) if run_id else {"created_at": "", "description": ""}
            session_desc = _get_session_desc(store, str(run_id), str(session_id)) if run_id and session_id else ""
            rows_data.append(
                {
                    "Type": "Session",
                    "Created": run_meta["created_at"],
                    "Run description": run_meta["description"],
                    "Session / aggregation": session_desc,
                    "Run ID": str(run_id),
                    "Session ID / key": str(session_id),
                    "Members": 1,
                }
            )

        for agg in agg_store.list():
            base = _format_aggregation_label(
                aggregation_key=str(agg.aggregation_key),
                title=str(agg.title),
                n_members=len(agg.member_session_keys),
                show_ids=True,
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
            rows_data.append(
                {
                    "Type": "Aggregation",
                    "Created": "",
                    "Run description": "",
                    "Session / aggregation": str(agg.title or agg.aggregation_key),
                    "Run ID": "",
                    "Session ID / key": str(agg.aggregation_key),
                    "Members": len(agg.member_session_keys),
                }
            )

        _entity_label_to_entity = mapping
        _entity_key_to_label = {
            str(entity.entity_key): label for label, entity in _entity_label_to_entity.items()
        }
        entities_sel.options = options
        _grid_index_to_label = {idx: label for idx, label in enumerate(options)}
        _grid_df = pd.DataFrame.from_records(
            rows_data,
            columns=[
                "Type",
                "Created",
                "Run description",
                "Session / aggregation",
                "Run ID",
                "Session ID / key",
                "Members",
            ],
        )
        _grid_df.index = pd.RangeIndex(start=0, stop=len(_grid_df), step=1)
        entity_grid.data = _grid_df

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
        _sync_grid_from_hidden()

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
            match = _entity_key_to_label.get(str(entity_key))
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
        result = load_entity_scope_selection(
            artifacts_dir=store.root,
            aggregation_store=agg_store,
            strict=False,
        )
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
    entity_grid.observe(_sync_hidden_from_grid, names="selections")
    entities_sel.observe(_sync_grid_from_hidden, names="value")
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
            W.HBox([autosave_cb, b_refresh, b_save_selection, b_load_selection]),
            entity_grid,
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
        "aggregation_store": agg_store,
        "run_dd": run_dd,
        "entity_grid": entity_grid,
        "entities_sel": entities_sel,
        "show_ids_cb": None,
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
