from __future__ import annotations

from bodaqs_analysis.dashboards.simple_suspension_metrics import (
    _resolve_displacement_sources_by_session,
    _resolve_velocity_source_by_session,
)


def test_displacement_sources_resolve_rear_wheel_semantics() -> None:
    def session_loader(session_key: str) -> dict:
        assert session_key == "s1"
        return {
            "meta": {
                "signals": {
                    "rear_shock_dom_suspension [mm]": {
                        "sensor": "rear_shock",
                        "end": "rear",
                        "domain": "suspension",
                        "quantity": "disp",
                        "unit": "mm",
                        "op_chain": [],
                    },
                    "rear_shock_dom_suspension [1]_op_norm": {
                        "sensor": "rear_shock",
                        "end": "rear",
                        "domain": "suspension",
                        "quantity": "disp_norm",
                        "unit": "1",
                        "op_chain": ["norm"],
                    },
                    "rear_wheel_dom_wheel [mm]": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp",
                        "unit": "mm",
                        "op_chain": [],
                    },
                    "rear_wheel_dom_wheel [1]_op_norm": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp_norm",
                        "unit": "1",
                        "op_chain": ["norm"],
                    },
                }
            }
        }

    norm_by_session, mm_by_session, missing_norm, missing_mm = _resolve_displacement_sources_by_session(
        session_loader=session_loader,
        session_keys=["s1"],
        selector={"end": "rear", "domain": "wheel"},
    )

    assert norm_by_session == {"s1": "rear_wheel_dom_wheel [1]_op_norm"}
    assert mm_by_session == {"s1": "rear_wheel_dom_wheel [mm]"}
    assert missing_norm == []
    assert missing_mm == []


def test_displacement_sources_prefer_primary_analysis_series() -> None:
    def session_loader(session_key: str) -> dict:
        assert session_key == "s1"
        return {
            "meta": {
                "signals": {
                    "rear_wheel_dom_wheel [mm]": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp",
                        "unit": "mm",
                        "op_chain": [],
                    },
                    "rear_wheel_dom_wheel [mm]_op_Butterworth_10Hz_2Order": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp",
                        "unit": "mm",
                        "op_chain": ["Butterworth_10Hz_2Order"],
                        "processing_role": "primary_analysis",
                    },
                    "rear_wheel_dom_wheel [1]_op_norm": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp_norm",
                        "unit": "1",
                        "op_chain": ["norm"],
                    },
                    "rear_wheel_dom_wheel [1]_op_Butterworth_10Hz_2Order_norm": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp_norm",
                        "unit": "1",
                        "op_chain": ["Butterworth_10Hz_2Order", "norm"],
                        "processing_role": "primary_analysis",
                        "source": ["rear_wheel_dom_wheel [mm]_op_Butterworth_10Hz_2Order"],
                    },
                }
            }
        }

    norm_by_session, mm_by_session, missing_norm, missing_mm = _resolve_displacement_sources_by_session(
        session_loader=session_loader,
        session_keys=["s1"],
        selector={"end": "rear", "domain": "wheel"},
    )

    assert norm_by_session == {"s1": "rear_wheel_dom_wheel [1]_op_Butterworth_10Hz_2Order_norm"}
    assert mm_by_session == {"s1": "rear_wheel_dom_wheel [mm]_op_Butterworth_10Hz_2Order"}
    assert missing_norm == []
    assert missing_mm == []


def test_displacement_sources_can_select_secondary_analysis_series() -> None:
    def session_loader(session_key: str) -> dict:
        assert session_key == "s1"
        return {
            "meta": {
                "signals": {
                    "rear_wheel_dom_wheel [mm]_op_Butterworth_10Hz_2Order": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp",
                        "unit": "mm",
                        "op_chain": ["Butterworth_10Hz_2Order"],
                        "processing_role": "primary_analysis",
                        "motion_profile_id": "primary",
                    },
                    "rear_wheel_dom_wheel [1]_op_Butterworth_10Hz_2Order_norm": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp_norm",
                        "unit": "1",
                        "op_chain": ["Butterworth_10Hz_2Order", "norm"],
                        "processing_role": "primary_analysis",
                        "motion_profile_id": "primary",
                    },
                    "rear_wheel_dom_wheel [mm]_op_Butterworth_5Hz_2Order": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp",
                        "unit": "mm",
                        "op_chain": ["Butterworth_5Hz_2Order"],
                        "processing_role": "secondary_analysis",
                        "motion_profile_id": "slow",
                    },
                    "rear_wheel_dom_wheel [1]_op_Butterworth_5Hz_2Order_norm": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp_norm",
                        "unit": "1",
                        "op_chain": ["Butterworth_5Hz_2Order", "norm"],
                        "processing_role": "secondary_analysis",
                        "motion_profile_id": "slow",
                    },
                }
            }
        }

    norm_by_session, mm_by_session, missing_norm, missing_mm = _resolve_displacement_sources_by_session(
        session_loader=session_loader,
        session_keys=["s1"],
        selector={
            "end": "rear",
            "domain": "wheel",
            "processing_role": "secondary_analysis",
            "motion_profile_id": "slow",
        },
    )

    assert norm_by_session == {"s1": "rear_wheel_dom_wheel [1]_op_Butterworth_5Hz_2Order_norm"}
    assert mm_by_session == {"s1": "rear_wheel_dom_wheel [mm]_op_Butterworth_5Hz_2Order"}
    assert missing_norm == []
    assert missing_mm == []


def test_velocity_sources_resolve_rear_wheel_semantics() -> None:
    def session_loader(session_key: str) -> dict:
        assert session_key == "s1"
        return {
            "meta": {
                "signals": {
                    "rear_shock_vel_dom_suspension [mm/s]": {
                        "sensor": "rear_shock",
                        "end": "rear",
                        "domain": "suspension",
                        "quantity": "vel",
                        "unit": "mm/s",
                    },
                    "rear_wheel_vel_dom_wheel [mm/s]": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "vel",
                        "unit": "mm/s",
                    },
                }
            }
        }

    source_by_session, missing = _resolve_velocity_source_by_session(
        session_loader=session_loader,
        session_keys=["s1"],
        selector={"end": "rear", "domain": "wheel"},
    )

    assert source_by_session == {"s1": "rear_wheel_vel_dom_wheel [mm/s]"}
    assert missing == []


def test_velocity_sources_prefer_primary_analysis_series() -> None:
    def session_loader(session_key: str) -> dict:
        assert session_key == "s1"
        return {
            "meta": {
                "signals": {
                    "rear_wheel_vel_dom_wheel [mm/s]": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "vel",
                        "unit": "mm/s",
                    },
                    "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "vel",
                        "unit": "mm/s",
                        "processing_role": "primary_analysis",
                        "op_chain": ["Butterworth_10Hz_2Order", "Savgol20ms3Poly", "Butterworth_8Hz_2Order"],
                    },
                }
            }
        }

    source_by_session, missing = _resolve_velocity_source_by_session(
        session_loader=session_loader,
        session_keys=["s1"],
        selector={"end": "rear", "domain": "wheel"},
    )

    assert source_by_session == {
        "s1": "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order"
    }
    assert missing == []


def test_velocity_sources_can_select_secondary_analysis_series() -> None:
    def session_loader(session_key: str) -> dict:
        assert session_key == "s1"
        return {
            "meta": {
                "signals": {
                    "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_10Hz_2Order_Savgol20ms3Poly_Butterworth_8Hz_2Order": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "vel",
                        "unit": "mm/s",
                        "processing_role": "primary_analysis",
                        "motion_profile_id": "primary",
                        "op_chain": ["Butterworth_10Hz_2Order", "Savgol20ms3Poly", "Butterworth_8Hz_2Order"],
                    },
                    "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_5Hz_2Order_Savgol50ms3Poly_Butterworth_4Hz_2Order": {
                        "sensor": "rear_wheel",
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "vel",
                        "unit": "mm/s",
                        "processing_role": "secondary_analysis",
                        "motion_profile_id": "slow",
                        "op_chain": ["Butterworth_5Hz_2Order", "Savgol50ms3Poly", "Butterworth_4Hz_2Order"],
                    },
                }
            }
        }

    source_by_session, missing = _resolve_velocity_source_by_session(
        session_loader=session_loader,
        session_keys=["s1"],
        selector={
            "end": "rear",
            "domain": "wheel",
            "processing_role": "secondary_analysis",
            "motion_profile_id": "slow",
        },
    )

    assert source_by_session == {
        "s1": "rear_wheel_vel_dom_wheel [mm/s]_op_Butterworth_5Hz_2Order_Savgol50ms3Poly_Butterworth_4Hz_2Order"
    }
    assert missing == []
