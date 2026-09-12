import inspect
import numpy as np
import pandas as pd
import pytest

from tests.helpers import make_minimal_segment_bundle


def _call_compute_metrics_from_segments(func, bundle, schema, *, strict=True):
    """
    Call compute_metrics_from_segments without guessing its exact signature.
    Only pass kwargs that exist.
    """
    sig = inspect.signature(func)
    kwargs = {}
    if "schema" in sig.parameters:
        kwargs["schema"] = schema
    if "strict" in sig.parameters:
        kwargs["strict"] = strict
    return func(bundle, **kwargs)


def _build_schema_interval_stats_mean_min_max(
    *,
    schema_id="test_event",
    signal="vel",
    start_trigger="rebound_start",
    end_trigger="rebound_end",
    ops=("mean", "max", "min"),
    return_debug=True,
):
    """
    Minimal schema dict that matches your actual metric spec shape:

      metrics:
      - type: interval_stats
        signal: vel
        start_trigger: rebound_start
        end_trigger: rebound_end
        ops: [mean, max, min]
        return_debug: true
      ...

    We keep everything else minimal so compute_metrics_from_segments can run.
    """
    return {
        "version": "1.0",
        "events": [
            {
                "id": schema_id,
                "label": "Test event",
                # Keep sensors/trigger omitted unless your engine requires them
                "metrics": [
                    {
                        "type": "interval_stats",
                        "signal": signal,
                        "start_trigger": start_trigger,
                        "end_trigger": end_trigger,
                        "ops": list(ops),
                        "return_debug": bool(return_debug),

                        # Neutralise policy knobs for deterministic interval slicing tests
                        "min_delay_s": 0.0,
                        # omit polarity
                        # omit smooth_ms
                    }
                ],
            }
        ],
    }


def test_interval_stats_between_secondary_triggers_mean_min_max():
    """
    Harness-backed test:
      interval_stats over [rebound_start_time_s, rebound_end_time_s]

    Validates:
      - trigger resolution uses per-trigger columns
      - interval slicing works
      - ops mean/min/max return expected values on a known signal
    """
    # Grid and signal
    t = np.linspace(-1.0, 1.0, 401)  # dt=0.005
    y = t.copy()                      # monotonic ramp: min/mean/max are easy

    # Secondary triggers inside the grid
    a = -0.2
    b = 0.6

    bundle = make_minimal_segment_bundle(
        t_rel_s=t,
        y=y,
        trigger_time_s=0.0,
        events_overrides={
            "session_id": ["test_session_001"],  
            "rebound_start_time_s": [a],
            "rebound_end_time_s": [b],
            # If your resolver also supports *_idx, you can add them later
        },
    )

    # Import using your package layout
    from bodaqs_analysis.metrics import compute_metrics_from_segments

    schema = _build_schema_interval_stats_mean_min_max(schema_id="test_event")

    metrics_df = _call_compute_metrics_from_segments(
        compute_metrics_from_segments,
        bundle,
        schema,
        strict=True,
    )

    assert isinstance(metrics_df, pd.DataFrame)
    assert len(metrics_df) == 1
    assert "session_id" in metrics_df.columns
    assert metrics_df.loc[0, "session_id"] == "test_session_001"


    # Expected on y=t over [a,b]
    expected_mean = 0.5 * (a + b)
    expected_min = a
    expected_max = b

    # Column naming: your engine likely prefixes with m_ and may include signal/op.
    # Be tolerant: look for columns containing op names.
    cols = list(metrics_df.columns)

    def find_col(op: str) -> str:
        # Prefer "m_{op}" exact, then any metric col ending in or containing op.
        if f"m_{op}" in cols:
            return f"m_{op}"
        candidates = [
            c for c in cols
            if isinstance(c, str) and c.startswith("m_") and (op in c)
        ]
        return candidates[0] if candidates else ""

    c_mean = find_col("mean")
    c_min = find_col("min")
    c_max = find_col("max")

    if not (c_mean and c_min and c_max):
        pytest.fail(
            "Could not find expected interval_stats metric columns for mean/min/max. "
            f"Got columns: {cols}. "
            "If your naming is e.g. m_vel_mean, m_vel_min, m_vel_max, this test should pass. "
            "Otherwise, adjust the find_col() heuristic."
        )

    got_mean = float(metrics_df.loc[0, c_mean])
    got_min = float(metrics_df.loc[0, c_min])
    got_max = float(metrics_df.loc[0, c_max])

    assert np.isfinite(got_mean) and np.isfinite(got_min) and np.isfinite(got_max)
    dt = float(t[1] - t[0])

    assert got_mean == pytest.approx(expected_mean, abs=dt)
    assert got_min == pytest.approx(expected_min, abs=dt)
    assert got_max == pytest.approx(expected_max, abs=dt)



def test_interval_stats_missing_end_trigger_strict_raises():
    """
    Harness-backed test:
      strict mode should raise when schema references an end_trigger
      but the corresponding {trigger_id}_time_s column is missing.
    """
    t = np.linspace(-1.0, 1.0, 401)
    y = np.sin(2 * np.pi * t)

    bundle = make_minimal_segment_bundle(
        t_rel_s=t,
        y=y,
        trigger_time_s=0.0,
        events_overrides={
            "session_id": ["test_session_001"],  # NEW
            "rebound_start_time_s": [-0.2],
            # Missing on purpose: rebound_end_time_s
        },
    )

    from bodaqs_analysis.metrics import compute_metrics_from_segments

    schema = _build_schema_interval_stats_mean_min_max(schema_id="test_event")

    with pytest.raises((KeyError, ValueError)) as excinfo:
        _call_compute_metrics_from_segments(
            compute_metrics_from_segments,
            bundle,
            schema,
            strict=True,
        )

    msg = str(excinfo.value)
    assert ("rebound_end" in msg) or ("rebound_end_time_s" in msg), (
        "Exception did not mention the missing trigger. "
        f"Got message: {msg}"
    )
