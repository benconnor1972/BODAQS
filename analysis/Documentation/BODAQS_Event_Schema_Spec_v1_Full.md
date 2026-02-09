# BODAQS Event Schema Specification v1.0 — Full Document

# BODAQS Event Schema Specification — Section 1
## Conceptual Model & Dataflow

### 1.1 Fundamental Objects

Signals, registry entries, roles, event instances, and SegmentBundles form the core abstractions.

Signals are numeric time series in session["df"].  
Registry entries provide semantic metadata.  
Roles are schema-level semantic references resolved dynamically.  
Event instances are per-sensor detected occurrences.  
SegmentBundles hold aligned waveform slices.

---

### 1.2 Signal Lifecycle

raw → canonicalized → registry → detection → segmentation → metrics

All schema logic operates exclusively on registry-resolved roles.

---

### 1.3 Registry-First Semantics

Resolution matches sensor, quantity, unit, kind, and op_chain.  
No suffix guessing or fallback is permitted.

Derived signals retain transformation lineage via op_chain.

---

### 1.4 Event Expansion

Each event definition expands into one instance per sensor at runtime.

Schemas remain sensor-agnostic.

---

### 1.5 Trigger Pipeline

1. Primary trigger detection  
2. Secondary trigger resolution  
3. Debounce clustering  
4. Condition filtering  
5. Event emission  

---

### 1.6 Determinism & Failure

Ambiguity or missing semantics produce hard failures.

The system guarantees deterministic, reproducible metrics.

---


---

# BODAQS Event Schema Specification — Section 2
## Formal Event Schema Grammar

### 2.1 EventDef

id: string  
label: string  
sensors: list[string]  
trigger: TriggerDef  
secondary_triggers: list[TriggerDef]  
preconditions: list[ConditionBlock]  
postconditions: list[ConditionBlock]  
window: WindowDef  
metrics: list[MetricDef]  
tags: list[string]  
segment_defaults: SegmentDefaults  

Each EventDef expands per sensor.

---

### 2.2 TriggerDef (common fields)

type: string  
signal: role  
dir: rising | falling | either  
search: SearchWindow  
distance_s: float  
edge_ignore_s: float  
debounce: DebounceSpec  

---

### 2.3 SearchWindow

min_delay_s: float  
max_delay_s: float  
direction: forward | backward  

---

### 2.4 DebounceSpec

gap_s: float  
prefer_key: string  
prefer_abs: bool  
prefer_max: bool  

---

### 2.5 ConditionBlock

within_s: [float, float]  
any_of: list[TestDef]  
all_of: list[TestDef]  

---

### 2.6 MetricDef

type: peak | interval_stats  
signal: role  

Additional fields depend on metric type.

---


---

# BODAQS Event Schema Specification — Section 3
## Trigger Engine: simple_threshold_crossing

This section defines the semantics of the simple_threshold_crossing trigger engine, including state behavior,
search window interaction, hysteresis, spacing, and debounce effects.

---

## 3.1 Purpose

The simple_threshold_crossing trigger detects directional crossings of a scalar threshold on a chosen signal role.

Typical uses:
- zero-crossing of velocity
- threshold exceedance of acceleration
- onset detection

---

## 3.2 Formal Definition

TriggerDef fields:

type: simple_threshold_crossing  
signal: role  
value: float  
dir: rising | falling | either (default: either)  
hysteresis: float (default: 0)  
distance_s: float | null  
edge_ignore_s: float | null  
search: SearchWindow | null  
debounce: DebounceSpec | null  

---

## 3.3 Armed State Machine

The trigger operates using an armed/disarmed mechanism to prevent chatter.

### Rising detection:

A rising crossing occurs when:

y[i-1] < value  
y[i]   ≥ value  

After firing, rising detection is disarmed until:

y ≤ value - hysteresis

### Falling detection:

A falling crossing occurs when:

y[i-1] > value  
y[i]   ≤ value  

After firing, falling detection is disarmed until:

y ≥ value + hysteresis

---

## 3.4 Direction Semantics

dir = rising  
→ only rising crossings detected  

dir = falling  
→ only falling crossings detected  

dir = either  
→ both types detected  

Both rising and falling have independent armed states.

---

## 3.5 Search Window Interaction

If search is absent and base trigger is undefined:

→ full signal range is scanned

If search is present:

start_time = base_time + min_delay_s  
end_time   = base_time + max_delay_s  

Indices are computed via timebase lookup.

Search windows apply equally to primary and secondary triggers.

---

## 3.6 Spacing (distance_s)

distance_s enforces minimum spacing between crossings in time.

Converted to samples:

distance_samples = round(distance_s / dt)

Crossings closer than this spacing are all recorded initially;
final filtering occurs during debounce.

---

## 3.7 Edge Ignore

edge_ignore_s defines a forbidden region near signal boundaries.

Converted to samples:

edge_samples = round(edge_ignore_s / dt)

Triggers within this region are discarded.

---

## 3.8 Output Candidate Structure

Each detected crossing yields:

t0_index  
t0_time  
trigger_value  
trigger_strength  

Where:

trigger_strength = |y[i] - y[i-1]|

Optional displacement value may also be attached when available.

---

## 3.9 Interaction with Debounce

simple_threshold_crossing produces raw candidate crossings.

Final selection occurs only after:

• spacing clustering  
• debounce scoring  

This allows flexible post-processing.

---

## 3.10 Worked Example

Given:

value = 0  
dir = rising  
hysteresis = 0  

Velocity signal:

Index: 0 1 2 3 4  
Value: -3 -1 1 3 2  

Crossing occurs at index 2.

If hysteresis = 1:

Re-arm occurs only once signal drops below -1.

---

## 3.11 Common Pitfalls

• forgetting hysteresis on noisy signals  
• large debounce gaps collapsing many crossings  
• inverted dir configuration  
• overly wide search windows  

---

## 3.12 Design Guarantees

• deterministic detection  
• monotonic time ordering  
• registry-resolved signal usage  
• no implicit filtering  

---

End of Section 3


---

# BODAQS Event Schema Specification — Section 4
## Trigger Engine: local_extrema

This section defines the semantics of the local_extrema trigger engine, which detects local maxima or minima
(peaks or troughs) in a signal role, using SciPy where available and a deterministic fallback algorithm otherwise.

---

## 4.1 Purpose

The local_extrema trigger identifies significant turning points in a signal.

Typical uses:
- suspension bottom-out (max displacement)
- top-out (min displacement)
- impact spikes (acceleration peaks)
- oscillation analysis

---

## 4.2 Formal Definition

TriggerDef fields:

type: local_extrema  
signal: role  
kind: max | min  
prominence: float | null  
distance_s: float | null  
edge_ignore_s: float | null  
search: SearchWindow | null  
debounce: DebounceSpec | null  

---

## 4.3 Concept of an Extremum

A sample i is a local maximum if:

y[i-1] < y[i] ≥ y[i+1]

A sample i is a local minimum if:

y[i-1] > y[i] ≤ y[i+1]

Flat plateaus are resolved by selecting the earliest qualifying index.

---

## 4.4 SciPy-Based Detection (Preferred)

When SciPy is available, peaks are detected using:

scipy.signal.find_peaks()

For maxima:

find_peaks(y, prominence=..., distance=...)

For minima:

find_peaks(-y, prominence=..., distance=...)

### Prominence

Prominence defines the minimum vertical separation between the peak and its surrounding baseline.

Higher prominence filters small oscillations.

---

### Distance

distance_s is converted to samples:

distance_samples = round(distance_s / dt)

Peaks closer than this spacing are suppressed by SciPy directly.

---

## 4.5 Fallback Detection Algorithm

When SciPy is unavailable:

1. Iterate through signal indices
2. Identify sign changes in slope
3. Select points matching extremum criteria
4. Apply manual distance filtering

This produces deterministic behavior but weaker noise rejection than prominence.

---

## 4.6 Search Window Interaction

If search is absent:

→ entire signal scanned

If search present:

start_time = base_time + min_delay_s  
end_time   = base_time + max_delay_s  

Only samples within this window are considered.

---

## 4.7 Edge Ignore

edge_ignore_s defines a forbidden region near signal boundaries.

Converted to samples:

edge_samples = round(edge_ignore_s / dt)

Peaks within this region are discarded.

---

## 4.8 Output Candidate Structure

Each detected extremum yields:

t0_index  
t0_time  
peak_value  
peak_strength  

Where:

peak_strength = |peak_value - local_baseline|

Exact baseline definition depends on SciPy prominence or local slope context.

---

## 4.9 Interaction with Debounce

local_extrema generates raw candidate extrema.

Debounce clustering is applied afterward to:

• group closely spaced extrema  
• select the preferred representative  

---

## 4.10 Worked Example

Signal:

Index: 0 1 2 3 4 5 6  
Value: 1 3 7 5 2 4 1  

Maxima detected at:

index 2 (value 7)  
index 5 (value 4)

If distance_s excludes close spacing, one may be suppressed.

---

## 4.11 Common Pitfalls

• forgetting prominence on noisy data  
• over-large search windows capturing unrelated peaks  
• misunderstanding min vs max semantics  
• relying on fallback algorithm for heavy noise  

---

## 4.12 Design Guarantees

• deterministic ordering of peaks  
• consistent time resolution  
• registry-based signal access  
• explicit filtering controls  

---

End of Section 4


---

# BODAQS Event Schema Specification — Section 5
## Trigger Engine: phased_threshold_crossing

This section defines the phased_threshold_crossing trigger engine, a robust state-machine based detector designed
to identify threshold transitions in noisy signals by enforcing dwell times within defined bands.

---

## 5.1 Purpose

phased_threshold_crossing is intended for signals where simple crossings are unreliable due to noise or oscillation.

Typical uses:
- velocity zero-crossings in vibration
- contact onset/offset
- regime transitions

---

## 5.2 Conceptual Model

The trigger enforces progression through ordered signal bands:

NEGATIVE → ZERO → POSITIVE  (for rising direction)  
POSITIVE → ZERO → NEGATIVE  (for falling direction)

Each band must be occupied for a minimum dwell time before transition.

---

## 5.3 Formal Definition

TriggerDef fields:

type: phased_threshold_crossing  
signal: role  
dir: rising | falling  
bands:
  neg:
    max: float
    dwell_samples: int
  zero:
    min: float
    max: float
    dwell_samples: int
  pos:
    min: float
    dwell_samples: int
cross_samples: int  
search: SearchWindow | null  
edge_ignore_s: float | null  
debounce: DebounceSpec | null  

---

## 5.4 Band Semantics

### Negative band

Signal must satisfy:

y ≤ neg.max

for at least neg.dwell_samples consecutive samples.

---

### Zero band

Signal must satisfy:

zero.min ≤ y ≤ zero.max

for at least zero.dwell_samples consecutive samples.

---

### Positive band

Signal must satisfy:

y ≥ pos.min

for at least pos.dwell_samples consecutive samples.

---

## 5.5 Rising Direction Sequence

The trigger fires only after successful progression:

NEGATIVE dwell  
→ ZERO dwell  
→ POSITIVE dwell  
→ cross confirmation

---

## 5.6 Falling Direction Sequence

The trigger fires only after:

POSITIVE dwell  
→ ZERO dwell  
→ NEGATIVE dwell  
→ cross confirmation

---

## 5.7 Cross Confirmation

cross_samples defines how many consecutive samples must satisfy the final band before the trigger is emitted.

This further suppresses spurious transitions.

---

## 5.8 State Reset Behavior

If at any point the signal violates the current band constraints:

• dwell counters reset  
• state machine returns to initial band  

This guarantees monotonic progression only.

---

## 5.9 Search Window Interaction

If search is absent:

→ entire signal scanned

If search present:

start_time = base_time + min_delay_s  
end_time   = base_time + max_delay_s  

Only samples in this window participate in the state machine.

---

## 5.10 Edge Ignore

edge_ignore_s defines forbidden regions near boundaries.

Triggers occurring within this region are discarded.

---

## 5.11 Output Candidate Structure

Each successful phased transition yields:

t0_index  
t0_time  
transition_strength  

Where:

transition_strength is typically the magnitude of the final band excursion.

---

## 5.12 Worked Example

Given rising configuration:

neg.max = -5  
zero.min = -2  
zero.max = 2  
pos.min = 5  

Signal:

[-8, -7, -6, -3, -1, 1, 3, 6, 7]

Progression:

NEG dwell → ZERO dwell → POS dwell → trigger at first sustained ≥ 5

---

## 5.13 Common Pitfalls

• dwell_samples too small (noise leakage)  
• overly wide zero band  
• missing cross_samples  
• misordered thresholds  
• excessive debounce masking transitions  

---

## 5.14 Design Guarantees

• extremely noise robust  
• deterministic state progression  
• explicit timing control  
• registry-resolved signal semantics  

---

End of Section 5


---

# BODAQS Event Schema Specification — Section 6
## Secondary Trigger Search & Debounce Semantics

This section formalizes how secondary triggers are resolved relative to base triggers and how debounce clustering
selects the final trigger candidate.

This is the most subtle and error-prone part of the event detection pipeline.

---

## 6.1 Conceptual Purpose

Secondary triggers allow events to be defined by relationships between multiple signal transitions.

Examples:

• rebound start relative to rebound end  
• contact onset before impact  
• extrema surrounding crossings  

They always operate relative to a base trigger.

---

## 6.2 Search Window Definition

Each secondary trigger may define:

search:
  min_delay_s: float  
  max_delay_s: float  
  direction: forward | backward  

The absolute search interval is:

start_time = base_trigger_time + min_delay_s  
end_time   = base_trigger_time + max_delay_s  

Only candidate triggers whose timestamps fall within this interval are considered.

---

## 6.3 Direction Semantics

### forward

Candidates are ordered by increasing time:

t₀ < t₁ < t₂ ...

Default preferred candidate (pre-debounce):

→ earliest timestamp

---

### backward

Candidates are ordered by decreasing time:

tₙ > tₙ₋₁ > tₙ₋₂ ...

Default preferred candidate (pre-debounce):

→ latest timestamp

---

## 6.4 Candidate Generation

Secondary trigger engines generate raw candidates using the same trigger logic as primary triggers.

Search windows restrict which samples are evaluated.

The result is an ordered list of candidate trigger events.

---

## 6.5 Why Debounce Exists

Raw candidates often include:

• noise crossings  
• oscillatory transitions  
• closely spaced peaks  

Debounce collapses clusters of nearby triggers into a single representative event.

---

## 6.6 Debounce Clustering Algorithm

Given candidate indices:

i₀, i₁, i₂, ..., iₙ

Convert gap_s to samples:

gap_samples = round(gap_s / dt)

Clusters are formed where:

|iₖ₊₁ - iₖ| ≤ gap_samples

Each contiguous group becomes one cluster.

---

## 6.7 Debounce Scoring

Within each cluster, a score is computed per candidate:

score = candidate[prefer_key]

If prefer_abs is true:

score = |score|

Winner selection:

prefer_max = true  → select max(score)  
prefer_max = false → select min(score)

---

## 6.8 Interaction with Direction

Important:

Debounce ALWAYS runs after directional ordering.

However:

Debounce selection ignores time order unless prefer_key encodes time or index.

Thus:

prefer_key: t0_index  
prefer_max: false  

will always select the earliest index in the cluster — regardless of backward search.

This is a common misconfiguration.

---

## 6.9 Safe Configuration Patterns

### Pattern A — take first found in backward search

Disable debounce or use:

prefer_key: t0_index  
prefer_max: true  

---

### Pattern B — strongest physical event

prefer_key: trigger_strength  
prefer_max: true  

---

### Pattern C — earliest onset

prefer_key: t0_index  
prefer_max: false  

---

## 6.10 Worked Example

Base trigger at t = 5.0 s

Secondary candidates at:

4.2 s (index 420)  
4.6 s (index 460)  
4.8 s (index 480)

search direction = backward

Raw preferred = 4.8 s

If gap_s collapses all into one cluster:

prefer_key: t0_index  
prefer_max: false  

Winner → index 420 (earliest)

Unexpected unless intended.

---

## 6.11 Common Pitfalls

• using large gap_s values  
• prefer_key not encoding desired priority  
• assuming backward search overrides debounce  
• clustering across entire search window  

---

## 6.12 Design Guarantees

• deterministic cluster formation  
• explicit scoring rules  
• no hidden heuristics  
• full user control over selection  

---

End of Section 6


---

# BODAQS Event Schema Specification — Section 7
## Conditions DSL (Preconditions & Postconditions)

This section defines the domain-specific language used to constrain detected triggers using signal-based tests
applied within relative time windows.

Conditions act as semantic filters that determine whether a candidate trigger becomes a valid event instance.

---

## 7.1 Conceptual Purpose

Conditions enforce physical meaning beyond simple signal crossings.

Examples:

• ensure rebound only occurs after sufficient compression  
• reject noise-induced extrema  
• require displacement minima near trigger  
• constrain velocity regimes  

Conditions are evaluated only after trigger detection.

---

## 7.2 ConditionBlock Structure

A ConditionBlock has the form:

within_s: [start_offset, end_offset]  
any_of: [TestDef...]  
all_of: [TestDef...]  

Where:

• within_s defines the relative time window around the trigger  
• any_of requires at least one TestDef to pass  
• all_of requires every TestDef to pass  

Either any_of or all_of may be omitted, but at least one must be present.

---

## 7.3 Window Semantics

Given trigger_time T:

window_start = T + within_s[0]  
window_end   = T + within_s[1]  

All signal samples within this interval are extracted for testing.

Offsets may be positive or negative.

---

## 7.4 TestDef Types

Supported test types:

• peak  
• range  
• delta  

Each test operates on a single signal role.

---

## 7.5 peak Test

Detects extrema within the condition window.

Definition:

type: peak  
signal: role  
kind: max | min  
cmp: "<" | "<=" | ">" | ">=" | "=="  
value: float  

Evaluation:

1. compute extremum in window  
2. compare extremum to value using cmp  
3. return pass/fail  

---

### Example

Require minimum normalized displacement below 0.02:

type: peak  
signal: disp_norm  
kind: min  
cmp: "<="  
value: 0.02  

---

## 7.6 range Test

Ensures all samples lie within bounds.

Definition:

type: range  
signal: role  
min: float | null  
max: float | null  

Evaluation:

Passes if:

∀ y in window: min ≤ y ≤ max  

Unspecified bounds are ignored.

---

### Example

Require velocity between -50 and 50:

type: range  
signal: vel  
min: -50  
max: 50  

---

## 7.7 delta Test

Measures change over the window.

Definition:

type: delta  
signal: role  
cmp: "<" | "<=" | ">" | ">=" | "=="  
value: float  

Evaluation:

delta = y_end - y_start  

Compare delta to value using cmp.

---

### Example

Require displacement increase of at least 5 mm:

type: delta  
signal: disp  
cmp: ">="  
value: 5  

---

## 7.8 any_of vs all_of Logic

all_of:

Every test must pass.

any_of:

At least one test must pass.

Both may coexist:

• all_of enforces hard constraints  
• any_of allows alternative satisfaction paths  

---

## 7.9 Missing Data Handling

If no valid samples exist in the condition window:

→ condition fails

If signal role cannot be resolved:

→ hard failure (schema error)

---

## 7.10 Performance Characteristics

Conditions are evaluated using vectorized window slices.

Complexity scales with:

number of events × window size × test count

---

## 7.11 Common Pitfalls

• overly narrow windows missing extrema  
• forgetting sign of delta  
• using range when peak intended  
• overlapping contradictory tests  

---

## 7.12 Design Guarantees

• deterministic evaluation  
• strict registry-resolved signals  
• explicit numeric semantics  
• no heuristic smoothing  

---

End of Section 7


---

# BODAQS Event Schema Specification — Section 8
## Window Semantics & Alignment

This section defines how temporal windows are specified, how they are applied during detection and segmentation,
and how alignment anchors affect downstream metric computation.

Windows exist in two distinct contexts:

• detection visibility windows  
• segment extraction windows  

Although similarly shaped, their semantics differ.

---

## 8.1 Conceptual Purpose

Windows define the temporal neighborhood of interest around an event trigger.

They are used to:

• restrict candidate trigger visibility  
• define waveform segments  
• bound condition evaluation  
• provide fallback metric intervals  

---

## 8.2 WindowDef Structure

Window definitions appear in two places:

### Event-level detection window

window:
  pre_s: float  
  post_s: float  
  align: trigger | start | end  

### Segment-level window (segment_defaults)

window:
  pre_s: float  
  post_s: float  

Segment windows are always aligned to the chosen anchor.

---

## 8.3 Detection Visibility Window

For a trigger occurring at time T:

visible_start = T - pre_s  
visible_end   = T + post_s  

Only signal samples within this region are:

• eligible for secondary trigger search  
• used for condition evaluation  
• considered for extrema detection  

Outside samples are ignored.

---

## 8.4 Alignment Modes

### align: trigger

Window is centered on the primary trigger time.

This is the default and most common behavior.

---

### align: start

Window start defines the anchor.

anchor_time = first valid sample in window

Primarily used when onset detection precedes known trigger.

---

### align: end

Window end defines the anchor.

anchor_time = last valid sample in window

Useful for termination-style events.

---

## 8.5 Interaction with Secondary Triggers

Secondary trigger search windows are always defined relative to the primary trigger time,
not the detection visibility window bounds.

However:

Candidates must still lie within the detection window to be valid.

---

## 8.6 Segment Extraction Windows

Segment extraction uses its own WindowSpec:

window:
  pre_s: float  
  post_s: float  

And an anchor field:

anchor: trigger_time_s | start_time_s | end_time_s

The extracted segment spans:

[anchor_time - pre_s , anchor_time + post_s]

---

## 8.7 Clipping Behavior

If requested window exceeds signal bounds:

• samples are clipped to available range  
• padding may be applied (nan, edge, or drop)  

Padding behavior is controlled by OutputSpec.

---

## 8.8 Metric Fallback Intervals

If explicit metric triggers are missing (in permissive mode):

Metrics may fall back to the detection window bounds.

In strict mode:

Missing trigger times produce errors.

---

## 8.9 Timebase Resolution

All window boundaries are resolved using the session timebase:

time_s column

Sample indices are computed via nearest-time lookup.

This guarantees monotonic ordering and deterministic slicing.

---

## 8.10 Common Pitfalls

• overly wide windows capturing unrelated dynamics  
• overly narrow windows missing extrema  
• misunderstanding align semantics  
• relying on fallback metric behavior  
• forgetting padding effects  

---

## 8.11 Design Guarantees

• deterministic window slicing  
• explicit temporal bounds  
• strict anchor semantics  
• reproducible segment shapes  

---

End of Section 8


---

# BODAQS Event Schema Specification — Section 9
## Segment Extraction & Registry-First Role Binding Contract

This section defines the formal contract for extracting waveform segments around events and the deterministic
resolution of schema roles to concrete signal columns using the signal registry.

Segment extraction is the bridge between event detection and metric computation.

---

## 9.1 Conceptual Purpose

Segment extraction:

• aligns signal data around event anchors  
• resolves semantic roles into concrete signals  
• enforces deterministic sensor binding  
• produces reproducible waveform arrays  

All metrics operate exclusively on extracted segments.

---

## 9.2 SegmentBundle Structure

The output of segment extraction is a SegmentBundle:

data:
  role → ndarray per event

segments:
  per-event metadata including:
    start_idx
    end_idx
    valid
    reason

events:
  filtered event table

spec:
  resolved anchor, window, grid, roles

qc:
  quality summaries

---

## 9.3 SegmentDefaults Grammar

Defined in the schema as:

segment_defaults:
  anchor: trigger_time_s | start_time_s | end_time_s
  window:
    pre_s: float
    post_s: float
  grid:
    mode: native | resample
    dt_s: float | null
  roles:
    - role: string
      prefer:
        quantity: string
        unit: string | null
        kind: string | null
        op_chain: list[string] | null
        sensor: string | null

---

## 9.4 Anchor Semantics

anchor defines the reference timestamp for segment extraction.

Allowed values:

• trigger_time_s  
• start_time_s  
• end_time_s  

Anchor time MUST exist in the event table.

Missing anchors produce hard failures in strict mode.

---

## 9.5 Window Application

For anchor time A:

segment_start = A - pre_s  
segment_end   = A + post_s  

All samples in this interval are included in the segment grid.

---

## 9.6 Registry-First Role Resolution

Each RoleSpec is resolved by matching registry entries against:

(sensor, quantity, unit, kind, op_chain)

Resolution rules:

1. Exact matches preferred  
2. More semantically rich entries scored higher  
3. Primary signal favored if tied  
4. Ambiguity produces hard failure  

---

## 9.7 Per-Event Sensor Binding

Role resolution occurs per event instance.

The event's triggering signal determines its bound sensor.

Thus:

rear_shock event resolves to rear_shock signals  
front_shock event resolves to front_shock signals  

Schemas remain sensor-agnostic.

---

## 9.8 op_chain Normalization

Transformation lineage is preserved as:

op_chain tokens

Examples:

op_zeroed → zeroed  
op_norm → norm  

Normalization removes prefixes for consistent matching.

---

## 9.9 Grid Modes

### native

Uses original sample spacing.

No resampling occurs.

---

### resample

Signals are interpolated to uniform dt_s spacing.

Ensures identical segment lengths across events.

---

## 9.10 Padding Behavior

If requested window exceeds data bounds:

pad mode determines behavior:

• nan → fill missing samples with NaN  
• edge → extend boundary values  
• drop → invalidate segment  

---

## 9.11 Failure Conditions

Hard failures occur when:

• role cannot be resolved  
• multiple equally valid roles exist  
• anchor field missing  
• resolved column absent from dataframe  

---

## 9.12 Common Pitfalls

• forgetting sensor inheritance  
• ambiguous registry entries  
• mismatched units  
• incorrect op_chain tokens  
• assuming column name matching  

---

## 9.13 Design Guarantees

• deterministic role binding  
• strict semantic correctness  
• reproducible waveform extraction  
• early detection of schema errors  

---

End of Section 9


---

# BODAQS Event Schema Specification — Section 10
## Metrics DSL & Computation Semantics

This section defines the domain-specific language for metric extraction and the precise semantics of metric
computation over extracted segments.

Metrics operate strictly on SegmentBundles and never on raw dataframe columns.

---

## 10.1 Conceptual Purpose

Metrics transform waveform segments into scalar values suitable for:

• statistical analysis  
• comparison across events  
• visualization  
• downstream modeling  

Metrics MUST be deterministic and traceable to signal semantics.

---

## 10.2 MetricDef Structure

Each metric definition has the form:

type: string  
signal: role  
id: string | null  
tags: list[string] | null  

Additional fields depend on metric type.

If id is omitted, a stable id is auto-generated.

---

## 10.3 Metric Execution Order

Metrics are computed in the order defined in the schema.

Each metric is independent; no metric may depend on the output of another.

---

## 10.4 peak Metric

The peak metric extracts extrema from a segment.

Definition:

type: peak  
signal: role  
kind: max | min  
return_time: bool (default: false)  

---

### 10.4.1 Computation

Given a segment array y:

If kind = max:

peak_value = max(y)

If kind = min:

peak_value = min(y)

NaN values are ignored.

---

### 10.4.2 Time Reporting

If return_time is true:

peak_time = time index of extremum (relative or absolute)

Time resolution follows the segment grid.

---

## 10.5 interval_stats Metric

interval_stats computes statistics between two trigger times.

Definition:

type: interval_stats  
signal: role  
start_trigger: string  
end_trigger: string  
ops: list[string]  
smooth_ms: float | null  
min_delay_s: float | null  
polarity: pos_to_neg | neg_to_pos | null  
return_debug: bool (default: false)  

---

## 10.5.1 Trigger Time Resolution

Trigger times are resolved as:

{trigger_id}_time_s  
trigger_time_s (for primary trigger only)

No inference or substitution is permitted.

---

## 10.5.2 Interval Definition

Let:

t_start = resolved start trigger time  
t_end   = resolved end trigger time  

If t_end < t_start:

In strict mode → error  
In permissive mode → swap times  

---

## 10.5.3 Signal Extraction

Signal samples between t_start and t_end are selected.

If min_delay_s is specified:

t_start = t_start + min_delay_s

---

## 10.5.4 Smoothing

If smooth_ms is specified:

A moving average filter is applied before statistics.

Window size is computed from dt.

---

## 10.5.5 Operations

Supported ops:

• mean  
• max  
• min  
• delta (y_end - y_start)  
• integral (trapezoidal)  

Each op yields a scalar metric.

---

## 10.5.6 Polarity

polarity constrains the expected sign of change.

If violated:

• metric may be flagged  
• debug output records violation  

---

## 10.5.7 Debug Output

If return_debug is true:

Additional columns are emitted:

• interval_start_time  
• interval_end_time  
• n_samples  
• violated_polarity  

---

## 10.6 Missing Data Behavior

If no samples exist in interval:

→ metric value is NaN

If trigger times are missing:

→ strict mode error  
→ permissive mode NaN  

---

## 10.7 Naming & Namespacing

Metric column names encode:

metric id  
signal role  
operation  

Ensures uniqueness and traceability.

---

## 10.8 Common Pitfalls

• swapped trigger ids  
• missing trigger_time columns  
• overly aggressive smoothing  
• assuming fallback behavior  
• polarity misuse  

---

## 10.9 Design Guarantees

• deterministic computation  
• explicit interval semantics  
• strict trigger-time usage  
• reproducible metrics  

---

End of Section 10


---

# BODAQS Event Schema Specification — Section 11
## Trigger Time & Session Invariants

This section formalizes the guarantees provided by preprocessing and the strict trigger-time contract relied upon
by detection, segmentation, and metric computation.

These invariants are foundational for deterministic behavior across the pipeline.

---

## 11.1 Conceptual Purpose

Trigger times are the temporal anchors for:

• secondary trigger resolution  
• window slicing  
• segment extraction  
• interval metric computation  

If trigger times are ambiguous or inconsistent, the entire pipeline becomes invalid.

---

## 11.2 Canonical Timebase

Every session MUST include a monotonic time column:

time_s

Properties:

• strictly increasing (after repair if needed)  
• numeric float seconds  
• no missing interior values  

All temporal logic references this column.

---

## 11.3 Trigger Time Fields

Each emitted event instance MUST include:

trigger_time_s

Additionally, each trigger (primary and secondary) MAY emit:

{trigger_id}_time_s

Examples:

rebound_end_time_s  
rebound_start_time_s  

---

## 11.4 Resolution Rules

Metric and segmentation logic resolves trigger times in the following strict order:

1. {trigger_id}_time_s  
2. trigger_time_s (only for primary trigger)  

No fallback to window bounds or extrema is permitted in strict mode.

---

## 11.5 Strict vs Permissive Mode

### Strict Mode

• missing trigger times → error  
• invalid intervals → error  
• ambiguous resolution → error  

Used for development and validation.

---

### Permissive Mode

• missing trigger times → NaN  
• reversed intervals → auto-swapped  
• missing samples → NaN  

Used for exploratory analysis.

---

## 11.6 Preprocessing Guarantees

Preprocessing ensures:

• canonical signal naming  
• registry completeness  
• derived velocity/acceleration availability  
• timebase repair if needed  
• QC metadata population  

Event detection MUST run only after preprocessing.

---

## 11.7 Activity Mask (QC)

Optional activity masks may be applied as QC flags.

Properties:

• never part of signal registry  
• may gate detection or metrics  
• must not mutate timebase  

---

## 11.8 Failure Conditions

Hard failures occur when:

• time_s missing  
• trigger_time_s missing  
• trigger id fields malformed  
• time ordering violated  

---

## 11.9 Design Guarantees

• single authoritative timebase  
• explicit trigger anchoring  
• deterministic window resolution  
• reproducible metric intervals  

---

End of Section 11


---

# BODAQS Event Schema Specification — Section 12
## Worked Event Walkthroughs

This section provides concrete, end-to-end examples demonstrating how event schema definitions propagate
through trigger detection, secondary trigger resolution, segmentation, and metric computation.

Each walkthrough follows the same structure:

1. Schema definition  
2. Trigger detection behavior  
3. Secondary trigger resolution  
4. Condition filtering  
5. Segment extraction  
6. Metric outputs  

---

## 12.1 Rebound / Top-Out Event Example

### 12.1.1 Schema Definition

```yaml
id: top_out
label: rebound events with min normalized displacement <= 0.02
sensors: [rear_shock, front_shock]

trigger:
  id: rebound_end
  type: simple_threshold_crossing
  signal: vel
  value: 0.0
  dir: rising

secondary_triggers:
  - id: rebound_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    search:
      min_delay_s: -0.8
      max_delay_s: -0.05
      direction: backward

preconditions:
  - within_s: [-0.01, 0.01]
    all_of:
      - type: peak
        signal: disp_norm
        kind: min
        cmp: "<="
        value: 0.02

window:
  pre_s: 0.8
  post_s: 0.2

metrics:
  - type: interval_stats
    signal: vel
    start_trigger: rebound_end
    end_trigger: rebound_start
    ops: [mean, max, min]
```

---

### 12.1.2 Primary Trigger Detection

Velocity zero-crossings in the rising direction identify rebound_end events.

Each sensor resolves its own vel signal via the registry.

---

### 12.1.3 Secondary Trigger Resolution

Backward search identifies the nearest falling zero-crossing preceding rebound_end.

Debounce collapses oscillations if present.

---

### 12.1.4 Condition Filtering

Normalized displacement is inspected in a ±10 ms window around rebound_end.

Event is accepted only if minimum disp_norm ≤ 0.02.

---

### 12.1.5 Segment Extraction

Segments are extracted around trigger_time_s:

[start - 0.8 s , start + 0.2 s]

Roles disp, vel, acc are bound per sensor.

---

### 12.1.6 Metric Computation

Velocity statistics are computed between rebound_end_time_s and rebound_start_time_s.

Results yield mean rebound velocity and peak dynamics.

---

## 12.2 Impact Event Example (Acceleration Peak)

### 12.2.1 Schema Definition

```yaml
id: impact
label: high acceleration spike
sensors: [rear_shock]

trigger:
  type: local_extrema
  signal: acc
  kind: max
  prominence: 500
```

---

### 12.2.2 Detection Behavior

High-prominence acceleration peaks are detected as impacts.

No secondary triggers required.

---

### 12.2.3 Segment Extraction

Short windows around peaks capture impulse response.

---

### 12.2.4 Metrics

Peak acceleration and post-impact oscillation metrics are computed.

---

## 12.3 Regime Transition Example (Phased Trigger)

### 12.3.1 Schema Definition

```yaml
id: compression_to_rebound
label: velocity regime transition
sensors: [rear_shock]

trigger:
  type: phased_threshold_crossing
  signal: vel
  dir: rising
  bands:
    neg: {max: -10, dwell_samples: 3}
    zero: {min: -2, max: 2, dwell_samples: 2}
    pos: {min: 10, dwell_samples: 3}
  cross_samples: 2
```

---

### 12.3.2 Detection Behavior

Only sustained transitions across negative → zero → positive velocity are accepted.

Noise crossings are suppressed.

---

### 12.3.3 Downstream Flow

Events feed directly into segmentation and rebound metrics.

---

## 12.4 Design Lessons from Walkthroughs

• roles remain sensor-agnostic  
• secondary windows define physical relationships  
• conditions enforce meaning  
• segmentation standardizes waveform context  
• metrics are strictly time-anchored  

---

End of Section 12


---

# BODAQS Event Schema Specification — Section 13
## Anti-Patterns & Debugging Guide

This section documents common failure modes encountered when authoring event schemas and provides systematic
approaches for diagnosing incorrect detection, segmentation, and metric behavior.

---

## 13.1 Philosophy of Debugging

The BODAQS pipeline is designed to:

• fail early on semantic ambiguity  
• avoid hidden heuristics  
• make every transformation explicit  

Most bugs arise from violated invariants rather than algorithmic faults.

---

## 13.2 Common Anti-Patterns

### 13.2.1 Overusing Debounce Windows

Symptom:
• secondary trigger resolves to unexpected early event  
• clusters collapse entire search window  

Cause:
• gap_s larger than physical oscillation scale  

Fix:
• reduce gap_s  
• or select prefer_max when using t0_index  

---

### 13.2.2 Assuming Direction Overrides Debounce

Symptom:
• backward search returns earliest event  

Cause:
• debounce scoring ignores time ordering  

Fix:
• encode time/index into prefer_key  
• or disable debounce  

---

### 13.2.3 Ambiguous Role Resolution

Symptom:
• runtime error: ambiguous role  
• unexpected signal binding  

Cause:
• multiple registry entries matching prefer spec  

Fix:
• specify unit, op_chain, or sensor explicitly  

---

### 13.2.4 Using Column Names in Schema Logic

Symptom:
• silent misbinding after renaming  
• brittle schemas  

Cause:
• bypassing registry-first design  

Fix:
• always use roles  

---

### 13.2.5 Overly Broad Search Windows

Symptom:
• unrelated transitions captured  
• spurious secondary triggers  

Fix:
• tighten min_delay_s / max_delay_s  

---

### 13.2.6 Forgetting Hysteresis on Noisy Signals

Symptom:
• chatter triggers  
• dense candidate clusters  

Fix:
• add hysteresis or phased trigger  

---

## 13.3 Systematic Debugging Workflow

### Step 1 — Inspect Signal Registry

Verify:

• sensor  
• quantity  
• unit  
• op_chain  

Ensure no ambiguity exists.

---

### Step 2 — Visualize Trigger Candidates

Plot raw candidates before debounce.

Confirm:

• correct crossings/extrema  
• expected ordering  

---

### Step 3 — Check Debounce Clusters

Print cluster membership and scores.

Verify winner selection logic.

---

### Step 4 — Validate Trigger Times

Confirm:

trigger_time_s  
{trigger_id}_time_s  

exist and are monotonic.

---

### Step 5 — Inspect Segment Extraction

Verify:

• anchor correctness  
• window bounds  
• resolved role columns  

---

### Step 6 — Inspect Metric Intervals

Confirm:

• start < end  
• expected sample count  
• smoothing not oversuppressing  

---

## 13.4 Debug Flags & Instrumentation

Recommended tools:

• return_debug on interval_stats  
• logging of candidate triggers  
• visualization of segments  
• registry dumps  

---

## 13.5 Fast Diagnosis Table

| Symptom | Likely Cause |
|--------|------------|
| wrong secondary trigger | debounce scoring |
| no metrics output | missing trigger_time |
| NaNs everywhere | window empty |
| role errors | registry ambiguity |
| noisy triggers | missing hysteresis |
| clipped segments | window too large |

---

## 13.6 Design Intent Reminder

If behavior seems surprising:

It is almost always due to:

• explicit schema configuration  
• strict deterministic rules  

Not hidden heuristics.

---

End of Section 13


---

# BODAQS Event Schema Specification — Section 14
## Schema Design Best Practices

This section provides practical guidance for authoring robust, scalable, and maintainable event schemas
that remain correct as signal sets, sensors, and analysis complexity grow.

---

## 14.1 Design Philosophy

Effective schemas should be:

• semantically explicit  
• sensor-agnostic  
• noise-robust  
• narrowly scoped  
• easy to debug  

Prefer correctness and clarity over compactness.

---

## 14.2 Always Design Around Physical Meaning

Triggers should represent physical events:

✔ velocity zero-crossings → regime change  
✔ extrema → mechanical limits  
✔ phased transitions → robust state changes  

Avoid abstract numeric thresholds with no physical interpretation.

---

## 14.3 Keep Roles Generic

Use roles such as:

disp, vel, acc, disp_norm, raw

Avoid sensor-specific naming in schema logic.

Let registry binding handle sensor resolution.

---

## 14.4 Minimize Debounce Use

Use debounce only when:

• oscillations are unavoidable  
• physical grouping is required  

Prefer:

• hysteresis  
• phased triggers  
• tighter search windows  

Overuse of debounce hides true dynamics.

---

## 14.5 Prefer Narrow Search Windows

Search windows should reflect physical causality:

✔ rebound start occurs shortly before rebound end  
✔ impacts are localized in time  

Wide windows increase false associations.

---

## 14.6 Make Conditions Express Meaning

Conditions should enforce real constraints:

✔ displacement minima at top-out  
✔ velocity sign consistency  
✔ range-limited regimes  

Avoid arbitrary numeric gating.

---

## 14.7 Use Strict Mode During Development

Always validate schemas with:

strict = True

This catches:

• missing trigger times  
• ambiguous roles  
• invalid intervals  
• schema grammar issues  

Relax only for exploratory analysis.

---

## 14.8 Version Schemas Explicitly

Maintain:

schema_version

Increment when semantics change.

This ensures reproducibility across datasets.

---

## 14.9 Document Each Event

Each EventDef should include:

• clear label  
• physical interpretation  
• expected dynamics  

Future readers should understand intent immediately.

---

## 14.10 Validate Registry Early

Always inspect:

session["meta"]["signals"]

before debugging schema behavior.

Most bugs originate in semantic misbinding.

---

## 14.11 Build Incrementally

Recommended workflow:

1. validate primary trigger alone  
2. add secondary triggers  
3. add conditions  
4. add segmentation  
5. add metrics  

Test at each stage.

---

## 14.12 Performance Considerations

• minimize window sizes  
• limit condition complexity  
• avoid excessive resampling  
• restrict debounce clustering  

Scalability improves with tight semantics.

---

## 14.13 Long-Term Maintainability Rules

✔ avoid magic numbers  
✔ encode physical meaning  
✔ keep schemas modular  
✔ reuse trigger patterns  
✔ document assumptions  

---

## 14.14 Final Design Guarantee

Well-designed schemas yield:

• deterministic detection  
• reproducible metrics  
• interpretable results  
• scalable analysis  

---

End of Section 14


---

