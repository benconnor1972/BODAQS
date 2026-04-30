# Spec: BODAQS Web App v1

## Objective

A hosted web application that replaces the Jupyter notebook workflow for end users who want to analyse their BODAQS logger data without a Python environment.

**User flow:** Upload one or more logger CSV files (with sidecar metadata JSON and bike profile) → backend runs the preprocessing pipeline → frontend displays the Simple Suspension Metrics dashboard as interactive charts → user exports a portable `.bodaqs.zip` file to save and restore the session.

**Success criteria:**
- [ ] Upload a logger CSV (+ optional same-stem sidecar JSON, optional bike profile JSON) and see all 10 suspension dashboard tiles populated
- [ ] Selecting a bike profile normalises displacement axes correctly (front/rear travel % vs mm toggle)
- [ ] Multiple runs can be loaded into the library; dashboard shows one session at a time (overlay is out of scope for v1)
- [ ] Export ZIP restores the full session (signals, events, metrics) on re-import — no re-upload or re-processing required
- [ ] Frontend deploys successfully to Cloudflare Pages / Vercel / Netlify
- [ ] Backend passes all tests after migration from `run_macro` → `preprocess_session`
- [ ] Missing signals produce partial charts + a warning list, not a hard failure

---

## Relationship to PoC (`git branch: feat/preprocess-mvp`)

The PoC established several decisions that are **kept**:
- SvelteKit 5 (Svelte runes mode), TypeScript strict
- Dexie.js (IndexedDB) schema: `runs / sessions / signals / events / metrics` tables
- Signal encoding: base64 float32 arrays (compact, fast to decode in the browser)
- JSZip export: ZIP with `runs/{run_id}/sessions/{session_id}/…` directory structure
- FastAPI + Python backend, same monorepo layout (`frontend/` + `api/`)

**What changes:**
- `run_macro` (deleted from analysis package) → `preprocess_session`
- Backend accepts bike profile + preprocess profile, not a raw schema YAML pasted in the UI
- API returns raw processed data only; all chart computation moves to the frontend
- Run library manifest moves from localStorage to Dexie (`runs` table); single source of truth, no drift risk
- SvelteKit adapter switches from `adapter-auto` to a target-specific adapter
- A new `/dashboard/[run_id]` route with Plotly.js visualisations (the PoC had no viz page)

---

## Tech Stack

| Layer              | Choice                                       | Notes                                                      |
|--------------------|----------------------------------------------|------------------------------------------------------------|
| Layer | Choice | Notes |
|---|---|---|
| Frontend framework | SvelteKit 5 (runes mode) | Continue from PoC |
| Frontend adapter | `adapter-vercel` | Vercel serverless/SSR integration |
| Hosting | Vercel (frontend + backend) | Single platform; `api/` dir matches PoC layout |
| Charts | Plotly.js | Interactive; D3 primitives available as escape hatch |
| Client storage | Dexie.js v4 (IndexedDB) | Continue from PoC |
| Export/import | JSZip | Continue from PoC |
| Backend runtime | Vercel Python Functions (FastAPI/ASGI) | `api/index.py`; free tier 10s timeout, Pro 60s |
| Analysis package | `bodaqs_analysis` (pip install) | Listed in `api/requirements.txt` |

---

## Commands

```bash
# Full-stack local dev (frontend + Python functions together)
cd webapp.bodaqs.net
vercel dev           # runs on :3000; Python functions on /api/*

# Frontend only
cd webapp.bodaqs.net/frontend
npm run dev          # dev server on :5173
npm run build        # production build
npm run check        # svelte-check + tsc
npm run lint         # prettier + eslint
npm run test         # vitest unit tests

# Backend only (useful for pytest)
cd webapp.bodaqs.net/api
uvicorn bodaqs_api.main:app --reload --port 8000
pytest               # all tests
pytest tests/test_preprocess_endpoint.py  # integration only
```

---

## Project Structure

```
webapp.bodaqs.net/
├── vercel.json                     ← routes: /api/* → Python functions, /* → SvelteKit
├── SPEC.md                         ← this file
│
├── frontend/                       ← SvelteKit app
│   ├── svelte.config.js            ← adapter-vercel
│   ├── vite.config.ts
│   ├── package.json
│   └── src/
│       ├── app.html
│       ├── app.d.ts
│       ├── lib/
│       │   ├── api/
│       │   │   └── preprocess.ts   ← POST /api/preprocess, types
│       │   ├── db/
│       │   │   ├── dexie.ts        ← Dexie schema (extend from PoC)
│       │   │   └── artifacts.ts    ← read/write helpers
│       │   ├── stores/
│       │   │   └── library.svelte.ts  ← run library (Dexie only; add localStorage fast-read cache only if init jank observed)
│       │   ├── charts/
│       │   │   ├── DisplacementHistogram.svelte
│       │   │   ├── VelocityHistogram.svelte
│       │   │   ├── EventsBar.svelte
│       │   │   └── MetricScatter.svelte
│       │   └── zip/
│       │       ├── export.ts       ← ZIP export (extend from PoC)
│       │       └── import.ts       ← ZIP import (extend from PoC)
│       └── routes/
│           ├── +layout.svelte      ← nav, global state
│           ├── +page.svelte        ← library / landing page
│           ├── upload/
│           │   └── +page.svelte    ← file upload + run creation; four required files (CSV, sidecar, bike profile, event schema) + optional preprocess profile
│           ├── dashboard/
│           │   └── [run_id]/
│           │       └── +page.svelte  ← 10-tile suspension dashboard
│           └── transfer/
│               └── +page.svelte    ← import / export ZIP
│
└── api/                            ← FastAPI Python backend
    ├── requirements.txt
    ├── requirements-dev.txt
    └── bodaqs_api/
        ├── main.py                 ← FastAPI app + CORS
        ├── default_preprocess_profile.json  ← bundled fallback; used when no profile file is uploaded
        ├── routes/
        │   └── preprocess.py       ← POST /api/preprocess
        ├── services/
        │   └── preprocess_service.py  ← wraps preprocess_session
        ├── schemas/
        │   └── preprocess.py       ← Pydantic request/response models
        └── index.py                ← Vercel ASGI entry point (exports `app`)
```

---

## API Design

### `POST /api/preprocess`

Multipart form upload. Runs the full `preprocess_session` pipeline for a single logger file.

**Inputs (multipart form):**
| Field | Type | Required | Notes |
|---|---|---|---|
| `csv_file` | File | Yes | Logger CSV; gzip accepted (decompress before processing) |
| `bike_profile_json` | File | Yes | Bike profile JSON |
| `sidecar_json` | File | Yes | Log metadata sidecar JSON |
| `event_schema_yaml` | File | Yes | Event schema YAML — passed directly to the pipeline; `schema_path` inside the preprocess profile is ignored |
| `preprocess_profile_json` | File | No | Preprocess profile JSON; if omitted the app's bundled default is used |

**Response `PreprocessResponse`:**
```jsonc
{
  "session_id": "2026-04-29_11-16-50",
  "meta": { /* session["meta"] — serialised to JSON */ },
  "source_sha256": "abc123...",
  "signals": {
    "column_names": ["front_wheel_disp_dom_wheel [mm]", ...],
    "n_rows": 12345,
    "columns": { "front_wheel_disp_dom_wheel [mm]": "<base64 float32>" }
  },
  "events": [ /* events_df records, NaN → null */ ],
  "metrics": [ /* metrics_df records, NaN → null */ ],
  "warnings": ["Event 'bottom_out': no matching signal for rear end"]
}
```

All chart computation (histogramming, scatter preparation, unit conversion) is a **frontend concern**. The backend returns the minimum data needed to reconstruct any view. This keeps the backend stateless and the API stable as new visualisations are added.

**Processing constraints:**
- Synchronous; 30 s server timeout
- Max upload: 50 MB per CSV
- Temp files cleaned up after response; no server-side persistence

_No profile listing endpoints._ Bike and preprocess profiles are user-supplied files, not server-managed. The upload UI provides a file picker for each; both are optional.

---

## Export Format (`.bodaqs.zip`)

A ZIP file that fully restores the in-browser session without re-uploading or re-processing. Contains the complete processed data so charts can be redrawn entirely on the frontend.

```
runs/
  {run_id}/
    run_manifest.json        ← { run_id, description, created_at, session_ids }
    sessions/
      {session_id}/
        session_manifest.json    ← { meta, source_sha256 }
        signals/signals.json     ← { col: base64float32, ... }   (full processed signal data)
        events/{schema_id}.json  ← event rows
        metrics/{schema_id}.json ← metric rows
```

A single export can contain multiple runs (the user selects which runs to include on the Transfer page). On import, runs are merged into the local library; duplicates (matched by `run_id`) are skipped.

The 50 MB upload cap is a starting point and should be revisited once typical full-ride file sizes are known.

---

## Dashboard: Suspension Metrics (`/dashboard/[run_id]`)

Mirrors `make_simple_suspension_metrics_dashboard` from the analysis notebook. 10 Plotly tiles in a 2-column grid:

| Row | Left | Right |
|---|---|---|
| 1 | Front: Displacement histogram | Rear: Displacement histogram |
| 2 | Front: Velocity histogram | Rear: Velocity histogram |
| 3 | Front: Events bar | Rear: Events bar |
| 4 | Front: Compressions >25% scatter | Rear: Compressions >25% scatter |
| 5 | Front: Rebounds >25% scatter | Rear: Rebounds >25% scatter |

**Controls:**
- Session selector: choose a single session to display (one at a time; multi-session overlay is out of scope for v1)
- Unit toggle: normalised (0–1) vs engineering units (mm / mm/s) for displacement/velocity tiles
- Missing tile: if a chart has no data (e.g. no rear signal), show a muted placeholder — not an error

---

## Code Style

**TypeScript / Svelte:**
```ts
// Svelte 5 runes — $state, $derived, $effect
// Strict TypeScript; no implicit `any`
// Named exports, not default for non-route modules
export function decodeSignalColumns(response: PreprocessResponse): Record<string, Float32Array> { ... }
```

**Python:**
```python
# Type annotations on all public functions
# Pydantic v2 models for all API schemas
# No bare `except:` — always catch a specific type or log + re-raise
def run_preprocess(csv_bytes: bytes, config: PreprocessConfig, filename: str) -> PreprocessResponse: ...
```

---

## Testing Strategy

**Backend (pytest):**
- `tests/test_health.py` — health endpoint (keep from PoC)
- `tests/test_preprocess_endpoint.py` — integration test: upload example CSV + sidecar, assert response schema, check `warnings` list
- `tests/test_preprocess_service.py` — unit test the service layer with a real (small) CSV from `analysis/Examples/logs/`
- Coverage target: all public service functions

**Frontend (vitest):**
- `db/artifacts.test.ts` — Dexie store/retrieve round-trip (keep from PoC, uses `fake-indexeddb`)
- `zip/export.test.ts` — export then import round-trip; verify signal round-trip fidelity
- `api/preprocess.test.ts` — response shape validation against TypeScript types

No full E2E (Playwright) in v1.

---

## Boundaries

**Always:**
- Validate file MIME types and size (reject > 50 MB CSV, reject non-JSON sidecar)
- Reject `POST /api/preprocess` with HTTP 422 if any required file is missing (`csv_file`, `bike_profile_json`, `sidecar_json`, `event_schema_yaml`)
- If `preprocess_profile_json` is not supplied, the service layer loads the bundled default profile from `api/bodaqs_api/default_preprocess_profile.json`
- Ignore `schema_path` inside the preprocess profile — the event schema always comes from the uploaded `event_schema_yaml` file
- Force `fit_import.enabled = false` in any preprocess profile (user-supplied or bundled default) — the web API has no access to a FIT file directory
- The event schema YAML must use the `inputs:` selector format (spec 0.1.2+); the older `sensors:` list format is not supported by the current event detection code
- Block the upload form submit button until all four required files are selected (frontend guard matches backend constraint)
- Clean up temp files after each request
- Include `warnings` array in every response (never silently swallow pipeline warnings)
- Use `preprocess_session` (not `run_macro`) — the old function no longer exists
- Keep signals encoded as float32 (not float64) to control IndexedDB/export size

**Ask first:**
- Adding new dashboard tiles or changing the existing 10
- Changing the ZIP export format in a backwards-incompatible way (bump a version field)
- Adding dependencies to the frontend or backend
- Schema changes to the Dexie database (requires a migration version bump)
- Adding user accounts or server-side session storage

**Never:**
- Persist uploaded CSV bytes on the server beyond the request lifetime
- Store PII (names, emails) anywhere in the app
- Commit secrets or API keys
- Remove or skip failing tests

---

---

*All open questions resolved. Spec is complete.*
