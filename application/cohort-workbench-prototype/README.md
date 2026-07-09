# BODAQS Study Set Workbench Prototype

Static React/Vite prototype for the BODAQS Library Browser and Study Set
Builder.

The prototype is designed to run in two local modes:

- Vite development mode, with the browser app on `http://localhost:5173` and the
  Library API service on `http://127.0.0.1:8765`.
- Bundled local mode, where the Library API service serves the built web app and
  API from the same origin.

## Run

```powershell
cd C:\Users\benco\dev\BODAQS\application\cohort-workbench-prototype
npm install
npm run dev
```

Start the Library API service in a second terminal:

```powershell
cd C:\Users\benco\dev\BODAQS\analysis
..\.venv\Scripts\python.exe -m bodaqs_analysis.library_api_service --libraries-root "C:\Users\benco\OneDrive\BODAQS-data" --host 127.0.0.1 --port 8765
```

If the current terminal does not know where Node.js is, open a fresh terminal or
prepend the Node install path:

```powershell
$env:Path = "C:\Program Files\nodejs;$env:Path"
```

By default, dev and hosted builds call `http://127.0.0.1:8765`. Override that
with `VITE_BODAQS_LIBRARY_API_URL` when needed:

```powershell
$env:VITE_BODAQS_LIBRARY_API_URL = "http://127.0.0.1:8766"
npm run dev
```

## Bundled Local Smoke Test

Build the web app:

```powershell
cd C:\Users\benco\dev\BODAQS\application\cohort-workbench-prototype
npm run build
```

Serve the built app from the Library API service:

```powershell
cd C:\Users\benco\dev\BODAQS\analysis
..\.venv\Scripts\python.exe -m bodaqs_analysis.library_api_service --libraries-root "C:\Users\benco\OneDrive\BODAQS-data" --host 127.0.0.1 --port 8765 --web-root "..\application\cohort-workbench-prototype\dist"
```

Open `http://127.0.0.1:8765/`. In this mode the web app uses the same origin for
API calls, so no `VITE_BODAQS_LIBRARY_API_URL` setting is required.

Optional health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/v1/health | ConvertTo-Json -Depth 5
```

The `web_app` field should report `enabled: true` and `index_present: true`.

## Checks

```powershell
npm run build
npm run lint
```

## Current Scope

- Browse, sort, filter, inspect, rename, and delete library sessions.
- Create, save, load, analyze, and manage Study Sets.
- Manage saved filters, tracks, notes, bookmarks, GPS previews, and signal
  inspection workflows through the Library API service.
- Launch analysis views from the library browser or saved/current Study Sets.
