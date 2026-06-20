# Specification: Import Manager

**Created**: 2025-06-20
**Status**: Draft
**Design Docs**: [docs/design/import-manager.md](../../design/import-manager.md)

## Scope

**What part of the design is being implemented:**
This spec documents the existing Import Manager system as it currently behaves.
It covers the desktop GUI application, the reusable import engine, the
provisioning system, the Wi-Fi logger acquisition pipeline, the mDNS discovery
layer, the profile/note builders, and the supporting infrastructure (single
instance, tray, startup). All components are already implemented; this spec
captures their actual behavior for future maintenance and enhancement.

**Out of scope for this spec:**
- The BODAQS preprocessing pipeline internals (session loading, signal
  standardization, event detection, metrics) — these are analysis library
  modules, not import manager components.
- The `ArtifactStore` contract and library artifact format — documented
  separately.
- Firmware and logger hardware behavior.
- macOS/Linux packaging (planned, not shipped).

## Design Context

### Relevant Invariants

- **INV-1**: Every config file has a `schema` and `version` field validated on load.
- **INV-2**: Source IDs must be unique within an app config.
- **INV-3**: Library IDs must be unique within an app config.
- **INV-4**: Every managed source must reference a valid `library_id`.
- **INV-5**: A library cannot be removed while sources target it.
- **INV-6**: Processing key (SHA-256) deduplication prevents re-importing the same archive+profiles.
- **INV-7**: Per-library file lock (`import_agent.lock`) with 12h stale timeout.
- **INV-8**: Single-instance lock per app config path (OS-level file locking).
- **INV-9**: Wi-Fi logger `logger_id` must match device response.
- **INV-10**: Wi-Fi session transfer requires upload mode.
- **INV-11**: Archive patterns always include `*.bdq` when `*.zip` is present.
- **INV-12**: Filesystem archives must be settled (≥ `settle_time_s`) before import.
- **INV-13**: Directory deletion guarded against path traversal.
- **INV-14**: Rename changes display name only — IDs/paths/history preserved.
- **INV-15**: Session note auto-attach requires template_path and setup_preset_path.
- **INV-16**: Bike setup preset `template_id` must match session note template.
- **INV-17**: Wi-Fi API responses validated for `schema` and `api_version == 1`.

### Relevant Contracts

- ImportAgentSupervisor: multi-source scan orchestrator
- ImportSourceRunner: per-source scan + import pipeline
- LoggerWifiApiClient: HTTP API v1 client with schema validation
- Logger WiFi Discovery: mDNS + AP fallback
- Provisioning: library/source/workspace lifecycle management
- Profile Builders: bike profile and session note template construction
- ImportAgentManagerWindow: Tkinter GUI with event-queue polling
- ImportAgentWatchService: background daemon thread watch loop
- SingleInstanceLock: OS-level process lock
- ImportAgentTrayIcon: system tray integration
- Windows Startup: registry-based auto-start

### Relevant Failure Modes

- Archive validation/import failures → archive to `failed_dir`, error in state
- Wi-Fi unreachable/not-in-upload-mode → source skipped with status
- Wi-Fi ack/cleanup failures → recorded but don't block import
- data.syn.bike export failure → logged, doesn't block import
- Session note creation failure → blocks import (exception propagates)
- Stale lock → auto-cleared after 12h
- Active lock → `FileExistsError` propagates
- Duplicate processing key → skipped (succeeded or failed)
- Workspace drift → sync prompt on startup

---

## Component Specifications

### ImportAgentSupervisor — `analysis/bodaqs_analysis/import_agent.py`

**Design doc reference:** [Component Contracts → ImportAgentSupervisor](../../design/import-manager.md#importagentsupervisor--analysisbodaqs_analysisimport_agentpy)
**Depends on:** ImportSourceRunner, ImportSourceConfig

#### Interface Signatures

```python
class ImportAgentSupervisor:
    def __init__(self, sources: Sequence[ImportSourceConfig]) -> None: ...
    @classmethod
    def from_paths(cls, paths_or_dirs: Sequence[str | Path]) -> "ImportAgentSupervisor": ...
    def source_ids(self) -> list[str]: ...
    def get_state(self, source_id: str) -> ImportSourceSupervisorState: ...
    def pause_source(self, source_id: str) -> None: ...
    def resume_source(self, source_id: str, *, scan_immediately: bool = True) -> None: ...
    def scan_source_once(
        self, source_id: str, *, now_s: Optional[float] = None,
        include_paused: bool = False,
        progress_callback: Optional[ImportProgressCallback] = None,
        run_description_override: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]: ...
    def scan_all_once(
        self, *, include_paused: bool = False, now_s: Optional[float] = None,
        progress_callback: Optional[ImportProgressCallback] = None,
        run_description_override: Optional[str] = None,
    ) -> Dict[str, Any]: ...
    def scan_due(
        self, *, now_s: Optional[float] = None,
        progress_callback: Optional[ImportProgressCallback] = None,
    ) -> list[Dict[str, Any]]: ...
    def watch(
        self, *, max_loops: Optional[int] = None,
        time_fn: Any = time.time, sleep_fn: Any = time.sleep,
        progress_callback: Optional[ImportProgressCallback] = None,
    ) -> None: ...
    def snapshot(self, *, now_s: Optional[float] = None) -> Dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `sources` | Must not contain duplicate `source_id` | `ValueError("Duplicate import source id: ...")` |
| `source_id` (get_state) | Must exist in supervisor | `KeyError("Unknown import source id: ...")` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `ValueError` | Duplicate source IDs in constructor | `{"source_id": str}` | Fix source configs |
| `KeyError` | Unknown source_id in get_state/pause/resume/scan | `{"source_id": str}` | Check source_ids() |
| Runner exceptions | Propagated from scan_source_once | Varies | Handle or let watch loop catch |

#### Acceptance Criteria

- **AC1:** Given multiple sources, When `scan_all_once()` is called, Then each source is scanned sequentially in source_id order.
- **AC2:** Given a paused source, When `scan_due()` is called, Then the paused source is skipped.
- **AC3:** Given a paused source, When `scan_source_once(include_paused=True)` is called, Then the source is scanned.
- **AC4:** Given `watch()` is running, When no sources are due, Then the loop sleeps for min(next_due_time, 5.0) seconds.
- **AC5:** Given `watch(max_loops=N)`, When N loops complete, Then `watch()` returns.
- **AC6:** Given no sources, When `watch()` is called, Then it returns immediately.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `ImportSourceRunner` | `scan_once(progress_callback, run_description_override)` | `Dict[str, Any]` summary | Propagates to caller |
| `ImportSourceRunner` | `source.poll_interval_s` | `float` | Used for next_due_s calculation |

#### Performance Constraints

| Metric | Target | How verified |
|--------|--------|--------------|
| Scan interval | ≥ `poll_interval_s` per source | Code inspection |
| Watch sleep cap | ≤ 5.0s | Code inspection |

---

### ImportSourceRunner — `analysis/bodaqs_analysis/import_agent.py`

**Design doc reference:** [Component Contracts → ImportSourceRunner](../../design/import-manager.md#importsourcerunner--analysisbodaqs_analysisimport_agentpy)
**Depends on:** ImportAgentState, ImportAgentLock, ArtifactStore, LoggerWifiApiClient, Logger WiFi Discovery, preprocess_session, session_archive, session_notes

#### Interface Signatures

```python
class ImportSourceRunner:
    def __init__(
        self, source: ImportSourceConfig, *,
        store: Optional[ArtifactStore] = None,
        state_path: Optional[Path] = None,
    ) -> None: ...
    def validate(self) -> tuple[list[str], list[str]]: ...
    def ensure_runtime_dirs(self) -> None: ...
    def scan_once(
        self, *,
        progress_callback: Optional[ImportProgressCallback] = None,
        run_description_override: Optional[str] = None,
    ) -> Dict[str, Any]: ...
    def import_candidate(
        self, candidate: ImportArchiveCandidate, *,
        batch: Optional[ImportRunBatch] = None,
    ) -> Dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `source_id` | Must be non-empty | `ValueError` |
| `source_type` | Must be `filesystem_archive` or `logger_wifi` | `ValueError` |
| `logger_wifi` | Required when `source_type == logger_wifi` | `ValueError` |
| `archive_patterns` | Must be non-empty | `ValueError` |
| `max_archives_per_scan` | Must be > 0 when provided | `ValueError` |
| `session_note.attach_on_import` | Requires `template_path` and `setup_preset_path` | `ValueError` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `FileExistsError` | Library lock held by another process | Lock file path | Retry or wait |
| `FileNotFoundError` | Source config not found | Config path | Create config |
| `ValueError` | Config schema/version mismatch | Expected vs actual | Fix config |
| `LoggerWifiApiError` | Wi-Fi API failure | HTTP status, error code | Check logger connectivity |

#### Acceptance Criteria

- **AC1:** Given an archive in inbox that is not settled, When `scan_once()` is called, Then the archive is deferred (added to `deferred_unsettled`).
- **AC2:** Given a settled archive with a new processing key, When `scan_once()` is called, Then the archive is imported, moved to `done_dir`, and a success record is stored in state.
- **AC3:** Given an archive with a processing key that already succeeded, When `scan_once()` is called (without `force_reprocess`), Then the archive is moved to `done_dir` and skipped.
- **AC4:** Given an archive with a processing key that previously failed, When `scan_once()` is called, Then the archive is moved to `failed_dir` and skipped.
- **AC5:** Given an import failure, When `import_candidate()` raises, Then partial session/run directories are cleaned up and the archive is moved to `failed_dir`.
- **AC6:** Given a Wi-Fi source with `base_url=None`, When `scan_once()` is called, Then mDNS discovery is attempted before acquisition.
- **AC7:** Given a Wi-Fi source where the logger is not in upload mode, When `scan_once()` is called, Then no sessions are downloaded and status is `waiting_upload_mode`.
- **AC8:** Given a successful Wi-Fi import, When postprocess runs, Then `ack_session()` is called; if `cleanup_mode != none`, `cleanup_session()` is also called.
- **AC9:** Given a Wi-Fi ack failure, When postprocess runs, Then the import is still marked succeeded and the error is recorded as `remote_postprocess_error`.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `ImportAgentLock` | `acquire()` / `release()` (context manager) | Lock held | `FileExistsError` propagates |
| `preprocess_session()` | `preprocess_session(input_path, preprocess_config, ...)` | `{"session", "events", "metrics"}` | Exception propagates, import fails |
| `ArtifactStore` | `save_session_artifacts()`, `write_run_manifest()`, etc. | Artifacts written | Exception propagates |
| `LoggerWifiApiClient` | `get_device()`, `get_status()`, `list_sessions()`, `download_*()` | API responses | `LoggerWifiApiError` caught, recorded |
| `discover_single_logger_wifi_source()` | Discovery with logger_id | `Optional[LoggerWifiDiscoveryResult]` | Discovery errors caught, recorded |
| `SessionNoteStore` | `create_note_from_template()`, `update_note()`, `save_note()` | Saved note | Exception propagates, import fails |

#### Performance Constraints

| Metric | Target | How verified |
|--------|--------|--------------|
| Settle time | ≥ `settle_time_s` (default 15s) for filesystem archives | Code inspection |
| Max archives per scan | `max_archives_per_scan` if set | Code inspection |
| SHA-256 chunk size | 1MB | Code inspection |

---

### LoggerWifiApiClient — `analysis/bodaqs_analysis/import_agent_logger_wifi.py`

**Design doc reference:** [Component Contracts → LoggerWifiApiClient](../../design/import-manager.md#loggerwifiapiclient--analysisbodaqs_analysisimport_agent_logger_wifipy)
**Depends on:** import_agent_sources (normalization), io_bdq (BDQ validation)

#### Interface Signatures

```python
@dataclass(frozen=True)
class LoggerWifiApiClient:
    base_url: str
    request_timeout_s: float = 5.0
    download_timeout_s: float = 60.0

    def get_device(self) -> dict[str, Any]: ...
    def get_status(self) -> dict[str, Any]: ...
    def enter_upload_mode(self) -> dict[str, Any]: ...
    def exit_upload_mode(self) -> dict[str, Any]: ...
    def list_sessions(self) -> list[dict[str, Any]]: ...
    def download_archive_to_part(self, session_id: str, target_path: str | Path, *, chunk_size: int = 262144) -> Path: ...
    def download_bdq_to_part(self, session_id: str, target_path: str | Path, *, chunk_size: int = 262144) -> Path: ...
    def ack_session(self, *, session_id: str, status: str = "imported", library_id: Optional[str] = None, run_id: Optional[str] = None, imported_at: Optional[str] = None) -> dict[str, Any]: ...
    def cleanup_session(self, *, session_id: str, mode: str = "none") -> dict[str, Any]: ...
    def move_session_to_uploaded(self, *, session_id: str) -> dict[str, Any]: ...
    def delete_session(self, *, session_id: str) -> dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `base_url` | Must be non-empty absolute http(s) URL | `ValueError` |
| `request_timeout_s` | Must be > 0 | `ValueError` |
| `download_timeout_s` | Must be > 0 | `ValueError` |
| `session_id` (download) | Must be non-empty | `ValueError` |
| `chunk_size` (download) | Must be > 0 | `ValueError` |
| `mode` (cleanup) | Must be one of: none, move_to_uploaded, delete | `ValueError` |
| `mode` (cleanup) | `none` raises (no API call) | `ValueError` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `LoggerWifiApiError` | HTTP error response | `status_code`, `error`, `response_body` | Check logger state |
| `LoggerWifiApiError` | Connection failure | `error="connection_failed"` | Check network/logger |
| `LoggerWifiApiError` | Invalid JSON response | `error="invalid_json"` | Check firmware version |
| `LoggerWifiApiError` | Unsupported api_version | `error` message | Check firmware version |
| `LoggerWifiApiError` | Unexpected schema | `error` message | Check firmware version |
| `LoggerWifiApiError` | Download incomplete | `error="download_incomplete"` | Retry download |
| `LoggerWifiApiError` | Invalid archive | `error="invalid_archive"` | Check session data |
| `LoggerWifiApiError` | Invalid BDQ | `error="invalid_bdq"` | Check session data |

#### Acceptance Criteria

- **AC1:** Given a valid base_url, When `get_device()` is called, Then the response schema must be `bodaqs.logger.device` and `logger_id` must be non-empty.
- **AC2:** Given a session list response, When `list_sessions()` is called, Then each entry must have a non-empty `session_id`.
- **AC3:** Given a download, When Content-Length is present and doesn't match bytes written, Then `LoggerWifiApiError` with `error="download_incomplete"` is raised.
- **AC4:** Given a ZIP download, When the file is not a valid ZIP, Then `LoggerWifiApiError` with `error="invalid_archive"` is raised.
- **AC5:** Given a BDQ download, When the file has no metadata/channel_schema/samples, Then `LoggerWifiApiError` with `error="invalid_bdq"` is raised.
- **AC6:** Given a download, When it completes, Then the `.part` file is atomically replaced to the target path via `os.replace()`.
- **AC7:** Given `cleanup_session(mode="none")`, When called, Then `ValueError` is raised (no API call made).
- **AC8:** Given an HTTP error, When the response body is JSON, Then the `error` and `message` fields are extracted into `LoggerWifiApiError`.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `urllib.request.urlopen` | HTTP request | Response object | `HTTPError`/`URLError` caught |
| `zipfile.ZipFile` | ZIP validation | `testzip()` returns None | `BadZipFile` caught |
| `read_bdq()` | BDQ validation | `BdqReadResult` with metadata/samples | Exception caught |

---

### Logger WiFi Discovery — `analysis/bodaqs_analysis/import_agent_logger_wifi_discovery.py`

**Design doc reference:** [Component Contracts → Logger WiFi Discovery](../../design/import-manager.md#logger-wifi-discovery--analysisbodaqs_analysisimport_agent_logger_wifi_discoverypy)
**Depends on:** LoggerWifiApiClient, zeroconf (optional)

#### Interface Signatures

```python
@dataclass(frozen=True)
class LoggerWifiDiscoveryResult:
    service_name: str
    base_url: str
    addresses: tuple[str, ...]
    port: int
    logger_id: Optional[str] = None
    display_name: Optional[str] = None
    hostname: Optional[str] = None
    api_version: Optional[int] = None
    upload_mode: Optional[bool] = None
    properties: Mapping[str, str] | None = None

def discover_logger_wifi_sources(
    *, logger_id: Optional[str] = None, timeout_s: float = 3.0,
    service_type: str = "_bodaqs-logger._tcp.local.",
    include_default_ap: bool = False,
    default_ap_base_url: str = "http://192.168.4.1",
    default_ap_timeout_s: float = 1.0,
) -> list[LoggerWifiDiscoveryResult]: ...

def discover_single_logger_wifi_source(
    *, logger_id: str, timeout_s: float = 3.0,
    service_type: str = "_bodaqs-logger._tcp.local.",
    include_default_ap: bool = False,
    default_ap_base_url: str = "http://192.168.4.1",
    default_ap_timeout_s: float = 1.0,
) -> Optional[LoggerWifiDiscoveryResult]: ...

def probe_logger_wifi_base_url(
    base_url: str, *, logger_id: Optional[str] = None,
    request_timeout_s: float = 1.0, service_name: str = "direct",
) -> Optional[LoggerWifiDiscoveryResult]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `timeout_s` | Must be > 0 | `ValueError` |
| `logger_id` (discover_single) | Must be non-empty | `ValueError` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `LoggerWifiDiscoveryUnavailable` | `zeroconf` not installed and AP fallback disabled | Message string | Install zeroconf or enable AP fallback |
| `LoggerWifiDiscoveryError` | Multiple loggers with same ID found | Count, logger_id | Ensure unique logger IDs |
| `LoggerWifiDiscoveryUnavailable` | `zeroconf` not installed, AP fallback enabled, but AP probe also fails | Message string | Install zeroconf or check logger connectivity |

#### Acceptance Criteria

- **AC1:** Given zeroconf is available, When `discover_logger_wifi_sources(timeout_s=3.0)` is called, Then mDNS browsing runs for 3 seconds and returns discovered loggers sorted by (logger_id, base_url).
- **AC2:** Given a `logger_id` filter, When discovery is called, Then only results matching that `logger_id` are returned.
- **AC3:** Given `include_default_ap=True` and no mDNS results, When discovery is called, Then `http://192.168.4.1` is probed as fallback.
- **AC4:** Given `include_default_ap=True` and zeroconf unavailable, When discovery is called, Then only the AP probe is attempted.
- **AC5:** Given `discover_single_logger_wifi_source()` finds 2+ matches, When called, Then `LoggerWifiDiscoveryError` is raised.
- **AC6:** Given a discovery result, When IPv4 and IPv6 addresses are available, Then IPv4 is preferred for the base_url.
- **AC7:** Given `probe_logger_wifi_base_url()` with a `logger_id` that doesn't match the device, When called, Then `None` is returned.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `zeroconf.ServiceBrowser` | mDNS browse | Service info via listener | `ImportError` → `LoggerWifiDiscoveryUnavailable` |
| `LoggerWifiApiClient` | `get_device()`, `get_status()` | Device/status dicts | All exceptions caught, returns `None` |

---

### Provisioning — `import-manager/bodaqs_import_manager/import_agent_provisioning.py`

**Design doc reference:** [Component Contracts → Provisioning](../../design/import-manager.md#provisioning--import-managerbodaqs_import_managerimport_agent_provisioningpy)
**Depends on:** bodaqs_analysis (bike_profile, preprocess_profile, schema, session_notes, session_note_presets, import_agent, import_agent_sources)

#### Interface Signatures

```python
# Key types
@dataclass(frozen=True)
class ImportAgentAppConfig:
    sources_root: Path
    libraries_root: Path
    libraries: tuple[ImportAgentLibraryConfig, ...]
    sources: tuple[ImportAgentManagedSourceConfig, ...]
    auto_start: bool

@dataclass(frozen=True)
class ProvisionedImportAgentLibrary: ...

@dataclass(frozen=True)
class ProvisionedImportAgentSource: ...

@dataclass(frozen=True)
class ProvisionedImportAgentAppSetup: ...

# Key functions
def provision_import_agent_library(...) -> ProvisionedImportAgentLibrary: ...
def provision_import_agent_source(...) -> ProvisionedImportAgentSource: ...
def provision_import_agent_app_setup(...) -> ProvisionedImportAgentAppSetup: ...
def provision_import_agent_library_for_app(...) -> tuple[ImportAgentAppConfig, ProvisionedImportAgentLibrary]: ...
def provision_import_agent_source_for_app(...) -> tuple[ImportAgentAppConfig, ProvisionedImportAgentSource]: ...
def load_import_agent_app_config(path: str | Path) -> ImportAgentAppConfig: ...
def save_import_agent_app_config(config, path, *, overwrite=True) -> Path: ...
def validate_import_agent_app_config(config) -> None: ...
def discover_import_agent_libraries(libraries_root) -> list[ImportAgentLibraryConfig]: ...
def discover_import_agent_sources(sources_root, *, known_library_ids=None) -> list[ImportAgentManagedSourceConfig]: ...
def adopt_import_agent_existing_workspace(...) -> AdoptedImportAgentWorkspace: ...
def check_import_agent_workspace_sync(config) -> ImportAgentWorkspaceSyncReport: ...
def sync_import_agent_workspace_from_roots(app_config_path) -> SyncedImportAgentWorkspace: ...
def update_import_agent_source_enabled(app_config_path, *, source_id, enabled) -> ImportAgentAppConfig: ...
def update_import_agent_source_library(app_config_path, *, source_id, library_id) -> ImportAgentAppConfig: ...
def update_import_agent_source_display_name(app_config_path, *, source_id, display_name) -> ImportAgentAppConfig: ...
def update_import_agent_library_display_name(app_config_path, *, library_id, display_name) -> ImportAgentAppConfig: ...
def update_import_agent_source_logger_wifi(app_config_path, *, source_id, logger_wifi) -> ImportAgentAppConfig: ...
def update_import_agent_source_session_naming(...) -> ImportAgentAppConfig: ...
def update_import_agent_source_session_note_attach_enabled(...) -> ImportAgentAppConfig: ...
def update_import_agent_source_force_reprocess_enabled(...) -> ImportAgentAppConfig: ...
def update_import_agent_source_bike_profile(...) -> ImportAgentAppConfig: ...
def update_import_agent_source_preprocess_profile(...) -> ImportAgentAppConfig: ...
def update_import_agent_library_data_syn_bike_export_enabled(...) -> ImportAgentAppConfig: ...
def update_import_agent_app_auto_start(app_config_path, *, enabled) -> ImportAgentAppConfig: ...
def remove_import_agent_source(app_config_path, *, source_id, delete_files=False) -> ImportAgentAppConfig: ...
def remove_import_agent_library(app_config_path, *, library_id, delete_files=False) -> ImportAgentAppConfig: ...
def load_managed_import_source_configs(config, *, enabled_only=False) -> list[Any]: ...
def managed_import_agent_source_roots(config, *, enabled_only=False) -> list[Path]: ...
def default_import_agent_app_config_dir(...) -> Path: ...
def default_import_agent_app_config_path(...) -> Path: ...
def runtime_import_agent_app_config_path(...) -> Path: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `library_id` | Must be non-empty | `ValueError` |
| `display_name` (library/source) | Must be non-empty | `ValueError` |
| `source_id` | Must be non-empty | `ValueError` |
| `library_id` (source) | Must exist in libraries | `ValueError` |
| `source_type` | Must be `filesystem_archive` or `logger_wifi` | `ValueError` |
| `logger_wifi` | Required for `logger_wifi` type, forbidden for `filesystem_archive` | `ValueError` |
| `data_syn_bike_export_enabled` | Must be boolean | `ValueError` |
| `attach_session_note_on_import` | Must be boolean | `ValueError` |
| `force_reprocess` | Must be boolean | `ValueError` |
| `enabled` | Must be boolean | `ValueError` |
| `auto_start` | Must be boolean | `ValueError` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `FileExistsError` | Library/source dir exists and not empty, `overwrite=False` | Path | Use overwrite or choose different name |
| `ValueError` | Unknown source_id/library_id in update functions | ID | Check app config |
| `ValueError` | Library removal with linked sources | Source ID list | Remove sources first |
| `ValueError` | Deletion outside managed root | Path | Check path |
| `FileNotFoundError` | Libraries/sources root doesn't exist | Path | Create root first |

#### Acceptance Criteria

- **AC1:** Given a new library, When `provision_import_agent_library()` is called, Then the full directory structure is created (runs, library, bike_profiles, preprocess_profiles, event_schemas) and default assets are seeded.
- **AC2:** Given a new source, When `provision_import_agent_source()` is called, Then inbox/done/failed/staging/fit/notes directories are created, default note template and setup preset are written, and `import_source.json` is written with portable relative paths.
- **AC3:** Given an existing app config, When `provision_import_agent_source_for_app()` is called, Then the source is added to the config and the config is saved.
- **AC4:** Given a library with linked sources, When `remove_import_agent_library()` is called, Then `ValueError` is raised listing the linked sources.
- **AC5:** Given `delete_files=True`, When `remove_import_agent_source()` is called, Then the source directory is deleted (if inside sources_root).
- **AC6:** Given `delete_files=True`, When `remove_import_agent_library()` is called, Then the library artifacts directory is deleted (if inside libraries_root and is a managed library).
- **AC7:** Given a display name change, When `update_import_agent_library_display_name()` is called, Then both the app config and `library_definition.json` are updated, but the library_id and artifacts_dir are unchanged.
- **AC8:** Given workspace drift, When `check_import_agent_workspace_sync()` is called, Then a report with added/updated/missing libraries and sources is returned.
- **AC9:** Given syncable changes, When `sync_import_agent_workspace_from_roots()` is called, Then the app config is updated with discovered libraries/sources and saved.
- **AC10:** Given `mode="installed"`, When `runtime_import_agent_app_config_path()` is called, Then the platform default app data path is returned.
- **AC11:** Given `mode="portable"` and a writable preferred_dir, When `runtime_import_agent_app_config_path()` is called, Then the preferred_dir path is returned.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `bodaqs_analysis.bike_profile` | `validate_bike_profile()` | None | Exception propagates |
| `bodaqs_analysis.preprocess_profile` | `validate_preprocess_profile()`, `normalize_preprocess_config_keys()` | None | Exception propagates |
| `bodaqs_analysis.schema` | `parse_event_schema()` | Parsed schema | Exception propagates |
| `bodaqs_analysis.session_notes` | `validate_session_note_template()` | None | Exception propagates |
| `bodaqs_analysis.session_note_presets` | `validate_bike_setup_preset()` | None | Exception propagates |
| `bodaqs_analysis.import_agent` | `load_import_source_config()` | `ImportSourceConfig` | Exception propagates |
| `importlib.resources.files` | Asset discovery | Asset entries | Exception propagates |

---

### Profile Builders — `import-manager/bodaqs_import_manager/import_agent_profile_builders.py`

**Design doc reference:** [Component Contracts → Profile Builders](../../design/import-manager.md#profile-builders--import-managerbodaqs_import_managerimport_agent_profile_builderspy)
**Depends on:** bodaqs_analysis (bike_profile, session_notes, session_note_presets)

#### Interface Signatures

```python
def derive_profile_id(display_name: str, *, existing_ids: Sequence[str] = (), fallback: str = "bike-profile", max_length: int = 64) -> str: ...
def bike_profile_form_values(profile: Mapping[str, Any]) -> dict[str, Any]: ...
def apply_bike_profile_form_values(profile: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any]: ...
def build_bike_profile_from_form(values: Mapping[str, Any], *, base_profile: Optional[Mapping[str, Any]] = None) -> dict[str, Any]: ...
def front_head_angle_from_profile(profile: Mapping[str, Any]) -> Optional[float]: ...
def front_vertical_transform_from_profile(profile: Mapping[str, Any]) -> Optional[dict[str, Any]]: ...
def set_front_vertical_wheel_transform(profile: Mapping[str, Any], head_angle_deg: Any) -> dict[str, Any]: ...
def rear_wheel_lut_from_profile(profile: Mapping[str, Any]) -> Optional[dict[str, Any]]: ...
def set_rear_wheel_lut_transform(profile, points, *, input_unit="mm", enabled=True, interpolation="linear", extrapolation="linear") -> dict[str, Any]: ...
def normalize_lut_points(points: Sequence[Mapping[str, Any]]) -> list[dict[str, float]]: ...
def normalize_rear_lut_with_endpoints(points, *, rear_shock_travel_mm, rear_wheel_travel_mm) -> list[dict[str, float]]: ...
def parse_lut_text(text: str) -> list[dict[str, float]]: ...
def format_lut_text(points: Sequence[Mapping[str, Any]]) -> str: ...
def load_session_note_field_catalog() -> list[dict[str, Any]]: ...
def build_session_note_template_from_field_ids(*, field_ids, template_id, template_version="1.0", title, description="", allow_custom_fields=True, custom_field_section="Custom", field_defaults=None, catalog=None) -> dict[str, Any]: ...
def derive_session_note_field_id(display_name: str, *, existing_ids=(), fallback="custom_field", max_length=64) -> str: ...
def build_custom_session_note_field(*, field_name, default_value="", existing_ids=(), section="Custom") -> dict[str, Any]: ...
def coerce_session_note_default_value(field: Mapping[str, Any], value: Any) -> Any: ...
def load_source_bike_profile(source_root) -> tuple[Path, dict[str, Any]]: ...
def save_source_bike_profile(source_root, profile, *, filename=None) -> Path: ...
def load_source_session_note_template(source_root) -> tuple[Path, dict[str, Any]]: ...
def save_source_session_note_template(source_root, template, *, filename=None) -> Path: ...
def load_source_bike_setup_preset(source_root) -> tuple[Path, dict[str, Any]]: ...
def save_source_bike_setup_preset(source_root, preset, *, filename=None) -> Path: ...
def copy_source_bike_profile(from_source_root, to_source_root) -> Path: ...
def copy_source_note_assets(from_source_root, to_source_root) -> tuple[Path, Path]: ...
def save_source_session_note_assets(source_root, template, *, preset=None) -> tuple[Path, Path]: ...
def sync_source_bike_setup_preset(source_root) -> Path: ...
def sync_bike_setup_preset_for_template(preset, template, *, bike_profile=None) -> dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `display_name` (profile) | Must be non-empty | `ValueError` |
| `front_head_angle_deg` | Must be > 0 and < 90, or empty/None | `ValueError` |
| LUT points | ≥ 2 points, strictly increasing inputs, finite values | `ValueError` |
| LUT interior points | Must be between 0 and rear_shock_travel | `ValueError` |
| `interpolation` | Must be `linear` or `nearest` | `ValueError` |
| `extrapolation` | Must be `clamp`, `linear`, or `error` | `ValueError` |
| `field_ids` (template) | Must be non-empty, all must exist in catalog | `ValueError` |
| `field_name` (custom) | Must be non-empty | `ValueError` |
| `max_length` (derive_*_id) | Must be ≥ 8 | `ValueError` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `ValueError` | Invalid head angle | Message | Fix angle value |
| `ValueError` | LUT validation failure | Message | Fix LUT points |
| `ValueError` | Unknown field IDs | Missing IDs list | Use catalog field IDs |
| `ValueError` | Profile validation failure | Message | Fix profile values |
| `FileNotFoundError` | Source bike profile not found | Path | Create profile first |

#### Acceptance Criteria

- **AC1:** Given a display name, When `derive_profile_id()` is called, Then a slug is generated; if it collides with existing IDs, a `-N` suffix is appended.
- **AC2:** Given a head angle of 65°, When `set_front_vertical_wheel_transform()` is called, Then a linear polynomial transform with coefficient `sin(65°)` is added and the front wheel normalization range is derived as `front_fork_travel * sin(65°)`.
- **AC3:** Given a head angle of None/empty, When `set_front_vertical_wheel_transform()` is called, Then the managed front vertical transform and its normalization range are removed.
- **AC4:** Given LUT text with header line and comments, When `parse_lut_text()` is called, Then the header is skipped, comments are skipped, and point pairs are parsed.
- **AC5:** Given LUT interior points, When `normalize_rear_lut_with_endpoints()` is called, Then `(0, 0)` and `(shock_travel, wheel_travel)` endpoints are injected and interior points at 0 or shock_travel are filtered.
- **AC6:** Given a field catalog, When `build_session_note_template_from_field_ids()` is called, Then only selected fields are included, defaults are applied, and the template is validated.
- **AC7:** Given a custom field name with newlines or >80 chars, When `build_custom_session_note_field()` is called, Then `field_type` is `"text"`; otherwise `"string"`.
- **AC8:** Given a source with a bike profile, When `copy_source_bike_profile()` is called, Then the profile is copied to the target source's bike profile path.
- **AC9:** Given a template and preset, When `sync_bike_setup_preset_for_template()` is called, Then the preset's `template_id`/`template_version` are updated, values not in the template are filtered, and the bike display name is set if the `bike` field exists.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `bodaqs_analysis.bike_profile` | `validate_bike_profile()` | None | Exception propagates |
| `bodaqs_analysis.session_notes` | `validate_session_note_template()` | None | Exception propagates |
| `bodaqs_analysis.session_note_presets` | `validate_bike_setup_preset()` | None | Exception propagates |
| `bodaqs_analysis.import_agent` | `load_import_source_config()` | `ImportSourceConfig` | Exception caught, returns None |
| `importlib.resources.files` | Asset loading | JSON payload | Exception propagates |

---

### ImportAgentManagerWindow — `import-manager/bodaqs_import_manager/import_agent_setup.py`

**Design doc reference:** [Component Contracts → ImportAgentManagerWindow](../../design/import-manager.md#importagentmanagerwindow--import-managerbodaqs_import_managerimport_agent_setuppy)
**Depends on:** ImportAgentManagerController, ImportAgentWatchService, ImportAgentTrayIcon, SingleInstanceLock, Provisioning, Profile Builders, LoggerWifiApiClient, Logger WiFi Discovery

#### Interface Signatures

```python
class ImportAgentManagerWindow:
    def __init__(self, args: argparse.Namespace) -> None: ...
    def run(self) -> int: ...

# Module-level
def build_parser() -> argparse.ArgumentParser: ...
def main(argv: Optional[Sequence[str]] = None) -> int: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `app_config` | Must exist or be creatable via provision tab | UI prompts |
| `sources_root` | Must be a valid directory path | UI validation |
| `libraries_root` | Must be a valid directory path | UI validation |
| `source_type` | Must be `filesystem_archive` or `logger_wifi` | UI combo box |
| `logger_wifi` | Required fields when source_type is `logger_wifi` | UI validation |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `messagebox.showerror` | Provisioning failure | Error message | User fixes input |
| `messagebox.showerror` | Watch error | Error message | User restarts watch |
| `messagebox.showerror` | Import-now error | Error message | User checks sources |
| `messagebox.showinfo` | Already running | App config path | User uses existing instance |

#### Acceptance Criteria

- **AC1:** Given no app config exists, When the window opens, Then the Provision tab is selected and the Manager tab shows a "no config" message.
- **AC2:** Given an app config exists, When the window opens, Then the Manager tab shows library and source Treeviews populated from the config.
- **AC3:** Given the window is open, When the user clicks a source row, Then a context menu appears with validation, bike editing, target-library change, details, rename, and removal actions.
- **AC4:** Given the window is open, When the user clicks a library row, Then a context menu appears with rename and details actions.
- **AC5:** Given Wi-Fi sources exist, When the source context menu is opened for a Wi-Fi source, Then Wi-Fi-specific actions appear (check logger, request upload mode, open web UI, edit Wi-Fi settings).
- **AC6:** Given the watch is running, When the user closes the window, Then the window hides to tray (if tray active) or quits.
- **AC7:** Given `--startup-launch` is passed, When the app starts, Then watch starts automatically and the window starts minimized.
- **AC8:** Given the event queue has events, When `_poll_event_queue()` runs (every 250ms), Then all queued events are processed (watch reports, import progress, tray actions).
- **AC9:** Given workspace drift on startup, When `_check_workspace_sync_on_startup()` runs, Then the user is prompted to sync.
- **AC10:** Given the tray "Quit" action, When the event is processed, Then `_quit_application()` stops the watch, stops the tray, and destroys the window.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `ImportAgentManagerController` | Provisioning/update functions | Config objects | `messagebox.showerror` |
| `ImportAgentWatchService` | `start()`, `stop()` | Background thread | `messagebox.showerror` on watch_error |
| `ImportAgentTrayIcon` | `start()`, `stop()`, `refresh()` | Tray icon | Returns `False` if unsupported |
| `ImportAgentSupervisor` | `scan_all_once()`, `snapshot()` | Reports, snapshot | `messagebox.showerror` |
| `LoggerWifiApiClient` | `get_device()`, `get_status()` | Device/status dicts | `messagebox.showerror` |
| `discover_logger_wifi_sources()` | mDNS discovery | `list[LoggerWifiDiscoveryResult]` | `messagebox.showerror` |

---

### ImportAgentWatchService — `import-manager/bodaqs_import_manager/import_agent_setup.py`

**Design doc reference:** [Component Contracts → ImportAgentWatchService](../../design/import-manager.md#importagentwatchservice--import-managerbodaqs_import_managerimport_agent_setuppy)
**Depends on:** ImportAgentSupervisor

#### Interface Signatures

```python
class ImportAgentWatchService:
    def __init__(self, supervisor: ImportAgentSupervisor, event_queue: "queue.Queue[dict[str, Any]]") -> None: ...
    @property
    def running(self) -> bool: ...
    def start(self) -> None: ...
    def stop(self, *, timeout_s: float = 5.0) -> bool: ...
```

#### Acceptance Criteria

- **AC1:** Given `start()` is called, When the thread launches, Then a `watch_started` event is posted.
- **AC2:** Given the watch loop is running, When `scan_due()` returns reports, Then `watch_reports` events with snapshot are posted.
- **AC3:** Given the watch loop is running, When `scan_due()` returns no reports, Then the loop sleeps for min(next_due, 5.0)s or 0.25s if no active sources.
- **AC4:** Given an exception in the run loop, When caught, Then a `watch_error` event is posted followed by `watch_stopped`.
- **AC5:** Given `stop()` is called, When the thread exits within timeout, Then `True` is returned; otherwise `False`.
- **AC6:** Given import progress callbacks, When fired, Then `import_progress` events are posted to the queue.

---

### SingleInstanceLock — `import-manager/bodaqs_import_manager/import_agent_single_instance.py`

**Design doc reference:** [Component Contracts → SingleInstanceLock](../../design/import-manager.md#singleinstancelock--import-managerbodaqs_import_managerimport_agent_single_instancepy)
**Depends on:** None (OS-level locking)

#### Interface Signatures

```python
@dataclass
class SingleInstanceLock:
    app_config_path: Path
    lock_path: Path
    _handle: Optional[BinaryIO] = None

    @classmethod
    def for_app_config(cls, app_config_path: str | Path) -> "SingleInstanceLock": ...
    def acquire(self) -> bool: ...
    def release(self) -> None: ...
    def __enter__(self) -> "SingleInstanceLock": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
```

#### Acceptance Criteria

- **AC1:** Given no lock exists, When `acquire()` is called, Then `True` is returned and a lock file with PID/timestamp is written.
- **AC2:** Given a lock is held by another process, When `acquire()` is called, Then `False` is returned.
- **AC3:** Given a lock is held, When `release()` is called, Then the lock file handle is closed and the lock is released.
- **AC4:** Given `acquire()` returns `False`, When used as context manager, Then `RuntimeError` is raised.
- **AC5:** Given `release()` is called twice, When the second call is made, Then it is a no-op (idempotent).

---

### ImportAgentTrayIcon — `import-manager/bodaqs_import_manager/import_agent_tray.py`

**Design doc reference:** [Component Contracts → ImportAgentTrayIcon](../../design/import-manager.md#importagenttrayicon--import-managerbodaqs_import_managerimport_agent_traypy)
**Depends on:** pystray (optional), Pillow (optional)

#### Interface Signatures

```python
class ImportAgentTrayIcon:
    def __init__(self, *, event_queue: "queue.Queue[dict[str, Any]]", status_supplier: Callable[[], dict[str, Any]], title: str = "BODAQS Import Manager") -> None: ...
    @property
    def started(self) -> bool: ...
    def start(self) -> bool: ...
    def stop(self) -> None: ...
    def refresh(self) -> None: ...
```

#### Acceptance Criteria

- **AC1:** Given Windows with pystray and Pillow, When `start()` is called, Then the tray icon is created and run detached.
- **AC2:** Given non-Windows or missing dependencies, When `start()` is called, Then `False` is returned.
- **AC3:** Given the tray icon is active, When `refresh()` is called, Then the title is updated from `status_supplier()` and the menu is updated.
- **AC4:** Given a menu item is clicked, When the callback fires, Then an event is posted to the event queue.
- **AC5:** Given the tray icon asset is missing, When `load_import_agent_tray_image()` is called, Then a procedurally generated image is returned as fallback.

---

### Windows Startup — `import-manager/bodaqs_import_manager/import_agent_startup.py`

**Design doc reference:** [Component Contracts → Windows Startup](../../design/import-manager.md#windows-startup--import-managerbodaqs_import_managerimport_agent_startuppy)
**Depends on:** winreg (Windows only)

#### Interface Signatures

```python
def windows_startup_supported(*, platform: Optional[str] = None) -> bool: ...
def build_windows_startup_command(argv: Sequence[str | Path]) -> str: ...
def read_windows_startup_registration(*, value_name: str = WINDOWS_STARTUP_VALUE_NAME, ...) -> Optional[str]: ...
def sync_windows_startup_registration(*, enabled: bool, command: Optional[str] = None, ...) -> Optional[str]: ...
```

#### Acceptance Criteria

- **AC1:** Given Windows, When `sync_windows_startup_registration(enabled=True, command="...")` is called, Then the registry Run key is set with value name `"BODAQS Import Manager"`.
- **AC2:** Given the legacy value name `"BODAQS Import Agent"` exists, When sync is called, Then the legacy value is deleted.
- **AC3:** Given `enabled=False`, When sync is called, Then both the current and legacy value names are deleted.
- **AC4:** Given non-Windows, When any function is called, Then `windows_startup_supported()` returns `False` and other functions return `None`.
- **AC5:** Given `enabled=True` and empty command, When sync is called, Then `ValueError` is raised.

---

## Implementation Approach

### High-Level Architecture

The system is a three-layer desktop application:

1. **Import Engine** (`analysis/bodaqs_analysis/import_agent*.py`): Reusable
   Python modules for source management, scanning, importing, and Wi-Fi
   acquisition. The core orchestrator is `ImportAgentSupervisor` which manages
   multiple `ImportSourceRunner` instances.

2. **Desktop Shell** (`import-manager/bodaqs_import_manager/`): Tkinter GUI
   (`ImportAgentManagerWindow`), background watch service
   (`ImportAgentWatchService`), system tray (`ImportAgentTrayIcon`), and
   provisioning utilities. The GUI communicates with the engine via the
   controller and event queue.

3. **Installer/Provisioner**: Inno Setup installer for Windows, in-app
   first-run provisioning flow. The provisioning module creates the full
   directory structure and seeds default assets.

The shim pattern in `analysis/bodaqs_analysis/` allows the engine modules to be
imported from either the analysis package or the desktop app package, with
`_ensure_import_manager_path()` bridging the `sys.path` gap.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| GUI framework | Tkinter + ttk | Bundled with Python, no extra dependency for basic GUI; tksheet for tables |
| Tray library | pystray + Pillow | Lightweight, cross-platform potential; currently Windows-only |
| mDNS library | zeroconf (optional) | Not always available; AP fallback for default logger address |
| Config format | JSON with schema/version | Human-readable, forward-compatible |
| Path storage | POSIX relative in source configs | Portable across platforms |
| Lock mechanism | File-based (O_CREAT\|O_EXCL) | Simple, cross-platform, stale detection |
| Single instance | OS file locking (msvcrt/fcntl) | Reliable per-process locking |
| Watch loop | In-process daemon thread | Single process, no IPC needed |
| Import pipeline | Reuses bodaqs_analysis.pipeline | No duplication of preprocessing logic |

### Research

- The BODAQS Wi-Fi Upload API v1 is documented in the firmware and uses JSON
  responses with `schema` and `api_version` fields.
- mDNS service type is `_bodaqs-logger._tcp.local.`.
- Default logger AP address is `http://192.168.4.1` (ESP32 soft AP default).
- The `data.syn.bike` format is an external tool format; exports are
  best-effort convenience, not canonical artifacts.

### Alternatives Considered

| Alternative | Why not chosen |
|-------------|----------------|
| PySide6 for GUI | Larger bundle; Tkinter is sufficient for the current UI complexity |
| Web UI split architecture | More complex; would require a local server |
| One process per source | More lock contention, harder auto-start, more complex status surface |
| SQLite for state | JSON files are simpler, human-readable, and sufficient for the current scale |
| Cloud-based config sync | System is local-first by design |

## Dependencies

### Design Dependencies
- [docs/design/import-manager.md](../../design/import-manager.md) — this spec's design doc

### Spec Dependencies
- None — this is a backfill of existing code

### Package Dependencies
- `bodaqs_analysis` — preprocessing pipeline, artifact store, bike profiles, session notes, event schemas
- `tkinter` / `ttk` — GUI framework (bundled with Python)
- `tksheet` — Treeview-like table widget (optional, checked at import)
- `pystray` — system tray icon (optional, checked at import)
- `Pillow` (PIL) — image handling for tray icon (optional, checked at import)
- `zeroconf` — mDNS discovery (optional, checked at import)
- `pandas` — DataFrame operations (via bodaqs_analysis)
- `numpy`, `scipy` — numerical operations (via bodaqs_analysis)
- `winreg` — Windows registry (Windows only, imported lazily)
- `msvcrt` — Windows file locking (Windows only, imported lazily)
- `fcntl` — Unix file locking (Unix only, imported lazily)

## Open Questions

| # | Question | Blocks | Resolution |
|---|----------|--------|------------|
| 1 | `include_events`/`include_metrics` hardcoded to True — intentional? | None | UNRESOLVED (OQ-1) |
| 2 | `require_upload_mode` always True — intentional? | None | UNRESOLVED (OQ-2) |
| 3 | `run_tz_label` default mismatch (AWST vs LOCAL) | None | UNRESOLVED (OQ-3) |
| 4 | `raw_scale_mode` silent override — permanent or temporary? | None | UNRESOLVED (OQ-4) |
| 5 | Shim `import *` pattern stability | None | UNRESOLVED (OQ-5) |
| 6 | Watch loop doesn't catch `scan_due` exceptions — intentional? | None | UNRESOLVED |
| 7 | `ImportAgentState` concurrent write safety — intentional? | None | UNRESOLVED |
| 8 | `template_version` match only checked when preset specifies version | None | UNRESOLVED (INV-16) |

## Risks

| Risk | Mitigation |
|------|------------|
| Tkinter not available in some Python distributions | Packaged builds bundle Python with Tk |
| zeroconf blocked by firewall/VPN | AP fallback to `http://192.168.4.1` |
| Large bundle size (pandas, numpy, scipy, Tk) | Accepted for alpha; CLI removed from GUI installer to reduce size |
| Unsigned installer triggers SmartScreen | Documented as known limitation |
| File-based lock can be left stale if process crashes | 12-hour stale timeout with auto-clear |
| JSON state file can lose writes under concurrent access | Library lock prevents concurrent imports to same library; different libraries have separate state files |

## Success Criteria

- [ ] Design doc accurately describes the system architecture and component contracts (maps to all INV-*)
- [ ] Spec captures all component interfaces, validation rules, and acceptance criteria
- [ ] All failure modes from the design doc are covered by acceptance criteria
- [ ] Open questions are documented for future review
- [ ] The spec can serve as a baseline for future enhancements or bug fixes
