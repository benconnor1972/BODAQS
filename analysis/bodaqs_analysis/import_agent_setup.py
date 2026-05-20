from __future__ import annotations

import argparse
import base64
import ctypes
import queue
import sys
import threading
import time
import webbrowser
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .import_agent import ImportAgentSupervisor, load_import_source_config, validate_import_sources
from .import_agent_logger_wifi import LoggerWifiApiClient
from .import_agent_logger_wifi_discovery import (
    LoggerWifiDiscoveryResult,
    discover_logger_wifi_sources,
    discover_single_logger_wifi_source,
)
from .import_agent_provisioning import (
    IMPORT_AGENT_APP_CONFIG_MODE_AUTO,
    IMPORT_AGENT_APP_CONFIG_MODE_INSTALLED,
    IMPORT_AGENT_APP_CONFIG_MODE_PORTABLE,
    ImportAgentAppConfig,
    load_import_agent_app_config,
    managed_import_agent_source_roots,
    provision_import_agent_app_setup,
    provision_import_agent_library_for_app,
    provision_import_agent_source_for_app,
    remove_import_agent_source,
    runtime_import_agent_app_config_path,
    update_import_agent_app_auto_start,
    update_import_agent_library_data_syn_bike_export_enabled,
    update_import_agent_source_session_note_attach_enabled,
    update_import_agent_source_enabled,
)
from .import_agent_sources import (
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


_ASSET_PACKAGE = "bodaqs_analysis.import_agent_assets"
_APP_DISPLAY_NAME = "BODAQS Import Manager"
_WINDOW_ICON_FILENAME = "app_icon.png"
_WINDOW_ICON_ICO_FILENAME = "app_icon.ico"
_WINDOWS_APP_USER_MODEL_ID = "BODAQS.ImportAgent.Manager"
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
        overwrite: bool,
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
            auto_start=auto_start,
            overwrite=overwrite,
        )
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
        overwrite: bool,
    ) -> Any:
        updated, source = provision_import_agent_source_for_app(
            self.app_config_path,
            library_id=library_id,
            display_name=display_name,
            source_type=source_type,
            logger_wifi=logger_wifi,
            run_tz_label=run_tz_label,
            attach_session_note_on_import=attach_session_note_on_import,
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

    def remove_source(self, source_id: str) -> ImportAgentAppConfig:
        updated = remove_import_agent_source(
            self.app_config_path,
            source_id=source_id,
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
        return validate_import_sources(self.managed_source_roots(enabled_only=enabled_only))

    def make_enabled_supervisor(self) -> ImportAgentSupervisor:
        source_roots = self.managed_source_roots(enabled_only=True)
        if not source_roots:
            raise ValueError("No enabled managed sources are available.")
        return ImportAgentSupervisor.from_paths(source_roots)

    def import_once(self) -> tuple[dict[str, Any], dict[str, Any]]:
        supervisor = self.make_enabled_supervisor()
        report = supervisor.scan_all_once()
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

    def _run(self) -> None:
        self.event_queue.put({"kind": "watch_started"})
        try:
            while not self._stop_event.is_set():
                now_s = time.time()
                reports = self.supervisor.scan_due(now_s=now_s)
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


class ImportAgentManagerWindow:
    def __init__(self, args: argparse.Namespace) -> None:
        _apply_windows_app_user_model_id()
        self.root = tk.Tk()
        self._window_icon_image: Optional[tk.PhotoImage] = None
        self._apply_window_icon()
        self.root.title(_APP_DISPLAY_NAME)
        self.root.geometry("1120x760")
        self.root.minsize(980, 680)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.controller = ImportAgentManagerController(args.app_config)
        self.args = args
        self.event_queue: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.watch_service: Optional[ImportAgentWatchService] = None
        self.tray_icon: Optional[ImportAgentTrayIcon] = None
        self.watch_state_var = tk.StringVar(value="Watcher stopped.")
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
        self.auto_start_var = tk.BooleanVar(value=bool(args.auto_start))
        self.overwrite_var = tk.BooleanVar(value=bool(args.overwrite))
        self.source_library_choice_var = tk.StringVar(value="")
        self.wifi_address_var = tk.StringVar(value="")
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

        self._library_choice_map: dict[str, str] = {}
        self._source_runtime_status: dict[str, str] = {}
        self.sources_root_entry: Optional[ttk.Entry] = None
        self.libraries_root_entry: Optional[ttk.Entry] = None
        self.sources_root_browse_button: Optional[ttk.Button] = None
        self.libraries_root_browse_button: Optional[ttk.Button] = None
        self.create_initial_button: Optional[ttk.Button] = None
        self.add_library_button: Optional[ttk.Button] = None
        self.add_source_button: Optional[ttk.Button] = None
        self.apply_app_settings_button: Optional[ttk.Button] = None
        self.library_choice_combo: Optional[ttk.Combobox] = None
        self.source_type_combo: Optional[ttk.Combobox] = None
        self.wifi_frame: Optional[ttk.LabelFrame] = None

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
            columns=("display_name", "library_id", "syn_export", "artifacts_dir"),
            show="headings",
            height=9,
        )
        libraries_xscroll = ttk.Scrollbar(libraries_frame, orient="horizontal", command=libraries_tree.xview)
        libraries_tree.configure(xscrollcommand=libraries_xscroll.set)
        libraries_tree.heading("display_name", text="Display Name", anchor="w")
        libraries_tree.heading("library_id", text="Library ID", anchor="w")
        libraries_tree.heading("syn_export", text="Syn Export", anchor="w")
        libraries_tree.heading("artifacts_dir", text="Artifacts Directory", anchor="w")
        libraries_tree.column("display_name", width=180, anchor="w")
        libraries_tree.column("library_id", width=140, anchor="w")
        libraries_tree.column("syn_export", width=90, anchor="center", stretch=False)
        libraries_tree.column("artifacts_dir", width=520, anchor="w")
        libraries_tree.grid(row=0, column=0, sticky="nsew")
        libraries_xscroll.grid(row=1, column=0, sticky="ew")
        libraries_tree.bind("<Button-1>", self._on_libraries_tree_click)
        self.libraries_tree = libraries_tree

        sources_frame = ttk.Frame(lists)
        sources_frame.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        sources_frame.columnconfigure(0, weight=1)
        sources_frame.rowconfigure(0, weight=1)
        sources_tree = ttk.Treeview(
            sources_frame,
            columns=(
                "enabled",
                "attach_note",
                "display_name",
                "source_id",
                "source_type",
                "library_id",
                "status",
                "source_root",
            ),
            show="headings",
            height=9,
        )
        sources_xscroll = ttk.Scrollbar(sources_frame, orient="horizontal", command=sources_tree.xview)
        sources_tree.configure(xscrollcommand=sources_xscroll.set)
        sources_tree.heading("enabled", text="Enabled", anchor="w")
        sources_tree.heading("attach_note", text="Attach Note", anchor="w")
        sources_tree.heading("display_name", text="Display Name", anchor="w")
        sources_tree.heading("source_id", text="Source ID", anchor="w")
        sources_tree.heading("source_type", text="Type", anchor="w")
        sources_tree.heading("library_id", text="Library ID", anchor="w")
        sources_tree.heading("status", text="Status", anchor="w")
        sources_tree.heading("source_root", text="Source Root", anchor="w")
        sources_tree.column("enabled", width=80, anchor="center", stretch=False)
        sources_tree.column("attach_note", width=95, anchor="center", stretch=False)
        sources_tree.column("display_name", width=180, anchor="w")
        sources_tree.column("source_id", width=140, anchor="w")
        sources_tree.column("source_type", width=120, anchor="w")
        sources_tree.column("library_id", width=120, anchor="w")
        sources_tree.column("status", width=180, anchor="w")
        sources_tree.column("source_root", width=420, anchor="w")
        sources_tree.grid(row=0, column=0, sticky="nsew")
        sources_xscroll.grid(row=1, column=0, sticky="ew")
        sources_tree.bind("<Button-1>", self._on_sources_tree_click)
        self.sources_tree = sources_tree

        actions = ttk.Frame(parent)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 8))
        for col in range(6):
            actions.columnconfigure(col, weight=0)
        ttk.Button(actions, text="Refresh", command=self._refresh_ui_from_config).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Validate", command=self._validate_sources).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="Import Now", command=self._import_now).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(actions, text="Start Watch", command=self._start_watch).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(actions, text="Stop Watch", command=self._stop_watch).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(actions, text="Remove Source", command=self._remove_selected_source).grid(row=0, column=5)
        ttk.Button(actions, text="Check Logger", command=self._check_selected_logger).grid(
            row=1, column=0, padx=(0, 8), pady=(8, 0)
        )
        ttk.Button(actions, text="Request Upload Mode", command=self._request_selected_upload_mode).grid(
            row=1, column=1, padx=(0, 8), pady=(8, 0)
        )
        ttk.Button(actions, text="Open Logger Web UI", command=self._open_selected_logger_web_ui).grid(
            row=1, column=2, padx=(0, 8), pady=(8, 0)
        )

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
        ttk.Checkbutton(
            source_frame,
            text="Attach draft setup note on import",
            variable=self.attach_session_note_var,
        ).grid(row=5, column=1, sticky="w", pady=(6, 0), padx=(12, 8))

        self.wifi_frame = self._build_wifi_provision_frame(source_frame)
        self.wifi_frame.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 4))

        self.add_source_button = ttk.Button(source_frame, text="Add Source", command=self._add_source)
        self.add_source_button.grid(row=7, column=1, sticky="w", pady=(8, 0), padx=(12, 8))

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
        self.apply_app_settings_button = ttk.Button(
            actions,
            text="Apply App Settings",
            command=self._apply_app_settings,
        )
        self.apply_app_settings_button.grid(row=0, column=1)

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

        ttk.Label(frame, text="Logger address (optional)").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.wifi_address_var).grid(row=1, column=1, sticky="ew", pady=4, padx=(12, 8))
        ttk.Button(frame, text="Verify Logger", command=self._verify_logger_from_provision_form).grid(
            row=1, column=2, sticky="e", pady=4
        )

        ttk.Label(frame, text="After import").grid(row=2, column=0, sticky="w", pady=4)
        cleanup_combo = ttk.Combobox(
            frame,
            textvariable=self.wifi_cleanup_choice_var,
            values=list(_LOGGER_WIFI_CLEANUP_BY_LABEL),
            state="readonly",
        )
        cleanup_combo.grid(row=2, column=1, sticky="ew", pady=4, padx=(12, 8))

        timeouts = ttk.Frame(frame)
        timeouts.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(timeouts, text="Request timeout (s)").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(timeouts, textvariable=self.wifi_request_timeout_var, width=8).grid(
            row=0, column=1, sticky="w", padx=(0, 18)
        )
        ttk.Label(timeouts, text="Download timeout (s)").grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Entry(timeouts, textvariable=self.wifi_download_timeout_var, width=8).grid(
            row=0, column=3, sticky="w"
        )

        ttk.Label(frame, textvariable=self.wifi_status_var, wraplength=880, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )
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

    def _sync_source_type_fields(self) -> None:
        if self.wifi_frame is None:
            return
        if self._selected_source_type() == SOURCE_TYPE_LOGGER_WIFI:
            self.wifi_frame.grid()
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
        base_url = self.wifi_address_var.get().strip()
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
        if result.base_url:
            self.wifi_address_var.set(result.base_url)
        if result.logger_id:
            self.wifi_logger_id_var.set(result.logger_id)
        display_name = result.display_name or result.logger_id or result.hostname or "Wi-Fi Logger"
        if self.source_name_var.get().strip() in {"", "Default Source"}:
            self.source_name_var.set(display_name)
        upload_text = "unknown" if result.upload_mode is None else ("yes" if result.upload_mode else "no")
        self.wifi_status_var.set(
            f"Discovered {display_name} at {result.base_url}; upload_mode={upload_text}."
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
            results = discover_logger_wifi_sources(timeout_s=timeout_s)
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
        if base_url is None:
            result = discover_single_logger_wifi_source(
                logger_id=source.logger_wifi.logger_id,
                timeout_s=max(1.0, min(float(source.logger_wifi.request_timeout_s), 5.0)),
            )
            if result is None:
                raise ValueError(
                    f"Selected Wi-Fi source '{source.logger_wifi.logger_id}' was not discovered on the local network."
                )
            base_url = result.base_url
        client = LoggerWifiApiClient(
            base_url,
            request_timeout_s=source.logger_wifi.request_timeout_s,
            download_timeout_s=source.logger_wifi.download_timeout_s,
        )
        return client, source

    def _set_source_runtime_status(self, source_id: str, status: str) -> None:
        self._source_runtime_status[source_id] = status
        if self.sources_tree is None or not self.sources_tree.exists(source_id):
            return
        values = list(self.sources_tree.item(source_id, "values"))
        if len(values) >= 7:
            values[6] = status
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
            self._render_libraries([])
            self._render_sources([])
            self._library_choice_map = {}
            if self.library_choice_combo is not None:
                self.library_choice_combo.configure(values=[])
            self.source_library_choice_var.set("")
            self._set_root_editable(True)
            if self.create_initial_button is not None:
                self.create_initial_button.configure(state="normal")
            if self.add_library_button is not None:
                self.add_library_button.configure(state="disabled")
            if self.add_source_button is not None:
                self.add_source_button.configure(state="disabled")
            if self.apply_app_settings_button is not None:
                self.apply_app_settings_button.configure(state="disabled")
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
        if self.add_library_button is not None:
            self.add_library_button.configure(state="normal")
        if self.add_source_button is not None:
            self.add_source_button.configure(state="normal")
        if self.apply_app_settings_button is not None:
            self.apply_app_settings_button.configure(state="normal")
        self._refresh_tray()

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
                    library.library_id,
                    (
                        _SOURCE_ENABLED_CHECKED
                        if getattr(library, "data_syn_bike_export_enabled", False)
                        else _SOURCE_ENABLED_UNCHECKED
                    ),
                    str(library.artifacts_dir),
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
            self.sources_tree.insert(
                "",
                "end",
                iid=source.source_id,
                values=(
                    _SOURCE_ENABLED_CHECKED if source.enabled else _SOURCE_ENABLED_UNCHECKED,
                    (
                        _SOURCE_ENABLED_CHECKED
                        if getattr(source, "attach_session_note_on_import", False)
                        else _SOURCE_ENABLED_UNCHECKED
                    ),
                    source.display_name,
                    source.source_id,
                    _SOURCE_TYPE_LABELS.get(source.source_type, source.source_type),
                    source.library_id,
                    status_text,
                    str(source.source_root),
                ),
            )

    def _selected_source_id(self) -> Optional[str]:
        if self.sources_tree is None:
            return None
        selection = self.sources_tree.selection()
        return str(selection[0]) if selection else None

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

    def _on_sources_tree_click(self, event: tk.Event) -> Optional[str]:
        if self.sources_tree is None:
            return None
        region = self.sources_tree.identify("region", event.x, event.y)
        if region != "cell":
            return None
        column = self.sources_tree.identify_column(event.x)
        if column not in {"#1", "#2"}:
            return None
        source_id = self.sources_tree.identify_row(event.y)
        if not source_id:
            return None
        self.sources_tree.selection_set(source_id)
        if column == "#1":
            self._toggle_source_enabled(source_id)
        else:
            self._toggle_source_session_note_attach(source_id)
        return "break"

    def _on_libraries_tree_click(self, event: tk.Event) -> Optional[str]:
        if self.libraries_tree is None:
            return None
        region = self.libraries_tree.identify("region", event.x, event.y)
        if region != "cell":
            return None
        if self.libraries_tree.identify_column(event.x) != "#3":
            return None
        library_id = self.libraries_tree.identify_row(event.y)
        if not library_id:
            return None
        self.libraries_tree.selection_set(library_id)
        self._toggle_library_syn_export(library_id)
        return "break"

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

    def _has_enabled_sources(self) -> bool:
        config = self.controller.app_config
        return bool(config and any(source.enabled for source in config.sources))

    def _window_visible(self) -> bool:
        return self.root.state() != "withdrawn"

    def _guard_watch_inactive(self, *, action_label: str) -> bool:
        if self._watch_running():
            messagebox.showinfo(
                _APP_DISPLAY_NAME,
                f"Stop the watcher before running '{action_label}'.",
                parent=self.root,
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
            "can_start_watch": config is not None and self._has_enabled_sources() and not self._watch_running(),
            "can_stop_watch": self._watch_running(),
            "can_import_now": config is not None and not self._watch_running(),
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
        if self.tray_icon is not None:
            self.tray_icon.stop()
            self.tray_icon = None
        self.root.destroy()

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
                auto_start=bool(self.auto_start_var.get()),
                overwrite=bool(self.overwrite_var.get()),
            )
        except Exception as exc:
            self._set_provision_status(f"Initial setup failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
        self._sync_startup_registration(show_errors=True, emit_status=False)
        self._set_provision_status(
            f"Created initial library '{result.library.display_name}' and source '{result.source.display_name}'."
        )
        if self.notebook is not None:
            self.notebook.select(0)

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
                overwrite=bool(self.overwrite_var.get()),
            )
        except Exception as exc:
            self._set_provision_status(f"Add source failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
        self._set_provision_status(f"Added source '{source.display_name}'.")

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
        try:
            report, snapshot = self.controller.import_once()
        except Exception as exc:
            self._set_manager_status(f"Import failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return

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

    def _remove_selected_source(self) -> None:
        if not self._guard_watch_inactive(action_label="Remove Source"):
            return
        source_id = self._selected_source_id()
        if source_id is None:
            messagebox.showinfo(_APP_DISPLAY_NAME, "Select a source first.", parent=self.root)
            return
        try:
            source = self._selected_source_config()
        except Exception as exc:
            self._set_manager_status(f"Remove source failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        confirmed = messagebox.askyesno(
            "Remove Source",
            (
                f"Remove source '{source.description or source.source_id}' from the manager?\n\n"
                "This only removes the source from the app configuration. "
                "Existing files and directories will not be deleted."
            ),
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self.controller.remove_source(source_id)
        except Exception as exc:
            self._set_manager_status(f"Remove source failed: {exc}")
            messagebox.showerror(_APP_DISPLAY_NAME, str(exc), parent=self.root)
            return
        self._source_runtime_status.pop(source_id, None)
        self._refresh_ui_from_config()
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
    window = ImportAgentManagerWindow(args)
    return window.run()
