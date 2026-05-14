# BODAQS Event Schema Specification v0.1 (updated: segment role dicts)

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

# End of document
