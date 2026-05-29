# BODAQS Python Library Adapter Implementation Plan

**Status:** In progress
**Date:** 2026-05-28
**Scope:** Python adapter plus initial local HTTP service wrapper for the BODAQS Library API
**Related contract:** [`BODAQS_Library_API_Contract_v0_draft.md`](../contracts/BODAQS_Library_API_Contract_v0_draft.md)

## 1. Goal

Build a reusable Python adapter that reads processed BODAQS libraries and emits
the payloads expected by the browser application and future localhost Library
API service.

The adapter should be usable from:

- notebooks
- tests
- fixture-generation scripts
- the local HTTP service

It should not depend on Jupyter, Tk, Import Manager UI code, or a running web
server.

## 2. Non-Goals

The adapter should not implement:

- logger import
- Wi-Fi transfer
- raw archive validation
- preprocessing
- event detection
- metric extraction
- Import Manager configuration
- HTTP routing
- browser UI behavior

Those remain separate concerns.

## 3. Proposed Module Layout

Add a new package area:

```text
analysis/
  bodaqs_analysis/
    library_api/
      __init__.py
      adapter.py
      catalog.py
      ids.py
      models.py
      study_sets.py
      timeseries.py
      fixtures.py
    library_api_service/
      __init__.py
      __main__.py
      app.py
      cli.py
```

Recommended responsibilities:

- `models.py`: dataclasses / TypedDict-style helpers for API payloads.
- `ids.py`: display-name-derived ID generation and session-ref helpers.
- `adapter.py`: high-level `LibraryAdapter` facade.
- `catalog.py`: library discovery and session catalog building.
- `study_sets.py`: Study Set validation and revision-safe persistence.
- `timeseries.py`: one-session window extraction and downsampling.
- `fixtures.py`: static fixture export for frontend development.

This layout keeps the web-facing library logic separate from existing notebook
widget modules, while allowing reuse of current artifact and loader helpers.

The `library_api_service` package is intentionally thin. It owns HTTP routing,
CORS, CLI startup, and adapter-error to HTTP-error conversion. It should not
duplicate library-reading, Study Set, catalog, or time-series logic.

## 4. Existing Code To Reuse

### Artifact Access

Use:

- `analysis/bodaqs_analysis/artifacts.py`

Relevant pieces:

- `ArtifactStore`
- `list_runs`
- `list_sessions`
- `list_event_types`
- `list_metric_event_types`
- `load_session_artifacts`
- `path_session_df`
- `path_session_meta`
- `path_events_df`
- `path_metrics_df`

### Note Projection

Use or extend:

- `analysis/bodaqs_analysis/session_notes.py`

Relevant pieces:

- `make_session_key`
- `SessionNoteStore`
- `SessionNoteTemplateStore`
- `build_session_catalog_df`
- catalog projection behavior

The existing note catalog is close to what the Library API needs, but the new
adapter should shape the output into API JSON objects rather than notebook table
rows.

### Event And Metric Loading

Use:

- `analysis/bodaqs_analysis/widgets/loaders.py`

Relevant pieces:

- `load_all_events_for_selected`
- `load_all_metrics_for_selected`
- robust event parquet fallback for historical `pd.NA` integer columns

For catalog summaries, the adapter may load per-session event/metric parquet
files directly through `ArtifactStore`, using the same robust read helper where
needed.

### Session Window Data

Use logic from:

- `analysis/bodaqs_analysis/widgets/session_window_data.py`

Relevant pieces:

- signal registry interpretation patterns
- event/metric merge helpers
- signal option derivation ideas

The adapter should not import UI widget constructors. It may reuse pure helper
logic or move shared pure helpers if needed.

## 5. Core Public API

The adapter should expose a small Python API that maps directly to the future
HTTP endpoints.

Recommended facade:

```python
adapter = LibraryAdapter(libraries_root)

adapter.capabilities()
adapter.list_libraries()
adapter.get_library(library_id)
adapter.refresh_library(library_id)
adapter.get_catalog(library_id)

adapter.list_study_sets(library_id)
adapter.load_study_set(library_id, study_set_id)
adapter.create_study_set(library_id, payload)
adapter.update_study_set(library_id, study_set_id, expected_revision, payload)
adapter.delete_study_set(library_id, study_set_id)

adapter.get_timeseries_window(library_id, request)
```

Implementation detail:

- The facade should delegate to pure functions where practical.
- Return plain JSON-serializable dicts/lists.
- Avoid returning pandas objects from public adapter methods.
- Use explicit adapter exceptions that can later map to HTTP error codes.

## 6. Error Model

Define adapter exceptions that align with the API contract:

```text
LibraryApiError
LibraryNotFoundError
SessionNotFoundError
StudySetNotFoundError
InvalidRequestError
InvalidStudySetError
RevisionConflictError
CapabilityUnavailableError
SignalNotFoundError
TimeseriesUnavailableError
```

Each exception should carry:

- `code`
- `message`
- optional `details`

The HTTP service can later convert these into the standard error envelope.

## 7. Library Discovery

Input:

```text
libraries_root
```

Recommended v0 discovery:

1. Iterate immediate child directories under `libraries_root`.
2. Treat a child as a library if it has:
   - `library_definition.json`, or
   - a `runs/` directory with at least one run.
3. Prefer `library_definition.json` for:
   - `library_id`
   - `display_name`
   - feature flags such as data.syn.bike export metadata if useful later.
4. Fall back to directory name for `library_id` and display name.

Output shape should align with:

```json
{
  "library_id": "default-library",
  "display_name": "Default Library",
  "root": "C:/Users/.../libraries/default-library",
  "capabilities": {
    "read_processed_library": true,
    "read_parquet": true,
    "write_study_sets": true
  }
}
```

For later portability, API responses may omit or hide absolute paths if desired,
but the adapter can retain paths internally.

## 8. Catalog Generation

The adapter should build a catalog from canonical run/session artifacts and cache
it in memory per library.

### Catalog Cache

For v0:

- build catalog on first access or service startup
- keep an in-memory copy
- expose `refresh_library(library_id)` to rebuild
- defer persisted catalog files

### Catalog Row Sources

Build each row from:

- run manifest
- session manifest
- session meta
- note document/template projection
- event parquet partitions
- metric parquet partitions
- source/provenance manifest fields

### Required Catalog Row Content

Each row should include:

- `session_key`, `run_id`, `session_id`
- display labels
- timestamps:
  - `started_at_utc`
  - `started_at_local`
  - `processed_at`
  - `imported_at`
- note status:
  - `missing`
  - `draft`
  - `edited`
  - `unreadable`
  - `template_missing`
  - `invalid`
- projected note fields:
  - `bike`
  - `rider`
- QC summary
- compact provenance
- event schema identity
- compact semantic signal summary
- event summary
- metric summary

### Signal Summary

The signal summary should come primarily from `meta["signals"]`.

For each signal, emit compact semantics:

```json
{
  "signal_id": "front_wheel_disp_dom_wheel_mm",
  "column": "front_wheel_disp_dom_wheel [mm]",
  "display_name": "Front wheel travel",
  "end": "front",
  "domain": "wheel",
  "quantity": "disp",
  "unit": "mm",
  "processing_role": "primary_analysis"
}
```

Initial implementation can include all semantic signals from the registry, or
limit to numeric signals present in the dataframe. Prefer validating that the
column exists in `df.parquet` metadata or by reading only parquet schema if this
is easy.

### Event Summary

For each session:

- scan `events/<schema_id>/events.parquet`
- count total rows
- count by event type or schema event field
- report schema ID/display name where available

The implementation should be tolerant of sessions with no events.

### Metric Summary

For each session:

- scan `metrics/<schema_id>/metrics.parquet`
- count metric columns or rows
- count events with metrics

The implementation should be tolerant of sessions with no metrics.

## 9. Study Set Persistence

Study Sets live at:

```text
<library>/
  library/
    study_sets/
      <study_set_id>.json
```

### Validation

Validate:

- `schema == "bodaqs.study_set"`
- supported `version`
- filename-safe `study_set_id`
- `session_key == f"{run_id}::{session_id}"`
- top-level sessions exist in the library catalog
- grouping sessions are contained in top-level sessions
- bookmark sessions are contained in top-level sessions
- each bookmark has exactly one of `time_s` or `time_window`
- track references are structurally valid, even if track endpoints are deferred

### Revision Checks

Implement revision-safe writes:

- New Study Set starts at `revision: 1`.
- Update requires `expected_revision`.
- If stored revision differs, raise `RevisionConflictError`.
- Successful update increments revision and updates provenance timestamp.

### Atomic Writes

Use atomic JSON writes:

1. write to temporary file in the same directory
2. `os.replace` into place

Consider a simple per-file lock later if concurrent service requests become a
real concern. Revision checks are enough for v0 behavior.

## 10. ID Generation

Implement display-name-derived IDs in `ids.py`.

Rules:

1. trim whitespace
2. lowercase
3. replace whitespace runs with hyphens
4. replace or remove filename-unsafe characters
5. collapse repeated hyphens
6. apply length limit
7. add numeric suffixes on conflict

Use the same function for Study Set IDs and future Track IDs.

## 11. Time-Series Window Extraction

Endpoint-equivalent helper:

```python
get_timeseries_window(library_id, request) -> dict
```

### Request Support

Support:

- one session per request
- semantic signal selectors
- concrete column names
- `start_s`
- `end_s`
- `target_points`
- `include_events`

### Time Column

Initial time-column resolution:

1. Prefer primary stream time metadata if present.
2. Fall back to a signal registered as time.
3. Fall back to common columns such as `time_s`, `timestamp`, or `time`.
4. Raise `TimeseriesUnavailableError` if no usable time column is found.

The selected time column and units should be reflected in the response.

### Signal Resolution

For semantic selectors:

- use `meta["signals"]`
- match requested fields exactly where specified
- require a column present in the dataframe
- prefer `processing_role == "primary_analysis"` when multiple matches exist
- raise `SignalNotFoundError` for no match
- raise `InvalidRequestError` or a specific ambiguity error for multiple equal matches

For concrete columns:

- require the column to exist
- include registry semantics if available

### Windowing

Read only required columns where possible:

- time column
- selected signal columns

Filter rows by:

```text
start_s <= time <= end_s
```

If the requested window is outside session bounds, return the available
intersection with a warning. If no data intersects, raise
`TimeseriesUnavailableError`.

### Downsampling

Use v0 policy:

- if source points <= `target_points`, return raw samples
- if source points > `target_points`, use min/max bucket decimation
- preserve time order
- report:
  - `mode`
  - `source_points`
  - `returned_points`
  - `target_points`

For multiple signals, preserve spikes across all selected signals. A practical
v0 approach is:

1. bucket by source row index/time
2. collect min/max row indices for each signal in each bucket
3. union selected row indices across signals
4. return rows sorted by original order

This avoids each signal returning a different time vector.

### Event Overlays

If `include_events` is true:

- load events for the session
- include events overlapping the returned/requested window
- emit compact event objects:
  - `event_id`
  - `event_type`
  - `display_name`
  - `start_s`
  - `end_s`
  - `peak_time_s`
  - `end`

Column names differ across historical event tables, so the first implementation
should centralize event-time column resolution and be tolerant of missing fields.

## 12. Fixture Generation

Add a fixture-generation helper that can export a small static payload for
frontend development.

Recommended output:

```text
<fixture_dir>/
  capabilities.json
  libraries.json
  libraries/
    <library_id>/
      catalog.json
      study_sets/
        <study_set_id>.json
      timeseries_windows/
        <session_key_safe>__front-rear-wheel.json
```

The fixture should include:

- one library
- a representative catalog subset
- one Study Set
- at least one front/rear wheel travel time-series window
- event overlays if available

This allows the browser chart work to proceed without requiring the local
service to exist on George's machine.

## 13. Notebook Remediation

Some notebook remediation will be useful, but it should be staged. The web
adapter should not require a wholesale notebook rewrite before frontend work can
begin.

### 13.1 Principle

The adapter should become a shared library layer that notebooks may consume,
rather than a web-only path that forks library/catalog/study-set behavior.

However, the existing notebooks should not be forced to adopt the adapter all at
once. The safer approach is to add adapter-compatible bridges first, then migrate
notebook entry points incrementally.

### 13.2 Notebooks That Do Not Need Immediate Remediation

Producer/import notebooks and workflows can continue writing canonical artifacts
as they do now:

- batch preprocessor
- one-step preprocessing/metrics workflow, where it is acting as a producer
- Import Manager processing pipeline

These workflows are upstream of the adapter. The adapter reads their outputs.

### 13.3 Notebooks That Should Be Remediated First

The library-manager notebook should be the first notebook consumer to adopt the
adapter concepts because it already owns catalog, notes, descriptions, and
aggregation-like library curation.

Recommended changes:

- use the adapter catalog builder instead of maintaining a separate catalog shape
- introduce Study Set load/save/edit operations
- keep existing aggregation support as legacy or compatibility behavior until it
  can be retired or mapped into Study Set-local groupings
- show Study Set revision/conflict behavior if editing from multiple places

This keeps the notebook and web app from developing two different answers to
"what is a selected analysis scope?"

### 13.4 Consumer Notebook Bridge

Existing consumer widgets already use a useful internal contract:

- `session_key`
- `key_to_ref`
- `events_index_df`
- session loaders
- event loaders
- metric loaders

Add a bridge that converts a Study Set into the existing widget selector inputs:

```python
snapshot = adapter.study_set_to_selection_snapshot(
    library_id="default-library",
    study_set_id="setup-comparison",
)
```

The bridge should return the same shape currently expected by consumer widgets
or a small compatible wrapper around it.

This lets notebooks such as the data explorer, session browser, simple
suspension metrics, and session-window browser consume Study Sets without
rewriting their visualization widgets immediately.

### 13.5 Consumer Notebook Migration Order

Recommended order:

1. Library manager: create/edit Study Sets.
2. Data explorer: open a Study Set as selection scope.
3. Session browser: optionally open a Study Set or one session from a Study Set.
4. Simple suspension metrics: use Study Set scope for front/rear adequacy and browsing.
5. One-step suspension metrics: keep producer behavior first; add Study Set output/selection only if useful.

### 13.6 Compatibility With Existing Aggregations

Existing canonical aggregations should not block the Study Set model.

For v0:

- keep aggregation modules working for existing notebooks
- treat new Study Set `groupings` as the forward path for per-study-set buckets
- do not persist groupings as reusable library objects
- optionally provide a migration helper that copies an existing aggregation into
  a Study Set grouping

### 13.7 When Notebook Remediation Becomes Required

Notebook remediation becomes required when:

- the team wants notebooks and the web app to operate on the same saved Study Sets
- Study Set files become canonical user-facing library objects
- browser-generated Study Sets need to be opened in JupyterLab
- notebook-generated Study Sets need to be opened in the browser app

Until then, adapter implementation and frontend visualization can proceed with a
static fixture and direct adapter tests.

## 14. Test Plan

Add tests under:

```text
analysis/tests/
```

Suggested files:

```text
test_library_api_ids.py
test_library_api_study_sets.py
test_library_api_catalog.py
test_library_api_timeseries.py
```

### ID Tests

- display-name slug generation
- unsafe character stripping/replacement
- conflict suffixing
- length limit

### Study Set Tests

- create Study Set
- update Study Set with matching revision
- reject stale revision
- reject invalid session refs
- reject grouping/bookmark refs outside top-level sessions
- atomic write leaves valid JSON

### Catalog Tests

- discover library under libraries root
- build catalog from a minimal artifact fixture
- project draft/edited/missing note statuses
- include compact signal semantics
- include event/metric summaries
- tolerate missing events/metrics

### Time-Series Tests

- resolve semantic front/rear wheel signals
- resolve concrete columns
- reject missing signals
- return raw samples below target point count
- min/max bucket downsample above target point count
- preserve shared time vector across multiple signals
- include overlapping event overlays
- handle out-of-range windows with warning or clear error

### Notebook Bridge Tests

- convert a Study Set into `key_to_ref`
- convert a Study Set into a widget-compatible selection snapshot
- reject Study Sets with sessions missing from the current library
- preserve grouping labels where they can be represented

## 15. Implementation Phases

### Phase 1A: Skeleton And IDs

Status: complete.

- create `library_api` package
- add model helpers
- add adapter error classes
- implement ID generation
- add ID tests

### Phase 1B: Library Discovery

Status: complete.

- implement `LibraryAdapter(libraries_root)`
- discover libraries under root
- read `library_definition.json` where present
- expose `capabilities()` and `list_libraries()`
- add tests with temporary library roots

### Phase 1C: Study Sets

Status: complete.

- implement Study Set validation
- implement list/load/create/update/delete
- implement revision checks
- implement atomic writes
- add tests

### Phase 1D: Catalog

Status: complete.

- build catalog rows from artifacts
- integrate note projection
- emit compact signal summaries
- emit event/metric summaries
- cache catalog in memory
- implement explicit refresh
- add tests

### Phase 1E: Time-Series Windows

Status: complete.

- implement session/time/signal resolution
- implement window extraction
- implement min/max bucket downsampling
- implement event overlays
- add tests

### Phase 1F: Static Fixture Export

Status: complete.

- export one small fixture payload for frontend development
- include a Study Set and one time-series window
- document how George should consume it

### Phase 1G: Notebook Compatibility Bridge

Status: complete.

- add Study Set to widget-selection conversion helpers
- update or prototype the library manager notebook against Study Set CRUD
- document how existing notebooks can load a Study Set scope

### Phase 2A: Local HTTP Service Wrapper

Status: complete.

- add a thin FastAPI wrapper around `LibraryAdapter`
- expose health, capabilities, library, catalog, Study Set, and time-series
  endpoints
- map adapter exceptions to the standard JSON error envelope
- add CLI startup via `python -m bodaqs_analysis.library_api_service`
- add focused route tests with `fastapi.testclient.TestClient`

## 16. Open Decisions

These can be decided during implementation:

- exact Python type style: dataclasses, TypedDicts, or plain dict validators
- whether to depend on `pyarrow` schema inspection or just use pandas reads
- exact event time column priority for overlays
- exact generated fixture location
- whether fixture generation should also have a CLI entry point
- how far to remediate notebooks before the first browser prototype
- whether the local service should later add write controls, auth tokens, or
  browser-launch helpers before broader release

## 17. Recommended Next Step

Start the browser-facing service trial:

1. run the service against a real libraries root
2. fetch capabilities, library list, catalog, and one time-series window from a
   browser or API client
3. decide the first frontend fixture/service boundary George should consume
4. keep notebook remediation incremental through the existing Study Set bridge

The service wrapper is deliberately small at this stage: enough to validate the
API seam without turning the Import Manager into a broader web platform.
