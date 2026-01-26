# BODAQS Analysis Artifacts
Canonical Artifact Layout & Manifest Specifications  
**Version:** 0.2  
**Status:** Active  
**Scope:** JupyterLab / Python analysis pipeline

---

## 1. Purpose

This document defines the **canonical on-disk artifact layout** used by the BODAQS analysis pipeline, and the **manifest formats** that describe those artifacts.

The goals are:

- Explicit, reproducible sharing of data between notebooks
- Clear separation between *code* and *data*
- Deterministic paths for widgets and downstream analysis
- Support for batch runs containing multiple sessions
- Contract-oriented validation and provenance tracking

Artifacts are the **primary interface** between pipeline stages and notebooks.

---

## 2. Design principles

1. **Artifacts are explicit**
   - No hidden kernel state
   - Everything a notebook consumes can be reloaded from disk

2. **One run = one batch**
   - A *run* represents a single execution of the pipeline
   - A run may contain one or more sessions

3. **Sessions are the unit of analysis**
   - Each session has its own preprocessed dataframe, events, metrics, etc.

4. **Columnar, structured formats**
   - DataFrames are stored as Parquet
   - Metadata is stored as JSON or YAML

5. **Manifests over magic**
   - Structure and provenance live in manifest files
   - Filenames remain stable and predictable

---

## 3. Artifact root

All artifacts live under a single root directory:

```

artifacts/

```

This path is configurable in code, but all relative paths in this document assume it as the root.

---

## 4. Canonical directory layout (v0.2)

```

artifacts/
runs/
<run_id>/
manifest.json
env.json                     # optional
logs/
pipeline.log               # optional

```
  sessions/
    <session_id>/
      manifest.json

      source/
        input.csv              # optional copy or symlink
        input.sha256           # optional

      session/
        df.parquet             # canonical session dataframe
        meta.json              # session metadata
        qc.parquet             # optional QC tables

      registry/
        signals.json            # snapshot of signal registry
        naming_spec.json        # snapshot of SignalSpec

      events/
        <event_type>/
          events.parquet        # Events Table Contract output
          schema.yaml           # frozen schema used
          manifest.json         # optional summary/validation

      segments/
        <event_type>/
          segments.parquet      # segment table form
          arrays.npz            # optional dense array cache

      metrics/
        <event_type>/
          metrics.parquet       # Metrics Table Contract output
          manifest.json         # optional summary/validation

      figures/
        ...                     # optional saved plots
```

```

---

## 5. Identifiers

### 5.1 `run_id`
- Identifies a **batch execution** of the analysis pipeline
- Typically timestamp-based, optionally including git SHA

Example:
```

run_2026-01-26T16-40-12_AWST__a1b2c3d

```

### 5.2 `session_id`
- Identifies a single recording / logger session
- Should be deterministic with respect to the source data
- Used consistently across firmware, analysis, and artifacts

---

## 6. Data formats

### 6.1 DataFrames
- **Format:** Parquet
- **Compression:** `zstd` (default)
- **Index:** not stored (all identity columns are explicit)

Used for:
- session dataframes
- events tables
- segments tables
- metrics tables
- QC tables (if tabular)

### 6.2 Metadata
- **Format:** JSON
- UTF-8 encoded
- Sorted keys, pretty-printed

Used for:
- manifests
- session metadata
- registry snapshots

### 6.3 Schemas
- **Format:** YAML
- Frozen copy of the exact schema used for generation

---

## 7. Manifest specifications

### 7.1 Run manifest

**Path**
```

artifacts/runs/<run_id>/manifest.json

````

**Purpose**
- Describe the batch run as a whole
- Provide entry point for discovery and widgets

**Minimum fields**
```json
{
  "artifact_layout_version": "0.2",
  "run_id": "<run_id>",
  "created_at": "2026-01-26T16:40:12+08:00",
  "timezone": "AWST",
  "sessions": ["<session_id_1>", "<session_id_2>"]
}
````

**Optional fields**

* `git_sha`
* `pipeline_config`
* global analysis parameters

---

### 7.2 Session manifest

**Path**

```
artifacts/runs/<run_id>/sessions/<session_id>/manifest.json
```

**Purpose**

* Describe a single session’s artifacts and provenance

**Minimum fields**

```json
{
  "session_id": "<session_id>"
}
```

**Common optional fields**

```json
{
  "contracts": {
    "session": "v0.x",
    "events": "v0.x",
    "metrics": "v0.x"
  },
  "source": {
    "path": "source/input.csv",
    "sha256": "..."
  },
  "summary": {
    "n_rows": 123456,
    "t_start_s": 0.0,
    "t_end_s": 600.0
  }
}
```

---

### 7.3 Event / metric manifests (optional)

**Paths**

```
events/<event_type>/manifest.json
metrics/<event_type>/manifest.json
```

**Purpose**

* Store lightweight summaries and validation results
* Not required for loading, but useful for QC

Typical contents:

* `event_type`
* `n_events` or `n_rows`
* validation status
* warnings / errors

---

## 8. Canonical paths (guarantees)

Code and widgets may assume the following paths exist if the artifact is present:

* Session dataframe

  ```
  runs/<run_id>/sessions/<session_id>/session/df.parquet
  ```

* Session metadata

  ```
  runs/<run_id>/sessions/<session_id>/session/meta.json
  ```

* Events table

  ```
  runs/<run_id>/sessions/<session_id>/events/<event_type>/events.parquet
  ```

* Metrics table

  ```
  runs/<run_id>/sessions/<session_id>/metrics/<event_type>/metrics.parquet
  ```

Schemas and manifests are always colocated with the tables they describe.

---

## 9. Notebook interaction model

* Notebooks **do not share kernel state**
* All cross-notebook communication happens via artifacts
* Producer notebooks write artifacts
* Consumer notebooks discover and load artifacts

Artifacts are the stable API.

---

## 10. Future extensions (non-breaking)

* Global catalog (DuckDB / SQLite) layered over Parquet artifacts
* Cross-run comparison helpers
* Artifact validation on read
* CI-driven artifact generation

---

## 11. Summary

This artifact layout provides:

* Deterministic structure
* Explicit contracts
* Batch + session flexibility
* Clean separation between computation and visualization

It is intended to evolve conservatively, with backward compatibility as a priority.

```

---


