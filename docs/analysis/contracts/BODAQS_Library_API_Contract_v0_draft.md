# BODAQS Library API Contract v0 Draft

**Status:** Accepted v0 implementation baseline  
**Scope:** Local-first API seam for browsing processed BODAQS libraries, managing root-scoped study sets/tracks, and serving browser-native visualisation data  
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
9. **Study sets and tracks belong to the configured libraries root, not to one library.**

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
  study_sets/
    <study_set_id>.json
  tracks/
    <track_id>.json
```

The first implementation reads one active libraries root at a time. The local
service may expose a setup endpoint for changing that active root, so the
browser can recover when the default configured root is wrong or when the user
needs to move between field and development workspaces.

### 4.1 Library

A library is a processed BODAQS artifacts tree. Multiple libraries may live under
one configured libraries root.

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
- study-set-local bookmarks
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

A bookmark is a study-set-local reference to a point or time window in one
session.

Bookmarks are not reusable library objects in v0 because their meaning is
intrinsically tied to the study set where they were created.

### 4.6 Track

A track is a reusable root-level object representing a route/path and optional
named points along that route.

Canonical future location:

```text
<libraries_root>/
  tracks/
    <track_id>.json
```

The v0 API contract defines track objects and references, but the first endpoint
implementation does not need to include track CRUD.

### 4.7 Filter

A filter is a future reusable library helper for finding candidate sessions.

Filters are not part of the first endpoint implementation. If a filter was used
to create a study set, record it as study-set provenance only.

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
    "read_tracks": false,
    "write_tracks": false,
    "read_filters": false,
    "write_filters": false,
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
      "from_point_id": "start-gate",
      "to_point_id": "rock-garden-entry"
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
- `display_state` is optional and non-authoritative.

---

## 8. Track Contract v1

Example:

```json
{
  "schema": "bodaqs.track",
  "version": 1,
  "track_id": "munda-biddi-test-loop",
  "display_name": "Munda Biddi test loop",
  "geometry": {
    "type": "LineString",
    "coordinates": [
      [115.8571, -31.9523],
      [115.8580, -31.9531]
    ]
  },
  "points": [
    {
      "point_id": "start-gate",
      "display_name": "Start gate",
      "position": {
        "type": "Point",
        "coordinates": [115.8571, -31.9523]
      },
      "route_fraction": 0.0
    },
    {
      "point_id": "rock-garden-entry",
      "display_name": "Rock garden entry",
      "position": {
        "type": "Point",
        "coordinates": [115.8580, -31.9531]
      },
      "route_fraction": 0.42
    }
  ],
  "source": {
    "kind": "session",
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
`track_id + from_point_id + to_point_id`.

Track ids are unique within the libraries root. They are not scoped to an
individual processed library.

---

## 9. Session Catalog Row Contract v1

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
  "provenance": {
    "source_type": "logger_wifi",
    "source_id": "prototype-f",
    "logger_id": "Prototype F",
    "archive_name": "2026-02-19_09-43-31_3.zip",
    "processing_key": "7f273ed9348c54cdafe707412abcbd661b7dd3414a71f914efa830d237423918"
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

The first projected `note_fields` should include `bike` and `rider` where
available. Additional projected fields may be added later without changing the
core row shape.

---

## 10. Time-Series Window Contract v1

The first high-value browser-native visualisation is a one-session time-series
window view, initially for front/rear wheel travel and event overlays.

### 10.1 Request

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
  "include_events": true
}
```

Signals may be requested by semantic selector or concrete column. UI flows should
prefer semantic selectors. Concrete columns are useful for data-explorer and
debugging views.

The endpoint serves one session per request in v1. The path `library_id` must
match `session.library_id` when that request field is present. Comparison views
should make multiple requests and align results in the frontend.

### 10.2 Response

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
  "warnings": []
}
```

### 10.3 Downsampling

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

## 11. Endpoint List v0

### 11.1 Service

```text
GET /api/v1/health
GET /api/v1/capabilities
POST /api/v1/config/libraries-root
```

### 11.2 Libraries

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

### 11.3 Study Sets

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

### 11.4 Signals, Events, Metrics, And Time-Series

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

## 12. Error Response Contract

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
track_not_found
invalid_request
invalid_study_set
revision_conflict
capability_unavailable
signal_not_found
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

## 13. First Implementation Cut

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

---

## 14. Deferred Work

The following are deliberately outside the first implementation:

- import, logger transfer, and preprocessing endpoints
- user accounts and hosted-service concerns
- LAN-facing service access
- authentication tokens for development mode
- persisted catalog indexes
- track CRUD endpoints
- filter CRUD endpoints
- static bundle export
- Arrow/binary time-series payloads
- multi-session time-series window requests
- browser-local direct filesystem implementation

These may be added later without changing the core resource model if the v0
contracts are kept stable.
