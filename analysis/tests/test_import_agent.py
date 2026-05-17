import json
import os
import zipfile
from pathlib import Path

from bodaqs_analysis.import_agent import (
    ImportAgentSupervisor,
    ImportSourceRunner,
    load_import_source_config,
    load_import_sources,
    run_sources_once,
)
from bodaqs_analysis.preprocess_profile import (
    default_preprocess_config,
    make_preprocess_profile,
    save_preprocess_profile,
)


def _set_old_mtime(path: Path, *, seconds_ago: int = 120) -> None:
    ts = max(1, int(path.stat().st_mtime) - seconds_ago)
    os.utime(path, (ts, ts))


def _write_schema(path: Path) -> Path:
    path.write_text("events: []\n", encoding="utf-8")
    return path


def _write_preprocess_profile(path: Path, *, schema_path: Path) -> Path:
    config = default_preprocess_config()
    config["schema_path"] = schema_path.name
    profile = make_preprocess_profile("import_agent_test", config=config)
    save_preprocess_profile(profile, path)
    return path


def _write_bike_profile(path: Path) -> Path:
    bike_profile = {
        "schema": "bodaqs.bike_profile",
        "version": 1,
        "bike_profile_id": "import_agent_test_bike",
        "display_name": "Import Agent Test Bike",
        "normalization_ranges": [
            {
                "id": "front_suspension_range",
                "signal": {
                    "end": "front",
                    "quantity": "disp",
                    "domain": "suspension",
                    "unit": "mm",
                },
                "full_range": 170.0,
            },
            {
                "id": "rear_suspension_range",
                "signal": {
                    "end": "rear",
                    "quantity": "disp",
                    "domain": "suspension",
                    "unit": "mm",
                },
                "full_range": 65.0,
            },
        ],
        "signal_transforms": [],
    }
    path.write_text(json.dumps(bike_profile, indent=2), encoding="utf-8")
    return path


def _write_source_config(
    source_root: Path,
    *,
    artifacts_dir: Path,
    settle_time_s: float = 1.0,
    preprocess_profile_path: str = "preprocess_profile.json",
    bike_profile_path: str = "bike_profile.json",
) -> Path:
    payload = {
        "schema": "bodaqs.import_source",
        "version": 1,
        "source_id": source_root.name,
        "artifacts_dir": str(artifacts_dir),
        "preprocess_profile_path": preprocess_profile_path,
        "bike_profile_path": bike_profile_path,
        "inbox_dir": "inbox",
        "done_dir": "done",
        "failed_dir": "failed",
        "staging_dir": "staging",
        "archive_patterns": ["*.zip"],
        "logger_timezone": "Australia/Perth",
        "run_tz_label": "AWST",
        "poll_interval_s": 0.01,
        "settle_time_s": settle_time_s,
        "include_events": False,
        "include_metrics": False,
    }
    config_path = source_root / "import_source.json"
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return config_path


def _write_session_archive(
    inbox_dir: Path,
    *,
    stem: str,
    front_values: tuple[float, float, float] = (10.0, 11.0, 12.0),
    rear_values: tuple[float, float, float] = (20.0, 21.0, 22.0),
) -> Path:
    archive_path = inbox_dir / f"{stem}.zip"
    sidecar = {
        "contract": {
            "name": "mtb_logger_timeseries",
            "version": "0.2.0",
            "sidecar_kind": "session",
        },
        "session": {
            "session_id": stem,
            "started_at_local": "2026-05-16T10:00:00+08:00",
            "timezone": "Australia/Perth",
        },
        "data_file": {
            "delimiter": ",",
            "header": True,
        },
        "streams": {
            "primary": {
                "type": "uniform",
                "time_column": "time_s",
                "time_encoding": "elapsed_s",
                "time_unit": "s",
                "sample_rate_hz": 33.3333333,
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
            },
            "mark": {
                "class": "event_flag",
                "dtype": "bool",
                "stream": "primary",
            },
        },
    }

    csv_text = "\n".join(
        [
            "time_s,front_shock_dom_suspension [mm],rear_shock_dom_suspension [mm],mark",
            f"0.00,{front_values[0]},{rear_values[0]},0",
            f"0.03,{front_values[1]},{rear_values[1]},1",
            f"0.06,{front_values[2]},{rear_values[2]},0",
        ]
    )

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{stem}.CSV", csv_text)
        zf.writestr(f"{stem}.json", json.dumps(sidecar, indent=2))

    return archive_path


def _write_invalid_archive(inbox_dir: Path, *, name: str = "broken.zip") -> Path:
    archive_path = inbox_dir / name
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("session.csv", "time_s,value\n0.0,1.0\n")
    return archive_path


def _prepare_source(
    tmp_path: Path,
    name: str,
    artifacts_dir: Path,
    *,
    settle_time_s: float = 1.0,
    use_profile_dirs: bool = True,
) -> Path:
    source_root = tmp_path / name
    inbox_dir = source_root / "inbox"
    inbox_dir.mkdir(parents=True)

    if use_profile_dirs:
        settings_dir = source_root / "settings"
        bike_dir = source_root / "bike"
        settings_dir.mkdir()
        bike_dir.mkdir()
        schema_path = _write_schema(settings_dir / "event_schema.yaml")
        _write_preprocess_profile(settings_dir / "import_agent_test_settings.json", schema_path=schema_path)
        _write_bike_profile(bike_dir / "import_agent_test_bike.json")
        _write_source_config(
            source_root,
            artifacts_dir=artifacts_dir,
            settle_time_s=settle_time_s,
            preprocess_profile_path="settings",
            bike_profile_path="bike",
        )
    else:
        schema_path = _write_schema(source_root / "schema.yaml")
        _write_preprocess_profile(source_root / "preprocess_profile.json", schema_path=schema_path)
        _write_bike_profile(source_root / "bike_profile.json")
        _write_source_config(source_root, artifacts_dir=artifacts_dir, settle_time_s=settle_time_s)
    return source_root


def test_load_import_source_config_from_directory(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir)

    source = load_import_source_config(source_root)

    assert source.source_id == "source_a"
    assert source.inbox_dir == source_root / "inbox"
    assert source.preprocess_profile_path == source_root / "settings"
    assert source.bike_profile_path == source_root / "bike"


def test_run_sources_once_supports_explicit_profile_files(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_files", artifacts_dir, use_profile_dirs=False)
    archive_path = _write_session_archive(source_root / "inbox", stem="session_001")
    _set_old_mtime(archive_path)

    report = run_sources_once([source_root])

    assert report["totals"]["imported"] == 1
    done_archives = list((source_root / "done").glob("*.zip"))
    assert len(done_archives) == 1


def test_run_sources_once_imports_archive_and_moves_it_to_done(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir)
    archive_path = _write_session_archive(source_root / "inbox", stem="session_001")
    _set_old_mtime(archive_path)

    report = run_sources_once([source_root])

    assert report["totals"]["imported"] == 1
    assert report["totals"]["failed"] == 0
    assert not archive_path.exists()

    done_archives = list((source_root / "done").glob("*.zip"))
    assert len(done_archives) == 1

    record = report["sources"][0]["imported"][0]
    session_manifest = artifacts_dir / "runs" / record["run_id"] / "sessions" / record["session_id"] / "manifest.json"
    manifest = json.loads(session_manifest.read_text(encoding="utf-8"))

    assert manifest["source"]["original_archive_filename"] == "session_001.zip"
    assert manifest["source"]["archive_csv_member"] == "session_001.CSV"
    assert manifest["source"]["archive_log_metadata_member"] == "session_001.json"
    assert manifest["source"]["import_source_id"] == "source_a"


def test_run_sources_once_skips_duplicate_success_and_moves_duplicate_archive_to_done(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir)
    first_archive = _write_session_archive(source_root / "inbox", stem="session_001")
    _set_old_mtime(first_archive)

    first_report = run_sources_once([source_root])
    second_archive = _write_session_archive(source_root / "inbox", stem="session_001")
    _set_old_mtime(second_archive)
    second_report = run_sources_once([source_root])

    assert first_report["totals"]["imported"] == 1
    assert second_report["totals"]["imported"] == 0
    assert second_report["totals"]["skipped_succeeded"] == 1

    done_archives = list((source_root / "done").glob("*.zip"))
    assert len(done_archives) == 2


def test_run_sources_once_defers_unsettled_archive(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir, settle_time_s=3600.0)
    archive_path = _write_session_archive(source_root / "inbox", stem="session_001")

    report = run_sources_once([source_root])

    assert report["totals"]["imported"] == 0
    assert report["totals"]["failed"] == 0
    assert report["totals"]["deferred_unsettled"] == 1
    assert archive_path.exists()


def test_run_sources_once_moves_invalid_archive_to_failed(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir)
    broken_archive = _write_invalid_archive(source_root / "inbox")
    _set_old_mtime(broken_archive)

    report = run_sources_once([source_root])

    assert report["totals"]["failed"] == 1
    assert not broken_archive.exists()
    failed_archives = list((source_root / "failed").glob("*.zip"))
    assert len(failed_archives) == 1


def test_two_sources_can_target_shared_central_library(tmp_path):
    artifacts_dir = tmp_path / "central_artifacts"
    source_a = _prepare_source(tmp_path, "source_a", artifacts_dir)
    source_b = _prepare_source(tmp_path, "source_b", artifacts_dir)
    archive_a = _write_session_archive(source_a / "inbox", stem="session_a", rear_values=(20.0, 21.0, 22.0))
    archive_b = _write_session_archive(source_b / "inbox", stem="session_b", rear_values=(30.0, 31.0, 32.0))
    _set_old_mtime(archive_a)
    _set_old_mtime(archive_b)

    report = run_sources_once([source_a, source_b])

    assert report["totals"]["imported"] == 2
    run_dirs = [p for p in (artifacts_dir / "runs").iterdir() if p.is_dir()]
    assert len(run_dirs) == 2


def test_runner_validate_reports_missing_runtime_dirs_as_warnings(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = tmp_path / "source_a"
    source_root.mkdir()
    settings_dir = source_root / "settings"
    bike_dir = source_root / "bike"
    settings_dir.mkdir()
    bike_dir.mkdir()
    schema_path = _write_schema(settings_dir / "event_schema.yaml")
    _write_preprocess_profile(settings_dir / "import_agent_test_settings.json", schema_path=schema_path)
    _write_bike_profile(bike_dir / "import_agent_test_bike.json")
    _write_source_config(
        source_root,
        artifacts_dir=artifacts_dir,
        preprocess_profile_path="settings",
        bike_profile_path="bike",
    )

    runner = ImportSourceRunner(load_import_source_config(source_root))
    errors, warnings = runner.validate()

    assert errors == []
    assert len(warnings) == 4


def test_runner_validate_requires_exactly_one_valid_preprocess_profile_in_directory(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir)
    settings_dir = source_root / "settings"
    schema_path = settings_dir / "event_schema.yaml"
    _write_preprocess_profile(settings_dir / "second_settings_profile.json", schema_path=schema_path)

    runner = ImportSourceRunner(load_import_source_config(source_root))
    errors, _warnings = runner.validate()

    assert len(errors) == 1
    assert "Preprocess profile directory must contain exactly one valid JSON file" in errors[0]


def test_supervisor_snapshot_and_pause_resume(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_a = _prepare_source(tmp_path, "source_a", artifacts_dir)
    source_b = _prepare_source(tmp_path, "source_b", artifacts_dir)
    archive_a = _write_session_archive(source_a / "inbox", stem="session_a")
    archive_b = _write_session_archive(source_b / "inbox", stem="session_b")
    _set_old_mtime(archive_a)
    _set_old_mtime(archive_b)

    supervisor = ImportAgentSupervisor(load_import_sources([source_a, source_b]))
    supervisor.pause_source("source_b")

    report = supervisor.scan_all_once()

    assert report["totals"]["imported"] == 1
    assert report["skipped_paused_sources"] == ["source_b"]

    snapshot = supervisor.snapshot(now_s=100.0)
    source_states = {item["source_id"]: item for item in snapshot["sources"]}
    assert snapshot["source_count"] == 2
    assert snapshot["active_source_count"] == 1
    assert source_states["source_a"]["paused"] is False
    assert source_states["source_a"]["last_totals"]["imported"] == 1
    assert source_states["source_b"]["paused"] is True
    assert source_states["source_b"]["last_totals"] is None

    supervisor.resume_source("source_b")
    report_b = supervisor.scan_source_once("source_b", now_s=200.0)
    assert report_b is not None
    assert report_b["source_id"] == "source_b"


def test_supervisor_scan_due_respects_poll_interval(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir)
    first_archive = _write_session_archive(source_root / "inbox", stem="session_001")
    _set_old_mtime(first_archive)

    supervisor = ImportAgentSupervisor(load_import_sources([source_root]))

    first_reports = supervisor.scan_due(now_s=10.0)
    assert len(first_reports) == 1

    second_archive = _write_session_archive(source_root / "inbox", stem="session_002")
    _set_old_mtime(second_archive)

    second_reports = supervisor.scan_due(now_s=10.005)
    assert second_reports == []

    third_reports = supervisor.scan_due(now_s=10.02)
    assert len(third_reports) == 1
