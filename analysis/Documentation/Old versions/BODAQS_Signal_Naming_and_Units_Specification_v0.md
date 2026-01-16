## Signal naming & units spec (v0.2)

This project uses **column name conventions + a signal registry** to make units/kind/processing unambiguous and machine-parseable.

### 1) Column name grammar

A numeric signal column name is:

`<base><kind><domain><unit><ops>`

Where:

- **base**: required, snake_case (e.g. `rear_shock`, `accel_x`, `battery`)
- **kind**: optional suffix, one of:
  - *(default / engineered)*: no suffix
  - `_raw` : raw sensor/ADC domain (must include `[counts]`)
  - `_qc`  : quality-control / flags (unitless unless explicitly specified)
- **domain**: optional suffix, used when the same physical quantity exists in multiple frames/domains:
  - `_dom_sensor`, `_dom_wheel`, `_dom_bike`, `_dom_world` (extend as needed)
  - Omit when domain is unambiguous or encoded in the base name.
- **unit**: required for engineered & derived numeric signals, formatted exactly:
  - ` ␠[<unit>]` (single space before `[`)
  - Examples: `[mm]`, `[mm/s]`, `[V]`, `[deg/s]`, `[g]`
- **ops**: optional analysis-side processing operations, appended as:
  - `_op_<token1>_<token2>_...`
  - Tokens are lowercase identifiers (e.g. `zeroed`, `norm`, `filt`, `clip`).

#### Examples
Engineered (default kind):
- `rear_shock [mm]`
- `rear_shock [mm]_op_zeroed`
- `rear_shock [mm]_op_zeroed_norm`

Raw:
- `rear_shock_raw [counts]`
- `battery_raw [counts]`

QC:
- `rear_shock_qc`
- `rear_shock_qc_dropouts`

Domain disambiguation:
- `accel_x_dom_sensor [g]`
- `accel_x_dom_bike [g]`
- `rear_shock_dom_sensor [mm]`
- `rear_shock_dom_wheel [mm]`

Derived quantities should be separate engineered signals (preferred):
- `rear_shock_vel [mm/s]`
- `rear_shock_acc [mm/s^2]`

### 2) Mandatory rules

- **Engineered/derived numeric signals MUST include a unit** (` <space>[unit]`).
- **Raw numeric signals MUST**:
  - end with `_raw`
  - include unit `[counts]` (unless explicitly overridden by a documented raw unit)
- **QC signals MUST** be boolean-like (bool or 0/1), and are typically unitless.
- **Ops MUST represent analysis-side operations only.**
  - Ops do **not** imply anything about transforms performed on the logger.
- Prefer **append-only** processing: produce new columns for `_op_*` outputs rather than overwriting inputs.

### 3) Signal registry (Session.meta.signals)

`session['meta']['signals']` is a mapping: `{ column_name: SignalInfo }`.

**SignalInfo fields (v0.2):**
- `kind`: `"" | "raw" | "qc"`  (empty string means engineered default)
- `unit`: string or `None`
- `domain`: string or `None` (e.g. `"sensor"`, `"wheel"`, `"bike"`)
- `op_chain`: list of op tokens (analysis-side), possibly empty
- `source`: optional list of parent column names (recommended for derived/op outputs)
- `notes`: optional free-text

**Consistency requirements:**
- Every numeric column in `session['df']` MUST have a corresponding `signals` entry.
- For `kind == ""`, `unit` MUST be non-empty.
- For `kind == "raw"`, `unit` SHOULD be `"counts"`.
- For `kind == "qc"`, `unit` SHOULD be `None`.

### 4) Normalisation/standardisation pass

A single canonical function is responsible for:
1) Renaming legacy columns → canonical names
2) Building/updating `meta.signals`
3) Creating derived/op columns (append-only) and updating `signals` (`source`, `op_chain`)
4) Validating all rules above before downstream steps (segment extraction, metrics)
