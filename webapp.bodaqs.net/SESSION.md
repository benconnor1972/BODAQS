# BODAQS Webapp Session State
*Last updated: 2026-05-01*

## What we're building
`webapp.bodaqs.net/` — a hosted SvelteKit 5 + FastAPI web app that replaces the Jupyter notebook workflow. Users upload logger files → backend runs preprocessing → frontend shows the 10-tile suspension dashboard → export/import as `.bodaqs.zip`.

Spec lives at: `/Volumes/www/BODAQS/webapp.bodaqs.net/SPEC.md` — keep it updated as decisions are made.

---

## Phase status

| Phase | Status | Notes |
|---|---|---|
| 1 — Backend | ✅ Complete, 19/19 tests passing | See below for details |
| 2 — Frontend scaffold | 🔜 Next | Replace adapter-auto, add vercel.json, strip PoC pages |
| 3 — Core data layer | ⬜ Not started | Dexie schema, library store |
| 4 — Upload flow | ⬜ Not started | File pickers, API call, Dexie write |
| 5 — Dashboard | ⬜ Not started | 10-tile Plotly grid |
| 6 — Transfer + deploy | ⬜ Not started | ZIP export/import, Vercel deploy |

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

## Phase 2 — What to do next

The `webapp.bodaqs.net/frontend/` directory exists but only contains `.svelte-kit/` generated files — no actual source yet. The PoC was on `feat/preprocess-mvp` branch (not this branch).

Steps:
1. Init a SvelteKit 5 project in `frontend/` (or scaffold from PoC if it was rebased in)
2. Replace `adapter-auto` with `adapter-vercel` in `svelte.config.js`
3. Add `vercel.json` routing: `api/*` → Python functions, `/*` → SvelteKit
4. Strip PoC preprocess page back to placeholder; keep Dexie and zip modules
5. Add `export const prerender = false` to `/dashboard/[run_id]/+page.ts`
6. Checkpoint: `npm run build` succeeds, `vercel dev` starts

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
