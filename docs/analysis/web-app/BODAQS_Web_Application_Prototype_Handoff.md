# BODAQS Web Application Prototype Handoff

**Status:** Implementation handoff  
**Date:** 2026-05-23  
**Audience:** BODAQS application prototype implementers

## Purpose

This note captures the immediate implementation context for starting the BODAQS
Library Browser and Study Set Builder prototype on another machine.

It should be read alongside:

- [`BODAQS_Web_Application_Roadmap.md`](./BODAQS_Web_Application_Roadmap.md)
- [`BODAQS_session_notes_and_catalog_contract_draft.md`](../contracts/BODAQS_session_notes_and_catalog_contract_draft.md)
- [`BODAQS_aggregation_library_contract_draft.md`](../contracts/BODAQS_aggregation_library_contract_draft.md)
- [`BODAQS_analysis_artifacts_specification_v0_2.md`](../contracts/BODAQS_analysis_artifacts_specification_v0_2.md)
- [`BODAQS_session_selector_consumer_widgets_contract.md`](../contracts/BODAQS_session_selector_consumer_widgets_contract.md)

## Prototype Goal

Build a static React prototype for the BODAQS Library Browser and Study Set
Builder.

The prototype should help explore UI structure, Study Set building workflows,
and browser-native visualisation before wiring the application to real BODAQS
artifacts, Parquet files, browser file APIs, or the local Library API.

The first screen should be a usable workbench, not a landing page.

## Recommended Location

Place the prototype under the existing `application/` area:

```text
application/
  cohort-workbench-prototype/
```

This keeps it separate from the Python analysis package, firmware, and
documentation site while still keeping it in the BODAQS repository.

The directory name still uses the earlier "cohort" wording from the initial
scaffold. User-facing UI and contracts should use "Study Set".

## Recommended Stack

Start with:

- Vite
- React
- TypeScript
- npm
- plain CSS or CSS modules
- `lucide-react` for icons

Add visualisation libraries only as the prototype needs them:

- `uPlot` for dense time-series charts
- `d3` for custom scales and interactions
- Observable Plot for faster metric plot experiments
- MapLibre GL JS for route maps and geographical section editing
- Turf.js for geospatial helpers such as route snapping and intersections

Add test tooling later when useful:

- Vitest for pure helper and contract tests
- Playwright for UI screenshots and regression checks

## Initial Setup Commands

When ready to scaffold the prototype:

```powershell
cd C:\Users\benco\dev\BODAQS
npm create vite@latest application/cohort-workbench-prototype -- --template react-ts
cd application\cohort-workbench-prototype
npm install
npm run dev
```

Vite normally starts at:

```text
http://localhost:5173/
```

If that port is in use, Vite will choose another port.

## Environment Setup Performed On 2026-06-01

The prototype environment was set up on Windows using `winget`, Node.js LTS,
and npm.

Node was not initially available on this machine, so Node.js LTS was installed
with:

```powershell
winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements --silent
```

Installed runtime versions:

```text
node v24.16.0
npm 11.13.0
```

The installer placed Node under:

```text
C:\Program Files\nodejs
```

The current terminal session did not immediately pick up the new Node.js PATH
entry. For commands run in that same session, the Node path was prepended
manually:

```powershell
$env:Path = "C:\Program Files\nodejs;$env:Path"
```

A new terminal should normally pick up Node and npm without that manual PATH
line.

The Vite React TypeScript app was scaffolded with:

```powershell
cd C:\Users\benco\dev\BODAQS
$env:Path = "C:\Program Files\nodejs;$env:Path"
npm.cmd create vite@latest application/cohort-workbench-prototype -- --template react-ts
cd application\cohort-workbench-prototype
npm.cmd install
```

Prototype runtime dependencies were installed with:

```powershell
npm.cmd install lucide-react d3 uplot @observablehq/plot maplibre-gl @turf/turf
```

The D3 TypeScript declarations were installed with:

```powershell
npm.cmd install -D @types/d3
```

Top-level installed package versions after setup:

```text
@observablehq/plot 0.6.17
@turf/turf 7.3.5
@types/d3 7.4.3
d3 7.9.0
lucide-react 1.17.0
maplibre-gl 5.24.0
react 19.2.6
react-dom 19.2.6
typescript 6.0.3
uplot 1.6.32
vite 8.0.15
```

The generated project includes:

```text
application/cohort-workbench-prototype/package.json
application/cohort-workbench-prototype/package-lock.json
```

Use `npm install` inside the prototype directory on another machine to restore
the dependency tree from `package-lock.json`.

The production build was verified with:

```powershell
cd C:\Users\benco\dev\BODAQS\application\cohort-workbench-prototype
$env:Path = "C:\Program Files\nodejs;$env:Path"
npm.cmd run build
npm.cmd run lint
```

Result:

```text
tsc -b && vite build
completed successfully
eslint .
completed successfully
```

Vitest and Playwright were not installed during this setup. Add them later when
the prototype has enough logic or UI structure to justify tests and screenshots.

## Prototype Implementation Status On 2026-06-01

The first layout skeleton has been implemented and then split into a modest
domain/data-source/component structure.

Current source map:

```text
application/cohort-workbench-prototype/src/App.tsx
application/cohort-workbench-prototype/src/App.css
application/cohort-workbench-prototype/src/index.css
application/cohort-workbench-prototype/src/components/
application/cohort-workbench-prototype/src/data/
application/cohort-workbench-prototype/src/domain/
application/cohort-workbench-prototype/README.md
```

`App.tsx` now acts mostly as the orchestration layer for workbench state and
user actions. Domain types and pure helpers live under `src/domain/`, fixture
catalog data and the mock persistence layer live under `src/data/`, and
presentational pieces such as the session table, Study Set table, route preview,
badges, modal, and common controls live under `src/components/`.

Implemented fixture-backed behavior:

- two-panel Library Browser and Study Set Builder layout
- horizontal collapse controls for both panels
- multi-library selection from fixture data
- session catalog with visible-column controls, search, sorting, and multi-select
- first selected session retained as the primary GPS preview session
- quick read-only note, QC, and metadata inspection modals
- Add to Study Set and Analyze now actions
- Study Set session table with removal controls
- overlapping Study Set-local groupings with short names
- fixture track list and whole-track attachment to the Study Set
- saved Study Set list with analyze, view, and load actions
- fixture-backed `LibraryDataSource` interface
- in-memory mock saving/loading of Study Sets through `FixtureLibraryDataSource`

Deliberate placeholders:

- reusable Filter Manager
- track creation/editing
- real Library API access
- real Study Set persistence to disk
- analysis navigation and chart views

## Current Prototype Structure

The current prototype uses this smaller version of the proposed structure:

```text
application/
  cohort-workbench-prototype/
    src/
      App.tsx
      main.tsx
      domain/
        routes.ts
        sessionCatalog.ts
        studySets.ts
        types.ts
      data/
        LibraryDataSource.ts
        FixtureLibraryDataSource.ts
        fixtures.ts
      components/
        Common.tsx
        Modal.tsx
        RoutePreview.tsx
        SessionTable.tsx
        StatusBadges.tsx
        StudySessionTable.tsx
```

The exact file layout can still change as the prototype evolves, but the key
idea is already in place: keep domain types, data-source boundaries, components,
and charts separate.

## Data Source Boundary

Build around a frontend `LibraryDataSource` interface from the beginning.

The first implementation can be fixture-backed:

```text
FixtureLibraryDataSource
```

The current prototype already uses this seam. `App.tsx` loads libraries,
sessions, tracks, and saved Study Sets through `FixtureLibraryDataSource` rather
than importing fixture arrays directly. Saving a Study Set is still in-memory,
but it goes through the data-source interface so later disk/API persistence can
replace the implementation without rewriting the UI.

Later implementations may include:

```text
BrowserDirectoryDataSource
StaticBundleDataSource
LocalApiDataSource
RemoteApiDataSource
```

This keeps the UI stable while the backing data access model evolves.

Useful conceptual operations:

```text
listSessions()
listStudySets()
loadStudySet(studySetId)
saveStudySet(studySet)
listFilters()
applyFilter(filterCriteria)
listTracks()
saveTrack(track)
getSessionMeta(sessionKey)
getSignalCatalog(studySet)
getEvents(studySet, query)
getMetrics(studySet, query)
getTimeseriesWindow(studySet, signals, start, end, resolution)
checkStudySetAdequacy(studySet, requirements)
```

## Key Product Assumptions

The prototype should preserve these decisions:

- The BODAQS library is the starting point for user interaction.
- A saved Study Set is an explicit, stable analysis scope.
- Filters are helper tools and optional provenance, not hidden live Study Set definitions.
- Study Sets should be saved as individual JSON files associated with the library root.
- Study Sets may contain sessions from multiple libraries, and session references should carry `library_id`.
- Groupings are Study Set-local, may overlap, and should support short user names.
- Tracks are reusable library objects, not private Study Set state.
- Analyze now creates an unsaved one-session Study Set.
- The practical v1 session identity is `<run_id>::<session_id>`.
- Browser UI owns interaction and visualisation.
- Python remains authoritative for import, preprocessing, event detection, metrics, artifact writing, and heavy data preparation.

## First UI Target

The first useful prototype should support:

1. Show a session catalog with run/session names and IDs.
2. Show note status, QC status, provenance, preprocessing, and aggregation indicators.
3. Filter and sort visible catalog columns.
4. Select sessions into a Study Set.
5. Show a Study Set summary and member list.
6. Save/load Study Set JSON against fixture or mock storage.
7. Inspect session note, QC, provenance, and preprocessing details in a side panel or modal.
8. Render one browser-native chart preview from fake time-series data.
9. Run one adequacy check against the Study Set.

This target is intentionally small enough to build quickly, but rich enough to
test the product shape.

## Later Prototype Areas

Once the basic workbench feels coherent, explore:

- aggregation graph indicators in the session catalog
- editable draft note fields while building a Study Set
- persisted helper filters
- track creation/editing and route coverage previews
- map-based section selection
- linked table/chart/map interactions
- richer chart readiness and adequacy checks

## Source References

Useful existing code and contracts:

- `analysis/bodaqs_analysis/artifacts.py`
- `analysis/bodaqs_analysis/library/aggregations.py`
- `analysis/bodaqs_analysis/session_notes.py`
- `analysis/bodaqs_analysis/widgets/session_window_data.py`
- `analysis/bodaqs_analysis/widgets/metric_widget_data.py`
- `analysis/bodaqs_analysis/widgets/loaders.py`

These are references for concepts and contracts. The prototype should not depend
on importing Python modules directly.
