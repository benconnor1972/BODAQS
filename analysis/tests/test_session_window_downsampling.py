import numpy as np
import pandas as pd

from bodaqs_analysis.widgets.session_window_browser_widget import _downsample_indices_min_max


def test_min_max_downsampling_preserves_narrow_extrema():
    n = 1000
    values = np.zeros(n, dtype=float)
    values[503] = 100.0
    values[777] = -80.0
    df = pd.DataFrame({"signal": values})

    idx = _downsample_indices_min_max(df, value_cols=["signal"], max_points=20)

    assert len(idx) <= 20
    assert 503 in set(map(int, idx))
    assert 777 in set(map(int, idx))
