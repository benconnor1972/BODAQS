# Specification: Library API & Service

**Created**: 2025-06-20
**Status**: Draft
**Design Docs**: `docs/design/library-api.md`

## Scope

**What part of the design is being implemented:**
This spec documents the existing Library API & Service sphere as it currently
behaves. It covers:
- The `LibraryAdapter` facade and all `library_api/` modules (catalog,
  timeseries, geospatial, trackpoint queries, study sets, session filters,
  session notes, session descriptions, selection bridge, fixtures, IDs, models,
  errors)
- The FastAPI service in `library_api_service/` (app, CLI, `__main__`)
- The aggregation stores in `library/` (AggregationStore, AggregationProvider,
  JsonAggregationStore, LocalAggregationStore, CanonicalAggregationStore)

**Out of scope for this spec:**
- Import, preprocessing, event detection, metric extraction (owned by Import
  Manager / Python processing domain)
- The `bodaqs_analysis.artifacts.ArtifactStore` implementation (external
  dependency, consumed but not owned)
- The `bodaqs_analysis.widgets` entity selection implementation (external
  dependency, consumed by selection bridge)
- The `bodaqs_analysis.session_notes` template store implementation (external
  dependency, consumed by session notes module)
- The `bodaqs_analysis.gps_semantics` column resolver (external dependency,
  consumed by catalog)

## Design Context

### Relevant Invariants

- **INV-1**: Object IDs are filename-safe slugs matching `^[a-z0-9](?:[a-z0-9-]{0,70}[a-z0-9])?$`
- **INV-2**: Session keys are `run_id::session_id` with non-empty parts
- **INV-3**: Session reference IDs are `library_id|||session_key`
- **INV-4**: All persisted JSON payloads carry `schema` string and integer `version`
- **INV-5**: Optimistic concurrency via `revision` for study sets, session filters, tracks (geospatial policies excluded)
- **INV-6**: All file writes are atomic (tmp + `os.replace`)
- **INV-7**: Adapter caches library list and per-library catalogs
- **INV-8**: Default geospatial policy always available
- **INV-9**: Study set validation requires all session refs exist in discovered libraries
- **INV-10**: Trackpoint station_m within `[0, track_length_m]`
- **INV-11**: Track path is GeoJSON LineString with >=2 coords
- **INV-12**: Aggregation validation: non-empty members, valid session keys, policies in `{union, intersection, strict}`
- **INV-13**: Service binds to 127.0.0.1, CORS for localhost dev origins
- **INV-14**: All `LibraryApiError` subclasses carry code, status_code, message, details
- **INV-15**: Time-series min-max bucket downsampling when source > target_points
- **INV-16**: GPS source selection prefers explicit metadata, falls back to legacy_heuristic *(legacy)*
- **INV-17**: Trackpoint query results are JSONL with offset pagination (max 500/page)

### Relevant Contracts

- Library discovery: scan `libraries/` then root for dirs with `library_definition.json` or `runs/`
- Session catalog: built from ArtifactStore runs/sessions, includes GPS/event/metric/note summaries
- Time-series window: resolve time column, resolve signals by column or selector, downsample, optional events
- Track matching: project to local XY, find nearest projections within max_point_distance_m, compute cutline crossings; fallback to catalog summary
- Trackpoint queries: deterministic ID, idempotent create, async worker, JSONL results, offset pagination
- Study sets: validate session refs against all libraries, support groupings/bookmarks/tracks, legacy dir migration
- Session filters: predicate tree (and/or groups, eq/in/contains/present/matches leaves), defined fields, definitions only (not evaluated)
- Aggregation stores: JSON persistence, schema validation, bootstrap from local to canonical

### Relevant Failure Modes

- Missing/invalid libraries root → `InvalidRequestError` (400)
- Unknown library/session/study_set/track/policy/query → 404 errors
- Revision mismatch → `RevisionConflictError` (409)
- Corrupt JSON files → 400/404 errors with details
- Unreadable parquet → `TimeseriesUnavailableError` (404)
- Worker crash → query marked `failed`
- Worker killed mid-run → query stuck in `running` (unhandled)
- Non-`LibraryApiError` in HTTP → FastAPI default 500 (no envelope)
- Aggregation store corrupt → `.corrupt` copy, `AggregationStoreError`

---

## Component Specifications

### LibraryAdapter — `library_api/adapter.py`

**Design doc reference:** LibraryAdapter component contract
**Depends on:** catalog, timeseries, geospatial, trackpoint_queries, study_sets, session_filters, session_notes, session_descriptions, selection, ids, models, errors

#### Interface Signatures

```python
class LibraryAdapter:
    def __init__(self, libraries_root: str | Path) -> None: ...

    def capabilities(self) -> dict[str, Any]: ...
    def list_libraries(self, *, refresh: bool = False) -> list[dict[str, Any]]: ...
    def get_library(self, library_id: str) -> dict[str, Any]: ...
    def refresh_library(self, library_id: str) -> dict[str, Any]: ...
    def get_catalog(self, library_id: str, *, refresh: bool = False) -> dict[str, Any]: ...
    def get_timeseries_window(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]: ...
    def get_session_gps_summary(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]: ...
    def get_session_gps_points(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]: ...
    def load_session_note(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]: ...
    def save_session_note(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]: ...
    def update_session_descriptions(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]: ...

    # Tracks
    def list_tracks(self) -> list[dict[str, Any]]: ...
    def load_track(self, track_id: str) -> dict[str, Any]: ...
    def create_track(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_track(self, track_id: str, *, payload: dict[str, Any], expected_revision: int | None = None) -> dict[str, Any]: ...
    def delete_track(self, track_id: str) -> dict[str, Any]: ...

    # Geospatial policies
    def list_geospatial_policies(self) -> list[dict[str, Any]]: ...
    def load_geospatial_policy(self, policy_id: str) -> dict[str, Any]: ...
    def create_geospatial_policy(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_geospatial_policy(self, policy_id: str, *, payload: dict[str, Any]) -> dict[str, Any]: ...
    def delete_geospatial_policy(self, policy_id: str) -> dict[str, Any]: ...

    # Track matches
    def query_track_matches(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def compute_track_match(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def load_track_match(self, track_match_id: str) -> dict[str, Any]: ...

    # Trackpoint match queries
    def create_trackpoint_match_query(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def load_trackpoint_match_query(self, query_id: str) -> dict[str, Any]: ...
    def load_trackpoint_match_query_results(self, query_id: str, *, cursor: str | None = None, limit: int = 100) -> dict[str, Any]: ...
    def cancel_trackpoint_match_query(self, query_id: str) -> dict[str, Any]: ...
    def fail_trackpoint_match_query(self, query_id: str, message: str) -> dict[str, Any]: ...
    def run_trackpoint_match_query(self, query_id: str) -> dict[str, Any]: ...

    # Session filters
    def list_session_filters(self) -> list[dict[str, Any]]: ...
    def load_session_filter(self, filter_id: str) -> dict[str, Any]: ...
    def create_session_filter(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_session_filter(self, filter_id: str, *, expected_revision: int, payload: dict[str, Any]) -> dict[str, Any]: ...
    def delete_session_filter(self, filter_id: str) -> dict[str, Any]: ...

    # Study sets
    def list_study_sets(self, library_id: str | None = None) -> list[dict[str, Any]]: ...
    def load_study_set(self, *args: str) -> dict[str, Any]: ...
    def resolve_study_set_id(self, study_set_ref: str, *, library_id: str | None = None) -> str: ...
    def create_study_set(self, *args: Any) -> dict[str, Any]: ...
    def update_study_set(self, *args: Any, expected_revision: int, payload: dict[str, Any]) -> dict[str, Any]: ...
    def delete_study_set(self, *args: str) -> dict[str, Any]: ...
    def study_set_to_selection_snapshot(self, library_id: str, study_set_id: str, *, include_groupings: bool = True) -> dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `library_id` | Must match a discovered library | `LibraryNotFoundError` (404) |
| `session_ref` | Must be a JSON object with library_id + (run_id/session_id or session_key) | `InvalidRequestError` (400) |
| `session_key` | Must match `run_id::session_id` | `InvalidRequestError` (400) |
| `session_ref_id` | Must match `library_id\|\|\|session_key` | `InvalidRequestError` (400) |
| `study_set_ref` (resolve) | Must match ID, exact display_name, case-insensitive, or be filename-safe | `InvalidStudySetError` (400) |
| Track match compute | Exactly one track and one session | `InvalidRequestError` (400) |
| Trackpoint query scope | `session_filter_ids` not supported | `InvalidRequestError` (400) |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `LibraryNotFoundError` | Unknown library_id | `{library_id}` | Check library list |
| `SessionNotFoundError` | Session not in catalog | `{library_id, session_ref_id, session_key, run_id, session_id}` | Check catalog |
| `InvalidRequestError` | Bad request shape, missing fields | varies | Fix request |
| `InvalidStudySetError` | Bad study set ref, multi-library snapshot | `{study_set_ref, ...}` | Fix study set |

#### Acceptance Criteria

- **AC1:** Given a valid libraries_root, When `list_libraries()` is called, Then all libraries with `library_definition.json` or `runs/` are returned.
- **AC2:** Given an unknown library_id, When `get_library()` is called, Then `LibraryNotFoundError` (404) is raised.
- **AC3:** Given a session_ref with session_key but no run_id/session_id, When any session method is called, Then run_id/session_id are parsed from session_key.
- **AC4:** Given a session_ref with inconsistent session_key/run_id/session_id, When any session method is called, Then `InvalidRequestError` is raised.
- **AC5:** Given a study_set_ref that matches a display_name exactly, When `resolve_study_set_id` is called, Then the corresponding study_set_id is returned.
- **AC6:** Given a study_set_ref that matches multiple display names case-insensitively, When `resolve_study_set_id` is called, Then `InvalidStudySetError` (ambiguous) is raised.
- **AC7:** Given a track match compute request with !=1 track or !=1 session, When `compute_track_match` is called, Then `InvalidRequestError` is raised.
- **AC8:** Given a trackpoint query request with `scope.session_filter_ids`, When `create_trackpoint_match_query` is called, Then `InvalidRequestError` is raised.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `catalog` | `discover_libraries(root)` | `list[dict]` | Propagate `InvalidRequestError` |
| `catalog` | `build_session_catalog(root, library_id)` | `dict` | Propagate `InvalidRequestError` |
| `catalog` | `get_session_gps_points(root, ref, ...)` | `dict` | Propagate errors |
| `timeseries` | `get_timeseries_window(root, request, library_id)` | `dict` | Propagate `SessionNotFoundError`, `SignalNotFoundError`, `TimeseriesUnavailableError` |
| `geospatial` | CRUD + `build_session_track_match` | `dict` | Propagate `TrackNotFoundError`, etc. |
| `study_sets` | CRUD + `validate_study_set` | `dict` | Propagate `StudySetNotFoundError`, `InvalidStudySetError`, `RevisionConflictError` |

---

### FastAPI Service — `library_api_service/app.py`

**Design doc reference:** FastAPI Service component contract
**Depends on:** LibraryAdapter, errors

#### Interface Signatures

```python
@dataclass(frozen=True)
class LibraryApiServiceConfig:
    libraries_root: Path
    allow_origins: tuple[str, ...]

def create_app(libraries_root: str | Path, *, allow_origins: Sequence[str] | None = None) -> FastAPI: ...
```

#### REST API Endpoints

| Method | Path | Handler | Notes |
|--------|------|---------|-------|
| GET | `/api/v1/health` | `health` | Returns status, service name, api_version, libraries_root |
| GET | `/api/v1/capabilities` | `capabilities` | Returns `default_capabilities()` |
| POST | `/api/v1/config/libraries-root` | `set_libraries_root` | Hot-swaps adapter, clears thread registry |
| GET | `/api/v1/libraries` | `list_libraries` | |
| GET | `/api/v1/libraries/{library_id}` | `get_library` | |
| POST | `/api/v1/libraries/{library_id}/refresh` | `refresh_library` | |
| GET | `/api/v1/libraries/{library_id}/catalog` | `get_catalog` | |
| POST | `/api/v1/libraries/{library_id}/sessions/gps-summary` | `get_session_gps_summary` | |
| POST | `/api/v1/libraries/{library_id}/sessions/gps/points` | `get_session_gps_points` | |
| POST | `/api/v1/libraries/{library_id}/sessions/note` | `load_session_note` | |
| PUT | `/api/v1/libraries/{library_id}/sessions/note` | `save_session_note` | |
| PUT | `/api/v1/libraries/{library_id}/sessions/descriptions` | `update_session_descriptions` | |
| POST | `/api/v1/libraries/{library_id}/timeseries/window` | `get_timeseries_window` | |
| GET | `/api/v1/tracks` | `list_root_tracks` | |
| POST | `/api/v1/tracks` | `create_root_track` | Unwraps `track` or uses payload |
| GET | `/api/v1/tracks/{track_id}` | `load_root_track` | |
| PUT | `/api/v1/tracks/{track_id}` | `update_root_track` | Optional `expected_revision` |
| DELETE | `/api/v1/tracks/{track_id}` | `delete_root_track` | |
| GET | `/api/v1/geospatial-policies` | `list_root_geospatial_policies` | |
| POST | `/api/v1/geospatial-policies` | `create_root_geospatial_policy` | Unwraps `geospatial_policy`/`policy` |
| GET | `/api/v1/geospatial-policies/{policy_id}` | `load_root_geospatial_policy` | |
| PUT | `/api/v1/geospatial-policies/{policy_id}` | `update_root_geospatial_policy` | |
| DELETE | `/api/v1/geospatial-policies/{policy_id}` | `delete_root_geospatial_policy` | |
| GET | `/api/v1/study-sets` | `list_root_study_sets` | |
| POST | `/api/v1/study-sets` | `create_root_study_set` | Unwraps `study_set` |
| GET | `/api/v1/study-sets/{study_set_id}` | `load_root_study_set` | |
| PUT | `/api/v1/study-sets/{study_set_id}` | `update_root_study_set` | Requires `expected_revision` |
| DELETE | `/api/v1/study-sets/{study_set_id}` | `delete_root_study_set` | |
| GET | `/api/v1/session-filters` | `list_root_session_filters` | |
| POST | `/api/v1/session-filters` | `create_root_session_filter` | Unwraps `session_filter`/`filter` |
| GET | `/api/v1/session-filters/{filter_id}` | `load_root_session_filter` | |
| PUT | `/api/v1/session-filters/{filter_id}` | `update_root_session_filter` | Requires `expected_revision` |
| DELETE | `/api/v1/session-filters/{filter_id}` | `delete_root_session_filter` | |
| POST | `/api/v1/track-matches/query` | `query_track_matches` | |
| POST | `/api/v1/track-matches/compute` | `compute_track_match` | |
| GET | `/api/v1/track-matches/{track_match_id}` | `load_track_match` | |
| POST | `/api/v1/trackpoint-match-queries` | `create_trackpoint_match_query` | Spawns worker if queued/running |
| GET | `/api/v1/trackpoint-match-queries/{query_id}` | `load_trackpoint_match_query` | |
| GET | `/api/v1/trackpoint-match-queries/{query_id}/results` | `load_trackpoint_match_query_results` | `cursor`, `limit` query params |
| DELETE | `/api/v1/trackpoint-match-queries/{query_id}` | `cancel_trackpoint_match_query` | |

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| Request body | Must be JSON object (for endpoints with body) | `InvalidRequestError` (400) |
| `expected_revision` | Must be integer (not bool) | `InvalidRequestError` (400) |
| `libraries_root` (set) | Must be non-empty string | `InvalidRequestError` (400) |
| Study set payload | Must include `study_set` object or be the object | `InvalidRequestError` (400) |
| Track payload | Must include `track` object or be the object | `InvalidRequestError` (400) |
| Geospatial policy payload | Must include `geospatial_policy`/`policy` object or be the object | `InvalidRequestError` (400) |
| Session filter payload | Must include `session_filter`/`filter` object or be the object | `InvalidRequestError` (400) |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `LibraryApiError` envelope | Any adapter error | `{code, message, details}` | Check code/details |
| FastAPI 500 | Non-`LibraryApiError` exception | FastAPI default | Server bug |

#### Acceptance Criteria

- **AC1:** Given a running service, When `GET /api/v1/health` is called, Then `{"status": "ok", "service": "BODAQS Library API", "api_version": "0", "libraries_root": "..."}` is returned.
- **AC2:** Given a `LibraryNotFoundError` raised by adapter, When any endpoint is called, Then HTTP 404 with `{"error": {"code": "library_not_found", ...}}` is returned.
- **AC3:** Given a `POST /api/v1/trackpoint-match-queries` with a new query, When the query status is "queued" or "running", Then a daemon thread is started to run the query.
- **AC4:** Given a `POST /api/v1/config/libraries-root` with a valid path, When called, Then the adapter is replaced, thread registry cleared, and library list returned.
- **AC5:** Given a `PUT /api/v1/study-sets/{id}` without `expected_revision`, When called, Then `InvalidRequestError` (400) is returned.
- **AC6:** Given a `PUT /api/v1/tracks/{id}` without `expected_revision`, When called, Then the track is updated without revision checking.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `LibraryAdapter` | All adapter methods | `dict` / `list[dict]` | `LibraryApiError` → JSON envelope |
| `threading.Thread` | `_run_trackpoint_query_worker` | void | Exception → query marked failed |

---

### Catalog — `library_api/catalog.py`

**Design doc reference:** Catalog component contract
**Depends on:** artifacts.ArtifactStore, gps_semantics, ids, models, errors

#### Interface Signatures

```python
def discover_libraries(libraries_root: str | Path) -> list[dict[str, Any]]: ...
def build_session_catalog(library_root: str | Path, *, library_id: str | None = None) -> dict[str, Any]: ...
def get_session_gps_points(
    library_root: str | Path,
    session_ref: Mapping[str, Any],
    *,
    library_id: str | None = None,
    max_points: int | None = None,
    window: Mapping[str, Any] | None = None,
    source_id: str | None = None,
) -> dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `libraries_root` | Must exist and be a directory | `InvalidRequestError` (400) |
| `library_root` | Must exist and be a directory | `InvalidRequestError` (400) |
| `run_id` | Required non-empty text | `InvalidRequestError` (400) |
| `session_id` | Required non-empty text | `InvalidRequestError` (400) |
| `max_points` | Integer, not bool; default 2000 | — |
| `window` | Object with `start_s`/`end_s` (numeric) | — |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `InvalidRequestError` | Missing/invalid root, duplicate library_id | varies | Fix path/config |
| (GPS read failures) | Parquet unreadable | Source skipped, warning in response | Non-fatal |

#### Acceptance Criteria

- **AC1:** Given a libraries_root with `libraries/` subdir, When `discover_libraries` is called, Then libraries in `libraries/` are discovered first, then root.
- **AC2:** Given two library dirs with the same library_id, When `discover_libraries` is called, Then `InvalidRequestError` (duplicate) is raised.
- **AC3:** Given a library with no `library_definition.json` but with `runs/`, When discovered, Then library_id is derived from directory name.
- **AC4:** Given a session with GPS sources metadata, When catalog is built, Then GPS summary uses `gps_sources` selection method.
- **AC5:** Given a session without GPS sources metadata, When catalog is built, Then GPS summary uses `legacy_heuristic` method. *(legacy behavior)*
- **AC6:** Given a session with <3 GPS points, When GPS summary is built, Then quality is "limited" and warning "gps_low_point_count" is added.
- **AC7:** Given a session with GPS coverage >=0.85, When GPS summary is built, Then quality is "usable".
- **AC8:** Given a GPS source read failure, When GPS summary is built, Then source is included with point_count=0 and warning "gps_source_read_failed".
- **AC9:** Given a max_points request, When `get_session_gps_points` is called, Then points are stride-sampled and last point always included.

---

### Timeseries — `library_api/timeseries.py`

**Design doc reference:** Timeseries component contract
**Depends on:** artifacts.ArtifactStore, catalog (signal helpers), ids, errors

#### Interface Signatures

```python
def get_timeseries_window(
    library_root: str | Path,
    request: Mapping[str, Any],
    *,
    library_id: str | None = None,
) -> dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `session` | Must be object with run_id/session_id | `InvalidRequestError` (400) |
| `session.library_id` | Must match request library_id if both present | `InvalidRequestError` (400) |
| `signals` | Must be non-empty list of objects with `column` or `selector` | `InvalidRequestError` (400) |
| `signal.column` | Must exist in parquet columns | `SignalNotFoundError` (404) |
| `signal.selector` | Must match exactly one signal (or unique best rank) | `SignalNotFoundError` (404) / `InvalidRequestError` (400) |
| `window.start_s`/`end_s` | Numeric, end >= start | `InvalidRequestError` (400) |
| `resolution.target_points` | Integer >= 2, default 2000 | `InvalidRequestError` (400) |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `SessionNotFoundError` | Session dir missing | `{run_id, session_id, session_key}` | Check catalog |
| `SignalNotFoundError` | Column/selector no match | `{column}` or `{selector}` | Check available_signals |
| `TimeseriesUnavailableError` | DF missing/unreadable, no time column, empty window | varies | Check session data |
| `InvalidRequestError` | Bad request shape | varies | Fix request |

#### Acceptance Criteria

- **AC1:** Given a session with time_column in meta, When window is requested, Then that column is used as time.
- **AC2:** Given no explicit time column, When window is requested, Then fallback candidates `time_s`, `elapsed_time_s`, `timestamp_s`, `timestamp`, `time` are tried.
- **AC3:** Given source points > target_points, When window is requested, Then min_max_bucket downsampling is applied and mode is "min_max_bucket".
- **AC4:** Given source points <= target_points, When window is requested, Then no downsampling and mode is "raw".
- **AC5:** Given include_events=True, When window is requested, Then event overlays within the window are included.
- **AC6:** Given a requested window starting before the session, When window is requested, Then warning "requested_window_starts_before_session" is returned.
- **AC7:** Given a selector matching multiple signals with same rank, When window is requested, Then `InvalidRequestError` (ambiguous) is raised.

---

### Geospatial — `library_api/geospatial.py`

**Design doc reference:** Geospatial component contract
**Depends on:** ids, errors

#### Interface Signatures

```python
# Tracks
def list_tracks(libraries_root: str | Path) -> list[dict[str, Any]]: ...
def load_track(libraries_root: str | Path, track_id: str) -> dict[str, Any]: ...
def create_track(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]: ...
def update_track(libraries_root: str | Path, track_id: str, *, payload: Mapping[str, Any], expected_revision: int | None = None) -> dict[str, Any]: ...
def delete_track(libraries_root: str | Path, track_id: str) -> dict[str, Any]: ...

# Geospatial policies
def list_geospatial_policies(libraries_root: str | Path) -> list[dict[str, Any]]: ...
def load_geospatial_policy(libraries_root: str | Path, policy_id: str) -> dict[str, Any]: ...
def create_geospatial_policy(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]: ...
def update_geospatial_policy(libraries_root: str | Path, policy_id: str, *, payload: Mapping[str, Any]) -> dict[str, Any]: ...
def delete_geospatial_policy(libraries_root: str | Path, policy_id: str) -> dict[str, Any]: ...

# Track matches
def load_track_match(libraries_root: str | Path, track_match_id: str) -> dict[str, Any]: ...
def build_session_track_match(*, track, policy, session_ref, gps_summary, gps_points=None) -> dict[str, Any]: ...
def write_track_match(libraries_root: str | Path, payload: Mapping[str, Any]) -> None: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `track_id` | Filename-safe slug | `InvalidTrackError` (400) |
| `display_name` | Required non-empty | `InvalidTrackError` (400) |
| `path.type` | Must be "LineString" | `InvalidTrackError` (400) |
| `path.coordinates` | List of >=2 coordinate arrays | `InvalidTrackError` (400) |
| `trackpoints[].station_m` | Numeric, within [0, track_length_m] | `InvalidTrackError` (400) |
| `trackpoints[].position` | Must be GeoJSON Point | `InvalidTrackError` (400) |
| `policy_id` | Filename-safe slug | `InvalidGeospatialPolicyError` (400) |
| `cutline_left/right_length_m` | Non-negative number | `InvalidGeospatialPolicyError` (400) |
| `max_point_distance_m` | Non-negative number | `InvalidGeospatialPolicyError` (400) |
| `expected_revision` (track) | Must match current if provided | `RevisionConflictError` (409) |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `TrackNotFoundError` | Track file missing | `{track_id}` | Check track list |
| `GeospatialPolicyNotFoundError` | Policy file missing + not default | `{policy_id}` | Check policy list |
| `TrackMatchNotFoundError` | Match file missing | `{track_match_id}` | Compute match first |
| `InvalidTrackError` | Bad track payload/ID | varies | Fix payload |
| `InvalidGeospatialPolicyError` | Bad policy payload/ID | varies | Fix payload |
| `RevisionConflictError` | Track revision mismatch | `{track_id, expected_revision, current_revision}` | Reload and retry |

#### Acceptance Criteria

- **AC1:** Given a track with no length_m, When created, Then length_m is computed from coordinates (geodesic).
- **AC2:** Given trackpoints, When track is normalized, Then trackpoints are sorted by station_m.
- **AC3:** Given the default policy ID, When `delete_geospatial_policy` is called, Then `{"deleted": False, "default_restored": True}` is returned (no error).
- **AC4:** Given a policy payload, When created, Then it is deep-merged with the default policy.
- **AC5:** Given GPS points for a session, When `build_session_track_match` is called, Then geometric projection matching is attempted first.
- **AC6:** Given no GPS points or geometry failure, When `build_session_track_match` is called, Then catalog-summary fallback is used.
- **AC7:** Given coverage_ratio >=0.85, When match is built from points, Then status is "matched".
- **AC8:** Given coverage_ratio <0.85 with some overlap, When match is built from points, Then status is "partial".
- **AC9:** Given no GPS points within max_point_distance_m, When match is built from points, Then status is "no_overlap".
- **AC10:** Given a trackpoint cutline crossing, When match is built from points, Then crossing_time_s is interpolated from segment endpoints.
- **AC11:** Given `update_geospatial_policy`, When called, Then no revision conflict check is performed. *(unverified intent — needs review)*

---

### Trackpoint Queries — `library_api/trackpoint_queries.py`

**Design doc reference:** Trackpoint Queries component contract
**Depends on:** ids, errors

#### Interface Signatures

```python
def create_trackpoint_match_query_record(
    libraries_root: str | Path,
    request: Mapping[str, Any],
    *,
    track: Mapping[str, Any],
    policy: Mapping[str, Any],
    candidate_session_refs: list[Mapping[str, Any]],
    candidate_gps_sources: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]: ...
def load_trackpoint_match_query(libraries_root: str | Path, query_id: str) -> dict[str, Any]: ...
def update_trackpoint_match_query(libraries_root: str | Path, query_id: str, updates: Mapping[str, Any]) -> dict[str, Any]: ...
def cancel_trackpoint_match_query(libraries_root: str | Path, query_id: str) -> dict[str, Any]: ...
def fail_trackpoint_match_query(libraries_root: str | Path, query_id: str, message: str) -> dict[str, Any]: ...
def complete_trackpoint_match_query(libraries_root: str | Path, query_id: str, *, processed_count, matched_count, failed_count) -> dict[str, Any]: ...
def write_trackpoint_match_query_results(libraries_root: str | Path, query_id: str, results: list[Mapping[str, Any]]) -> None: ...
def load_trackpoint_match_query_results(libraries_root: str | Path, query_id: str, *, cursor: str | None = None, limit: int = 100) -> dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `query_id` | Filename-safe slug (or derived) | `InvalidRequestError` (400) |
| `trackpoint_ids` | Non-empty list, all must exist in track | `InvalidRequestError` (400) |
| `match_mode` | One of `any`, `all`, `min_count` | `InvalidRequestError` (400) |
| `min_count` | Integer 1..trackpoint_count (when mode=min_count) | `InvalidRequestError` (400) |
| `tolerance_m` | Non-negative number, default 5.0 | `InvalidRequestError` (400) |
| `cursor` | Integer offset string | `InvalidRequestError` (400) |
| `limit` | 1..500, default 100 | — |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `TrackpointMatchQueryNotFoundError` | Query file missing/unreadable | `{query_id}` | Check query list |
| `InvalidRequestError` | Bad ID, unknown trackpoints, bad mode/count/tolerance | varies | Fix request |

#### Acceptance Criteria

- **AC1:** Given a query with no explicit query_id, When created, Then ID is deterministically derived from track+policy+trackpoints+mode+scope.
- **AC2:** Given an existing active query (queued/running/completed), When re-created with same parameters, Then the existing query is returned unchanged.
- **AC3:** Given a query in "cancelled" or "completed" status, When `run_trackpoint_match_query` is called, Then the query is returned without re-running.
- **AC4:** Given a running query, When a candidate session raises `LibraryApiError`, Then failed_count is incremented and processing continues.
- **AC5:** Given a running query, When status becomes "cancelled" (checked per-candidate), Then partial results are written and the query is returned.
- **AC6:** Given an unhandled exception in the worker, When the query fails, Then status is "failed" with error message.
- **AC7:** Given 250 results, When `load_trackpoint_match_query_results` is called with limit=100, Then first 100 are returned with next_cursor="100".
- **AC8:** Given cursor="200" and limit=100, When results are loaded, Then results 200-249 are returned with next_cursor=None.

---

### Study Sets — `library_api/study_sets.py`

**Design doc reference:** Study Sets component contract
**Depends on:** artifacts.ArtifactStore, catalog (discover_libraries), ids, errors

#### Interface Signatures

```python
def list_study_sets(libraries_root: str | Path) -> list[dict[str, Any]]: ...
def load_study_set(libraries_root: str | Path, study_set_id: str) -> dict[str, Any]: ...
def create_study_set(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]: ...
def update_study_set(libraries_root: str | Path, study_set_id: str, *, expected_revision: int, payload: Mapping[str, Any]) -> dict[str, Any]: ...
def delete_study_set(libraries_root: str | Path, study_set_id: str) -> dict[str, Any]: ...
def validate_study_set(libraries_root: str | Path, payload: Mapping[str, Any]) -> None: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `study_set_id` | Filename-safe slug | `InvalidStudySetError` (400) |
| `display_name` | Required non-empty | `InvalidStudySetError` (400) |
| `revision` | Integer (not bool) | `InvalidStudySetError` (400) |
| `sessions` | List of session ref objects | `InvalidStudySetError` (400) |
| `sessions[].library_id/run_id/session_id` | Required non-empty | `InvalidStudySetError` (400) |
| `sessions[].session_key` | Must match run_id::session_id | `InvalidStudySetError` (400) |
| `sessions[].session_ref_id` | Must match library_id\|\|\|session_key | `InvalidStudySetError` (400) |
| Session refs | Must exist in some discovered library | `InvalidStudySetError` (400) |
| Top-level sessions | No duplicates | `InvalidStudySetError` (400) |
| `groupings[].session_refs` | Must reference top-level sessions | `InvalidStudySetError` (400) |
| `groupings[].grouping_id` | No duplicates | `InvalidStudySetError` (400) |
| `bookmarks[].session_ref` | Must reference top-level session | `InvalidStudySetError` (400) |
| `bookmarks[]` | Exactly one of time_s or time_window | `InvalidStudySetError` (400) |
| `tracks[]` | from/to trackpoint both or neither | `InvalidStudySetError` (400) |
| `expected_revision` | Must match current | `RevisionConflictError` (409) |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `StudySetNotFoundError` | File missing | `{study_set_id}` | Check list |
| `InvalidStudySetError` | Schema/version/ID/validation failure | varies | Fix payload |
| `RevisionConflictError` | Revision mismatch | `{study_set_id, expected_revision, current_revision}` | Reload and retry |

#### Acceptance Criteria

- **AC1:** Given a study set in legacy `library/study_sets/`, When `list_study_sets` is called, Then it is included.
- **AC2:** Given a study set update, When written, Then the file is written to `study_sets/` and any legacy file is deleted.
- **AC3:** Given a study set with a session ref not in any library, When `validate_study_set` is called, Then `InvalidStudySetError` is raised.
- **AC4:** Given a study set with duplicate top-level session refs, When `validate_study_set` is called, Then `InvalidStudySetError` is raised.
- **AC5:** Given a grouping referencing a session not in top-level sessions, When `validate_study_set` is called, Then `InvalidStudySetError` is raised.
- **AC6:** Given a bookmark with both time_s and time_window, When `validate_study_set` is called, Then `InvalidStudySetError` is raised.
- **AC7:** Given a track ref with from_trackpoint_id but no to_trackpoint_id, When `validate_study_set` is called, Then `InvalidStudySetError` is raised.
- **AC8:** Given expected_revision != current, When `update_study_set` is called, Then `RevisionConflictError` (409) is raised.

---

### Session Filters — `library_api/session_filters.py`

**Design doc reference:** Session Filters component contract
**Depends on:** ids, errors

#### Interface Signatures

```python
def list_session_filters(libraries_root: str | Path) -> list[dict[str, Any]]: ...
def load_session_filter(libraries_root: str | Path, filter_id: str) -> dict[str, Any]: ...
def create_session_filter(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]: ...
def update_session_filter(libraries_root: str | Path, filter_id: str, *, expected_revision: int, payload: Mapping[str, Any]) -> dict[str, Any]: ...
def delete_session_filter(libraries_root: str | Path, filter_id: str) -> dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `filter_id` | Filename-safe slug | `InvalidSessionFilterError` (400) |
| `display_name` | Required non-empty | `InvalidSessionFilterError` (400) |
| `predicate` | Object with `op` | `InvalidSessionFilterError` (400) |
| `predicate.op` (group) | `and` or `or`, with `children` list | `InvalidSessionFilterError` (400) |
| `predicate.op` (leaf) | `eq`, `in`, `contains`, `present`, `matches` | `InvalidSessionFilterError` (400) |
| `predicate.field` | One of supported fields | `InvalidSessionFilterError` (400) |
| `trackpoint.crossing` | Requires `matches` op | `InvalidSessionFilterError` (400) |
| `matches` value | Object with track_id, trackpoint_ids, match_mode, tolerance_m | `InvalidSessionFilterError` (400) |
| `match_mode` | `any`, `all`, or `min_count` | `InvalidSessionFilterError` (400) |
| `tolerance_m` | Non-negative, default 5.0 | `InvalidSessionFilterError` (400) |
| `expected_revision` | Must match current | `RevisionConflictError` (409) |

**Supported fields:** `bike`, `event.schema`, `firmware`, `gps.present`, `gps.quality`, `gps.source`, `note.status`, `preprocessing.profile`, `qc.level`, `rider`, `signals`, `source.archive`, `trackpoint.crossing`

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `SessionFilterNotFoundError` | File missing | `{filter_id}` | Check list |
| `InvalidSessionFilterError` | Bad predicate/field/op/ID | varies | Fix payload |
| `RevisionConflictError` | Revision mismatch | `{filter_id, expected_revision, current_revision}` | Reload and retry |

#### Acceptance Criteria

- **AC1:** Given a predicate with op "and" and children, When normalized, Then a recursive group predicate is returned.
- **AC2:** Given a predicate with field "trackpoint.crossing" and op "eq", When normalized, Then `InvalidSessionFilterError` is raised (requires "matches" op).
- **AC3:** Given a trackpoint.crossing matches value with camelCase keys (trackpointIds, matchMode), When normalized, Then it is accepted and normalized to snake_case.
- **AC4:** Given a trackpoint.crossing matches value with match_mode "min_count", When normalized, Then min_count (positive integer) is required.
- **AC5:** Given expected_revision != current, When `update_session_filter` is called, Then `RevisionConflictError` (409) is raised.
- **AC6:** Given a filter with category not specified, When normalized, Then category defaults to "custom".

---

### Session Notes — `library_api/session_notes.py`

**Design doc reference:** Session Notes component contract
**Depends on:** artifacts.ArtifactStore, session_notes (template store), errors

#### Interface Signatures

```python
def load_session_note(library_root: str | Path, session_ref: Mapping[str, Any]) -> dict[str, Any]: ...
def save_session_note(library_root: str | Path, session_ref: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `session_ref.library_id` | Required non-empty | `InvalidRequestError` (400) |
| `session_ref.session_key` | Required non-empty | `InvalidRequestError` (400) |
| `session_ref.run_id` | Required non-empty | `InvalidRequestError` (400) |
| `session_ref.session_id` | Required non-empty | `InvalidRequestError` (400) |
| `note`/`session_note` | Must be object | `InvalidRequestError` (400) |
| `values`/`custom_values` | Must be object if present | `InvalidRequestError` (400) |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `InvalidRequestError` | Bad payload/session ref | varies | Fix request |

#### Acceptance Criteria

- **AC1:** Given no existing note, When `load_session_note` is called, Then a default editable document is returned with present=False.
- **AC2:** Given an existing note, When `load_session_note` is called, Then the persisted document is returned with present=True.
- **AC3:** Given a save with no template_id, When normalized, Then template_id defaults to "web_session_note" and template_version to "1.0".
- **AC4:** Given a save with previous note existing, When normalized, Then created_at_utc is preserved from previous.
- **AC5:** Given a note with a template_id, When loaded, Then template summary is resolved via template store (status "ok" or "missing").

---

### Session Descriptions — `library_api/session_descriptions.py`

**Design doc reference:** Session Descriptions component contract
**Depends on:** artifacts.ArtifactStore, errors

#### Interface Signatures

```python
def update_session_descriptions(
    library_root: str | Path,
    session_ref: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `session_ref.run_id` | Required non-empty | `InvalidRequestError` (400) |
| `session_ref.session_id` | Required non-empty | `InvalidRequestError` (400) |
| `descriptions` | Must be object | `InvalidRequestError` (400) |
| At least one of | `run_description` or `session_description` | `InvalidRequestError` (400) |

#### Acceptance Criteria

- **AC1:** Given only run_description, When updated, Then only run manifest is written and updated_fields=["run_description"].
- **AC2:** Given both run_description and session_description, When updated, Then both manifests are written.
- **AC3:** Given neither field, When updated, Then `InvalidRequestError` is raised.

---

### Selection Bridge — `library_api/selection.py`

**Design doc reference:** Selection Bridge component contract
**Depends on:** artifacts.ArtifactStore, widgets.contracts, widgets.entity_scope, study_sets, ids, errors

#### Interface Signatures

```python
def study_set_to_selection_snapshot(
    library_root: str | Path,
    study_set_or_id: str | Mapping[str, Any],
    *,
    include_groupings: bool = True,
) -> dict[str, Any]: ...
def make_study_set_selector_handle(
    study_set_bridge: Mapping[str, Any],
    *,
    title: str = "Study Set chart scope",
    rows: int = 8,
    select_first_by_default: bool = True,
    auto_display: bool = False,
) -> dict[str, Any]: ...
```

#### Acceptance Criteria

- **AC1:** Given a study set with sessions and groupings, When `study_set_to_selection_snapshot` is called with include_groupings=True, Then both grouping and session entities are in the snapshot.
- **AC2:** Given a study set with groupings, When called with include_groupings=False, Then only session entities are in the snapshot.
- **AC3:** Given a grouping with session_refs using `|||` separator, When converted, Then the session_key is extracted after the separator.
- **AC4:** Given a selector handle, When "Select all" is clicked, Then all entity options are selected.

---

### Fixtures — `library_api/fixtures.py`

**Design doc reference:** Fixtures component contract
**Depends on:** adapter, ids, errors

#### Interface Signatures

```python
def export_library_fixture(
    libraries_root: str | Path,
    library_id: str,
    fixture_dir: str | Path,
    *,
    study_set_id: str | None = None,
    timeseries_request: Mapping[str, Any] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]: ...
```

#### Acceptance Criteria

- **AC1:** Given a non-empty fixture_dir without overwrite=True, When export is called, Then `InvalidRequestError` is raised.
- **AC2:** Given no study_set_id and no existing study sets, When export is called, Then a fixture study set is synthesized from the first catalog row.
- **AC3:** Given no timeseries_request, When export is called, Then a default request is synthesized with front/rear wheel displacement signals (if available).
- **AC4:** Given a successful export, When complete, Then a manifest.json is written with schema "bodaqs.library_api_fixture" v1.

---

### Aggregation Stores — `library/aggregations.py`

**Design doc reference:** Aggregation Stores component contract
**Depends on:** artifacts.ArtifactStore, widgets.contracts

#### Interface Signatures

```python
class AggregationStore(Protocol):
    path: Path
    def load(self) -> None: ...
    def save(self) -> None: ...
    def list(self) -> list[AggregationDefinition]: ...
    def get(self, aggregation_key: str) -> AggregationDefinition | None: ...
    def create(self, *, title: str, member_session_keys: Sequence[str], registry_policy: RegistryPolicy = "union", event_schema_policy: EventSchemaPolicy = "union", note: str | None = None, aggregation_key: str | None = None) -> AggregationDefinition: ...
    def update(self, aggregation_key: str, *, patch: Mapping[str, Any]) -> AggregationDefinition: ...
    def delete(self, aggregation_key: str) -> bool: ...

class AggregationProvider(Protocol):
    def list(self) -> list[AggregationDefinition]: ...
    def get(self, aggregation_key: str) -> AggregationDefinition | None: ...

class JsonAggregationStore:
    def __init__(self, *, path: Path, schema: str) -> None: ...

class LocalAggregationStore(JsonAggregationStore):
    def __init__(self, path: Path | None = None) -> None: ...

class CanonicalAggregationStore(JsonAggregationStore):
    def __init__(self, *, artifact_store: ArtifactStore | None = None, path: Path | None = None) -> None: ...

def bootstrap_canonical_from_local(*, canonical_store: CanonicalAggregationStore, artifact_store: ArtifactStore | None = None, local_store: LocalAggregationStore | None = None) -> int: ...
def make_default_aggregation_store(*, artifact_store: ArtifactStore | None = None) -> CanonicalAggregationStore: ...
def build_aggregation_catalog_df(*, aggregation_store: AggregationProvider, scope: str, artifact_store: ArtifactStore | None = None) -> pd.DataFrame: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `aggregation_key` | Required non-empty string | `AggregationStoreValidationError` |
| `title` | Required non-empty string | `AggregationStoreValidationError` |
| `member_session_keys` | Non-empty list/tuple of valid session keys | `AggregationStoreValidationError` |
| `session_key` format | Must contain `::` with non-empty parts | `AggregationStoreValidationError` |
| `registry_policy` | One of `union`, `intersection`, `strict` | `AggregationStoreValidationError` |
| `event_schema_policy` | One of `union`, `intersection`, `strict` | `AggregationStoreValidationError` |
| Store `schema` | Must match expected schema | `AggregationStoreValidationError` |
| Store `version` | Must equal 1 | `AggregationStoreValidationError` |
| Duplicate `aggregation_key` in store | Not allowed | `AggregationStoreValidationError` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `AggregationStoreError` | Load failure, update missing key | message string | Check file/path |
| `AggregationStoreValidationError` | Invalid schema/version/aggregation/policy | message string | Fix definition |

#### Acceptance Criteria

- **AC1:** Given a non-existent store file, When `load` is called, Then an empty store is initialized (no error).
- **AC2:** Given a corrupt store file, When `load` is called, Then file is copied to `.corrupt` and `AggregationStoreError` is raised.
- **AC3:** Given a store with duplicate aggregation_keys, When `validate_store` is called, Then `AggregationStoreValidationError` is raised.
- **AC4:** Given an aggregation with duplicate member session keys, When coerced, Then duplicates are silently removed.
- **AC5:** Given `add` with existing key, When called, Then `AggregationStoreValidationError` is raised.
- **AC6:** Given `update` with non-existent key, When called, Then `AggregationStoreError` is raised.
- **AC7:** Given `save`, When called, Then a `.bak` backup is created before atomic write.
- **AC8:** Given a non-empty canonical store, When `bootstrap_canonical_from_local` is called, Then 0 is returned (no migration).
- **AC9:** Given an empty canonical store and local store with valid aggregations, When `bootstrap_canonical_from_local` is called, Then aggregations are migrated and count returned.
- **AC10:** Given an artifact_store and local aggregation with invalid members, When `bootstrap_canonical_from_local` is called, Then that aggregation is silently skipped. *(unverified intent — needs review)*
- **AC11:** Given `list`, When called, Then aggregations are sorted by updated_at_utc descending (fallback created_at_utc).
- **AC12:** Given `LocalAggregationStore` with no path, When initialized, Then path defaults to `~/.bodaqs/session_aggregations_v1.json`. *(legacy behavior — may be removed in future cleanup)*

---

### IDs — `library_api/ids.py`

**Design doc reference:** IDs component contract
**Depends on:** (none)

#### Interface Signatures

```python
def derive_object_id(display_name: str, *, fallback: str = "item", max_length: int = 72) -> str: ...
def make_unique_object_id(display_name: str, existing_ids: Iterable[str], *, fallback: str = "item", max_length: int = 72) -> str: ...
def make_session_key(run_id: str, session_id: str) -> str: ...
def make_session_ref_id(library_id: str, session_key: str) -> str: ...
def is_valid_object_id(value: str) -> bool: ...
def parse_session_key(session_key: str) -> tuple[str, str]: ...
```

#### Acceptance Criteria

- **AC1:** Given "My Track Name!", When `derive_object_id` is called, Then "my-track-name" is returned.
- **AC2:** Given a name with non-ASCII characters, When `derive_object_id` is called, Then NFKD normalization strips to ASCII.
- **AC3:** Given a name longer than max_length, When `derive_object_id` is called, Then result is truncated to max_length and trimmed of trailing hyphens.
- **AC4:** Given "my-track" already in existing_ids, When `make_unique_object_id` is called, Then "my-track-2" is returned.
- **AC5:** Given 9998 suffixes exhausted, When `make_unique_object_id` is called, Then `ValueError` is raised.
- **AC6:** Given empty run_id, When `make_session_key` is called, Then `ValueError` is raised.
- **AC7:** Given "run::session", When `parse_session_key` is called, Then ("run", "session") is returned.
- **AC8:** Given "no-separator", When `parse_session_key` is called, Then `ValueError` is raised.
- **AC9:** Given "my-track", When `is_valid_object_id` is called, Then True is returned.
- **AC10:** Given "-my-track" (leading hyphen), When `is_valid_object_id` is called, Then False is returned.

---

## Implementation Approach

### High-Level Architecture

The system is a three-layer design:
1. **HTTP layer** (`library_api_service/`): Thin FastAPI wrapper, JSON parsing, error envelope mapping, trackpoint query thread management.
2. **Adapter layer** (`library_api/adapter.py`): Facade that validates session references, manages caches, and delegates to module functions.
3. **Module layer** (`library_api/*.py`): Stateless functions owning one resource domain each, reading/writing JSON files on disk.

The `library/` package (aggregation stores) is a parallel concern that does not participate in the HTTP API.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| HTTP framework | FastAPI | Async support, automatic OpenAPI, exception handlers |
| Time-series encoding | JSON arrays | Browser-native, simple for v0 |
| Object persistence | JSON files on disk | Simple, debuggable, no database dependency |
| Concurrency control | Revision-based optimistic locking | Prevents lost updates without server-side sessions |
| Trackpoint query execution | Daemon threads | Simple async for localhost single-user |
| GPS source selection | Explicit metadata → legacy heuristic | Backwards compatible with older sessions |
| Track matching | Local equirectangular projection | Avoids heavy geo library dependency |
| Aggregation store | JSON file with schema validation | Consistent with other root-scoped objects |

### Research

- Equirectangular projection is used for track matching (sufficient for local
  bicycle-scale distances). Earth radius hardcoded to 6,371,000 m.
- Min-max bucket downsampling preserves visual shape of signals by keeping
  extrema in each bucket.
- GPS source selection supports multiple sources per session (logger sensor, FIT
  enrichment, imported route) with quality-based preference.

### Alternatives Considered

| Alternative | Why not chosen |
|-------------|----------------|
| Database for root-scoped objects | Adds dependency, harder to debug, overkill for localhost single-user |
| Binary time-series encoding | Not browser-native, deferred per contract |
| Process pool for trackpoint queries | Overkill for localhost; threads sufficient |
| Full geo library (shapely/pyproj) | Heavy dependency; equirectangular sufficient for local tracks |
| File locking | Revision conflict checking sufficient for single-user; locking adds complexity |

## Dependencies

### Design Dependencies
- `docs/design/library-api.md` (this spec's design doc)

### Spec Dependencies
- None (this is a backfill of existing code)

### Package Dependencies
- `bodaqs_analysis.artifacts` (ArtifactStore, list_runs, list_sessions, list_event_types, list_metric_event_types, set_run_description, set_session_description)
- `bodaqs_analysis.gps_semantics` (resolve_gps_columns)
- `bodaqs_analysis.session_notes` (make_session_note_template_store)
- `bodaqs_analysis.widgets.contracts` (AggregationDefinition, SelectionSnapshot, EntitySelectionSnapshot, ScopeEntity, etc.)
- `bodaqs_analysis.widgets.entity_scope` (build_entity_selection_snapshot)
- External: `fastapi`, `uvicorn`, `pandas`, `numpy`, `pyarrow`

## Open Questions

| # | Question | Blocks | Resolution |
|---|----------|--------|------------|
| 1 | Should `update_geospatial_policy` enforce revision conflict checking? | Geospatial policy updates | UNRESOLVED *(unverified intent — needs review)* |
| 2 | Should `LocalAggregationStore` be deprecated in favor of canonical-only? | Aggregation store usage | UNRESOLVED *(unverified intent — needs review)* |
| 3 | Should `bootstrap_canonical_from_local` report skipped aggregations? | Aggregation migration | UNRESOLVED *(unverified intent — needs review)* |
| 4 | Is the daemon-thread concurrency model for trackpoint queries intended long-term? | Trackpoint query execution | UNRESOLVED *(unverified intent — needs review)* |
| 5 | Should GPS gap threshold and default max points be configurable? | GPS summary/points behavior | UNRESOLVED *(unverified intent — needs review)* |
| 6 | Is the hardcoded 25,000 max_points for track match GPS intentional? | Track matching accuracy | UNRESOLVED *(unverified intent — needs review)* |

## Risks

| Risk | Mitigation |
|------|------------|
| Trackpoint query worker killed mid-run leaves query stuck in "running" | No current mitigation; requires manual status update or process restart |
| Non-`LibraryApiError` exceptions return FastAPI default 500 without error envelope | Could add catch-all handler; currently relies on adapter raising typed errors |
| Concurrent writes to same object without file locking could corrupt files | Atomic writes (tmp+replace) prevent partial writes; revision checking prevents lost updates |
| `set_libraries_root` during active query clears thread registry silently | No current mitigation; running worker may fail or write to old path |
| GPS legacy_heuristic may misidentify GPS streams | Explicit `gps_sources` metadata preferred; heuristic is fallback only |

## Success Criteria

- [ ] Design doc accurately describes all components in `library_api/`, `library_api_service/`, and `library/`
- [ ] All REST API endpoints are documented with method, path, and behavior
- [ ] All error types are documented with code, status_code, and trigger conditions
- [ ] All 17 system invariants are documented and traceable to code
- [ ] Failure modes table covers both handled and unhandled cases
- [ ] Ambiguities are classified (intentional / legacy / unknown) with counts
- [ ] Mermaid architecture diagram matches actual code structure
- [ ] Trackpoint query state machine matches actual status transitions
- [ ] Aggregation store validation rules match `validate_aggregation_definition` / `validate_store`
