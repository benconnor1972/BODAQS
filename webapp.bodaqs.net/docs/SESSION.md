# BODAQS Webapp Session State
*Last updated: 2026-05-01 (Vercel/local-dev setup session)*

## What we're building
`webapp.bodaqs.net/` — a hosted SvelteKit 5 + FastAPI web app that replaces the Jupyter notebook workflow. Users upload logger files → backend runs preprocessing → frontend shows the 10-tile suspension dashboard → export/import as `.bodaqs.zip`.

Spec lives at: `/Volumes/www/BODAQS/webapp.bodaqs.net/SPEC.md` — keep it updated as decisions are made.

---

## Phase status

| Phase | Status | Notes |
|---|---|---|
| 1 — Backend | ✅ Complete, 19/19 tests passing | See below for details |
| 2 — Frontend scaffold | ✅ Complete, npm run build passes | See below for details |
| 3 — Core data layer | ✅ Complete, 23/23 tests passing | See below for details |
| 4 — Upload flow | ✅ Complete, 43/43 tests passing | See below for details |
| 5 — Dashboard | ✅ Complete, 65/65 tests passing | See below for details |
| 6 — Transfer + deploy | ✅ Complete (partial — transfer page only), 65/65 tests passing | ZIP export/import UI done, Vercel deploy out of scope |
| Dev infrastructure | ✅ Complete | vercel.json fixed, local dev setup documented — see below |

---

## Phase 1 — What was built

### File structure created
```
webapp.bodaqs.net/
└── api/
    ├── pytest.ini
    ├── requirements.txt          — fastapi, uvicorn, mangum, pydantic, python-multipart + numpy/pandas/scipy/PyYAML/fitparse
    ├── requirements-dev.txt      — adds pytest, httpx
    ├── bodaqs_api/
    │   ├── __init__.py
    │   ├── main.py               — FastAPI app, CORS, GET /api/health
    │   ├── index.py              — Vercel/Mangum ASGI entry point (exports `handler`)
    │   ├── default_preprocess_profile.json  — bundled fallback profile
    │   ├── schemas/
    │   │   └── preprocess.py     — PreprocessResponse, SignalsPayload (Pydantic v2)
    │   ├── routes/
    │   │   └── preprocess.py     — POST /api/preprocess route
    │   └── services/
    │       └── preprocess_service.py  — run_preprocess(), encoding, FIT override
    └── tests/
        ├── conftest.py
        ├── fixtures/
        │   ├── ride.csv                    — 5000 rows from application/Examples/Logs/2026-02-20_08-34-26.CSV
        │   ├── ride_sidecar.json           — from application/Examples/Config/generic_log_metadata/
        │   ├── test_bike_profile.json      — Bens STEVO_bike_profile_v1.json
        │   ├── event_schema.yaml           — event_schema - Basic.yaml (inputs format)
        │   └── test_preprocess_profile.json — suspension_default_v1.json
        ├── test_health.py
        ├── test_preprocess_service.py      — 11 tests
        └── test_preprocess_endpoint.py     — 7 tests
```

### Key decisions made

**Upload form — five files, four required:**
| Field | Required |
|---|---|
| `csv_file` | ✅ |
| `bike_profile_json` | ✅ |
| `sidecar_json` | ✅ |
| `event_schema_yaml` | ✅ |
| `preprocess_profile_json` | optional — falls back to `default_preprocess_profile.json` |

**Service layer constraints:**
- `fit_import.enabled` is always forced to `false` by `_disable_fit_import()` regardless of what any profile says — web API has no FIT directory
- `schema_path` inside any preprocess profile is ignored — event schema always comes from the uploaded file
- Signals are encoded as base64 little-endian float32 per column
- Excluded from signals payload: `time_s`, `sample_id`, `active_mask_qc`
- NaN in events/metrics → null via `df.to_json(orient="records")`

**Default preprocess profile:**
- `motion_derivation.enabled = true` (matches example profile — needed for vel/acc channels that drive event detection)
- Sources: both `rear_wheel` and `front_wheel` (domain: "wheel")
- `fit_import.enabled = false`

**Event schema format:**
- Must use the `inputs:` selector format (spec 0.1.2+, version '7')
- The older `sensors:` list format in `event_schema.yaml` is NOT supported by current detect.py
- Example file is: `application/Examples/Config/Event schema/event_schema - Basic.yaml`

**`bodaqs_analysis` package:**
- Installed as editable: `pip install -e /Volumes/www/BODAQS/analysis`
- No pyproject.toml visible — installed via setuptools implicit namespace
- Not on PyPI; Vercel deployment story TBD in Phase 6

**Running tests:**
```bash
cd webapp.bodaqs.net/api
python -m pytest tests/ -v
```

### Known warnings in test output (expected, not bugs)
- `Pandas4Warning` copy keyword deprecated — comes from `io_logger.py` and `signal_legacy.py` in analysis package
- `bike_profile_signal_transform_input_unmatched:rear_shock_to_rear_wheel_travel` — example sidecar declares rear_shock as `domain: "wheel"` but bike profile LUT expects `domain: "suspension"` input; graceful skip
- `bike_profile_normalization_range_unmatched:rear_shock_travel_range` — same cause
- `filename_stem_time_anchor_used_local_machine_timezone` — expected for time-of-day timestamp CSVs without explicit timezone

---

## Phase 2 — What was built

### File structure created
```
webapp.bodaqs.net/
├── vercel.json                     — routes /api/* → Python, /* → SvelteKit
└── frontend/
    ├── svelte.config.js            — adapter-vercel + runes mode forced globally
    ├── vite.config.ts              — Vite 8 + vitest/config
    ├── tsconfig.json               — strict TypeScript, extends .svelte-kit/tsconfig.json
    ├── package.json                — SvelteKit ^2.57, adapter-vercel ^6, Svelte ^5.55, TS ^6, Vite ^8, Vitest ^4
    ├── eslint.config.js            — ESLint 10 flat config
    ├── .prettierrc                 — tabs, prettier-plugin-svelte
    ├── src/
    │   ├── app.html
    │   ├── app.d.ts
    │   ├── lib/
    │   │   ├── api/
    │   │   │   └── preprocess.ts  — SignalsPayload, PreprocessResponse, PreprocessFormData; postPreprocess(); decodeSignalColumn()
    │   │   ├── db/
    │   │   │   ├── dexie.ts       — BodaqsDB (Dexie 4), schema v1: runs/sessions/signals/events/metrics
    │   │   │   └── artifacts.ts   — saveRun, saveSession (keeps session_ids in sync), getAllRuns, query helpers
    │   │   ├── stores/
    │   │   │   └── library.svelte.ts  — libraryStore ($state, try/finally on load)
    │   │   └── zip/
    │   │       ├── export.ts      — exportRuns() → Blob (JSZip)
    │   │       └── import.ts      — importZip() → {imported, skipped}; skips by run_id
    │   └── routes/
    │       ├── +layout.svelte     — nav: Library / Upload / Transfer
    │       ├── +page.svelte       — run library list (loads from Dexie via libraryStore)
    │       ├── upload/
    │       │   └── +page.svelte   — placeholder (Phase 4)
    │       ├── dashboard/
    │       │   └── [run_id]/
    │       │       ├── +page.ts   — export const prerender = false
    │       │       └── +page.svelte — placeholder (Phase 5)
    │       └── transfer/
    │           └── +page.svelte   — placeholder (Phase 6)
```

### Key decisions made

**Build setup:**
- Used `npx sv create` with `--add sveltekit-adapter=adapter:vercel` to let CLI pick latest compatible versions
- Received: `adapter-vercel ^6`, `SvelteKit ^2.57`, `Svelte ^5.55`, `TypeScript ^6`, `Vite ^8`, `Vitest ^4`, `ESLint 10` flat config
- Runes mode (`$state`, `$derived`) forced globally in `svelte.config.js` via `compilerOptions.runes: true` function

**Dexie schema (version 1):**
- Tables: `runs`, `sessions`, `signals`, `events`, `metrics`
- `saveSession()` utility keeps `Run.session_ids` in sync in Dexie when saving
- Handles both session-based and run-based data flows

**Library store:**
- `libraryStore.load()` uses try/finally to always reset loading state
- Reactive `$derived` computed properties for filtered/sorted runs
- Integrates Dexie database reads on mount

**Routing:**
- `vercel.json` at `webapp.bodaqs.net/` routes `/api/*` → Python Lambda functions, `/*` → SvelteKit app
- Enables seamless FastAPI + SvelteKit coexistence

**SvelteKit 2 API changes:**
- Import `{ page }` from `'$app/state'` (not `'$app/stores'`)
- Pages with dynamic routes require `export const prerender = false` in `+page.ts`
- TypeScript 6 + Svelte 5 strict compatibility enforced

**Verification:**
- `npm run build` — builds to `.svelte-kit/output/` with Vite + Vercel adapter (no Vercel CLI needed locally)
- `npm run check` — `svelte-check found 0 errors and 0 warnings`

---

## Phase 6 — What was built (partial — transfer page only)

### Files modified
```
frontend/src/routes/transfer/
└── +page.svelte  — ZIP export (run selector, download trigger) + ZIP import (file picker, imported/skipped report)
```

### Key decisions made

**Export:** User selects runs via checkboxes, "Export selected" calls existing `exportRuns()` → browser download as `bodaqs-export-{YYYY-MM-DD}.bodaqs.zip`. Select All / None shortcuts included.

**Import:** File picker + "Import" calls existing `importZip()` → reports "Imported N, skipped M". On success, run list reloads from Dexie so newly imported runs appear in the export list immediately.

**No new lib code:** `lib/zip/export.ts` and `lib/zip/import.ts` were already complete and tested in Phase 3. The transfer page is pure UI wiring.

**Deployment not included:** Vercel deploy setup is out of scope for this session.

---

## Phase 5 — What was built

### Files created/modified
```
frontend/src/lib/charts/
├── prepare.ts                  — findDisplacementColumn, findVelocityColumn, computePercentileRange, computeHistogram, prepareEventsBar, prepareMetricScatter
├── prepare.test.ts             — 22 tests: signal lookup, histogram, events bar, scatter
├── DisplacementHistogram.svelte — Plotly bar histogram, 50 bins, 5–95th percentile trim, normalised/mm toggle
├── VelocityHistogram.svelte    — Plotly bar histogram, 100 bins, ±2000 mm/s range
├── EventsBar.svelte            — Plotly bar, event counts by name for front/rear
├── MetricScatter.svelte        — Plotly scatter, compression/rebound metrics
└── EmptyTile.svelte            — Muted placeholder shown when data is absent

frontend/src/routes/dashboard/[run_id]/
└── +page.svelte                — Full 10-tile dashboard: loads Dexie, session selector, unit toggle, 2-column CSS grid
```

### Key decisions made

**Signal column matching:** `findDisplacementColumn` and `findVelocityColumn` use substring matching (`startsWith(end + '_')` + quantity/unit keywords). Robust to column name variations while the naming convention is preserved.

**Histogram trimming:** Displacement tiles trim to [5th, 95th] percentile via `computePercentileRange`; velocity tiles clamp to ±2000 mm/s. Handled in chart components so prepare.ts stays testable without browser context.

**Event/metric filtering:** Filtered by `signal_col.includes('front'/'rear')` for side, `event_name.includes('compression'/'rebound')` for event type. Matches actual pipeline event names (`'wheel compression events with max normalized displacement >0.25'`).

**Missing tile:** Each chart component renders `EmptyTile` when data is null or empty — never an error state.

---

## Phase 4 — What was built

### Files created/modified
```
frontend/src/lib/upload/
├── validate.ts        — UploadFiles type, MAX_CSV_BYTES (50 MB), validateUploadFiles(), isUploadReady()
└── validate.test.ts   — 20 tests: extension checks, size limits, required field checks

frontend/src/routes/upload/
└── +page.svelte       — 5 file inputs, $state form, $derived ready flag, postPreprocess call, saveRun+saveSession, goto dashboard
```

### Key decisions made

**Run ID strategy:** `crypto.randomUUID()` generated in browser before API call — avoids any server-side ID management. Run description derived from CSV filename stem.

**Validation approach:** Pure `validate.ts` module (no browser/Dexie needed) makes unit testing straightforward. Extension checks guard against wrong file types; `isUploadReady` drives the disabled state so the button can never be clicked with missing required files.

**Warnings:** Stored on `Session.warnings` in Dexie via `saveSession`. Not shown on upload page — Phase 5 dashboard will surface them.

**No library store interaction:** Upload page calls `saveRun` + `saveSession` directly. The library page reloads from Dexie on mount, so navigating back to `/` will always show the new run.

---

## Phase 3 — What to do next

The frontend scaffold is complete with all routes and lib stubs in place. Core data layer integration next.

Steps:
1. Implement full Dexie schema with all required fields and indexes
2. Build library store reactive queries and filters
3. Implement upload form with file pickers
4. Connect upload flow to `/api/preprocess` endpoint
5. Implement 10-tile dashboard with Plotly
6. Build ZIP export/import flow and deploy to Vercel

---

---

## Dev infrastructure — What was set up

### Problem
`vercel dev` did not work out of the box due to multiple issues discovered and resolved iteratively.

### Files changed
```
webapp.bodaqs.net/
├── vercel.json               — fixed (see below)
├── setup.sh                  — NEW: one-shot setup script for new checkouts
├── .gitignore                — added api/bodaqs_analysis (generated symlink)
├── api/
│   ├── .python-version       — NEW: pins Python 3.12 for Vercel runtime
│   └── bodaqs_analysis -> ../../analysis/bodaqs_analysis   — symlink (gitignored, created by setup.sh)
└── frontend/
    └── vite.config.ts        — added server.proxy: /api → http://localhost:8000
```

### vercel.json — final state
```json
{
  "buildCommand": "cd frontend && npm run build",
  "installCommand": "cd frontend && npm install && cd .. && ln -sfn ../../analysis/bodaqs_analysis api/bodaqs_analysis",
  "outputDirectory": "frontend/.vercel/output",
  "functions": {
    "api/index.py": { "maxDuration": 30 }
  },
  "rewrites": [
    { "source": "/api/:path*", "destination": "/api/index.py" }
  ]
}
```

### Issues resolved
| Issue | Fix |
|---|---|
| `runtime: "python3.12"` not a valid runtime identifier | Removed `runtime` field; added `api/.python-version` instead |
| `functions: {}` — "must have at least one property" | Used `{ "maxDuration": 30 }` |
| `vercel dev` returned 404 for all `/api/*` | Root cause: CLI v53 does not emulate Python functions locally at all (`Resolved builders: ""`) |
| Frontend hang "waiting for localhost" | `devCommand` passed `$PORT` to Vite but Vite ignored it; removed `devCommand` |
| `bodaqs_analysis` not importable | Symlinked via `setup.sh`: `api/bodaqs_analysis → ../../analysis/bodaqs_analysis` |

### Local development workflow
`vercel dev` cannot run Python functions locally (CLI v53 limitation). Use two processes instead:

```sh
# First time only (or after fresh clone):
cd webapp.bodaqs.net && ./setup.sh

# terminal 1 — API on :8000
cd webapp.bodaqs.net/api && uvicorn bodaqs_api.main:app --reload

# terminal 2 — Frontend on :5173 (proxies /api → :8000 via vite.config.ts)
cd webapp.bodaqs.net/frontend && npm run dev
```

Browse at `http://localhost:5173`. No CORS issues — Vite proxy is transparent.

### Vercel project
- Linked project: `webapp-bodaqs-net` (george-karbons-projects team)
- Project root: assumed to be full BODAQS repo root (not `webapp.bodaqs.net/`) — **not yet confirmed in Vercel dashboard**
- When confirmed: paths in `vercel.json` may need `webapp.bodaqs.net/` prefix (e.g. `functions: { "webapp.bodaqs.net/api/index.py": ... }`)
- `installCommand` creates the symlink during Vercel build — works when repo root = Vercel root

---

## Key paths
- Spec: `/Volumes/www/BODAQS/webapp.bodaqs.net/SPEC.md`
- API: `/Volumes/www/BODAQS/webapp.bodaqs.net/api/`
- Frontend (skeleton): `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/`
- Example files: `/Volumes/www/BODAQS/application/Examples/`
  - Logs: `Logs/2026-02-20_08-34-26.CSV`, `_08-36-01.CSV`, `_08-39-06.CSV`
  - Bike profile: `Config/bike_profiles/Bens STEVO_bike_profile_v1.json`
  - Sidecar: `Config/generic_log_metadata/log_metadata_human_readable_timestamps.json`
  - Event schema: `Config/Event schema/event_schema - Basic.yaml`
  - Preprocess profile: `Config/preprocess_profiles/suspension_default_v1.json`
- Analysis package: `/Volumes/www/BODAQS/analysis/bodaqs_analysis/`
- Pipeline entry point: `pipeline.py::preprocess_session()`
