import json
import os
import sys
import zipfile
from importlib.resources import files
from pathlib import Path

import bodaqs_analysis.import_agent_provisioning as provisioning_module
import bodaqs_analysis.import_agent_setup as import_agent_setup_module
import bodaqs_analysis.import_agent_startup as import_agent_startup_module
import bodaqs_analysis.import_agent_tray as import_agent_tray_module
from bodaqs_analysis.import_agent import (
    ImportAgentSupervisor,
    ImportSourceRunner,
    load_import_source_config,
    load_import_sources,
    run_sources_once,
)
from bodaqs_analysis.import_agent_sources import (
    SOURCE_TYPE_FILESYSTEM_ARCHIVE,
    SOURCE_TYPE_LOGGER_WIFI,
)
from bodaqs_analysis.import_agent_provisioning import (
    ImportAgentLibraryConfig,
    ImportAgentManagedSourceConfig,
    default_import_agent_app_config_path,
    load_import_agent_app_config,
    managed_import_agent_source_roots,
    make_import_agent_app_config,
    provision_import_agent_app_setup,
    provision_import_agent_library_for_app,
    provision_import_agent_library,
    provision_import_agent_source_for_app,
    provision_import_agent_source,
    runtime_import_agent_app_config_path,
    save_import_agent_app_config,
    update_import_agent_app_auto_start,
    update_import_agent_source_enabled,
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


def _write_asset_package(package_dir: Path) -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    _write_schema(package_dir / "event schema - default.yaml")
    _write_preprocess_profile(package_dir / "suspension settings default.json", schema_path=Path("event schema - default.yaml"))
    _write_bike_profile(package_dir / "stumpjumper evo default.json")


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
    assert source.source_type == SOURCE_TYPE_FILESYSTEM_ARCHIVE
    assert source.inbox_dir == source_root / "inbox"
    assert source.preprocess_profile_path == source_root / "settings"
    assert source.bike_profile_path == source_root / "bike"


def test_load_import_source_config_parses_logger_wifi_source(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "wifi_source", artifacts_dir)
    config_path = source_root / "import_source.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["source_type"] = SOURCE_TYPE_LOGGER_WIFI
    payload["logger_wifi"] = {
        "logger_id": "Prototype E",
        "base_url": "http://192.168.4.1/",
        "request_timeout_s": 3,
        "download_timeout_s": 45,
        "require_upload_mode": True,
        "cleanup_mode": "move_to_uploaded",
    }
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    source = load_import_source_config(source_root)

    assert source.source_type == SOURCE_TYPE_LOGGER_WIFI
    assert source.logger_wifi is not None
    assert source.logger_wifi.logger_id == "Prototype E"
    assert source.logger_wifi.base_url == "http://192.168.4.1"
    assert source.logger_wifi.cleanup_mode == "move_to_uploaded"


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


def test_provision_import_agent_library_creates_artifact_store_dirs(tmp_path):
    libraries_root = tmp_path / "libraries"

    library = provision_import_agent_library(libraries_root, display_name="Alice Library")

    assert library.library_id == "alice-library"
    assert library.runs_dir.exists()
    assert library.state_dir.exists()
    metadata = json.loads(library.metadata_path.read_text(encoding="utf-8"))
    assert metadata["library_id"] == "alice-library"


def test_provision_import_agent_source_seeds_defaults_and_config_is_loadable(tmp_path):
    libraries_root = tmp_path / "libraries"
    sources_root = tmp_path / "sources"
    library = provision_import_agent_library(libraries_root, display_name="Alice Library")

    source = provision_import_agent_source(
        sources_root / "Alice Enduro",
        artifacts_dir=library.artifacts_dir,
        library_id=library.library_id,
        display_name="Alice Enduro",
        logger_timezone="Australia/Perth",
        run_tz_label="AWST",
        include_events=False,
        include_metrics=False,
    )

    loaded = load_import_source_config(source.source_root)
    preprocess_profile = json.loads(source.preprocess_profile_path.read_text(encoding="utf-8"))
    source_payload = json.loads(source.import_source_config_path.read_text(encoding="utf-8"))

    assert source.settings_dir.exists()
    assert source.bike_dir.exists()
    assert source.event_schema_path.exists()
    assert loaded.preprocess_profile_path == source.settings_dir
    assert loaded.bike_profile_path == source.bike_dir
    assert loaded.artifacts_dir == library.artifacts_dir
    assert loaded.source_type == SOURCE_TYPE_FILESYSTEM_ARCHIVE
    assert source_payload["source_type"] == SOURCE_TYPE_FILESYSTEM_ARCHIVE
    assert preprocess_profile["config"]["schema_path"] == "event_schema.yaml"


def test_provision_import_agent_source_can_seed_logger_wifi_config(tmp_path):
    libraries_root = tmp_path / "libraries"
    sources_root = tmp_path / "sources"
    library = provision_import_agent_library(libraries_root, display_name="Alice Library")

    source = provision_import_agent_source(
        sources_root / "Alice WiFi Logger",
        artifacts_dir=library.artifacts_dir,
        library_id=library.library_id,
        display_name="Alice WiFi Logger",
        source_type=SOURCE_TYPE_LOGGER_WIFI,
        logger_wifi={
            "logger_id": "Prototype E",
            "base_url": "http://192.168.4.1",
            "cleanup_mode": "none",
        },
        include_events=False,
        include_metrics=False,
    )

    loaded = load_import_source_config(source.source_root)

    assert source.source_type == SOURCE_TYPE_LOGGER_WIFI
    assert loaded.source_type == SOURCE_TYPE_LOGGER_WIFI
    assert loaded.logger_wifi is not None
    assert loaded.logger_wifi.logger_id == "Prototype E"


def test_provision_import_agent_source_discovers_nonstandard_asset_filenames(tmp_path, monkeypatch):
    asset_root = tmp_path / "asset_pkg_root"
    package_dir = asset_root / "temp_import_agent_assets"
    _write_asset_package(package_dir)
    monkeypatch.syspath_prepend(str(asset_root))
    monkeypatch.setattr(provisioning_module, "_ASSET_PACKAGE", "temp_import_agent_assets")

    libraries_root = tmp_path / "libraries"
    sources_root = tmp_path / "sources"
    library = provision_import_agent_library(libraries_root, display_name="Alice Library")

    source = provision_import_agent_source(
        sources_root / "Alice Enduro",
        artifacts_dir=library.artifacts_dir,
        library_id=library.library_id,
        display_name="Alice Enduro",
        include_events=False,
        include_metrics=False,
    )

    preprocess_profile = json.loads(source.preprocess_profile_path.read_text(encoding="utf-8"))

    assert source.preprocess_profile_path.name == "preprocess_profile.json"
    assert source.event_schema_path.name == "event_schema.yaml"
    assert source.bike_profile_path.name == "bike_profile.json"
    assert preprocess_profile["config"]["schema_path"] == "event_schema.yaml"


def test_import_agent_app_config_round_trip(tmp_path):
    libraries_root = tmp_path / "libraries"
    sources_root = tmp_path / "sources"
    library = provision_import_agent_library(libraries_root, display_name="Alice Library")
    source = provision_import_agent_source(
        sources_root / "Alice Enduro",
        artifacts_dir=library.artifacts_dir,
        library_id=library.library_id,
        display_name="Alice Enduro",
        include_events=False,
        include_metrics=False,
    )

    config = make_import_agent_app_config(
        sources_root=sources_root,
        libraries_root=libraries_root,
        libraries=[
            ImportAgentLibraryConfig(
                library_id=library.library_id,
                display_name=library.display_name,
                artifacts_dir=library.artifacts_dir,
            )
        ],
        sources=[
            ImportAgentManagedSourceConfig(
                source_id=source.source_id,
                display_name=source.display_name,
                source_root=source.source_root,
                library_id=library.library_id,
                enabled=True,
            )
        ],
        auto_start=True,
    )
    config_path = tmp_path / "app_config.json"
    save_import_agent_app_config(config, config_path)

    loaded = load_import_agent_app_config(config_path)

    assert loaded == config
    assert loaded.sources[0].source_type == SOURCE_TYPE_FILESYSTEM_ARCHIVE


def test_import_agent_app_config_defaults_legacy_source_type(tmp_path):
    libraries_root = tmp_path / "libraries"
    sources_root = tmp_path / "sources"
    library = provision_import_agent_library(libraries_root, display_name="Alice Library")
    source_root = sources_root / "Alice Enduro"
    source_root.mkdir(parents=True)
    config_path = tmp_path / "app_config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema": "bodaqs.import_agent_app",
                "version": 1,
                "sources_root": str(sources_root),
                "libraries_root": str(libraries_root),
                "libraries": [
                    {
                        "library_id": library.library_id,
                        "display_name": library.display_name,
                        "artifacts_dir": str(library.artifacts_dir),
                    }
                ],
                "sources": [
                    {
                        "source_id": "alice-enduro",
                        "display_name": "Alice Enduro",
                        "source_root": str(source_root),
                        "library_id": library.library_id,
                        "enabled": True,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = load_import_agent_app_config(config_path)

    assert loaded.sources[0].source_type == SOURCE_TYPE_FILESYSTEM_ARCHIVE


def test_default_import_agent_app_config_path_uses_windows_convention():
    win_path = default_import_agent_app_config_path(
        platform="win32",
        env={"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"},
        home=r"C:\Users\Test",
    )

    assert win_path == Path(r"C:\Users\Test\AppData\Local\BODAQS\import-agent\import_agent_app.json")


def test_runtime_import_agent_app_config_path_prefers_writable_directory(tmp_path):
    preferred_dir = tmp_path / "bundle"
    preferred_dir.mkdir()

    config_path = runtime_import_agent_app_config_path(preferred_dir=preferred_dir)

    assert config_path == preferred_dir.resolve() / "import_agent_app.json"


def test_runtime_import_agent_app_config_path_installed_mode_uses_appdata_even_when_bundle_dir_is_writable(tmp_path):
    preferred_dir = tmp_path / "bundle"
    preferred_dir.mkdir()

    config_path = runtime_import_agent_app_config_path(
        preferred_dir=preferred_dir,
        mode="installed",
        platform="win32",
        env={"LOCALAPPDATA": str(tmp_path / "AppData" / "Local")},
        home=tmp_path,
    )

    assert config_path == (
        tmp_path / "AppData" / "Local" / "BODAQS" / "import-agent" / "import_agent_app.json"
    ).resolve()


def test_runtime_import_agent_app_config_path_falls_back_when_preferred_directory_is_missing_file(tmp_path):
    preferred_file = tmp_path / "not_a_directory.txt"
    preferred_file.write_text("x", encoding="utf-8")

    config_path = runtime_import_agent_app_config_path(
        preferred_dir=preferred_file,
        platform="win32",
        env={"LOCALAPPDATA": str(tmp_path / "AppData" / "Local")},
        home=tmp_path,
    )

    assert config_path == (
        tmp_path / "AppData" / "Local" / "BODAQS" / "import-agent" / "import_agent_app.json"
    ).resolve()


def test_available_logger_timezones_includes_blank_option_and_sorted_values(monkeypatch):
    monkeypatch.setattr(
        import_agent_setup_module,
        "available_timezones",
        lambda: {"Europe/Paris", "Australia/Perth", "UTC"},
    )

    values = import_agent_setup_module.available_logger_timezones()

    assert values[0] == ""
    assert values[1:] == ["Australia/Perth", "Europe/Paris", "UTC"]


def test_provision_import_agent_app_setup_creates_seeded_desktop_setup(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"

    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
        logger_timezone="Australia/Perth",
        run_tz_label="AWST",
        include_events=False,
        include_metrics=False,
    )

    config = load_import_agent_app_config(app_config_path)

    assert provisioned.app_config_path == app_config_path.resolve()
    assert provisioned.library.artifacts_dir.exists()
    assert provisioned.source.import_source_config_path.exists()
    assert len(config.libraries) == 1
    assert config.libraries[0].library_id == "alice-library"
    assert len(config.sources) == 1
    assert config.sources[0].source_id == "alice-enduro"


def test_provision_import_agent_app_setup_merges_additional_source_and_library(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    sources_root = tmp_path / "sources"
    libraries_root = tmp_path / "libraries"

    first = provision_import_agent_app_setup(
        sources_root=sources_root,
        libraries_root=libraries_root,
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    second = provision_import_agent_app_setup(
        sources_root=sources_root,
        libraries_root=libraries_root,
        library_display_name="Ben Library",
        source_display_name="Ben DH",
        app_config_path=app_config_path,
    )

    config = load_import_agent_app_config(app_config_path)

    assert first.library.library_id == "alice-library"
    assert second.library.library_id == "ben-library"
    assert {item.library_id for item in config.libraries} == {"alice-library", "ben-library"}
    assert {item.source_id for item in config.sources} == {"alice-enduro", "ben-dh"}


def test_provision_import_agent_library_for_app_adds_library_to_existing_config(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )

    updated, library = provision_import_agent_library_for_app(
        app_config_path,
        display_name="Ben Library",
    )

    assert library.library_id == "ben-library"
    assert {item.library_id for item in updated.libraries} == {"alice-library", "ben-library"}


def test_provision_import_agent_source_for_app_adds_source_to_selected_library(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
        include_events=False,
        include_metrics=False,
    )

    updated, source = provision_import_agent_source_for_app(
        app_config_path,
        library_id=provisioned.library.library_id,
        display_name="Alice DH",
        include_events=False,
        include_metrics=False,
    )

    assert source.library_id == provisioned.library.library_id
    assert {item.source_id for item in updated.sources} == {"alice-enduro", "alice-dh"}
    assert source.source_root.exists()


def test_provision_import_agent_source_for_app_persists_logger_wifi_source(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
        include_events=False,
        include_metrics=False,
    )

    _updated, source = provision_import_agent_source_for_app(
        app_config_path,
        library_id=provisioned.library.library_id,
        display_name="Prototype E WiFi",
        source_type=SOURCE_TYPE_LOGGER_WIFI,
        logger_wifi={
            "logger_id": "Prototype E",
            "base_url": "http://192.168.4.1",
            "cleanup_mode": "move_to_uploaded",
        },
        include_events=False,
        include_metrics=False,
    )

    reloaded_app_config = load_import_agent_app_config(app_config_path)
    reloaded_source = load_import_source_config(source.source_root)
    managed_wifi_source = next(item for item in reloaded_app_config.sources if item.source_id == source.source_id)

    assert managed_wifi_source.source_type == SOURCE_TYPE_LOGGER_WIFI
    assert reloaded_source.source_type == SOURCE_TYPE_LOGGER_WIFI
    assert reloaded_source.logger_wifi is not None
    assert reloaded_source.logger_wifi.logger_id == "Prototype E"
    assert reloaded_source.logger_wifi.base_url == "http://192.168.4.1"
    assert reloaded_source.logger_wifi.cleanup_mode == "move_to_uploaded"


def test_update_import_agent_source_enabled_persists_and_filters_enabled_roots(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )

    disabled = update_import_agent_source_enabled(
        app_config_path,
        source_id=provisioned.source.source_id,
        enabled=False,
    )

    assert disabled.sources[0].enabled is False
    assert managed_import_agent_source_roots(disabled, enabled_only=True) == []


def test_update_import_agent_app_auto_start_persists(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
        auto_start=False,
    )

    updated = update_import_agent_app_auto_start(app_config_path, enabled=True)

    assert updated.auto_start is True
    assert load_import_agent_app_config(app_config_path).auto_start is True


class _FakeRegistryKey:
    def __init__(self, storage: dict[str, str], path: str) -> None:
        self.storage = storage
        self.path = path

    def Close(self) -> None:
        return None


class _FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_READ = 0x1
    KEY_SET_VALUE = 0x2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def CreateKeyEx(self, root: object, path: str, reserved: int, access: int) -> _FakeRegistryKey:
        return _FakeRegistryKey(self.values, path)

    def OpenKey(self, root: object, path: str, reserved: int, access: int) -> _FakeRegistryKey:
        return _FakeRegistryKey(self.values, path)

    def SetValueEx(self, key: _FakeRegistryKey, value_name: str, reserved: int, value_type: int, value: str) -> None:
        self.values[(key.path, value_name)] = value

    def QueryValueEx(self, key: _FakeRegistryKey, value_name: str) -> tuple[str, int]:
        storage_key = (key.path, value_name)
        if storage_key not in self.values:
            raise FileNotFoundError(storage_key)
        return self.values[storage_key], self.REG_SZ

    def DeleteValue(self, key: _FakeRegistryKey, value_name: str) -> None:
        storage_key = (key.path, value_name)
        if storage_key not in self.values:
            raise FileNotFoundError(storage_key)
        del self.values[storage_key]


def test_build_windows_startup_command_quotes_paths_with_spaces(tmp_path):
    exe_path = tmp_path / "Program Files" / "bodaqs-import-setup.exe"
    config_path = tmp_path / "App Data" / "import_agent_app.json"
    command = import_agent_startup_module.build_windows_startup_command(
        [
            exe_path,
            "--app-config",
            str(config_path),
            "--startup-launch",
        ]
    )

    assert f'"{exe_path.resolve()}"' in command
    assert f'"{config_path.resolve()}"' in command
    assert "--startup-launch" in command


def test_build_import_agent_tray_image_returns_square_rgba_image():
    image = import_agent_tray_module.build_import_agent_tray_image(size=48)

    assert image.size == (48, 48)
    assert image.mode == "RGBA"


def test_load_import_agent_tray_image_uses_packaged_asset():
    image = import_agent_tray_module.load_import_agent_tray_image()

    assert image.size == (256, 256)
    assert image.mode == "RGBA"


def test_import_agent_window_icon_asset_exists():
    asset = files("bodaqs_analysis.import_agent_assets").joinpath("app_icon.png")
    with asset.open("rb") as handle:
        payload = handle.read()

    assert len(payload) > 0


def test_import_agent_window_icon_ico_asset_exists():
    asset = files("bodaqs_analysis.import_agent_assets").joinpath("app_icon.ico")
    with asset.open("rb") as handle:
        payload = handle.read()

    assert len(payload) > 0


def test_tray_supported_is_false_for_non_windows_platform():
    assert import_agent_tray_module.tray_supported(platform="linux") is False


def test_sync_windows_startup_registration_round_trips_command_with_fake_registry():
    fake_reg = _FakeWinreg()
    command = '"C:\\Program Files\\BODAQS Import Agent\\manager\\bodaqs-import-setup.exe" --startup-launch'

    stored = import_agent_startup_module.sync_windows_startup_registration(
        enabled=True,
        command=command,
        registry_module=fake_reg,
        platform="win32",
    )
    read_back = import_agent_startup_module.read_windows_startup_registration(
        registry_module=fake_reg,
        platform="win32",
    )

    assert stored == command
    assert read_back == command

    cleared = import_agent_startup_module.sync_windows_startup_registration(
        enabled=False,
        registry_module=fake_reg,
        platform="win32",
    )

    assert cleared is None
    assert (
        import_agent_startup_module.read_windows_startup_registration(
            registry_module=fake_reg,
            platform="win32",
        )
        is None
    )
