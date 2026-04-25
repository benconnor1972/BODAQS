# MTB Logger CSV + JSON Interchange Contract

Version: v0.1 draft
Status: Proposal
Scope: Common interchange contract for MTB logger session outputs

## 1. Purpose

This document proposes a simple interchange contract for mountain bike data logger outputs using:

- one CSV file for time-series samples
- one JSON sidecar for semantics, calibration, transforms, quality-control information, and provenance

The goal is to make downstream analysis tooling independent of logger-specific knowledge. A consumer should be able to interpret the CSV using only the sidecar JSON and the contract defined here.

## 2. Design goals

- Keep the minimum valid implementation as small as possible.
- Keep semantic meaning outside the CSV header naming convention.
- Make time handling explicit and uniform.
- Separate calibration from later semantic transformations.
- Allow richer provenance when producers care to provide it.
- Allow consumers to ignore metadata sections they do not need.

## 3. Conformance language

The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY in this document are to be interpreted as normative requirements.

## 4. File pair

A session consists of a pair of files sharing a common base name.

Example:

- `2026-02-19_08-35-11.csv`
- `2026-02-19_08-35-11.json`

The CSV contains samples.
The JSON contains metadata.

## 5. Core principles

- The CSV is the authoritative source of sampled values.
- The JSON is the authoritative source of semantic interpretation.
- `columns` metadata is keyed by exact CSV header strings.
- Each stream has exactly one canonical time column.
- Time columns are always numeric seconds from session start.
- The minimal valid JSON should be easy to produce even for simple loggers.

## 6. Top-level JSON object

The JSON sidecar is a single object with the following top-level keys.

Required:

- `contract`
- `streams`
- `columns`

Optional:

- `data_file`
- `session`
- `sensors`
- `transforms`
- `qc`
- `provenance`

## 7. Top-level sections

### 7.1 `contract`

Purpose:
- identifies the contract and version

Required fields:
- `name`: string
- `version`: string

Constraints:
- producers MUST set `name`
- producers MUST set `version`
- consumers MUST reject documents where either field is missing or not a string

Recommended values:
- `name`: `mtb_logger_timeseries`
- `version`: `0.1.0`

### 7.2 `data_file`

Purpose:
- describes the associated CSV file

Optional fields:
- `path`: string
- `sha256`: string
- `delimiter`: string
- `header`: boolean
- `row_count`: integer

Constraints:
- if present, `row_count` MUST be a non-negative integer
- if present, `header` SHOULD be `true`
- if present, `delimiter` SHOULD be a single-character string

### 7.3 `session`

Purpose:
- provides session identity and human context

Optional fields:
- `session_id`: string
- `started_at_local`: string
- `timezone`: string
- `notes`: string or null

Constraints:
- if present, `session_id` MUST be a string
- if present, `started_at_local` SHOULD be an ISO 8601 local datetime string with UTC offset

Interpretation rule:
- all stream time columns are measured in seconds from the session start represented by `session.started_at_local` when that field is present

### 7.4 `streams`

Purpose:
- declares each timebase present in the CSV

Shape:
- object keyed by stream id

Required per stream:
- `type`
- `time_col`
- `time_unit`

Optional per stream:
- `sample_rate_hz`
- `jitter_frac`
- `notes`

Constraints:
- `type` MUST be one of `uniform` or `intermittent`
- `time_col` MUST be a string naming a CSV column
- `time_unit` MUST be `s`
- for `uniform` streams, `sample_rate_hz` MAY be provided
- for `uniform` streams, `jitter_frac` MAY be provided
- for `intermittent` streams, `sample_rate_hz` SHOULD be omitted
- for `intermittent` streams, `jitter_frac` SHOULD be omitted

### 7.5 `sensors`

Purpose:
- describes reusable sensor-level calibration and identity information

Shape:
- object keyed by sensor id

All fields in this section are optional.

Suggested sensor fields:
- `type`: string
- `domain`: string
- `raw_unit`: string
- `calibration`: object

Suggested linear calibration fields:
- `type`
- `input_unit`
- `output_unit`
- `installed_zero_count`
- `sensor_zero_count`
- `sensor_full_count`
- `sensor_full_travel`
- `invert`

Constraints:
- if `calibration` is present, `type`, `input_unit`, and `output_unit` SHOULD be present
- if `sensor_full_travel` is present, it is interpreted in `calibration.output_unit`

### 7.6 `transforms`

Purpose:
- optional registry of post-calibration transforms referenced by column metadata

Shape:
- object keyed by transform id

All fields in this section are optional.

Suggested transform fields:
- `type`: string
- `input_unit`: string
- `output_unit`: string
- `description`: string
- `interpolation`: string
- `extrapolation`: string
- `lut`: array

Suggested LUT point fields:
- `input`: number
- `output`: number

Constraints:
- transform ids MUST be unique
- if a transform is referenced by `transform_chain`, the id SHOULD resolve in this section when `transforms` is present
- if `type` is `lut` and `lut` is present, the LUT MUST contain at least two points
- LUT `input` values MUST be strictly increasing

### 7.7 `columns`

Purpose:
- defines the semantics of every CSV column

Shape:
- object keyed by exact CSV header string

Rule:
- every CSV column MUST appear exactly once in `columns`

Supported `class` values:
- `time`
- `signal`
- `index`
- `event_flag`
- `qc_flag`

Required for every column entry:
- `class`
- `dtype`

Required for `class: "time"`:
- `stream`
- `unit`

Required for `class: "signal"`:
- `stream`
- `quantity`
- `unit`

Optional signal fields:
- `sensor`
- `domain`
- `source_columns`
- `calibration_ref`
- `transform_chain`
- `notes`

Interpretation rules:
- `quantity: "raw"` identifies raw signal columns
- engineered signals use any non-`raw` quantity, for example `disp`, `ang_disp`, `vel`, `acc`
- `transform_chain` contains ordered transform ids
- `calibration_ref` identifies the sensor calibration used to derive a signal

Recommended quantity vocabulary:
- `raw`
- `disp`
- `ang_disp`
- `vel`
- `ang_vel`
- `acc`
- `ang_acc`
- `force`
- `pressure`
- `temperature`

### 7.8 `qc`

Purpose:
- records quality-control facts and warnings

Optional fields:
- `warnings`: array
- `time`: object
- `firmware_stats`: object

Suggested `time` fields:
- `monotonic`: boolean
- `repaired`: boolean

No fixed vocabulary is required for `warnings` in v0.1.

### 7.9 `provenance`

Purpose:
- records optional source and generation information

Optional fields:
- `logger_family`
- `firmware_version`
- `metadata_generated_at`
- `generator`

## 8. Minimum valid implementation

A minimum valid JSON sidecar MUST include:

- `contract.name`
- `contract.version`
- at least one stream in `streams`
- one `columns` entry for every CSV column
- one time column entry with `class: "time"` and `unit: "s"`

No sensor, transform, QC, or provenance metadata is required for minimum validity.

## 9. Formal validation rules

The validation model has two layers:

- structural validation of the JSON sidecar
- cross-file validation of the CSV against the sidecar

### 9.1 Structural validation

A sidecar is structurally valid if all of the following hold:

1. The JSON parses to an object.
2. `contract` exists and is an object.
3. `contract.name` exists and is a string.
4. `contract.version` exists and is a string.
5. `streams` exists, is an object, and is non-empty.
6. Every stream entry is an object.
7. Every stream entry contains `type`, `time_col`, and `time_unit`.
8. Every stream `type` is either `uniform` or `intermittent`.
9. Every stream `time_unit` is exactly `s`.
10. `columns` exists and is an object.
11. Every column entry is an object.
12. Every column entry contains `class` and `dtype`.
13. Every `class` value is one of `time`, `signal`, `index`, `event_flag`, `qc_flag`.
14. Every `time` column entry contains `stream` and `unit`.
15. Every `signal` column entry contains `stream`, `quantity`, and `unit`.
16. If present, `transform_chain` MUST be an array of strings.
17. If present, `source_columns` MUST be an array of strings.
18. If present, `calibration_ref` MUST be a string.
19. If present, `sensors` MUST be an object.
20. If present, `transforms` MUST be an object.

### 9.2 Cross-file validation

A file pair is cross-file valid if all of the following hold:

1. The CSV parses successfully.
2. The CSV contains a header row.
3. CSV header strings are unique.
4. Every CSV column name appears as an exact key in `columns`.
5. Every `columns` key appears as a CSV header.
6. Every `columns[*].stream` reference resolves to an entry in `streams`.
7. Every `streams[*].time_col` exists in the CSV.
8. Every `streams[*].time_col` resolves to a `columns` entry with `class: "time"`.
9. Every time column is numeric.
10. Every time column contains only finite values.
11. Every time column is monotonic non-decreasing.
12. Every time column uses seconds from session start.
13. Every `signal` column is parseable as numeric or nullable numeric.
14. If `data_file.row_count` is present, it matches the number of CSV data rows.
15. If `data_file.sha256` is present, it matches the CSV file content.

### 9.3 Conditional validation

These rules apply only when the relevant metadata is present:

1. If `streams[*].type` is `uniform` and `sample_rate_hz` is present, it MUST be finite and greater than zero.
2. If `streams[*].type` is `uniform` and `jitter_frac` is present, it MUST be finite and greater than or equal to zero.
3. If `streams[*].type` is `intermittent`, `sample_rate_hz` SHOULD be omitted.
4. If `streams[*].type` is `intermittent`, `jitter_frac` SHOULD be omitted.
5. If a signal column has `calibration_ref`, that sensor id MUST exist in `sensors`.
6. If a sensor defines `raw_unit`, any signal column with `quantity: "raw"` for that sensor SHOULD use that unit.
7. If a sensor defines calibration, `calibration.input_unit` and `calibration.output_unit` SHOULD be present.
8. If `transforms` is present and a signal column references transform ids, those ids SHOULD resolve in `transforms`.
9. If a transform has `type: "lut"` and `lut` is present, the LUT MUST contain at least two points.
10. If a transform has a LUT, its LUT `input` values MUST be strictly increasing.
11. If a signal column references a non-empty `transform_chain` and the corresponding transforms resolve, transform-unit continuity SHOULD hold across the chain.

## 10. Recommended warnings

The following conditions SHOULD produce warnings rather than hard failure in v0.1:

- missing `session.session_id`
- missing `session.started_at_local`
- first time sample not near zero
- unresolved transform ids
- missing `source_columns` on engineered signals
- missing `qc` section
- missing `provenance` section

## 11. Minimal example

Standalone example file:

- `MTB_Logger_CSV_JSON_Interchange_Example_Minimal_v0_1.json`

Example CSV:

```csv
time_s,rear_shock_raw [counts]
0.000,1540
0.002,1542
0.004,1541
```

Example sidecar:

```json
{
  "contract": {
    "name": "mtb_logger_timeseries",
    "version": "0.1.0"
  },
  "session": {
    "session_id": "example_minimal"
  },
  "streams": {
    "primary": {
      "type": "uniform",
      "time_col": "time_s",
      "time_unit": "s"
    }
  },
  "columns": {
    "time_s": {
      "class": "time",
      "dtype": "float64",
      "stream": "primary",
      "unit": "s"
    },
    "rear_shock_raw [counts]": {
      "class": "signal",
      "dtype": "float64",
      "stream": "primary",
      "quantity": "raw",
      "unit": "counts"
    }
  }
}
```

## 12. Extensive example

Standalone example file:

- `MTB_Logger_CSV_JSON_Interchange_Example_Extensive_v0_1.json`

Example CSV:

```csv
time_s,rear_shock_raw [counts],rear_shock_sensor_travel [deg],rear_wheel_travel [mm],mark
0.000,1540,12.1,24.8,0
0.002,1542,12.3,25.2,0
0.004,1541,12.2,25.0,1
```

The extensive example demonstrates:

- a reusable sensor calibration block
- a transform registry with LUT contents
- a calibrated angular-displacement signal
- a transformed wheel-displacement signal
- optional QC and provenance metadata

## 13. Evolution guidance

Backward-compatible changes include:

- adding optional top-level fields
- adding optional per-column fields
- adding optional sensor metadata
- adding optional transform metadata
- expanding quantity vocabularies

Breaking changes include:

- changing the meaning of existing required fields
- changing time units from seconds
- changing column-key matching away from exact CSV headers
- removing required fields

## 14. Related files

This proposal is accompanied by:

- `MTB_Logger_CSV_JSON_Interchange_Contract_v0_1.schema.json`
- `MTB_Logger_CSV_JSON_Interchange_Example_Minimal_v0_1.json`
- `MTB_Logger_CSV_JSON_Interchange_Example_Extensive_v0_1.json`
