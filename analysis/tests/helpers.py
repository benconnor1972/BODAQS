import numpy as np
import pandas as pd


def make_minimal_segment_bundle(
    *,
    t_rel_s: np.ndarray,
    y: np.ndarray,
    trigger_time_s: float = 0.0,
    events_overrides: dict | None = None,
):
    """
    Construct a minimal, valid SegmentBundle for metrics testing.

    - Single segment
    - Single signal role ('vel')
    - Explicit trigger alignment
    """

    t_rel_s = np.asarray(t_rel_s, dtype=float)
    y = np.asarray(y, dtype=float)

    assert t_rel_s.ndim == 1
    assert y.ndim == 1
    assert len(t_rel_s) == len(y)

    # --- events_df ---
    events = {
        "event_id": ["e0"],
        "schema_id": ["test"],
        "schema_version": ["1.0"],
        "event_name": ["Test event"],
        "signal": ["vel"],
        "signal_col": ["vel"],
        "trigger_time_s": [trigger_time_s],
    }

    if events_overrides:
        events.update(events_overrides)

    events_df = pd.DataFrame(events)

    # --- segments_df ---
    segments_df = pd.DataFrame({
        "event_row": [0],
        "valid": [True],
        "trigger_time_s": [trigger_time_s],
    })

    # --- data ---
    data = {
        "vel": y.reshape(1, -1),
        "t_rel_s": t_rel_s.reshape(1, -1),
    }

    return {
        "events": events_df,
        "segments": segments_df,
        "data": data,
        "spec": {},
    }
