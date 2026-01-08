# tests/test_preprocess_session.py
import numpy as np
import pandas as pd

from bodaqs_analysis.pipeline import preprocess_session


def test_preprocess_session_invariants_basic():
    n = 200
    df = pd.DataFrame({
        "time_s": np.arange(n) * 0.01,
        "front_shock [mm]": np.linspace(10, 50, n),
        "rear_shock [mm]": np.linspace(5, 45, n),
    })
    session = {
        "session_id": "test_session_001",
        "source": {"type": "unit"},
        "meta": {},
        "qc": {},
        "df": df,
    }

    normalize_ranges = {
        "front_shock [mm]": 200.0,
        "rear_shock [mm]": 200.0,
    }

    out = preprocess_session(
        session,
        normalize_ranges=normalize_ranges,
        sample_rate_hz=100.0,
    )

    odf = out["df"]

    # time is numeric and monotonic
    t = pd.to_numeric(odf["time_s"], errors="coerce").to_numpy()
    assert np.isfinite(t).all()
    assert (np.diff(t) >= 0).all()

    # Base cols + canonical norm cols exist
    assert "front_shock_dom_suspension [mm]" in odf.columns
    assert "rear_shock_dom_suspension [mm]" in odf.columns
    assert "front_shock_norm [1]" in odf.columns
    assert "rear_shock_norm [1]" in odf.columns

    # Zeroed columns exist if zeroing is enabled by default
    assert "front_shock_dom_suspension [mm]_op_zeroed" in odf.columns
    assert "rear_shock_dom_suspension [mm]_op_zeroed" in odf.columns

    # QC transforms structure exists
    qc = out.get("qc", {})
    tr = qc.get("transforms", {})
    assert "zeroed" in tr and isinstance(tr["zeroed"].get("applied"), bool)
    assert "scaled" in tr and tr["scaled"].get("applied") is True
    assert "va" in tr and tr["va"].get("applied") is True
