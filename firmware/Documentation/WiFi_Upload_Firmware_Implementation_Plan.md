# Wi-Fi Upload Firmware Implementation Plan

Status: draft

This plan implements the API described in `WiFi_Upload_API_v1.md`.

The core firmware change is to add an explicit upload mode and a small
machine-readable API for completed session archives. The desktop import agent
will then download archives and hand them to the existing preprocessing
pipeline.

## Design Decisions

- Upload is allowed only in explicit upload mode.
- The logger creates a session ZIP when a log is closed and the same-stem JSON
  metadata has been written.
- The configured logger identity string is reused as `logger_id`.
- Session identity is `logger_id + "__" + session_stem`.
- File size is not part of session identity.
- Automatic PC connection to logger AP mode is out of scope.
- Delete-after-import is optional and disabled by default.

## Firmware Areas Touched

Expected files/modules:

- `LoggingManager`: trigger archive creation after log close and metadata write
- `LogMetadataWriter`: confirm JSON completion point is observable
- `StorageManager`: provide reusable file/archive helpers if needed
- `Routes_Files`: reuse or extract existing ZIP streaming/building helpers
- `Routes_Api`: new API route module
- `WebServerManager`: register the new API routes
- `WiFiManager`: report mode/IP/MAC/hostname details
- `ConfigManager`: expose/persist logger identity cleanly if needed
- `MenuSystem` / `ButtonActions` / `UI`: enter/exit upload mode
- `FirmwareInfo`: report firmware version in `/api/v1/device`

## Phase 1. Contract And State Model

Purpose:

- define the firmware state needed before adding transfer behavior

Status:

- implemented as a runtime `UploadModeManager`
- logging start is refused while upload mode is active
- `upload_mode_toggle` is available as an optional button binding action
- the idle OLED HUD shows `UPLOAD MODE` while the mode is active

Tasks:

- Add an `UploadModeManager` or equivalent small state holder.
- Track `upload_mode` as a runtime state, not just a config field.
- Provide functions:
  - `bool isUploadModeActive()`
  - `bool canEnterUploadMode()`
  - `bool enterUploadMode()`
  - `void exitUploadMode()`
- Block entering upload mode while a log is actively open unless a clean close
  path is explicitly implemented.
- Block starting a new log while upload mode is active.
- Make UI/display status able to show upload mode.

Acceptance checks:

- upload mode can be entered and exited without Wi-Fi enabled
- logging cannot start in upload mode
- upload mode cannot expose a currently open log

## Phase 2. Logger Identity

Purpose:

- expose a stable configured logger identity in the API

Status:

- implemented `ConfigManager::loggerId()` and
  `ConfigManager::loggerId(const LoggerConfig&)`
- `logger_name` remains the persisted source of truth
- the helper trims whitespace, replaces path/filename-unsafe characters with
  underscores, and falls back to `BODAQS` if the result is empty
- `/api/v1/device` exposure remains part of the Phase 5 API route work

Tasks:

- Map the existing `logger_name` config key directly to `logger_id` in the API.
- Add a helper such as `ConfigManager::loggerId()` or a local API helper that:
  - trims whitespace
  - rejects or replaces path separators
  - returns a non-empty fallback

Acceptance checks:

- `/api/v1/device` can report `logger_id`
- session IDs remain stable across reboot
- session IDs are safe to place in URL query parameters after encoding

## Phase 3. Archive Creation At Log Close

Purpose:

- make each completed session self-contained before upload

Status:

- implemented a file-output store-only `ZipArchiveWriter`
- `StorageManager_stopLog()` now creates a same-stem session archive only after
  the CSV is closed and same-stem JSON metadata has been saved successfully
- archive creation writes `<session_stem>.zip.tmp` first, then renames to
  `<session_stem>.zip`
- failed archive creation leaves the CSV and JSON in place and removes the
  incomplete temp archive where possible
- metadata-disabled logs do not create archives because the import contract
  requires both CSV and JSON

Tasks:

- Identify the exact point where `StorageManager_stopLog()` closes the CSV.
- Identify the exact point where `LogMetadataWriter` completes the same-stem
  JSON file.
- After both files are closed successfully, create:
  - `<session_stem>.zip`
- The archive must contain exactly:
  - `<session_stem>.CSV`
  - `<session_stem>.json`
- Write the archive to a temporary name first, for example:
  - `<session_stem>.zip.tmp`
- Rename to `<session_stem>.zip` only after archive creation completes.
- If archive creation fails:
  - keep the CSV and JSON
  - do not create a final `.zip`
  - log/report the failure

Implementation notes:

- `Routes_Files.cpp` already has store-only ZIP helpers for `/download_zip`.
- Prefer extracting reusable ZIP helpers rather than duplicating ZIP-writing
  code inside `LoggingManager`.
- The current `/download_zip` implementation streams directly to HTTP. Archive
  creation needs the same ZIP records written to an SD file instead of a
  `WebServer` response.
- A small `ZipWriter` helper that can write to either `File` or `WebServer`
  would reduce duplication, but a file-only helper is acceptable for the first
  implementation.

Acceptance checks:

- every normal completed log creates a ZIP containing the same-stem CSV and JSON
- after successful ZIP creation, loose same-stem CSV/JSON files are removed
- failed ZIP creation does not corrupt or remove CSV or JSON
- no `.zip` is visible until complete
- generated ZIP opens on Windows
- generated ZIP passes the import-agent archive validation contract

## Phase 4. Session Discovery

Purpose:

- enumerate importable sessions from SD

Status:

- implemented `UploadSessionScanner`
- scanner walks a requested SD directory, currently expected to be `/` for the
  existing logger file layout
- scanner treats same-stem `.zip` files as canonical importable sessions; loose
  same-stem `.CSV`/`.json` files may exist on older cards but are not required
- scanner ignores `.zip.tmp` files as importable archives and counts them for
  diagnostics
- scanner returns only complete importable sessions and reports incomplete
  candidates in a bounded summary
- `session_id` is derived as `ConfigManager::loggerId() + "__" +
  session_stem`
- upload/acknowledgement flags are currently placeholders until the upload
  index/ack phase is implemented

Tasks:

- Add a session scanner that walks the log directory or relevant SD root.
- Find same-stem ZIP archives:
  - `.zip`
- Return only complete sessions as importable.
- Optionally return incomplete sessions for diagnostics with
  `archive_ready: false`.
- Derive:
  - `session_stem`
  - `session_id`
  - CSV path
  - JSON path
  - archive path
  - acknowledgement/upload flags if present

Implementation notes:

- Keep scanner logic separate from HTML file browsing.
- Avoid heap-heavy full-directory JSON construction if many logs exist.
- Start with a reasonable session list limit if memory becomes tight.

Acceptance checks:

- only complete closed sessions appear as downloadable
- partially written `.zip.tmp` files are ignored
- incomplete CSV/JSON pairs are not importable

## Phase 5. API Route Module

Purpose:

- expose a machine-readable API without disturbing the existing web UI

Status:

- implemented `Routes_Api`
- registered API routes from `WebServerManager::setupRoutes()`
- implemented:
  - `GET /api/v1/device`
  - `GET /api/v1/status`
  - `POST /api/v1/upload-mode/enter`
  - `POST /api/v1/upload-mode/exit`
  - `GET /api/v1/sessions`
  - `GET /api/v1/session/archive?id=<session_id>`
- session list and archive download require upload mode and return `409` when
  upload mode is inactive
- session acknowledgement is implemented in Phase 7
- session deletion is registered but returns `501 not_implemented` after
  upload-mode gating until the deletion policy is implemented
- API responses use JSON envelopes and no-store cache headers

Tasks:

- Add `firmware/src/Routes_Api.h`.
- Add `firmware/src/Routes_Api.cpp`.
- Register routes from `WebServerManager::setupRoutes()`.
- Implement:
  - `GET /api/v1/device`
  - `GET /api/v1/status`
  - `POST /api/v1/upload-mode/enter`
  - `POST /api/v1/upload-mode/exit`
  - `GET /api/v1/sessions`
  - `GET /api/v1/session/archive?id=<session_id>`
  - `POST /api/v1/session/ack`
  - `POST /api/v1/session/delete`

Implementation notes:

- Use query-argument route shapes for session operations because Arduino
  `WebServer` is simpler with fixed route paths.
- Use ArduinoJson for response JSON, with careful document sizes.
- Return JSON error bodies where feasible.
- Call existing activity hooks so Wi-Fi/power idle timers do not cut off an
  active upload.

Acceptance checks:

- `/api/v1/device` and `/api/v1/status` work outside upload mode
- session list/download/delete return `409` outside upload mode
- API routes do not break existing `/files`, `/config`, or transform routes

## Phase 6. Archive Download

Purpose:

- allow the import agent to pull one completed session archive

Status:

- implemented during Phase 5 as `GET /api/v1/session/archive?id=<session_id>`
- route requires upload mode and returns `409` otherwise
- route resolves the requested session through `UploadSessionScanner`
- route streams the completed `.zip` archive with `Content-Type:
  application/zip` and a `<session_id>.zip` attachment filename
- repeated downloads do not mutate logger-side state

Tasks:

- Resolve `session_id` to an archive path.
- Validate the resolved file belongs to the session list.
- Stream the `.zip` file with:
  - `Content-Type: application/zip`
  - `Content-Disposition: attachment; filename="<session_id>.zip"`
- Reject unknown sessions with `404`.
- Reject non-upload-mode requests with `409`.

Acceptance checks:

- importing a downloaded archive succeeds through the existing desktop import
  agent
- interrupted HTTP download does not change logger-side session state
- repeated downloads of the same session are allowed

## Phase 7. Acknowledgement Index

Purpose:

- let the logger remember sessions successfully handled by a PC

Status:

- implemented `UploadAckIndex`
- acknowledgement records are stored as newline-delimited JSON at
  `/upload_index.ndjson`
- latest valid record for a `session_id` wins
- corrupt lines are skipped when reading the index
- `POST /api/v1/session/ack` now validates upload mode, validates that the
  session exists, appends an acknowledgement record, and returns the recorded
  state
- `/api/v1/sessions` now reports `uploaded` and `acknowledged` from the index

Tasks:

- Add a small upload acknowledgement index on SD.
- Suggested path:
  - `/logs/upload_index.json`
  - implemented path: `/upload_index.ndjson`
- Record at minimum:
  - `session_id`
  - `status`
  - `library_id`
  - `run_id`
  - `imported_at`
- Add helpers:
  - `bool markSessionAcknowledged(...)`
  - `bool isSessionAcknowledged(session_id)`
- Include acknowledgement state in `/api/v1/sessions`.

Implementation notes:

- Keep the index append/update behavior robust against power loss.
- If JSON rewrite complexity is high, start with newline-delimited JSON records
  and let latest record win.

Acceptance checks:

- acknowledged sessions remain acknowledged after reboot
- repeated acknowledgement is idempotent
- corrupt acknowledgement index does not block session listing

## Phase 8. Optional Cleanup

Purpose:

- support user-requested storage cleanup after successful import

Status:

- implemented `UploadSessionCleanup`
- `POST /api/v1/session/delete` now requires upload mode
- cleanup requires a prior acknowledgement in `UploadAckIndex`
- supported request modes:
  - `move_to_uploaded`
  - `delete`
- `move_to_uploaded` creates `/uploaded` if needed and moves the ZIP; loose
  same-stem CSV/JSON files are moved too when present on older cards
- `delete` removes the ZIP; loose same-stem CSV/JSON files are removed too when
  present on older cards
- partial cleanup failures are reported with per-file success flags

Tasks:

- Implement `POST /api/v1/session/delete`.
- Require upload mode.
- Require prior acknowledgement unless a future explicit force flag is added.
- Support:
  - `move_to_uploaded`
  - `delete`
- For `move_to_uploaded`, move the ZIP and any loose legacy CSV/JSON companions.
- For `delete`, delete the ZIP and any loose legacy CSV/JSON companions.

Recommended default:

- desktop app setting off
- firmware endpoint available but conservative

Acceptance checks:

- unacknowledged sessions cannot be deleted through normal API calls
- partial cleanup failure is reported clearly
- moved/deleted sessions no longer appear as importable

## Phase 9. Wi-Fi Discovery Support

Purpose:

- make station-mode discovery smoother without forcing AP automation

Status:

- implemented `WiFiManager::hostname()` as the shared stable hostname helper
- station-mode connection sets the Wi-Fi hostname before association
- station-mode ONLINE starts mDNS advertisement:
  - service: `_bodaqs-logger._tcp`
  - port: `80`
- mDNS TXT records currently include:
  - `api=1`
  - `logger_id=<logger_id>`
  - `upload_mode=true|false`
  - `hostname=<hostname>`
- upload mode enter/exit refreshes mDNS so `upload_mode` TXT stays current
- mDNS is stopped when Wi-Fi leaves station-online mode or AP mode starts
- `/api/v1/device` and `/api/v1/status` report the same hostname

Tasks:

- Add a stable hostname derived from logger ID if not already present.
- Add mDNS advertisement in station mode:
  - service: `_bodaqs-logger._tcp`
  - port: `80`
- Include TXT records where practical:
  - `api=1`
  - `logger_id=<logger_id>`
  - `upload_mode=true|false`
- In AP mode, keep a recognizable SSID, but the PC still confirms identity via
  `/api/v1/device`.

Acceptance checks:

- station-mode logger is discoverable on a local network that permits mDNS
- API works equally in station and AP modes after the PC is connected
- no desktop AP auto-join behavior is required

## Phase 10. UI And Controls

Purpose:

- make upload mode discoverable and hard to enter accidentally

Status:

- implemented an `Upload: ON/OFF` main-menu entry
- selecting the menu entry opens an upload status screen rather than toggling
  immediately
- upload status screen shows:
  - upload mode state
  - Wi-Fi SSID/mode
  - IP address
  - importable and incomplete session counts
- Enter/Right toggles upload mode from the upload status screen
- the existing `upload_mode_toggle` button binding action remains available
- `/files` now includes a `Logger upload` panel with upload mode status,
  network details, session counts, and enter/exit controls
- generic file-browser mutations are blocked while logging or upload mode is
  active; downloads remain available
- config pages and config POST routes are locked while logging or upload mode
  is active

Tasks:

- Add upload mode to the on-device menu.
- Add button binding action if useful:
  - `upload_mode_toggle`
  - or `upload_mode_enter`
- Add status display:
  - upload mode active
  - IP/SSID
  - sessions available
- Add web UI controls to enter/exit upload mode.
- Ensure config pages and upload API do not allow conflicting operations while
  logging or upload mode state blocks them.

Acceptance checks:

- user can enter upload mode without a PC
- user can tell when upload mode is active
- user can exit upload mode cleanly

## Testing Plan

### Compile Tests

- Build all active PlatformIO environments.
- Confirm no route/module include cycles.

### Bench Tests

- Record a short log.
- Confirm a ZIP is created and loose same-stem CSV/JSON files are removed after
  successful archiving.
- Connect in station mode.
- Enter upload mode.
- Fetch `/api/v1/device`.
- Fetch `/api/v1/status`.
- Fetch `/api/v1/sessions`.
- Download archive.
- Import archive with the desktop import agent.
- Acknowledge the session.
- Reboot logger and confirm acknowledgement persists.

### AP Mode Tests

- Put logger in AP mode.
- Connect PC manually to logger AP.
- Confirm API behavior matches station mode.
- Confirm no app-level AP/station mode choice is required.

### Failure Tests

- Interrupt archive download and retry.
- Remove JSON for a CSV and confirm session is not importable.
- Leave `.zip.tmp` present and confirm it is ignored.
- Try list/download outside upload mode and confirm `409`.
- Try delete before acknowledgement and confirm rejection.

## Suggested Implementation Order

1. Add upload-mode state and logging guard.
2. Add `/api/v1/device` and `/api/v1/status`.
3. Add archive creation at log close.
4. Add session scanning.
5. Add session list/download endpoints.
6. Add desktop known-host download/import proof of concept.
7. Add acknowledgement persistence.
8. Add optional cleanup endpoint.
9. Add mDNS discovery.
10. Polish UI/menu controls.

This order proves the most important risk early: a real completed session can
be archived on-device, downloaded over HTTP, and imported by the existing
desktop pipeline without changing preprocessing.
