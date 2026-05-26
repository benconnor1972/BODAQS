# BODAQS Bookmarks Specification (Per‑User Store) — v1

**Status:** Proposed  
**Scope:** Analysis UI / widgets (e.g., Session Window Browser)  
**Persistence model:** **Per-user local store** (JSON on disk), independent of session artifacts.

---

## Goals

Bookmarks capture “interesting windows” within a session (time range) plus optional UI view state, so a user can:

- Quickly return to the same window `(t0, t1)` in a session.
- Restore common view configuration (selected signals, event overlays, show-marks toggle, y-axis lock).
- Keep personal exploration notes **without polluting** canonical session metadata.

---

## Non‑Goals

- Team-shared / canonical annotations (future: export/promote selected bookmarks).
- Server-side / multi-user sync.
- Hard guarantees across reprocessed sessions (we support *drift detection* and warnings).

---

## Storage

### Default location

Choose one of these (support both, with explicit precedence):

1. **User home (recommended)**  
   - POSIX: `~/.bodaqs/bookmarks_v1.json`  
   - Windows: `%USERPROFILE%\.bodaqs\bookmarks_v1.json`

2. **Repo-local (project scoped, optional)**  
   - `<repo>/.bodaqs/bookmarks_v1.json`

### File format

- UTF-8 JSON
- Top-level object with `schema` and `version` for compatibility
- Atomic write recommended (write temp + replace)

---

## Data model

### BookmarkStore (file) — v1

```json
{
  "schema": "bodaqs.bookmarks.store",
  "version": 1,
  "created_at_utc": "2026-02-05T10:12:33Z",
  "updated_at_utc": "2026-02-05T10:22:10Z",
  "bookmarks": [ /* BookmarkEntry[] */ ]
}
```

#### Required fields

- `schema` (string): must equal `"bodaqs.bookmarks.store"`
- `version` (int): must equal `1`
- `bookmarks` (array): list of `BookmarkEntry` objects

#### Recommended fields

- `created_at_utc`, `updated_at_utc` (RFC3339/ISO-8601 UTC timestamp strings)

---

### BookmarkEntry — v1

A bookmark represents a **window within a session**, plus optional view state.

```json
{
  "bookmark_id": "bkmk_01J0K5W5M2B8Q9S1F1VJY7H6T3",
  "created_at_utc": "2026-02-05T10:12:33Z",
  "updated_at_utc": "2026-02-05T10:12:33Z",

  "title": "Big huck landing",
  "note": "Nice compression spike; compare front vs rear",

  "scope": {
    "session_key": "2026-01-30__ride_07",
    "session_id": "S_20260130_ride07",
    "source": {
      "kind": "file",
      "ref": "raw/2026-01-30/ride07.csv"
    },
    "fingerprint": {
      "n_rows": 123456,
      "time_col": "time_s",
      "time_min": 0.0,
      "time_max": 812.345,
      "df_raw_sha1": "optional",
      "df_sha1": "optional"
    }
  },

  "window": {
    "t0": 260.700,
    "t1": 265.900,
    "units": "s"
  },

  "view": {
    "detail_signals": [
      "front_shock_dom_suspension [mm]",
      "rear_shock_dom_suspension [mm]"
    ],
    "event_types": ["rebound_end", "compression_start"],
    "show_marks": true,

    "y_lock": {
      "enabled": true,
      "range": [0.0, 120.0]
    }
  },

  "tags": ["landing", "setup"],
  "private": true
}
```

#### Required fields

- `bookmark_id` (string): unique within the store  
  - **Recommendation:** ULID (time-sortable) or UUID.
- `created_at_utc` (string): UTC timestamp
- `scope.session_key` (string): loader key used to resolve a session
- `window.t0`, `window.t1` (number): finite seconds in the same units as `time_col`
- `window.units` (string): must be `"s"` in v1 (sanity)

#### Optional fields

- `updated_at_utc` (string): UTC timestamp
- `title` (string)
- `note` (string)
- `scope.session_id` (string)
- `scope.source` (object): where the session originated (`kind`, `ref`)
- `scope.fingerprint` (object): drift detection fields
- `view` (object): UI restoration state
- `tags` (string[])
- `private` (bool): defaults `true` if omitted

---

## Semantics

### Scope

`scope` is used to locate and validate applicability of a bookmark.

- `session_key` is the primary identity for loading via existing selector/loader flows.
- `session_id` is optional and may be used for display or cross-checks.
- `source` provides human context (e.g., the raw CSV path).
- `fingerprint` supports *drift detection*:
  - `n_rows`, `time_min/max` allow warning if the session has changed materially.
  - `df_raw_sha1` / `df_sha1` can be added later for stronger validation.

### Window

`window` defines the time interval:

- Invariant: `t0 <= t1`
- Interpreted against `scope.fingerprint.time_col` if provided, else assumed `"time_s"`.

### View state

`view` is optional and widget-specific, but recommended fields for the Session Window Browser:

- `detail_signals` (string[]): selected detail signals
- `event_types` (string[]): selected event types
- `show_marks` (bool): restore the marks overlay toggle
- `y_lock`:
  - `enabled` (bool)
  - `range` ([lo, hi]) numeric

Widgets should tolerate missing/unknown view fields.

---

## Validation rules (v1)

On load:

1. File-level validation
   - `schema` must match
   - `version` must be `1`
   - `bookmarks` must be an array

2. Entry-level validation (per bookmark)
   - `bookmark_id` present and unique
   - `scope.session_key` non-empty
   - `window.t0`, `window.t1` finite and `t0 <= t1`
   - `window.units == "s"` (warn if not)

Drift checks (warnings, not hard failures):

- If `fingerprint.time_min/max` present and `(t0, t1)` falls outside, warn.
- If hashes present and mismatch, warn.

---

## API specification (Python)

### Overview

Provide a small, dependency-light module (e.g., `bodaqs_analysis/bookmarks.py`) with:

- A `BookmarkStore` class for load/save and CRUD.
- Pure functions for validation and drift checks.
- Minimal coupling to widgets (widgets call into the store, store remains UI-agnostic).

### Types

- `BookmarkEntry` (TypedDict or dataclass)
- `BookmarkStoreData` (TypedDict)
- `BookmarkQuery` (optional convenience)

### Public API

#### Construction / loading

- `BookmarkStore(path: Optional[Path] = None, *, repo_root: Optional[Path] = None)`
  - Resolves default path if `path` not provided.
  - Supports home-based and repo-local stores (configurable precedence).

- `store.load() -> None`
  - Loads file if present, else initializes an empty store.
  - Performs validation and de-duplicates if necessary (warn).

- `store.save() -> None`
  - Writes atomically (temp file + replace).
  - Updates `updated_at_utc`.

#### CRUD

- `store.list(*, session_key: Optional[str] = None, tag: Optional[str] = None) -> list[BookmarkEntry]`
  - Returns bookmarks, optionally filtered.

- `store.get(bookmark_id: str) -> BookmarkEntry | None`

- `store.add(entry: BookmarkEntry) -> str`
  - Validates.
  - Assigns `bookmark_id` if missing (ULID/UUID).
  - Sets `created_at_utc` / `updated_at_utc`.
  - Returns `bookmark_id`.

- `store.update(bookmark_id: str, *, patch: dict) -> BookmarkEntry`
  - Applies shallow patch (or structured patch for nested fields).
  - Updates `updated_at_utc`.
  - Validates.

- `store.delete(bookmark_id: str) -> bool`
  - Returns True if deleted.

#### Convenience helpers

- `store.add_from_view(*, session: dict, t0: float, t1: float, view: dict, title: str = "", note: str = "", tags: list[str] | None = None, private: bool = True) -> str`
  - Builds `scope` + `fingerprint` from `session`.
  - Recommended for widgets.

- `check_drift(entry: BookmarkEntry, *, session: dict) -> list[str]`
  - Returns warning strings (empty if OK).

- `coerce_restore_view(entry: BookmarkEntry, *, available_signals: list[str], available_event_types: list[str]) -> dict`
  - Returns a safe view state by intersecting stored selections with current options.

### Behavioural notes

- API should be tolerant:
  - Unknown fields are preserved on read-write (round-trip).
  - Missing optional fields should not break widget restore.
- Store should be safe:
  - No partial writes (atomic save).
  - Corrupt file handling: keep a `.bak` copy when possible.

---

## UI integration (Session Window Browser)

### Save bookmark

On “Save”:

1. Read current session key and session object.
2. Read current window `(t0, t1)` from Plotly x-axis range.
3. Collect view state:
   - `detail_signals` selection
   - `event_types` selection
   - `show_marks` toggle
   - `y_lock` state (if you persist it)
4. Call `store.add_from_view(...)`
5. Refresh bookmark list in the widget.

### Load bookmark

On “Load”:

1. Lookup bookmark entry.
2. Ensure the session is loaded (`session_key`).
3. Run `check_drift(...)` and optionally display warnings.
4. Restore view state (intersect with current options).
5. Set `fig.layout.xaxis.range = [t0, t1]`.

### Delete bookmark

On “Delete”:

1. Call `store.delete(bookmark_id)`
2. Refresh list.

