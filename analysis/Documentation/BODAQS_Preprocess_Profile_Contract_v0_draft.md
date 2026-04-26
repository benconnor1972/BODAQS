# BODAQS Preprocess Profile Contract (Draft)

**Status:** Draft  
**Scope:** Persisted preprocessing configuration for notebook-driven analysis ingestion  
**Primary goal:** allow notebooks to load a versioned preprocessing profile from disk instead of rebuilding the config interactively

---

## 1. Summary

This contract defines a small persisted JSON document that captures the preprocessing configuration used when calling the BODAQS analysis pipeline.

The profile is intended to support:

- repeatable preprocessing across notebook runs
- fewer interactive setup steps before results are shown
- explicit, reviewable configuration that can be stored alongside analysis code
- later formalization of named preprocessing presets
- optional Garmin FIT import policy for GPS enrichment during preprocessing
- optional references to generic log metadata and bike-profile artifacts

This contract is intentionally narrow:

- it covers the persisted preprocessing profile document
- it does not define log discovery rules
- it does not define artifact layout
- it does not define user-prompt behavior for run/session descriptions

---

## 2. Architectural boundaries

### 2.1 What the profile controls

The profile captures parameters that are logically part of `run_macro(...)` preprocessing and event extraction, including:

- event schema selection
- optional FIT import policy and field selection
- optional generic log metadata fallback selection
- optional bike profile selection
- zeroing and normalization policy
- optional Butterworth smoothing behavior
- activity-mask signal and threshold settings
- strict vs tolerant ingestion mode

### 2.2 What the profile does not control

The following are notebook/runtime concerns and are explicitly **out of scope** for this contract:

- the log directory to scan
- the artifacts root directory
- CSV filename/glob rules
- SHA cache location and processed-file detection policy
- whether to prompt for run or session descriptions
- timezone label or other run-labeling policy
- the per-session user choice required when multiple overlapping FIT files exist
- the contents of referenced bike profiles

### 2.3 Relationship to other contracts

This contract depends on, or should be read alongside:

- `analysis/documentation/BODAQS_analysis_artifacts_specification_v0_2.md`
- `analysis/documentation/BODAQS_event_schema_specification_v0_1_2.md`
- `analysis/documentation/BODAQS_Minimum_Signal_Registry_Semantics_v0_1_1.md`
- `analysis/documentation/BODAQS_Bike_Profile_Contract_v0_draft.md`

The profile does not replace those contracts. It points at them.

---

## 3. Recommended storage

This contract does not require one global storage root, but a recommended repository-local location is:

```text
analysis/config/preprocess_profiles/
```

Recommended filename pattern:

```text
<profile_id>_v<version>.json
```

Example:

```text
analysis/config/preprocess_profiles/suspension_default_v1.json
```

---

## 4. Core concepts

### 4.1 Profile

A **preprocess profile** is a versioned JSON document describing one reusable preprocessing preset.

### 4.2 Profile schema version

The root `version` field identifies the profile-document contract version, not the event schema version and not the notebook version.

### 4.3 Pipeline config payload

The root `config` object is the preferred public payload passed to `run_macro(..., preprocess_config=config)`.

Legacy notebook code may still unpack the same fields into individual `run_macro(...)` arguments, but new callers should pass the config object intact.

---

## 5. Root document contract

### 5.1 Canonical JSON shape

```python
from typing import Literal, NotRequired, TypedDict

class BODAQSPreprocessProfileV1(TypedDict):
    schema: Literal["bodaqs.preprocess_profile"]
    version: Literal[1]
    profile_id: str
    description: NotRequired[str]
    config: "PreprocessRunConfigV1"
```

### 5.2 Required root fields

| field | type | required | meaning |
|---|---|---|---|
| `schema` | string | yes | Must be exactly `"bodaqs.preprocess_profile"` |
| `version` | integer | yes | Must be exactly `1` for this contract version |
| `profile_id` | string | yes | Stable identifier for the profile |
| `description` | string | no | Human-readable description |
| `config` | object | yes | Preprocessing configuration payload |

### 5.3 Root-field rules

- `profile_id` should be stable across edits to the same logical preset.
- `profile_id` should be filesystem-friendly; lowercase snake_case is recommended.
- `description` is informational only.
- Consumers should reject documents with an unexpected `schema` or unsupported `version`.
- Consumers may ignore unknown root-level fields.

---

## 6. Config payload contract

### 6.1 Typed shape

```python
from typing import TypedDict

class ButterworthSmoothingConfigV1(TypedDict):
    cutoff_hz: float
    order: int

class FitImportConfigV1(TypedDict, total=False):
    enabled: bool
    fit_dir: str
    field_allowlist: list[str]
    ambiguity_policy: str
    partial_overlap: str
    persist_raw_stream: bool
    resample_to_primary: bool
    resample_method: str
    raw_stream_name: str
    bindings_path: str | None

class PreprocessRunConfigV1(TypedDict, total=False):
    schema_path: str
    strict: bool
    fit_import: FitImportConfigV1 | None
    generic_log_metadata_paths: list[str]
    bike_profile_path: str | None
    bike_profile_id: str | None
    zeroing_enabled: bool
    zero_window_s: float
    zero_min_samples: int
    clip_0_1: bool
    butterworth_smoothing: list[ButterworthSmoothingConfigV1]
    butterworth_generate_residuals: bool
    active_signal_disp_col: str | None
    active_signal_vel_col: str | None
    active_disp_thresh: float
    active_vel_thresh: float
    active_window: str
    active_padding: str
    active_min_seg: str
    normalize_ranges: dict[str, float]  # deprecated transitional compatibility
    sample_rate_hz: float | None
```

`total=False` is used above only to show that some fields are optional in JSON. The required/optional split is defined below.

### 6.2 Required config fields

| field | type | meaning |
|---|---|---|
| `schema_path` | string | Path to the event schema YAML |
| `strict` | boolean | `True` for strict ingestion/metrics behavior, `False` for tolerant behavior |
| `zeroing_enabled` | boolean | Enable zeroing before bike-profile signal transforms |
| `zero_window_s` | number | Window length in seconds for zero-offset estimation |
| `zero_min_samples` | integer | Minimum samples required for zero-offset estimation |
| `clip_0_1` | boolean | Clip normalized channels to `[0, 1]` |
| `butterworth_smoothing` | array | Sequence of zero or more Butterworth filter configs |
| `butterworth_generate_residuals` | boolean | Whether residual series should be generated when smoothing is enabled |
| `active_signal_disp_col` | string or `null` | Canonical displacement signal used for activity-mask derivation |
| `active_disp_thresh` | number | Activity-mask displacement threshold |
| `active_vel_thresh` | number | Activity-mask velocity threshold |
| `active_window` | string | Rolling-softening window, for example `500ms` |
| `active_padding` | string | Padding added to merged active regions, for example `1s` |
| `active_min_seg` | string | Minimum active segment duration, for example `3s` |

### 6.3 Optional config fields

| field | type | meaning |
|---|---|---|
| `active_signal_vel_col` | string or `null` | Explicit velocity signal to use for activity masking; if absent or `null`, consumers may derive it from the displacement signal |
| `fit_import` | object or `null` | Optional Garmin FIT import policy block; when absent or `null`, FIT import is disabled |
| `sample_rate_hz` | number or `null` | Explicit preprocessing sample-rate override; if absent or `null`, infer from `time_s` |
| `generic_log_metadata_paths` | array | Optional list of reusable log metadata fallback files/directories |
| `bike_profile_path` | string or `null` | Optional path to a bike profile JSON document |
| `bike_profile_id` | string or `null` | Optional bike profile identifier used for UI matching or future lookup |
| `normalize_ranges` | object | Deprecated transitional override for legacy callers that still provide canonical-column range maps; canonical range data belongs in the referenced bike profile |

### 6.4 Config-field rules

- `schema_path` must resolve to an event schema YAML understood by the event schema loader.
- `generic_log_metadata_paths`, when present, must resolve to exactly one usable generic log metadata file in non-interactive runs.
- `bike_profile_path`, when present, should resolve to a `bodaqs.bike_profile` JSON document.
- `bike_profile_id`, when present, should match the selected bike profile's `bike_profile_id`.
- Normalization ranges should be derived from the selected bike profile's semantic `normalization_ranges` declarations.
- `normalize_ranges`, if present, is a deprecated transitional field for compatibility with legacy callers that have not yet migrated to bike-profile range resolution.
- Values in `normalize_ranges`, if present, must be numeric and greater than zero.
- Keys in `normalize_ranges`, if present, should be canonical displacement signal names, not raw logger column names.
- If `zeroing_enabled` is true, zeroing is applied to resolved physical displacement signals before bike-profile signal transforms are evaluated.
- Normalized `[1]` outputs are generated after bike-profile signal transforms, so generated signals can be normalized from the same bike profile.
- `butterworth_smoothing` may be empty.
- If `active_signal_disp_col` is `null`, `active_signal_vel_col` should also be `null`.
- When `fit_import` is present, `fit_import.enabled=True` requires a non-empty `fit_dir`.
- `fit_import.field_allowlist` should contain Garmin record-field names such as `speed` or `position_lat`.
- `fit_import.ambiguity_policy` should default to `require_binding` when user choice is required for multi-match sessions.
- Consumers may ignore unknown config fields that they do not support.

### 6.5 `fit_import` block

When present, `fit_import` has the shape:

```json
{
  "enabled": true,
  "fit_dir": "Garmin/FIT",
  "field_allowlist": [
    "position_lat",
    "position_long",
    "altitude",
    "enhanced_altitude",
    "speed",
    "enhanced_speed",
    "distance",
    "grade",
    "heading"
  ],
  "ambiguity_policy": "require_binding",
  "partial_overlap": "allow",
  "persist_raw_stream": true,
  "resample_to_primary": true,
  "resample_method": "linear",
  "raw_stream_name": "gps_fit",
  "bindings_path": "analysis/config/fit_bindings_v1.json"
}
```

Rules:

- `fit_dir` is part of the reusable preprocess policy for FIT discovery.
- `bindings_path` points at a separate session-binding manifest used only when multiple overlapping FIT files exist.
- `partial_overlap: "allow"` means incomplete GPS coverage is acceptable as long as there is some overlap.
- `persist_raw_stream` and `resample_to_primary` may both be `true`; that is the recommended current implementation pattern.

---

## 7. Butterworth smoothing config contract

Each entry in `butterworth_smoothing` must have the shape:

```json
{
  "cutoff_hz": 3.0,
  "order": 4
}
```

Rules:

- `cutoff_hz` must be numeric and greater than zero
- `order` must be a positive integer
- duplicate filter definitions that canonicalize to the same generated operation tag should be rejected

The generated filter-operation tag is derived by code and is **not** part of the stored profile contract.

---

## 8. Path and resolution semantics

### 8.1 `schema_path`

`schema_path` is stored as a string.

This contract allows either:

- an absolute path, or
- a relative path

Path resolution policy is consumer-defined.

**Current combined-notebook behavior:** relative paths are resolved against the notebook working directory, not the profile file's parent directory.

That behavior should be treated as the current implementation detail for v1 authorship. Profile authors should therefore choose relative paths that are valid from the notebook working directory used in practice.

Public API consumers that need deterministic path handling outside notebooks should call `resolve_preprocess_config_paths(config, base_dir=...)` before passing the config to `run_macro(...)`.

---

## 9. Profile authoring utilities

The analysis package provides utility functions so notebooks and scripts do not
need to hand-roll preprocess profile JSON:

```python
config = default_preprocess_config(**overrides)
profile = make_preprocess_profile("suspension_default", config=config)
save_preprocess_profile(profile, "config/preprocess_profiles/suspension_default_v1.json")
profiles = discover_preprocess_profiles("config/preprocess_profiles")
```

Notebook users can also use the widget editor:

```python
from bodaqs_analysis.ui import make_preprocess_profile_editor

editor = make_preprocess_profile_editor(
    profile_path="config/preprocess_profiles/suspension_default_v1.json"
)
display(editor.ui)

profile = editor.get_profile()
config = editor.get_config()
```

The editor is a convenience layer over this contract. The JSON document it saves
must still validate as a normal `bodaqs.preprocess_profile` document.

---

## 10. Example document

```json
{
  "schema": "bodaqs.preprocess_profile",
  "version": 1,
  "profile_id": "suspension_default",
  "description": "Default preprocessing profile for the combined preprocessing and suspension dashboard notebook.",
  "config": {
    "schema_path": "event schema/event_schema.yaml",
    "strict": false,
    "fit_import": {
      "enabled": false,
      "fit_dir": "Garmin/FIT",
      "field_allowlist": [
        "position_lat",
        "position_long",
        "altitude",
        "enhanced_altitude",
        "speed",
        "enhanced_speed",
        "distance",
        "grade",
        "heading"
      ],
      "ambiguity_policy": "require_binding",
      "partial_overlap": "allow",
      "persist_raw_stream": true,
      "resample_to_primary": true,
      "resample_method": "linear",
      "raw_stream_name": "gps_fit",
      "bindings_path": "analysis/config/fit_bindings_v1.json"
    },
    "generic_log_metadata_paths": [
      "config/log_metadata_examples/current_logger_config_fast_timestamp_log_metadata.json"
    ],
    "bike_profile_path": "config/bike_profiles/example_enduro_bike_v1.json",
    "bike_profile_id": "example_enduro_bike",
    "zeroing_enabled": false,
    "zero_window_s": 0.4,
    "zero_min_samples": 10,
    "clip_0_1": false,
    "butterworth_smoothing": [],
    "butterworth_generate_residuals": false,
    "active_signal_disp_col": "front_shock_dom_suspension [mm]",
    "active_signal_vel_col": null,
    "active_disp_thresh": 20.0,
    "active_vel_thresh": 50.0,
    "active_window": "500ms",
    "active_padding": "1s",
    "active_min_seg": "3s"
  }
}
```

Activity-signal examples use canonical signal names because the current activity-mask API still expects dataframe columns. Normalization ranges are intentionally not embedded in this profile example; they are bike/setup facts and should be resolved from the referenced bike profile.

Compatibility note: existing callers may still supply a legacy `normalize_ranges` map. New profile-authored workflows should prefer `bike_profile_path`, allowing the pipeline to resolve normalization ranges from bike-profile signal semantics.

---

## 11. Consumer behavior

Consumers implementing this contract should:

1. read the JSON document as UTF-8
2. validate `schema` and `version`
3. validate that `config` is an object
4. validate required fields and value shapes
5. resolve `schema_path`
6. pass the resulting values into the preprocessing pipeline in a documented way

Consumers should fail fast on:

- unsupported profile version
- missing required fields
- invalid Butterworth config entries
- unresolved required bike profile or normalization range semantics
- invalid legacy `normalize_ranges`, if supplied
- unresolved `schema_path`

---

## 12. Current limitations and open issues

1. There is no explicit `active_enabled` flag in v1. The current profile shape assumes an activity-mask configuration is always present. A cleaner enable/disable contract may be added in a later version.
2. The profile assumes the target log set is homogeneous enough that one selected bike profile and one activity-mask signal selection are valid for every file being processed.
3. This contract does not yet define profile discovery, cataloging, inheritance, or profile-composition behavior.

---

## 13. Suggested future evolution

Likely v2 candidates:

- explicit `active_enabled`
- explicit relative-path base semantics
- profile-level metadata for intended bike/platform/logger family
- optional validation hints for expected signal presence
- a formal JSON Schema or Pydantic model published alongside the prose contract
