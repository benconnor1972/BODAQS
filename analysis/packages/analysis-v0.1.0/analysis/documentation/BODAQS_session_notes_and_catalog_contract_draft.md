# BODAQS Session Notes and Catalog Contract (Draft)

**Status:** Draft  
**Scope:** Canonical run/session library management in analysis tooling  
**Primary goal:** support editable descriptions, canonical structured session notes, reusable note templates, and later catalog filtering/sorting over both note fields and selected artifact metadata

---

## 1. Summary

This contract introduces a **canonical session-note layer** that is separate from:

- brief run/session descriptions already stored in manifests
- pipeline-derived technical metadata in `meta.json`
- personal/local UI state such as bookmarks

The note layer is intended to support:

- rich structured session setup notes
- reusable templates
- controlled template evolution over time
- stable field identities for filtering and sorting

This contract is intentionally **session-centric**:

- session notes are canonical
- run-level notes are out of scope for v1
- sessions do **not** inherit notes from runs

---

## 2. Architectural boundaries

### 2.1 Keep as-is

Run/session descriptions remain in canonical manifests:

- `artifacts/runs/<run_id>/manifest.json`
- `artifacts/runs/<run_id>/sessions/<session_id>/manifest.json`

These are short identity/description fields, not the main structured note store.

### 2.2 Do not use for session notes

Do **not** store canonical user-authored structured notes in:

- session `meta.json`
- manifest `summary`
- ad hoc extra manifest root fields without an explicit note contract

Reason:

- `meta.json` is pipeline-facing
- `summary` is derived/technical summary data
- unstructured manifest expansion is fragile under rewrite/reprocess workflows

### 2.3 New canonical note layer

Canonical session notes should live in a separate session-attached document with an explicit contract.

Recommended location:

```text
artifacts/runs/<run_id>/sessions/<session_id>/annotations/session_notes.json
```

Templates should live centrally, outside individual sessions.

Recommended location:

```text
analysis/templates/session_note_templates/<template_id>/<version>.json
```

---

## 3. Design principles

1. **Canonical, not per-user**
   Session notes are part of the canonical library, not local UI state.

2. **Structured enough to query**
   Fields must have stable ids and basic types.

3. **Flexible enough to evolve**
   Template versions may change over time.

4. **Do not hard-code one global schema**
   Different note templates may coexist.

5. **Projection for filtering is explicit**
   Filtering should run against a catalog projection, not arbitrary raw note JSON.

---

## 4. Core concepts

### 4.1 Template

A template defines:

- stable template identity
- versioned field definitions
- defaults for new note documents
- which fields are intended for catalog projection/filtering

### 4.2 Session note document

A session note document is the canonical stored note attached to a session.

It records:

- which template/version it was created from
- typed field values
- optional custom fields
- timestamps and edit metadata

### 4.3 Catalog projection

The library browser/filter layer should not query arbitrary note JSON directly.

Instead it should build a flattened catalog projection per session using:

- selected artifact metadata
- run/session descriptions
- projected note fields from the chosen template-version resolution policy

---

## 5. Template contract

### 5.1 Template identity

```python
TemplateId = str
TemplateVersion = str
FieldId = str
```

Rules:

- `template_id` is stable across revisions
- `template_version` is immutable once published
- field ids are stable within a template lineage

### 5.2 Field types

Supported v1 field types:

```python
FieldType = Literal[
    "string",
    "text",
    "int",
    "float",
    "bool",
    "enum",
    "multi_enum",
    "date",
]
```

Notes:

- `text` is long-form text, not intended for numeric filtering
- `enum` and `multi_enum` should define explicit allowed values
- later field types may be added, but these are sufficient for suspension settings/configuration data

### 5.3 Template field definition

```python
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
```

Rules:

- `field_id` is the canonical storage and filter key
- `label` is presentation only
- `project_to_catalog=False` means the field is stored but not included in the flattened filter projection
- `sortable` / `filterable` are advisory UI hints

### 5.4 Template document

```python
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
```

Rules:

- template versions are immutable
- template evolution occurs by publishing a new version
- `supersedes_version` is informational; it does not imply automatic migration

---

## 6. Session note document contract

### 6.1 Stored document

```python
@dataclass(frozen=True)
class SessionNoteDocument:
    schema: Literal["bodaqs.session_notes.document"]
    version: int
    run_id: str
    session_id: str
    session_key: str
    template_id: str
    template_version: str
    title: str | None
    values: dict[str, Any]
    custom_values: dict[str, Any]
    free_text_notes: str | None
    created_at_utc: str
    updated_at_utc: str
```

Recommended on-disk JSON shape:

```json
{
  "schema": "bodaqs.session_notes.document",
  "version": 1,
  "run_id": "run_2026-03-12T20-17-49_AWST",
  "session_id": "session_001",
  "session_key": "run_2026-03-12T20-17-49_AWST::session_001",
  "template_id": "suspension_setup",
  "template_version": "1.1",
  "title": "Maydena baseline setup",
  "values": {
    "front_spring_rate": 38.0,
    "rear_spring_rate": 420.0,
    "fork_tokens": 2,
    "shock_hsc": "middle"
  },
  "custom_values": {
    "fork_air_can_service_hours": 6.0
  },
  "free_text_notes": "Rear felt harsh on repeated square edges.",
  "created_at_utc": "2026-03-15T10:02:11Z",
  "updated_at_utc": "2026-03-15T10:15:47Z"
}
```

### 6.2 Validation rules

- `schema` must equal `bodaqs.session_notes.document`
- `version` must equal `1`
- `session_key` must match `run_id::session_id`
- `template_id` and `template_version` are required
- `values` may only contain known template field ids for the referenced template version
- `custom_values` may contain arbitrary keys only if `allow_custom_fields=True` on the template

### 6.3 Custom fields

Custom fields are allowed, but they must be isolated:

- template-defined fields go in `values`
- ad hoc user-added fields go in `custom_values`

This preserves:

- stable projection/filter fields from templates
- flexibility for exceptional cases

---

## 7. Template evolution and mismatch handling

Template versions are expected to evolve over time.

This contract separates:

- the **stored document version** used when the note was authored
- the **projection version** used for catalog filtering/sorting

### 7.1 Projection config

```python
ProjectionPolicy = Literal[
    "stored_version",
    "exact_version",
    "latest_compatible",
]

@dataclass(frozen=True)
class CatalogProjectionConfig:
    template_id: str
    projection_version: str | None
    policy: ProjectionPolicy = "latest_compatible"
```

Semantics:

- `stored_version`
  - project using the note document's own stored template version
- `exact_version`
  - project using the explicitly selected `projection_version`
  - non-matching sessions are projected with compatibility warnings/errors
- `latest_compatible`
  - project onto the selected or latest known version using compatibility rules

### 7.2 Compatibility rules

Compatibility should be field-id based, not label based.

Recommended v1 rules:

1. If a field id exists in both stored and projection versions with compatible type:
   - carry value through

2. If a field id exists in the stored document but not in the projection version:
   - retain in raw note document
   - exclude from projection
   - surface as dropped/unprojected metadata if needed

3. If a field id exists in the projection version but not in the stored version:
   - projected value is null/default

4. If the same field id exists with incompatible type:
   - mark projection mismatch
   - projected value becomes null unless a migration rule is defined

5. Custom fields:
   - remain stored
   - are not filter-projected by default
   - may be opt-in projected later via explicit config, not automatically

### 7.3 Migration rules

Migration is optional in v1.

If later needed, introduce explicit migration declarations:

```python
@dataclass(frozen=True)
class FieldMigrationRule:
    from_version: str
    to_version: str
    old_field_id: str
    new_field_id: str
    transform: str | None = None
```

Do not introduce automatic migration before the base note/template/catalog contracts are working.

---

## 8. Catalog projection contract

### 8.1 Session catalog row

The library UI should work from a flattened session catalog dataframe.

Canonical row shape:

```python
@dataclass(frozen=True)
class SessionCatalogRow:
    run_id: str
    session_id: str
    session_key: str
    created_at: str | None
    run_description: str | None
    session_description: str | None
    note_template_id: str | None
    note_template_version: str | None
    note_updated_at_utc: str | None
    projection_status: Literal["ok", "missing_note", "template_missing", "mismatch"]
    projected_fields: dict[str, Any]
```

In dataframe form, `projected_fields` should be flattened to stable column names, for example:

```text
note.front_spring_rate
note.rear_spring_rate
note.fork_tokens
note.shock_hsc
```

### 8.2 Filter sources

The catalog may derive filters from:

- canonical manifest fields
  - `created_at`
  - `run_description`
  - `session_description`
- projected note fields from the active `CatalogProjectionConfig`

It should not derive filters directly from raw `custom_values` by default.

---

## 9. Service/API boundaries

### 9.1 Template store

```python
class SessionNoteTemplateStore(Protocol):
    def list_templates(self) -> list[SessionNoteTemplate]: ...
    def get_template(self, template_id: str, template_version: str) -> SessionNoteTemplate: ...
    def get_latest_template(self, template_id: str) -> SessionNoteTemplate: ...
```

### 9.2 Session note store

```python
class SessionNoteStore(Protocol):
    def load_note(self, *, run_id: str, session_id: str) -> SessionNoteDocument | None: ...
    def save_note(self, note: SessionNoteDocument) -> SessionNoteDocument: ...
    def create_note_from_template(
        self,
        *,
        run_id: str,
        session_id: str,
        template_id: str,
        template_version: str | None = None,
    ) -> SessionNoteDocument: ...
```

### 9.3 Catalog service

```python
class SessionCatalogService(Protocol):
    def build_catalog_df(
        self,
        *,
        artifacts_dir: str | Path = "artifacts",
        projection_configs: Sequence[CatalogProjectionConfig] = (),
    ) -> pd.DataFrame: ...
```

---

## 10. UI implications

The library-management UI should be built on top of the catalog service, not by directly scanning files in widget code.

Recommended v1 UI capabilities:

1. browse sessions in a flat table
2. inspect manifest metadata
3. edit run/session descriptions
4. create/edit session note document from a chosen template
5. filter/sort using projected note fields and selected metadata fields

This should be implemented as a dedicated library-management view, not inside the entity selector.

---

## 11. Explicit non-goals for v1

- run-level note inheritance
- arbitrary nested-object filtering
- automatic migration between template versions
- mixing canonical session notes with per-user bookmarks/local state
- pushing note editing directly into existing plotting widgets

---

## 12. Recommended implementation order

1. Finalize this note/template/catalog contract
2. Implement template-store and note-store services
3. Implement catalog projection service
4. Build a minimal library browser/editor notebook or widget
5. Add filter/sort UI over the flattened catalog
6. Integrate catalog-driven filtering with session/entity selection later
