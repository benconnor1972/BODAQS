import json
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
from bodaqs_analysis.io_fit import (
    find_overlapping_fit_files,
    load_fit_bindings,
    select_fit_candidate,
    upsert_fit_binding,
)
from bodaqs_analysis.model import validate_session
from bodaqs_analysis.pipeline import enrich_session_with_fit, load_session, preprocess_session
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


def test_load_session_auto_uses_same_stem_sidecar(tmp_path):
    csv_path, sidecar_path = _write_csv_and_sidecar(tmp_path)

    session = load_session(str(csv_path))

    assert session["source"]["sidecar_path"] == str(sidecar_path)
    assert session["source"]["created_local"] == "2026-02-19T08:35:11+08:00"
    assert session["source"]["timezone"] == "Australia/Perth"
    assert session["meta"]["t0_datetime"] == "2026-02-19T08:35:11+08:00"
    assert session["meta"]["notes"] == "test sidecar"
    assert session["meta"]["sample_rate_hz"] == 40.0
    assert session["meta"]["channel_info"]["rear_shock_dom_suspension [mm]"]["sensor"] == "rear_shock"
    assert session["meta"]["channel_info"]["rear_shock_dom_suspension [mm]"]["role"] == "disp"
    assert session["meta"]["device"]["firmware_version"] == "1.2.3"


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
    )

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
