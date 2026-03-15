# BODAQS Analysis – v0 Session Schema Contract

This document defines the **v0 Session data model and contract** for the BODAQS JupyterLab analysis pipeline.
It captures the agreed structure, invariants, and intent for how session data flows through macro and micro analysis.

---

## Overview

A **Session** represents one logging run (ride, test, or recording).  
It may contain data from multiple sensors, with different units and potentially different effective sample rates.

Design goals:
- Support **macro** (aggregate) and **micro** (inspection/browsing) analysis with the same backend
- Preserve provenance and quality-control information
- Avoid column proliferation (e.g. zeroing is in-place)
- Remain flexible as firmware and analysis evolve

---

## Session Object (Top-Level)

A Session is a plain Python `dict` with the following keys:

```python
session = {
    "session_id": str,
    "source": dict,
    "meta": dict,
    "qc": dict,
    "df_raw": pandas.DataFrame,
    "df": pandas.DataFrame,
}
```

---

## session_id

Stable identifier for the run.

- Default: filename stem (no extension)
- Optional: include a short hash for guaranteed uniqueness

---

## source (Provenance)

```python
source = {
    "path": str,                 # full or relative input path
    "filename": str,             # basename only
    "created_local": datetime | None,
    "timezone": str | None,      # e.g. "Australia/Perth" or "AWST"
}
```

---

## meta (Channels, Units, Sampling)

Sessions may contain multiple sensors with different units and characteristics.

```python
meta = {
    "channels": list[str],       # canonical base channel names present in df
    "channel_info": dict[str, dict],

    # Optional convenience summary (may be derived from streams["primary"])
    "sample_rate_hz": float | None,              # session-wide estimate if meaningful
    "sample_rate_by_channel_hz": dict[str, float] | None,

    # NEW (v0+): per-stream timebase metadata (required when df present)
    # At minimum, streams["primary"] describes the timebase of session["df"].
    "streams": dict[str, dict],

    "device": dict | None,       # firmware / hardware metadata if available
    "notes": str | None,
}
```

### channel_info (Per-Channel Metadata)

Keyed by canonical base channel name:

```python
meta["channel_info"][channel] = {
    "unit": str | None,              # e.g. "mm", "g", "deg/s", "V"
    "sensor": str | None,            # logical grouping (e.g. "rear_shock", "imu")
    "role": str | None,              # e.g. "position", "accel", "gyro"
    "nominal_rate_hz": float | None, # if known from firmware/config
    "source_columns": list[str],     # raw CSV columns used (optional)
}
```


### meta.streams (Per-Stream Timebase Metadata)

This structure supports **multiple sensors with different (uniform) sample rates**.

A **stream** is a time series with its own time column (usually `time_s`) and its own dt.
In v0, `session["df"]` is the canonical **analysis dataframe**, and its timebase is recorded as
`meta["streams"]["primary"]`.

```python
meta["streams"][stream_name] = {
    "kind": "uniform",          # v0: uniform sampling
    "time_col": str,            # e.g. "time_s"
    "sample_rate_hz": float,    # estimated or declared
    "dt_s": float,              # 1 / sample_rate_hz
    "jitter_frac": float,       # std(dt) / median(dt) from time deltas
}
```

**Contract notes:**
- `meta["streams"]` must be present (non-empty) when `session["df"]` is present.
- `meta["streams"]["primary"]` must exist and describe the timebase of `session["df"]`.
- There is **no requirement** that all streams share the same dt.
- When secondary sensor metrics are computed in the future, those sensors may be **resampled onto the trigger grid**
  (Option A), and the resampling method/provenance should be recorded in `qc`.

---

## qc (Quality Control and Transforms)

The QC section records **everything that may affect interpretation** of the data.

```python
qc = {
    "time_monotonic": bool,
    "time_repaired": bool,
    "n_time_gaps": int,
    "gap_total_s": float,
    "warnings": list[str],  # human-readable warnings, may include timebase jitter/resampling notes

    "transforms": dict,
    "firmware_stats": dict | None,
    "parse": dict | None,
}
```
**Notes:**
- `qc["warnings"]` is the canonical location for simple, human-readable warnings.
  Examples: `"high_jitter:primary"`, `"time_nonmonotonic_repaired"`, `"resampled:imu->primary"`.
- If you later want structured warnings (per-stream, with numeric fields), you may add an optional `qc["time"]`
  sub-dict without breaking v0 readers.


### transforms

All preprocessing operations are recorded here.

#### Zeroing (in-place)

Zeroing modifies the base channel **in-place**.  
No `*_zeroed` columns are created.

```python
"zeroed": {
    "applied": bool,
    "method": str | None,                 # e.g. "lowest_1s_mean"
    "by_channel": dict[str, dict] | None, # offsets per channel
}
```

#### Scaling

```python
"scaled": {
    "applied": bool,
    "by_channel": dict[str, dict] | None, # scale factors / ranges
}
```

#### Filtering

```python
"filtered": {
    "applied": bool,
    "method": str | None,              # e.g. "butterworth_zero_phase_sosfiltfilt"
    "params": dict | None,             # includes smoothing configs + generated/skip counts
                                      # and optional residual generation metadata
}
```

#### Resampling

```python
"resampled": {
    "applied": bool,
    "target_rate_hz": float | None,
    "method": str | None,
}
```

---

### firmware_stats (Logger-Provided QC)

Captured from end-of-file footer stats when available.

```python
"firmware_stats": {
    "samples_dropped": int | None,
    "flush_count": int | None,
    "max_flush_ms": float | None,
    "avg_flush_ms": float | None,
    "late_ticks": int | None,
    "max_lag_ms": float | None,
}
```

This is intentionally a flexible “bag of numbers” to allow future expansion.

---

### parse (Optional Parsing Info)

```python
"parse": {
    "clock_column_used": str | None,
    "rows_read": int | None,
    "rows_ignored": int | None,
}
```

---

## df_raw (Raw DataFrame)

- Near-direct output of CSV load
- Minimal parsing only
- Raw column names largely preserved
- May include parse artifacts depending on file format

---

## df (Canonical Processed DataFrame)

The canonical **analysis** table used by the pipeline for event detection and metrics.

Requirements:
- Contains a time axis:
  - `time_s` column is required (index named `time_s` is also allowed)
  - Time is finite and monotonic non-decreasing (after repair if needed)
- `meta["streams"]["primary"]` must exist and describe the timebase of `session["df"]`
- Contains canonical base channel columns listed in `meta["channels"]`
- Derived columns are added only when computed:
  - Butterworth smoothing variants (displacement only): `{channel}_op_Butterworth_<x>Hz_<y>Order`
  - Butterworth residual variants (optional): `{channel}_op_Butterworth_<x>Hz_<y>Order_resid`
  - Velocity: `{channel}_vel`
  - Acceleration: `{channel}_acc`

Residual semantics:
- Residual values are `source_disp - smoothed_disp`.
- Registry `op_chain` for residual columns includes `diff` and excludes the Butterworth token.

Units for derived columns are implied from base channel units.

**Timebase / Option A (trigger grid):**
- Event detection and event windows operate on the grid of the triggering signal within this dataframe.
- When computing metrics on non-triggering sensors in the future, those sensors may be resampled onto the trigger grid.

---
## Invariants (Contract Guarantees)

- `df` always has a valid time axis (`time_s` present; finite; monotonic non-decreasing)
- `meta["streams"]` is present when `df` is present, and `meta["streams"]["primary"]` describes the timebase of `df`
- Any preprocessing applied is recorded in `qc["transforms"]`
- Zeroing is never implicit or silent (zeroing decisions are recorded)
- Firmware QC stats are preserved when present
- Channel units and roles are explicit via `meta["channel_info"]`

---
## Notes

This v0 schema is intentionally lightweight and dictionary-based.
It provides a stable contract without committing to a heavy class hierarchy.
As concepts stabilize, this structure can later be wrapped in dataclasses
or validated with stricter schema tooling.
