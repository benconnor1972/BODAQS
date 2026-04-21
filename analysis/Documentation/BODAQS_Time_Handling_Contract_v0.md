# BODAQS Time Handling Contract v0 (Option A: Trigger Grid)

**Status:** Draft (v0)  
**Scope:** A uniform primary analysis grid with optional secondary streams. Secondary streams may be uniform or intermittent.

---

## Goals

1. Provide a **canonical time axis** for event detection and metric computation.
2. Support **multiple sensors with different sample rates**.
3. Enable computing metrics on **non-triggering sensors** by **resampling them onto the trigger grid**.
4. Make all time decisions **explicit, validated, and recorded** in session metadata/QC.

---

## Definitions

### Stream
A stream is a sensor-provided time series with:
- its own time column (typically `time_s`)
- one or more signal columns

Streams may be:
- `uniform`: dt is approximately constant and `sample_rate_hz` / `dt_s` can be recorded
- `intermittent`: timestamps are monotonic but sample intervals may be irregular or sparse

### Trigger grid (Option A)
For each event type, the **primary grid** is the timebase of the **triggering stream/signal**.
Indices such as `start_idx`, `trigger_idx`, `end_idx` refer to that grid.

---

## Canonical Columns

### `time_s`
- Units: **seconds from stream start**
- Type: numeric float
- Must be finite and **monotonic non-decreasing**

Each stream has its own `time_s` (or a configured time column).  
The event’s grid is defined by the trigger stream’s `time_s`.

---

## dt (sample period) Rules

### Per-stream dt
Uniform streams record:
- `sample_rate_hz`
- `dt_s = 1/sample_rate_hz`
- a **jitter fraction** computed from time deltas

A uniform stream is considered “uniform enough” if jitter is below a configurable tolerance (default 5%).

Intermittent streams record only their `time_col` and stream kind unless richer metadata is available.

### No global dt requirement
There is **no requirement** that all streams share the same dt.

---

## Event Table Interpretation

All `*_idx` and `*_time_s` in the Event Table refer to the **trigger grid** for that event:

- `start_idx`, `trigger_idx`, `end_idx`
- `start_time_s`, `trigger_time_s`, `end_time_s`

To compute metrics on non-triggering sensors:
- resample secondary sensor signals onto the trigger grid
- compute metrics over `[start_idx:end_idx]` in trigger-grid sample coordinates

---

## Resampling Rules (Secondary Sensors)

### Default resampling method
- **Linear interpolation** for continuous signals.
- Behavior outside the source range: return NaN (no extrapolation) by default.

### Provenance / QC
When resampling is used, record:
- source stream name
- target stream name (trigger stream)
- method
- columns resampled
- NaN fraction introduced within each event window (optional)

---

## Required Session Metadata

Session must include:

```python
session["meta"]["streams"] = {
  "<stream_name>": {
    "kind": "uniform",
    "time_col": "time_s",
    "sample_rate_hz": 100.0,
    "dt_s": 0.01,
    "jitter_frac": 0.002,
  },
  "<secondary_stream_name>": {
    "kind": "intermittent",
    "time_col": "time_s",
  },
  ...
}
```

This metadata describes each available stream and its timebase properties.

---

## Validation Rules (v0)

For each stream listed in `session["meta"]["streams"]`:

1. `time_col` exists
2. time is finite and monotonic non-decreasing
3. if `kind == "uniform"`, dt can be estimated (at least one positive delta)
4. if `kind == "uniform"`, jitter is recorded; if jitter exceeds tolerance, set a QC warning

---

## Notes / Evolution

- A future version may introduce a session-wide “master grid” (Option B).
- Intermittent/event-driven sensors may later gain richer stream-local or per-event timebase metadata.
