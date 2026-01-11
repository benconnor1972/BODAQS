
# BODAQS event Schema Specification v0_1

## 1. Overview

The event schema defines how events are detected and analysed within the data logger's Python analysis framework.  
It describes:

- **Which signals** (disp/vel/acc) to analyse per sensor  
- **How to detect event triggers**
- **Optional secondary triggers** relative to the primary one  
- **Pre/post-conditions**
- **Debounce behaviour**
- **Window extraction for each event**
- **Metrics** to compute from extracted slices

## Signal resolution (registry-based)

The schema’s `signal` field is a **role**, not a literal dataframe column name. The detector resolves each role
to a concrete column (`signal_col`) using the session’s **signal registry** (`session["meta"]["signals"]`)
and the **Signal Naming & Units Specification (v0.2)**.

### Signal roles (schema-level)

Recommended role vocabulary:

- `disp`        : engineered displacement for the sensor (canonical; may be domain-injected upstream)
- `vel`         : engineered velocity (derived signal; preferred as its own column)
- `acc`         : engineered acceleration (derived signal; preferred as its own column)
- `disp_zeroed` : displacement with analysis-side zeroing applied (append-only; e.g. `_op_zeroed`)
- `disp_norm`   : dimensionless normalised displacement (unit `[1]`)

Notes:
- Domain disambiguation (e.g. `_dom_suspension`) is handled upstream by signal standardisation; the schema does not hardcode domain suffixes.
- The detector should not hardcode suffix conventions; it should resolve via `session["meta"]["signals"]`.

---

# 2. Top-Level Schema Structure

```yaml
version: "1.0"

naming:
  suffixes:
    disp: "_disp"
    vel: "_vel"
    acc: "_acc"

defaults:
  window:
    pre_s: 0.2
    post_s: 0.8
    align: trigger
  debounce_s: 0.2
```

---

# 3. Event Definition

Each event entry looks like:

```yaml
- id: rebounds
  label: "all rebound events"
  sensors: [rear_shock, front_shock]

  trigger: {...}

  secondary_triggers:
    - { ... }
    - { ... }

  preconditions: [...]
  postconditions: [...]

  debounce: {...}
  window: {...}

  metrics: [...]
  tags: [kinematics, rebound]
```

Per-sensor expansion occurs automatically.

---

# 4. Trigger Types and Parameters

## 4.1 `simple_threshold_crossing`

Detects rising/falling/either threshold crossings with hysteresis.

```yaml
trigger:
  id: "start"
  type: simple_threshold_crossing
  signal: vel
  value: 0.0
  dir: falling          # rising | falling | either
  hysteresis: 0.0
  distance_s: 0.015
  edge_ignore_s: 1.0
```

### Parameters

| Parameter | Type | Meaning |
|----------|------|---------|
| `signal` | str | `disp`, `vel`, `acc` |
| `value` | float | threshold |
| `dir` | str | rising/falling/either |
| `hysteresis` | float | re-arm band |
| `distance_s` | float | minimum time between peaks (SciPy-like) |
| `edge_ignore_s` | float | ignore edges of the dataset |

---

## 4.2 `phased_threshold_crossing`

Pattern-based detection of NEG → ZERO → POS (rising) or reversed (falling).

```yaml
trigger:
  id: phase_start
  type: phased_threshold_crossing
  signal: vel
  dir: falling

  value: 0.0

  search:
    min_delay_s: 0.0
    max_delay_s: 0.8
    smooth_ms: 20

  bands:
    neg:  {min: -5000, max: -0.1, dwell_samples: 1}
    zero: {min: -0.1, max: 0.1}
    pos:  {min: 0.1,  max: 5000, dwell_samples: 1}

  cross_samples: 1
```

### Parameters

#### Search window
| Key | Meaning |
|-----|---------|
| `min_delay_s` | Start searching this long after base trigger time |
| `max_delay_s` | Stop searching afterwards |
| `smooth_ms` | Optional moving-average smoothing |

#### Phase bands
Each band defines a value range and required dwell samples.

| Band | Parameters |
|------|------------|
| neg | {min, max, dwell_samples} |
| zero | {min, max, dwell_samples} |
| pos | {min, max, dwell_samples} |

#### Final phase
`cross_samples` defines minimum dwell in last band.

---

## 4.3 `secondary_triggers`

Each secondary trigger is its own trigger block:

```yaml
secondary_triggers:
  - id: rebound_end
    type: simple_threshold_crossing
    signal: vel
    value: 0
    dir: rising
    base_trigger: rebound_start
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
    debounce:
      gap_s: 0.15
      prefer_key: t0_index
      prefer_max: false
```

### Extra secondary-only fields

| Parameter | Meaning |
|----------|---------|
| `base_trigger` | Which trigger to anchor to |
| `search.*` | Optional windowing overrides |
| `debounce.*` | Per-secondary debounce |

---

# 5. Conditions

## 5.1 Preconditions / Postconditions

```yaml
preconditions:
  - within_s: [-0.005, 0.005]
    any_of:
      - { type: peak, signal: disp_norm, kind: max, cmp: ">=", value: 0.4 }
```

### Test types

| Type | Fields | Meaning |
|------|--------|---------|
| `range` | min, max | Segment must lie within range |
| `delta` | cmp, value | delta from t0 meets condition |
| `peak` | kind, cmp, value | peak/minimum meets threshold |

### Comparators

In condition clauses, use `cmp` (not `op`) for comparison operators to avoid ambiguity with signal `op_chain`
tokens (e.g. `_op_zeroed`).

Supported comparators: `>`, `>=`, `<`, `<=`, `==`, `!=`.
---

# 6. Debounce (per trigger)

```yaml
debounce:
  gap_s: 0.2
  prefer_key: trigger_strength
  prefer_abs: true
  prefer_max: true     # optional: pick max or min value
```

Effective behaviour:

- cluster candidates within `gap_s`
- score using `prefer_key`
- choose **max or min** according to `prefer_max`

---

# 7. Window

```yaml
window:
  pre_s: 0.2
  post_s: 0.8
  align: trigger   # or "start"
```

Defines the extraction window around t0.

---

# 8. Metrics

Metrics are computed *after* triggers and windows are resolved.

## 8.1 General metrics

### Integral
```yaml
- type: integral
  signal: vel
  abs: true
```

### Peak
```yaml
- type: peak
  signal: vel
  kind: min
  return_time: true
```

### Time above threshold
```yaml
- type: time_above
  signal: vel
  threshold: 0.3
```

---

## 8.2 Interval-based metrics

```yaml
- type: interval_stats
  signal: vel
  start_trigger: rebound_start
  end_trigger: rebound_end
  ops: [mean, max, min, delta, integral]
  smooth_ms: 20
  min_delay_s: 0.02
  polarity: neg_to_pos
  return_debug: true
```

### Supported operations
| op | meaning |
|----|---------|
| mean | average |
| max | maximum |
| min | minimum |
| peak | peak (polarity aware) |
| delta | last − first |
| integral | area under curve |
| time_above | time above threshold |

### Optional fields
| Field | Meaning |
|-------|---------|
| `smooth_ms` | smoothing before computing ops |
| `polarity` | affects `"peak"` behaviour |
| `min_delay_s` | discard intervals too short |
| `return_debug` | export start/end timestamps |

---



# End of Document
