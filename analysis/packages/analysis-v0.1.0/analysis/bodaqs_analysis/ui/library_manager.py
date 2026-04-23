from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import ipywidgets as W
import pandas as pd
from IPython.display import display
from ipydatagrid import DataGrid, TextRenderer

from bodaqs_analysis.artifacts import (
    ArtifactStore,
    set_run_description,
    set_session_description,
)
from bodaqs_analysis.library.aggregations import (
    AggregationStore,
    make_default_aggregation_store,
)
from bodaqs_analysis.session_notes import (
    CatalogProjectionConfig,
    SessionNoteDocument,
    SessionNoteFieldDef,
    SessionNoteStore,
    SessionNoteTemplate,
    SessionNoteTemplateStore,
    build_session_catalog_df,
)
from bodaqs_analysis.ui.aggregation_manager import make_aggregation_library_manager


DESCRIPTION_LABEL_WIDTH = "120px"
NOTE_LABEL_WIDTH = "120px"
NOTE_INPUT_WIDTH = "520px"


def _read_json_safe(store: ArtifactStore, path: Path) -> dict[str, Any]:
    try:
        return store.read_json(path)
    except Exception:
        return {}

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
) -> DataGrid:
    return DataGrid(
        pd.DataFrame(columns=list(columns)),
        selection_mode="row",
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


def _template_label(template: SessionNoteTemplate) -> str:
    return f"{template.title} [{template.template_id}@{template.template_version}]"


def _coerce_text_value(raw: str) -> str | None:
    text = str(raw or "").strip()
    return text or None


def _field_label(field: SessionNoteFieldDef) -> str:
    return field.label


def _make_field_widget(field: SessionNoteFieldDef) -> W.Widget:
    style = {"description_width": NOTE_LABEL_WIDTH}
    layout = W.Layout(width=NOTE_INPUT_WIDTH)
    description = _field_label(field)
    if field.field_type == "bool":
        return W.Checkbox(
            value=bool(field.default) if field.default is not None else False,
            description=description,
            indent=False,
            layout=layout,
            style=style,
        )
    if field.field_type == "enum":
        options: list[tuple[str, str | None]] = []
        if not field.required:
            options.append(("(blank)", None))
        options.extend((option, option) for option in field.enum_options)
        value = field.default if field.default in field.enum_options else None
        if value is None and field.required and field.enum_options:
            value = field.enum_options[0]
        return W.Dropdown(
            options=options,
            value=value,
            description=description,
            layout=layout,
            style=style,
        )
    if field.field_type == "multi_enum":
        return W.SelectMultiple(
            options=list(field.enum_options),
            value=tuple(field.default or ()),
            description=description,
            rows=min(max(len(field.enum_options), 2), 6),
            layout=layout,
            style=style,
        )
    if field.field_type == "text":
        return W.Textarea(
            value=str(field.default or ""),
            description=description,
            layout=W.Layout(width="520px", height="90px"),
            style=style,
        )
    return W.Text(
        value="" if field.default is None else str(field.default),
        description=description,
        layout=layout,
        style=style,
    )


def _widget_value(widget: W.Widget, field: SessionNoteFieldDef) -> Any:
    if field.field_type == "bool":
        return bool(getattr(widget, "value", False))
    if field.field_type == "multi_enum":
        return list(map(str, getattr(widget, "value", ()) or ()))
    if field.field_type == "enum":
        value = getattr(widget, "value", None)
        return None if value in (None, "") else str(value)

    text = str(getattr(widget, "value", "") or "").strip()
    if not text:
        return None
    if field.field_type in {"string", "text", "date"}:
        return text
    if field.field_type == "int":
        return int(text)
    if field.field_type == "float":
        return float(text)
    return text


def _set_widget_value(widget: W.Widget, field: SessionNoteFieldDef, value: Any) -> None:
    if field.field_type == "bool":
        widget.value = bool(value) if value is not None else False
        return
    if field.field_type == "multi_enum":
        widget.value = tuple(value or ())
        return
    if field.field_type == "enum":
        normalized = None if value in (None, "") else str(value)
        valid_values = {option[1] for option in getattr(widget, "options", ())}
        if normalized not in valid_values:
            if not field.required and None in valid_values:
                normalized = None
            elif field.enum_options:
                normalized = field.enum_options[0]
        widget.value = normalized
        return
    widget.value = "" if value is None else str(value)


def _blank_field_value(field: SessionNoteFieldDef) -> Any:
    if field.field_type == "bool":
        return False
    if field.field_type == "multi_enum":
        return ()
    return None


def make_library_manager(
    *,
    artifacts_dir: str | Path = "artifacts",
    template_root: str | Path | None = None,
    aggregation_store: AggregationStore | None = None,
    projection_configs: Sequence[CatalogProjectionConfig] = (),
    rows: int = 14,
    show_ids_default: bool = False,
    auto_display: bool = False,
) -> dict[str, Any]:
    artifact_store = ArtifactStore(Path(artifacts_dir))
    template_store = SessionNoteTemplateStore(template_root)
    note_store = SessionNoteStore(store=artifact_store, template_store=template_store)
    agg_store = aggregation_store or make_default_aggregation_store(artifact_store=artifact_store)

    w_filter = W.Text(
        value="",
        description="Filter",
        placeholder="Search ids, descriptions, or projected note fields",
        layout=W.Layout(width="520px"),
    )
    b_refresh = W.Button(description="Refresh")
    sessions_sel = W.SelectMultiple(
        options=[],
        value=(),
        rows=rows,
        description="Sessions",
        layout=W.Layout(display="none"),
    )
    session_grid_max_rows = max(8, rows)
    session_grid = _make_grid(
        [
            "Created",
            "Run description",
            "Session / aggregation",
            "Projection status",
            "Run ID",
            "Session ID",
        ],
        height=_grid_height_px(row_count=0, min_rows=3, max_rows=session_grid_max_rows),
        base_column_size=155,
        column_widths={
            "Created": 165,
            "Run description": 220,
            "Session / aggregation": 250,
            "Projection status": 130,
            "Run ID": 180,
            "Session ID": 220,
        },
    )

    w_run_desc = W.Textarea(
        value="",
        description="Run desc",
        layout=W.Layout(width="520px", height="70px"),
        style={"description_width": DESCRIPTION_LABEL_WIDTH},
    )
    w_session_desc = W.Textarea(
        value="",
        description="Session desc",
        layout=W.Layout(width="520px", height="70px"),
        style={"description_width": DESCRIPTION_LABEL_WIDTH},
    )
    b_save_desc = W.Button(
        description="Save descriptions",
        layout=W.Layout(margin=f"0 0 0 {DESCRIPTION_LABEL_WIDTH}"),
    )

    templates = template_store.list_templates()
    template_options = [(_template_label(t), f"{t.template_id}@{t.template_version}") for t in templates]
    w_template = W.Dropdown(
        options=template_options or [("(No templates found)", "")],
        value=(template_options[0][1] if template_options else ""),
        description="Template",
        layout=W.Layout(width=NOTE_INPUT_WIDTH),
        style={"description_width": NOTE_LABEL_WIDTH},
    )
    b_load_note = W.Button(description="Load note")
    b_new_note = W.Button(description="New from template")
    b_save_note = W.Button(description="Save note")
    w_note_title = W.Text(
        value="",
        description="Note title",
        layout=W.Layout(width=NOTE_INPUT_WIDTH),
        style={"description_width": NOTE_LABEL_WIDTH},
    )
    w_custom_json = W.Textarea(
        value="{}",
        description="Custom",
        layout=W.Layout(width=NOTE_INPUT_WIDTH, height="90px"),
        style={"description_width": NOTE_LABEL_WIDTH},
    )
    w_free_text = W.Textarea(
        value="",
        description="Notes",
        layout=W.Layout(width=NOTE_INPUT_WIDTH, height="120px"),
        style={"description_width": NOTE_LABEL_WIDTH},
    )
    metadata_html = W.HTML()
    fields_box = W.VBox()
    save_confirm_html = W.HTML()
    b_confirm_save_note = W.Button(description="Confirm save", button_style="warning")
    b_cancel_save_note = W.Button(description="Cancel")
    save_confirm_box = W.VBox(
        [
            save_confirm_html,
            W.HBox([b_confirm_save_note, b_cancel_save_note]),
        ],
        layout=W.Layout(
            display="none",
            width=NOTE_INPUT_WIDTH,
            border="1px solid #f59e0b",
            padding="8px",
            margin=f"0 0 0 {NOTE_LABEL_WIDTH}",
        ),
    )
    status_out = W.Output(layout=W.Layout(width="100%"))

    run_manifest_out = W.Output(layout=W.Layout(width="100%", max_height="240px", overflow="auto"))
    session_manifest_out = W.Output(layout=W.Layout(width="100%", max_height="240px", overflow="auto"))
    session_meta_out = W.Output(layout=W.Layout(width="100%", max_height="320px", overflow="auto"))
    details = W.Accordion(children=[run_manifest_out, session_manifest_out, session_meta_out])
    details.set_title(0, "Run manifest")
    details.set_title(1, "Session manifest")
    details.set_title(2, "Session meta")

    aggregation_manager = make_aggregation_library_manager(
        artifacts_dir=artifact_store.root,
        aggregation_store=agg_store,
        auto_display=False,
    )

    state: Dict[str, Any] = {
        "catalog_df": pd.DataFrame(),
        "label_to_session_key": {},
        "session_key_to_row": {},
        "grid_index_to_label": {},
        "current_note": None,
        "current_template": None,
        "field_defs": {},
        "field_widgets": {},
        "template_errors": {},
        "updating": False,
        "syncing_grid": False,
        "syncing_hidden": False,
        "pending_note_save_session_keys": (),
        "editor_staged": False,
        "editor_source_session_key": None,
    }

    def _status(lines: Sequence[str]) -> None:
        with status_out:
            status_out.clear_output()
            for line in lines:
                print(line)

    def _clear_save_confirmation() -> None:
        state["pending_note_save_session_keys"] = ()
        save_confirm_html.value = ""
        save_confirm_box.layout.display = "none"

    def _show_save_confirmation(lines: Sequence[str], session_keys: Sequence[str]) -> None:
        html_lines = [html.escape(str(line)) for line in lines]
        save_confirm_html.value = (
            "<div style='font-size:0.95em;line-height:1.45'>"
            + "<br>".join(html_lines)
            + "</div>"
        )
        state["pending_note_save_session_keys"] = tuple(map(str, session_keys))
        save_confirm_box.layout.display = "flex"

    def _rows_from_session_keys(session_keys: Sequence[str]) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        for session_key in session_keys:
            key = str(session_key)
            if not key or key in seen:
                continue
            row = state["session_key_to_row"].get(key)
            if row is None:
                continue
            seen.add(key)
            rows.append(row)
        return rows

    def _selected_session_keys() -> tuple[str, ...]:
        keys: list[str] = []
        seen: set[str] = set()
        for label in tuple(map(str, sessions_sel.value or ())):
            key = state["label_to_session_key"].get(label)
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)
        return tuple(keys)

    def _selected_rows() -> list[Mapping[str, Any]]:
        return _rows_from_session_keys(_selected_session_keys())

    def _selected_row() -> Mapping[str, Any] | None:
        rows = _selected_rows()
        if not rows:
            return None
        return rows[0]

    def _editor_source_row() -> Mapping[str, Any] | None:
        session_key = str(state.get("editor_source_session_key") or "")
        if session_key:
            row = state["session_key_to_row"].get(session_key)
            if row is not None:
                return row
        return _selected_row()

    def _selected_ids() -> tuple[str, str] | None:
        row = _selected_row()
        if not row:
            return None
        return str(row["run_id"]), str(row["session_id"])

    def _refresh_session_options(*_) -> None:
        catalog_df = build_session_catalog_df(
            artifacts_dir=artifact_store.root,
            template_root=template_store.root,
            projection_configs=projection_configs,
        )
        state["catalog_df"] = catalog_df

        label_to_session_key: dict[str, str] = {}
        session_key_to_row: dict[str, Mapping[str, Any]] = {}
        options: list[str] = []
        rows_data: list[dict[str, Any]] = []
        filter_text = str(w_filter.value or "").strip().lower()
        label_counts: dict[str, int] = {}

        for _, row in catalog_df.iterrows():
            row_dict = row.to_dict()
            search_blob = " ".join(
                str(value)
                for value in row_dict.values()
                if value is not None and not (isinstance(value, float) and pd.isna(value))
            ).lower()
            if filter_text and filter_text not in search_blob:
                continue
            base_label = str(row_dict["session_key"])
            n = label_counts.get(base_label, 0) + 1
            label_counts[base_label] = n
            unique_label = base_label if n == 1 else f"{base_label} [#{n}]"
            session_key = str(row_dict["session_key"])
            options.append(unique_label)
            label_to_session_key[unique_label] = session_key
            session_key_to_row[session_key] = row_dict
            rows_data.append(
                {
                    "Created": str(row_dict.get("created_at") or ""),
                    "Run description": str(row_dict.get("run_description") or ""),
                    "Session / aggregation": str(row_dict.get("session_description") or ""),
                    "Projection status": str(row_dict.get("projection_status") or ""),
                    "Run ID": str(row_dict.get("run_id") or ""),
                    "Session ID": str(row_dict.get("session_id") or ""),
                }
            )

        previous = tuple(map(str, sessions_sel.value or ()))
        sessions_sel.options = options
        kept = tuple(label for label in previous if label in label_to_session_key)
        sessions_sel.value = kept if kept else ((options[0],) if options else ())
        grid_df = pd.DataFrame.from_records(
            rows_data,
            columns=[
                "Created",
                "Run description",
                "Session / aggregation",
                "Projection status",
                "Run ID",
                "Session ID",
            ],
        )
        grid_df.index = pd.RangeIndex(start=0, stop=len(grid_df), step=1)
        session_grid.data = grid_df
        session_grid.layout.height = _grid_height_px(
            row_count=len(rows_data),
            min_rows=3,
            max_rows=session_grid_max_rows,
        )
        state["label_to_session_key"] = label_to_session_key
        state["session_key_to_row"] = session_key_to_row
        state["grid_index_to_label"] = {idx: label for idx, label in enumerate(options)}
        _sync_grid_from_hidden()

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
                label = state["grid_index_to_label"].get(int(visible_df.index[row_pos]))
                if not label or label in seen:
                    continue
                seen.add(label)
                labels.append(label)
        return tuple(labels)

    def _sync_hidden_from_grid(*_) -> None:
        if state["syncing_grid"]:
            return
        state["syncing_hidden"] = True
        try:
            sessions_sel.value = _selected_labels_from_grid()
        finally:
            state["syncing_hidden"] = False

    def _sync_grid_from_hidden(*_) -> None:
        if state["syncing_hidden"]:
            return
        selected_labels = set(map(str, sessions_sel.value or ()))
        visible_df = session_grid.get_visible_data()
        state["syncing_grid"] = True
        try:
            session_grid.clear_selection()
            if visible_df.empty or not selected_labels:
                return
            last_col = max(0, len(visible_df.columns) - 1)
            for row_pos in range(len(visible_df.index)):
                label = state["grid_index_to_label"].get(int(visible_df.index[row_pos]))
                if label in selected_labels:
                    session_grid.select(row_pos, 0, row_pos, last_col, clear_mode="none")
        finally:
            state["syncing_grid"] = False

    def _render_metadata(
        run_id: str,
        session_id: str,
        row: Mapping[str, Any],
        note: SessionNoteDocument | None,
        *,
        selected_count: int,
    ) -> None:
        note_part = "None"
        if note is not None:
            note_part = f"{note.template_id}@{note.template_version} | updated {note.updated_at_utc}"
        selected_part = (
            f"<b>Selected sessions:</b> {selected_count}<br>"
            if selected_count > 1
            else ""
        )
        metadata_html.value = (
            "<div style='font-family:monospace'>"
            f"{selected_part}"
            f"<b>Run:</b> {html.escape(str(run_id))}<br>"
            f"<b>Session:</b> {html.escape(str(session_id))}<br>"
            f"<b>Created:</b> {html.escape(str(row.get('created_at') or ''))}<br>"
            f"<b>Projection status:</b> {html.escape(str(row.get('projection_status') or ''))}<br>"
            f"<b>Note:</b> {html.escape(note_part)}"
            "</div>"
        )

        run_manifest = _read_json_safe(artifact_store, artifact_store.path_run_manifest(run_id))
        session_manifest = _read_json_safe(
            artifact_store,
            artifact_store.path_session_manifest(run_id, session_id),
        )
        session_meta = _read_json_safe(
            artifact_store,
            artifact_store.path_session_meta(run_id, session_id),
        )

        for out_widget, obj in (
            (run_manifest_out, run_manifest),
            (session_manifest_out, session_manifest),
            (session_meta_out, session_meta),
        ):
            with out_widget:
                out_widget.clear_output()
                print(json.dumps(obj, indent=2, sort_keys=True))

    def _build_fields(template: SessionNoteTemplate) -> None:
        sections: dict[str, list[W.Widget]] = {}
        field_defs: dict[str, SessionNoteFieldDef] = {}
        field_widgets: dict[str, W.Widget] = {}

        for field in template.fields:
            widget = _make_field_widget(field)
            field_defs[field.field_id] = field
            field_widgets[field.field_id] = widget
            sections.setdefault(field.section or "General", []).append(widget)

        children: list[W.Widget] = []
        for section, widgets in sections.items():
            children.append(W.HTML(f"<b>{html.escape(section)}</b>"))
            children.append(W.VBox(widgets))

        state["current_template"] = template
        state["field_defs"] = field_defs
        state["field_widgets"] = field_widgets
        fields_box.children = tuple(children)

    def _load_note_into_controls(
        note: SessionNoteDocument | None,
        template: SessionNoteTemplate,
        *,
        use_template_defaults: bool,
    ) -> None:
        _build_fields(template)
        state["current_note"] = note
        w_note_title.value = "" if note is None or note.title is None else str(note.title)
        w_free_text.value = (
            "" if note is None or note.free_text_notes is None else str(note.free_text_notes)
        )
        w_custom_json.value = json.dumps(
            {} if note is None else note.custom_values,
            indent=2,
            sort_keys=True,
        )

        value_source: dict[str, Any] = {}
        if note is not None:
            value_source.update(note.values)
        for field in template.fields:
            if note is None and not use_template_defaults:
                value = _blank_field_value(field)
            else:
                value = value_source.get(field.field_id, field.default)
            _set_widget_value(
                state["field_widgets"][field.field_id],
                field,
                value,
            )

    def _refresh_editor(*_) -> None:
        _clear_save_confirmation()
        selected_rows = _selected_rows()
        selected_count = len(selected_rows)
        row = _selected_row()
        source_row = _editor_source_row()
        source_session_key = "" if source_row is None else str(source_row["session_key"])
        selected_session_key = "" if row is None else str(row["session_key"])
        if (
            state["editor_staged"]
            and source_row is not None
            and (selected_count != 1 or selected_session_key != source_session_key)
        ):
            _render_metadata(
                str(source_row["run_id"]),
                str(source_row["session_id"]),
                source_row,
                state.get("current_note"),
                selected_count=selected_count,
            )
            return
        if not row:
            metadata_html.value = "<i>No session selected.</i>"
            fields_box.children = ()
            w_run_desc.value = ""
            w_session_desc.value = ""
            w_note_title.value = ""
            w_custom_json.value = "{}"
            w_free_text.value = ""
            state["current_note"] = None
            state["editor_staged"] = False
            state["editor_source_session_key"] = None
            return

        run_id = str(row["run_id"])
        session_id = str(row["session_id"])
        w_run_desc.value = "" if row.get("run_description") is None else str(row.get("run_description"))
        w_session_desc.value = "" if row.get("session_description") is None else str(row.get("session_description"))

        note = note_store.load_note(run_id=run_id, session_id=session_id)
        template: SessionNoteTemplate | None = None
        if note is not None:
            template_key = f"{note.template_id}@{note.template_version}"
            valid_values = {value for _, value in w_template.options}
            if template_key in valid_values:
                state["updating"] = True
                try:
                    w_template.value = template_key
                finally:
                    state["updating"] = False
            try:
                template = template_store.get_template(note.template_id, note.template_version)
            except Exception:
                template = None

        if template is None:
            template_value = str(w_template.value or "")
            if template_value:
                template_id, template_version = template_value.split("@", 1)
                template = template_store.get_template(template_id, template_version)
            elif templates:
                template = templates[0]

        if template is not None:
            _load_note_into_controls(
                note,
                template,
                use_template_defaults=False,
            )
        else:
            fields_box.children = (W.HTML("<i>No templates available.</i>"),)
            state["current_note"] = note
            state["current_template"] = None
            state["field_defs"] = {}
            state["field_widgets"] = {}

        state["editor_staged"] = False
        state["editor_source_session_key"] = str(row["session_key"])
        _render_metadata(
            run_id,
            session_id,
            row,
            note,
            selected_count=selected_count,
        )

    def _refresh_all(*_) -> None:
        template_errors = template_store.template_load_errors()
        state["template_errors"] = template_errors
        _refresh_session_options()
        _refresh_editor()
        aggregation_manager["refresh"]()
        if template_errors:
            _status(
                [
                    "Template load warnings:",
                    *[
                        f"- {path}: {error}"
                        for path, error in sorted(template_errors.items())
                    ],
                ]
            )

    def _on_template_change(change: Mapping[str, Any]) -> None:
        if state["updating"]:
            return
        _clear_save_confirmation()
        new_value = str(change.get("new") or "")
        if not new_value:
            return
        template_id, template_version = new_value.split("@", 1)
        template = template_store.get_template(template_id, template_version)
        note = state.get("current_note")
        if note is not None and note.template_id == template_id and note.template_version == template_version:
            _load_note_into_controls(
                note,
                template,
                use_template_defaults=False,
            )
            source_row = _editor_source_row()
            state["editor_staged"] = True
            state["editor_source_session_key"] = None if source_row is None else str(source_row["session_key"])
            return
        _load_note_into_controls(
            None,
            template,
            use_template_defaults=False,
        )
        source_row = _editor_source_row()
        state["editor_staged"] = True
        state["editor_source_session_key"] = None if source_row is None else str(source_row["session_key"])

    def _on_select(_):
        _refresh_editor()

    def _on_save_descriptions(_):
        _clear_save_confirmation()
        ids = _selected_ids()
        selected_count = len(_selected_rows())
        if ids is None:
            _status(["Select a session before saving descriptions."])
            return
        run_id, session_id = ids
        set_run_description(
            artifact_store,
            run_id=run_id,
            description=_coerce_text_value(w_run_desc.value),
        )
        set_session_description(
            artifact_store,
            run_id=run_id,
            session_id=session_id,
            description=_coerce_text_value(w_session_desc.value),
        )
        _refresh_all()
        lines = [f"Saved run/session descriptions for {run_id}::{session_id}."]
        if selected_count > 1:
            lines.append(f"{selected_count} sessions are selected; descriptions apply to the active session only.")
        _status(lines)

    def _selected_template() -> SessionNoteTemplate | None:
        value = str(w_template.value or "")
        if not value:
            return None
        template_id, template_version = value.split("@", 1)
        return template_store.get_template(template_id, template_version)

    def _collect_note_values() -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field_id, field in state["field_defs"].items():
            value = _widget_value(state["field_widgets"][field_id], field)
            if value is None:
                continue
            values[field_id] = value
        return values

    def _parse_custom_values() -> dict[str, Any]:
        raw = str(w_custom_json.value or "").strip()
        if not raw:
            return {}
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError("Custom fields must be a JSON object")
        return {str(k): v for k, v in obj.items()}

    def _on_load_note(_):
        _clear_save_confirmation()
        row = _selected_row()
        selected_count = len(_selected_rows())
        if not row:
            _status(["Select a session before loading a note."])
            return
        note = note_store.load_note(run_id=str(row["run_id"]), session_id=str(row["session_id"]))
        if note is None:
            _status(["No saved note exists for the selected session."])
            return
        template = template_store.get_template(note.template_id, note.template_version)
        state["updating"] = True
        try:
            w_template.value = f"{template.template_id}@{template.template_version}"
        finally:
            state["updating"] = False
        _load_note_into_controls(
            note,
            template,
            use_template_defaults=False,
        )
        state["editor_staged"] = True
        state["editor_source_session_key"] = str(row["session_key"])
        _render_metadata(
            str(row["run_id"]),
            str(row["session_id"]),
            row,
            note,
            selected_count=selected_count,
        )
        lines = [f"Loaded note for active session {row['session_key']}."]
        if selected_count > 1:
            lines.append(f"Save note will apply the current editor contents to {selected_count} selected sessions.")
        _status(lines)

    def _on_new_note(_):
        _clear_save_confirmation()
        ids = _selected_ids()
        template = _selected_template()
        selected_count = len(_selected_rows())
        if ids is None:
            _status(["Select a session before creating a note."])
            return
        if template is None:
            _status(["No note template is available."])
            return
        run_id, session_id = ids
        note = note_store.create_note_from_template(
            run_id=run_id,
            session_id=session_id,
            template_id=template.template_id,
            template_version=template.template_version,
        )
        _load_note_into_controls(
            note,
            template,
            use_template_defaults=True,
        )
        state["editor_staged"] = True
        state["editor_source_session_key"] = str(run_id) + "::" + str(session_id)
        lines = [
            f"Prepared new note for active session {run_id}::{session_id} from {template.template_id}@{template.template_version}."
        ]
        if selected_count > 1:
            lines.append(f"Save note will apply the current editor contents to {selected_count} selected sessions.")
        _status(lines)

    def _save_note_to_rows(rows: Sequence[Mapping[str, Any]]) -> None:
        template = state.get("current_template")
        if template is None:
            _status(["No note template is selected."])
            return
        try:
            note_values = _collect_note_values()
            custom_values = _parse_custom_values()
            free_text_notes = _coerce_text_value(w_free_text.value)
            title = _coerce_text_value(w_note_title.value)
        except Exception as exc:
            _status([f"Failed to save note: {exc}"])
            return

        source_session_key = str(state.get("editor_source_session_key") or "")
        saved_source: SessionNoteDocument | None = None
        overwrite_count = 0

        try:
            for row in rows:
                run_id = str(row["run_id"])
                session_id = str(row["session_id"])
                session_key = str(row["session_key"])
                existing = note_store.load_note(run_id=run_id, session_id=session_id)
                if existing is not None:
                    overwrite_count += 1
                note = existing
                if (
                    note is None
                    or note.template_id != template.template_id
                    or note.template_version != template.template_version
                ):
                    note = note_store.create_note_from_template(
                        run_id=run_id,
                        session_id=session_id,
                        template_id=template.template_id,
                        template_version=template.template_version,
                    )
                updated = note_store.update_note(
                    note,
                    values=note_values,
                    custom_values=custom_values,
                    free_text_notes=free_text_notes,
                    title=title,
                    replace_values=True,
                )
                saved = note_store.save_note(updated)
                if source_session_key and session_key == source_session_key:
                    saved_source = saved
        except Exception as exc:
            _status([f"Failed to save note: {exc}"])
            return

        state["current_note"] = saved_source if saved_source is not None else state.get("current_note")
        state["editor_staged"] = True
        _refresh_all()
        lines = [f"Saved session note to {len(rows)} session(s)."]
        if overwrite_count > 0:
            lines.append(f"Overwrote existing notes for {overwrite_count} session(s).")
        _status(lines)

    def _on_save_note(_):
        _clear_save_confirmation()
        rows = _selected_rows()
        template = state.get("current_template")
        if not rows:
            _status(["Select a session before saving a note."])
            return
        if template is None:
            _status(["No note template is selected."])
            return
        try:
            _collect_note_values()
            _parse_custom_values()
        except Exception as exc:
            _status([f"Failed to save note: {exc}"])
            return

        overwrite_session_keys: list[str] = []
        for row in rows:
            existing = note_store.load_note(
                run_id=str(row["run_id"]),
                session_id=str(row["session_id"]),
            )
            if existing is not None:
                overwrite_session_keys.append(str(row["session_key"]))

        if len(rows) > 1 or overwrite_session_keys:
            lines = [f"This will save the current editor note to {len(rows)} selected session(s)."]
            if overwrite_session_keys:
                lines.append(f"Existing notes will be overwritten for {len(overwrite_session_keys)} session(s).")
                preview = ", ".join(overwrite_session_keys[:3])
                if preview:
                    suffix = " ..." if len(overwrite_session_keys) > 3 else ""
                    lines.append(f"Overwrite targets: {preview}{suffix}")
            lines.append("Click Confirm save to continue, or Cancel to keep editing.")
            _show_save_confirmation(
                lines,
                [str(row["session_key"]) for row in rows],
            )
            return

        _save_note_to_rows(rows)

    def _on_confirm_save_note(_):
        rows = _rows_from_session_keys(state["pending_note_save_session_keys"])
        _clear_save_confirmation()
        if not rows:
            _status(["Select a session before saving a note."])
            return
        _save_note_to_rows(rows)

    def _on_cancel_save_note(_):
        _clear_save_confirmation()
        _status(["Cancelled note save."])

    w_template.observe(_on_template_change, names="value")
    sessions_sel.observe(_on_select, names="value")
    sessions_sel.observe(_sync_grid_from_hidden, names="value")
    session_grid.observe(_sync_hidden_from_grid, names="selections")
    b_refresh.on_click(_refresh_all)
    b_save_desc.on_click(_on_save_descriptions)
    b_load_note.on_click(_on_load_note)
    b_new_note.on_click(_on_new_note)
    b_save_note.on_click(_on_save_note)
    b_confirm_save_note.on_click(_on_confirm_save_note)
    b_cancel_save_note.on_click(_on_cancel_save_note)
    w_filter.observe(_refresh_session_options, names="value")

    session_controls = W.HBox([w_filter, b_refresh])
    description_box = W.VBox(
        [
            W.HTML("<div style='font-size:1.15em;font-weight:700'>Descriptions</div>"),
            w_run_desc,
            w_session_desc,
            b_save_desc,
        ],
        layout=W.Layout(width="540px"),
    )
    note_controls = W.VBox(
        [
            w_template,
            W.HBox(
                [b_load_note, b_new_note, b_save_note],
                layout=W.Layout(margin=f"0 0 0 {NOTE_LABEL_WIDTH}"),
            ),
        ]
    )
    note_box = W.VBox(
        [
            W.HTML("<div style='font-size:1.15em;font-weight:700'>Session note</div>"),
            note_controls,
            save_confirm_box,
            w_note_title,
            fields_box,
            w_custom_json,
            w_free_text,
        ],
        layout=W.Layout(width="860px"),
    )
    right_col = W.VBox(
        [
            metadata_html,
            description_box,
            note_box,
            details,
            status_out,
        ],
        layout=W.Layout(width="930px"),
    )
    sessions_tab = W.HBox(
        [
            W.VBox([session_controls, session_grid, sessions_sel], layout=W.Layout(width="740px")),
            right_col,
        ]
    )

    tabs = W.Tab(children=[sessions_tab, aggregation_manager["ui"]])
    tabs.set_title(0, "Sessions")
    tabs.set_title(1, "Aggregations")

    _refresh_all()

    if auto_display:
        display(tabs)

    return {
        "ui": tabs,
        "refresh": _refresh_all,
        "artifact_store": artifact_store,
        "template_store": template_store,
        "note_store": note_store,
        "aggregation_store": agg_store,
        "aggregation_manager": aggregation_manager,
        "controls": {
            "filter": w_filter,
            "show_ids": None,
            "sessions": sessions_sel,
            "session_grid": session_grid,
            "run_description": w_run_desc,
            "session_description": w_session_desc,
            "template": w_template,
            "note_title": w_note_title,
            "custom_json": w_custom_json,
            "free_text": w_free_text,
        },
        "state": state,
    }
