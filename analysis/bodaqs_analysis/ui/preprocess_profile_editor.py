# bodaqs_analysis/ui/preprocess_profile_editor.py

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import ipywidgets as W

from ..preprocess_filters import normalize_butterworth_smoothing_configs
from ..preprocess_profile import (
    DEFAULT_PREPROCESS_PROFILE_CONFIG,
    DEFAULT_PREPROCESS_PROFILE_DIR,
    default_preprocess_config,
    discover_preprocess_profiles,
    load_preprocess_profile,
    make_preprocess_profile,
    preprocess_config_from_profile,
    preprocess_profile_path,
    save_preprocess_profile,
    validate_preprocess_config,
    validate_preprocess_profile,
)


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2)


def _parse_json_or_literal(text: str, *, expected: type, field_name: str) -> Any:
    raw_text = (text or "").strip()
    if not raw_text:
        return expected()
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError:
        try:
            raw = ast.literal_eval(raw_text)
        except Exception as exc:
            raise ValueError(f"{field_name} must be valid JSON") from exc

    if not isinstance(raw, expected):
        raise ValueError(f"{field_name} must be a {expected.__name__}")
    return raw


def _optional_text(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def _parse_optional_json_object(text: str, *, field_name: str) -> Optional[Dict[str, Any]]:
    raw_text = (text or "").strip()
    if not raw_text:
        return None
    raw = _parse_json_or_literal(raw_text, expected=dict, field_name=field_name)
    return dict(raw) if raw else None


def _fit_defaults(raw: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    defaults = copy.deepcopy(DEFAULT_PREPROCESS_PROFILE_CONFIG["fit_import"])
    if isinstance(raw, Mapping):
        defaults.update(copy.deepcopy(dict(raw)))
    return defaults


def _motion_defaults(raw: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    defaults = copy.deepcopy(DEFAULT_PREPROCESS_PROFILE_CONFIG["motion_derivation"])
    if isinstance(raw, Mapping):
        defaults.update(copy.deepcopy(dict(raw)))
    return defaults


def _set_dropdown_value(widget: W.Dropdown, value: Any, fallback: str) -> None:
    allowed = [item[1] if isinstance(item, tuple) else item for item in widget.options]
    widget.value = str(value) if str(value) in allowed else fallback


def _stretch_layout(**kwargs: Any) -> W.Layout:
    return W.Layout(width="auto", flex="1 1 auto", min_width="0", **kwargs)


def _full_width_layout(**kwargs: Any) -> W.Layout:
    return W.Layout(width="100%", min_width="0", **kwargs)


def _row(children: List[W.Widget]) -> W.HBox:
    return W.HBox(children, layout=W.Layout(width="100%", min_width="0", overflow="hidden"))


class PreprocessProfileEditor:
    """
    Notebook-friendly editor for persisted BODAQS preprocess profiles.

    The editor deliberately covers reusable processing policy only. Runtime
    binding choices such as log metadata, bike profile, log directories, FIT
    directories, and artifact roots should be supplied by the notebook/run layer.
    """

    def __init__(
        self,
        *,
        profile_path: Optional[str | Path] = None,
        profile: Optional[Mapping[str, Any]] = None,
        profiles_dir: str | Path = DEFAULT_PREPROCESS_PROFILE_DIR,
    ) -> None:
        if profile_path is not None and profile is not None:
            raise ValueError("Use only one of profile_path or profile")

        self.profiles_dir = Path(profiles_dir)
        self.current_profile_path: Optional[Path] = Path(profile_path) if profile_path is not None else None

        if profile_path is not None:
            initial_profile = load_preprocess_profile(profile_path)
            self.profiles_dir = Path(profile_path).parent
        elif profile is not None:
            validate_preprocess_profile(profile)
            initial_profile = copy.deepcopy(dict(profile))
        else:
            initial_profile = make_preprocess_profile(
                "new_preprocess_profile",
                config=default_preprocess_config(),
                description="New preprocessing profile",
            )

        self._out = W.Output(layout=W.Layout(border="1px solid #ddd", padding="8px"))

        # Profile identity/storage
        self.w_profile_dir = W.Text(
            value=str(self.profiles_dir),
            description="Directory",
            layout=_stretch_layout(),
        )
        self.b_profile_dir = W.Button(description="Browse...", icon="folder-open", layout=W.Layout(width="120px"))
        self.w_profile_id = W.Combobox(
            options=self._profile_id_options(),
            ensure_option=False,
            description="Profile id",
            placeholder="choose or type a profile id",
            layout=_stretch_layout(),
        )
        self.b_refresh = W.Button(description="Refresh", icon="refresh")
        self.b_load = W.Button(description="Load", icon="folder-open")
        self.w_save_filename = W.Text(
            description="Save file",
            placeholder="profile_filename_v1.json",
            layout=_stretch_layout(),
        )
        self.w_description = W.Textarea(description="Description", layout=_full_width_layout(height="80px"))

        # Core preprocessing config
        self.w_schema_path = W.Text(description="Schema path", layout=_full_width_layout())
        self.w_strict = W.Checkbox(description="Strict mode")

        # FIT import policy. Paths are deliberately not profile fields.
        self.w_fit_enabled = W.Checkbox(description="Enable FIT import")
        self.w_fit_field_allowlist = W.Textarea(description="Fields", layout=_full_width_layout(height="120px"))
        self.w_fit_ambiguity_policy = W.Dropdown(
            options=["require_binding", "largest_overlap", "latest_start"],
            description="Multi-match",
            layout=W.Layout(width="320px"),
        )
        self.w_fit_partial_overlap = W.Dropdown(
            options=["allow", "reject"],
            description="Overlap",
            layout=W.Layout(width="260px"),
        )
        self.w_fit_persist_raw_stream = W.Checkbox(description="Persist raw stream")
        self.w_fit_resample_to_primary = W.Checkbox(description="Resample to primary")
        self.w_fit_resample_method = W.Dropdown(options=["linear"], description="Method", layout=W.Layout(width="220px"))
        self.w_fit_raw_stream_name = W.Text(description="Stream", layout=W.Layout(width="320px"))

        # Signal processing policy
        self.w_zero_enabled = W.Checkbox(description="Enable zeroing")
        self.w_zero_window_s = W.FloatText(description="Window (s)")
        self.w_zero_min_samples = W.IntText(description="Min samples")
        self.w_clip_0_1 = W.Checkbox(description="Clip normalized channels to [0, 1]")
        self.w_motion_enabled = W.Checkbox(description="Enable motion derivation")
        self.w_motion_sources = W.Textarea(description="Sources", layout=_full_width_layout(height="110px"))
        self.w_motion_primary = W.Textarea(description="Primary", layout=_full_width_layout(height="155px"))
        self.w_motion_secondary = W.Textarea(description="Secondary", layout=_full_width_layout(height="100px"))
        self.w_bw_smoothing = W.Textarea(description="Smoothing", layout=_full_width_layout(height="100px"))
        self.w_bw_generate_residuals = W.Checkbox(description="Generate residual series")

        # Activity mask
        self.w_active_enabled = W.Checkbox(description="Enable activity mask")
        self.w_active_disp_selector = W.Textarea(
            description="Disp selector",
            layout=_full_width_layout(height="92px"),
        )
        self.w_active_vel_selector = W.Textarea(
            description="Vel selector",
            layout=_full_width_layout(height="92px"),
        )
        self.w_active_disp_thresh = W.FloatText(description="Disp thresh")
        self.w_active_vel_thresh = W.FloatText(description="Vel thresh")
        self.w_active_window = W.Text(description="Window", layout=W.Layout(width="220px"))
        self.w_active_padding = W.Text(description="Padding", layout=W.Layout(width="220px"))
        self.w_active_min_seg = W.Text(description="Min segment", layout=W.Layout(width="220px"))

        # Actions
        self.b_validate = W.Button(description="Validate", button_style="info", icon="check")
        self.b_save = W.Button(description="Save", button_style="success", icon="save")

        self.b_profile_dir.on_click(lambda _: self._browse_profile_dir())
        self.b_refresh.on_click(lambda _: self.refresh_profile_list())
        self.b_load.on_click(lambda _: self._load_selected_profile())
        self.b_validate.on_click(lambda _: self.validate(print_to_output=True))
        self.b_save.on_click(lambda _: self._save_clicked())

        self.ui = self._build_ui()
        self.set_profile(initial_profile, path=self.current_profile_path)

    def _profile_records(self) -> List[Dict[str, Any]]:
        return discover_preprocess_profiles(Path(self.w_profile_dir.value or self.profiles_dir), include_invalid=False)

    def _profile_id_options(self) -> List[str]:
        return [str(rec["profile_id"]) for rec in self._profile_records() if rec.get("profile_id")]

    def _profile_path_for_id(self, profile_id: str) -> Path:
        for rec in self._profile_records():
            if rec.get("profile_id") == profile_id:
                return Path(str(rec["path"]))
        return preprocess_profile_path(profile_id, directory=Path(self.w_profile_dir.value or self.profiles_dir))

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
        sections = [
            self._section(
                "Profile",
                "Choose which reusable preprocessing profile you are editing, and where it should be saved. The profile ID is the stable logical name; the save filename lets you save a copy or variant.",
                [
                    _row([self.w_profile_dir, self.b_profile_dir]),
                    _row([self.w_profile_id, self.b_refresh, self.b_load]),
                    self.w_description,
                ],
            ),
            self._section(
                "Event Schema",
                "Select the event schema used by the macro pipeline and choose whether ingestion should be strict or tolerant.",
                [
                    self.w_schema_path,
                    self.w_strict,
                ],
            ),
            self._section(
                "FIT Import Policy",
                "Control how optional Garmin FIT data is handled if the notebook provides FIT source paths at run time.",
                [
                    W.HTML(
                        "<p style='margin:0;color:#555'>FIT directory and binding-file paths are run/notebook inputs, not profile fields.</p>"
                    ),
                    self.w_fit_enabled,
                    _row([self.w_fit_partial_overlap, self.w_fit_ambiguity_policy]),
                    _row([self.w_fit_persist_raw_stream, self.w_fit_resample_to_primary]),
                    _row([self.w_fit_resample_method, self.w_fit_raw_stream_name]),
                    W.HTML("<b>FIT field allowlist</b> (JSON list)"),
                    self.w_fit_field_allowlist,
                ],
            ),
            self._section(
                "Zeroing, Scaling & Smoothing",
                "Set preprocessing operations applied to logger signals before event detection and metric extraction.",
                [
                    self.w_zero_enabled,
                    _row([self.w_zero_window_s, self.w_zero_min_samples]),
                    self.w_clip_0_1,
                    W.HTML("<b>Motion derivation</b>"),
                    W.HTML(
                        "<p style='margin:0;color:#555'>Generate primary/secondary filtered displacement, "
                        "velocity, and acceleration channels from selected displacement sources.</p>"
                    ),
                    self.w_motion_enabled,
                    W.HTML("<b>Motion sources</b> (JSON list of source selectors)"),
                    self.w_motion_sources,
                    W.HTML("<b>Primary motion profile</b> (JSON object)"),
                    self.w_motion_primary,
                    W.HTML("<b>Secondary motion profiles</b> (JSON list)"),
                    self.w_motion_secondary,
                    W.HTML("<b>Butterworth smoothing</b> (JSON list of dicts)"),
                    self.w_bw_smoothing,
                    self.w_bw_generate_residuals,
                ],
            ),
            self._section(
                "Activity Mask",
                "Choose the semantic displacement and velocity signals used to decide which parts of a session are active enough to analyse.",
                [
                    self.w_active_enabled,
                    self.w_active_disp_selector,
                    self.w_active_vel_selector,
                    _row([self.w_active_disp_thresh, self.w_active_vel_thresh]),
                    _row([self.w_active_window, self.w_active_padding, self.w_active_min_seg]),
                ],
            ),
            self._section(
                "Actions",
                "Validate the current settings or write the profile JSON to the selected directory and filename.",
                [
                    _row([self.w_save_filename, self.b_validate, self.b_save]),
                    self._out,
                ],
            ),
        ]
        return W.VBox(sections, layout=W.Layout(width="100%", min_width="0", overflow="hidden"))

    def refresh_profile_list(self) -> None:
        current = self.w_profile_id.value
        self.profiles_dir = Path(self.w_profile_dir.value or self.profiles_dir)
        self.w_profile_id.options = self._profile_id_options()
        self.w_profile_id.value = current

    def set_profile(self, profile: Mapping[str, Any], *, path: Optional[str | Path] = None) -> None:
        validate_preprocess_profile(profile, path=path)
        cfg = preprocess_config_from_profile(profile)
        fit = _fit_defaults(cfg.get("fit_import"))
        motion = _motion_defaults(cfg.get("motion_derivation"))

        self.current_profile_path = Path(path) if path is not None else self.current_profile_path
        if path is not None:
            self.w_profile_dir.value = str(Path(path).parent)
            self.w_save_filename.value = Path(path).name
            self.profiles_dir = Path(path).parent
            self.w_profile_id.options = self._profile_id_options()
        elif not _optional_text(self.w_save_filename.value):
            self.w_save_filename.value = preprocess_profile_path(
                str(profile.get("profile_id") or "new_preprocess_profile"),
                directory="",
            ).name

        self.w_profile_id.value = str(profile.get("profile_id") or "")
        self.w_description.value = str(profile.get("description") or "")

        self.w_schema_path.value = str(cfg.get("schema_path") or "")
        self.w_strict.value = bool(cfg.get("strict", False))

        self.w_fit_enabled.value = bool(fit.get("enabled", False))
        self.w_fit_field_allowlist.value = _json_text(fit.get("field_allowlist") or [])
        _set_dropdown_value(self.w_fit_ambiguity_policy, fit.get("ambiguity_policy") or "require_binding", "require_binding")
        _set_dropdown_value(self.w_fit_partial_overlap, fit.get("partial_overlap") or "allow", "allow")
        self.w_fit_persist_raw_stream.value = bool(fit.get("persist_raw_stream", True))
        self.w_fit_resample_to_primary.value = bool(fit.get("resample_to_primary", True))
        _set_dropdown_value(self.w_fit_resample_method, fit.get("resample_method") or "linear", "linear")
        self.w_fit_raw_stream_name.value = str(fit.get("raw_stream_name") or "gps_fit")

        self.w_zero_enabled.value = bool(cfg.get("zeroing_enabled", False))
        self.w_zero_window_s.value = float(cfg.get("zero_window_s", 0.4))
        self.w_zero_min_samples.value = int(cfg.get("zero_min_samples", 10))
        self.w_clip_0_1.value = bool(cfg.get("clip_0_1", False))
        self.w_motion_enabled.value = bool(motion.get("enabled", False))
        self.w_motion_sources.value = _json_text(motion.get("sources") or [])
        self.w_motion_primary.value = _json_text(motion.get("primary") or {})
        self.w_motion_secondary.value = _json_text(motion.get("secondary") or [])
        self.w_bw_smoothing.value = _json_text(cfg.get("butterworth_smoothing") or [])
        self.w_bw_generate_residuals.value = bool(cfg.get("butterworth_generate_residuals", False))

        self.w_active_enabled.value = cfg.get("active_signal_disp_selector") is not None
        self.w_active_disp_selector.value = _json_text(cfg.get("active_signal_disp_selector") or {})
        self.w_active_vel_selector.value = _json_text(cfg.get("active_signal_vel_selector") or {})
        self.w_active_disp_thresh.value = float(cfg.get("active_disp_thresh", 20.0))
        self.w_active_vel_thresh.value = float(cfg.get("active_vel_thresh", 50.0))
        self.w_active_window.value = str(cfg.get("active_window") or "500ms")
        self.w_active_padding.value = str(cfg.get("active_padding") or "1s")
        self.w_active_min_seg.value = str(cfg.get("active_min_seg") or "3s")

    def load_profile(self, path: str | Path) -> Dict[str, Any]:
        profile = load_preprocess_profile(path)
        self.set_profile(profile, path=path)
        return profile

    def get_config(self) -> Dict[str, Any]:
        fields = _parse_json_or_literal(
            self.w_fit_field_allowlist.value,
            expected=list,
            field_name="fit_import.field_allowlist",
        )
        bw_raw = _parse_json_or_literal(
            self.w_bw_smoothing.value,
            expected=list,
            field_name="butterworth_smoothing",
        )
        bw_normalized = normalize_butterworth_smoothing_configs(bw_raw)
        motion_sources = _parse_json_or_literal(
            self.w_motion_sources.value,
            expected=list,
            field_name="motion_derivation.sources",
        )
        motion_primary = _parse_json_or_literal(
            self.w_motion_primary.value,
            expected=dict,
            field_name="motion_derivation.primary",
        )
        motion_secondary = _parse_json_or_literal(
            self.w_motion_secondary.value,
            expected=list,
            field_name="motion_derivation.secondary",
        )
        motion_derivation = {
            "enabled": bool(self.w_motion_enabled.value),
            "sources": motion_sources,
            "primary": motion_primary,
            "secondary": motion_secondary,
        }

        config: Dict[str, Any] = {
            "schema_path": str(self.w_schema_path.value or "").strip(),
            "strict": bool(self.w_strict.value),
            "fit_import": {
                "enabled": bool(self.w_fit_enabled.value),
                "field_allowlist": [str(x).strip() for x in fields if str(x).strip()],
                "ambiguity_policy": str(self.w_fit_ambiguity_policy.value),
                "partial_overlap": str(self.w_fit_partial_overlap.value),
                "persist_raw_stream": bool(self.w_fit_persist_raw_stream.value),
                "resample_to_primary": bool(self.w_fit_resample_to_primary.value),
                "resample_method": str(self.w_fit_resample_method.value),
                "raw_stream_name": str(self.w_fit_raw_stream_name.value or "").strip(),
            },
            "zeroing_enabled": bool(self.w_zero_enabled.value),
            "zero_window_s": float(self.w_zero_window_s.value),
            "zero_min_samples": int(self.w_zero_min_samples.value),
            "clip_0_1": bool(self.w_clip_0_1.value),
            "motion_derivation": motion_derivation,
            "butterworth_smoothing": [
                {"cutoff_hz": float(cfg.cutoff_hz), "order": int(cfg.order)}
                for cfg in bw_normalized
            ],
            "butterworth_generate_residuals": bool(self.w_bw_generate_residuals.value),
            "active_signal_disp_selector": _parse_optional_json_object(
                self.w_active_disp_selector.value,
                field_name="active_signal_disp_selector",
            )
            if self.w_active_enabled.value
            else None,
            "active_signal_vel_selector": _parse_optional_json_object(
                self.w_active_vel_selector.value,
                field_name="active_signal_vel_selector",
            )
            if self.w_active_enabled.value
            else None,
            "active_disp_thresh": float(self.w_active_disp_thresh.value),
            "active_vel_thresh": float(self.w_active_vel_thresh.value),
            "active_window": str(self.w_active_window.value or "").strip(),
            "active_padding": str(self.w_active_padding.value or "").strip(),
            "active_min_seg": str(self.w_active_min_seg.value or "").strip(),
        }

        validate_preprocess_config(config)
        return config

    def get_profile(self) -> Dict[str, Any]:
        return make_preprocess_profile(
            self.w_profile_id.value,
            config=self.get_config(),
            description=_optional_text(self.w_description.value),
        )

    def validate(self, *, print_to_output: bool = False) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        try:
            profile = self.get_profile()
            validate_preprocess_profile(profile)
        except Exception as exc:
            errors.append(str(exc))

        if self.w_fit_enabled.value:
            warnings.append("FIT import is enabled; remember to provide FIT_DIR and FIT_BINDINGS_PATH at run time.")

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

    def save_profile(self, path: Optional[str | Path] = None, *, overwrite: bool = True) -> Path:
        profile = self.get_profile()
        out_path = Path(path) if path is not None else self._save_path_for_profile(profile["profile_id"])
        saved = save_preprocess_profile(profile, out_path, overwrite=overwrite)
        self.current_profile_path = saved
        self.w_profile_dir.value = str(saved.parent)
        self.w_save_filename.value = saved.name
        self.refresh_profile_list()
        return saved

    def _save_path_for_profile(self, profile_id: str) -> Path:
        filename = _optional_text(self.w_save_filename.value)
        if filename is None:
            filename = preprocess_profile_path(profile_id, directory="").name
            self.w_save_filename.value = filename

        path = Path(filename)
        if path.is_absolute():
            return path
        return Path(self.w_profile_dir.value or self.profiles_dir) / path

    def _load_selected_profile(self) -> None:
        profile_id = _optional_text(self.w_profile_id.value)
        if not profile_id:
            return
        with self._out:
            self._out.clear_output()
            try:
                path = self._profile_path_for_id(profile_id)
                self.load_profile(path)
                print(f"Loaded profile: {path}")
            except Exception as exc:
                print(f"Could not load profile: {exc}")

    def _save_clicked(self) -> None:
        with self._out:
            self._out.clear_output()
            try:
                saved = self.save_profile()
                print(f"Saved profile: {saved}")
            except Exception as exc:
                print(f"Could not save profile: {exc}")

    def _browse_profile_dir(self) -> None:
        import tkinter as tk
        from tkinter import filedialog

        current = _optional_text(self.w_profile_dir.value)
        start_dir = current if current and Path(current).exists() else str(Path.cwd())

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title="Select preprocess profile directory", initialdir=start_dir)
        root.destroy()

        if chosen:
            self.w_profile_dir.value = chosen
            self.refresh_profile_list()


def make_preprocess_profile_editor(
    *,
    profile_path: Optional[str | Path] = None,
    profile: Optional[Mapping[str, Any]] = None,
    profiles_dir: str | Path = DEFAULT_PREPROCESS_PROFILE_DIR,
) -> PreprocessProfileEditor:
    """Construct a ``PreprocessProfileEditor`` for notebook use."""
    return PreprocessProfileEditor(profile_path=profile_path, profile=profile, profiles_dir=profiles_dir)
