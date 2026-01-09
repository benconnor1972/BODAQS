# BODAQS Event Table Contract (v0)

**Status:** Stable (v0)  
**Applies to:** `events_df` produced by `detect_events_from_schema()`  
**Related docs:**  
- `BODAQS_Public_API_Contract_v0.md`  
- `BODAQS_Session_Schema_v0.md`  
- Event Schema Specification (v1.x)

---

## 1. Purpose

This document defines the **canonical structure and invariants** of the BODAQS **event table** (`events_df`).  
Each row represents **one detected event instance**.

The contract is designed to:
- Align closely with the **event schema terminology**
- Support robust downstream analysis, metrics, and UI
- Be future‑proof for multi‑sensor and multi‑schema evolution

Anything not defined here is considered **non‑contractual** and may change.

---

## 2. Row Identity

### Required columns

| Column | Type | Meaning |
|------|------|--------|
| `event_id` | str | Unique identifier for this event instance within the session |
| `schema_id` | str | Event definition ID from the schema |
| `schema_version` | str | Schema version string (e.g. `"1.0"`) |
| `event_name` | str | Human‑readable label for the event |

### Notes

- `event_id` **must be unique** across the entire table.
- Recommended format:  
  `"{schema_id}:{occurrence_index}"`
- `event_name` corresponds to the schema’s `label` field (or defaults to `schema_id`).
- `schema_version` allows schema IDs to evolve without ambiguity.

---

## 3. Time & Index Anchoring

### Required columns

| Column | Type | Meaning |
|------|------|--------|
| `start_idx` | int | Inclusive start sample index |
| `end_idx` | int | Inclusive end sample index |
| `start_time_s` | float | `time_s` at `start_idx` |
| `end_time_s` | float | `time_s` at `end_idx` |
| `trigger_idx` | int | Sample index of the primary trigger |
| `trigger_time_s` | float | `time_s` at `trigger_idx` |

### Derived (may be computed)

| Column | Type | Meaning |
|------|------|--------|
| `duration_s` | float | `end_time_s - start_time_s` |

### Invariants

- `0 <= start_idx <= trigger_idx <= end_idx < len(session["df"])`
- `start_time_s <= trigger_time_s <= end_time_s`
- `duration_s >= 0`

### Real‑time anchoring (future‑proof)

If the session provides a real datetime reference (e.g. `session["meta"]["t0_datetime"]`):

| Optional column | Type | Meaning |
|----------------|------|--------|
| `trigger_datetime` | datetime | Absolute datetime of trigger |

This is **optional in v0**, but reserved by the contract.

---

## 4. Signal Context (Schema‑Aligned)

### Required columns

| Column | Type | Meaning |
|------|------|--------|
| `signal` | str | Primary signal used for detection (schema terminology) |

### Optional / Future‑proof

| Column | Type | Meaning |
|------|------|--------|
| `signals` | list[str] | All signals involved in the event |
| `units` | str | Units of the primary signal |

### Notes

- `signal` maps directly to schema `signal` fields (`disp`, `vel`, `acc`).
- Signal name resolution (suffixing) is handled upstream.

---

## 5. Segmentation & Classification

### Optional columns

| Column | Type | Meaning |
|------|------|--------|
| `segment_id` | int / str | Segment identifier active at trigger time |
| `tags` | list[str] | Semantic tags from schema (e.g. `["rebound", "kinematics"]`) |

### Notes

- `segment_id` should be resolved during event detection if segmentation exists.
- Absence of segmentation implies `segment_id` is omitted.

---

## 6. Provenance & Quality Control

### Required columns

| Column | Type | Meaning |
|------|------|--------|
| `detector_version` | str | Version of detection logic |
| `params_hash` | str | Hash of the event’s effective schema block |

### Optional

| Column | Type | Meaning |
|------|------|--------|
| `qc_flags` | list[str] | Quality warnings (e.g. `edge_clipped`) |
| `score` | float | Detection confidence / prominence |

### Meta payload

| Column | Type | Meaning |
|------|------|--------|
| `meta` | dict | Non‑flat debug and provenance data |

The `meta` field may include:
- trigger strengths
- debounce decisions
- secondary trigger timings
- window parameters

---

## 7. Minimal Enforced v0 Set

The following **must** exist for all rows:

- `event_id`
- `schema_id`
- `schema_version`
- `event_name`
- `signal`
- `start_idx`
- `end_idx`
- `trigger_idx`
- `start_time_s`
- `end_time_s`
- `trigger_time_s`

All other fields are optional but strongly recommended.

---

## 8. Validation Rules

A conforming `events_df` must satisfy:

- `event_id` is unique
- All index fields are integers and within bounds
- All time fields are finite floats
- `signal` refers to a known signal or derived signal
- Schema metadata matches the schema used for detection

Violations indicate a **detector bug or schema mismatch**, not user error.

---

## 9. Design Rationale

- Terminology mirrors the **event schema specification**  
- Trigger‑centric naming (`trigger_*`) avoids ambiguity  
- Index + time dual anchoring supports both slicing and plotting  
- Real‑time anchoring is supported without forcing it in v0  
- Flat columns stay minimal; deep detail lives in `meta`  

---

**End of Event Table Contract (v0)**  
