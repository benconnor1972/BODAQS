import numpy as np
import pandas as pd
import pytest

from bodaqs_analysis.pipeline import preprocess_session

try:
    import scipy.signal as _sp_signal  # type: ignore
    _HAVE_SCIPY = True
except Exception:
    _HAVE_SCIPY = False


def _make_session(n: int = 400, fs: float = 100.0):
    t = np.arange(n, dtype=float) / fs
    front = 10.0 + 5.0 * np.sin(2.0 * np.pi * 1.2 * t)
    rear = 8.0 + 3.0 * np.sin(2.0 * np.pi * 1.4 * t + 0.2)

    df = pd.DataFrame(
        {
            "time_s": t,
            "front_shock [mm]": front,
            "rear_shock [mm]": rear,
        }
    )
    session = {
        "session_id": "butter_test",
        "source": {"type": "unit"},
        "meta": {},
        "qc": {},
        "df": df,
    }
    return session, df


@pytest.mark.skipif(not _HAVE_SCIPY, reason="requires scipy.signal")
def test_butterworth_preprocess_adds_append_only_columns():
    session, df_in = _make_session()

    result = preprocess_session(
        session,
        normalize_ranges={
            "front_shock_dom_suspension [mm]": 170.0,
            "rear_shock_dom_suspension [mm]": 150.0,
        },
        sample_rate_hz=100.0,
        zeroing_enabled=False,
        butterworth_smoothing=[{"cutoff_hz": 3.0, "order": 4}],
    )
    out = result["session"]

    odf = out["df"]
    bw_front = "front_shock_dom_suspension [mm]_op_Butterworth_3Hz_4Order"
    bw_rear = "rear_shock_dom_suspension [mm]_op_Butterworth_3Hz_4Order"

    assert bw_front in odf.columns
    assert bw_rear in odf.columns

    np.testing.assert_allclose(
        odf["front_shock_dom_suspension [mm]"].to_numpy(),
        df_in["front_shock [mm]"].to_numpy(),
        rtol=0.0,
        atol=1e-12,
    )

    sig = out["meta"]["signals"]
    assert sig[bw_front]["op_chain"][-1] == "Butterworth_3Hz_4Order"
    assert sig[bw_rear]["op_chain"][-1] == "Butterworth_3Hz_4Order"
    assert out["qc"]["transforms"]["filtered"]["applied"] is True


def test_butterworth_preprocess_empty_configs_is_noop():
    session, _ = _make_session()

    result = preprocess_session(
        session,
        normalize_ranges={
            "front_shock_dom_suspension [mm]": 170.0,
            "rear_shock_dom_suspension [mm]": 150.0,
        },
        sample_rate_hz=100.0,
        zeroing_enabled=False,
        butterworth_smoothing=[],
    )
    out = result["session"]
    odf = out["df"]
    assert not any("Butterworth_" in c for c in odf.columns)
    assert out["qc"]["transforms"]["filtered"]["applied"] is False


def test_butterworth_preprocess_invalid_cutoff_rejected():
    session, _ = _make_session()
    with pytest.raises(ValueError, match="must be below Nyquist"):
        preprocess_session(
            session,
            normalize_ranges={
                "front_shock_dom_suspension [mm]": 170.0,
                "rear_shock_dom_suspension [mm]": 150.0,
            },
            sample_rate_hz=100.0,
            zeroing_enabled=False,
            butterworth_smoothing=[{"cutoff_hz": 50.0, "order": 2}],
        )


@pytest.mark.skipif(not _HAVE_SCIPY, reason="requires scipy.signal")
def test_butterworth_preprocess_short_series_is_skipped_not_crash():
    session, _ = _make_session(n=6, fs=100.0)
    result = preprocess_session(
        session,
        normalize_ranges={
            "front_shock_dom_suspension [mm]": 170.0,
            "rear_shock_dom_suspension [mm]": 150.0,
        },
        sample_rate_hz=100.0,
        zeroing_enabled=False,
        butterworth_smoothing=[{"cutoff_hz": 3.0, "order": 4}],
    )
    out = result["session"]

    odf = out["df"]
    assert not any("Butterworth_" in c for c in odf.columns)
    warnings = out.get("qc", {}).get("warnings", [])
    assert any("Skipped" in str(w) and "Butterworth" in str(w) for w in warnings)


@pytest.mark.skipif(not _HAVE_SCIPY, reason="requires scipy.signal")
def test_butterworth_residual_series_optional_and_registry_ops():
    session, _ = _make_session()

    result_no_resid = preprocess_session(
        session,
        normalize_ranges={
            "front_shock_dom_suspension [mm]": 170.0,
            "rear_shock_dom_suspension [mm]": 150.0,
        },
        sample_rate_hz=100.0,
        zeroing_enabled=False,
        butterworth_smoothing=[{"cutoff_hz": 3.0, "order": 4}],
    )
    out_no_resid = result_no_resid["session"]
    assert not any(str(c).endswith("_resid") for c in out_no_resid["df"].columns)

    session2, _ = _make_session()
    result = preprocess_session(
        session2,
        normalize_ranges={
            "front_shock_dom_suspension [mm]": 170.0,
            "rear_shock_dom_suspension [mm]": 150.0,
        },
        sample_rate_hz=100.0,
        zeroing_enabled=False,
        butterworth_smoothing=[{"cutoff_hz": 3.0, "order": 4}],
        butterworth_generate_residuals=True,
    )
    out = result["session"]

    odf = out["df"]
    bw_front = "front_shock_dom_suspension [mm]_op_Butterworth_3Hz_4Order"
    resid_front = f"{bw_front}_resid"
    assert bw_front in odf.columns
    assert resid_front in odf.columns

    np.testing.assert_allclose(
        odf["front_shock_dom_suspension [mm]"].to_numpy(dtype=float)
        - odf[bw_front].to_numpy(dtype=float),
        odf[resid_front].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-9,
    )

    sig = out["meta"]["signals"]
    assert sig[bw_front]["op_chain"][-1] == "Butterworth_3Hz_4Order"
    assert "diff" in sig[resid_front]["op_chain"]
    assert not any(op.startswith("Butterworth_") for op in sig[resid_front]["op_chain"])

    filtered_params = out["qc"]["transforms"]["filtered"]["params"]
    assert filtered_params["generate_residuals"] is True
    assert filtered_params["n_generated_residuals"] >= 1
    assert resid_front in filtered_params["generated_residual_columns"]
