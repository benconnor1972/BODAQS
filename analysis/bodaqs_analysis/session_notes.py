from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, Mapping, Optional, Sequence

import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore, list_runs, list_sessions

FieldType = Literal["string", "text", "int", "float", "bool", "enum", "multi_enum", "date"]
ProjectionPolicy = Literal["stored_version", "exact_version", "latest_compatible"]

TEMPLATE_SCHEMA = "bodaqs.session_notes.template"
TEMPLATE_VERSION = 1
NOTE_SCHEMA = "bodaqs.session_notes.document"
NOTE_VERSION = 1
DEFAULT_TEMPLATE_ROOT = Path("Configs") / "session_note_templates"


class SessionNotesError(ValueError):
    pass


class SessionNoteValidationError(SessionNotesError):
    pass


@dataclass(frozen=True)
class SessionNoteFieldDef:
    field_id: str
    label: str
    field_type: FieldType
    section: str = "General"
    required: bool = False
    default: Any | None = None
    unit: str | None = None
    help_text: str | None = None
    enum_options: tuple[str, ...] = ()
    project_to_catalog: bool = True
    sortable: bool = True
    filterable: bool = True


@dataclass(frozen=True)
class SessionNoteTemplate:
    template_id: str
    template_version: str
    title: str
    description: str | None
    fields: tuple[SessionNoteFieldDef, ...]
    allow_custom_fields: bool = True
    custom_field_section: str = "Custom"
    created_at_utc: str = ""
    supersedes_version: str | None = None


@dataclass(frozen=True)
class SessionNoteDocument:
    schema: str
    version: int
    run_id: str
    session_id: str
    session_key: str
    template_id: str
    template_version: str
    title: str | None
    values: Dict[str, Any]
    custom_values: Dict[str, Any]
    free_text_notes: str | None
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True)
class CatalogProjectionConfig:
    template_id: str
    projection_version: str | None
    policy: ProjectionPolicy = "latest_compatible"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_session_key(run_id: str, session_id: str) -> str:
    return f"{run_id}::{session_id}"


def default_template_root() -> Path:
    return Path(__file__).resolve().parents[2] / DEFAULT_TEMPLATE_ROOT


def _is_int_like(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_float_like(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)) or value is None


def _validate_field_value(field: SessionNoteFieldDef, value: Any) -> None:
    if value is None:
        if field.required:
            raise SessionNoteValidationError(f"Field {field.field_id!r} is required")
        return

    ftype = field.field_type
    if ftype in {"string", "text", "date"}:
        if not isinstance(value, str):
            raise SessionNoteValidationError(f"Field {field.field_id!r} must be a string")
        return

    if ftype == "int":
        if not _is_int_like(value):
            raise SessionNoteValidationError(f"Field {field.field_id!r} must be an int")
        return

    if ftype == "float":
        if not _is_float_like(value):
            raise SessionNoteValidationError(f"Field {field.field_id!r} must be numeric")
        return

    if ftype == "bool":
        if not isinstance(value, bool):
            raise SessionNoteValidationError(f"Field {field.field_id!r} must be a bool")
        return

    if ftype == "enum":
        if not isinstance(value, str):
            raise SessionNoteValidationError(f"Field {field.field_id!r} must be a string enum")
        if field.enum_options and value not in field.enum_options:
            raise SessionNoteValidationError(
                f"Field {field.field_id!r} must be one of {list(field.enum_options)!r}"
            )
        return

    if ftype == "multi_enum":
        if not isinstance(value, (list, tuple)):
            raise SessionNoteValidationError(f"Field {field.field_id!r} must be a list")
        invalid = [item for item in value if not isinstance(item, str)]
        if invalid:
            raise SessionNoteValidationError(
                f"Field {field.field_id!r} multi_enum values must be strings"
            )
        if field.enum_options:
            unknown = [item for item in value if item not in field.enum_options]
            if unknown:
                raise SessionNoteValidationError(
                    f"Field {field.field_id!r} contains invalid options: {unknown!r}"
                )
        return

    raise SessionNoteValidationError(f"Unsupported field type: {ftype!r}")


def _field_from_mapping(data: Mapping[str, Any]) -> SessionNoteFieldDef:
    field_id = str(data.get("field_id") or "").strip()
    label = str(data.get("label") or "").strip()
    field_type = str(data.get("field_type") or "").strip()

    if not field_id:
        raise SessionNoteValidationError("Template field is missing field_id")
    if not label:
        raise SessionNoteValidationError(f"Template field {field_id!r} is missing label")
    if field_type not in {"string", "text", "int", "float", "bool", "enum", "multi_enum", "date"}:
        raise SessionNoteValidationError(
            f"Template field {field_id!r} has unsupported field_type {field_type!r}"
        )

    field = SessionNoteFieldDef(
        field_id=field_id,
        label=label,
        field_type=field_type,  # type: ignore[arg-type]
        section=str(data.get("section") or "General"),
        required=bool(data.get("required", False)),
        default=data.get("default"),
        unit=(None if data.get("unit") is None else str(data.get("unit"))),
        help_text=(None if data.get("help_text") is None else str(data.get("help_text"))),
        enum_options=tuple(map(str, data.get("enum_options", ()) or ())),
        project_to_catalog=bool(data.get("project_to_catalog", True)),
        sortable=bool(data.get("sortable", True)),
        filterable=bool(data.get("filterable", True)),
    )
    _validate_field_value(field, field.default)
    return field


def _template_from_mapping(data: Mapping[str, Any]) -> SessionNoteTemplate:
    if str(data.get("schema") or "") != TEMPLATE_SCHEMA:
        raise SessionNoteValidationError("Invalid session note template schema")
    if int(data.get("version", -1)) != TEMPLATE_VERSION:
        raise SessionNoteValidationError("Invalid session note template version")

    template_id = str(data.get("template_id") or "").strip()
    template_version = str(data.get("template_version") or "").strip()
    title = str(data.get("title") or "").strip()
    fields_raw = data.get("fields")

    if not template_id:
        raise SessionNoteValidationError("Template missing template_id")
    if not template_version:
        raise SessionNoteValidationError("Template missing template_version")
    if not title:
        raise SessionNoteValidationError("Template missing title")
    if not isinstance(fields_raw, list) or not fields_raw:
        raise SessionNoteValidationError("Template fields must be a non-empty list")

    fields = tuple(_field_from_mapping(row) for row in fields_raw if isinstance(row, Mapping))
    if len(fields) != len(fields_raw):
        raise SessionNoteValidationError("Template contains invalid field entries")

    seen: set[str] = set()
    for field in fields:
        if field.field_id in seen:
            raise SessionNoteValidationError(f"Duplicate field_id in template: {field.field_id}")
        seen.add(field.field_id)

    return SessionNoteTemplate(
        template_id=template_id,
        template_version=template_version,
        title=title,
        description=(None if data.get("description") is None else str(data.get("description"))),
        fields=fields,
        allow_custom_fields=bool(data.get("allow_custom_fields", True)),
        custom_field_section=str(data.get("custom_field_section") or "Custom"),
        created_at_utc=str(data.get("created_at_utc") or ""),
        supersedes_version=(
            None if data.get("supersedes_version") is None else str(data.get("supersedes_version"))
        ),
    )


def _template_to_mapping(template: SessionNoteTemplate) -> dict[str, Any]:
    data = asdict(template)
    data["schema"] = TEMPLATE_SCHEMA
    data["version"] = TEMPLATE_VERSION
    data["fields"] = [asdict(field) for field in template.fields]
    return data


def _document_from_mapping(data: Mapping[str, Any]) -> SessionNoteDocument:
    if str(data.get("schema") or "") != NOTE_SCHEMA:
        raise SessionNoteValidationError("Invalid session note document schema")
    if int(data.get("version", -1)) != NOTE_VERSION:
        raise SessionNoteValidationError("Invalid session note document version")

    run_id = str(data.get("run_id") or "").strip()
    session_id = str(data.get("session_id") or "").strip()
    session_key = str(data.get("session_key") or "").strip()
    template_id = str(data.get("template_id") or "").strip()
    template_version = str(data.get("template_version") or "").strip()

    if not run_id or not session_id or not session_key:
        raise SessionNoteValidationError("Session note document is missing session identity")
    if session_key != make_session_key(run_id, session_id):
        raise SessionNoteValidationError("session_key must match run_id::session_id")
    if not template_id or not template_version:
        raise SessionNoteValidationError("Session note document is missing template identity")

    values = data.get("values", {})
    custom_values = data.get("custom_values", {})
    if not isinstance(values, Mapping):
        raise SessionNoteValidationError("values must be an object")
    if not isinstance(custom_values, Mapping):
        raise SessionNoteValidationError("custom_values must be an object")

    return SessionNoteDocument(
        schema=NOTE_SCHEMA,
        version=NOTE_VERSION,
        run_id=run_id,
        session_id=session_id,
        session_key=session_key,
        template_id=template_id,
        template_version=template_version,
        title=(None if data.get("title") is None else str(data.get("title"))),
        values={str(k): v for k, v in dict(values).items()},
        custom_values={str(k): v for k, v in dict(custom_values).items()},
        free_text_notes=(
            None if data.get("free_text_notes") is None else str(data.get("free_text_notes"))
        ),
        created_at_utc=str(data.get("created_at_utc") or ""),
        updated_at_utc=str(data.get("updated_at_utc") or ""),
    )


def _document_to_mapping(doc: SessionNoteDocument) -> dict[str, Any]:
    return asdict(doc)


class SessionNoteTemplateStore:
    def __init__(self, root: Optional[str | Path] = None):
        self.root = Path(root).expanduser() if root else default_template_root()

    def _template_paths(self) -> Iterable[Path]:
        if not self.root.exists():
            return ()
        return sorted(self.root.glob("*/*.json"))

    def list_templates(self) -> list[SessionNoteTemplate]:
        templates: list[SessionNoteTemplate] = []
        for path in self._template_paths():
            try:
                templates.append(self.load_template_file(path))
            except Exception:
                continue
        templates.sort(key=lambda t: (t.template_id, t.template_version))
        return templates

    def load_template_file(self, path: str | Path) -> SessionNoteTemplate:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return _template_from_mapping(data)

    def get_template(self, template_id: str, template_version: str) -> SessionNoteTemplate:
        path = self.root / str(template_id) / f"{template_version}.json"
        if not path.exists():
            raise SessionNotesError(f"Template not found: {template_id}@{template_version}")
        return self.load_template_file(path)

    def get_latest_template(self, template_id: str) -> SessionNoteTemplate:
        matches = [t for t in self.list_templates() if t.template_id == str(template_id)]
        if not matches:
            raise SessionNotesError(f"No templates found for template_id={template_id!r}")
        return sorted(matches, key=lambda t: t.template_version)[-1]


def validate_note_document(doc: SessionNoteDocument, template: SessionNoteTemplate) -> None:
    if doc.template_id != template.template_id or doc.template_version != template.template_version:
        raise SessionNoteValidationError("Note document template does not match validation template")

    field_map = {field.field_id: field for field in template.fields}
    unknown = [field_id for field_id in doc.values.keys() if field_id not in field_map]
    if unknown:
        raise SessionNoteValidationError(f"Unknown template field ids in note document: {unknown!r}")

    for field in template.fields:
        _validate_field_value(field, doc.values.get(field.field_id, field.default))

    if doc.custom_values and not template.allow_custom_fields:
        raise SessionNoteValidationError("Template does not allow custom fields")


class SessionNoteStore:
    def __init__(
        self,
        *,
        store: ArtifactStore,
        template_store: Optional[SessionNoteTemplateStore] = None,
    ):
        self.store = store
        self.template_store = template_store or SessionNoteTemplateStore()

    def note_path(self, *, run_id: str, session_id: str) -> Path:
        return self.store.path_session_notes(run_id, session_id)

    def load_note(self, *, run_id: str, session_id: str) -> SessionNoteDocument | None:
        path = self.note_path(run_id=run_id, session_id=session_id)
        if not path.exists():
            return None
        data = self.store.read_json(path)
        return _document_from_mapping(data)

    def save_note(self, note: SessionNoteDocument) -> SessionNoteDocument:
        template = self.template_store.get_template(note.template_id, note.template_version)
        validate_note_document(note, template)
        self.store.write_json(self.note_path(run_id=note.run_id, session_id=note.session_id), _document_to_mapping(note))
        return note

    def create_note_from_template(
        self,
        *,
        run_id: str,
        session_id: str,
        template_id: str,
        template_version: str | None = None,
        title: str | None = None,
    ) -> SessionNoteDocument:
        template = (
            self.template_store.get_template(template_id, template_version)
            if template_version
            else self.template_store.get_latest_template(template_id)
        )
        ts = now_utc_iso()
        doc = SessionNoteDocument(
            schema=NOTE_SCHEMA,
            version=NOTE_VERSION,
            run_id=str(run_id),
            session_id=str(session_id),
            session_key=make_session_key(str(run_id), str(session_id)),
            template_id=template.template_id,
            template_version=template.template_version,
            title=title,
            values={field.field_id: field.default for field in template.fields if field.default is not None},
            custom_values={},
            free_text_notes=None,
            created_at_utc=ts,
            updated_at_utc=ts,
        )
        validate_note_document(doc, template)
        return doc

    def update_note(
        self,
        note: SessionNoteDocument,
        *,
        values: Optional[Mapping[str, Any]] = None,
        custom_values: Optional[Mapping[str, Any]] = None,
        free_text_notes: Optional[str | None] = None,
        title: Optional[str | None] = None,
    ) -> SessionNoteDocument:
        updated = SessionNoteDocument(
            schema=note.schema,
            version=note.version,
            run_id=note.run_id,
            session_id=note.session_id,
            session_key=note.session_key,
            template_id=note.template_id,
            template_version=note.template_version,
            title=note.title if title is None else title,
            values={
                **dict(note.values),
                **({str(k): v for k, v in dict(values).items()} if values else {}),
            },
            custom_values=(
                dict(note.custom_values)
                if custom_values is None
                else {str(k): v for k, v in dict(custom_values).items()}
            ),
            free_text_notes=note.free_text_notes if free_text_notes is None else free_text_notes,
            created_at_utc=note.created_at_utc,
            updated_at_utc=now_utc_iso(),
        )
        template = self.template_store.get_template(updated.template_id, updated.template_version)
        validate_note_document(updated, template)
        return updated


def _read_json_safe(store: ArtifactStore, path: Path) -> dict[str, Any]:
    try:
        return store.read_json(path)
    except Exception:
        return {}


def _run_manifest_fields(store: ArtifactStore, run_id: str) -> dict[str, Any]:
    data = _read_json_safe(store, store.path_run_manifest(run_id))
    return {
        "created_at": data.get("created_at"),
        "run_description": data.get("description"),
    }


def _session_manifest_fields(store: ArtifactStore, run_id: str, session_id: str) -> dict[str, Any]:
    data = _read_json_safe(store, store.path_session_manifest(run_id, session_id))
    return {
        "session_description": data.get("description"),
    }


def _project_note_fields(
    note: SessionNoteDocument,
    *,
    template_store: SessionNoteTemplateStore,
    config: CatalogProjectionConfig | None,
) -> tuple[dict[str, Any], str]:
    policy = "stored_version" if config is None else str(config.policy)

    if policy == "stored_version":
        target = template_store.get_template(note.template_id, note.template_version)
    elif policy == "exact_version":
        if config is None or not config.projection_version:
            raise SessionNotesError("exact_version projection requires projection_version")
        target = template_store.get_template(note.template_id, config.projection_version)
    elif policy == "latest_compatible":
        target = (
            template_store.get_template(note.template_id, config.projection_version)
            if config is not None and config.projection_version
            else template_store.get_latest_template(note.template_id)
        )
    else:
        raise SessionNotesError(f"Unsupported projection policy: {policy!r}")

    stored = template_store.get_template(note.template_id, note.template_version)
    stored_fields = {field.field_id: field for field in stored.fields}

    projected: dict[str, Any] = {}
    status = "ok"
    for field in target.fields:
        if not field.project_to_catalog:
            continue
        stored_field = stored_fields.get(field.field_id)
        if stored_field is None:
            projected[f"note.{field.field_id}"] = field.default
            continue
        if stored_field.field_type != field.field_type:
            projected[f"note.{field.field_id}"] = None
            status = "mismatch"
            continue
        projected[f"note.{field.field_id}"] = note.values.get(field.field_id, field.default)

    return projected, status


def build_session_catalog_df(
    *,
    artifacts_dir: str | Path = "artifacts",
    template_root: str | Path | None = None,
    projection_configs: Sequence[CatalogProjectionConfig] = (),
) -> pd.DataFrame:
    store = ArtifactStore(Path(artifacts_dir))
    template_store = SessionNoteTemplateStore(template_root)
    note_store = SessionNoteStore(store=store, template_store=template_store)
    projection_by_template = {cfg.template_id: cfg for cfg in projection_configs}

    rows: list[dict[str, Any]] = []
    for run_id in list_runs(store):
        run_fields = _run_manifest_fields(store, run_id)
        for session_id in list_sessions(store, run_id):
            row: dict[str, Any] = {
                "run_id": str(run_id),
                "session_id": str(session_id),
                "session_key": make_session_key(str(run_id), str(session_id)),
                "created_at": run_fields.get("created_at"),
                "run_description": run_fields.get("run_description"),
                **_session_manifest_fields(store, run_id, session_id),
                "note_template_id": None,
                "note_template_version": None,
                "note_updated_at_utc": None,
                "projection_status": "missing_note",
            }
            note = note_store.load_note(run_id=run_id, session_id=session_id)
            if note is not None:
                row["note_template_id"] = note.template_id
                row["note_template_version"] = note.template_version
                row["note_updated_at_utc"] = note.updated_at_utc
                try:
                    projected, status = _project_note_fields(
                        note,
                        template_store=template_store,
                        config=projection_by_template.get(note.template_id),
                    )
                    row.update(projected)
                    row["projection_status"] = status
                except SessionNotesError:
                    row["projection_status"] = "template_missing"
            rows.append(row)

    return pd.DataFrame(rows)
