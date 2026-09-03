# tests/test_step4_acceptance.py
import numpy as np
import pandas as pd

from typing import Dict, Any

from bodaqs_analysis import preprocess_session
from bodaqs_analysis.signalname import parse_signal_name


def make_df(n: int = 200, fs: float = 100.0) -> pd.DataFrame:
    t = np.arange(n, dtype=float) / fs

    # Smooth polynomial displacement in mm (known derivatives)
    # x(t) = 10 + 2t + 0.5 t^2
    x = 10.0 + 2.0 * t + 0.5 * t**2

    df = pd.DataFrame({
        "sample_id": np.arange(n, dtype=np.int64),
        "time_s": t,
        "front_shock [mm]": x,
        "front_shock_raw [counts]": (x * 10).astype(np.int64),
        "rear_shock [mm]": x * 0.5,
        "rear_shock_raw [counts]": (x * 5).astype(np.int64),
        "mark": np.zeros(n, dtype=np.int8),
    })
    return df


def make_session(df: pd.DataFrame) -> Dict[str, Any]:
    return {"session_id": "test_session_001", "source": {"type": "unit"}, "meta": {}, "qc": {}, "df": df}


def test_va_zero_norm_outputs_canonical_columns_and_registry():
    df_in = make_df()
    session = make_session(df_in)

    ranges = {
        "front_shock_dom_suspension [mm]": 200.0,
        "rear_shock_dom_suspension [mm]": 200.0,
    }

    result = preprocess_session(
        session,
        normalize_ranges=ranges,
        sample_rate_hz=100.0,
        zeroing_enabled=True,
        zero_window_s=0.2,
        clip_0_1=True,
    )
    out = result["session"]

    odf = out["df"]

    # Canonical physical displacement is retained and zeroed in place.
    assert "front_shock_dom_suspension [mm]" in odf.columns
    assert "rear_shock_dom_suspension [mm]" in odf.columns

    # The standard pipeline does not proliferate separate physical zeroed columns.
    assert "front_shock_dom_suspension [mm]_op_zeroed" not in odf.columns
    assert "rear_shock_dom_suspension [mm]_op_zeroed" not in odf.columns

    # Dimensionless normalised columns with correct unit
    assert "front_shock_dom_suspension [1]_op_zeroed_norm" in odf.columns
    assert "rear_shock_dom_suspension [1]_op_zeroed_norm" in odf.columns

    # VA columns are canonical with correct units
    assert "front_shock_vel_dom_suspension [mm/s]" in odf.columns
    assert "front_shock_acc_dom_suspension [mm/s^2]" in odf.columns

    # Parse sanity (won't raise)
    parse_signal_name("front_shock_dom_suspension [1]_op_zeroed_norm")
    parse_signal_name("front_shock_vel_dom_suspension [mm/s]")
    parse_signal_name("front_shock_acc_dom_suspension [mm/s^2]")



    # time_s should be finite and monotonic (non-decreasing)
    t = pd.to_numeric(odf["time_s"], errors="coerce").to_numpy()
    assert np.isfinite(t).all()
    assert (np.diff(t) >= 0).all()

    # Registry exists and contains core signals
    sigs = out["meta"]["signals"]
    assert isinstance(sigs, dict)
    assert sigs["front_shock_dom_suspension [mm]"]["kind"] == ""
    assert sigs["front_shock_dom_suspension [mm]"]["unit"] == "mm"
    assert sigs["front_shock_raw_dom_suspension [counts]"]["kind"] == "raw"
    assert sigs["front_shock_raw_dom_suspension [counts]"]["unit"] == "counts"
    assert sigs["front_shock_dom_suspension [1]_op_zeroed_norm"]["unit"] == "1"



def test_zeroing_applies_constant_offset_to_canonical_displacement():
    df_in = make_df()
    session = make_session(df_in)

    result = preprocess_session(
        session,
        normalize_ranges={"front_shock_dom_suspension [mm]": 200.0},
        sample_rate_hz=100.0,
        zeroing_enabled=True,
        zero_window_s=0.2,
        clip_0_1=True,
    )
    out = result["session"]

    odf = out["df"]

    base_in = df_in["front_shock [mm]"].to_numpy()
    base_out = odf["front_shock_dom_suspension [mm]"].to_numpy()

    # Zeroing changes the canonical displacement by one recorded constant offset.
    diff = base_in - base_out
    assert np.nanmax(diff) - np.nanmin(diff) < 1e-6
    recorded_offset = out["qc"]["transforms"]["zeroed"]["by_channel"][
        "front_shock_dom_suspension [mm]"
    ]["offset"]
    np.testing.assert_allclose(diff, recorded_offset, rtol=0, atol=1e-12)

    # Normalization uses the zeroed canonical displacement and is clipped [0,1].
    norm = odf["front_shock_dom_suspension [1]_op_zeroed_norm"].to_numpy()
    np.testing.assert_allclose(norm, np.clip(base_out / 200.0, 0.0, 1.0), rtol=0, atol=1e-12)
    assert np.nanmin(norm) >= -1e-3
    assert np.nanmax(norm) <= 1.0 + 1e-3
