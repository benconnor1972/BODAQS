"""Regression coverage for clipped stroke windows and discontinuous recordings."""

from functools import wraps

import numpy as np
import pandas as pd
import pytest

import bodaqs_analysis.detect as detect
from bodaqs_analysis.metrics import compute_metrics_from_segments
from bodaqs_analysis.motion_derivation import derive_motion_channels
from bodaqs_analysis.preprocess_filters import apply_butterworth_smoothing, normalize_butterworth_smoothing_configs
from bodaqs_analysis.schema import basic_validate, parse_event_schema
from bodaqs_analysis.segment import extract_segments, SegmentRequest, OutputSpec
from bodaqs_analysis.timebase import continuous_segments
from bodaqs_analysis.raw_signal_dropouts import (
    apply_raw_signal_dropout_filter, DEFAULT_RAW_SIGNAL_DROPOUT_FILTER,
)
from bodaqs_analysis.va import estimate_va


def _meta():
    return {"signals": {
        "disp": {"quantity": "disp", "unit": "mm", "end": "front", "domain": "wheel"},
        "vel": {"quantity": "vel", "unit": "mm/s", "end": "front", "domain": "wheel"},
    }}


def _schema():
    return {"version": "1", "events": [{
        "id": "stroke", "inputs": {
            "disp": {"quantity": "disp", "unit": "mm"},
            "vel": {"quantity": "vel", "unit": "mm/s"},
        },
        "trigger": {"id": "finish", "type": "local_extrema", "signal": "disp", "kind": "max"},
        "segment_defaults": {"window": {"pre_s": .8, "post_s": .2}, "roles": [
            {"role": "disp", "prefer": {"quantity": "disp", "unit": "mm"}},
            {"role": "vel", "prefer": {"quantity": "vel", "unit": "mm/s"}},
        ]},
        "metrics": [{"id": "stroke_disp", "type": "interval_stats", "signal": "disp",
                     "start_trigger": "begin", "end_trigger": "finish",
                     "ops": ["min", "max", "range", "delta", "integral"], "return_debug": True},
                    {"id": "peak", "type": "peak", "signal": "disp", "kind": "max", "return_time": True}],
    }]}


def _events(times):
    return pd.DataFrame({
        "session_id": ["test"] * len(times), "event_id": [f"e{i}" for i in range(len(times))],
        "schema_id": ["stroke"] * len(times), "signal_col": ["vel"] * len(times),
        "trigger_time_s": times, "begin_time_s": np.asarray(times) - .1, "finish_time_s": times,
    })


def test_clipped_first_window_does_not_shift_other_stroke_metrics():
    t = np.arange(2001) * .002
    df = pd.DataFrame({"time_s": t, "disp": t * 100, "vel": np.full(len(t), 100.)})
    events, schema = _events([.304, 2.4]), _schema()
    results = []
    for ordered in [events, events.iloc[::-1].reset_index(drop=True)]:
        bundle = extract_segments(df, ordered, meta=_meta(), schema=schema)
        result = compute_metrics_from_segments(bundle, schema=schema).set_index("event_id").sort_index()
        np.testing.assert_allclose(result.m_stroke_disp_range, 10, atol=1e-10)
        np.testing.assert_allclose(result.m_stroke_disp_delta, 10, atol=1e-10)
        np.testing.assert_allclose(result.m_stroke_disp_integral, [2.54, 23.5], atol=1e-10)
        results.append(result)
    pd.testing.assert_frame_equal(*results)


def test_sample_timestamps_keep_float64_even_with_float32_signal_output():
    t = 70000 + np.arange(501) * .002
    df = pd.DataFrame({"time_s": t, "disp": np.arange(len(t), dtype=float), "vel": np.ones(len(t))})
    event = _events([t[200]])
    event["begin_time_s"] = t[180]
    schema = _schema()
    for output in [OutputSpec(), OutputSpec(dtype=np.float32)]:
        bundle = extract_segments(df, event, meta=_meta(), schema=schema, request=SegmentRequest(output=output))
        assert bundle["data"]["time_s"].dtype == np.float64
        assert bundle["data"]["t_rel_s"].dtype == np.float64
        metrics = compute_metrics_from_segments(bundle, schema=schema)
        assert metrics.m_stroke_disp_range.iloc[0] == 20


@pytest.mark.parametrize("explicit", [False, True])
def test_extracted_windows_and_metrics_cannot_cross_a_boundary(explicit):
    t = np.arange(100) * .01
    if not explicit:
        t[50:] += 1
    df = pd.DataFrame({"time_s": t, "disp": np.r_[np.zeros(50), np.full(50, 100.)], "vel": np.ones(100)})
    if explicit:
        df["segment_id"] = np.repeat(["a", "b"], 50)
    event = _events([t[60]])
    event["begin_time_s"] = t[40]
    bundle = extract_segments(df, event, meta=_meta(), schema=_schema())
    assert bundle["segments"].start_idx.iloc[0] == 50
    assert np.nanmin(bundle["data"]["disp"]) == 100
    result = compute_metrics_from_segments(bundle, schema=_schema())
    assert np.isnan(result.m_stroke_disp_range.iloc[0])


def _motion_config():
    return {"enabled": True, "sources": [{"id": "front", "selector": {"quantity": "disp", "unit": "mm"}}],
            "primary": {"displacement_lowpass_hz": 80, "displacement_lowpass_order": 4,
                        "velocity_sg_window_ms": 20, "acceleration_sg_window_ms": 40, "sg_polyorder": 3,
                        "velocity_lowpass_hz": 60, "velocity_lowpass_order": 4,
                        "acceleration_lowpass_hz": 30, "acceleration_lowpass_order": 4}}


@pytest.mark.parametrize("explicit", [False, True])
def test_motion_matches_processing_each_continuous_segment_independently(explicit):
    col = "front_dom_wheel [mm]"
    t = np.arange(300) * .002
    df = pd.DataFrame({"time_s": t, col: np.r_[np.sin(t[:150] * 20), 100 + np.sin(t[150:] * 20)]})
    if explicit:
        df["segment_id"] = np.repeat([1, 2], 150)
    else:
        df.loc[150:, "time_s"] += 1
    meta = {"signals": {col: {"quantity": "disp", "unit": "mm", "end": "front", "domain": "wheel"}}}
    combined, info = derive_motion_channels({"df": df, "meta": meta}, _motion_config(), sample_rate_hz=500)
    for start, end in [(0, 150), (150, 300)]:
        alone, _ = derive_motion_channels({"df": df.iloc[start:end], "meta": meta}, _motion_config(), sample_rate_hz=500)
        for generated in info["generated"]:
            name = generated["output_col"]
            np.testing.assert_allclose(combined[name].iloc[start:end], alone[name], atol=1e-10)


def test_short_motion_island_is_unavailable_without_borrowing_other_samples():
    col = "front_dom_wheel [mm]"
    df = pd.DataFrame({"time_s": np.arange(101) * .002, col: np.ones(101),
                       "segment_id": [0] + [1] * 100})
    meta = {"signals": {col: {"quantity": "disp", "unit": "mm", "domain": "wheel"}}}
    out, info = derive_motion_channels({"df": df, "meta": meta}, _motion_config(), sample_rate_hz=500)
    assert info["warnings"]
    for item in info["generated"]:
        assert np.isnan(out[item["output_col"]].iloc[0])
        assert np.isfinite(out[item["output_col"]].iloc[1:]).all()


def test_legacy_smoothing_and_derivatives_reset_at_gaps():
    col = "front_shock [mm]"
    df = pd.DataFrame({"time_s": np.r_[np.arange(100) * .01, 2 + np.arange(100) * .01],
                       col: np.r_[np.zeros(100), np.full(100, 100.)]})
    out = estimate_va(df, cols=[col], sample_rate_hz=100)
    np.testing.assert_allclose(out["front_shock_vel [mm/s]"], 0, atol=1e-8)
    configs = normalize_butterworth_smoothing_configs([{"cutoff_hz": 10, "order": 4}])
    smooth, report = apply_butterworth_smoothing(df, sample_rate_hz=100, configs=configs)
    np.testing.assert_allclose(smooth[report["generated"][0]["output_col"]], df[col], atol=1e-8)


def _trigger(kind):
    config = {"type": kind, "signal": "vel"}
    if kind == "local_extrema":
        config.update(kind="max", prominence=0)
    elif kind == "phased_threshold_crossing":
        config.update(phase_sequence="neg_pos", trigger_point="final_start",
                      bands={"neg": {"max": -1}, "pos": {"min": 1}, "zero": {"min": -1, "max": 1}})
    else:
        config.update(value=0, dir="rising", hysteresis=.1)
    return {"trigger": config, "inputs": {"vel": "vel"}}


@pytest.mark.parametrize("kind,scanner", [
    ("local_extrema", "_scan_local_extrema"),
    ("simple_threshold_crossing", "_scan_threshold_crossing"),
    ("phased_threshold_crossing", "_scan_phased_threshold_crossing"),
])
def test_trigger_searches_reuse_scans_per_signal_and_segment(monkeypatch, kind, scanner):
    df = pd.DataFrame({"time_s": np.r_[np.arange(20), 100 + np.arange(20)],
                       "vel": np.tile([-2., -2., 2., 2., -2.], 8)})
    context = detect._DetectionContext(df)
    original, calls = getattr(detect, scanner), []

    @wraps(original)
    def counted(*args, **kwargs):
        calls.append(len(args[0]))
        return original(*args, **kwargs)

    monkeypatch.setattr(detect, scanner, counted)
    wrapper = getattr(detect, {"local_extrema": "_trigger_local_extrema",
                              "simple_threshold_crossing": "_trigger_threshold_crossing",
                              "phased_threshold_crossing": "_trigger_phased_threshold_crossing"}[kind])
    ev = _trigger(kind)
    all_found = wrapper(df, 1, ev, context=context)
    assert all_found
    for base in [0., 5., 10., 100., 105.]:
        ev["trigger"]["search"] = {"min_delay_s": 0, "max_delay_s": 5}
        found = wrapper(df, 1, ev, base_t0_sec=base, context=context)
        assert all(base <= c["t0_time"] <= base + 5 for c in found)
    assert calls == [20, 20]


@pytest.mark.parametrize("kind", ["local_extrema", "simple_threshold_crossing", "phased_threshold_crossing"])
def test_trigger_state_and_secondary_searches_do_not_cross_gaps(kind):
    df = pd.DataFrame({"time_s": [0., 1., 2., 10., 11., 12.], "vel": [-2., -2., -2., 2., 3., 2.]})
    wrapper = getattr(detect, {"local_extrema": "_trigger_local_extrema",
                              "simple_threshold_crossing": "_trigger_threshold_crossing",
                              "phased_threshold_crossing": "_trigger_phased_threshold_crossing"}[kind])
    ev = _trigger(kind)
    found = wrapper(df, 1, ev)
    assert len(found) == (1 if kind == "local_extrema" else 0)
    ev["trigger"]["search"] = {"min_delay_s": 0, "max_delay_s": 20}
    assert wrapper(df, 1, ev, base_t0_sec=1.) == []


def test_metric_smoothing_and_interval_rejection_respect_segment_ids():
    df = pd.DataFrame({"time_s": np.arange(40) * .002, "disp": np.r_[np.zeros(20), np.full(20, 100.)],
                       "segment_id": np.repeat([0, 1], 20)})
    event = {"inputs": {"disp": "disp"}, "metrics": [{"id": "stroke", "type": "interval_stats",
             "signal": "disp", "start_trigger": "begin", "end_trigger": "finish",
             "ops": ["range"], "smooth_ms": 20}]}
    anchors = {"begin": {"t0_time": .04, "t0_index": 20}, "finish": {"t0_time": .06, "t0_index": 30}}
    result = detect._compute_metrics(df, .002, event, 30, 20, 40, trig_results=anchors)
    assert result["m_stroke_range"] == 0
    anchors["begin"] = {"t0_time": .02, "t0_index": 10}
    assert detect._compute_metrics(df, .002, event, 30, 20, 40, trig_results=anchors) == {}


def test_dropout_repair_does_not_borrow_context_across_a_gap():
    values = np.full(100, 1000.)
    values[48:52] = 0
    df = pd.DataFrame({"time_s": np.r_[np.arange(50) * .002, 1 + np.arange(50) * .002],
                       "raw": values})
    session = {"df": df, "meta": {"sample_rate_hz": 500, "channel_info": {
        "raw": {"quantity": "raw", "unit": "counts", "sensor": "fork"}},
        "declared_sensors": {"fork": {"type": "analog_pot", "calibration": {
            "sensor_full_count": 4095, "sensor_zero_count": 0}}}}}
    result = apply_raw_signal_dropout_filter(session, DEFAULT_RAW_SIGNAL_DROPOUT_FILTER)
    assert result.report["detected_samples"] >= 4
    assert result.report["repaired_samples"] == 0
    np.testing.assert_array_equal(session["df"].raw, values)


def test_explicit_segments_and_missing_samples_reset_continuity():
    df = pd.DataFrame({"time_s": [0, .002, .006, .008, .01], "segment_id": [0, 0, 0, 1, 1]})
    assert continuous_segments(df) == [(0, 2), (2, 3), (3, 5)]
    candidates = [{"t0_index": 1, "_continuous_segment": 0},
                  {"t0_index": 2, "_continuous_segment": 2}]
    assert len(detect._debounce_and_select(candidates, .002, 1, prefer_key="t0_index")) == 2


def test_conditions_and_secondary_delay_endpoints_are_precise():
    df = pd.DataFrame({"time_s": np.arange(10) * .1, "vel": np.ones(10)})
    ev = {"inputs": {"vel": "vel"}, "preconditions": [{"within_s": [0, 0], "all_of": [
        {"type": "peak", "signal": "vel", "kind": "max", "cmp": ">", "value": 0}]}]}
    assert detect._apply_conditions(df, .1, ev, 4, ev["inputs"], context=detect._DetectionContext(df))
    candidate = {"t0_time": .7, "t0_index": 7}
    assert detect._pick_secondary_candidate([candidate], .4, {"min_delay_s": .3, "max_delay_s": .3}) == candidate


def test_secondary_window_does_not_restart_threshold_hysteresis():
    df = pd.DataFrame({"time_s": np.arange(7, dtype=float), "vel": [-1, .5, .2, .6, .1, -1, .6]})
    ev = {"inputs": {"vel": "vel"}, "trigger": {
        "type": "simple_threshold_crossing", "signal": "vel", "dir": "rising",
        "value": .4, "hysteresis": .4, "search": {"min_delay_s": 0, "max_delay_s": 2}}}
    # Index 3 crosses .4 but the detector has not rearmed since index 1.
    assert detect._trigger_threshold_crossing(df, 1, ev, base_t0_sec=2.) == []


def test_phased_cache_distinguishes_changed_band_configuration():
    df = pd.DataFrame({"time_s": np.arange(4, dtype=float), "vel": [-2., -2., 2., 2.]})
    context = detect._DetectionContext(df)
    ev = _trigger("phased_threshold_crossing")
    assert len(detect._trigger_phased_threshold_crossing(df, 1, ev, context=context)) == 1
    ev["trigger"]["bands"]["pos"]["min"] = 3
    assert detect._trigger_phased_threshold_crossing(df, 1, ev, context=context) == []


@pytest.mark.parametrize("secondary", [False, True])
def test_custom_trigger_is_rejected_at_validation_parse_and_detection(secondary):
    schema = _schema()
    event = schema["events"][0]
    if secondary:
        event["secondary_triggers"] = [{"id": "custom", "type": "custom"}]
    else:
        event["trigger"]["type"] = "custom"
    assert any("custom" in issue for issue in basic_validate(schema))
    with pytest.raises(ValueError, match="custom.*not supported"):
        parse_event_schema(schema)
    with pytest.raises(ValueError, match="custom.*not supported"):
        detect.detect_events_from_schema(pd.DataFrame({"time_s": [0., 1.]}), schema)
