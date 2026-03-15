# BODAQS Event Schema Specification v0.12 

This document specifies the YAML schema used by the BODAQS analysis pipeline to define event detection,
segmentation defaults, and metric extraction.

This update introduces **registry-first, no-fallback** segment role definitions (Option B):
`segment_defaults.roles` must be expressed in **dict form** with a `prefer` selector that is **sensor-relative**
(i.e., the sensor is bound from the event instance / anchor signal, not hard-coded in the schema).

---

## 1. Key concepts

### 1.1 Signals and the signal registry
The analysis pipeline maintains a canonical signal registry at:

- `session["meta"]["signals"]`

The registry maps **dataframe columns** → semantic metadata, including (at minimum):

- `sensor` (e.g. `rear_shock`, `front_shock`)
- `quantity` (e.g. `disp`, `vel`, `acc`, `raw`)
- `unit` (e.g. `mm`, `mm/s`, `mm/s^2`, `counts`)
- `kind` (e.g. `""` engineered, `raw`, `qc`)
- `op_chain` (list of operations/variants applied, e.g. `["zeroed"]`)

All downstream components must resolve signals **via the registry**. No suffix-guessing or fallback concatenation.

### 1.2 Events are expanded per sensor
An event definition can list multiple sensors. During event detection, each event is expanded into one row per sensor.
Event rows are expected to include an anchor signal column (commonly `signal_col`) that identifies the sensor for that
event instance.

---

## 2. Top-level YAML structure

Top-level keys:

- `specification`: schema specification version (string)
- `version`: schema file revision (string)
- `naming`: naming/suffix conventions (legacy; discouraged for role resolution)
- `defaults`: global defaults for triggers/windows/metrics
- `series`: named series definitions (optional)
- `events`: list of event definitions

---

## 3. Event definition

Each entry in `events` is an object with (common fields):

- `id` (string, stable key used in `events_df["schema_id"]`)
- `label` (string, human-readable)
- `sensors` (list[str], e.g. `["rear_shock", "front_shock"]`)
- `trigger` (definition of primary trigger)
- `preconditions` (optional constraints)
- `window` (time window defaults for detection)
- `metrics` (metric definitions)
- `tags` (optional)
- `segment_defaults` (defaults used by `extract_segments` / segment viewer)

---

## 4. segment_defaults

`segment_defaults` provides defaults used when extracting segments for events of a given schema id.

### 4.1 segment_defaults fields

- `anchor` (string): which timestamp field anchors the segment (commonly `trigger_time_s`)
- `window` (object): segment window, in seconds
  - `pre_s` (float)
  - `post_s` (float)
- `roles` (list[RoleDef]): **required in registry-first mode**

### 4.2 RoleDef (dict form)

Each entry in `segment_defaults.roles` MUST be a dict with:

- `role` (string): output role name in the segment bundle (e.g. `disp`, `vel`, `raw`)
- `prefer` (dict): registry selector constraints

`prefer` MUST include:

- `quantity` (string): one of `disp`, `vel`, `acc`, `raw`, ...

`prefer` MAY include:

- `unit` (string): e.g. `mm`, `mm/s`, `counts`
- `kind` (string): `""` (engineered), `raw`, `qc`
- `op_chain` (list[str]): operation/variant chain, e.g. `["zeroed"]`, `["norm"]`

Note: Operation tokens in op_chain are canonicalised (zeroed, norm, …).
Implementations MAY accept legacy tokens prefixed with op_ and normalize them internally, but schemas SHOULD use canonical tokens.

In v0.1.1+, `segment_defaults.roles` MUST be specified in dictionary form.

Each role entry MUST include a `prefer` block with at least:
- `quantity`
- `unit`

`sensor` MAY be omitted; 
- The sensor is bound from the **event instance** (via its anchor signal / `signal_col` and the registry).
- This avoids duplicating role lists per sensor and keeps schemas sensor-agnostic.

### 4.3 Resolution rules (Option B)

When extracting segments for a specific event row:

1. Determine the event sensor from the anchor signal column (e.g. `signal_col`) via `meta["signals"][signal_col]["sensor"]`.
2. For each RoleDef, resolve the dataframe column by matching registry entries on:
   - the event sensor (bound at runtime)
   - `prefer.quantity`
   - and any optional `prefer` fields (`unit`, `kind`, `op_chain`)
3. Resolution must be **deterministic**:
   - 0 matches → error (missing signal)
   - >1 matches → error (ambiguous signal)

String roles (e.g. `roles: ["disp", "vel"]`) are **not permitted** in registry-first mode.

### Normalised displacement (`disp_norm`)

`disp_norm` is a **role name**, not a physical quantity.

Semantics:
- `quantity`: `disp`
- `unit`: `"1"` (dimensionless)
- `op_chain`: typically `["zeroed", "norm"]`

Example role specification:

```yaml
- role: disp_norm
  prefer:
    quantity: disp
    unit: "1"
    op_chain: [zeroed, norm]

---

## 5. Example (segment_defaults.roles)

```yaml
segment_defaults:
  anchor: trigger_time_s
  window: { pre_s: 0.2, post_s: 0.8 }
  roles:
    - role: disp
      prefer: { quantity: disp, unit: mm, op_chain: [zeroed] }
    - role: vel
      prefer: { quantity: vel, unit: mm/s, op_chain: [zeroed] }
    - role: raw
      prefer: { quantity: raw, unit: counts, kind: raw }
```

---

## 6. Metric definitions

Metrics are defined under each event's `metrics` list.

### 6.1 Signal-role metrics

The existing waveform metrics operate on **roles** resolved from the registry-bound segment bundle:

- `peak`
- `interval_stats`

For these metric types:

- `signal` refers to a **role** such as `disp`, `vel`, `acc`, `disp_norm`
- `signal` must not refer to trigger metadata such as `t0_index`

### 6.2 Trigger-derived metrics: `trigger_delta`

`trigger_delta` computes a scalar difference between two resolved trigger anchors for the same event instance.

Definition:

```yaml
- type: trigger_delta
  start_trigger: <trigger id>
  end_trigger: <trigger id>
  quantity: seconds | samples
  id: <optional metric id>
  abs: <optional bool, default false>
  return_debug: <optional bool, default false>
```

Rules:

- `signal` MUST NOT be present
- `start_trigger` and `end_trigger` are required
- `quantity: seconds` computes `end_time_s - start_time_s`
- `quantity: samples` computes `end_idx - start_idx`
- if `abs: true`, the absolute value is returned

Trigger resolution uses the event table trigger fields:

- primary trigger:
  - time: `trigger_time_s`
  - index: `trigger_idx` (or legacy `t0_index` where present)
- named trigger ids:
  - time: `{trigger_id}_time_s`
  - index: `{trigger_id}_idx`

Example:

```yaml
metrics:
  - type: trigger_delta
    start_trigger: topout_start
    end_trigger: topout_end
    quantity: samples
    id: airtime_n
    return_debug: true
```

This metric type is intended for trigger/index/time-derived quantities and should be preferred over treating
trigger metadata as a fake signal role.

---

## Appendix: Sensor-Bound Signal Resolution Model

### Overview

Event detection, segmentation, and metrics in BODAQS operate on **roles** (e.g. `disp`, `vel`, `disp_norm`) rather than directly referencing DataFrame column names.

This appendix defines the **sensor-bound resolution model** used to map schema roles to concrete signal columns in the analysis DataFrame.

---

### Core Design Principle

**Signal roles are resolved relative to the sensor that triggered the event.**

In other words:

> The meaning of a role like `disp` or `disp_norm` is *contextual*, not global.

This avoids ambiguity when multiple sensors produce signals with identical physical meaning (e.g. front and rear suspension displacement).

---

### Event Sensor Binding

Each detected event row MUST identify a *primary signal column* (`signal_col`) that caused the trigger.

From this column, the system derives the **event sensor context** using the signal registry:

```text
event sensor := meta.signals[signal_col].sensor
```

All subsequent role resolution for that event is performed **within this sensor context**.

---

### Role Resolution Process

For each event row and each requested role:

1. **Determine the bound sensor**

   * If the role explicitly specifies `prefer.sensor`, that value is used.
   * Otherwise, the sensor is inherited from the event’s primary trigger signal.

2. **Match against the signal registry**

   * Candidate signals are filtered by:

     * `sensor`
     * `quantity`
     * `unit`
     * `op_chain` (if specified)
     * `kind` (engineered vs raw vs qc)

3. **Require deterministic resolution**

   * Exactly one signal must match.
   * Zero matches or multiple matches are treated as errors.

4. **Bind role → column**

   * The resolved column name is recorded for that event row.

This resolution is performed **per event row**, allowing different events in the same session to bind to different sensors without ambiguity.

---

### Role Specification Requirements

To ensure deterministic resolution, roles defined in `segment_defaults.roles` MUST be specified in dictionary form and MUST include:

* `prefer.quantity`
* `prefer.unit`

Example:

```yaml
- role: disp
  prefer:
    quantity: disp
    unit: mm
    op_chain: [zeroed]
```

The following fields are OPTIONAL:

* `prefer.sensor`
  (omitted when the role should bind to the event’s sensor)
* `prefer.op_chain`
  (may be empty if no specific operations are required)

---

### Derived and Normalised Signals

Some role names (e.g. `disp_norm`) represent **derived views** of an underlying physical quantity.

In these cases:

* `role` is a semantic label
* `prefer.quantity` identifies the physical quantity (e.g. `disp`)
* `prefer.unit` identifies the resulting unit (e.g. `"1"` for dimensionless)
* `prefer.op_chain` encodes the transformation sequence

Example:

```yaml
- role: disp_norm
  prefer:
    quantity: disp
    unit: "1"
    op_chain: [zeroed, norm]
```

This model ensures that derived signals remain traceable to their physical origin while remaining easy to reference in schemas.

---

### Registry-First, No-Fallback Policy

Role resolution is **registry-only**:

* No string concatenation
* No suffix guessing
* No implicit fallbacks

If a role cannot be resolved deterministically via the signal registry, the system MUST raise a validation error.

This ensures:

* Early failure for mis-specified schemas
* Predictable behavior across sessions
* Clear contracts between preprocessing, schemas, and analysis stages

---

### Rationale

This sensor-bound resolution model:

* Eliminates ambiguity in multi-sensor datasets
* Allows a single schema to apply across sensors
* Decouples schemas from column naming conventions
* Scales naturally to additional sensors and derived signals

It is a foundational design choice that underpins robust, contract-driven analysis in BODAQS.

---

# End of document
