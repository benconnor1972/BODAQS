# BODAQS Web Preprocessing Integration Note

**Audience:** web/API developers wrapping the BODAQS Python analysis modules  
**Scope:** single-log or batch preprocessing using supplied profiles and schemas  
**Related reference:** `analysis/documentation/BODAQS_Public_API_Contract_v0.md`

---

## Integration shape

The web service should call the BODAQS Python modules directly rather than
reimplementing preprocessing logic. For remote or uploaded inputs, the preferred
integration shape is the resolved-content API:

```python
from bodaqs_analysis import (
    build_session_from_dataframe,
    load_preprocess_config,
    parse_bike_profile,
    parse_event_schema,
    prepare_logger_dataframe,
    preprocess_resolved,
)

config = load_preprocess_config(preprocess_profile_path)
schema = parse_event_schema(event_schema_text)
bike_profile = parse_bike_profile(bike_profile_json)
df_prepared, log_metadata = prepare_logger_dataframe(
    uploaded_df,
    log_metadata=uploaded_log_metadata_json,  # optional
)
session = build_session_from_dataframe(
    df_prepared,
    source_name=uploaded_filename,
    log_metadata=log_metadata,
)

results = preprocess_resolved(
    session,
    preprocess_config=config,
    schema=schema,
    bike_profile=bike_profile,
    fit_candidates=fit_candidates,   # optional
    fit_bindings=fit_bindings,       # optional
)
```

`preprocess_resolved(...)` is the preferred backend/service entry point. It
accepts already-resolved session/schema/profile/FIT content and avoids any
assumption that the worker shares a local filesystem layout with the client.

`preprocess_session(...)` remains available as the notebook/local convenience
wrapper when the service intentionally stages files on disk and wants the older
path-based behavior.

---

## Expected inputs

For this integration case we expect to provide:

- **Log data:** one or more uploaded logger tables or CSV payloads.
- **Specific log metadata:** optional log-specific JSON metadata payload.
- **Generic log metadata:** optional fallback metadata describing a logger output format.
- **Event schema:** YAML or already-parsed schema object used for event detection and metric extraction.
- **Bike profile:** JSON or already-parsed bike/setup-specific parameters, including normalization ranges and bike-specific transforms.
- **Preprocess profile:** JSON reusable preprocessing policy, including zeroing, motion derivation, activity-mask settings, strictness, and optional FIT import policy.
- **FIT candidates/bindings:** optional precomputed FIT summaries, raw FIT content, or in-memory bindings used for GPS enrichment during preprocessing.

Runtime/local paths are deliberately not embedded in the preprocess profile.
The web service should resolve uploaded assets into loaded objects, dataframes,
or candidate metadata and pass those resolved inputs explicitly.

---

## Metadata resolution

Recommended resolution order for a backend using resolved-content APIs:

1. If a log-specific metadata payload is available, pass it to `prepare_logger_dataframe(..., log_metadata=...)`.
2. Otherwise pass one selected generic metadata payload.
3. If neither is available, `prepare_logger_dataframe(...)` falls back to generic CSV/header parsing behavior where possible.

If multiple possible generic metadata profiles are available, the web layer
should require a user or configuration choice before calling the pipeline. Do
not silently try multiple generic profiles after one has been selected.

For FIT enrichment, the preferred backend pattern is:

1. Inspect uploaded FIT assets with `inspect_fit_stream(...)` or equivalent cached summaries.
2. Resolve overlaps with `find_overlapping_fit_candidates(...)`.
3. Pass `fit_candidates`, `fit_bindings`, or a fully preloaded `fit_stream` to `preprocess_resolved(...)`.

The older `fit_dir` and `bindings_path` pattern is still supported for notebook
and local staging workflows, but it is not the preferred remote-service contract.

---

## Return value

Both `preprocess_resolved(...)` and `preprocess_session(...)` return a dictionary:

```python
{
    "session": session,
    "schema": schema,
    "events": events_df,
    "segments": segments_by_schema_id,
    "metrics": metrics_df,
}
```

The main user-facing outputs are usually:

- `results["session"]["df"]`: preprocessed time-series data
- `results["session"]["meta"]["signals"]`: signal registry and semantic metadata
- `results["events"]`: detected events
- `results["metrics"]`: per-event metrics table

These pandas dataframes can be serialized to CSV, Parquet, or JSON depending on
the web service contract. Prefer Parquet or CSV for larger time-series outputs.

---

## Error handling

Treat `ValueError` as a user/configuration error: invalid profile, missing
required metadata columns, ambiguous signal selector, invalid event schema, and
similar issues.

Unexpected exceptions should be logged as server errors with the input bundle
identifiers, but the service should avoid returning Python tracebacks to end
users.

The BODAQS modules use Python `logging`; the web application should configure
logging at the application boundary.

---

## Batch pattern

For a batch of uploaded logs, load the preprocess profile once and call
`preprocess_resolved(...)` once per resolved session:

```python
config = load_preprocess_config(preprocess_profile_path)

batch_results = {}
for uploaded in uploaded_logs:
    df_prepared, log_metadata = prepare_logger_dataframe(
        uploaded.df,
        log_metadata=uploaded.log_metadata,
    )
    session = build_session_from_dataframe(
        df_prepared,
        source_name=uploaded.filename,
        log_metadata=log_metadata,
    )
    batch_results[uploaded.filename] = preprocess_resolved(
        session,
        preprocess_config=config,
        schema=schema,
        bike_profile=bike_profile,
        fit_candidates=uploaded.fit_candidates,
        fit_bindings=uploaded.fit_bindings,
    )
```

The service should record which artifact paths, resource identifiers, and
versions were used for each processed log so outputs remain reproducible.
