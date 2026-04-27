# BODAQS Public API Contract (v0)

**Status:** Stable (v0)  
**Audience:** Analysis notebooks, scripts, and future UI/CLI layers  
**Scope:** Public-facing analysis pipeline functions only

This document defines the **stable public API contract** for the BODAQS analysis pipeline.  
Anything not explicitly documented here is considered **internal** and may change without notice.

---

## 1. Purpose & Scope

The BODAQS public API provides a stable interface for:

- Loading logger CSV data into a canonical session structure
- Applying normalization, zeroing, and derived-signal transforms
- Detecting events from schema definitions
- Extracting metrics from detected events
- Running the full analysis pipeline via a single macro call

### Out of scope
- Internal helper functions
- Experimental utilities
- Visualization helpers
- Notebook-only convenience code

---

## 2. Core Concepts

### 2.1 Session

A **session** is a mutable dictionary that represents a single logging run and its analysis state.

At minimum, a valid session contains:

```python
session = {
    "df": pandas.DataFrame,   # canonical data table
    "meta": dict,             # optional metadata
    "qc": dict,               # optional quality-control / transform provenance
}
```

Detailed guarantees for the session structure are defined in  
**`BODAQS_Session_Schema_v0.md`**.

---

### 2.2 Canonical Time Axis

All public pipeline functions operate on a canonical time axis:

- **Column name:** `time_s`
- **Units:** seconds
- **Definition:** elapsed time from start of logging
- **Type:** float

**Guarantee:**  
Any public function that consumes a DataFrame assumes `time_s` exists.

Functions that load raw data (e.g. CSVs) must ensure `time_s` is created.

---

## 3. Return & Diagnostics Conventions

### 3.1 Default Return Rule

> **Public functions return a single primary object by default.**

No public function returns a tuple unless explicitly requested.

---

### 3.2 Optional Diagnostics (`return_meta`)

Functions that can produce diagnostics, provenance, or algorithm details support:

```python
return_meta: bool = False
```

- `return_meta=False` (default): return the primary object only
- `return_meta=True`: return `(primary_object, meta_dict)`

The `meta_dict` is **machine-readable** and intended for:
- QC recording
- Provenance
- Debugging
- Reproducibility

---

### 3.3 Tuple Returns Are Forbidden by Default

Public API functions **must not** return tuples unless:
- `return_meta=True` is explicitly requested, and
- The tuple structure is documented here

Any tuple returned without opt-in is a contract violation.

---

## 4. Public Functions (v0)

### 4.1 Preprocess Profile Helpers

**Purpose:**  
Load and validate persisted preprocessing configuration.

**Signatures:**
```python
config = default_preprocess_config(**overrides)
profile = make_preprocess_profile(profile_id: str, config=config, ...)
profile = load_preprocess_profile(path: str | Path)
config = load_preprocess_config(path: str | Path)
config = preprocess_config_from_profile(profile: Mapping[str, Any])
config = resolve_preprocess_config_paths(config, base_dir=path)
path = save_preprocess_profile(profile, path: str | Path)
records = discover_preprocess_profiles(directory: str | Path)
```

**Returns:**
- `default_preprocess_config(...)`: a validated default config payload
- `make_preprocess_profile(...)`: a validated full profile document
- `load_preprocess_profile(...)`: the full profile document
- `load_preprocess_config(...)`: the validated `profile["config"]` payload
- `resolve_preprocess_config_paths(...)`: a copy of the config with path-like fields resolved
- `save_preprocess_profile(...)`: the path written
- `discover_preprocess_profiles(...)`: lightweight profile records for menus/editors

**Guarantees:**
- No tuple returns
- Unexpected profile schema/version raises `ValueError`
- Missing required config fields raise `ValueError`
- New callers can pass the returned config directly to `run_macro(..., preprocess_config=config)`
- Scripts and notebook UIs can create/edit/save profiles without duplicating JSON-shaping logic
- Persisted preprocess profiles contain reusable processing policy only; run-specific bindings such as log metadata paths, bike profile paths, FIT directories, and FIT binding manifests are supplied separately by the caller.

---

### 4.2 `load_session()`

**Purpose:**  
Load raw logger data into a canonical session.

**Signature (conceptual):**
```python
session = load_session(
    csv_path: str,
    *,
    timezone: Optional[str] = None,
    log_metadata_path: Optional[str] = None,
    generic_log_metadata_paths: Optional[Sequence[str | Path]] = None,
)
```

**Returns:**  
- `session: Dict[str, Any]`

**Guarantees:**
- `session["df"]` is a pandas DataFrame
- `session["df"]` contains `time_s`
- Timestamp parsing is handled internally
- When logger log metadata is available, ingest may use it for delimiter, time-column, and metadata hints
- Generic log metadata paths are a run-level fallback and are not loaded from the preprocess profile.

---

### 4.3 `load_event_schema()`

**Purpose:**  
Load an event detection schema from YAML.

**Signature:**
```python
schema = load_event_schema(path: str)
schema, meta = load_event_schema(path: str, return_meta=True)
```

**Returns:**
- Default: `schema: Dict[str, Any]`
- With `return_meta=True`: `(schema, meta)`

**Meta contents (minimum):**
- `sha256`: content hash
- `source_path`: schema file path

---

### 4.4 `normalize_and_scale()`

**Purpose:**  
Legacy convenience helper for applying optional zeroing and scaling to selected columns.

**Signature (conceptual):**
```python
df = normalize_and_scale(df, ranges, ...)
df, meta = normalize_and_scale(df, ranges, ..., return_meta=True)
```

**Behavior:**
- Returns a new DataFrame; the input frame is not modified.
- If zeroing is enabled, explicit `<col>_op_zeroed` physical columns are created.
- Normalized outputs are always created from the selected normalization source.
- If the normalization source is zeroed, output names encode both operations, for example `<col> [1]_op_zeroed_norm`.
- For full preprocessing runs, callers should prefer `preprocess_session()`, which applies zeroing before bike-profile transforms and normalization after bike-profile transforms.

**Returns:**
- Default: `DataFrame`
- With `return_meta=True`: `(DataFrame, meta)`

**Guarantees:**
- Output DataFrame preserves `time_s`
- Scaling is deterministic given inputs
- Meta describes zeroing and scaling truthfully

---

### 4.5 `estimate_va_from_zeroed()`

**Purpose:**  
Compute velocity and acceleration via Savitzky–Golay differentiation.

**Signature (conceptual):**
```python
df = estimate_va_from_zeroed(df, ...)
df, meta = estimate_va_from_zeroed(df, ..., return_meta=True)
```

**Returns:**
- Default: `DataFrame`
- With `return_meta=True`: `(DataFrame, meta)`

**Guarantees:**
- Adds `<col>_vel` and `<col>_acc`
- Does not modify existing base columns
- Uses `time_s` or inferred `dt`

---

### 4.6 `preprocess_session()`

**Purpose:**  
Apply all standard preprocessing steps to a session.

**Signature:**
```python
session = preprocess_session(
    session,
    *,
    preprocess_config: Optional[Mapping[str, Any]] = None,
    normalize_ranges: Optional[Dict[str, float]] = None,
    bike_profile_path: Optional[str | Path] = None,
    bike_profile: Optional[Mapping[str, Any]] = None,
    sample_rate_hz: Optional[float] = None,
    motion_derivation: Optional[Mapping[str, Any]] = None,
    butterworth_smoothing: Optional[list[dict[str, float | int]]] = None,
    butterworth_generate_residuals: bool = False,
    active_signal_disp_selector: Optional[Mapping[str, Any]] = None,
    active_signal_vel_selector: Optional[Mapping[str, Any]] = None,
    ...
)
```

**Returns:**  
- `session: Dict[str, Any]`

**Guarantees:**
- `session["df"]` remains a DataFrame
- `time_s` is preserved
- QC and transform provenance are recorded under `session["qc"]`
- New callers may pass a single `preprocess_config` payload instead of unpacking individual preprocessing fields.
- Normalization ranges may be supplied directly as a runtime `normalize_ranges` map, or resolved
  from a bike profile using semantic signal selectors.
- Persisted preprocess profiles select activity-mask signals by semantic selectors, not dataframe
  column names. Runtime column-name overrides remain available for scripts that need them.
- Persisted preprocess profiles may include a `motion_derivation` block describing
  analysis-channel filtering and VA derivation policy. When enabled, preprocessing
  generates primary/secondary filtered displacement, velocity, and acceleration
  channels before normalization and activity-mask resolution.
- Generated analysis channels may carry registry provenance such as `processing_role`,
  `motion_source_id`, `motion_profile_id`, and structured `derivation` metadata. Semantic
  selectors may use these fields to request a primary analysis channel explicitly.
- If zeroing is enabled, physical displacement columns are zeroed before bike-profile signal transforms are applied.
- Normalized `[1]` outputs are generated after bike-profile signal transforms have been applied.
- When motion derivation is enabled, generated displacement analysis channels are also
  normalized using the full range of their source displacement signal.
- When `butterworth_smoothing` is provided, additional append-only displacement variants are created
  using zero-phase SOS Butterworth filtering.
- When `butterworth_generate_residuals=True`, each generated Butterworth series also emits an
  append-only residual series named `<butterworth_series>_resid`.

---

### 4.7 `detect_events_from_schema()`

**Purpose:**  
Detect events based on a schema definition.

**Signature (conceptual):**
```python
events_df = detect_events_from_schema(df, schema)
```

**Returns:**
- `events_df: DataFrame`

**Guarantees:**
- Events are indexed or timestamped in `time_s`
- Schema is treated as read-only

---

### 4.8 `extract_metrics_df()`

**Purpose:**  
Extract per-event metrics into a flat table.

**Signature:**
```python
metrics_df = extract_metrics_df(events_df)
```

**Returns:**
- `metrics_df: DataFrame`

---

### 4.9 `run_macro()`

**Purpose:**  
Run the full analysis pipeline in one call.

**Signature:**
```python
results = run_macro(
    csv_path: str,
    schema_path: Optional[str | Path] = None,
    *,
    preprocess_profile_path: Optional[str | Path] = None,
    preprocess_profile: Optional[Mapping[str, Any]] = None,
    preprocess_config: Optional[Mapping[str, Any]] = None,
    normalize_ranges: Optional[Dict[str, float]] = None,
    bike_profile_path: Optional[str | Path] = None,
    bike_profile: Optional[Mapping[str, Any]] = None,
    fit_import: Optional[dict[str, Any]] = None,
    sample_rate_hz: Optional[float] = None,
    motion_derivation: Optional[Mapping[str, Any]] = None,
    butterworth_smoothing: Optional[list[dict[str, float | int]]] = None,
    butterworth_generate_residuals: bool = False,
    active_signal_disp_selector: Optional[Mapping[str, Any]] = None,
    active_signal_vel_selector: Optional[Mapping[str, Any]] = None,
    timezone: Optional[str] = None,
    log_metadata_path: Optional[str] = None,
    generic_log_metadata_paths: Optional[Sequence[str | Path]] = None,
)
```

Preferred new-call pattern:

```python
config = load_preprocess_config("config/preprocess_profiles/suspension_default_v1.json")
fit_import = dict(config.get("fit_import") or {})
if fit_import.get("enabled"):
    fit_import["fit_dir"] = "Garmin/FIT"
    fit_import["bindings_path"] = "config/fit_bindings_v1.json"

results = run_macro(
    "ride.csv",
    preprocess_config=config,
    generic_log_metadata_paths=["config/log_metadata_examples/current_logger_config_hr_timestamp_log_metadata.json"],
    bike_profile_path="config/bike_profiles/example_enduro_bike_v1.json",
    fit_import=fit_import,
)
```

Callers should prefer `preprocess_config` or `preprocess_profile_path` for reusable preprocessing policy in new workflows. Local/run-specific inputs such as log metadata selection, bike profile selection, FIT source directory, and FIT binding manifest are passed as explicit run-level arguments rather than persisted inside the preprocess profile.

**Returns:**
```python
{
    "session": session,
    "schema": schema,
    "events": events_df,
    "metrics": metrics_df,
}
```

**Guarantees:**
- No tuple returns
- Stable keys in results dict
- Fully validated session
- When `fit_import` is enabled and a matching FIT file is resolved, the session may include
  resampled GPS columns on `session["df"]` and raw secondary stream data under `session["stream_dfs"]`

---

## 5. Error & Validation Model

### 5.1 Validation Errors
- Bad user input → `ValueError`
- Invalid schema structure → `ValueError`

### 5.2 Internal Invariants
- Enforced via `assert`
- Indicate programmer error, not user error

### 5.3 Session Validation
- `validate_session()` enforces session invariants
- Called at public pipeline boundaries

---

## 6. Versioning & Stability

### v0 Guarantees
- Public function signatures documented here are stable
- Return types and invariants will not change silently

### May Change Without v1
- Meta dictionary contents may expand
- QC fields may gain additional detail

### Requires Version Bump
- Breaking signature changes
- Changing canonical column names
- Changing default return types

---

## 7. Design Principles (Non-Normative)

- Explicit over implicit
- No tuple surprises
- Provenance is opt-in but structured
- Canonical time everywhere

---

**End of v0 Public API Contract**
