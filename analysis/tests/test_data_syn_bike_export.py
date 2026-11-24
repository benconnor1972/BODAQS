from __future__ import annotations

import pandas as pd

from bodaqs_analysis.exporters.data_syn_bike import (
    default_data_syn_bike_export_config,
    export_data_syn_bike_resolved,
    write_data_syn_bike_exports,
)


def _session() -> dict:
    df = pd.DataFrame(
        {
            "time_s": [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
            "front_wheel_raw_dom_wheel [counts]": [4090, 4080, 4070, 4060, 4050, 4040, 4030],
            "rear_suspension_raw_dom_suspension [counts]": [100, 110, 120, 130, 140, 150, 160],
            "gps_fit_position_latitude_dom_world [deg]": [-31.0] * 7,
            "gps_fit_position_longitude_dom_world [deg]": [116.0] * 7,
            "gps_fit_speed_dom_world [m/s]": [5.0] * 7,
            "active_mask_qc": [False, True, True, False, True, True, True],
        }
    )
    return {
        "session_id": "ride one",
        "df": df,
        "meta": {
            "signals": {
                "front_wheel_raw_dom_wheel [counts]": {
                    "end": "front",
                    "domain": "wheel",
                    "quantity": "raw",
                    "unit": "counts",
                    "kind": "raw",
                    "calibration": {
                        "installed_zero_count": 3766,
                        "sensor_full_count": 4,
                    },
                },
                "rear_suspension_raw_dom_suspension [counts]": {
                    "end": "rear",
                    "domain": "suspension",
                    "quantity": "raw",
                    "unit": "counts",
                    "kind": "raw",
                    "calibration": {
                        "installed_zero_count": 0,
                        "sensor_full_count": 3671,
                    },
                },
            }
        },
    }


def test_export_data_syn_bike_resolved_drops_inactive_and_inverts_independently():
    result = export_data_syn_bike_resolved(_session())

    assert result["format"] == "data_syn_bike"
    assert result["summary"]["n_exports"] == 1
    assert result["summary"]["front_raw_inverted"] is True
    assert result["summary"]["rear_raw_inverted"] is False
    assert result["summary"]["inactive_rows_dropped"] == 2

    export = result["exports"][0]
    df = export["dataframe"]
    assert list(df.columns) == ["Sample Time", "Front Raw", "Rear Raw", "Long", "Lat", "Speed"]
    assert len(df) == 5
    assert df["Sample Time"].tolist() == [1, 2, 4, 5, 6]
    assert df["Front Raw"].tolist() == [15, 25, 45, 55, 65]
    assert df["Rear Raw"].tolist() == [110, 120, 140, 150, 160]


def test_export_data_syn_bike_resolved_can_split_by_activity_regions():
    config = default_data_syn_bike_export_config(
        split_by_activity=True,
        sample_count_origin="export",
    )

    result = export_data_syn_bike_resolved(_session(), export_config=config)

    assert result["summary"]["n_exports"] == 2
    first, second = result["exports"]
    assert first["export_id"] == "activity_001"
    assert second["export_id"] == "activity_002"
    assert first["region"]["start_row"] == 1
    assert first["region"]["end_row_exclusive"] == 3
    assert second["region"]["start_row"] == 4
    assert second["region"]["end_row_exclusive"] == 7
    assert first["dataframe"]["Sample Time"].tolist() == [0, 1]
    assert second["dataframe"]["Sample Time"].tolist() == [0, 1, 2]


def test_write_data_syn_bike_exports_writes_headerless_files(tmp_path):
    config = default_data_syn_bike_export_config(
        split_by_activity=True,
        sample_count_origin="export",
    )
    result = export_data_syn_bike_resolved(_session(), export_config=config)

    written = write_data_syn_bike_exports(result, tmp_path)

    assert written["n_files"] == 2
    first_path = written["written"][0]["path"]
    text = first_path.read_text(encoding="utf-8").splitlines()
    assert text[0].startswith("0,15,110,116.0,-31.0,")
    assert "Sample Time" not in text[0]
