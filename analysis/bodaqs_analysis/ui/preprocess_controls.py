# bodaqs_analysis/ui/preprocess_controls.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List
import ast
import json

import ipywidgets as W

from ..va import name_vel
from ..preprocess_filters import normalize_butterworth_smoothing_configs

_FIT_IMPORT_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "fit_dir": "Garmin/FIT",
    "field_allowlist": [
        "position_lat",
        "position_long",
        "altitude",
        "enhanced_altitude",
        "speed",
        "enhanced_speed",
        "distance",
        "grade",
        "heading",
    ],
    "ambiguity_policy": "require_binding",
    "partial_overlap": "allow",
    "persist_raw_stream": True,
    "resample_to_primary": True,
    "resample_method": "linear",
    "raw_stream_name": "gps_fit",
    "bindings_path": "analysis/config/fit_bindings_v1.json",
}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


@dataclass
class PreprocessDefaults:
    schema_path: str = r"event schema\event_schema.yaml"
    ingestion_mode: str = "tolerant"  # "tolerant" or "strict"
    fit_import: Optional[Dict[str, Any]] = None

    zeroing_enabled: bool = False
    zero_window_s: float = 0.4
    zero_min_samples: int = 10

    clip_0_1: bool = False
    butterworth_smoothing: Optional[List[Dict[str, Any]]] = None
    butterworth_generate_residuals: bool = False

    active_enabled: bool = True
    active_disp_thresh: float = 20.0
    active_vel_thresh: float = 50.0
    active_window: str = "500ms"
    active_padding: str = "1s"
    active_min_seg: str = "3s"

    prompt_for_descriptions: bool = True


class PreprocessControls:
    """
    Builds an Accordion UI for Step 2 parameters and produces a validated config dict
    suitable for calling run_macro(...).

    - disp_cols_all: list of canonical displacement column names (quantity == "disp")
    - sessions_by_id: dict of sessions from Step 1 (used for session selector only)
    """

    def __init__(
        self,
        disp_cols_all: List[str],
        sessions_by_id: Dict[str, Any],
        *,
        defaults: Optional[PreprocessDefaults] = None,
        default_ranges: Optional[Dict[str, float]] = None,
    ) -> None:
        self.disp_cols_all = list(disp_cols_all)
        self.sessions_by_id = dict(sessions_by_id)
        self.defaults = defaults or PreprocessDefaults()
        self.default_ranges = default_ranges or {}
        self._fit_defaults = self._normalize_fit_defaults(self.defaults.fit_import)

        # ---- Widgets ----
        self._out = W.Output(layout=W.Layout(border="1px solid #ddd", padding="8px"))

        # Schema & mode
        self.w_schema_path = W.Text(
            value=self.defaults.schema_path,
            description="Schema path",
            layout=W.Layout(width="100%"),
        )
        self.w_mode = W.Dropdown(
            options=["tolerant", "strict"],
            value=self.defaults.ingestion_mode if self.defaults.ingestion_mode in ("tolerant", "strict") else "tolerant",
            description="Mode",
            layout=W.Layout(width="300px"),
        )
        self.w_preview_session = W.Dropdown(
            options=sorted(self.sessions_by_id.keys()),
            description="Preview session",
            layout=W.Layout(width="400px"),
        )

        # FIT import
        self.w_fit_enabled = W.Checkbox(
            value=bool(self._fit_defaults["enabled"]),
            description="Enable FIT import",
        )
        self.w_fit_dir = W.Text(
            value=str(self._fit_defaults["fit_dir"]),
            description="FIT dir",
            layout=W.Layout(width="100%"),
        )
        self.b_fit_dir_browse = W.Button(
            description="Browse...",
            icon="folder-open",
            button_style="",
            layout=W.Layout(width="110px"),
        )
        self.w_fit_bindings_path = W.Text(
            value=str(self._fit_defaults["bindings_path"]),
            description="Bindings",
            layout=W.Layout(width="100%"),
        )
        self.w_fit_field_allowlist = W.Textarea(
            value=json.dumps(list(self._fit_defaults["field_allowlist"]), indent=2),
            description="Fields",
            layout=W.Layout(width="100%", height="130px"),
        )
        self.w_fit_partial_overlap = W.Dropdown(
            options=["allow", "reject"],
            value=str(self._fit_defaults["partial_overlap"]),
            description="Overlap",
            layout=W.Layout(width="260px"),
        )
        self.w_fit_ambiguity_policy = W.Dropdown(
            options=["require_binding", "largest_overlap", "latest_start"],
            value=str(self._fit_defaults["ambiguity_policy"]),
            description="Multi-match",
            layout=W.Layout(width="320px"),
        )
        self.w_fit_persist_raw_stream = W.Checkbox(
            value=bool(self._fit_defaults["persist_raw_stream"]),
            description="Persist raw stream",
        )
        self.w_fit_resample_to_primary = W.Checkbox(
            value=bool(self._fit_defaults["resample_to_primary"]),
            description="Resample to primary",
        )
        self.w_fit_resample_method = W.Dropdown(
            options=["linear"],
            value=str(self._fit_defaults["resample_method"]),
            description="Method",
            layout=W.Layout(width="220px"),
        )
        self.w_fit_raw_stream_name = W.Text(
            value=str(self._fit_defaults["raw_stream_name"]),
            description="Stream name",
            layout=W.Layout(width="320px"),
        )

        # Displacement selection
        self.w_disp_select = W.SelectMultiple(
            options=self.disp_cols_all,
            value=tuple(self.disp_cols_all),
            description="Displacements",
            layout=W.Layout(width="100%", height="160px"),
        )

        # Normalisation ranges grid (built dynamically)
        self._ranges_grid = None
        self._range_widgets: Dict[str, W.FloatText] = {}

        # Zeroing
        self.w_zero_enabled = W.Checkbox(value=self.defaults.zeroing_enabled, description="Enable zeroing")
        self.w_zero_window_s = W.FloatText(value=_safe_float(self.defaults.zero_window_s, 0.4), description="Window (s)")
        self.w_zero_min_samples = W.IntText(value=_safe_int(self.defaults.zero_min_samples, 10), description="Min samples")

        # Activity mask
        self.w_active_enabled = W.Checkbox(value=self.defaults.active_enabled, description="Enable activity mask")
        self.w_active_disp_col = W.Dropdown(
            options=self.disp_cols_all,
            value=self.disp_cols_all[0] if self.disp_cols_all else None,
            description="Disp signal",
            layout=W.Layout(width="100%"),
        )
        self.w_active_vel_label = W.Label(value=self._derived_vel_label())

        self.w_active_disp_thresh = W.FloatText(value=_safe_float(self.defaults.active_disp_thresh, 20.0), description="Disp thresh (mm)")
        self.w_active_vel_thresh = W.FloatText(value=_safe_float(self.defaults.active_vel_thresh, 50.0), description="Vel thresh (mm/s)")
        self.w_active_window = W.Text(value=self.defaults.active_window, description="Window", placeholder="e.g. 500ms, 1s")
        self.w_active_padding = W.Text(value=self.defaults.active_padding, description="Padding", placeholder="e.g. 1s")
        self.w_active_min_seg = W.Text(value=self.defaults.active_min_seg, description="Min segment", placeholder="e.g. 3s")

        # Clipping & prompting
        self.w_clip_0_1 = W.Checkbox(value=self.defaults.clip_0_1, description="Clip to [0, 1]")
        self.w_bw_smoothing = W.Textarea(
            value=json.dumps(self.defaults.butterworth_smoothing or [], indent=2),
            description="Configs",
            placeholder='e.g. [{"cutoff_hz": 3.0, "order": 4}]',
            layout=W.Layout(width="100%", height="120px"),
        )
        self.w_bw_generate_residuals = W.Checkbox(
            value=bool(self.defaults.butterworth_generate_residuals),
            description="Generate residual series",
        )
        self.w_prompt_desc = W.Checkbox(value=self.defaults.prompt_for_descriptions, description="Prompt for descriptions")

        # Actions
        self.b_validate = W.Button(description="Validate", button_style="info", icon="check")
        self.b_build = W.Button(description="Build config", button_style="success", icon="play")

        # Wire handlers
        self.w_disp_select.observe(self._on_disp_selection_changed, names="value")
        self.w_active_disp_col.observe(self._on_active_disp_changed, names="value")
        self.b_fit_dir_browse.on_click(lambda _: self._on_fit_dir_browse())
        self.b_validate.on_click(lambda _: self.validate(print_to_output=True))
        self.b_build.on_click(lambda _: self._print_config())

        # Build UI
        self.ui = self._build_accordion()

        # Initial grid build
        self._rebuild_ranges_grid()

    # ---------- UI building ----------
    def _build_accordion(self) -> W.Accordion:
        sec_schema = W.VBox([
            self.w_schema_path,
            W.HBox([self.w_mode, self.w_preview_session]),
        ])

        sec_fit = W.VBox([
            self.w_fit_enabled,
            W.HBox([self.w_fit_dir, self.b_fit_dir_browse]),
            self.w_fit_bindings_path,
            W.HBox([self.w_fit_partial_overlap, self.w_fit_ambiguity_policy]),
            W.HBox([self.w_fit_persist_raw_stream, self.w_fit_resample_to_primary]),
            W.HBox([self.w_fit_resample_method, self.w_fit_raw_stream_name]),
            W.HTML("<b>FIT field allowlist</b> (JSON/Python list of Garmin record fields)"),
            self.w_fit_field_allowlist,
        ])

        sec_norm = W.VBox([
            W.HTML("<b>Displacement signals</b> (select which to normalise / derive VA)"),
            self.w_disp_select,
            W.HTML("<b>Normalisation ranges</b> (mm)"),
            self._placeholder_grid_box(),
        ])

        sec_zero = W.VBox([
            self.w_zero_enabled,
            W.HBox([self.w_zero_window_s, self.w_zero_min_samples]),
        ])

        sec_active = W.VBox([
            self.w_active_enabled,
            self.w_active_disp_col,
            W.HBox([W.HTML("<b>Derived vel col:</b>"), self.w_active_vel_label]),
            W.HBox([self.w_active_disp_thresh, self.w_active_vel_thresh]),
            self.w_active_window,
            self.w_active_padding,
            self.w_active_min_seg,
        ])

        sec_misc = W.VBox([
            self.w_clip_0_1,
            W.HTML("<b>Offline Butterworth smoothing</b> (JSON/Python list of dicts)"),
            self.w_bw_smoothing,
            self.w_bw_generate_residuals,
            self.w_prompt_desc,
        ])

        sec_actions = W.VBox([
            W.HBox([self.b_validate, self.b_build]),
            self._out,
        ])

        acc = W.Accordion(children=[sec_schema, sec_fit, sec_norm, sec_zero, sec_active, sec_misc, sec_actions])
        acc.set_title(0, "Schema & Mode")
        acc.set_title(1, "FIT Import")
        acc.set_title(2, "Displacements & Normalisation")
        acc.set_title(3, "Zeroing")
        acc.set_title(4, "Activity Mask")
        acc.set_title(5, "Clipping, Smoothing & Notes")
        acc.set_title(6, "Actions")
        acc.selected_index = 0
        return acc

    def _placeholder_grid_box(self) -> W.Box:
        # placeholder replaced once grid built
        return W.Box(layout=W.Layout(width="100%"))

    def _set_grid_in_section(self, grid: W.Widget) -> None:
        # Replace the placeholder (the 4th child of section 2 VBox)
        sec_norm: W.VBox = self.ui.children[2]  # Displacements & Normalisation section
        children = list(sec_norm.children)
        # children layout: HTML, SelectMultiple, HTML, <placeholder>
        if len(children) >= 4:
            children[3] = grid
            sec_norm.children = tuple(children)

    # ---------- Range grid ----------
    def _rebuild_ranges_grid(self) -> None:
        selected = list(self.w_disp_select.value or ())
        self._range_widgets.clear()

        nrows = max(1, len(selected))
        grid = W.GridspecLayout(n_rows=nrows, n_columns=2, layout=W.Layout(width="100%"))
        for i, col in enumerate(selected):
            lbl = W.HTML(f"<code>{col}</code>")
            default = self.default_ranges.get(col, 0.0)
            box = W.FloatText(value=_safe_float(default, 0.0), layout=W.Layout(width="160px"))
            self._range_widgets[col] = box
            grid[i, 0] = lbl
            grid[i, 1] = box

        self._ranges_grid = grid
        self._set_grid_in_section(grid)

        # Keep activity dropdown options aligned to displacement selection
        self._refresh_activity_disp_options()

    def _refresh_activity_disp_options(self) -> None:
        selected = list(self.w_disp_select.value or ())
        current = self.w_active_disp_col.value
        self.w_active_disp_col.options = selected if selected else self.disp_cols_all
        if current in (self.w_active_disp_col.options or ()):
            self.w_active_disp_col.value = current
        else:
            # choose first available
            opts = list(self.w_active_disp_col.options or [])
            self.w_active_disp_col.value = opts[0] if opts else None
        self.w_active_vel_label.value = self._derived_vel_label()

    # ---------- Derived velocity label ----------
    def _derived_vel_label(self) -> str:
        col = self.w_active_disp_col.value
        if not col:
            return "(no displacement selected)"
        try:
            return name_vel(str(col))
        except Exception as e:
            return f"(cannot derive vel: {e})"

    # ---------- Observers ----------
    def _on_disp_selection_changed(self, change: Dict[str, Any]) -> None:
        self._rebuild_ranges_grid()

    def _on_active_disp_changed(self, change: Dict[str, Any]) -> None:
        self.w_active_vel_label.value = self._derived_vel_label()

    def _on_fit_dir_browse(self) -> None:
        import tkinter as tk
        from tkinter import filedialog

        current = (self.w_fit_dir.value or "").strip()
        start_dir = current if current and Path(current).exists() else str(Path.cwd())

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title="Select FIT directory", initialdir=start_dir)
        root.destroy()

        if chosen:
            self.w_fit_dir.value = chosen

    # ---------- Validation / config ----------
    def validate(self, *, print_to_output: bool = False) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        schema = (self.w_schema_path.value or "").strip()
        if not schema:
            errors.append("Schema path is blank.")

        mode = self.w_mode.value
        if mode not in ("tolerant", "strict"):
            errors.append("Mode must be 'tolerant' or 'strict'.")

        if self.w_fit_enabled.value:
            if not (self.w_fit_dir.value or "").strip():
                errors.append("FIT import is enabled but FIT dir is blank.")
            if self.w_fit_ambiguity_policy.value == "require_binding" and not (self.w_fit_bindings_path.value or "").strip():
                errors.append("FIT ambiguity policy 'require_binding' requires a bindings path.")
            if not (self.w_fit_raw_stream_name.value or "").strip():
                errors.append("FIT raw stream name must not be blank.")
            try:
                fit_fields = self._parse_fit_field_allowlist()
                if not fit_fields:
                    warnings.append("FIT import is enabled but field allowlist is empty.")
            except Exception as e:
                errors.append(f"FIT field allowlist is invalid: {e}")

        disp_selected = list(self.w_disp_select.value or ())
        if not disp_selected:
            errors.append("No displacement signals selected.")

        # Normalisation ranges must be > 0
        for col in disp_selected:
            v = self._range_widgets.get(col)
            if v is None:
                errors.append(f"Missing range widget for: {col}")
                continue
            if v.value is None or v.value <= 0:
                errors.append(f"Normalisation range must be > 0 for: {col}")

        # Zeroing sanity
        if self.w_zero_enabled.value:
            if self.w_zero_window_s.value <= 0:
                errors.append("Zero window must be > 0.")
            if self.w_zero_min_samples.value <= 0:
                errors.append("Zero min samples must be > 0.")

        # Activity mask sanity
        if self.w_active_enabled.value:
            a_disp = self.w_active_disp_col.value
            if not a_disp:
                errors.append("Activity mask is enabled but no displacement signal is selected.")
            else:
                try:
                    _ = name_vel(str(a_disp))
                except Exception as e:
                    errors.append(f"Cannot derive velocity column from activity displacement: {e}")

            if self.w_active_disp_thresh.value < 0:
                errors.append("Activity disp threshold must be >= 0.")
            if self.w_active_vel_thresh.value < 0:
                errors.append("Activity vel threshold must be >= 0.")

            for label, w in [
                ("Activity window", self.w_active_window),
                ("Activity padding", self.w_active_padding),
                ("Activity min segment", self.w_active_min_seg),
            ]:
                if not (w.value or "").strip():
                    warnings.append(f"{label} is blank (this will likely error later).")

        # Butterworth smoothing config sanity
        try:
            _ = self._parse_butterworth_smoothing_configs()
        except Exception as e:
            errors.append(f"Butterworth smoothing config is invalid: {e}")

        if print_to_output:
            with self._out:
                self._out.clear_output()
                if errors:
                    print("❌ Errors:")
                    for e in errors:
                        print(" -", e)
                else:
                    print("✅ No blocking errors.")
                if warnings:
                    print("\n⚠️ Warnings:")
                    for w in warnings:
                        print(" -", w)

        return errors, warnings

    def get_config(self) -> Dict[str, Any]:
        """
        Returns a dict ready to be splatted into run_macro(...).
        This does NOT include csv_path; that stays in the notebook loop.
        """
        disp_selected = list(self.w_disp_select.value or ())

        normalize_ranges = {col: float(self._range_widgets[col].value) for col in disp_selected}

        cfg = dict(
            schema_path=(self.w_schema_path.value or "").strip(),
            strict=(self.w_mode.value == "strict"),
            fit_import=self._build_fit_import_config(),

            zeroing_enabled=bool(self.w_zero_enabled.value),
            zero_window_s=float(self.w_zero_window_s.value),
            zero_min_samples=int(self.w_zero_min_samples.value),

            clip_0_1=bool(self.w_clip_0_1.value),
            butterworth_smoothing=self._parse_butterworth_smoothing_configs(),
            butterworth_generate_residuals=bool(self.w_bw_generate_residuals.value),

            # Activity mask: only displacement; velocity derived in pipeline (or can be passed explicitly)
            active_signal_disp_col=(str(self.w_active_disp_col.value) if self.w_active_enabled.value else None),
            active_signal_vel_col=None,
            active_disp_thresh=float(self.w_active_disp_thresh.value),
            active_vel_thresh=float(self.w_active_vel_thresh.value),
            active_window=(self.w_active_window.value or "").strip(),
            active_padding=(self.w_active_padding.value or "").strip(),
            active_min_seg=(self.w_active_min_seg.value or "").strip(),

            normalize_ranges=normalize_ranges,

            prompt_for_descriptions=bool(self.w_prompt_desc.value),
        )

        return cfg

    def _normalize_fit_defaults(self, fit_import: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = dict(_FIT_IMPORT_DEFAULTS)
        if isinstance(fit_import, dict):
            cfg.update(dict(fit_import))
        return cfg

    def _parse_fit_field_allowlist(self) -> List[str]:
        text = (self.w_fit_field_allowlist.value or "").strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            try:
                raw = ast.literal_eval(text)
            except Exception as e:
                raise ValueError(
                    "Expected JSON (or Python-literal) list of strings like "
                    "[\"speed\", \"position_lat\"]"
                ) from e

        if not isinstance(raw, list):
            raise ValueError("Expected a list of field names")

        out = []
        for item in raw:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("FIT field allowlist entries must be non-empty strings")
            out.append(item.strip())
        return out

    def _build_fit_import_config(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.w_fit_enabled.value),
            "fit_dir": (self.w_fit_dir.value or "").strip(),
            "field_allowlist": self._parse_fit_field_allowlist(),
            "ambiguity_policy": str(self.w_fit_ambiguity_policy.value),
            "partial_overlap": str(self.w_fit_partial_overlap.value),
            "persist_raw_stream": bool(self.w_fit_persist_raw_stream.value),
            "resample_to_primary": bool(self.w_fit_resample_to_primary.value),
            "resample_method": str(self.w_fit_resample_method.value),
            "raw_stream_name": (self.w_fit_raw_stream_name.value or "").strip(),
            "bindings_path": ((self.w_fit_bindings_path.value or "").strip() or None),
        }

    def _parse_butterworth_smoothing_configs(self) -> List[Dict[str, Any]]:
        text = (self.w_bw_smoothing.value or "").strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            try:
                raw = ast.literal_eval(text)
            except Exception as e:
                raise ValueError(
                    "Expected JSON (or Python-literal) list of dicts like "
                    "[{\"cutoff_hz\": 3.0, \"order\": 4}]"
                ) from e

        if not isinstance(raw, list):
            raise ValueError("Expected a list of dict configs")

        normalized = normalize_butterworth_smoothing_configs(raw)
        return [
            {"cutoff_hz": float(cfg.cutoff_hz), "order": int(cfg.order)}
            for cfg in normalized
        ]

    def _print_config(self) -> None:
        errs, warns = self.validate(print_to_output=True)
        if errs:
            return
        cfg = self.get_config()
        with self._out:
            print("\nConfig dict (copy/paste friendly):")
            for k in sorted(cfg.keys()):
                print(f"  {k}: {cfg[k]!r}")
