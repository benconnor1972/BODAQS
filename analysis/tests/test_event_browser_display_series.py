import numpy as np
import pandas as pd

from bodaqs_analysis.segment import WindowSpec
from bodaqs_analysis.widgets.event_browser import _extract_series_for_selected_roles


def test_event_browser_extracts_selected_cross_domain_display_series():
    session = {
        "df": pd.DataFrame(
            {
                "time_s": np.arange(5, dtype=float) * 0.002,
                "rear_wheel_vel_dom_wheel [mm/s]": [0.0, 10.0, -10.0, 0.0, 5.0],
                "rear_suspension_disp_dom_suspension [deg]": [100.0, 101.0, 102.0, 103.0, 104.0],
                "rear_suspension_raw_dom_suspension [counts]": [1800.0, 1810.0, 1820.0, 1830.0, 1840.0],
            }
        ),
        "meta": {
            "signals": {
                "rear_wheel_vel_dom_wheel [mm/s]": {
                    "end": "rear",
                    "domain": "wheel",
                    "quantity": "vel",
                    "unit": "mm/s",
                    "kind": "",
                    "op_chain": [],
                    "processing_role": "primary_analysis",
                },
                "rear_suspension_disp_dom_suspension [deg]": {
                    "end": "rear",
                    "domain": "suspension",
                    "quantity": "disp",
                    "unit": "deg",
                    "kind": "",
                    "op_chain": [],
                },
                "rear_suspension_raw_dom_suspension [counts]": {
                    "end": "rear",
                    "domain": "suspension",
                    "quantity": "raw",
                    "unit": "counts",
                    "kind": "raw",
                    "op_chain": [],
                },
            }
        },
    }
    event_row_df = pd.DataFrame(
        [
            {
                "session_id": "s1",
                "event_id": "compressions_all:rear:0",
                "schema_id": "compressions_all",
                "signal": "vel",
                "signal_col": "rear_wheel_vel_dom_wheel [mm/s]",
                "trigger_time_s": 0.004,
            }
        ]
    )
    selected_roles = [
        (
            "disp__rear__sel_0",
            "rear",
            ("disp", "deg", "", ""),
            "rear_suspension_disp_dom_suspension [deg]",
        ),
        (
            "raw__rear__sel_1",
            "rear",
            ("raw", "counts", "raw", ""),
            "rear_suspension_raw_dom_suspension [counts]",
        ),
    ]

    t_rel, series, _spec, primary_reason = _extract_series_for_selected_roles(
        session=session,
        event_row_df=event_row_df,
        event_type="compressions_all",
        schema={"events": [{"id": "compressions_all"}]},
        window=WindowSpec(mode="time", pre_s=0.002, post_s=0.002),
        selected_roles=selected_roles,
    )

    assert primary_reason is None
    assert t_rel is not None
    assert [name for name, _y, _semantic in series] == [
        "rear | disp [deg]",
        "rear | raw [counts] (raw)",
    ]
    np.testing.assert_allclose(series[0][1], [101.0, 102.0, 103.0])
    np.testing.assert_allclose(series[1][1], [1810.0, 1820.0, 1830.0])
