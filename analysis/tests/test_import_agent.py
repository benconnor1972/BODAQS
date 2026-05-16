import json
import os
import zipfile
from pathlib import Path

from bodaqs_analysis.import_agent import (
    ImportSourceRunner,
    load_import_source_config,
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
    config["schema_path"] = str(schema_path)
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
) -> Path:
    payload = {
        "schema": "bodaqs.import_source",
        "version": 1,
        "source_id": source_root.name,
        "artifacts_dir": str(artifacts_dir),
        "preprocess_profile_path": "preprocess_profile.json",
        "bike_profile_path": "bike_profile.json",
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


def _prepare_source(tmp_path: Path, name: str, artifacts_dir: Path, *, settle_time_s: float = 1.0) -> Path:
    source_root = tmp_path / name
    inbox_dir = source_root / "inbox"
    inbox_dir.mkdir(parents=True)

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
    assert source.preprocess_profile_path == source_root / "preprocess_profile.json"


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
    schema_path = _write_schema(source_root / "schema.yaml")
    _write_preprocess_profile(source_root / "preprocess_profile.json", schema_path=schema_path)
    _write_bike_profile(source_root / "bike_profile.json")
    _write_source_config(source_root, artifacts_dir=artifacts_dir)

    runner = ImportSourceRunner(load_import_source_config(source_root))
    errors, warnings = runner.validate()

    assert errors == []
    assert len(warnings) == 4
