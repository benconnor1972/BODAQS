# BODAQS Event Table Contract  
**Version:** v0.1.2 (draft)  
**Status:** Backward-compatible additive update to v0.1.1  

---

## 1. Purpose

The **Events Table** is the canonical, row-oriented representation of detected events produced by the analysis pipeline.  
Each row represents **one detected event instance** derived from a schema definition applied to one or more signals.

This contract defines:
- required and optional columns
- naming and typing rules
- invariants relied upon by segment extraction and metrics

---

## 2. Core invariants

- One row = one detected event instance  
- `event_id` **must be globally unique** within the table  
- Index columns (`*_idx`) refer to **row indices in `session["df"]`**  
- Time columns (`*_time_s`) are in **seconds**, monotonic, float  
- Start/end indices are **inclusive**  
- Canonical trigger columns always exist even if additional triggers are present  

---

## 3. Required columns (minimal enforced v0 set)

| Column | Type | Description |
|------|------|-------------|
| `event_id` | `str` | Unique identifier for this event instance |
| `schema_id` | `str` | Event schema identifier |
| `schema_version` | `str` | Schema version string |
| `event_name` | `str` | Human-readable event name |
| `signal` | `str` | Logical signal role (e.g. `"vel"`, `"disp"`) |
| `signal_col` | `str` | Resolved DataFrame column actually used |
| `start_idx` | `int` | Inclusive start index in `session["df"]` |
| `end_idx` | `int` | Inclusive end index in `session["df"]` |
| `trigger_idx` | `int` | Index of the **primary trigger** |
| `start_time_s` | `float` | Start time in seconds |
| `end_time_s` | `float` | End time in seconds |
| `trigger_time_s` | `float` | Time of primary trigger (seconds) |

---

## 4. Event identity

### 4.1 `event_id` format

Recommended format:

```
{schema_id}:{sensor}:{occurrence_index}
```

Example:

```
rebounds:rear_shock:3
```

Notes:
- `occurrence_index` is zero-based per `(schema_id, sensor)`
- The **only hard requirement** is global uniqueness
- Consumers **must not parse** `event_id` positionally

---

## 5. Canonical trigger columns

Every event row **must** contain the canonical primary trigger anchors:

- `trigger_idx`
- `trigger_time_s`

These always refer to the **schema’s primary trigger**.

---

## 6. Secondary trigger columns (v0.1.2)

Schemas may define **multiple triggers** (primary + secondary).  
Secondary triggers are promoted to **first-class columns** in the events table.

### 6.1 Column naming

For each trigger with id `{tid}`, the following columns MAY be present:

| Column | Type | Meaning |
|------|------|--------|
| `{tid}_idx` | `int` | Index of trigger occurrence |
| `{tid}_time_s` | `float` | Trigger time in seconds |

Example:

```
rebound_start_idx
rebound_start_time_s
rebound_end_idx
rebound_end_time_s
```

### 6.2 Conventions

- Trigger ids **must be column-safe** (`[a-zA-Z0-9_]+`)
- Missing / non-resolved triggers are represented as `NaN`
- Primary trigger **may** also appear in this expanded form

### 6.3 Rationale

Promoting secondary triggers to columns:
- simplifies metrics resolution
- avoids opaque nested metadata
- preserves full temporal information per event

---

## 7. Optional but recommended columns

| Column | Type | Description |
|------|------|-------------|
| `signals` | `list[str]` | All signal roles involved in this event |
| `segment_id` | `str` | Segment identifier if segmentation is applied |
| `tags` | `list[str]` | Schema-defined tags |
| `score` | `float` | Detector confidence score |
| `qc_flags` | `list[str]` | Quality control flags |
| `meta` | `dict` | Detector-specific payload |

---

## 8. Datetime anchoring (optional)

If the session metadata provides a real-time anchor, events may include:

| Column | Type | Description |
|------|------|-------------|
| `trigger_datetime` | `datetime64[ns]` | Wall-clock time of primary trigger |

Rules:
- Derived as: `trigger_datetime = t0_datetime + trigger_time_s`
- If unavailable, column may be omitted or set to `NaT`
- No timezone conversion is implied

---

## 9. Provenance fields

| Column | Type | Description |
|------|------|-------------|
| `detector_version` | `str` | Version of detection implementation |
| `params_hash` | `str` | Hash of effective detector parameters |

---

## 10. Backward compatibility

- v0.1.2 is **additive** relative to v0.1.1
- Existing consumers that ignore unknown columns will continue to work
- Canonical columns (`trigger_*`, `start_*`, `end_*`) are unchanged
- Secondary trigger columns are optional but preferred when available
