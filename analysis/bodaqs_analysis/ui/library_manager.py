from __future__ import annotations

import html
import json
import warnings
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import ipywidgets as W
import pandas as pd
from IPython.display import display
from ipydatagrid import DataGrid, TextRenderer

from bodaqs_analysis.artifacts import ArtifactStore
from bodaqs_analysis.library_api import LibraryAdapter
from bodaqs_analysis.library_api.errors import RevisionConflictError
from bodaqs_analysis.library_api.ids import make_session_ref_id, make_unique_object_id
from bodaqs_analysis.session_notes import (
    CatalogProjectionConfig,
    NOTE_SCHEMA,
    NOTE_VERSION,
    SessionNoteDocument,
    SessionNoteFieldDef,
    SessionNoteTemplate,
    make_session_note_template_store,
)


DESCRIPTION_LABEL_WIDTH = "120px"
NOTE_LABEL_WIDTH = "120px"
NOTE_INPUT_WIDTH = "520px"


def _read_json_safe(store: ArtifactStore, path: Path) -> dict[str, Any]:
    try:
        return store.read_json(path)
    except Exception:
        return {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _note_dict_to_document(note: Mapping[str, Any] | None) -> SessionNoteDocument | None:
    if not isinstance(note, Mapping):
        return None
    values = note.get("values") if isinstance(note.get("values"), Mapping) else {}
    custom_values = note.get("custom_values") if isinstance(note.get("custom_values"), Mapping) else {}
    source_context = note.get("source_context")
    return SessionNoteDocument(
        schema=str(note.get("schema") or NOTE_SCHEMA),
        version=int(note.get("version") or NOTE_VERSION),
        run_id=str(note.get("run_id") or ""),
        session_id=str(note.get("session_id") or ""),
        session_key=str(note.get("session_key") or ""),
        template_id=str(note.get("template_id") or ""),
        template_version=str(note.get("template_version") or ""),
        title=_optional_text(note.get("title")),
        values={str(k): v for k, v in dict(values).items()},
        custom_values={str(k): v for k, v in dict(custom_values).items()},
        free_text_notes=_optional_text(note.get("free_text_notes")),
        created_at_utc=str(note.get("created_at_utc") or ""),
        updated_at_utc=str(note.get("updated_at_utc") or ""),
        draft=bool(note.get("draft", False)),
        source_context=dict(source_context) if isinstance(source_context, Mapping) else None,
    )


def _new_note_dict_from_template(
    *,
    row: Mapping[str, Any],
    template: SessionNoteTemplate,
) -> dict[str, Any]:
    session_key = str(row["session_key"])
    return {
        "schema": NOTE_SCHEMA,
        "version": NOTE_VERSION,
        "run_id": str(row["run_id"]),
        "session_id": str(row["session_id"]),
        "session_key": session_key,
        "template_id": template.template_id,
        "template_version": template.template_version,
        "title": "Session note",
        "values": {},
        "custom_values": {},
        "free_text_notes": "",
        "created_at_utc": "",
        "updated_at_utc": "",
        "draft": True,
    }


def _note_save_dict(
    *,
    row: Mapping[str, Any],
    template: SessionNoteTemplate,
    existing: SessionNoteDocument | None,
    values: Mapping[str, Any],
    custom_values: Mapping[str, Any],
    free_text_notes: str | None,
    title: str | None,
    draft: bool,
) -> dict[str, Any]:
    base = (
        _new_note_dict_from_template(row=row, template=template)
        if existing is None
        else {
            "schema": existing.schema,
            "version": existing.version,
            "run_id": existing.run_id,
            "session_id": existing.session_id,
            "session_key": existing.session_key,
            "template_id": existing.template_id,
            "template_version": existing.template_version,
            "title": existing.title,
            "values": dict(existing.values),
            "custom_values": dict(existing.custom_values),
            "free_text_notes": existing.free_text_notes,
            "created_at_utc": existing.created_at_utc,
            "updated_at_utc": existing.updated_at_utc,
            "draft": existing.draft,
            **({"source_context": existing.source_context} if existing.source_context else {}),
        }
    )
    base["run_id"] = str(row["run_id"])
    base["session_id"] = str(row["session_id"])
    base["session_key"] = str(row["session_key"])
    base["template_id"] = template.template_id
    base["template_version"] = template.template_version
    base["title"] = title
    base["values"] = {str(k): v for k, v in dict(values).items()}
    base["custom_values"] = {str(k): v for k, v in dict(custom_values).items()}
    base["free_text_notes"] = free_text_notes or ""
    base["draft"] = bool(draft)
    return base


def _manager_row_from_catalog_row(row: Mapping[str, Any]) -> dict[str, Any]:
    display = row.get("display") if isinstance(row.get("display"), Mapping) else {}
    timestamps = row.get("timestamps") if isinstance(row.get("timestamps"), Mapping) else {}
    note_status = row.get("note_status") if isinstance(row.get("note_status"), Mapping) else {}
    note_fields = row.get("note_fields") if isinstance(row.get("note_fields"), Mapping) else {}
    qc_summary = row.get("qc_summary") if isinstance(row.get("qc_summary"), Mapping) else {}
    gps_summary = row.get("gps_summary") if isinstance(row.get("gps_summary"), Mapping) else {}

    library_id = str(row.get("library_id") or "")
    session_key = str(row.get("session_key") or "")
    run_id = str(row.get("run_id") or "")
    session_id = str(row.get("session_id") or "")
    run_label = str(display.get("run_label") or "")
    session_label = str(display.get("session_label") or "")

    return {
        "library_id": library_id,
        "session_ref_id": str(row.get("session_ref_id") or make_session_ref_id(library_id, session_key)),
        "session_key": session_key,
        "run_id": run_id,
        "session_id": session_id,
        "created_at": str(timestamps.get("started_at_local") or timestamps.get("processed_at") or ""),
        "run_description": "" if run_label == run_id else run_label,
        "session_description": "" if session_label == session_id else session_label,
        "display_label": str(display.get("label") or session_label or session_key),
        "note_state": str(note_status.get("status") or "missing"),
        "note_has_note": bool(note_status.get("has_note", False)),
        "note_draft": bool(note_status.get("draft", False)),
        "projection_status": "ok" if note_fields else "",
        "bike": note_fields.get("bike"),
        "rider": note_fields.get("rider"),
        "qc_status": str(qc_summary.get("status") or ""),
        "gps_quality": str(gps_summary.get("quality") or ""),
        "api_row": dict(row),
    }


def _catalog_df_from_adapter_catalog(catalog: Mapping[str, Any]) -> pd.DataFrame:
    rows = catalog.get("rows")
    if not isinstance(rows, list):
        return pd.DataFrame()
    return pd.DataFrame.from_records(
        [_manager_row_from_catalog_row(row) for row in rows if isinstance(row, Mapping)]
    )


def _session_ref_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    library_id = str(row.get("library_id") or "")
    session_key = str(row.get("session_key") or "")
    return {
        "library_id": library_id,
        "session_ref_id": str(row.get("session_ref_id") or make_session_ref_id(library_id, session_key)),
        "session_key": session_key,
        "run_id": str(row.get("run_id") or ""),
        "session_id": str(row.get("session_id") or ""),
        "label": str(row.get("display_label") or session_key),
    }


def _resolve_manager_context(
    *,
    libraries_root: str | Path | None,
    library_id: str | None,
    artifacts_dir: str | Path,
    artifact_store: ArtifactStore | None,
    library_adapter: LibraryAdapter | None,
) -> tuple[LibraryAdapter, str, ArtifactStore]:
    store = artifact_store or ArtifactStore(Path(artifacts_dir))
    adapter = library_adapter
    if adapter is None:
        root = Path(libraries_root).expanduser() if libraries_root is not None else store.root.parent
        adapter = LibraryAdapter(root)

    libraries = adapter.list_libraries()
    selected_library: Mapping[str, Any] | None = None
    if library_id:
        selected_library = adapter.get_library(str(library_id))
    else:
        store_root = store.root.resolve()
        for library in libraries:
            try:
                if Path(str(library.get("root"))).expanduser().resolve() == store_root:
                    selected_library = library
                    break
            except Exception:
                continue
        if selected_library is None and len(libraries) == 1:
            selected_library = libraries[0]

    if selected_library is None:
        raise ValueError(
            "Could not infer library_id. Pass libraries_root=... and library_id=... "
            "to make_library_manager(...)."
        )

    resolved_library_id = str(selected_library["library_id"])
    resolved_store = ArtifactStore(Path(str(selected_library["root"])))
    return adapter, resolved_library_id, resolved_store

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
    libraries_root: str | Path | None = None,
    library_id: str | None = None,
    artifacts_dir: str | Path = "artifacts",
    selector: Mapping[str, Any] | None = None,
    artifact_store: ArtifactStore | None = None,
    library_adapter: LibraryAdapter | None = None,
    template_root: str | Path | None = None,
    aggregation_store: Any | None = None,
    projection_configs: Sequence[CatalogProjectionConfig] = (),
    rows: int = 14,
    show_ids_default: bool = False,
    auto_display: bool = False,
) -> dict[str, Any]:
    if aggregation_store is not None:
        warnings.warn(
            "aggregation_store is ignored by make_library_manager(); "
            "legacy aggregations are deprecated in favour of Study Set groupings.",
            DeprecationWarning,
            stacklevel=2,
        )
    if artifact_store is None and selector is not None:
        selector_store = selector.get("store") if isinstance(selector, Mapping) else None
        if isinstance(selector_store, ArtifactStore):
            artifact_store = selector_store
    adapter, active_library_id, artifact_store = _resolve_manager_context(
        libraries_root=libraries_root,
        library_id=library_id,
        artifacts_dir=artifacts_dir,
        artifact_store=artifact_store,
        library_adapter=library_adapter,
    )
    template_store = make_session_note_template_store(
        artifacts_dir=artifact_store.root,
        template_root=template_root,
    )

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
            "Session",
            "Note state",
            "Rider",
            "Bike",
            "QC",
            "GPS",
            "Run ID",
            "Session ID",
        ],
        height=_grid_height_px(row_count=0, min_rows=3, max_rows=session_grid_max_rows),
        base_column_size=155,
        column_widths={
            "Created": 165,
            "Run description": 220,
            "Session": 250,
            "Note state": 95,
            "Rider": 120,
            "Bike": 150,
            "QC": 70,
            "GPS": 90,
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

    study_set_select = W.Dropdown(
        options=[("(No saved Study Sets)", "")],
        value="",
        description="Study Set",
        layout=W.Layout(width="520px"),
        style={"description_width": "90px"},
    )
    study_set_name = W.Text(
        value="",
        description="Name",
        layout=W.Layout(width="520px"),
        style={"description_width": "90px"},
    )
    study_set_id = W.Text(
        value="",
        description="ID",
        placeholder="Optional for new Study Sets",
        layout=W.Layout(width="520px"),
        style={"description_width": "90px"},
    )
    study_set_revision = W.Text(
        value="",
        description="Revision",
        disabled=True,
        layout=W.Layout(width="220px"),
        style={"description_width": "90px"},
    )
    b_study_refresh = W.Button(description="Refresh")
    b_study_new = W.Button(description="New / clear")
    b_study_load = W.Button(description="Load")
    b_study_create = W.Button(description="Create from selected")
    b_study_update = W.Button(description="Update from selected")
    b_study_delete = W.Button(description="Delete", button_style="danger")

    grouping_name = W.Text(
        value="",
        description="Grouping",
        placeholder="Short grouping name",
        layout=W.Layout(width="420px"),
        style={"description_width": "90px"},
    )
    grouping_select = W.Dropdown(
        options=[("(No groupings)", "")],
        value="",
        description="Saved",
        layout=W.Layout(width="420px"),
        style={"description_width": "90px"},
    )
    b_grouping_add = W.Button(description="Add/update from selected")
    b_grouping_remove = W.Button(description="Remove grouping")
    study_set_summary = W.HTML()
    study_set_out = W.Output(layout=W.Layout(width="100%"))

    state: Dict[str, Any] = {
        "catalog_df": pd.DataFrame(),
        "label_to_session_key": {},
        "session_key_to_row": {},
        "session_key_to_label": {},
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
        "study_set_summaries": [],
        "current_study_set": None,
        "working_groupings": [],
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
        catalog = adapter.get_catalog(active_library_id, refresh=True)
        catalog_df = _catalog_df_from_adapter_catalog(catalog)
        state["catalog_df"] = catalog_df

        label_to_session_key: dict[str, str] = {}
        session_key_to_row: dict[str, Mapping[str, Any]] = {}
        session_key_to_label: dict[str, str] = {}
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
            session_key_to_label[session_key] = unique_label
            session_key_to_row[session_key] = row_dict
            rows_data.append(
                {
                    "Created": str(row_dict.get("created_at") or ""),
                    "Run description": str(row_dict.get("run_description") or ""),
                    "Session": str(row_dict.get("session_description") or row_dict.get("display_label") or ""),
                    "Note state": str(row_dict.get("note_state") or "missing"),
                    "Rider": str(row_dict.get("rider") or ""),
                    "Bike": str(row_dict.get("bike") or ""),
                    "QC": str(row_dict.get("qc_status") or ""),
                    "GPS": str(row_dict.get("gps_quality") or ""),
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
                "Session",
                "Note state",
                "Rider",
                "Bike",
                "QC",
                "GPS",
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
        state["session_key_to_label"] = session_key_to_label
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
        note_state_part = ""
        if note is not None:
            note_part = f"{note.template_id}@{note.template_version} | updated {note.updated_at_utc}"
            note_state_part = "draft" if note.draft else "edited"
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
            f"<b>Note state:</b> {html.escape(note_state_part)}<br>"
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

        try:
            note_response = adapter.load_session_note(
                active_library_id,
                {"session_ref": _session_ref_from_row(row)},
            )
        except Exception as exc:
            note_response = {"present": False, "note": None, "error": f"{type(exc).__name__}: {exc}"}
            _status([f"Failed to load session note: {note_response['error']}"])
        note = _note_dict_to_document(note_response.get("note")) if note_response.get("present") else None
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

    def _study_status(lines: Sequence[str]) -> None:
        with study_set_out:
            study_set_out.clear_output()
            for line in lines:
                print(line)

    def _selected_study_set_id() -> str:
        return str(study_set_select.value or "").strip()

    def _study_set_active_library_only(study_set: Mapping[str, Any] | None) -> bool:
        if not isinstance(study_set, Mapping):
            return True
        sessions = study_set.get("sessions")
        if not isinstance(sessions, list):
            return True
        library_ids = {
            str(session.get("library_id"))
            for session in sessions
            if isinstance(session, Mapping) and session.get("library_id") is not None
        }
        return not library_ids or library_ids == {active_library_id}

    def _selected_session_refs() -> list[dict[str, Any]]:
        return [_session_ref_from_row(row) for row in _selected_rows()]

    def _selected_session_ref_ids() -> set[str]:
        return {str(ref["session_ref_id"]) for ref in _selected_session_refs()}

    def _refresh_grouping_options() -> None:
        groupings = [
            dict(grouping)
            for grouping in list(state.get("working_groupings") or [])
            if isinstance(grouping, Mapping)
        ]
        options: list[tuple[str, str]] = []
        for grouping in groupings:
            grouping_id = str(grouping.get("grouping_id") or "")
            if not grouping_id:
                continue
            name = str(grouping.get("display_name") or grouping_id)
            refs = grouping.get("session_refs")
            count = len(refs) if isinstance(refs, list) else 0
            options.append((f"{name} ({count})", grouping_id))
        grouping_select.options = options or [("(No groupings)", "")]
        valid = {value for _, value in grouping_select.options}
        if grouping_select.value not in valid:
            grouping_select.value = options[0][1] if options else ""
        _render_study_set_summary()

    def _render_study_set_summary() -> None:
        current = state.get("current_study_set")
        groupings = list(state.get("working_groupings") or [])
        if not isinstance(current, Mapping):
            selected_count = len(_selected_rows())
            study_set_summary.value = (
                "<b>No Study Set loaded.</b><br>"
                f"Selected sessions ready for new Study Set: {selected_count}<br>"
                f"Working groupings: {len(groupings)}"
            )
            return
        sessions = current.get("sessions") if isinstance(current.get("sessions"), list) else []
        library_ids = sorted(
            {
                str(session.get("library_id"))
                for session in sessions
                if isinstance(session, Mapping) and session.get("library_id") is not None
            }
        )
        warning = ""
        if not _study_set_active_library_only(current):
            warning = (
                "<br><b>Read-only in this notebook:</b> this Study Set contains "
                "sessions from libraries outside the active library."
            )
        study_set_summary.value = (
            f"<b>{html.escape(str(current.get('display_name') or current.get('study_set_id') or 'Study Set'))}</b><br>"
            f"ID: {html.escape(str(current.get('study_set_id') or ''))}<br>"
            f"Revision: {html.escape(str(current.get('revision') or ''))}<br>"
            f"Sessions: {len(sessions)} | Libraries: {', '.join(library_ids) or active_library_id}<br>"
            f"Working groupings: {len(groupings)}"
            f"{warning}"
        )

    def _refresh_study_sets(*_) -> None:
        summaries = adapter.list_study_sets(active_library_id)
        state["study_set_summaries"] = list(summaries)
        options = [
            (
                f"{summary.get('display_name') or summary.get('study_set_id')} "
                f"({summary.get('session_count', 0)} sessions, rev {summary.get('revision', 0)})",
                str(summary.get("study_set_id") or ""),
            )
            for summary in summaries
            if summary.get("study_set_id")
        ]
        previous = _selected_study_set_id()
        study_set_select.options = options or [("(No saved Study Sets)", "")]
        values = {value for _, value in study_set_select.options}
        study_set_select.value = previous if previous in values else (options[0][1] if options else "")
        _render_study_set_summary()

    def _select_sessions_from_study_set(study_set: Mapping[str, Any]) -> None:
        labels: list[str] = []
        session_key_to_label = state.get("session_key_to_label") or {}
        sessions = study_set.get("sessions")
        if not isinstance(sessions, list):
            return
        for session in sessions:
            if not isinstance(session, Mapping):
                continue
            if str(session.get("library_id") or "") != active_library_id:
                continue
            label = session_key_to_label.get(str(session.get("session_key") or ""))
            if label:
                labels.append(label)
        valid = set(map(str, sessions_sel.options or ()))
        sessions_sel.value = tuple(label for label in labels if label in valid)

    def _set_current_study_set(study_set: Mapping[str, Any] | None) -> None:
        current = dict(study_set) if isinstance(study_set, Mapping) else None
        state["current_study_set"] = current
        if current is None:
            study_set_name.value = ""
            study_set_id.value = ""
            study_set_id.disabled = False
            study_set_revision.value = ""
            state["working_groupings"] = []
            _refresh_grouping_options()
            _render_study_set_summary()
            return
        study_set_name.value = str(current.get("display_name") or current.get("study_set_id") or "")
        study_set_id.value = str(current.get("study_set_id") or "")
        study_set_id.disabled = True
        study_set_revision.value = str(current.get("revision") or "")
        state["working_groupings"] = [
            dict(grouping)
            for grouping in list(current.get("groupings") or [])
            if isinstance(grouping, Mapping)
        ]
        _select_sessions_from_study_set(current)
        _refresh_grouping_options()
        _render_study_set_summary()

    def _study_set_payload_from_editor(
        existing: Mapping[str, Any] | None,
        *,
        require_existing_id: bool,
    ) -> dict[str, Any]:
        display_name = _coerce_text_value(study_set_name.value)
        if not display_name:
            raise ValueError("Study Set name is required.")
        sessions = _selected_session_refs()
        if not sessions:
            raise ValueError("Select at least one active-library session for the Study Set.")
        known_refs = {str(session["session_ref_id"]) for session in sessions}
        groupings: list[dict[str, Any]] = []
        for grouping in list(state.get("working_groupings") or []):
            if not isinstance(grouping, Mapping):
                continue
            refs = [
                str(ref)
                for ref in list(grouping.get("session_refs") or [])
                if str(ref) in known_refs
            ]
            if not refs:
                continue
            groupings.append(
                {
                    **dict(grouping),
                    "session_refs": refs,
                    "display_name": str(grouping.get("display_name") or grouping.get("grouping_id") or "Grouping"),
                }
            )

        payload = dict(existing) if isinstance(existing, Mapping) else {}
        payload["display_name"] = display_name
        requested_id = _coerce_text_value(study_set_id.value)
        if requested_id:
            payload["study_set_id"] = requested_id
        elif require_existing_id and existing is not None:
            payload["study_set_id"] = str(existing["study_set_id"])
        payload["sessions"] = sessions
        payload["groupings"] = groupings
        payload.setdefault("tracks", list(existing.get("tracks") or []) if isinstance(existing, Mapping) else [])
        payload.setdefault("bookmarks", list(existing.get("bookmarks") or []) if isinstance(existing, Mapping) else [])
        return payload

    def _on_study_load(_=None) -> None:
        study_id = _selected_study_set_id()
        if not study_id:
            _study_status(["Select a Study Set to load."])
            return
        try:
            study_set = adapter.load_study_set(active_library_id, study_id)
        except Exception as exc:
            _study_status([f"Failed to load Study Set: {exc}"])
            return
        _set_current_study_set(study_set)
        lines = [f"Loaded Study Set {study_id}."]
        if not _study_set_active_library_only(study_set):
            lines.append("This Study Set is read-only here because it spans multiple libraries.")
        _study_status(lines)

    def _on_study_new(_=None) -> None:
        _set_current_study_set(None)
        _study_status(["Cleared Study Set editor. Select sessions, enter a name, then create a new Study Set."])

    def _on_study_create(_=None) -> None:
        try:
            payload = _study_set_payload_from_editor(None, require_existing_id=False)
            created = adapter.create_study_set(active_library_id, payload)
        except Exception as exc:
            _study_status([f"Failed to create Study Set: {exc}"])
            return
        _refresh_study_sets()
        study_set_select.value = str(created["study_set_id"])
        _set_current_study_set(created)
        _study_status([f"Created Study Set {created['study_set_id']}."])

    def _on_study_update(_=None) -> None:
        current = state.get("current_study_set")
        if not isinstance(current, Mapping):
            _study_status(["Load or create a Study Set before updating."])
            return
        if not _study_set_active_library_only(current):
            _study_status(["Cannot update a multi-library Study Set from this notebook."])
            return
        try:
            payload = _study_set_payload_from_editor(current, require_existing_id=True)
            updated = adapter.update_study_set(
                active_library_id,
                str(current["study_set_id"]),
                expected_revision=int(current.get("revision") or 0),
                payload=payload,
            )
        except RevisionConflictError as exc:
            _study_status([f"Revision conflict: {exc}", "Reload the Study Set before editing again."])
            return
        except Exception as exc:
            _study_status([f"Failed to update Study Set: {exc}"])
            return
        _refresh_study_sets()
        study_set_select.value = str(updated["study_set_id"])
        _set_current_study_set(updated)
        _study_status([f"Updated Study Set {updated['study_set_id']} to revision {updated['revision']}."])

    def _on_study_delete(_=None) -> None:
        current = state.get("current_study_set")
        study_id = str(current.get("study_set_id") if isinstance(current, Mapping) else _selected_study_set_id())
        if not study_id:
            _study_status(["Select a Study Set to delete."])
            return
        try:
            adapter.delete_study_set(active_library_id, study_id)
        except Exception as exc:
            _study_status([f"Failed to delete Study Set: {exc}"])
            return
        _set_current_study_set(None)
        _refresh_study_sets()
        _study_status([f"Deleted Study Set {study_id}."])

    def _on_grouping_add(_=None) -> None:
        selected_refs = sorted(_selected_session_ref_ids())
        if not selected_refs:
            _study_status(["Select one or more sessions before adding a grouping."])
            return
        name = _coerce_text_value(grouping_name.value)
        if not name:
            _study_status(["Enter a grouping name."])
            return
        groupings = [
            dict(grouping)
            for grouping in list(state.get("working_groupings") or [])
            if isinstance(grouping, Mapping)
        ]
        selected_id = str(grouping_select.value or "").strip()
        existing_ids = [str(grouping.get("grouping_id")) for grouping in groupings if grouping.get("grouping_id")]
        grouping_id = selected_id if selected_id else make_unique_object_id(
            name,
            existing_ids,
            fallback="grouping",
        )
        replacement = {
            "grouping_id": grouping_id,
            "display_name": name,
            "session_refs": selected_refs,
        }
        replaced = False
        for index, grouping in enumerate(groupings):
            if str(grouping.get("grouping_id") or "") == grouping_id:
                groupings[index] = replacement
                replaced = True
                break
        if not replaced:
            groupings.append(replacement)
        state["working_groupings"] = groupings
        grouping_name.value = ""
        _refresh_grouping_options()
        grouping_select.value = grouping_id
        _study_status([f"{'Updated' if replaced else 'Added'} grouping {grouping_id}."])

    def _on_grouping_remove(_=None) -> None:
        grouping_id = str(grouping_select.value or "").strip()
        if not grouping_id:
            _study_status(["Select a grouping to remove."])
            return
        groupings = [
            dict(grouping)
            for grouping in list(state.get("working_groupings") or [])
            if isinstance(grouping, Mapping) and str(grouping.get("grouping_id") or "") != grouping_id
        ]
        state["working_groupings"] = groupings
        _refresh_grouping_options()
        _study_status([f"Removed grouping {grouping_id}. Save/update the Study Set to persist this change."])

    def _refresh_all(*_) -> None:
        template_errors = template_store.template_load_errors()
        state["template_errors"] = template_errors
        _refresh_session_options()
        _refresh_editor()
        _refresh_study_sets()
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
        row = _selected_row()
        if row is None:
            _status(["Select a session before saving descriptions."])
            return
        try:
            adapter.update_session_descriptions(
                active_library_id,
                {
                    "session_ref": _session_ref_from_row(row),
                    "run_description": _coerce_text_value(w_run_desc.value),
                    "session_description": _coerce_text_value(w_session_desc.value),
                },
            )
        except Exception as exc:
            _status([f"Failed to save descriptions: {exc}"])
            return
        _refresh_all()
        lines = [f"Saved run/session descriptions for {run_id}::{session_id}."]
        if selected_count > 1:
            lines.append(f"{selected_count} sessions are selected; descriptions apply to the active session only.")
        lines.append("Run description applies to every session in the same run.")
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
        try:
            note_response = adapter.load_session_note(
                active_library_id,
                {"session_ref": _session_ref_from_row(row)},
            )
        except Exception as exc:
            _status([f"Failed to load note: {exc}"])
            return
        note = _note_dict_to_document(note_response.get("note")) if note_response.get("present") else None
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
        note = _note_dict_to_document(
            _new_note_dict_from_template(
                row=_selected_row() or {
                    "run_id": run_id,
                    "session_id": session_id,
                    "session_key": f"{run_id}::{session_id}",
                },
                template=template,
            )
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
                session_key = str(row["session_key"])
                note_response = adapter.load_session_note(
                    active_library_id,
                    {"session_ref": _session_ref_from_row(row)},
                )
                existing = _note_dict_to_document(note_response.get("note")) if note_response.get("present") else None
                if existing is not None:
                    overwrite_count += 1
                note = (
                    existing
                    if existing is not None
                    and existing.template_id == template.template_id
                    and existing.template_version == template.template_version
                    else None
                )
                updated = _note_save_dict(
                    row=row,
                    template=template,
                    existing=note,
                    values=note_values,
                    custom_values=custom_values,
                    free_text_notes=free_text_notes,
                    title=title,
                    draft=False,
                )
                saved_response = adapter.save_session_note(
                    active_library_id,
                    {
                        "session_ref": _session_ref_from_row(row),
                        "note": updated,
                    },
                )
                saved = _note_dict_to_document(saved_response.get("note"))
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
            existing_response = adapter.load_session_note(
                active_library_id,
                {"session_ref": _session_ref_from_row(row)},
            )
            if existing_response.get("present"):
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
    b_study_refresh.on_click(_refresh_study_sets)
    b_study_new.on_click(_on_study_new)
    b_study_load.on_click(_on_study_load)
    b_study_create.on_click(_on_study_create)
    b_study_update.on_click(_on_study_update)
    b_study_delete.on_click(_on_study_delete)
    b_grouping_add.on_click(_on_grouping_add)
    b_grouping_remove.on_click(_on_grouping_remove)

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
    study_sets_tab = W.VBox(
        [
            W.HTML("<div style='font-size:1.15em;font-weight:700'>Study Sets</div>"),
            W.HBox([study_set_select, b_study_refresh, b_study_load, b_study_new]),
            W.HBox([study_set_name, study_set_id, study_set_revision]),
            W.HBox([b_study_create, b_study_update, b_study_delete]),
            study_set_summary,
            W.HTML("<div style='font-size:1.05em;font-weight:700;margin-top:10px'>Groupings</div>"),
            W.HBox([grouping_select, grouping_name]),
            W.HBox([b_grouping_add, b_grouping_remove]),
            W.HTML(
                "<small>Groupings use the sessions currently selected in the Sessions tab. "
                "Click Update from selected to persist grouping changes to a loaded Study Set.</small>"
            ),
            study_set_out,
        ],
        layout=W.Layout(width="1180px"),
    )

    tabs = W.Tab(children=[sessions_tab, study_sets_tab])
    tabs.set_title(0, "Sessions")
    tabs.set_title(1, "Study Sets")

    _refresh_all()

    if auto_display:
        display(tabs)

    return {
        "ui": tabs,
        "refresh": _refresh_all,
        "artifact_store": artifact_store,
        "library_adapter": adapter,
        "library_id": active_library_id,
        "template_store": template_store,
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
            "study_set": study_set_select,
            "study_set_name": study_set_name,
            "study_set_id": study_set_id,
            "grouping": grouping_select,
            "grouping_name": grouping_name,
        },
        "state": state,
    }
