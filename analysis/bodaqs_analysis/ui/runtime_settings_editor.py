from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import ipywidgets as W


def _optional_text(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def _optional_path(value: Any) -> Optional[Path]:
    text = _optional_text(value)
    return Path(text) if text is not None else None


def _paths_to_text(paths: Optional[Sequence[str | Path]]) -> str:
    if not paths:
        return ""
    return "\n".join(str(p) for p in paths if _optional_text(p) is not None)


def _paths_from_text(text: str) -> Optional[List[Path]]:
    paths = [Path(line.strip()) for line in (text or "").splitlines() if line.strip()]
    return paths or None


def _stretch_layout(**kwargs: Any) -> W.Layout:
    return W.Layout(width="auto", flex="1 1 auto", min_width="0", **kwargs)


def _full_width_layout(**kwargs: Any) -> W.Layout:
    return W.Layout(width="100%", min_width="0", **kwargs)


def _row(children: List[W.Widget]) -> W.HBox:
    return W.HBox(children, layout=W.Layout(width="100%", min_width="0", overflow="hidden"))


class PreprocessRuntimeSettingsEditor:
    """
    Notebook widget for run-level preprocessing settings.

    These settings are deliberately local/runtime concerns rather than part of a
    persisted preprocess profile. They describe where this notebook should find
    local inputs and where it should write artifacts for the current run.
    """

    def __init__(
        self,
        *,
        preprocess_profile_path: str | Path = Path("config/preprocess_profiles/suspension_default_v1.json"),
        artifacts_dir: str | Path = Path("artifacts"),
        generic_log_metadata_paths: Optional[Sequence[str | Path]] = None,
        bike_profile_path: Optional[str | Path] = Path("config/bike_profiles/example_enduro_bike_v1.json"),
        fit_dir: Optional[str | Path] = Path("Garmin/FIT"),
        fit_bindings_path: Optional[str | Path] = Path("config/fit_bindings_v1.json"),
        prompt_for_descriptions: bool = True,
        run_tz_label: str = "AWST",
    ) -> None:
        self._bound_log_selectors: List[Any] = []

        self.w_preprocess_profile_path = W.Text(
            value=str(preprocess_profile_path),
            description="Profile",
            layout=_stretch_layout(),
        )
        self.b_profile_browse = W.Button(description="Browse...", icon="file", layout=W.Layout(width="120px"))

        self.w_artifacts_dir = W.Text(
            value=str(artifacts_dir),
            description="Artifacts",
            layout=_stretch_layout(),
        )
        self.b_artifacts_browse = W.Button(description="Browse...", icon="folder-open", layout=W.Layout(width="120px"))

        self.w_generic_log_metadata_paths = W.Textarea(
            value=_paths_to_text(generic_log_metadata_paths),
            description="Log metadata",
            placeholder="One generic log metadata file or directory per line. Leave blank for same-stem metadata/header parsing only.",
            layout=_full_width_layout(height="96px"),
        )
        self.b_add_log_metadata_file = W.Button(description="Add file", icon="file")
        self.b_add_log_metadata_dir = W.Button(description="Add dir", icon="folder-open")
        self.b_clear_log_metadata = W.Button(description="Clear", icon="times")

        self.w_bike_profile_path = W.Text(
            value=str(bike_profile_path) if bike_profile_path is not None else "",
            description="Bike profile",
            layout=_stretch_layout(),
        )
        self.b_bike_profile_browse = W.Button(description="Browse...", icon="file", layout=W.Layout(width="120px"))

        self.w_fit_dir = W.Text(
            value=str(fit_dir) if fit_dir is not None else "",
            description="FIT dir",
            layout=_stretch_layout(),
        )
        self.b_fit_dir_browse = W.Button(description="Browse...", icon="folder-open", layout=W.Layout(width="120px"))

        self.w_fit_bindings_path = W.Text(
            value=str(fit_bindings_path) if fit_bindings_path is not None else "",
            description="FIT bindings",
            layout=_stretch_layout(),
        )
        self.b_fit_bindings_browse = W.Button(description="Browse...", icon="file", layout=W.Layout(width="120px"))

        self.w_run_tz_label = W.Text(
            value=str(run_tz_label or "AWST"),
            description="Run TZ",
            layout=W.Layout(width="240px"),
        )
        self.w_prompt_for_descriptions = W.Checkbox(
            value=bool(prompt_for_descriptions),
            description="Prompt for run/session descriptions",
        )

        self.b_validate = W.Button(description="Validate", button_style="info", icon="check")
        self._out = W.Output(layout=W.Layout(border="1px solid #ddd", padding="8px"))

        self.b_profile_browse.on_click(lambda _: self._browse_file(self.w_preprocess_profile_path, "Select preprocess profile JSON"))
        self.b_artifacts_browse.on_click(lambda _: self._browse_dir(self.w_artifacts_dir, "Select artifacts directory"))
        self.b_add_log_metadata_file.on_click(lambda _: self._add_generic_log_metadata_file())
        self.b_add_log_metadata_dir.on_click(lambda _: self._add_generic_log_metadata_dir())
        self.b_clear_log_metadata.on_click(lambda _: setattr(self.w_generic_log_metadata_paths, "value", ""))
        self.b_bike_profile_browse.on_click(lambda _: self._browse_file(self.w_bike_profile_path, "Select bike profile JSON"))
        self.b_fit_dir_browse.on_click(lambda _: self._browse_dir(self.w_fit_dir, "Select FIT directory"))
        self.b_fit_bindings_browse.on_click(lambda _: self._browse_file(self.w_fit_bindings_path, "Select FIT bindings JSON"))
        self.b_validate.on_click(lambda _: self.validate(print_to_output=True))
        self.w_artifacts_dir.observe(lambda _: self._sync_bound_log_selectors(), names="value")

        self.ui = self._build_ui()

    def _section(self, title: str, help_text: str, children: List[W.Widget]) -> W.VBox:
        return W.VBox(
            [
                W.HTML(f"<h3 style='margin: 16px 0 6px 0'>{title}</h3>"),
                W.HTML(
                    "<p style='margin:0 0 10px 0;color:#555;line-height:1.35;white-space:normal'>"
                    f"{help_text}"
                    "</p>"
                ),
                *children,
            ],
            layout=W.Layout(width="100%", min_width="0", overflow="hidden"),
        )

    def _build_ui(self) -> W.VBox:
        return W.VBox(
            [
                self._section(
                    "Runtime Paths",
                    "Choose the local files and folders this notebook should use for this run. These values are not saved inside the preprocess profile.",
                    [
                        _row([self.w_preprocess_profile_path, self.b_profile_browse]),
                        _row([self.w_artifacts_dir, self.b_artifacts_browse]),
                        _row([self.w_bike_profile_path, self.b_bike_profile_browse]),
                    ],
                ),
                self._section(
                    "Logger Metadata",
                    "Select reusable generic log metadata fallbacks for logs that do not have same-stem metadata beside the CSV.",
                    [
                        self.w_generic_log_metadata_paths,
                        _row([self.b_add_log_metadata_file, self.b_add_log_metadata_dir, self.b_clear_log_metadata]),
                    ],
                ),
                self._section(
                    "Optional FIT Inputs",
                    "Point to local Garmin FIT sources and the binding manifest used when more than one FIT file overlaps a logger session.",
                    [
                        _row([self.w_fit_dir, self.b_fit_dir_browse]),
                        _row([self.w_fit_bindings_path, self.b_fit_bindings_browse]),
                    ],
                ),
                self._section(
                    "Run Behaviour",
                    "Set local run labelling and whether the notebook should ask for free-text descriptions after writing artifacts.",
                    [
                        _row([self.w_run_tz_label, self.w_prompt_for_descriptions]),
                        _row([self.b_validate]),
                        self._out,
                    ],
                ),
            ],
            layout=W.Layout(width="100%", min_width="0", overflow="hidden"),
        )

    def get_settings(self) -> Dict[str, Any]:
        """Return the current runtime settings as notebook-friendly values."""
        return {
            "preprocess_profile_path": Path(str(self.w_preprocess_profile_path.value).strip()),
            "artifacts_dir": Path(str(self.w_artifacts_dir.value).strip()),
            "generic_log_metadata_paths": _paths_from_text(self.w_generic_log_metadata_paths.value),
            "bike_profile_path": _optional_path(self.w_bike_profile_path.value),
            "fit_dir": _optional_path(self.w_fit_dir.value),
            "fit_bindings_path": _optional_path(self.w_fit_bindings_path.value),
            "prompt_for_descriptions": bool(self.w_prompt_for_descriptions.value),
            "run_tz_label": str(self.w_run_tz_label.value or "").strip() or "AWST",
        }

    def validate(self, *, print_to_output: bool = False) -> tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []
        settings = self.get_settings()

        if not str(settings["preprocess_profile_path"]).strip():
            errors.append("Preprocess profile path is blank.")
        elif not settings["preprocess_profile_path"].exists():
            warnings.append(f"Preprocess profile does not exist yet: {settings['preprocess_profile_path']}")

        if not str(settings["artifacts_dir"]).strip():
            errors.append("Artifacts directory is blank.")
        elif not settings["artifacts_dir"].exists():
            warnings.append(f"Artifacts directory does not exist yet and may be created later: {settings['artifacts_dir']}")

        bike_profile_path = settings["bike_profile_path"]
        if bike_profile_path is None:
            warnings.append("Bike profile path is blank; preprocessing will fail unless the notebook supplies one another way.")
        elif not bike_profile_path.exists():
            warnings.append(f"Bike profile does not exist: {bike_profile_path}")

        for p in settings["generic_log_metadata_paths"] or []:
            if not p.exists():
                warnings.append(f"Generic log metadata path does not exist: {p}")

        fit_dir = settings["fit_dir"]
        if fit_dir is not None and not fit_dir.exists():
            warnings.append(f"FIT directory does not exist: {fit_dir}")

        fit_bindings_path = settings["fit_bindings_path"]
        if fit_bindings_path is not None and not fit_bindings_path.exists():
            warnings.append(f"FIT bindings path does not exist: {fit_bindings_path}")

        if print_to_output:
            with self._out:
                self._out.clear_output()
                if errors:
                    print("Errors:")
                    for item in errors:
                        print(" -", item)
                else:
                    print("No blocking errors.")
                if warnings:
                    print("\nWarnings:")
                    for item in warnings:
                        print(" -", item)

        return errors, warnings

    def bind_log_selector(self, selector: Any) -> None:
        """
        Keep a ``PreprocessLogSelector`` artifact directory aligned with this widget.

        The selector is intentionally still created by the notebook; this binding
        just means changing the runtime artifact directory refreshes processed-file
        status without requiring a manual selector rebuild.
        """
        if selector not in self._bound_log_selectors:
            self._bound_log_selectors.append(selector)
        self._sync_selector(selector)

    def _sync_bound_log_selectors(self) -> None:
        for selector in list(self._bound_log_selectors):
            self._sync_selector(selector)

    def _sync_selector(self, selector: Any) -> None:
        try:
            selector.artifacts_dir = Path(str(self.w_artifacts_dir.value).strip())
            selector.refresh()
        except Exception:
            # Best-effort convenience only; processing cells still read settings directly.
            pass

    def _browse_file(self, widget: W.Text, title: str) -> None:
        import tkinter as tk
        from tkinter import filedialog

        current = _optional_text(widget.value)
        start_dir = str(Path(current).parent) if current else str(Path.cwd())
        if not Path(start_dir).exists():
            start_dir = str(Path.cwd())

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askopenfilename(title=title, initialdir=start_dir)
        root.destroy()

        if chosen:
            widget.value = chosen

    def _browse_dir(self, widget: W.Text, title: str) -> None:
        import tkinter as tk
        from tkinter import filedialog

        current = _optional_text(widget.value)
        start_dir = current if current and Path(current).exists() else str(Path.cwd())

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title=title, initialdir=start_dir)
        root.destroy()

        if chosen:
            widget.value = chosen

    def _append_generic_log_metadata_path(self, path: str | Path) -> None:
        current = _paths_from_text(self.w_generic_log_metadata_paths.value) or []
        new_path = Path(path)
        existing = {str(p) for p in current}
        if str(new_path) not in existing:
            current.append(new_path)
        self.w_generic_log_metadata_paths.value = _paths_to_text(current)

    def _add_generic_log_metadata_file(self) -> None:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askopenfilename(title="Select generic log metadata JSON", initialdir=str(Path.cwd()))
        root.destroy()

        if chosen:
            self._append_generic_log_metadata_path(chosen)

    def _add_generic_log_metadata_dir(self) -> None:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title="Select generic log metadata directory", initialdir=str(Path.cwd()))
        root.destroy()

        if chosen:
            self._append_generic_log_metadata_path(chosen)


def make_preprocess_runtime_settings_editor(**kwargs: Any) -> PreprocessRuntimeSettingsEditor:
    """Construct a runtime settings editor for notebook use."""
    return PreprocessRuntimeSettingsEditor(**kwargs)
