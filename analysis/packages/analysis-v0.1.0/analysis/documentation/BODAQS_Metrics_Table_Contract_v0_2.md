# BODAQS Metrics Table Contract v0.2

## Purpose

The **Metrics Table** represents *derived numerical summaries* computed for each detected event.
It is designed to:

- Join **1:1** with the Event Table via a stable event identifier
- Be easy to aggregate, plot, and export
- Remain backward-compatible as new metrics are added

This contract defines the **required structure**, **join rules**, and **naming conventions** for `metrics_df`.

---

## Cardinality & Join Contract

### One row per event instance
- `len(metrics_df) == len(events_df)` (unless explicitly filtered)
- Each row corresponds to exactly one detected event

### Join key
- **Required**: `session_id` (string), `event_id` (string)
- `(session_id, event_id)` **must be unique** within `metrics_df`
- Every `(session_id, event_id)` in `metrics_df` **must exist exactly once** in `events_df`

This guarantees a strict **1:1 join**:

```python
metrics_df.merge(events_df, on=["session_id", "event_id"], how="inner")

```

---

## Required Columns

### Identity / Join Columns

The following columns **must** exist:

| Column | Type | Description |
|------|------|-------------|
| `session_id` | str | Stable identifier of the source session |
| `event_id` | str | Unique identifier for the event instance (unique within a session) |

---

## Recommended Identity Columns (Copied Through)

These columns are **strongly recommended** to be included to make `metrics_df` self-describing,
even without joining back to `events_df`:

| Column | Type | Description |
|------|------|-------------|
| `schema_id` | str | Event schema identifier |
| `schema_version` | str | Version of the event schema |
| `event_name` | str | Human-readable event description |
| `signal` | str | Primary signal used for detection |
| `segment_id` | int / str | Segment identifier (if segmentation is used) |
| `trigger_time_s` | float | Event trigger time in seconds (session-relative) |

These columns **must match exactly** the values in `events_df`.

---

## Metric Columns

### Naming convention
- **All metric columns must be prefixed with `m_`**
- Metric names should be **stable and descriptive**

Examples:
- `m_peak_vel_mm_s`
- `m_rebound_tau_s`
- `m_travel_mm`
- `m_area_pos`
- `m_trigger_strength`

### Units
For v0, **units should be encoded in the metric name** when ambiguous:

- `_s` → seconds
- `_mm` → millimetres
- `_mm_s` → mm/s
- `_mm_s2` → mm/s²

Example:
- `m_peak_vel_mm_s` (preferred over `m_peak_vel`)

---

## Debug / Diagnostic Columns (Optional)

For development and debugging, `metrics_df` may include *diagnostic* columns prefixed with:

- `d_`

These columns are optional, may change more frequently than `m_` metrics, and are not intended to be relied upon for stable downstream analyses. They are typically produced when running metric computations in a debug mode (e.g. `return_debug=True`), and may include intermediate values such as resolved trigger times, window indices, or quality flags.

Rules:
- Debug columns **must** be prefixed with `d_`
- Debug columns **must not** include Event Table window columns (e.g. `start_idx`, `end_idx`, `start_time_s`, `end_time_s`)
- Debug columns **should not** be treated as part of the stable contract; they may be added/removed/renamed without a contract version bump

---

## Missing / Undefined Metrics

- Metrics **may be NaN** when undefined for a given event
- Metrics **should not raise errors** when unavailable
- Missing metric columns are allowed if never computed

NaN is preferred over sentinel values.

---

## Excluded Columns

The following **must NOT** appear in `metrics_df`:

- `start_idx`
- `end_idx`
- `start_time_s`
- `end_time_s`

These belong exclusively to the **Event Table**.

---

## Validation Rules (v0)

A valid `metrics_df` must satisfy:

1. `event_id` column exists
2. `(session_id, event_id)` pairs are unique
3. All `(session_id, event_id)` pairs exist exactly once in `events_df`
4. All metric columns start with `m_`
5. Identity columns match `events_df` values exactly

---

## Evolution Rules

### Backward-compatible changes
- Adding a new metric column
- Adding new recommended identity columns

### Breaking changes
- Renaming a metric column
- Changing metric semantics or units
- Removing a metric column

Breaking changes require a **contract version bump**.

---

## Notes

- This contract intentionally specifies a **wide-format table**
- A long/tidy format may be introduced in a future version
- This contract pairs with:
  - `BODAQS_Event_Table_Contract_v0.md`
  - `BODAQS_Public_API_Contract_v0.md`

