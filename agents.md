# AGENTS.md — BODAQS (Bicycle Open Data Acquisition System)

This repository contains firmware, analysis tooling, and supporting hardware/mechanical assets for BODAQS.
Agents should follow the collaboration rules and project conventions below.

## 1) Collaboration rules (read first)

1. **Overview first.** Before making edits, briefly state the intended approach and which files you expect to touch.
2. **Don’t guess about missing context.** If an edit depends on information not in the repo (e.g., hardware wiring, board variant, external service), ask a short question or present clearly-labeled assumptions.
3. **Prefer small, reviewable diffs.** Make minimal changes that solve the task; avoid drive-by refactors.
4. **Preserve public interfaces unless requested.** If you must change an interface (function signature, config fields, file format), call it out explicitly and update all call sites.
5. **Keep behavior stable by default.** If you change behavior, document the change (and any migration steps).

## 2) Repository layout (current)

Top-level folders in this repo include:

- `bodocs/`  
  Astro/starlight(https://starlight.astro.build/) powered documentation site (treat as separate from source code; edits here should be limited to docs updates).
  Contents of this folder are not expected to be edited when working on firmware or analysis tasks, except for documentation updates.
  Content should be added to `bodocs/src/content/` in MDX format and assets to `bodocs/src/assets/` when relevant.

- `docs/`  
  Formal project/reference documentation, including analysis contracts,
  firmware notes, and cross-project interchange specifications. This is separate
  from the published `bodocs/` site.

- `firmware/`  
  ESP32 logger firmware (Arduino-style multi-file sketch folder: `.ino` + `.h/.cpp`).
  Firmware reference docs live under `docs/firmware/`.

- `analysis/`  
  Python analysis tooling (package code and notebooks). Analysis contracts and
  reference docs live under `docs/analysis/`.

- `import-manager/`  
  BODAQS Import Manager desktop app, launchers, packaging/build scripts, and
  app-specific docs/release/planning notes. Reusable import engine modules remain
  under `analysis/bodaqs_analysis/`.

- `hardware/`  
  Electronics design assets (schematics/PCB, etc.).

- `mechanical/`  
  Mechanical CAD / 3D printing assets.

- `assets/`  
  Photos, screenshots, and other media used for documentation and communication.

- `Configs/`  
  Configuration files used by firmware and/or analysis (treat as canonical sources of configuration where applicable).

- `Tools/`  
  Developer tooling, scripts, or supporting utilities.

- `Examples/logs/`  
  Example datasets / sample log files used for documentation or testing.

- `To do/`  
  Project notes and task tracking.

- `.virtual_documents/analysis/`  
  Editor-generated artifacts (treat as non-source).

**Notes**
- Prefer keeping edits scoped to the relevant area (`firmware/` vs `analysis/` etc.).
- Do not invent new top-level folders without a clear reason.

## 3) Do not edit unless explicitly requested

To avoid accidental churn, **do not edit** the following unless the user explicitly asks:

- `Examples/logs/` (example datasets; treat as read-only)
- `assets/` (media; do not rename/optimise/re-encode)
- `To do/` (personal project notes/tasks)
- `.virtual_documents/analysis/` (editor-generated artifacts)

Do not move, rename, or reorganize files/folders unless the user explicitly requests it.

Also avoid “drive-by” formatting-only changes to:
- `.gitattributes`
- `.gitignore`
- `requirements.txt`
- `README.md`

…unless the user request is directly about those files.

## 4) Firmware conventions (ESP32 logger)

### 4.1 Modularity
Firmware is structured around modules/managers (e.g., `RTCManager`, `StorageManager`, `ButtonManager`, `DisplayManager`, `MenuManager`, etc.).

- Prefer **single-responsibility modules**.
- Prefer **clear, explicit interfaces** between modules.
- Avoid hidden global coupling. If a module depends on another, make that dependency obvious.

### 4.2 Configuration
If configuration is present (e.g., `LoggerConfig` or similar):
- Prefer adding fields in a single canonical config struct/source of truth.
- Update all consumers consistently (menu, web UI, logging, etc.).
- If defaults change, document them.

### 4.3 Logging and diagnostics
- Prefer consistent log tags/prefixes (e.g., `[Storage]`, `[WiFi]`, etc.) if already used.
- Avoid very chatty logging in tight loops unless guarded by a debug flag.
- For high-rate sampling/logging paths, avoid allocations and blocking calls when possible.

### 4.4 Time/timestamps
- Preserve existing timestamp formats and semantics unless the task explicitly changes them.
- If both human-readable and fast integer timestamps exist, keep them consistent and document any conversions.

### 4.5 Style
- Keep existing formatting and naming conventions.
- Prefer descriptive names over abbreviations.
- Keep headers tidy (forward declarations when helpful, avoid circular includes).

## 5) Python analysis conventions (`analysis/`)

### 5.1 Code structure
- The analysis code is intended to be modular and reproducible.
- Prefer pure functions and explicit inputs/outputs for pipeline stages.

### 5.2 Notebooks
- Avoid embedding large blocks of “library code” inside notebooks—prefer putting reusable code into the package and importing it.
- Notebooks should be runnable top-to-bottom when feasible.

### 5.3 Logging
- Use Python’s `logging` module (not print) for library code.
- Avoid changing global logging configuration inside library modules.

### 5.4 Style & tooling
If the repo contains tooling config (e.g., `pyproject.toml`, `ruff.toml`, `pytest.ini`):
- Follow it.
If not present:
- Keep edits minimal and consistent with surrounding code.

## 6) Safety and correctness checks

When making changes:
- Identify likely regressions (build errors, missing imports, renamed symbols).
- Update all call sites.
- If tests/build commands are available, run them; if not, state what should be run manually.

## 7) Commands (adjust to what exists in this repo)

### Firmware
- Primary workflow: **Arduino IDE build/upload** (manual).
- If a CLI build is later added (e.g., PlatformIO), prefer:
  - `pio run`
  - `pio run -t upload`

### Analysis
- If tests exist: `pytest -q`
- If a venv workflow is used: install dependencies per `requirements.txt`.
- Keep notebook-specific steps documented in `analysis/` where relevant.

## 8) What “done” means

A change is considered done when:
- The implementation matches the requested behavior.
- All call sites are updated.
- The change is reviewable (diff is reasonably scoped).
- Any required manual steps (Arduino IDE compile/upload, notebook run) are clearly listed.

## 9) Azure Boards backlog management

- Organization: `bodaqs`
- Project: `BODAQS`
- Team: `BODAQS Team`
- Process: Agile
- Default product-backlog work item type: `User Story`
- Use the configured Azure DevOps MCP server for backlog requests.
- Treat an explicit request to "add" or "create" an item as authorization for that
  item. Otherwise, prepare a preview before writing to Azure DevOps.
- Do not delete work items, perform bulk updates, or change item state unless the
  user explicitly requests it.
- After creating an item, report its work item ID and URL.
