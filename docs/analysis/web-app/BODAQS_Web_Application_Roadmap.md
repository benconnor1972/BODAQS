# BODAQS Application Roadmap

**Status:** Discussion draft  
**Date:** 2026-05-23  
**Audience:** BODAQS project team

## Purpose

This document describes the recommended direction for evolving BODAQS from a
notebook-driven analysis workflow toward a product application.

The current direction is browser-first, offline-capable, and backend-optional.
Zero-install web use remains valuable where it fits, but it cannot cover all
important use cases because field use may involve no internet connection.

The architecture should support multiple deployment modes over the same BODAQS
library and cohort contracts.

## Current BODAQS Starting Point

BODAQS analysis is already part-way toward an application architecture.

Today, the system includes:

- reusable Python analysis code in `analysis/bodaqs_analysis/`
- notebook-based orchestration and UI in `analysis/*.ipynb`
- an installed Import Manager direction for local acquisition and import
- an explicit on-disk artifact model for processed sessions and derived outputs
- documented public analysis interfaces and contracts
- notebook consumer widgets that already separate some data preparation from rendering

This means the migration is not primarily about rewriting the analysis logic.
It is mainly about separating product interaction from notebook runtime state,
while preserving the existing processing engine and artifact structure.

Relevant existing references:

- [`BODAQS_Public_API_Contract_v0.md`](../contracts/BODAQS_Public_API_Contract_v0.md)
- [`BODAQS_analysis_artifacts_specification_v0_2.md`](../contracts/BODAQS_analysis_artifacts_specification_v0_2.md)
- [`BODAQS_session_selector_consumer_widgets_contract.md`](../contracts/BODAQS_session_selector_consumer_widgets_contract.md)
- [`BODAQS_Analysis_Notebook_Overview.md`](../notebooks/BODAQS_Analysis_Notebook_Overview.md)

## Product Direction

The starting point for user interaction is the BODAQS library.

A user opens or connects to a library, selects or creates a cohort, then uses
that cohort as the basis for analysis, comparison, charting, notes, exports,
and reports.

A cohort is a named or temporary analysis scope. It should be explicit and
stable once saved. It may include session references, aggregation references,
bookmark references, geographical section references, comparison labels, display
state, and provenance explaining how the scope was created.

Cohorts should be first-class, versioned library objects, not only transient UI
state.

Filters are helper tools used to find, narrow, validate, or refresh candidate
membership. They should not be the hidden source of truth for saved cohort
membership.

## Session Identity

The practical session identity remains:

```text
<run_id>::<session_id>
```

This is assumed to be unique for normal single-library workflows and is also
expected to be unique enough for current multi-library exploration. The first
application implementation should not redesign the whole cohort model around
multi-library identity.

If later required, session references can gain an optional `library_id` or
`library_ref` field without changing the core principle that cohort membership
is explicit.

## Core Architecture

```text
Browser application
  -> data source interface
  -> local API, browser-local library, static bundle, or remote API
  -> BODAQS processed library
  -> optional Python processing engine
```

The browser application should not care whether a library is reached through a
local Import Manager, a static website bundle, direct browser file access, or a
remote service. Each mode should expose the same conceptual operations:

- list libraries
- list sessions
- load cohorts
- save cohorts where the data source is writable
- load signal metadata
- load events and metrics
- request chart-ready time-series windows
- request summaries and downsampled traces
- export selected data or a workspace bundle

## Deployment Modes

### Installed Local Mode

The Import Manager manages a user-owned local BODAQS library and may expose a
localhost API to the browser UI.

This is the strongest field-use mode because it supports offline operation,
local Python processing, folder watching, artifact writing, and efficient
Parquet access without requiring internet connectivity.

The Import Manager does not need to own all application state. Cohorts are
canonical library objects and may be written by the browser directly where the
browser has appropriate file permissions.

### Browser-Local Mode

The browser opens a BODAQS library or workspace bundle directly using browser
file APIs.

This is suitable for processed-library visualisation and cohort editing where
the browser supports the required file access. It may use browser storage,
Web Workers, DuckDB-WASM, Arrow, or similar browser-side tools for local
querying and interaction.

Browser-local mode is useful, but should not be the only architecture because
local file and directory write support varies across browsers.

### Static Bundle Mode

A processed library and the web app are packaged together as a "website in a
box."

This is suitable for demos, reports, training material, and read-only review.
It works best when the bundle includes prebuilt indexes and chart summaries.

### Remote Service Mode

The browser connects to a hosted backend that can process uploads, serve
libraries, or provide heavier query support.

This mode remains useful for cloud workflows, collaboration, public demos, or
users who prefer zero-install operation. It should be optional rather than
assumed as the primary field workflow.

## Browser Responsibilities

The browser should own the product experience:

- cohort creation and selection
- session catalog browsing
- interactive helper filtering, searching, and sorting
- interactive geographical section editing and preview where practical
- comparison layout
- chart rendering with React, D3, Canvas, SVG, or WebGL
- pan, zoom, brush, hover, and linked-chart interaction
- lightweight filtering and sorting
- UI state and draft view state
- read-only exploration of processed artifacts where practical
- writing cohort files directly where browser-local write support is available

For processed libraries, the browser can realistically perform much of the
current notebook consumer functionality, including event and metric browsing,
histograms, scatter plots, and many session-window visualisations.

## Local Or Server Engine Responsibilities

Python should remain authoritative for:

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
- provenance and QC recording

The local or remote engine may also provide performance-oriented visualisation
support:

- Parquet reads across many sessions
- signal registry resolution
- large time-series downsampling
- multiresolution trace generation
- geospatial filtering over large datasets
- batch coverage calculations for geographical sections
- durable indexes for session catalogs, filters, sections, and cohorts
- writing cohort, bookmark, note, and export artifacts when browser-local writes are unavailable

## Cohort Contract

A cohort should be a versioned, portable object stored with the library.

The preferred canonical storage shape is one cohort document per file:

```text
artifacts/
  library/
    cohorts/
      <cohort_id>.json
```

Separate files reduce write conflicts, make browser-local saves simpler, and
allow cohorts to be copied, shared, reviewed, and versioned independently.

An optional generated cohort index may be added for fast discovery, but the
individual cohort documents should be treated as the canonical source of truth.

A cohort should be able to describe explicit committed scope:

- explicit session references
- aggregation references
- bookmark references
- geographical section references
- time windows or activity regions when they are explicitly selected
- comparison grouping labels
- display preferences that are truly cohort-specific
- provenance explaining how the cohort was created

A cohort should avoid duplicating session data. It should reference library
artifacts and record selection intent.

Filters may be recorded as cohort provenance, for example "created from filter X
at time Y", but a filter should not define live cohort membership. If a user
wants to refresh a cohort from a saved filter later, that should be an explicit
review-and-apply action.

The cohort contract becomes the main handoff between catalog browsing,
visualisation, comparison, exports, and later reporting.

## Filters And Adequacy Checks

Filters should be treated as helper tools for cohort creation, not as canonical
cohort definitions.

A filter may include criteria over:

- visible session catalog columns
- run and session descriptions
- note status and projected note fields
- QC summary status
- provenance and preprocessing settings
- signal registry semantics
- event schema availability
- event and metric contents
- geographical section coverage

Filters may be temporary UI state or saved reusable library helpers. A saved
filter can be useful for repeated discovery, but applying it to a cohort should
produce an explicit set of cohort members.

Adequacy checks are related, but serve a different purpose. An adequacy check
tests whether a cohort can support a view or analysis, for example:

- the cohort has reviewed notes
- the cohort has GPS coverage
- the cohort contains front and rear primary suspension signals
- the cohort uses compatible event schemas
- the cohort covers a required geographical section

Adequacy checks should report pass, warning, or fail states with reasons. They
should help a user improve a cohort without silently changing the cohort.

## Geographical Sections

Geographical sections should be canonical reusable library objects, not private
cohort state.

The preferred storage shape is:

```text
artifacts/
  library/
    geography/
      section_cuts/
        <section_cut_id>.json
      sections/
        <section_id>.json
```

A section cut is an authored boundary on or near a GPS path. A section is a
route region or interval derived from one or more cuts.

A section cut should record enough information to be inspected, redrawn, and
recomputed:

- stable section cut id
- title or label
- reference session key
- snapped point geometry
- cut-line geometry
- route distance or fraction along the reference route
- route bearing at the snapped point
- cut width or extent
- creation and update timestamps

The browser can perform the interactive parts of sectioning for typical
processed sessions:

- show GPS paths on a map
- snap a clicked point to the visible route
- estimate local route direction
- draw a perpendicular cut-line
- preview sections and session coverage
- save section definitions where the current data source is writable

A local API or remote service may be used for heavier or more durable work:

- batch coverage calculations across many sessions
- generation of section coverage indexes
- validation and repair of section definitions
- support for browsers that cannot write local library files directly

## Cohort Writing Model

Cohort writing should be an application/library capability, not an Import
Manager-only capability.

The application should define a small writer interface for cohort storage:

```text
listCohorts()
loadCohort(cohortId)
saveCohort(cohort)
deleteCohort(cohortId)
```

Different deployment modes can implement that interface differently:

- `BrowserDirectoryCohortStore` writes directly to a user-selected library folder where supported.
- `LocalApiCohortStore` asks the installed local service to write the cohort file.
- `DownloadCohortStore` exports a cohort file or updated workspace bundle when direct writes are unavailable.
- `StaticReadOnlyCohortStore` loads bundled cohorts but does not save changes.

This keeps cohort definition conceptually independent of the Import Manager,
while still allowing the Import Manager or local API to be the most reliable
writer in installed mode.

## Recommended Technical Pattern

Define a frontend `LibraryDataSource` interface with implementations such as:

- `LocalApiDataSource`
- `StaticBundleDataSource`
- `BrowserDirectoryDataSource`
- `RemoteApiDataSource`

Each implementation should provide the same application-level methods even if
the backing mechanism differs.

Example operations:

```text
listSessions()
listCohorts()
loadCohort(cohortId)
saveCohort(cohort)
listFilters()
applyFilter(filterCriteria)
listGeographicalSections()
saveGeographicalSection(section)
getSessionMeta(sessionKey)
getSignalCatalog(cohort)
getEvents(cohort, query)
getMetrics(cohort, query)
getTimeseriesWindow(cohort, signals, start, end, resolution)
checkCohortAdequacy(cohort, requirements)
```

This keeps the React/D3 application stable while allowing the deployment model
to evolve.

## Implementation Roadmap

### Phase 0: Contracts And Boundaries

Goal: define the application-level contracts before building a large UI.

Work in this phase:

- define the library catalog contract
- define the cohort contract
- define the filter helper and adequacy-check contracts
- define the geographical section contract
- define the chart-ready payload contract
- define the frontend data source interface
- decide final cohort file locations and ID rules
- decide final geographical section file locations and ID rules
- map existing notebook selector and widget concepts to web concepts
- identify notebook-only dependencies that should not leak into application code

Expected outcome:

- a clear boundary between BODAQS library artifacts, cohort state, processing logic, and browser rendering

### Phase 1: Library Browser Plus Cohorts

Goal: build the first browser UI around an existing processed library.

Work in this phase:

- implement a session catalog
- implement cohort creation and selection
- implement helper filtering over visible catalog columns
- write cohort documents as individual library files where possible
- display cohort summaries
- display note, QC, provenance, and preprocessing indicators
- show event and metric table views
- support at least one read-only data source such as a static bundle or local API

Expected outcome:

- an internal application prototype that can open a processed library, create a cohort, and use that cohort as the analysis scope

### Phase 1A: Geographical Section Prototype

Goal: prove the geographical sectioning model with processed sessions that
include GPS data.

Work in this phase:

- render session GPS paths on a browser map
- create perpendicular section cuts from points on the route
- persist section cuts and sections as canonical library objects where possible
- preview which sessions cover a selected section
- expose section coverage as a filter helper and adequacy-check input

Expected outcome:

- a reusable geographical section model that can feed cohort creation without becoming hidden cohort state

### Phase 2: Browser Visualisation

Goal: rebuild the highest-value notebook visualisations in React/D3 or related browser-native rendering tools.

Work in this phase:

- implement a time-series session window view
- implement an event browser
- implement metric scatter plots
- implement metric histograms
- implement signal histograms
- implement linked cohort and session selection
- define chart-ready API payloads
- add server-side or local downsampling where needed
- add local or server-side section coverage indexes where needed

Expected outcome:

- a browser-native visualisation experience for processed BODAQS libraries

### Phase 3: Installed Offline Mode

Goal: integrate the browser UI with the installed Import Manager where local services are useful.

Work in this phase:

- expose a localhost API for configured local libraries
- support user-owned local library configuration
- add local library indexing
- support local cohort save/load through the API as a fallback or preferred installed-mode writer
- add local chart data endpoints
- support an offline application launch path

Expected outcome:

- a field-usable local application mode that does not require internet connectivity

### Phase 4: Import And Processing Integration

Goal: expose preprocessing workflows through the application while keeping Python as the compute engine.

Work in this phase:

- add import status UI
- add preprocessing profile selection
- run local processing jobs
- write canonical artifacts back to the library
- add progress and error reporting
- add an optional remote processing adapter using the same job model

Expected outcome:

- a product workflow that can import, process, browse, and visualise BODAQS sessions without Jupyter

### Phase 5: Portable Workspaces And Static Sharing

Goal: make export/import and read-only sharing first-class.

Work in this phase:

- define a workspace bundle format
- support cohort export and import
- support static "website in a box" export
- generate report or review bundles
- add compatibility checks for older libraries

Expected outcome:

- portable BODAQS workspaces and static review bundles that preserve cohorts and visualisation context

### Phase 6: Optional Remote Product Hardening

Goal: add hosted-service features only if the product direction requires them.

Possible work in this phase:

- authentication
- accounts
- quotas
- remote job isolation
- cloud retention policy
- collaboration
- billing
- operational monitoring

Expected outcome:

- an externally usable hosted product path, if cloud operation becomes a product requirement

## Suggested First Deliverable

The first meaningful application milestone should support this flow:

1. Open an existing processed BODAQS library.
2. Browse the session catalog.
3. Use helper filters and catalog inspection to find candidate sessions.
4. Create a cohort from explicit sessions, aggregations, bookmarks, or geographical sections.
5. Save the cohort as a canonical library object where the current data source is writable.
6. Inspect note, QC, provenance, event, and metric information for the cohort.
7. Open at least one browser-native chart for the cohort.
8. Run at least one adequacy check against the cohort.

This first deliverable keeps the focus on the library and cohort model before
adding full import, preprocessing, or hosted-service complexity.

## Design Principles For The Product

- The BODAQS library is the primary user data object.
- Cohorts are the primary analysis scope.
- Saved cohorts should be explicit and stable, not live filters.
- Filters are helper tools for finding, validating, and refreshing candidate scope.
- Geographical sections are reusable library objects, not private cohort state.
- Browser UI owns visualisation and interaction.
- Python owns canonical processing and artifact generation.
- Local-first and offline use are first-class requirements.
- Zero-install web use remains an option, not the sole target.
- Deployment modes should share contracts rather than fork the product.
- The app should avoid depending on Jupyter runtime state.
- User-owned local libraries should remain usable outside the application where practical.
- Browser-local storage should not be the only saved copy of important library objects.

## Risks And Decisions To Resolve

The following decisions will materially affect implementation detail:

- the exact cohort schema and versioning policy
- the cohort ID format and filename rules
- the exact saved-filter schema, if filters become reusable library helpers
- the exact adequacy-check contract for views and visualisations
- the geographical section and section-cut schemas
- the section coverage index format
- whether the first browser-local writer targets Chromium-only file APIs or starts with export/download fallback
- whether v1 requires direct browser writing to library folders or only through local API and bundle export
- how chart summaries and downsampled traces should be stored
- what browser support target is required for v1
- how much of the current notebook widget feature set must be present in the first application release
- whether remote accounts, collaboration, billing, or long-term cloud storage are product requirements

## Things To Avoid

- Treating zero-install remote web use as the only target.
- Requiring internet access for field analysis.
- Exposing Jupyter or notebook sessions directly as the external product.
- Rewriting the Python analysis engine prematurely.
- Making the frontend depend on raw notebook-specific data structures.
- Treating cohort selection as temporary UI state only.
- Treating saved filters as hidden live cohort definitions.
- Hiding geographical sections inside cohort documents.
- Making browser storage the only saved copy of cohort definitions.
- Making the Import Manager the only way to view an already processed static library.
- Building separate incompatible apps for local, static, browser-local, and remote modes.

## Summary Recommendation

The recommended path is to build a browser-first BODAQS application around
processed libraries and canonical cohort objects.

The browser should provide the primary visualisation and interaction experience.
Python should remain the authoritative engine for import, preprocessing, event
detection, metrics, artifact writing, and heavy data preparation.

The application should support offline local use through the installed Import
Manager, browser-local and static-bundle use for processed libraries, and
optional remote service use where internet-backed workflows are valuable.
