# Sidecar Metadata Generation Task

Status: Deferred implementation task

This document captures the firmware work needed for BODAQS to emit a JSON
sidecar file alongside each CSV log. The sidecar is intended to provide signal
semantics for preprocessing and analysis without requiring logger-specific
knowledge in downstream tools.

The current interchange draft lives in:

`analysis/documentation/Standard interchange format (draft)/`

## 1. Goal

For each CSV log produced by the firmware, generate a sidecar JSON file from
the resolved runtime logger state.

The sidecar should describe:

- the CSV file layout
- the time column and its encoding
- the stream model
- each logged column's class, unit, and semantic meaning
- sensor calibration metadata where available
- selected transform ids where applicable
- basic provenance and firmware/runtime details

The sidecar should be generated at log start or log finalisation from the same
runtime state used to produce the CSV header. It should not be generated later
from the persisted config file alone.

## 2. Rationale

The persisted config is an important input, but it is not the complete truth
for a log file. The final CSV layout also depends on runtime state and resolved
behaviour, including:

- sensor mute state
- instantiated sensor types
- `include_raw`
- `output_mode`
- resolved transform selection
- generated CSV header order
- reserved logger columns such as `sample_id` and `mark`

The sidecar should therefore be treated as a resolved log manifest:

`saved config + runtime sensor state + selected transforms + final CSV header`

## 3. Existing Information That Appears Sufficient

The firmware already has enough runtime information for several sidecar fields:

- CSVs are comma-delimited and currently headered.
- `sample_id` is present and has stable meaning.
- `mark` is present and has stable meaning.
- The logger has one uniform primary stream at the configured sample rate.
- The firmware knows the exact final CSV header at log start.
- Raw sensor columns are identifiable as counts.
- Sensor names and sensor types are known after config load.
- Selected transform ids are known after transform resolution.
- Transform metadata includes ids, types, input units, and output units.

These fields should be generated from runtime state rather than rediscovered by
parsing the CSV after the fact.

## 4. Known Gaps To Address

### 4.1 Time metadata

The current interchange draft requires time columns to be numeric seconds from
session start. Current firmware writes either:

- `timestamp` as local time-of-day text, `HH:MM:SS.mmm`
- `timestamp_ms` as epoch milliseconds

Before implementation, update the interchange contract so it can describe
multiple explicit time encodings. A practical minimum would be:

- elapsed seconds from session start
- epoch milliseconds
- local time-of-day, anchored by session date and timezone

The preprocessing side can then derive a canonical elapsed-time axis where
needed, while the firmware can describe the time representation it actually
emits.

The contract should define how local time-of-day behaves across midnight.

### 4.2 Explicit semantic quantities

The firmware does not currently carry explicit signal quantities such as:

- `raw`
- `disp`
- `ang_disp`
- `force`
- `norm`

This is the largest metadata gap for deterministic sidecar generation.

Add explicit semantic fields to sensor instance configuration, or an equivalent
runtime metadata source, so the sidecar generator does not have to infer
meaning from sensor names, units, or CSV headers.

The exact field names are still open, but likely candidates include:

- `quantity`
- `domain`
- `role`

Examples:

- rear shock raw ADC counts: `quantity=raw`
- rear shock angular displacement: `quantity=ang_disp`
- rear wheel travel: `quantity=disp`

### 4.3 Sensor output descriptors

Each sensor class should be able to describe the columns it can emit after
configuration has been applied.

This should include, for each emitted column:

- stable semantic column id or enough data to generate one
- CSV header label
- column class
- dtype
- quantity
- unit
- source column relationship where applicable
- calibration reference where applicable
- transform chain where applicable

This should come from sensor runtime metadata, not from ad hoc parsing of CSV
header strings.

### 4.4 Calibration metadata

Current calibration fields are usable but mm-centric in naming, especially
`sensor_full_travel_mm`.

For sidecar generation, sensor classes should expose calibration metadata in a
unit-explicit form:

- calibration type
- input unit
- output unit
- zero count
- full count
- installed zero count
- full travel in output units
- invert flag where applicable

This may require sensor classes to carry slightly richer metadata than they do
today. In particular, firmware should not rely on a display `units_label` alone
to define calibration output units.

### 4.5 String-pot special cases

AS5600 string-pot sensors can involve wrapped counts, unwrapped counts,
linearised travel, and optional raw columns. The sidecar output should make
those distinctions explicit through the sensor output descriptors.

Do not assume the visible CSV column name is enough to determine whether a
column is wrapped raw counts, unwrapped counts, calibrated travel, or transformed
travel.

## 5. Proposed Firmware Work Items

1. Update the interchange contract to allow explicit time encodings beyond
   elapsed seconds.
2. Add a runtime sidecar writer that creates a JSON file next to the CSV log.
3. Generate the sidecar from resolved runtime state, not from config alone.
4. Add or expose sensor metadata needed for semantic column descriptors.
5. Extend sensor configuration, or an equivalent metadata source, with explicit
   semantic quantity/domain information.
6. Make calibration metadata unit-explicit in sensor runtime descriptors.
7. Include selected transform ids in engineered column metadata.
8. Optionally include full transform definitions where they are available and
   inexpensive to serialize.
9. Include basic provenance such as firmware version, logger family, and
   metadata generation time.
10. Add validation or debug logging that reports when a valid sidecar cannot be
    generated because required semantic metadata is missing.

## 6. Non-Goals For The First Implementation

- Do not require headerless CSV output from firmware.
- Do not require full LUT or polynomial payload serialization in the first pass.
- Do not make preprocessing depend on parsing human-readable CSV headers for
  semantics.
- Do not attempt to generate sidecars later from saved config files alone.
- Do not require all optional interchange fields to be populated.

## 7. Acceptance Criteria

A first implementation should be considered complete when:

- each new CSV log has a same-basename JSON sidecar
- the sidecar parses as valid JSON
- the sidecar identifies the CSV file and delimiter
- the sidecar declares one primary stream
- the sidecar describes the emitted time column and its encoding
- the sidecar describes `sample_id` and `mark`
- every emitted CSV column has a corresponding sidecar column descriptor
- raw sensor columns are identified as raw counts
- engineered sensor columns have explicit quantity and unit metadata
- selected transform ids are recorded for transformed columns
- calibration metadata is emitted where available
- missing required metadata produces a clear firmware log warning

## 8. Open Questions

- Should sidecar generation happen when the CSV header is written, when logging
  stops, or both?
- Should local time-of-day timestamps be allowed only when the sidecar includes
  a full session date and timezone?
- Should semantic quantity/domain fields live directly in `sensorN.*`
  configuration, or in a separate semantic profile?
- How should defaults be chosen for existing configs that lack semantic fields?
- Should semantic column ids be generated from sensor name and quantity, or
  stored explicitly?
- Should transform payloads be embedded in sidecars by default, or only the
  selected transform ids?
- What should the firmware do if a sidecar cannot be generated but CSV logging
  itself can continue?

