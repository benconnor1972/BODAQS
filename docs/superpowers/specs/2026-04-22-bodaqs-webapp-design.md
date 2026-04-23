# BODAQS Web App — Design Spec
_Date: 2026-04-22_

## Overview

Convert the BODAQS Jupyter notebook suite into a web application. The system analyses mountain bike suspension telemetry: raw CSV logs are preprocessed into structured artifacts (events, metrics, signal time-series), then explored through dashboards and session browsers.

**Stack:** SvelteKit frontend · FastAPI backend (stateless, remotely hosted) · IndexedDB + localStorage (local-first browser storage) · ZIP export/import

---

## Architecture

### Layers

**FastAPI (remote, stateless)**
- Pure compute engine. No database, no disk writes, no session state.
- Wraps `bodaqs_analysis` Python library unchanged.
- Accepts CSV uploads, returns processed artifacts as structured responses.
- CORS configured for the SvelteKit frontend origin.

**SvelteKit (browser)**
- Multi-page app with five primary routes (see Pages section).
- Svelte stores drive all reactive state; stores persist to localStorage or read from IndexedDB.
- Charts rendered via Plotly.js (time-series) and ECharts (metrics/histograms).

**Browser storage**
- `localStorage` — lightweight: library index (run/session list, SHA set), preprocess profiles, active selection.
- `IndexedDB` via Dexie.js — heavy data: signal Float32Arrays, events rows, metrics rows, session manifests.

### Shared Svelte Stores

| Store | Backed by | Purpose |
|---|---|---|
| `libraryStore` | localStorage | Run/session index, updated after each preprocess job |
| `selectionStore` | localStorage | Active entity set (sessions + aggregations); drives dashboard + session browser reactively |
| `profileStore` | localStorage | Named preprocess profiles |
| `schemaStore` | localStorage | Current event schema YAML |

### IndexedDB Schema (Dexie)

```
runs       { run_id, created_at, description, session_ids[], pipeline_config }
sessions   { session_key, run_id, session_id, manifest, signals_meta }
signals    { session_key, columns[], data: Float32Array[] }   // lazy-loaded
events        { session_key, schema_id, rows: object[] }
metrics       { session_key, schema_id, rows: object[] }
aggregations  { agg_key, title, session_keys[], created_at, description }
```

Aggregations are user-defined named groupings of sessions (e.g. "Maydena Day 1 + Day 2"). They are stored entirely in IndexedDB alongside sessions — no server involvement. The `/api/aggregate` endpoint accepts a list of session metric rows and returns combined statistics; the aggregation definition itself lives in the browser.

Signal columns stored as `Float32Array` typed arrays — ~4× more compact than JSON numbers and consumable directly by Plotly.js/ECharts without deserialisation overhead.

---

## Pages

### `/` — Library
Replaces `BODAQS_library_manager.ipynb`. Run/session browser with filter and sort. Inline description editing. Aggregation management. Selecting entities writes to `selectionStore`; navigating to `/dashboard` shows those entities.

### `/preprocess` — Preprocess
Replaces `bodaqs_batch_preprocessing_pipeline.ipynb` and `BODAQS_auto_preprocess_simple_suspension_metrics.ipynb` (both notebooks do the same job). File picker with SHA-256 dedup against library index to skip already-processed files. Named profile selector. Per-file progress indicator (queued / uploading / processing / done / failed). Run description prompt inline on completion.

### `/dashboard` — Metrics Dashboard
Replaces `BODAQS_simple_suspension_metrics.ipynb` and `BODAQS_simple_suspension_metrics_persisted_scope.ipynb` (the persisted-scope variant is redundant — `selectionStore` in localStorage gives all pages persisted scope for free). Reads active selection from `selectionStore`. Renders histograms and scatter charts from events/metrics tables in IndexedDB. Engineering units toggle (mm / normalised).

### `/session/[id]` — Session Browser
Replaces `bodaqs_session_test_notebook.ipynb`. Lazy-loads signal `Float32Array` data from IndexedDB on open. Zoomable time-series via Plotly.js. Event markers overlaid on the signal trace. Window bookmarks. Clicking an event jumps to its time window.

### `/schema` — Schema Editor
Replaces `bodaqs_event_schema_test_harness.ipynb`. CodeMirror YAML editor. Upload a single test CSV → `POST /api/validate-schema` → live event preview table rendered inline. Schema saved to localStorage. Iterates without touching the main artifact library.

---

## Data Flow

### Preprocessing (CSV → IndexedDB)

1. User selects CSV files on `/preprocess`. SHA-256 dedup runs client-side; already-processed files are skipped.
2. For each new file: browser gzip-compresses the CSV via `CompressionStream` (the API is remotely hosted — compression reduces upload size ~5–10×), then sends `POST /api/preprocess` with the compressed CSV + profile JSON.
3. FastAPI decompresses, calls `run_macro()`, returns a structured response:
   ```json
   {
     "session_id": "2026-02-20_08-34-26",
     "meta": { "signals": {}, "sample_rate_hz": 200 },
     "signals": { "column_names": [], "data": "<binary float32 blob>" },
     "events": [ { "schema_id": "...", "event_type": "...", "t_start": 0.0 } ],
     "metrics": [ { "schema_id": "...", "metric_name": "...", "value": 0.0 } ],
     "source_sha256": "abc123..."
   }
   ```
   Signal columns are returned as base64-encoded `Float32` binary blobs (one base64 string per column name key) rather than JSON number arrays. This avoids JSON number parsing overhead and is ~25% smaller than JSON text for float data, while remaining a valid JSON response. HTTP gzip transfer encoding is enabled on the FastAPI side for the full response.
4. Browser writes to IndexedDB in a single Dexie transaction; `libraryStore` updated in localStorage. `selectionStore` reacts automatically.

### Viewing (IndexedDB → Charts)

- `/dashboard` reads events/metrics rows directly from IndexedDB for the selected entities; no server call needed.
- `/session/[id]` lazy-loads signal `Float32Array` data from IndexedDB only when the page is opened.

---

## FastAPI Endpoints

| Method | Path | Input | Output |
|---|---|---|---|
| `POST` | `/api/preprocess` | Multipart: gzip CSV + profile JSON | Session artifacts (binary signals + JSON events/metrics) |
| `POST` | `/api/validate-schema` | YAML schema + single CSV | Lint errors + event preview rows |
| `POST` | `/api/aggregate` | Session keys + aggregation config | Aggregated metrics rows |

All endpoints are stateless. No authentication in v1 (rate limiting at the infrastructure level if needed).

---

## Export / Import

### Export
From the Library page, user selects runs via checkbox (oldest-first sort with size estimates when quota pressure is detected). Exports selected runs as a single ZIP:

```
bodaqs-export-<label>.zip
  └── runs/
        └── run_2026-04-19T12-00-16_AWST/
              ├── run_manifest.json
              └── sessions/
                    └── 2026-02-20_08-34-26/
                          ├── session_manifest.json
                          ├── events/
                          ├── metrics/
                          └── signals/
```

ZIP structure mirrors the existing artifact folder layout for backward compatibility with the notebook tooling.

### Import (selective)
1. User drops/selects a ZIP file.
2. App reads only `run_manifest.json` files from the ZIP using JSZip (no full extraction) to build a preview manifest.
3. User sees a checklist of runs in the ZIP: description, date, session count, estimated size.
4. User selects which runs to actually load into IndexedDB.
5. Selected runs are extracted and written to IndexedDB additively. Existing `run_id` entries are skipped (dedup).

Selective import prevents the common failure mode of re-importing a full-library export immediately refilling quota.

---

## Error Handling

### Upload / Preprocessing Failures
- Remote API: exponential backoff retry (max 3 attempts) for transient network errors.
- Server-side `run_macro` errors: structured error response `{ "error": "...", "detail": "...", "session_id": "..." }` shown inline per file on the `/preprocess` page.
- Failed files can be individually retried without re-submitting the whole batch.

### IndexedDB Quota Exceeded
- On `QuotaExceededError`, display a warning banner: "Storage is nearly full — export old runs to free space."
- Prompt user to the selective export flow (see above) rather than silently failing writes.

### Schema Validation Errors
- `POST /api/validate-schema` returns structured lint errors (event name, line number, message).
- `/schema` page renders errors inline beside the YAML editor.

---

## Testing

### FastAPI Backend
- `pytest` integration tests calling real `bodaqs_analysis` functions against CSV fixtures from `analysis/logs_test/`.
- No mocking of the processing library — integration tests only.
- API contract tests verify response shape matches frontend expectations.

### SvelteKit Frontend
- Vitest for store logic (`libraryStore`, `selectionStore`) using `fake-indexeddb` for Dexie.
- Playwright end-to-end: upload CSV → preprocess → session appears in library → dashboard renders charts.

### Visualisation
- Chart rendering correctness validated visually, not via automated tests.

---

## Feasibility Notes

- **Signal data size:** 18 sessions at ~50k rows × 6 columns as `Float32Array` ≈ 22MB in IndexedDB — well within typical browser quota (50–500MB). Events + metrics are negligible (<1MB total).
- **Preprocessing performance:** Large CSV round-trips to a remote server may take several seconds. Per-file progress indicators are important UX. Gzip upload compression reduces this.
- **`bodaqs_analysis` library:** Used unchanged as the FastAPI backend's processing library. The existing contract documents (`BODAQS_Public_API_Contract_v0.md`, `BODAQS_Session_Schema_v0_1.md`, etc.) map almost directly to FastAPI Pydantic response schemas.
- **Notebook backward compatibility:** The ZIP export format mirrors the existing artifact folder structure. Users can export from the web app and still open the artifacts in the existing notebooks.
