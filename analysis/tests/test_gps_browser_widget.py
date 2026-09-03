import sys
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ANALYSIS_ROOT = _REPO_ROOT / "analysis"
if str(_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_ROOT))

from bodaqs_analysis.widgets.gps_browser_widget import _downsample_route_df, _split_run_coordinates
from bodaqs_analysis.widgets.gps_data import build_line_runs_from_segments


def test_downsample_route_df_keeps_preview_bounded() -> None:
    route_df = pd.DataFrame(
        {
            "time_s": range(100),
            "latitude_deg": [1.0] * 100,
            "longitude_deg": [2.0] * 100,
            "altitude_m": range(100),
        }
    )

    preview, original_count = _downsample_route_df(route_df, max_points=10)

    assert original_count == 100
    assert len(preview) == 10
    assert preview["time_s"].iloc[0] == 0
    assert preview["time_s"].iloc[-1] == 99


def test_contiguous_route_segments_become_one_polyline_run() -> None:
    segments = pd.DataFrame(
        [
            {
                "time_start_s": 0,
                "time_end_s": 1,
                "lat0_deg": 1.0,
                "lon0_deg": 2.0,
                "lat1_deg": 1.1,
                "lon1_deg": 2.1,
                "alt0_m": 10,
                "alt1_m": 11,
                "speed_mps": 1,
            },
            {
                "time_start_s": 1,
                "time_end_s": 2,
                "lat0_deg": 1.1,
                "lon0_deg": 2.1,
                "lat1_deg": 1.2,
                "lon1_deg": 2.2,
                "alt0_m": 11,
                "alt1_m": 12,
                "speed_mps": 1,
            },
        ]
    )

    runs, _ = build_line_runs_from_segments(segments, color_by_speed=False)

    assert len(runs) == 1
    assert runs[0].point_count == 3
    assert _split_run_coordinates(runs[0]) == [[(1.0, 2.0), (1.1, 2.1), (1.2, 2.2)]]
