# PROJECT_CONTEXT

## Overview

BODAQS (Bicycle Open Data Acquisition System) is an ESP32-based bicycle data logger plus a Python analysis stack for turning ride logs into repeatable event- and metric-driven analysis. This repo currently holds PlatformIO firmware for a SparkFun ESP32-S3 Thing Plus logger, reusable Python modules in `analysis/bodaqs_analysis`, working Jupyter notebooks, hardware shield revisions, mechanical parts, config presets, sample logs, and a few developer support scripts.

## Repo Layout

- `firmware/`: Active firmware project using PlatformIO with the Arduino framework. Key subfolders are `src/` for manager-style modules and `main.cpp`, `boards/` for the custom SparkFun ESP32-S3 board JSON, `variants/` for local pin definitions, and `documentation/` / `libraries/` for firmware support material.
- `analysis/`: Active Python analysis workspace. `analysis/bodaqs_analysis/` contains reusable package code, root-level notebooks include `bodaqs_batch_preprocessing_pipeline.ipynb`, `bodaqs_event_schema_test_harness.ipynb`, `BODAQS_library_manager.ipynb`, `bodaqs_session_test_notebook.ipynb`, and `BODAQS_simple_suspension_metrics.ipynb`, `event schema/` holds YAML event definitions, and `tests/` holds Python tests.
- `hardware/`: Electronics design assets for multiple shield revisions, including Proto E, v1, and v2, with SMD variants.
- `mechanical/`: Mechanical assets, currently including linear potentiometer mount work.
- `Configs/`: Canonical config presets such as `loggercfg.txt`, `loggercfg_proto_A.txt`, and `loggercfg_Proto_D.txt`.
- `Tools/`: Developer support assets, including `run_widget_notebook_smoke_tests.ps1` and a lookup-table spreadsheet.
- `Examples/logs/`: Example CSV datasets and sample logs. Treat as read-only unless explicitly asked.
- `How_to/`: Supporting notes split into `Analysis/` and `Hardware/`.
- `analysis_old/`: Older analysis notebooks/docs kept as historical context.
- `logs/`: Local captured CSV log files used during current analysis work.
- `.virtual_documents/` and `analysis/.virtual_documents/`: Editor-generated artifacts, not source.
- `assets/`: Not present in this checkout. If added later, treat as media and do not edit unless requested.

## Local Dev Environment (Windows)

- Python is expected to use the repo-local virtual environment at `.venv/`.
- PowerShell activation command:

```powershell
.\.venv\Scripts\Activate.ps1
```

- Launch JupyterLab from the activated repo-local venv, not from Conda.
- Conda is not required for the current workflow and is better treated as legacy here.
- Note: `analysis\launch_jlab.bat` is still conda-oriented, but `.codex\config.toml` already reflects the preferred `.venv` workflow.

## Canonical Commands

### Firmware Build / Upload

Current default PlatformIO environment in `firmware/platformio.ini` is `thingplus_s3_usb_cdcserial`. There is also an alternate `thingplus_s3_usb_uartserial` environment.

```powershell
cd firmware
pio run
pio run -t upload
```

### Firmware Serial Monitor

`monitor_speed` is `115200` in `platformio.ini`.

```powershell
cd firmware
pio device monitor -b 115200
```

Or, if you want to stay inside the PlatformIO task flow:

```powershell
cd firmware
pio run -t monitor
```

### Python / Analysis Setup

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cd analysis
python -c "import bodaqs_analysis; print('bodaqs_analysis ok')"
cd ..
```

### JupyterLab

```powershell
.\.venv\Scripts\Activate.ps1
python -m jupyter lab --notebook-dir=analysis
```

### Useful Existing Codex Shortcuts

These are already defined in `.codex/config.toml`:

- `build_firmware = "cd firmware && pio run"`
- `upload_firmware = "cd firmware && pio run -t upload"`
- `smoke_analysis = ".\\.venv\\Scripts\\python -c \"import bodaqs_analysis; print('bodaqs_analysis ok')\""`
- `test_analysis = ".\\.venv\\Scripts\\python -m pytest -q analysis"`
- `jlab = ".\\.venv\\Scripts\\python -m jupyter lab --notebook-dir=analysis"`

## Important Project Conventions / Rules

- Start with an overview-first plan before editing, including which files you expect to touch.
- Do not guess about missing hardware, board, or external-service context. Ask or state assumptions explicitly.
- Keep diffs small and reviewable. Avoid drive-by refactors.
- Preserve public interfaces unless the task explicitly requires changes, and then update all call sites.
- Keep behavior stable by default. If behavior changes, call it out and document any migration steps.
- Scope edits to the relevant area (`firmware/`, `analysis/`, etc.) and avoid inventing new top-level folders.
- Run the relevant build/test command when practical; if you cannot, say what still needs manual verification.
- Avoid drive-by formatting-only edits to `.gitattributes`, `.gitignore`, `requirements.txt`, `README.md`, or any protected folders.

Do not edit these areas unless explicitly requested:

- `Examples/logs/`
- `assets/` if/when present
- `To do/`
- `.virtual_documents/`
- `analysis/.virtual_documents/`

Also do not move, rename, or reorganize files/folders unless explicitly asked.

## Key Architecture Notes

### Firmware

- `firmware/src/main.cpp` is the boot and wiring point: board selection, storage, config load, sensor setup, Wi-Fi, web server, UI/display, logging, and button registration.
- Firmware is organized around manager modules with explicit responsibilities: `ConfigManager`, `SensorManager`, `StorageManager`, `LoggingManager`, `RTCManager`, `WiFiManager`, `WebServerManager`, `DisplayManager`, `MenuSystem`, `IndicatorManager`, and `PowerManager`.
- Hardware details are increasingly board-profile driven: `BoardProfile`, `BoardSelect`, and the custom PlatformIO board/variant files separate pin/hardware setup from runtime config.
- Logging and diagnostics are centralized through `DebugLog` macros with tags such as `CFG`, `WiFi`, `Storage`, `WS`, `BTN`, and `BOOT`.
- `StorageManager` owns SD access and log-file lifecycle; `LoggingManager` controls start/stop/mark behavior; `WebServerManager` and logging are intentionally interlocked.
- `TransformRegistry` loads per-sensor transform definitions from storage, and `SensorManager` builds sensor objects from config-derived specs.

### Analysis

- The reusable code lives in `analysis/bodaqs_analysis/`; notebooks are mainly orchestration and UI surfaces over package code.
- The main preprocessing entry point is `bodaqs_analysis.pipeline.run_macro(...)`.
- The rough pipeline is: load logger CSV -> canonicalize/standardize signal names -> build signal registry -> normalize/zero/filter/resample/derive VA -> load event schema YAML -> detect events -> extract segments per `schema_id` -> compute metrics -> validate session/metrics -> optionally persist artifacts.
- Event schemas live under `analysis/event schema/`. The default UI path in `bodaqs_analysis.ui.preprocess_controls` is `event schema\event_schema.yaml`.
- `bodaqs_analysis.schema.load_event_schema()` loads the YAML and can return a SHA-256 hash for provenance.
- Event and metric artifacts are schema-aware: analysis code partitions outputs by `schema_id` and copies the exact `schema.yaml` used into artifact folders so downstream work can resolve provenance.
- Widget code is heavily schema-mediated: event browsers, metric widgets, and session/entity-scope tools use schema IDs plus signal registries to resolve the correct sensors/signals for each session.

## Current State / Recent Work

- Firmware was migrated from an Arduino sketch-style layout into a PlatformIO project under `firmware/`, with the main entry point now at `firmware/src/main.cpp`.
- The PlatformIO migration added a custom board definition at `firmware/boards/sparkfun_esp32s3_thing_plus.json` and a local variant under `firmware/variants/sparkfun_esp32s3_thing_plus/`.
- `firmware/platformio.ini` now carries two serial-mode environments and explicitly sets local variants plus default Arduino partitions (`board_build.partitions = default.csv` in the current file).
- Recent firmware work also adjusted Wi-Fi behavior, including a move to synchronous scanning (`c86b112`) and logic around configured SSID/BSSID-based network selection in `WiFiManager.cpp`.
- Hardware/button definitions were previously moved toward board profiles rather than living only in config; `ConfigManager` now logs that hardware buttons come from `BoardProfile`.
- The analysis side has been rebuilt into reusable modules under `analysis/bodaqs_analysis/` instead of leaving core logic embedded only in notebooks.
- Recent analysis work added Butterworth smoothing support, cleaned up widget shared utilities, added persisted selector/entity-scope behavior, and introduced the newer library manager/session notes flow.
- There are active notebooks for batch preprocessing, event-schema testing, session browsing, library management, and simple suspension metrics rather than a single monolithic notebook.
- The repo already carries a `.venv/` and a `.codex/config.toml` with common build, test, smoke, and Jupyter commands, which is the current Codex-friendly workflow.
- `analysis/launch_jlab.bat` is a legacy conda-based launcher; prefer the repo-local venv commands above for durable cross-machine setup.

## How To Ask Codex To Work Safely In This Repo

### Firmware Task Template

```text
Task: Make this firmware change in `firmware/` only: <describe change>.

Rules:
- Start with a brief overview and list the firmware files you expect to touch.
- Do not edit anything under `analysis/`, notebooks, `Examples/logs/`, `To do/`, or `.virtual_documents/`.
- Keep interfaces stable unless absolutely necessary, and call out any interface changes.
- After editing, run `cd firmware && pio run` and report the result.
```

### Analysis Task Template

```text
Task: Make this analysis change in `analysis/` only: <describe change>.

Rules:
- Prefer edits in `analysis/bodaqs_analysis/` and `analysis/tests/`.
- Do not edit notebooks unless I explicitly ask.
- Keep the diff minimal and avoid unrelated cleanup.
- After editing, run `.\.venv\Scripts\python -m pytest -q analysis` or a smaller smoke command if that is more appropriate, and report what passed.
```

### Notebook Creation Template

```text
Task: Create a new notebook under `analysis/` named `<new_notebook>.ipynb`.

Rules:
- New notebook only; do not modify existing modules or existing notebooks.
- Reuse imports from `analysis/bodaqs_analysis/` instead of pasting library code into the notebook.
- Do not touch `Examples/logs/`, `To do/`, `assets/`, or `.virtual_documents/`.
- Briefly explain the notebook purpose and which existing package modules it depends on.
```

