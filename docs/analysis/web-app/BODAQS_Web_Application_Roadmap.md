# BODAQS Application Roadmap

**Status:** Discussion draft
**Date:** 2026-05-28
**Audience:** BODAQS project team

## Purpose

This document describes the recommended direction for evolving BODAQS from a
notebook-driven analysis workflow toward a product application.

The current direction is browser-first, local-first, and service-backed for the
first implementation. The application should work with user-owned processed
BODAQS libraries without requiring cloud services, Jupyter runtime state, or an
expanded Import Manager scope.

The first product seam is the **BODAQS Library API**: a local Python service that
reads processed libraries, manages Study Sets, and serves chart-ready data to a
browser frontend.

## Current BODAQS Starting Point

BODAQS analysis is already part-way toward an application architecture.

Today, the system includes:

- reusable Python analysis code in `analysis/bodaqs_analysis/`
- notebook-based orchestration and UI in `analysis/*.ipynb`
- an installed Import Manager for local acquisition and preprocessing
- an explicit on-disk artifact model for processed sessions and derived outputs
- documented public analysis interfaces and contracts
- notebook consumer widgets that already separate some data preparation from rendering

This means the migration is not primarily about rewriting the analysis logic. It
is mainly about separating product interaction from notebook runtime state,
while preserving the existing processing engine and artifact structure.

Relevant existing references:

- [`BODAQS_Library_API_Contract_v0_draft.md`](../contracts/BODAQS_Library_API_Contract_v0_draft.md)
- [`BODAQS_Public_API_Contract_v0.md`](../contracts/BODAQS_Public_API_Contract_v0.md)
- [`BODAQS_analysis_artifacts_specification_v0_2.md`](../contracts/BODAQS_analysis_artifacts_specification_v0_2.md)
- [`BODAQS_session_selector_consumer_widgets_contract.md`](../contracts/BODAQS_session_selector_consumer_widgets_contract.md)
- [`BODAQS_Analysis_Notebook_Overview.md`](../notebooks/BODAQS_Analysis_Notebook_Overview.md)

## Product Direction

The starting point for user interaction is the BODAQS library.

A user opens or connects to a library, selects or creates a **Study Set**, then
uses that Study Set as the basis for analysis, comparison, charting, notes,
exports, and reports.

A Study Set is a named analysis scope stored under the configured libraries
root. It should be explicit and stable once saved, and it may include sessions
from more than one library. It may include:

- explicit session references
- Study Set-local groupings
- Study Set-local bookmarks
- reusable track references
- provenance explaining how the Study Set was created
- optional namespaced display state

Study Sets should be first-class, versioned library objects, not only transient
UI state.

Filters are helper tools used to find, narrow, validate, or refresh candidate
membership. They should not be the hidden source of truth for saved Study Set
membership.

## Session Identity

The practical session identity remains:

```text
<run_id>::<session_id>
```

Study Set session references should carry:

- `library_id`
- `session_ref_id`
- `session_key`
- `run_id`
- `session_id`
- optional display label

`run_id` and `session_id` are canonical. `session_key` is a readable convenience
field that should be validated against those values. `session_ref_id` is
`library_id|||session_key` and is the stable reference used by Study Set
groupings and bookmarks.

## Core Architecture

```text
Browser application
  -> frontend LibraryDataSource
  -> localhost BODAQS Library API
  -> Python library adapter
  -> processed BODAQS library
```

The first implementation should use the local Library API as the primary data
source. This gives the browser a stable API seam while keeping Python
authoritative for artifact interpretation, Parquet reads, signal semantics, and
time-series window preparation.

The frontend should default to a configured local API URL, initially
`http://127.0.0.1:8765` unless overridden by deployment configuration. If the
service is reachable but pointed at the wrong workspace, the Library Selector
should provide a fallback "select library root" control that asks the local API
to switch its active `libraries_root`.

The API is not an Import Manager API. Import Manager remains responsible for
import, logger transfer, preprocessing, and artifact writing. The Library API is
responsible for processed-library browsing, Study Set persistence, and
visualisation data.

The frontend should still keep its own `LibraryDataSource` boundary so future
data sources can be added without rewriting charts and product UI. Future
implementations may include static bundles, browser-local file access, or remote
services, but those modes should not drive the first build.

## Deployment Modes

### Installed Local Mode

Installed local mode is the first target.

The user has:

- one configured libraries root
- one or more processed BODAQS libraries under that root
- a localhost Library API service bound to `127.0.0.1`
- a browser frontend that talks to the local service

This mode supports offline operation, efficient Parquet access, local Study Set
writes, and Python-backed time-series preparation without requiring internet
connectivity.

The browser does not need direct filesystem custody of the library root in this
mode. It should ask the local API which libraries are available. The optional
root selector is a setup fallback for changing the service's active root, not a
browser-side directory reader.

### Browser-Local Mode

Browser-local mode means the browser opens a BODAQS library or workspace bundle
directly using browser file APIs.

This remains useful, but is deferred. Browser file and directory write support
varies across browsers, and heavy processed-artifact reads are better served by
the Python adapter in the first implementation.

### Static Bundle Mode

A processed library and the web app may later be packaged together as a
"website in a box."

This is suitable for demos, reports, training material, and read-only review.
It works best when the bundle includes prebuilt catalogs, Study Sets, and
chart-ready payloads.

Static bundle mode is not part of the first implementation.

### Remote Service Mode

A future browser app may connect to a hosted backend that can serve libraries or
provide heavier query support.

This remains useful for cloud workflows, collaboration, public demos, or users
who prefer zero-install operation. It is not part of the first implementation.

## Browser Responsibilities

The browser should own the product experience:

- library selection from the service-reported library list
- Study Set creation, editing, selection, and comparison
- analysis-view launch, adequacy feedback, and addressable analysis tabs
- reloadable analysis routes for saved Study Sets, with temporary browser-local
  routes for unsaved analysis scopes
- session catalog browsing
- interactive helper filtering, searching, and sorting
- comparison layout
- chart rendering with React, D3, Canvas, SVG, WebGL, uPlot, or similar tools
- pan, zoom, brush, hover, and linked-chart interaction
- UI state and draft view state
- display of note, QC, provenance, event, metric, and signal summaries

For processed libraries, the browser can realistically perform much of the
current notebook consumer experience, provided the local service supplies
semantic catalog data and chart-ready time-series windows.

Prototype-only UI preferences, such as session-table column visibility and
column order, may initially use browser `localStorage` so iteration remains
fast. Longer term, durable UI preferences that are associated with a configured
libraries root should be exposed through the Library API as root-level
namespaced preferences, not hidden in Study Sets unless they are genuinely
Study Set-specific display state.

## Python Adapter And Local Service Responsibilities

Python should remain authoritative for:

- processed library discovery
- artifact layout interpretation
- Parquet reads
- signal registry resolution
- semantic signal selection
- event and metric table loading
- time-series window extraction
- large time-series downsampling
- Study Set file validation and revision-safe writes
- provenance and QC interpretation

Python should also remain authoritative, outside the Library API scope, for:

- raw logger import
- session archive validation
- metadata interpretation
- FIT parsing and enrichment
- preprocessing profiles
- calibration and derived-signal materialisation
- filtering and motion derivation
- event detection
- metric extraction
- canonical artifact writing

## Study Set Contract

Study Sets are versioned, portable objects stored with the configured libraries
root.

Canonical storage shape:

```text
<libraries_root>/
  study_sets/
    <study_set_id>.json
```

Separate files reduce write conflicts, make saves simple, and allow Study Sets
to be copied, shared, reviewed, and versioned independently.

A Study Set should describe explicit committed scope:

- explicit session references
- Study Set-local groupings
- Study Set-local bookmarks
- reusable track references
- display preferences that are truly Study Set-specific
- provenance explaining how the Study Set was created

A Study Set should avoid duplicating session data. It should reference library
artifacts and record selection intent.

Filters may be recorded as Study Set provenance, for example "created from
filter X at time Y", but a filter should not define live Study Set membership.
If a user wants to refresh a Study Set from a saved filter later, that should be
an explicit review-and-apply action.

Study Set writes should use revision checks so two browser tabs or machines do
not silently overwrite each other.

The Study Set contract is documented in:

- [`BODAQS_Library_API_Contract_v0_draft.md`](../contracts/BODAQS_Library_API_Contract_v0_draft.md)

## Tracks, Bookmarks, Groupings, And Filters

### Tracks

Tracks are reusable root-level objects. A track is a GPS path or route,
optionally derived from a session but not required to be tied to one.

Canonical future storage shape:

```text
<libraries_root>/
  tracks/
    <track_id>.json
```

A track may have zero or more named points. A Study Set can reference a whole
track or a track interval defined by two track points.

Track and trackpoint inventory should remain cheap descriptive data. It should
tell the browser what tracks and trackpoints exist, their names, station
positions, revisions, and policy references. It should not include expensive
session-to-trackpoint match results.

Track contracts are included in the Library API and geospatial contracts.
Trackpoint match results belong in a separate derived query/cache layer.

### Bookmarks

Bookmarks are embedded in Study Sets. They refer to a point or time window in a
single session and are not reusable library objects in v0.

### Groupings

Groupings are simple named buckets of sessions inside a Study Set. They are not
persisted independently and do not require richer roles or semantics for v0.

### Filters

Filters are reusable library helpers for finding candidate sessions. They are
stronger reusable concepts than groupings, but they still do not define saved
Study Set membership.

Catalog-backed filters can be evaluated in the browser after loading the
session catalog and persisted filter definitions. Trackpoint-backed filters
should be API-backed because they depend on track revision, geospatial policy,
tolerance, GPS source identity, and matching algorithm version.

Trackpoint-backed filters should use an asynchronous query/index pattern:

- the filter definition records the track, trackpoints, match mode, and
  tolerance.
- the browser asks the Library API to create or resume a
  `TrackpointMatchQuery`.
- the service processes broad scopes in the background and reuses cached
  per-session match evidence.
- the browser polls status and pages matched session refs into the active
  filter result.
- rejected sessions are not returned by default; diagnostics can be optional.

## Recommended Technical Pattern

The frontend should define a small `LibraryDataSource` interface and build UI
components against that interface.

Initial implementation:

```text
LocalApiDataSource
```

Future implementations may include:

```text
StaticBundleDataSource
BrowserDirectoryDataSource
RemoteApiDataSource
```

The first endpoint set should be deliberately small:

```text
GET  /api/v1/health
GET  /api/v1/capabilities
POST /api/v1/config/libraries-root
GET  /api/v1/libraries
GET  /api/v1/libraries/{library_id}
POST /api/v1/libraries/{library_id}/refresh
GET  /api/v1/libraries/{library_id}/catalog

GET    /api/v1/study-sets
POST   /api/v1/study-sets
GET    /api/v1/study-sets/{study_set_id}
PUT    /api/v1/study-sets/{study_set_id}
DELETE /api/v1/study-sets/{study_set_id}

POST /api/v1/libraries/{library_id}/timeseries/window
```

The first visualization should use `timeseries/window` for one session at a
time. Requests should support semantic signal selectors and concrete column
names. Responses should use JSON arrays in v0 and may use Arrow or another
binary encoding later.

## Implementation Roadmap

### Phase 0: Contract Baseline

Goal: define enough contract shape to let frontend and backend work proceed in
parallel.

Status: completed for the initial v0 implementation baseline.

Work in this phase:

- define the Library API resource model
- define Study Set v1
- define Track v1, without implementing track endpoints yet
- define session catalog row v1
- define capability reporting
- define time-series window request/response v1
- define endpoint list and error response shape

Expected outcome:

- a shared contract document that both the local service and browser frontend
  can build against

Primary artifact:

- `docs/analysis/contracts/BODAQS_Library_API_Contract_v0_draft.md`

### Phase 1: Python Library Adapter

Goal: build reusable Python functions that read processed BODAQS libraries and
emit the API payloads.

Work in this phase:

- discover libraries under one configured libraries root
- load library metadata
- build an in-memory session catalog from run/session artifacts
- include compact semantic signal summaries in catalog rows
- include note status and projected `bike` / `rider` fields where available
- include QC, event schema, event summary, metric summary, timestamps, and compact provenance
- implement Study Set load/save/delete helpers with revision checks
- implement ID derivation from display names
- implement a one-session time-series window helper
- implement raw-or-min/max-bucket downsampling
- add tests around catalog generation, Study Set writes, and time-series windows
- generate one static fixture library payload for frontend development

Expected outcome:

- notebooks and service code can call the same library adapter
- George can receive stable fixture data for the first browser-native chart
- Study Set builder work can proceed without depending on chart implementation

### Phase 2: Local Library API Service

Goal: wrap the Python library adapter in a small localhost HTTP service.

Work in this phase:

- choose a minimal Python HTTP framework
- bind to `127.0.0.1`
- read local service config containing `libraries_root`
- expose a local setup endpoint for switching the active `libraries_root`
- implement `health`, `capabilities`, `libraries`, `refresh`, `catalog`, Study Set CRUD, and `timeseries/window`
- keep import/preprocessing endpoints out of scope
- provide consistent API error responses
- add lightweight service tests using a temporary processed-library fixture

Expected outcome:

- the browser app can talk to a real local service without knowing the artifact layout

### Phase 3: Frontend Shell And Data Source Boundary

Goal: start the browser app around the Library API contract.

Work in this phase:

- scaffold the React/TypeScript frontend if not already present
- define domain types for libraries, sessions, Study Sets, signals, events, and time-series windows
- implement `LibraryDataSource`
- implement `LocalApiDataSource`
- implement `FixtureLibraryDataSource` for George's static development fixture
- build a basic library selector
- default to the configured local API URL and provide a Library Selector fallback for changing the active root
- build a basic session catalog table
- persist first-cut session table layout locally in the browser
- add a follow-on Library API contract for root-level UI preferences, including
  session table visibility/order and other app display preferences that should
  follow the configured libraries root
- load and display service capabilities

Expected outcome:

- the frontend has a stable data boundary and can run against either the local API or fixture data

### Phase 4: Study Set Builder

Goal: build the first browser-native library manager / Study Set workflow.

Work in this phase:

- create Study Sets from explicit selected sessions
- edit Study Set display names
- add/remove Study Set sessions
- create/edit simple groupings
- create/edit single-session bookmarks
- reference tracks where present, without requiring track CRUD
- save Study Sets through the local API with revision checks
- handle revision conflicts clearly
- show Study Set summaries

Expected outcome:

- a user can open a processed library, create a Study Set, save it as a library object, and reopen it

### Phase 5: First Browser-Native Visualization

Goal: implement the first high-value chart against the time-series window
endpoint.

Work in this phase:

- request front/rear wheel displacement by semantic selector
- render one-session time-series windows
- display event overlays returned by the endpoint
- support pan/zoom/window changes
- request downsampled windows using `target_points`
- show warnings from the time-series response
- keep chart components independent of the service implementation

Expected outcome:

- George can build and iterate on a real browser-native suspension time-series view

### Phase 6: Event And Metric Exploration

Goal: expand beyond the first time-series chart into notebook-equivalent
consumer views.

Work in this phase:

- implement event table queries
- implement metric table queries
- build metric scatter and histogram views
- build signal histogram views
- link Study Set, catalog, chart, event, and metric selections

Expected outcome:

- the browser app covers a meaningful subset of the current consumer notebook experience

### Phase 7: Tracks, Map Prototype, And Trackpoint Filters

Goal: prove reusable tracks, trackpoint inventory, and broad trackpoint-backed
filters with processed sessions that include GPS data.

Work in this phase:

- render session GPS paths on a browser map
- create reusable track objects from session paths where useful
- add/edit track points
- reference whole tracks or point-to-point intervals from Study Sets
- preview session coverage over a selected track interval
- keep the session catalog compact and track-independent
- add async trackpoint match query endpoints with status polling and paged
  matched-session results
- cache match evidence by session GPS identity, track revision, policy,
  tolerance, match mode, and algorithm version
- add browser UI states for queued, running, partially available, complete,
  cancelled, and failed trackpoint filters
- defer a general server-side saved-filter evaluator until the prototype proves
  the filter contract and at least one expensive predicate
- harden derived-cache invalidation after the first trackpoint-filter UI slice,
  including track revision, policy version, session GPS identity, tolerance,
  match mode, and algorithm version

Expected outcome:

- reusable track objects and trackpoint-backed filters can feed Study Set
  creation without becoming hidden Study Set state

Implementation sequence:

1. Finalize the `trackpoint.crossing` persisted-filter predicate shape.
2. Add Library API request/status/results models for `TrackpointMatchQuery`.
3. Implement a simple in-process job runner for local service development.
4. Reuse existing per-session `SessionTrackMatch` evidence where possible.
5. Persist query status/results under the libraries root as derived cache.
6. Wire the frontend filter pane to start/resume a query when a trackpoint
   filter is applied.
7. Apply matched session refs incrementally as results arrive.
8. Add cancellation and clear user messaging before optimizing the worker.
9. Add a general server-side saved-filter evaluation endpoint once catalog,
   geospatial, signal-content, and adequacy predicates need one shared execution
   path.
10. Replace the first-cut derived-cache checks with explicit stale detection and
    cache refresh controls.

### Phase 8: Static Bundles And Remote Options

Goal: add secondary deployment modes only after the local API-backed app is
working.

Possible work in this phase:

- static "website in a box" export
- read-only review bundles
- browser-local directory access
- remote service adapter
- authentication and hosted-service concerns, if needed

Expected outcome:

- the application can expand beyond installed local use without changing its core concepts

## Suggested First Deliverable

The first meaningful application milestone should support this flow:

1. Start the local Library API service against a configured libraries root.
2. Open the browser application.
3. Select an existing processed BODAQS library.
4. Browse the session catalog.
5. Inspect note, QC, provenance, event schema, signal, event, and metric summaries.
6. Create a Study Set from explicit sessions.
7. Save and reload the Study Set as a canonical library object.
8. Open a browser-native time-series window for one session in the Study Set.
9. View front/rear wheel displacement and event overlays.

This first deliverable keeps the focus on the processed-library and Study Set
model before adding import, preprocessing, tracks, saved filters, static
bundles, or hosted-service complexity.

## Design Principles For The Product

- The BODAQS library is the primary user data object.
- Study Sets are the primary analysis scope.
- Saved Study Sets should be explicit and stable, not live filters.
- Filters are helper tools for finding, validating, and refreshing candidate scope.
- Tracks are reusable root-level objects, not private Study Set state.
- Bookmarks and groupings are Study Set-local in v0.
- Browser UI owns visualisation and interaction.
- Python owns canonical processing, artifact interpretation, and heavy data preparation.
- Local-first and offline use are first-class requirements.
- The Library API should remain separate from Import Manager import/preprocessing scope.
- The app should avoid depending on Jupyter runtime state.
- User-owned local libraries should remain usable outside the application where practical.

## Risks And Decisions To Resolve

The following decisions will materially affect implementation detail:

- which Python HTTP framework to use for the local service
- exact local service configuration file location
- how the browser discovers the local service port in installed mode
- whether development mode needs no auth and packaged mode needs a local token
- how much catalog data can be built quickly enough at service startup
- how broad trackpoint match jobs should be scheduled, cancelled, resumed, and
  expired
- how much trackpoint match evidence should be retained in the derived cache
- exact min/max downsampling behavior for multiple signals
- how much event detail should be included in first time-series overlays
- what browser charting library George should use for dense time-series data
- whether Study Set files need additional migration/versioning helpers before wider use
- when to add track CRUD and map support

## Things To Avoid

- Expanding Import Manager into a general application backend.
- Requiring internet access for field analysis.
- Exposing Jupyter or notebook sessions directly as the external product.
- Rewriting the Python analysis engine prematurely.
- Making the frontend depend on raw notebook-specific data structures.
- Treating Study Set selection as temporary UI state only.
- Treating saved filters as hidden live Study Set definitions.
- Hiding reusable tracks inside Study Set documents.
- Putting trackpoint match results into the main session catalog.
- Making a broad library-scale trackpoint filter block one HTTP request until
  all candidate sessions have been processed.
- Building the first visualization directly against raw artifact paths.
- Building separate incompatible apps for local, static, browser-local, and remote modes.

## Summary Recommendation

The recommended path is to build a browser-first BODAQS application around
processed libraries, canonical Study Set objects, and a local Python-backed
Library API.

The browser should provide the primary visualisation and interaction experience.
Python should remain authoritative for processed-artifact interpretation,
Parquet reads, signal semantics, downsampling, and Study Set persistence.

The first implementation should support local offline use through a dedicated
localhost Library API service, while keeping static bundle, browser-local, and
remote service modes as future-compatible deployment paths rather than first
drivers.
