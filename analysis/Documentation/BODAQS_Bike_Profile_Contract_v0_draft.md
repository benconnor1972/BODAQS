# BODAQS Bike Profile Contract

Version: v0 draft
Status: Proposal
Scope: Bike/setup-specific parameters used by preprocessing

## 1. Purpose

A bike profile is a persisted JSON document that describes parameters belonging
to a specific bike setup rather than to a logger, CSV file, or generic
preprocessing recipe.

Typical contents include:

- normalization ranges for physical travel signals, identified by semantics rather than column names
- bike/setup-specific signal transforms, such as shock travel to wheel travel
- installed sensor notes and mount context
- optional identifiers that logger-emitted log metadata can reference

The goal is to keep logger metadata focused on what was logged, while the bike
profile describes how those logged signals should be interpreted for a specific
bike installation.

## 2. Boundaries

### 2.1 Belongs In A Bike Profile

- suspension travel ranges
- sensor mounting notes
- linkage transforms
- wheel-travel transforms
- polynomial or LUT parameters that depend on installation geometry
- stable bike/setup identifiers

### 2.2 Does Not Belong In A Bike Profile

- CSV column bindings
- logger timestamp format
- logger firmware metadata
- event schema selection
- FIT import paths
- smoothing/zeroing/VA algorithm choices
- per-run artifact output locations

Those items belong in log metadata, preprocess profiles, or notebook/runtime
configuration.

## 3. Recommended Storage

Recommended repository-local location:

```text
analysis/config/bike_profiles/
```

Recommended filename pattern:

```text
<bike_profile_id>_v<version>.json
```

Example:

```text
analysis/config/bike_profiles/example_enduro_bike_v1.json
```

## 4. Top-Level JSON Object

Required fields:

- `schema`
- `version`
- `bike_profile_id`
- `display_name`

Optional fields:

- `description`
- `bike`
- `setup`
- `normalization_ranges`
- `signal_transforms`
- `installed_sensors`
- `provenance`

## 5. Root Fields

### 5.1 `schema`

Required string.

Recommended value:

```json
"bodaqs.bike_profile"
```

### 5.2 `version`

Required integer.

For this draft, the only supported value is:

```json
1
```

### 5.3 `bike_profile_id`

Required string.

Rules:

- SHOULD be stable across edits to the same logical bike/setup.
- SHOULD be lowercase snake_case.
- MAY be referenced by logger-emitted log metadata as a hint.

### 5.4 `display_name`

Required string.

Human-readable name shown in UI controls.

## 6. Bike And Setup Metadata

### 6.1 `bike`

Optional object.

Suggested fields:

- `manufacturer`
- `model`
- `model_year`
- `frame_size`
- `wheel_size`
- `notes`

All fields are optional strings.

### 6.2 `setup`

Optional object.

Suggested fields:

- `setup_id`
- `display_name`
- `created_at`
- `notes`

Use this when the same bike can have multiple sensor/linkage/setup variants.

## 7. Normalization Ranges

`normalization_ranges` is an optional array of semantic range declarations.

The range belongs to the physical signal, not to whatever the dataframe column
happens to be called after ingestion. Consumers should resolve each declaration
against the signal registry/log metadata semantics, then apply the range to the
matching canonical analysis signal.

Example:

```json
[
  {
    "id": "front_fork_travel_range",
    "signal": {
      "sensor": "front_shock",
      "quantity": "disp",
      "domain": "suspension",
      "unit": "mm"
    },
    "full_range": 170.0
  },
  {
    "id": "rear_shock_travel_range",
    "signal": {
      "sensor": "rear_shock",
      "quantity": "disp",
      "domain": "suspension",
      "unit": "mm"
    },
    "full_range": 65.0
  }
]
```

Rules:

- `id` MUST be unique within `normalization_ranges`.
- `signal` MUST identify the physical signal by semantics.
- `signal` SHOULD be specific enough to resolve exactly one signal.
- Sensor aliases MAY be canonicalized before matching, using the same rules as signal selectors.
- `full_range` MUST be a finite number greater than zero.
- These ranges are bike/setup facts, not logger facts.
- Consumers MAY derive the dataframe column name only after semantic binding has been completed.

## 8. Signal Transforms

`signal_transforms` is an optional array of transforms applied during
preprocessing.

Transforms are declared by signal semantics, not by CSV headers, logger channel
names, or directory names.

Each transform has:

- an `id`
- a semantic `input` selector
- a semantic `output` declaration
- a `method`
- method-specific parameters

### 8.1 Transform Object

Required fields:

- `id`
- `input`
- `output`
- `method`

Optional fields:

- `description`
- `enabled`
- `interpolation`
- `extrapolation`
- `lut`
- `polynomial`

Rules:

- `id` MUST be unique within the bike profile.
- `enabled`, if omitted, SHOULD be interpreted as `true`.
- `method` MUST be one of `lut` or `polynomial`.
- A transform SHOULD be applied after log metadata binding and before velocity/acceleration calculation.
- If the transform output signal already exists in the dataframe, consumers SHOULD keep the existing column, skip the bike-profile transform, and record a warning/provenance note rather than overwriting data.

### 8.2 Signal Selector

A signal selector identifies an input signal by semantics.

Supported selector fields:

- `sensor`
- `quantity`
- `domain`
- `unit`

Example:

```json
{
  "sensor": "rear_shock",
  "quantity": "disp",
  "domain": "suspension",
  "unit": "mm"
}
```

Rules:

- Selectors SHOULD be specific enough to resolve exactly one input signal.
- Sensor values are semantic sensor identifiers. Consumers MAY canonicalize known aliases, for example `fork` to `front_shock` and `shock` to `rear_shock`, before matching.
- If a selector resolves zero signals, consumers SHOULD warn and skip the transform unless the transform is required by local policy.
- If a selector resolves multiple signals, consumers SHOULD fail or ask the user to choose.

### 8.3 Output Declaration

The `output` object uses the same semantic fields as a selector, but declares
the signal to be created.

Example:

```json
{
  "sensor": "rear_wheel",
  "quantity": "disp",
  "domain": "wheel",
  "unit": "mm"
}
```

Consumers SHOULD derive the output dataframe column name from these semantics
using the canonical BODAQS signal naming rules.

### 8.4 LUT Transform

For `method: "lut"`, required fields:

- `lut`

Each LUT point has:

- `input`
- `output`

Rules:

- `lut` MUST contain at least two points.
- LUT `input` values MUST be strictly increasing.
- `interpolation`, if present, SHOULD be one of `linear` or `nearest`.
- `extrapolation`, if present, SHOULD be one of `clamp`, `linear`, or `error`.

### 8.5 Polynomial Transform

For `method: "polynomial"`, required fields:

- `polynomial`

Suggested polynomial fields:

- `coefficients`
- `coefficient_order`
- `input_offset`
- `input_scale`
- `output_offset`

Rules:

- `coefficients` MUST contain at least one number.
- `coefficient_order` SHOULD be `ascending`, meaning `a0 + a1*x + a2*x^2 ...`.
- If `coefficient_order` is omitted, consumers SHOULD assume `ascending`.
- If `input_offset`, `input_scale`, or `output_offset` are present, consumers SHOULD evaluate `y = polynomial((x - input_offset) * input_scale) + output_offset`.

## 9. Installed Sensors

`installed_sensors` is an optional array describing sensor installation context.

Suggested fields:

- `sensor`
- `logger_channel`
- `mount_location`
- `notes`

This section is informational in v0. It can help users understand why a
particular transform is appropriate for a given bike setup.

## 10. Validation Rules

A bike profile is structurally valid if:

1. The JSON parses to an object.
2. `schema` is exactly `bodaqs.bike_profile`.
3. `version` is `1`.
4. `bike_profile_id` is a non-empty string.
5. `display_name` is a non-empty string.
6. `normalization_ranges`, if present, is an array of semantic range declarations with positive numeric `full_range` values.
7. Every normalization range has a unique non-empty `id`.
8. Every normalization range has `signal` and `full_range`.
9. `signal_transforms`, if present, is an array.
10. Every transform has a unique non-empty `id`.
11. Every transform has `input`, `output`, and `method`.
12. Every transform `method` is `lut` or `polynomial`.
13. Every LUT transform has at least two points with strictly increasing `input` values.
14. Every polynomial transform has at least one numeric coefficient.

## 11. Relationship To Other Artifacts

- Log metadata MAY include `bike_profile_id` as a hint.
- A preprocess profile MAY reference a bike profile by path or id.
- The bike profile does not replace log metadata; it complements it.
- The bike profile should be treated as analysis configuration, not firmware configuration.

## 12. Minimal Example

```json
{
  "schema": "bodaqs.bike_profile",
  "version": 1,
  "bike_profile_id": "example_enduro_bike",
  "display_name": "Example enduro bike",
  "normalization_ranges": [
    {
      "id": "front_fork_travel_range",
      "signal": {
        "sensor": "front_shock",
        "quantity": "disp",
        "domain": "suspension",
        "unit": "mm"
      },
      "full_range": 170.0
    },
    {
      "id": "rear_shock_travel_range",
      "signal": {
        "sensor": "rear_shock",
        "quantity": "disp",
        "domain": "suspension",
        "unit": "mm"
      },
      "full_range": 65.0
    }
  ]
}
```
