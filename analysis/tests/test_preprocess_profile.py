from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from bodaqs_analysis import (
    default_preprocess_config,
    discover_preprocess_profiles,
    load_preprocess_config,
    load_preprocess_profile,
    make_preprocess_profile,
    preprocess_config_from_profile,
    preprocess_profile_filename,
    preprocess_profile_path,
    resolve_preprocess_config_paths,
    save_preprocess_profile,
)
from bodaqs_analysis.ui.preprocess_profile_editor import PreprocessProfileEditor
from bodaqs_analysis.pipeline import preprocess_session


def _profile() -> dict:
    return {
        "schema": "bodaqs.preprocess_profile",
        "version": 1,
        "profile_id": "test_profile",
        "config": {
            "schema_path": "event schema/event_schema.yaml",
            "strict": False,
            "zeroing_enabled": False,
            "zero_window_s": 0.4,
            "zero_min_samples": 10,
            "clip_0_1": False,
            "butterworth_smoothing": [],
            "butterworth_generate_residuals": False,
            "active_signal_disp_selector": {
                "end": "rear",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
            },
            "active_signal_vel_selector": {
                "end": "rear",
                "quantity": "vel",
                "domain": "suspension",
                "unit": "mm/s",
            },
            "active_disp_thresh": 20.0,
            "active_vel_thresh": 50.0,
            "active_window": "500ms",
            "active_padding": "1s",
            "active_min_seg": "3s",
        },
    }


def test_load_preprocess_profile_and_config(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(_profile()), encoding="utf-8")

    profile = load_preprocess_profile(profile_path)
    cfg = load_preprocess_config(profile_path)

    assert profile["profile_id"] == "test_profile"
    assert cfg == preprocess_config_from_profile(profile)
    assert cfg is not profile["config"]
    assert "prefer_postprocessing_transformations" not in cfg


def test_legacy_on_logger_transform_key_maps_to_postprocessing_preference(tmp_path):
    profile = _profile()
    profile["config"]["ignore_on_logger_transformations"] = True
    profile_path = tmp_path / "legacy_profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    loaded = load_preprocess_profile(profile_path)
    cfg = load_preprocess_config(profile_path)

    assert loaded["config"]["prefer_postprocessing_transformations"] is True
    assert "ignore_on_logger_transformations" not in loaded["config"]
    assert cfg["prefer_postprocessing_transformations"] is True
    assert "ignore_on_logger_transformations" not in cfg


def test_make_save_and_discover_preprocess_profile(tmp_path):
    config = default_preprocess_config(
        schema_path="event schema/event_schema - Basic.yaml",
    )
    assert config["motion_derivation"]["enabled"] is False
    assert config["motion_derivation"]["primary"]["velocity_sg_window_ms"] == 20.0

    profile = make_preprocess_profile(
        "Test Profile",
        config=config,
        description="Test profile for UI/editor helpers",
    )
    path = tmp_path / preprocess_profile_filename(profile["profile_id"])

    saved = save_preprocess_profile(profile, path)
    loaded = load_preprocess_profile(saved)
    discovered = discover_preprocess_profiles(tmp_path)

    assert loaded["profile_id"] == "Test Profile"
    assert path.name == "test_profile_v1.json"
    assert discovered == [
        {
            "path": str(path),
            "profile_id": "Test Profile",
            "version": 1,
            "description": "Test profile for UI/editor helpers",
            "valid": True,
        }
    ]
    assert preprocess_profile_path("Test Profile", directory=tmp_path) == path


def test_resolve_preprocess_config_paths_uses_supplied_base_dir(tmp_path):
    cfg = preprocess_config_from_profile(_profile())

    resolved = resolve_preprocess_config_paths(cfg, base_dir=tmp_path)

    assert resolved["schema_path"] == str((tmp_path / "event schema/event_schema.yaml").resolve())


def test_preprocess_profile_editor_loads_edits_and_saves(tmp_path):
    source_profile = make_preprocess_profile(
        "editor_profile",
        config=default_preprocess_config(
            schema_path="event schema/event_schema.yaml",
        ),
    )
    source_path = save_preprocess_profile(source_profile, tmp_path / "editor_profile_v1.json")

    editor = PreprocessProfileEditor(profile_path=source_path, profiles_dir=tmp_path)
    editor.w_profile_id.value = "edited_profile"
    editor.w_schema_path.value = "event schema/event_schema - Basic.yaml"

    errors, warnings = editor.validate()
    out_path = editor.save_profile(tmp_path / "edited_profile_v1.json")
    saved = load_preprocess_profile(out_path)

    assert errors == []
    assert warnings == []
    assert saved["profile_id"] == "edited_profile"
    assert saved["config"]["schema_path"] == "event schema/event_schema - Basic.yaml"
    assert saved["config"]["motion_derivation"]["primary"]["displacement_lowpass_hz"] == 80.0
    assert saved["config"]["motion_derivation"]["enabled"] is False
    assert "prefer_postprocessing_transformations" in saved["config"]


def test_preprocess_profile_editor_save_filename_supports_save_as(tmp_path):
    source_profile = make_preprocess_profile(
        "editor_profile",
        config=default_preprocess_config(),
    )
    source_path = save_preprocess_profile(source_profile, tmp_path / "editor_profile_v1.json")

    editor = PreprocessProfileEditor(profile_path=source_path, profiles_dir=tmp_path)
    editor.w_profile_id.value = "edited_profile"
    editor.w_save_filename.value = "save_as_profile_v1.json"

    out_path = editor.save_profile()
    saved = load_preprocess_profile(out_path)

    assert out_path == tmp_path / "save_as_profile_v1.json"
    assert editor.current_profile_path == out_path
    assert saved["profile_id"] == "edited_profile"


def test_preprocess_profile_editor_motion_derivation_controls_roundtrip(tmp_path):
    source_profile = make_preprocess_profile(
        "editor_profile",
        config=default_preprocess_config(),
    )
    source_path = save_preprocess_profile(source_profile, tmp_path / "editor_profile_v1.json")

    editor = PreprocessProfileEditor(profile_path=source_path, profiles_dir=tmp_path)
    editor.w_motion_enabled.value = True
    editor.w_motion_sources.value = json.dumps(
        [
            {
                "id": "rear_wheel",
                "selector": {
                    "end": "rear",
                    "domain": "wheel",
                    "quantity": "disp",
                    "unit": "mm",
                },
            }
        ]
    )
    editor.w_motion_primary.value = json.dumps(
        {
            "displacement_lowpass_hz": 80.0,
            "displacement_lowpass_order": 4,
            "velocity_sg_window_ms": 20.0,
            "acceleration_sg_window_ms": 40.0,
            "sg_polyorder": 3,
            "velocity_lowpass_hz": 60.0,
            "velocity_lowpass_order": 4,
            "acceleration_lowpass_hz": 30.0,
            "acceleration_lowpass_order": 4,
        }
    )
    editor.w_motion_secondary.value = json.dumps(
        [
            {
                "id": "low_bandwidth",
                "displacement_lowpass_hz": 20.0,
                "displacement_lowpass_order": 4,
                "velocity_sg_window_ms": 50.0,
                "acceleration_sg_window_ms": 80.0,
                "sg_polyorder": 3,
                "velocity_lowpass_hz": 15.0,
                "velocity_lowpass_order": 4,
                "acceleration_lowpass_hz": 10.0,
                "acceleration_lowpass_order": 4,
            }
        ]
    )

    saved = load_preprocess_profile(editor.save_profile(tmp_path / "motion_enabled_v1.json"))

    motion = saved["config"]["motion_derivation"]
    assert motion["enabled"] is True
    assert motion["sources"][0]["id"] == "rear_wheel"
    assert motion["primary"]["velocity_sg_window_ms"] == 20.0
    assert motion["secondary"][0]["id"] == "low_bandwidth"


def test_load_preprocess_profile_rejects_runtime_binding_fields(tmp_path):
    profile = _profile()
    profile["config"]["bike_profile_path"] = "config/bike_profiles/example_enduro_bike_v1.json"
    profile_path = tmp_path / "bad_profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    with pytest.raises(ValueError, match="runtime binding field"):
        load_preprocess_profile(profile_path)


def test_load_preprocess_profile_rejects_invalid_motion_derivation(tmp_path):
    profile = _profile()
    profile["config"]["motion_derivation"] = {
        "enabled": True,
        "sources": [],
        "primary": {
            "displacement_lowpass_hz": 80.0,
            "displacement_lowpass_order": 4,
            "velocity_sg_window_ms": 20.0,
            "acceleration_sg_window_ms": 40.0,
            "sg_polyorder": 3,
            "velocity_lowpass_hz": 60.0,
            "velocity_lowpass_order": 4,
            "acceleration_lowpass_hz": 30.0,
            "acceleration_lowpass_order": 4,
        },
        "secondary": [],
    }
    profile_path = tmp_path / "bad_motion_profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    with pytest.raises(ValueError, match="motion_derivation.sources"):
        load_preprocess_profile(profile_path)


def test_preprocess_session_accepts_preprocess_config_with_legacy_ranges():
    session = {
        "session_id": "profile_config_test",
        "source": {},
        "meta": {},
        "qc": {"warnings": [], "transforms": {}},
        "df": pd.DataFrame(
            {
                "time_s": np.arange(30, dtype=float) * 0.02,
                "front_shock_dom_suspension [mm]": np.linspace(0.0, 29.0, 30),
            }
        ),
    }
    cfg = _profile()["config"]

    out = preprocess_session(
        session,
        preprocess_config=cfg,
        normalize_ranges={"front_shock_dom_suspension [mm]": 170.0},
        include_events=False,
        include_metrics=False,
    )["session"]

    assert "front_shock_dom_suspension [1]_op_norm" in out["df"].columns
