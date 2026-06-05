import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bodaqs_analysis.artifacts import (
    ArtifactStore,
    copy_session_aux_sources,
    load_session_artifacts,
    save_session_artifacts,
)
from bodaqs_analysis.io_logger import parse_logger_log_metadata, prepare_logger_dataframe
from bodaqs_analysis.io_fit import (
    find_overlapping_fit_candidates,
    find_overlapping_fit_files,
    load_fit_bindings,
    parse_fit_bindings,
    inspect_fit_stream,
    parse_fit_stream,
    select_fit_candidate,
    upsert_fit_binding,
    upsert_fit_binding_records,
)
from bodaqs_analysis.model import validate_session
from bodaqs_analysis.pipeline import (
    build_session_from_dataframe,
    enrich_session_with_fit,
    load_session,
    preprocess_resolved,
    preprocess_session,
)
from bodaqs_analysis.signal_registry import build_signals_registry
from bodaqs_analysis.timebase import register_stream_metadata
from bodaqs_analysis.ui.fit_bindings_editor import build_fit_candidate_summary
from bodaqs_analysis.ui.preprocess_file_selector import PreprocessLogSelector
from bodaqs_analysis.ui.preprocess_controls import PreprocessControls, PreprocessDefaults


def _write_csv_and_sidecar(tmp_path):
    csv_path = tmp_path / "session.csv"
    csv_path.write_text(
        "\n".join(
            [
                "time_s,front_shock_dom_suspension [mm],rear_shock_dom_suspension [mm],mark",
                "0.00,10.0,20.0,0",
                "0.03,11.0,21.0,1",
                "0.06,12.0,22.0,0",
            ]
        ),
        encoding="utf-8",
    )

    sidecar = {
        "contract": {
            "name": "mtb_logger_timeseries",
            "version": "0.1.0",
        },
        "session": {
            "session_id": "logger_sidecar_session",
            "started_at_local": "2026-02-19T08:35:11+08:00",
            "timezone": "Australia/Perth",
            "notes": "test sidecar",
        },
        "streams": {
            "primary": {
                "type": "uniform",
                "time_col": "time_s",
                "time_unit": "s",
                "sample_rate_hz": 40.0,
                "jitter_frac": 0.0,
            }
        },
        "columns": {
            "time_s": {
                "class": "time",
                "dtype": "float64",
                "stream": "primary",
                "unit": "s",
            },
            "front_shock_dom_suspension [mm]": {
                "class": "signal",
                "dtype": "float64",
                "stream": "primary",
                "sensor": "front_shock",
                "end": "front",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
                "source_columns": [],
            },
            "rear_shock_dom_suspension [mm]": {
                "class": "signal",
                "dtype": "float64",
                "stream": "primary",
                "sensor": "rear_shock",
                "end": "rear",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
                "source_columns": [],
            },
            "mark": {
                "class": "event_flag",
                "dtype": "bool",
                "stream": "primary",
            },
        },
        "provenance": {
            "logger_family": "BODAQS",
            "firmware_version": "1.2.3",
        },
    }
    sidecar_path = tmp_path / "session.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return csv_path, sidecar_path


def test_log_metadata_started_at_utc_takes_precedence_for_absolute_anchor():
    df = pd.DataFrame({"time_s": [0.0, 1.0], "front_shock_dom_suspension [mm]": [10.0, 11.0]})
    session = build_session_from_dataframe(
        df,
        session_id="utc_anchor",
        log_metadata={
            "contract": {"name": "mtb_logger_timeseries", "version": "0.2.0"},
            "session": {
                "session_id": "utc_anchor",
                "started_at_utc": "2026-02-19T00:35:11Z",
                "started_at_local": "2026-02-19T08:35:11",
                "timezone": "AWST-8",
            },
            "streams": {"primary": {"type": "uniform", "time_col": "time_s"}},
            "columns": {
                "time_s": {"class": "time", "stream": "primary", "unit": "s"},
                "front_shock_dom_suspension [mm]": {"class": "signal", "stream": "primary", "unit": "mm"},
            },
        },
    )

    assert session["meta"]["t0_datetime"] == "2026-02-19T00:35:11Z"
    assert session["source"]["created_utc"] == "2026-02-19T00:35:11Z"
    assert session["source"]["created_local"] == "2026-02-19T08:35:11"


def test_fit_import_failure_policy_warn_continues_without_fit_stream():
    session = {
        "session_id": "fit_failure_policy",
        "df": pd.DataFrame({"time_s": [0.0, 1.0], "front_shock_dom_suspension [mm]": [10.0, 11.0]}),
        "meta": {"t0_datetime": "2026-02-19T00:35:11Z", "channel_info": {}},
        "source": {},
        "qc": {"warnings": []},
    }

    out = enrich_session_with_fit(
        session,
        fit_import={
            "enabled": True,
            "failure_policy": "warn",
            "ambiguity_policy": "largest_overlap",
        },
        fit_candidates=[
            {
                "filename": "bad.fit",
                "fit_input": b"not a fit file",
                "start_datetime": "2026-02-19T00:35:10Z",
                "end_datetime": "2026-02-19T00:35:20Z",
            }
        ],
    )

    assert out is session
    assert "fit_import_failed" in out["qc"]["warnings"]
    assert out["qc"]["fit_import"]["status"] == "failed"
    assert "stream_dfs" not in out


def _write_csv_only(tmp_path, name: str = "session.csv"):
    csv_path = tmp_path / name
    csv_path.write_text(
        "\n".join(
            [
                "time_s,front_shock_dom_suspension [mm],rear_shock_dom_suspension [mm],mark",
                "0.00,10.0,20.0,0",
                "0.03,11.0,21.0,1",
                "0.06,12.0,22.0,0",
            ]
        ),
        encoding="utf-8",
    )
    return csv_path


def _write_generic_sidecar(
    tmp_path,
    *,
    name: str = "generic_sidecar.json",
    header: bool = True,
    include_optional_shock: bool = True,
):
    columns = {
        "timestamp_ms": {
            "csv_ref": {"by": "header", "header": "timestamp_ms"} if header else {"by": "index", "index": 0},
            "class": "time",
            "dtype": "uint64",
            "stream": "primary",
            "unit": "ms",
        },
        "fork_travel_mm": {
            "csv_ref": {"by": "header", "header": "Fork [mm]"} if header else {"by": "index", "index": 1},
            "class": "signal",
            "dtype": "float64",
            "stream": "primary",
            "sensor": "fork",
            "end": "front",
            "quantity": "disp",
            "domain": "suspension",
            "unit": "mm",
        },
    }
    if include_optional_shock:
        columns["shock_travel_mm"] = {
            "csv_ref": {"by": "header", "header": "Shock [mm]"} if header else {"by": "index", "index": 2},
            "class": "signal",
            "dtype": "float64",
            "stream": "primary",
            "sensor": "shock",
            "end": "rear",
            "quantity": "disp",
            "domain": "suspension",
            "unit": "mm",
            "required": False,
        }

    sidecar = {
        "contract": {
            "name": "mtb_logger_timeseries",
            "version": "0.2.0",
            "sidecar_kind": "generic",
        },
        "data_file": {
            "delimiter": ",",
            "header": header,
        },
        "streams": {
            "primary": {
                "type": "uniform",
                "time_column": "timestamp_ms",
                "time_encoding": "epoch_ms",
                "time_unit": "ms",
                "sample_rate_hz": 1000.0,
            }
        },
        "columns": columns,
    }
    sidecar_path = tmp_path / name
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return sidecar_path


def _write_syn_bike_raw_sidecar_with_linear_calibration(
    tmp_path,
    *,
    name: str = "syn_bike_raw_sidecar.json",
):
    sidecar = {
        "contract": {
            "name": "mtb_logger_timeseries",
            "version": "0.2.0",
            "sidecar_kind": "generic",
        },
        "data_file": {
            "delimiter": ",",
            "header": False,
        },
        "streams": {
            "primary": {
                "type": "uniform",
                "time_column": "sample_id",
                "time_encoding": "sample_index",
                "time_unit": "sample",
                "sample_rate_hz": 100.0,
            }
        },
        "sensors": {
            "front_shock": {
                "name": "front_shock",
                "type": "analog_pot",
                "domain": "wheel",
                "raw_unit": "counts",
                "calibration": {
                    "type": "linear",
                    "input_unit": "counts",
                    "output_unit": "mm",
                    "installed_zero_count": 3500,
                    "sensor_zero_count": 4095,
                    "sensor_full_count": 0,
                    "sensor_full_travel": 170.0,
                    "invert": True,
                },
            },
            "rear_shock": {
                "name": "rear_shock",
                "type": "analog_pot",
                "domain": "suspension",
                "raw_unit": "counts",
                "calibration": {
                    "type": "linear",
                    "input_unit": "counts",
                    "output_unit": "mm",
                    "installed_zero_count": 3000,
                    "sensor_zero_count": 4095,
                    "sensor_full_count": 0,
                    "sensor_full_travel": 55.0,
                    "invert": True,
                },
            },
        },
        "columns": {
            "sample_id": {
                "csv_ref": {"by": "index", "index": 0},
                "class": "time",
                "dtype": "uint32",
                "stream": "primary",
                "unit": "sample",
            },
            "front_raw": {
                "csv_ref": {"by": "index", "index": 1},
                "class": "signal",
                "dtype": "uint32",
                "stream": "primary",
                "sensor": "front_shock",
                "end": "front",
                "quantity": "raw",
                "domain": "wheel",
                "unit": "counts",
            },
            "rear_raw": {
                "csv_ref": {"by": "index", "index": 2},
                "class": "signal",
                "dtype": "uint32",
                "stream": "primary",
                "sensor": "rear_shock",
                "end": "rear",
                "quantity": "raw",
                "domain": "suspension",
                "unit": "counts",
            },
            "lat": {
                "csv_ref": {"by": "index", "index": 3},
                "class": "signal",
                "dtype": "float64",
                "stream": "primary",
                "sensor": "gps_position",
                "quantity": "latitude",
                "domain": "world",
                "unit": "deg",
                "required": False,
            },
            "long": {
                "csv_ref": {"by": "index", "index": 4},
                "class": "signal",
                "dtype": "float64",
                "stream": "primary",
                "sensor": "gps_position",
                "quantity": "longitude",
                "domain": "world",
                "unit": "deg",
                "required": False,
            },
            "speed": {
                "csv_ref": {"by": "index", "index": 5},
                "class": "signal",
                "dtype": "float64",
                "stream": "primary",
                "sensor": "gps",
                "quantity": "speed",
                "domain": "world",
                "unit": "m/s",
                "required": False,
            },
        },
    }
    sidecar_path = tmp_path / name
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return sidecar_path


def test_load_session_auto_uses_same_stem_sidecar(tmp_path):
    csv_path, sidecar_path = _write_csv_and_sidecar(tmp_path)

    session = load_session(str(csv_path))

    assert session["source"]["log_metadata_path"] == str(sidecar_path)
    assert session["source"]["sidecar_path"] == str(sidecar_path)
    assert session["source"]["created_local"] == "2026-02-19T08:35:11+08:00"
    assert session["source"]["timezone"] == "Australia/Perth"
    assert session["meta"]["t0_datetime"] == "2026-02-19T08:35:11+08:00"
    assert session["meta"]["notes"] == "test sidecar"
    assert session["meta"]["sample_rate_hz"] == 40.0
    assert session["meta"]["channel_info"]["rear_shock_dom_suspension [mm]"]["sensor"] == "rear_shock"
    assert session["meta"]["channel_info"]["rear_shock_dom_suspension [mm]"]["end"] == "rear"
    assert session["meta"]["channel_info"]["rear_shock_dom_suspension [mm]"]["role"] == "disp"
    assert session["meta"]["device"]["firmware_version"] == "1.2.3"


def test_load_session_preserves_sensor_calibration_for_raw_signal_metadata(tmp_path):
    csv_path = tmp_path / "session.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timestamp_ms,front_raw [counts]",
                "1000,3700",
                "1001,3690",
            ]
        ),
        encoding="utf-8",
    )
    log_metadata = {
        "contract": {"name": "mtb_logger_timeseries", "version": "0.2.0"},
        "data_file": {"delimiter": ",", "header": True},
        "streams": {
            "primary": {
                "type": "uniform",
                "time_column": "timestamp_ms",
                "time_encoding": "epoch_ms",
                "time_unit": "ms",
                "sample_rate_hz": 500.0,
            }
        },
        "sensors": {
            "front linear pot": {
                "name": "front linear pot",
                "type": "analog_pot",
                "domain": "wheel",
                "raw_unit": "counts",
                "calibration": {
                    "type": "linear",
                    "input_unit": "counts",
                    "output_unit": "mm",
                    "installed_zero_count": 3766,
                    "sensor_full_count": 4,
                    "sensor_full_travel": 203.0,
                    "invert": True,
                },
            }
        },
        "columns": {
            "timestamp_ms": {
                "csv_ref": {"by": "header", "header": "timestamp_ms"},
                "class": "time",
                "dtype": "uint64",
                "stream": "primary",
                "unit": "ms",
            },
            "front_wheel_raw": {
                "csv_ref": {"by": "header", "header": "front_raw [counts]"},
                "class": "signal",
                "dtype": "uint32",
                "stream": "primary",
                "sensor": "front linear pot",
                "end": "front",
                "quantity": "raw",
                "domain": "wheel",
                "unit": "counts",
            },
        },
    }
    (tmp_path / "session.json").write_text(json.dumps(log_metadata, indent=2), encoding="utf-8")

    session = load_session(str(csv_path))
    raw_col = "front_wheel_raw_dom_wheel [counts]"
    channel_info = session["meta"]["channel_info"][raw_col]

    assert session["meta"]["declared_sensors"]["front linear pot"]["calibration"]["invert"] is True
    assert channel_info["calibration_ref"] == "front linear pot"
    assert channel_info["calibration"]["installed_zero_count"] == 3766
    assert channel_info["calibration"]["sensor_full_count"] == 4

    build_signals_registry(session)
    signal_info = session["meta"]["signals"][raw_col]
    assert signal_info["calibration"]["installed_zero_count"] == 3766
    assert signal_info["calibration"]["sensor_full_count"] == 4


def test_parse_logger_log_metadata_accepts_mapping_text_and_bytes(tmp_path):
    _, sidecar_path = _write_csv_and_sidecar(tmp_path)
    sidecar_text = sidecar_path.read_text(encoding="utf-8")
    sidecar_obj = json.loads(sidecar_text)

    parsed_from_mapping = parse_logger_log_metadata(sidecar_obj)
    parsed_from_text = parse_logger_log_metadata(sidecar_text)
    parsed_from_bytes = parse_logger_log_metadata(sidecar_text.encode("utf-8"))

    assert parsed_from_mapping["contract"]["name"] == "mtb_logger_timeseries"
    assert parsed_from_text["session"]["timezone"] == "Australia/Perth"
    assert parsed_from_bytes["streams"]["primary"]["sample_rate_hz"] == 40.0


def test_build_session_from_dataframe_applies_log_metadata_without_paths(tmp_path):
    csv_path, sidecar_path = _write_csv_and_sidecar(tmp_path)
    raw_df = pd.read_csv(csv_path)
    prepared_df, log_metadata = prepare_logger_dataframe(
        raw_df,
        log_metadata=sidecar_path,
    )

    session = build_session_from_dataframe(
        prepared_df,
        source_name="uploaded-session.csv",
        timezone="Australia/Perth",
        log_metadata=log_metadata,
    )

    assert session["session_id"] == "uploaded-session"
    assert session["source"]["filename"] == "uploaded-session.csv"
    assert "path" not in session["source"]
    assert "log_metadata_path" not in session["source"]
    assert session["source"]["created_local"] == "2026-02-19T08:35:11+08:00"
    assert session["meta"]["sample_rate_hz"] == 40.0
    assert session["meta"]["channel_info"]["rear_shock_dom_suspension [mm]"]["sensor"] == "rear_shock"


def test_build_session_from_dataframe_uses_source_name_for_time_anchor(tmp_path):
    csv_path = _write_csv_only(tmp_path, name="2026-02-19_08-35-11.csv")
    raw_df = pd.read_csv(csv_path)
    prepared_df, _ = prepare_logger_dataframe(raw_df)

    session = build_session_from_dataframe(
        prepared_df,
        source_name="2026-02-19_08-35-11.csv",
        timezone="Australia/Perth",
    )

    assert session["session_id"] == "2026-02-19_08-35-11"
    assert session["source"]["filename"] == "2026-02-19_08-35-11.csv"
    assert session["source"]["created_local"] == "2026-02-19T08:35:11+08:00"
    assert session["meta"]["t0_datetime"] == "2026-02-19T08:35:11+08:00"
    assert "path" not in session["source"]


def test_session_sidecar_requires_every_physical_csv_column(tmp_path):
    csv_path = tmp_path / "session.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timestamp_ms,Fork [mm],extra_voltage",
                "1000,10.0,3.7",
                "1001,11.0,3.8",
            ]
        ),
        encoding="utf-8",
    )

    sidecar = {
        "contract": {
            "name": "mtb_logger_timeseries",
            "version": "0.2.0",
            "sidecar_kind": "session",
        },
        "data_file": {"delimiter": ",", "header": True},
        "streams": {
            "primary": {
                "type": "uniform",
                "time_column": "timestamp_ms",
                "time_encoding": "epoch_ms",
                "time_unit": "ms",
            }
        },
        "columns": {
            "timestamp_ms": {
                "csv_ref": {"by": "header", "header": "timestamp_ms"},
                "class": "time",
                "dtype": "uint64",
                "stream": "primary",
                "unit": "ms",
            },
            "fork_travel_mm": {
                "csv_ref": {"by": "header", "header": "Fork [mm]"},
                "class": "signal",
                "dtype": "float64",
                "stream": "primary",
                "sensor": "fork",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
            },
        },
    }
    (tmp_path / "session.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="does not describe every CSV column"):
        load_session(str(csv_path))


def test_load_session_uses_single_generic_sidecar_permissively(tmp_path):
    csv_path = tmp_path / "session.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timestamp_ms,Fork [mm],rear_shock_dom_suspension [mm]",
                "1000,10.0,20.0",
                "1001,11.0,21.0",
                "1002,12.0,22.0",
            ]
        ),
        encoding="utf-8",
    )
    generic_sidecar = _write_generic_sidecar(tmp_path)

    session = load_session(str(csv_path), generic_log_metadata_paths=[generic_sidecar])

    assert session["source"]["log_metadata_path"] == str(generic_sidecar)
    assert session["source"]["sidecar_path"] == str(generic_sidecar)
    assert session["source"]["log_metadata_kind"] == "generic"
    assert session["source"]["sidecar_kind"] == "generic"
    assert "front_suspension_disp_dom_suspension [mm]" in session["df"].columns
    assert "rear_shock_dom_suspension [mm]" not in session["df"].columns
    assert "sidecar_optional_column_missing:shock_travel_mm" in session["qc"]["warnings"]
    assert "sidecar_unknown_csv_column_skipped:rear_shock_dom_suspension [mm]" in session["qc"]["warnings"]
    assert session["meta"]["channel_info"]["front_suspension_disp_dom_suspension [mm]"]["sensor"] == "fork"
    assert session["meta"]["channel_info"]["front_suspension_disp_dom_suspension [mm]"]["end"] == "front"
    assert session["meta"]["channel_info"]["front_suspension_disp_dom_suspension [mm]"]["role"] == "disp"


def test_load_session_logs_sidecar_selection_and_column_binding(tmp_path, caplog):
    csv_path = tmp_path / "session.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timestamp_ms,Fork [mm],extra_voltage",
                "1000,10.0,3.7",
                "1001,11.0,3.8",
                "1002,12.0,3.9",
            ]
        ),
        encoding="utf-8",
    )
    generic_sidecar = _write_generic_sidecar(
        tmp_path,
        include_optional_shock=False,
    )

    caplog.set_level(logging.INFO, logger="bodaqs_analysis.io_logger")

    load_session(str(csv_path), generic_log_metadata_paths=[generic_sidecar])

    messages = [record.getMessage() for record in caplog.records]
    assert any("Logger same-stem log metadata not found" in msg for msg in messages)
    assert any("Logger generic log metadata found" in msg for msg in messages)
    assert any("csv_column='timestamp_ms'" in msg and "matched log metadata" in msg for msg in messages)
    assert any("csv_column='Fork [mm]'" in msg and "matched log metadata" in msg for msg in messages)
    assert any("csv_column='extra_voltage'" in msg and "no log metadata match" in msg for msg in messages)


def test_multiple_generic_sidecars_require_explicit_selection(tmp_path):
    csv_path = _write_csv_only(tmp_path)
    first = _write_generic_sidecar(tmp_path, name="generic_a.json")
    second = _write_generic_sidecar(tmp_path, name="generic_b.json")

    with pytest.raises(ValueError, match="Multiple generic log metadata"):
        load_session(str(csv_path), generic_log_metadata_paths=[first, second])


def test_configured_missing_generic_sidecar_does_not_fall_back_to_header_parsing(tmp_path):
    csv_path = _write_csv_only(tmp_path)
    missing_sidecar = tmp_path / "missing_generic_sidecar.json"

    with pytest.raises(FileNotFoundError, match="No usable generic log metadata"):
        load_session(str(csv_path), generic_log_metadata_paths=[missing_sidecar])


def test_empty_generic_log_metadata_paths_falls_back_to_header_parsing(tmp_path):
    csv_path = _write_csv_only(tmp_path)

    session = load_session(str(csv_path), generic_log_metadata_paths=[])

    assert session["source"].get("log_metadata_path") is None
    assert "time_s" in session["df"].columns


def test_generic_sidecar_supports_headerless_csv_by_column_index(tmp_path):
    csv_path = tmp_path / "session.csv"
    csv_path.write_text(
        "\n".join(
            [
                "1000,10.0,999",
                "1001,11.0,998",
                "1002,12.0,997",
            ]
        ),
        encoding="utf-8",
    )
    generic_sidecar = _write_generic_sidecar(
        tmp_path,
        header=False,
        include_optional_shock=False,
    )

    session = load_session(str(csv_path), generic_log_metadata_paths=[generic_sidecar])

    assert "front_suspension_disp_dom_suspension [mm]" in session["df"].columns
    assert 2 not in session["df"].columns
    assert "sidecar_unknown_csv_column_skipped:2" in session["qc"]["warnings"]
    assert session["qc"]["parse"]["log_metadata_column_bindings"]["fork_travel_mm"]["csv_ref"] == {
        "by": "index",
        "index": 1,
    }
    assert session["qc"]["parse"]["sidecar_column_bindings"]["fork_travel_mm"]["csv_ref"] == {
        "by": "index",
        "index": 1,
    }


def test_repo_syn_bike_generic_log_metadata_loads_headerless_syn_bike_csv(tmp_path):
    csv_path = tmp_path / "session.csv"
    csv_path.write_text(
        "\n".join(
            [
                "0,3700,1800,,,",
                "1,3698,1802,,,",
                "2,3695,1805,,,",
            ]
        ),
        encoding="utf-8",
    )
    generic_sidecar = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "log_metadata_examples"
        / "syn_bike_raw_generic_log_metadata.json"
    )

    session = load_session(str(csv_path), generic_log_metadata_paths=[generic_sidecar])

    assert session["source"]["log_metadata_path"] == str(generic_sidecar)
    assert session["source"]["log_metadata_kind"] == "generic"
    assert session["meta"]["sample_rate_hz"] == 100.0
    assert np.isclose(float(session["df"]["time_s"].iloc[-1]), 0.02)
    np.testing.assert_allclose(np.diff(session["df"]["time_s"].to_numpy()), [0.01])
    assert "front_wheel_raw_dom_wheel [counts]" in session["df"].columns
    assert "rear_suspension_raw_dom_suspension [counts]" in session["df"].columns
    assert session["meta"]["channel_info"]["front_wheel_raw_dom_wheel [counts]"]["sensor"] == "front_shock"
    assert session["meta"]["channel_info"]["rear_suspension_raw_dom_suspension [counts]"]["sensor"] == "rear_shock"


def test_preprocess_session_materializes_linear_logger_displacement_for_bike_profile(tmp_path):
    csv_path = tmp_path / "session.csv"
    csv_path.write_text(
        "\n".join(
            [
                "0,3500,3000,,,",
                "1,3400,2800,,,",
                "2,3300,2600,,,",
                "3,3200,2400,,,",
                "4,3100,2200,,,",
            ]
        ),
        encoding="utf-8",
    )
    sidecar = _write_syn_bike_raw_sidecar_with_linear_calibration(tmp_path)
    bike_profile_path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "bike_profiles"
        / "Stumpjumper Evo 2021.json"
    )

    result = preprocess_session(
        str(csv_path),
        generic_log_metadata_paths=[sidecar],
        bike_profile_path=str(bike_profile_path),
        fit_import={"enabled": False},
        zeroing_enabled=False,
        include_events=False,
        include_metrics=False,
        strict=False,
    )

    session = result["session"]
    df = session["df"]
    generated = session["qc"]["transforms"]["logger_calibration"]["generated"]

    assert "front_wheel_disp_dom_wheel [mm]" in df.columns
    assert "rear_suspension_disp_dom_suspension [mm]" in df.columns
    assert "rear_wheel_disp_dom_wheel [mm]" in df.columns
    assert len(generated) == 2
    assert {item["output_column"] for item in generated} == {
        "front_wheel_disp_dom_wheel [mm]",
        "rear_suspension_disp_dom_suspension [mm]",
    }
    resolved_ranges = session["qc"]["bike_profile"]["normalization_ranges"]
    assert {item["column"]: item["full_range"] for item in resolved_ranges} == {
        "front_wheel_disp_dom_wheel [mm]": 170.0,
        "rear_suspension_disp_dom_suspension [mm]": 55.0,
        "rear_wheel_disp_dom_wheel [mm]": 150.0,
    }


def test_load_session_uses_filename_stem_anchor_without_sidecar(tmp_path):
    csv_path = _write_csv_only(tmp_path, name="2026-02-19_08-35-11.CSV")

    session = load_session(str(csv_path), timezone="Australia/Perth")

    assert session["source"]["created_local"] == "2026-02-19T08:35:11+08:00"
    assert session["meta"]["t0_datetime"] == "2026-02-19T08:35:11+08:00"
    assert session["qc"]["parse"]["time_anchor_source"] == "filename_stem"
    assert session["qc"]["parse"]["time_anchor_timezone_source"] == "explicit_timezone"
    assert session["qc"]["warnings"] == []


def test_load_session_uses_filename_stem_anchor_with_suffix(tmp_path):
    csv_path = _write_csv_only(tmp_path, name="2026-02-19_08-35-11_slackline.CSV")

    session = load_session(str(csv_path), timezone="Australia/Perth")

    assert session["source"]["created_local"] == "2026-02-19T08:35:11+08:00"
    assert session["meta"]["t0_datetime"] == "2026-02-19T08:35:11+08:00"


def test_load_session_uses_compact_filename_stem_anchor(tmp_path):
    csv_path = _write_csv_only(tmp_path, name="260219_083511.CSV")

    session = load_session(str(csv_path), timezone="Australia/Perth")

    assert session["source"]["created_local"] == "2026-02-19T08:35:11+08:00"
    assert session["meta"]["t0_datetime"] == "2026-02-19T08:35:11+08:00"
    assert session["qc"]["parse"]["time_anchor_source"] == "filename_stem"
    assert session["qc"]["parse"]["time_anchor_timezone_source"] == "explicit_timezone"
    assert session["qc"]["warnings"] == []


def test_log_metadata_timezone_overrides_runtime_fallback_for_filename_anchor(tmp_path):
    csv_path = _write_csv_only(tmp_path, name="2026-02-19_08-35-11.csv")
    sidecar = {
        "contract": {"name": "mtb_logger_timeseries", "version": "0.2.0"},
        "session": {"timezone": "Australia/Perth"},
        "streams": {
            "primary": {
                "type": "uniform",
                "time_column": "time_s",
                "time_encoding": "elapsed_s",
                "time_unit": "s",
                "sample_rate_hz": 40.0,
            }
        },
        "columns": {
            "time_s": {
                "csv_ref": {"by": "header", "header": "time_s"},
                "class": "time",
                "dtype": "float64",
                "stream": "primary",
                "unit": "s",
            },
            "front_shock": {
                "csv_ref": {"by": "header", "header": "front_shock_dom_suspension [mm]"},
                "class": "signal",
                "dtype": "float64",
                "stream": "primary",
                "end": "front",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
            },
            "rear_shock": {
                "csv_ref": {"by": "header", "header": "rear_shock_dom_suspension [mm]"},
                "class": "signal",
                "dtype": "float64",
                "stream": "primary",
                "end": "rear",
                "quantity": "disp",
                "domain": "suspension",
                "unit": "mm",
            },
            "mark": {
                "csv_ref": {"by": "header", "header": "mark"},
                "class": "event_flag",
                "dtype": "bool",
                "stream": "primary",
            },
        },
    }
    (tmp_path / "2026-02-19_08-35-11.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    session = load_session(str(csv_path), timezone="UTC")

    assert session["source"]["timezone"] == "Australia/Perth"
    assert session["source"]["timezone_source"] == "log_metadata"
    assert session["source"]["created_local"] == "2026-02-19T08:35:11+08:00"
    assert session["meta"]["t0_datetime"] == "2026-02-19T08:35:11+08:00"
    assert session["qc"]["parse"]["runtime_timezone_fallback"] == "UTC"
    assert session["qc"]["parse"]["runtime_timezone_overridden_by_log_metadata"] is True


def test_preprocess_session_uses_declared_sidecar_sample_rate(tmp_path):
    csv_path, _ = _write_csv_and_sidecar(tmp_path)
    session = load_session(str(csv_path))

    out = preprocess_session(
        session,
        normalize_ranges={
            "front_shock_dom_suspension [mm]": 170.0,
            "rear_shock_dom_suspension [mm]": 150.0,
        },
        zeroing_enabled=False,
    )["session"]

    primary = out["meta"]["streams"]["primary"]
    assert primary["sample_rate_hz"] == 40.0
    assert np.isclose(primary["dt_s"], 0.025)


def test_validate_session_allows_intermittent_secondary_streams():
    primary_df = pd.DataFrame(
        {
            "time_s": np.array([0.0, 0.02, 0.04, 0.06]),
            "rear_shock_dom_suspension [mm]": np.array([10.0, 11.0, 12.0, 13.0]),
        }
    )
    gps_df = pd.DataFrame(
        {
            "time_s": np.array([0.05, 0.41, 0.95]),
            "gps_fit_speed [m/s]": np.array([1.1, 2.2, 3.3]),
        }
    )

    session = {
        "session_id": "test_session_intervals",
        "source": {"path": "dummy.csv", "filename": "dummy.csv"},
        "meta": {},
        "qc": {},
        "df": primary_df,
        "stream_dfs": {"gps_fit": gps_df},
    }
    register_stream_metadata(
        session,
        stream_name="primary",
        kind="uniform",
        time_col="time_s",
        sample_rate_hz=50.0,
        dt_s=0.02,
        jitter_frac=0.0,
    )
    register_stream_metadata(
        session,
        stream_name="gps_fit",
        kind="intermittent",
        time_col="time_s",
    )

    validate_session(session)


def test_select_fit_candidate_requires_binding_when_multiple_overlap(tmp_path):
    candidates = [
        {
            "path": str(tmp_path / "ride_a.fit"),
            "filename": "ride_a.fit",
            "fit_start_datetime": "2026-02-19T00:00:00+00:00",
            "fit_end_datetime": "2026-02-19T00:10:00+00:00",
            "overlap_s": 120.0,
        },
        {
            "path": str(tmp_path / "ride_b.fit"),
            "filename": "ride_b.fit",
            "fit_start_datetime": "2026-02-19T00:01:00+00:00",
            "fit_end_datetime": "2026-02-19T00:11:00+00:00",
            "overlap_s": 110.0,
        },
    ]

    with pytest.raises(ValueError, match="Multiple overlapping FIT files"):
        select_fit_candidate(
            session_id="session_001",
            csv_path=str(tmp_path / "session.csv"),
            csv_sha256=None,
            candidates=candidates,
            ambiguity_policy="require_binding",
            bindings_path=None,
        )

    bindings_path = tmp_path / "fit_bindings_v1.json"
    bindings_path.write_text(
        json.dumps(
            {
                "schema": "bodaqs.fit_bindings",
                "version": 1,
                "bindings": [
                    {
                        "session_id": "session_001",
                        "fit_file": str(tmp_path / "ride_b.fit"),
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    selected = select_fit_candidate(
        session_id="session_001",
        csv_path=str(tmp_path / "session.csv"),
        csv_sha256=None,
        candidates=candidates,
        ambiguity_policy="require_binding",
        bindings_path=str(bindings_path),
    )

    assert selected["filename"] == "ride_b.fit"


def test_parse_fit_bindings_accepts_mapping_text_and_bytes(tmp_path):
    bindings_payload = {
        "schema": "bodaqs.fit_bindings",
        "version": 1,
        "bindings": [{"session_id": "session_001", "fit_file": "ride_a.fit"}],
    }
    bindings_text = json.dumps(bindings_payload)
    bindings_path = tmp_path / "fit_bindings_v1.json"
    bindings_path.write_text(bindings_text, encoding="utf-8")

    parsed_from_mapping = parse_fit_bindings(bindings_payload)
    parsed_from_text = parse_fit_bindings(bindings_text)
    parsed_from_bytes = parse_fit_bindings(bindings_text.encode("utf-8"))
    parsed_from_path = parse_fit_bindings(bindings_path)

    assert parsed_from_mapping[0]["fit_file"] == "ride_a.fit"
    assert parsed_from_text[0]["session_id"] == "session_001"
    assert parsed_from_bytes[0]["fit_file"] == "ride_a.fit"
    assert parsed_from_path[0]["fit_file"] == "ride_a.fit"


def test_select_fit_candidate_accepts_in_memory_bindings_and_filename_only_candidates():
    candidates = [
        {
            "filename": "ride_a.fit",
            "fit_start_datetime": "2026-02-19T00:00:00+00:00",
            "fit_end_datetime": "2026-02-19T00:10:00+00:00",
            "overlap_s": 120.0,
            "fit_sha256": "fitsha_a",
        },
        {
            "filename": "ride_b.fit",
            "fit_start_datetime": "2026-02-19T00:01:00+00:00",
            "fit_end_datetime": "2026-02-19T00:11:00+00:00",
            "overlap_s": 110.0,
            "fit_sha256": "fitsha_b",
        },
    ]
    bindings = [
        {
            "session_id": "session_001",
            "fit_file": "ride_b.fit",
        }
    ]

    selected = select_fit_candidate(
        session_id="session_001",
        csv_path=None,
        csv_sha256=None,
        candidates=candidates,
        ambiguity_policy="require_binding",
        bindings=bindings,
    )

    assert selected["filename"] == "ride_b.fit"


def test_upsert_fit_binding_records_replaces_existing_match():
    bindings = [
        {
            "session_id": "session_001",
            "csv_path": "session.csv",
            "csv_sha256": "abc123",
            "fit_file": "ride_a.fit",
            "fit_sha256": "fitsha1",
        }
    ]

    updated, replacement = upsert_fit_binding_records(
        bindings,
        session_id="session_001",
        csv_path="session.csv",
        csv_sha256="abc123",
        fit_file="ride_b.fit",
        fit_sha256="fitsha2",
    )

    assert replacement["fit_file"] == "ride_b.fit"
    assert len(updated) == 1
    assert updated[0]["fit_file"] == "ride_b.fit"


def test_find_overlapping_fit_files_deduplicates_case_variants(tmp_path, monkeypatch):
    fit_path = tmp_path / "ride.fit"
    fit_path.write_bytes(b"fit-binary-placeholder")

    monkeypatch.setattr(
        "bodaqs_analysis.io_fit.inspect_fit_file",
        lambda path, field_allowlist=None: {
            "path": str(path),
            "filename": Path(path).name,
            "start_datetime": "2026-02-19T00:35:11+00:00",
            "end_datetime": "2026-02-19T00:45:11+00:00",
            "available_fields": ["enhanced_speed"],
            "field_units": {"enhanced_speed": "m/s"},
        },
    )

    candidates = find_overlapping_fit_files(
        fit_dir=tmp_path,
        session_start_datetime="2026-02-19T00:36:00+00:00",
        session_end_datetime="2026-02-19T00:37:00+00:00",
    )

    assert len(candidates) == 1
    assert candidates[0]["filename"] == "ride.fit"


def test_inspect_fit_stream_accepts_bytes_without_paths(monkeypatch):
    def fake_iter_fit_record_rows_from_fileish(fileish):
        assert fileish.read(4) == b"fake"
        fileish.seek(0)
        return (
            [
                {"timestamp": "2026-02-19T00:35:11.250000+00:00", "speed": 1.0, "altitude": 100.0},
                {"timestamp": "2026-02-19T00:35:11.750000+00:00", "speed": 3.0, "altitude": 102.0},
            ],
            {"speed": "m/s", "altitude": "m"},
        )

    monkeypatch.setattr(
        "bodaqs_analysis.io_fit._iter_fit_record_rows_from_fileish",
        fake_iter_fit_record_rows_from_fileish,
    )

    summary = inspect_fit_stream(
        b"fake-fit-binary",
        field_allowlist=["speed", "altitude"],
        source_name="ride.fit",
    )

    assert summary["filename"] == "ride.fit"
    assert "path" not in summary
    assert summary["available_fields"] == ["altitude", "speed"]
    assert summary["start_datetime"] == "2026-02-19T00:35:11.250000+00:00"
    assert isinstance(summary["fit_sha256"], str) and summary["fit_sha256"]


def test_find_overlapping_fit_candidates_accepts_precomputed_summaries():
    candidates = find_overlapping_fit_candidates(
        [
            {
                "filename": "ride_a.fit",
                "start_datetime": "2026-02-19T00:35:11+00:00",
                "end_datetime": "2026-02-19T00:36:11+00:00",
            },
            {
                "filename": "ride_b.fit",
                "fit_start_datetime": "2026-02-19T00:40:00+00:00",
                "fit_end_datetime": "2026-02-19T00:41:00+00:00",
            },
        ],
        session_start_datetime="2026-02-19T00:35:30+00:00",
        session_end_datetime="2026-02-19T00:35:45+00:00",
    )

    assert len(candidates) == 1
    assert candidates[0]["filename"] == "ride_a.fit"
    assert candidates[0]["overlap_s"] == 15.0


def test_parse_fit_stream_accepts_bytes_without_paths(monkeypatch):
    def fake_iter_fit_record_rows_from_fileish(fileish):
        assert fileish.read(4) == b"fake"
        fileish.seek(0)
        return (
            [
                {"timestamp": "2026-02-19T00:35:11.250000+00:00", "speed": 1.0, "altitude": 100.0},
                {"timestamp": "2026-02-19T00:35:11.750000+00:00", "speed": 3.0, "altitude": 102.0},
            ],
            {"speed": "m/s", "altitude": "m"},
        )

    monkeypatch.setattr(
        "bodaqs_analysis.io_fit._iter_fit_record_rows_from_fileish",
        fake_iter_fit_record_rows_from_fileish,
    )

    fit_df, fit_meta = parse_fit_stream(
        b"fake-fit-binary",
        session_start_datetime="2026-02-19T08:35:11+08:00",
        field_allowlist=["speed", "altitude"],
        source_name="ride.fit",
    )

    assert fit_df["time_s"].tolist() == [0.25, 0.75]
    assert fit_df["gps_fit_speed_dom_world [m/s]"].tolist() == [1.0, 3.0]
    assert fit_meta["filename"] == "ride.fit"
    assert "path" not in fit_meta
    assert isinstance(fit_meta["fit_sha256"], str) and fit_meta["fit_sha256"]
    assert fit_meta["loaded_fields"] == ["altitude", "speed"]


def test_enrich_session_with_fit_adds_raw_stream_and_resampled_columns(tmp_path, monkeypatch):
    fit_path = tmp_path / "ride.fit"
    fit_path.write_bytes(b"not-a-real-fit-fixture")

    session = {
        "session_id": "session_001",
        "source": {"path": str(tmp_path / "session.csv"), "filename": "session.csv"},
        "meta": {"t0_datetime": "2026-02-19T08:35:11+08:00", "channel_info": {}},
        "qc": {"warnings": [], "transforms": {}},
        "df": pd.DataFrame({"time_s": np.array([0.0, 0.5, 1.0, 1.5])}),
    }

    def fake_find_overlapping_fit_files(**kwargs):
        assert kwargs["fit_dir"] == str(tmp_path)
        return [
            {
                "path": str(fit_path),
                "filename": fit_path.name,
                "fit_start_datetime": "2026-02-19T00:35:11.250000+00:00",
                "fit_end_datetime": "2026-02-19T00:35:12.250000+00:00",
                "overlap_start_datetime": "2026-02-19T00:35:11.250000+00:00",
                "overlap_end_datetime": "2026-02-19T00:35:12.250000+00:00",
                "overlap_s": 1.0,
            }
        ]

    def fake_load_fit_stream(path, *, session_start_datetime, field_allowlist):
        assert path == str(fit_path)
        assert session_start_datetime == "2026-02-19T08:35:11+08:00"
        fit_df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [
                        "2026-02-19T00:35:11.250000+00:00",
                        "2026-02-19T00:35:11.750000+00:00",
                        "2026-02-19T00:35:12.250000+00:00",
                    ],
                    utc=True,
                ),
                "time_s": np.array([0.25, 0.75, 1.25]),
                "gps_fit_speed_dom_world [m/s]": np.array([1.0, 3.0, 5.0]),
                "gps_fit_altitude_dom_world [m]": np.array([100.0, 102.0, 104.0]),
            }
        )
        fit_meta = {
            "path": str(fit_path),
            "filename": fit_path.name,
            "fit_sha256": "abc123",
            "stream_name": "gps_fit",
            "resample_columns": [
                "gps_fit_speed_dom_world [m/s]",
                "gps_fit_altitude_dom_world [m]",
            ],
            "channel_info": {
                "gps_fit_speed_dom_world [m/s]": {"unit": "m/s", "sensor": "gps_fit", "role": "speed"},
                "gps_fit_altitude_dom_world [m]": {"unit": "m", "sensor": "gps_fit", "role": "altitude"},
            },
        }
        return fit_df, fit_meta

    monkeypatch.setattr(
        "bodaqs_analysis.pipeline.find_overlapping_fit_files",
        fake_find_overlapping_fit_files,
    )
    monkeypatch.setattr(
        "bodaqs_analysis.pipeline.load_fit_stream",
        fake_load_fit_stream,
    )

    out = enrich_session_with_fit(
        session,
        fit_import={
            "enabled": True,
            "fit_dir": str(tmp_path),
            "field_allowlist": ["speed", "altitude"],
            "persist_raw_stream": True,
            "resample_to_primary": True,
        },
    )

    assert "gps_fit" in out["stream_dfs"]
    assert out["meta"]["streams"]["gps_fit"]["kind"] == "intermittent"
    assert out["source"]["aux_sources"][0]["filename"] == fit_path.name

    speed = out["df"]["gps_fit_speed_dom_world [m/s]"].to_numpy()
    altitude = out["df"]["gps_fit_altitude_dom_world [m]"].to_numpy()
    assert np.isnan(speed[0]) and np.isnan(speed[-1])
    assert np.isnan(altitude[0]) and np.isnan(altitude[-1])
    assert np.allclose(speed[1:3], np.array([2.0, 4.0]))
    assert np.allclose(altitude[1:3], np.array([101.0, 103.0]))
    assert out["meta"]["channel_info"]["gps_fit_speed_dom_world [m/s]"]["role"] == "speed"
    assert out["qc"]["fit_import"]["selected_file"] == fit_path.name


def test_enrich_session_with_fit_does_not_bridge_paused_gps_gap():
    session = {
        "session_id": "session_in_fit_pause",
        "source": {"filename": "session.csv"},
        "meta": {"t0_datetime": "2026-02-19T08:55:18+08:00", "channel_info": {}},
        "qc": {"warnings": [], "transforms": {}},
        "df": pd.DataFrame({"time_s": np.array([10.0, 20.0, 30.0])}),
    }

    lat_col = "gps_fit_position_latitude_dom_world [deg]"
    lon_col = "gps_fit_position_longitude_dom_world [deg]"
    fit_df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-02-19T00:55:18+00:00",
                    "2026-02-19T00:56:58+00:00",
                ],
                utc=True,
            ),
            "time_s": np.array([0.0, 100.0]),
            lat_col: np.array([-32.0, -32.01]),
            lon_col: np.array([116.0, 116.01]),
        }
    )
    fit_meta = {
        "filename": "paused_ride.fit",
        "fit_sha256": "abc123",
        "stream_name": "gps_fit",
        "resample_columns": [lat_col, lon_col],
        "channel_info": {
            lat_col: {"unit": "deg", "sensor": "gps_fit", "role": "position_latitude"},
            lon_col: {"unit": "deg", "sensor": "gps_fit", "role": "position_longitude"},
        },
    }

    out = enrich_session_with_fit(
        session,
        fit_import={
            "enabled": True,
            "persist_raw_stream": True,
            "resample_to_primary": True,
            "gps_resample_max_gap_s": 5.0,
        },
        fit_stream={"df": fit_df, "meta": fit_meta},
    )

    assert "gps_fit" in out["stream_dfs"]
    assert np.isnan(out["df"][lat_col].to_numpy()).all()
    assert np.isnan(out["df"][lon_col].to_numpy()).all()

    warnings = out["qc"]["warnings"]
    assert "fit_import_no_gps_position_points_in_session_window" in warnings
    assert "fit_import_gps_resample_gap_limited" in warnings

    gps_qc = out["qc"]["fit_import"]["gps_resampling"]
    assert gps_qc["raw_position_points_in_session_window"] == 0
    assert gps_qc["resampled_position_points"] == 0
    assert gps_qc["gap_rejected_samples"] == 6


def test_enrich_session_with_fit_accepts_in_memory_bindings(tmp_path, monkeypatch):
    first_fit = tmp_path / "ride_a.fit"
    second_fit = tmp_path / "ride_b.fit"
    first_fit.write_bytes(b"fit-a")
    second_fit.write_bytes(b"fit-b")

    session = {
        "session_id": "session_001",
        "source": {"filename": "session.csv"},
        "meta": {"t0_datetime": "2026-02-19T08:35:11+08:00", "channel_info": {}},
        "qc": {"warnings": [], "transforms": {}},
        "df": pd.DataFrame({"time_s": np.array([0.0, 0.5, 1.0])}),
    }

    def fake_find_overlapping_fit_files(**kwargs):
        return [
            {
                "path": str(first_fit),
                "filename": first_fit.name,
                "fit_start_datetime": "2026-02-19T00:35:11.250000+00:00",
                "fit_end_datetime": "2026-02-19T00:35:12.250000+00:00",
                "overlap_start_datetime": "2026-02-19T00:35:11.250000+00:00",
                "overlap_end_datetime": "2026-02-19T00:35:12.250000+00:00",
                "overlap_s": 1.0,
            },
            {
                "path": str(second_fit),
                "filename": second_fit.name,
                "fit_start_datetime": "2026-02-19T00:35:11.250000+00:00",
                "fit_end_datetime": "2026-02-19T00:35:12.250000+00:00",
                "overlap_start_datetime": "2026-02-19T00:35:11.250000+00:00",
                "overlap_end_datetime": "2026-02-19T00:35:12.250000+00:00",
                "overlap_s": 1.0,
            },
        ]

    def fake_load_fit_stream(path, *, session_start_datetime, field_allowlist):
        fit_df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [
                        "2026-02-19T00:35:11.250000+00:00",
                        "2026-02-19T00:35:11.750000+00:00",
                    ],
                    utc=True,
                ),
                "time_s": np.array([0.25, 0.75]),
                "gps_fit_speed_dom_world [m/s]": np.array([1.0, 3.0]),
            }
        )
        fit_meta = {
            "path": path,
            "filename": Path(path).name,
            "fit_sha256": "chosen-sha",
            "stream_name": "gps_fit",
            "resample_columns": ["gps_fit_speed_dom_world [m/s]"],
            "channel_info": {
                "gps_fit_speed_dom_world [m/s]": {"unit": "m/s", "sensor": "gps_fit", "role": "speed"},
            },
        }
        return fit_df, fit_meta

    monkeypatch.setattr(
        "bodaqs_analysis.pipeline.find_overlapping_fit_files",
        fake_find_overlapping_fit_files,
    )
    monkeypatch.setattr(
        "bodaqs_analysis.pipeline.load_fit_stream",
        fake_load_fit_stream,
    )

    out = enrich_session_with_fit(
        session,
        fit_import={
            "enabled": True,
            "fit_dir": str(tmp_path),
            "persist_raw_stream": False,
            "resample_to_primary": False,
        },
        fit_bindings=[{"session_id": "session_001", "fit_file": "ride_b.fit"}],
    )

    assert out["qc"]["fit_import"]["selected_file"] == "ride_b.fit"


def test_enrich_session_with_preloaded_fit_stream_avoids_fit_dir_requirement():
    session = {
        "session_id": "session_001",
        "source": {"filename": "session.csv"},
        "meta": {"channel_info": {}},
        "qc": {"warnings": [], "transforms": {}},
        "df": pd.DataFrame({"time_s": np.array([0.0, 0.5, 1.0, 1.5])}),
    }
    fit_df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-02-19T00:35:11.250000+00:00",
                    "2026-02-19T00:35:11.750000+00:00",
                    "2026-02-19T00:35:12.250000+00:00",
                ],
                utc=True,
            ),
            "time_s": np.array([0.25, 0.75, 1.25]),
            "gps_fit_speed_dom_world [m/s]": np.array([1.0, 3.0, 5.0]),
        }
    )
    fit_meta = {
        "filename": "uploaded.fit",
        "fit_sha256": "abc123",
        "stream_name": "gps_fit",
        "resample_columns": ["gps_fit_speed_dom_world [m/s]"],
        "channel_info": {
            "gps_fit_speed_dom_world [m/s]": {"unit": "m/s", "sensor": "gps_fit", "role": "speed"},
        },
    }

    out = enrich_session_with_fit(
        session,
        fit_import={
            "enabled": True,
            "persist_raw_stream": True,
            "resample_to_primary": True,
        },
        fit_stream={"df": fit_df, "meta": fit_meta},
    )

    assert "gps_fit" in out["stream_dfs"]
    speed = out["df"]["gps_fit_speed_dom_world [m/s]"].to_numpy()
    assert np.isnan(speed[0]) and np.isnan(speed[-1])
    assert np.allclose(speed[1:3], np.array([2.0, 4.0]))
    assert out["source"]["aux_sources"][0]["filename"] == "uploaded.fit"
    assert "path" not in out["source"]["aux_sources"][0] or out["source"]["aux_sources"][0]["path"] is None
    assert out["qc"]["fit_import"]["selected_file"] == "uploaded.fit"
    assert out["qc"]["fit_import"]["overlap_s"] is None


def test_enrich_session_with_fit_candidates_accepts_in_memory_fit_input(monkeypatch):
    session = {
        "session_id": "session_001",
        "source": {"filename": "session.csv"},
        "meta": {"t0_datetime": "2026-02-19T08:35:11+08:00", "channel_info": {}},
        "qc": {"warnings": [], "transforms": {}},
        "df": pd.DataFrame({"time_s": np.array([0.0, 0.5, 1.0, 1.5])}),
    }

    def fake_parse_fit_stream(fit_input, *, session_start_datetime, field_allowlist, source_name=None):
        assert fit_input == b"remote-fit-binary"
        assert source_name == "uploaded.fit"
        fit_df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [
                        "2026-02-19T00:35:11.250000+00:00",
                        "2026-02-19T00:35:11.750000+00:00",
                        "2026-02-19T00:35:12.250000+00:00",
                    ],
                    utc=True,
                ),
                "time_s": np.array([0.25, 0.75, 1.25]),
                "gps_fit_speed_dom_world [m/s]": np.array([1.0, 3.0, 5.0]),
            }
        )
        fit_meta = {
            "filename": "uploaded.fit",
            "fit_sha256": "remote-sha",
            "stream_name": "gps_fit",
            "resample_columns": ["gps_fit_speed_dom_world [m/s]"],
            "channel_info": {
                "gps_fit_speed_dom_world [m/s]": {"unit": "m/s", "sensor": "gps_fit", "role": "speed"},
            },
        }
        return fit_df, fit_meta

    monkeypatch.setattr(
        "bodaqs_analysis.pipeline.parse_fit_stream",
        fake_parse_fit_stream,
    )

    out = enrich_session_with_fit(
        session,
        fit_import={
            "enabled": True,
            "persist_raw_stream": False,
            "resample_to_primary": True,
        },
        fit_candidates=[
            {
                "filename": "uploaded.fit",
                "start_datetime": "2026-02-19T00:35:11.250000+00:00",
                "end_datetime": "2026-02-19T00:35:12.250000+00:00",
                "fit_input": b"remote-fit-binary",
                "fit_sha256": "remote-sha",
            }
        ],
    )

    speed = out["df"]["gps_fit_speed_dom_world [m/s]"].to_numpy()
    assert np.isnan(speed[0]) and np.isnan(speed[-1])
    assert np.allclose(speed[1:3], np.array([2.0, 4.0]))
    assert out["qc"]["fit_import"]["selected_file"] == "uploaded.fit"


def test_preprocess_resolved_accepts_fit_candidates_with_in_memory_fit_input(monkeypatch):
    session = {
        "session_id": "session_001",
        "source": {"filename": "session.csv"},
        "meta": {"t0_datetime": "2026-02-19T08:35:11+08:00", "channel_info": {}},
        "qc": {"warnings": [], "transforms": {}},
        "df": pd.DataFrame(
            {
                "time_s": np.array([0.0, 0.5, 1.0, 1.5]),
                "rear_shock_dom_suspension [mm]": np.array([20.0, 22.0, 24.0, 26.0]),
            }
        ),
    }

    def fake_parse_fit_stream(fit_input, *, session_start_datetime, field_allowlist, source_name=None):
        fit_df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [
                        "2026-02-19T00:35:11.250000+00:00",
                        "2026-02-19T00:35:11.750000+00:00",
                        "2026-02-19T00:35:12.250000+00:00",
                    ],
                    utc=True,
                ),
                "time_s": np.array([0.25, 0.75, 1.25]),
                "gps_fit_speed_dom_world [m/s]": np.array([1.0, 3.0, 5.0]),
            }
        )
        fit_meta = {
            "filename": "uploaded.fit",
            "fit_sha256": "remote-sha",
            "stream_name": "gps_fit",
            "resample_columns": ["gps_fit_speed_dom_world [m/s]"],
            "channel_info": {
                "gps_fit_speed_dom_world [m/s]": {"unit": "m/s", "sensor": "gps_fit", "role": "speed"},
            },
        }
        return fit_df, fit_meta

    monkeypatch.setattr(
        "bodaqs_analysis.pipeline.parse_fit_stream",
        fake_parse_fit_stream,
    )

    out = preprocess_resolved(
        session,
        fit_import={
            "enabled": True,
            "persist_raw_stream": False,
            "resample_to_primary": True,
        },
        fit_candidates=[
            {
                "filename": "uploaded.fit",
                "start_datetime": "2026-02-19T00:35:11.250000+00:00",
                "end_datetime": "2026-02-19T00:35:12.250000+00:00",
                "fit_input": b"remote-fit-binary",
                "fit_sha256": "remote-sha",
            }
        ],
        normalize_ranges={"rear_shock_dom_suspension [mm]": 100.0},
        include_events=False,
        include_metrics=False,
    )["session"]

    speed = out["df"]["gps_fit_speed_dom_world [m/s]"].to_numpy()
    assert np.isnan(speed[0]) and np.isnan(speed[-1])
    assert np.allclose(speed[1:3], np.array([2.0, 4.0]))
    assert out["qc"]["fit_import"]["selected_file"] == "uploaded.fit"


def test_session_artifacts_round_trip_secondary_streams(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    session_df = pd.DataFrame({"time_s": np.array([0.0, 0.5]), "signal": np.array([1.0, 2.0])})
    gps_df = pd.DataFrame({"time_s": np.array([0.1, 0.8]), "gps_fit_speed_dom_world [m/s]": np.array([3.0, 4.0])})

    save_session_artifacts(
        store,
        run_id="run_test",
        session_id="session_001",
        session_df=session_df,
        session_meta={"sample_rate_hz": 2.0},
        secondary_stream_dfs={"gps_fit": gps_df},
        secondary_stream_meta={"gps_fit": {"stream_name": "gps_fit", "kind": "intermittent"}},
    )

    loaded = load_session_artifacts(store, run_id="run_test", session_id="session_001")

    assert list(loaded["df"].columns) == ["time_s", "signal"]
    assert "stream_dfs" in loaded
    assert "gps_fit" in loaded["stream_dfs"]
    assert np.allclose(
        loaded["stream_dfs"]["gps_fit"]["gps_fit_speed_dom_world [m/s]"].to_numpy(),
        np.array([3.0, 4.0]),
    )
    assert loaded["secondary_stream_meta"]["gps_fit"]["kind"] == "intermittent"


def test_copy_session_aux_sources_copies_fit_file(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    fit_path = tmp_path / "ride.fit"
    fit_path.write_bytes(b"fit-binary-placeholder")

    copied = copy_session_aux_sources(
        store=store,
        run_id="run_test",
        session_id="session_001",
        aux_sources=[
            {
                "kind": "fit",
                "stream_name": "gps_fit",
                "path": str(fit_path),
                "filename": "ride.fit",
            }
        ],
    )

    assert len(copied) == 1
    assert copied[0]["path"] == "source_aux/ride.fit"
    copied_path = store.path_session_aux_source_dir("run_test", "session_001") / "ride.fit"
    assert copied_path.exists()
    assert copied_path.read_bytes() == b"fit-binary-placeholder"


def test_preprocess_controls_builds_fit_import_config():
    controls = PreprocessControls(
        disp_cols_all=["front_shock_dom_suspension [mm]"],
        sessions_by_id={"session_001": {}},
        defaults=PreprocessDefaults(
            fit_import={
                "enabled": True,
                "fit_dir": "Garmin/FIT",
                "field_allowlist": ["speed", "position_lat"],
                "ambiguity_policy": "require_binding",
                "partial_overlap": "allow",
                "persist_raw_stream": True,
                "resample_to_primary": True,
                "resample_method": "linear",
                "raw_stream_name": "gps_fit",
                "bindings_path": "analysis/config/fit_bindings_v1.json",
            }
        ),
        default_ranges={"front_shock_dom_suspension [mm]": 170.0},
    )

    errors, _warnings = controls.validate()
    assert errors == []

    cfg = controls.get_config()
    assert cfg["fit_import"]["enabled"] is True
    assert cfg["fit_import"]["fit_dir"] == "Garmin/FIT"
    assert cfg["fit_import"]["field_allowlist"] == ["speed", "position_lat"]
    assert cfg["fit_import"]["bindings_path"] == "analysis/config/fit_bindings_v1.json"


def test_upsert_fit_binding_replaces_existing_match(tmp_path):
    bindings_path = tmp_path / "fit_bindings_v1.json"

    first = upsert_fit_binding(
        bindings_path,
        session_id="session_001",
        csv_path="session.csv",
        csv_sha256="abc123",
        fit_file="ride_a.fit",
        fit_sha256="fitsha1",
        selected_by="user",
    )
    second = upsert_fit_binding(
        bindings_path,
        session_id="session_001",
        csv_path="session.csv",
        csv_sha256="abc123",
        fit_file="ride_b.fit",
        fit_sha256="fitsha2",
        selected_by="user",
    )

    bindings = load_fit_bindings(bindings_path)
    assert first["fit_file"] == "ride_a.fit"
    assert second["fit_file"] == "ride_b.fit"
    assert len(bindings) == 1
    assert bindings[0]["fit_file"] == "ride_b.fit"


def test_build_fit_candidate_summary_marks_ambiguous_sessions(monkeypatch):
    session = {
        "session_id": "session_001",
        "source": {"path": "session.csv"},
        "meta": {"t0_datetime": "2026-02-19T08:35:11+08:00"},
        "df": pd.DataFrame({"time_s": np.array([0.0, 1.0, 2.0])}),
    }

    monkeypatch.setattr(
        "bodaqs_analysis.ui.fit_bindings_editor.find_overlapping_fit_files",
        lambda **kwargs: [
            {"path": "ride_a.fit", "filename": "ride_a.fit", "overlap_s": 2.0},
            {"path": "ride_b.fit", "filename": "ride_b.fit", "overlap_s": 1.5},
        ],
    )

    summary = build_fit_candidate_summary(
        {"session_001": session},
        fit_import={
            "enabled": True,
            "fit_dir": "Garmin/FIT",
            "ambiguity_policy": "require_binding",
            "bindings_path": None,
        },
    )

    assert len(summary.index) == 1
    assert summary.loc[0, "session_id"] == "session_001"
    assert summary.loc[0, "status"] == "ambiguous"
    assert summary.loc[0, "n_candidates"] == 2


def test_preprocess_log_selector_imports_without_ipydatagrid(tmp_path):
    csv_path = tmp_path / "session.csv"
    csv_path.write_text("time_s,value\n0.0,1.0\n", encoding="utf-8")

    selector = PreprocessLogSelector(
        artifacts_dir=tmp_path / "artifacts",
        state_file=tmp_path / ".last_dir.json",
        sha_cache_file=tmp_path / ".sha_cache.json",
        include_lowercase_csv=True,
    )
    selector.w_dir.value = str(tmp_path)
    selector.refresh()

    selector.w_files.value = (str(csv_path.resolve()),)
    selected = selector.get_selected_files()

    assert len(selected) == 1
    assert selected[0] == csv_path.resolve()
