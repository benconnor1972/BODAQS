from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import ipywidgets as W
import pandas as pd
from IPython.display import display

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


def _read_json_safe(store: ArtifactStore, path: Path) -> dict[str, Any]:
    try:
        return store.read_json(path)
    except Exception:
        return {}


def _format_session_label(row: Mapping[str, Any], *, show_ids: bool) -> str:
    created_at = str(row.get("created_at") or "").strip()
    run_id = str(row.get("run_id") or "").strip()
    session_id = str(row.get("session_id") or "").strip()
    run_desc = str(row.get("run_description") or "").strip()
    session_desc = str(row.get("session_description") or "").strip()

    if show_ids:
        run_part = f"run_id={run_id} | run_desc={run_desc or '(none)'}"
        session_part = f"session_id={session_id} | session_desc={session_desc or '(none)'}"
    else:
        run_part = run_desc or run_id
        session_part = session_desc or session_id

    parts = [p for p in (created_at, run_part, session_part) if p]
    return " | ".join(parts)


def _template_label(template: SessionNoteTemplate) -> str:
    return f"{template.title} [{template.template_id}@{template.template_version}]"


def _coerce_text_value(raw: str) -> str | None:
    text = str(raw or "").strip()
    return text or None


def _field_label(field: SessionNoteFieldDef) -> str:
    if field.unit:
        return f"{field.label} ({field.unit})"
    return field.label


def _make_field_widget(field: SessionNoteFieldDef) -> W.Widget:
    layout = W.Layout(width="340px")
    description = _field_label(field)
    if field.field_type == "bool":
        return W.Checkbox(
            value=bool(field.default) if field.default is not None else False,
            description=description,
            indent=False,
            layout=layout,
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
        )
    if field.field_type == "multi_enum":
        return W.SelectMultiple(
            options=list(field.enum_options),
            value=tuple(field.default or ()),
            description=description,
            rows=min(max(len(field.enum_options), 2), 6),
            layout=layout,
        )
    if field.field_type == "text":
        return W.Textarea(
            value=str(field.default or ""),
            description=description,
            layout=W.Layout(width="520px", height="90px"),
        )
    return W.Text(
        value="" if field.default is None else str(field.default),
        description=description,
        layout=layout,
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
    show_ids_cb = W.Checkbox(
        value=bool(show_ids_default),
        description="Show run and session IDs",
        indent=False,
        layout=W.Layout(width="250px"),
    )
    b_refresh = W.Button(description="Refresh")
    sessions_sel = W.Select(
        options=[],
        value=None,
        rows=rows,
        description="Sessions",
        layout=W.Layout(width="920px"),
    )

    w_run_desc = W.Textarea(
        value="",
        description="Run desc",
        layout=W.Layout(width="520px", height="70px"),
    )
    w_session_desc = W.Textarea(
        value="",
        description="Session desc",
        layout=W.Layout(width="520px", height="70px"),
    )
    b_save_desc = W.Button(description="Save descriptions")

    templates = template_store.list_templates()
    template_options = [(_template_label(t), f"{t.template_id}@{t.template_version}") for t in templates]
    w_template = W.Dropdown(
        options=template_options or [("(No templates found)", "")],
        value=(template_options[0][1] if template_options else ""),
        description="Template",
        layout=W.Layout(width="520px"),
    )
    b_load_note = W.Button(description="Load note")
    b_new_note = W.Button(description="New from template")
    b_save_note = W.Button(description="Save note")
    w_note_title = W.Text(
        value="",
        description="Note title",
        layout=W.Layout(width="520px"),
    )
    w_custom_json = W.Textarea(
        value="{}",
        description="Custom",
        layout=W.Layout(width="520px", height="90px"),
    )
    w_free_text = W.Textarea(
        value="",
        description="Notes",
        layout=W.Layout(width="520px", height="120px"),
    )
    metadata_html = W.HTML()
    fields_box = W.VBox()
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
        "current_note": None,
        "current_template": None,
        "field_defs": {},
        "field_widgets": {},
        "updating": False,
    }

    def _status(lines: Sequence[str]) -> None:
        with status_out:
            status_out.clear_output()
            for line in lines:
                print(line)

    def _selected_row() -> Mapping[str, Any] | None:
        key = state["label_to_session_key"].get(str(sessions_sel.value or ""))
        if not key:
            return None
        return state["session_key_to_row"].get(key)

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
        filter_text = str(w_filter.value or "").strip().lower()
        label_counts: dict[str, int] = {}

        for _, row in catalog_df.iterrows():
            row_dict = row.to_dict()
            label = _format_session_label(row_dict, show_ids=bool(show_ids_cb.value))
            search_blob = " ".join(
                str(value)
                for value in row_dict.values()
                if value is not None and not (isinstance(value, float) and pd.isna(value))
            ).lower()
            if filter_text and filter_text not in search_blob:
                continue
            n = label_counts.get(label, 0) + 1
            label_counts[label] = n
            unique_label = label if n == 1 else f"{label} [#{n}]"
            session_key = str(row_dict["session_key"])
            options.append(unique_label)
            label_to_session_key[unique_label] = session_key
            session_key_to_row[session_key] = row_dict

        previous = str(sessions_sel.value or "")
        sessions_sel.options = options
        sessions_sel.value = previous if previous in label_to_session_key else (options[0] if options else None)
        state["label_to_session_key"] = label_to_session_key
        state["session_key_to_row"] = session_key_to_row

    def _render_metadata(run_id: str, session_id: str, row: Mapping[str, Any], note: SessionNoteDocument | None) -> None:
        note_part = "None"
        if note is not None:
            note_part = f"{note.template_id}@{note.template_version} | updated {note.updated_at_utc}"
        metadata_html.value = (
            "<div style='font-family:monospace'>"
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

    def _load_note_into_controls(note: SessionNoteDocument | None, template: SessionNoteTemplate) -> None:
        _build_fields(template)
        state["current_note"] = note
        w_note_title.value = "" if note is None or note.title is None else str(note.title)
        w_free_text.value = "" if note is None or note.free_text_notes is None else str(note.free_text_notes)
        w_custom_json.value = json.dumps(
            {} if note is None else note.custom_values,
            indent=2,
            sort_keys=True,
        )

        value_source: dict[str, Any] = {}
        if note is not None:
            value_source.update(note.values)
        for field in template.fields:
            _set_widget_value(
                state["field_widgets"][field.field_id],
                field,
                value_source.get(field.field_id, field.default),
            )

    def _refresh_editor(*_) -> None:
        row = _selected_row()
        if not row:
            metadata_html.value = "<i>No session selected.</i>"
            fields_box.children = ()
            w_run_desc.value = ""
            w_session_desc.value = ""
            w_note_title.value = ""
            w_custom_json.value = "{}"
            w_free_text.value = ""
            state["current_note"] = None
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
            _load_note_into_controls(note, template)
        else:
            fields_box.children = (W.HTML("<i>No templates available.</i>"),)
            state["current_note"] = note
            state["current_template"] = None
            state["field_defs"] = {}
            state["field_widgets"] = {}

        _render_metadata(run_id, session_id, row, note)

    def _refresh_all(*_) -> None:
        _refresh_session_options()
        _refresh_editor()
        aggregation_manager["refresh"]()

    def _on_template_change(change: Mapping[str, Any]) -> None:
        if state["updating"]:
            return
        new_value = str(change.get("new") or "")
        if not new_value:
            return
        template_id, template_version = new_value.split("@", 1)
        template = template_store.get_template(template_id, template_version)
        note = state.get("current_note")
        if note is not None and note.template_id == template_id and note.template_version == template_version:
            _load_note_into_controls(note, template)
            return
        _load_note_into_controls(None, template)

    def _on_select(_):
        _refresh_editor()

    def _on_save_descriptions(_):
        ids = _selected_ids()
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
        _status([f"Saved run/session descriptions for {run_id}::{session_id}."])

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
        row = _selected_row()
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
        _load_note_into_controls(note, template)
        _render_metadata(str(row["run_id"]), str(row["session_id"]), row, note)
        _status([f"Loaded note for {row['session_key']}."])

    def _on_new_note(_):
        ids = _selected_ids()
        template = _selected_template()
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
        _load_note_into_controls(note, template)
        _status([f"Prepared new note for {run_id}::{session_id} from {template.template_id}@{template.template_version}."])

    def _on_save_note(_):
        ids = _selected_ids()
        template = state.get("current_template")
        if ids is None:
            _status(["Select a session before saving a note."])
            return
        if template is None:
            _status(["No note template is selected."])
            return
        run_id, session_id = ids
        note = state.get("current_note")
        if note is None or note.template_id != template.template_id or note.template_version != template.template_version:
            note = note_store.create_note_from_template(
                run_id=run_id,
                session_id=session_id,
                template_id=template.template_id,
                template_version=template.template_version,
            )
        try:
            updated = note_store.update_note(
                note,
                values=_collect_note_values(),
                custom_values=_parse_custom_values(),
                free_text_notes=_coerce_text_value(w_free_text.value),
                title=_coerce_text_value(w_note_title.value),
            )
            saved = note_store.save_note(updated)
        except Exception as exc:
            _status([f"Failed to save note: {exc}"])
            return
        state["current_note"] = saved
        _refresh_all()
        _status([f"Saved session note for {run_id}::{session_id}."])

    w_template.observe(_on_template_change, names="value")
    sessions_sel.observe(_on_select, names="value")
    b_refresh.on_click(_refresh_all)
    b_save_desc.on_click(_on_save_descriptions)
    b_load_note.on_click(_on_load_note)
    b_new_note.on_click(_on_new_note)
    b_save_note.on_click(_on_save_note)
    show_ids_cb.observe(_refresh_session_options, names="value")
    w_filter.observe(_refresh_session_options, names="value")

    session_controls = W.HBox([w_filter, show_ids_cb, b_refresh])
    description_box = W.VBox(
        [
            W.HTML("<b>Descriptions</b>"),
            w_run_desc,
            w_session_desc,
            b_save_desc,
        ],
        layout=W.Layout(width="540px"),
    )
    note_controls = W.HBox([w_template, b_load_note, b_new_note, b_save_note])
    note_box = W.VBox(
        [
            W.HTML("<b>Session note</b>"),
            note_controls,
            w_note_title,
            fields_box,
            w_custom_json,
            w_free_text,
        ],
        layout=W.Layout(width="560px"),
    )
    right_col = W.VBox(
        [
            metadata_html,
            description_box,
            note_box,
            details,
            status_out,
        ],
        layout=W.Layout(width="620px"),
    )
    sessions_tab = W.HBox(
        [
            W.VBox([session_controls, sessions_sel], layout=W.Layout(width="940px")),
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
            "show_ids": show_ids_cb,
            "sessions": sessions_sel,
            "run_description": w_run_desc,
            "session_description": w_session_desc,
            "template": w_template,
            "note_title": w_note_title,
            "custom_json": w_custom_json,
            "free_text": w_free_text,
        },
        "state": state,
    }
