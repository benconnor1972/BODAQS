# BODAQS Scenario And Episode Contract v0 Draft

**Status:** Draft  
**Scope:** Reusable condition definitions and their matched occurrences within processed sessions  
**Audience:** BODAQS web application, Library API service, analysis-library, and notebook implementers

---

## 1. Purpose

A **Scenario** describes a meaningful riding or operating situation using one
or more criteria over processed data. Examples include:

- steep, twisty terrain;
- high suspension activity while descending;
- braking on rough terrain; and
- unbraked high-speed cornering.

An **Episode** is one continuous occurrence of a Scenario within one session.
Evaluating a Scenario against a set of sessions returns zero or more Episodes
per session.

Scenarios may use:

- distance-domain spatial-context metrics;
- time-domain session signals;
- boolean or categorical processed signals where supported; and
- combinations of criteria from more than one source or coordinate domain.

The contract separates:

1. the reusable Scenario definition;
2. an evaluation of that definition against a specified scope and artifact
   state; and
3. the Episodes produced by that evaluation.

This separation permits a Scenario to be reused, revised, compared with other
Scenarios, or evaluated again after preprocessing changes without treating an
old result as current evidence.

---

## 2. Terminology

| Term | Meaning |
|---|---|
| Scenario | A named, reusable definition of conditions of interest |
| Criterion | One condition evaluated against one resolved data series |
| Episode | One continuous session occurrence satisfying a Scenario |
| Evaluation | The act and recorded result of applying a Scenario to an explicit session scope |
| Restriction | Using matching Episodes to limit the evidence included in an analysis |
| Scenario facet | Treating one Scenario result as a labelled comparison population |
| Exposure | Included duration and, where known, included distance represented by Episodes |

“Scenario” and “Episode” are the preferred product and user-interface terms.
Implementations may use interval, range, run, mask, or bounds internally where
those terms make algorithms clearer.

---

## 3. Relationship To Existing Concepts

### 3.1 Session filters

A `bodaqs.session_filter` selects whole sessions using catalog or API-backed
session properties. It does not identify occurrences inside a session.

A Scenario operates within sessions. It must not be stored as, or silently
converted into, a session filter. A session-filtered set may be used as the
input scope of a Scenario evaluation.

### 3.2 Study Sets and groupings

A Study Set defines explicit session membership. Evaluating or applying a
Scenario does not alter that membership. Study Set groupings remain collections
of sessions and are independent of Scenario facets.

### 3.3 Spatial context

The canonical `spatial_context` stream contains continuous session-derived
fields over cumulative session distance. Thresholds and named terrain classes
are deliberately downstream of that stream. Scenarios are the downstream
concept that may turn those fields into meaningful occurrences.

Scenario evaluation must consume the persisted metric values and their
validity boundaries. It must not silently derive a different smoothing variant.
Notebook-only metric variants may be evaluated as explicitly in-memory
Scenarios, but they are not equivalent to canonical persisted evidence.

### 3.4 Events, metrics, and SegmentBundles

An Episode is not a detected Event and does not receive an Event Table row
unless a future explicit conversion operation is defined.

An Episode is also not a `SegmentBundle`. SegmentBundles are fixed-length,
event-centred extraction inputs for metric computation. Episodes are
variable-length occurrences used primarily for selection, comparison, and
visualisation.

---

## 4. Scenario Definition

Canonical persisted schema name:

```text
bodaqs.scenario
```

Version 0 example:

```json
{
  "schema": "bodaqs.scenario",
  "version": 1,
  "scenario_id": "steep-twisty-braking",
  "revision": 3,
  "display_name": "Steep, twisty braking",
  "description": "Braking while descending through relatively tight terrain.",
  "category": "riding-context",
  "predicate": {
    "op": "and",
    "children": [
      {
        "criterion_id": "descending",
        "series": {
          "stream_name": "spatial_context",
          "column": "gradient_fraction"
        },
        "op": "lte",
        "value": -0.08
      },
      {
        "criterion_id": "twisty",
        "series": {
          "stream_name": "spatial_context",
          "column": "twistiness_rad_per_m"
        },
        "op": "gte",
        "value": 0.04
      },
      {
        "criterion_id": "rear-brake",
        "series": {
          "stream_name": "primary",
          "selector": {
            "control": "rear_brake",
            "quantity": "application"
          }
        },
        "op": "gte",
        "value": 0.2
      }
    ]
  },
  "episode_policy": {
    "minimum_duration_s": 0.5,
    "minimum_distance_m": null,
    "bridge_gap_s": 0.0,
    "bridge_gap_m": null
  },
  "eligibility_policy": {
    "activity": "require_active"
  },
  "provenance": {
    "created_at": "2026-09-09T04:00:00Z",
    "created_by": "user",
    "updated_at": "2026-09-09T04:15:00Z"
  },
  "display_state": {
    "bodaqs_web_v1": {}
  }
}
```

Validation rules:

- `schema` must be `bodaqs.scenario`.
- `version` must be supported by the evaluator.
- `scenario_id` must be stable and filename-safe when persisted.
- `revision` is assigned and incremented by the persistence service.
- `predicate` is required and must contain at least one criterion.
- every `criterion_id` must be unique within the Scenario.
- omitted `eligibility_policy.activity` defaults to `require_active`.
- `display_state` is optional, non-authoritative UI state.
- provenance timestamps do not determine evaluation currency; artifact and
  definition identities do.

The canonical root-scoped storage location, if Scenario persistence is enabled,
is:

```text
<libraries_root>/
  scenarios/
    <scenario_id>.json
```

An ad-hoc Scenario may use the same definition shape without a revision or
persisted file.

---

## 5. Predicate Model

Predicates are recursive. Version 0 group operators are:

```text
and | or
```

Example group:

```json
{
  "op": "or",
  "children": []
}
```

An empty group is invalid. `not` is deferred because missing evidence requires
three-valued logic and must not be converted accidentally into a positive
match.

All criteria are evaluated in their native source domain before their matching
regions are mapped to session time. Group operations are then performed over
the mapped session-time regions.

For `and`, an occurrence must satisfy every child predicate. For `or`, an
occurrence may satisfy any child predicate. Grouping controls Boolean meaning;
it does not control display facets.

---

## 6. Criterion Contract

A criterion contains:

```json
{
  "criterion_id": "high-front-activity",
  "series": {
    "stream_name": "spatial_context",
    "column": "front_suspension_activity"
  },
  "op": "gte",
  "value": 12.0
}
```

### 6.1 Series references

A series reference must identify exactly one processed series using either:

- an explicit `column`; or
- a semantic `selector` resolved through registered signal metadata.

```json
{
  "stream_name": "primary",
  "selector": {
    "end": "rear",
    "domain": "control",
    "quantity": "brake_application"
  }
}
```

`stream_name` is required. `primary` identifies the canonical session
dataframe; other names identify registered materialised streams such as
`spatial_context`.

Resolution is authoritative in the Python Library API or analysis library.
The evaluator must record the resolved stream, column, units, coordinate
column, coordinate unit, and relevant signal metadata. A browser must not
resolve a selector differently from the service.

Selectors are preferable for stable semantic concepts. Explicit columns are
appropriate for exploratory, diagnostic, or source-specific Scenarios.

### 6.2 Numeric operators

Version 0 numeric operators are:

```text
lt | lte | gt | gte | between | outside
```

Single-threshold operators require `value`.

Range operators require:

```json
{
  "criterion_id": "moderate-descent",
  "series": {
    "stream_name": "spatial_context",
    "column": "gradient_fraction"
  },
  "op": "between",
  "range": {
    "lower": -0.15,
    "upper": -0.05,
    "include_lower": true,
    "include_upper": true
  }
}
```

`lower` must not exceed `upper`. Units are those of the resolved series;
implicit unit conversion is not permitted in version 0.

### 6.3 Boolean and categorical operators

Version 0 also reserves:

```text
eq | in | present
```

These are intended for boolean or categorical processed series. `present`
tests whether usable evidence exists at a coordinate; it does not test whether
the entire stream exists for the session.

### 6.4 Value transforms

Version 0 evaluates the stored series value directly. Arbitrary formulas,
rolling calculations, user code, and implicit re-smoothing are not supported.

An `absolute` value transform may be added before canonicalisation if required
for an initial use case, but it must be explicit in the criterion and recorded
in evaluation provenance. It must not change the stored source series.

---

## 7. Native-Domain Evaluation

### 7.1 Coordinate discovery

The evaluator determines the native coordinate from stream metadata:

- primary and ordinary time-series streams normally use session-relative time;
- `spatial_context` uses session cumulative distance and supplies
  `representative_time_s` as its mapping to session time.

The Scenario does not force every input onto one common sample grid.

### 7.2 Validity

A sample is eligible only when:

- its coordinate is finite;
- its value is usable for the requested operator;
- the stream marks it valid or supported under its own contract; and
- the coordinate-to-time mapping is valid.

Null, NaN, unsupported, inactive, and discontinuity-boundary values are not
false samples that may be bridged freely. They are unknown evidence and create
hard boundaries unless a source contract explicitly says otherwise.

Spatial-context criteria inherit `active_mask_qc`, source-window, smoothing,
and track-cut boundaries already represented by the canonical stream. Scenario
evaluation must not fill those gaps.

### 7.3 Scenario activity eligibility

The initial activity policies are:

```text
require_active | ignore
```

`require_active` is the default. It applies the session's canonical
`active_mask_qc` as eligibility evidence for the complete Scenario, including
criteria from ordinary time-domain signals. Inactive runs and transitions are
hard boundaries that cannot be bridged. If the mask is unavailable, evaluation
of that session is unavailable rather than treating every sample as active.

`ignore` is an explicit opt-out for a Scenario that genuinely needs inactive
evidence. It does not override validity rules already embodied in a derived
source such as `spatial_context`; it merely avoids adding a separate global
activity restriction.

### 7.4 Forming matching regions

Pointwise criterion results are converted into continuous native-coordinate
regions. Version 0 must record the intervalisation method used.

Recommended defaults are:

- numeric continuous signals: linearly interpolate a threshold crossing
  between adjacent finite samples;
- boolean or categorical signals: step semantics;
- regular spatial bin centres: use the represented cell edges, clipped to
  valid support; and
- never span a source discontinuity or a gap exceeding the source's effective
  maximum-gap policy.

Implementations may initially use conservative sample-edge boundaries instead
of interpolated crossings, but this must be explicit and stable for the
evaluation algorithm version.

### 7.5 Mapping to session time

Each native matching region is mapped to session-relative time before Boolean
combination with criteria from another domain.

For spatial context, mapping uses the canonical `representative_time_s`
evidence and its piecewise valid intervals. Mapping must not interpolate across
unsupported GPS gaps, inactivity boundaries, or other recorded continuity
breaks.

Session time is the mandatory interchange coordinate because downstream
full-resolution signals are time-domain evidence. Native distance bounds are
retained when available; distance is not discarded merely because combination
occurs in time.

---

## 8. Missing Evidence And Three-Valued Semantics

Criterion evaluation has three logical states at a location:

```text
true | false | unknown
```

Unknown includes:

- missing streams or columns;
- unresolved selectors;
- null or invalid samples;
- unsupported spatial cells;
- invalid coordinate mapping; and
- gaps beyond the source continuity policy.

Group semantics are:

| Operation | Rule |
|---|---|
| `and` | false if any child is false; true if all are true; otherwise unknown |
| `or` | true if any child is true; false if all are false; otherwise unknown |

Only true regions produce Episodes. Unknown regions do not match and remain
visible in evaluation diagnostics.

A session with missing required evidence is not silently treated as entirely
false or entirely matching. Its evaluation status is `partial` or
`unavailable`, with criterion-specific reasons.

---

## 9. Episode Formation

After the complete predicate has been evaluated, adjacent true regions become
candidate Episodes. Episode shaping is then applied in this order:

1. preserve hard validity and continuity boundaries;
2. optionally bridge eligible short false gaps;
3. discard occurrences below configured minimum exposure; and
4. assign deterministic order and identifiers.

### 9.1 Gap bridging

`bridge_gap_s` may merge two matching regions separated by a known false gap
no longer than the configured duration. `bridge_gap_m` provides the analogous
rule when distance evidence is available.

Unknown or discontinuous gaps must never be bridged. When both limits are
specified, both must be satisfied.

### 9.2 Minimum exposure

`minimum_duration_s` removes candidate Episodes shorter than the configured
duration. `minimum_distance_m` removes candidates with insufficient known
distance exposure.

When both limits are present, both must be satisfied. A minimum-distance rule
cannot be evaluated without adequate distance mapping; that candidate is
unknown, not accepted using duration alone.

Null means that the corresponding shaping rule is disabled. Values must be
finite and non-negative.

### 9.3 Boundary convention

Episode time bounds use half-open intervals:

```text
[start_time_s, end_time_s)
```

The exclusive end bound must include the represented support of a final
matching observation where appropriate. Consumers use half-open membership to
prevent double counting adjacent Episodes.

---

## 10. Scenario Evaluation Request

An evaluation request identifies an immutable Scenario definition or a saved
Scenario reference and an explicit session scope.

Example:

```json
{
  "schema": "bodaqs.scenario_evaluation_request",
  "version": 1,
  "scenario_ref": {
    "scenario_id": "steep-twisty-braking",
    "revision": 3
  },
  "sessions": [
    {
      "library_id": "default-library",
      "session_key": "run-1::session-1",
      "run_id": "run-1",
      "session_id": "session-1"
    }
  ],
  "options": {
    "include_criterion_diagnostics": true
  }
}
```

Exactly one of `scenario_ref` or an embedded `scenario` definition is required.
A saved reference should include `revision` so an edited Scenario cannot alter
an in-flight or cached evaluation.

The initial application may evaluate only explicit Study Set session
references. Root-wide catalog or session-filter scopes may later use an
asynchronous job without changing Scenario or Episode semantics.

---

## 11. Evaluation Result

Canonical result schema:

```text
bodaqs.scenario_evaluation
```

Example:

```json
{
  "schema": "bodaqs.scenario_evaluation",
  "version": 1,
  "evaluation_id": "scenario-eval-4d72",
  "status": "succeeded",
  "scenario": {
    "scenario_id": "steep-twisty-braking",
    "revision": 3,
    "display_name": "Steep, twisty braking"
  },
  "algorithm_version": 1,
  "sessions": [
    {
      "session_ref": {
        "library_id": "default-library",
        "session_key": "run-1::session-1",
        "run_id": "run-1",
        "session_id": "session-1"
      },
      "status": "succeeded",
      "episode_count": 2,
      "matched_duration_s": 8.4,
      "matched_distance_m": 72.5,
      "episodes": [
        {
          "episode_id": "episode-0001",
          "ordinal": 1,
          "start_time_s": 82.4,
          "end_time_s": 86.1,
          "duration_s": 3.7,
          "start_distance_m": 612.0,
          "end_distance_m": 645.5,
          "distance_m": 33.5,
          "continuity": {
            "source_groups": ["spatial-context-4", "primary-1"]
          }
        }
      ],
      "criteria": [
        {
          "criterion_id": "twisty",
          "status": "succeeded",
          "resolved_series": {
            "stream_name": "spatial_context",
            "column": "twistiness_rad_per_m",
            "unit": "rad/m",
            "coordinate_column": "distance_m",
            "coordinate_unit": "m"
          },
          "true_duration_s": 12.1,
          "unknown_duration_s": 1.5,
          "warnings": []
        }
      ],
      "warnings": []
    }
  ],
  "summary": {
    "requested_session_count": 1,
    "evaluated_session_count": 1,
    "matched_session_count": 1,
    "episode_count": 2,
    "matched_duration_s": 8.4,
    "matched_distance_m": 72.5
  },
  "provenance": {
    "scenario_definition_digest": "sha256:...",
    "input_artifacts": [],
    "evaluated_at": "2026-09-09T04:30:00Z"
  },
  "warnings": []
}
```

### 11.1 Status

Evaluation and per-session status vocabulary is:

```text
queued | running | succeeded | partial | unavailable | failed | cancelled
```

Synchronous evaluation normally returns `succeeded`, `partial`, or
`unavailable`. Job states permit the same result contract to support broad or
expensive scopes later.

### 11.2 Episode identity

An Episode identifier is stable only within one immutable evaluation identity.
It may be derived from the evaluation identity, session reference, bounds, and
ordinal. Re-evaluation after a Scenario, algorithm, source artifact, or
preprocessing change may produce different Episode identifiers.

An Episode is not a root-scoped mutable resource in version 0.

### 11.3 Exposure accounting

The result reports matched duration for every successful session and matched
distance when it can be measured without crossing unknown mapping regions.

Exposure totals must avoid double counting overlapping Episodes produced by
the same Scenario evaluation. Results from different Scenarios may overlap and
must not be assumed additive.

---

## 12. Provenance And Cache Identity

A conforming evaluator records or makes reproducible:

- the complete effective Scenario definition;
- saved Scenario id and revision, when applicable;
- a deterministic definition digest;
- evaluator algorithm version;
- resolved series and signal metadata;
- input artifact paths, identities, revisions, or fingerprints;
- spatial-context algorithm and effective configuration when consumed;
- intervalisation and coordinate-mapping policy;
- effective Scenario activity-eligibility policy;
- episode shaping policy; and
- warnings and unavailable evidence.

Cache identity must include at least:

- effective Scenario definition digest;
- evaluator algorithm version;
- every session reference;
- input artifact fingerprints;
- relevant track identity and revision if future track-coordinate mapping is
  requested; and
- response-detail options that change the result shape.

Editing a Scenario, reprocessing a session, replacing a spatial-context stream,
or changing a resolved signal must invalidate the affected result.

---

## 13. Application To Analysis Views

Scenario application is non-destructive. It does not modify a Study Set,
session, event table, metrics table, or source signal.

### 13.1 Continuous samples

For continuous-signal analysis, a sample is included when its session-relative
time lies inside a selected Episode. Lines and trajectories must break between
Episodes and across internal continuity gaps. Phase plots must not draw a line
from the end of one Episode to the start of another.

### 13.2 Events and event metrics

The version 0 default is **anchor inclusion**: an Event or its joined Metrics
row is included when the Event's primary trigger time lies within an Episode.
This agrees with the initial track-sector behaviour.

Consumers must use the Event Table to resolve an anchor when a Metrics row does
not carry one. Rows without a resolvable anchor are excluded with diagnostics.

Future policies may include `any_overlap` and `fully_contained`. Such policies
must be explicit because an event-derived metric may use evidence outside the
matching Episode even when its trigger lies inside.

### 13.3 Restriction versus faceting

Restriction and faceting are separate operations:

- **restrict by Scenario** limits analysis evidence to matching Episodes;
- **facet by Scenario** evaluates each selected Scenario as an independent,
  labelled comparison population.

A view may first apply a restriction and then facet the remaining evidence by
other Scenarios. The effective population of a facet is the intersection of
the base restriction and that facet's Episodes.

Scenario facets may overlap. A sample or Event may therefore appear in more
than one facet. The application must not imply that facet counts are mutually
exclusive or additive unless disjointness has been established.

### 13.4 Existing analysis dimensions

Scenario is an additional analysis dimension alongside:

- session or Study Set grouping;
- suspension end;
- track sector;
- manual time scope; and
- other view-specific series dimensions.

The contract does not require a view to render the Cartesian product of every
dimension. A view may limit active facet dimensions while preserving the
underlying selection semantics.

### 13.5 Exposure-aware comparisons

Views that compare counts should display or use matched exposure. Raw counts
from Scenarios with different included duration or distance are not directly
comparable. Suitable derived presentations may include:

- events per active minute;
- events per 100 metres;
- sample distributions normalised within each Scenario; and
- both count and exposure shown together.

The analysis view must identify whether a statistic is a count, proportion,
time-normalised rate, or distance-normalised rate.

---

## 14. Track And Distance Semantics

Canonical Scenario evaluation is session-based. A spatial criterion uses the
session's persisted spatial-context metric and session cumulative distance.
It does not substitute reusable track geometry or a track-derived metric.

An Episode may later carry optional track station bounds when a specified
track traversal has been matched. Those bounds are alignment annotations, not
the evidence used to evaluate session-derived metrics.

Displaying Scenario evidence in Track Analysis does not itself require
track-scoped evaluation. Cross-session overlays on a common track-station axis
do require an explicit session-to-track traversal mapping and are outside the
initial contract.

---

## 15. API And Execution Guidance

The contract does not mandate exact endpoint paths. A Library API implementation
should support:

- resolving and validating a Scenario definition;
- evaluating it against explicit session references;
- returning compact Episode results without returning every source sample;
- optionally returning criterion diagnostics;
- caching immutable evaluations; and
- asynchronous, paged execution for broad scopes when needed.

The initial Study Set use case may be synchronous when session count and source
size are bounded. The service should retain the option to promote the same
request to a job rather than creating different semantics for root-wide use.

Spatial metric visualisation is a related but separate data query. It should
return distance-native spatial series rather than embedding all chart samples
in every Scenario evaluation result.

---

## 16. Compatibility And Migration

- Existing session filters remain valid and unchanged.
- Existing Study Sets and groupings remain valid and unchanged.
- Existing Events, Metrics Tables, SegmentBundles, tracks, and bookmarks are
  not migrated into Scenarios.
- Sessions without a materialised spatial-context stream may still satisfy
  Scenarios that use only available time-domain signals, provided their
  activity eligibility evidence is also available or explicitly ignored.
- A spatial criterion against a legacy session without spatial context is
  unavailable, not false.
- Read-only hosted or demo deployments may evaluate Scenarios if their bundles
  include the required processed artifacts. They need not support Scenario
  persistence.
- Saved Scenario definitions may be portable across libraries roots only when
  their semantic selectors can resolve there. Explicit source columns reduce
  portability.

---

## 17. Performance Requirements

Evaluation should occur in Python or another authoritative service layer, not
by downloading every candidate signal into the browser.

Implementations should:

- read only required coordinates, values, validity, and mapping columns;
- evaluate and cache per session where practical;
- compose multi-session results from per-session cache entries;
- return Episodes rather than full boolean masks by default;
- impose explicit limits on session count, returned Episodes, diagnostics, and
  source rows for synchronous requests;
- preserve native-resolution evidence when evaluating high-rate signals; and
- avoid resampling high-rate suspension or rider-input data onto the coarser
  spatial grid.

An initial pandas/NumPy implementation is acceptable. Persistent indexes or a
columnar query engine should be introduced only if measured workloads justify
them.

---

## 18. Quality And Diagnostics

At minimum, per-session diagnostics should distinguish:

- no Episodes because the predicate was known false;
- no Episodes after minimum-exposure shaping;
- unavailable source stream;
- unresolved selector;
- unsupported or invalid source evidence;
- unavailable distance-to-time mapping;
- excessive source or mapping gaps;
- evaluation limit exceeded; and
- internal evaluation failure.

Warnings should use stable machine-readable codes where practical. A zero-match
result is not itself a warning or failure.

---

## 19. Conformance Tests

A conforming implementation should test at least:

1. a single time-domain numeric criterion produces expected Episode bounds;
2. a single spatial criterion maps distance regions to valid session times;
3. a mixed time-and-distance `and` predicate intersects correctly;
4. an `or` predicate unions and coalesces overlapping matches;
5. unknown evidence does not produce matches;
6. `and` and `or` follow the specified three-valued truth table;
7. no Episode crosses a source discontinuity or active-mask boundary;
8. `require_active` makes a missing activity mask unavailable while `ignore`
   permits otherwise valid time-domain evaluation;
9. eligible short false gaps are bridged only within configured limits;
10. unknown gaps are never bridged;
11. minimum duration and distance policies are applied after bridging;
12. adjacent half-open Episodes do not double count boundary samples;
13. native high-rate signal samples are not replaced by spatial-grid samples;
14. event and Metrics rows use the resolved primary trigger-time policy;
15. phase trajectories break between Episodes;
16. exposure totals do not double count overlapping Episodes within one
    evaluation;
17. two overlapping Scenario facets may legitimately include the same sample
    or Event;
18. cache identity changes after Scenario revision or input artifact change;
19. a missing spatial stream does not prevent a time-signal-only Scenario;
20. read-only evaluation does not write Scenario or session artifacts; and
21. deterministic inputs produce deterministic Episode ordering and identity.

The spatial-context regression corpus should supply initial physical evidence
for spatial-only and mixed-domain evaluation tests. Synthetic cases should
cover exact boundaries, missing evidence, Boolean truth tables, and gap
shaping.

---

## 20. Initial Scope And Deferred Decisions

Recommended version 0 core:

- ad-hoc Scenario definitions using a persistence-compatible shape, with
  optional root-scoped persistence;
- explicit Study Set session scopes;
- numeric spatial-context and primary-signal criteria;
- recursive `and` and `or` groups;
- session-time interchange and optional distance bounds;
- minimum exposure and conservative gap bridging;
- compact Episode results with provenance and diagnostics;
- application as one analysis restriction; and
- data shapes that permit later Scenario faceting.

Deferred:

- `not` predicates;
- arbitrary formulas and user-defined transforms;
- rolling-window criteria defined inside a Scenario;
- categorical operators beyond demonstrated processed signals;
- automatic terrain or manoeuvre classification;
- conversion of Episodes into Events or SegmentBundles;
- mutable or manually edited Episode resources;
- automatic persistence of evaluation results;
- root-wide live Scenario membership;
- persistent query indexes before performance evidence exists;
- common track-station overlays across sessions;
- UI rules for combining all possible facet dimensions; and
- permissions and sharing for hosted collaborative deployments.

---

## 21. Initial Canonical Decisions

- Version 1 uses conservative source-sample or spatial-cell boundaries.
  Interpolated numeric threshold crossings are deferred until evidence shows
  that the additional precision is useful.
- GPS speed is the initial non-spatial signal criterion. Brake-use selectors
  remain deferred until canonical brake signals exist.
- `bridge_gap_s` defaults to `0.0`. A Scenario may explicitly request a short
  bridge, but unknown, inactive, unsupported, or discontinuous gaps remain hard
  boundaries.
- Event and Metrics consumers initially use anchor inclusion.
- Saved Scenarios are scoped to the configured libraries root from version 1.
- A Scenario contains at most four leaf criteria.
- Synchronous evaluation accepts at most 32 explicit session references and
  returns at most 10,000 Episodes. Broader scopes require a future asynchronous
  execution form.
- The initial SSA and SPD consumers select either no Scenario or one Scenario
  restriction. That restriction intersects manual time windows, track-sector
  scope, activity exclusion, and the member sessions of selected groupings.
- Scratch Scenarios use the persisted definition shape without an id or
  revision. They are local to the analysis tab, survive editor closure, and are
  not restored after the tab is reloaded.
- The initial Workbench does not batch Scenario evaluation. Selection of more
  than 32 unique sessions is rejected before calling the synchronous service.

The remaining pre-canonicalisation question is the semantic selector for a
future processed brake-use signal.
