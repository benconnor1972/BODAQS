# BODAQS Spatial Context Stream Contract v0 Draft

**Status:** Draft  
**Scope:** Session-derived distance-domain metrics, with optional post-derivation track traversal scoping
**Initial consumer:** JupyterLab exploratory analysis  
**Future consumers:** BODAQS Library API and Workbench

---

## 1. Purpose

This contract defines a versioned spatial-context product for one processed
session. The product represents continuous ride-context quantities on a regular
distance grid:

- gradient;
- twistiness;
- front-wheel suspension activity;
- rear-wheel suspension activity; and
- an optional combined suspension-activity view.

The authoritative representation is a set of continuous fields over session
cumulative distance. Thresholds, named terrain classes, breakpoints, and
variable-length regions are downstream queries or analysis products. They are
not canonical fields in this stream.

The first implementation is intended for parameterized preprocessing and
visualization in JupyterLab. The canonical metrics are derived for the whole
session. A later post-processing step may select one traversal of a reusable
track without changing the evidence or estimator used for those metrics. The
stored shape deliberately avoids notebook-only objects so that the Library API
and Workbench can consume it later.

---

## 2. Non-goals

Version 0 does not define:

- semantic terrain labels;
- automatic terrain classification;
- machine-learning features or models;
- fixed-length terrain segments;
- change-point or persistence models;
- setup recommendations;
- one universally correct smoothing scale;
- a Workbench endpoint or browser interaction contract; or
- deriving gradient, twistiness, or suspension activity from reusable track
  geometry.

The canonical preprocessed stream coordinate is cumulative distance travelled
within one session. A track-scoped exploratory result may rebase that session
distance at the selected traversal start and expose track station as a separate
diagnostic coordinate. Session distance and track station must not be conflated.

---

## 3. Relationship To Existing Contracts

This contract should be read alongside:

- `BODAQS_analysis_artifacts_specification_v0_2.md`;
- `BODAQS_Stream_Materialisation_Policy_v0_draft.md`;
- `BODAQS_Preprocess_Profile_Contract_v0_draft.md`;
- `BODAQS_Geospatial_Contracts_v0_draft.md`;
- `BODAQS_Minimum_Signal_Registry_Semantics_v0_1_1.md`; and
- `BODAQS_Bike_Profile_Contract_v0_draft.md`.

The spatial-context stream is a session-derived analysis product. It is not an
event metrics table: the metrics table remains one row per detected event. It
is also not a reusable track profile: suspension activity depends on the
session, rider, speed, line, bike, and setup.

---

## 4. Core Concepts

### 4.1 Session distance

`distance_m` is a monotonic cumulative ground-distance coordinate for the
session. It is measured in metres from the selected distance origin.

The source of distance is chosen by an ordered source-priority policy. The
initial priority is:

1. a recorded cumulative-distance signal from a selected GPS or FIT source;
2. cumulative distance derived from selected, denoised GPS geometry.

The vocabulary must remain extensible to later candidates such as wheel
odometry. Adding a candidate does not change the meaning of `distance_m`, but
the selected candidate and its provenance must always be recorded.

For GPS-geometry distance, version 0 denoises the source positions before
stationing. The exploratory policy is a 20 m local quadratic fit with tricube
distance weighting and two Tukey robust-weight iterations. This prevents
metre-scale GPS zig-zags from accumulating as false travelled distance while
retaining bends at the configured spatial scale. The raw geometry length,
denoised length, and effective fit parameters must be recorded.

When a reusable Workbench track is created from the same session and GPS
source, its stored path and `station_m` coordinate should use the same denoised
geometry policy. This makes session distance and track station closely
comparable without redefining either coordinate. Endpoint trimming, a
different source, recorded-distance priority, or later track editing can still
make the two ranges differ.

### 4.2 Spatial grid

The materialized stream uses a regular spatial grid. `distance_grid_interval_m`
describes grid spacing and is independent of metric smoothing distance.

A finer grid does not imply finer source measurement resolution. In
particular, interpolating 1 Hz GPS onto a 0.5 m grid does not create 0.5 m GPS
evidence. Source support and interpolation gaps must remain visible in QC.

### 4.3 Local and smoothed quantities

Where practical, the stream preserves both:

- a local or unsmoothed per-grid quantity; and
- the corresponding centred spatially smoothed field.

Smoothing scale is effective configuration and provenance. It is not encoded
as a permanent part of the metric definition.

### 4.4 Distance-to-time mapping

Each spatial row may expose `representative_time_s`, allowing a downstream
consumer to navigate back to the native time-domain evidence. Implementations
must retain enough internal mapping information to translate a selected
distance range into one or more valid time ranges.

The mapping must not imply support through GPS gaps or invalid distance
intervals.

### 4.5 Optional track traversal scope

Track scoping is a post-derivation selection operation. The implementation must
first calculate the whole-session spatial-context stream, including native-rate
suspension accumulation and all spatial filtering/smoothing. It may then use a
root-scoped `Track` to retain the rows belonging to one qualifying traversal.
Track geometry must not replace session GPS altitude, session GPS geometry, or
session suspension signals as metric evidence.

The default traversal policy is:

```text
last_forward_traversal
```

The initial supported selection policies are:

```text
first_forward_traversal | last_forward_traversal | longest_forward_traversal
```

Initial exploratory configuration shape:

```json
{
  "traversal_selection": "last_forward_traversal",
  "matching": {
    "maximum_lateral_distance_m": 8.0,
    "maximum_match_gap_s": 5.0,
    "endpoint_tolerance_m": 15.0,
    "minimum_track_coverage_ratio": 0.85,
    "minimum_forward_fraction": 0.60,
    "projection_candidate_count": 8,
    "projection_station_separation_m": 5.0,
    "transition_distance_weight": 0.5,
    "heading_alignment_weight": 2.0
  }
}
```

A qualifying forward traversal must approach both directed track endpoints,
meet the configured track-coverage and forward-progress fractions, remain
within the configured lateral-distance tolerance, and not bridge a match gap
larger than the configured limit. All thresholds are effective configuration
and must be recorded.

Nearest-segment projection alone is insufficient at crossings, overlapping
out-and-back geometry, and close parallel sections. Matching must retain
alternative plausible projections and resolve them as an ordered sequence.
The initial matcher uses GPS movement distance, heading agreement, and track
station continuity. Its algorithm version and diagnostics must be recorded.

The selected output retains `session_distance_m`, rebases `distance_m` to the
selected traversal start for convenient comparison, and may expose
`track_station_m` as diagnostic alignment evidence. Metric values are copied
from the whole-session result rather than recalculated after the cut.

---

## 5. Input Requirements And Resolution

### 5.1 GPS or FIT evidence

Gradient and twistiness require a coherent selected GPS/FIT source with:

- session-relative time;
- latitude and longitude;
- altitude for gradient; and
- either recorded cumulative distance or sufficient position geometry to
  derive distance.

Source and column selection must use GPS source metadata and signal-registry
semantics. Implementations must not silently choose similarly named dataframe
columns.

Gradient may be omitted while twistiness and suspension activity remain
available when altitude is absent or unsuitable.

### 5.2 Suspension evidence

Suspension activity consumes filtered wheel-domain displacement from the
full-resolution primary session dataframe.

The preferred selectors are:

```json
{
  "end": "front",
  "quantity": "disp",
  "domain": "wheel",
  "unit": "mm",
  "processing_role": "primary_analysis"
}
```

and:

```json
{
  "end": "rear",
  "quantity": "disp",
  "domain": "wheel",
  "unit": "mm",
  "processing_role": "primary_analysis"
}
```

Rear-shock displacement is not an acceptable substitute for rear-wheel
displacement. If a bike-profile transform or other valid wheel-motion signal is
not available, rear activity must be omitted.

### 5.3 Activity-mask evidence

When configured, suspension activity uses the existing preprocessing
`active_mask_qc` as an eligibility mask. The mask determines which native-rate
sample intervals are eligible; it does not define the activity magnitude.

If the configured mask is unavailable, suspension activity must be omitted
rather than treating all samples as active.

The spatial-context metadata must record the active-mask policy and QC that
were effective for the session.

### 5.4 Optional track evidence

Track scoping requires a valid directed Track path with at least two positions.
Track id and revision must be recorded. The track is selection evidence only;
the selected session GPS source remains the source for traversal matching and
all metric derivation.

---

## 6. Distance Source Policy And QC

### 6.1 Source selection

Candidates are evaluated in configured order. A candidate should be selected
only when it supplies a usable monotonic mapping over some positive travelled
distance. Selection must record:

- candidate kind;
- concrete source and stream identity;
- resolved distance or position columns;
- source-selection method;
- coverage and cadence observations;
- repairs or rejected intervals; and
- fallback reasons for higher-priority candidates.

The GPS source policy and distance source policy are related but distinct. The
GPS source policy chooses coherent GPS evidence. The distance policy chooses
how cumulative distance is obtained from that evidence.

### 6.2 Initial exploratory quality guidance

Initial diagnostic thresholds are:

```text
minimum nominal GPS rate:       1.0 Hz
minimum GPS time coverage:      0.99
```

The initial implementation also exposes an implausible-speed ceiling and
minimum per-bin distance support. Their values are exploratory parameters and
must be recorded rather than treated as stable contract constants.

These thresholds are provisional. During exploratory work, failing them should
default to a warning rather than a hard preprocessing failure. The result may
still be generated when minimally viable, but its status and unsupported
regions must be explicit.

`minimum_gps_coverage_ratio` refers to session time coverage under the active
GPS gap policy, not to an assumption that GPS samples are uniformly spaced.

### 6.3 Required checks

Distance construction should diagnose at least:

- non-finite time, position, or recorded-distance values;
- duplicate timestamps;
- distance reversals and counter resets;
- implausible distance jumps or implied speed;
- stationary or non-increasing spans;
- source gaps beyond the configured interpolation limit;
- incomplete session coverage; and
- insufficient distinct observations.

For GPS-geometry candidates, diagnostics must also include the undenoised path
length and the denoising policy used to establish the cumulative coordinate.

Repair behavior must be explicit and versioned. Long gaps must remain invalid
support; they must not be bridged merely to make the spatial grid continuous.
Logger GPS streams that repeat one asynchronous fix across many primary rows
may be collapsed to distinct observations before implied-speed checks; the
observation filter and collapsed-row count must be recorded.

---

## 7. Metric Semantics

### 7.1 Gradient

The canonical smoothed gradient field is:

```text
gradient_fraction
```

It is dimensionless and represents local `dz/ds`. A value of `-0.20` means a
20 percent descent in the session direction.

Version 0 uses GPS altitude. The local estimator must fit altitude against
distance over a configurable neighbourhood. It must not differentiate raw
point-to-point altitude directly.

The optional local estimator output is:

```text
gradient_fraction_local
```

IMU pitch may become supporting or comparative evidence later, but it must not
silently change the meaning or source of the version 0 gradient field.

### 7.2 Twistiness

The canonical twistiness field is:

```text
twistiness_rad_per_m
```

It is a centred spatial aggregate of local curvature magnitude. GPS geometry
must be denoised before the magnitude operation: smoothing curvature magnitude
afterward cannot cancel short-scale left/right position error.

The optional local field is:

```text
curvature_abs_rad_per_m_local
```

The geometry estimator, source-observation input policy, coordinate
transformation, neighbourhood, fit weighting, robust-fit parameters, smoothing
kernel, smoothing distance, and local-polynomial order must be recorded.

The local polynomial must be fit directly to the independent source-position
observations in its centred distance window. Interpolated spatial-grid rows are
evaluation locations, not additional observations. The polynomial derivatives
are evaluated analytically and combined with the standard planar parametric
curvature equation.

Curvature is not valid merely because a polynomial can be fit mathematically.
For a polynomial order `p`, the window must contain at least `p + 1` usable
independent positions and meet the configured observation minimum. Its
equivalent odd spatial-grid support window must contain at least `2p + 1` rows
and be no shorter than the configured geometry window. With the recommended
0.5 m grid, 20 m window, and order 2, the support window is 41 rows.

When full-window validity is enabled, a contiguous supported run shorter than
the effective window produces no twistiness. On longer runs, the first and last
half-window are null so every emitted local curvature value has a complete
centred neighbourhood. For the recommended values this excludes 20 rows, or 10 m,
at each discontinuity boundary.

Each eligible geometry window must also contain a configured minimum number of
distinct supported source-position observations. The minimum must be at least
3; the initial exploratory hard minimum is 3. The recommended 20 m geometry
window should normally contain substantially more than that minimum.

The complete-window rule is evaluated against genuine geometry continuity
before applying this per-centre observation-count threshold. Rows below the
observation minimum become null individually; they do not split the underlying
geometry run or cause the half-window boundary exclusion to be applied again.

These exclusions apply before smoothing. Excluded values remain null rather
than zero, and smoothing must neither fill nor bridge the resulting gaps.

The exploratory fit uses tricube distance weighting, optional inverse-variance
weighting from receiver horizontal accuracy with a configurable accuracy floor,
and iterative robust residual weighting. Missing receiver accuracy must not
make the estimator unavailable; it falls back to distance and robust weighting.

### 7.3 Suspension activity

Suspension activity is cumulative absolute wheel movement divided by ground
distance. It is dimensionless when both quantities use the same length unit.

Canonical smoothed fields are:

```text
front_suspension_activity
rear_suspension_activity
```

Optional local fields are:

```text
front_suspension_activity_local
rear_suspension_activity_local
```

The local activity calculation must use all eligible native-rate filtered
displacement samples. It must not calculate absolute motion from displacement
that has first been resampled onto the coarser spatial grid.

For adjacent native-rate samples:

```text
movement_increment = abs(displacement[i] - displacement[i - 1])
```

The movement increment is mapped through the time-to-distance relation and
allocated to the spatial distance it represents. If an interval crosses more
than one spatial bin, implementations should allocate it proportionally across
those bins rather than assigning all motion to one bin.

Intervals with invalid distance support, non-increasing distance, excessive
GPS gaps, invalid displacement, or an ineligible active mask do not contribute
movement or denominator distance.

A bin with insufficient evidence must be `NaN`/null, not zero. Zero means that
valid evidence was present and no wheel motion was measured.

The minimum local activity-support fraction is effective configuration and
must be applied before spatial smoothing.

### 7.4 Combined suspension activity

`combined_suspension_activity` is optional and derived. The initial supported
method is the arithmetic mean of front and rear activity:

```text
(front_suspension_activity + rear_suspension_activity) / 2
```

It may be emitted only where both wheel-domain inputs are available and valid.
The combination method must be recorded. No arbitrary scaling constant may be
used to balance front and rear values.

---

## 8. Stream Dataframe Contract v1

### 8.1 Identity

Recommended persisted stream name:

```text
spatial_context
```

Recommended stream metadata schema:

```text
bodaqs.spatial_context_stream
```

Version:

```text
1
```

### 8.2 Required dataframe columns

| column | type | unit | meaning |
|---|---|---|---|
| `distance_m` | float | m | Monotonic regular spatial coordinate |
| `representative_time_s` | float/null | s | Representative session-relative time for valid mapping |
| `distance_support_fraction` | float | 1 | Fraction of the grid cell supported by valid distance evidence |

`distance_m` must be unique and strictly increasing within the materialized
stream. `distance_support_fraction` must lie within `[0, 1]`.

For the canonical whole-session stream, `distance_m` is session cumulative
distance. In a track-scoped result, it is the same session-derived coordinate
rebased at the selected traversal start.

### 8.3 Optional metric columns

| column | type | unit | meaning |
|---|---|---|---|
| `gradient_fraction_local` | float/null | 1 | Local altitude-vs-distance slope estimate |
| `gradient_fraction` | float/null | 1 | Spatially smoothed gradient |
| `curvature_abs_rad_per_m_local` | float/null | rad/m | Local curvature magnitude |
| `twistiness_rad_per_m` | float/null | rad/m | Spatially smoothed curvature magnitude |
| `twistiness_source_observation_count` | integer | count | Distinct supported source-position observations in the centred geometry window |
| `front_suspension_activity_local` | float/null | 1 | Front-wheel movement per valid ground metre in the grid cell |
| `front_suspension_activity` | float/null | 1 | Spatially smoothed front activity |
| `rear_suspension_activity_local` | float/null | 1 | Rear-wheel movement per valid ground metre in the grid cell |
| `rear_suspension_activity` | float/null | 1 | Spatially smoothed rear activity |
| `combined_suspension_activity` | float/null | 1 | Optional derived front/rear combination |
| `front_activity_support_fraction` | float/null | 1 | Eligible front evidence coverage in the grid cell |
| `rear_activity_support_fraction` | float/null | 1 | Eligible rear evidence coverage in the grid cell |

Metric columns may be absent when their required evidence cannot be resolved.
Consumers must distinguish an absent metric from a present metric containing
null regions.

### 8.4 Optional track-scope coordinate columns

| column | type | unit | meaning |
|---|---|---|---|
| `session_distance_m` | float | m | Original whole-session distance before track-scope rebasing |
| `track_station_m` | float/null | m | Sequence-matched directed track station used as alignment evidence |

These columns are present only in a track-scoped result. They are coordinate
or QC evidence rather than spatial-context metrics.

### 8.5 Signal registry

Every numeric metric intended for semantic selection must have a signal entry
in the stream-local `signals` registry. Registry entries should include:

- `quantity`;
- `unit`;
- `domain: "spatial_context"`;
- `processing_role`;
- source columns or selectors;
- derivation method and parameters; and
- algorithm version.

Coordinate and support columns may be marked as coordinate/QC fields rather
than selectable analysis signals.

---

## 9. Stream Metadata Contract v1

A persisted stream metadata document should have this overall shape:

```json
{
  "schema": "bodaqs.spatial_context_stream",
  "version": 1,
  "stream_name": "spatial_context",
  "kind": "derived",
  "coordinate": {
    "column": "distance_m",
    "unit": "m",
    "spacing_m": 0.5,
    "domain": "session_cumulative_distance"
  },
  "status": "succeeded",
  "effective_config": {},
  "distance_source": {},
  "time_mapping": {},
  "track_scope": {
    "mode": "track_traversal",
    "metric_source": "session",
    "coordinate_source": "session_distance",
    "track_ref": {"track_id": "pipenhot", "revision": 3},
    "traversal_selection": "last_forward_traversal",
    "status": "matched",
    "effective_config": {},
    "matching": {},
    "traversals": [],
    "selected_traversal": {}
  },
  "metric_provenance": {},
  "quality": {},
  "signals": {},
  "warnings": []
}
```

Recommended `status` values are:

```text
succeeded | partial | unavailable | failed
```

Required metadata behavior:

- `effective_config` contains the normalized configuration actually used, not
  merely a profile reference.
- `distance_source` records all evaluated candidates and the selected source.
- `time_mapping` records interpolation method, maximum gap, valid intervals,
  and mapping coverage.
- `track_scope`, when present, records track identity and revision, selection
  policy, effective matching thresholds, sequence-matcher diagnostics, all
  qualifying forward traversals, and the selected traversal.
- `metric_provenance` records estimator and smoothing details per metric.
- suspension provenance includes the concrete filtered displacement signal,
  its motion-derivation/filter metadata, wheel-domain transform provenance, and
  active-mask provenance.
- `quality` records observed GPS cadence, coverage, support, repairs, and metric
  availability.
- `warnings` uses stable machine-readable warning codes where practical.

A stream may have `partial` status when some metrics are available and others
are omitted. For example, missing altitude may omit gradient without preventing
twistiness or front activity.

---

## 10. Spatial Smoothing

Version 0 supports a centred spatial exponential kernel:

```text
weight(delta_s) = exp(-abs(delta_s) / smoothing_distance_m)
```

Each metric owns its smoothing distance. Initial exploratory hypotheses are:

| metric | initial smoothing distance |
|---|---:|
| gradient | 10-20 m |
| twistiness | 10-20 m |
| suspension activity | 3-5 m |

These are notebook defaults, not contract constants.

Smoothing must be support-aware. Invalid or unsupported samples must not be
treated as zero. Implementations should expose or record minimum support rules
and must not smooth across gaps that exceed the configured gap policy.

---

## 11. Persistence And Exploratory Variants

The notebook may calculate many in-memory variants during parameter
exploration. A persisted canonical `spatial_context` stream represents one
exact whole-session effective configuration. Track-scoped views are initially
post-processing results and must not overwrite that canonical stream.

Implementations must not silently overwrite an existing persisted stream with
different semantics. Until a multi-variant naming contract is introduced, the
safe options are:

- explicitly replace the stream as part of reprocessing the session; or
- retain alternative variants as notebook-local/in-memory results.

The source session data remains authoritative and must permit historical
sessions to be reprocessed when algorithms or defaults change.

---

## 12. Compatibility And Consumer Behavior

- Existing sessions without a spatial-context stream remain valid.
- Consumers must treat stream absence as feature unavailability, not as zero
  context values.
- Unknown metric columns and metadata fields may be ignored.
- Consumers must reject unsupported stream schema versions when interpreting
  metric semantics.
- Read-only hosted or static consumers may display a precomputed stream but are
  not required to derive or persist one.
- Future APIs should window this stream by distance without changing the
  existing time-series window contract.
- A distance selection may map to one or more valid time ranges when source
  gaps exist. Consumers must not fabricate a continuous time selection through
  unsupported intervals.
- Consumers must treat track scope as row selection and coordinate rebasing,
  not as permission to substitute track-derived metric values.
- Failure to find a qualifying traversal produces an explicit unavailable
  scoped result; it must not silently fall back to a different traversal or the
  whole session.

---

## 13. Validation Invariants

A conforming implementation should test at least these invariants:

1. `distance_m` is finite, unique, and strictly increasing.
2. Identical motion per travelled metre is approximately invariant to traversal
   speed and native suspension sample rate.
3. Coarsening the spatial output grid does not discard native-rate movement
   before accumulation.
4. Alternating signed curvature at spatial scales retained by the geometry fit
   does not cancel twistiness.
5. A twistiness run shorter than its effective geometry window is entirely
   null, and full-window edge exclusions are enforced at discontinuities.
6. Twistiness is null where the configured minimum distinct source-position
   observation count is not met.
7. Short-wavelength source-position zig-zag is attenuated by the geometry fit
   before curvature magnitude is calculated.
8. Rear activity is absent when only rear-shock-domain displacement exists.
9. Unsupported bins are null rather than zero.
10. Changing a filter, selector, estimator, smoothing distance, source, or
   algorithm version changes recorded provenance.
11. Disabling spatial-context derivation leaves existing preprocessing outputs
   unchanged.
12. `last_forward_traversal` selects the chronologically last qualifying
    forward pass when a session contains repeated passes.
13. Track scoping does not change metric values for retained whole-session rows.
14. Sequence-aware projection does not jump between distant track stations at
    an overlapping or self-near section merely because the local distances tie.

---

## 14. Deferred Decisions

The following remain deliberately open during the Jupyter prototype:

- final local projection and curvature estimator;
- exact distance-reset and implausible-jump repair policy;
- the empirical GPS usability boundary;
- whether a second canonical smoothing scale is justified;
- use of IMU pitch as gradient support or validation;
- wheel-odometry source priority and fusion;
- persistence of multiple parameter variants;
- API request/response shapes for spatial windows;
- saved distance-range queries and bookmarks; and
- combining several traversals into one spatial coordinate;
- automatic fallback to partial-track traversals; and
- change-point, classification, and region contracts.
