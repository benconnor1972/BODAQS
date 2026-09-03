import numpy as np
import pandas as pd

from bodaqs_analysis.detect import _apply_metric_conditions, _compute_metrics
from bodaqs_analysis.metrics import compute_metrics_from_segments


def test_detector_interval_stats_range_is_max_minus_min():
    df = pd.DataFrame(
        {
            "time_s": np.arange(5, dtype=float),
            "disp": [2.0, 5.0, 1.0, 4.0, 3.0],
        }
    )
    event = {
        "inputs": {"disp": "disp"},
        "metrics": [
            {
                "type": "interval_stats",
                "signal": "disp",
                "start_trigger": "stroke_start",
                "end_trigger": "stroke_end",
                "ops": ["max", "min", "range"],
            }
        ],
    }
    trig_results = {
        "stroke_start": {"t0_index": 1, "t0_time": 1.0},
        "stroke_end": {"t0_index": 3, "t0_time": 3.0},
    }

    metrics = _compute_metrics(
        df,
        1.0,
        event,
        t0_idx=3,
        start_idx=0,
        end_idx=len(df),
        trig_results=trig_results,
        primary_trigger_id="stroke_end",
    )

    assert metrics["m_int_disp_max"] == 5.0
    assert metrics["m_int_disp_min"] == 1.0
    assert metrics["m_int_disp_range"] == 4.0


def test_detector_interval_stats_id_controls_metric_prefix():
    df = pd.DataFrame(
        {
            "time_s": np.arange(5, dtype=float),
            "disp": [2.0, 5.0, 1.0, 4.0, 3.0],
        }
    )
    event = {
        "inputs": {"disp": "disp"},
        "metrics": [
            {
                "id": "stroke_disp",
                "type": "interval_stats",
                "signal": "disp",
                "start_trigger": "stroke_start",
                "end_trigger": "stroke_end",
                "ops": ["range"],
                "return_debug": True,
            }
        ],
    }
    trig_results = {
        "stroke_start": {"t0_index": 1, "t0_time": 1.0},
        "stroke_end": {"t0_index": 3, "t0_time": 3.0},
    }

    metrics = _compute_metrics(
        df,
        1.0,
        event,
        t0_idx=3,
        start_idx=0,
        end_idx=len(df),
        trig_results=trig_results,
        primary_trigger_id="stroke_end",
    )

    assert metrics["m_stroke_disp_range"] == 4.0
    assert metrics["d_stroke_disp_t_start"] == 1.0
    assert metrics["d_stroke_disp_t_end"] == 3.0


def test_detector_interval_stats_smooths_before_interval_slice():
    df = pd.DataFrame(
        {
            "time_s": np.arange(40, dtype=float) * 0.002,
            "disp": np.full(40, 36.0),
        }
    )
    event = {
        "inputs": {"disp": "disp"},
        "metrics": [
            {
                "id": "stroke_disp",
                "type": "interval_stats",
                "signal": "disp",
                "start_trigger": "stroke_start",
                "end_trigger": "stroke_end",
                "ops": ["max", "min", "range"],
                "smooth_ms": 20,
            }
        ],
    }
    trig_results = {
        "stroke_start": {"t0_index": 10, "t0_time": 0.020},
        "stroke_end": {"t0_index": 24, "t0_time": 0.048},
    }

    metrics = _compute_metrics(
        df,
        0.002,
        event,
        t0_idx=10,
        start_idx=0,
        end_idx=len(df),
        trig_results=trig_results,
        primary_trigger_id="stroke_start",
    )

    assert metrics["m_stroke_disp_max"] == 36.0
    assert metrics["m_stroke_disp_min"] == 36.0
    assert metrics["m_stroke_disp_range"] == 0.0


def test_detector_interval_stats_min_delay_offsets_start_trigger():
    df = pd.DataFrame(
        {
            "time_s": np.arange(5, dtype=float),
            "disp": [0.0, 100.0, 2.0, 3.0, 4.0],
        }
    )
    event = {
        "inputs": {"disp": "disp"},
        "metrics": [
            {
                "id": "stroke_disp",
                "type": "interval_stats",
                "signal": "disp",
                "start_trigger": "stroke_start",
                "end_trigger": "stroke_end",
                "ops": ["range"],
                "min_delay_s": 1.0,
                "return_debug": True,
            }
        ],
    }
    trig_results = {
        "stroke_start": {"t0_index": 1, "t0_time": 1.0},
        "stroke_end": {"t0_index": 3, "t0_time": 3.0},
    }

    metrics = _compute_metrics(
        df,
        1.0,
        event,
        t0_idx=1,
        start_idx=0,
        end_idx=len(df),
        trig_results=trig_results,
        primary_trigger_id="stroke_start",
    )

    assert metrics["m_stroke_disp_range"] == 1.0
    assert metrics["d_stroke_disp_t_start"] == 2.0
    assert metrics["d_stroke_disp_t_end"] == 3.0


def test_metric_conditions_filter_computed_metric_values():
    event = {
        "metric_conditions": {
            "all_of": [
                {"metric": "m_stroke_disp_range", "cmp": ">", "value": 5.0},
            ]
        }
    }

    assert _apply_metric_conditions({"m_stroke_disp_range": 6.0}, event)
    assert not _apply_metric_conditions({"m_stroke_disp_range": 5.0}, event)
    assert not _apply_metric_conditions({}, event)
    assert not _apply_metric_conditions({"m_stroke_disp_range": np.nan}, event)


def test_segment_bundle_interval_stats_range_is_max_minus_min():
    events = pd.DataFrame(
        {
            "session_id": ["s1"],
            "event_id": ["range_event:front:0"],
            "schema_id": ["range_event"],
            "event_name": ["range event"],
            "trigger_time_s": [10.0],
            "stroke_start_time_s": [10.0],
            "stroke_end_time_s": [12.0],
        }
    )
    segments = pd.DataFrame(
        {
            "valid": [True],
            "event_row": [0],
            "trigger_time_s": [10.0],
        }
    )
    bundle = {
        "events": events,
        "segments": segments,
        "data": {
            "t_rel_s": np.array([[-1.0, 0.0, 1.0, 2.0, 3.0]]),
            "disp": np.array([[2.0, 5.0, 1.0, 4.0, 3.0]]),
        },
    }
    schema = {
        "events": [
            {
                "id": "range_event",
                "metrics": [
                    {
                        "type": "interval_stats",
                        "id": "disp_interval",
                        "signal": "disp",
                        "start_trigger": "stroke_start",
                        "end_trigger": "stroke_end",
                        "ops": ["max", "min", "range"],
                    }
                ],
            }
        ]
    }

    metrics = compute_metrics_from_segments(bundle, schema=schema)

    assert metrics.loc[0, "m_disp_interval_max"] == 5.0
    assert metrics.loc[0, "m_disp_interval_min"] == 1.0
    assert metrics.loc[0, "m_disp_interval_range"] == 4.0


def test_segment_bundle_interval_stats_min_delay_offsets_start_trigger():
    events = pd.DataFrame(
        {
            "session_id": ["s1"],
            "event_id": ["range_event:front:0"],
            "schema_id": ["range_event"],
            "event_name": ["range event"],
            "trigger_time_s": [10.0],
            "stroke_start_time_s": [9.0],
            "stroke_end_time_s": [12.0],
        }
    )
    segments = pd.DataFrame(
        {
            "valid": [True],
            "event_row": [0],
            "trigger_time_s": [10.0],
        }
    )
    bundle = {
        "events": events,
        "segments": segments,
        "data": {
            "t_rel_s": np.array([[-2.0, -1.0, 0.0, 1.0, 2.0]]),
            "disp": np.array([[0.0, 100.0, 2.0, 3.0, 4.0]]),
        },
    }
    schema = {
        "events": [
            {
                "id": "range_event",
                "metrics": [
                    {
                        "type": "interval_stats",
                        "id": "disp_interval",
                        "signal": "disp",
                        "start_trigger": "stroke_start",
                        "end_trigger": "stroke_end",
                        "ops": ["range"],
                        "min_delay_s": 1.0,
                        "return_debug": True,
                    }
                ],
            }
        ]
    }

    metrics = compute_metrics_from_segments(bundle, schema=schema)

    assert metrics.loc[0, "m_disp_interval_range"] == 2.0
    assert metrics.loc[0, "d_disp_interval_t0_rel_s"] == 0.0
    assert metrics.loc[0, "d_disp_interval_t1_rel_s"] == 2.0
