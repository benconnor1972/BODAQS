from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Sequence

import ipywidgets as W
import pandas as pd
from IPython.display import display
from ipydatagrid import DataGrid, TextRenderer

from bodaqs_analysis.artifacts import ArtifactStore
from bodaqs_analysis.library.aggregations import (
    AggregationStore,
    CanonicalAggregationStore,
    build_aggregation_catalog_df,
)
from bodaqs_analysis.session_notes import build_session_catalog_df
from bodaqs_analysis.widgets.entity_scope import (
    resolve_event_schema_sets_for_sessions,
    validate_registry_policy_for_sessions,
)
from bodaqs_analysis.widgets.loaders import make_session_loader


_GRID_STYLE = {
    "background_color": "#ffffff",
    "grid_line_color": "#e5e7eb",
    "header_background_color": "#f5f7fa",
    "header_grid_line_color": "#d9dde3",
    "selection_fill_color": "rgba(156, 163, 175, 0.18)",
    "selection_border_color": "#9ca3af",
    "header_selection_fill_color": "rgba(156, 163, 175, 0.18)",
    "header_selection_border_color": "#9ca3af",
}


def _grid_height_px(*, row_count: int, min_rows: int, max_rows: int) -> str:
    visible_rows = max(min_rows, min(max_rows, row_count if row_count > 0 else min_rows))
    return f"{visible_rows * 28 + 36}px"


def _make_grid(
    columns: Sequence[str],
    *,
    width: str = "100%",
    height: str,
    base_column_size: int,
    column_widths: dict[str, int],
    selection_mode: str = "row",
) -> DataGrid:
    return DataGrid(
        pd.DataFrame(columns=list(columns)),
        selection_mode=selection_mode,
        header_visibility="column",
        base_column_size=base_column_size,
        base_row_size=30,
        layout=W.Layout(width=width, height=height, border="1px solid #d1d5db"),
        auto_fit_columns=False,
        column_widths=column_widths,
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
        grid_style=_GRID_STYLE,
    )


def make_aggregation_library_manager(
    *,
    artifacts_dir: str | Path = "artifacts",
    aggregation_store: AggregationStore | None = None,
    rows: int = 12,
    show_ids_default: bool = False,
    auto_display: bool = False,
) -> dict[str, Any]:
    artifact_store = ArtifactStore(Path(artifacts_dir))
    agg_store = aggregation_store or CanonicalAggregationStore(artifact_store=artifact_store)
    try:
        agg_store.load()
    except Exception:
        pass

    w_filter = W.Text(
        value="",
        description="Filter",
        placeholder="Search run/session ids or descriptions",
        layout=W.Layout(width="520px"),
    )
    sessions_sel = W.SelectMultiple(
        options=[],
        value=(),
        rows=rows,
        description="Sessions",
        layout=W.Layout(display="none"),
    )
    session_grid_max_rows = max(8, rows)
    session_grid = _make_grid(
        ["Created", "Run description", "Session description", "Run ID", "Session ID"],
        height=_grid_height_px(row_count=0, min_rows=3, max_rows=session_grid_max_rows),
        base_column_size=160,
        column_widths={
            "Created": 165,
            "Run description": 240,
            "Session description": 280,
            "Run ID": 180,
            "Session ID": 220,
        },
    )

    w_agg_list = W.Dropdown(
        options=[("(No saved aggregations)", "")],
        value="",
        description="Saved agg",
        layout=W.Layout(display="none"),
    )
    agg_grid_max_rows = max(6, rows // 2)
    agg_grid = _make_grid(
        ["Title", "Members", "Missing", "Registry", "Schema", "Updated", "Key", "Note"],
        height=_grid_height_px(row_count=0, min_rows=2, max_rows=agg_grid_max_rows),
        base_column_size=130,
        column_widths={
            "Title": 220,
            "Members": 85,
            "Missing": 85,
            "Registry": 95,
            "Schema": 95,
            "Updated": 170,
            "Key": 240,
            "Note": 260,
        },
    )
    w_title = W.Text(value="", description="Title", layout=W.Layout(width="520px"))
    w_note = W.Text(value="", description="Note", layout=W.Layout(width="520px"))
    w_registry_policy = W.Dropdown(
        options=[("union", "union"), ("intersection", "intersection"), ("strict", "strict")],
        value="union",
        description="Registry",
        layout=W.Layout(width="220px"),
    )
    w_schema_policy = W.Dropdown(
        options=[("union", "union"), ("intersection", "intersection"), ("strict", "strict")],
        value="union",
        description="Schema",
        layout=W.Layout(width="220px"),
    )

    b_refresh = W.Button(description="Refresh")
    b_create = W.Button(description="Create")
    b_update = W.Button(description="Update")
    b_delete = W.Button(description="Delete")
    b_load = W.Button(description="Load")

    out = W.Output(layout=W.Layout(width="1280px"))

    state: Dict[str, Any] = {
        "catalog_df": pd.DataFrame(),
        "label_to_session_key": {},
        "session_key_to_label": {},
        "catalog_agg_df": pd.DataFrame(),
        "agg_key_to_row": {},
        "grid_index_to_label": {},
        "agg_grid_index_to_key": {},
        "updating": False,
        "syncing_session_grid": False,
        "syncing_session_hidden": False,
        "syncing_agg_grid": False,
        "syncing_agg_hidden": False,
    }

    def _set_status(lines: Sequence[str]) -> None:
        with out:
            out.clear_output()
            for line in lines:
                print(line)

    def _refresh_session_options(*_) -> None:
        catalog_df = build_session_catalog_df(artifacts_dir=artifact_store.root)
        state["catalog_df"] = catalog_df

        label_to_session_key: dict[str, str] = {}
        session_key_to_label: dict[str, str] = {}
        options: list[str] = []
        rows_data: list[dict[str, Any]] = []
        filter_text = str(w_filter.value or "").strip().lower()
        label_counts: dict[str, int] = {}

        for _, row in catalog_df.iterrows():
            row_dict = row.to_dict()
            session_key = str(row_dict["session_key"])
            search_blob = " ".join(
                str(value)
                for value in row_dict.values()
                if value is not None and not (isinstance(value, float) and pd.isna(value))
            ).lower()
            if filter_text and filter_text not in search_blob:
                continue
            base_label = session_key
            n = label_counts.get(base_label, 0) + 1
            label_counts[base_label] = n
            unique_label = base_label if n == 1 else f"{base_label} [#{n}]"
            options.append(unique_label)
            label_to_session_key[unique_label] = session_key
            session_key_to_label[session_key] = unique_label
            rows_data.append(
                {
                    "Created": str(row_dict.get("created_at") or ""),
                    "Run description": str(row_dict.get("run_description") or ""),
                    "Session description": str(row_dict.get("session_description") or ""),
                    "Run ID": str(row_dict.get("run_id") or ""),
                    "Session ID": str(row_dict.get("session_id") or ""),
                }
            )

        prev = tuple(map(str, sessions_sel.value or ()))
        sessions_sel.options = options
        sessions_sel.value = tuple(lbl for lbl in prev if lbl in label_to_session_key)
        grid_df = pd.DataFrame.from_records(
            rows_data,
            columns=["Created", "Run description", "Session description", "Run ID", "Session ID"],
        )
        grid_df.index = pd.RangeIndex(start=0, stop=len(grid_df), step=1)
        session_grid.data = grid_df
        session_grid.layout.height = _grid_height_px(
            row_count=len(rows_data),
            min_rows=3,
            max_rows=session_grid_max_rows,
        )
        state["label_to_session_key"] = label_to_session_key
        state["session_key_to_label"] = session_key_to_label
        state["grid_index_to_label"] = {idx: label for idx, label in enumerate(options)}
        _sync_session_grid_from_hidden()

    def _refresh_aggregation_options(*_) -> None:
        try:
            agg_store.load()
        except Exception:
            pass

        catalog_agg_df = build_aggregation_catalog_df(
            aggregation_store=agg_store,
            scope="canonical" if isinstance(agg_store, CanonicalAggregationStore) else "custom",
            artifact_store=artifact_store,
        )
        state["catalog_agg_df"] = catalog_agg_df
        state["agg_key_to_row"] = {}

        if catalog_agg_df.empty:
            w_agg_list.options = [("(No saved aggregations)", "")]
            w_agg_list.value = ""
            agg_grid.data = pd.DataFrame(
                columns=["Title", "Members", "Missing", "Registry", "Schema", "Updated", "Key", "Note"]
            )
            agg_grid.layout.height = _grid_height_px(row_count=0, min_rows=2, max_rows=agg_grid_max_rows)
            state["agg_grid_index_to_key"] = {}
            return

        opts: list[tuple[str, str]] = []
        rows_data: list[dict[str, Any]] = []
        agg_grid_index_to_key: dict[int, str] = {}
        for idx, (_, row) in enumerate(catalog_agg_df.iterrows()):
            row_dict = row.to_dict()
            aggregation_key = str(row_dict["aggregation_key"])
            title = str(row_dict.get("title") or "")
            opts.append((title or aggregation_key, aggregation_key))
            rows_data.append(
                {
                    "Title": title,
                    "Members": int(row_dict.get("n_members") or 0),
                    "Missing": int(row_dict.get("missing_member_count") or 0),
                    "Registry": str(row_dict.get("registry_policy") or ""),
                    "Schema": str(row_dict.get("event_schema_policy") or ""),
                    "Updated": str(row_dict.get("updated_at_utc") or ""),
                    "Key": aggregation_key,
                    "Note": str(row_dict.get("note") or ""),
                }
            )
            agg_grid_index_to_key[idx] = aggregation_key
            state["agg_key_to_row"][aggregation_key] = row_dict
        prev = str(w_agg_list.value or "")
        valid = {value for _, value in opts}
        w_agg_list.options = opts
        w_agg_list.value = prev if prev in valid else opts[0][1]
        grid_df = pd.DataFrame.from_records(
            rows_data,
            columns=["Title", "Members", "Missing", "Registry", "Schema", "Updated", "Key", "Note"],
        )
        grid_df.index = pd.RangeIndex(start=0, stop=len(grid_df), step=1)
        agg_grid.data = grid_df
        agg_grid.layout.height = _grid_height_px(
            row_count=len(rows_data),
            min_rows=2,
            max_rows=agg_grid_max_rows,
        )
        state["agg_grid_index_to_key"] = agg_grid_index_to_key
        _sync_agg_grid_from_hidden()

    def _refresh_all(*_) -> None:
        _refresh_session_options()
        _refresh_aggregation_options()

    def _selected_session_labels_from_grid() -> tuple[str, ...]:
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
                label = state["grid_index_to_label"].get(int(visible_df.index[row_pos]))
                if not label or label in seen:
                    continue
                seen.add(label)
                labels.append(label)
        return tuple(labels)

    def _sync_session_hidden_from_grid(*_) -> None:
        if state["syncing_session_grid"]:
            return
        state["syncing_session_hidden"] = True
        try:
            sessions_sel.value = _selected_session_labels_from_grid()
        finally:
            state["syncing_session_hidden"] = False

    def _sync_session_grid_from_hidden(*_) -> None:
        if state["syncing_session_hidden"]:
            return
        label_set = set(map(str, sessions_sel.value or ()))
        visible_df = session_grid.get_visible_data()
        state["syncing_session_grid"] = True
        try:
            session_grid.clear_selection()
            if visible_df.empty or not label_set:
                return
            last_col = max(0, len(visible_df.columns) - 1)
            for row_pos in range(len(visible_df.index)):
                label = state["grid_index_to_label"].get(int(visible_df.index[row_pos]))
                if label in label_set:
                    session_grid.select(row_pos, 0, row_pos, last_col, clear_mode="none")
        finally:
            state["syncing_session_grid"] = False

    def _selected_agg_key_from_grid() -> str:
        visible_df = agg_grid.get_visible_data()
        for rect in list(agg_grid.selections or []):
            row_start = int(rect.get("r1", -1))
            row_end = int(rect.get("r2", -1))
            if row_start < 0 or row_end < row_start:
                continue
            for row_pos in range(row_start, row_end + 1):
                if row_pos < 0 or row_pos >= len(visible_df.index):
                    continue
                key = state["agg_grid_index_to_key"].get(int(visible_df.index[row_pos]))
                if key:
                    return key
        return ""

    def _sync_agg_hidden_from_grid(*_) -> None:
        if state["syncing_agg_grid"]:
            return
        selected_key = _selected_agg_key_from_grid()
        if not selected_key:
            return
        state["syncing_agg_hidden"] = True
        try:
            w_agg_list.value = selected_key
        finally:
            state["syncing_agg_hidden"] = False

    def _sync_agg_grid_from_hidden(*_) -> None:
        if state["syncing_agg_hidden"]:
            return
        selected_key = str(w_agg_list.value or "")
        visible_df = agg_grid.get_visible_data()
        state["syncing_agg_grid"] = True
        try:
            agg_grid.clear_selection()
            if visible_df.empty or not selected_key:
                return
            last_col = max(0, len(visible_df.columns) - 1)
            for row_pos in range(len(visible_df.index)):
                key = state["agg_grid_index_to_key"].get(int(visible_df.index[row_pos]))
                if key == selected_key:
                    agg_grid.select(row_pos, 0, row_pos, last_col, clear_mode="all")
                    return
        finally:
            state["syncing_agg_grid"] = False

    def _selected_session_keys() -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()
        for label in sessions_sel.value:
            session_key = state["label_to_session_key"].get(str(label))
            if not session_key or session_key in seen:
                continue
            seen.add(session_key)
            selected.append(session_key)
        return selected

    def _validate_members(
        *,
        member_session_keys: Sequence[str],
        registry_policy: str,
        event_schema_policy: str,
    ) -> None:
        if not member_session_keys:
            raise ValueError("Select at least one physical session before saving an aggregation.")

        key_to_ref = {
            str(row["session_key"]): (str(row["run_id"]), str(row["session_id"]))
            for _, row in state["catalog_df"].iterrows()
        }
        missing = [session_key for session_key in member_session_keys if session_key not in key_to_ref]
        if missing:
            raise ValueError(f"Aggregation includes unknown sessions: {', '.join(missing[:3])}")

        session_loader = make_session_loader(store=artifact_store, key_to_ref=key_to_ref)
        validate_registry_policy_for_sessions(
            session_keys=member_session_keys,
            session_loader=session_loader,
            policy=registry_policy,
        )
        resolve_event_schema_sets_for_sessions(
            session_keys=member_session_keys,
            key_to_ref=key_to_ref,
            store=artifact_store,
            session_loader=session_loader,
            policy=event_schema_policy,
        )

    def _on_select(change):
        if state["updating"]:
            return
        key = str(change.get("new") or "")
        if not key:
            return
        agg = agg_store.get(key)
        if agg is None:
            return

        state["updating"] = True
        try:
            w_title.value = agg.title
            w_note.value = agg.note or ""
            w_registry_policy.value = agg.registry_policy
            w_schema_policy.value = agg.event_schema_policy
        finally:
            state["updating"] = False

    def _on_load(_):
        key = str(w_agg_list.value or "")
        if not key:
            _set_status(["Select a saved aggregation to load."])
            return
        agg = agg_store.get(key)
        if agg is None:
            _set_status([f"Aggregation not found: {key}"])
            return
        labels = [
            state["session_key_to_label"][session_key]
            for session_key in agg.member_session_keys
            if session_key in state["session_key_to_label"]
        ]
        sessions_sel.value = tuple(labels)
        _set_status([f"Loaded {len(labels)} sessions from {key}."])

    def _on_create(_):
        members = _selected_session_keys()
        title = str(w_title.value or "").strip()
        note = str(w_note.value or "").strip() or None
        registry_policy = str(w_registry_policy.value or "union")
        schema_policy = str(w_schema_policy.value or "union")
        try:
            _validate_members(
                member_session_keys=members,
                registry_policy=registry_policy,
                event_schema_policy=schema_policy,
            )
            created = agg_store.create(
                title=(title or f"Aggregation ({len(members)} sessions)"),
                member_session_keys=members,
                registry_policy=registry_policy,
                event_schema_policy=schema_policy,
                note=note,
            )
            agg_store.save()
            _refresh_aggregation_options()
            _set_status([f"Created aggregation {created.aggregation_key}."])
        except Exception as exc:
            _set_status([f"Create failed: {exc}"])

    def _on_update(_):
        key = str(w_agg_list.value or "")
        if not key:
            _set_status(["Select a saved aggregation to update."])
            return
        members = _selected_session_keys()
        title = str(w_title.value or "").strip()
        note = str(w_note.value or "").strip() or None
        registry_policy = str(w_registry_policy.value or "union")
        schema_policy = str(w_schema_policy.value or "union")
        if not title:
            _set_status(["Aggregation title is required for update."])
            return
        try:
            _validate_members(
                member_session_keys=members,
                registry_policy=registry_policy,
                event_schema_policy=schema_policy,
            )
            agg_store.update(
                key,
                patch={
                    "title": title,
                    "member_session_keys": members,
                    "registry_policy": registry_policy,
                    "event_schema_policy": schema_policy,
                    "note": note,
                },
            )
            agg_store.save()
            _refresh_aggregation_options()
            _set_status([f"Updated aggregation {key}."])
        except Exception as exc:
            _set_status([f"Update failed: {exc}"])

    def _on_delete(_):
        key = str(w_agg_list.value or "")
        if not key:
            _set_status(["Select a saved aggregation to delete."])
            return
        try:
            deleted = agg_store.delete(key)
            if deleted:
                agg_store.save()
            _refresh_aggregation_options()
            _set_status([f"Deleted aggregation {key}." if deleted else "Aggregation not found."])
        except Exception as exc:
            _set_status([f"Delete failed: {exc}"])

    w_filter.observe(_refresh_session_options, names="value")
    session_grid.observe(_sync_session_hidden_from_grid, names="selections")
    sessions_sel.observe(_sync_session_grid_from_hidden, names="value")
    agg_grid.observe(_sync_agg_hidden_from_grid, names="selections")
    w_agg_list.observe(_on_select, names="value")
    w_agg_list.observe(_sync_agg_grid_from_hidden, names="value")
    b_refresh.on_click(_refresh_all)
    b_load.on_click(_on_load)
    b_create.on_click(_on_create)
    b_update.on_click(_on_update)
    b_delete.on_click(_on_delete)

    _refresh_all()

    ui = W.VBox(
        [
            W.HBox([w_filter, b_refresh]),
            session_grid,
            sessions_sel,
            W.VBox(
                [
                    W.HTML("<b>Canonical Aggregations</b>"),
                    W.HBox([b_load]),
                    agg_grid,
                    w_agg_list,
                    W.HBox([w_title, w_note]),
                    W.HBox([w_registry_policy, w_schema_policy]),
                    W.HBox([b_create, b_update, b_delete]),
                ]
            ),
            out,
        ]
    )

    handle = {
        "ui": ui,
        "store": artifact_store,
        "aggregation_store": agg_store,
        "sessions_sel": sessions_sel,
        "session_grid": session_grid,
        "show_ids_cb": None,
        "out": out,
        "refresh": _refresh_all,
        "controls": {
            "filter": w_filter,
            "saved_aggregations": w_agg_list,
            "saved_aggregation_grid": agg_grid,
            "title": w_title,
            "note": w_note,
            "registry_policy": w_registry_policy,
            "event_schema_policy": w_schema_policy,
            "load": b_load,
            "create": b_create,
            "update": b_update,
            "delete": b_delete,
        },
        "state": state,
    }
    if auto_display:
        display(ui)
    return handle
