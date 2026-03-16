# Session Note Templates

Session note templates define the typed fields used by the analysis-side library manager for canonical session notes.

## Location

Templates live under:

```text
analysis/templates/session_note_templates/
```

Each template family has its own directory:

```text
analysis/templates/session_note_templates/<template_id>/<template_version>.json
```

Example:

```text
analysis/templates/session_note_templates/suspension_setup/1.0.json
```

## Naming

- `template_id`
  - stable template family name
  - use lowercase snake case where practical
  - example: `suspension_setup`

- `template_version`
  - immutable published version within that template family
  - stored as the filename without the `.json` suffix
  - example: `1.0`

## Required consistency

The filesystem path and the JSON payload should agree.

For:

```text
analysis/templates/session_note_templates/suspension_setup/1.0.json
```

the JSON should contain:

```json
{
  "template_id": "suspension_setup",
  "template_version": "1.0"
}
```

## Loader behavior

`SessionNoteTemplateStore` discovers templates with:

```text
<root>/*/*.json
```

and resolves specific templates with:

```text
<root>/<template_id>/<template_version>.json
```

If a template file is invalid JSON or fails contract validation, it will not load. Template load failures are now surfaced through:

- library logging
- `SessionNoteTemplateStore.template_load_errors()`
- library-manager status output

## Practical rules

1. Keep `template_id` stable across revisions of the same template family.
2. Publish new revisions as new files, for example `1.1.json`, not by mutating historical versions silently.
3. Keep field ids stable if existing notes will be projected or migrated forward.
4. Prefer analysis-specific assets here; do not store these templates under firmware config paths.
