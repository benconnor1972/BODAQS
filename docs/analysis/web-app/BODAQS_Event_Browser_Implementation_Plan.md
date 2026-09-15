# BODAQS Event Browser Implementation Plan

**Status:** Approved; Browse and initial Compare increments implemented  
**Date:** 2026-09-15  
**Scope:** BODAQS Workbench analysis view, Library API read operations, and
root-scoped event-tag persistence  
**Related views:** Simple Suspension Analysis (SSA), Suspension Phase Diagram
(SPD), Signal Inspector  
**Related contracts:**

- [`BODAQS_Event_Table_Contract_v0_1_3_draft.md`](../contracts/BODAQS_Event_Table_Contract_v0_1_3_draft.md)
- [`BODAQS_Metrics_Table_Contract_v0_2.md`](../contracts/BODAQS_Metrics_Table_Contract_v0_2.md)
- [`BODAQS_SegmentBundle_Contract_v0_1_1.md`](../contracts/BODAQS_SegmentBundle_Contract_v0_1_1.md)
- [`BODAQS_Scenario_Contract_v0_draft.md`](../contracts/BODAQS_Scenario_Contract_v0_draft.md)
- [`BODAQS_Library_API_Contract_v0_draft.md`](../contracts/BODAQS_Library_API_Contract_v0_draft.md)
- [`BODAQS_Web_App_Design_Language.md`](BODAQS_Web_App_Design_Language.md)

## Implementation checkpoint — 2026-09-15

The first end-to-end vertical slice is implemented. It includes analysis-view
registration and adequacy checks, event-definition discovery, schema-aware
segment extraction, primary and secondary trigger rendering, Event metrics,
session/group/end/Scenario/time-window/metric controls, revision-safe user
tags, and bounded Event overlays aligned on the primary trigger.

The consolidation pass now also shares the drawer, session/group, end, and
Scenario primitives with SSA/SPD; supports multi-Scenario OR restriction;
prefetches adjacent Event windows; adds arrow-key navigation and Signal
Inspector hand-off; displays Event identity, QC, and provenance; degrades to a
resolvable primary signal for historical Events without schema role defaults;
and establishes Vitest/Testing Library coverage for the common controls and
Event Browser interaction loop.

The next population-and-comparison increment is also implemented. It adds
independent schema-tag and user-tag population filters, stable trigger/session/
end/metric ordering, explicit base and filtered counts, missing-metric counts,
an explicit pin tray, tag-based bulk pinning, per-trace visibility, schema-
revision compatibility feedback, enforcement of the 12-Event comparison
limit, and Study-Set-scoped local persistence for view controls and pins.

The remaining open items are representative performance measurement,
virtualization/query projection or server pagination if those measurements
justify them, the final accessibility and user-documentation pass, and the
separate later Event authoring/detection project.

## 1. Goal

Add an analysis view called **Event Browser** to the BODAQS Workbench. It will
let a user work through detected event instances in an explicit Study Set,
inspect the signal window and metrics associated with each event, narrow the
event population, tag useful events, and compare selected or tagged events on
an aligned chart.

The intended user loop is:

```text
Select Study Set population
  -> choose an event definition
  -> restrict and sort matching events
  -> inspect one event
  -> tag or pin useful events
  -> compare compatible events
```

The first releases remain consumers of canonical processed artifacts. Event
definition authoring and event-detection execution are explicitly deferred.

## 2. Agreed Product Decisions

The following decisions are part of this plan:

1. Event Browser is a normal Workbench analysis view with a Study Set scope.
2. Its left `Select and Filter` drawer should reuse the SSA/SPD visual language
   and as much implementation as reasonably possible.
3. The shared controls include:
   - sessions and Study Set groups;
   - front/rear ends where the event population supports them;
   - Scenarios;
   - per-session time windows; and
   - the same collapsible left drawer, chips, status text, info tips, colours,
     spacing, and interaction states used by SSA/SPD.
4. Scenario restriction uses Event primary-trigger inclusion, consistent with
   the Scenario contract.
5. Metric filtering excludes missing/non-numeric values for that predicate and
   reports the excluded count.
6. Schema-defined Event Table tags and user-applied tags are distinct.
7. Pinning an event for comparison does not require applying a tag.
8. There is no `review status` concept in this feature.
9. Initial comparison is limited to compatible events and aligns them by their
   primary trigger.
10. Python remains authoritative for event schema interpretation, signal-role
    resolution, and segment extraction.
11. Event authoring and detector execution will be designed as a later,
    separate workflow rather than hidden inside the initial Event Browser.

## 3. User-Facing Scope

### 3.1 Browse Mode

Browse mode presents one de-duplicated list of qualifying event instances.

The user can:

- enable or disable Study Set sessions and groups;
- choose an event definition;
- choose one or both supported ends;
- apply one or more Scenario restrictions;
- set a different manual time window for each enabled session;
- filter by Event metrics;
- filter by schema tags or user tags;
- sort the population;
- select an event from the navigator;
- move to the previous or next qualifying event using buttons or keyboard
  shortcuts;
- inspect the event-relative signal window, triggers, metrics, identity, QC,
  and provenance;
- add/remove user tags;
- pin/unpin the event for comparison; and
- open the event's wider time context in Signal Inspector.

### 3.2 Compare Mode

Compare mode operates on a bounded comparison tray. Events can be added
directly with `Pin`, or added in bulk from the current user-tag selection.

The initial comparison supports:

- events from the same logical event definition and compatible schema revision;
- one selected end per comparison, unless all compared events have one common
  event context;
- primary-trigger alignment at `t = 0`;
- a common explicit pre/post window;
- one semantic signal per stacked chart panel;
- raw physical values without implicit normalization;
- individual trace visibility toggles;
- selection/highlight of one active trace; and
- removal and clearing of comparison entries.

The initial tray limit should be 12 events. The UI should explain an
incompatibility or limit instead of silently omitting an event.

### 3.3 Deferred Product Scope

The following are not part of the initial implementation:

- review/accept/reject status;
- event-schema editing;
- running or scheduling detection;
- promoting an ad-hoc filter into a canonical event definition;
- alignment by a secondary trigger;
- cross-event-definition overlays;
- automatic waveform normalization;
- mean, median, percentile, or confidence envelopes;
- collaborative hosted annotations and permissions;
- automatic rebinding of tags after reprocessing; and
- background indexing before performance evidence requires it.

## 4. Interaction And Layout Specification

### 4.1 Analysis Page Shell

Event Browser uses the existing analysis route/page shell and opens in a new
Workbench tab from the Analysis Launcher.

```text
+--------------------------------------------------------------------------+
| Study Set title                                      Event Browser        |
+----------------------+---------------------------------------------------+
| Select and Filter    | Browse | Compare                                  |
|                      +---------------------------------------------------+
| Sessions and groups  | Event navigator / result count / sort             |
| Event definition     +---------------------------------------------------+
| Ends                 | Event-relative signal chart                       |
| Scenarios            |                                                   |
| Time windows         +---------------------------+-----------------------+
| Metric filters       | Trigger and provenance    | Event metrics         |
| Tags                 |                           | Tags / Pin / Inspect  |
+----------------------+---------------------------+-----------------------+
```

On narrower screens, the event details and metrics move below the chart. The
left drawer remains collapsible to the same vertical rail used by SSA/SPD.

### 4.2 Shared `Select and Filter` Drawer

The drawer order is:

1. **Sessions and groups**
2. **Event definition**
3. **Ends**
4. **Scenarios**
5. **Time windows**
6. **Metric filters**
7. **Tags**
8. **Signal choices**
9. **Display options**

The first, third, fourth, and fifth sections should be shared components used
by SSA/SPD and Event Browser. The drawer shell and collapsed rail should also
be shared.

The Event Browser does not show SSA/SPD comparison-layout or Session/Track-mode
controls. Track sectors are not part of the first Event Browser release.

#### Sessions and groups

- Use the existing session/group chips and icons.
- Selecting a group selects its member sessions as an analysis population.
- If a session is selected directly and through one or more groups, its Event
  rows appear only once.
- Group colour can identify membership in the navigator, but must not change
  Event identity.
- Disabling every entity produces an empty-state prompt and performs no Event
  or Scenario queries.

#### Event definition

- Present logical event labels and counts, not artifact folder names.
- Keep the filesystem-safe Event set ID available only in diagnostic detail.
- Distinguish incompatible schema revisions/digests rather than silently
  pooling them.
- Preserve the selected definition if it remains available after scope
  changes; otherwise choose the first compatible definition and announce the
  change.

#### Ends

- Reuse the SSA/SPD front-teal and rear-dark chips.
- Hide or disable an end that is unavailable for the selected definition and
  current population.
- Events without a resolved front/rear context remain available under an
  `Other/unknown` option when such rows exist. Do not infer an end from a
  positional parse of `event_id`.

#### Scenarios

- Reuse the SSA/SPD Scenario list, edit entry point, loading states, warnings,
  and revision labels.
- Event Browser uses Scenarios as restrictions rather than chart facets.
- With no Scenario selected, all otherwise qualifying events are included.
- With several Scenarios selected, an event is included when its primary
  trigger belongs to any selected Scenario Episode (`OR`).
- Show the matching Scenario names on the selected Event when it belongs to
  more than one.
- Keep this `any selected Scenario` rule visible in the info tip so the shared
  checkbox visual does not imply an `AND` intersection.

#### Time windows

- Reuse the SSA/SPD per-session tabs, overview selection, reset actions,
  bookmarks, and `Inspect signals` hand-off.
- Split the current time-window component's UI/state behavior from its
  suspension-specific overview data input.
- SSA/SPD will continue supplying their loaded suspension overview data.
- Event Browser will lazily request a low-resolution overview signal for the
  active time-window session.
- An Event is included when its primary trigger lies in the selected session
  window. Use the same half-open/end-boundary policy as the Scenario contract.

#### Metric filters

- Metric controls are populated only after an Event definition is selected.
- Show only `m_*` fields with at least one finite value in the active base
  population.
- Each predicate supports minimum, maximum, or a bounded inclusive range.
- Multiple metric predicates combine with `AND`.
- Missing/non-numeric values fail that predicate and contribute to an explicit
  `missing metric` count.
- The control shows population extent, active range, matching count, and unit
  when the persisted schema provides one.
- Metric diagnostic `d_*` fields do not appear as filter choices.

#### Tags

- Display `Schema tags` as read-only filters.
- Display `My tags` as editable user annotations and filters.
- User-tag filter mode is `has any selected tag` in version 1.
- Tag matching is normalized for surrounding whitespace and case-insensitive
  comparison, while the first stored display spelling is retained.
- Tags are not required for pinning or comparison.

### 4.3 Event Navigator

Use a compact virtualizable list or table rather than a dropdown.

Each row shows:

- selected-state marker;
- ordinal within the filtered population;
- session label;
- primary-trigger session time;
- end/context;
- up to three configured key metrics;
- user-tag chips; and
- pin state.

Required sort choices:

- session then primary-trigger time (default);
- primary-trigger time across sessions;
- detector score;
- each available numeric metric ascending/descending; and
- deterministic shuffle with an explicit seed.

All sorts use a final stable tie-breaker of library, run, session, primary
trigger, and event ID.

Navigation rules:

- `Previous` and `Next` follow the visible sorted population.
- Left/Right move between events when focus is not in an editable control.
- Home/End select the first/last result.
- If filtering removes the selected event, select the nearest remaining row by
  the current ordering.
- The heading shows `Event n of N` and the unfiltered base count.
- Selection does not change Study Set membership or filter state.

### 4.4 Event Inspection

The inspection chart defaults to the persisted event definition's
`segment_defaults` roles and window. The user may override signals and pre/post
duration without modifying the schema or artifacts.

Rendering rules:

- one x-axis in seconds relative to the primary trigger;
- stacked panels by semantic signal/unit;
- front series teal and rear series dark, consistent with SSA/SPD;
- primary trigger at `0` with a strong labelled line;
- secondary triggers identified from the schema's declared trigger IDs and
  shown with quieter labelled lines;
- no attempt to treat arbitrary `*_time_s` diagnostics as triggers;
- zero reference lines where physically useful;
- gaps remain gaps; and
- warnings remain visible without replacing otherwise usable panels.

The detail area shows:

- event display name and ID;
- library, run, session, and primary-trigger time;
- event context/end;
- schema ID, schema version, and schema digest;
- detector version and parameter hash;
- schema tags;
- Event QC flags and score;
- stable `m_*` metrics;
- collapsed `d_*` diagnostics;
- user tags; and
- `Pin`, `Open in Signal Inspector`, and copy-reference actions.

### 4.5 Compare Mode

Compare mode uses the same event-segment response as Browse mode and does not
load whole session signals.

Compatibility is checked against:

- logical schema ID;
- schema version/digest;
- event context/end;
- requested semantic signal roles and units; and
- available time coverage.

The chart uses one trace per Event per panel. The active Event uses a stronger
line; other traces use stable session/event colours at lower opacity. Secondary
trigger markers are shown for the active trace only in version 1 to avoid
unreadable marker forests.

Bulk actions include:

- add all currently visible events with a selected user tag, up to the tray
  limit;
- remove events no longer present in the active Study Set scope;
- clear comparison; and
- switch the active trace.

## 5. Existing Foundation And Required Refactoring

### 5.1 Existing Code To Reuse

Python:

- `analysis/bodaqs_analysis/artifacts.py`
  - `ArtifactStore`
  - Event and Metrics artifact paths
  - frozen event-schema paths
- `analysis/bodaqs_analysis/schema.py`
  - persisted schema parsing
- `analysis/bodaqs_analysis/segment.py`
  - `SegmentRequest`
  - `WindowSpec`
  - `RoleSpec`
  - `extract_segments`
- `analysis/bodaqs_analysis/widgets/event_browser.py`
  - behavioral reference for Event selection, semantic signals, metrics, and
    trigger rendering
- `analysis/bodaqs_analysis/library_api/queries.py`
  - existing Event and Metrics table reads
- `analysis/bodaqs_analysis/library_api/cache.py`
  - cache identity and invalidation patterns
- `analysis/bodaqs_analysis/library_api/scenarios.py`
  - Scenario persistence and evaluation
- `analysis/bodaqs_analysis/library_api/bookmarks.py`
  - root-scoped revision-safe persistence pattern

Frontend:

- `application/cohort-workbench-prototype/src/components/SuspensionVisualization.tsx`
  - drawer shell;
  - session/group selection;
  - end selection;
  - Scenario loading/evaluation states;
  - per-session time-window manager;
  - primary-trigger population filtering; and
  - analysis-view settings persistence patterns
- `application/cohort-workbench-prototype/src/components/SignalInspector.tsx`
  - uPlot time-series configuration and event-selection interaction patterns
- `application/cohort-workbench-prototype/src/components/AnalysisLauncher.tsx`
  - view discovery, adequacy, and launch behavior
- `application/cohort-workbench-prototype/src/data/LibraryDataSource.ts`
  - data-source abstraction
- `application/cohort-workbench-prototype/src/data/LocalApiDataSource.ts`
  - API mapping and transport
- `application/cohort-workbench-prototype/src/data/FixtureLibraryDataSource.ts`
  - offline/demo behavior
- `application/cohort-workbench-prototype/src/App.css` and `src/index.css`
  - canonical tokens and current analysis-control styling

### 5.2 Shared Analysis-Control Extraction

The reusable SSA/SPD controls are currently local functions inside
`SuspensionVisualization.tsx`. Before building the Event Browser drawer, extract
the presentational/state-neutral pieces into:

```text
application/cohort-workbench-prototype/src/components/analysis-controls/
  AnalysisControlDrawer.tsx
  AnalysisEntityControl.tsx
  AnalysisEndControl.tsx
  AnalysisScenarioControl.tsx
  AnalysisTimeWindowControl.tsx
  AnalysisControlTypes.ts
```

Recommended boundaries:

- `AnalysisControlDrawer` owns expanded/collapsed rendering and rail behavior.
- `AnalysisEntityControl` receives already-built session/group entities and
  selection callbacks.
- `AnalysisEndControl` receives available and selected ends.
- `AnalysisScenarioControl` accepts a `selectionMode` and explanatory text so
  SSA/SPD can retain facet behavior while Event Browser uses `restrict-any`.
- `AnalysisTimeWindowControl` owns session tabs, summaries, reset/bookmark
  controls, and accessibility behavior; its overview plot receives a generic
  time-series model rather than `VisualizationData`.

Keep data loading, Scenario evaluation, and Event-population filtering in each
analysis view or focused hooks. Do not create a single oversized universal
analysis-state hook.

SSA and SPD must render and behave equivalently after extraction. This is a
prerequisite rather than an opportunity for unrelated visual changes.

## 6. Data Contracts

### 6.1 Event Definition Descriptor

Add a read operation that describes logical event definitions available across
explicit sessions. A representative response item is:

```json
{
  "definition_key": "sha256:...:compressions_all>25",
  "schema_id": "compressions_all>25",
  "schema_version": "7",
  "schema_digest": "sha256:...",
  "display_name": "Wheel compression over 25% travel",
  "schema_tags": ["kinematics", "compression"],
  "event_set_ids": ["compressions_all_25"],
  "available_ends": ["front", "rear"],
  "primary_trigger": { "id": "compression_end" },
  "secondary_triggers": [{ "id": "compression_start" }],
  "default_window": { "pre_s": 0.8, "post_s": 0.2, "anchor": "trigger_time_s" },
  "default_roles": [
    { "role": "disp", "selector": { "quantity": "disp", "unit": "mm" } },
    { "role": "vel", "selector": { "quantity": "vel", "unit": "mm/s" } }
  ],
  "metric_fields": [
    { "column": "m_interval_vel_min", "display_name": "Minimum interval velocity", "unit": "mm/s" }
  ],
  "event_count": 168,
  "session_count": 1,
  "warnings": []
}
```

Rules:

- `schema_id` is the logical definition ID from Event rows/schema.
- `event_set_ids` are filesystem-safe artifact partition identifiers and are
  never presented as the logical Event name.
- `definition_key` includes the frozen schema digest and logical schema ID.
- Do not use `params_hash` as the definition key because expanded front/rear
  contexts may legitimately have different effective parameter hashes.
- Metric descriptors are derived from schema metadata where possible and fall
  back to populated Metrics Table columns.
- Definitions with the same schema ID but different schema digests remain
  separate choices unless the user explicitly enables mixed-definition mode in
  a later release.

Suggested endpoint:

```text
POST /api/v1/event-definitions/query
```

The request contains explicit cross-library session references. Keeping this
operation root-scoped avoids making the browser merge conflicting logical
definitions independently for each library.

### 6.2 Event Reference

Every selected, pinned, or tagged event uses an opaque structured reference:

```json
{
  "library_id": "default-library",
  "run_id": "run_...",
  "session_id": "2026-02-19_09-43-31",
  "session_key": "run_...::2026-02-19_09-43-31",
  "event_set_id": "compressions_all_25",
  "event_id": "compressions_all>25:front:0",
  "schema_id": "compressions_all>25",
  "schema_version": "7",
  "schema_digest": "sha256:...",
  "params_hash": "sha256:...",
  "trigger_time_s": 2.006
}
```

The canonical lookup key is library + run + session + Event set + Event ID.
The remaining fields detect drift and support unresolved-annotation display.
Clients must not parse `event_id` positionally.

### 6.3 Event And Metrics Population

For the first implementation, retain the existing Event and Metrics query
operations and fetch them concurrently, grouped by library as SSA already does.

Add or clarify request fields:

```text
event_set_ids   filesystem-safe artifact partitions
schema_ids      logical row-level schema IDs
columns         optional projected fields
```

Retain `event_types` as a backward-compatible alias until existing consumers
are migrated. Stop using one field name for both artifact-set IDs and logical
schema IDs.

Join Event and Metrics rows in a tested shared domain helper using:

```text
library_id + session_key + event_id + schema_id
```

The Event Table remains authoritative for primary trigger, secondary triggers,
window bounds, context, QC, score, and provenance. The Metrics Table remains
authoritative for displayed/filterable `m_*` values. Duplicate copied identity
fields must agree or produce a diagnostic.

Initial time-window, Scenario, metric, and tag filtering can remain client-side
over the fetched population, matching the existing SSA population model. Add
payload and filtering timings before deciding to add server pagination or
indexes.

### 6.4 Event Segment Query

Add a schema-aware event-segment operation rather than rebuilding Python Event
semantics in TypeScript.

Suggested endpoint:

```text
POST /api/v1/libraries/{library_id}/event-segments/query
```

Representative request:

```json
{
  "events": [{ "session_key": "...", "event_set_id": "...", "event_id": "..." }],
  "roles": ["disp", "vel"],
  "window": { "pre_s": 0.8, "post_s": 0.2 },
  "alignment": { "kind": "primary_trigger" },
  "resolution": { "target_points": 1200 }
}
```

Representative response per Event:

```json
{
  "event_ref": {},
  "window": {
    "requested_pre_s": 0.8,
    "requested_post_s": 0.2,
    "returned_start_rel_s": -0.8,
    "returned_end_rel_s": 0.2
  },
  "time_rel_s": [],
  "signals": [
    {
      "role": "disp",
      "column": "front_wheel_disp_dom_wheel [mm]",
      "display_name": "Front wheel travel",
      "end": "front",
      "quantity": "disp",
      "unit": "mm",
      "values": []
    }
  ],
  "triggers": [
    { "id": "compression_end", "kind": "primary", "time_rel_s": 0.0 },
    { "id": "compression_start", "kind": "secondary", "time_rel_s": -0.25 }
  ],
  "metrics": {},
  "qc": {},
  "warnings": []
}
```

Implementation rules:

- load the exact Event row from its Event set artifact;
- load and parse the frozen schema beside that artifact;
- select the logical event block matching `schema_id`;
- resolve roles through the session signal registry;
- call `extract_segments` with schema defaults or explicit overrides;
- derive trigger markers only from declared schema trigger IDs;
- return JSON-serializable values and explicit missing/invalid-segment
  diagnostics;
- read only necessary signal columns where practical;
- accept at most 12 Event references per library request initially; and
- preserve each Event's native relative time vector. Do not resample several
  Events to a common grid merely to draw individual traces.

### 6.5 User Event Tags

Do not write user tags into Event or Metrics parquet files. Add a root-scoped,
revision-safe `bodaqs.event_annotation` resource whose version 1 writable
content is only tags.

Suggested storage:

```text
<libraries_root>/
  event_annotations/
    <annotation_id>.json
```

Representative object:

```json
{
  "schema": "bodaqs.event_annotation",
  "version": 1,
  "annotation_id": "event-annotation-...",
  "revision": 2,
  "event_ref": {},
  "tags": ["harsh", "setup-a"],
  "created_at_utc": "2026-09-15T00:00:00Z",
  "updated_at_utc": "2026-09-15T00:10:00Z"
}
```

Suggested API:

```text
POST   /api/v1/event-annotations/query
POST   /api/v1/event-annotations
PUT    /api/v1/event-annotations/{annotation_id}
DELETE /api/v1/event-annotations/{annotation_id}
```

Create/update uses revision checks and atomic writes following bookmarks,
Scenarios, and Study Sets. One active annotation should exist per canonical
Event reference. Removing the final tag may delete the annotation through an
explicit API request.

Add service capabilities:

```text
read_event_annotations
write_event_annotations
```

Read-only hosted/demo mode may show persisted tags but must disable tag edits.
Temporary pins and Compare mode remain available because they do not write.

Annotations whose Event can no longer be resolved remain listable as orphaned
annotations. Never attach them automatically to a nearby event after
reprocessing.

## 7. Frontend Architecture

### 7.1 Proposed Files

```text
application/cohort-workbench-prototype/src/
  components/
    EventBrowser.tsx
    event-browser/
      EventBrowserControlDrawer.tsx
      EventDefinitionControl.tsx
      EventMetricFilters.tsx
      EventTagControl.tsx
      EventNavigator.tsx
      EventInspection.tsx
      EventSignalChart.tsx
      EventMetricsPanel.tsx
      EventComparisonTray.tsx
      EventComparisonView.tsx
    analysis-controls/
      AnalysisControlDrawer.tsx
      AnalysisEntityControl.tsx
      AnalysisEndControl.tsx
      AnalysisScenarioControl.tsx
      AnalysisTimeWindowControl.tsx
      AnalysisControlTypes.ts
  domain/
    eventBrowser.ts
    eventFilters.ts
    eventIdentity.ts
  data/
    LibraryDataSource.ts
    LocalApiDataSource.ts
    FixtureLibraryDataSource.ts
```

`EventBrowser.tsx` should orchestrate data and state but delegate controls,
tables, charts, and details to focused components. Avoid creating another
single component comparable in size to `SuspensionVisualization.tsx` or
`SignalInspector.tsx`.

### 7.2 Domain State

Keep the following state explicit:

```text
scope
  selected entity IDs
  de-duplicated session refs
  selected ends
  Scenario IDs and evaluation results
  per-session time windows

event population
  selected definition key
  joined Event/Metric rows
  metric predicates
  schema-tag predicates
  user-tag predicates
  sort specification and shuffle seed

inspection
  selected Event reference
  signal roles/overrides
  pre/post window
  loaded segment

comparison
  pinned Event references
  active Event reference
  compatibility result

presentation
  Browse/Compare tab
  drawer collapsed state
  navigator width
  detail-panel collapsed states
```

Pure functions in `domain/eventFilters.ts` should apply population restrictions
in this order:

1. de-duplicated session scope;
2. selected logical event definition;
3. end/context;
4. manual time windows;
5. selected Scenario Episode union;
6. metric predicates;
7. schema tags;
8. user tags; and
9. stable sort.

### 7.3 Data Loading

1. Resolve selected entities to unique session references.
2. Query Event definitions for that explicit scope.
3. Query Event and Metrics rows concurrently, grouped by library.
4. Query Event annotations once for the scoped sessions and index them by
   canonical Event reference.
5. Evaluate selected Scenarios only for enabled sessions, using the existing
   Scenario cache pattern.
6. Compute the filtered/sorted navigator population with deferred React state
   when filter interaction is active.
7. Fetch one Event segment when selection changes.
8. Prefetch the immediately previous and next Event segment after the selected
   segment becomes ready.
9. Fetch missing pinned segments in batches by library when Compare opens.

Scope and definition changes cancel or ignore stale async responses. Reuse
in-flight promises and cache successful results by artifact-sensitive request
identity.

### 7.4 View Settings Persistence

Use the existing analysis-view local-storage pattern and key settings by view,
Study Set identity/revision, and a settings schema version.

Persist:

- selected entity IDs;
- selected ends;
- selected Scenario IDs;
- per-session time windows;
- selected definition key where still valid;
- metric and tag filters;
- sort selection and shuffle seed;
- signal-role overrides;
- pre/post chart window;
- drawer and panel collapsed state; and
- pinned Event references.

Do not treat locally persisted filters or pins as canonical Study Set content.
Do not persist loaded signal arrays.

## 8. Backend Architecture

### 8.1 Proposed Files

```text
analysis/bodaqs_analysis/library_api/
  event_definitions.py
  event_segments.py
  event_annotations.py
  queries.py
  models.py
  adapter.py

analysis/bodaqs_analysis/library_api_service/
  app.py
```

Keep HTTP handling thin. Parsing schemas, resolving Event references,
extracting segments, and annotation persistence belong in reusable Library API
modules callable without FastAPI.

### 8.2 Adapter Operations

Add facade methods:

```python
adapter.query_event_definitions(request)
adapter.query_event_segments(library_id, request)
adapter.query_event_annotations(request)
adapter.create_event_annotation(payload)
adapter.update_event_annotation(annotation_id, expected_revision, payload)
adapter.delete_event_annotation(annotation_id)
```

Extend Event/Metrics queries with unambiguous Event set/schema selection and
optional column projection while retaining old request compatibility.

### 8.3 Cache Identity And Invalidation

Definition-query cache identity includes:

- session references;
- Event parquet fingerprints;
- frozen schema fingerprints; and
- Metrics parquet fingerprints used for field discovery.

Segment-query cache identity includes:

- Event reference;
- session dataframe fingerprint;
- session metadata/registry fingerprint;
- Event parquet fingerprint;
- frozen schema fingerprint;
- Metrics parquet fingerprint;
- requested roles;
- window; and
- resolution policy.

Annotation reads are invalidated by their directory/file fingerprints.
Annotation writes invalidate only annotation-related cache entries.

Expose event-definition and event-segment cache counts/timings through the
existing diagnostics structure.

## 9. Analysis View Registration And Adequacy

Register:

```text
view_id: event-browser
route: /analysis/event-browser
category: Events
adequacy_policy: partial
```

Recommended adequacy requirements:

### Required

- At least one scoped session has a readable Event Table with canonical Event
  ID and primary-trigger fields.

### Recommended

- Frozen Event schema is available.
- A Metrics row can be joined for at least some Events.
- At least one schema-default or primary Event signal can be resolved.

### Optional

- Secondary triggers are populated.
- front and rear contexts are both present;
- Scenario-compatible signals are available; and
- writable user Event tags are supported.

Adequacy should be partial when some Study Set sessions can browse Events and
others cannot. The launcher should state how many sessions are usable.

Update:

- `analysis/bodaqs_analysis/library_api/analysis_views.py`;
- frontend supported-view guards;
- route titles and renderer selection in `App.tsx`;
- fixture analysis-view/adequacy behavior; and
- analysis-view tests.

## 10. Compatibility And Failure Behavior

### 10.1 Historical Libraries

- Event Tables with primary triggers but no secondary triggers remain browsable.
- Event Tables without Metrics remain browsable; metric controls show an empty
  state.
- Event Tables with no frozen schema use a generic fallback:
  - Event row window or a configured default;
  - primary `signal_col` when present; and
  - manual signal selection from the session catalog.
- Missing schema defaults or roles produce warnings, not fabricated semantics.
- Rows lacking a resolvable primary trigger are excluded from time/Scenario
  restriction and inspection with diagnostics.
- Conflicting copied identity fields between Event and Metrics rows prevent that
  metric join and produce a warning.

### 10.2 Mixed Definitions

When the same `schema_id` appears with multiple schema digests:

- show separate Event-definition choices;
- include revision/digest detail in the label or warning;
- do not compare across definitions by default; and
- never infer compatibility from the display name alone.

### 10.3 Read-Only Mode

Browse, filters, Scenario restriction, temporary pins, and Compare remain
usable. Tag inputs are disabled with an explanatory capability message.

### 10.4 Partial Errors

One unreadable session/Event set should not discard successful rows from other
sessions. Aggregate warnings by session and Event set and provide expandable
detail.

## 11. Performance Plan

### 11.1 Initial Strategy

- Reuse cached Event and Metrics table queries.
- Request only selected Event sets when the API can identify them.
- Add optional column projection so the navigator does not receive large nested
  `meta` fields unnecessarily.
- Keep filter/sort operations pure and memoized.
- Use deferred filter values while sliders are moving.
- Virtualize the navigator when result counts exceed a measured threshold.
- Load one short Event segment rather than whole session signals.
- Prefetch adjacent Events only after the selected request completes.
- Batch comparison segment requests by library and enforce the tray limit.

### 11.2 Instrument Before Adding Indexes

Record in development diagnostics:

- Event/Metric row counts;
- JSON payload bytes;
- Event/Metric fetch duration;
- join duration;
- filter/sort duration;
- definition discovery duration;
- segment extraction duration;
- segment payload bytes;
- cache hit/miss counts; and
- time from navigation action to chart-ready state.

Initial performance targets on a representative local library:

- cached previous/next navigation: under 100 ms to painted chart;
- uncached single-Event navigation: under 500 ms median;
- filter/sort interaction for 10,000 joined Events: under 100 ms after data is
  resident; and
- Compare load for 12 cached/local Events: under 1.5 s median.

If representative Study Sets exceed these targets or produce excessive
payloads, add a version 2 server-side Event-instance query with predicates,
sorting, cursor pagination, and facet counts. Do not introduce a persistent
index until measurements show parquet scan/caching is insufficient.

## 12. Testing Plan

### 12.1 Python Unit And Adapter Tests

Add:

```text
analysis/tests/test_library_api_event_definitions.py
analysis/tests/test_library_api_event_segments.py
analysis/tests/test_library_api_event_annotations.py
```

Cover:

- logical schema ID versus Event set ID;
- descriptor grouping by frozen schema digest;
- same schema ID with incompatible schema digests;
- schema default window/role/trigger projection;
- fallback when schema is absent or invalid;
- metric-field discovery with sparse wide tables;
- exact Event reference lookup;
- primary and secondary trigger offsets;
- schema-declared trigger filtering of unrelated `*_time_s` fields;
- semantic role resolution for front and rear;
- explicit window and role overrides;
- clipped/invalid segment diagnostics;
- multi-Event request limit;
- JSON serialization of nullable pandas/numpy values;
- annotation create, list/query, update, tag removal, and delete;
- revision conflict;
- orphaned Event annotation;
- read-only route rejection for writes;
- partial results when one Event cannot be read; and
- cache invalidation after Event, schema, Metrics, session, or annotation file
  changes.

Extend service route tests for every new endpoint and the standard error
envelope.

### 12.2 Frontend Domain Tests

Introduce Vitest for pure domain and component tests if no frontend test runner
has been added before this feature.

Cover:

- session/group de-duplication;
- definition, end, and tag filtering;
- inclusive metric range and missing-metric behavior;
- manual time-window primary-trigger inclusion;
- half-open Scenario Episode inclusion;
- OR semantics for several selected Scenarios;
- stable metric/time/shuffle sorting;
- Event/Metrics join identity and conflict warnings;
- selection fallback when the active Event is filtered out;
- comparison compatibility and tray limit;
- settings serialization/migration; and
- stale async response rejection.

### 12.3 Frontend Component Tests

Cover:

- shared drawer expansion/collapse in SSA/SPD/Event Browser;
- session/group chips and end colours remain consistent;
- Scenario control explains facet versus restriction mode;
- keyboard navigation and editable-control exclusions;
- loading, empty, partial-warning, and error states;
- tag edits hidden/disabled in read-only mode;
- trigger and metrics detail rendering; and
- responsive movement of details below the chart.

### 12.4 Manual Regression Matrix

Before release, exercise:

1. one-session Study Set;
2. several sessions in one library;
3. sessions across libraries;
4. overlapping Study Set groups;
5. front-only, rear-only, and front/rear Events;
6. Events with several secondary triggers;
7. Events with no Metrics;
8. mixed historical schema revisions;
9. Scenario with zero, one, and many Episodes;
10. per-session time windows and bookmarks;
11. writable local service;
12. read-only hosted/demo service;
13. tag persistence across reload;
14. an orphaned annotation after artifact replacement; and
15. 12-Event comparison with mixed sessions.

Run at minimum:

```text
cd analysis
pytest -q

cd application/cohort-workbench-prototype
npm run lint
npm run build
npm test
```

Add `npm test` as part of the Vitest setup.

## 13. Implementation Phases

### Phase 0: Contract Decisions And Shared-Control Extraction

Deliverables:

- approve Event reference, definition descriptor, segment response, and Event
  annotation shapes;
- update the Library API contract draft;
- add an Event annotation contract draft;
- extract the common analysis drawer and reusable controls;
- adapt SSA/SPD to those shared controls without behavior change; and
- add focused shared-control tests.

Exit criteria:

- SSA/SPD build and manual regression pass;
- Event Browser can compose the shared drawer in a placeholder route; and
- no duplicate session/end/Scenario/time-window control implementation is
  introduced.

### Phase 1: Analysis Registration And Event Population

Deliverables:

- register `event-browser` and its adequacy policy;
- add launcher and route support;
- implement Event-definition discovery;
- clarify Event set versus logical schema query fields;
- add Event/Metric join and filter domain models;
- implement the Event-definition selector and Event navigator;
- add fixture data for ready, partial, and empty populations; and
- render identity/metric detail before signal extraction is available.

Exit criteria:

- the user can open Event Browser for a Study Set;
- select sessions/groups, definition, and ends;
- navigate joined Event/Metric rows; and
- see partial-session warnings.

### Phase 2: Notebook-Parity Event Inspection

Deliverables:

- implement the Event segment adapter and HTTP route;
- add frontend types/data-source methods;
- render schema-default signal panels;
- render primary and secondary triggers;
- display metrics, QC, and provenance;
- add previous/next keyboard navigation and adjacent prefetch; and
- add the Signal Inspector hand-off.

Exit criteria:

- representative compression, rebound, and jump Events reproduce the signal
  window, trigger positions, and metrics available in the notebook browser;
- missing schema/metrics/secondary triggers degrade as specified; and
- navigation does not load whole session signal arrays.

### Phase 3: Shared Population Restrictions

Deliverables:

- integrate shared per-session time windows;
- integrate shared Scenario selection/evaluation in `restrict-any` mode;
- add metric filters and stable sorting;
- add schema-tag filters;
- show base, filtered, and missing-value counts; and
- persist view settings.

Exit criteria:

- manual time windows and Scenario Episodes include Events by primary trigger;
- multiple Scenarios have documented/tested OR behavior;
- metric filters handle missing values explicitly; and
- reloading restores valid selections without restoring signal payloads.

### Phase 4: User Event Tags

Deliverables:

- add Event annotation persistence and capabilities;
- add list/create/update/delete routes;
- add `My tags` filter and selected-Event tag editor;
- handle revision conflicts;
- show orphaned annotations in diagnostics; and
- support read-only mode.

Exit criteria:

- tags persist across Workbench reloads in local writable mode;
- canonical Event/Metric artifacts are unchanged;
- tags can be added and removed without creating duplicates; and
- hosted/read-only mode remains fully browseable.

### Phase 5: Compare Mode

Deliverables:

- add comparison tray and compatibility checks;
- persist pins as local view state;
- add tagged-event bulk selection;
- batch segment requests by library;
- render aligned stacked overlays;
- add trace visibility and active-trace selection; and
- enforce/explain the 12-Event limit.

Exit criteria:

- the user can overlay directly pinned or tagged compatible Events aligned on
  primary trigger;
- incompatible Events are rejected with a concrete reason;
- secondary triggers are shown for the active trace; and
- comparison does not modify tags or processed artifacts.

### Phase 6: Performance, Accessibility, And Documentation Hardening

Deliverables:

- collect representative performance measurements;
- add navigator virtualization if required;
- add projected Event/Metric fields and server pagination only if measurements
  justify them;
- complete keyboard and screen-reader labeling;
- update helper-text inventory;
- update roadmap and API documentation;
- add user-facing Workbench documentation; and
- add release-note coverage.

Exit criteria:

- performance targets are met or an evidenced follow-up is recorded;
- all automated checks pass;
- manual regression matrix passes; and
- user and API behavior are documented.

## 14. Expected File Touchpoints

### Analysis library and API

- `analysis/bodaqs_analysis/library_api/analysis_views.py`
- `analysis/bodaqs_analysis/library_api/adapter.py`
- `analysis/bodaqs_analysis/library_api/models.py`
- `analysis/bodaqs_analysis/library_api/queries.py`
- `analysis/bodaqs_analysis/library_api/event_definitions.py` (new)
- `analysis/bodaqs_analysis/library_api/event_segments.py` (new)
- `analysis/bodaqs_analysis/library_api/event_annotations.py` (new)
- `analysis/bodaqs_analysis/library_api_service/app.py`
- `analysis/tests/test_library_api_adapter.py`
- new focused Event Browser API test files listed above

### Workbench

- `application/cohort-workbench-prototype/src/App.tsx`
- `application/cohort-workbench-prototype/src/App.css`
- `application/cohort-workbench-prototype/src/domain/types.ts`
- `application/cohort-workbench-prototype/src/data/LibraryDataSource.ts`
- `application/cohort-workbench-prototype/src/data/LocalApiDataSource.ts`
- `application/cohort-workbench-prototype/src/data/FixtureLibraryDataSource.ts`
- `application/cohort-workbench-prototype/src/components/AnalysisLauncher.tsx`
- `application/cohort-workbench-prototype/src/components/SuspensionVisualization.tsx`
- new shared analysis-control and Event Browser components listed above
- frontend test configuration and files

### Contracts and documentation

- `docs/analysis/contracts/BODAQS_Library_API_Contract_v0_draft.md`
- `docs/analysis/contracts/BODAQS_Event_Annotation_Contract_v0_draft.md` (new)
- `docs/analysis/web-app/BODAQS_Web_App_Design_Language.md`
- `docs/analysis/web-app/BODAQS_Web_App_Helper_Text_Inventory.md`
- `docs/analysis/web-app/BODAQS_Web_Application_Roadmap.md`
- relevant `bodocs/src/content/` user documentation at release time

No firmware or Import Manager changes are expected for Browse, filters, tags,
or Compare. A future Event authoring/execution project would affect event-schema
editing, preprocessing orchestration, artifact provenance, and possibly Import
Manager controls.

## 15. Acceptance Criteria

The feature is complete when:

1. Event Browser appears in the Analysis Launcher and reports useful adequacy.
2. It opens against saved and temporary Study Set scopes, including
   cross-library Study Sets.
3. Its left drawer shares the SSA/SPD drawer, session/group, end, Scenario, and
   time-window components and visual language.
4. Sessions selected through overlapping groups never duplicate Events.
5. Logical Event definitions remain distinct from artifact folder IDs and
   incompatible schema revisions.
6. The Event navigator accurately reports the base and filtered populations and
   supports stable sort and keyboard previous/next navigation.
7. Selected Events show schema-default signal windows, primary and populated
   secondary triggers, metrics, QC, and provenance.
8. Time-window and Scenario restrictions use primary-trigger inclusion.
9. Metric filters explicitly handle missing values.
10. Schema tags and user tags are visibly and technically separate.
11. User tags persist without changing Event or Metrics artifacts.
12. Read-only mode supports Browse and Compare while preventing tag writes.
13. Directly pinned and tagged Events can be added to a bounded comparison tray.
14. Compatible Events overlay at their primary trigger with consistent signal
    and unit semantics.
15. Invalid, historical, or partially missing data produces scoped warnings and
    useful fallback behavior rather than a blank or failed analysis page.
16. Python, frontend, build, lint, and manual regression checks pass.

## 16. Later Event Authoring Direction

Event authoring should be planned separately after Event Browser usage reveals
which exploratory actions are valuable. A likely progression is:

1. save reusable Event Browser filter configurations;
2. compare detector output against tagged examples;
3. preview detector parameter changes against one session without writing;
4. validate a draft schema and compare existing versus candidate detections;
5. explicitly run preprocessing to produce a new versioned Event set; and
6. expose provenance and promotion rules for adopting that Event definition.

This keeps the Event Browser a reliable consumer while allowing a future
`Event Lab` or `Detector Studio` to own compute, validation, and artifact-write
semantics.

## 17. Recommended Starting Point

Begin with Phase 0 and a thin Phase 1 vertical slice:

1. agree the four new/clarified data shapes;
2. extract and regression-test the common SSA/SPD controls;
3. register a placeholder Event Browser route;
4. implement Event-definition discovery; and
5. display a joined, navigable Event/Metric population before adding signal
   extraction.

This proves the shared visual language, identity model, and Study Set population
semantics before the more specialized chart, tag persistence, and comparison
work depends on them.
