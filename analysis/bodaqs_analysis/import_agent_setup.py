from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from zoneinfo import available_timezones

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .import_agent import ImportAgentSupervisor, validate_import_sources
from .import_agent_provisioning import (
    ImportAgentAppConfig,
    load_import_agent_app_config,
    managed_import_agent_source_roots,
    provision_import_agent_app_setup,
    provision_import_agent_library_for_app,
    provision_import_agent_source_for_app,
    runtime_import_agent_app_config_path,
    update_import_agent_source_enabled,
)


def _default_workspace_root() -> Path:
    return Path.home() / "BODAQS"


def _default_sources_root() -> Path:
    return _default_workspace_root() / "sources"


def _default_libraries_root() -> Path:
    return _default_workspace_root() / "libraries"


def _default_app_config_path() -> Path:
    preferred_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    return runtime_import_agent_app_config_path(preferred_dir=preferred_dir)


def available_logger_timezones() -> list[str]:
    try:
        zones = sorted(str(item) for item in available_timezones() if str(item).strip())
    except Exception:
        zones = []
    if not zones:
        zones = ["UTC", "Australia/Perth"]
    return ["", *zones]


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bodaqs-import-setup",
        description="Create or manage a local BODAQS import-agent desktop setup.",
    )
    parser.add_argument("--app-config", default=str(_default_app_config_path()), help=argparse.SUPPRESS)
    parser.add_argument("--sources-root", default=str(_default_sources_root()))
    parser.add_argument("--libraries-root", default=str(_default_libraries_root()))
    parser.add_argument("--library-name", default="Default Library")
    parser.add_argument("--source-name", default="Default Source")
    parser.add_argument("--logger-timezone", default="")
    parser.add_argument("--run-tz-label", default="LOCAL")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--auto-start", action="store_true")
    parser.add_argument("--disable-events", action="store_true")
    parser.add_argument("--disable-metrics", action="store_true")
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
        logger_timezone: Optional[str],
        run_tz_label: str,
        include_events: bool,
        include_metrics: bool,
        auto_start: bool,
        overwrite: bool,
    ) -> Any:
        result = provision_import_agent_app_setup(
            sources_root=sources_root,
            libraries_root=libraries_root,
            library_display_name=library_display_name,
            source_display_name=source_display_name,
            app_config_path=self.app_config_path,
            logger_timezone=logger_timezone,
            run_tz_label=run_tz_label,
            include_events=include_events,
            include_metrics=include_metrics,
            auto_start=auto_start,
            overwrite=overwrite,
        )
        self.app_config = result.app_config
        return result

    def add_library(self, *, display_name: str, overwrite: bool) -> Any:
        updated, library = provision_import_agent_library_for_app(
            self.app_config_path,
            display_name=display_name,
            overwrite=overwrite,
        )
        self.app_config = updated
        return library

    def add_source(
        self,
        *,
        library_id: str,
        display_name: str,
        logger_timezone: Optional[str],
        run_tz_label: str,
        include_events: bool,
        include_metrics: bool,
        overwrite: bool,
    ) -> Any:
        updated, source = provision_import_agent_source_for_app(
            self.app_config_path,
            library_id=library_id,
            display_name=display_name,
            logger_timezone=logger_timezone,
            run_tz_label=run_tz_label,
            include_events=include_events,
            include_metrics=include_metrics,
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
        self.root = tk.Tk()
        self.root.title("BODAQS Import Agent Manager")
        self.root.geometry("1120x760")
        self.root.minsize(980, 680)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.controller = ImportAgentManagerController(args.app_config)
        self.event_queue: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.watch_service: Optional[ImportAgentWatchService] = None
        self.watch_state_var = tk.StringVar(value="Watcher stopped.")
        self.manager_status_var = tk.StringVar(value="Ready.")
        self.provision_status_var = tk.StringVar(value="Ready to provision or extend the managed setup.")
        self.summary_var = tk.StringVar(value="")

        self.sources_root_var = tk.StringVar(value=str(args.sources_root))
        self.libraries_root_var = tk.StringVar(value=str(args.libraries_root))
        self.library_name_var = tk.StringVar(value=str(args.library_name))
        self.source_name_var = tk.StringVar(value=str(args.source_name))
        self.logger_timezone_var = tk.StringVar(value=str(args.logger_timezone or ""))
        self.run_tz_label_var = tk.StringVar(value=str(args.run_tz_label or "LOCAL"))
        self.include_events_var = tk.BooleanVar(value=not bool(args.disable_events))
        self.include_metrics_var = tk.BooleanVar(value=not bool(args.disable_metrics))
        self.auto_start_var = tk.BooleanVar(value=bool(args.auto_start))
        self.overwrite_var = tk.BooleanVar(value=bool(args.overwrite))
        self.source_library_choice_var = tk.StringVar(value="")

        self._library_choice_map: dict[str, str] = {}
        self.sources_root_entry: Optional[ttk.Entry] = None
        self.libraries_root_entry: Optional[ttk.Entry] = None
        self.sources_root_browse_button: Optional[ttk.Button] = None
        self.libraries_root_browse_button: Optional[ttk.Button] = None
        self.create_initial_button: Optional[ttk.Button] = None
        self.add_library_button: Optional[ttk.Button] = None
        self.add_source_button: Optional[ttk.Button] = None
        self.library_choice_combo: Optional[ttk.Combobox] = None
        self.logger_timezone_combo: Optional[ttk.Combobox] = None

        self.libraries_tree: Optional[ttk.Treeview] = None
        self.sources_tree: Optional[ttk.Treeview] = None
        self.log_text: Optional[tk.Text] = None
        self.notebook: Optional[ttk.Notebook] = None

        self._build()
        self._refresh_ui_from_config(select_provision_when_missing=True)
        self.root.after(250, self._poll_event_queue)

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

        libraries_tree = ttk.Treeview(
            lists,
            columns=("display_name", "library_id", "artifacts_dir"),
            show="headings",
            height=9,
        )
        libraries_tree.heading("display_name", text="Display Name")
        libraries_tree.heading("library_id", text="Library ID")
        libraries_tree.heading("artifacts_dir", text="Artifacts Directory")
        libraries_tree.column("display_name", width=180, anchor="w")
        libraries_tree.column("library_id", width=140, anchor="w")
        libraries_tree.column("artifacts_dir", width=320, anchor="w")
        libraries_tree.grid(row=1, column=0, sticky="nsew")
        self.libraries_tree = libraries_tree

        sources_tree = ttk.Treeview(
            lists,
            columns=("display_name", "source_id", "library_id", "enabled", "source_root"),
            show="headings",
            height=9,
        )
        sources_tree.heading("display_name", text="Display Name")
        sources_tree.heading("source_id", text="Source ID")
        sources_tree.heading("library_id", text="Library ID")
        sources_tree.heading("enabled", text="Enabled")
        sources_tree.heading("source_root", text="Source Root")
        sources_tree.column("display_name", width=180, anchor="w")
        sources_tree.column("source_id", width=140, anchor="w")
        sources_tree.column("library_id", width=120, anchor="w")
        sources_tree.column("enabled", width=80, anchor="center")
        sources_tree.column("source_root", width=320, anchor="w")
        sources_tree.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        self.sources_tree = sources_tree

        actions = ttk.Frame(parent)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 8))
        for col in range(7):
            actions.columnconfigure(col, weight=0)
        ttk.Button(actions, text="Refresh", command=self._refresh_ui_from_config).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Validate", command=self._validate_sources).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="Import Now", command=self._import_now).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(actions, text="Start Watch", command=self._start_watch).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(actions, text="Stop Watch", command=self._stop_watch).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(actions, text="Enable Source", command=self._enable_selected_source).grid(
            row=0, column=5, padx=(0, 8)
        )
        ttk.Button(actions, text="Disable Source", command=self._disable_selected_source).grid(row=0, column=6)

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
        parent.columnconfigure(1, weight=1)

        ttk.Label(
            parent,
            text=(
                "Create the first managed library and source, or extend an existing managed setup "
                "with another library or source."
            ),
            wraplength=980,
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))

        self.sources_root_entry = self._add_text_row(
            parent=parent,
            row=1,
            label="Sources root",
            variable=self.sources_root_var,
            browse_command=lambda: self._choose_directory(self.sources_root_var, "Choose sources root"),
        )
        self.libraries_root_entry = self._add_text_row(
            parent=parent,
            row=2,
            label="Libraries root",
            variable=self.libraries_root_var,
            browse_command=lambda: self._choose_directory(self.libraries_root_var, "Choose libraries root"),
        )
        self._add_text_row(parent=parent, row=3, label="Library name", variable=self.library_name_var)
        combo = ttk.Combobox(parent, textvariable=self.source_library_choice_var, state="readonly")
        ttk.Label(parent, text="Source target library").grid(row=4, column=0, sticky="w", pady=4)
        combo.grid(row=4, column=1, sticky="ew", pady=4, padx=(12, 8))
        self.library_choice_combo = combo
        self._add_text_row(parent=parent, row=5, label="Source name", variable=self.source_name_var)
        ttk.Label(parent, text="Logger timezone (optional)").grid(row=6, column=0, sticky="w", pady=4)
        logger_timezone_combo = ttk.Combobox(
            parent,
            textvariable=self.logger_timezone_var,
            values=available_logger_timezones(),
            state="normal",
        )
        logger_timezone_combo.grid(row=6, column=1, sticky="ew", pady=4, padx=(12, 8))
        self.logger_timezone_combo = logger_timezone_combo
        self._add_text_row(parent=parent, row=7, label="Run TZ label", variable=self.run_tz_label_var)

        options = ttk.Frame(parent)
        options.grid(row=8, column=0, columnspan=3, sticky="w", pady=(12, 8))
        ttk.Checkbutton(options, text="Include events", variable=self.include_events_var).grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Checkbutton(options, text="Include metrics", variable=self.include_metrics_var).grid(
            row=0, column=1, sticky="w", padx=(0, 12)
        )
        ttk.Checkbutton(options, text="Store auto-start preference", variable=self.auto_start_var).grid(
            row=0, column=2, sticky="w", padx=(0, 12)
        )
        ttk.Checkbutton(options, text="Overwrite existing seeded files", variable=self.overwrite_var).grid(
            row=0, column=3, sticky="w"
        )

        actions = ttk.Frame(parent)
        actions.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        actions.columnconfigure(0, weight=0)
        actions.columnconfigure(1, weight=0)
        actions.columnconfigure(2, weight=0)
        self.create_initial_button = ttk.Button(
            actions,
            text="Create Initial Library + Source",
            command=self._create_initial_setup,
        )
        self.create_initial_button.grid(row=0, column=0, padx=(0, 8))
        self.add_library_button = ttk.Button(actions, text="Add Library", command=self._add_library)
        self.add_library_button.grid(row=0, column=1, padx=(0, 8))
        self.add_source_button = ttk.Button(actions, text="Add Source", command=self._add_source)
        self.add_source_button.grid(row=0, column=2)

        ttk.Label(parent, textvariable=self.provision_status_var, wraplength=980, justify="left").grid(
            row=10, column=0, columnspan=3, sticky="ew", pady=(10, 0)
        )

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
            if select_provision_when_missing and self.notebook is not None:
                self.notebook.select(1)
            return

        self.sources_root_var.set(str(config.sources_root))
        self.libraries_root_var.set(str(config.libraries_root))
        enabled_count = sum(1 for source in config.sources if source.enabled)
        self.summary_var.set(
            "Managed roots: "
            f"sources={config.sources_root} | libraries={config.libraries_root} | "
            f"libraries={len(config.libraries)} | sources={len(config.sources)} | enabled sources={enabled_count}"
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
                values=(library.display_name, library.library_id, str(library.artifacts_dir)),
            )

    def _render_sources(self, sources: Sequence[Any]) -> None:
        if self.sources_tree is None:
            return
        self.sources_tree.delete(*self.sources_tree.get_children())
        for source in sources:
            self.sources_tree.insert(
                "",
                "end",
                iid=source.source_id,
                values=(
                    source.display_name,
                    source.source_id,
                    source.library_id,
                    "yes" if source.enabled else "no",
                    str(source.source_root),
                ),
            )

    def _selected_source_id(self) -> Optional[str]:
        if self.sources_tree is None:
            return None
        selection = self.sources_tree.selection()
        return str(selection[0]) if selection else None

    def _selected_library_id_from_choice(self) -> Optional[str]:
        label = self.source_library_choice_var.get().strip()
        return self._library_choice_map.get(label)

    def _watch_running(self) -> bool:
        return self.watch_service is not None and self.watch_service.running

    def _guard_watch_inactive(self, *, action_label: str) -> bool:
        if self._watch_running():
            messagebox.showinfo(
                "BODAQS Import Agent Manager",
                f"Stop the watcher before running '{action_label}'.",
                parent=self.root,
            )
            return False
        return True

    def _create_initial_setup(self) -> None:
        if not self._guard_watch_inactive(action_label="Create Initial Library + Source"):
            return
        try:
            result = self.controller.create_initial_setup(
                sources_root=self.sources_root_var.get(),
                libraries_root=self.libraries_root_var.get(),
                library_display_name=self.library_name_var.get(),
                source_display_name=self.source_name_var.get(),
                logger_timezone=self.logger_timezone_var.get().strip() or None,
                run_tz_label=self.run_tz_label_var.get().strip() or "LOCAL",
                include_events=bool(self.include_events_var.get()),
                include_metrics=bool(self.include_metrics_var.get()),
                auto_start=bool(self.auto_start_var.get()),
                overwrite=bool(self.overwrite_var.get()),
            )
        except Exception as exc:
            self._set_provision_status(f"Initial setup failed: {exc}")
            messagebox.showerror("BODAQS Import Agent Manager", str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
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
                overwrite=bool(self.overwrite_var.get()),
            )
        except Exception as exc:
            self._set_provision_status(f"Add library failed: {exc}")
            messagebox.showerror("BODAQS Import Agent Manager", str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
        self._set_provision_status(f"Added library '{library.display_name}'.")

    def _add_source(self) -> None:
        if not self._guard_watch_inactive(action_label="Add Source"):
            return
        library_id = self._selected_library_id_from_choice()
        if library_id is None:
            messagebox.showinfo(
                "BODAQS Import Agent Manager",
                "Select a target library for the new source first.",
                parent=self.root,
            )
            return
        try:
            source = self.controller.add_source(
                library_id=library_id,
                display_name=self.source_name_var.get(),
                logger_timezone=self.logger_timezone_var.get().strip() or None,
                run_tz_label=self.run_tz_label_var.get().strip() or "LOCAL",
                include_events=bool(self.include_events_var.get()),
                include_metrics=bool(self.include_metrics_var.get()),
                overwrite=bool(self.overwrite_var.get()),
            )
        except Exception as exc:
            self._set_provision_status(f"Add source failed: {exc}")
            messagebox.showerror("BODAQS Import Agent Manager", str(exc), parent=self.root)
            return

        self._refresh_ui_from_config()
        self._set_provision_status(f"Added source '{source.display_name}'.")

    def _validate_sources(self) -> None:
        if not self._guard_watch_inactive(action_label="Validate"):
            return
        try:
            results = self.controller.validate_sources(enabled_only=False)
        except Exception as exc:
            self._set_manager_status(f"Validation failed: {exc}")
            messagebox.showerror("BODAQS Import Agent Manager", str(exc), parent=self.root)
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
            messagebox.showerror("BODAQS Import Agent Manager", str(exc), parent=self.root)
            return

        totals = report.get("totals", {})
        self._set_manager_status(
            "Import complete: "
            f"seen={totals.get('seen', 0)} imported={totals.get('imported', 0)} "
            f"deferred={totals.get('deferred_unsettled', 0)} failed={totals.get('failed', 0)}"
        )
        for source_report in report.get("sources", []):
            source_totals = _aggregate_reports([source_report])
            self._append_log(
                f"Import source {source_report['source_id']}: "
                f"seen={source_totals['seen']} imported={source_totals['imported']} "
                f"deferred={source_totals['deferred_unsettled']} failed={source_totals['failed']}"
            )
        self._apply_snapshot(snapshot)

    def _start_watch(self) -> None:
        if self._watch_running():
            return
        try:
            supervisor = self.controller.make_enabled_supervisor()
        except Exception as exc:
            self._set_manager_status(f"Unable to start watch: {exc}")
            messagebox.showerror("BODAQS Import Agent Manager", str(exc), parent=self.root)
            return

        self.watch_service = ImportAgentWatchService(supervisor, self.event_queue)
        self.watch_service.start()
        self.watch_state_var.set("Watcher starting...")
        self._set_manager_status("Started watch loop.")

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

    def _enable_selected_source(self) -> None:
        if not self._guard_watch_inactive(action_label="Enable Source"):
            return
        source_id = self._selected_source_id()
        if source_id is None:
            messagebox.showinfo("BODAQS Import Agent Manager", "Select a source first.", parent=self.root)
            return
        try:
            self.controller.set_source_enabled(source_id, True)
        except Exception as exc:
            self._set_manager_status(f"Enable source failed: {exc}")
            messagebox.showerror("BODAQS Import Agent Manager", str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        self._set_manager_status(f"Enabled source '{source_id}'.")

    def _disable_selected_source(self) -> None:
        if not self._guard_watch_inactive(action_label="Disable Source"):
            return
        source_id = self._selected_source_id()
        if source_id is None:
            messagebox.showinfo("BODAQS Import Agent Manager", "Select a source first.", parent=self.root)
            return
        try:
            self.controller.set_source_enabled(source_id, False)
        except Exception as exc:
            self._set_manager_status(f"Disable source failed: {exc}")
            messagebox.showerror("BODAQS Import Agent Manager", str(exc), parent=self.root)
            return
        self._refresh_ui_from_config()
        self._set_manager_status(f"Disabled source '{source_id}'.")

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
                    "BODAQS Import Agent Manager",
                    str(item.get("error") or "Unknown watch error"),
                    parent=self.root,
                )
            elif kind == "watch_stopped":
                self.watch_state_var.set("Watcher stopped.")
                self._append_log("Watcher stopped.")
                self._apply_snapshot(item.get("snapshot", {}))
                if self.watch_service is not None and not self.watch_service.running:
                    self.watch_service = None

        self.root.after(250, self._poll_event_queue)

    def _on_close(self) -> None:
        if self.watch_service is not None:
            self.watch_service.stop(timeout_s=2.0)
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    window = ImportAgentManagerWindow(args)
    return window.run()
