# BODAQS Session Filter Contract v0 Draft

**Status:** Draft  
**Scope:** Persisted reusable filters for selecting candidate sessions from a
BODAQS libraries root  
**Audience:** BODAQS web application, Library API service, notebook/library
adapter implementers

---

## 1. Purpose

A persisted session filter is a named reusable helper for finding candidate
sessions. It describes a predicate over session catalog fields, signal metadata,
and later derived summaries.

Persisted filters are **not** Study Set definitions. Applying a filter changes
which sessions are visible or selectable. Adding sessions to a Study Set still
writes explicit session references.

Ad-hoc table filters are also outside this contract. They are transient UI state
owned by the Session Selector table headers. They may combine with persisted
filters during browsing, but they are not saved as `bodaqs.session_filter`
objects unless the user explicitly saves or copies them into a persisted filter.

---

## 2. Resource Scope

Persisted filters are root-level application objects.

Canonical location:

```text
<libraries_root>/
  session_filters/
    <filter_id>.json
```

Filters are scoped to the configured libraries root, not to an individual
processed library. A filter may optionally restrict its own applicability through
`scope`, but the file still lives at the root.

---

## 3. Filter Object

Example:

```json
{
  "schema": "bodaqs.session_filter",
  "version": 1,
  "filter_id": "ben-rides-with-usable-gps",
  "revision": 2,
  "display_name": "Ben rides with usable GPS",
  "description": "Reusable helper for GPS comparison sessions.",
  "scope": {
    "library_ids": ["default-library"]
  },
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
  "provenance": {
    "created_at": "2026-06-02T00:00:00Z",
    "created_by": "user",
    "updated_at": "2026-06-02T00:12:00Z"
  },
  "display_state": {
    "bodaqs_web_v1": {}
  }
}
```

Validation notes:

- `schema` must be `bodaqs.session_filter`.
- `version` must be supported by the service.
- `filter_id` must be filename-safe and unique within the libraries root.
- `revision` is assigned by the service and must increment on successful write.
- `display_name` should be short enough for chips and filter-list rows.
- `predicate` is required.
- `scope` is optional. Missing scope means the filter can be evaluated against
  all libraries under the active libraries root.
- `display_state` is optional and non-authoritative.

---

## 4. Predicate Model

Predicates are recursive. Group predicates combine child predicates. Leaf
predicates compare one field against one value or set of values.

Group predicate:

```json
{
  "op": "and",
  "children": []
}
```

Recommended group operators:

```text
and | or
```

Leaf predicate:

```json
{
  "field": "gps.quality",
  "op": "eq",
  "value": "usable"
}
```

Recommended leaf operators:

```text
eq | in | contains | present
```

Operator semantics:

- `eq`: field value equals `value` after normalisation appropriate to the field.
- `in`: field value equals any item in `value`.
- `contains`: text or list field contains `value`.
- `present`: field has a non-empty value, or equals the boolean `value` if one
  is supplied.

The service and browser should treat unknown fields/operators as invalid for
saved objects. Future versions may add numeric comparison, date/time comparison,
geospatial-section predicates, and signal-content predicates.

---

## 5. Initial Field Names

Initial catalog-backed fields:

```text
bike
event.schema
firmware
gps.present
gps.quality
gps.source
note.status
preprocessing.profile
qc.level
rider
signals
source.archive
```

Field notes:

- `note.status` uses `missing | draft | edited`.
- `qc.level` uses `ok | warning | alert`.
- `gps.quality` uses `absent | limited | usable | invalid`.
- `gps.source` may match the preferred GPS source, any source kind, or source
  stream names exposed by the catalog.
- `signals` evaluates over available signal names and semantic labels.

Signal-content filters are not part of the initial catalog-only implementation.
They should become API-backed predicates once signal summaries are available.

---

## 6. Applying Filters

The default filter stack behavior is:

```text
selected libraries
-> persisted saved-filter stack
-> ad-hoc table filters
-> search text
-> sort
```

Multiple applied persisted filters are combined with `AND` by default. Each
persisted filter may contain its own internal `and`/`or` predicate tree.

Example active stack:

```json
{
  "applied_filters": [
    { "filter_id": "ben-rides" },
    { "filter_id": "has-accelerometer" },
    { "filter_id": "has-usable-gps" }
  ],
  "combine": "and"
}
```

The active stack is UI/session state. It is not a Study Set definition. If the
user creates a Study Set after applying filters, the Study Set stores explicit
session membership. The filter stack may be recorded in Study Set provenance,
but refreshing membership from filters must be an explicit user action.

---

## 7. API Endpoints

Root-scoped session-filter CRUD:

```text
GET    /api/v1/session-filters
POST   /api/v1/session-filters
GET    /api/v1/session-filters/{filter_id}
PUT    /api/v1/session-filters/{filter_id}
DELETE /api/v1/session-filters/{filter_id}
```

Filter writes should use revision checks:

```json
{
  "expected_revision": 2,
  "session_filter": {
    "schema": "bodaqs.session_filter",
    "version": 1,
    "filter_id": "ben-rides",
    "revision": 2,
    "display_name": "Ben's rides",
    "predicate": {
      "field": "rider",
      "op": "contains",
      "value": "ben"
    }
  }
}
```

The browser may evaluate catalog-backed filters locally after loading filter
objects. API-backed evaluation can be added later for predicates requiring data
that is not present in the session catalog.

---

## 8. Deferred Work

Deferred beyond the first persisted-filter contract:

- full visual predicate builder
- ad-hoc table-header filtering
- saving an ad-hoc table filter as a persisted filter
- API-backed signal-content predicates
- API-backed geospatial-section predicates
- importing/exporting filters across libraries roots
- hosted/shared filter permissions
