from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bodaqs_analysis.motion_derivation import (
    build_savgol_op_tag,
    derive_motion_channels,
    sg_window_samples,
)
from bodaqs_analysis.pipeline import preprocess_session
from bodaqs_analysis.signal_registry import build_signals_registry
from bodaqs_analysis.signal_selectors import resolve_signal_selector
from bodaqs_analysis.dashboards.simple_suspension_metrics import _norm_candidates_for_selector


def _motion_config(**overrides):
    config = {
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
    }
    config.update(overrides)
    return config


def _session(sample_rate_hz=100.0):
    t = np.arange(300, dtype=float) / sample_rate_hz
    raw = 25.0 * np.sin(2 * np.pi * 1.5 * t) + 0.5 * np.sin(2 * np.pi * 30.0 * t)
    session = {
        "session_id": "motion_test",
        "source": {},
        "meta": {},
        "qc": {"warnings": [], "transforms": {}},
        "df": pd.DataFrame(
            {
                "time_s": t,
                "rear_wheel_dom_wheel [mm]": raw,
            }
        ),
    }
    return build_signals_registry(session)


def test_sg_window_samples_materializes_ms_to_odd_samples():
    window = sg_window_samples(20.0, 500.0, 3)

    assert window.requested_samples == 10
    assert window.window_points == 11
    assert window.poly_order == 3
    assert window.adjusted is True


def test_sg_window_samples_preserves_duration_across_sample_rates():
    assert sg_window_samples(20.0, 500.0, 3).window_points == 11
    assert sg_window_samples(20.0, 1000.0, 3).window_points == 21


def test_sg_window_samples_rejects_fractional_polyorder():
    with pytest.raises(ValueError, match="positive integer"):
        sg_window_samples(20.0, 500.0, 3.5)


def test_build_savgol_op_tag_is_parser_safe():
    assert build_savgol_op_tag(20.0, 3) == "Savgol20ms3Poly"
    assert build_savgol_op_tag(12.5, 2) == "Savgol12p5ms2Poly"


def test_derive_motion_channels_generates_primary_series_with_provenance():
    session = _session()

    out, meta = derive_motion_channels(
        session,
        _motion_config(),
        sample_rate_hz=100.0,
    )

    disp_col = "rear_wheel_disp_dom_wheel [mm]"
    vel_col = "rear_wheel_vel_dom_wheel [mm/s]"
    acc_col = "rear_wheel_acc_dom_wheel [mm/s^2]"

    assert disp_col in out.columns
    assert vel_col in out.columns
    assert acc_col in out.columns
    assert len(meta["generated"]) == 3
    assert meta["generated_channel_info"][vel_col]["processing_role"] == "primary_analysis"
    assert meta["generated_channel_info"][vel_col]["quantity"] == "vel"
    assert meta["generated_channel_info"][vel_col]["derivation"]["velocity_sg_window"]["window_points"] == 5


def test_derive_motion_channels_generates_secondary_series():
    session = _session()
    config = _motion_config(
        secondary=[
            {
                "id": "slow",
                "displacement_lowpass_hz": 5.0,
                "displacement_lowpass_order": 2,
                "velocity_sg_window_ms": 50.0,
                "acceleration_sg_window_ms": 70.0,
                "sg_polyorder": 3,
                "velocity_lowpass_hz": 4.0,
                "velocity_lowpass_order": 2,
                "acceleration_lowpass_hz": 3.0,
                "acceleration_lowpass_order": 2,
            }
        ],
    )

    out, meta = derive_motion_channels(session, config, sample_rate_hz=100.0)

    primary_disp_col = "rear_wheel_disp_dom_wheel [mm]"
    secondary_disp_col = "rear_wheel_disp_lp5hz_dom_wheel [mm]"
    secondary_vel_col = "rear_wheel_vel_lp5hz_dom_wheel [mm/s]"

    assert primary_disp_col in out.columns
    assert secondary_disp_col in out.columns
    assert secondary_vel_col in out.columns
    assert len(meta["generated"]) == 6
    assert meta["generated_channel_info"][secondary_disp_col]["processing_role"] == "secondary_analysis"
    assert meta["generated_channel_info"][secondary_disp_col]["motion_profile_id"] == "slow"
    assert meta["generated_channel_info"][secondary_vel_col]["processing_role"] == "secondary_analysis"


def test_same_parameter_secondary_profile_gets_its_own_compact_suffix():
    session = _session()
    config = _motion_config(secondary=[{"id": "duplicate", **_motion_config()["primary"]}])

    _out, meta = derive_motion_channels(session, config, sample_rate_hz=100.0)

    assert len(meta["generated"]) == 6
    assert len(meta["generated_channel_info"]) == 6
    assert len(meta["skipped"]) == 0
    assert "rear_wheel_disp_lp10hz_dom_wheel [mm]" in meta["generated_channel_info"]


def test_generated_motion_channel_info_survives_registry_rebuild_and_selector_resolution():
    session = _session()
    out, meta = derive_motion_channels(
        session,
        _motion_config(),
        sample_rate_hz=100.0,
    )
    session["df"] = out
    session["meta"].setdefault("channel_info", {}).update(meta["generated_channel_info"])

    build_signals_registry(session)

    vel_col = "rear_wheel_vel_dom_wheel [mm/s]"
    signal_info = session["meta"]["signals"][vel_col]
    assert signal_info["processing_role"] == "primary_analysis"
    assert signal_info["motion_source_id"] == "rear_wheel"
    assert signal_info["motion_profile_id"] == "primary"
    assert signal_info["source"] == ["rear_wheel_dom_wheel [mm]"]
    assert signal_info["derivation"]["method"] == "motion_derivation"

    resolved = resolve_signal_selector(
        session,
        {
            "end": "rear",
            "domain": "wheel",
            "quantity": "vel",
            "unit": "mm/s",
            "processing_role": "primary_analysis",
        },
        purpose="test primary analysis velocity",
        allow_missing=False,
    )
    assert resolved == vel_col


def test_primary_motion_disp_collision_can_annotate_or_overwrite_existing_logger_signal():
    existing_col = "rear_wheel_disp_dom_wheel [mm]"
    t = np.arange(300, dtype=float) / 100.0
    raw = 25.0 * np.sin(2 * np.pi * 1.5 * t) + 0.5 * np.sin(2 * np.pi * 30.0 * t)
    session = {
        "df": pd.DataFrame({"time_s": t, existing_col: raw}),
        "meta": {
            "signals": {
                existing_col: {
                    "end": "rear",
                    "domain": "wheel",
                    "quantity": "disp",
                    "unit": "mm",
                    "origin": "logger",
                }
            }
        },
    }
    original = session["df"][existing_col].copy()

    kept, kept_meta = derive_motion_channels(
        session,
        _motion_config(),
        sample_rate_hz=100.0,
        overwrite_existing_primary=False,
    )
    overwritten, overwritten_meta = derive_motion_channels(
        session,
        _motion_config(),
        sample_rate_hz=100.0,
        overwrite_existing_primary=True,
    )

    assert kept_meta["generated"][0]["existing_output"] == "annotated_existing"
    assert overwritten_meta["generated"][0]["existing_output"] == "overwritten"
    assert kept[existing_col].equals(original)
    assert not overwritten[existing_col].equals(original)
    assert kept_meta["generated_channel_info"][existing_col]["processing_role"] == "primary_analysis"
    assert kept_meta["generated_channel_info"][existing_col]["origin"] == "logger"
    assert overwritten_meta["generated_channel_info"][existing_col]["origin"] == "analysis"


def test_derive_motion_channels_disabled_is_noop_copy():
    session = _session()

    out, meta = derive_motion_channels(
        session,
        {"enabled": False},
        sample_rate_hz=100.0,
    )

    assert out is not session["df"]
    assert list(out.columns) == list(session["df"].columns)
    assert meta["enabled"] is False
    assert meta["generated"] == []


def test_derive_motion_channels_rejects_cutoffs_above_nyquist():
    session = _session()
    config = _motion_config(
        primary={
            **_motion_config()["primary"],
            "displacement_lowpass_hz": 60.0,
        }
    )

    with pytest.raises(ValueError, match="below Nyquist"):
        derive_motion_channels(session, config, sample_rate_hz=100.0)


def test_preprocess_session_applies_motion_derivation_before_normalization_and_activity():
    session = _session()
    config = {
        "schema_path": "event schema/event_schema.yaml",
        "strict": True,
        "zeroing_enabled": False,
        "zero_window_s": 0.4,
        "zero_min_samples": 10,
        "clip_0_1": False,
        "motion_derivation": _motion_config(),
        "butterworth_smoothing": [],
        "butterworth_generate_residuals": False,
        "active_signal_disp_selector": {
            "end": "rear",
            "domain": "wheel",
            "quantity": "disp",
            "unit": "mm",
            "processing_role": "primary_analysis",
        },
        "active_signal_vel_selector": {
            "end": "rear",
            "domain": "wheel",
            "quantity": "vel",
            "unit": "mm/s",
            "processing_role": "primary_analysis",
        },
        "active_disp_thresh": 1.0,
        "active_vel_thresh": 1.0,
        "active_window": "100ms",
        "active_padding": "0s",
        "active_min_seg": "0s",
    }

    out = preprocess_session(
        session,
        preprocess_config=config,
        normalize_ranges={"rear_wheel_dom_wheel [mm]": 150.0},
        include_events=False,
        include_metrics=False,
    )["session"]

    disp_col = "rear_wheel_disp_dom_wheel [mm]"
    vel_col = "rear_wheel_vel_dom_wheel [mm/s]"
    norm_col = "rear_wheel_disp_norm_dom_wheel [1]"

    assert disp_col in out["df"].columns
    assert vel_col in out["df"].columns
    assert norm_col in out["df"].columns
    assert out["qc"]["transforms"]["motion_derivation"]["applied"] is True
    assert out["qc"]["activity_mask"]["disp_col"] == disp_col
    assert out["qc"]["activity_mask"]["vel_col"] == vel_col
    assert out["meta"]["signals"][disp_col]["processing_role"] == "primary_analysis"
    assert out["meta"]["signals"][norm_col]["processing_role"] == "primary_analysis"
    assert out["meta"]["signals"][norm_col]["source"] == [disp_col]
    assert "norm" in out["meta"]["signals"][norm_col]["op_chain"]
    assert _norm_candidates_for_selector(
        out["meta"]["signals"],
        {"end": "rear", "domain": "wheel"},
    )[0] == norm_col


def test_simple_metrics_norm_resolver_accepts_semantic_norm_without_op_chain():
    signals = {
        "rear_wheel_disp_norm_dom_wheel [1]": {
            "end": "rear",
            "domain": "wheel",
            "quantity": "disp_norm",
            "unit": "1",
            "processing_role": "primary_analysis",
            "op_chain": [],
        }
    }

    assert _norm_candidates_for_selector(signals, {"end": "rear", "domain": "wheel"}) == [
        "rear_wheel_disp_norm_dom_wheel [1]"
    ]
