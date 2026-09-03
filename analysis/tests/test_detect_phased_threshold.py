import numpy as np
import pandas as pd

from bodaqs_analysis.detect import _trigger_phased_threshold_crossing


def _event(direction="rising", **trigger_overrides):
    trigger = {
        "type": "phased_threshold_crossing",
        "signal": "vel",
        "dir": direction,
        "bands": {
            "neg": {"max": -1.0, "dwell_samples": 2},
            "zero": {"min": -0.5, "max": 0.5, "dwell_samples": 2},
            "pos": {"min": 1.0, "dwell_samples": 2},
        },
        "cross_samples": 2,
    }
    trigger.update(trigger_overrides)
    return {
        "trigger": trigger,
        "inputs": {"vel": "vel"},
    }


def test_phased_rising_aligns_to_zero_band_midpoint():
    df = pd.DataFrame(
        {
            "time_s": np.arange(9, dtype=float),
            "vel": [-2.0, -2.0, -2.0, -0.5, 0.0, 0.5, 2.0, 2.0, 2.0],
        }
    )

    candidates = _trigger_phased_threshold_crossing(df, 1.0, _event("rising"))

    assert len(candidates) == 1
    assert candidates[0]["t0_index"] == 4
    assert candidates[0]["t0_time"] == 4.0
    assert candidates[0]["trigger_value"] == 0.0


def test_phased_falling_aligns_to_zero_band_lower_midpoint_for_even_runs():
    df = pd.DataFrame(
        {
            "time_s": np.arange(8, dtype=float),
            "vel": [2.0, 2.0, 2.0, 0.5, 0.0, -2.0, -2.0, -2.0],
        }
    )

    candidates = _trigger_phased_threshold_crossing(df, 1.0, _event("falling"))

    assert len(candidates) == 1
    assert candidates[0]["t0_index"] == 3
    assert candidates[0]["t0_time"] == 3.0
    assert candidates[0]["trigger_value"] == 0.5


def test_phase_sequence_zero_pos_can_fire_from_extended_zero_region():
    df = pd.DataFrame(
        {
            "time_s": np.arange(7, dtype=float),
            "vel": [0.0, 0.0, 0.0, 0.0, 2.0, 2.0, 2.0],
        }
    )

    candidates = _trigger_phased_threshold_crossing(
        df,
        1.0,
        _event(phase_sequence="zero_pos", trigger_point="zero_end"),
    )

    assert len(candidates) == 1
    assert candidates[0]["t0_index"] == 3
    assert candidates[0]["t0_time"] == 3.0
    assert candidates[0]["trigger_value"] == 0.0


def test_phase_sequence_zero_pos_requires_adjacent_positive_run():
    df = pd.DataFrame(
        {
            "time_s": np.arange(10, dtype=float),
            "vel": [0.0, 0.0, -2.0, -2.0, 0.0, 0.0, 2.0, 2.0, 0.0, 0.0],
        }
    )

    candidates = _trigger_phased_threshold_crossing(
        df,
        1.0,
        _event(phase_sequence="zero_pos", trigger_point="zero_end"),
    )

    assert len(candidates) == 1
    assert candidates[0]["t0_index"] == 5
    assert candidates[0]["t0_time"] == 5.0
    assert candidates[0]["trigger_value"] == 0.0


def test_phase_sequence_pos_zero_can_fire_on_entry_to_extended_zero_region():
    df = pd.DataFrame(
        {
            "time_s": np.arange(7, dtype=float),
            "vel": [2.0, 2.0, 2.0, 0.4, 0.0, 0.0, 0.0],
        }
    )

    candidates = _trigger_phased_threshold_crossing(
        df,
        1.0,
        _event(phase_sequence="pos_zero", trigger_point="zero_start"),
    )

    assert len(candidates) == 1
    assert candidates[0]["t0_index"] == 3
    assert candidates[0]["t0_time"] == 3.0
    assert candidates[0]["trigger_value"] == 0.4


def test_trigger_point_final_start_marks_first_sample_in_final_band():
    df = pd.DataFrame(
        {
            "time_s": np.arange(9, dtype=float),
            "vel": [-2.0, -2.0, -2.0, -0.5, 0.0, 0.5, 2.0, 2.0, 2.0],
        }
    )

    candidates = _trigger_phased_threshold_crossing(
        df,
        1.0,
        _event(phase_sequence="neg_zero_pos", trigger_point="final_start"),
    )

    assert len(candidates) == 1
    assert candidates[0]["t0_index"] == 6
    assert candidates[0]["t0_time"] == 6.0
    assert candidates[0]["trigger_value"] == 2.0


def test_phase_sequence_falling_alias_matches_legacy_dir_alias():
    df = pd.DataFrame(
        {
            "time_s": np.arange(8, dtype=float),
            "vel": [2.0, 2.0, 2.0, 0.5, 0.0, -2.0, -2.0, -2.0],
        }
    )

    candidates = _trigger_phased_threshold_crossing(
        df,
        1.0,
        _event(phase_sequence="falling"),
    )

    assert len(candidates) == 1
    assert candidates[0]["t0_index"] == 3


def test_phase_sequence_neg_pos_can_skip_narrow_zero_band():
    df = pd.DataFrame(
        {
            "time_s": np.arange(5, dtype=float),
            "vel": [-2.0, -2.0, -2.0, 2.0, 2.0],
        }
    )

    candidates = _trigger_phased_threshold_crossing(
        df,
        1.0,
        _event(phase_sequence="neg_pos", trigger_point="final_start"),
    )

    assert len(candidates) == 1
    assert candidates[0]["t0_index"] == 3
    assert candidates[0]["t0_time"] == 3.0
    assert candidates[0]["trigger_value"] == 2.0


def test_phase_sequence_pos_neg_can_skip_narrow_zero_band():
    df = pd.DataFrame(
        {
            "time_s": np.arange(5, dtype=float),
            "vel": [2.0, 2.0, 2.0, -2.0, -2.0],
        }
    )

    candidates = _trigger_phased_threshold_crossing(
        df,
        1.0,
        _event(phase_sequence="pos_neg", trigger_point="final_start"),
    )

    assert len(candidates) == 1
    assert candidates[0]["t0_index"] == 3
    assert candidates[0]["t0_time"] == 3.0
    assert candidates[0]["trigger_value"] == -2.0


def test_phase_sequence_list_can_mix_zero_and_direct_alternatives():
    df = pd.DataFrame(
        {
            "time_s": np.arange(6, dtype=float),
            "vel": [-2.0, -2.0, -2.0, 2.0, 2.0, 2.0],
        }
    )

    candidates = _trigger_phased_threshold_crossing(
        df,
        1.0,
        _event(phase_sequence=["neg_zero", "neg_pos"], trigger_point="final_start"),
    )

    assert len(candidates) == 1
    assert candidates[0]["t0_index"] == 3

