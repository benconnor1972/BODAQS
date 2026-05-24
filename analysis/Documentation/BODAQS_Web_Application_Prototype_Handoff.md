# BODAQS Web Application Prototype Handoff

**Status:** Implementation handoff  
**Date:** 2026-05-23  
**Audience:** BODAQS application prototype implementers

## Purpose

This note captures the immediate implementation context for starting the BODAQS
library and cohort workbench prototype on another machine.

It should be read alongside:

- [`BODAQS_Web_Application_Roadmap.md`](./BODAQS_Web_Application_Roadmap.md)
- [`BODAQS_session_notes_and_catalog_contract_draft.md`](./BODAQS_session_notes_and_catalog_contract_draft.md)
- [`BODAQS_aggregation_library_contract_draft.md`](./BODAQS_aggregation_library_contract_draft.md)
- [`BODAQS_analysis_artifacts_specification_v0_2.md`](./BODAQS_analysis_artifacts_specification_v0_2.md)
- [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)

## Prototype Goal

Build a static React prototype for the BODAQS library and cohort workbench.

The prototype should help explore UI structure, cohort-building workflows, and
browser-native visualisation before wiring the application to real BODAQS
artifacts, Parquet files, browser file APIs, or the Import Manager.

The first screen should be a usable workbench, not a landing page.

## Recommended Location

Place the prototype under the existing `application/` area:

```text
application/
  cohort-workbench-prototype/
```

This keeps it separate from the Python analysis package, firmware, and
documentation site while still keeping it in the BODAQS repository.

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

## Suggested Prototype Structure

Use static fixture data at first, shaped like the future application contracts:

```text
application/
  cohort-workbench-prototype/
    src/
      App.tsx
      main.tsx
      styles/
      domain/
        cohort.ts
        session.ts
        library.ts
        geography.ts
      data/
        LibraryDataSource.ts
        FixtureLibraryDataSource.ts
        fixtures/
          libraryCatalog.ts
          sessions.ts
          cohorts.ts
          aggregations.ts
          bookmarks.ts
          events.ts
          metrics.ts
          timeseries.ts
      components/
        LibrarySidebar.tsx
        SessionCatalog.tsx
        CohortBuilder.tsx
        CohortSummary.tsx
        InspectorPanel.tsx
        ChartPanel.tsx
      charts/
        TimeSeriesChart.tsx
        MetricScatter.tsx
        MetricHistogram.tsx
```

The exact file layout can change as the prototype evolves, but the key idea is
to keep domain types, data-source boundaries, components, and charts separate.

## Data Source Boundary

Build around a frontend `LibraryDataSource` interface from the beginning.

The first implementation can be fixture-backed:

```text
FixtureLibraryDataSource
```

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

## Key Product Assumptions

The prototype should preserve these decisions:

- The BODAQS library is the starting point for user interaction.
- A saved cohort is an explicit, stable analysis scope.
- Filters are helper tools and optional provenance, not hidden live cohort definitions.
- Cohorts should be saved as individual JSON files in the library model.
- Geographical sections are reusable library objects, not private cohort state.
- The practical v1 session identity is `<run_id>::<session_id>`.
- Browser UI owns interaction and visualisation.
- Python remains authoritative for import, preprocessing, event detection, metrics, artifact writing, and heavy data preparation.

## First UI Target

The first useful prototype should support:

1. Show a session catalog with run/session names and IDs.
2. Show note status, QC status, provenance, preprocessing, and aggregation indicators.
3. Filter and sort visible catalog columns.
4. Select sessions into a cohort.
5. Show a cohort summary and member list.
6. Save/load cohort JSON against fixture or mock storage.
7. Inspect session note, QC, provenance, and preprocessing details in a side panel or modal.
8. Render one browser-native chart preview from fake time-series data.
9. Run one adequacy check against the cohort.

This target is intentionally small enough to build quickly, but rich enough to
test the product shape.

## Later Prototype Areas

Once the basic workbench feels coherent, explore:

- aggregation graph indicators in the session catalog
- editable draft note fields while building a cohort
- persisted helper filters
- geographical section cuts and route coverage previews
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
