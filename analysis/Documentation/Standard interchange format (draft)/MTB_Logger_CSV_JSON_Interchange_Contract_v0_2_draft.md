# MTB Logger CSV + JSON Interchange Contract

Version: v0.2 draft
Status: Proposal
Scope: Common interchange contract for MTB logger session outputs

## 1. Purpose

This document proposes a simple interchange contract for mountain bike data logger outputs using:

- one CSV file for time-series samples
- one JSON log metadata file for semantics, calibration, transforms, quality-control information, and provenance

The goal is to make downstream analysis tooling independent of logger-specific knowledge. A consumer should be able to interpret the CSV using only the log metadata JSON and the contract defined here.

## 2. Design goals

- Keep the minimum valid implementation as small as possible.
- Keep semantic meaning outside the CSV header naming convention.
- Support both headered and headerless CSV files.
- Make time handling explicit and uniform.
- Separate calibration from later semantic transformations.
- Allow richer provenance when producers care to provide it.
- Allow consumers to ignore metadata sections they do not need.

## 3. Conformance language

The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY in this document are to be interpreted as normative requirements.

## 3.1 Naming note

Earlier drafts and some code paths used the term `sidecar` for this JSON file.
This described the file relationship rather than its function. The preferred
user-facing term is now **log metadata**.

The `contract.sidecar_kind` field is retained in v0.2 for compatibility. A
future breaking revision may rename it to `log_metadata_kind`.

## 4. File pair

A session consists of a pair of files sharing a common base name.

Example:

- `2026-02-19_08-35-11.csv`
- `2026-02-19_08-35-11.json`

The CSV contains samples.
The JSON contains metadata.

The preferred producer-generated form is session log metadata: a JSON file that
shares a base name with one specific CSV file.

Consumers MAY also support generic log metadata. Generic log metadata is a reusable
metadata template selected by local policy or by the user when no matching
session log metadata is available. Generic log metadata is useful for existing loggers
that do not yet emit per-log sidecars.

### 4.1 Log Metadata Selection

This contract defines the structure and meaning of a log metadata document. It
does not require one universal discovery or storage policy for generic log
metadata.

Recommended consumer selection order:

1. Use an explicitly selected session log metadata file, if supplied by the user or caller.
2. Otherwise, use same-stem session log metadata beside the CSV, if present.
3. Otherwise, use an explicitly selected generic log metadata file, if supplied by run-level ingestion configuration.
4. Otherwise, consumers MAY search configured generic log metadata directories or file lists.
5. If more than one generic candidate is available, non-interactive consumers SHOULD fail or ask the user to choose rather than silently selecting the first candidate.
6. If no log metadata is available, consumers MAY fall back to legacy header parsing or other local heuristics.

Generic log metadata selection is normally an ingestion/run concern because it
must match the concrete logger output format for the CSV being loaded. A
preprocessing profile SHOULD NOT own a generic log metadata path; reusable
analysis presets can outlive, and be reused across, several logger output
formats. Notebooks, CLIs, or other run-level orchestration layers should pass
generic log metadata paths explicitly when they are needed.

## 5. Core principles

- The CSV is the authoritative source of sampled values.
- The JSON is the authoritative source of semantic interpretation.
- `columns` metadata is keyed by metadata-defined column ids, not by CSV headers.
- Each column definition contains an explicit CSV locator.
- Each stream has exactly one canonical time column.
- Time columns declare an explicit encoding so consumers can derive a canonical elapsed-time axis.
- Session log metadata describes one concrete CSV and should cover it strictly.
- Generic log metadata describes a reusable binding template and may cover only a subset of a CSV.
- The minimal valid JSON should be easy to produce even for simple loggers.

## 6. Top-level JSON object

The JSON log metadata file is a single object with the following top-level keys.

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

Optional fields:
- `sidecar_kind`: string

Constraints:
- producers MUST set `name`
- producers MUST set `version`
- consumers MUST reject documents where either field is missing or not a string
- if present, `sidecar_kind` MUST be one of `session` or `generic`
- if omitted, `sidecar_kind` SHOULD be interpreted as `session` for same-stem sidecars
- consumers MAY treat an explicitly user-selected fallback sidecar as `generic` by local policy

Recommended values:
- `name`: `mtb_logger_timeseries`
- `version`: `0.2.0`
- `sidecar_kind`: `session` for logger-emitted same-stem log metadata, `generic` for reusable fallback log metadata

### 7.2 `data_file`

Purpose:
- describes the associated CSV file and how it should be parsed

Optional fields:
- `path`: string
- `sha256`: string
- `delimiter`: string
- `header`: boolean
- `row_count`: integer

Constraints:
- if present, `row_count` MUST be a non-negative integer
- if present, `delimiter` SHOULD be a single-character string
- if present, `header` declares whether the CSV contains a header row
- if omitted, consumers MAY infer header presence using local policy, but producers SHOULD set it when practical

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
- when `session.started_at_local` is present, it provides the preferred real-time anchor for elapsed or local time encodings
- when a stream uses local time-of-day encoding, `session.started_at_local` or equivalent date/timezone metadata is required for unambiguous real-time reconstruction

### 7.4 `streams`

Purpose:
- declares each timebase present in the CSV

Shape:
- object keyed by stream id

Required per stream:
- `type`
- `time_column`
- `time_unit`

Optional per stream:
- `time_encoding`
- `time_format`
- `time_anchor`
- `sample_rate_hz`
- `jitter_frac`
- `notes`

Constraints:
- `type` MUST be one of `uniform` or `intermittent`
- `time_column` MUST be a string naming a column id present in `columns`
- `time_encoding`, if present, MUST be one of `elapsed_s`, `epoch_ms`, or `local_time`
- if `time_encoding` is omitted and `time_unit` is `s`, consumers MAY interpret the stream as `elapsed_s`
- producers SHOULD provide `time_encoding`
- `elapsed_s` streams MUST use `time_unit: "s"`
- `epoch_ms` streams MUST use `time_unit: "ms"`
- `local_time` streams MUST use `time_unit: "time_of_day"`
- `local_time` streams SHOULD provide `time_format`
- `local_time` streams SHOULD use `time_format: "HH:MM:SS.mmm"` when matching current BODAQS firmware output
- `local_time` streams MUST be anchored by `session.started_at_local` or equivalent session date and timezone metadata
- for `uniform` streams, `sample_rate_hz` MAY be provided
- for `uniform` streams, `jitter_frac` MAY be provided
- for `intermittent` streams, `sample_rate_hz` SHOULD be omitted
- for `intermittent` streams, `jitter_frac` SHOULD be omitted

Time encoding interpretation:

- `elapsed_s`: numeric seconds from session start
- `epoch_ms`: numeric milliseconds since the Unix epoch in UTC
- `local_time`: local time-of-day text anchored by session date and timezone metadata

Consumers SHOULD derive a canonical elapsed-time axis during preprocessing.

For `local_time`, consumers MUST combine each time-of-day value with the session
date and timezone. If the local time-of-day decreases relative to the previous
sample, consumers MUST treat it as a midnight rollover and advance the local
date by one day. Producers SHOULD avoid `local_time` for logs longer than 24
hours unless they provide additional date disambiguation metadata.

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
- defines the semantics of CSV columns

Shape:
- object keyed by metadata-defined column id

Session sidecar rule:
- every physical CSV column MUST be represented exactly once in `columns`

Generic sidecar rule:
- `columns` MAY represent only the subset of CSV columns the generic sidecar knows how to interpret
- consumers MUST NOT infer semantics for unknown CSV columns once a generic sidecar has been selected
- consumers SHOULD warn and skip unknown CSV columns
- consumers SHOULD warn when an optional generic-sidecar column is not present in the CSV
- consumers MUST fail when a required generic-sidecar column is not present in the CSV

Supported `class` values:
- `time`
- `signal`
- `index`
- `event_flag`
- `qc_flag`

Required for every column entry:
- `csv_ref`
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
- `end`
- `domain`
- `source_columns`
- `calibration_ref`
- `transform_chain`
- `notes`

Optional fields for any column entry:
- `required`: boolean

Column requiredness:
- in a session sidecar, every column entry is required
- in a generic sidecar, time columns are required
- in a generic sidecar, non-time columns default to optional unless `required: true`
- `required: false` in a session sidecar has no effect on strict session-sidecar coverage rules

#### 7.7.1 `csv_ref`

Purpose:
- locates the physical column in the CSV

Supported forms:

By header:

```json
{ "by": "header", "header": "time_s" }
```

By index:

```json
{ "by": "index", "index": 0 }
```

Constraints:
- `by` MUST be one of `header` or `index`
- if `by` is `header`, `header` MUST be present and MUST be an exact CSV header string
- if `by` is `index`, `index` MUST be a zero-based integer
- if `data_file.header` is `false`, `csv_ref.by` MUST be `index`

Interpretation rules:
- `quantity: "raw"` identifies raw signal columns
- engineered signals use any non-`raw` quantity, for example `disp`, `ang_disp`, `vel`, `acc`
- `end`, when present, identifies front/rear bike location and SHOULD be one of `front` or `rear`
- for front/rear suspension and wheel signals, `end` is used for bike-level
  semantic matching; `sensor` identifies only the logger/source sensor when
  supplied
- `transform_chain` contains ordered transform ids
- `calibration_ref` identifies the sensor calibration used to derive a signal
- `source_columns` contains column ids, not CSV headers

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

No fixed vocabulary is required for `warnings` in v0.2.

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
- one time column entry with `class: "time"`
- a supported time encoding/unit pair for every stream

No sensor, transform, QC, or provenance metadata is required for minimum validity.

For a session sidecar, minimum validity also requires that every physical CSV
column is represented by exactly one `columns` entry during cross-file
validation.

For a generic sidecar, minimum validity requires only that the selected CSV
contains the required time column and any non-time columns explicitly marked
`required: true`. Missing optional columns produce warnings, not failure.
Unknown CSV columns are skipped with warnings and are not interpreted by header
parsing.

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
7. Every stream entry contains `type`, `time_column`, and `time_unit`.
8. Every stream `type` is either `uniform` or `intermittent`.
9. Every stream `time_unit` is compatible with its `time_encoding`.
10. `columns` exists and is an object.
11. Every column entry is an object.
12. Every column entry contains `csv_ref`, `class`, and `dtype`.
13. Every `class` value is one of `time`, `signal`, `index`, `event_flag`, `qc_flag`.
14. Every `csv_ref.by` value is one of `header` or `index`.
15. Every `csv_ref.by == "header"` entry contains `header`.
16. Every `csv_ref.by == "index"` entry contains `index`.
17. Every `time` column entry contains `stream` and `unit`.
18. Every `signal` column entry contains `stream`, `quantity`, and `unit`.
19. If present, `transform_chain` MUST be an array of strings.
20. If present, `source_columns` MUST be an array of strings.
21. If present, `calibration_ref` MUST be a string.
22. If present, `required` MUST be a boolean.
23. If present, `sensors` MUST be an object.
24. If present, `transforms` MUST be an object.

### 9.2 Cross-file validation

A session sidecar and CSV file pair is cross-file valid if all of the following hold:

1. The CSV parses successfully.
2. If `data_file.header` is `true`, the CSV contains a header row.
3. If `data_file.header` is `false`, the CSV is parsed without a header row.
4. If the CSV has a header row, CSV header strings are unique.
5. Every physical CSV column is referenced exactly once by a `columns[*].csv_ref`.
6. Every `columns[*].stream` reference resolves to an entry in `streams`.
7. Every `streams[*].time_column` resolves to an entry in `columns`.
8. Every `streams[*].time_column` resolves to a column entry with `class: "time"`.
9. Every `csv_ref.by == "header"` locator resolves to an exact CSV header string.
10. Every `csv_ref.by == "index"` locator resolves to a valid zero-based CSV column index.
11. Every time column's `unit` matches the resolved `time_unit` for its stream.
12. Every time column value parses according to its stream's `time_encoding`.
13. Every numeric time column contains only finite values.
14. Every derived elapsed-time axis is monotonic non-decreasing.
15. Every stream's time encoding is sufficient to derive elapsed time within the session.
16. Every `signal` column is parseable as numeric or nullable numeric.
17. If `data_file.row_count` is present, it matches the number of CSV data rows.
18. If `data_file.sha256` is present, it matches the CSV file content.

### 9.2.1 Generic sidecar cross-file validation

A generic sidecar selected for a CSV is cross-file valid if all of the following hold:

1. The CSV parses successfully.
2. If `data_file.header` is `true`, the CSV contains a header row.
3. If `data_file.header` is `false`, the CSV is parsed without a header row.
4. If the CSV has a header row, CSV header strings are unique.
5. Every required column locator resolves to exactly one physical CSV column.
6. Every `streams[*].time_column` resolves to a required column entry with `class: "time"`.
7. Every resolved time column's `unit` matches the resolved `time_unit` for its stream.
8. Every resolved time column value parses according to its stream's `time_encoding`.
9. Every numeric time column contains only finite values.
10. Every derived elapsed-time axis is monotonic non-decreasing.
11. Every stream's time encoding is sufficient to derive elapsed time within the session.
12. Every resolved `signal` column is parseable as numeric or nullable numeric.
13. Every optional column locator that does not resolve produces a warning.
14. Every physical CSV column not resolved by the generic sidecar produces a warning and is skipped.

When a generic sidecar has been selected, consumers MUST NOT fall back to header
parsing for unresolved CSV columns. Header parsing is permitted only when no
session sidecar is found and no generic sidecar is selected.

### 9.3 Conditional validation

These rules apply only when the relevant metadata is present:

1. If `streams[*].type` is `uniform` and `sample_rate_hz` is present, it MUST be finite and greater than zero.
2. If `streams[*].type` is `uniform` and `jitter_frac` is present, it MUST be finite and greater than or equal to zero.
3. If `streams[*].type` is `intermittent`, `sample_rate_hz` SHOULD be omitted.
4. If `streams[*].type` is `intermittent`, `jitter_frac` SHOULD be omitted.
5. If a signal column has `calibration_ref`, that sensor id MUST exist in `sensors`.
6. If a signal column lists `source_columns`, every source id SHOULD resolve in `columns`.
7. If a sensor defines `raw_unit`, any signal column with `quantity: "raw"` for that sensor SHOULD use that unit.
8. If a sensor defines calibration, `calibration.input_unit` and `calibration.output_unit` SHOULD be present.
9. If `transforms` is present and a signal column references transform ids, those ids SHOULD resolve in `transforms`.
10. If a transform has `type: "lut"` and `lut` is present, the LUT MUST contain at least two points.
11. If a transform has a LUT, its LUT `input` values MUST be strictly increasing.
12. If a signal column references a non-empty `transform_chain` and the corresponding transforms resolve, transform-unit continuity SHOULD hold across the chain.
13. If `data_file.header` is `false`, no column entry SHOULD use `csv_ref.by == "header"`.
14. If a stream uses `local_time`, `session.started_at_local` or equivalent date/timezone metadata MUST be present.

## 10. Recommended warnings

The following conditions SHOULD produce warnings rather than hard failure in v0.2:

- missing `session.session_id`
- missing `session.started_at_local` when real-time anchoring is desired
- missing `time_encoding`
- first elapsed-time sample not near zero
- unresolved transform ids
- unresolved `source_columns`
- missing `source_columns` on engineered signals
- missing optional generic-sidecar columns
- skipped unknown CSV columns when using a generic sidecar
- missing `qc` section
- missing `provenance` section

## 11. Minimal headed example

Standalone example file:

- `MTB_Logger_CSV_JSON_Interchange_Example_Minimal_Headed_v0_2.json`

Example CSV:

```csv
time_s,rear_shock_raw [counts]
0.000,1540
0.002,1542
0.004,1541
```

## 12. Minimal headerless example

Standalone example file:

- `MTB_Logger_CSV_JSON_Interchange_Example_Minimal_Headerless_v0_2.json`

Example CSV:

```csv
0.000,1540
0.002,1542
0.004,1541
```

## 13. Extensive headed example

Standalone example file:

- `MTB_Logger_CSV_JSON_Interchange_Example_Extensive_Headed_v0_2.json`

Example CSV:

```csv
sample_id,time_s,rear_shock_raw [counts],rear_shock_sensor_travel [deg],rear_wheel_travel [mm],mark
0,0.000,1540,12.1,24.8,0
1,0.002,1542,12.3,25.2,0
2,0.004,1541,12.2,25.0,1
```

The extensive example demonstrates:

- semantic column ids decoupled from CSV headers
- CSV binding by exact header text
- a reusable sensor calibration block
- a transform registry with LUT contents
- a calibrated angular-displacement signal
- a transformed wheel-displacement signal
- optional QC and provenance metadata

## 14. Evolution guidance

Backward-compatible changes include:

- adding optional top-level fields
- adding optional per-column fields
- adding optional sensor metadata
- adding optional transform metadata
- expanding quantity vocabularies

Breaking changes include:

- changing the meaning of existing required fields
- changing the meaning of existing time encoding/unit pairs
- changing `csv_ref` semantics
- removing required fields

## 15. Related files

This proposal is accompanied by:

- `MTB_Logger_CSV_JSON_Interchange_Contract_v0_2.schema.json`
- `MTB_Logger_CSV_JSON_Interchange_Example_Minimal_Headed_v0_2.json`
- `MTB_Logger_CSV_JSON_Interchange_Example_Minimal_Headerless_v0_2.json`
- `MTB_Logger_CSV_JSON_Interchange_Example_Extensive_Headed_v0_2.json`

Earlier v0.1 draft files are retained under:

- `archive/`
