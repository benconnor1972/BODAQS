# Session Browser Suspension Visualization Specification

Status: draft for manual review  
Audience: BODAQS browser / Library API / visualization implementation agents  
Prototype target: session browser extension in the React/TypeScript browser app  

## 1. Purpose

This document specifies the next visualization direction for BODAQS suspension
comparison views. It replaces the earlier notebook-first implementation target:
the prototype should be built as an extension to the browser session/study-set
browser, using the browser visualization stack already adopted for the web
application.

The goal is a clean but flexible comparison view for suspension signals,
metrics, event counts, and distributions, starting from a Study Set scope.

The core visualization grammar is:

- selected Study Set entities can be arranged horizontally, with front/rear
  compared within each entity
- front/rear can alternatively be arranged horizontally, with selected
  entities compared within each end
- sectors, when enabled, are arranged vertically in track order
- each quantity or chart family lives in a vertically collapsible panel

The first implementation should feel like a high-value quick view, not a
general pivot-table builder. It should nevertheless use data and component
shapes that can later support saved visualization setups and a richer comparison
builder.

## 2. Current Context

Assume the following are already available:

- a BODAQS artifact library exposed through the current Library API service
- a Study Set selected or loaded in the browser app
- Study Set entities consisting of explicit sessions and optional groupings
- processed sessions containing signal data, event tables, metrics, and
  metadata
- optional track/trackpoint sector information for sessions where geospatial
  matching has been performed

Implementation target:

```text
application/cohort-workbench-prototype/
```

Relevant current stack:

- Vite
- React
- TypeScript
- plain CSS / application CSS
- `@tanstack/react-table` for table behavior where useful
- `d3` for scales, binning, and custom visualization helpers
- `@observablehq/plot` for fast distribution/scatter experiments where useful
- `uPlot` for dense time-series views where useful
- `lucide-react` for icons

The existing Python/Jupyter simple suspension metrics dashboard remains useful
as a reference for semantics, selectors, metric defaults, and summary
calculations. It is not the prototype implementation target for this work.

Implementation checkpoint:

- Browser entry point from the Study Set `Analyze` modal is implemented.
- Whole-session displacement and velocity distribution panels are implemented.
- Whole-session event counts are implemented as tables.
- Whole-session compression and rebound scatter panels are implemented.
- Compression and rebound scatter panels include best-fit lines, equations, and
  `R^2` summaries.
- The view supports a comparison layout toggle:
  - `Entities as columns`: front/rear overlaid inside each entity tile.
  - `Ends as columns`: selected entities overlaid inside front/rear tiles.
- A sector-mode UI scaffold is implemented. It lists the selected track and
  trackpoint-bounded sectors.
- Initial sectorized displacement and velocity distributions are implemented.
  The browser assigns raw signal samples to sectors using trackpoint
  crossing-time intervals from loaded track match summaries, then renders
  front/rear mini ridgeline distributions by sector.

## 3. Architecture Direction

The browser should own interaction and chart rendering. The Library API should
serve catalog, Study Set, signal, event, metric, and time-series data in stable
payloads without requiring the browser to understand artifact paths.

For this view, the browser may compute lightweight visualization transforms
such as:

- histogram bins from raw or raw-equivalent samples
- ridgeline density/bin geometry
- chart scales and layout
- front/rear styling
- entity visibility
- panel collapse state

The Library API should be used for data access and heavier or cross-session
work where browser-side computation would be slow, lossy, or require artifact
knowledge.

Important constraint:

Do not build distributions from display-decimated time-series payloads unless
the endpoint explicitly preserves distribution correctness. A decimated trace is
good for drawing a line; it is not necessarily valid input for histograms,
percentiles, or ridgelines.

## 4. Non-goals For The First Version

Do not implement the following in the first version unless explicitly requested:

- a general-purpose pivot table builder
- saved visualization specifications
- arbitrary time-window comparison across multiple sessions
- syn.bike-style displacement navigation bar
- time matching between sessions
- sector data slicing / ridgeline rendering
- sector support for compression/rebound metric scatter plots
- authoring or editing Study Sets from this visualization view
- changing canonical Study Set membership from visualization controls
- notebook/Jupyter implementation of the new layout

The syn.bike-style single-session time-window navigator is a roadmap item. It
may be introduced later as an ad-hoc visualization-only scope refinement when
exactly one session entity is active.

## 5. Key Concepts

### 5.1 Visualization Entity

A visualization entity is either:

- a single processed session
- a Study Set grouping

Sessions and groupings should be listed together in visualization controls.
Groupings are deselected by default. Users may turn entities on/off for the
current visualization without changing Study Set membership.

### 5.2 Grouping Semantics

When a Study Set grouping is visualized as one entity, use pooled raw
samples/events from its member sessions.

Examples:

- displacement distribution for a grouping pools matching displacement samples
  from the grouping's member sessions
- velocity distribution for a grouping pools matching velocity samples
- event counts for a grouping count matching events from all member sessions
- scatter plots for a grouping plot pooled event/metric rows from all member
  sessions unless this proves visually misleading

Grouping behavior is allowed only where pooling is meaningful. If a chart type
cannot represent a grouping safely, show a clear disabled/unsupported message
for that entity rather than silently choosing a misleading behavior.

### 5.3 Signal Role

Signal role is the front/rear distinction.

Front and rear are first-class visualization roles, not generic aggregation
dimensions. They should not be pooled into one combined distribution. They may
be shown on the same chart, adjacent within an entity, or both, depending on
chart type.

Use fixed front/rear colors globally across the browser app.

Recommended initial colors:

- front: BODAQS teal
- rear: black or a dark neutral

Exact color tokens should be aligned with the broader BODAQS UI styling once
design tokens exist.

### 5.4 Sector

A sector is a track-ordered subdivision derived from trackpoints / track
matching. In visualizations, sectors are ordered by track order almost always.

If a session/entity has no data for a sector, keep the sector row visible but
empty/faint so track order remains stable across entities.

### 5.5 View Scope

The first implementation should support:

- whole selected entities
- optional sector breakdown where implemented

Do not implement ad-hoc time-window scope in the first version. Keep it on the
roadmap as a single-session-only refinement.

## 6. Overall Browser Layout

Add the suspension visualization as a mode or panel within the session browser /
Study Set browser area. The user should be able to move from a loaded Study Set
to visualization without re-selecting the library root or Study Set.

The visualization view is a vertical stack of collapsible panels.

Initial panels:

- Displacement distribution
- Velocity distribution
- Event counts
- Compression metrics
- Rebound metrics

Each panel uses a horizontal entity strip:

```text
Panel title / controls
------------------------------------------------------------
| Entity A | Entity B | Entity C | ...
------------------------------------------------------------
```

The entity strip should scroll horizontally if it exceeds available width.
Do not paginate in the first implementation unless horizontal scrolling proves
unworkable.

The browser visualization now also supports a comparison-layout control:

- `Entities as columns`: the original entity strip; front/rear are compared
  within each entity tile.
- `Ends as columns`: front and rear become the horizontal tiles; selected
  entities are overlaid as colored series within each end tile.

This control is intended to become part of the general visualization grammar,
not a one-off chart option.

Within each entity, front/rear comparison is arranged according to the chart
type:

- distribution whole-entity mode: front/rear may be overlaid on one chart
- distribution sector mode: front/rear should be adjacent horizontally within
  the entity, with sectors arranged vertically
- scatter metrics: front/rear may be on the same chart
- event counts: front/rear should be presented in a table

Sector breakdown, where available, is vertical:

```text
Entity tile
------------------------------------------------
Front                         Rear
Sector 1   chart/row          Sector 1   chart/row
Sector 2   chart/row          Sector 2   chart/row
Sector 3   chart/row          Sector 3   chart/row
```

This sector-mode rule supersedes any earlier design idea that front/rear should
be stacked vertically.

## 7. Shared Axis And Scale Rules

Use shared axes where comparison depends on scale.

Default scale rules:

- distribution panel x-axis: shared across all entity tiles
- distribution panel y-axis: shared within comparable chart rows where relevant
- displacement normalized x-axis: fixed `0..1`
- velocity x-axis: symmetric around zero, with a fixed default limit unless
  explicitly changed
- metric scatter axes: shared across all entity tiles in the panel
- event count tables: no chart y-axis; counts are tabular because they may span
  several orders of magnitude

Where an axis is fixed by domain semantics, prefer the fixed value over
autoscaling. Where autoscaling is needed, compute panel-level shared extents
before rendering entity tiles.

## 8. Panel Specifications

### 8.1 Displacement Distribution Panel

Purpose:

Show normalized suspension displacement distributions and summary displacement
statistics for selected entities.

Inputs:

- selected visualization entities
- front displacement signal selector
- rear displacement signal selector
- optional engineering-unit displacement source for stats
- optional sector assignments

Whole-entity mode:

- one tile per selected entity
- front and rear shown on the same histogram chart
- x-axis is normalized displacement, fixed `0..1`
- y-axis is shared across entity tiles
- summary stats shown per entity and per role

End-faceted mode:

- one tile for front and one tile for rear
- selected entities are overlaid as colored distribution series within each end
- x/y scale rules remain panel-level shared

Sector mode:

- one tile per selected entity
- front and rear arranged horizontally inside the tile
- sectors arranged vertically in track order
- each front/rear role uses ridgeline-style distributions by sector
- empty sectors remain visible and faint

Summary stats:

- dynamic sag / median
- 95th percentile
- maximum travel
- interquartile range
- skew

Stats should continue to show normalized values. If engineering-unit values are
available, show paired normalized/mm values as the current Python dashboard
does.

### 8.2 Velocity Distribution Panel

Purpose:

Show suspension velocity distributions for selected entities.

Inputs:

- selected visualization entities
- front velocity signal selector
- rear velocity signal selector
- optional sector assignments

Whole-entity mode:

- one tile per selected entity
- front and rear shown on the same histogram chart
- x-axis is velocity in `mm/s`
- x-axis is symmetric around zero
- default fixed absolute limit may remain the current Python dashboard's
  default unless changed during implementation
- y-axis is shared across entity tiles

End-faceted mode:

- one tile for front and one tile for rear
- selected entities are overlaid as colored distribution series within each end
- x/y scale rules remain panel-level shared

Sector mode:

- one tile per selected entity
- front and rear arranged horizontally inside the tile
- sectors arranged vertically in track order
- each front/rear role uses ridgeline-style distributions by sector

### 8.3 Event Counts Panel

Purpose:

Show event counts by entity and front/rear role.

Reasoning:

Event counts may span several orders of magnitude, so tabular display is
preferred over bar charts for the first version.

Inputs:

- selected visualization entities
- front event signal selector
- rear event signal selector
- event table data
- optional sector assignments, if later extended

Whole-entity mode:

- one tile per selected entity or one table spanning entities
- counts grouped by event type and front/rear role
- groupings use pooled events

Sector mode:

- optional for later implementation
- if implemented, sectors are vertical and ordered by track order
- counts remain tabular

### 8.4 Compression Metrics Panel

Purpose:

Show compression metric relationships for selected entities.

Current default:

- event type: `compressions_all`
- x metric: `m_stroke_disp_max`
- y metric: `m_interval_vel_max`

Whole-entity mode:

- one tile per selected entity
- front and rear may be shown on the same scatter chart
- shared x/y axes across all entity tiles
- regression/fit overlays may remain if already supported and meaningful

End-faceted mode:

- one tile for front and one tile for rear
- selected entities are overlaid as colored scatter series within each end
- best-fit lines, equations, and `R^2` are shown per entity series when enough
  points are available

Sector mode:

- defer in first version
- future behavior: facet vertically by sector
- do not implement sector support for compression scatter in the first slice

### 8.5 Rebound Metrics Panel

Purpose:

Show rebound metric relationships for selected entities.

Current default:

- event type: `rebounds_all`
- x metric: `m_stroke_disp_max`
- y metric: `m_interval_vel_min`

Whole-entity mode:

- one tile per selected entity
- front and rear may be shown on the same scatter chart
- shared x/y axes across all entity tiles
- regression/fit overlays may remain if already supported and meaningful

End-faceted mode:

- one tile for front and one tile for rear
- selected entities are overlaid as colored scatter series within each end
- best-fit lines, equations, and `R^2` are shown per entity series when enough
  points are available

Sector mode:

- defer in first version
- future behavior: facet vertically by sector
- do not implement sector support for rebound scatter in the first slice

## 9. Browser Data Shape

Create browser-side domain types for visualization records. These may be built
from multiple API responses, but downstream chart components should consume a
tidy shape rather than raw service payloads.

Recommended record shape:

```text
entity_id
entity_label
entity_type          session | grouping
source_session_ref_id
source_session_key
source_run_id
source_session_id
signal_role          front | rear
sector_id
sector_label
sector_order
quantity             displacement | velocity | event_count | event_metric
value
unit
metric_name
event_type
time_s
```

Not every field is required for every panel. Missing fields should be explicit
null/empty values rather than inferred from labels.

Recommended TypeScript locations:

```text
application/cohort-workbench-prototype/src/domain/
application/cohort-workbench-prototype/src/components/
```

Prefer keeping data shaping in domain/helper modules and rendering in chart
components. Avoid embedding Library API response handling deeply inside visual
components.

## 10. API And Data Access Requirements

### 10.1 Existing API To Reuse

Use the current Library API for:

- library/catalog loading
- Study Set loading
- session references and entity membership
- event and metric query endpoints where available
- time-series windows for trace-style views where downsampling is acceptable
- track/trackpoint metadata where needed

### 10.2 Distribution Data Requirement

Histogram, percentile, and ridgeline views require distribution-correct data.

Acceptable first-version approaches:

- add or use a Library API signal query endpoint that returns raw or
  distribution-correct samples for selected sessions/signals
- add a Library API distribution endpoint that returns bin counts and summary
  stats for selected sessions/signals
- use `timeseries/window` only if the requested payload is not display-decimated
  or the endpoint explicitly returns distribution-correct samples

Do not silently compute histograms or summary stats from min/max bucket
decimated trace data.

### 10.3 Event And Metric Data Requirement

Compression/rebound scatter and event count panels require event/metric rows for
the selected entities.

If `events/query` and `metrics/query` are already implemented, use them. If not,
the first implementation should add minimal table-oriented API support rather
than reading artifacts directly in the browser.

### 10.4 Grouping Resolution

The browser may resolve a grouping into member session references from the Study
Set object. API requests can then be made per member session and pooled in the
browser, provided the data volume remains acceptable.

If grouping data volumes become large, move pooling/summary work server-side in
a later slice.

## 11. User Controls

Minimum first-version controls:

- entry point from the session browser / Study Set browser
- visualization entity selector: sessions and groupings, groupings deselected by
  default
- visualization scope selector: whole session vs sector scaffold
- comparison layout selector: entities as columns vs ends as columns
- panel collapse/expand
- sector breakdown toggle, initially scaffolded for displacement and velocity
  panels
- engineering-unit display option for displacement stats if engineering-unit
  values are available

Nice-to-have but not required for first implementation:

- select all sessions
- select all groupings
- reset entity visibility
- per-panel chart options
- save visualization setup
- single-session time-window navigator

Visualization entity selection is local to the visualization view and must not
mutate the Study Set.

## 12. Implementation Plan

### Slice 1: Browser Shell And Entity-First Whole-Session View

Status: implemented

Goal:

Add the suspension visualization view to the browser session/study-set browser
with whole-session entity-first panels and no sector mode.

Expected work:

- add a session-browser visualization entry point
- add visualization entity selection backed by the loaded Study Set
- list sessions and groupings together, with groupings deselected by default
- create collapsible panel components
- create horizontally scrolling entity strips
- add browser-side data/domain helpers for entity, role, and panel data
- implement whole-session displacement and velocity distribution panels
- implement event counts as tabular display
- implement compression and rebound scatter panels with front/rear on the same
  chart per entity
- use fixed front/rear colors

Acceptance criteria:

- user can open the visualization view from a loaded Study Set/session browser
  context
- user can select one or more session entities for visualization
- groupings appear but are deselected by default
- enabling a grouping pools member-session samples/events where supported
- displacement and velocity panels compare front/rear within each entity
- compression and rebound panels show front/rear on the same chart per entity
- event counts are readable as tables
- axes are shared at panel level where specified
- large selections scroll horizontally rather than breaking layout
- frontend build passes

### Slice 1A: Comparison Layout Flip

Status: implemented

Goal:

Allow the user to flip the two primary comparison dimensions without changing
the selected Study Set entities.

Expected work:

- add a comparison-layout control
- keep `Entities as columns` as the default mode
- add `Ends as columns` mode for distribution and metric scatter panels
- overlay selected entities as colored series inside front/rear tiles
- keep event counts table-oriented

Acceptance criteria:

- user can switch between entity-faceted and end-faceted layouts at runtime
- no new API request is required when only the layout changes
- distribution panels remain scale-comparable across the panel
- compression and rebound scatter panels keep shared axes and regression
  summaries in both modes

### Slice 2: API Hardening For Chart-Ready Data

Status: minimal implementation complete; continue hardening as data volume and
sector requirements become clearer

Goal:

Ensure the browser is receiving statistically valid data for distributions,
events, and metrics.

Expected work:

- review existing `signals/query`, `events/query`, `metrics/query`, and
  `timeseries/window` behavior
- add minimal API support if needed for distribution-correct samples or
  server-computed distribution bins
- add request/response types in the browser data source layer
- add tests for data-source mapping and distribution correctness assumptions

Acceptance criteria:

- displacement and velocity histograms are not built from display-decimated
  data
- event count inputs include all relevant events for selected entities
- scatter inputs include matching event/metric rows
- browser components consume stable typed data-source methods rather than ad
  hoc fetch calls

### Slice 3A: Sector Mode UI Scaffold

Status: implemented

Goal:

Expose sector mode in the visualization UI without pretending sector data
slicing is complete.

Expected work:

- add a visualization scope control: whole session vs by sector
- use Study Set `trackIds` and loaded track records to select a track
- derive trackpoint-bounded sector rows from ordered trackpoints
- show sector rows in displacement and velocity panels when sector mode is
  selected
- show clear deferred-state messaging for metric scatter panels

Acceptance criteria:

- sector mode is disabled or unavailable when no track is attached
- track selection appears when sector mode is active
- displacement and velocity panels show ordered sector scaffold rows
- compression and rebound panels clearly state that sector scatter is deferred
- frontend build passes

### Slice 3B: Add Distribution Sector Data And Ridgelines

Status: initial browser-side implementation complete

Goal:

Add real sector breakdown for displacement and velocity distributions.

Expected work:

- use `signals/query` raw time arrays for sample timestamps
- use loaded track match summaries for per-session trackpoint crossing times
- assign displacement/velocity samples to sectors in the browser when both
  bounding trackpoints have valid crossing times
- produce ridgeline-style distributions by sector
- keep sector rows stable and ordered by track order
- show empty rows/cells for missing sector data

Acceptance criteria:

- sector mode affects displacement and velocity panels first
- sector mode works for one session and multiple sessions
- entities remain arranged horizontally
- front/rear are adjacent horizontally within entity tiles
- sectors are vertical and ordered by track order
- groupings pool samples by sector where sector assignment is available
- sectors with missing crossing intervals remain visible but empty
- frontend build passes

Current limitations:

- sector assignment is browser-side and interval-based; it depends on loaded
  `SessionTrackMatchRecord.trackpointResults[].crossingTimeS` values.
- samples are assigned to the time interval between adjacent crossed
  trackpoints; this does not yet account for path direction beyond using the
  min/max crossing time as the interval.
- compression/rebound scatter sector mode remains deferred.
- event-count sector mode remains deferred.
- no server-side sector cache or chart-ready sector aggregation exists yet.

### Slice 4: Polish And Error Handling

Goal:

Make the view robust enough for routine browser use.

Expected work:

- improve loading, empty-data, and unsupported-data states
- add warnings for groupings where pooling is not meaningful
- ensure chart labels and legends remain readable
- keep layout usable on tablet-sized displays or larger
- add manual validation notes to the relevant browser handoff or README

Acceptance criteria:

- missing front/rear signals produce clear messages
- missing sector data produces clear messages
- API failures produce recoverable UI states
- large selections remain usable
- no raw exception text is shown for ordinary missing-data conditions

## 13. Testing Plan

Automated tests should be added where practical for data preparation helpers and
browser components.

Recommended frontend/unit tests:

- entity list includes sessions and groupings, with groupings deselected by
  default
- grouping distribution input pools member-session samples
- front/rear roles are kept separate and not pooled
- displacement x-axis domain remains fixed `0..1`
- sector ordering follows track order
- missing sector rows are preserved in sector-mode data
- event-count grouping pools events correctly
- data-source methods reject or flag decimated data when distribution-correct
  data is required

Recommended browser/manual tests:

- start the Library API service against a real library root
- start the Vite browser app
- load a Study Set containing one session
- open the suspension visualization view
- load a Study Set containing multiple sessions
- load a Study Set containing at least one grouping
- confirm groupings are visible but initially deselected
- enable a grouping and confirm distributions/events pool member data
- verify front/rear colors are consistent across panels
- verify horizontal scrolling works with many selected entities
- verify sector mode for displacement and velocity where sector data exists
- verify sector mode missing-data behavior where sector data does not exist

Recommended commands:

```powershell
cd C:\Users\benco\dev\BODAQS\application\cohort-workbench-prototype
npm run build
```

If API code is changed:

```powershell
cd C:\Users\benco\dev\BODAQS\analysis
..\.venv\Scripts\python.exe -m pytest
```

## 14. Assumptions

The implementation may proceed using these assumptions unless contradicted:

- "Session browser" means the React/TypeScript browser application's
  session/study-set browser area, not the Jupyter `bodaqs_session_browser`
  notebook.
- Study Set groupings are available in the loaded Study Set object.
- A grouping can be resolved to member sessions in browser state.
- Pooled raw samples/events are the correct default for grouping visualization.
- Front/rear colors should be fixed globally.
- Displacement distributions use normalized displacement as the primary x-axis.
- Track sectors, where present, have a stable order derived from track order.
- Horizontal scrolling is acceptable for entity overflow in the prototype.
- Sector support is required first for displacement and velocity only.
- Time-window navigation is omitted from the first version.

## 15. Ambiguities And Design Questions

The following should be reviewed before or during implementation:

- Exact front/rear color tokens are not finalized.
- The exact browser entry point is not specified: implementation may add a
  dedicated "Visualize" mode/tab/panel inside the current session browser /
  Study Set browser UI.
- The precise API shape for distribution-correct signal samples or server-side
  histogram bins may need to be defined before Slice 1 can be fully useful.
- The precise storage/location of per-sample sector assignments may need code
  inspection before Slice 3.
- If sector assignments are not already materialized per sample, Slice 3 may
  require a new computation/cache layer rather than only a frontend change.
- The preferred ridgeline implementation is not fixed. D3 or Observable Plot are
  both acceptable for the first browser implementation if wrapped behind a
  reusable component boundary.
- For grouping scatter plots, it is assumed that plotting all pooled events is
  acceptable. If this becomes visually noisy, a summary mode may be needed.
- Event count sector mode is intentionally deferred, but the eventual table
  layout should be revisited once sector data volume is better understood.
- Panel collapse state persistence is not specified. First implementation may
  keep it runtime-only.
- Visualization entity selection persistence is not specified. First
  implementation may keep it runtime-only.

## 16. Future Roadmap Items

Potential follow-up work:

- saved visualization setups
- advanced comparison/spec builder
- single-session displacement navigation / time-window scope
- per-entity time windows, only if a clear use case emerges
- sector support for compression/rebound metric scatter
- metric-distribution panels for compression/rebound metrics
- richer distribution forms such as violin plots
- reusable visualization-spec contract shared by notebooks and browser
- server-side chart-ready aggregation endpoints if browser-side pooling becomes
  too slow for large Study Sets
