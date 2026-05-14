
# BODAQS SegmentBundle Contract (v0.1)

**Status:** Draft (v0.1)  
**Applies to:** Output of `extract_segments()`  
**Related docs:**  
- BODAQS Session Schema Contract (v0.1)  
- BODAQS Event Table Contract (v0.1.1)  

---

## 1. Purpose

The **SegmentBundle** is a first‑class intermediate data structure produced by the
*segment extractor* and consumed by *metrics* and *visualisation* layers.

It represents **aligned, fixed‑length sample windows** (“segments”) extracted
around detected events, operating on the canonical session dataframe
(`session["df"]`) and its primary timebase (`time_s`).

The SegmentBundle cleanly separates:

- **Event detection** – what happened and when (event table)
- **Segment extraction** – what data window to analyse (this contract)
- **Metrics computation** – what to measure (downstream)

---

## 2. Position in the analysis pipeline

```
load_session
  → preprocess_session
    → detect_events_from_schema
      → extract_segments        ← SegmentBundle produced here
        → extract_metrics
```

Metrics **must not**:
- re‑slice `session["df"]`
- reinterpret event timing
- depend on detection schema logic

Metrics operate *only* on SegmentBundles.

---

## 3. High‑level structure

A SegmentBundle is a plain Python `dict` with the following keys:

```text
SegmentBundle
├─ spec       # resolved extraction specification
├─ events     # filtered event table (input)
├─ segments   # per‑segment metadata and QC
├─ data       # aligned sample arrays (wide / matrix form)
└─ qc         # summary quality information
```

---

## 4. `spec`: resolved extraction specification

Describes **how** the segments were extracted, after merging:

- schema‑level `segment_defaults` (if present)
- runtime overrides (SegmentRequest)

```python
spec = {
    "anchor": str,                 # e.g. "trigger_time_s"
    "window": WindowSpec,          # resolved pre/post window
    "grid": GridSpec,              # native or resampled
    "roles": list[str],            # semantic roles requested
    "role_to_col": dict[str, str], # resolved df columns
    "output": OutputSpec,          # padding, dtype, time arrays
}
```

### Contract guarantees

- `role_to_col` maps semantic roles to **existing columns in `session["df"]`**
- Roles refer to **signal semantics** (`disp`, `vel`, `acc`, etc.), not column names
- `spec` is fully self‑describing and sufficient to reproduce extraction

---

## 5. `events`: input event table (filtered)

A pandas DataFrame containing the subset of detected events used for extraction.

This table conforms to the **Event Table Contract (v0.1.1)**.

### Guarantees

- Row order is preserved
- Index is reset to `0..N−1`
- No columns are added or removed

Purpose:
- provenance
- traceability
- joining metrics back to events

---

## 6. `segments`: per‑segment metadata table

A pandas DataFrame with **one row per requested segment**, regardless of validity.

### Required columns

| Column | Type | Meaning |
|------|-----|--------|
| `event_row` | int | Row index into `events` |
| `valid` | bool | Whether the segment was successfully extracted |
| `reason` | str | Reason for invalid segments (empty if valid) |
| `trigger_time_s` | float | Trigger time used for alignment (bundle alignment time) |
| `trigger_idx` | int | Trigger index in `session["df"]` |
| `start_idx` | int | First index actually read |
| `end_idx_excl` | int | One‑past‑last index actually read |
| `req_start_idx` | int | Requested (pre‑clamp) start index |
| `req_end_idx_excl` | int | Requested (pre‑clamp) end index |
| `n_expected` | int | Expected samples per segment |

---

## 7. `data`: aligned sample arrays (wide / matrix form)

A dictionary mapping **roles** (and optional time arrays) to NumPy arrays.

### Shape contract

```python
data[role].shape == (n_valid_segments, n_samples)
```

---

## 8. `qc`: quality summary

A lightweight summary derived from `segments`.

---

## 9. Explicit non‑goals (v0)

The SegmentBundle intentionally does **not** support variable‑length segments within a bundle.

---

**End of SegmentBundle Contract (v0.1)**
