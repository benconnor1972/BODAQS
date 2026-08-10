import binascii
import json
import math
import os
import re
import shutil
import stat
import struct
import sys
import zipfile
from importlib.resources import files
from pathlib import Path

import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _package_root in (_REPO_ROOT / "analysis", _REPO_ROOT / "import-manager"):
    _package_root_text = str(_package_root)
    if _package_root_text not in sys.path:
        sys.path.insert(0, _package_root_text)

import bodaqs_import_manager.import_agent_provisioning as provisioning_module
import bodaqs_import_manager.import_agent_single_instance as single_instance_module
import bodaqs_import_manager.import_agent_setup as import_agent_setup_module
import bodaqs_import_manager.import_agent_startup as import_agent_startup_module
import bodaqs_import_manager.import_agent_tray as import_agent_tray_module
import bodaqs_analysis.library_preprocessing as library_preprocessing
from bodaqs_analysis.exporters.data_syn_bike import (
    data_syn_bike_manual_settings,
    default_data_syn_bike_export_config,
    export_data_syn_bike_resolved,
    render_data_syn_bike_manual_settings_text,
    write_data_syn_bike_exports,
)
from bodaqs_analysis.import_agent import (
    ImportAgentSupervisor,
    ImportSourceRunner,
    load_import_source_config,
    load_import_sources,
    run_sources_once,
)
from bodaqs_analysis.library_preprocessing import (
    PreprocessBatchRequest,
    batch_result_to_study_set,
    preprocess_requested_sessions_to_library,
)
from bodaqs_analysis.import_agent_sources import (
    SOURCE_TYPE_FILESYSTEM_ARCHIVE,
    SOURCE_TYPE_LOGGER_WIFI,
)
from bodaqs_analysis.widgets.histogram_core import compute_trimmed_quantile_metrics
from bodaqs_import_manager.import_agent_provisioning import (
    ImportAgentLibraryConfig,
    ImportAgentManagedSourceConfig,
    adopt_import_agent_existing_workspace,
    check_import_agent_workspace_sync,
    default_import_agent_app_config_path,
    discover_import_agent_libraries,
    load_managed_import_source_configs,
    load_import_agent_app_config,
    managed_import_agent_source_roots,
    make_import_agent_app_config,
    provision_import_agent_app_setup,
    provision_import_agent_library_for_app,
    provision_import_agent_library,
    provision_import_agent_source_for_app,
    provision_import_agent_source,
    remove_import_agent_library,
    remove_import_agent_source,
    runtime_import_agent_app_config_path,
    save_import_agent_app_config,
    sync_import_agent_workspace_from_roots,
    update_import_agent_app_auto_start,
    update_import_agent_library_data_syn_bike_export_enabled,
    update_import_agent_library_display_name,
    update_import_agent_source_bike_profile,
    update_import_agent_source_display_name,
    update_import_agent_source_force_reprocess_enabled,
    update_import_agent_source_preprocess_profile,
    update_import_agent_source_session_naming,
    update_import_agent_source_session_note_attach_enabled,
    update_import_agent_source_enabled,
    update_import_agent_source_library,
    update_import_agent_source_logger_wifi,
)
from bodaqs_import_manager.import_agent_profile_builders import (
    apply_bike_profile_form_values,
    bike_profile_form_values,
    build_custom_session_note_field,
    build_session_note_template_from_field_ids,
    copy_source_note_assets,
    derive_profile_id,
    front_head_angle_from_profile,
    front_vertical_transform_from_profile,
    load_session_note_field_catalog,
    load_source_bike_profile,
    load_source_session_note_template,
    normalize_rear_lut_with_endpoints,
    parse_lut_text,
    rear_wheel_lut_from_profile,
    save_bike_profile_path,
    save_source_bike_profile,
    save_source_session_note_assets,
    set_rear_wheel_lut_transform,
)
from bodaqs_analysis.preprocess_profile import (
    default_preprocess_config,
    make_preprocess_profile,
    save_preprocess_profile,
)
from bodaqs_analysis.session_archive import (
    prepare_session_input,
    raw_session_identity,
    read_session_archive_contract,
    session_input_identity,
    sha256_file,
)
from bodaqs_analysis.session_notes import build_session_catalog_df
from bodaqs_analysis.ui.preprocess_file_selector import load_processed_sha256_set
from tools.smoke_test_packaged_imu_bdq import imu_int16_bdq_fixture_bytes


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
                "id": "front_wheel_range",
                "signal": {
                    "end": "front",
                    "quantity": "disp",
                    "domain": "wheel",
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
            {
                "id": "rear_wheel_range",
                "signal": {
                    "end": "rear",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                },
                "full_range": 150.0,
            },
        ],
        "signal_transforms": [],
    }
    path.write_text(json.dumps(bike_profile, indent=2), encoding="utf-8")
    return path


def _write_session_note_template(path: Path) -> Path:
    template = {
        "schema": "bodaqs.session_notes.template",
        "version": 1,
        "template_id": "import_agent_test_setup",
        "template_version": "1.0",
        "title": "Import agent test setup",
        "description": "Test template for import-agent draft notes.",
        "allow_custom_fields": True,
        "fields": [
            {
                "field_id": "bike",
                "label": "Bike",
                "field_type": "string",
                "section": "Bike",
                "default": "",
                "project_to_catalog": True,
            },
            {
                "field_id": "fork",
                "label": "Fork",
                "field_type": "string",
                "section": "Front",
                "default": "",
                "project_to_catalog": True,
            },
            {
                "field_id": "rear_air_pressure_psi",
                "label": "Rear pressure",
                "field_type": "float",
                "section": "Rear",
                "unit": "psi",
                "project_to_catalog": True,
            },
            {
                "field_id": "front_sag_pct",
                "label": "Front sag",
                "field_type": "float",
                "section": "Front",
                "unit": "%",
                "project_to_catalog": True,
            },
        ],
    }
    path.write_text(json.dumps(template, indent=2), encoding="utf-8")
    return path


def _write_bike_setup_preset(path: Path, *, bike_profile_id: str = "import_agent_test_bike") -> Path:
    preset = {
        "schema": "bodaqs.session_note_preset",
        "version": 1,
        "preset_id": "test_setup",
        "display_name": "Test setup",
        "template_id": "import_agent_test_setup",
        "template_version": "1.0",
        "bike_profile_id": bike_profile_id,
        "title": "Imported test setup",
        "values": {
            "bike": "Import Agent Test Bike",
            "fork": "Test Fork",
            "rear_air_pressure_psi": 185.0,
        },
        "custom_values": {},
        "free_text_notes": "Created from test preset.",
    }
    path.write_text(json.dumps(preset, indent=2), encoding="utf-8")
    return path


def _write_asset_package(package_dir: Path) -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    _write_schema(package_dir / "event schema - default.yaml")
    _write_preprocess_profile(package_dir / "suspension settings default.json", schema_path=Path("event schema - default.yaml"))
    _write_bike_profile(package_dir / "stumpjumper evo default.json")
    _write_session_note_template(package_dir / "source note template.json")
    _write_bike_setup_preset(package_dir / "source setup preset.json")


def _write_source_config(
    source_root: Path,
    *,
    artifacts_dir: Path,
    settle_time_s: float = 1.0,
    preprocess_profile_path: str = "preprocess_profile.json",
    bike_profile_path: str = "bike_profile.json",
    session_note: dict | None = None,
    force_reprocess: bool = False,
    naming: dict | None = None,
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
        "force_reprocess": bool(force_reprocess),
    }
    if session_note is not None:
        payload["session_note"] = session_note
    if naming is not None:
        payload["naming"] = naming
    config_path = source_root / "import_source.json"
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return config_path


def _write_session_archive(
    inbox_dir: Path,
    *,
    stem: str,
    front_values: tuple[float, float, float] = (10.0, 11.0, 12.0),
    rear_values: tuple[float, float, float] = (20.0, 21.0, 22.0),
    metadata_note: str | None = None,
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
    if metadata_note is not None:
        sidecar["session"]["notes"] = metadata_note

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


_BDQ_FILE_HEADER = struct.Struct("<8sHHIQII")
_BDQ_CHUNK_HEADER = struct.Struct("<4sHHIII")
_BDQ_DATA_HEADER = struct.Struct("<IIQHH")
_BDQ_FRAME = struct.Struct("<IffH")


def _bdq_crc32(payload: bytes) -> int:
    return binascii.crc32(payload) & 0xFFFFFFFF


def _bdq_chunk(chunk_type: int, sequence: int, payload: bytes) -> bytes:
    return _BDQ_CHUNK_HEADER.pack(b"BDQC", 1, chunk_type, sequence, len(payload), _bdq_crc32(payload)) + payload


def _bdq_json_chunk(chunk_type: int, sequence: int, payload: dict) -> bytes:
    return _bdq_chunk(chunk_type, sequence, json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _write_bdq_input(
    inbox_dir: Path,
    *,
    stem: str,
    front_values: tuple[float, float, float] = (10.0, 11.0, 12.0),
    rear_values: tuple[float, float, float] = (20.0, 21.0, 22.0),
) -> Path:
    bdq_path = inbox_dir / f"{stem}.bdq"
    metadata = {
        "format": "bdq.v1",
        "format_name": "BDQLOG v1",
        "device_id": "Prototype_E",
        "firmware_name": "BODAQS Firmware",
        "firmware_version": "0.3.0",
        "recording_id": stem,
        "path": f"/{stem}.bdq",
        "created_unix_us": 1_768_998_942_000_000,
        "sample_rate_hz": 33,
        "sample_period_us": 30_000,
        "timezone": "Australia/Perth",
        "started_at_utc": "2026-05-16T02:00:00Z",
        "started_at_local": "2026-05-16T10:00:00+08:00",
        "log_format": "bodaqs_compact_binary",
    }
    schema = {
        "schema_format": "bdq.channel_schema.v1",
        "frame_layout": "fixed_mixed_v1",
        "endianness": "little",
        "frame_size_bytes": _BDQ_FRAME.size,
        "timebase": {
            "type": "fixed_rate",
            "sample_rate_hz": 33,
            "sample_period_us": 30_000,
            "timestamp_per_sample": False,
        },
        "channels": [
            {
                "field": "sample_id",
                "quantity": "sample_index",
                "unit": "sample",
                "storage_type": "uint32",
                "byte_offset": 0,
                "source": "frame",
                "raw": False,
            },
            {
                "field": "front_suspension_disp",
                "quantity": "disp",
                "unit": "mm",
                "storage_type": "float32",
                "byte_offset": 4,
                "sensor": "front_shock",
                "source": "linear_calibrated",
                "raw": False,
            },
            {
                "field": "rear_suspension_disp",
                "quantity": "disp",
                "unit": "mm",
                "storage_type": "float32",
                "byte_offset": 8,
                "sensor": "rear_shock",
                "source": "linear_calibrated",
                "raw": False,
            },
            {
                "field": "flags",
                "quantity": "flags",
                "unit": "bitfield",
                "storage_type": "uint16",
                "byte_offset": 12,
                "source": "frame",
                "raw": False,
            },
        ],
        "sample_flags": {"mark": 1},
    }
    rows = [
        _BDQ_FRAME.pack(i, float(front_values[i]), float(rear_values[i]), 1 if i == 1 else 0)
        for i in range(3)
    ]
    data_payload = _BDQ_DATA_HEADER.pack(0, len(rows), 1_768_998_942_000_000, _BDQ_FRAME.size, 0) + b"".join(rows)
    header = _BDQ_FILE_HEADER.pack(b"BDQLOG\x00\x01", 1, 0, _BDQ_FILE_HEADER.size, metadata["created_unix_us"], 0, 0)
    bdq_path.write_bytes(
        header
        + _bdq_json_chunk(1, 0, metadata)
        + _bdq_json_chunk(2, 1, schema)
        + _bdq_chunk(3, 2, data_payload)
        + _bdq_json_chunk(5, 3, {"summary_format": "bdq.final_summary.v1", "samples_written": 3})
    )
    return bdq_path


def _write_invalid_archive(inbox_dir: Path, *, name: str = "broken.zip") -> Path:
    archive_path = inbox_dir / name
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("session.csv", "time_s,value\n0.0,1.0\n")
    return archive_path


def test_session_archive_contract_requires_same_stem_csv_and_metadata(tmp_path):
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("session_a.CSV", "time_s\n0.0\n")
        zf.writestr("session_b.json", "{}")

    with pytest.raises(ValueError, match="share the same stem"):
        read_session_archive_contract(archive_path)


def test_session_archive_identity_includes_csv_and_metadata_hashes(tmp_path):
    archive_path = _write_session_archive(tmp_path, stem="session_001")

    contract = read_session_archive_contract(archive_path)
    identity = session_input_identity(archive_path)

    assert contract.session_stem == "session_001"
    assert identity.source_identity_kind == "raw_session_identity"
    assert identity.source_identity == raw_session_identity(
        csv_sha256=contract.csv_sha256,
        log_metadata_sha256=contract.log_metadata_sha256,
    )


def test_prepare_session_input_extracts_archive_and_builds_manifest(tmp_path):
    archive_path = _write_session_archive(tmp_path, stem="session_001")

    with prepare_session_input(archive_path) as session_input:
        assert session_input.csv_path.exists()
        assert session_input.log_metadata_path is not None
        assert session_input.log_metadata_path.exists()
        manifest = session_input.source_manifest(source_sha256=sha256_file(session_input.csv_path))

    assert manifest["path"] == "source/input.csv"
    assert manifest["input_kind"] == "archive"
    assert manifest["archive_csv_member"] == "session_001.CSV"
    assert manifest["archive_log_metadata_member"] == "session_001.json"
    assert manifest["raw_session_identity"] == session_input.source_identity


def test_prepare_session_input_accepts_bdq_file(tmp_path):
    bdq_path = _write_bdq_input(tmp_path, stem="260516_201542")

    identity = session_input_identity(bdq_path)
    with prepare_session_input(bdq_path) as session_input:
        manifest = session_input.source_manifest(source_path="source/input.bdq")

    assert identity.input_kind == "bdq"
    assert identity.source_identity_kind == "bdq_session_identity"
    assert session_input.input_kind == "bdq"
    assert session_input.csv_path == bdq_path.resolve()
    assert manifest["path"] == "source/input.bdq"
    assert manifest["input_kind"] == "bdq"
    assert manifest["original_bdq_filename"] == "260516_201542.bdq"
    assert manifest["source_identity"] == identity.source_identity


def test_processed_identity_loader_reads_raw_session_identity(tmp_path):
    archive_path = _write_session_archive(tmp_path, stem="session_001")
    identity = session_input_identity(archive_path)

    manifest_path = tmp_path / "artifacts" / "runs" / "run_1" / "sessions" / "session_001" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"source": {"path": "source/input.csv", "raw_session_identity": identity.source_identity}}),
        encoding="utf-8",
    )

    assert identity.source_identity in load_processed_sha256_set(tmp_path / "artifacts")


def test_metadata_change_changes_archive_source_identity(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    first = _write_session_archive(first_dir, stem="session_001", metadata_note="first")
    second = _write_session_archive(second_dir, stem="session_001", metadata_note="second")

    assert session_input_identity(first).source_identity != session_input_identity(second).source_identity


def test_manual_preprocessing_batch_writes_one_run_and_draft_notes(tmp_path, monkeypatch):
    schema_path = _write_schema(tmp_path / "event_schema.yaml")
    profile_path = _write_preprocess_profile(tmp_path / "preprocess_profile.json", schema_path=schema_path)
    bike_profile_path = _write_bike_profile(tmp_path / "bike_profile.json")
    template_path = _write_session_note_template(tmp_path / "note_template.json")
    first_csv = tmp_path / "session_a.csv"
    second_csv = tmp_path / "session_b.csv"
    first_csv.write_text("time_s,value\n0,1\n1,2\n", encoding="utf-8")
    second_csv.write_text("time_s,value\n0,3\n1,4\n", encoding="utf-8")

    def fake_preprocess_session(csv_path, *_args, **_kwargs):
        session_id = Path(csv_path).stem
        return {
            "session": {
                "session_id": session_id,
                "df": pd.DataFrame({"time_s": [0.0, 1.0], "value": [1.0, 2.0]}),
                "meta": {"signals": {}},
                "source": {},
            },
            "events": pd.DataFrame(),
            "metrics": pd.DataFrame(),
        }

    monkeypatch.setattr(library_preprocessing, "preprocess_session", fake_preprocess_session)

    result = preprocess_requested_sessions_to_library(
        PreprocessBatchRequest(
            artifacts_dir=tmp_path / "library",
            input_paths=(first_csv, second_csv),
            preprocess_profile_path=profile_path,
            bike_profile_path=bike_profile_path,
            run_description="Manual batch",
            attach_draft_note=True,
            session_note_template_path=template_path,
        )
    )

    run_manifest = json.loads(Path(result["run_manifest_path"]).read_text(encoding="utf-8"))
    assert run_manifest["description"] == "Manual batch"
    assert run_manifest["sessions"] == ["session_a", "session_b"]
    assert run_manifest["pipeline_config"]["batch_policy"] == "one_run_per_requested_batch"
    assert run_manifest["pipeline_config"]["success_count"] == 2
    assert run_manifest["pipeline_config"]["failure_count"] == 0

    run_id = result["run_id"]
    note_path = (
        tmp_path
        / "library"
        / "runs"
        / run_id
        / "sessions"
        / "session_a"
        / "annotations"
        / "session_notes.json"
    )
    note = json.loads(note_path.read_text(encoding="utf-8"))
    assert note["draft"] is True
    assert note["template_id"] == "import_agent_test_setup"
    assert note["values"]["bike"] == ""
    assert note["source_context"]["origin"] == "manual_preprocessing"

    copied_template = (
        tmp_path
        / "library"
        / "library"
        / "session_note_templates"
        / "import_agent_test_setup"
        / "1.0.json"
    )
    assert copied_template.exists()
    revision = result["library_catalog_revision"]
    assert revision["schema"] == "bodaqs.library_catalog_revision"
    assert revision["reason"] == "manual_preprocessing_sessions_written"
    assert revision["actor"] == "library_preprocessing"
    assert [row["session_id"] for row in revision["changed_sessions"]] == ["session_a", "session_b"]

    study_set = batch_result_to_study_set(result, library_id="default-library")
    assert study_set["study_set_id"].startswith("unsaved-")
    assert [row["session_id"] for row in study_set["sessions"]] == ["session_a", "session_b"]


def test_data_syn_bike_export_can_scale_calibrated_raw_to_full_adc_range():
    session = {
        "session_id": "session_001",
        "df": pd.DataFrame(
            {
                "time_s": [0.0, 0.01],
                "front_raw [counts]": [100.0, 200.0],
                "rear_raw [counts]": [1000.0, 1500.0],
            }
        ),
        "meta": {
            "signals": {
                "front_raw [counts]": {
                    "end": "front",
                    "quantity": "raw",
                    "domain": "suspension",
                    "unit": "counts",
                    "calibration": {
                        "type": "linear",
                        "input_unit": "counts",
                        "output_unit": "mm",
                        "sensor_zero_count": 100,
                        "sensor_full_count": 200,
                        "sensor_full_travel": 170,
                    },
                },
                "rear_raw [counts]": {
                    "end": "rear",
                    "quantity": "raw",
                    "domain": "suspension",
                    "unit": "counts",
                    "calibration": {
                        "type": "linear",
                        "input_unit": "counts",
                        "output_unit": "mm",
                        "sensor_zero_count": 1000,
                        "sensor_full_count": 1500,
                        "sensor_full_travel": 65,
                    },
                },
            }
        },
    }
    config = default_data_syn_bike_export_config(
        raw_scale_mode="calibrated_full_scale",
        raw_full_scale_by_end={"front": 170, "rear": 65},
        adc_bit_count=12,
        drop_inactive=False,
    )

    result = export_data_syn_bike_resolved(session, export_config=config)
    exported = result["exports"][0]["dataframe"]

    assert exported["Front Raw"].tolist() == [0, 4095]
    assert exported["Rear Raw"].tolist() == [0, 4095]
    assert result["exports"][0]["metadata"]["front_raw_scale"]["status"] == "ok"
    assert result["exports"][0]["metadata"]["rear_raw_scale"]["target_full_range"] == 65.0


def test_data_syn_bike_export_infers_raw_direction_from_installed_zero():
    session = {
        "session_id": "session_001",
        "df": pd.DataFrame(
            {
                "time_s": [0.0, 0.01],
                "front_raw [counts]": [4095.0, 3071.25],
                "rear_raw [counts]": [0.0, 2047.5],
            }
        ),
        "meta": {
            "signals": {
                "front_raw [counts]": {
                    "end": "front",
                    "quantity": "raw",
                    "domain": "suspension",
                    "unit": "counts",
                    "calibration": {
                        "type": "linear",
                        "input_unit": "counts",
                        "output_unit": "mm",
                        "installed_zero_count": 4095,
                        "sensor_zero_count": 0,
                        "sensor_full_count": 4095,
                        "sensor_full_travel": 170,
                        "invert": False,
                    },
                },
                "rear_raw [counts]": {
                    "end": "rear",
                    "quantity": "raw",
                    "domain": "suspension",
                    "unit": "counts",
                    "calibration": {
                        "type": "linear",
                        "input_unit": "counts",
                        "output_unit": "mm",
                        "installed_zero_count": 0,
                        "sensor_zero_count": 0,
                        "sensor_full_count": 4095,
                        "sensor_full_travel": 65,
                    },
                },
            }
        },
    }
    config = default_data_syn_bike_export_config(
        raw_scale_mode="calibrated_full_scale",
        raw_full_scale_by_end={"front": 170, "rear": 65},
        adc_bit_count=12,
        drop_inactive=False,
    )

    result = export_data_syn_bike_resolved(session, export_config=config)
    exported = result["exports"][0]["dataframe"]

    assert exported["Front Raw"].tolist() == [0, 1024]
    assert result["exports"][0]["metadata"]["front_raw_scale"]["inverted"] is True
    assert (
        result["exports"][0]["metadata"]["front_raw_scale"]["inversion_reason"]
        == "raw_values_decrease_from_zero_reference"
    )


def test_data_syn_bike_export_can_emit_processed_wheel_travel_as_synthetic_raw():
    session = {
        "session_id": "session_001",
        "df": pd.DataFrame(
            {
                "time_s": [0.0, 0.01, 0.02, 0.03],
                "front_wheel_disp_dom_wheel [mm]": [-5.0, 0.0, 75.0, 150.0],
                "rear_wheel_disp_dom_wheel [mm]": [0.0, 82.5, 165.0, 200.0],
            }
        ),
        "meta": {
            "signals": {
                "front_wheel_disp_dom_wheel [mm]": {
                    "end": "front",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                    "origin": "analysis",
                    "processing_role": "primary_analysis",
                },
                "rear_wheel_disp_dom_wheel [mm]": {
                    "end": "rear",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                    "origin": "analysis",
                    "processing_role": "primary_analysis",
                },
            }
        },
    }
    config = default_data_syn_bike_export_config(
        raw_scale_mode="processed_wheel_travel",
        raw_full_scale_by_end={"front": 150, "rear": 165},
        adc_bit_count=12,
        drop_inactive=False,
    )

    result = export_data_syn_bike_resolved(session, export_config=config)
    exported = result["exports"][0]["dataframe"]

    assert exported["Front Raw"].tolist() == [0, 0, 2048, 4095]
    assert exported["Rear Raw"].tolist() == [0, 2048, 4095, 4095]
    assert result["summary"]["front_raw_col"] == "front_wheel_disp_dom_wheel [mm]"
    assert result["summary"]["rear_raw_col"] == "rear_wheel_disp_dom_wheel [mm]"
    assert result["exports"][0]["metadata"]["front_raw_scale"]["mode"] == "processed_wheel_travel"
    assert result["exports"][0]["metadata"]["front_raw_scale"]["clipped_low_rows"] == 1
    assert result["exports"][0]["metadata"]["rear_raw_scale"]["clipped_high_rows"] == 1


def test_data_syn_bike_export_zero_fills_missing_processed_wheel_travel_end(tmp_path):
    session = {
        "session_id": "session_001",
        "df": pd.DataFrame(
            {
                "time_s": [0.0, 0.01, 0.02],
                "front_wheel_disp_dom_wheel [mm]": [0.0, 75.0, 150.0],
            }
        ),
        "meta": {
            "signals": {
                "front_wheel_disp_dom_wheel [mm]": {
                    "end": "front",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                    "origin": "analysis",
                    "processing_role": "primary_analysis",
                },
            }
        },
    }
    config = default_data_syn_bike_export_config(
        raw_scale_mode="processed_wheel_travel",
        raw_full_scale_by_end={"front": 150, "rear": 165},
        adc_bit_count=12,
        drop_inactive=False,
    )

    result = export_data_syn_bike_resolved(session, export_config=config)
    exported = result["exports"][0]["dataframe"]
    write_result = write_data_syn_bike_exports(result, tmp_path)
    written_rows = write_result["written"][0]["path"].read_text(encoding="utf-8").strip().splitlines()

    assert exported["Front Raw"].tolist() == [0, 2048, 4095]
    assert exported["Rear Raw"].tolist() == [0, 0, 0]
    assert result["summary"]["rear_raw_col"] is None
    assert result["exports"][0]["metadata"]["rear_raw_scale"]["status"] == "missing_raw_column"
    assert result["exports"][0]["metadata"]["rear_raw_scale"]["zero_filled"] is True
    assert [row.split(",")[2] for row in written_rows] == ["0", "0", "0"]


def test_data_syn_bike_export_uses_logger_gps_columns_from_primary_dataframe():
    session = {
        "session_id": "session_001",
        "df": pd.DataFrame(
            {
                "time_s": [0.0, 0.01],
                "front_wheel_disp_dom_wheel [mm]": [0.0, 10.0],
                "rear_wheel_disp_dom_wheel [mm]": [0.0, 12.0],
                "gps0_position_latitude_dom_world [deg]": [-32.0, -32.1],
                "gps0_position_longitude_dom_world [deg]": [116.0, 116.1],
                "gps0_speed_dom_world [m/s]": [4.0, 4.1],
            }
        ),
        "meta": {
            "signals": {
                "front_wheel_disp_dom_wheel [mm]": {
                    "end": "front",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                },
                "rear_wheel_disp_dom_wheel [mm]": {
                    "end": "rear",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                },
                "gps0_position_latitude_dom_world [deg]": {
                    "sensor": "gps0",
                    "source": "async_snapshot",
                    "quantity": "position_latitude",
                    "domain": "world",
                    "unit": "deg",
                },
                "gps0_position_longitude_dom_world [deg]": {
                    "sensor": "gps0",
                    "source": "async_snapshot",
                    "quantity": "position_longitude",
                    "domain": "world",
                    "unit": "deg",
                },
                "gps0_speed_dom_world [m/s]": {
                    "sensor": "gps0",
                    "source": "async_snapshot",
                    "quantity": "speed",
                    "domain": "world",
                    "unit": "m/s",
                },
            }
        },
    }
    config = default_data_syn_bike_export_config(
        raw_scale_mode="processed_wheel_travel",
        raw_full_scale_by_end={"front": 150, "rear": 165},
        adc_bit_count=12,
        drop_inactive=False,
    )

    result = export_data_syn_bike_resolved(session, export_config=config)
    exported = result["exports"][0]["dataframe"]

    assert exported["Long"].tolist() == [116.0, 116.1]
    assert exported["Lat"].tolist() == [-32.0, -32.1]
    assert exported["Speed"].tolist() == pytest.approx([7.775377969762419, 7.969762419006479])
    assert result["summary"]["gps_source_id"] == "primary"
    assert result["summary"]["lat_col"] == "gps0_position_latitude_dom_world [deg]"


def test_data_syn_bike_export_uses_preferred_logger_gps_stream():
    session = {
        "session_id": "session_001",
        "df": pd.DataFrame(
            {
                "time_s": [0.0, 0.01, 0.02],
                "front_wheel_disp_dom_wheel [mm]": [0.0, 10.0, 20.0],
                "rear_wheel_disp_dom_wheel [mm]": [0.0, 12.0, 24.0],
            }
        ),
        "stream_dfs": {
            "gps_logger": pd.DataFrame(
                {
                    "time_s": [0.0, 0.02],
                    "latitude_deg": [-32.0, -32.2],
                    "longitude_deg": [116.0, 116.2],
                    "speed_mps": [4.0, 4.2],
                }
            )
        },
        "meta": {
            "signals": {
                "front_wheel_disp_dom_wheel [mm]": {
                    "end": "front",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                },
                "rear_wheel_disp_dom_wheel [mm]": {
                    "end": "rear",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                },
            },
            "gps_sources": {
                "preferred_source": "gps_logger",
                "sources": [{"source_id": "gps_logger", "kind": "logger_sensor"}],
            },
            "secondary_streams": {
                "gps_logger": {
                    "stream_name": "gps_logger",
                    "source_kind": "logger_sensor",
                    "time_col": "time_s",
                    "channel_info": {
                        "latitude_deg": {
                            "sensor": "gps0",
                            "source": "logger_gps",
                            "quantity": "position_latitude",
                            "domain": "world",
                            "unit": "deg",
                        },
                        "longitude_deg": {
                            "sensor": "gps0",
                            "source": "logger_gps",
                            "quantity": "position_longitude",
                            "domain": "world",
                            "unit": "deg",
                        },
                        "speed_mps": {
                            "sensor": "gps0",
                            "source": "logger_gps",
                            "quantity": "speed",
                            "domain": "world",
                            "unit": "m/s",
                        },
                    },
                }
            },
        },
    }
    config = default_data_syn_bike_export_config(
        raw_scale_mode="processed_wheel_travel",
        raw_full_scale_by_end={"front": 150, "rear": 165},
        adc_bit_count=12,
        drop_inactive=False,
        gps_resample_max_gap_s=1.0,
    )

    result = export_data_syn_bike_resolved(session, export_config=config)
    exported = result["exports"][0]["dataframe"]
    gps_meta = result["exports"][0]["metadata"]["gps_source"]

    assert exported["Long"].tolist() == pytest.approx([116.0, 116.1, 116.2])
    assert exported["Lat"].tolist() == pytest.approx([-32.0, -32.1, -32.2])
    assert exported["Speed"].tolist() == pytest.approx([7.775377969762419, 7.969762419006479, 8.164146868250541])
    assert result["summary"]["gps_source_id"] == "gps_logger"
    assert result["summary"]["gps_source_location"] == "stream"
    assert result["summary"]["lat_col"] == "gps_logger.latitude_deg"
    assert gps_meta["status"] == "ok"
    assert gps_meta["resampling"]["columns"] == ["longitude_deg", "latitude_deg", "speed_mps"]


def test_data_syn_bike_manual_settings_reports_bike_profile_values():
    bike_profile = {
        "bike_profile_id": "example-bike",
        "normalization_ranges": [
            {
                "id": "front",
                "signal": {"end": "front", "quantity": "disp", "domain": "wheel", "unit": "mm"},
                "full_range": 170,
            },
            {
                "id": "rear_shock",
                "signal": {"end": "rear", "quantity": "disp", "domain": "suspension", "unit": "mm"},
                "full_range": 65,
            },
            {
                "id": "rear_wheel",
                "signal": {"end": "rear", "quantity": "disp", "domain": "wheel", "unit": "mm"},
                "full_range": 150,
            },
        ],
    }

    settings = data_syn_bike_manual_settings(bike_profile=bike_profile)
    text = render_data_syn_bike_manual_settings_text(settings)

    assert settings["front_wheel_travel_mm"] == 170.0
    assert settings["max_shock_mm"] == 65.0
    assert settings["rear_wheel_travel_mm"] == 150.0
    assert settings["average_leverage_rate"] == 150.0 / 65.0
    assert "Average leverage rate:" in text


def test_data_syn_bike_manual_settings_use_one_to_one_rear_linkage_for_processed_wheel_travel():
    bike_profile = {
        "bike_profile_id": "example-bike",
        "normalization_ranges": [
            {
                "id": "front",
                "signal": {"end": "front", "quantity": "disp", "domain": "wheel", "unit": "mm"},
                "full_range": 170,
            },
            {
                "id": "rear_shock",
                "signal": {"end": "rear", "quantity": "disp", "domain": "suspension", "unit": "mm"},
                "full_range": 65,
            },
            {
                "id": "rear_wheel",
                "signal": {"end": "rear", "quantity": "disp", "domain": "wheel", "unit": "mm"},
                "full_range": 150,
            },
        ],
    }
    config = default_data_syn_bike_export_config(raw_scale_mode="processed_wheel_travel")

    settings = data_syn_bike_manual_settings(bike_profile=bike_profile, export_config=config)
    text = render_data_syn_bike_manual_settings_text(settings)

    assert settings["max_shock_mm"] == 150.0
    assert settings["rear_shock_normalization_range_mm"] == 150.0
    assert settings["rear_wheel_travel_mm"] == 150.0
    assert settings["average_leverage_rate"] == 1.0
    assert "Average leverage rate: 1" in text


def test_data_syn_bike_manual_settings_derives_front_wheel_travel_from_transform():
    bike_profile = {
        "bike_profile_id": "example-bike",
        "normalization_ranges": [
            {
                "id": "front_suspension",
                "signal": {"end": "front", "quantity": "disp", "domain": "suspension", "unit": "mm"},
                "full_range": 170,
            },
            {
                "id": "rear_shock",
                "signal": {"end": "rear", "quantity": "disp", "domain": "suspension", "unit": "mm"},
                "full_range": 55,
            },
            {
                "id": "rear_wheel",
                "signal": {"end": "rear", "quantity": "disp", "domain": "wheel", "unit": "mm"},
                "full_range": 165,
            },
        ],
        "signal_transforms": [
            {
                "enabled": True,
                "method": "polynomial",
                "input": {"end": "front", "quantity": "disp", "domain": "suspension", "unit": "mm"},
                "output": {"end": "front", "quantity": "disp", "domain": "wheel", "unit": "mm"},
                "polynomial": {
                    "coefficient_order": "ascending",
                    "coefficients": [0, 0.8910065241883678],
                },
            }
        ],
    }

    settings = data_syn_bike_manual_settings(bike_profile=bike_profile)

    assert settings["front_normalization_range_mm"] == pytest.approx(151.47110911202253)
    assert settings["front_wheel_travel_mm"] == pytest.approx(151.47110911202253)
    assert "missing_front_wheel_travel" not in settings["warnings"]


def test_histogram_trimmed_metrics_include_mean_min_max():
    metrics = compute_trimmed_quantile_metrics([1, 2, 3, 4, 5], cutoff=None)

    assert metrics.insufficient is False
    assert metrics.mean == pytest.approx(3.0)
    assert metrics.minimum == pytest.approx(1.0)
    assert metrics.maximum == pytest.approx(5.0)


def test_histogram_trimmed_metrics_mean_min_max_use_trimmed_values():
    metrics = compute_trimmed_quantile_metrics([1, 2, 3, 4, 5, 100], cutoff=2)

    assert metrics.insufficient is False
    assert metrics.n_trim == 5
    assert metrics.mean == pytest.approx((2 + 3 + 4 + 5 + 100) / 5)
    assert metrics.minimum == pytest.approx(2.0)
    assert metrics.maximum == pytest.approx(100.0)


def test_histogram_trimmed_metrics_mean_min_max_nan_when_insufficient():
    metrics = compute_trimmed_quantile_metrics([1, 2, 3, 4], cutoff=None)

    assert metrics.insufficient is True
    assert math.isnan(metrics.mean)
    assert math.isnan(metrics.minimum)
    assert math.isnan(metrics.maximum)


def _prepare_source(
    tmp_path: Path,
    name: str,
    artifacts_dir: Path,
    *,
    settle_time_s: float = 1.0,
    use_profile_dirs: bool = True,
    attach_session_note_on_import: bool = False,
    force_reprocess: bool = False,
) -> Path:
    source_root = tmp_path / name
    inbox_dir = source_root / "inbox"
    inbox_dir.mkdir(parents=True)

    if use_profile_dirs:
        settings_dir = source_root / "settings"
        bike_dir = source_root / "bike"
        notes_dir = source_root / "notes"
        settings_dir.mkdir()
        bike_dir.mkdir()
        notes_dir.mkdir()
        schema_path = _write_schema(settings_dir / "event_schema.yaml")
        _write_preprocess_profile(settings_dir / "import_agent_test_settings.json", schema_path=schema_path)
        _write_bike_profile(bike_dir / "import_agent_test_bike.json")
        _write_session_note_template(notes_dir / "import_agent_test_note_template.json")
        _write_bike_setup_preset(notes_dir / "import_agent_test_setup_preset.json")
        _write_source_config(
            source_root,
            artifacts_dir=artifacts_dir,
            settle_time_s=settle_time_s,
            preprocess_profile_path="settings",
            bike_profile_path="bike",
            session_note={
                "attach_on_import": attach_session_note_on_import,
                "template_path": "notes",
                "setup_preset_path": "notes",
            },
            force_reprocess=force_reprocess,
        )
    else:
        schema_path = _write_schema(source_root / "schema.yaml")
        _write_preprocess_profile(source_root / "preprocess_profile.json", schema_path=schema_path)
        _write_bike_profile(source_root / "bike_profile.json")
        _write_source_config(
            source_root,
            artifacts_dir=artifacts_dir,
            settle_time_s=settle_time_s,
            force_reprocess=force_reprocess,
        )
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


def test_load_import_source_config_parses_session_auto_naming(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = tmp_path / "source_named"
    inbox_dir = source_root / "inbox"
    inbox_dir.mkdir(parents=True)
    schema_path = _write_schema(source_root / "schema.yaml")
    _write_preprocess_profile(source_root / "preprocess_profile.json", schema_path=schema_path)
    _write_bike_profile(source_root / "bike_profile.json")
    _write_source_config(
        source_root,
        artifacts_dir=artifacts_dir,
        naming={
            "session_description": {
                "enabled": True,
                "mode": "base_index",
                "base": "Lower chute",
                "index_start": 3,
                "index_padding": 2,
            }
        },
    )

    source = load_import_source_config(source_root)

    session_naming = source.naming.session_description
    assert session_naming.enabled is True
    assert session_naming.mode == "base_index"
    assert session_naming.base == "Lower chute"
    assert session_naming.index_start == 3
    assert session_naming.index_padding == 2


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

    assert re.fullmatch(r"source_a_\d{6}_\d{6}(?:_\d{2})?", record["run_id"])
    assert record["session_id"] == "session_001"
    assert manifest["source"]["original_archive_filename"] == "session_001.zip"
    assert manifest["source"]["archive_csv_member"] == "session_001.CSV"
    assert manifest["source"]["archive_log_metadata_member"] == "session_001.json"
    assert manifest["source"]["import_source_id"] == "source_a"


def test_run_sources_once_notifies_library_api_after_successful_import(tmp_path, monkeypatch):
    import bodaqs_analysis.import_agent as import_agent_module

    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_notify", artifacts_dir)
    config_path = source_root / "import_source.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["library_id"] = "default-library"
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    archive_path = _write_session_archive(source_root / "inbox", stem="session_001")
    _set_old_mtime(archive_path)
    notified_library_ids: list[str | None] = []

    def fake_notify(source):
        notified_library_ids.append(source.library_id)
        return {
            "attempted": True,
            "notified": True,
            "library_id": source.library_id,
        }

    monkeypatch.setattr(import_agent_module, "_notify_library_api_catalog_changed", fake_notify)

    report = run_sources_once([source_root])

    assert report["totals"]["imported"] == 1
    assert notified_library_ids == ["default-library"]
    assert report["sources"][0]["library_api_notification"]["notified"] is True
    revision_path = artifacts_dir / "library_catalog_revision.json"
    revision = json.loads(revision_path.read_text(encoding="utf-8"))
    assert revision["schema"] == "bodaqs.library_catalog_revision"
    assert revision["reason"] == "import_agent_sessions_imported"
    assert revision["actor"] == "import_agent"
    assert revision["changed_sessions"][0]["library_id"] == "default-library"
    assert revision["changed_sessions"][0]["session_id"] == "session_001"


def test_run_sources_once_emits_detection_and_archive_progress(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir)
    archive_a = _write_session_archive(source_root / "inbox", stem="session_001")
    archive_b = _write_session_archive(source_root / "inbox", stem="session_002")
    _set_old_mtime(archive_a)
    _set_old_mtime(archive_b)
    events: list[dict[str, object]] = []

    report = run_sources_once([source_root], progress_callback=lambda event: events.append(dict(event)))

    assert report["totals"]["imported"] == 2
    names = [str(event.get("event")) for event in events]
    assert names[0] == "source_scan_started"
    assert names[-1] == "source_scan_completed"

    detected_index = names.index("archives_detected")
    assert events[detected_index]["archive_count"] == 2

    processing_indices = [index for index, name in enumerate(names) if name == "archive_processing_started"]
    imported_indices = [index for index, name in enumerate(names) if name == "archive_imported"]
    assert len(processing_indices) == 2
    assert len(imported_indices) == 2
    assert detected_index < processing_indices[0]
    assert [events[index]["archive_index"] for index in processing_indices] == [1, 2]
    assert [events[index]["archive_count"] for index in processing_indices] == [2, 2]
    assert len({events[index]["run_id"] for index in processing_indices}) == 1
    assert {events[index]["session_id"] for index in imported_indices} == {"session_001", "session_002"}
    assert all(event.get("source_id") == "source_a" for event in events)
    assert events[-1]["totals"] == {
        "seen": 2,
        "deferred_unsettled": 0,
        "skipped_succeeded": 0,
        "skipped_failed": 0,
        "imported": 2,
        "failed": 0,
    }


def test_run_sources_once_imports_same_source_archives_into_one_run(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir)
    archive_a = _write_session_archive(source_root / "inbox", stem="session_001")
    archive_b = _write_session_archive(source_root / "inbox", stem="session_002")
    _set_old_mtime(archive_a)
    _set_old_mtime(archive_b)

    report = run_sources_once([source_root])

    assert report["totals"]["imported"] == 2
    records = report["sources"][0]["imported"]
    records_by_session = {record["session_id"]: record for record in records}
    run_ids = {record["run_id"] for record in records}
    assert len(run_ids) == 1

    run_id = next(iter(run_ids))
    run_dirs = [path for path in (artifacts_dir / "runs").iterdir() if path.is_dir()]
    run_manifest = json.loads((artifacts_dir / "runs" / run_id / "manifest.json").read_text(encoding="utf-8"))
    archive_import = run_manifest["pipeline_config"]["archive_import"]

    assert len(run_dirs) == 1
    assert set(run_manifest["sessions"]) == {"session_001", "session_002"}
    assert archive_import["mode"] == "source_scan_batch_v1"
    assert set(archive_import["sessions"]) == {"session_001", "session_002"}
    assert (
        archive_import["sessions"]["session_001"]["processing_key"]
        == records_by_session["session_001"]["processing_key"]
    )
    for session_id in ("session_001", "session_002"):
        assert (artifacts_dir / "runs" / run_id / "sessions" / session_id / "manifest.json").exists()


def test_run_sources_once_applies_run_override_and_session_auto_names(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = tmp_path / "source_named"
    inbox_dir = source_root / "inbox"
    inbox_dir.mkdir(parents=True)
    schema_path = _write_schema(source_root / "schema.yaml")
    _write_preprocess_profile(source_root / "preprocess_profile.json", schema_path=schema_path)
    _write_bike_profile(source_root / "bike_profile.json")
    _write_source_config(
        source_root,
        artifacts_dir=artifacts_dir,
        naming={
            "session_description": {
                "enabled": True,
                "mode": "base_index",
                "base": "Lower chute",
                "index_start": 1,
                "index_padding": 2,
            }
        },
    )
    archive_a = _write_session_archive(inbox_dir, stem="session_001")
    archive_b = _write_session_archive(inbox_dir, stem="session_002")
    _set_old_mtime(archive_a)
    _set_old_mtime(archive_b)

    report = run_sources_once([source_root], run_description_override="Morning shuttle laps")

    assert report["totals"]["imported"] == 2
    records = report["sources"][0]["imported"]
    run_id = records[0]["run_id"]
    assert {record["run_id"] for record in records} == {run_id}

    run_manifest = json.loads((artifacts_dir / "runs" / run_id / "manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["description"] == "Morning shuttle laps"

    descriptions = {}
    for session_id in ("session_001", "session_002"):
        manifest_path = artifacts_dir / "runs" / run_id / "sessions" / session_id / "manifest.json"
        descriptions[session_id] = json.loads(manifest_path.read_text(encoding="utf-8"))["description"]

    assert descriptions == {
        "session_001": "Lower chute 01",
        "session_002": "Lower chute 02",
    }


def test_run_sources_once_keeps_successful_batch_session_when_later_archive_fails(tmp_path, monkeypatch):
    import bodaqs_analysis.import_agent as import_agent_module

    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir)
    archive_good = _write_session_archive(source_root / "inbox", stem="session_good")
    archive_bad = _write_session_archive(source_root / "inbox", stem="session_bad")
    _set_old_mtime(archive_good)
    _set_old_mtime(archive_bad)
    real_preprocess_session = import_agent_module.preprocess_session

    def fail_bad_archive(input_path, *args, **kwargs):
        if Path(input_path).name == "session_bad.CSV":
            raise ValueError("test preprocessing failure")
        return real_preprocess_session(input_path, *args, **kwargs)

    monkeypatch.setattr(import_agent_module, "preprocess_session", fail_bad_archive)

    report = run_sources_once([source_root])

    assert report["totals"]["imported"] == 1
    assert report["totals"]["failed"] == 1
    imported_record = report["sources"][0]["imported"][0]
    run_id = imported_record["run_id"]
    run_manifest = json.loads((artifacts_dir / "runs" / run_id / "manifest.json").read_text(encoding="utf-8"))

    assert run_manifest["sessions"] == ["session_good"]
    assert (artifacts_dir / "runs" / run_id / "sessions" / "session_good" / "manifest.json").exists()
    assert not (artifacts_dir / "runs" / run_id / "sessions" / "session_bad").exists()
    assert len(list((source_root / "done").glob("session_good*.zip"))) == 1
    assert len(list((source_root / "failed").glob("session_bad*.zip"))) == 1


def test_run_sources_once_imports_bdq_and_moves_it_to_done(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir)
    bdq_path = _write_bdq_input(source_root / "inbox", stem="260516_201542")
    _set_old_mtime(bdq_path)

    report = run_sources_once([source_root])

    assert report["totals"]["imported"] == 1
    assert report["totals"]["failed"] == 0
    assert not bdq_path.exists()

    done_bdq_files = list((source_root / "done").glob("*.bdq"))
    assert len(done_bdq_files) == 1

    record = report["sources"][0]["imported"][0]
    session_manifest = artifacts_dir / "runs" / record["run_id"] / "sessions" / record["session_id"] / "manifest.json"
    manifest = json.loads(session_manifest.read_text(encoding="utf-8"))
    source_input = artifacts_dir / "runs" / record["run_id"] / "sessions" / record["session_id"] / "source" / "input.bdq"

    assert record["session_id"] == "260516_201542"
    assert record["input_kind"] == "bdq"
    assert record["source_identity_kind"] == "bdq_session_identity"
    assert source_input.exists()
    assert manifest["source"]["path"] == "source/input.bdq"
    assert manifest["source"]["input_kind"] == "bdq"
    assert manifest["source"]["original_bdq_filename"] == "260516_201542.bdq"
    assert manifest["source"]["bdq_sha256"] == record["archive_sha256"]
    assert manifest["source"]["import_source_id"] == "source_a"


def test_run_sources_once_can_attach_draft_session_note_from_source_preset(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(
        tmp_path,
        "source_a",
        artifacts_dir,
        attach_session_note_on_import=True,
    )
    archive_path = _write_session_archive(source_root / "inbox", stem="session_001")
    _set_old_mtime(archive_path)

    report = run_sources_once([source_root])

    assert report["totals"]["imported"] == 1
    record = report["sources"][0]["imported"][0]
    note_path = (
        artifacts_dir
        / "runs"
        / record["run_id"]
        / "sessions"
        / record["session_id"]
        / "annotations"
        / "session_notes.json"
    )
    note = json.loads(note_path.read_text(encoding="utf-8"))
    catalog = build_session_catalog_df(artifacts_dir=artifacts_dir)
    run_manifest = json.loads(
        (artifacts_dir / "runs" / record["run_id"] / "manifest.json").read_text(encoding="utf-8")
    )

    assert note["draft"] is True
    assert note["template_id"] == "import_agent_test_setup"
    assert note["values"]["fork"] == "Test Fork"
    assert note["values"]["rear_air_pressure_psi"] == 185.0
    assert "front_sag_pct" in note["values"]
    assert note["values"]["front_sag_pct"] is None
    assert note["source_context"]["origin"] == "import_agent"
    assert note["source_context"]["bike_profile_id"] == "import_agent_test_bike"
    assert note["source_context"]["setup_preset_id"] == "test_setup"
    assert (
        artifacts_dir / "library" / "session_note_templates" / "import_agent_test_setup" / "1.0.json"
    ).exists()
    assert run_manifest["pipeline_config"]["archive_import"]["session_note"]["draft"] is True
    assert bool(catalog.loc[0, "note_draft"]) is True
    assert catalog.loc[0, "note.fork"] == "Test Fork"


def test_run_sources_once_writes_data_syn_bike_outputs_when_library_enables_them(tmp_path):
    library = provision_import_agent_library(
        tmp_path / "libraries",
        display_name="Alice Library",
        data_syn_bike_export_enabled=True,
    )
    metadata = json.loads(library.metadata_path.read_text(encoding="utf-8"))
    metadata["exports"]["data_syn_bike"]["drop_inactive"] = False
    library.metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    source_root = _prepare_source(tmp_path, "source_a", library.artifacts_dir)
    archive_path = _write_session_archive(source_root / "inbox", stem="session_001")
    _set_old_mtime(archive_path)

    report = run_sources_once([source_root])

    assert report["totals"]["imported"] == 1
    record = report["sources"][0]["imported"][0]
    syn_dir = library.artifacts_dir / "syn"
    csv_files = list(syn_dir.glob("*__data_syn_bike.csv"))
    settings_files = list(syn_dir.glob("*__data_syn_bike_settings.txt"))
    manifest = json.loads((syn_dir / "data_syn_bike_export_manifest.json").read_text(encoding="utf-8"))
    run_manifest = json.loads(
        (library.artifacts_dir / "runs" / record["run_id"] / "manifest.json").read_text(encoding="utf-8")
    )

    assert len(csv_files) == 1
    assert len(settings_files) == 1
    assert "ADC bit count: 12" in settings_files[0].read_text(encoding="utf-8")
    assert f"{record['run_id']}/{record['session_id']}" in manifest["records"]
    assert (
        run_manifest["pipeline_config"]["archive_import"]["data_syn_bike_export"]["status"]
        == "succeeded"
    )


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


def test_run_sources_once_force_reprocess_imports_duplicate_success(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    source_root = _prepare_source(tmp_path, "source_a", artifacts_dir, force_reprocess=True)
    first_archive = _write_session_archive(source_root / "inbox", stem="session_001")
    _set_old_mtime(first_archive)

    first_report = run_sources_once([source_root])
    second_archive = _write_session_archive(source_root / "inbox", stem="session_001")
    _set_old_mtime(second_archive)
    second_report = run_sources_once([source_root])

    assert first_report["totals"]["imported"] == 1
    assert second_report["totals"]["imported"] == 1
    assert second_report["totals"]["skipped_succeeded"] == 0
    assert first_report["sources"][0]["imported"][0]["run_id"] != second_report["sources"][0]["imported"][0]["run_id"]


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
    assert len(warnings) == 5
    assert any(str(source_root / "fit") in item for item in warnings)


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
    assert library.artifacts_dir == libraries_root / "libraries" / "alice-library"
    assert library.runs_dir.exists()
    assert library.state_dir.exists()
    assert library.bike_profiles_dir == libraries_root / "bike_profiles"
    assert library.preprocess_profiles_dir == libraries_root / "preprocess_profiles"
    assert library.event_schemas_dir == libraries_root / "event_schemas"
    assert library.bike_profiles_dir.exists()
    assert any(library.bike_profiles_dir.glob("*.json"))
    metadata = json.loads(library.metadata_path.read_text(encoding="utf-8"))
    assert metadata["library_id"] == "alice-library"
    assert metadata["exports"]["data_syn_bike"]["enabled"] is False


def test_provision_import_agent_library_can_enable_data_syn_bike_exports(tmp_path):
    libraries_root = tmp_path / "libraries"

    library = provision_import_agent_library(
        libraries_root,
        display_name="Alice Library",
        data_syn_bike_export_enabled=True,
    )

    metadata = json.loads(library.metadata_path.read_text(encoding="utf-8"))
    assert library.data_syn_bike_export_enabled is True
    assert metadata["exports"]["data_syn_bike"]["enabled"] is True
    assert metadata["exports"]["data_syn_bike"]["raw_scale_mode"] == "processed_wheel_travel"


def test_provisioned_libraries_share_root_level_bike_profiles_dir(tmp_path):
    libraries_root = tmp_path / "libraries"

    first = provision_import_agent_library(libraries_root, display_name="Alice Library")
    second = provision_import_agent_library(libraries_root, display_name="Ben Library")

    assert first.bike_profiles_dir == libraries_root / "bike_profiles"
    assert second.bike_profiles_dir == first.bike_profiles_dir
    assert first.preprocess_profiles_dir == libraries_root / "preprocess_profiles"
    assert second.preprocess_profiles_dir == first.preprocess_profiles_dir
    assert first.event_schemas_dir == libraries_root / "event_schemas"
    assert second.event_schemas_dir == first.event_schemas_dir
    assert first.artifacts_dir == libraries_root / "libraries" / "alice-library"
    assert second.artifacts_dir == libraries_root / "libraries" / "ben-library"
    assert first.bike_profiles_dir.exists()


def test_discover_import_agent_libraries_supports_new_and_legacy_layouts(tmp_path):
    libraries_root = tmp_path / "libraries"
    new_library = provision_import_agent_library(libraries_root, display_name="Alice Library")
    legacy_library = libraries_root / "legacy-library"
    legacy_library.mkdir(parents=True)
    (legacy_library / "library_definition.json").write_text(
        json.dumps(
            {
                "schema": "bodaqs.import_agent_library",
                "version": 1,
                "library_id": "legacy-library",
                "display_name": "Legacy Library",
                "artifacts_dir": str(legacy_library),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (legacy_library / "runs").mkdir()
    (legacy_library / "library").mkdir()

    discovered = discover_import_agent_libraries(libraries_root)

    by_id = {library.library_id: library for library in discovered}
    assert set(by_id) == {"alice-library", "legacy-library"}
    assert by_id["alice-library"].artifacts_dir == new_library.artifacts_dir
    assert by_id["legacy-library"].artifacts_dir == legacy_library.resolve()


def test_update_import_agent_library_data_syn_bike_export_enabled_updates_app_and_library_metadata(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )

    updated = update_import_agent_library_data_syn_bike_export_enabled(
        app_config_path,
        library_id=provisioned.library.library_id,
        enabled=True,
    )

    metadata = json.loads(provisioned.library.metadata_path.read_text(encoding="utf-8"))
    assert updated.libraries[0].data_syn_bike_export_enabled is True
    assert metadata["exports"]["data_syn_bike"]["enabled"] is True


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

    assert not source.settings_dir.exists()
    assert source.notes_dir.exists()
    assert source.event_schema_path.exists()
    assert source.event_schema_path.parent == library.event_schemas_dir
    assert source.preprocess_profile_path.exists()
    assert source.preprocess_profile_path.parent == library.preprocess_profiles_dir
    assert source.bike_profile_path.exists()
    assert source.bike_profile_path.parent == library.bike_profiles_dir
    assert source.session_note_template_path.exists()
    assert source.bike_setup_preset_path.exists()
    assert loaded.preprocess_profile_path == source.preprocess_profile_path
    assert loaded.bike_profile_path == source.bike_profile_path
    assert loaded.session_note.template_path == source.notes_dir
    assert loaded.session_note.setup_preset_path == source.notes_dir
    assert loaded.artifacts_dir == library.artifacts_dir
    assert loaded.source_type == SOURCE_TYPE_FILESYSTEM_ARCHIVE
    assert source_payload["display_name"] == "Alice Enduro"
    assert source_payload["source_type"] == SOURCE_TYPE_FILESYSTEM_ARCHIVE
    assert not Path(source_payload["artifacts_dir"]).is_absolute()
    assert not Path(source_payload["preprocess_profile_path"]).is_absolute()
    assert not Path(source_payload["bike_profile_path"]).is_absolute()
    assert source_payload["session_note"]["attach_on_import"] is False
    assert preprocess_profile["config"]["schema_path"] == "../event_schemas/event_schema.yaml"


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


def test_provision_import_agent_source_can_seed_logger_wifi_config_without_base_url(tmp_path):
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
            "cleanup_mode": "none",
        },
        include_events=False,
        include_metrics=False,
    )

    loaded = load_import_source_config(source.source_root)

    assert loaded.logger_wifi is not None
    assert loaded.logger_wifi.logger_id == "Prototype E"
    assert loaded.logger_wifi.base_url is None


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
    assert source.preprocess_profile_path.parent == library.preprocess_profiles_dir
    assert source.event_schema_path.parent == library.event_schemas_dir
    assert source.bike_profile_path.parent == library.bike_profiles_dir
    assert source.bike_profile_path.name == "import_agent_test_bike.json"
    assert source.session_note_template_path.name == "session_note_template.json"
    assert source.bike_setup_preset_path.name == "bike_setup_preset.json"
    assert preprocess_profile["config"]["schema_path"] == "../event_schemas/event_schema.yaml"


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


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows path convention relies on ntpath semantics; pathlib.Path only "
    "builds Windows-style paths on Windows.",
)
def test_default_import_agent_app_config_path_uses_windows_convention():
    win_path = default_import_agent_app_config_path(
        platform="win32",
        env={"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"},
        home=r"C:\Users\Test",
    )

    assert win_path == Path(r"C:\Users\Test\AppData\Local\BODAQS\import-agent\import_agent_app.json")


@pytest.mark.skipif(
    os.name == "nt",
    reason="macOS path convention relies on POSIX semantics; pathlib.Path.resolve() "
    "anchors POSIX-style paths to a drive letter on Windows.",
)
def test_default_import_agent_app_config_path_uses_macos_convention():
    macos_path = default_import_agent_app_config_path(
        platform="darwin",
        home="/Users/Test",
    )

    assert macos_path == Path(
        "/Users/Test/Library/Application Support/BODAQS/import-agent/import_agent_app.json"
    )


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
    assert (provisioned.source.source_root / "fit").is_dir()
    assert (provisioned.source.source_root / "notes").is_dir()
    source_payload = json.loads(provisioned.source.import_source_config_path.read_text(encoding="utf-8"))
    assert source_payload["fit_dir"] == "fit"
    assert source_payload["session_note"]["template_path"] == "notes"
    assert source_payload["session_note"]["setup_preset_path"] == "notes"
    assert source_payload["session_note"]["attach_on_import"] is False
    assert "logger_timezone" not in source_payload
    assert "include_events" not in source_payload
    assert "include_metrics" not in source_payload
    assert len(config.libraries) == 1
    assert config.libraries[0].library_id == "alice-library"
    assert len(config.sources) == 1
    assert config.sources[0].source_id == "alice-enduro"


def test_load_managed_import_source_configs_uses_local_library_path(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    source_payload = json.loads(provisioned.source.import_source_config_path.read_text(encoding="utf-8"))
    source_payload["artifacts_dir"] = str(tmp_path / "old-machine" / "wrong-library")
    provisioned.source.import_source_config_path.write_text(
        json.dumps(source_payload, indent=2),
        encoding="utf-8",
    )

    stale_source = load_import_source_config(provisioned.source.source_root)
    managed_sources = load_managed_import_source_configs(load_import_agent_app_config(app_config_path))

    assert stale_source.artifacts_dir == (tmp_path / "old-machine" / "wrong-library").resolve()
    assert managed_sources[0].artifacts_dir == provisioned.library.artifacts_dir
    assert managed_sources[0].library_id == provisioned.library.library_id


def test_adopt_import_agent_existing_workspace_rebuilds_local_app_config_with_new_paths(tmp_path):
    first_workspace = tmp_path / "machine-a" / "BODAQS"
    second_workspace = tmp_path / "machine-b" / "BODAQS"
    first_app_config_path = tmp_path / "machine-a" / "config" / "import_agent_app.json"
    second_app_config_path = tmp_path / "machine-b" / "config" / "import_agent_app.json"

    provision_import_agent_app_setup(
        sources_root=first_workspace / "sources",
        libraries_root=first_workspace / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=first_app_config_path,
        data_syn_bike_export_enabled=True,
        attach_session_note_on_import=True,
    )
    shutil.copytree(first_workspace, second_workspace)

    adopted = adopt_import_agent_existing_workspace(
        sources_root=second_workspace / "sources",
        libraries_root=second_workspace / "libraries",
        app_config_path=second_app_config_path,
        auto_start=True,
    )
    config = load_import_agent_app_config(second_app_config_path)
    managed_sources = load_managed_import_source_configs(config)

    assert adopted.app_config_path == second_app_config_path.resolve()
    assert config.sources_root == (second_workspace / "sources").resolve()
    assert config.libraries_root == (second_workspace / "libraries").resolve()
    assert config.auto_start is True
    assert config.libraries[0].library_id == "alice-library"
    assert config.libraries[0].display_name == "Alice Library"
    assert config.libraries[0].artifacts_dir == (
        second_workspace / "libraries" / "libraries" / "alice-library"
    ).resolve()
    assert config.libraries[0].data_syn_bike_export_enabled is True
    assert config.sources[0].source_id == "alice-enduro"
    assert config.sources[0].display_name == "Alice Enduro"
    assert config.sources[0].source_root == (second_workspace / "sources" / "alice-enduro").resolve()
    assert config.sources[0].library_id == "alice-library"
    assert config.sources[0].attach_session_note_on_import is True
    assert managed_sources[0].artifacts_dir == config.libraries[0].artifacts_dir


def test_workspace_sync_adds_shared_entries_and_preserves_local_enabled_state(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    sources_root = tmp_path / "sources"
    libraries_root = tmp_path / "libraries"
    provisioned = provision_import_agent_app_setup(
        sources_root=sources_root,
        libraries_root=libraries_root,
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    update_import_agent_source_enabled(app_config_path, source_id=provisioned.source.source_id, enabled=False)

    shared_library = provision_import_agent_library(libraries_root, display_name="Ben Library")
    shared_source = provision_import_agent_source(
        sources_root / "ben-dh",
        artifacts_dir=shared_library.artifacts_dir,
        library_id=shared_library.library_id,
        display_name="Ben DH",
    )

    report = check_import_agent_workspace_sync(app_config_path)

    assert report.added_libraries == (shared_library.library_id,)
    assert report.added_sources == (shared_source.source_id,)
    assert report.has_changes is True
    assert report.has_syncable_changes is True

    synced = sync_import_agent_workspace_from_roots(app_config_path)
    config = load_import_agent_app_config(app_config_path)

    assert synced.report.added_libraries == (shared_library.library_id,)
    assert {library.library_id for library in config.libraries} == {
        provisioned.library.library_id,
        shared_library.library_id,
    }
    assert {source.source_id for source in config.sources} == {
        provisioned.source.source_id,
        shared_source.source_id,
    }
    assert next(source for source in config.sources if source.source_id == provisioned.source.source_id).enabled is False
    assert next(source for source in config.sources if source.source_id == shared_source.source_id).enabled is True


def test_workspace_sync_updates_shared_metadata_without_removing_missing_entries(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    update_import_agent_source_enabled(app_config_path, source_id=provisioned.source.source_id, enabled=False)

    library_metadata_path = provisioned.library.artifacts_dir / "library_definition.json"
    library_payload = json.loads(library_metadata_path.read_text(encoding="utf-8"))
    library_payload["display_name"] = "Alice Shared Library"
    library_metadata_path.write_text(json.dumps(library_payload, indent=2), encoding="utf-8")

    source_config_path = provisioned.source.import_source_config_path
    source_payload = json.loads(source_config_path.read_text(encoding="utf-8"))
    source_payload["display_name"] = "Alice Shared Source"
    source_payload["force_reprocess"] = True
    source_config_path.write_text(json.dumps(source_payload, indent=2), encoding="utf-8")

    missing_library = ImportAgentLibraryConfig(
        library_id="missing-library",
        display_name="Missing Library",
        artifacts_dir=tmp_path / "missing-library",
    )
    config = load_import_agent_app_config(app_config_path)
    with_missing = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=(*config.libraries, missing_library),
        sources=config.sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(with_missing, app_config_path)

    report = check_import_agent_workspace_sync(app_config_path)

    assert report.updated_libraries == (provisioned.library.library_id,)
    assert report.updated_sources == (provisioned.source.source_id,)
    assert report.missing_libraries == ("missing-library",)

    synced = sync_import_agent_workspace_from_roots(app_config_path)
    updated = load_import_agent_app_config(app_config_path)
    library = next(item for item in updated.libraries if item.library_id == provisioned.library.library_id)
    source = next(item for item in updated.sources if item.source_id == provisioned.source.source_id)

    assert synced.report.missing_libraries == ("missing-library",)
    assert library.display_name == "Alice Shared Library"
    assert source.display_name == "Alice Shared Source"
    assert source.force_reprocess is True
    assert source.enabled is False
    assert any(item.library_id == "missing-library" for item in updated.libraries)


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
    source_payload = json.loads(source.import_source_config_path.read_text(encoding="utf-8"))
    assert "require_upload_mode" not in source_payload["logger_wifi"]


def test_update_import_agent_source_logger_wifi_can_clear_fixed_address(tmp_path):
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
            "base_url": "http://192.168.1.42",
            "cleanup_mode": "move_to_uploaded",
        },
        include_events=False,
        include_metrics=False,
    )

    updated = update_import_agent_source_logger_wifi(
        app_config_path,
        source_id=source.source_id,
        logger_wifi={
            "logger_id": "Prototype E",
            "request_timeout_s": 3,
            "download_timeout_s": 90,
            "cleanup_mode": "none",
        },
    )

    reloaded_source = load_import_source_config(source.source_root)
    source_payload = json.loads(source.import_source_config_path.read_text(encoding="utf-8"))

    assert next(item for item in updated.sources if item.source_id == source.source_id).source_root == source.source_root
    assert reloaded_source.logger_wifi is not None
    assert reloaded_source.logger_wifi.logger_id == "Prototype E"
    assert reloaded_source.logger_wifi.base_url is None
    assert reloaded_source.logger_wifi.request_timeout_s == pytest.approx(3)
    assert reloaded_source.logger_wifi.download_timeout_s == pytest.approx(90)
    assert source_payload["logger_wifi"]["base_url"] is None


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


def test_update_import_agent_source_session_note_attach_updates_app_and_source_config(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )

    updated = update_import_agent_source_session_note_attach_enabled(
        app_config_path,
        source_id=provisioned.source.source_id,
        enabled=True,
    )
    source_payload = json.loads(provisioned.source.import_source_config_path.read_text(encoding="utf-8"))
    reloaded = load_import_agent_app_config(app_config_path)

    assert updated.sources[0].attach_session_note_on_import is True
    assert reloaded.sources[0].attach_session_note_on_import is True
    assert source_payload["session_note"]["attach_on_import"] is True


def test_update_import_agent_source_force_reprocess_updates_app_and_source_config(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )

    updated = update_import_agent_source_force_reprocess_enabled(
        app_config_path,
        source_id=provisioned.source.source_id,
        enabled=True,
    )
    source_payload = json.loads(provisioned.source.import_source_config_path.read_text(encoding="utf-8"))
    reloaded = load_import_agent_app_config(app_config_path)
    loaded_source = load_import_source_config(provisioned.source.source_root)

    assert updated.sources[0].force_reprocess is True
    assert reloaded.sources[0].force_reprocess is True
    assert source_payload["force_reprocess"] is True
    assert loaded_source.force_reprocess is True


def test_update_import_agent_source_session_naming_updates_source_config(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )

    updated = update_import_agent_source_session_naming(
        app_config_path,
        source_id=provisioned.source.source_id,
        enabled=True,
        base="Flow trail",
        index_start=5,
        index_padding=3,
    )
    source_payload = json.loads(provisioned.source.import_source_config_path.read_text(encoding="utf-8"))
    loaded_source = load_import_source_config(provisioned.source.source_root)

    assert updated.sources[0].source_id == provisioned.source.source_id
    assert source_payload["naming"]["session_description"] == {
        "enabled": True,
        "mode": "base_index",
        "base": "Flow trail",
        "index_start": 5,
        "index_padding": 3,
    }
    assert loaded_source.naming.session_description.enabled is True
    assert loaded_source.naming.session_description.base == "Flow trail"
    assert loaded_source.naming.session_description.index_start == 5
    assert loaded_source.naming.session_description.index_padding == 3


def test_update_import_agent_source_library_updates_app_and_source_config(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    _updated, second_library = provision_import_agent_library_for_app(
        app_config_path,
        display_name="Ben Library",
    )
    original_bike_profile_path = load_import_source_config(provisioned.source.source_root).bike_profile_path

    updated = update_import_agent_source_library(
        app_config_path,
        source_id=provisioned.source.source_id,
        library_id=second_library.library_id,
    )
    source_payload = json.loads(provisioned.source.import_source_config_path.read_text(encoding="utf-8"))
    loaded_source = load_import_source_config(provisioned.source.source_root)

    managed_source = next(source for source in updated.sources if source.source_id == provisioned.source.source_id)
    assert managed_source.library_id == second_library.library_id
    assert source_payload["library_id"] == second_library.library_id
    assert not Path(source_payload["artifacts_dir"]).is_absolute()
    assert not Path(source_payload["bike_profile_path"]).is_absolute()
    assert (provisioned.source.source_root / source_payload["artifacts_dir"]).resolve() == second_library.artifacts_dir
    assert loaded_source.artifacts_dir == second_library.artifacts_dir
    assert second_library.bike_profiles_dir == provisioned.library.bike_profiles_dir
    assert loaded_source.bike_profile_path == original_bike_profile_path
    assert loaded_source.bike_profile_path.parent == second_library.bike_profiles_dir


def test_update_import_agent_display_names_do_not_change_ids_or_paths(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )

    renamed_library_config = update_import_agent_library_display_name(
        app_config_path,
        library_id=provisioned.library.library_id,
        display_name="Race Library",
    )
    renamed_source_config = update_import_agent_source_display_name(
        app_config_path,
        source_id=provisioned.source.source_id,
        display_name="Race Source",
    )
    reloaded = load_import_agent_app_config(app_config_path)
    library_metadata = json.loads(provisioned.library.metadata_path.read_text(encoding="utf-8"))
    source_payload = json.loads(provisioned.source.import_source_config_path.read_text(encoding="utf-8"))

    assert renamed_library_config.libraries[0].library_id == provisioned.library.library_id
    assert renamed_library_config.libraries[0].display_name == "Race Library"
    assert renamed_library_config.libraries[0].artifacts_dir == provisioned.library.artifacts_dir
    assert renamed_source_config.sources[0].source_id == provisioned.source.source_id
    assert renamed_source_config.sources[0].display_name == "Race Source"
    assert renamed_source_config.sources[0].source_root == provisioned.source.source_root
    assert reloaded.libraries[0].display_name == "Race Library"
    assert reloaded.sources[0].display_name == "Race Source"
    assert library_metadata["display_name"] == "Race Library"
    assert source_payload["display_name"] == "Race Source"


def test_derive_profile_id_slugifies_and_suffixes_duplicates():
    profile_id = derive_profile_id(
        "Alice's Enduro / Wet Setup",
        existing_ids=["alice-s-enduro-wet-setup", "alice-s-enduro-wet-setup-2"],
    )

    assert profile_id == "alice-s-enduro-wet-setup-3"


def test_import_agent_bike_profile_builder_updates_basic_fields_and_lut(tmp_path):
    library = provision_import_agent_library(tmp_path / "libraries", display_name="Alice Library")
    source = provision_import_agent_source(
        tmp_path / "sources" / "Alice Enduro",
        artifacts_dir=library.artifacts_dir,
        library_id=library.library_id,
        display_name="Alice Enduro",
    )
    _profile_path, profile = load_source_bike_profile(source.source_root)

    updated = apply_bike_profile_form_values(
        profile,
        {
            "display_name": "Alice Enduro",
            "manufacturer": "Specialized",
            "model": "Stumpjumper Evo",
            "front_fork_travel_mm": "160",
            "front_head_angle_deg": "63.5",
            "rear_shock_travel_mm": "55",
            "rear_wheel_travel_mm": "150",
        },
    )
    updated = set_rear_wheel_lut_transform(
        updated,
        parse_lut_text("0, 0\n10, 25\n55, 150\n"),
        extrapolation="clamp",
    )
    save_source_bike_profile(source.source_root, updated)
    _reloaded_path, reloaded = load_source_bike_profile(source.source_root)
    transform = rear_wheel_lut_from_profile(reloaded)
    front_transform = front_vertical_transform_from_profile(reloaded)

    assert reloaded["bike_profile_id"] == "alice-enduro"
    assert reloaded["bike"]["manufacturer"] == "Specialized"
    assert reloaded["bike"]["steering_head_angle_deg"] == pytest.approx(63.5)
    assert "setup" not in reloaded
    assert front_transform is not None
    assert front_transform["method"] == "polynomial"
    assert front_transform["polynomial"]["coefficients"][0] == 0.0
    assert front_transform["polynomial"]["coefficients"][1] == pytest.approx(math.sin(math.radians(63.5)))
    assert front_head_angle_from_profile(reloaded) == pytest.approx(63.5)
    front_wheel_ranges = [
        item
        for item in reloaded["normalization_ranges"]
        if item.get("signal") == {"end": "front", "quantity": "disp", "domain": "wheel", "unit": "mm"}
    ]
    assert len(front_wheel_ranges) == 1
    assert front_wheel_ranges[0]["id"] == "front_wheel_travel_range"
    assert front_wheel_ranges[0]["full_range"] == pytest.approx(160 * math.sin(math.radians(63.5)))
    assert front_wheel_ranges[0]["metadata"]["source"] == "import_agent_head_angle"
    assert transform is not None
    assert transform["extrapolation"] == "clamp"
    assert transform["lut"][-1] == {"input": 55.0, "output": 150.0}


def test_import_agent_bike_profile_builder_allows_degree_rear_lut_input(tmp_path):
    library = provision_import_agent_library(tmp_path / "libraries", display_name="Alice Library")
    source = provision_import_agent_source(
        tmp_path / "sources" / "Alice Enduro",
        artifacts_dir=library.artifacts_dir,
        library_id=library.library_id,
        display_name="Alice Enduro",
    )
    _profile_path, profile = load_source_bike_profile(source.source_root)

    updated = apply_bike_profile_form_values(
        profile,
        {
            "display_name": "Alice Enduro",
            "front_fork_travel_mm": "160",
            "rear_shock_lut_input_unit": "deg",
            "rear_shock_travel_mm": "90",
            "rear_wheel_travel_mm": "150",
        },
    )
    updated = set_rear_wheel_lut_transform(
        updated,
        parse_lut_text("0, 0\n45, 80\n90, 150\n"),
        input_unit="deg",
    )
    save_source_bike_profile(source.source_root, updated)
    _reloaded_path, reloaded = load_source_bike_profile(source.source_root)
    transform = rear_wheel_lut_from_profile(reloaded)
    values = bike_profile_form_values(reloaded)

    rear_shock_ranges = [
        item
        for item in reloaded["normalization_ranges"]
        if item.get("id") == "rear_shock_travel_range"
    ]
    assert len(rear_shock_ranges) == 1
    assert rear_shock_ranges[0]["signal"] == {
        "end": "rear",
        "quantity": "disp",
        "domain": "suspension",
        "unit": "deg",
    }
    assert rear_shock_ranges[0]["full_range"] == pytest.approx(90.0)
    assert transform is not None
    assert transform["input"] == {"end": "rear", "quantity": "disp", "domain": "suspension", "unit": "deg"}
    assert transform["output"] == {"end": "rear", "quantity": "disp", "domain": "wheel", "unit": "mm"}
    assert values["rear_shock_lut_input_unit"] == "deg"
    assert values["rear_shock_travel_mm"] == pytest.approx(90.0)


def test_import_agent_bike_profile_builder_reads_stored_head_angle(tmp_path):
    library = provision_import_agent_library(tmp_path / "libraries", display_name="Alice Library")
    source = provision_import_agent_source(
        tmp_path / "sources" / "Alice Enduro",
        artifacts_dir=library.artifacts_dir,
        library_id=library.library_id,
        display_name="Alice Enduro",
    )
    _profile_path, profile = load_source_bike_profile(source.source_root)
    profile["signal_transforms"] = [
        transform
        for transform in profile.get("signal_transforms", [])
        if transform.get("id") != "front_fork_to_front_vertical_wheel_travel"
    ]
    profile["bike"]["steering_head_angle_deg"] = 64.0

    values = bike_profile_form_values(profile)
    assert values["front_head_angle_deg"] == "64"

    updated = apply_bike_profile_form_values(profile, values)
    front_transform = front_vertical_transform_from_profile(updated)
    assert front_transform is not None
    assert front_transform["polynomial"]["coefficients"][1] == pytest.approx(math.sin(math.radians(64.0)))


def test_normalize_rear_lut_with_endpoints_forces_travel_endpoints():
    points = [
        {"input": 0, "output": 123},
        {"input": 55, "output": 999},
        {"input": 30, "output": 90},
        {"input": 10, "output": 25},
    ]

    normalized = normalize_rear_lut_with_endpoints(
        points,
        rear_shock_travel_mm=55,
        rear_wheel_travel_mm=150,
    )

    assert normalized == [
        {"input": 0.0, "output": 0.0},
        {"input": 10.0, "output": 25.0},
        {"input": 30.0, "output": 90.0},
        {"input": 55.0, "output": 150.0},
    ]


def test_normalize_rear_lut_with_endpoints_rejects_out_of_range_interior_points():
    with pytest.raises(ValueError, match="between 0 and rear shock travel"):
        normalize_rear_lut_with_endpoints(
            [{"input": 60, "output": 151}],
            rear_shock_travel_mm=55,
            rear_wheel_travel_mm=150,
        )


def test_update_import_agent_source_bike_profile_links_shared_library_profile(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    first = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    _updated, second = provision_import_agent_source_for_app(
        app_config_path,
        library_id=first.library.library_id,
        display_name="Ben DH",
    )
    first_profile_path, first_profile = load_source_bike_profile(first.source.source_root)
    second_profile_path, _second_profile = load_source_bike_profile(second.source_root)
    assert first_profile_path == second_profile_path

    ben_profile = apply_bike_profile_form_values(
        first_profile,
        {
            "bike_profile_id": "ben-bike",
            "display_name": "Ben Bike",
            "front_fork_travel_mm": "180",
            "rear_shock_travel_mm": "75",
            "rear_wheel_travel_mm": "200",
        },
    )
    ben_profile_path = first.library.bike_profiles_dir / "ben-bike.json"
    save_bike_profile_path(ben_profile_path, ben_profile)

    update_import_agent_source_bike_profile(
        app_config_path,
        source_id=second.source_id,
        bike_profile_path=ben_profile_path,
    )
    source_payload = json.loads(second.import_source_config_path.read_text(encoding="utf-8"))
    target_profile_path, target_profile = load_source_bike_profile(second.source_root)

    assert not Path(source_payload["bike_profile_path"]).is_absolute()
    assert target_profile_path == ben_profile_path
    assert target_profile["bike_profile_id"] == "ben-bike"
    assert load_source_bike_profile(first.source.source_root)[0] == first_profile_path


def test_update_import_agent_source_preprocess_profile_links_shared_profile(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    first = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    _updated, second = provision_import_agent_source_for_app(
        app_config_path,
        library_id=first.library.library_id,
        display_name="Ben DH",
    )
    first_source_config = load_import_source_config(first.source.source_root)
    second_source_config = load_import_source_config(second.source_root)
    assert first_source_config.preprocess_profile_path == second_source_config.preprocess_profile_path

    profile_config = default_preprocess_config()
    profile_config["schema_path"] = "../event_schemas/event_schema.yaml"
    profile_config["logger_timezone"] = "UTC"
    custom_profile_path = first.library.preprocess_profiles_dir / "utc-preprocess-profile.json"
    save_preprocess_profile(make_preprocess_profile("utc_preprocess", config=profile_config), custom_profile_path)

    update_import_agent_source_preprocess_profile(
        app_config_path,
        source_id=second.source_id,
        preprocess_profile_path=custom_profile_path,
    )
    source_payload = json.loads(second.import_source_config_path.read_text(encoding="utf-8"))
    target_config = load_import_source_config(second.source_root)

    assert not Path(source_payload["preprocess_profile_path"]).is_absolute()
    assert target_config.preprocess_profile_path == custom_profile_path
    assert (
        load_import_source_config(first.source.source_root).preprocess_profile_path
        == first_source_config.preprocess_profile_path
    )


def test_session_note_template_builder_and_copy_relinks_setup_preset_to_target_bike(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    first = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    _updated, second = provision_import_agent_source_for_app(
        app_config_path,
        library_id=first.library.library_id,
        display_name="Ben DH",
    )
    _target_profile_path, target_profile = load_source_bike_profile(second.source_root)
    target_profile = apply_bike_profile_form_values(
        target_profile,
        {
            "bike_profile_id": "ben-bike",
            "display_name": "Ben Bike",
            "front_fork_travel_mm": "180",
            "rear_shock_travel_mm": "75",
            "rear_wheel_travel_mm": "200",
        },
    )
    save_source_bike_profile(second.source_root, target_profile)

    catalog = load_session_note_field_catalog()
    template = build_session_note_template_from_field_ids(
        field_ids=["bike", "rider", "rear_air_pressure_psi", "test_conditions"],
        template_id="source_setup",
        template_version="1.0",
        title="Source setup",
        catalog=catalog,
    )
    save_source_session_note_assets(first.source.source_root, template)
    copy_source_note_assets(first.source.source_root, second.source_root)

    _template_path, copied_template = load_source_session_note_template(second.source_root)
    preset = json.loads(second.bike_setup_preset_path.read_text(encoding="utf-8"))
    field_ids = [field["field_id"] for field in copied_template["fields"]]

    assert field_ids == ["bike", "rider", "rear_air_pressure_psi", "test_conditions"]
    assert preset["bike_profile_id"] == "ben-bike"
    assert preset["values"]["bike"] == "Ben Bike"


def test_import_agent_note_field_catalog_is_valid_and_unique():
    catalog = load_session_note_field_catalog()
    field_ids = [field["field_id"] for field in catalog]

    assert catalog
    assert len(field_ids) == len(set(field_ids))
    assert "front_HBO" in field_ids


def test_session_note_template_builder_applies_typed_default_values():
    catalog = load_session_note_field_catalog()
    template = build_session_note_template_from_field_ids(
        field_ids=["setup_variant", "front_air_pressure_psi", "front_tokens", "test_conditions"],
        template_id="source_setup",
        title="Source setup",
        field_defaults={
            "setup_variant": "wet setup",
            "front_air_pressure_psi": "82.5",
            "front_tokens": "3",
            "test_conditions": "Loose and dusty",
        },
        catalog=catalog,
    )
    fields = {field["field_id"]: field for field in template["fields"]}

    assert fields["setup_variant"]["default"] == "wet setup"
    assert fields["front_air_pressure_psi"]["default"] == 82.5
    assert fields["front_tokens"]["default"] == 3
    assert fields["test_conditions"]["default"] == "Loose and dusty"


def test_custom_session_note_field_builder_slugifies_and_defaults():
    field = build_custom_session_note_field(
        field_name="Shim Stack Notes",
        default_value="Baseline tune",
        existing_ids=["shim_stack_notes"],
    )

    assert field["field_id"] == "shim_stack_notes_2"
    assert field["label"] == "Shim Stack Notes"
    assert field["section"] == "Custom"
    assert field["field_type"] == "string"
    assert field["default"] == "Baseline tune"


def test_remove_import_agent_source_only_updates_app_config(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    source_root = provisioned.source.source_root
    marker = source_root / "keep_me.txt"
    marker.write_text("do not delete", encoding="utf-8")

    updated = remove_import_agent_source(
        app_config_path,
        source_id=provisioned.source.source_id,
    )

    assert updated.sources == ()
    assert load_import_agent_app_config(app_config_path).sources == ()
    assert source_root.exists()
    assert marker.read_text(encoding="utf-8") == "do not delete"


def test_remove_import_agent_source_can_delete_source_folder(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    source_root = provisioned.source.source_root
    marker = source_root / "delete_me.txt"
    marker.write_text("delete me", encoding="utf-8")

    updated = remove_import_agent_source(
        app_config_path,
        source_id=provisioned.source.source_id,
        delete_files=True,
    )

    assert updated.sources == ()
    assert load_import_agent_app_config(app_config_path).sources == ()
    assert not source_root.exists()


def test_remove_import_agent_source_can_delete_readonly_source_folder(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    source_root = provisioned.source.source_root
    done_dir = source_root / "done"
    marker = done_dir / "delete_me.txt"
    marker.write_text("delete me", encoding="utf-8")

    try:
        os.chmod(marker, stat.S_IREAD)
        os.chmod(done_dir, stat.S_IREAD)
        os.chmod(source_root, stat.S_IREAD)

        updated = remove_import_agent_source(
            app_config_path,
            source_id=provisioned.source.source_id,
            delete_files=True,
        )
    finally:
        for path in (marker, done_dir, source_root):
            if path.exists():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)

    assert updated.sources == ()
    assert load_import_agent_app_config(app_config_path).sources == ()
    assert not source_root.exists()


def test_remove_import_agent_source_delete_failure_keeps_app_config(tmp_path, monkeypatch):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )

    def fail_delete(*args, **kwargs):
        raise PermissionError("blocked")

    monkeypatch.setattr(provisioning_module, "_delete_directory_tree", fail_delete)

    with pytest.raises(PermissionError, match="blocked"):
        remove_import_agent_source(
            app_config_path,
            source_id=provisioned.source.source_id,
            delete_files=True,
        )

    loaded = load_import_agent_app_config(app_config_path)
    assert [source.source_id for source in loaded.sources] == [provisioned.source.source_id]
    assert provisioned.source.source_root.exists()


def test_remove_import_agent_library_requires_no_targeting_sources(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )

    with pytest.raises(ValueError, match="source\\(s\\) still target"):
        remove_import_agent_library(
            app_config_path,
            library_id=provisioned.library.library_id,
        )


def test_remove_import_agent_library_can_delete_library_data_without_shared_assets(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    library_dir = provisioned.library.artifacts_dir
    shared_bike_dir = provisioned.library.bike_profiles_dir
    shared_preprocess_dir = provisioned.library.preprocess_profiles_dir
    shared_schema_dir = provisioned.library.event_schemas_dir

    remove_import_agent_source(
        app_config_path,
        source_id=provisioned.source.source_id,
        delete_files=True,
    )
    updated = remove_import_agent_library(
        app_config_path,
        library_id=provisioned.library.library_id,
        delete_files=True,
    )

    assert updated.libraries == ()
    assert load_import_agent_app_config(app_config_path).libraries == ()
    assert not library_dir.exists()
    assert shared_bike_dir.exists()
    assert shared_preprocess_dir.exists()
    assert shared_schema_dir.exists()


def test_remove_import_agent_library_delete_failure_keeps_app_config(tmp_path, monkeypatch):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    provisioned = provision_import_agent_app_setup(
        sources_root=tmp_path / "sources",
        libraries_root=tmp_path / "libraries",
        library_display_name="Alice Library",
        source_display_name="Alice Enduro",
        app_config_path=app_config_path,
    )
    remove_import_agent_source(
        app_config_path,
        source_id=provisioned.source.source_id,
    )

    def fail_delete(*args, **kwargs):
        raise PermissionError("blocked")

    monkeypatch.setattr(provisioning_module, "_delete_library_artifacts_dir", fail_delete)

    with pytest.raises(PermissionError, match="blocked"):
        remove_import_agent_library(
            app_config_path,
            library_id=provisioned.library.library_id,
            delete_files=True,
        )

    loaded = load_import_agent_app_config(app_config_path)
    assert [library.library_id for library in loaded.libraries] == [provisioned.library.library_id]
    assert provisioned.library.artifacts_dir.exists()


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


def test_single_instance_lock_path_is_per_app_config(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"

    lock_path = single_instance_module.single_instance_lock_path(app_config_path)

    assert lock_path == app_config_path.resolve().with_suffix(".json.lock")


def test_single_instance_lock_rejects_second_active_manager_for_same_config(tmp_path):
    app_config_path = tmp_path / "config" / "import_agent_app.json"
    first = single_instance_module.SingleInstanceLock.for_app_config(app_config_path)
    second = single_instance_module.SingleInstanceLock.for_app_config(app_config_path)

    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.release()

    try:
        assert second.acquire() is True
    finally:
        second.release()


def test_single_instance_lock_allows_different_app_configs(tmp_path):
    first = single_instance_module.SingleInstanceLock.for_app_config(tmp_path / "one" / "import_agent_app.json")
    second = single_instance_module.SingleInstanceLock.for_app_config(tmp_path / "two" / "import_agent_app.json")

    try:
        assert first.acquire() is True
        assert second.acquire() is True
    finally:
        second.release()
        first.release()


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
    asset = files("bodaqs_import_manager.import_agent_assets").joinpath("app_icon.png")
    with asset.open("rb") as handle:
        payload = handle.read()

    assert len(payload) > 0


def test_import_agent_window_icon_ico_asset_exists():
    asset = files("bodaqs_import_manager.import_agent_assets").joinpath("app_icon.ico")
    with asset.open("rb") as handle:
        payload = handle.read()

    assert len(payload) > 0


def test_manager_imu_smoke_entry_point_loads_int16_bdq(tmp_path: Path) -> None:
    fixture_path = tmp_path / "imu_int16.bdq"
    fixture_path.write_bytes(imu_int16_bdq_fixture_bytes())

    summary = import_agent_setup_module._smoke_test_imu_bdq(fixture_path)

    assert summary["rows"] == 4
    assert summary["columns"] == 9


def test_manager_imu_smoke_cli_bypasses_desktop_window(monkeypatch, tmp_path: Path) -> None:
    fixture_path = tmp_path / "imu_int16.bdq"
    fixture_path.write_bytes(imu_int16_bdq_fixture_bytes())

    def fail_if_lock_is_created(*args, **kwargs):
        raise AssertionError("smoke-test mode must not enter the desktop single-instance path")

    monkeypatch.setattr(
        import_agent_setup_module.SingleInstanceLock,
        "for_app_config",
        fail_if_lock_is_created,
    )

    assert import_agent_setup_module.main(["--smoke-test-imu-bdq", str(fixture_path)]) == 0


def test_packaged_workbench_launch_uses_sibling_service_directory(monkeypatch, tmp_path: Path) -> None:
    bundle_root = tmp_path / "BODAQS Desktop"
    manager_exe = bundle_root / "manager" / "bodaqs-import-setup.exe"
    service_exe = bundle_root / "service" / "bodaqs-library-service.exe"
    web_root = bundle_root / "service" / "web"
    manager_exe.parent.mkdir(parents=True)
    service_exe.parent.mkdir(parents=True)
    web_root.mkdir()
    manager_exe.touch()
    service_exe.touch()
    (web_root / "index.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(import_agent_setup_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(import_agent_setup_module.sys, "executable", str(manager_exe))
    monkeypatch.setattr(import_agent_setup_module.sys, "platform", "win32")

    service = import_agent_setup_module.LibraryApiServiceProcess(libraries_root=tmp_path / "libraries")
    command, cwd = service._launch_command()

    assert Path(command[0]) == service_exe.resolve()
    assert cwd == service_exe.parent.resolve()
    assert command[command.index("--web-root") + 1] == str(web_root.resolve())


def test_packaged_workbench_layout_smoke_cli_bypasses_desktop_window(monkeypatch, tmp_path: Path) -> None:
    bundle_root = tmp_path / "BODAQS Desktop"
    manager_exe = bundle_root / "manager" / "bodaqs-import-setup.exe"
    service_exe = bundle_root / "service" / "bodaqs-library-service.exe"
    web_root = bundle_root / "service" / "web"
    manager_exe.parent.mkdir(parents=True)
    service_exe.parent.mkdir(parents=True)
    web_root.mkdir()
    manager_exe.touch()
    service_exe.touch()
    (web_root / "index.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(import_agent_setup_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(import_agent_setup_module.sys, "executable", str(manager_exe))
    monkeypatch.setattr(import_agent_setup_module.sys, "platform", "win32")

    def fail_if_lock_is_created(*args, **kwargs):
        raise AssertionError("smoke-test mode must not enter the desktop single-instance path")

    monkeypatch.setattr(
        import_agent_setup_module.SingleInstanceLock,
        "for_app_config",
        fail_if_lock_is_created,
    )

    assert import_agent_setup_module.main(["--smoke-test-workbench-layout"]) == 0


def test_tray_supported_is_false_for_non_windows_platform():
    assert import_agent_tray_module.tray_supported(platform="linux") is False


def test_sync_windows_startup_registration_round_trips_command_with_fake_registry():
    fake_reg = _FakeWinreg()
    command = '"C:\\Program Files\\BODAQS Import Manager\\manager\\bodaqs-import-setup.exe" --startup-launch'

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
    assert (
        fake_reg.values[
            (
                import_agent_startup_module.WINDOWS_RUN_KEY_PATH,
                import_agent_startup_module.WINDOWS_STARTUP_VALUE_NAME,
            )
        ]
        == command
    )

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


def test_sync_windows_startup_registration_removes_legacy_value_name():
    fake_reg = _FakeWinreg()
    legacy_name = import_agent_startup_module.LEGACY_WINDOWS_STARTUP_VALUE_NAMES[0]
    fake_reg.values[
        (
            import_agent_startup_module.WINDOWS_RUN_KEY_PATH,
            legacy_name,
        )
    ] = "legacy command"
    command = '"C:\\Program Files\\BODAQS Import Manager\\manager\\bodaqs-import-setup.exe" --startup-launch'

    import_agent_startup_module.sync_windows_startup_registration(
        enabled=True,
        command=command,
        registry_module=fake_reg,
        platform="win32",
    )

    assert (
        import_agent_startup_module.WINDOWS_RUN_KEY_PATH,
        legacy_name,
    ) not in fake_reg.values


# ---------------------------------------------------------------------------
# macOS startup registration tests
# ---------------------------------------------------------------------------


def test_macos_startup_supported_is_true_for_darwin():
    assert import_agent_startup_module.macos_startup_supported(platform="darwin") is True


def test_macos_startup_supported_is_false_for_non_darwin():
    assert import_agent_startup_module.macos_startup_supported(platform="win32") is False
    assert import_agent_startup_module.macos_startup_supported(platform="linux") is False


def test_macos_launch_agent_path_uses_library_launchagents():
    path = import_agent_startup_module.macos_launch_agent_path(
        home="/Users/Test",
        label="org.bodaqs.importmanager",
    )
    assert path == Path("/Users/Test/Library/LaunchAgents/org.bodaqs.importmanager.plist")


def test_build_macos_launch_agent_plist_includes_required_keys():
    argv = [
        "/open",
        "-a",
        "/Applications/BODAQS Import Manager.app",
        "--args",
        "--app-config",
        "/Users/Test/Library/Application Support/BODAQS/import-agent/import_agent_app.json",
        "--app-config-mode",
        "installed",
        "--startup-launch",
    ]
    plist = import_agent_startup_module.build_macos_launch_agent_plist(argv)

    assert plist["Label"] == "org.bodaqs.importmanager"
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is False
    program_args = plist["ProgramArguments"]
    assert "--startup-launch" in program_args
    assert "--app-config-mode" in program_args
    assert "installed" in program_args
    assert program_args[0] == "/open"


def test_sync_macos_startup_registration_writes_and_removes_plist(tmp_path):
    label = "org.bodaqs.importmanager.test"
    argv = ["/usr/bin/open", "-a", "/Applications/Test.app", "--args", "--startup-launch"]

    # Enable
    applied = import_agent_startup_module.sync_macos_startup_registration(
        enabled=True,
        argv=argv,
        home=tmp_path,
        label=label,
        platform="darwin",
        load_agent=False,
    )
    plist_path = tmp_path / "Library" / "LaunchAgents" / f"{label}.plist"
    assert plist_path.is_file()
    assert applied is not None
    assert "--startup-launch" in applied

    # Disable
    cleared = import_agent_startup_module.sync_macos_startup_registration(
        enabled=False,
        home=tmp_path,
        label=label,
        platform="darwin",
        load_agent=False,
    )
    assert cleared is None
    assert not plist_path.exists()


def test_sync_macos_startup_registration_raises_on_empty_argv(tmp_path):
    with pytest.raises(ValueError, match="non-empty argv"):
        import_agent_startup_module.sync_macos_startup_registration(
            enabled=True,
            argv=None,
            home=tmp_path,
            platform="darwin",
            load_agent=False,
        )


def test_read_macos_startup_registration_returns_none_when_no_plist(tmp_path):
    result = import_agent_startup_module.read_macos_startup_registration(
        home=tmp_path,
        platform="darwin",
    )
    assert result is None


def test_sync_macos_startup_registration_propagates_load_failure(tmp_path, monkeypatch):
    label = "org.bodaqs.importmanager.test"
    argv = ["/usr/bin/open", "-a", "/Applications/Test.app", "--args", "--startup-launch"]

    def fail_bootstrap(plist_path):
        raise RuntimeError("launchctl bootstrap failed (exit 1): malformed plist")

    monkeypatch.setattr(
        import_agent_startup_module, "_macos_load_launch_agent", fail_bootstrap
    )

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        import_agent_startup_module.sync_macos_startup_registration(
            enabled=True,
            argv=argv,
            home=tmp_path,
            label=label,
            platform="darwin",
            load_agent=True,
        )


def test_sync_macos_startup_registration_tolerates_unload_not_loaded(tmp_path, monkeypatch):
    label = "org.bodaqs.importmanager.test"
    argv = ["/usr/bin/open", "-a", "/Applications/Test.app", "--args", "--startup-launch"]

    # _macos_unload_launch_agent should tolerate "not loaded" errors
    unload_called = []
    original_unload = import_agent_startup_module._macos_unload_launch_agent

    def tolerant_unload(lbl):
        unload_called.append(lbl)

    monkeypatch.setattr(import_agent_startup_module, "_macos_unload_launch_agent", tolerant_unload)
    monkeypatch.setattr(
        import_agent_startup_module, "_macos_load_launch_agent", lambda p: None
    )

    applied = import_agent_startup_module.sync_macos_startup_registration(
        enabled=True,
        argv=argv,
        home=tmp_path,
        label=label,
        platform="darwin",
        load_agent=True,
    )
    assert applied is not None
    assert label in unload_called


# ---------------------------------------------------------------------------
# Generic startup wrapper tests
# ---------------------------------------------------------------------------


def test_startup_supported_is_true_for_windows_and_macos():
    assert import_agent_startup_module.startup_supported(platform="win32") is True
    assert import_agent_startup_module.startup_supported(platform="darwin") is True


def test_startup_supported_is_false_for_linux():
    assert import_agent_startup_module.startup_supported(platform="linux") is False


def test_build_startup_command_uses_windows_format_on_windows():
    command = import_agent_startup_module.build_startup_command(
        ["C:\\Program Files\\app.exe", "--flag"],
        platform="win32",
    )
    assert '"C:\\Program Files\\app.exe"' in command


def test_build_startup_command_quotes_paths_on_macos():
    command = import_agent_startup_module.build_startup_command(
        ["/Applications/My App.app", "--flag"],
        platform="darwin",
    )
    assert "/Applications/My App.app" in command
    assert "--flag" in command


def test_sync_startup_registration_noop_on_linux():
    result = import_agent_startup_module.sync_startup_registration(
        enabled=True,
        command="test",
        platform="linux",
    )
    assert result is None


# ---------------------------------------------------------------------------
# Tray tests for macOS
# ---------------------------------------------------------------------------


def test_tray_supported_is_true_for_darwin_when_deps_available():
    # pystray and PIL may or may not be installed in the test environment.
    # Verify the platform gate passes for darwin (deps are checked separately).
    has_pystray = import_agent_tray_module.pystray is not None
    has_pil = import_agent_tray_module.Image is not None
    expected = has_pystray and has_pil
    assert import_agent_tray_module.tray_supported(platform="darwin") is expected


def test_tray_supported_is_false_for_linux():
    assert import_agent_tray_module.tray_supported(platform="linux") is False


def test_import_manager_import_now_guard_allows_watch_start_when_idle():
    window = object.__new__(import_agent_setup_module.ImportAgentManagerWindow)
    window.import_now_thread = None

    assert window._guard_import_now_inactive(action_label="Start Watch") is True


class _FakeSourcesTree:
    def __init__(self) -> None:
        self.columns = (
            "enabled",
            "force_reprocess",
            "display_name",
            "source_type",
            "status",
            "library_name",
            "bike_name",
            "attach_note",
        )
        self.values = [
            "✓",
            "✓",
            "Demo Source",
            "Wi-Fi logger",
            "not checked",
            "Demo Library",
            "Demo Bike",
            "",
        ]

    def __getitem__(self, key: str):
        if key == "columns":
            return self.columns
        raise KeyError(key)

    def exists(self, source_id: str) -> bool:
        return source_id == "source-a"

    def item(self, source_id: str, option: str | None = None, **kwargs):
        assert source_id == "source-a"
        if "values" in kwargs:
            self.values = list(kwargs["values"])
            return None
        if option == "values":
            return tuple(self.values)
        raise AssertionError(f"Unexpected item call: option={option!r}, kwargs={kwargs!r}")


def test_import_manager_source_runtime_status_updates_status_column_not_type_column():
    window = object.__new__(import_agent_setup_module.ImportAgentManagerWindow)
    window._source_runtime_status = {}
    tree = _FakeSourcesTree()
    window.sources_tree = tree

    window._set_source_runtime_status("source-a", "waiting for upload mode")

    assert tree.values[3] == "Wi-Fi logger"
    assert tree.values[4] == "waiting for upload mode"
