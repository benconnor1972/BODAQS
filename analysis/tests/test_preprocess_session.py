# tests/test_preprocess_session.py
import numpy as np
import pandas as pd
import pytest

import bodaqs_analysis.pipeline as pipeline
from bodaqs_analysis.pipeline import preprocess_session
from bodaqs_analysis.preprocess_profile import default_preprocess_config


def test_preprocess_session_invariants_basic():
    n = 200
    df = pd.DataFrame({
        "time_s": np.arange(n) * 0.01,
        "front_shock_dom_suspension [mm]": np.linspace(10, 50, n),
        "rear_shock_dom_suspension [mm]": np.linspace(5, 45, n),
    })
    session = {
        "session_id": "test_session_001",
        "source": {"type": "unit"},
        "meta": {},
        "qc": {},
        "df": df,
    }

    normalize_ranges = {
        "front_shock_dom_suspension [mm]": 200.0,
        "rear_shock_dom_suspension [mm]": 200.0,
    }

    result = preprocess_session(
        session,
        normalize_ranges=normalize_ranges,
        sample_rate_hz=100.0,
    )
    out = result["session"]

    odf = out["df"]

    # time is numeric and monotonic
    t = pd.to_numeric(odf["time_s"], errors="coerce").to_numpy()
    assert np.isfinite(t).all()
    assert (np.diff(t) >= 0).all()

    # Base cols + canonical norm cols exist
    assert "front_shock_dom_suspension [mm]" in odf.columns
    assert "rear_shock_dom_suspension [mm]" in odf.columns
    assert "front_shock_dom_suspension [1]_op_zeroed_norm" in odf.columns
    assert "rear_shock_dom_suspension [1]_op_zeroed_norm" in odf.columns

    # Standard preprocessing zeroes the canonical physical columns in place.
    assert "front_shock_dom_suspension [mm]_op_zeroed" not in odf.columns
    assert "rear_shock_dom_suspension [mm]_op_zeroed" not in odf.columns

    # QC transforms structure exists
    qc = out.get("qc", {})
    tr = qc.get("transforms", {})
    assert "zeroed" in tr and isinstance(tr["zeroed"].get("applied"), bool)
    assert set(tr["zeroed"]["by_channel"]) == set(normalize_ranges)
    assert "scaled" in tr and tr["scaled"].get("applied") is True
    assert "va" in tr and tr["va"].get("applied") is True


def _attitude_profile_session() -> dict:
    return {
        "session_id": "attitude_profile_test",
        "source": {},
        "meta": {},
        "qc": {},
        "df": pd.DataFrame(
            {
                "time_s": np.arange(20, dtype=float) * 0.01,
                "signal [mm]": np.arange(20, dtype=float),
            }
        ),
    }


def _attitude_profile_config(*, enabled: bool, required: bool = False) -> dict:
    config = default_preprocess_config()
    config["imu_attitude"] = {"enabled": enabled, "required": required}
    return config


def test_profile_enabled_imu_attitude_stage_persists_status(monkeypatch):
    def fake_build_attitude_streams(session, *, config=None):
        session.setdefault("stream_dfs", {})["attitude_imu0"] = pd.DataFrame({"time_s": [0.0]})
        session.setdefault("meta", {}).setdefault("secondary_streams", {})["attitude_imu0"] = {
            "schema": pipeline.ATTITUDE_STREAM_SCHEMA,
        }
        session.setdefault("qc", {}).setdefault("attitude", {})["imu0"] = {"status": "gravity_only"}
        return session

    monkeypatch.setattr(pipeline, "build_attitude_streams", fake_build_attitude_streams)
    result = pipeline.preprocess_resolved(
        _attitude_profile_session(),
        preprocess_config=_attitude_profile_config(enabled=True),
        normalize_ranges={},
        include_events=False,
        include_metrics=False,
        strict=False,
    )

    status = result["session"]["meta"]["attitude_preprocessing"]
    assert status["status"] == "completed"
    assert status["output_streams"] == ["attitude_imu0"]
    assert "imu_attitude" in result["timings"]["stages_s"]


def test_required_imu_attitude_stage_fails_when_no_stream_is_available(monkeypatch):
    monkeypatch.setattr(pipeline, "build_attitude_streams", lambda session, *, config=None: session)

    with pytest.raises(ValueError, match="IMU attitude preprocessing was required"):
        pipeline.preprocess_resolved(
            _attitude_profile_session(),
            preprocess_config=_attitude_profile_config(enabled=True, required=True),
            normalize_ranges={},
            include_events=False,
            include_metrics=False,
            strict=False,
        )
