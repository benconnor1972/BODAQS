# BODAQS Web Preprocessing Integration Note

**Audience:** web/API developers wrapping the BODAQS Python analysis modules  
**Scope:** single-log or batch preprocessing using supplied profiles and schemas  
**Related reference:** `analysis/documentation/BODAQS_Public_API_Contract_v0.md`

---

## Integration shape

The web service should call the BODAQS Python modules directly rather than
reimplementing preprocessing logic. For each uploaded or supplied log file, the
service should call:

```python
from bodaqs_analysis import load_preprocess_config, preprocess_session

config = load_preprocess_config(preprocess_profile_path)

results = preprocess_session(
    log_csv_path,
    preprocess_config=config,
    schema_path=event_schema_path,
    bike_profile_path=bike_profile_path,
    log_metadata_path=same_stem_log_metadata_path,          # optional
    generic_log_metadata_paths=[generic_log_metadata_path], # fallback
)
```

`preprocess_session(...)` is the public all-in-one entry point. It loads the
CSV, applies logger metadata, applies bike-profile transforms, runs filtering
and motion derivation, normalizes signals, detects events, extracts segments,
and computes metrics.

---

## Expected inputs

For this integration case we expect to provide:

- **Log CSV file(s):** one or more logger output files.
- **Specific log metadata file:** optional same-stem JSON metadata for a log, for example `ride_001.csv` plus `ride_001.json`.
- **Generic log metadata file:** fallback metadata describing a logger output format when no same-stem metadata exists.
- **Event schema:** YAML event definitions used for event detection and metric extraction.
- **Bike profile:** JSON bike/setup-specific parameters, including normalization ranges and bike-specific transforms.
- **Preprocess profile:** JSON reusable preprocessing policy, including zeroing, motion derivation, activity-mask settings, strictness, and optional FIT import policy.

Runtime/local paths are deliberately not embedded in the preprocess profile.
The web service should resolve and pass paths explicitly.

---

## Metadata resolution

Recommended resolution order:

1. If a same-stem log metadata file exists beside the CSV, pass it as `log_metadata_path`.
2. Otherwise pass one selected generic metadata profile in `generic_log_metadata_paths`.
3. If neither is available, the loader falls back to existing CSV/header parsing behavior where possible.

If a generic metadata directory contains multiple possible profiles, the web
layer should require a user or configuration choice before calling the pipeline.
Do not silently try multiple generic profiles after one has been selected.

---

## Return value

`preprocess_session(...)` always returns a dictionary:

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

For a batch of logs, load the preprocess profile once and call
`preprocess_session(...)` once per CSV:

```python
config = load_preprocess_config(preprocess_profile_path)

batch_results = {}
for csv_path in csv_paths:
    log_metadata_path = find_same_stem_metadata(csv_path)
    batch_results[str(csv_path)] = preprocess_session(
        csv_path,
        preprocess_config=config,
        schema_path=event_schema_path,
        bike_profile_path=bike_profile_path,
        log_metadata_path=log_metadata_path,
        generic_log_metadata_paths=[generic_log_metadata_path],
    )
```

The service should record which artifact paths and versions were used for each
processed log so outputs remain reproducible.

