# BODAQS Web Application

Browser-based interface for BODAQS suspension telemetry analysis. Converts raw mountain bike suspension CSV logs into events, metrics, and signal visualisations — no desktop install required.

This directory contains the application layer that sits on top of the existing `analysis/` Python library.

```
webapp.bodaqs.net/
  api/       FastAPI backend — stateless compute engine
  webapp/    SvelteKit frontend — runs entirely in the browser
```

The backend wraps `bodaqs_analysis.pipeline.run_macro()` and exposes it as an HTTP endpoint. The frontend compresses CSVs before upload, stores processed artifacts in IndexedDB, and lets users export their data as a portable ZIP bundle.

---

## Architecture overview

| Layer | Technology | Role |
|---|---|---|
| Frontend | SvelteKit + TypeScript | Upload, results, export/import UI |
| Browser storage | IndexedDB (Dexie.js) + localStorage | Working data cache + run index |
| Backend | FastAPI + Python | Stateless preprocessing via `run_macro()` |
| Persistence | ZIP export / import | User-owned portable workspace |

The server holds no data between requests. After processing, users export a ZIP bundle containing their runs; they re-import it to resume work later.

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- The `analysis/` package at the repo root (installed below)

---

## Quickstart

### 1 — Backend

```bash
# From repo root
pip install -r webapp.bodaqs.net/api/requirements.txt -e analysis/

cd webapp.bodaqs.net
uvicorn api.main:app --reload
```

The API starts at `http://localhost:8000`. Test it:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### 2 — Frontend

```bash
cd webapp.bodaqs.net/webapp
npm install
npm run dev
```

The app starts at `http://localhost:5173`.

### 3 — Process your first session

1. Open `http://localhost:5173/preprocess`
2. Paste the contents of `analysis/event schema/event_schema.yaml` into the schema field
3. Pick one or more CSV files from `analysis/logs_test/`
4. Click **Process** — each file shows a per-file status as it uploads
5. Navigate to `/` — your run appears in the library
6. Go to `/transfer` to export a ZIP bundle for safekeeping

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/preprocess` | Upload CSV → get back events, metrics, signals |

`POST /api/preprocess` accepts multipart form data:
- `csv_file` — raw or gzip-compressed CSV
- `config_json` — JSON string matching the `PreprocessConfig` schema

The frontend compresses files with `CompressionStream('gzip')` before upload.

---

## Running tests

```bash
# From repo root — backend integration tests (call real run_macro())
pytest

# Frontend unit tests
cd webapp.bodaqs.net/webapp
npx vitest run
```

---

## Export / import

The `/transfer` page lets you:

- **Export** — select runs and download a ZIP. The ZIP mirrors the existing artifact folder layout and is compatible with the analysis notebooks.
- **Import** — drop a ZIP, preview which runs it contains, and selectively load only the ones you want. This prevents re-importing a full export from immediately filling browser storage quota.
