# BODAQS Import Agent CLI (v1)

**Status:** Initial implementation  
**Scope:** Windows-first packaged CLI for local archive import into the existing BODAQS artifact library

---

## 1. Summary

The BODAQS Import Agent CLI watches one or more **import sources** and imports
session archives into a canonical BODAQS artifact library using the existing
analysis pipeline.

Version 1 is intentionally narrow:

- local-first only
- packaged CLI first
- Windows-first deployment target
- one archive = one session
- optional FIT enrichment from the source-local `fit/` directory
- no generic log-metadata fallback
- existing artifact contract preserved

---

## 2. Import Source Layout

Each watched source is a directory containing:

```text
<source_root>/
  import_source.json
  settings/
    <exactly one valid preprocess profile JSON>
    event_schema.yaml
  notes/
    <exactly one valid session-note template JSON>
    <exactly one valid bike setup preset JSON>
  fit/
  inbox/
  done/
  failed/
  staging/
```

Relative paths in `import_source.json` resolve relative to that file.
The `preprocess_profile_path` and `bike_profile_path` fields may point either
to a specific JSON file or to a directory. When a directory is used, it must
contain exactly one valid JSON file for that profile type. New Import Manager
sources normally point `bike_profile_path` at a specific shared profile file
under the common libraries root's `bike_profiles/` directory. Legacy source-local
`bike/` directories remain valid if they contain exactly one bike profile JSON.
The event schema YAML can live alongside the preprocess profile inside
`settings/`.

Managed workspaces created by the Import Manager include shared bike profiles:

```text
<libraries_root>/
  bike_profiles/
    <one or more valid bike profile JSON files>
  <library>/
    runs/
    library/
```

If `session_note.attach_on_import` is enabled in `import_source.json`, the
`notes/` directory is also used at import time. The agent creates a draft
session note from the setup preset, records the linked bike profile and preset
in the note `source_context`, and copies the template into the target library.

Multiple sources may target the same central artifact library.

If `fit_import.enabled` is true in the preprocess profile, the import agent
looks for fully copied `.fit` files in `fit/`, selects the largest-overlap FIT
file, leaves the original FIT file in place, and records a QC warning rather
than failing the import if FIT enrichment cannot be applied.

---

## 3. Archive Contract

Each archive must contain exactly two files at the archive root:

- one `.csv`
- one `.json`

The two files must share the same basename, for example:

```text
2026-05-16_10-00-00.CSV
2026-05-16_10-00-00.json
```

Version 1 rejects:

- nested archive members
- archives with multiple CSV files
- archives with multiple JSON files
- archives where the CSV and JSON stems do not match

The `.json` is passed to preprocessing as the explicit session log metadata
file. There is no generic fallback selection in this workflow.

---

## 4. CLI Commands

The CLI accepts either:

- a source directory containing `import_source.json`, or
- a direct path to `import_source.json`

### Validate

```powershell
python import-manager\bodaqs_import_agent_cli.py validate C:\BODAQS\SourceA
```

Checks:

- source config schema/version
- preprocess profile file/directory resolution and validity
- bike profile file/directory resolution and validity
- session-note template and bike setup preset validity when auto-notes are enabled
- runtime directory presence

### Once

```powershell
python import-manager\bodaqs_import_agent_cli.py once C:\BODAQS\SourceA C:\BODAQS\SourceB
```

Behavior:

1. scan each source inbox
2. defer archives younger than `settle_time_s`
3. move ready archives into `staging/`
4. validate the archive contract
5. extract the session pair to a temporary staging folder
6. run `preprocess_session(...)`
7. write canonical artifacts
8. move successful archives to `done/`
9. move failed archives to `failed/`

### Watch

```powershell
python import-manager\bodaqs_import_agent_cli.py watch C:\BODAQS\SourceA C:\BODAQS\SourceB
```

Behavior:

- repeatedly scans each source using its configured `poll_interval_s`
- uses the same import flow as `once`

---

## 5. Idempotency Model

The importer tracks state per artifact library under:

```text
artifacts/library/import_agent_state_v1.json
```

It uses two identities:

### Raw session identity

Derived from:

- CSV content hash
- session JSON content hash

### Processing key

Derived from:

- raw session identity
- preprocess profile hash
- bike profile hash

This means:

- the same archive dropped twice is skipped after the first successful import
- the same session re-zipped with identical CSV/JSON content is also skipped
- the same session can be re-imported if the preprocess or bike profile changes

---

## 6. Artifact Output

The import agent writes the existing artifact contract:

- `runs/<run_id>/manifest.json`
- `runs/<run_id>/sessions/<session_id>/manifest.json`
- `runs/<run_id>/sessions/<session_id>/source/input.csv`
- `runs/<run_id>/sessions/<session_id>/session/df.parquet`
- `runs/<run_id>/sessions/<session_id>/session/meta.json`
- optional event and metric partitions when enabled
- optional library-level `syn/` data.syn.bike CSV/helper outputs

Version 1 uses **one run per imported session**.

The session manifest `source` block includes import provenance such as:

- import source id
- import source config path
- original archive filename
- original archive SHA-256
- archive member names
- raw session identity
- processing key

If the target library enables data.syn.bike exports, the importer additionally
writes files under:

```text
<library>/syn/
```

Each imported session gets one or more headerless data.syn.bike CSV files and a
per-session helper text file with the manual settings to enter in
data.syn.bike. The export scales logger raw ranges to the configured ADC bit
count for data.syn.bike compatibility. These outputs are generated for new
imports only; older imported sessions are not backfilled by the v1 importer.

---

## 7. Locking

Each artifact library uses a best-effort single-writer lock:

```text
artifacts/library/import_agent.lock
```

This prevents two import processes from writing into the same library at once.

---

## 8. Windows Packaging

The CLI entry script for packaging is:

```text
import-manager/bodaqs_import_agent_cli.py
```

Recommended first packaging workflow:

1. build on Windows
2. test a one-folder bundle first
3. switch to one-file only after validation

The repository spec file targets a one-folder console build and excludes
notebook, plotting, and test-only modules that are not needed by the CLI.

Example PyInstaller command:

```powershell
pyinstaller --noconfirm --clean --name bodaqs-import import-manager\bodaqs_import_agent_cli.py
```

One-folder is the safer first target for scientific Python dependencies because
it is easier to debug than one-file extraction behavior.

Repository-local Windows build helper:

```powershell
powershell -ExecutionPolicy Bypass -File import-manager\build_import_manager.ps1
```

Build output:

```text
import-manager/dist/pyinstaller/bodaqs-import/bodaqs-import.exe
```

Optional first-time install of PyInstaller into the repo virtual environment:

```powershell
powershell -ExecutionPolicy Bypass -File import-manager\build_import_manager.ps1 -InstallPyInstaller
```

---

## 9. Example `import_source.json`

See:

```text
analysis/config/import_source_examples/example_import_source.json
```

That example is intended to be copied into a real source folder and edited in
place.
