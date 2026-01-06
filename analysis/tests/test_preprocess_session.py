import numpy as np
import pandas as pd

from bodaqs_analysis import preprocess_session

def test_preprocess_session_invariants_basic():
    # Minimal synthetic session
    n = 200
    df = pd.DataFrame({
        "time_s": np.arange(n) * 0.01,
        "front_shock": np.linspace(10, 50, n),
        "rear_shock": np.linspace(5, 45, n),
    })
    session = {
        "session_id": "test_session_001",
        "source": {
            "kind": "unit_test",
            "path": "synthetic",
        },
        "df": df,
        "meta": {
            "sample_rate_hz": 100.0,
        },
        "qc": {},
    }
    normalize_ranges = {"front_shock": 100.0, "rear_shock": 100.0}

    out = preprocess_session(session, normalize_ranges=normalize_ranges, sample_rate_hz=100.0)

    assert "df" in out and isinstance(out["df"], pd.DataFrame)
    odf = out["df"]

    assert "time_s" in odf.columns
    # monotonic-ish time (allow equals if duplicates appear)
    t = pd.to_numeric(odf["time_s"], errors="coerce").to_numpy()
    assert np.isfinite(t).all()
    assert (np.diff(t) >= 0).all()

    # Norm columns exist
    for k in normalize_ranges.keys():
        assert k in odf.columns
        assert f"{k}_norm" in odf.columns

    # QC transforms structure exists
    qc = out.get("qc", {})
    tr = qc.get("transforms", {})
    assert "zeroed" in tr and isinstance(tr["zeroed"].get("applied"), bool)
    assert "scaled" in tr and tr["scaled"].get("applied") is True
