from __future__ import annotations

import pandas as pd

from bodaqs_analysis.detect import _resolve_inputs_from_event_inputs
from bodaqs_analysis.segment import RoleSpec, _pick_column_for_role


def test_event_detection_inputs_prefer_primary_analysis_channels() -> None:
    meta = {
        "signals": {
            "rear_suspension_disp_dom_suspension [mm]": {
                "end": "rear",
                "domain": "suspension",
                "quantity": "disp",
                "kind": "",
                "unit": "mm",
                "op_chain": [],
                "processing_role": "primary_analysis",
            },
            "rear_suspension_vel_dom_suspension [mm/s]": {
                "end": "rear",
                "domain": "suspension",
                "quantity": "vel",
                "kind": "",
                "unit": "mm/s",
                "op_chain": [],
                "processing_role": "primary_analysis",
            },
        }
    }

    inputs = _resolve_inputs_from_event_inputs(
        {
            "disp": {"end": "rear", "domain": "suspension", "quantity": "disp", "unit": "mm", "processing_role": "primary_analysis"},
            "vel": {"end": "rear", "domain": "suspension", "quantity": "vel", "unit": "mm/s", "processing_role": "primary_analysis"},
        },
        meta=meta,
        event_id="test",
    )

    assert inputs["disp"] == "rear_suspension_disp_dom_suspension [mm]"
    assert inputs["vel"] == "rear_suspension_vel_dom_suspension [mm/s]"


def test_segment_role_resolution_prefers_primary_analysis_unless_role_spec_overrides() -> None:
    signals = {
        "rear_wheel_vel_dom_wheel [mm/s]": {
            "sensor": "rear_wheel",
            "end": "rear",
            "domain": "wheel",
            "quantity": "vel",
            "kind": "",
            "unit": "mm/s",
            "op_chain": [],
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
        "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_5Hz_2Order_Savgol50ms3Poly_Butterworth_4Hz_2Order": {
            "sensor": "rear_wheel",
            "end": "rear",
            "domain": "wheel",
            "quantity": "vel",
            "kind": "",
            "unit": "mm/s",
            "op_chain": ["Butterworth_5Hz_2Order", "Savgol50ms3Poly", "Butterworth_4Hz_2Order"],
            "processing_role": "secondary_analysis",
            "motion_profile_id": "slow",
        },
    }

    primary = _pick_column_for_role(
        signals,
        "vel",
        {"quantity": "vel", "unit": "mm/s", "domain": "wheel"},
    )
    secondary = _pick_column_for_role(
        signals,
        "vel",
        {
            "quantity": "vel",
            "unit": "mm/s",
            "domain": "wheel",
            "processing_role": "secondary_analysis",
            "motion_profile_id": "slow",
        },
    )
    base = _pick_column_for_role(
        signals,
        "vel",
        {"quantity": "vel", "unit": "mm/s", "domain": "wheel", "op_chain": []},
    )

    assert (
        primary
        == "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order"
    )
    assert (
        secondary
        == "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_5Hz_2Order_Savgol50ms3Poly_Butterworth_4Hz_2Order"
    )
    assert base == "rear_wheel_vel_dom_wheel [mm/s]"


def test_role_spec_import_remains_available() -> None:
    assert RoleSpec(role="vel", prefer={"quantity": "vel"}).role == "vel"
    assert isinstance(pd.DataFrame(), pd.DataFrame)
