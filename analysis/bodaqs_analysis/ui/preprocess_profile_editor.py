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


def _fit_defaults(raw: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    defaults = copy.deepcopy(DEFAULT_PREPROCESS_PROFILE_CONFIG["fit_import"])
    if isinstance(raw, Mapping):
        defaults.update(copy.deepcopy(dict(raw)))
    return defaults


def _set_dropdown_value(widget: W.Dropdown, value: Any, fallback: str) -> None:
    allowed = [item[1] if isinstance(item, tuple) else item for item in widget.options]
    widget.value = str(value) if str(value) in allowed else fallback


class PreprocessProfileEditor:
    """
    Notebook-friendly editor for persisted BODAQS preprocess profiles.

    The editor is profile-first: it loads, validates, and saves full
    ``bodaqs.preprocess_profile`` JSON documents, while still exposing the
    nested ``config`` payload used by ``run_macro(..., preprocess_config=...)``.
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

        # Profile metadata
        self.w_profile_path = W.Text(
            value=str(self.current_profile_path or preprocess_profile_path("new_preprocess_profile", directory=self.profiles_dir)),
            description="Profile path",
            layout=W.Layout(width="100%"),
        )
        self.w_profile_id = W.Text(description="Profile id", layout=W.Layout(width="420px"))
        self.w_description = W.Textarea(description="Description", layout=W.Layout(width="100%", height="80px"))

        # Discovery
        self.w_discovered_profiles = W.Dropdown(
            options=self._profile_options(),
            description="Existing",
            layout=W.Layout(width="100%"),
        )
        self.b_refresh = W.Button(description="Refresh", icon="refresh")
        self.b_load = W.Button(description="Load", icon="folder-open")

        # Core config
        self.w_schema_path = W.Text(description="Schema path", layout=W.Layout(width="100%"))
        self.w_strict = W.Checkbox(description="Strict mode")
        self.w_generic_log_metadata_paths = W.Textarea(
            description="Log metadata",
            layout=W.Layout(width="100%", height="90px"),
        )
        self.w_bike_profile_path = W.Text(description="Bike profile", layout=W.Layout(width="100%"))
        self.w_bike_profile_id = W.Text(description="Bike id", layout=W.Layout(width="420px"))

        # Legacy fallback
        self.w_use_legacy_ranges = W.Checkbox(description="Use legacy normalize_ranges")
        self.w_legacy_ranges = W.Textarea(description="Ranges", layout=W.Layout(width="100%", height="100px"))

        # FIT import
        self.w_fit_enabled = W.Checkbox(description="Enable FIT import")
        self.w_fit_dir = W.Text(description="FIT dir", layout=W.Layout(width="100%"))
        self.w_fit_bindings_path = W.Text(description="Bindings", layout=W.Layout(width="100%"))
        self.w_fit_field_allowlist = W.Textarea(description="Fields", layout=W.Layout(width="100%", height="120px"))
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

        # Preprocessing policy
        self.w_zero_enabled = W.Checkbox(description="Enable zeroing")
        self.w_zero_window_s = W.FloatText(description="Window (s)")
        self.w_zero_min_samples = W.IntText(description="Min samples")
        self.w_clip_0_1 = W.Checkbox(description="Clip normalized channels to [0, 1]")
        self.w_bw_smoothing = W.Textarea(description="Smoothing", layout=W.Layout(width="100%", height="100px"))
        self.w_bw_generate_residuals = W.Checkbox(description="Generate residual series")

        # Activity mask
        self.w_active_enabled = W.Checkbox(description="Enable activity mask")
        self.w_active_disp_col = W.Text(description="Disp signal", layout=W.Layout(width="100%"))
        self.w_active_vel_col = W.Text(description="Vel signal", layout=W.Layout(width="100%"))
        self.w_active_disp_thresh = W.FloatText(description="Disp thresh")
        self.w_active_vel_thresh = W.FloatText(description="Vel thresh")
        self.w_active_window = W.Text(description="Window", layout=W.Layout(width="220px"))
        self.w_active_padding = W.Text(description="Padding", layout=W.Layout(width="220px"))
        self.w_active_min_seg = W.Text(description="Min segment", layout=W.Layout(width="220px"))

        # Notebook convenience
        self.w_prompt_desc = W.Checkbox(description="Prompt for descriptions")

        # Actions
        self.b_validate = W.Button(description="Validate", button_style="info", icon="check")
        self.b_save = W.Button(description="Save", button_style="success", icon="save")
        self.b_save_as_conventional = W.Button(description="Use conventional path", icon="magic")

        self.b_refresh.on_click(lambda _: self.refresh_profile_list())
        self.b_load.on_click(lambda _: self._load_selected_profile())
        self.b_validate.on_click(lambda _: self.validate(print_to_output=True))
        self.b_save.on_click(lambda _: self._save_clicked())
        self.b_save_as_conventional.on_click(lambda _: self._set_conventional_path())

        self.ui = self._build_ui()
        self.set_profile(initial_profile, path=self.current_profile_path)

    def _profile_options(self) -> List[Tuple[str, str]]:
        records = discover_preprocess_profiles(self.profiles_dir, include_invalid=True)
        options: List[Tuple[str, str]] = [("(choose a profile)", "")]
        for rec in records:
            label = str(rec.get("profile_id") or Path(str(rec.get("path"))).name)
            if not rec.get("valid"):
                label = f"{label} (invalid)"
            options.append((label, str(rec.get("path") or "")))
        return options

    def _build_ui(self) -> W.VBox:
        sec_profile = W.VBox(
            [
                W.HBox([self.w_discovered_profiles, self.b_refresh, self.b_load]),
                self.w_profile_path,
                W.HBox([self.w_profile_id, self.b_save_as_conventional]),
                self.w_description,
            ]
        )
        sec_core = W.VBox(
            [
                self.w_schema_path,
                self.w_strict,
                W.HTML("<b>Generic log metadata paths</b> (JSON list)"),
                self.w_generic_log_metadata_paths,
                self.w_bike_profile_path,
                self.w_bike_profile_id,
            ]
        )
        sec_legacy = W.VBox(
            [
                self.w_use_legacy_ranges,
                W.HTML("<b>Legacy normalize_ranges</b> (JSON object; only used when enabled)"),
                self.w_legacy_ranges,
            ]
        )
        sec_fit = W.VBox(
            [
                self.w_fit_enabled,
                self.w_fit_dir,
                self.w_fit_bindings_path,
                W.HBox([self.w_fit_partial_overlap, self.w_fit_ambiguity_policy]),
                W.HBox([self.w_fit_persist_raw_stream, self.w_fit_resample_to_primary]),
                W.HBox([self.w_fit_resample_method, self.w_fit_raw_stream_name]),
                W.HTML("<b>FIT field allowlist</b> (JSON list)"),
                self.w_fit_field_allowlist,
            ]
        )
        sec_preprocess = W.VBox(
            [
                self.w_zero_enabled,
                W.HBox([self.w_zero_window_s, self.w_zero_min_samples]),
                self.w_clip_0_1,
                W.HTML("<b>Butterworth smoothing</b> (JSON list of dicts)"),
                self.w_bw_smoothing,
                self.w_bw_generate_residuals,
            ]
        )
        sec_active = W.VBox(
            [
                self.w_active_enabled,
                self.w_active_disp_col,
                self.w_active_vel_col,
                W.HBox([self.w_active_disp_thresh, self.w_active_vel_thresh]),
                W.HBox([self.w_active_window, self.w_active_padding, self.w_active_min_seg]),
            ]
        )
        sec_actions = W.VBox([self.w_prompt_desc, W.HBox([self.b_validate, self.b_save]), self._out])

        acc = W.Accordion(children=[sec_profile, sec_core, sec_legacy, sec_fit, sec_preprocess, sec_active, sec_actions])
        acc.set_title(0, "Profile")
        acc.set_title(1, "Log Metadata & Bike")
        acc.set_title(2, "Legacy Ranges")
        acc.set_title(3, "FIT Import")
        acc.set_title(4, "Zeroing, Scaling & Smoothing")
        acc.set_title(5, "Activity Mask")
        acc.set_title(6, "Actions")
        acc.selected_index = 0
        return W.VBox([acc])

    def refresh_profile_list(self) -> None:
        current = self.w_discovered_profiles.value
        self.w_discovered_profiles.options = self._profile_options()
        values = [v for _, v in self.w_discovered_profiles.options]
        self.w_discovered_profiles.value = current if current in values else ""

    def set_profile(self, profile: Mapping[str, Any], *, path: Optional[str | Path] = None) -> None:
        validate_preprocess_profile(profile, path=path)
        cfg = preprocess_config_from_profile(profile)
        fit = _fit_defaults(cfg.get("fit_import"))

        self.current_profile_path = Path(path) if path is not None else self.current_profile_path
        if path is not None:
            self.w_profile_path.value = str(path)
        self.w_profile_id.value = str(profile.get("profile_id") or "")
        self.w_description.value = str(profile.get("description") or "")

        self.w_schema_path.value = str(cfg.get("schema_path") or "")
        self.w_strict.value = bool(cfg.get("strict", False))
        self.w_generic_log_metadata_paths.value = _json_text(cfg.get("generic_log_metadata_paths") or [])
        self.w_bike_profile_path.value = str(cfg.get("bike_profile_path") or "")
        self.w_bike_profile_id.value = str(cfg.get("bike_profile_id") or "")

        legacy_ranges = cfg.get("normalize_ranges")
        self.w_use_legacy_ranges.value = isinstance(legacy_ranges, Mapping)
        self.w_legacy_ranges.value = _json_text(legacy_ranges or {})

        self.w_fit_enabled.value = bool(fit.get("enabled", False))
        self.w_fit_dir.value = str(fit.get("fit_dir") or "")
        self.w_fit_bindings_path.value = str(fit.get("bindings_path") or "")
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
        self.w_bw_smoothing.value = _json_text(cfg.get("butterworth_smoothing") or [])
        self.w_bw_generate_residuals.value = bool(cfg.get("butterworth_generate_residuals", False))

        self.w_active_enabled.value = cfg.get("active_signal_disp_col") is not None
        self.w_active_disp_col.value = str(cfg.get("active_signal_disp_col") or "")
        self.w_active_vel_col.value = str(cfg.get("active_signal_vel_col") or "")
        self.w_active_disp_thresh.value = float(cfg.get("active_disp_thresh", 20.0))
        self.w_active_vel_thresh.value = float(cfg.get("active_vel_thresh", 50.0))
        self.w_active_window.value = str(cfg.get("active_window") or "500ms")
        self.w_active_padding.value = str(cfg.get("active_padding") or "1s")
        self.w_active_min_seg.value = str(cfg.get("active_min_seg") or "3s")

        self.w_prompt_desc.value = bool(cfg.get("prompt_for_descriptions", True))

    def load_profile(self, path: str | Path) -> Dict[str, Any]:
        profile = load_preprocess_profile(path)
        self.set_profile(profile, path=path)
        return profile

    def get_config(self) -> Dict[str, Any]:
        generic_paths = _parse_json_or_literal(
            self.w_generic_log_metadata_paths.value,
            expected=list,
            field_name="generic_log_metadata_paths",
        )
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

        config: Dict[str, Any] = {
            "schema_path": str(self.w_schema_path.value or "").strip(),
            "strict": bool(self.w_strict.value),
            "fit_import": {
                "enabled": bool(self.w_fit_enabled.value),
                "fit_dir": str(self.w_fit_dir.value or "").strip(),
                "field_allowlist": [str(x).strip() for x in fields if str(x).strip()],
                "ambiguity_policy": str(self.w_fit_ambiguity_policy.value),
                "partial_overlap": str(self.w_fit_partial_overlap.value),
                "persist_raw_stream": bool(self.w_fit_persist_raw_stream.value),
                "resample_to_primary": bool(self.w_fit_resample_to_primary.value),
                "resample_method": str(self.w_fit_resample_method.value),
                "raw_stream_name": str(self.w_fit_raw_stream_name.value or "").strip(),
                "bindings_path": _optional_text(self.w_fit_bindings_path.value),
            },
            "generic_log_metadata_paths": [str(x).strip() for x in generic_paths if str(x).strip()],
            "bike_profile_path": _optional_text(self.w_bike_profile_path.value),
            "bike_profile_id": _optional_text(self.w_bike_profile_id.value),
            "zeroing_enabled": bool(self.w_zero_enabled.value),
            "zero_window_s": float(self.w_zero_window_s.value),
            "zero_min_samples": int(self.w_zero_min_samples.value),
            "clip_0_1": bool(self.w_clip_0_1.value),
            "butterworth_smoothing": [
                {"cutoff_hz": float(cfg.cutoff_hz), "order": int(cfg.order)}
                for cfg in bw_normalized
            ],
            "butterworth_generate_residuals": bool(self.w_bw_generate_residuals.value),
            "active_signal_disp_col": _optional_text(self.w_active_disp_col.value) if self.w_active_enabled.value else None,
            "active_signal_vel_col": _optional_text(self.w_active_vel_col.value) if self.w_active_enabled.value else None,
            "active_disp_thresh": float(self.w_active_disp_thresh.value),
            "active_vel_thresh": float(self.w_active_vel_thresh.value),
            "active_window": str(self.w_active_window.value or "").strip(),
            "active_padding": str(self.w_active_padding.value or "").strip(),
            "active_min_seg": str(self.w_active_min_seg.value or "").strip(),
            "prompt_for_descriptions": bool(self.w_prompt_desc.value),
        }

        if self.w_use_legacy_ranges.value:
            ranges = _parse_json_or_literal(
                self.w_legacy_ranges.value,
                expected=dict,
                field_name="normalize_ranges",
            )
            config["normalize_ranges"] = {str(k): float(v) for k, v in ranges.items()}

        # Drop a null bike profile if legacy ranges are being used. Otherwise
        # validation will correctly require a bike profile path.
        if config["bike_profile_path"] is None and self.w_use_legacy_ranges.value:
            config.pop("bike_profile_path", None)

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

        if self.w_fit_enabled.value and not _optional_text(self.w_fit_dir.value):
            errors.append("FIT import is enabled but FIT dir is blank.")
        if not self.w_use_legacy_ranges.value and not _optional_text(self.w_bike_profile_path.value):
            errors.append("Bike profile path is blank and legacy ranges are disabled.")
        if self.w_use_legacy_ranges.value:
            warnings.append("Legacy normalize_ranges are enabled; prefer a bike profile for new workflows.")

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
        out_path = Path(path or self.w_profile_path.value)
        saved = save_preprocess_profile(profile, out_path, overwrite=overwrite)
        self.current_profile_path = saved
        self.w_profile_path.value = str(saved)
        self.refresh_profile_list()
        return saved

    def _load_selected_profile(self) -> None:
        selected = _optional_text(self.w_discovered_profiles.value)
        if not selected:
            return
        with self._out:
            self._out.clear_output()
            try:
                self.load_profile(selected)
                print(f"Loaded profile: {selected}")
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

    def _set_conventional_path(self) -> None:
        profile_id = _optional_text(self.w_profile_id.value)
        if not profile_id:
            return
        self.w_profile_path.value = str(preprocess_profile_path(profile_id, directory=self.profiles_dir))


def make_preprocess_profile_editor(
    *,
    profile_path: Optional[str | Path] = None,
    profile: Optional[Mapping[str, Any]] = None,
    profiles_dir: str | Path = DEFAULT_PREPROCESS_PROFILE_DIR,
) -> PreprocessProfileEditor:
    """Construct a ``PreprocessProfileEditor`` for notebook use."""
    return PreprocessProfileEditor(profile_path=profile_path, profile=profile, profiles_dir=profiles_dir)
