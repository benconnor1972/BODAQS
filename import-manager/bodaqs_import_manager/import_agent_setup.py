from __future__ import annotations

import argparse
import base64
import copy
import ctypes
import math
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from tksheet import Sheet
except Exception:  # pragma: no cover - dependency presence is checked in packaged builds.
    Sheet = None

from bodaqs_analysis.import_agent import ImportAgentSupervisor, load_import_source_config
from bodaqs_analysis.import_agent_logger_wifi import LoggerWifiApiClient
from bodaqs_analysis.import_agent_logger_wifi_discovery import (
    LoggerWifiDiscoveryResult,
    discover_logger_wifi_sources,
    discover_single_logger_wifi_source,
)
from .import_agent_provisioning import (
    IMPORT_AGENT_APP_CONFIG_MODE_AUTO,
    IMPORT_AGENT_APP_CONFIG_MODE_INSTALLED,
    IMPORT_AGENT_APP_CONFIG_MODE_PORTABLE,
    ImportAgentAppConfig,
    ImportAgentWorkspaceSyncReport,
    adopt_import_agent_existing_workspace,
    check_import_agent_workspace_sync,
    load_import_agent_app_config,
    load_managed_import_source_configs,
    managed_import_agent_source_roots,
    provision_import_agent_app_setup,
    provision_import_agent_library_for_app,
    provision_import_agent_source_for_app,
    remove_import_agent_library,
    remove_import_agent_source,
    runtime_import_agent_app_config_path,
    sync_import_agent_workspace_from_roots,
    update_import_agent_app_auto_start,
    update_import_agent_library_data_syn_bike_export_enabled,
    update_import_agent_library_display_name,
    update_import_agent_source_bike_profile,
    update_import_agent_source_library,
    update_import_agent_source_display_name,
    update_import_agent_source_force_reprocess_enabled,
    update_import_agent_source_preprocess_profile,
    update_import_agent_source_session_naming,
    update_import_agent_source_session_note_attach_enabled,
    update_import_agent_source_enabled,
    update_import_agent_source_logger_wifi,
    validate_managed_import_sources,
)
from .import_agent_profile_builders import (
    apply_bike_profile_form_values,
    bike_profile_filename,
    bike_profile_form_values,
    build_custom_session_note_field,
    build_session_note_template_from_field_ids,
    copy_source_note_assets,
    derive_profile_id,
    discover_bike_profiles,
    format_lut_text,
    library_bike_profiles_dir,
    load_session_note_field_catalog,
    load_source_bike_setup_preset,
    load_source_bike_profile,
    load_source_session_note_template,
    normalize_lut_points,
    normalize_rear_lut_with_endpoints,
    parse_lut_text,
    rear_wheel_lut_from_profile,
    save_bike_profile_path,
    save_source_bike_profile,
    save_source_session_note_assets,
    set_rear_wheel_lut_transform,
    sync_source_bike_setup_preset,
)
from .import_agent_single_instance import SingleInstanceLock
from bodaqs_analysis.import_agent_sources import (
    LOGGER_WIFI_CLEANUP_DELETE,
    LOGGER_WIFI_CLEANUP_MOVE_TO_UPLOADED,
    LOGGER_WIFI_CLEANUP_NONE,
    SOURCE_TYPE_FILESYSTEM_ARCHIVE,
    SOURCE_TYPE_LOGGER_WIFI,
)
from .import_agent_startup import (
    build_windows_startup_command,
    sync_windows_startup_registration,
    windows_startup_supported,
)
from .import_agent_tray import ImportAgentTrayIcon, tray_supported

try:
    from bodaqs_import_manager_build_version import APP_VERSION as _PACKAGED_APP_VERSION
except Exception:
    _PACKAGED_APP_VERSION = ""


_ASSET_PACKAGE = "bodaqs_import_manager.import_agent_assets"
_APP_DISPLAY_NAME = "BODAQS Import Manager"
_WINDOW_ICON_FILENAME = "app_icon.png"
_WINDOW_ICON_ICO_FILENAME = "app_icon.ico"
_WINDOWS_APP_USER_MODEL_ID = "BODAQS.ImportAgent.Manager"
_LIBRARY_SERVICE_HOST = "127.0.0.1"
_LIBRARY_SERVICE_PORT = 8765
_LIBRARY_SERVICE_STARTUP_TIMEOUT_S = 12.0
_SOURCE_TYPE_LABELS = {
    SOURCE_TYPE_FILESYSTEM_ARCHIVE: "Local archive folder",
    SOURCE_TYPE_LOGGER_WIFI: "Wi-Fi logger",
}
_SOURCE_TYPE_BY_LABEL = {label: value for value, label in _SOURCE_TYPE_LABELS.items()}
_LOGGER_WIFI_CLEANUP_LABELS = {
    LOGGER_WIFI_CLEANUP_NONE: "Keep files on logger",
    LOGGER_WIFI_CLEANUP_MOVE_TO_UPLOADED: "Move to uploaded",
    LOGGER_WIFI_CLEANUP_DELETE: "Delete from logger",
}
_LOGGER_WIFI_CLEANUP_BY_LABEL = {
    label: value for value, label in _LOGGER_WIFI_CLEANUP_LABELS.items()
}
_SOURCE_ENABLED_CHECKED = "☑"
_SOURCE_ENABLED_UNCHECKED = "☐"


def _app_window_title() -> str:
    version = str(_PACKAGED_APP_VERSION or "").strip()
    return f"{_APP_DISPLAY_NAME} {version}" if version else _APP_DISPLAY_NAME


def _default_workspace_root() -> Path:
    return Path.home() / "BODAQS"


def _default_sources_root() -> Path:
    return _default_workspace_root() / "sources"


def _default_libraries_root() -> Path:
    return _default_workspace_root() / "libraries"


def _default_app_config_path(*, mode: str = IMPORT_AGENT_APP_CONFIG_MODE_AUTO) -> Path:
    preferred_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    return runtime_import_agent_app_config_path(preferred_dir=preferred_dir, mode=mode)


def _aggregate_reports(reports: Sequence[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "seen": 0,
        "deferred_unsettled": 0,
        "skipped_succeeded": 0,
        "skipped_failed": 0,
        "imported": 0,
        "failed": 0,
    }
    for report in reports:
        totals["seen"] += int(report.get("seen", 0))
        for key in ("deferred_unsettled", "skipped_succeeded", "skipped_failed", "imported", "failed"):
            totals[key] += len(report.get(key, []))
    return totals


def _apply_windows_app_user_model_id() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_WINDOWS_APP_USER_MODEL_ID)
    except Exception:
        pass


def _show_already_running_message(app_config_path: str | Path) -> None:
    message = (
        f"{_APP_DISPLAY_NAME} is already running for this app configuration.\n\n"
        f"{Path(app_config_path).expanduser().resolve()}\n\n"
        "Use the existing window or tray icon, or close the existing manager before starting another one."
    )
    try:
        _apply_windows_app_user_model_id()
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(_APP_DISPLAY_NAME, message, parent=root)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bodaqs-import-setup",
        description="Create or manage a local BODAQS import manager desktop setup.",
    )
    parser.add_argument("--app-config", default="", help=argparse.SUPPRESS)
    parser.add_argument(
        "--app-config-mode",
        choices=(
            IMPORT_AGENT_APP_CONFIG_MODE_AUTO,
            IMPORT_AGENT_APP_CONFIG_MODE_PORTABLE,
            IMPORT_AGENT_APP_CONFIG_MODE_INSTALLED,
        ),
        default=IMPORT_AGENT_APP_CONFIG_MODE_AUTO,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--sources-root", default=str(_default_sources_root()))
    parser.add_argument("--libraries-root", default=str(_default_libraries_root()))
    parser.add_argument("--library-name", default="Default Library")
    parser.add_argument("--source-name", default="Default Source")
    parser.add_argument("--run-tz-label", default="LOCAL")
    parser.add_argument("--data-syn-bike-export", action="store_true")
    parser.add_argument("--attach-session-note", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--auto-start", action="store_true")
    parser.add_argument("--startup-launch", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--start-watch", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--start-minimized", action="store_true", help=argparse.SUPPRESS)
    return parser


class ImportAgentManagerController:
    def __init__(self, app_config_path: str | Path) -> None:
        self.app_config_path = Path(app_config_path).expanduser().resolve()
        self.app_config: Optional[ImportAgentAppConfig] = None
        self.reload()

    def reload(self) -> Optional[ImportAgentAppConfig]:
        self.app_config = load_import_agent_app_config(self.app_config_path) if self.app_config_path.exists() else None
        return self.app_config

    def require_config(self) -> ImportAgentAppConfig:
        if self.app_config is None:
            raise ValueError("No managed import-agent app config exists yet. Create the first setup first.")
        return self.app_config

    def has_config(self) -> bool:
        return self.app_config is not None

    def create_initial_setup(
        self,
        *,
        sources_root: str,
        libraries_root: str,
        library_display_name: str,
        source_display_name: str,
        source_type: str,
        logger_wifi: Optional[dict[str, Any]],
        run_tz_label: str,
        data_syn_bike_export_enabled: bool,
        attach_session_note_on_import: bool,
        auto_start: bool,
        session_auto_name_enabled: bool = False,
        session_name_base: str = "",
        overwrite: bool = False,
    ) -> Any:
        result = provision_import_agent_app_setup(
            sources_root=sources_root,
            libraries_root=libraries_root,
            library_display_name=library_display_name,
            source_display_name=source_display_name,
            app_config_path=self.app_config_path,
            source_type=source_type,
            logger_wifi=logger_wifi,
            run_tz_label=run_tz_label,
            data_syn_bike_export_enabled=data_syn_bike_export_enabled,
            attach_session_note_on_import=attach_session_note_on_import,
            session_auto_name_enabled=session_auto_name_enabled,
            session_name_base=session_name_base,
            auto_start=auto_start,
            overwrite=overwrite,
        )
        self.app_config = result.app_config
        return result

    def adopt_existing_workspace(
        self,
        *,
        sources_root: str,
        libraries_root: str,
        auto_start: bool,
    ) -> Any:
        result = adopt_import_agent_existing_workspace(
            sources_root=sources_root,
            libraries_root=libraries_root,
            app_config_path=self.app_config_path,
            auto_start=auto_start,
        )
        self.app_config = result.app_config
        return result

    def check_workspace_sync(self) -> ImportAgentWorkspaceSyncReport:
        config = self.require_config()
        return check_import_agent_workspace_sync(config)

    def sync_workspace_from_roots(self) -> Any:
        result = sync_import_agent_workspace_from_roots(self.app_config_path)
        self.app_config = result.app_config
        return result

    def add_library(self, *, display_name: str, data_syn_bike_export_enabled: bool, overwrite: bool) -> Any:
        updated, library = provision_import_agent_library_for_app(
            self.app_config_path,
            display_name=display_name,
            data_syn_bike_export_enabled=data_syn_bike_export_enabled,
            overwrite=overwrite,
        )
        self.app_config = updated
        return library

    def set_library_data_syn_bike_export_enabled(self, library_id: str, enabled: bool) -> ImportAgentAppConfig:
        updated = update_import_agent_library_data_syn_bike_export_enabled(
            self.app_config_path,
            library_id=library_id,
            enabled=enabled,
        )
        self.app_config = updated
        return updated

    def add_source(
        self,
        *,
        library_id: str,
        display_name: str,
        source_type: str,
        logger_wifi: Optional[dict[str, Any]],
        run_tz_label: str,
        attach_session_note_on_import: bool,
        session_auto_name_enabled: bool = False,
        session_name_base: str = "",
        overwrite: bool = False,
    ) -> Any:
        updated, source = provision_import_agent_source_for_app(
            self.app_config_path,
            library_id=library_id,
            display_name=display_name,
            source_type=source_type,
            logger_wifi=logger_wifi,
            run_tz_label=run_tz_label,
            attach_session_note_on_import=attach_session_note_on_import,
            session_auto_name_enabled=session_auto_name_enabled,
            session_name_base=session_name_base,
            overwrite=overwrite,
        )
        self.app_config = updated
        return source

    def set_source_enabled(self, source_id: str, enabled: bool) -> ImportAgentAppConfig:
        updated = update_import_agent_source_enabled(
            self.app_config_path,
            source_id=source_id,
            enabled=enabled,
        )
        self.app_config = updated
        return updated

    def set_source_session_note_attach_enabled(self, source_id: str, enabled: bool) -> ImportAgentAppConfig:
        updated = update_import_agent_source_session_note_attach_enabled(
            self.app_config_path,
            source_id=source_id,
            enabled=enabled,
        )
        self.app_config = updated
        return updated

    def set_source_force_reprocess_enabled(self, source_id: str, enabled: bool) -> ImportAgentAppConfig:
        updated = update_import_agent_source_force_reprocess_enabled(
            self.app_config_path,
            source_id=source_id,
            enabled=enabled,
        )
        self.app_config = updated
        return updated

    def set_source_session_naming(
        self,
        source_id: str,
        *,
        enabled: bool,
        base: str,
        index_start: int = 1,
        index_padding: int = 2,
    ) -> ImportAgentAppConfig:
        updated = update_import_agent_source_session_naming(
            self.app_config_path,
            source_id=source_id,
            enabled=enabled,
            base=base,
            index_start=index_start,
            index_padding=index_padding,
        )
        self.app_config = updated
        return updated

    def set_library_display_name(self, library_id: str, display_name: str) -> ImportAgentAppConfig:
        updated = update_import_agent_library_display_name(
            self.app_config_path,
            library_id=library_id,
            display_name=display_name,
        )
        self.app_config = updated
        return updated

    def set_source_library(self, source_id: str, library_id: str) -> ImportAgentAppConfig:
        updated = update_import_agent_source_library(
            self.app_config_path,
            source_id=source_id,
            library_id=library_id,
        )
        self.app_config = updated
        return updated

    def set_source_bike_profile(self, source_id: str, bike_profile_path: Path) -> ImportAgentAppConfig:
        updated = update_import_agent_source_bike_profile(
            self.app_config_path,
            source_id=source_id,
            bike_profile_path=bike_profile_path,
        )
        self.app_config = updated
        return updated

    def set_source_preprocess_profile(self, source_id: str, preprocess_profile_path: Path) -> ImportAgentAppConfig:
        updated = update_import_agent_source_preprocess_profile(
            self.app_config_path,
            source_id=source_id,
            preprocess_profile_path=preprocess_profile_path,
        )
        self.app_config = updated
        return updated

    def set_source_display_name(self, source_id: str, display_name: str) -> ImportAgentAppConfig:
        updated = update_import_agent_source_display_name(
            self.app_config_path,
            source_id=source_id,
            display_name=display_name,
        )
        self.app_config = updated
        return updated

    def set_source_logger_wifi(self, source_id: str, logger_wifi: dict[str, Any]) -> ImportAgentAppConfig:
        updated = update_import_agent_source_logger_wifi(
            self.app_config_path,
            source_id=source_id,
            logger_wifi=logger_wifi,
        )
        self.app_config = updated
        return updated

    def remove_source(self, source_id: str, *, delete_files: bool = False) -> ImportAgentAppConfig:
        updated = remove_import_agent_source(
            self.app_config_path,
            source_id=source_id,
            delete_files=delete_files,
        )
        self.app_config = updated
        return updated

    def remove_library(self, library_id: str, *, delete_files: bool = False) -> ImportAgentAppConfig:
        updated = remove_import_agent_library(
            self.app_config_path,
            library_id=library_id,
            delete_files=delete_files,
        )
        self.app_config = updated
        return updated

    def set_auto_start(self, enabled: bool) -> ImportAgentAppConfig:
        updated = update_import_agent_app_auto_start(
            self.app_config_path,
            enabled=enabled,
        )
        self.app_config = updated
        return updated

    def managed_source_roots(self, *, enabled_only: bool = False) -> list[Path]:
        return managed_import_agent_source_roots(self.require_config(), enabled_only=enabled_only)

    def validate_sources(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        return validate_managed_import_sources(self.require_config(), enabled_only=enabled_only)

    def make_enabled_supervisor(self) -> ImportAgentSupervisor:
        sources = load_managed_import_source_configs(self.require_config(), enabled_only=True)
        if not sources:
            raise ValueError("No enabled managed sources are available.")
        return ImportAgentSupervisor(sources)

    def import_once(
        self,
        *,
        progress_callback: Optional[Callable[[Mapping[str, Any]], None]] = None,
        run_description_override: Optional[str] = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        supervisor = self.make_enabled_supervisor()
        report = supervisor.scan_all_once(
            progress_callback=progress_callback,
            run_description_override=run_description_override,
        )
        return report, supervisor.snapshot()


class ImportAgentWatchService:
    def __init__(self, supervisor: ImportAgentSupervisor, event_queue: "queue.Queue[dict[str, Any]]") -> None:
        self.supervisor = supervisor
        self.event_queue = event_queue
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="ImportAgentWatchService", daemon=True)
        self._thread.start()

    def stop(self, *, timeout_s: float = 5.0) -> bool:
        if self._thread is None:
            return True
        self._stop_event.set()
        self._thread.join(timeout=max(timeout_s, 0.1))
        stopped = not self._thread.is_alive()
        if stopped:
            self._thread = None
        return stopped

    def _queue_progress(self, progress: Mapping[str, Any]) -> None:
        self.event_queue.put(
            {
                "kind": "import_progress",
                "origin": "watch",
                "progress": dict(progress),
            }
        )

    def _run(self) -> None:
        self.event_queue.put({"kind": "watch_started"})
        try:
            while not self._stop_event.is_set():
                now_s = time.time()
                reports = self.supervisor.scan_due(now_s=now_s, progress_callback=self._queue_progress)
                if reports:
                    self.event_queue.put(
                        {
                            "kind": "watch_reports",
                            "reports": reports,
                            "snapshot": self.supervisor.snapshot(now_s=now_s),
                        }
                    )
                    delay_s = 0.05
                else:
                    active_due_times = [
                        max(float(self.supervisor.get_state(source_id).next_due_s) - now_s, 0.0)
                        for source_id in self.supervisor.source_ids()
                        if not self.supervisor.get_state(source_id).paused
                    ]
                    if not active_due_times:
                        delay_s = 0.25
                    else:
                        delay_s = min(max(0.1, min(active_due_times)), 5.0)
                self._stop_event.wait(delay_s)
        except Exception as exc:
            self.event_queue.put({"kind": "watch_error", "error": str(exc)})
        finally:
            self.event_queue.put({"kind": "watch_stopped", "snapshot": self.supervisor.snapshot()})


class LibraryApiServiceProcess:
    def __init__(
        self,
        *,
        libraries_root: str | Path,
        host: str = _LIBRARY_SERVICE_HOST,
        port: int = _LIBRARY_SERVICE_PORT,
    ) -> None:
        self.libraries_root = Path(libraries_root).expanduser().resolve()
        self.host = host
        self.port = int(port)
        self.process: Optional[subprocess.Popen[Any]] = None
        self.started_by_manager = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}/api/v1/health"

    @property
    def web_url(self) -> str:
        return f"{self.base_url}/"

    def is_running(self) -> bool:
        if self._health_available():
            return True
        if self.process is None:
            return False
        return self.process.poll() is None

    def start(self) -> str:
        if self._health_available():
            return f"Library service already running at {self.base_url}."
        if self.process is not None and self.process.poll() is None:
            return f"Library service is starting at {self.base_url}."

        command, cwd = self._launch_command()
        self.process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_subprocess_creationflags(),
        )
        self.started_by_manager = True
        deadline = time.monotonic() + _LIBRARY_SERVICE_STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._health_available():
                return f"Library service started at {self.base_url}."
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"Library service exited during startup with code {self.process.returncode}."
                )
            time.sleep(0.15)
        raise TimeoutError(f"Timed out waiting for Library service at {self.base_url}.")

    def stop(self, *, timeout_s: float = 5.0) -> bool:
        if self.process is None or self.process.poll() is not None:
            self.process = None
            self.started_by_manager = False
            return True
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return False
        self.process = None
        self.started_by_manager = False
        return True

    def _health_available(self) -> bool:
        try:
            with urllib.request.urlopen(self.health_url, timeout=0.5) as response:
                return 200 <= int(response.status) < 300
        except (OSError, urllib.error.URLError, ValueError):
            return False

    def _launch_command(self) -> tuple[list[str], Path | None]:
        service_exe = _packaged_library_service_exe()
        web_root = _packaged_library_service_web_root()
        if service_exe is not None:
            command = [str(service_exe)]
            cwd = service_exe.parent
        else:
            command = [
                str(Path(sys.executable).resolve()),
                str(_repo_library_service_script()),
            ]
            cwd = _repo_library_service_script().parent
            web_root = _repo_web_app_dist()

        command.extend(
            [
                "--libraries-root",
                str(self.libraries_root),
                "--host",
                self.host,
                "--port",
                str(self.port),
            ]
        )
        if web_root is not None and (web_root / "index.html").is_file():
            command.extend(["--web-root", str(web_root)])
        return command, cwd


def _subprocess_creationflags() -> int:
    if not sys.platform.startswith("win"):
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _packaged_library_service_exe() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    manager_dir = Path(sys.executable).resolve().parent
    candidate = manager_dir.parent / "service" / "bodaqs-library-service.exe"
    return candidate if candidate.is_file() else None


def _packaged_library_service_web_root() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    manager_dir = Path(sys.executable).resolve().parent
    candidate = manager_dir.parent / "service" / "web"
    return candidate if (candidate / "index.html").is_file() else None


def _repo_root_from_manager_module() -> Path:
    return Path(__file__).resolve().parents[2]


def _repo_library_service_script() -> Path:
    return _repo_root_from_manager_module() / "import-manager" / "bodaqs_library_service.py"


def _repo_web_app_dist() -> Path | None:
    candidate = _repo_root_from_manager_module() / "application" / "cohort-workbench-prototype" / "dist"
    return candidate if (candidate / "index.html").is_file() else None


class ImportAgentManagerWindow:
    def __init__(self, args: argparse.Namespace) -> None:
        _apply_windows_app_user_model_id()
        self.root = tk.Tk()
        self._window_icon_image: Optional[tk.PhotoImage] = None
        self._apply_window_icon()
        self.root.title(_app_window_title())
        self.root.geometry("1120x760")
        self.root.minsize(980, 680)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.controller = ImportAgentManagerController(args.app_config)
        self.args = args
        self.event_queue: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.watch_service: Optional[ImportAgentWatchService] = None
        self.library_api_service: Optional[LibraryApiServiceProcess] = None
        self.import_now_thread: Optional[threading.Thread] = None
        self.tray_icon: Optional[ImportAgentTrayIcon] = None
        self.watch_state_var = tk.StringVar(value="Watcher stopped.")
        self.library_service_state_var = tk.StringVar(value="Library web app stopped.")
        self.manager_status_var = tk.StringVar(value="Ready.")
        self.provision_status_var = tk.StringVar(value="Ready to provision or extend the managed setup.")
        self.summary_var = tk.StringVar(value="")

        self.sources_root_var = tk.StringVar(value=str(args.sources_root))
        self.libraries_root_var = tk.StringVar(value=str(args.libraries_root))
        self.library_name_var = tk.StringVar(value=str(args.library_name))
        self.source_name_var = tk.StringVar(value=str(args.source_name))
        self.source_type_choice_var = tk.StringVar(value=_SOURCE_TYPE_LABELS[SOURCE_TYPE_FILESYSTEM_ARCHIVE])
        self.run_tz_label_var = tk.StringVar(value=str(args.run_tz_label or "LOCAL"))
        self.data_syn_bike_export_var = tk.BooleanVar(value=bool(args.data_syn_bike_export))
        self.attach_session_note_var = tk.BooleanVar(value=bool(args.attach_session_note))
        self.session_auto_name_var = tk.BooleanVar(value=False)
        self.session_name_base_var = tk.StringVar(value="")
        self.auto_start_var = tk.BooleanVar(value=bool(args.auto_start))
        self.overwrite_var = tk.BooleanVar(value=bool(args.overwrite))
        self.source_library_choice_var = tk.StringVar(value="")
        self.wifi_address_var = tk.StringVar(value="")
        self.wifi_remember_address_var = tk.BooleanVar(value=False)
        self.wifi_logger_id_var = tk.StringVar(value="")
        self.wifi_cleanup_choice_var = tk.StringVar(value=_LOGGER_WIFI_CLEANUP_LABELS[LOGGER_WIFI_CLEANUP_NONE])
        self.wifi_request_timeout_var = tk.StringVar(value="5")
        self.wifi_download_timeout_var = tk.StringVar(value="60")
        self.wifi_status_var = tk.StringVar(value="Wi-Fi logger not checked.")
        self.startup_launch = bool(args.startup_launch)
        self.start_watch_on_launch = bool(args.start_watch or args.startup_launch)
        self.start_minimized_on_launch = bool(args.start_minimized or args.startup_launch)
        self._launch_behavior_applied = False
        self._close_notice_shown = False
        self._shutdown_requested = False
        self._startup_workspace_sync_checked = False

        self._library_choice_map: dict[str, str] = {}
        self._source_runtime_status: dict[str, str] = {}
        self.sources_root_entry: Optional[ttk.Entry] = None
        self.libraries_root_entry: Optional[ttk.Entry] = None
        self.sources_root_browse_button: Optional[ttk.Button] = None
        self.libraries_root_browse_button: Optional[ttk.Button] = None
        self.create_initial_button: Optional[ttk.Button] = None
        self.adopt_workspace_button: Optional[ttk.Button] = None
        self.add_library_button: Optional[ttk.Button] = None
        self.add_source_button: Optional[ttk.Button] = None
        self.apply_app_settings_button: Optional[ttk.Button] = None
        self.open_web_app_button: Optional[ttk.Button] = None
        self.stop_web_app_button: Optional[ttk.Button] = None
        self.library_choice_combo: Optional[ttk.Combobox] = None
        self.source_type_combo: Optional[ttk.Combobox] = None
        self.wifi_frame: Optional[ttk.LabelFrame] = None
        self.wifi_address_entry: Optional[ttk.Entry] = None
        self.wifi_verify_button: Optional[ttk.Button] = None

        self.libraries_tree: Optional[ttk.Treeview] = None
        self.sources_tree: Optional[ttk.Treeview] = None
        self.log_text: Optional[tk.Text] = None
        self.notebook: Optional[ttk.Notebook] = None

        self._build()
        self._refresh_ui_from_config(select_provision_when_missing=True)
        self.root.after(100, self._apply_window_icon)
        self._start_tray_icon()
        self._sync_startup_registration(show_errors=False, emit_status=False)
        self.root.after(250, self._poll_event_queue)
        self.root.after(400, self._apply_launch_behavior)
        self.root.after(900, self._check_workspace_sync_on_startup)

    def _apply_window_icon(self) -> None:
        try:
            png_asset = files(_ASSET_PACKAGE).joinpath(_WINDOW_ICON_FILENAME)
            icon_bytes = png_asset.read_bytes()
            icon_data = base64.b64encode(icon_bytes).decode("ascii")

            if sys.platform.startswith("win"):
                ico_asset = files(_ASSET_PACKAGE).joinpath(_WINDOW_ICON_ICO_FILENAME)
                with as_file(ico_asset) as ico_path:
                    self.root.iconbitmap(str(ico_path))
                    self.root.iconbitmap(default=str(ico_path))

            self._window_icon_image = tk.PhotoImage(data=icon_data, format="png")
            self.root.iconphoto(True, self._window_icon_image)
        except Exception:
            self._window_icon_image = None

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(self.root)
        notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook = notebook

        manager_tab = ttk.Frame(notebook, padding=14)
        provision_tab = ttk.Frame(notebook, padding=14)
        notebook.add(manager_tab, text="Manager")
        notebook.add(provision_tab, text="Provision")

        self._build_manager_tab(manager_tab)
        self._build_provision_tab(provision_tab)

    def _build_manager_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        parent.rowconfigure(4, weight=1)

        ttk.Label(
            parent,
            text=(
                "Manage configured libraries and sources, validate source configurations, "
                "run one-shot imports, or start and stop the in-process watch loop."
            ),
            wraplength=980,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 12))

        overview = ttk.Frame(parent)
        overview.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        overview.columnconfigure(0, weight=1)
        ttk.Label(overview, textvariable=self.summary_var, wraplength=980, justify="left").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(overview, textvariable=self.watch_state_var, wraplength=980, justify="left").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Label(overview, textvariable=self.library_service_state_var, wraplength=980, justify="left").grid(
            row=2, column=0, sticky="w", pady=(4, 0)
        )

        lists = ttk.Frame(parent)
        lists.grid(row=2, column=0, sticky="nsew")
        lists.columnconfigure(0, weight=1)
        lists.columnconfigure(1, weight=1)
        lists.rowconfigure(1, weight=1)

        ttk.Label(lists, text="Libraries").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(lists, text="Sources").grid(row=0, column=1, sticky="w", pady=(0, 4), padx=(12, 0))

        libraries_frame = ttk.Frame(lists)
        libraries_frame.grid(row=1, column=0, sticky="nsew")
        libraries_frame.columnconfigure(0, weight=1)
        libraries_frame.rowconfigure(0, weight=1)
        libraries_tree = ttk.Treeview(
            libraries_frame,
            columns=("display_name", "syn_export"),
            show="headings",
            height=9,
        )
        libraries_xscroll = ttk.Scrollbar(libraries_frame, orient="horizontal", command=libraries_tree.xview)
        libraries_tree.configure(xscrollcommand=libraries_xscroll.set)
        libraries_tree.heading("display_name", text="Library Name", anchor="w")
        libraries_tree.heading("syn_export", text="Syn Export", anchor="w")
        libraries_tree.column("display_name", width=260, anchor="w")
        libraries_tree.column("syn_export", width=90, anchor="center", stretch=False)
        libraries_tree.grid(row=0, column=0, sticky="nsew")
        libraries_xscroll.grid(row=1, column=0, sticky="ew")
        libraries_tree.bind("<Button-1>", self._on_libraries_tree_click)
        libraries_tree.bind("<Button-3>", self._on_libraries_tree_context)
        self.libraries_tree = libraries_tree

        sources_frame = ttk.Frame(lists)
        sources_frame.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        sources_frame.columnconfigure(0, weight=1)
        sources_frame.rowconfigure(0, weight=1)
        sources_tree = ttk.Treeview(
            sources_frame,
            columns=(
                "enabled",
                "force_reprocess",
                "display_name",
                "source_type",
                "status",
                "library_name",
                "bike_name",
                "attach_note",
            ),
            show="headings",
            height=9,
        )
        sources_xscroll = ttk.Scrollbar(sources_frame, orient="horizontal", command=sources_tree.xview)
        sources_tree.configure(xscrollcommand=sources_xscroll.set)
        sources_tree.heading("enabled", text="Enabled", anchor="w")
        sources_tree.heading("force_reprocess", text="Allow Reprocessing", anchor="w")
        sources_tree.heading("display_name", text="Source Name", anchor="w")
        sources_tree.heading("source_type", text="Type", anchor="w")
        sources_tree.heading("status", text="Status", anchor="w")
        sources_tree.heading("library_name", text="Target Library", anchor="w")
        sources_tree.heading("bike_name", text="Bike Name", anchor="w")
        sources_tree.heading("attach_note", text="Attach Note", anchor="w")
        sources_tree.column("enabled", width=80, anchor="center", stretch=False)
        sources_tree.column("force_reprocess", width=130, anchor="center", stretch=False)
        sources_tree.column("display_name", width=180, anchor="w")
        sources_tree.column("source_type", width=120, anchor="w")
        sources_tree.column("status", width=180, anchor="w")
        sources_tree.column("library_name", width=170, anchor="w")
        sources_tree.column("bike_name", width=190, anchor="w")
        sources_tree.column("attach_note", width=95, anchor="center", stretch=False)
        sources_tree.grid(row=0, column=0, sticky="nsew")
        sources_xscroll.grid(row=1, column=0, sticky="ew")
        sources_tree.bind("<Button-1>", self._on_sources_tree_click)
        sources_tree.bind("<Button-3>", self._on_sources_tree_context)
        self.sources_tree = sources_tree

        actions = ttk.Frame(parent)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 8))
        for col in range(7):
            actions.columnconfigure(col, weight=0)
        ttk.Button(actions, text="Refresh", command=self._refresh_ui_from_config).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Sync Workspace", command=self._sync_workspace_from_roots).grid(
            row=0, column=1, padx=(0, 8)
        )
        ttk.Button(actions, text="Import Now", command=self._import_now).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(actions, text="Start Watch", command=self._start_watch).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(actions, text="Stop Watch", command=self._stop_watch).grid(row=0, column=4, padx=(0, 8))
        self.open_web_app_button = ttk.Button(actions, text="Open Web App", command=self._open_web_app)
        self.open_web_app_button.grid(row=0, column=5, padx=(12, 8))
        self.stop_web_app_button = ttk.Button(actions, text="Stop Web App", command=self._stop_web_app)
        self.stop_web_app_button.grid(row=0, column=6, padx=(0, 8))

        logs = ttk.Frame(parent)
        logs.grid(row=4, column=0, sticky="nsew")
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(1, weight=1)
        ttk.Label(logs, text="Activity").grid(row=0, column=0, sticky="w", pady=(0, 4))
        text = tk.Text(logs, height=12, wrap="word", state="disabled")
        text.grid(row=1, column=0, sticky="nsew")
        self.log_text = text

        ttk.Label(parent, textvariable=self.manager_status_var, wraplength=980, justify="left").grid(
            row=5, column=0, sticky="ew", pady=(8, 0)
        )

    def _build_provision_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        ttk.Label(
            parent,
            text=(
                "Create the first managed library and source, or extend an existing managed setup "
                "with another library or source."
            ),
            wraplength=980,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        library_frame = ttk.LabelFrame(parent, text="Library", padding=10)
        library_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        library_frame.columnconfigure(1, weight=1)

        self.libraries_root_entry = self._add_text_row(
            parent=library_frame,
            row=0,
            label="Libraries root",
            variable=self.libraries_root_var,
            browse_command=lambda: self._choose_directory(self.libraries_root_var, "Choose libraries root"),
        )
        self._add_text_row(parent=library_frame, row=1, label="Library name", variable=self.library_name_var)
        ttk.Checkbutton(
            library_frame,
            text="Generate data.syn.bike exports",
            variable=self.data_syn_bike_export_var,
        ).grid(row=2, column=1, sticky="w", pady=(6, 0), padx=(12, 8))
        self.add_library_button = ttk.Button(library_frame, text="Add Library", command=self._add_library)
        self.add_library_button.grid(row=3, column=1, sticky="w", pady=(8, 0), padx=(12, 8))

        source_frame = ttk.LabelFrame(parent, text="Source", padding=10)
        source_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        source_frame.columnconfigure(1, weight=1)

        self.sources_root_entry = self._add_text_row(
            parent=source_frame,
            row=0,
            label="Sources root",
            variable=self.sources_root_var,
            browse_command=lambda: self._choose_directory(self.sources_root_var, "Choose sources root"),
        )
        ttk.Label(source_frame, text="Source name").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(source_frame, textvariable=self.source_name_var).grid(
            row=1, column=1, sticky="ew", pady=4, padx=(12, 8)
        )
        ttk.Label(source_frame, text="Source type").grid(row=2, column=0, sticky="w", pady=4)
        source_type_combo = ttk.Combobox(
            source_frame,
            textvariable=self.source_type_choice_var,
            values=list(_SOURCE_TYPE_BY_LABEL),
            state="readonly",
        )
        source_type_combo.grid(row=2, column=1, sticky="ew", pady=4, padx=(12, 8))
        source_type_combo.bind("<<ComboboxSelected>>", lambda _event: self._sync_source_type_fields())
        self.source_type_combo = source_type_combo
        combo = ttk.Combobox(source_frame, textvariable=self.source_library_choice_var, state="readonly")
        ttk.Label(source_frame, text="Target library").grid(row=3, column=0, sticky="w", pady=4)
        combo.grid(row=3, column=1, sticky="ew", pady=4, padx=(12, 8))
        self.library_choice_combo = combo
        self._add_text_row(parent=source_frame, row=4, label="Run TZ label", variable=self.run_tz_label_var)
        session_naming_frame = ttk.Frame(source_frame)
        session_naming_frame.grid(row=5, column=1, sticky="ew", pady=(6, 0), padx=(12, 8))
        session_naming_frame.columnconfigure(2, weight=1)
        ttk.Checkbutton(
            session_naming_frame,
            text="Auto-name sessions on import",
            variable=self.session_auto_name_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(session_naming_frame, text="Session base name").grid(
            row=0, column=1, sticky="w", padx=(18, 6)
        )
        ttk.Entry(session_naming_frame, textvariable=self.session_name_base_var).grid(
            row=0, column=2, sticky="ew"
        )
        ttk.Checkbutton(
            source_frame,
            text="Attach draft setup note on import",
            variable=self.attach_session_note_var,
        ).grid(row=6, column=1, sticky="w", pady=(6, 0), padx=(12, 8))

        self.wifi_frame = self._build_wifi_provision_frame(source_frame)
        self.wifi_frame.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(10, 4))

        self.add_source_button = ttk.Button(source_frame, text="Add Source", command=self._add_source)
        self.add_source_button.grid(row=8, column=1, sticky="w", pady=(8, 0), padx=(12, 8))

        options = ttk.LabelFrame(parent, text="App options", padding=10)
        options.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        ttk.Checkbutton(options, text="Start at login", variable=self.auto_start_var).grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Checkbutton(options, text="Overwrite existing seeded files", variable=self.overwrite_var).grid(
            row=0, column=1, sticky="w"
        )

        actions = ttk.Frame(parent)
        actions.grid(row=4, column=0, sticky="ew")
        self.create_initial_button = ttk.Button(
            actions,
            text="Create Initial Library + Source",
            command=self._create_initial_setup,
        )
        self.create_initial_button.grid(row=0, column=0, padx=(0, 8))
        self.adopt_workspace_button = ttk.Button(
            actions,
            text="Use Existing Workspace",
            command=self._adopt_existing_workspace,
        )
        self.adopt_workspace_button.grid(row=0, column=1, padx=(0, 8))
        self.apply_app_settings_button = ttk.Button(
            actions,
            text="Apply App Settings",
            command=self._apply_app_settings,
        )
        self.apply_app_settings_button.grid(row=0, column=2)

        ttk.Label(parent, textvariable=self.provision_status_var, wraplength=980, justify="left").grid(
            row=5, column=0, sticky="ew", pady=(10, 0)
        )
        self._sync_source_type_fields()

    def _build_wifi_provision_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Wi-Fi logger source", padding=10)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Logger ID").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.wifi_logger_id_var).grid(
            row=0, column=1, sticky="ew", pady=4, padx=(12, 8)
        )
        ttk.Button(frame, text="Discover Loggers", command=self._discover_loggers_from_provision_form).grid(
            row=0, column=2, sticky="e", pady=4
        )

        ttk.Checkbutton(
            frame,
            text="Use fixed logger address",
            variable=self.wifi_remember_address_var,
            command=self._sync_wifi_address_mode,
        ).grid(row=1, column=1, sticky="w", pady=4, padx=(12, 8))

        ttk.Label(frame, text="Logger address").grid(row=2, column=0, sticky="w", pady=4)
        self.wifi_address_entry = ttk.Entry(frame, textvariable=self.wifi_address_var)
        self.wifi_address_entry.grid(row=2, column=1, sticky="ew", pady=4, padx=(12, 8))
        self.wifi_verify_button = ttk.Button(frame, text="Verify Logger", command=self._verify_logger_from_provision_form)
        self.wifi_verify_button.grid(
            row=2, column=2, sticky="e", pady=4
        )

        ttk.Label(frame, text="After import").grid(row=3, column=0, sticky="w", pady=4)
        cleanup_combo = ttk.Combobox(
            frame,
            textvariable=self.wifi_cleanup_choice_var,
            values=list(_LOGGER_WIFI_CLEANUP_BY_LABEL),
            state="readonly",
        )
        cleanup_combo.grid(row=3, column=1, sticky="ew", pady=4, padx=(12, 8))

        timeouts = ttk.Frame(frame)
        timeouts.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(timeouts, text="Request timeout (s)").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(timeouts, textvariable=self.wifi_request_timeout_var, width=8).grid(
            row=0, column=1, sticky="w", padx=(0, 18)
        )
        ttk.Label(timeouts, text="Download timeout (s)").grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Entry(timeouts, textvariable=self.wifi_download_timeout_var, width=8).grid(
            row=0, column=3, sticky="w"
        )

        ttk.Label(frame, textvariable=self.wifi_status_var, wraplength=880, justify="left").grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )
        self._sync_wifi_address_mode()
        return frame

    def _add_text_row(
        self,
        *,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse_command: Optional[Callable[[], None]] = None,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=4, padx=(12, 8))
        if browse_command is not None:
            button = ttk.Button(parent, text="Browse...", command=browse_command)
            button.grid(row=row, column=2, sticky="e", pady=4)
            if label == "Sources root":
                self.sources_root_browse_button = button
            elif label == "Libraries root":
                self.libraries_root_browse_button = button
        return entry

    def _choose_directory(self, variable: tk.StringVar, title: str) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            title=title,
            initialdir=variable.get() or str(Path.home()),
            mustexist=False,
        )
        if selected:
            variable.set(selected)

    def _selected_source_type(self) -> str:
        label = self.source_type_choice_var.get().strip()
        return _SOURCE_TYPE_BY_LABEL.get(label, SOURCE_TYPE_FILESYSTEM_ARCHIVE)

    def _selected_cleanup_mode(self) -> str:
        label = self.wifi_cleanup_choice_var.get().strip()
        return _LOGGER_WIFI_CLEANUP_BY_LABEL.get(label, LOGGER_WIFI_CLEANUP_NONE)

    def _sync_wifi_address_mode(self) -> None:
        state = "normal" if bool(self.wifi_remember_address_var.get()) else "disabled"
        if self.wifi_address_entry is not None:
            self.wifi_address_entry.configure(state=state)
        if self.wifi_verify_button is not None:
            self.wifi_verify_button.configure(state=state)

    def _sync_source_type_fields(self) -> None:
        if self.wifi_frame is None:
            return
        if self._selected_source_type() == SOURCE_TYPE_LOGGER_WIFI:
            self.wifi_frame.grid()
            self._sync_wifi_address_mode()
        else:
            self.wifi_frame.grid_remove()

    def _positive_float_from_var(self, variable: tk.StringVar, *, field_name: str) -> float:
        try:
            value = float(variable.get().strip())
        except ValueError:
            raise ValueError(f"{field_name} must be numeric") from None
        if value <= 0:
            raise ValueError(f"{field_name} must be > 0")
        return value

    def _logger_wifi_payload_from_form(self) -> Optional[dict[str, Any]]:
        if self._selected_source_type() != SOURCE_TYPE_LOGGER_WIFI:
            return None

        logger_id = self.wifi_logger_id_var.get().strip()
        base_url = self.wifi_address_var.get().strip() if self.wifi_remember_address_var.get() else ""
        if not logger_id:
            raise ValueError("Discover or verify the Wi-Fi logger, or enter its Logger ID, before creating the source.")

        payload = {
            "logger_id": logger_id,
            "request_timeout_s": self._positive_float_from_var(
                self.wifi_request_timeout_var,
                field_name="Wi-Fi request timeout",
            ),
            "download_timeout_s": self._positive_float_from_var(
                self.wifi_download_timeout_var,
                field_name="Wi-Fi download timeout",
            ),
            "cleanup_mode": self._selected_cleanup_mode(),
        }
        if base_url:
            payload["base_url"] = base_url
        return payload

    def _wifi_client_from_form(self) -> LoggerWifiApiClient:
        base_url = self.wifi_address_var.get().strip()
        if not base_url:
            raise ValueError("Enter a logger address first.")
        return LoggerWifiApiClient(
            base_url,
            request_timeout_s=self._positive_float_from_var(
                self.wifi_request_timeout_var,
                field_name="Wi-Fi request timeout",
            ),
            download_timeout_s=self._positive_float_from_var(
                self.wifi_download_timeout_var,
                field_name="Wi-Fi download timeout",
            ),
        )

    def _verify_logger_from_provision_form(self) -> None:
        try:
            client = self._wifi_client_from_form()
            device = client.get_device()
            status = client.get_status()
            logger_id = str(device.get("logger_id") or "").strip()
            if not logger_id:
                raise ValueError("Logger did not return a logger_id.")
            display_name = str(device.get("display_name") or logger_id).strip()
            self.wifi_logger_id_var.set(logger_id)
            if self.source_name_var.get().strip() in {"", "Default Source"}:
                self.source_name_var.set(display_name)
            text = self._logger_status_text(
                upload_mode=bool(status.get("upload_mode", False)),
                session_count=status.get("importable_session_count"),
            )
            self.wifi_status_var.set(f"Verified {display_name} ({logger_id}). {text}")
            self._set_provision_status(f"Verified Wi-Fi logger '{display_name}' at {client.base_url}.")
        except Exception as exc:
            self.wifi_status_var.set(f"Logger verification failed: {exc}")
            self._set_provision_status(f"Logger verification failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)

    def _apply_discovered_logger_to_provision_form(self, result: LoggerWifiDiscoveryResult) -> None:
        remembered = bool(self.wifi_remember_address_var.get())
        if result.base_url and remembered:
            self.wifi_address_var.set(result.base_url)
        if result.logger_id:
            self.wifi_logger_id_var.set(result.logger_id)
        display_name = result.display_name or result.logger_id or result.hostname or "Wi-Fi Logger"
        if self.source_name_var.get().strip() in {"", "Default Source"}:
            self.source_name_var.set(display_name)
        upload_text = "unknown" if result.upload_mode is None else ("yes" if result.upload_mode else "no")
        remember_text = "address remembered" if remembered else "address not remembered"
        self.wifi_status_var.set(
            f"Discovered {display_name} at {result.base_url}; upload_mode={upload_text}; {remember_text}."
        )

    def _discover_loggers_from_provision_form(self) -> None:
        try:
            timeout_s = max(
                1.0,
                min(
                    self._positive_float_from_var(
                        self.wifi_request_timeout_var,
                        field_name="Wi-Fi request timeout",
                    ),
                    5.0,
                ),
            )
            results = discover_logger_wifi_sources(
                timeout_s=timeout_s,
                include_default_ap=True,
                default_ap_timeout_s=1.0,
            )
            if not results:
                message = "No BODAQS Wi-Fi loggers were discovered on the local network."
                self.wifi_status_var.set(message)
                self._set_provision_status(message)
                return
            result = results[0] if len(results) == 1 else self._choose_discovered_logger(results)
            if result is None:
                self._set_provision_status("Logger discovery cancelled.")
                return
            self._apply_discovered_logger_to_provision_form(result)
            self._set_provision_status(
                f"Selected discovered Wi-Fi logger '{result.logger_id or result.hostname or result.base_url}'."
            )
        except Exception as exc:
            self.wifi_status_var.set(f"Logger discovery failed: {exc}")
            self._set_provision_status(f"Logger discovery failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)

    def _choose_discovered_logger(
        self,
        results: Sequence[LoggerWifiDiscoveryResult],
    ) -> Optional[LoggerWifiDiscoveryResult]:
        dialog = tk.Toplevel(self.root)
        dialog.title("Discovered BODAQS Loggers")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("760x320")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            dialog,
            columns=("logger_id", "address", "upload_mode", "hostname"),
            show="headings",
            selectmode="browse",
        )
        tree.heading("logger_id", text="Logger ID", anchor="w")
        tree.heading("address", text="Address", anchor="w")
        tree.heading("upload_mode", text="Upload Mode", anchor="w")
        tree.heading("hostname", text="Hostname", anchor="w")
        tree.column("logger_id", width=180, anchor="w")
        tree.column("address", width=190, anchor="w")
        tree.column("upload_mode", width=100, anchor="w")
        tree.column("hostname", width=220, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))

        result_by_iid: dict[str, LoggerWifiDiscoveryResult] = {}
        for idx, result in enumerate(results):
            iid = str(idx)
            result_by_iid[iid] = result
            upload_mode = "unknown" if result.upload_mode is None else ("yes" if result.upload_mode else "no")
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(result.logger_id or "", result.base_url, upload_mode, result.hostname or ""),
            )
        if result_by_iid:
            tree.selection_set("0")

        selected: dict[str, LoggerWifiDiscoveryResult] = {}

        def choose() -> None:
            selection = tree.selection()
            if selection:
                selected["result"] = result_by_iid[selection[0]]
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.grid(row=1, column=0, sticky="e", padx=10, pady=(0, 10))
        ttk.Button(buttons, text="Cancel", command=cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Select Logger", command=choose).grid(row=0, column=1)
        tree.bind("<Double-1>", lambda _event: choose())
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self.root.wait_window(dialog)
        return selected.get("result")

    def _logger_status_text(self, *, upload_mode: bool, session_count: Any = None) -> str:
        session_part = ""
        if session_count is not None:
            session_part = f", sessions={session_count}"
        return f"upload_mode={'yes' if upload_mode else 'no'}{session_part}"

    def _session_name_base_from_form(self) -> str:
        return self.session_name_base_var.get().strip() or self.source_name_var.get().strip()

    def _selected_source_config(self) -> Any:
        source_id = self._selected_source_id()
        if source_id is None:
            raise ValueError("Select a source first.")
        config = self.controller.require_config()
        managed_source = next((item for item in config.sources if item.source_id == source_id), None)
        if managed_source is None:
            raise ValueError(f"Unknown source: {source_id}")
        return load_import_source_config(managed_source.source_root)

    def _selected_logger_wifi_client_and_source(self) -> tuple[LoggerWifiApiClient, Any]:
        source = self._selected_source_config()
        if source.source_type != SOURCE_TYPE_LOGGER_WIFI or source.logger_wifi is None:
            raise ValueError("Select a Wi-Fi logger source first.")
        base_url = source.logger_wifi.base_url
        configured_error: Optional[Exception] = None
        if base_url is not None:
            client = LoggerWifiApiClient(
                base_url,
                request_timeout_s=source.logger_wifi.request_timeout_s,
                download_timeout_s=source.logger_wifi.download_timeout_s,
            )
            try:
                device = client.get_device()
                logger_id = str(device.get("logger_id") or "").strip()
                if logger_id != source.logger_wifi.logger_id:
                    raise ValueError(
                        f"Logger identity mismatch: expected {source.logger_wifi.logger_id!r}, got {logger_id!r}"
                    )
                return client, source
            except Exception as exc:
                configured_error = exc

        result = discover_single_logger_wifi_source(
            logger_id=source.logger_wifi.logger_id,
            timeout_s=max(1.0, min(float(source.logger_wifi.request_timeout_s), 5.0)),
            include_default_ap=True,
            default_ap_timeout_s=1.0,
        )
        if result is None:
            detail = (
                f" Remembered address {base_url!r} also failed: {configured_error}"
                if configured_error is not None and base_url is not None
                else ""
            )
            raise ValueError(
                f"Selected Wi-Fi source '{source.logger_wifi.logger_id}' was not discovered on the local network."
                + detail
            )
        client = LoggerWifiApiClient(
            result.base_url,
            request_timeout_s=source.logger_wifi.request_timeout_s,
            download_timeout_s=source.logger_wifi.download_timeout_s,
        )
        try:
            device = client.get_device()
            logger_id = str(device.get("logger_id") or "").strip()
            if logger_id != source.logger_wifi.logger_id:
                raise ValueError(
                    f"Logger identity mismatch: expected {source.logger_wifi.logger_id!r}, got {logger_id!r}"
                )
        except Exception as exc:
            if configured_error is not None and base_url is not None:
                raise ValueError(
                    f"Remembered logger address failed ({configured_error}); "
                    f"discovered address {result.base_url!r} also failed: {exc}"
                ) from exc
            raise
        return client, source

    def _set_source_runtime_status(self, source_id: str, status: str) -> None:
        self._source_runtime_status[source_id] = status
        if self.sources_tree is None or not self.sources_tree.exists(source_id):
            return
        columns = tuple(str(column) for column in self.sources_tree["columns"])
        try:
            status_index = columns.index("status")
        except ValueError:
            return
        values = list(self.sources_tree.item(source_id, "values"))
        if len(values) > status_index:
            values[status_index] = status
            self.sources_tree.item(source_id, values=values)

    def _remote_report_status_text(self, remote: Any) -> Optional[str]:
        if not isinstance(remote, dict):
            return None
        status = remote.get("status")
        if not isinstance(status, dict):
            return None
        state = str(status.get("state") or "unknown")
        if state == "ready":
            return self._logger_status_text(
                upload_mode=bool(status.get("upload_mode", False)),
                session_count=status.get("importable_session_count", remote.get("sessions_seen")),
            )
        if state == "waiting_upload_mode":
            return "waiting for upload mode"
        if state == "missing_base_url":
            return "missing logger address"
        if state == "error":
            return f"error: {status.get('error')}"
        return state

    def _update_source_status_from_report(self, report: dict[str, Any]) -> None:
        status = self._remote_report_status_text(report.get("remote"))
        if status:
            self._set_source_runtime_status(str(report.get("source_id") or ""), status)

    def _append_log(self, message: str) -> None:
        if self.log_text is None:
            return
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _progress_int(self, progress: Mapping[str, Any], key: str, default: int = 0) -> int:
        try:
            return int(progress.get(key, default))
        except (TypeError, ValueError):
            return default

    def _source_status_from_progress(self, progress: Mapping[str, Any]) -> Optional[str]:
        event = str(progress.get("event") or "")
        if event == "source_scan_started":
            return "scanning..."
        if event == "remote_acquisition_started":
            return "checking logger..."
        if event == "remote_status":
            state = str(progress.get("remote_state") or "unknown")
            if state == "waiting_upload_mode":
                return "waiting for upload mode"
            if state == "error":
                return f"error: {progress.get('error')}"
            return state
        if event == "remote_sessions_detected":
            return f"{self._progress_int(progress, 'session_count')} remote session(s) detected"
        if event == "remote_session_download_started":
            return (
                f"downloading remote {self._progress_int(progress, 'remote_session_index')}/"
                f"{self._progress_int(progress, 'remote_session_count')}"
            )
        if event == "remote_session_downloaded":
            return (
                f"downloaded remote {self._progress_int(progress, 'remote_session_index')}/"
                f"{self._progress_int(progress, 'remote_session_count')}"
            )
        if event == "remote_session_failed":
            return (
                f"remote failed {self._progress_int(progress, 'remote_session_index')}/"
                f"{self._progress_int(progress, 'remote_session_count')}"
            )
        if event == "archives_detected":
            count = self._progress_int(progress, "archive_count")
            return f"{count} archive(s) detected" if count else "no archives detected"
        if event == "archive_deferred":
            return (
                f"deferred {self._progress_int(progress, 'archive_index')}/"
                f"{self._progress_int(progress, 'archive_count')}"
            )
        if event == "archive_processing_started":
            return (
                f"processing {self._progress_int(progress, 'archive_index')}/"
                f"{self._progress_int(progress, 'archive_count')}"
            )
        if event == "archive_imported":
            return (
                f"imported {self._progress_int(progress, 'archive_index')}/"
                f"{self._progress_int(progress, 'archive_count')}"
            )
        if event == "archive_failed":
            return (
                f"failed {self._progress_int(progress, 'archive_index')}/"
                f"{self._progress_int(progress, 'archive_count')}"
            )
        if event == "archive_skipped":
            return (
                f"skipped {self._progress_int(progress, 'archive_index')}/"
                f"{self._progress_int(progress, 'archive_count')}"
            )
        if event == "source_scan_completed":
            totals = progress.get("totals")
            if isinstance(totals, Mapping):
                return (
                    f"complete: seen={totals.get('seen', 0)} imported={totals.get('imported', 0)} "
                    f"failed={totals.get('failed', 0)}"
                )
        return None

    def _format_import_progress_log(self, progress: Mapping[str, Any], *, origin: str) -> Optional[str]:
        event = str(progress.get("event") or "")
        source_id = str(progress.get("source_id") or "")
        label = "Watch" if origin == "watch" else "Import"
        archive_name = str(progress.get("archive_name") or "")
        remote_session_id = str(progress.get("remote_session_id") or "")

        if event == "remote_status":
            state = str(progress.get("remote_state") or "unknown")
            if origin == "watch" and state not in {"error"}:
                return None
            detail = progress.get("error") or progress.get("message") or state
            return f"{label} source {source_id}: logger status {detail}."
        if event == "remote_sessions_detected":
            count = self._progress_int(progress, "session_count")
            if origin == "watch" and count == 0:
                return None
            return f"{label} source {source_id}: detected {count} remote session(s)."
        if event == "remote_session_download_started":
            return (
                f"{label} source {source_id}: downloading remote "
                f"{self._progress_int(progress, 'remote_session_index')}/"
                f"{self._progress_int(progress, 'remote_session_count')}: {remote_session_id}"
            )
        if event == "remote_session_downloaded":
            return f"{label} source {source_id}: downloaded remote session {remote_session_id}."
        if event == "remote_session_failed":
            return f"{label} source {source_id}: remote session {remote_session_id} failed: {progress.get('error')}"
        if event == "remote_session_skipped":
            return (
                f"{label} source {source_id}: skipped remote session {remote_session_id} "
                f"({progress.get('reason')})."
            )
        if event == "archives_detected":
            count = self._progress_int(progress, "archive_count")
            if origin == "watch" and count == 0:
                return None
            return f"{label} source {source_id}: detected {count} archive(s)."
        if event == "archive_deferred":
            return f"{label} source {source_id}: deferred {archive_name} while it settles."
        if event == "archive_processing_started":
            return (
                f"{label} source {source_id}: processing "
                f"{self._progress_int(progress, 'archive_index')}/"
                f"{self._progress_int(progress, 'archive_count')}: {archive_name}"
            )
        if event == "archive_imported":
            session_id = progress.get("session_id")
            suffix = f" -> {session_id}" if session_id else ""
            return f"{label} source {source_id}: imported {archive_name}{suffix}."
        if event == "archive_failed":
            return f"{label} source {source_id}: failed {archive_name}: {progress.get('error')}"
        if event == "archive_skipped":
            return f"{label} source {source_id}: skipped {archive_name} ({progress.get('reason')})."
        return None

    def _handle_import_progress(self, progress: Mapping[str, Any], *, origin: str) -> None:
        source_id = str(progress.get("source_id") or "")
        status = self._source_status_from_progress(progress)
        if source_id and status:
            self._set_source_runtime_status(source_id, status)

        message = self._format_import_progress_log(progress, origin=origin)
        if message:
            self.manager_status_var.set(message)
            self._append_log(message)
            self._refresh_tray()

    def _set_manager_status(self, message: str) -> None:
        self.manager_status_var.set(message)
        self._append_log(message)
        self._refresh_tray()

    def _set_provision_status(self, message: str) -> None:
        self.provision_status_var.set(message)
        self._append_log(message)

    def _refresh_ui_from_config(self, *, select_provision_when_missing: bool = False) -> None:
        self.controller.reload()
        config = self.controller.app_config
        if config is None:
            self.summary_var.set(
                "No managed app config exists yet. Use the Provision tab to create the first library and source."
            )
            self.watch_state_var.set("Watcher stopped.")
            self.library_service_state_var.set("Library web app unavailable until a managed setup exists.")
            self._render_libraries([])
            self._render_sources([])
            self._library_choice_map = {}
            if self.library_choice_combo is not None:
                self.library_choice_combo.configure(values=[])
            self.source_library_choice_var.set("")
            self._set_root_editable(True)
            if self.create_initial_button is not None:
                self.create_initial_button.configure(state="normal")
            if self.adopt_workspace_button is not None:
                self.adopt_workspace_button.configure(state="normal")
            if self.add_library_button is not None:
                self.add_library_button.configure(state="disabled")
            if self.add_source_button is not None:
                self.add_source_button.configure(state="disabled")
            if self.apply_app_settings_button is not None:
                self.apply_app_settings_button.configure(state="disabled")
            self._refresh_web_app_controls(has_config=False)
            if select_provision_when_missing and self.notebook is not None:
                self.notebook.select(1)
            self._refresh_tray()
            return

        self.sources_root_var.set(str(config.sources_root))
        self.libraries_root_var.set(str(config.libraries_root))
        self.auto_start_var.set(bool(config.auto_start))
        enabled_count = sum(1 for source in config.sources if source.enabled)
        self.summary_var.set(
            "Managed roots: "
            f"sources={config.sources_root} | libraries={config.libraries_root} | "
            f"libraries={len(config.libraries)} | sources={len(config.sources)} | "
            f"enabled sources={enabled_count} | start at login={'yes' if config.auto_start else 'no'}"
        )
        self._render_libraries(config.libraries)
        self._render_sources(config.sources)

        choices = [f"{library.display_name} ({library.library_id})" for library in config.libraries]
        self._library_choice_map = {
            f"{library.display_name} ({library.library_id})": library.library_id for library in config.libraries
        }
        if self.library_choice_combo is not None:
            self.library_choice_combo.configure(values=choices)
        if choices and self.source_library_choice_var.get() not in self._library_choice_map:
            self.source_library_choice_var.set(choices[0])

        self._set_root_editable(False)
        if self.create_initial_button is not None:
            self.create_initial_button.configure(state="disabled")
        if self.adopt_workspace_button is not None:
            self.adopt_workspace_button.configure(state="disabled")
        if self.add_library_button is not None:
            self.add_library_button.configure(state="normal")
        if self.add_source_button is not None:
            self.add_source_button.configure(state="normal")
        if self.apply_app_settings_button is not None:
            self.apply_app_settings_button.configure(state="normal")
        self._refresh_web_app_controls(has_config=True)
        self._refresh_tray()

    def _refresh_web_app_controls(self, *, has_config: bool) -> None:
        if self.open_web_app_button is not None:
            self.open_web_app_button.configure(state="normal" if has_config else "disabled")
        if self.stop_web_app_button is not None:
            self.stop_web_app_button.configure(
                state="normal" if self.library_api_service is not None and self.library_api_service.is_running() else "disabled"
            )
        if not has_config:
            return
        service = self._library_api_service_for_current_config(create=False)
        if service is not None and service.is_running():
            self.library_service_state_var.set(f"Library web app available at {service.web_url}")
        else:
            base_url = f"http://{_LIBRARY_SERVICE_HOST}:{_LIBRARY_SERVICE_PORT}"
            self.library_service_state_var.set(
                f"Library web app stopped. Use Open Web App to start {base_url}."
            )

    def _set_root_editable(self, editable: bool) -> None:
        state = "normal" if editable else "disabled"
        for entry in (self.sources_root_entry, self.libraries_root_entry):
            if entry is not None:
                entry.configure(state=state)
        for button in (self.sources_root_browse_button, self.libraries_root_browse_button):
            if button is not None:
                button.configure(state=state)

    def _render_libraries(self, libraries: Sequence[Any]) -> None:
        if self.libraries_tree is None:
            return
        self.libraries_tree.delete(*self.libraries_tree.get_children())
        for library in libraries:
            self.libraries_tree.insert(
                "",
                "end",
                iid=library.library_id,
                values=(
                    library.display_name,
                    (
                        _SOURCE_ENABLED_CHECKED
                        if getattr(library, "data_syn_bike_export_enabled", False)
                        else _SOURCE_ENABLED_UNCHECKED
                    ),
                ),
            )

    def _render_sources(self, sources: Sequence[Any]) -> None:
        if self.sources_tree is None:
            return
        self.sources_tree.delete(*self.sources_tree.get_children())
        for source in sources:
            status_text = self._source_runtime_status.get(source.source_id)
            if status_text is None:
                status_text = "not checked" if source.source_type == SOURCE_TYPE_LOGGER_WIFI else "-"
            library_name = self._managed_library_display_name(source.library_id)
            bike_name = self._source_bike_display_name(source.source_root)
            self.sources_tree.insert(
                "",
                "end",
                iid=source.source_id,
                values=(
                    _SOURCE_ENABLED_CHECKED if source.enabled else _SOURCE_ENABLED_UNCHECKED,
                    (
                        _SOURCE_ENABLED_CHECKED
                        if getattr(source, "force_reprocess", False)
                        else _SOURCE_ENABLED_UNCHECKED
                    ),
                    source.display_name,
                    _SOURCE_TYPE_LABELS.get(source.source_type, source.source_type),
                    status_text,
                    library_name,
                    bike_name,
                    (
                        _SOURCE_ENABLED_CHECKED
                        if getattr(source, "attach_session_note_on_import", False)
                        else _SOURCE_ENABLED_UNCHECKED
                    ),
                ),
            )

    def _managed_library_config(self, library_id: str) -> Any:
        config = self.controller.require_config()
        for library in config.libraries:
            if library.library_id == library_id:
                return library
        raise ValueError(f"Unknown library: {library_id}")

    def _managed_library_display_name(self, library_id: str) -> str:
        try:
            return str(self._managed_library_config(library_id).display_name)
        except Exception:
            return f"Unavailable ({library_id})"

    def _source_bike_display_name(self, source_root: Path) -> str:
        try:
            _profile_path, profile = load_source_bike_profile(source_root)
        except Exception:
            return "Unavailable"
        return str(profile.get("display_name") or profile.get("bike_profile_id") or "Unnamed bike")

    def _selected_source_id(self) -> Optional[str]:
        if self.sources_tree is None:
            return None
        selection = self.sources_tree.selection()
        return str(selection[0]) if selection else None

    def _select_source_in_manager(self, source_id: str) -> None:
        if self.notebook is not None:
            self.notebook.select(0)
        if self.sources_tree is not None and self.sources_tree.exists(source_id):
            self.sources_tree.selection_set(source_id)
            self.sources_tree.focus(source_id)
            self.sources_tree.see(source_id)

    def _selected_library_id(self) -> Optional[str]:
        if self.libraries_tree is None:
            return None
        selection = self.libraries_tree.selection()
        return str(selection[0]) if selection else None

    def _managed_library_syn_export_enabled(self, library_id: str) -> bool:
        config = self.controller.require_config()
        for library in config.libraries:
            if library.library_id == library_id:
                return bool(getattr(library, "data_syn_bike_export_enabled", False))
        raise ValueError(f"Unknown library: {library_id}")

    def _managed_source_enabled(self, source_id: str) -> bool:
        config = self.controller.require_config()
        for source in config.sources:
            if source.source_id == source_id:
                return bool(source.enabled)
        raise ValueError(f"Unknown source: {source_id}")

    def _managed_source_session_note_attach_enabled(self, source_id: str) -> bool:
        config = self.controller.require_config()
        for source in config.sources:
            if source.source_id == source_id:
                return bool(getattr(source, "attach_session_note_on_import", False))
        raise ValueError(f"Unknown source: {source_id}")

    def _managed_source_force_reprocess_enabled(self, source_id: str) -> bool:
        config = self.controller.require_config()
        for source in config.sources:
            if source.source_id == source_id:
                return bool(getattr(source, "force_reprocess", False))
        raise ValueError(f"Unknown source: {source_id}")

    def _managed_source_config(self, source_id: str) -> Any:
        config = self.controller.require_config()
        for source in config.sources:
            if source.source_id == source_id:
                return source
        raise ValueError(f"Unknown source: {source_id}")

    def _selected_managed_source_config(self) -> Any:
        source_id = self._selected_source_id()
        if source_id is None:
            raise ValueError("Select a source first.")
        return self._managed_source_config(source_id)

    def _choose_library_id_dialog(self, *, current_library_id: str) -> Optional[str]:
        config = self.controller.require_config()
        choices = [f"{library.display_name} ({library.library_id})" for library in config.libraries]
        choice_map = {f"{library.display_name} ({library.library_id})": library.library_id for library in config.libraries}
        if not choices:
            messagebox.showinfo(_APP_DISPLAY_NAME, "Create a library first.", parent=self.root)
            return None

        dialog = tk.Toplevel(self.root)
        dialog.title("Choose Library")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        selected = tk.StringVar()
        for label, library_id in choice_map.items():
            if library_id == current_library_id:
                selected.set(label)
                break
        if not selected.get():
            selected.set(choices[0])

        ttk.Label(dialog, text="Choose the target library for this source.", justify="left").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )
        combo = ttk.Combobox(dialog, textvariable=selected, values=choices, state="readonly", width=56)
        combo.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        result: dict[str, Optional[str]] = {"library_id": None}

        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="e", padx=12, pady=(0, 12))

        def accept() -> None:
            result["library_id"] = choice_map.get(selected.get())
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Apply", command=accept).grid(row=0, column=1)
        combo.focus_set()
        self.root.wait_window(dialog)
        return result["library_id"]

    def _choose_source_dialog(self, *, title: str, exclude_source_id: Optional[str] = None) -> Optional[Any]:
        config = self.controller.require_config()
        sources = [source for source in config.sources if source.source_id != exclude_source_id]
        if not sources:
            messagebox.showinfo(_APP_DISPLAY_NAME, "No other source is available.", parent=self.root)
            return None
        choices = [f"{source.display_name} ({source.source_id})" for source in sources]
        choice_map = {f"{source.display_name} ({source.source_id})": source for source in sources}

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        selected = tk.StringVar(value=choices[0])
        ttk.Label(dialog, text="Choose the source to copy from.", justify="left").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )
        combo = ttk.Combobox(dialog, textvariable=selected, values=choices, state="readonly", width=56)
        combo.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        result: dict[str, Any] = {"source": None}

        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="e", padx=12, pady=(0, 12))

        def accept() -> None:
            result["source"] = choice_map.get(selected.get())
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Copy", command=accept).grid(row=0, column=1)
        combo.focus_set()
        self.root.wait_window(dialog)
        return result["source"]

    def _managed_library_bike_profile_choices(
        self,
        library_id: str,
    ) -> tuple[list[str], dict[str, tuple[Path, dict[str, Any]]]]:
        library = self._managed_library_config(library_id)
        records = discover_bike_profiles(library_bike_profiles_dir(library.artifacts_dir))
        choices: list[str] = []
        choice_map: dict[str, tuple[Path, dict[str, Any]]] = {}
        for path, profile in records:
            display = str(profile.get("display_name") or profile.get("bike_profile_id") or path.stem).strip()
            profile_id = str(profile.get("bike_profile_id") or path.stem).strip()
            label = f"{display} ({profile_id})" if profile_id and profile_id != display else display
            if label in choice_map:
                label = f"{label} [{path.name}]"
            suffix = 2
            base_label = label
            while label in choice_map:
                label = f"{base_label} #{suffix}"
                suffix += 1
            choices.append(label)
            choice_map[label] = (path, profile)
        return choices, choice_map

    def _choose_bike_profile_dialog(self, *, source: Any, title: str) -> Optional[tuple[Path, dict[str, Any]]]:
        choices, choice_map = self._managed_library_bike_profile_choices(source.library_id)
        if not choices:
            messagebox.showinfo(
                _APP_DISPLAY_NAME,
                "No shared bike profiles are available in this workspace.",
                parent=self.root,
            )
            return None

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        selected = tk.StringVar(value=choices[0])
        try:
            current_path, _current_profile = load_source_bike_profile(source.source_root)
        except Exception:
            current_path = None
        if current_path is not None:
            for label, (path, _profile) in choice_map.items():
                if path == current_path:
                    selected.set(label)
                    break

        ttk.Label(dialog, text="Choose the shared bike profile for this source.", justify="left").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )
        combo = ttk.Combobox(dialog, textvariable=selected, values=choices, state="readonly", width=64)
        combo.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        result: dict[str, Optional[tuple[Path, dict[str, Any]]]] = {"profile": None}

        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="e", padx=12, pady=(0, 12))

        def accept() -> None:
            result["profile"] = choice_map.get(selected.get())
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Apply", command=accept).grid(row=0, column=1)
        combo.focus_set()
        self.root.wait_window(dialog)
        return result["profile"]

    def _unique_library_bike_profile_path(self, profiles_dir: Path, profile: Mapping[str, Any]) -> Path:
        candidate = profiles_dir / bike_profile_filename(profile)
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix_text = candidate.suffix
        suffix = 2
        while True:
            candidate = profiles_dir / f"{stem}-{suffix}{suffix_text}"
            if not candidate.exists():
                return candidate
            suffix += 1

    def _change_selected_source_library(self) -> None:
        if not self._guard_watch_inactive(action_label="Change Target Library"):
            return
        try:
            source = self._selected_managed_source_config()
            target_library_id = self._choose_library_id_dialog(current_library_id=source.library_id)
            if target_library_id is None or target_library_id == source.library_id:
                return
            self.controller.set_source_library(source.source_id, target_library_id)
            sync_source_bike_setup_preset(source.source_root)
        except Exception as exc:
            self._set_manager_status(f"Change target library failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        if self.sources_tree is not None and self.sources_tree.exists(source.source_id):
            self.sources_tree.selection_set(source.source_id)
        self._set_manager_status(f"Source '{source.source_id}' now targets library '{target_library_id}'.")

    def _assign_selected_bike_profile(self) -> None:
        if not self._guard_watch_inactive(action_label="Assign Bike Profile"):
            return
        try:
            source = self._selected_managed_source_config()
            selected = self._choose_bike_profile_dialog(source=source, title="Assign Bike Profile")
            if selected is None:
                return
            profile_path, profile = selected
            self.controller.set_source_bike_profile(source.source_id, profile_path)
            sync_source_bike_setup_preset(source.source_root)
        except Exception as exc:
            self._set_manager_status(f"Assign bike profile failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        if self.sources_tree is not None and self.sources_tree.exists(source.source_id):
            self.sources_tree.selection_set(source.source_id)
        profile_name = str(profile.get("display_name") or profile.get("bike_profile_id") or profile_path.stem)
        self._set_manager_status(f"Assigned bike profile '{profile_name}' to source '{source.source_id}'.")

    def _assign_selected_preprocess_profile(self) -> None:
        if not self._guard_watch_inactive(action_label="Assign Preprocess Profile"):
            return
        try:
            source = self._selected_managed_source_config()
            source_config = load_import_source_config(source.source_root)
            current_path = source_config.preprocess_profile_path
            initialdir = current_path if current_path.is_dir() else current_path.parent
            if not initialdir.exists():
                initialdir = source.source_root
            profile_path_text = filedialog.askopenfilename(
                title="Assign Preprocess Profile",
                initialdir=str(initialdir),
                initialfile="" if current_path.is_dir() else current_path.name,
                filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
                parent=self.root,
            )
            if not profile_path_text:
                return
            profile_path = Path(profile_path_text)
            self.controller.set_source_preprocess_profile(source.source_id, profile_path)
        except Exception as exc:
            self._set_manager_status(f"Assign preprocess profile failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        if self.sources_tree is not None and self.sources_tree.exists(source.source_id):
            self.sources_tree.selection_set(source.source_id)
        self._set_manager_status(
            f"Assigned preprocess profile '{profile_path.name}' to source '{source.source_id}'."
        )

    def _duplicate_selected_bike_profile(self) -> None:
        if not self._guard_watch_inactive(action_label="Duplicate Bike Profile"):
            return
        try:
            source = self._selected_managed_source_config()
            _current_path, current_profile = load_source_bike_profile(source.source_root)
            default_name = str(current_profile.get("display_name") or "Bike Profile").strip()
            requested_name = simpledialog.askstring(
                "Duplicate Bike Profile",
                "New bike profile name:",
                initialvalue=f"{default_name} Copy",
                parent=self.root,
            )
            if requested_name is None:
                return
            display_name = requested_name.strip()
            if not display_name:
                raise ValueError("Bike profile name must be a non-empty string")
            library = self._managed_library_config(source.library_id)
            profiles_dir = library_bike_profiles_dir(library.artifacts_dir)
            existing_ids = [
                str(profile.get("bike_profile_id"))
                for _path, profile in discover_bike_profiles(profiles_dir)
                if str(profile.get("bike_profile_id") or "").strip()
            ]
            updated_profile = copy.deepcopy(dict(current_profile))
            updated_profile["display_name"] = display_name
            updated_profile["bike_profile_id"] = derive_profile_id(
                display_name,
                existing_ids=existing_ids,
                fallback="bike-profile",
            )
            target_path = self._unique_library_bike_profile_path(profiles_dir, updated_profile)
            save_bike_profile_path(target_path, updated_profile)
        except Exception as exc:
            self._set_manager_status(f"Duplicate bike profile failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._set_manager_status(
            f"Created bike profile '{display_name}'. Use Assign bike profile to select it for a source."
        )

    def _managed_source_asset_choices(
        self,
        *,
        exclude_source_id: str,
        loader: Callable[[Path], tuple[Path, dict[str, Any]]],
        label_fields: Sequence[str],
    ) -> tuple[list[str], dict[str, tuple[Any, dict[str, Any]]]]:
        choices: list[str] = []
        choice_map: dict[str, tuple[Any, dict[str, Any]]] = {}
        for candidate in self.controller.require_config().sources:
            if candidate.source_id == exclude_source_id:
                continue
            try:
                _path, payload = loader(candidate.source_root)
            except Exception:
                continue
            display = next(
                (
                    str(payload.get(field)).strip()
                    for field in label_fields
                    if str(payload.get(field) or "").strip()
                ),
                candidate.display_name,
            )
            label = f"{display} ({candidate.display_name})"
            if label in choice_map:
                label = f"{display} ({candidate.display_name}, {candidate.source_id})"
            suffix = 2
            base_label = label
            while label in choice_map:
                label = f"{base_label} #{suffix}"
                suffix += 1
            choices.append(label)
            choice_map[label] = (candidate, payload)
        return choices, choice_map

    def _edit_selected_bike_profile(self) -> None:
        if not self._guard_watch_inactive(action_label="Edit Bike Profile"):
            return
        try:
            source = self._selected_managed_source_config()
            _profile_path, profile = load_source_bike_profile(source.source_root)
            form_values = bike_profile_form_values(profile)
            transform = rear_wheel_lut_from_profile(profile)
            if transform is None:
                shock_travel = float(form_values.get("rear_shock_travel_mm") or 1.0)
                wheel_travel = float(form_values.get("rear_wheel_travel_mm") or shock_travel)
                lut_rows = normalize_rear_lut_with_endpoints(
                    [],
                    rear_shock_travel_mm=shock_travel,
                    rear_wheel_travel_mm=wheel_travel,
                )
                lut_options = {"enabled": True, "interpolation": "linear", "extrapolation": "linear"}
            else:
                lut_rows = normalize_rear_lut_with_endpoints(
                    transform.get("lut", []),
                    rear_shock_travel_mm=form_values.get("rear_shock_travel_mm") or 1.0,
                    rear_wheel_travel_mm=form_values.get("rear_wheel_travel_mm") or 1.0,
                )
                lut_options = {
                    "enabled": bool(transform.get("enabled", True)),
                    "interpolation": str(transform.get("interpolation", "linear")),
                    "extrapolation": str(transform.get("extrapolation", "linear")),
                }
        except Exception as exc:
            self._set_manager_status(f"Open bike profile failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        if Sheet is None:
            messagebox.showerror(
                _APP_DISPLAY_NAME,
                "The editable LUT table requires the 'tksheet' package. Install requirements and restart the manager.",
                parent=self.root,
            )
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Bike Profile - {source.display_name}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        profile_state: dict[str, dict[str, Any]] = {"profile": profile}
        lut_input_unit_var = tk.StringVar(value=str(form_values.get("rear_shock_lut_input_unit") or "mm"))

        field_defs = [
            ("Display name", "display_name"),
            ("Description", "description"),
            ("Manufacturer", "manufacturer"),
            ("Model", "model"),
            ("Model year", "model_year"),
            ("Wheel size", "wheel_size"),
            ("Bike notes", "bike_notes"),
            ("Front fork travel (mm)", "front_fork_travel_mm"),
            ("Steering head angle (deg)", "front_head_angle_deg"),
            ("Rear sensor input range", "rear_shock_travel_mm"),
            ("Rear wheel travel (mm)", "rear_wheel_travel_mm"),
        ]
        variables: dict[str, tk.StringVar] = {}
        field_labels: dict[str, ttk.Label] = {}

        form = ttk.Frame(dialog, padding=(12, 12, 12, 4))
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        bike_choices, bike_choice_map = self._managed_library_bike_profile_choices(source.library_id)
        bike_create_from_var = tk.StringVar(value=bike_choices[0] if bike_choices else "")
        ttk.Label(form, text="Load from").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        create_from_frame = ttk.Frame(form)
        create_from_frame.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        create_from_frame.columnconfigure(0, weight=1)
        bike_create_combo = ttk.Combobox(
            create_from_frame,
            textvariable=bike_create_from_var,
            values=bike_choices,
            state="readonly" if bike_choices else "disabled",
        )
        bike_create_combo.grid(row=0, column=0, sticky="ew")
        field_start_row = 1
        for row, (label, key) in enumerate(field_defs, start=field_start_row):
            label_widget = ttk.Label(form, text=label)
            label_widget.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            field_labels[key] = label_widget
            var = tk.StringVar(value=str(form_values.get(key, "")))
            variables[key] = var
            ttk.Entry(form, textvariable=var).grid(row=row, column=1, sticky="ew", pady=3)

        unit_row = field_start_row + len(field_defs)
        ttk.Label(form, text="Rear LUT input unit").grid(row=unit_row, column=0, sticky="w", padx=(0, 8), pady=(8, 3))
        unit_frame = ttk.Frame(form)
        unit_frame.grid(row=unit_row, column=1, sticky="w", pady=(8, 3))
        ttk.Radiobutton(unit_frame, text="mm", variable=lut_input_unit_var, value="mm").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(unit_frame, text="deg", variable=lut_input_unit_var, value="deg").grid(
            row=0,
            column=1,
            sticky="w",
            padx=(12, 0),
        )

        def current_note_profile_label() -> str:
            try:
                _note_path, note_template = load_source_session_note_template(source.source_root)
            except Exception as exc:
                return f"Unavailable: {exc}"
            return str(
                note_template.get("title")
                or note_template.get("template_id")
                or "Source bike setup"
            )

        note_row = unit_row + 1
        note_name_var = tk.StringVar(value=current_note_profile_label())
        ttk.Label(form, text="Note profile").grid(row=note_row, column=0, sticky="w", padx=(0, 8), pady=(8, 3))
        note_frame = ttk.Frame(form)
        note_frame.grid(row=note_row, column=1, sticky="ew", pady=(8, 3))
        note_frame.columnconfigure(0, weight=1)
        ttk.Entry(note_frame, textvariable=note_name_var, state="readonly").grid(row=0, column=0, sticky="ew")

        lut_frame = ttk.LabelFrame(dialog, text="Rear Wheel LUT", padding=8)
        lut_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 0))
        lut_frame.columnconfigure(0, weight=1)
        lut_frame.rowconfigure(1, weight=1)
        ttk.Label(
            lut_frame,
            text="Map rear sensor travel to rear wheel travel. Select a row to edit it, or insert a new row before the selection.",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        table_frame = ttk.Frame(lut_frame)
        table_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        lut_sheet = Sheet(
            table_frame,
            headers=[f"sensor {lut_input_unit_var.get() if lut_input_unit_var.get() == 'deg' else 'mm'}", "Wheel mm"],
            data=[[f"{point['input']:g}", f"{point['output']:g}"] for point in lut_rows],
            width=300,
            height=210,
            show_row_index=True,
            show_header=True,
            show_x_scrollbar=False,
            show_y_scrollbar=True,
            default_column_width=120,
        )
        lut_sheet.grid(row=0, column=0, sticky="nsew")
        lut_sheet.enable_bindings(
            "single_select",
            "row_select",
            "drag_select",
            "column_width_resize",
            "row_height_resize",
            "arrowkeys",
            "right_click_popup_menu",
            "rc_select",
            "copy",
            "cut",
            "paste",
            "delete",
            "undo",
            "edit_cell",
        )

        graph_canvas = tk.Canvas(lut_frame, width=280, height=180, bg="white", highlightthickness=1)
        graph_canvas.grid(row=1, column=1, sticky="ne")

        edit_frame = ttk.Frame(lut_frame)
        edit_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        edit_frame.columnconfigure(2, weight=1)

        def _format_lut_value(value: Any) -> str:
            try:
                return f"{float(value):g}"
            except (TypeError, ValueError):
                return str(value)

        def rear_travel_values() -> tuple[float, float]:
            try:
                shock = float(variables["rear_shock_travel_mm"].get())
                wheel = float(variables["rear_wheel_travel_mm"].get())
            except (TypeError, ValueError):
                raise ValueError("Rear sensor travel and rear wheel travel must be numeric") from None
            if not math.isfinite(shock) or shock <= 0.0:
                raise ValueError("Rear sensor travel must be greater than zero")
            if not math.isfinite(wheel) or wheel <= 0.0:
                raise ValueError("Rear wheel travel must be greater than zero")
            return shock, wheel

        def lut_input_unit() -> str:
            return "deg" if str(lut_input_unit_var.get()).strip().lower() == "deg" else "mm"

        def apply_lut_unit_labels(*_args: Any) -> None:
            unit = lut_input_unit()
            rear_label = field_labels.get("rear_shock_travel_mm")
            if rear_label is not None:
                rear_label.configure(text=f"Rear sensor input range ({unit})")
            try:
                lut_sheet.headers([f"sensor {unit}", "Wheel mm"], redraw=True)
            except Exception:
                pass
            render_lut_graph()

        def apply_lut_endpoint_state() -> None:
            total_rows = lut_sheet.get_total_rows()
            if total_rows < 2:
                shock, wheel = rear_travel_values()
                lut_sheet.set_sheet_data(
                    [["0", "0"], [_format_lut_value(shock), _format_lut_value(wheel)]],
                    redraw=False,
                )
                total_rows = 2
            try:
                shock, wheel = rear_travel_values()
            except Exception:
                return
            all_rows = list(range(total_rows))
            if all_rows:
                lut_sheet.readonly_rows(all_rows, readonly=False, redraw=False)
                lut_sheet.dehighlight_rows("all", redraw=False)
            lut_sheet.set_cell_data(0, 0, "0", redraw=False)
            lut_sheet.set_cell_data(0, 1, "0", redraw=False)
            last_row = total_rows - 1
            lut_sheet.set_cell_data(last_row, 0, _format_lut_value(shock), redraw=False)
            lut_sheet.set_cell_data(last_row, 1, _format_lut_value(wheel), redraw=False)
            lut_sheet.readonly_rows([0, last_row], readonly=True, redraw=False)
            lut_sheet.highlight_rows([0, last_row], bg="#f1f5f7", fg="#444444", redraw=False)
            lut_sheet.redraw()

        def set_lut_sheet_rows(points: Sequence[Mapping[str, Any]]) -> None:
            try:
                shock, wheel = rear_travel_values()
                rows = normalize_rear_lut_with_endpoints(
                    points,
                    rear_shock_travel_mm=shock,
                    rear_wheel_travel_mm=wheel,
                )
            except Exception:
                rows = list(points)
            lut_sheet.set_sheet_data(
                [[_format_lut_value(point.get("input")), _format_lut_value(point.get("output"))] for point in rows],
                redraw=False,
            )
            apply_lut_endpoint_state()
            render_lut_graph()

        def sync_lut_endpoints_from_travel(*_args: Any) -> None:
            try:
                apply_lut_endpoint_state()
            except Exception:
                return
            render_lut_graph()

        def selected_lut_index() -> Optional[int]:
            rows = sorted(lut_sheet.get_selected_rows())
            if rows:
                return int(rows[0])
            selected = lut_sheet.get_currently_selected()
            row = getattr(selected, "row", None)
            return int(row) if isinstance(row, int) and row >= 0 else None

        def current_lut_rows() -> list[dict[str, float]]:
            rows: list[dict[str, float]] = []
            for row_number, raw_row in enumerate(lut_sheet.get_sheet_data(), start=1):
                if len(raw_row) < 2:
                    raise ValueError(f"LUT row {row_number} must contain sensor and wheel values")
                if str(raw_row[0]).strip() == "" and str(raw_row[1]).strip() == "":
                    continue
                try:
                    point = {"input": float(raw_row[0]), "output": float(raw_row[1])}
                except (TypeError, ValueError):
                    raise ValueError(f"LUT row {row_number} values must be numeric") from None
                if not all(math.isfinite(value) for value in point.values()):
                    raise ValueError(f"LUT row {row_number} values must be finite")
                rows.append(point)
            shock, wheel = rear_travel_values()
            return normalize_rear_lut_with_endpoints(
                rows,
                rear_shock_travel_mm=shock,
                rear_wheel_travel_mm=wheel,
            )

        def render_lut_graph() -> None:
            graph_canvas.delete("all")
            width = max(int(graph_canvas.winfo_width() or 280), 120)
            height = max(int(graph_canvas.winfo_height() or 180), 100)
            margin_left = 42
            margin_bottom = 28
            margin_top = 16
            margin_right = 14
            x0 = margin_left
            y0 = height - margin_bottom
            x1 = width - margin_right
            y1 = margin_top
            graph_canvas.create_line(x0, y0, x1, y0, fill="#777777")
            graph_canvas.create_line(x0, y0, x0, y1, fill="#777777")
            graph_canvas.create_text(
                (x0 + x1) / 2,
                height - 9,
                text=f"Sensor {lut_input_unit()}",
                fill="#555555",
                font=("TkDefaultFont", 8),
            )
            graph_canvas.create_text(14, (y0 + y1) / 2, text="Wheel", fill="#555555", font=("TkDefaultFont", 8), angle=90)
            try:
                points = current_lut_rows()
            except Exception:
                graph_canvas.create_text(
                    (x0 + x1) / 2,
                    (y0 + y1) / 2,
                    text="LUT needs increasing numeric rows",
                    fill="#9a4a00",
                    font=("TkDefaultFont", 8),
                )
                return
            xs = [point["input"] for point in points]
            ys = [point["output"] for point in points]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            if max_x == min_x:
                max_x = min_x + 1.0
            if max_y == min_y:
                max_y = min_y + 1.0

            def scale(point: Mapping[str, float]) -> tuple[float, float]:
                x = x0 + ((point["input"] - min_x) / (max_x - min_x)) * (x1 - x0)
                y = y0 - ((point["output"] - min_y) / (max_y - min_y)) * (y0 - y1)
                return x, y

            coords: list[float] = []
            for point in points:
                x, y = scale(point)
                coords.extend([x, y])
                graph_canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#1f6f8b", outline="")
            if len(coords) >= 4:
                graph_canvas.create_line(*coords, fill="#1f6f8b", width=2)
            graph_canvas.create_text(x0, y0 + 10, text=f"{min_x:g}", anchor="w", fill="#666666", font=("TkDefaultFont", 7))
            graph_canvas.create_text(x1, y0 + 10, text=f"{max_x:g}", anchor="e", fill="#666666", font=("TkDefaultFont", 7))
            graph_canvas.create_text(x0 - 4, y0, text=f"{min_y:g}", anchor="e", fill="#666666", font=("TkDefaultFont", 7))
            graph_canvas.create_text(x0 - 4, y1, text=f"{max_y:g}", anchor="e", fill="#666666", font=("TkDefaultFont", 7))

        def add_lut_row() -> None:
            index = max(lut_sheet.get_total_rows() - 1, 1)
            lut_sheet.insert_row(row=["", ""], idx=index, undo=True, emit_event=True)
            apply_lut_endpoint_state()
            row = index
            lut_sheet.select_cell(row, 0)
            render_lut_graph()

        def insert_lut_row() -> None:
            index = selected_lut_index()
            if index is None:
                index = max(lut_sheet.get_total_rows() - 1, 1)
            else:
                index = min(max(index, 1), max(lut_sheet.get_total_rows() - 1, 1))
            lut_sheet.insert_row(row=["", ""], idx=index, undo=True, emit_event=True)
            apply_lut_endpoint_state()
            lut_sheet.select_cell(index, 0)
            render_lut_graph()

        def delete_lut_row() -> None:
            index = selected_lut_index()
            if index is None:
                messagebox.showinfo(_APP_DISPLAY_NAME, "Select a LUT row to delete.", parent=dialog)
                return
            if index == 0 or index == lut_sheet.get_total_rows() - 1:
                messagebox.showinfo(
                    _APP_DISPLAY_NAME,
                    "The first and last LUT rows are set from rear sensor and rear wheel travel.",
                    parent=dialog,
                )
                return
            lut_sheet.delete_rows([index], undo=True, emit_event=True)
            apply_lut_endpoint_state()
            if lut_sheet.get_total_rows():
                lut_sheet.select_cell(min(index, lut_sheet.get_total_rows() - 1), 0)
            render_lut_graph()

        def load_bike_profile_into_editor(new_profile: Mapping[str, Any]) -> None:
            profile_state["profile"] = copy.deepcopy(dict(new_profile))
            values = bike_profile_form_values(profile_state["profile"])
            for key, var in variables.items():
                var.set(str(values.get(key, "")))
            lut_input_unit_var.set(str(values.get("rear_shock_lut_input_unit") or "mm"))
            transform_payload = rear_wheel_lut_from_profile(profile_state["profile"])
            if transform_payload is None:
                set_lut_sheet_rows([])
            else:
                set_lut_sheet_rows(transform_payload.get("lut", []))
            apply_lut_unit_labels()

        def create_bike_from_selected() -> None:
            selected_label = bike_create_from_var.get()
            if not selected_label:
                return
            candidate = bike_choice_map.get(selected_label)
            if candidate is None:
                return
            candidate_path, candidate_profile = candidate
            if not messagebox.askyesno(
                _APP_DISPLAY_NAME,
                f"Replace the bike profile currently shown with '{candidate_profile.get('display_name')}' "
                f"from '{candidate_path.name}'?",
                parent=dialog,
            ):
                return
            load_bike_profile_into_editor(candidate_profile)

        ttk.Button(
            create_from_frame,
            text="Load",
            command=create_bike_from_selected,
            state=("normal" if bike_choices else "disabled"),
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        ttk.Button(edit_frame, text="Add Row", command=add_lut_row).grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Button(edit_frame, text="Insert Before Selected", command=insert_lut_row).grid(row=0, column=1, sticky="w", padx=(0, 6))
        ttk.Button(edit_frame, text="Delete Selected Row", command=delete_lut_row).grid(row=0, column=2, sticky="w")
        lut_sheet.extra_bindings("all_modified_events", lambda _event: render_lut_graph())
        graph_canvas.bind("<Configure>", lambda _event: render_lut_graph())
        variables["rear_shock_travel_mm"].trace_add("write", sync_lut_endpoints_from_travel)
        variables["rear_wheel_travel_mm"].trace_add("write", sync_lut_endpoints_from_travel)
        lut_input_unit_var.trace_add("write", apply_lut_unit_labels)
        set_lut_sheet_rows(lut_rows)
        if lut_rows:
            lut_sheet.select_cell(0, 0)
        apply_lut_unit_labels()
        render_lut_graph()

        saved = {"ok": False}
        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="e", padx=12, pady=(10, 12))

        def save_profile() -> bool:
            try:
                values = {key: var.get() for key, var in variables.items()}
                values["rear_shock_lut_input_unit"] = lut_input_unit()
                updated = apply_bike_profile_form_values(profile_state["profile"], values)
                updated = set_rear_wheel_lut_transform(
                    updated,
                    current_lut_rows(),
                    input_unit=lut_input_unit(),
                    enabled=bool(lut_options["enabled"]),
                    interpolation=str(lut_options["interpolation"]),
                    extrapolation=str(lut_options["extrapolation"]),
                )
                save_source_bike_profile(source.source_root, updated)
                sync_source_bike_setup_preset(source.source_root)
            except Exception as exc:
                messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=dialog)
                return False
            profile_state["profile"] = updated
            saved["ok"] = True
            return True

        def save_and_close() -> None:
            if save_profile():
                dialog.destroy()

        def edit_note_profile() -> None:
            if not save_profile():
                return

            def open_note_profile() -> None:
                self._set_manager_status(f"Opening note profile for source '{source.source_id}'.")
                try:
                    dialog.grab_release()
                except Exception:
                    pass
                try:
                    dialog.withdraw()
                except Exception:
                    pass
                try:
                    self._edit_selected_note_template(parent=self.root, source=source)
                except Exception as exc:
                    self._set_manager_status(f"Open note profile failed: {exc}")
                    messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
                try:
                    dialog.deiconify()
                    dialog.lift()
                    dialog.focus_force()
                    dialog.grab_set()
                except Exception:
                    pass
                note_name_var.set(current_note_profile_label())

            dialog.after_idle(open_note_profile)

        ttk.Button(note_frame, text="Edit Note Profile", command=edit_note_profile).grid(
            row=0,
            column=1,
            sticky="e",
            padx=(8, 0),
        )
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Save", command=save_and_close).grid(row=0, column=1)
        self.root.wait_window(dialog)
        if saved["ok"]:
            self._set_manager_status(f"Saved bike profile for source '{source.source_id}'.")

    def _edit_selected_rear_lut(self) -> None:
        if not self._guard_watch_inactive(action_label="Edit Rear LUT"):
            return
        try:
            source = self._selected_managed_source_config()
            _profile_path, profile = load_source_bike_profile(source.source_root)
            transform = rear_wheel_lut_from_profile(profile)
            values = bike_profile_form_values(profile)
            input_unit = str(values.get("rear_shock_lut_input_unit") or "mm")
            if transform is None:
                shock_travel = float(values.get("rear_shock_travel_mm") or 1.0)
                wheel_travel = float(values.get("rear_wheel_travel_mm") or shock_travel)
                points = [{"input": 0.0, "output": 0.0}, {"input": shock_travel, "output": wheel_travel}]
                initial_text = format_lut_text(points)
                interpolation = "linear"
                extrapolation = "linear"
                enabled = True
            else:
                initial_text = format_lut_text(transform.get("lut", []))
                interpolation = str(transform.get("interpolation", "linear"))
                extrapolation = str(transform.get("extrapolation", "linear"))
                enabled = bool(transform.get("enabled", True))
        except Exception as exc:
            self._set_manager_status(f"Open rear LUT failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Rear Wheel LUT - {source.display_name}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(2, weight=1)

        input_unit_var = tk.StringVar(value="deg" if input_unit == "deg" else "mm")
        instruction_var = tk.StringVar(
            value=f"Enter one LUT point per line as: rear sensor {input_unit_var.get()}, rear wheel mm"
        )
        ttk.Label(
            dialog,
            textvariable=instruction_var,
            justify="left",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        options = ttk.Frame(dialog)
        options.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        enabled_var = tk.BooleanVar(value=enabled)
        interpolation_var = tk.StringVar(value=interpolation)
        extrapolation_var = tk.StringVar(value=extrapolation)
        ttk.Checkbutton(options, text="Enabled", variable=enabled_var).grid(row=0, column=0, sticky="w")
        ttk.Label(options, text="Input").grid(row=0, column=1, sticky="w", padx=(18, 6))
        ttk.Radiobutton(options, text="mm", variable=input_unit_var, value="mm").grid(row=0, column=2, sticky="w")
        ttk.Radiobutton(options, text="deg", variable=input_unit_var, value="deg").grid(
            row=0,
            column=3,
            sticky="w",
            padx=(8, 0),
        )
        ttk.Label(options, text="Interpolation").grid(row=0, column=4, sticky="w", padx=(18, 6))
        ttk.Combobox(
            options,
            textvariable=interpolation_var,
            values=("linear", "nearest"),
            state="readonly",
            width=10,
        ).grid(row=0, column=5, sticky="w")
        ttk.Label(options, text="Extrapolation").grid(row=0, column=6, sticky="w", padx=(18, 6))
        ttk.Combobox(
            options,
            textvariable=extrapolation_var,
            values=("linear", "clamp", "error"),
            state="readonly",
            width=10,
        ).grid(row=0, column=7, sticky="w")
        input_unit_var.trace_add(
            "write",
            lambda *_args: instruction_var.set(
                f"Enter one LUT point per line as: rear sensor {input_unit_var.get()}, rear wheel mm"
            ),
        )

        text_frame = ttk.Frame(dialog)
        text_frame.grid(row=2, column=0, sticky="nsew", padx=12)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        lut_text = tk.Text(text_frame, height=18, width=56, wrap="none")
        yscroll = ttk.Scrollbar(text_frame, orient="vertical", command=lut_text.yview)
        lut_text.configure(yscrollcommand=yscroll.set)
        lut_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        lut_text.insert("1.0", initial_text)

        saved = {"ok": False}
        buttons = ttk.Frame(dialog)
        buttons.grid(row=3, column=0, sticky="e", padx=12, pady=(10, 12))

        def save() -> None:
            try:
                points = parse_lut_text(lut_text.get("1.0", "end"))
                updated = set_rear_wheel_lut_transform(
                    profile,
                    points,
                    input_unit=input_unit_var.get(),
                    enabled=enabled_var.get(),
                    interpolation=interpolation_var.get(),
                    extrapolation=extrapolation_var.get(),
                )
                save_source_bike_profile(source.source_root, updated)
            except Exception as exc:
                messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=dialog)
                return
            saved["ok"] = True
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Save", command=save).grid(row=0, column=1)
        lut_text.focus_set()
        self.root.wait_window(dialog)
        if saved["ok"]:
            self._set_manager_status(f"Saved rear-wheel LUT for source '{source.source_id}'.")

    def _edit_selected_note_template(self, *, parent: Optional[tk.Misc] = None, source: Optional[Any] = None) -> bool:
        parent_window = parent or self.root
        if not self._guard_watch_inactive(action_label="Edit Note Template", parent=parent_window):
            return False
        try:
            if source is None:
                source = self._selected_managed_source_config()
            _template_path, template = load_source_session_note_template(source.source_root)
            catalog = load_session_note_field_catalog()
        except Exception as exc:
            self._set_manager_status(f"Open note template failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=parent_window)
            return False

        template_state = {"template": copy.deepcopy(dict(template))}
        base_catalog = [copy.deepcopy(dict(field)) for field in catalog if isinstance(field, Mapping)]
        dialog = tk.Toplevel(parent_window)
        dialog.title(f"Edit Note Template - {source.display_name}")
        dialog.transient(parent_window)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)
        dialog.rowconfigure(4, weight=1)

        title_var = tk.StringVar(value=str(template.get("title") or "Source bike setup"))
        description_var = tk.StringVar(value=str(template.get("description") or ""))
        allow_custom_var = tk.BooleanVar(value=bool(template.get("allow_custom_fields", True)))
        note_choices, note_choice_map = self._managed_source_asset_choices(
            exclude_source_id=source.source_id,
            loader=load_source_session_note_template,
            label_fields=("title", "template_id"),
        )
        note_create_from_var = tk.StringVar(value=note_choices[0] if note_choices else "")

        ttk.Label(dialog, text="Create from").grid(row=0, column=0, sticky="w", padx=(12, 8), pady=(12, 3))
        note_create_frame = ttk.Frame(dialog)
        note_create_frame.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 3))
        note_create_frame.columnconfigure(0, weight=1)
        ttk.Combobox(
            note_create_frame,
            textvariable=note_create_from_var,
            values=note_choices,
            state="readonly" if note_choices else "disabled",
        ).grid(row=0, column=0, sticky="ew")

        rows = [
            ("Title", title_var),
            ("Description", description_var),
        ]
        for row, (label, var) in enumerate(rows, start=1):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=(12, 8), pady=3)
            ttk.Entry(dialog, textvariable=var).grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=3)
        ttk.Checkbutton(dialog, text="Allow custom fields", variable=allow_custom_var).grid(
            row=3, column=1, sticky="w", padx=(0, 12), pady=(4, 8)
        )

        fields_frame = ttk.LabelFrame(dialog, text="Fields", padding=6)
        fields_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=12)
        fields_frame.columnconfigure(0, weight=1)
        fields_frame.rowconfigure(0, weight=1)
        canvas = tk.Canvas(fields_frame, height=280, highlightthickness=0)
        scrollbar = ttk.Scrollbar(fields_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        def configure_inner(_event: tk.Event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def configure_canvas(event: tk.Event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        inner.bind("<Configure>", configure_inner)
        canvas.bind("<Configure>", configure_canvas)

        catalog_items: list[dict[str, Any]] = []
        field_vars: dict[str, tk.BooleanVar] = {}
        default_vars: dict[str, tk.StringVar] = {}
        custom_frame_ref: dict[str, Optional[ttk.LabelFrame]] = {"frame": None}

        def reset_catalog_for_template(template_payload: Mapping[str, Any]) -> None:
            catalog_items.clear()
            catalog_items.extend(copy.deepcopy(base_catalog))
            known_ids = {str(field.get("field_id")) for field in catalog_items}
            for field in template_payload.get("fields", []) or []:
                if not isinstance(field, Mapping):
                    continue
                field_id = str(field.get("field_id") or "")
                if field_id and field_id not in known_ids:
                    catalog_items.append(copy.deepcopy(dict(field)))
                    known_ids.add(field_id)

        def collect_note_field_state() -> tuple[set[str], dict[str, str]]:
            selected = {field_id for field_id, var in field_vars.items() if var.get()}
            defaults = {field_id: var.get() for field_id, var in default_vars.items()}
            return selected, defaults

        def update_custom_block_visibility(*_args: Any) -> None:
            custom_frame = custom_frame_ref.get("frame")
            if custom_frame is None:
                return
            if allow_custom_var.get():
                custom_frame.grid()
            else:
                custom_frame.grid_remove()

        def add_note_field_row(
            *,
            parent: tk.Misc,
            row: int,
            field: Mapping[str, Any],
            current_ids: set[str],
            template_fields_by_id: Mapping[str, Mapping[str, Any]],
            default_overrides: Optional[Mapping[str, str]] = None,
        ) -> None:
            field_id = str(field.get("field_id"))
            label = str(field.get("label") or field_id)
            section = str(field.get("section") or "General")
            unit = field.get("unit")
            suffix = f" [{unit}]" if unit else ""
            var = tk.BooleanVar(value=field_id in current_ids)
            field_vars[field_id] = var
            selected_field = template_fields_by_id.get(field_id)
            default_value = (
                selected_field.get("default")
                if isinstance(selected_field, dict) and "default" in selected_field
                else field.get("default")
            )
            if default_overrides is not None and field_id in default_overrides:
                default_value = default_overrides[field_id]
            default_var = tk.StringVar(value="" if default_value is None else str(default_value))
            default_vars[field_id] = default_var
            ttk.Checkbutton(
                parent,
                text=f"{label}{suffix}",
                variable=var,
            ).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(parent, textvariable=default_var, width=24).grid(
                row=row,
                column=1,
                sticky="ew",
                padx=(12, 0),
                pady=2,
            )

        def note_field_section_key(field: Mapping[str, Any]) -> str:
            section = str(field.get("section") or "Overview").strip().lower()
            if section in {"front", "rear", "notes", "custom"}:
                return section
            if section in {"note"}:
                return "notes"
            return "overview"

        def render_note_fields(
            *,
            selected_override: Optional[set[str]] = None,
            default_overrides: Optional[Mapping[str, str]] = None,
        ) -> None:
            for child in inner.winfo_children():
                child.destroy()
            field_vars.clear()
            default_vars.clear()
            inner.columnconfigure(0, weight=1)
            template_payload = template_state["template"]
            template_fields_by_id = {
                str(field.get("field_id")): dict(field)
                for field in template_payload.get("fields", []) or []
                if isinstance(field, dict) and field.get("field_id")
            }
            current_ids = (
                set(selected_override)
                if selected_override is not None
                else {
                    str(field.get("field_id"))
                    for field in template_payload.get("fields", []) or []
                    if isinstance(field, dict) and field.get("field_id")
                }
            )
            grouped_fields: dict[str, list[dict[str, Any]]] = {
                "overview": [],
                "front": [],
                "rear": [],
                "notes": [],
                "custom": [],
            }
            for field in catalog_items:
                grouped_fields[note_field_section_key(field)].append(field)

            block_titles = {
                "overview": "Overview",
                "front": "Front",
                "rear": "Rear",
                "notes": "Notes",
                "custom": "Custom",
            }
            block_row = 0
            custom_frame: ttk.LabelFrame | None = None
            for key in ("overview", "front", "rear", "notes", "custom"):
                fields = grouped_fields[key]
                if key != "custom" and not fields:
                    continue
                if key == "custom" and not fields and not allow_custom_var.get():
                    continue
                block = ttk.LabelFrame(inner, text=block_titles[key], padding=6)
                block.grid(row=block_row, column=0, sticky="ew", pady=(0 if block_row == 0 else 10, 0))
                block.columnconfigure(0, weight=1)
                block.columnconfigure(1, weight=1)
                ttk.Label(block, text="Include").grid(row=0, column=0, sticky="w", pady=(0, 4))
                ttk.Label(block, text="Default value").grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 4))
                for row_index, field in enumerate(fields, start=1):
                    add_note_field_row(
                        parent=block,
                        row=row_index,
                        field=field,
                        current_ids=current_ids,
                        template_fields_by_id=template_fields_by_id,
                        default_overrides=default_overrides,
                    )
                if key == "custom":
                    custom_frame = block
                    custom_frame_ref["frame"] = block
                block_row += 1

            if custom_frame is None:
                custom_frame = ttk.LabelFrame(inner, text="Custom", padding=6)
                custom_frame.grid(row=block_row, column=0, sticky="ew", pady=(0 if block_row == 0 else 10, 0))
                custom_frame_ref["frame"] = custom_frame
            custom_frame.columnconfigure(1, weight=1)
            custom_frame.columnconfigure(3, weight=1)
            custom_frame_ref["frame"] = custom_frame
            custom_name_var = tk.StringVar()
            custom_default_var = tk.StringVar()
            create_row = len(grouped_fields["custom"]) + 1
            if grouped_fields["custom"]:
                ttk.Separator(custom_frame, orient="horizontal").grid(
                    row=create_row,
                    column=0,
                    columnspan=5,
                    sticky="ew",
                    pady=(8, 6),
                )
                create_row += 1
            ttk.Label(custom_frame, text="Field name").grid(row=create_row, column=0, sticky="w", padx=(0, 6))
            ttk.Entry(custom_frame, textvariable=custom_name_var, width=24).grid(
                row=create_row,
                column=1,
                sticky="ew",
                padx=(0, 12),
            )
            ttk.Label(custom_frame, text="Default value").grid(row=create_row, column=2, sticky="w", padx=(0, 6))
            ttk.Entry(custom_frame, textvariable=custom_default_var, width=24).grid(
                row=create_row,
                column=3,
                sticky="ew",
                padx=(0, 12),
            )

            def create_custom_field() -> None:
                try:
                    selected_ids, defaults = collect_note_field_state()
                    field = build_custom_session_note_field(
                        field_name=custom_name_var.get(),
                        default_value=custom_default_var.get(),
                        existing_ids=[str(item.get("field_id")) for item in catalog_items],
                    )
                except Exception as exc:
                    messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=dialog)
                    return
                catalog_items.append(field)
                field_id = str(field.get("field_id"))
                selected_ids.add(field_id)
                defaults[field_id] = "" if field.get("default") is None else str(field.get("default"))
                render_note_fields(selected_override=selected_ids, default_overrides=defaults)

            ttk.Button(custom_frame, text="Create", command=create_custom_field).grid(
                row=create_row,
                column=4,
                sticky="e",
            )
            update_custom_block_visibility()
            canvas.configure(scrollregion=canvas.bbox("all"))

        def create_note_from_selected() -> None:
            selected_label = note_create_from_var.get()
            if not selected_label:
                return
            candidate = note_choice_map.get(selected_label)
            if candidate is None:
                return
            candidate_source, candidate_template = candidate
            if not messagebox.askyesno(
                _APP_DISPLAY_NAME,
                f"Replace the note profile currently shown with '{candidate_template.get('title')}' "
                f"from source '{candidate_source.display_name}'?",
                parent=dialog,
            ):
                return
            template_state["template"] = copy.deepcopy(dict(candidate_template))
            title_var.set(str(candidate_template.get("title") or "Source bike setup"))
            description_var.set(str(candidate_template.get("description") or ""))
            allow_custom_var.set(bool(candidate_template.get("allow_custom_fields", True)))
            reset_catalog_for_template(template_state["template"])
            render_note_fields()

        ttk.Button(
            note_create_frame,
            text="Create",
            command=create_note_from_selected,
            state=("normal" if note_choices else "disabled"),
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        allow_custom_var.trace_add("write", update_custom_block_visibility)
        reset_catalog_for_template(template_state["template"])
        render_note_fields()

        saved = {"ok": False}
        buttons = ttk.Frame(dialog)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", padx=12, pady=(10, 12))

        def save() -> None:
            try:
                selected_field_ids = [field_id for field_id, var in field_vars.items() if var.get()]
                template_payload = template_state["template"]
                template_id = str(template_payload.get("template_id") or "").strip()
                if template_id in {"", "import_agent_bike_setup", "source_bike_setup"}:
                    template_id = derive_profile_id(title_var.get(), fallback="session-note-template")
                updated_template = build_session_note_template_from_field_ids(
                    field_ids=selected_field_ids,
                    template_id=template_id,
                    template_version=str(template_payload.get("template_version") or "1.0"),
                    title=title_var.get(),
                    description=description_var.get(),
                    allow_custom_fields=allow_custom_var.get(),
                    field_defaults={field_id: var.get() for field_id, var in default_vars.items()},
                    catalog=catalog_items,
                )
                preset_payload = None
                try:
                    _preset_path, existing_preset = load_source_bike_setup_preset(source.source_root)
                    preset_payload = dict(existing_preset)
                    preset_payload["values"] = {
                        str(field.get("field_id")): field.get("default")
                        for field in updated_template.get("fields", []) or []
                        if isinstance(field, dict) and "default" in field and field.get("default") is not None
                    }
                except Exception:
                    preset_payload = None
                save_source_session_note_assets(source.source_root, updated_template, preset=preset_payload)
            except Exception as exc:
                messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=dialog)
                return
            saved["ok"] = True
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Save", command=save).grid(row=0, column=1)
        dialog.lift(parent_window)
        dialog.focus_force()
        self.root.wait_window(dialog)
        if saved["ok"]:
            self._set_manager_status(f"Saved note template for source '{source.source_id}'.")
        return saved["ok"]

    def _copy_selected_bike_profile_from_source(self) -> None:
        self._duplicate_selected_bike_profile()

    def _copy_selected_note_template_from_source(self) -> None:
        if not self._guard_watch_inactive(action_label="Copy Note Template"):
            return
        try:
            target = self._selected_managed_source_config()
            source = self._choose_source_dialog(title="Copy Note Template", exclude_source_id=target.source_id)
            if source is None:
                return
            copy_source_note_assets(source.source_root, target.source_root)
        except Exception as exc:
            self._set_manager_status(f"Copy note template failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._set_manager_status(f"Copied note template from '{source.source_id}' to '{target.source_id}'.")

    def _offer_configure_source_after_creation(self, source_id: str) -> None:
        self._select_source_in_manager(source_id)
        if messagebox.askyesno(
            _APP_DISPLAY_NAME,
            "Open the bike-profile editor for this new source now? From there you can also edit the rear LUT and note template.",
            parent=self.root,
        ):
            self._edit_selected_bike_profile()

    def _on_sources_tree_click(self, event: tk.Event) -> Optional[str]:
        if self.sources_tree is None:
            return None
        region = self.sources_tree.identify("region", event.x, event.y)
        if region != "cell":
            return None
        column = self.sources_tree.identify_column(event.x)
        if column not in {"#1", "#2", "#8"}:
            return None
        source_id = self.sources_tree.identify_row(event.y)
        if not source_id:
            return None
        self.sources_tree.selection_set(source_id)
        if column == "#1":
            self._toggle_source_enabled(source_id)
        elif column == "#2":
            self._toggle_source_force_reprocess(source_id)
        else:
            self._toggle_source_session_note_attach(source_id)
        return "break"

    def _on_libraries_tree_click(self, event: tk.Event) -> Optional[str]:
        if self.libraries_tree is None:
            return None
        region = self.libraries_tree.identify("region", event.x, event.y)
        if region != "cell":
            return None
        if self.libraries_tree.identify_column(event.x) != "#2":
            return None
        library_id = self.libraries_tree.identify_row(event.y)
        if not library_id:
            return None
        self.libraries_tree.selection_set(library_id)
        self._toggle_library_syn_export(library_id)
        return "break"

    def _on_libraries_tree_context(self, event: tk.Event) -> Optional[str]:
        if self.libraries_tree is None:
            return None
        library_id = self.libraries_tree.identify_row(event.y)
        if not library_id:
            return None
        self.libraries_tree.selection_set(library_id)
        self.libraries_tree.focus(library_id)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Rename library", command=self._rename_selected_library)
        menu.add_command(label="Details", command=self._show_selected_library_details)
        menu.add_separator()
        menu.add_command(label="Remove Library", command=self._remove_selected_library)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _on_sources_tree_context(self, event: tk.Event) -> Optional[str]:
        if self.sources_tree is None:
            return None
        source_id = self.sources_tree.identify_row(event.y)
        if not source_id:
            return None
        self.sources_tree.selection_set(source_id)
        self.sources_tree.focus(source_id)
        try:
            source = self._managed_source_config(source_id)
        except Exception:
            return None

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Edit bike", command=self._edit_selected_bike_profile)
        menu.add_command(label="Assign bike profile", command=self._assign_selected_bike_profile)
        menu.add_command(label="Duplicate bike profile", command=self._duplicate_selected_bike_profile)
        menu.add_command(label="Assign preprocess profile", command=self._assign_selected_preprocess_profile)
        menu.add_command(label="Change target library", command=self._change_selected_source_library)
        menu.add_command(label="Import naming", command=self._edit_selected_source_naming)
        menu.add_command(label="Details", command=self._show_selected_source_details)
        if source.source_type == SOURCE_TYPE_LOGGER_WIFI:
            menu.add_separator()
            menu.add_command(label="Edit Wi-Fi settings", command=self._edit_selected_wifi_settings)
            menu.add_command(label="Check Logger", command=self._check_selected_logger)
            menu.add_command(label="Request Upload Mode", command=self._request_selected_upload_mode)
            menu.add_command(label="Open Logger Web UI", command=self._open_selected_logger_web_ui)
        menu.add_separator()
        menu.add_command(label="Validate", command=self._validate_sources)
        menu.add_command(label="Rename source", command=self._rename_selected_source)
        menu.add_command(label="Remove Source", command=self._remove_selected_source)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _choose_remove_mode_dialog(
        self,
        *,
        title: str,
        item_name: str,
        folder_path: Path,
        remove_only_text: str,
        delete_text: str,
        delete_note: str = "",
    ) -> Optional[bool]:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)

        ttk.Label(dialog, text=item_name, justify="left").grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6)
        )
        mode_var = tk.StringVar(value="remove")
        ttk.Radiobutton(
            dialog,
            text="Remove from Import Manager only",
            variable=mode_var,
            value="remove",
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(6, 0))
        ttk.Label(dialog, text=remove_only_text, wraplength=640, justify="left").grid(
            row=2, column=0, sticky="ew", padx=34, pady=(2, 8)
        )
        ttk.Radiobutton(
            dialog,
            text="Remove from Import Manager and delete folder",
            variable=mode_var,
            value="delete",
        ).grid(row=3, column=0, sticky="w", padx=12, pady=(6, 0))
        ttk.Label(dialog, text=delete_text, wraplength=640, justify="left").grid(
            row=4, column=0, sticky="ew", padx=34, pady=(2, 4)
        )
        path_entry = ttk.Entry(dialog)
        path_entry.insert(0, str(folder_path))
        path_entry.configure(state="readonly")
        path_entry.grid(row=5, column=0, sticky="ew", padx=34, pady=(0, 8))
        if delete_note:
            ttk.Label(dialog, text=delete_note, wraplength=640, justify="left").grid(
                row=6, column=0, sticky="ew", padx=34, pady=(0, 8)
            )

        result: dict[str, Optional[bool]] = {"delete_files": None}

        def accept() -> None:
            result["delete_files"] = mode_var.get() == "delete"
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.grid(row=7, column=0, sticky="e", padx=12, pady=(8, 12))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Remove", command=accept).grid(row=0, column=1)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.lift(self.root)
        dialog.focus_force()
        self.root.wait_window(dialog)
        return result["delete_files"]

    def _confirm_delete_from_disk(self, *, title: str, folder_path: Path) -> bool:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)

        ttk.Label(
            dialog,
            text=(
                "This will permanently delete the folder below. "
                "This cannot be undone by BODAQS Import Manager."
            ),
            wraplength=640,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        path_entry = ttk.Entry(dialog)
        path_entry.insert(0, str(folder_path))
        path_entry.configure(state="readonly")
        path_entry.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        ttk.Label(dialog, text="Type DELETE to confirm.").grid(
            row=2, column=0, sticky="w", padx=12, pady=(4, 4)
        )
        confirm_var = tk.StringVar(value="")
        confirm_entry = ttk.Entry(dialog, textvariable=confirm_var)
        confirm_entry.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))
        result = {"ok": False}

        def accept() -> None:
            if confirm_var.get() != "DELETE":
                return
            result["ok"] = True
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.grid(row=4, column=0, sticky="e", padx=12, pady=(8, 12))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        delete_button = ttk.Button(buttons, text="Delete from disk", command=accept, state="disabled")
        delete_button.grid(row=0, column=1)

        def sync_delete_button(*_args: Any) -> None:
            delete_button.configure(state="normal" if confirm_var.get() == "DELETE" else "disabled")

        confirm_var.trace_add("write", sync_delete_button)
        dialog.bind("<Return>", lambda _event: accept())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.lift(self.root)
        dialog.focus_force()
        confirm_entry.focus_set()
        self.root.wait_window(dialog)
        return bool(result["ok"])

    def _show_details_dialog(self, *, title: str, rows: Sequence[tuple[str, str]]) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)
        for row, (label, value) in enumerate(rows):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=(12, 8), pady=(12 if row == 0 else 4, 4))
            entry = ttk.Entry(dialog)
            entry.insert(0, value)
            entry.configure(state="readonly")
            entry.grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=(12 if row == 0 else 4, 4))
        buttons = ttk.Frame(dialog)
        buttons.grid(row=len(rows), column=0, columnspan=2, sticky="e", padx=12, pady=(8, 12))
        ttk.Button(buttons, text="Close", command=dialog.destroy).grid(row=0, column=0)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.lift(self.root)
        dialog.focus_force()
        self.root.wait_window(dialog)

    def _show_selected_library_details(self) -> None:
        library_id = self._selected_library_id()
        if library_id is None:
            messagebox.showinfo(_APP_DISPLAY_NAME, "Select a library first.", parent=self.root)
            return
        try:
            library = self._managed_library_config(library_id)
        except Exception as exc:
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._show_details_dialog(
            title=f"Library Details - {library.display_name}",
            rows=(
                ("Library ID", str(library.library_id)),
                ("Artifacts Directory", str(library.artifacts_dir)),
            ),
        )

    def _show_selected_source_details(self) -> None:
        source_id = self._selected_source_id()
        if source_id is None:
            messagebox.showinfo(_APP_DISPLAY_NAME, "Select a source first.", parent=self.root)
            return
        try:
            source = self._managed_source_config(source_id)
            source_config = load_import_source_config(source.source_root)
        except Exception as exc:
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        session_naming = source_config.naming.session_description
        if session_naming.enabled and session_naming.mode == "base_index":
            naming_text = (
                f"{session_naming.base} + index "
                f"(start={session_naming.index_start}, padding={session_naming.index_padding})"
            )
        else:
            naming_text = "Default"
        self._show_details_dialog(
            title=f"Source Details - {source.display_name}",
            rows=(
                ("Source ID", str(source.source_id)),
                ("Library ID", str(source.library_id)),
                ("Source Root", str(source.source_root)),
                ("Preprocess Profile", str(source_config.preprocess_profile_path)),
                ("Session Naming", naming_text),
            ),
        )

    def _edit_selected_wifi_settings(self) -> None:
        if not self._guard_watch_inactive(action_label="Edit Wi-Fi Settings"):
            return
        try:
            source = self._selected_source_config()
        except Exception as exc:
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        if source.source_type != SOURCE_TYPE_LOGGER_WIFI or source.logger_wifi is None:
            messagebox.showinfo(_APP_DISPLAY_NAME, "Select a Wi-Fi logger source first.", parent=self.root)
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Wi-Fi Settings - {source.description or source.source_id}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)

        logger_id_var = tk.StringVar(value=source.logger_wifi.logger_id)
        fixed_address_var = tk.BooleanVar(value=bool(source.logger_wifi.base_url))
        address_var = tk.StringVar(value=source.logger_wifi.base_url or "")
        cleanup_label = next(
            (
                label
                for label, value in _LOGGER_WIFI_CLEANUP_BY_LABEL.items()
                if value == source.logger_wifi.cleanup_mode
            ),
            _LOGGER_WIFI_CLEANUP_LABELS[LOGGER_WIFI_CLEANUP_NONE],
        )
        cleanup_var = tk.StringVar(value=cleanup_label)
        request_timeout_var = tk.StringVar(value=f"{float(source.logger_wifi.request_timeout_s):g}")
        download_timeout_var = tk.StringVar(value=f"{float(source.logger_wifi.download_timeout_s):g}")
        status_var = tk.StringVar(value="Logger ID is the stable identity. Fixed address is optional.")

        ttk.Label(dialog, text="Logger ID").grid(row=0, column=0, sticky="w", padx=(12, 8), pady=(12, 4))
        ttk.Entry(dialog, textvariable=logger_id_var).grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 4))
        ttk.Button(dialog, text="Discover", command=lambda: discover()).grid(
            row=0, column=2, sticky="e", padx=(0, 12), pady=(12, 4)
        )

        ttk.Checkbutton(
            dialog,
            text="Use fixed logger address",
            variable=fixed_address_var,
            command=lambda: sync_fixed_address_state(),
        ).grid(row=1, column=1, sticky="w", padx=(0, 12), pady=4)

        ttk.Label(dialog, text="Fixed address").grid(row=2, column=0, sticky="w", padx=(12, 8), pady=4)
        address_entry = ttk.Entry(dialog, textvariable=address_var)
        address_entry.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=4)
        verify_button = ttk.Button(dialog, text="Verify", command=lambda: verify())
        verify_button.grid(row=2, column=2, sticky="e", padx=(0, 12), pady=4)

        ttk.Label(dialog, text="After import").grid(row=3, column=0, sticky="w", padx=(12, 8), pady=4)
        ttk.Combobox(
            dialog,
            textvariable=cleanup_var,
            values=list(_LOGGER_WIFI_CLEANUP_BY_LABEL),
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", padx=(0, 12), pady=4)

        timeouts = ttk.Frame(dialog)
        timeouts.grid(row=4, column=0, columnspan=3, sticky="w", padx=12, pady=(6, 2))
        ttk.Label(timeouts, text="Request timeout (s)").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(timeouts, textvariable=request_timeout_var, width=8).grid(row=0, column=1, sticky="w", padx=(0, 18))
        ttk.Label(timeouts, text="Download timeout (s)").grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Entry(timeouts, textvariable=download_timeout_var, width=8).grid(row=0, column=3, sticky="w")

        ttk.Label(dialog, textvariable=status_var, wraplength=720, justify="left").grid(
            row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=(8, 4)
        )

        def positive_float_from_text(text: str, *, field_name: str) -> float:
            try:
                value = float(text.strip())
            except ValueError:
                raise ValueError(f"{field_name} must be numeric") from None
            if value <= 0:
                raise ValueError(f"{field_name} must be > 0")
            return value

        def sync_fixed_address_state() -> None:
            state = "normal" if bool(fixed_address_var.get()) else "disabled"
            address_entry.configure(state=state)
            verify_button.configure(state=state)

        def payload_from_dialog() -> dict[str, Any]:
            logger_id = logger_id_var.get().strip()
            if not logger_id:
                raise ValueError("Logger ID must be non-empty.")
            fixed_address = bool(fixed_address_var.get())
            base_url = address_var.get().strip() if fixed_address else ""
            if fixed_address and not base_url:
                raise ValueError("Enter a fixed logger address, or turn off fixed address mode.")
            payload: dict[str, Any] = {
                "logger_id": logger_id,
                "request_timeout_s": positive_float_from_text(
                    request_timeout_var.get(),
                    field_name="Wi-Fi request timeout",
                ),
                "download_timeout_s": positive_float_from_text(
                    download_timeout_var.get(),
                    field_name="Wi-Fi download timeout",
                ),
                "cleanup_mode": _LOGGER_WIFI_CLEANUP_BY_LABEL.get(
                    cleanup_var.get().strip(),
                    LOGGER_WIFI_CLEANUP_NONE,
                ),
            }
            if base_url:
                payload["base_url"] = base_url
            return payload

        def discover() -> None:
            try:
                timeout_s = max(
                    1.0,
                    min(
                        positive_float_from_text(
                            request_timeout_var.get(),
                            field_name="Wi-Fi request timeout",
                        ),
                        5.0,
                    ),
                )
                wanted_logger_id = logger_id_var.get().strip() or None
                results = discover_logger_wifi_sources(
                    logger_id=wanted_logger_id,
                    timeout_s=timeout_s,
                    include_default_ap=True,
                    default_ap_timeout_s=1.0,
                )
                if not results:
                    status_var.set("No matching BODAQS Wi-Fi logger was discovered on the local network.")
                    return
                dialog.grab_release()
                try:
                    result = results[0] if len(results) == 1 else self._choose_discovered_logger(results)
                finally:
                    dialog.grab_set()
                if result is None:
                    status_var.set("Logger discovery cancelled.")
                    return
                if result.logger_id:
                    logger_id_var.set(result.logger_id)
                if fixed_address_var.get():
                    address_var.set(result.base_url)
                upload_text = "unknown" if result.upload_mode is None else ("yes" if result.upload_mode else "no")
                remember_text = "address remembered" if fixed_address_var.get() else "address not remembered"
                status_var.set(
                    f"Discovered {result.display_name or result.logger_id or result.hostname or 'logger'} "
                    f"at {result.base_url}; upload_mode={upload_text}; {remember_text}."
                )
            except Exception as exc:
                status_var.set(f"Discovery failed: {exc}")
                messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=dialog)

        def verify() -> None:
            try:
                if not fixed_address_var.get():
                    raise ValueError("Turn on fixed address mode before verifying a fixed address.")
                client = LoggerWifiApiClient(
                    address_var.get().strip(),
                    request_timeout_s=positive_float_from_text(
                        request_timeout_var.get(),
                        field_name="Wi-Fi request timeout",
                    ),
                    download_timeout_s=positive_float_from_text(
                        download_timeout_var.get(),
                        field_name="Wi-Fi download timeout",
                    ),
                )
                device = client.get_device()
                status = client.get_status()
                logger_id = str(device.get("logger_id") or "").strip()
                if not logger_id:
                    raise ValueError("Logger did not return a logger_id.")
                logger_id_var.set(logger_id)
                status_var.set(
                    f"Verified {device.get('display_name') or logger_id} ({logger_id}). "
                    + self._logger_status_text(
                        upload_mode=bool(status.get("upload_mode", False)),
                        session_count=status.get("importable_session_count"),
                    )
                )
            except Exception as exc:
                status_var.set(f"Verification failed: {exc}")
                messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=dialog)

        saved = {"ok": False}

        def save() -> None:
            try:
                payload = payload_from_dialog()
                self.controller.set_source_logger_wifi(source.source_id, payload)
            except Exception as exc:
                status_var.set(f"Save failed: {exc}")
                messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=dialog)
                return
            saved["ok"] = True
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", padx=12, pady=(8, 12))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Save", command=save).grid(row=0, column=1)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        sync_fixed_address_state()
        dialog.lift(self.root)
        dialog.focus_force()
        self.root.wait_window(dialog)

        if saved["ok"]:
            self._refresh_ui_from_config()
            if self.sources_tree is not None and self.sources_tree.exists(source.source_id):
                self.sources_tree.selection_set(source.source_id)
            self._set_manager_status(f"Updated Wi-Fi settings for source '{source.source_id}'.")

    def _rename_selected_library(self) -> None:
        if not self._guard_watch_inactive(action_label="Rename Library"):
            return
        library_id = self._selected_library_id()
        if library_id is None:
            messagebox.showinfo(_APP_DISPLAY_NAME, "Select a library first.", parent=self.root)
            return
        try:
            library = self._managed_library_config(library_id)
        except Exception as exc:
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        new_name = simpledialog.askstring(
            _APP_DISPLAY_NAME,
            "Library name",
            initialvalue=str(library.display_name),
            parent=self.root,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name or new_name == library.display_name:
            return
        try:
            self.controller.set_library_display_name(library.library_id, new_name)
        except Exception as exc:
            self._set_manager_status(f"Rename library failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        if self.libraries_tree is not None and self.libraries_tree.exists(library.library_id):
            self.libraries_tree.selection_set(library.library_id)
        self._set_manager_status(f"Renamed library '{library.library_id}' to '{new_name}'.")

    def _rename_selected_source(self) -> None:
        if not self._guard_watch_inactive(action_label="Rename Source"):
            return
        source_id = self._selected_source_id()
        if source_id is None:
            messagebox.showinfo(_APP_DISPLAY_NAME, "Select a source first.", parent=self.root)
            return
        try:
            source = self._managed_source_config(source_id)
        except Exception as exc:
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        new_name = simpledialog.askstring(
            _APP_DISPLAY_NAME,
            "Source name",
            initialvalue=str(source.display_name),
            parent=self.root,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name or new_name == source.display_name:
            return
        try:
            self.controller.set_source_display_name(source.source_id, new_name)
        except Exception as exc:
            self._set_manager_status(f"Rename source failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        if self.sources_tree is not None and self.sources_tree.exists(source.source_id):
            self.sources_tree.selection_set(source.source_id)
        self._set_manager_status(f"Renamed source '{source.source_id}' to '{new_name}'.")

    def _edit_selected_source_naming(self) -> None:
        if not self._guard_watch_inactive(action_label="Edit Import Naming"):
            return
        source_id = self._selected_source_id()
        if source_id is None:
            messagebox.showinfo(_APP_DISPLAY_NAME, "Select a source first.", parent=self.root)
            return
        try:
            managed_source = self._managed_source_config(source_id)
            source_config = load_import_source_config(managed_source.source_root)
        except Exception as exc:
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        session_naming = source_config.naming.session_description
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Import Naming - {managed_source.display_name}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)

        enabled_var = tk.BooleanVar(
            value=bool(session_naming.enabled and session_naming.mode == "base_index")
        )
        base_var = tk.StringVar(value=str(session_naming.base or managed_source.display_name or ""))
        index_start_var = tk.StringVar(value=str(session_naming.index_start))
        index_padding_var = tk.StringVar(value=str(session_naming.index_padding))
        status_var = tk.StringVar(value="")

        ttk.Checkbutton(
            dialog,
            text="Auto-name sessions on import",
            variable=enabled_var,
        ).grid(row=0, column=1, sticky="w", padx=(0, 12), pady=(12, 6))

        ttk.Label(dialog, text="Session base name").grid(row=1, column=0, sticky="w", padx=(12, 8), pady=4)
        base_entry = ttk.Entry(dialog, textvariable=base_var)
        base_entry.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=4)

        ttk.Label(dialog, text="Index start").grid(row=2, column=0, sticky="w", padx=(12, 8), pady=4)
        index_start_entry = ttk.Entry(dialog, textvariable=index_start_var, width=10)
        index_start_entry.grid(row=2, column=1, sticky="w", padx=(0, 12), pady=4)

        ttk.Label(dialog, text="Index padding").grid(row=3, column=0, sticky="w", padx=(12, 8), pady=4)
        index_padding_entry = ttk.Entry(dialog, textvariable=index_padding_var, width=10)
        index_padding_entry.grid(row=3, column=1, sticky="w", padx=(0, 12), pady=4)

        ttk.Label(dialog, textvariable=status_var, foreground="#a33").grid(
            row=4, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 0)
        )

        def sync_entry_state(*_args: Any) -> None:
            state = "normal" if bool(enabled_var.get()) else "disabled"
            for widget in (base_entry, index_start_entry, index_padding_entry):
                widget.configure(state=state)

        def parse_nonnegative_int(value: str, *, label: str) -> int:
            try:
                number = int(str(value).strip())
            except ValueError:
                raise ValueError(f"{label} must be an integer") from None
            if number < 0:
                raise ValueError(f"{label} must be >= 0")
            return number

        def save() -> None:
            try:
                enabled = bool(enabled_var.get())
                base = base_var.get().strip()
                if enabled and not base:
                    raise ValueError("Session base name is required when auto-naming is enabled.")
                index_start = parse_nonnegative_int(index_start_var.get(), label="Index start")
                index_padding = parse_nonnegative_int(index_padding_var.get(), label="Index padding")
                self.controller.set_source_session_naming(
                    source_id,
                    enabled=enabled,
                    base=base,
                    index_start=index_start,
                    index_padding=index_padding,
                )
            except Exception as exc:
                status_var.set(str(exc))
                return
            dialog.destroy()
            self._refresh_ui_from_config()
            if self.sources_tree is not None and self.sources_tree.exists(source_id):
                self.sources_tree.selection_set(source_id)
            self._set_manager_status(f"Updated import naming for source '{source_id}'.")

        buttons = ttk.Frame(dialog)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", padx=12, pady=(8, 12))
        ttk.Button(buttons, text="Save", command=save).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=1)

        enabled_var.trace_add("write", sync_entry_state)
        sync_entry_state()
        dialog.bind("<Return>", lambda _event: save())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.lift(self.root)
        dialog.focus_force()
        if bool(enabled_var.get()):
            base_entry.focus_set()
        self.root.wait_window(dialog)

    def _toggle_source_enabled(self, source_id: str) -> None:
        if not self._guard_watch_inactive(action_label="Toggle Source"):
            return
        try:
            enabled = not self._managed_source_enabled(source_id)
            self.controller.set_source_enabled(source_id, enabled)
        except Exception as exc:
            self._set_manager_status(f"Toggle source failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        if self.sources_tree is not None and self.sources_tree.exists(source_id):
            self.sources_tree.selection_set(source_id)
        self._set_manager_status(f"{'Enabled' if enabled else 'Disabled'} source '{source_id}'.")

    def _toggle_source_session_note_attach(self, source_id: str) -> None:
        if not self._guard_watch_inactive(action_label="Toggle Source Draft Note"):
            return
        try:
            enabled = not self._managed_source_session_note_attach_enabled(source_id)
            self.controller.set_source_session_note_attach_enabled(source_id, enabled)
        except Exception as exc:
            self._set_manager_status(f"Toggle source draft-note attach failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        if self.sources_tree is not None and self.sources_tree.exists(source_id):
            self.sources_tree.selection_set(source_id)
        self._set_manager_status(
            f"{'Enabled' if enabled else 'Disabled'} draft setup notes for source '{source_id}'."
        )

    def _toggle_source_force_reprocess(self, source_id: str) -> None:
        if not self._guard_watch_inactive(action_label="Toggle Source Reprocessing"):
            return
        try:
            enabled = not self._managed_source_force_reprocess_enabled(source_id)
            self.controller.set_source_force_reprocess_enabled(source_id, enabled)
        except Exception as exc:
            self._set_manager_status(f"Toggle source reprocessing failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        if self.sources_tree is not None and self.sources_tree.exists(source_id):
            self.sources_tree.selection_set(source_id)
        self._set_manager_status(
            f"{'Enabled' if enabled else 'Disabled'} reprocessing for source '{source_id}'."
        )

    def _toggle_selected_library_syn_export(self) -> None:
        library_id = self._selected_library_id()
        if library_id is None:
            messagebox.showinfo(
                _APP_DISPLAY_NAME,
                "Select a library first.",
                parent=self.root,
            )
            return
        self._toggle_library_syn_export(library_id)

    def _toggle_library_syn_export(self, library_id: str) -> None:
        if not self._guard_watch_inactive(action_label="Toggle Syn Export"):
            return
        try:
            enabled = not self._managed_library_syn_export_enabled(library_id)
            self.controller.set_library_data_syn_bike_export_enabled(library_id, enabled)
        except Exception as exc:
            self._set_manager_status(f"Toggle syn export failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        if self.libraries_tree is not None and self.libraries_tree.exists(library_id):
            self.libraries_tree.selection_set(library_id)
        self._set_manager_status(
            f"{'Enabled' if enabled else 'Disabled'} data.syn.bike exports for library '{library_id}'."
        )

    def _selected_library_id_from_choice(self) -> Optional[str]:
        label = self.source_library_choice_var.get().strip()
        return self._library_choice_map.get(label)

    def _watch_running(self) -> bool:
        return self.watch_service is not None and self.watch_service.running

    def _import_now_running(self) -> bool:
        return self.import_now_thread is not None and self.import_now_thread.is_alive()

    def _has_enabled_sources(self) -> bool:
        config = self.controller.app_config
        return bool(config and any(source.enabled for source in config.sources))

    def _library_api_service_for_current_config(self, *, create: bool) -> Optional[LibraryApiServiceProcess]:
        config = self.controller.app_config
        if config is None:
            return None
        libraries_root = Path(config.libraries_root).expanduser().resolve()
        if self.library_api_service is not None:
            if self.library_api_service.libraries_root == libraries_root:
                return self.library_api_service
            if self.library_api_service.is_running():
                return self.library_api_service
            self.library_api_service = None
        if not create:
            return None
        self.library_api_service = LibraryApiServiceProcess(libraries_root=libraries_root)
        return self.library_api_service

    def _open_web_app(self) -> None:
        if not self.controller.has_config():
            messagebox.showinfo(
                _APP_DISPLAY_NAME,
                "Create or use an existing managed workspace first.",
                parent=self.root,
            )
            return
        service = self._library_api_service_for_current_config(create=True)
        if service is None:
            return
        try:
            message = service.start()
            webbrowser.open(service.web_url)
        except Exception as exc:
            self.library_service_state_var.set("Library web app failed to start.")
            self._set_manager_status(f"Open web app failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            self._refresh_web_app_controls(has_config=True)
            return
        self.library_service_state_var.set(f"Library web app available at {service.web_url}")
        self._set_manager_status(f"{message} Opened {service.web_url}")
        self._refresh_web_app_controls(has_config=True)

    def _stop_web_app(self) -> None:
        service = self._library_api_service_for_current_config(create=False)
        if service is None or not service.is_running():
            self.library_service_state_var.set("Library web app stopped.")
            self._refresh_web_app_controls(has_config=self.controller.has_config())
            return
        if not service.started_by_manager:
            self._set_manager_status(
                f"Library service at {service.base_url} was not started by this Manager, so it was left running."
            )
            self._refresh_web_app_controls(has_config=self.controller.has_config())
            return
        if service.stop():
            self._set_manager_status("Stopped Library web app service.")
            self.library_service_state_var.set("Library web app stopped.")
        else:
            self._set_manager_status("Library web app stop requested; service is still shutting down.")
            self.library_service_state_var.set(f"Library web app still running at {service.web_url}.")
        self._refresh_web_app_controls(has_config=self.controller.has_config())

    def _window_visible(self) -> bool:
        return self.root.state() != "withdrawn"

    def _guard_watch_inactive(self, *, action_label: str, parent: Optional[tk.Misc] = None) -> bool:
        if self._watch_running():
            messagebox.showinfo(
                _APP_DISPLAY_NAME,
                f"Stop the watcher before running '{action_label}'.",
                parent=parent or self.root,
            )
            return False
        return True

    def _guard_import_now_inactive(self, *, action_label: str, parent: Optional[tk.Misc] = None) -> bool:
        if self._import_now_running():
            messagebox.showinfo(
                _APP_DISPLAY_NAME,
                f"Wait for the current import to finish before running '{action_label}'.",
                parent=parent or self.root,
            )
            return False
        return True

    def _manager_startup_argv(self) -> list[str]:
        app_config_path = str(Path(self.args.app_config).expanduser().resolve())
        app_config_mode = str(self.args.app_config_mode or IMPORT_AGENT_APP_CONFIG_MODE_AUTO)
        if getattr(sys, "frozen", False):
            launch_argv: list[str] = [str(Path(sys.executable).resolve())]
        else:
            launch_argv = [
                str(Path(sys.executable).resolve()),
                str((Path(__file__).resolve().parents[1] / "bodaqs_import_agent_setup.py").resolve()),
            ]
        launch_argv.extend(["--app-config", app_config_path, "--app-config-mode", app_config_mode, "--startup-launch"])
        return launch_argv

    def _tray_status_snapshot(self) -> dict[str, Any]:
        config = self.controller.app_config
        return {
            "has_config": config is not None,
            "auto_start": bool(config.auto_start) if config is not None else False,
            "watch_running": self._watch_running(),
            "window_visible": self._window_visible(),
            "import_now_running": self._import_now_running(),
            "can_start_watch": (
                config is not None
                and self._has_enabled_sources()
                and not self._watch_running()
                and not self._import_now_running()
            ),
            "can_stop_watch": self._watch_running(),
            "can_import_now": config is not None and not self._watch_running() and not self._import_now_running(),
            "source_count": len(config.sources) if config is not None else 0,
        }

    def _refresh_tray(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.refresh()

    def _start_tray_icon(self) -> None:
        if not tray_supported():
            return
        tray_icon = ImportAgentTrayIcon(
            event_queue=self.event_queue,
            status_supplier=self._tray_status_snapshot,
        )
        if tray_icon.start():
            self.tray_icon = tray_icon
            self._append_log("Tray icon started.")
            self._refresh_tray()

    def _hide_to_tray(self) -> None:
        if self.tray_icon is None:
            self._minimize_window()
            return
        self.root.withdraw()
        self._refresh_tray()
        if not self._close_notice_shown:
            self._append_log("Manager window hidden to the tray. Use the tray icon to reopen or quit.")
            self._close_notice_shown = True

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass
        self._refresh_tray()

    def _quit_application(self) -> None:
        self._shutdown_requested = True
        if self.watch_service is not None:
            self.watch_service.stop(timeout_s=2.0)
            self.watch_service = None
        self._shutdown_library_api_service()
        if self.tray_icon is not None:
            self.tray_icon.stop()
            self.tray_icon = None
        self.root.destroy()

    def _shutdown_library_api_service(self) -> None:
        if self.library_api_service is None:
            return
        if self.library_api_service.started_by_manager:
            self.library_api_service.stop(timeout_s=2.0)
        self.library_api_service = None

    def _sync_startup_registration(self, *, show_errors: bool, emit_status: bool) -> None:
        config = self.controller.app_config
        if config is None:
            return
        if not windows_startup_supported():
            if emit_status:
                self._append_log("Start-at-login registration is only available on Windows in this build.")
            return

        command = (
            build_windows_startup_command(self._manager_startup_argv())
            if config.auto_start
            else None
        )
        try:
            applied = sync_windows_startup_registration(enabled=config.auto_start, command=command)
        except Exception as exc:
            if emit_status:
                self._set_manager_status(f"Start-at-login update failed: {exc}")
            if show_errors:
                messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        if not emit_status:
            return
        if config.auto_start:
            self._set_manager_status("Start-at-login enabled.")
            if applied:
                self._append_log(f"Startup command: {applied}")
        else:
            self._set_manager_status("Start-at-login disabled.")

    def _minimize_window(self) -> None:
        self.root.update_idletasks()
        self.root.iconify()

    def _apply_launch_behavior(self) -> None:
        if self._launch_behavior_applied:
            return
        self._launch_behavior_applied = True

        config = self.controller.app_config
        if config is None:
            return
        if not self.start_watch_on_launch:
            return
        if not config.auto_start:
            self._append_log("Startup launch did not start the watcher because start-at-login is disabled.")
            return

        self._start_watch(show_errors=not self.startup_launch)
        if self.start_minimized_on_launch and self._watch_running():
            self.root.after(150, self._hide_to_tray)

    def _create_initial_setup(self) -> None:
        if not self._guard_watch_inactive(action_label="Create Initial Library + Source"):
            return
        try:
            source_type = self._selected_source_type()
            logger_wifi = self._logger_wifi_payload_from_form()
            result = self.controller.create_initial_setup(
                sources_root=self.sources_root_var.get(),
                libraries_root=self.libraries_root_var.get(),
                library_display_name=self.library_name_var.get(),
                source_display_name=self.source_name_var.get(),
                source_type=source_type,
                logger_wifi=logger_wifi,
                run_tz_label=self.run_tz_label_var.get().strip() or "LOCAL",
                data_syn_bike_export_enabled=bool(self.data_syn_bike_export_var.get()),
                attach_session_note_on_import=bool(self.attach_session_note_var.get()),
                session_auto_name_enabled=bool(self.session_auto_name_var.get()),
                session_name_base=self._session_name_base_from_form(),
                auto_start=bool(self.auto_start_var.get()),
                overwrite=bool(self.overwrite_var.get()),
            )
        except Exception as exc:
            if isinstance(exc, FileExistsError) and self._confirm_adopt_existing_workspace_after_create_failure(exc):
                self._adopt_existing_workspace(confirm=False)
                return
            self._set_provision_status(f"Initial setup failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
        self._sync_startup_registration(show_errors=True, emit_status=False)
        self._set_provision_status(
            f"Created initial library '{result.library.display_name}' and source '{result.source.display_name}'."
        )
        self._offer_configure_source_after_creation(result.source.source_id)

    def _confirm_adopt_existing_workspace_after_create_failure(self, exc: Exception) -> bool:
        return messagebox.askyesno(
            _APP_DISPLAY_NAME,
            "The selected roots already contain files, so the manager will not seed a new setup there.\n\n"
            "Would you like to use the existing BODAQS workspace in those folders and rebuild this "
            "computer's local app settings instead?\n\n"
            f"Original error: {exc}",
            parent=self.root,
        )

    def _format_workspace_sync_report(self, report: ImportAgentWorkspaceSyncReport) -> str:
        lines: list[str] = []

        def add(label: str, values: Sequence[str]) -> None:
            if values:
                lines.append(f"{label}: {', '.join(values)}")

        add("New libraries", report.added_libraries)
        add("Updated libraries", report.updated_libraries)
        add("Libraries missing from shared root", report.missing_libraries)
        add("New sources", report.added_sources)
        add("Updated sources", report.updated_sources)
        add("Sources missing from shared root", report.missing_sources)
        if not lines:
            return "No workspace differences found."
        return "\n".join(lines)

    def _sync_workspace_from_roots(self, *, confirm: bool = True, startup_check: bool = False) -> None:
        if not self.controller.has_config():
            messagebox.showinfo(
                _APP_DISPLAY_NAME,
                "Create or use an existing managed workspace first.",
                parent=self.root,
            )
            return
        if not self._guard_watch_inactive(action_label="Sync Workspace"):
            return

        try:
            report = self.controller.check_workspace_sync()
        except Exception as exc:
            self._set_manager_status(f"Workspace sync check failed: {exc}")
            if not startup_check:
                messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        if not report.has_changes:
            self._set_manager_status("Workspace sync check complete: no differences found.")
            if not startup_check:
                messagebox.showinfo(_APP_DISPLAY_NAME, "No workspace differences found.", parent=self.root)
            return

        summary = self._format_workspace_sync_report(report)
        if not report.has_syncable_changes:
            message = (
                "Workspace differences were found, but there are no new or updated shared definitions "
                "to apply. Local entries missing from the shared root are preserved.\n\n"
                f"{summary}"
            )
            self._set_manager_status("Workspace differences found; no syncable additions or updates.")
            if not startup_check:
                messagebox.showinfo(_APP_DISPLAY_NAME, message, parent=self.root)
            return

        if confirm:
            should_sync = messagebox.askyesno(
                _APP_DISPLAY_NAME,
                "Workspace changes were found under the configured source/library roots.\n\n"
                f"{summary}\n\n"
                "Apply new and updated shared definitions to this computer's local Import Manager settings?\n\n"
                "Local enabled/disabled state and start-at-login settings will be preserved. Entries missing "
                "from the shared root will not be removed automatically.",
                parent=self.root,
            )
            if not should_sync:
                self._set_manager_status("Workspace sync deferred.")
                return

        try:
            result = self.controller.sync_workspace_from_roots()
        except Exception as exc:
            self._set_manager_status(f"Workspace sync failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
        applied_summary = self._format_workspace_sync_report(result.report)
        self._set_manager_status(
            "Workspace sync complete. "
            f"libraries={len(result.app_config.libraries)} sources={len(result.app_config.sources)}."
        )
        if not startup_check:
            messagebox.showinfo(
                _APP_DISPLAY_NAME,
                "Workspace sync complete.\n\n" + applied_summary,
                parent=self.root,
            )

    def _check_workspace_sync_on_startup(self) -> None:
        if self._startup_workspace_sync_checked:
            return
        self._startup_workspace_sync_checked = True
        if not self.controller.has_config():
            return

        try:
            report = self.controller.check_workspace_sync()
        except Exception as exc:
            self._set_manager_status(f"Workspace sync check failed: {exc}")
            return
        if not report.has_changes:
            return

        summary = self._format_workspace_sync_report(report)
        if self.startup_launch or self.start_minimized_on_launch or self.watch_service is not None:
            self._set_manager_status(
                "Workspace changes found. Stop watch mode if needed, then use Sync Workspace to apply them."
            )
            self._append_log(summary)
            return

        if not report.has_syncable_changes:
            self._set_manager_status("Workspace differences found; no syncable additions or updates.")
            self._append_log(summary)
            return

        should_sync = messagebox.askyesno(
            _APP_DISPLAY_NAME,
            "Workspace changes were found under the configured source/library roots.\n\n"
            f"{summary}\n\n"
            "Sync this computer's local Import Manager settings now?",
            parent=self.root,
        )
        if should_sync:
            self._sync_workspace_from_roots(confirm=False, startup_check=True)
        else:
            self._set_manager_status("Workspace sync deferred.")

    def _adopt_existing_workspace(self, *, confirm: bool = True) -> None:
        if not self._guard_watch_inactive(action_label="Use Existing Workspace"):
            return
        if confirm:
            should_continue = messagebox.askyesno(
                _APP_DISPLAY_NAME,
                "Use the selected source and library roots as an existing BODAQS workspace?\n\n"
                "This rebuilds only this computer's local Import Manager app settings. It does not "
                "overwrite source folders, library folders, bike profiles, note templates, logs, or "
                "processed artifacts.",
                parent=self.root,
            )
            if not should_continue:
                return
        try:
            result = self.controller.adopt_existing_workspace(
                sources_root=self.sources_root_var.get(),
                libraries_root=self.libraries_root_var.get(),
                auto_start=bool(self.auto_start_var.get()),
            )
        except Exception as exc:
            self._set_provision_status(f"Use existing workspace failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
        self._sync_startup_registration(show_errors=True, emit_status=False)
        self._set_provision_status(
            "Using existing workspace: "
            f"libraries={len(result.app_config.libraries)} sources={len(result.app_config.sources)}. "
            "Local app settings were rebuilt for this computer."
        )

    def _add_library(self) -> None:
        if not self._guard_watch_inactive(action_label="Add Library"):
            return
        try:
            library = self.controller.add_library(
                display_name=self.library_name_var.get(),
                data_syn_bike_export_enabled=bool(self.data_syn_bike_export_var.get()),
                overwrite=bool(self.overwrite_var.get()),
            )
        except Exception as exc:
            self._set_provision_status(f"Add library failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
        self._set_provision_status(f"Added library '{library.display_name}'.")

    def _add_source(self) -> None:
        if not self._guard_watch_inactive(action_label="Add Source"):
            return
        library_id = self._selected_library_id_from_choice()
        if library_id is None:
            messagebox.showinfo(
                _APP_DISPLAY_NAME,
                "Select a target library for the new source first.",
                parent=self.root,
            )
            return
        try:
            source_type = self._selected_source_type()
            logger_wifi = self._logger_wifi_payload_from_form()
            source = self.controller.add_source(
                library_id=library_id,
                display_name=self.source_name_var.get(),
                source_type=source_type,
                logger_wifi=logger_wifi,
                run_tz_label=self.run_tz_label_var.get().strip() or "LOCAL",
                attach_session_note_on_import=bool(self.attach_session_note_var.get()),
                session_auto_name_enabled=bool(self.session_auto_name_var.get()),
                session_name_base=self._session_name_base_from_form(),
                overwrite=bool(self.overwrite_var.get()),
            )
        except Exception as exc:
            self._set_provision_status(f"Add source failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
        self._set_provision_status(f"Added source '{source.display_name}'.")
        self._offer_configure_source_after_creation(source.source_id)

    def _apply_app_settings(self) -> None:
        if not self.controller.has_config():
            messagebox.showinfo(
                _APP_DISPLAY_NAME,
                "Create the initial managed setup before applying app settings.",
                parent=self.root,
            )
            return
        try:
            updated = self.controller.set_auto_start(bool(self.auto_start_var.get()))
        except Exception as exc:
            self._set_provision_status(f"Apply app settings failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
        self._sync_startup_registration(show_errors=True, emit_status=False)
        self._set_provision_status(
            f"Updated app settings: start at login={'enabled' if updated.auto_start else 'disabled'}."
        )

    def _validate_sources(self) -> None:
        if not self._guard_watch_inactive(action_label="Validate"):
            return
        try:
            results = self.controller.validate_sources(enabled_only=False)
        except Exception as exc:
            self._set_manager_status(f"Validation failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        total_errors = sum(len(item.get("errors", [])) for item in results)
        total_warnings = sum(len(item.get("warnings", [])) for item in results)
        self._set_manager_status(
            f"Validated {len(results)} sources: {total_errors} error(s), {total_warnings} warning(s)."
        )
        for result in results:
            self._append_log(
                f"Validate {result['source_id']}: errors={len(result.get('errors', []))} "
                f"warnings={len(result.get('warnings', []))}"
            )
            for item in result.get("errors", []):
                self._append_log(f"  error: {item}")
            for item in result.get("warnings", []):
                self._append_log(f"  warning: {item}")

    def _import_now(self) -> None:
        if not self._guard_watch_inactive(action_label="Import Now"):
            return
        run_description_override = simpledialog.askstring(
            _APP_DISPLAY_NAME,
            "Run description override for this Import Now\n\nLeave blank to use source defaults.",
            initialvalue="",
            parent=self.root,
        )
        if run_description_override is None:
            return
        run_description_override = run_description_override.strip() or None
        try:
            supervisor = self.controller.make_enabled_supervisor()
        except Exception as exc:
            self._set_manager_status(f"Import failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        self.import_now_thread = threading.Thread(
            target=self._run_import_now_worker,
            args=(supervisor, run_description_override),
            name="ImportAgentImportNow",
            daemon=True,
        )
        self.import_now_thread.start()
        self._set_manager_status("Import started.")
        self._refresh_tray()

    def _queue_import_now_progress(self, progress: Mapping[str, Any]) -> None:
        self.event_queue.put(
            {
                "kind": "import_progress",
                "origin": "import_now",
                "progress": dict(progress),
            }
        )

    def _run_import_now_worker(
        self,
        supervisor: ImportAgentSupervisor,
        run_description_override: Optional[str],
    ) -> None:
        try:
            report = supervisor.scan_all_once(
                progress_callback=self._queue_import_now_progress,
                run_description_override=run_description_override,
            )
            self.event_queue.put(
                {
                    "kind": "import_now_complete",
                    "report": report,
                    "snapshot": supervisor.snapshot(),
                }
            )
        except Exception as exc:
            self.event_queue.put(
                {
                    "kind": "import_now_error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        finally:
            self.event_queue.put({"kind": "import_now_finished"})

    def _handle_import_now_complete(self, report: dict[str, Any], snapshot: dict[str, Any]) -> None:
        totals = report.get("totals", {})
        self._set_manager_status(
            "Import complete: "
            f"seen={totals.get('seen', 0)} imported={totals.get('imported', 0)} "
            f"deferred={totals.get('deferred_unsettled', 0)} failed={totals.get('failed', 0)}"
        )
        for source_report in report.get("sources", []):
            self._update_source_status_from_report(source_report)
            source_totals = _aggregate_reports([source_report])
            self._append_log(
                f"Import source {source_report['source_id']}: "
                f"seen={source_totals['seen']} imported={source_totals['imported']} "
                f"deferred={source_totals['deferred_unsettled']} failed={source_totals['failed']}"
            )
        self._apply_snapshot(snapshot)

    def _start_watch(self, *, show_errors: bool = True) -> None:
        if self._watch_running():
            return
        if not self._guard_import_now_inactive(action_label="Start Watch"):
            return
        try:
            supervisor = self.controller.make_enabled_supervisor()
        except Exception as exc:
            self._set_manager_status(f"Unable to start watch: {exc}")
            if show_errors:
                messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        self.watch_service = ImportAgentWatchService(supervisor, self.event_queue)
        self.watch_service.start()
        self.watch_state_var.set("Watcher starting...")
        self._set_manager_status("Started watch loop.")
        self._refresh_tray()

    def _stop_watch(self) -> None:
        if self.watch_service is None:
            self.watch_state_var.set("Watcher stopped.")
            return
        stopped = self.watch_service.stop()
        if stopped:
            self.watch_service = None
            self.watch_state_var.set("Watcher stopped.")
            self._set_manager_status("Stopped watch loop.")
        else:
            self.watch_state_var.set("Watcher stop requested; waiting for background loop to exit...")
        self._refresh_tray()

    def _remove_selected_library(self) -> None:
        if not self._guard_watch_inactive(action_label="Remove Library"):
            return
        library_id = self._selected_library_id()
        if library_id is None:
            messagebox.showinfo(_APP_DISPLAY_NAME, "Select a library first.", parent=self.root)
            return
        try:
            library = self._managed_library_config(library_id)
            config = self.controller.require_config()
        except Exception as exc:
            self._set_manager_status(f"Remove library failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        linked_sources = [source for source in config.sources if source.library_id == library.library_id]
        if linked_sources:
            names = ", ".join(source.display_name for source in linked_sources)
            messagebox.showinfo(
                "Remove Library",
                (
                    f"Library '{library.display_name}' still has source(s) assigned to it:\n\n"
                    f"{names}\n\n"
                    "Reassign or remove those sources before removing the library."
                ),
                parent=self.root,
            )
            return

        delete_files = self._choose_remove_mode_dialog(
            title="Remove Library",
            item_name=f"Remove library '{library.display_name}'?",
            folder_path=library.artifacts_dir,
            remove_only_text=(
                "The library will be removed from the manager configuration. "
                "The library data folder and files will be left on disk."
            ),
            delete_text="The library data folder below will also be deleted from disk.",
            delete_note=(
                "Shared bike profiles, preprocess profiles, and event schemas under the library root "
                "will not be deleted."
            ),
        )
        if delete_files is None:
            return
        if delete_files and not self._confirm_delete_from_disk(
            title="Delete Library Data Folder",
            folder_path=library.artifacts_dir,
        ):
            return
        try:
            self.controller.remove_library(library.library_id, delete_files=delete_files)
        except Exception as exc:
            self._refresh_ui_from_config()
            self._set_manager_status(f"Remove library failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        if delete_files:
            self._set_manager_status(
                f"Removed library '{library.library_id}' and deleted its data folder."
            )
        else:
            self._set_manager_status(
                f"Removed library '{library.library_id}' from the manager. Files were left in place."
            )

    def _remove_selected_source(self) -> None:
        if not self._guard_watch_inactive(action_label="Remove Source"):
            return
        source_id = self._selected_source_id()
        if source_id is None:
            messagebox.showinfo(_APP_DISPLAY_NAME, "Select a source first.", parent=self.root)
            return
        try:
            source = self._managed_source_config(source_id)
        except Exception as exc:
            self._set_manager_status(f"Remove source failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        delete_files = self._choose_remove_mode_dialog(
            title="Remove Source",
            item_name=f"Remove source '{source.display_name}'?",
            folder_path=source.source_root,
            remove_only_text=(
                "The source will be removed from the manager configuration. "
                "The source folder and files will be left on disk."
            ),
            delete_text="The source folder below will also be deleted from disk.",
        )
        if delete_files is None:
            return
        if delete_files and not self._confirm_delete_from_disk(
            title="Delete Source Folder",
            folder_path=source.source_root,
        ):
            return
        try:
            self.controller.remove_source(source_id, delete_files=delete_files)
        except Exception as exc:
            self._refresh_ui_from_config()
            self._set_manager_status(f"Remove source failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._source_runtime_status.pop(source_id, None)
        self._refresh_ui_from_config()
        if delete_files:
            self._set_manager_status(f"Removed source '{source_id}' and deleted its source folder.")
        else:
            self._set_manager_status(f"Removed source '{source_id}' from the manager. Files were left in place.")

    def _check_selected_logger(self) -> None:
        try:
            client, source = self._selected_logger_wifi_client_and_source()
            device = client.get_device()
            logger_id = str(device.get("logger_id") or "").strip()
            if source.logger_wifi is not None and logger_id != source.logger_wifi.logger_id:
                raise ValueError(
                    f"Logger identity mismatch: expected {source.logger_wifi.logger_id!r}, got {logger_id!r}"
                )
            status = client.get_status()
            upload_mode = bool(status.get("upload_mode", False))
            sessions = client.list_sessions() if upload_mode else []
            status_text = self._logger_status_text(
                upload_mode=upload_mode,
                session_count=len(sessions) if upload_mode else status.get("importable_session_count"),
            )
            self._set_source_runtime_status(source.source_id, status_text)
            self._set_manager_status(f"Checked logger '{logger_id}' for source '{source.source_id}': {status_text}.")
        except Exception as exc:
            source_id = self._selected_source_id() or ""
            if source_id:
                self._set_source_runtime_status(source_id, f"error: {exc}")
            self._set_manager_status(f"Check logger failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)

    def _request_selected_upload_mode(self) -> None:
        try:
            client, source = self._selected_logger_wifi_client_and_source()
            response = client.enter_upload_mode()
            status_text = self._logger_status_text(
                upload_mode=bool(response.get("upload_mode", False)),
                session_count=response.get("importable_session_count"),
            )
            self._set_source_runtime_status(source.source_id, status_text)
            self._set_manager_status(f"Requested upload mode for source '{source.source_id}': {status_text}.")
        except Exception as exc:
            source_id = self._selected_source_id() or ""
            if source_id:
                self._set_source_runtime_status(source_id, f"error: {exc}")
            self._set_manager_status(f"Request upload mode failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)

    def _open_selected_logger_web_ui(self) -> None:
        try:
            client, _source = self._selected_logger_wifi_client_and_source()
            webbrowser.open(client.base_url)
            self._set_manager_status(f"Opened logger web UI: {client.base_url}")
        except Exception as exc:
            self._set_manager_status(f"Open logger web UI failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)

    def _apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        if not snapshot:
            return
        due_count = sum(1 for item in snapshot.get("sources", []) if item.get("due_now"))
        paused_count = sum(1 for item in snapshot.get("sources", []) if item.get("paused"))
        self.watch_state_var.set(
            f"Watcher snapshot: active={snapshot.get('active_source_count', 0)} "
            f"paused={paused_count} due_now={due_count}"
        )

    def _poll_event_queue(self) -> None:
        while True:
            try:
                item = self.event_queue.get_nowait()
            except queue.Empty:
                break

            kind = item.get("kind")
            if kind == "watch_started":
                self.watch_state_var.set("Watcher running.")
                self._append_log("Watcher started.")
            elif kind == "watch_reports":
                reports = item.get("reports", [])
                snapshot = item.get("snapshot", {})
                self._apply_snapshot(snapshot)
                for report in reports:
                    self._update_source_status_from_report(report)
                    totals = _aggregate_reports([report])
                    self._append_log(
                        f"Watch source {report['source_id']}: "
                        f"seen={totals['seen']} imported={totals['imported']} "
                        f"deferred={totals['deferred_unsettled']} failed={totals['failed']}"
                    )
            elif kind == "import_progress":
                progress = item.get("progress", {})
                if isinstance(progress, Mapping):
                    self._handle_import_progress(
                        progress,
                        origin=str(item.get("origin") or ""),
                    )
            elif kind == "import_now_complete":
                report = item.get("report", {})
                snapshot = item.get("snapshot", {})
                if isinstance(report, dict) and isinstance(snapshot, dict):
                    self._handle_import_now_complete(report, snapshot)
            elif kind == "import_now_error":
                error = str(item.get("error") or "Unknown import error")
                self._set_manager_status(f"Import failed: {error}")
                messagebox.showerror(_APP_DISPLAY_NAME, error, parent=self.root)
            elif kind == "import_now_finished":
                self.import_now_thread = None
            elif kind == "watch_error":
                self.watch_state_var.set("Watcher error.")
                self._append_log(f"Watcher error: {item.get('error')}")
                messagebox.showerror(
                    _APP_DISPLAY_NAME,
                    str(item.get("error") or "Unknown watch error"),
                    parent=self.root,
                )
            elif kind == "watch_stopped":
                self.watch_state_var.set("Watcher stopped.")
                self._append_log("Watcher stopped.")
                self._apply_snapshot(item.get("snapshot", {}))
                if self.watch_service is not None and not self.watch_service.running:
                    self.watch_service = None
            elif kind == "tray_show_window":
                self._show_window()
            elif kind == "tray_hide_window":
                self._hide_to_tray()
            elif kind == "tray_start_watch":
                self._start_watch(show_errors=False)
            elif kind == "tray_stop_watch":
                self._stop_watch()
            elif kind == "tray_import_now":
                self._import_now()
            elif kind == "tray_toggle_auto_start":
                self.auto_start_var.set(not bool(self.auto_start_var.get()))
                self._apply_app_settings()
            elif kind == "tray_quit":
                self._quit_application()

            self._refresh_tray()
        self.root.after(250, self._poll_event_queue)

    def _on_close(self) -> None:
        if self._shutdown_requested:
            self._quit_application()
            return
        if self.tray_icon is not None:
            self._hide_to_tray()
            return
        if self.watch_service is not None:
            self.watch_service.stop(timeout_s=2.0)
        self._shutdown_library_api_service()
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.startup_launch:
        args.start_watch = True
        args.start_minimized = True
    if not str(args.app_config).strip():
        args.app_config = str(_default_app_config_path(mode=args.app_config_mode))
    single_instance_lock = SingleInstanceLock.for_app_config(args.app_config)
    if not single_instance_lock.acquire():
        if not args.startup_launch:
            _show_already_running_message(args.app_config)
        return 0
    try:
        window = ImportAgentManagerWindow(args)
        return window.run()
    finally:
        single_instance_lock.release()
