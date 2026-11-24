from __future__ import annotations

import numpy as np
import pandas as pd

from bodaqs_analysis.widgets.event_semantics import registry_signal_options_for_context
from bodaqs_analysis.widgets.session_window_data import derive_signal_options
from bodaqs_analysis.widgets.signal_histogram_scope import resolve_scope_signal_options


def _session() -> dict:
    df = pd.DataFrame(
        {
            "time_s": np.array([0.0, 1.0, 2.0]),
            "rear_wheel_dom_wheel [mm]": np.array([0.0, 10.0, 20.0]),
            "rear_wheel_dom_wheel [mm]_op_Butterworth_10Hz_2Order": np.array([0.0, 9.0, 18.0]),
            "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order": np.array(
                [0.0, 4.0, 8.0]
            ),
        }
    )
    signals = {
        "rear_wheel_dom_wheel [mm]": {
            "sensor": "rear_wheel",
            "end": "rear",
            "domain": "wheel",
            "quantity": "disp",
            "kind": "",
            "unit": "mm",
            "op_chain": [],
        },
        "rear_wheel_dom_wheel [mm]_op_Butterworth_10Hz_2Order": {
            "sensor": "rear_wheel",
            "end": "rear",
            "domain": "wheel",
            "quantity": "disp",
            "kind": "",
            "unit": "mm",
            "op_chain": ["Butterworth_10Hz_2Order"],
            "processing_role": "primary_analysis",
        },
        "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order": {
            "sensor": "rear_wheel",
            "end": "rear",
            "domain": "wheel",
            "quantity": "vel",
            "kind": "",
            "unit": "mm/s",
            "op_chain": ["Butterworth_10Hz_2Order", "Savgol20ms3Poly", "Butterworth_8Hz_2Order"],
            "processing_role": "primary_analysis",
        },
    }
    return {"df": df, "meta": {"signals": signals}}


def test_event_semantic_options_can_filter_to_primary_analysis() -> None:
    registry = _session()["meta"]["signals"]

    all_options = registry_signal_options_for_context(registry=registry, end="rear", primary_only=False)
    primary_options = registry_signal_options_for_context(registry=registry, end="rear", primary_only=True)

    assert len(all_options) == 3
    assert len(primary_options) == 2
    assert all(key[3] for _label, key in primary_options)
    assert {key[0] for _label, key in primary_options} == {"disp", "vel"}


def test_session_window_signal_options_can_filter_to_primary_analysis() -> None:
    session = _session()

    all_options = derive_signal_options(session=session, prev_detail=(), time_col="time_s", primary_only=False)
    primary_options = derive_signal_options(session=session, prev_detail=(), time_col="time_s", primary_only=True)

    assert "rear_wheel_dom_wheel [mm]" in all_options.numeric_cols_sorted
    assert "rear_wheel_dom_wheel [mm]" not in primary_options.numeric_cols_sorted
    assert primary_options.numeric_cols_sorted == [
        "rear_wheel_dom_wheel [mm]_op_Butterworth_10Hz_2Order",
        "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order",
    ]


def test_signal_histogram_scope_can_filter_to_primary_analysis() -> None:
    session = _session()

    resolved = resolve_scope_signal_options(
        scope_sessions=["s1"],
        get_session=lambda _sid: session,
        registry_policy="union",
        primary_only=True,
    )

    assert resolved.options == [
        "rear_wheel_dom_wheel [mm]_op_Butterworth_10Hz_2Order",
        "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order",
    ]
    assert resolved.by_session == {"s1": resolved.options}
