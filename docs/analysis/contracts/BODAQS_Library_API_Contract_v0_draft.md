# BODAQS Library API Contract v0 Draft

**Status:** Accepted v0 implementation baseline  
**Scope:** Local-first API seam for browsing processed BODAQS libraries, managing root-scoped study sets/tracks/filters, and serving browser-native visualisation data
**Audience:** BODAQS web application, local Library API service, notebook/library adapter implementers

---

## 1. Purpose

This document defines the first API seam between a BODAQS application frontend
and a processed BODAQS library.

The API is intentionally focused on **processed-library use**:

- list configured libraries
- list processed sessions
- create, load, update, and delete study sets
- carry study sets across multiple libraries under one configured libraries root
- expose processed-session GPS availability and quality summaries
- create, load, update, and delete root-scoped tracks, geospatial policies, and
  persisted session filters
- compute or read derived session-track matches where available
- expose compact semantic catalog information
- serve chart-ready time-series windows
- expose event and metric summaries/details where needed

The API is **not** an import or preprocessing API. Logger transfer, folder
watching, raw archive import, preprocessing, event detection, metric extraction,
and canonical artifact writing remain in the Import Manager / Python processing
domain.

The first implementation is expected to be a localhost Python service wrapping a
Python library adapter. The same resource model should remain usable by a future
remote service or static-bundle implementation.

---

## 2. Design Principles

1. **The BODAQS library is the primary data object.**
2. **Study sets are explicit, stable analysis scopes.**
3. **Study set membership is never a hidden live filter.**
4. **The browser owns interaction and visualisation.**
5. **Python remains authoritative for processed-artifact interpretation.**
6. **The API should describe capabilities explicitly.**
7. **The first implementation should be small, but not a dead end.**
8. **Import Manager scope should not expand merely to serve this API.**
9. **Study sets, tracks, and saved filters belong to the configured libraries root, not to one library.**
10. **Geospatial policies make track analysis reproducible.**
11. **Saved filters are reusable helpers; ad-hoc table filters are transient UI state.**
12. **The session catalog stays cheap.** Expensive derived relationships such as
    trackpoint crossings should live in async query/index caches, not in the
    basic session catalog.

---

## 3. Deployment Assumptions For v0

The first local service implementation should:

- bind to `127.0.0.1`
- use REST-ish JSON over HTTP
- read one configured `libraries_root`
- discover multiple libraries under that root
- build an in-memory session catalog from canonical artifacts on service start
- provide an explicit catalog refresh operation
- use JSON arrays for first time-series payloads
- omit authentication in early development

Packaged/local production builds may later add a per-user bearer token while
retaining the same endpoint and payload model.

---

## 4. Resource Model

### 4.0 Libraries Root

The libraries root is the configured local workspace containing one or more
processed BODAQS libraries plus root-scoped application objects.

Root-scoped application objects live under:

```text
<libraries_root>/
  libraries/
    <library_id>/
      library_definition.json
      runs/
      library/
  study_sets/
    <study_set_id>.json
  tracks/
    <track_id>.json
  geospatial_policies/
    <policy_id>.json
  track_matches/
    <track_match_id>.json
  trackpoint_match_queries/
    <query_id>.json
  trackpoint_match_results/
    <query_id>.jsonl
  session_filters/
    <filter_id>.json
```

The first implementation reads one active libraries root at a time. The local
service may expose a setup endpoint for changing that active root, so the
browser can recover when the default configured root is wrong or when the user
needs to move between field and development workspaces.

### 4.1 Library

A library is a processed BODAQS artifacts tree. Multiple libraries may live
under one configured libraries root. Current managed workspaces store processed
libraries under `<libraries_root>/libraries/`; older workspaces with library
directories directly under `<libraries_root>/` remain readable as a legacy
layout.

The API identifies libraries by `library_id`. The exact discovery rule is
implementation-defined for v0, but should prefer existing library metadata such
as `library_definition.json` where present.

### 4.2 Session

A session is a processed logger session under a library run.

The v0 session identity is:

```text
<run_id>::<session_id>
```

Study sets and API payloads should carry `library_id` plus the session identity
fields:

```json
{
  "library_id": "default-library",
  "session_ref_id": "default-library|||run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
  "session_key": "run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
  "run_id": "run_2026-05-25T13-57-10_LOCAL",
  "session_id": "2026-05-18_13-27-14",
  "label": "optional human label"
}
```

`run_id` and `session_id` are canonical. `session_key` is a readable convenience
field and should be validated against those values when written.
`session_ref_id` is the stable Study Set-local reference string:

```text
<library_id>|||<session_key>
```

### 4.3 Study Set

A study set is a named, versioned, portable analysis scope stored with the
configured libraries root. It may contain sessions from more than one library.

Canonical location:

```text
<libraries_root>/
  study_sets/
    <study_set_id>.json
```

Study sets contain:

- explicit session membership
- study-set-local groupings
- reusable track references
- optional references to root-level session bookmarks
- structured provenance
- optional namespaced display state

Study sets do not contain live membership rules. If a filter or track was used
to create a study set, that fact belongs in provenance. Refreshing membership
from a filter or track must be an explicit user action.

### 4.4 Grouping

A grouping is a simple named bucket of sessions inside one study set.

Groupings are not reusable library objects and are not persisted independently.
If reusable discovery logic is needed later, use filters rather than groupings.

### 4.5 Bookmark

A bookmark is a root-level reference to a point or time window in one session.
It is used by signal inspection and later by analysis views that need to filter
or facet data by user-selected time windows.

Canonical location:

```text
<libraries_root>/
  bookmarks/
    <bookmark_id>.json
```

Bookmarks must carry a concrete session reference. They are reusable by Study
Sets and analysis views, but are not session metadata: deleting a bookmark does
not modify the processed session artifact.

### 4.6 Track

A track is a reusable root-level object representing one directed geospatial
path and zero or more named `trackpoints` along that path.

Canonical location:

```text
<libraries_root>/
  tracks/
    <track_id>.json
```

The detailed contract is defined in
`BODAQS_Geospatial_Contracts_v0_draft.md`.

### 4.7 Geospatial Policy

A geospatial policy is a reusable root-level object that defines defaults for
track construction, trackpoint cutlines, session-track matching, and derived
profiles such as heading, gradient, and curvature.

Canonical location:

```text
<libraries_root>/
  geospatial_policies/
    <policy_id>.json
```

The package may provide defaults, but library-root policies should be used when
results need to be reproducible across machines.

### 4.8 Session Track Match

A session track match is a derived analysis result describing how one processed
session maps onto one track under one geospatial policy.

Optional derived-cache location:

```text
<libraries_root>/
  track_matches/
    <track_match_id>.json
```

Session track matches are not canonical session artifacts. They can be
recomputed from the referenced session, track, and policy.

### 4.9 Trackpoint Match Query

A trackpoint match query is a derived, root-scoped, asynchronous job/index used
to answer broad filtering questions such as "which sessions crossed these
trackpoints within this tolerance?"

Optional derived-cache locations:

```text
<libraries_root>/
  trackpoint_match_queries/
    <query_id>.json
  trackpoint_match_results/
    <query_id>.jsonl
```

Trackpoint match queries are not canonical session artifacts and are not Study
Set membership. They may be deleted and rebuilt from session GPS data, tracks,
policies, and persisted filters.

### 4.10 Session Filter

A persisted session filter is a reusable root-level helper for finding candidate
sessions from one or more libraries under the configured libraries root.

Canonical location:

```text
<libraries_root>/
  session_filters/
    <filter_id>.json
```

The detailed contract is defined in
`BODAQS_Session_Filter_Contract_v0_draft.md`.

Saved filters do not define Study Set membership. If a filter was used to create
a Study Set, record it as Study Set provenance only. The Study Set still stores
explicit session references.

Ad-hoc table filters are not `bodaqs.session_filter` objects. They are transient
Session Selector UI state, normally controlled from table column headers.

---

## 5. ID Rules

For user-created objects such as study sets and tracks, IDs should be derived
from display names by default:

```text
"Setup Comparison 1" -> "setup-comparison-1"
```

Recommended rule:

1. trim leading/trailing whitespace
2. lowercase
3. replace whitespace runs with hyphens
4. replace or remove filename-unsafe characters
5. collapse repeated hyphens
6. apply a reasonable length limit
7. add `-2`, `-3`, etc. on conflict

Manual ID override can be added later if needed.

---

## 6. Capability Reporting

The frontend should ask the backend what it can do before enabling features.

Some capabilities are hard requirements for the first browser visualisation app.
If a required capability is unavailable, the frontend should fail fast with a
clear preflight message.

Example:

```json
{
  "schema": "bodaqs.library_api_capabilities",
  "version": 1,
  "service": {
    "name": "BODAQS Library API",
    "api_version": "0",
    "implementation": "python-local-service"
  },
  "required": {
    "read_processed_library": true,
    "read_parquet": true,
    "list_sessions": true,
    "serve_timeseries_windows": true
  },
  "features": {
    "write_study_sets": true,
    "delete_study_sets": true,
    "delete_sessions": true,
    "read_session_gps_summaries": true,
    "read_tracks": true,
    "write_tracks": true,
    "read_geospatial_policies": true,
    "write_geospatial_policies": true,
    "compute_track_matches": true,
    "read_track_matches": true,
    "query_trackpoint_matches": true,
    "cancel_trackpoint_match_queries": true,
    "read_filters": true,
    "write_filters": true,
    "read_analysis_views": true,
    "evaluate_analysis_adequacy": true,
    "export_static_bundle": false,
    "run_processing_jobs": false
  }
}
```

`run_processing_jobs` is included only to make the absence explicit. Import and
preprocessing are outside v0 Library API scope.

---

## 7. Study Set Contract v1

Example:

```json
{
  "schema": "bodaqs.study_set",
  "version": 1,
  "study_set_id": "setup-comparison",
  "revision": 3,
  "display_name": "Setup comparison",
  "sessions": [
    {
      "library_id": "default-library",
      "session_ref_id": "default-library|||run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
      "session_key": "run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
      "run_id": "run_2026-05-25T13-57-10_LOCAL",
      "session_id": "2026-05-18_13-27-14",
      "label": "Prototype F - baseline"
    }
  ],
  "groupings": [
    {
      "grouping_id": "baseline",
      "display_name": "Baseline",
      "session_refs": [
        "default-library|||run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14"
      ]
    }
  ],
  "tracks": [
    {
      "track_id": "munda-biddi-test-loop",
      "display_name": "Munda Biddi test loop",
      "from_trackpoint_id": "start-gate",
      "to_trackpoint_id": "rock-garden-entry"
    }
  ],
  "bookmarks": [
    {
      "bookmark_id": "big-compression-before-bridge",
      "display_name": "Big compression before bridge",
      "session_ref": "default-library|||run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
      "time_window": {
        "start_s": 123.4,
        "end_s": 128.9
      },
      "notes": ""
    }
  ],
  "provenance": {
    "created_at": "2026-05-28T03:00:00Z",
    "created_by": "user",
    "created_from": {
      "kind": "manual_selection",
      "details": {}
    },
    "updated_at": "2026-05-28T03:05:00Z"
  },
  "display_state": {
    "bodaqs_web_v1": {}
  }
}
```

Validation notes:

- `schema` must be `bodaqs.study_set`.
- `version` must be supported by the service.
- `study_set_id` must be filename-safe and unique within the libraries root.
- `revision` is assigned by the service and must increment on successful write.
- top-level `sessions` are explicit membership and are the source of truth.
- every top-level session ref must include `library_id`, `session_ref_id`,
  `session_key`, `run_id`, and `session_id`.
- `session_key` must match `run_id::session_id`.
- `session_ref_id` must match `library_id|||session_key`.
- grouping `session_refs` should refer to top-level `session_ref_id` values.
- bookmark `session_ref` values should refer to top-level `session_ref_id` values.
- bookmark entries should define exactly one of `time_s` or `time_window`.
- study-set track intervals should use `from_trackpoint_id` and
  `to_trackpoint_id` when referencing a subset of a track.
- `display_state` is optional and non-authoritative.

---

## 8. Track Contract v1

The authoritative Track, Trackpoint, Geospatial Policy, and Session Track Match
object contracts are defined in `BODAQS_Geospatial_Contracts_v0_draft.md`.

The API-facing summary is:

- tracks are root-scoped objects under the configured libraries root.
- a track contains one and only one directed geospatial path.
- trackpoints are named locations along that path, ordered by `station_m`.
- default trackpoint cutlines are generated from policy.
- trackpoints store only cutline overrides unless explicit geometry editing is
  introduced later.
- heading, gradient, curvature, and session-track coverage are derived
  geospatial analysis outputs, not minimal canonical track fields.

Minimal API example:

```json
{
  "schema": "bodaqs.track",
  "version": 1,
  "track_id": "munda-biddi-test-loop",
  "revision": 1,
  "display_name": "Munda Biddi test loop",
  "path": {
    "type": "LineString",
    "coordinates": [
      [115.8571, -31.9523, 210.2],
      [115.8580, -31.9531, 208.7]
    ],
    "coordinate_reference_system": "EPSG:4326",
    "distance_model": "geodesic",
    "length_m": 1420.5
  },
  "direction": {
    "positive": "coordinate_order"
  },
  "default_policy_ref": {
    "policy_id": "default-geospatial-policy",
    "version": 1
  },
  "trackpoints": [
    {
      "trackpoint_id": "start-gate",
      "display_name": "Start gate",
      "station_m": 0.0,
      "position": {
        "type": "Point",
        "coordinates": [115.8571, -31.9523, 210.2]
      }
    },
    {
      "trackpoint_id": "rock-garden-entry",
      "display_name": "Rock garden entry",
      "station_m": 248.5,
      "position": {
        "type": "Point",
        "coordinates": [115.8580, -31.9531, 208.7]
      },
      "cutline_override": {
        "left_length_m": 8.0,
        "right_length_m": 4.0
      }
    }
  ],
  "source": {
    "kind": "session_gps",
    "library_id": "default-library",
    "session_ref_id": "default-library|||run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
    "session_key": "run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
    "run_id": "run_2026-05-25T13-57-10_LOCAL",
    "session_id": "2026-05-18_13-27-14"
  },
  "provenance": {
    "created_at": "2026-05-28T03:00:00Z",
    "created_by": "user"
  }
}
```

Track `source` is optional. A track may be authored from a session GPS path,
imported from GPX/GeoJSON in the future, or created manually.

A study set may reference a whole track by `track_id`, or a track interval by
`track_id + from_trackpoint_id + to_trackpoint_id`.

Track ids are unique within the libraries root. They are not scoped to an
individual processed library.

---

## 9. Session Filter Contract v1

The authoritative persisted Session Filter object contract is defined in
`BODAQS_Session_Filter_Contract_v0_draft.md`.

The API-facing summary is:

- persisted filters are root-scoped objects under the configured libraries root.
- a filter contains a named predicate over session catalog fields and, later,
  derived summaries.
- multiple applied saved filters are combined with `AND` by default.
- ad-hoc table filters are separate transient UI state and are not saved unless
  the user explicitly creates or copies a persisted filter.
- Study Sets store explicit session membership; filters may appear only in
  provenance unless an explicit refresh/update action is added later.

Minimal API example:

```json
{
  "schema": "bodaqs.session_filter",
  "version": 1,
  "filter_id": "ben-rides-with-usable-gps",
  "revision": 1,
  "display_name": "Ben rides with usable GPS",
  "description": "Reusable helper for GPS comparison sessions.",
  "category": "gps",
  "predicate": {
    "op": "and",
    "children": [
      {
        "field": "rider",
        "op": "contains",
        "value": "ben"
      },
      {
        "field": "gps.quality",
        "op": "eq",
        "value": "usable"
      }
    ]
  },
  "display_state": {
    "bodaqs_web_v1": {}
  }
}
```

---

## 10. Session Catalog Row Contract v1

The service should build the session catalog from canonical artifacts and cache
it in memory. The catalog source of truth remains the run/session artifacts on
disk.

Rows should include enough compact semantic information for study-set building
and simple adequacy checks, while leaving full session details behind separate
detail/query endpoints.

Example:

```json
{
  "schema": "bodaqs.session_catalog_row",
  "version": 1,
  "library_id": "default-library",
  "session_ref_id": "default-library|||run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
  "session_key": "run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
  "run_id": "run_2026-05-25T13-57-10_LOCAL",
  "session_id": "2026-05-18_13-27-14",
  "display": {
    "label": "Prototype F - 2026-05-18 13:27",
    "run_label": "Prototype F import",
    "session_label": "2026-05-18_13-27-14"
  },
  "timestamps": {
    "started_at_utc": "2026-05-18T05:27:14Z",
    "started_at_local": "2026-05-18T13:27:14+08:00",
    "processed_at": "2026-05-25T13:57:10+08:00",
    "imported_at": "2026-05-25T13:57:10+08:00"
  },
  "note_status": {
    "status": "edited",
    "has_note": true,
    "draft": false,
    "template_id": "import_agent_bike_setup",
    "template_version": "1.0"
  },
  "note_fields": {
    "bike": "Stumpjumper Evo",
    "rider": "Ben"
  },
  "qc_summary": {
    "status": "warning",
    "warning_count": 2,
    "error_count": 0
  },
  "summary": {
    "n_rows": 122480,
    "t_start_s": 0.0,
    "t_end_s": 612.4,
    "duration_s": 612.4,
    "duration_min": 10.2067,
    "distance_km": 1.42
  },
  "gps_summary": {
    "schema": "bodaqs.session_gps_summary",
    "version": 1,
    "present": true,
    "preferred_source": "gps_logger",
    "preferred_source_id": "gps_logger",
    "preferred_source_kind": "logger_sensor",
    "source_selection_method": "gps_sources",
    "gps_source_policy": {
      "preferred_source": "logger_then_fit",
      "preserve_all_sources": true
    },
    "session_duration_s": 612.4,
    "time_coverage_ratio": 0.94,
    "position_point_count": 1234,
    "quality": "usable",
    "sources": [
      {
        "source_id": "gps_logger",
        "kind": "logger_sensor",
        "stream_name": "gps_logger",
        "timebase": "intermittent",
        "point_count": 1234,
        "nominal_sample_rate_hz": 1.0,
        "median_gap_s": 1.0,
        "max_gap_s": 8.2
      }
    ],
    "warnings": []
  },
  "provenance": {
    "source_type": "logger_wifi",
    "source_id": "prototype-f",
    "logger_id": "Prototype F",
    "archive_name": "2026-02-19_09-43-31_3.zip",
    "processing_key": "7f273ed9348c54cdafe707412abcbd661b7dd3414a71f914efa830d237423918",
    "preprocessing_profile": "suspension_default_v1",
    "preprocess_profile_path": "sources/ben-stevo/preprocess_profile.json",
    "firmware_version": "0.3.0",
    "bike_profile_id": "ben-stevo",
    "bike_profile_path": "../bike_profiles/ben-stevo.json"
  },
  "event_schema": {
    "schema_id": "basic_suspension_events",
    "display_name": "Basic suspension events"
  },
  "available_signals": [
    {
      "signal_id": "front_wheel_disp_dom_wheel_mm",
      "column": "front_wheel_disp_dom_wheel [mm]",
      "display_name": "Front wheel travel",
      "end": "front",
      "domain": "wheel",
      "quantity": "disp",
      "unit": "mm",
      "processing_role": "primary_analysis"
    },
    {
      "signal_id": "rear_wheel_disp_dom_wheel_mm",
      "column": "rear_wheel_disp_dom_wheel [mm]",
      "display_name": "Rear wheel travel",
      "end": "rear",
      "domain": "wheel",
      "quantity": "disp",
      "unit": "mm",
      "processing_role": "primary_analysis"
    }
  ],
  "event_summary": {
    "total_count": 42,
    "by_type": {
      "bottom_out": 2,
      "jump": 4
    }
  },
  "metric_summary": {
    "metric_count": 12,
    "event_count_with_metrics": 38
  }
}
```

Recommended `note_status.status` values:

```text
missing | draft | edited
```

`edited` means a reviewed/saved note is available. Unreadable or invalid note
documents should still report `status: "missing"` and may include diagnostic
fields such as `error`.

Recommended `qc_summary.status` values:

```text
ok | warning | alert
```

Recommended `gps_summary.quality` values are defined in
`BODAQS_Geospatial_Contracts_v0_draft.md`:

```text
absent | limited | usable | invalid
```

The first projected `note_fields` should include `bike` and `rider` where
available. Additional projected fields may be added later without changing the
core row shape.

---

## 11. Time-Series Window Contract v1

The first high-value browser-native visualisation is a one-session time-series
window view, initially for front/rear wheel travel and event overlays.

### 11.1 Request

Endpoint:

```text
POST /api/v1/libraries/{library_id}/timeseries/window
```

Example request:

```json
{
  "session": {
    "library_id": "default-library",
    "session_ref_id": "default-library|||run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
    "session_key": "run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
    "run_id": "run_2026-05-25T13-57-10_LOCAL",
    "session_id": "2026-05-18_13-27-14"
  },
  "signals": [
    {
      "selector": {
        "end": "front",
        "domain": "wheel",
        "quantity": "disp",
        "unit": "mm",
        "processing_role": "primary_analysis"
      }
    },
    {
      "selector": {
        "end": "rear",
        "domain": "wheel",
        "quantity": "disp",
        "unit": "mm",
        "processing_role": "primary_analysis"
      }
    },
    {
      "column": "rear_wheel_disp_dom_wheel [mm]"
    }
  ],
  "window": {
    "start_s": 10.0,
    "end_s": 20.0
  },
  "resolution": {
    "target_points": 2000
  },
  "include_events": true,
  "include_marks": true
}
```

Signals may be requested by semantic selector or concrete column. UI flows should
prefer semantic selectors. Concrete columns are useful for data-explorer and
debugging views.

`include_events` controls event-table overlays. `include_marks` controls
logger/sample mark overlays from the processed session dataframe, normally the
truthy/non-zero values in the `mark` column.

The endpoint serves one session per request in v1. The path `library_id` must
match `session.library_id` when that request field is present. Comparison views
should make multiple requests and align results in the frontend.

### 11.2 Response

Example response:

```json
{
  "schema": "bodaqs.timeseries_window",
  "version": 1,
  "encoding": "json_arrays",
  "session": {
    "library_id": "default-library",
    "session_ref_id": "default-library|||run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
    "session_key": "run_2026-05-25T13-57-10_LOCAL::2026-05-18_13-27-14",
    "run_id": "run_2026-05-25T13-57-10_LOCAL",
    "session_id": "2026-05-18_13-27-14"
  },
  "window": {
    "requested_start_s": 10.0,
    "requested_end_s": 20.0,
    "returned_start_s": 10.0,
    "returned_end_s": 20.0
  },
  "sampling": {
    "mode": "raw",
    "source_points": 1000,
    "returned_points": 1000,
    "target_points": 2000
  },
  "time": {
    "unit": "s",
    "values": [10.0, 10.001, 10.002]
  },
  "signals": [
    {
      "signal_id": "front_wheel_disp_dom_wheel_mm",
      "column": "front_wheel_disp_dom_wheel [mm]",
      "display_name": "Front wheel travel",
      "end": "front",
      "domain": "wheel",
      "quantity": "disp",
      "unit": "mm",
      "processing_role": "primary_analysis",
      "values": [1.2, 1.3, 1.4]
    },
    {
      "signal_id": "rear_wheel_disp_dom_wheel_mm",
      "column": "rear_wheel_disp_dom_wheel [mm]",
      "display_name": "Rear wheel travel",
      "end": "rear",
      "domain": "wheel",
      "quantity": "disp",
      "unit": "mm",
      "processing_role": "primary_analysis",
      "values": [8.1, 8.4, 8.2]
    }
  ],
  "events": [
    {
      "event_id": "evt-001",
      "event_type": "bottom_out",
      "display_name": "Bottom out",
      "start_s": 12.34,
      "end_s": 12.56,
      "peak_time_s": 12.42,
      "end": "rear"
    }
  ],
  "marks": [
    {
      "mark_id": "mark-1",
      "time_s": 14.72,
      "display_name": "Mark 1",
      "column": "mark"
    }
  ],
  "warnings": []
}
```

### 11.3 Downsampling

Recommended v1 behavior:

1. If source samples in the requested window are less than or equal to
   `target_points`, return raw samples.
2. If source samples exceed `target_points`, use min/max bucket decimation.
3. Preserve time order in the returned arrays.
4. Record sampling mode and source/returned counts in the response.

Example decimated sampling block:

```json
{
  "mode": "min_max_bucket",
  "source_points": 120000,
  "returned_points": 2400,
  "target_points": 2000
}
```

---

## 12. Endpoint List v0

### 12.1 Service

```text
GET /api/v1/health
GET /api/v1/capabilities
POST /api/v1/config/libraries-root
```

### 12.2 Libraries

```text
GET  /api/v1/libraries
GET  /api/v1/libraries/{library_id}
POST /api/v1/libraries/{library_id}/refresh
GET  /api/v1/libraries/{library_id}/catalog
```

The first implementation discovers libraries under the active `libraries_root`.
`POST /api/v1/config/libraries-root` is a local setup operation: the browser
sends a service-local filesystem path, the service validates/discovers that
root, and subsequent calls use the new adapter state. This is not an Import
Manager import/preprocessing operation.

### 12.3 Session Curation

```text
POST /api/v1/libraries/{library_id}/sessions/note
PUT  /api/v1/libraries/{library_id}/sessions/note
PUT  /api/v1/libraries/{library_id}/sessions/descriptions
DELETE /api/v1/libraries/{library_id}/runs/{run_id}/sessions/{session_id}
```

`sessions/descriptions` updates the short manifest-backed run/session
description fields for one session reference. `run_description` applies to the
whole run; `session_description` applies only to the referenced session.

`DELETE .../runs/{run_id}/sessions/{session_id}` removes the processed session
artifact directory from the selected library. It must not delete original source
archives, FIT files, logger uploads, or other import-source material. By
default, the service must refuse to delete a session that is still referenced by
saved root-level objects, returning `409 session_delete_conflict` with reference
details. If the caller explicitly supplies `cleanup_memberships=true`, the
service may remove that session from saved Study Sets, remove bookmarks for that
session, delete groupings that become empty, and then delete the processed
session artifact.

Example guarded delete:

```text
DELETE /api/v1/libraries/default-library/runs/run-a/sessions/session-a
```

Example delete with saved-membership cleanup:

```text
DELETE /api/v1/libraries/default-library/runs/run-a/sessions/session-a?cleanup_memberships=true
```

Example conflict response:

```json
{
  "error": {
    "code": "session_delete_conflict",
    "message": "Session is still referenced by saved library objects.",
    "details": {
      "session_ref_id": "default-library|||run-a::session-a",
      "references": [
        {
          "study_set_id": "setup-comparison",
          "display_name": "Setup comparison",
          "session_member": true,
          "groupings": [
            {"grouping_id": "baseline", "display_name": "Baseline"}
          ],
          "bookmarks": []
        },
        {
          "kind": "bookmark",
          "bookmark_id": "big-compression-before-bridge",
          "display_name": "Big compression before bridge"
        }
      ]
    }
  }
}
```

Example successful cleanup response:

```json
{
  "deleted": true,
  "library_id": "default-library",
  "run_id": "run-a",
  "session_id": "session-a",
  "session_key": "run-a::session-a",
  "session_ref_id": "default-library|||run-a::session-a",
  "cleanup_memberships": true,
  "removed_paths": ["C:/BODAQS-data/default-library/runs/run-a/sessions/session-a"],
  "updated_study_sets": [
    {
      "study_set_id": "setup-comparison",
      "previous_revision": 3,
      "revision": 4,
      "removed_session": true,
      "removed_groupings": [],
      "removed_bookmark_count": 0
    }
  ],
  "removed_bookmarks": [
    {
      "bookmark_id": "big-compression-before-bridge",
      "display_name": "Big compression before bridge"
    }
  ]
}
```

Example request:

```json
{
  "session_ref": {
    "library_id": "default-library",
    "session_ref_id": "default-library|||run-a::session-a",
    "session_key": "run-a::session-a",
    "run_id": "run-a",
    "session_id": "session-a"
  },
  "run_description": "Morning shuttle laps",
  "session_description": "Lower chute run"
}
```

### 12.4 Analysis Views And Adequacy

```text
GET  /api/v1/analysis-views
POST /api/v1/analysis-views/{view_id}/adequacy
```

Analysis views are registered browser-facing analysis destinations. The first
implemented view is `simple-suspension`. The registry is intentionally small in
v0: it advertises discoverable view metadata and the requirements that are used
by the adequacy endpoint.

Adequacy checks distinguish the whole requested scope from individual sessions
and analyzable units such as `session_end`. Status values are:

- `ready`: the scope can run cleanly.
- `warning`: all selected sessions have at least one usable analysis unit, but
  recommended or optional features are missing.
- `partial`: at least one session is usable and at least one selected session
  is blocked or excluded.
- `blocked`: no selected sessions have the required data needed to launch the
  view meaningfully.

Requirements are tiered:

- `required`: needed for the view to have any meaningful output.
- `recommended`: needed for the full intended comparison or chart set, but not
  enough by itself to block launch.
- `optional`: enriches the view or unlocks secondary features.

For `simple-suspension`, the first adequacy policy treats wheel motion data
for at least one suspension end as required. In this contract, wheel motion data
means wheel displacement plus velocity evidence. Velocity evidence may come
from a semantic velocity signal or from compression/rebound velocity metrics.
Both ends, complete compression/rebound event metrics, and GPS/sector support
are treated as completeness features.

Example registry response entry:

```json
{
  "schema": "bodaqs.analysis_view",
  "version": 1,
  "view_id": "simple-suspension",
  "display_name": "Simple Suspension Analysis",
  "category": "Suspension",
  "route": "/analysis/simple-suspension",
  "scope_kinds": ["study_set", "session_refs"],
  "adequacy_policy": "partial",
  "requirements": {
    "required": [
      {
        "id": "wheel_motion_data",
        "applies_to": "session_end",
        "minimum": "at_least_one_end"
      }
    ],
    "recommended": [
      {"id": "both_ends", "applies_to": "session"},
      {"id": "event_metrics", "applies_to": "session"}
    ],
    "optional": [
      {"id": "gps", "applies_to": "session"}
    ]
  }
}
```

Example adequacy request using explicit sessions:

```json
{
  "sessions": [
    {
      "library_id": "default-library",
      "session_ref_id": "default-library|||run-a::session-a",
      "session_key": "run-a::session-a",
      "run_id": "run-a",
      "session_id": "session-a"
    }
  ]
}
```

Example adequacy request using a saved Study Set:

```json
{
  "study_set_id": "setup-comparison"
}
```

Example response:

```json
{
  "schema": "bodaqs.analysis_adequacy",
  "version": 1,
  "view_id": "simple-suspension",
  "status": "warning",
  "policy": "partial",
  "summary": "1 of 1 sessions can be analyzed with missing recommended or optional data.",
  "total_session_count": 1,
  "usable_session_count": 1,
  "blocked_session_count": 0,
  "usable_units": [
    {
      "session_ref_id": "default-library|||run-a::session-a",
      "unit_kind": "session_end",
      "end": "front"
    }
  ],
  "excluded_units": [
    {
      "session_ref_id": "default-library|||run-a::session-a",
      "unit_kind": "session_end",
      "end": "rear",
      "missing_required": ["wheel_displacement_signal", "wheel_velocity_data"]
    }
  ],
  "messages": [
    {
      "severity": "warning",
      "code": "missing_event_metrics",
      "message": "1 session(s) lack complete compression/rebound metric support."
    }
  ],
  "session_results": [
    {
      "session_ref_id": "default-library|||run-a::session-a",
      "status": "warning",
      "usable": true,
      "usable_end_count": 1,
      "missing_recommended": ["both_ends", "event_metrics"],
      "missing_optional": ["gps"]
    }
  ]
}
```

### 12.5 Study Sets

```text
GET    /api/v1/study-sets
POST   /api/v1/study-sets
GET    /api/v1/study-sets/{study_set_id}
PUT    /api/v1/study-sets/{study_set_id}
DELETE /api/v1/study-sets/{study_set_id}
```

Study Set endpoints are scoped to the configured libraries root, not to a single
processed library. Study Set writes should use revision checks.

Example update request:

```json
{
  "expected_revision": 3,
  "study_set": {
    "schema": "bodaqs.study_set",
    "version": 1,
    "study_set_id": "setup-comparison",
      "revision": 3,
      "display_name": "Setup comparison",
      "sessions": [],
    "groupings": [],
    "tracks": [],
    "bookmarks": [],
    "provenance": {
      "created_at": "2026-05-28T03:00:00Z",
      "created_by": "user",
      "created_from": {
        "kind": "manual_selection",
        "details": {}
      },
      "updated_at": "2026-05-28T03:05:00Z"
    },
    "display_state": {
      "bodaqs_web_v1": {}
    }
  }
}
```

### 12.6 Geospatial

Root-scoped tracks:

```text
GET    /api/v1/tracks
POST   /api/v1/tracks
GET    /api/v1/tracks/{track_id}
PUT    /api/v1/tracks/{track_id}
DELETE /api/v1/tracks/{track_id}
```

Root-scoped geospatial policies:

```text
GET    /api/v1/geospatial-policies
POST   /api/v1/geospatial-policies
GET    /api/v1/geospatial-policies/{policy_id}
PUT    /api/v1/geospatial-policies/{policy_id}
DELETE /api/v1/geospatial-policies/{policy_id}
```

Session GPS summaries and session-track matching:

```text
POST /api/v1/libraries/{library_id}/sessions/gps-summary
POST /api/v1/libraries/{library_id}/sessions/gps/points
POST /api/v1/track-matches/query
POST /api/v1/track-matches/compute
GET  /api/v1/track-matches/{track_match_id}

POST   /api/v1/trackpoint-match-queries
GET    /api/v1/trackpoint-match-queries/{query_id}
GET    /api/v1/trackpoint-match-queries/{query_id}/results
DELETE /api/v1/trackpoint-match-queries/{query_id}
```

The GPS summary endpoint accepts a session reference in the request body and
returns the `SessionGpsSummary` defined in
`BODAQS_Geospatial_Contracts_v0_draft.md`.

The GPS points endpoint accepts a session reference plus optional `source_id`,
`max_points`, and `window` fields, and returns downsampled longitude/latitude
points for offline browser preview. If `source_id` is omitted, the service uses
the `SessionGpsSummary.preferred_source_id`. The session catalog remains
summary-only; full GPS geometry is loaded on demand. If `window` is omitted, the
service must default to the processed session's own primary `time_s` bounds
rather than returning an entire auxiliary GPS/FIT stream.

Track and policy endpoints are scoped to the configured libraries root, not to
one processed library. Track match endpoints may return cached derived matches
or compute new matches, depending on service capabilities.

Trackpoint match query endpoints are for broad, potentially library-scale
filtering. `POST` should return quickly with a queued/running/completed query
object instead of blocking until all candidate sessions have been processed.
`GET .../results` should be paged and should return matched sessions by
default. Rejected session evidence should be optional diagnostics, not the
default response.

Broad query scopes should be described declaratively with `library_ids`,
`session_filter_ids`, or other root-scoped criteria rather than requiring the
browser to enumerate every session. Narrow UI-driven requests may still provide
explicit `session_refs`.

### 12.7 Session Filters

Root-scoped persisted session filters:

```text
GET    /api/v1/session-filters
POST   /api/v1/session-filters
GET    /api/v1/session-filters/{filter_id}
PUT    /api/v1/session-filters/{filter_id}
DELETE /api/v1/session-filters/{filter_id}
```

### 12.8 Bookmarks

Root-scoped persisted session bookmarks:

```text
GET    /api/v1/bookmarks
POST   /api/v1/bookmarks
GET    /api/v1/bookmarks/{bookmark_id}
PUT    /api/v1/bookmarks/{bookmark_id}
DELETE /api/v1/bookmarks/{bookmark_id}
```

`GET /api/v1/bookmarks` may be filtered by `library_id`, `session_key`, or
`session_ref_id`. Bookmarks are stored under the configured libraries root and
must carry a concrete `session` reference. They are intended for user-selected
points or time windows, not for logger sample marks.

Example bookmark:

```json
{
  "schema": "bodaqs.session_bookmark",
  "version": 1,
  "bookmark_id": "big-compression-before-bridge",
  "revision": 1,
  "display_name": "Big compression before bridge",
  "description": "",
  "session": {
    "library_id": "default-library",
    "session_ref_id": "default-library|||run-a::session-a",
    "session_key": "run-a::session-a",
    "run_id": "run-a",
    "session_id": "session-a",
    "label": "Session A"
  },
  "session_ref_id": "default-library|||run-a::session-a",
  "window": {
    "start_s": 42.5,
    "end_s": 48.0
  },
  "view_state": {
    "bodaqs_web_signal_inspector_v1": {
      "signal_columns": ["front_wheel_disp_dom_wheel [mm]"],
      "show_marks": true
    }
  },
  "tags": [],
  "private": true,
  "provenance": {
    "created_at": "2026-06-26T01:00:00Z",
    "created_by": "user",
    "updated_at": "2026-06-26T01:00:00Z"
  }
}
```

Session Filter endpoints are scoped to the configured libraries root, not to a
single processed library. Filter writes should use revision checks.

### 12.8 Signals, Events, Metrics, And Time-Series

```text
POST /api/v1/libraries/{library_id}/signals/query
POST /api/v1/libraries/{library_id}/events/query
POST /api/v1/libraries/{library_id}/metrics/query
POST /api/v1/libraries/{library_id}/timeseries/window
```

The first implementation only needs `timeseries/window` plus whatever minimal
signal/catalog support the frontend needs to choose valid signals. `events/query`
and `metrics/query` may start as table-oriented endpoints after the catalog and
window endpoint are working.

---

## 13. Error Response Contract

All API errors should use a consistent envelope:

```json
{
  "error": {
    "code": "study_set_not_found",
    "message": "Study set was not found.",
    "details": {
      "study_set_id": "setup-comparison"
    }
  }
}
```

Use normal HTTP status codes for broad categories and `error.code` for frontend
behavior.

Recommended initial error codes:

```text
library_not_found
session_not_found
study_set_not_found
session_filter_not_found
track_not_found
geospatial_policy_not_found
track_match_not_found
invalid_request
invalid_study_set
invalid_session_filter
invalid_track
invalid_geospatial_policy
revision_conflict
capability_unavailable
gps_unavailable
signal_not_found
track_match_unavailable
trackpoint_match_query_not_found
trackpoint_match_query_unavailable
timeseries_unavailable
internal_error
```

Revision conflict example:

```json
{
  "error": {
    "code": "revision_conflict",
    "message": "Study set was modified after it was loaded.",
    "details": {
      "study_set_id": "setup-comparison",
      "expected_revision": 3,
      "current_revision": 4
    }
  }
}
```

---

## 14. First Implementation Cut

The smallest useful v0 service should implement:

1. `GET /api/v1/health`
2. `GET /api/v1/capabilities`
3. `GET /api/v1/libraries`
4. `GET /api/v1/libraries/{library_id}/catalog`
5. `POST /api/v1/libraries/{library_id}/refresh`
6. root-scoped Study Set CRUD
7. `POST /api/v1/libraries/{library_id}/timeseries/window`

This is enough to support two parallel workstreams:

- library manager / study set builder
- first browser-native time-series visualisation

The first geospatial extension should add:

1. `gps_summary` in catalog rows
2. `POST /api/v1/libraries/{library_id}/sessions/gps-summary`
3. root-scoped Track CRUD
4. root-scoped Geospatial Policy read/list, with at least one default policy
5. session-track match computation as a derived, non-preprocessing analysis job

The first persisted-filter extension should add:

1. root-scoped Session Filter CRUD
2. loading saved filters into the web app Filters pane
3. applying catalog-backed saved filters in the browser
4. keeping ad-hoc table filters separate from persisted filter objects

The first trackpoint-filter extension should add:

1. track and trackpoint inventory loading from root-scoped Track objects
2. a planned `trackpoint.crossing` saved-filter predicate shape
3. async `trackpoint-match-queries` endpoints with status polling and paged
   matched-session results
4. cache keys based on session GPS identity, track revision, policy, tolerance,
   match mode, and algorithm version
5. browser states for queued/running/partial/complete trackpoint filters

---

## 15. Deferred Work

The following are deliberately outside the first implementation:

- import, logger transfer, and preprocessing endpoints
- user accounts and hosted-service concerns
- LAN-facing service access
- authentication tokens for development mode
- persisted catalog indexes
- full visual filter-builder UI
- ad-hoc table-header filter persistence
- advanced track editing, including explicit cutline endpoint editing
- mature persisted track match and trackpoint query cache management
- GPX/GeoJSON import/export
- static bundle export
- Arrow/binary time-series payloads
- multi-session time-series window requests
- browser-local direct filesystem implementation

These may be added later without changing the core resource model if the v0
contracts are kept stable.
