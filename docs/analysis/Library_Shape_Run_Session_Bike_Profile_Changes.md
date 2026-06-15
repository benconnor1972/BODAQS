# Library Shape Changes For Downstream Users

Status: draft  
Audience: library service / session browser / study-set builder implementation

This note summarizes the current Import Manager and artifact-library shape that
downstream library consumers should assume. It focuses on the recent changes to
run/session grouping and bike-profile ownership.

## Root Concepts

There are two related roots:

- `libraries_root`: the workspace-level folder managed by Import Manager.
- `library root` or `artifacts_dir`: one actual artifact library under
  `libraries_root`.

The current managed shape is:

```text
<libraries_root>/
  bike_profiles/
    <shared bike profile JSON files>
  <library_a>/
    library_definition.json
    runs/
    library/
    syn/
  <library_b>/
    library_definition.json
    runs/
    library/
    syn/
```

`bike_profiles/` is deliberately at the `libraries_root` level, not inside an
individual library. Profiles can therefore be reused by any library under the
same `libraries_root`.

## Run And Session Structure

The canonical artifact layout inside each library remains run/session based:

```text
<library_root>/
  runs/
    <run_id>/
      manifest.json
      sessions/
        <session_id>/
          manifest.json
          source/
            input.csv | input.bdq
          source_aux/
          session/
            df.parquet
            meta.json
            streams/
              <stream_name>/
                df.parquet
                meta.json
          events/
            <schema_id>/
              events.parquet
              schema.yaml
          metrics/
            <schema_id>/
              metrics.parquet
          annotations/
            session_notes.json
```

Optional library-level outputs may also exist:

```text
<library_root>/
  library/
    aggregations_v1.json
    session_note_templates/
  syn/
    data_syn_bike_export_manifest.json
    <data.syn.bike CSV/helper files>
```

### Run Meaning

Runs are no longer necessarily one archive or one physical logger session.

For Import Manager imports, a run now represents one source scan batch for one
import source. If multiple ready archives are detected and imported during the
same scan pass, they are written under the same `run_id` as separate sessions.

Implications:

- Downstream catalog code must not assume `run_id` is a physical session.
- The stable physical-session address is `(run_id, session_id)`.
- Session browsers and study-set builders should flatten runs into sessions.
- A run may contain one session for older imports or small scan passes.
- A run may contain many sessions for bulk imports or logger upload passes.

Import Manager run ids are compact source/timestamp ids such as:

```text
<source_id>_YYMMDD_HHMMSS
```

If that folder already exists, a numeric suffix may be added.

### Run Manifest

Each run has:

```text
runs/<run_id>/manifest.json
```

Important fields for downstream consumers:

- `artifact_layout_version`
- `run_id`
- `created_at`
- `timezone`
- `description`
- `sessions`: list of `session_id` values in that run
- `pipeline_config.import_source`
- `pipeline_config.archive_import`

For multi-session import batches, `pipeline_config.archive_import` uses:

```json
{
  "schema": "bodaqs.import_source",
  "version": 1,
  "mode": "source_scan_batch_v1",
  "session_count": 2,
  "sessions": {
    "<session_id>": {
      "...": "per-session import provenance"
    }
  }
}
```

For single-session runs, older/backwards-compatible flat fields may still appear
alongside a `sessions` mapping. Consumers should prefer the per-session
`sessions[session_id]` entry when present.

### Session Manifest

Each session has:

```text
runs/<run_id>/sessions/<session_id>/manifest.json
```

Important fields for downstream consumers:

- `session_id`
- `description`
- `contracts`
- `source`
- `summary`

The `source` block records import provenance such as:

- original archive or BDQ file identity
- raw session identity
- processing key
- import source id/type/config path
- archive member hashes when applicable
- remote logger identity when imported from Wi-Fi logger

The session manifest is the best per-session provenance entry point. The run
manifest is the best batch-level entry point.

## Bike Profiles

Bike profiles are no longer owned by import sources or individual libraries in
the managed Import Manager model.

Current managed location:

```text
<libraries_root>/
  bike_profiles/
    <bike_profile_id>.json
```

Each import source still stores its selected profile as `bike_profile_path` in
its `import_source.json`. New managed sources point this at a specific shared
profile file under `<libraries_root>/bike_profiles/`.

Example source config shape:

```json
{
  "bike_profile_path": "../../libraries/bike_profiles/default_import_agent_bike.json"
}
```

Important behavior:

- Multiple sources can point at the same bike profile file.
- Multiple libraries under the same `libraries_root` can use the same bike
  profile files.
- Changing a source's target library does not imply changing its bike profile.
- `Assign bike profile` is the explicit operation that changes a source's
  selected profile.
- `Duplicate bike profile` creates a new shared profile file but does not assign
  it to the source automatically.

### Legacy Compatibility

Existing source-local profiles remain valid if a source config points at them:

```text
<source_root>/
  bike/
    bike_profile.json
```

`bike_profile_path` may still point to either:

- a specific bike profile JSON file, or
- a directory containing exactly one valid bike profile JSON file.

Downstream consumers should not infer the bike profile from folder layout.
Always use the resolved `bike_profile_path`/manifest provenance when available.

## What Downstream Code Should Do

For library service and browser work:

- Treat `libraries_root` as the workspace that owns shared bike profiles and
  one or more libraries.
- Treat each library root as the artifact store that owns `runs/`, `library/`,
  and optional `syn/`.
- Build session catalogs by iterating `runs/<run_id>/manifest.json` and each
  `runs/<run_id>/sessions/<session_id>/manifest.json`.
- Use `(run_id, session_id)` as the canonical physical-session address.
- Avoid one-run-one-session assumptions in UI labels, filters, and study-set
  storage.
- Resolve bike profile identity from session/import provenance rather than from
  a source-local `bike/` folder.
- Be prepared for older libraries where most runs contain exactly one session
  and where bike profiles may still be source-local.

