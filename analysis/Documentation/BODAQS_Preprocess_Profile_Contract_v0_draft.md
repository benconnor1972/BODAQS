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

This contract is intentionally narrow:

- it covers the persisted preprocessing profile document
- it does not define log discovery rules
- it does not define artifact layout
- it does not define user-prompt behavior for run/session descriptions
- it does not bind a run to local files such as log metadata, bike profiles, FIT directories, or FIT binding manifests

---

## 2. Architectural boundaries

### 2.1 What the profile controls

The profile captures parameters that are logically part of the high-level preprocessing call, including:

- event schema selection
- optional FIT import policy and field selection
- zeroing and normalization-output policy
- motion-derivation policy for analysis displacement, velocity, and acceleration channels
- legacy optional Butterworth smoothing behavior
- activity-mask signal and threshold settings
- strict vs tolerant ingestion mode

### 2.2 What the profile does not control

The following are notebook/runtime concerns and are explicitly **out of scope** for this contract:

- the log directory to scan
- the artifacts root directory
- CSV filename/glob rules
- generic log metadata selection for the current log batch
- bike profile selection for the current log batch
- FIT source directory selection
- FIT binding-manifest selection
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

The preprocess profile deliberately does not point at a log metadata document or
a bike profile. Those documents are selected by the notebook, CLI, or other
run-level orchestration layer because they describe the concrete logger output
and bike/setup used for the current batch, not the reusable preprocessing policy.

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

The root `config` object is the preferred public payload passed to the high-level preprocessing call.

Callers should pass it to `preprocess_session(..., preprocess_config=config)`.

Notebook code may still unpack the same fields into individual function arguments when helpful, but new callers should pass the config object intact.

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

class SignalSelectorConfigV1(TypedDict, total=False):
    end: str
    sensor: str
    quantity: str
    domain: str
    unit: str
    processing_role: str
    motion_source_id: str
    motion_profile_id: str

class FitImportConfigV1(TypedDict, total=False):
    enabled: bool
    field_allowlist: list[str]
    ambiguity_policy: str
    partial_overlap: str
    persist_raw_stream: bool
    resample_to_primary: bool
    resample_method: str
    raw_stream_name: str

class MotionDerivationSourceConfigV1(TypedDict):
    id: str
    selector: SignalSelectorConfigV1

class MotionDerivationProfileConfigV1(TypedDict, total=False):
    id: str
    displacement_lowpass_hz: float
    displacement_lowpass_order: int
    velocity_sg_window_ms: float
    acceleration_sg_window_ms: float
    sg_polyorder: int
    velocity_lowpass_hz: float
    velocity_lowpass_order: int
    acceleration_lowpass_hz: float
    acceleration_lowpass_order: int

class MotionDerivationConfigV1(TypedDict, total=False):
    enabled: bool
    sources: list[MotionDerivationSourceConfigV1]
    primary: MotionDerivationProfileConfigV1
    secondary: list[MotionDerivationProfileConfigV1]

class PreprocessRunConfigV1(TypedDict, total=False):
    schema_path: str
    strict: bool
    fit_import: FitImportConfigV1 | None
    zeroing_enabled: bool
    zero_window_s: float
    zero_min_samples: int
    clip_0_1: bool
    motion_derivation: MotionDerivationConfigV1 | None
    butterworth_smoothing: list[ButterworthSmoothingConfigV1]
    butterworth_generate_residuals: bool
    active_signal_disp_selector: SignalSelectorConfigV1 | None
    active_signal_vel_selector: SignalSelectorConfigV1 | None
    active_disp_thresh: float
    active_vel_thresh: float
    active_window: str
    active_padding: str
    active_min_seg: str
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
| `active_signal_disp_selector` | object or `null` | Semantic selector for the displacement signal used for activity-mask derivation |
| `active_disp_thresh` | number | Activity-mask displacement threshold |
| `active_vel_thresh` | number | Activity-mask velocity threshold |
| `active_window` | string | Rolling-softening window, for example `500ms` |
| `active_padding` | string | Padding added to merged active regions, for example `1s` |
| `active_min_seg` | string | Minimum active segment duration, for example `3s` |

### 6.3 Optional config fields

| field | type | meaning |
|---|---|---|
| `active_signal_vel_selector` | object or `null` | Semantic selector for the velocity signal used for activity masking; if absent or `null`, consumers may derive it from the displacement signal |
| `fit_import` | object or `null` | Optional Garmin FIT import policy block; when absent or `null`, FIT import is disabled |
| `motion_derivation` | object or `null` | Optional policy for generating primary and secondary filtered displacement/velocity/acceleration channels |
| `sample_rate_hz` | number or `null` | Explicit preprocessing sample-rate override; if absent or `null`, infer from `time_s` |

### 6.4 Config-field rules

- `schema_path` must resolve to an event schema YAML understood by the event schema loader.
- Normalization ranges should be derived from the selected bike profile's semantic `normalization_ranges` declarations.
- If `zeroing_enabled` is true, zeroing is applied to resolved physical displacement signals before bike-profile signal transforms are evaluated.
- Normalized `[1]` outputs are generated after bike-profile signal transforms, so generated signals can be normalized from the same bike profile.
- `motion_derivation` is optional in v1 so older profiles can still be read. New profiles SHOULD include it, even when `enabled` is `false`.
- When `motion_derivation.enabled` is `true`, the preprocessing pipeline generates the configured motion-analysis channels after zeroing and bike-profile transforms, and before normalization, activity-mask resolution, event detection, and metrics.
- `butterworth_smoothing` may be empty.
- `butterworth_smoothing` is the legacy append-only displacement smoothing policy. It is retained in v1 for current pipeline compatibility and is expected to be superseded by `motion_derivation`.
- `active_signal_disp_selector` and `active_signal_vel_selector` use the same semantic selector fields as bike-profile normalization ranges and transforms.
- Recommended default activity-mask selectors target rear suspension displacement and velocity: `{"end": "rear", "quantity": "disp", "domain": "suspension", "unit": "mm"}` and `{"end": "rear", "quantity": "vel", "domain": "suspension", "unit": "mm/s"}`.
- If `active_signal_disp_selector` is `null`, `active_signal_vel_selector` should also be `null`.
- If `active_signal_vel_selector` is absent or `null`, consumers may derive the companion velocity signal from the resolved displacement signal.
- `fit_import.field_allowlist` should contain Garmin record-field names such as `speed` or `position_lat`.
- `fit_import.ambiguity_policy` should default to `require_binding` when user choice is required for multi-match sessions.
- If `fit_import.enabled` is true, the FIT source directory and optional binding manifest must be supplied by the run-level caller.
- Consumers may ignore unknown config fields that they do not support.
- Consumers should reject runtime binding fields such as `generic_log_metadata_paths`, `bike_profile_path`, `bike_profile_id`, `normalize_ranges`, `prompt_for_descriptions`, `fit_import.fit_dir`, or `fit_import.bindings_path` if they appear inside a persisted preprocess profile.

### 6.5 `fit_import` block

When present, `fit_import` has the shape:

```json
{
  "enabled": true,
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
  "raw_stream_name": "gps_fit"
}
```

Rules:

- The profile describes FIT import behavior, not where local FIT files are stored.
- `fit_dir` and `bindings_path` are run-level inputs and must not be persisted inside the preprocess profile.
- `partial_overlap: "allow"` means incomplete GPS coverage is acceptable as long as there is some overlap.
- `persist_raw_stream` and `resample_to_primary` may both be `true`; that is the recommended current implementation pattern.

---

## 7. Motion derivation config contract

`motion_derivation` describes how the pipeline should create analysis-ready
displacement, velocity, and acceleration channels from semantically selected
displacement sources.

It is intentionally expressed in physical/analytical units:

- Butterworth filter cutoffs are specified in `Hz`
- Savitzky-Golay windows are specified in milliseconds
- polynomial order and filter order are dimensionless integers

The sample rate is used only at runtime to materialize filter coefficients and
sample-count windows.

### 7.1 Canonical shape

```json
{
  "enabled": true,
  "sources": [
    {
      "id": "rear_wheel",
      "selector": {
        "end": "rear",
        "quantity": "disp",
        "domain": "wheel",
        "unit": "mm"
      }
    }
  ],
  "primary": {
    "displacement_lowpass_hz": 80.0,
    "displacement_lowpass_order": 4,
    "velocity_sg_window_ms": 20.0,
    "acceleration_sg_window_ms": 40.0,
    "sg_polyorder": 3,
    "velocity_lowpass_hz": 60.0,
    "velocity_lowpass_order": 4,
    "acceleration_lowpass_hz": 30.0,
    "acceleration_lowpass_order": 4
  },
  "secondary": [
    {
      "id": "low_bandwidth",
      "series_suffix": "lp20hz",
      "displacement_lowpass_hz": 20.0,
      "displacement_lowpass_order": 4,
      "velocity_sg_window_ms": 50.0,
      "acceleration_sg_window_ms": 80.0,
      "sg_polyorder": 3,
      "velocity_lowpass_hz": 15.0,
      "velocity_lowpass_order": 4,
      "acceleration_lowpass_hz": 10.0,
      "acceleration_lowpass_order": 4
    }
  ]
}
```

### 7.2 Field rules

- `enabled` is boolean. If omitted, consumers should treat motion derivation as disabled.
- `sources` is a list of semantic displacement sources. It must be non-empty when `enabled` is `true`.
- Each source `id` must be unique within the block.
- Each source `selector` must be a non-empty signal selector and should identify an engineered physical displacement signal, usually `quantity: "disp"` and `unit: "mm"`.
- `primary` defines the main analysis series. When `enabled` is `true`, `primary` is required.
- `secondary` is optional and contains named lower-bandwidth or alternative analysis variants.
- Each secondary profile must have a unique `id`.
- Each secondary profile MAY include `series_suffix`. If omitted, consumers
  should generate a compact suffix from the displacement low-pass cutoff, for
  example `lp5hz` or `lp2p5hz`.
- All low-pass cutoffs and S-G windows must be numeric and greater than zero.
- All filter orders and `sg_polyorder` must be positive integers.
- Runtime consumers must check sample-rate feasibility before applying filters. Cutoffs must be below Nyquist, and implementations may apply a stricter practical limit.
- A generated primary analysis channel should not overwrite the raw or transformed displacement source; it should be an additional signal with clear provenance.
- Primary analysis columns SHOULD use semantic stems without operation-chain
  suffixes, for example `rear_wheel_disp_dom_wheel [mm]`,
  `rear_wheel_vel_dom_wheel [mm/s]`, and
  `rear_wheel_acc_dom_wheel [mm/s^2]`.
- Secondary analysis columns SHOULD use the same semantic stems plus the compact
  profile suffix, for example `rear_wheel_disp_lp5hz_dom_wheel [mm]`.
- Full filter and derivation provenance belongs in the signal registry
  (`op_chain`, `derivation`, `motion_source_id`, and `motion_profile_id`), not
  in primary column names.

### 7.3 Intended runtime ordering

When implemented by the pipeline, motion derivation should occur after zeroing
and bike-profile transforms, but before normalization and event detection:

```text
raw displacement
-> zero physical displacement
-> apply bike-profile transforms
-> low-pass selected displacement source
-> derive velocity/acceleration with Savitzky-Golay
-> apply final velocity/acceleration low-pass filters
-> normalize selected analysis displacement channels
-> event detection and metrics
```

This ordering means that normalized `[1]` displacement channels used for event
thresholds can represent the filtered primary analysis displacement rather than
the unfiltered source.

## 8. Legacy Butterworth smoothing config contract

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

This block is retained for current pipeline compatibility. New profile authors
should prefer `motion_derivation` for analysis-channel bandwidth policy.

---

## 9. Signal selector contract

Signal selectors identify a signal by meaning rather than by dataframe column name.

Each selector may contain any of:

```json
{
  "end": "rear",
  "quantity": "disp",
  "domain": "suspension",
  "unit": "mm"
}
```

Supported selector fields:

| field | meaning |
|---|---|
| `end` | Bike end or location class, usually `front` or `rear` |
| `quantity` | Measured or derived quantity, for example `disp` or `vel` |
| `domain` | Physical domain, for example `suspension` or `wheel` |
| `unit` | Signal unit, for example `mm` or `mm/s` |
| `processing_role` | Analysis role, for example `primary_analysis` or `secondary_analysis` |
| `motion_source_id` | Optional source id from `motion_derivation.sources[]` |
| `motion_profile_id` | Optional motion profile id, for example `primary` or a secondary profile id |

Rules:

- A selector must be `null` or a non-empty object.
- Selectors must use semantic fields such as `end`, `domain`, `quantity`,
  `unit`, and `processing_role`. Logger/source `sensor` ids are not analysis
  selector fields.
- Selectors may include `processing_role` when the caller needs the primary filtered analysis signal rather than any semantically compatible source.
- Consumers should reject selectors that match more than one signal in a session.
- Consumers may treat a selector that matches no signal as a disabled activity mask for that run, provided this is recorded in QC or warnings.

---

## 10. Path and resolution semantics

### 10.1 `schema_path`

`schema_path` is stored as a string.

This contract allows either:

- an absolute path, or
- a relative path

Path resolution policy is consumer-defined.

**Current combined-notebook behavior:** relative paths are resolved against the notebook working directory, not the profile file's parent directory.

That behavior should be treated as the current implementation detail for v1 authorship. Profile authors should therefore choose relative paths that are valid from the notebook working directory used in practice.

Public API consumers that need deterministic path handling outside notebooks should call `resolve_preprocess_config_paths(config, base_dir=...)` before passing the config to the high-level preprocessing call.

---

## 11. Profile authoring utilities

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

## 12. Example document

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
      "raw_stream_name": "gps_fit"
    },
    "zeroing_enabled": false,
    "zero_window_s": 0.4,
    "zero_min_samples": 10,
    "clip_0_1": false,
    "motion_derivation": {
      "enabled": false,
      "sources": [
        {
          "id": "rear_wheel",
          "selector": {
            "end": "rear",
            "quantity": "disp",
            "domain": "wheel",
            "unit": "mm"
          }
        }
      ],
      "primary": {
        "displacement_lowpass_hz": 80.0,
        "displacement_lowpass_order": 4,
        "velocity_sg_window_ms": 20.0,
        "acceleration_sg_window_ms": 40.0,
        "sg_polyorder": 3,
        "velocity_lowpass_hz": 60.0,
        "velocity_lowpass_order": 4,
        "acceleration_lowpass_hz": 30.0,
        "acceleration_lowpass_order": 4
      },
      "secondary": []
    },
    "butterworth_smoothing": [],
    "butterworth_generate_residuals": false,
    "active_signal_disp_selector": {
      "end": "rear",
      "quantity": "disp",
      "domain": "suspension",
      "unit": "mm"
    },
    "active_signal_vel_selector": {
      "end": "rear",
      "quantity": "vel",
      "domain": "suspension",
      "unit": "mm/s"
    },
    "active_disp_thresh": 20.0,
    "active_vel_thresh": 50.0,
    "active_window": "500ms",
    "active_padding": "1s",
    "active_min_seg": "3s"
  }
}
```

Normalization ranges are intentionally not embedded in this profile example; they are bike/setup facts and should be resolved from the run-selected bike profile.

---

## 13. Consumer behavior

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
- runtime binding fields embedded in the profile
- unresolved `schema_path`

---

## 14. Current limitations and open issues

1. There is no explicit `active_enabled` flag in v1. The current profile shape assumes an activity-mask configuration is always present. A cleaner enable/disable contract may be added in a later version.
2. The profile assumes the target log set is homogeneous enough that one activity-mask signal selection is valid for every file being processed.
3. This contract does not yet define profile discovery, cataloging, inheritance, or profile-composition behavior.

---

## 15. Suggested future evolution

Likely v2 candidates:

- explicit `active_enabled`
- explicit relative-path base semantics
- profile-level metadata for intended bike/platform/logger family
- optional validation hints for expected signal presence
- a formal JSON Schema or Pydantic model published alongside the prose contract
