from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from bodaqs_analysis.bike_profile import (
    apply_signal_transforms,
    load_bike_profile,
    parse_bike_profile,
    resolve_normalization_ranges,
)
from bodaqs_analysis.preprocess_profile import default_preprocess_config
from bodaqs_analysis.pipeline import preprocess_resolved, preprocess_session


def _session() -> dict:
    n = 25
    return {
        "session_id": "bike_profile_test",
        "source": {},
        "meta": {},
        "qc": {"warnings": [], "transforms": {}},
        "df": pd.DataFrame(
            {
                "time_s": np.arange(n, dtype=float) * 0.02,
                "front_shock_dom_suspension [mm]": np.linspace(0.0, 24.0, n),
                "rear_shock_dom_suspension [mm]": np.linspace(2.0, 26.0, n),
            }
        ),
    }


def _bike_profile() -> dict:
    return {
        "schema": "bodaqs.bike_profile",
        "version": 1,
        "bike_profile_id": "test_bike",
        "display_name": "Test bike",
        "normalization_ranges": [
            {
                "id": "fork_range",
                "signal": {
                    "end": "front",
                    "quantity": "disp",
                    "domain": "suspension",
                    "unit": "mm",
                },
                "full_range": 170.0,
            },
            {
                "id": "rear_shock_range",
                "signal": {
                    "end": "rear",
                    "quantity": "disp",
                    "domain": "suspension",
                    "unit": "mm",
                },
                "full_range": 65.0,
            },
            {
                "id": "rear_wheel_range_not_logged",
                "signal": {
                    "end": "rear",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                },
                "full_range": 150.0,
            },
        ],
    }


def _bike_profile_with_transform() -> dict:
    profile = _bike_profile()
    profile["normalization_ranges"].append(
        {
            "id": "rear_wheel_range",
            "signal": {
                "end": "rear",
                "quantity": "disp",
                "domain": "wheel",
                "unit": "mm",
            },
            "full_range": 150.0,
        }
    )
    profile["signal_transforms"] = [
        {
            "id": "rear_shock_to_rear_wheel_travel",
            "enabled": True,
            "input": {
                "end": "rear",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
            },
            "output": {
                "end": "rear",
                "quantity": "disp",
                "domain": "wheel",
                "unit": "mm",
            },
            "method": "lut",
            "interpolation": "linear",
            "extrapolation": "linear",
            "lut": [
                {"input": 0.0, "output": 0.0},
                {"input": 10.0, "output": 25.0},
                {"input": 20.0, "output": 50.0},
            ],
        }
    ]
    return profile


def test_resolve_normalization_ranges_matches_semantic_selectors():
    session = _session()

    ranges = resolve_normalization_ranges(session, _bike_profile())

    assert ranges == {
        "front_shock_dom_suspension [mm]": 170.0,
        "rear_shock_dom_suspension [mm]": 65.0,
    }
    assert "bike_profile_normalization_range_unmatched:rear_wheel_range_not_logged" in session["qc"]["warnings"]
    assert session["meta"]["bike_profile_id"] == "test_bike"


def test_apply_signal_transforms_generates_semantic_output_column():
    session = _session()

    out = apply_signal_transforms(session, _bike_profile_with_transform())

    assert out is session
    assert "rear_wheel_disp_dom_wheel [mm]" in session["df"].columns
    assert np.isclose(session["df"]["rear_wheel_disp_dom_wheel [mm]"].iloc[4], 15.0)
    assert session["meta"]["signals"]["rear_wheel_disp_dom_wheel [mm]"]["end"] == "rear"
    assert session["meta"]["signals"]["rear_wheel_disp_dom_wheel [mm]"]["sensor"] == "rear_wheel"
    assert session["meta"]["signals"]["rear_wheel_disp_dom_wheel [mm]"]["domain"] == "wheel"
    assert session["qc"]["transforms"]["bike_profile_signal_transforms"]["generated"][0]["transform_id"] == (
        "rear_shock_to_rear_wheel_travel"
    )


def test_preprocess_session_resolves_ranges_after_bike_profile_transforms(tmp_path):
    profile_path = tmp_path / "test_bike_v1.json"
    profile_path.write_text(json.dumps(_bike_profile_with_transform()), encoding="utf-8")

    out = preprocess_session(
        _session(),
        bike_profile_path=profile_path,
        zeroing_enabled=False,
    )["session"]

    assert "rear_wheel_disp_dom_wheel [mm]" in out["df"].columns
    assert "rear_wheel_disp_norm_dom_wheel [1]" in out["df"].columns
    scaled = out["qc"]["transforms"]["scaled"]["by_channel"]
    assert scaled["rear_wheel_disp_dom_wheel [mm]"]["full_range"] == 150.0


def test_preprocess_session_zeroes_before_bike_profile_transforms(tmp_path):
    profile_path = tmp_path / "test_bike_v1.json"
    profile_path.write_text(json.dumps(_bike_profile_with_transform()), encoding="utf-8")

    out = preprocess_session(
        _session(),
        bike_profile_path=profile_path,
        zeroing_enabled=True,
    )["session"]

    assert np.isclose(out["df"]["rear_shock_dom_suspension [mm]"].iloc[0], 0.0)
    assert np.isclose(out["df"]["rear_wheel_disp_dom_wheel [mm]"].iloc[0], 0.0)
    assert np.isclose(out["df"]["rear_wheel_disp_dom_wheel [mm]"].iloc[4], 10.0)
    assert "rear_wheel_disp_dom_wheel [1]_op_zeroed_norm" in out["df"].columns


def test_preprocess_session_uses_one_canonical_wheel_displacement_after_motion_derivation():
    config = default_preprocess_config(
        prefer_postprocessing_transformations=True,
        zeroing_enabled=False,
        motion_derivation={
            "enabled": True,
            "sources": [
                {
                    "id": "rear_wheel",
                    "selector": {
                        "end": "rear",
                        "quantity": "disp",
                        "domain": "wheel",
                        "unit": "mm",
                    },
                }
            ],
            "primary": {
                "displacement_lowpass_hz": 10.0,
                "displacement_lowpass_order": 2,
                "velocity_sg_window_ms": 20.0,
                "acceleration_sg_window_ms": 40.0,
                "sg_polyorder": 3,
                "velocity_lowpass_hz": 8.0,
                "velocity_lowpass_order": 2,
                "acceleration_lowpass_hz": 6.0,
                "acceleration_lowpass_order": 2,
            },
            "secondary": [],
        },
        active_signal_disp_selector={
            "end": "rear",
            "quantity": "disp",
            "domain": "wheel",
            "unit": "mm",
        },
        active_signal_vel_selector={
            "end": "rear",
            "quantity": "vel",
            "domain": "wheel",
            "unit": "mm/s",
        },
    )

    out = preprocess_session(
        _session(),
        preprocess_config=config,
        bike_profile=_bike_profile_with_transform(),
        include_events=False,
        include_metrics=False,
    )["session"]

    disp_col = "rear_wheel_disp_dom_wheel [mm]"
    vel_col = "rear_wheel_vel_dom_wheel [mm/s]"
    assert disp_col in out["df"].columns
    assert "rear_wheel_dom_wheel [mm]" not in out["df"].columns
    assert out["qc"]["activity_mask"]["disp_col"] == disp_col
    assert out["qc"]["activity_mask"]["vel_col"] == vel_col
    disp_matches = [
        col
        for col, info in out["meta"]["signals"].items()
        if info.get("end") == "rear"
        and info.get("quantity") == "disp"
        and info.get("domain") == "wheel"
        and info.get("unit") == "mm"
        and not info.get("semantic_selection_excluded")
    ]
    assert disp_matches == [disp_col]
    assert out["meta"]["signals"][disp_col]["processing_role"] == "primary_analysis"


def test_apply_signal_transforms_skips_existing_output_column():
    session = _session()
    session["df"]["rear_wheel_disp_dom_wheel [mm]"] = np.linspace(0.0, 48.0, len(session["df"]))

    apply_signal_transforms(session, _bike_profile_with_transform())

    assert session["df"]["rear_wheel_disp_dom_wheel [mm]"].iloc[-1] == 48.0
    transform_qc = session["qc"]["transforms"]["bike_profile_signal_transforms"]
    assert transform_qc["generated"] == []
    assert transform_qc["skipped"][0]["reason"] == "output_exists"
    assert any(str(w).startswith("bike_profile_signal_transform_output_exists") for w in session["qc"]["warnings"])


def test_apply_signal_transforms_prefers_existing_equivalent_logger_semantics():
    session = _session()
    session["df"]["rear_wheel_disp_dom_wheel [mm]"] = np.linspace(0.0, 48.0, len(session["df"]))
    session["meta"]["channel_info"] = {
        "rear_wheel_disp_dom_wheel [mm]": {
            "end": "rear",
            "quantity": "disp",
            "domain": "wheel",
            "unit": "mm",
            "origin": "logger",
        }
    }

    apply_signal_transforms(session, _bike_profile_with_transform(), output_conflict_policy="prefer_existing")

    assert session["df"]["rear_wheel_disp_dom_wheel [mm]"].iloc[-1] == 48.0
    transform_qc = session["qc"]["transforms"]["bike_profile_signal_transforms"]
    assert transform_qc["generated"] == []
    assert transform_qc["skipped"][0]["reason"] == "logger_output_semantics_exists"


def test_apply_signal_transforms_can_supersede_equivalent_logger_semantics():
    session = _session()
    session["df"]["rear_wheel_disp_dom_wheel [mm]"] = np.linspace(0.0, 48.0, len(session["df"]))
    session["meta"]["channel_info"] = {
        "rear_wheel_disp_dom_wheel [mm]": {
            "end": "rear",
            "quantity": "disp",
            "domain": "wheel",
            "unit": "mm",
            "origin": "logger",
        }
    }

    apply_signal_transforms(session, _bike_profile_with_transform(), output_conflict_policy="prefer_analysis")

    assert np.isclose(session["df"]["rear_wheel_disp_dom_wheel [mm]"].iloc[4], 15.0)
    assert not session["meta"]["channel_info"]["rear_wheel_disp_dom_wheel [mm]"].get(
        "semantic_selection_excluded",
        False,
    )
    assert session["meta"]["channel_info"]["rear_wheel_disp_dom_wheel [mm]"]["origin"] == "analysis"
    transform_qc = session["qc"]["transforms"]["bike_profile_signal_transforms"]
    assert transform_qc["generated"][0]["transform_id"] == "rear_shock_to_rear_wheel_travel"


def test_preprocess_session_accepts_bike_profile_path(tmp_path):
    profile_path = tmp_path / "test_bike_v1.json"
    profile_path.write_text(json.dumps(_bike_profile()), encoding="utf-8")

    out = preprocess_session(
        _session(),
        bike_profile_path=profile_path,
        zeroing_enabled=False,
    )["session"]

    assert "front_shock_dom_suspension [1]_op_norm" in out["df"].columns
    assert "rear_shock_dom_suspension [1]_op_norm" in out["df"].columns
    assert out["qc"]["bike_profile"]["bike_profile_path"] == str(profile_path)


def test_parse_bike_profile_accepts_mapping_text_and_bytes():
    profile = _bike_profile()
    profile_text = json.dumps(profile)

    parsed_from_mapping = parse_bike_profile(profile)
    parsed_from_text = parse_bike_profile(profile_text)
    parsed_from_bytes = parse_bike_profile(profile_text.encode("utf-8"))

    assert parsed_from_mapping["bike_profile_id"] == "test_bike"
    assert parsed_from_text["display_name"] == "Test bike"
    assert parsed_from_bytes["normalization_ranges"][0]["id"] == "fork_range"


def test_preprocess_resolved_accepts_loaded_bike_profile_without_paths():
    out = preprocess_resolved(
        _session(),
        preprocess_config=default_preprocess_config(),
        bike_profile=_bike_profile(),
        include_events=False,
        include_metrics=False,
    )["session"]

    assert "front_shock_dom_suspension [1]_op_norm" in out["df"].columns
    assert "rear_shock_dom_suspension [1]_op_norm" in out["df"].columns
    assert out["meta"]["bike_profile_id"] == "test_bike"


def test_preprocess_session_resolves_activity_mask_from_semantic_selectors():
    out = preprocess_session(
        _session(),
        preprocess_config=default_preprocess_config(),
        bike_profile=_bike_profile(),
        include_events=False,
        include_metrics=False,
    )["session"]

    activity = out["qc"]["activity_mask"]

    assert activity["disp_col"] == "rear_shock_dom_suspension [mm]"
    assert activity["vel_col"] == "rear_shock_vel_dom_suspension [mm/s]"
    assert activity["disp_selector"] == {
        "end": "rear",
        "quantity": "disp",
        "domain": "suspension",
        "unit": "mm",
    }


def test_bike_profile_range_selector_must_not_match_multiple_signals():
    profile = _bike_profile()
    profile["normalization_ranges"] = [
        {
            "id": "ambiguous_suspension_displacement",
            "signal": {"quantity": "disp", "domain": "suspension", "unit": "mm"},
            "full_range": 100.0,
        }
    ]

    with pytest.raises(ValueError, match="matched multiple session signals"):
        resolve_normalization_ranges(_session(), profile)


def test_bike_profile_uses_end_for_suspension_range_selectors():
    profile = _bike_profile()
    profile["normalization_ranges"] = [
        {
            "id": "legacy_sensor_fork_range",
            "signal": {
                "end": "front",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
            },
            "full_range": 170.0,
        }
    ]

    ranges = resolve_normalization_ranges(_session(), profile)

    assert ranges == {"front_shock_dom_suspension [mm]": 170.0}


def test_load_bike_profile_rejects_legacy_range_map(tmp_path):
    profile = _bike_profile()
    profile["normalization_ranges"] = {"front_shock_dom_suspension [mm]": 170.0}
    profile_path = tmp_path / "legacy_range_map.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    with pytest.raises(ValueError, match="normalization_ranges.*array"):
        load_bike_profile(profile_path)
