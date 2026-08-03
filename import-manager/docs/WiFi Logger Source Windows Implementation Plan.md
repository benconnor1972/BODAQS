# BODAQS Import Manager Wi-Fi Logger Source Implementation Plan

## Status

Windows-first implementation plan. Manual-address Wi-Fi import is implemented.
The first mDNS implementation slice is also implemented on the agent side:
the manager can discover loggers, Wi-Fi sources may omit a fixed address, and
background acquisition can fall back from a remembered/manual address to
mDNS discovery by logger id.

This plan extends the existing BODAQS Import Manager so it can import
sessions directly from a logger over Wi-Fi while preserving the current archive
pipeline and artifact-library contract.

## Product Goal

Let a Windows user run the installed Import Manager, add one or more
Wi-Fi logger sources, and import completed logger sessions into one or more
local BODAQS libraries without using Python, cloud services, a phone, BLE, or a
database server.

The logger must already be reachable over Wi-Fi and must be in explicit upload
mode before session transfer proceeds.

## Non-Goals For The First Windows Version

- Automatic PC Wi-Fi switching into logger AP mode.
- Serial, BLE, cloud, or phone-bridge acquisition.
- Live streaming.
- Forcing upload mode automatically during background polling.
- Changing the existing preprocessing/artifact contract.

## Operating Assumptions

- The logger firmware exposes the Wi-Fi Upload API v1.
- The logger produces one completed archive per session.
- The desktop import agent validates the downloaded archive with the existing
  archive contract before preprocessing.
- Logger identity is the firmware `logger_id`, derived from the logger name.
- Session identity is `logger_id + "__" + session_stem` on the logger side,
  but the local preprocessing session id remains whatever the existing
  pipeline resolves from the metadata.
- A user may configure multiple Wi-Fi logger sources and multiple local
  libraries.
- Multiple sources may target the same library, protected by the existing
  library lock.

## Target User Workflow

1. Install and launch BODAQS Import Manager.
2. Create or select a local BODAQS library.
3. Add a Wi-Fi logger source.
4. Either discover nearby loggers with mDNS or enter a logger address manually.
5. The manager calls `/api/v1/device`, verifies identity, and records the
   logger id.
6. User selects the local bike/settings profile folders seeded by the manager.
7. User puts the logger into upload mode on the logger.
8. The manager polls `/api/v1/status` and `/api/v1/sessions`.
9. New sessions are downloaded to a local `.part` file, validated, imported,
   acknowledged, and optionally cleaned up on the logger.

## Architecture

### Source Types

The import source contract gains an explicit `source_type`.

Supported source types:

- `filesystem_archive`
- `logger_wifi`

Existing source configs without `source_type` are treated as
`filesystem_archive` for backward compatibility.

### Local Handoff Contract

Every acquisition adapter must materialize a local archive file before
preprocessing.

For Wi-Fi sources:

```text
<source_root>/
  import_source.json
  settings/
  bike/
  inbox/
  done/
  failed/
  staging/
  remote/
    downloads/
      <session_id>.zip.part
      <session_id>.zip
```

The first implementation can use the existing `inbox/`, `done/`, `failed/`,
and `staging/` directories. A later cleanup pass may split remote acquisition
state into a dedicated `remote/` tree if that proves clearer.

### Import Agent Layers

1. Source config model.
2. Logger API client.
3. Wi-Fi acquisition adapter.
4. Shared archive import runner.
5. Manager UI and tray status.
6. Packaging/build updates.

The key design rule is that the Wi-Fi adapter should stop after it has
downloaded and validated an archive into local staging/inbox. The existing
runner should still own preprocessing and artifact writing.

## Source Config Shape

Example `logger_wifi` source:

```json
{
  "schema": "bodaqs.import_source",
  "version": 1,
  "source_id": "prototype-e-wifi",
  "source_type": "logger_wifi",
  "description": "Prototype E Wi-Fi logger.",
  "artifacts_dir": "C:/Users/Ben/BODAQS/libraries/default-library",
  "preprocess_profile_path": "settings",
  "bike_profile_path": "bike",
  "fit_dir": "fit",
  "inbox_dir": "inbox",
  "done_dir": "done",
  "failed_dir": "failed",
  "staging_dir": "staging",
  "archive_patterns": ["*.zip"],
  "run_tz_label": "LOCAL",
  "poll_interval_s": 10,
  "settle_time_s": 0,
  "logger_wifi": {
    "logger_id": "Prototype E",
    "base_url": "http://bodaqs-prototype-e.local",
    "request_timeout_s": 5,
    "download_timeout_s": 60,
    "cleanup_mode": "none"
  }
}
```

Wi-Fi logger imports always require upload mode. If `fit_import.enabled` is true in the source
preprocess profile, the agent reads fully copied `.fit` files from `fit_dir`, selects the
largest-overlap match, leaves the original FIT file in place, and continues without FIT enrichment
if parsing or matching fails.

Cleanup modes:

- `none`
- `move_to_uploaded`
- `delete`

Default should be `none`.

With mDNS enabled, `logger_wifi.logger_id` remains the source identity.
`logger_wifi.base_url` becomes a remembered/manual address rather than a
required identity field. The agent may use it first for speed, but must verify
the logger id over HTTP before importing.

## Phase 1. Source Model And Config Scaffold

Purpose:

- make source type explicit before adding network behavior

Tasks:

- Add shared source-type constants.
- Default missing `source_type` to `filesystem_archive`.
- Add `logger_wifi` config parsing and validation.
- Persist `source_type` in app-managed source entries.
- Seed new filesystem sources with `source_type: "filesystem_archive"`.
- Display source type in the manager source list.
- Include source type in supervisor snapshots and import reports.
- Add tests for source-type defaults and Wi-Fi config parsing.

Acceptance:

- all existing filesystem archive tests still pass
- old source configs still load
- a manually-authored `logger_wifi` source config loads and validates
- no network calls are made yet

## Phase 2. Logger API Client

Purpose:

- provide a small, testable client for the firmware Wi-Fi Upload API

Status:

- implemented `bodaqs_analysis.import_agent_logger_wifi`
- uses standard-library HTTP only
- normalizes `base_url`
- parses JSON responses and structured API errors
- implements device/status/upload-mode/session/ack/cleanup calls
- streams archives to `<target>.part`
- validates ZIP integrity before atomic rename to the final target
- fake-server tests cover happy-path API calls, archive download, interrupted
  download, API error responses, invalid JSON, and cleanup safety

Tasks:

- Add `bodaqs_analysis.import_agent_logger_wifi`.
- Implement:
  - `get_device()`
  - `get_status()`
  - `enter_upload_mode()`
  - `exit_upload_mode()`
  - `list_sessions()`
  - `download_archive_to_part()`
  - `ack_session()`
  - `cleanup_session()`
- Use standard-library HTTP first if practical.
- Keep response validation explicit and friendly.
- Normalize `base_url` with no trailing slash.
- Stream downloads to `<target>.part`.
- Rename `.part` only after successful response and ZIP validation.
- Add unit tests with a local fake HTTP server.

Acceptance:

- client can talk to a fake API server
- interrupted/failed downloads leave only `.part`
- invalid JSON and API error responses produce actionable exceptions

## Phase 3. Wi-Fi Acquisition Adapter

Purpose:

- make a `logger_wifi` source acquire new archives into the local pipeline

Status:

- implemented acquisition inside the shared import runner
- calls device/status/sessions before archive discovery
- validates logger identity against configured `logger_id`
- treats upload mode inactive as a non-error waiting state
- downloads ready remote sessions into the local source inbox via `.part`
- validates the downloaded ZIP and archive contract before import
- bypasses local settle delay for Wi-Fi downloads
- reuses the existing archive preprocessing/artifact pipeline
- acknowledges successful local imports with `/api/v1/session/ack`
- optionally calls `/api/v1/session/delete` according to cleanup mode
- records remote session id, logger id, base URL, acknowledgement, and cleanup
  outcome in import-agent state
- fake-server tests cover happy-path import/ack/cleanup, duplicate remote
  suppression, and upload-mode waiting

Tasks:

- Add acquisition step before archive discovery for Wi-Fi sources.
- On each scan:
  - call `/api/v1/device`
  - confirm `logger_id`
  - call `/api/v1/status`
  - skip with warning if upload mode is inactive
  - call `/api/v1/sessions`
  - skip sessions already imported/acknowledged locally
  - download new archives to a local `.part` file
  - validate archive contract
  - expose ready archives in local `inbox/`
- Reuse the existing archive import runner after acquisition.
- After successful import:
  - call `/api/v1/session/ack`
  - optionally call `/api/v1/session/delete` according to cleanup mode
- Record remote session id, logger id, and base URL in local import state.

Acceptance:

- one scan can acquire and import a new session from a fake logger
- duplicate remote sessions are not re-imported
- upload mode inactive is not treated as an import failure
- acknowledgement is sent only after successful local artifact write

## Phase 4. Manager UI For Wi-Fi Sources

Purpose:

- let users configure and operate Wi-Fi sources without JSON editing

Status:

- added a source-type selector to the Provision tab
- added a Wi-Fi logger source panel with logger ID, optional logger address,
  Verify Logger, cleanup mode, and timeouts
- Verify Logger calls `/api/v1/device` and `/api/v1/status`, then stores the
  returned logger ID for source creation
- Create Initial Library + Source and Add Source can now provision
  `logger_wifi` sources
- the Manager source table shows source type and a runtime status column
- added selected-source actions:
  - Check Logger
  - Request Upload Mode
  - Open Logger Web UI
- import/watch reports update the runtime status column for Wi-Fi sources
- Request Upload Mode remains an explicit user action and is not triggered by
  background watch

Tasks:

- Add source type selection in the Add Source flow.
- For `logger_wifi`, show:
  - logger address
  - verify connection button
  - logger id/display name returned by `/api/v1/device`
  - cleanup mode selector
  - request timeout/download timeout advanced fields
- Store verified `logger_id` in `import_source.json`.
- Show source type, reachability, upload mode, session count, and last error in
  the Manager tab.
- Add source action buttons:
  - Check Logger
  - Request Upload Mode
  - Open Logger Web UI
- Keep “Request Upload Mode” explicit; do not run it silently from background
  watch.

Acceptance:

- user can add a Wi-Fi logger source by address
- manager clearly reports upload mode required
- manager can import once when logger is already in upload mode

## Phase 5. Windows Packaging

Purpose:

- ship the new Wi-Fi source support in the existing Windows installer

Status:

- added explicit PyInstaller hidden imports for the Wi-Fi API client and shared
  source-type module in both CLI and manager specs
- confirmed no new third-party dependency is required for Wi-Fi logger HTTP
  support
- documented that Wi-Fi logger checks use outbound HTTP only and should not
  require an inbound Windows Firewall exception
- added regression coverage for an offline Wi-Fi logger source reporting a
  remote error without creating an import failure
- added regression coverage for managed Wi-Fi source config surviving app
  config reload
- rebuilt the Windows PyInstaller bundles and installer payload

Tasks:

- Add any new Python modules to package collection.
- If a new dependency is introduced, update PyInstaller hidden imports and
  build documentation.
- Confirm no Windows firewall prompt is required for outbound-only HTTP.
- Confirm startup/watch mode handles offline Wi-Fi sources quietly.

Acceptance:

- installed manager starts cleanly
- filesystem sources still work
- Wi-Fi source config survives restart
- watch mode can poll an offline Wi-Fi source without noisy modal dialogs

## Phase 6. Bench Testing With Real Logger

Purpose:

- verify the full logger-to-library workflow

Tests:

- AP mode, manual PC connection, address `http://bodaqs-<logger-id>.local`.
- Station mode with manually entered `.local` address.
- Logger not in upload mode.
- Logger enters upload mode while manager is running.
- Interrupted download and retry.
- Repeated import scan after acknowledgement.
- Cleanup mode `none`.
- Cleanup mode `move_to_uploaded`.
- Multiple loggers targeting one central library.
- Two libraries under the same root.

Acceptance:

- no partial local artifacts after failed import
- no logger-side deletion before acknowledgement
- user-facing status explains what to do next

## Later Phases

### mDNS Discovery

Status:

- firmware already advertises `_bodaqs-logger._tcp` in station mode
- firmware already publishes `api`, `logger_id`, `upload_mode`, and `hostname`
  TXT records
- firmware already exposes `mdns_discovery` in `/api/v1/device` capabilities
- agent discovery module implemented with the Python `zeroconf` package
- manager discovery button implemented for the Add Source flow
- background acquisition fallback implemented for missing/stale `base_url`

Purpose:

- remove the need for fixed station-mode IP addresses
- let the manager find the current address for a known logger id
- keep AP-mode and troublesome-network workflows working through manual
  address entry

Design:

- logger id is the stable identity
- mDNS answers "where is that logger right now?"
- `/api/v1/device` remains the authoritative identity check
- discovered addresses are cached as reachability hints, not trusted identity
- AP mode keeps using manual/default address, because the PC must explicitly
  join the logger AP network

Firmware tasks:

- keep advertising service `_bodaqs-logger._tcp.local.` on port 80 in station
  mode only
- keep hostname stable and DNS-safe, derived from `logger_id`
- include TXT records:
  - `api=1`
  - `logger_id=<logger id>`
  - `upload_mode=true|false`
  - `hostname=<advertised hostname>`
- restart or refresh mDNS after:
  - station connection comes online
  - upload mode enters/exits
  - logger id/name changes
  - Wi-Fi disconnect/reconnect
- stop mDNS when:
  - Wi-Fi is disabled
  - logging suspends Wi-Fi
  - AP mode starts
  - sleep/shutdown begins
- keep `/api/v1/device` and `/api/v1/status` hostname/capability fields in
  sync with the mDNS advertisement
- document that mDNS is station-mode discovery only

Agent tasks:

- add a small `zeroconf`-backed discovery module for
  `_bodaqs-logger._tcp.local.`
- parse service addresses, port, server name, and TXT properties
- expose discovery results as:
  - `logger_id`
  - `display_name` when available
  - `base_url`
  - `hostname`
  - `upload_mode`
  - `api_version`
  - raw addresses/properties for diagnostics
- tolerate missing `zeroconf` with a friendly "mDNS support not installed"
  status rather than breaking normal imports
- add `zeroconf` to requirements and PyInstaller hidden imports
- in background acquisition:
  - try remembered/manual `base_url` first if configured
  - if it is missing or unreachable, discover by `logger_id`
  - verify `/api/v1/device.logger_id` before any session call
  - record the resolved address in import state/report
  - do not fail the local import scan if discovery finds nothing
- in the manager:
  - add `Discover Loggers`
  - list discovered loggers with logger id, address, upload mode, and hostname
  - selecting a logger fills logger id and address
  - allow source creation with logger id only when discovery is available
  - keep manual address entry visible as fallback
- add tests for:
  - TXT/address parsing
  - discovery unavailable path
  - acquisition with no configured `base_url` using discovery fallback
  - configured stale address falling back to discovered address
  - duplicate discovered logger ids refusing automatic selection

Acceptance:

- a source can be defined by logger id without a fixed station-mode IP
- manual AP address still works
- stale remembered station IPs do not block import if mDNS finds the logger
- no session is imported unless HTTP identity verification matches the source
  logger id
- offline or blocked mDNS appears as a waiting/not found status, not a modal
  error storm

### Serial Logger Source

Reuse the same source-adapter pattern but acquire archives over serial or
mass-storage style transfer.

### Cloud Storage Source

Normalize cloud-synced archives into the same local handoff contract.

## Key Risks And Resolutions

### Windows mDNS Reliability

Risk:

- mDNS availability varies depending on Bonjour/iTunes/Windows network setup.
- multicast DNS can be blocked by firewall profiles, VPN adapters, guest Wi-Fi,
  router/AP isolation, or VLAN boundaries.

Resolution:

- use the Python `zeroconf` package rather than relying on Bonjour being
  separately installed
- keep manual address and last-known-address fallback
- always verify identity with `/api/v1/device`
- surface "not discovered" as a normal waiting state

### Upload Mode Confusion

Risk:

- background watch looks broken if logger is reachable but not in upload mode.

Resolution:

- treat upload mode inactive as a non-error waiting state and display it
  clearly.

### Duplicate Sessions

Risk:

- the same remote session could be downloaded more than once.

Resolution:

- use remote `session_id`, archive hash, and existing local processing keys.
  Acknowledge only after successful local import.

### Cleanup Safety

Risk:

- deleting logger files too early could lose data.

Resolution:

- default cleanup off. Require successful acknowledgement before cleanup.

### Long Network Operations In UI

Risk:

- HTTP downloads could freeze Tk.

Resolution:

- run checks/import/watch in the existing background service pattern and report
  status through the queue.
