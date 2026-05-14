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

    "sample_rate_hz": float | None,              # session-wide estimate if meaningful
    "sample_rate_by_channel_hz": dict[str, float] | None,

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

---

## qc (Quality Control and Transforms)

The QC section records **everything that may affect interpretation** of the data.

```python
qc = {
    "time_monotonic": bool,
    "time_repaired": bool,
    "n_time_gaps": int,
    "gap_total_s": float,
    "warnings": list[str],

    "transforms": dict,
    "firmware_stats": dict | None,
    "parse": dict | None,
}
```

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
    "method": str | None,
    "params": dict | None,
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

The canonical analysis table.

Requirements:
- Contains a time axis (`time_s` as index preferred)
- Time is monotonic (after repair if needed)
- Contains canonical base channel columns listed in `meta["channels"]`
- Derived columns added only when computed:
  - Velocity: `{channel}_vel`
  - Acceleration: `{channel}_acc`

Units for derived columns are implied from base channel units.

---

## Invariants (Contract Guarantees)

- `df` always has a valid time axis
- Any preprocessing applied is recorded in `qc["transforms"]`
- Zeroing is never implicit or silent
- Firmware QC stats are preserved when present
- Channel units and roles are explicit via `meta["channel_info"]`

---

## Notes

This v0 schema is intentionally lightweight and dictionary-based.
It provides a stable contract without committing to a heavy class hierarchy.
As concepts stabilize, this structure can later be wrapped in dataclasses
or validated with stricter schema tooling.
