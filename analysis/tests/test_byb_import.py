import copy
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))

from bodaqs_analysis.byb import (
    BYBConfigurationError, load_byb_session, load_byb_setup,
    load_byb_snapshot, preprocess_byb_snapshot, validate_byb_config, write_byb_snapshot,
)
from bodaqs_analysis.io_byb import BYBFormatError, RECORD_DTYPE, read_byb
from bodaqs_analysis.import_agent import ImportSourceRunner, load_import_source_config
from bodaqs_analysis.pipeline import preprocess_session
from bodaqs_analysis.session_archive import prepare_session_input, session_input_identity


def recording_bytes(counters=None, n=1601, travel=(170, 65, 150)):
    if counters is None:
        counters = np.arange(n, dtype=np.uint32) + 12345
    n = len(counters)
    rows = np.zeros(n, dtype=RECORD_DTYPE)
    rows["counter"] = counters
    phase = np.arange(n) * 2 * np.pi / 200
    rows["front_counts"] = (1000 + 300 * np.sin(phase)).astype(int)
    rows["rear_counts"] = (3200 - 250 * np.sin(phase)).astype(int)
    rows["latitude_e7"] = -319500000
    rows["longitude_e7"] = 1158600000
    rows["gps_speed_kmh"] = 36
    rows["altitude_m"] = 123
    rows["accel_x_counts"] = -1234
    rows["marker"] = 0xFFFF
    header = bytearray(72)
    header[:7] = bytes((26, 0, 10, 18, 9, 43, 41))
    header[0x16:0x19] = b"MTB"
    header[0x20:0x24] = b"1000"
    trailer = bytearray(2012)
    trailer[:2] = b"\xf0\xf0"
    payload = b"Rider\0Frame\029\0" + b"\0".join(str(v).encode() for v in travel) + b"\0"
    trailer[2:2 + len(payload)] = payload
    return bytes(header) + rows.tobytes()[:-4] + bytes(trailer)


def setup_files(directory, kind="bodaqs_bike_profile", fixed=True):
    directory.mkdir(parents=True, exist_ok=True)
    examples = ROOT / "analysis/config/byb"
    example = "byb_bike_profile.example.json" if kind == "bodaqs_bike_profile" else "byb_leverage.example.json"
    config = json.loads((examples / example).read_text())
    for name in ("example_bike_profile.json", "example.bybLeverage"):
        shutil.copyfile(examples / name, directory / name)
    if fixed:
        config["suspension"]["front"]["zero"] = {"mode": "fixed", "count": 120}
        config["suspension"]["rear"]["zero"] = {"mode": "fixed", "count": 3900}
        config["suspension"]["rear"]["compression_direction"] = "decreasing_counts"
    else:
        for channel in config["suspension"].values():
            channel["zero"] = {"mode": "recording"}
    (directory / "byb.json").write_text(json.dumps(config))
    path = directory / "ride.byb"
    path.write_bytes(recording_bytes())
    return config, path


def make_source(directory, kind="bodaqs_bike_profile"):
    config, recording = setup_files(directory, kind)
    inbox = directory / "inbox"
    inbox.mkdir()
    recording.rename(inbox / recording.name)
    assets = ROOT / "import-manager/bodaqs_import_manager/import_agent_assets"
    profile = json.loads((assets / "preprocess_profile.json").read_text())
    profile["config"]["schema_path"] = "events.yaml"
    profile["config"]["fit_import"]["enabled"] = False
    (directory / "preprocess_profile.json").write_text(json.dumps(profile))
    shutil.copyfile(assets / "event_schema_combined.yaml", directory / "events.yaml")
    # This is intentionally not a usable native profile. BYB must use byb.json.
    source = {"schema": "bodaqs.import_source", "version": 1, "source_id": "byb_test", "artifacts_dir": str(directory / "library"), "preprocess_profile_path": "preprocess_profile.json", "bike_profile_path": "absent_native_bike.json", "logger_timezone": "Australia/Perth", "settle_time_s": 0}
    (directory / "import_source.json").write_text(json.dumps(source))
    return ImportSourceRunner(load_import_source_config(directory)), config


def test_reader_keeps_overlapped_final_record_and_excludes_padding(tmp_path):
    _, path = setup_files(tmp_path)
    recording = read_byb(path)
    assert len(recording.raw) == len(recording.analysis) == 1601
    assert recording.raw.counter.iloc[-1] == 12345 + 1600
    assert recording.analysis.time_s.iloc[-1] == pytest.approx(1.6)
    assert recording.travel == {"front_suspension_mm": 170, "rear_suspension_mm": 65, "rear_wheel_mm": 150}
    assert len(recording.gps) == 17  # Stationary repeated coordinates remain legitimate fixes.
    assert recording.gps.speed_mps.eq(10).all()
    assert recording.raw.accel_x_counts.eq(-1234).all()


@pytest.mark.parametrize("damage", ["sentinel", "alignment", "marker", "date"])
def test_reader_rejects_corrupt_recording(tmp_path, damage):
    data = bytearray(recording_bytes())
    if damage == "sentinel":
        data[-2012] = 0
    elif damage == "alignment":
        data.insert(72, 0)
    elif damage == "marker":
        data[72 + 44] = 0
    else:
        data[2] = 99
    path = tmp_path / "bad.byb"
    path.write_bytes(data)
    with pytest.raises(BYBFormatError):
        read_byb(path)


def test_counter_duplicates_short_skips_gaps_wrap_and_reset(tmp_path):
    path = tmp_path / "timing.byb"
    counters = np.array([123, 124, 125, 125, 126, 127, 129, 129, 130, 200, 201], dtype=np.uint32)
    path.write_bytes(recording_bytes(counters))
    result = read_byb(path)
    assert result.qc["timing"]["duplicate_counters"] == 2
    assert result.analysis.segment_id.nunique() == 2
    assert not result.analysis.time_s.between(.008, .076).any()
    assert result.analysis.time_s.iloc[-1] == pytest.approx(.078)
    path.write_bytes(recording_bytes(np.array([2 ** 32 - 2, 2 ** 32 - 1, 0, 1], dtype=np.uint32)))
    assert read_byb(path).qc["timing"]["counter_wraps"] == 1
    path.write_bytes(recording_bytes(np.array([20, 21, 0, 1], dtype=np.uint32)))
    with pytest.raises(BYBFormatError, match="reset"):
        read_byb(path)


@pytest.mark.parametrize("kind", ["byb_leverage", "bodaqs_bike_profile"])
def test_calibration_geometry_and_zero_survive_shared_pipeline(tmp_path, kind):
    _, path = setup_files(tmp_path, kind)
    session, profile, _ = load_byb_session(path)
    front = "front_shock_dom_suspension [mm]"
    rear = "rear_shock_dom_suspension [mm]"
    assert session["df"][front].iloc[0] == pytest.approx((1000 - 120) * 210 / 4095)
    assert session["df"][rear].iloc[0] == pytest.approx((3900 - 3200) * 80 / 4095)
    processed = preprocess_session(path, zeroing_enabled=True, include_events=False, include_metrics=False)
    assert processed["session"]["df"][front].iloc[0] == session["df"][front].iloc[0]
    assert processed["session"]["meta"]["byb"]["zero_references"]["rear"]["method"] == "fixed"
    assert processed["session"]["meta"]["t0_datetime"] == "2026-10-18T09:43:41+08:00"
    assert "logger_gps" in processed["session"]["stream_dfs"]
    assert processed["session"]["meta"]["gps_sources"]["preferred_source"] == "logger_gps"


def test_recording_zero_short_fallback_and_invalid_counts(tmp_path):
    _, path = setup_files(tmp_path, fixed=False)
    session, _, _ = load_byb_session(path)
    assert session["meta"]["byb"]["zero_references"]["front"]["method"] == "min_window_median"
    path.write_bytes(recording_bytes(n=3))
    session, _, _ = load_byb_session(path)
    assert session["meta"]["byb"]["zero_references"]["front"]["method"] == "fallback_first_value"
    data = bytearray(recording_bytes())
    for i in range(1601):
        data[72 + 48 * i + 4:72 + 48 * i + 6] = b"\xff\xff"
    path.write_bytes(data)
    with pytest.raises(BYBConfigurationError, match="no valid samples"):
        load_byb_session(path)


def test_travel_conflicts_require_explicit_per_fact_override(tmp_path):
    config, path = setup_files(tmp_path)
    path.write_bytes(recording_bytes(travel=(170, 65, 155)))
    with pytest.raises(BYBConfigurationError, match="rear_wheel_mm"):
        load_byb_session(path)
    config["travel_overrides"] = {"rear_wheel_mm": 155}
    (tmp_path / "byb.json").write_text(json.dumps(config))
    session, profile, _ = load_byb_session(path)
    assert session["meta"]["byb"]["travel"]["rear_wheel_mm"]["source"] == "override"
    assert profile["signal_transforms"][1]["lut"][-1]["output"] == 150


def test_rotary_profile_and_ambiguous_front_projection_rejected(tmp_path):
    config, path = setup_files(tmp_path)
    config["front_projection"] = {"head_angle_deg": 64}
    (tmp_path / "byb.json").write_text(json.dumps(config))
    with pytest.raises(BYBConfigurationError, match="Ambiguous front"):
        load_byb_session(path)
    del config["front_projection"]
    (tmp_path / "byb.json").write_text(json.dumps(config))
    profile_path = tmp_path / "example_bike_profile.json"
    profile = json.loads(profile_path.read_text())
    profile["signal_transforms"][1]["input"].update(quantity="ang_disp", unit="deg")
    profile_path.write_text(json.dumps(profile))
    with pytest.raises(BYBConfigurationError, match="rear.*linear"):
        load_byb_session(path)


@pytest.mark.parametrize("edit", [
    lambda c: c.update(version=2),
    lambda c: c.update(smoothing_ms=20),
    lambda c: c["suspension"]["front"].update(sensor_length_mm=0),
    lambda c: c["suspension"]["front"].update(zero={"mode": "fixed"}),
    lambda c: c["suspension"]["front"].update(zero={"mode": "recording", "count": 5}),
    lambda c: c["geometry"].update(path="*.json"),
    lambda c: c.update(timezone="not/a/zone"),
])
def test_configuration_errors(tmp_path, edit):
    config, _ = setup_files(tmp_path)
    edit(config)
    (tmp_path / "byb.json").write_text(json.dumps(config))
    with pytest.raises(BYBConfigurationError):
        load_byb_setup(tmp_path / "byb.json")


def test_strict_json_and_portable_snapshot(tmp_path):
    _, path = setup_files(tmp_path / "source")
    session, profile, setup = load_byb_session(path)
    snapshot = write_byb_snapshot(setup, tmp_path / "snapshot", resolved=session["meta"]["byb"])
    shutil.rmtree(path.parent)
    restored = load_byb_snapshot(snapshot)
    assert restored.identity == setup.identity
    (snapshot.parent / "geometry.json").write_text("{}")
    with pytest.raises(BYBConfigurationError, match="hash mismatch"):
        load_byb_snapshot(snapshot)
    for data in ('{"schema": 1, "schema": 2}', '{"version": NaN}'):
        config = tmp_path / "byb.json"
        config.write_text(data)
        with pytest.raises(BYBConfigurationError):
            load_byb_setup(config)


def test_raw_identity_independent_of_filename_and_setup(tmp_path):
    _, path = setup_files(tmp_path)
    identity = session_input_identity(path)
    renamed = path.with_name("renamed.BYB")
    shutil.copyfile(path, renamed)
    assert identity.source_identity == session_input_identity(renamed).source_identity
    with prepare_session_input(renamed) as prepared:
        assert prepared.source_manifest(source_path="source/input.byb")["input_kind"] == "byb"


@pytest.mark.parametrize("kind", ["byb_leverage", "bodaqs_bike_profile"])
def test_import_manager_end_to_end_and_snapshot_replay(tmp_path, kind):
    runner, config = make_source(tmp_path / "source", kind)
    report = runner.scan_once()
    assert not report["failed"], report
    assert len(report["imported"]) == 1, report
    record = report["imported"][0]
    session_dir = runner.store.session_dir(record["run_id"], record["session_id"])
    manifest = json.loads((session_dir / "manifest.json").read_text())
    assert manifest["source"]["input_kind"] == "byb"
    assert (session_dir / "source/input.byb").is_file()
    snapshot = session_dir / "source/byb/manifest.json"
    (tmp_path / "source" / "byb.json").unlink()
    (tmp_path / "source" / config["geometry"]["path"]).unlink()
    replay = preprocess_byb_snapshot(session_dir / "source/input.byb", snapshot)
    assert replay["session"]["session_id"] == record["session_id"]
    assert not replay["events"].empty
    assert not replay["metrics"].empty
    assert {"compression_byb", "rebound_byb"} <= set(replay["events"]["schema_id"])


def test_configuration_pending_retry_and_deduplication(tmp_path):
    runner, config = make_source(tmp_path)
    (tmp_path / "byb.json").unlink()
    report = runner.scan_once()
    assert len(report["needs_configuration"]) == 1
    assert not report["failed"]
    assert (tmp_path / "inbox/ride.byb").exists()
    (tmp_path / "byb.json").write_text(json.dumps(config))
    report = runner.scan_once()
    assert len(report["imported"]) == 1, report
    shutil.copyfile(tmp_path / "done/ride.byb", tmp_path / "inbox/renamed.byb")
    report = runner.scan_once()
    assert len(report["skipped_succeeded"]) == 1
    config["suspension"]["front"]["zero"]["count"] += 1
    (tmp_path / "byb.json").write_text(json.dumps(config))
    shutil.copyfile(tmp_path / "done/ride.byb", tmp_path / "inbox/changed_setup.byb")
    report = runner.scan_once()
    assert len(report["imported"]) == 1, report


@pytest.mark.parametrize("front,rear", [(True, False), (False, True), (False, False)])
def test_disabled_ends_import_without_fabricated_signals(tmp_path, front, rear):
    runner, config = make_source(tmp_path)
    for end, enabled in (("front", front), ("rear", rear)):
        if not enabled:
            config["suspension"][end] = {"enabled": False}
    (tmp_path / "byb.json").write_text(json.dumps(config))
    report = runner.scan_once()
    assert len(report["imported"]) == 1, report
    result = report["imported"][0]
    directory = runner.store.session_dir(result["run_id"], result["session_id"])
    replay = preprocess_byb_snapshot(directory / "source/input.byb", directory / "source/byb/manifest.json")
    for end, enabled in (("front", front), ("rear", rear)):
        exists = f"{end}_shock_dom_suspension [mm]" in replay["session"]["df"]
        assert exists == enabled


def test_mixed_native_inputs_progress_with_invalid_byb_configuration(tmp_path):
    from test_import_agent import _write_session_archive, _write_bdq_input, _write_bike_profile
    runner, _ = make_source(tmp_path)
    _write_bike_profile(tmp_path / "absent_native_bike.json")
    _write_session_archive(tmp_path / "inbox", stem="native_zip")
    _write_bdq_input(tmp_path / "inbox", stem="native_bdq")
    (tmp_path / "byb.json").write_text("{}")
    report = runner.scan_once()
    assert len(report["imported"]) == 2, report
    assert len(report["needs_configuration"]) == 1
    assert not report["failed"]


def test_frozen_candidate_ignores_live_config_schema_and_profile_edits(tmp_path):
    runner, _ = make_source(tmp_path)
    path = tmp_path / "inbox/ride.byb"
    runner.ensure_runtime_dirs()
    claimed = tmp_path / "staging/ride.byb"
    path.rename(claimed)
    candidate = runner._build_candidate(inbox_archive_path=path, claimed_archive_path=claimed)
    for filename in ("byb.json", "events.yaml", "preprocess_profile.json", "example_bike_profile.json"):
        (tmp_path / filename).write_text("broken live content")
    result = runner.import_candidate(candidate)
    directory = runner.store.session_dir(result["run_id"], result["session_id"])
    replay = preprocess_byb_snapshot(directory / "source/input.byb", directory / "source/byb/manifest.json")
    assert not replay["events"].empty
    assert replay["session"]["meta"]["byb"]["zero_references"]["front"]["count"] == 120


def test_pipeline_filters_do_not_cross_byb_gap(tmp_path):
    _, path = setup_files(tmp_path)
    counters = np.r_[np.arange(600), np.arange(1000, 1600)].astype(np.uint32)
    data = recording_bytes(counters)
    path.write_bytes(data)
    assets = ROOT / "import-manager/bodaqs_import_manager/import_agent_assets"
    cfg = json.loads((assets / "preprocess_profile.json").read_text())["config"]
    cfg["schema_path"] = str(assets / "event_schema_combined.yaml")
    cfg["fit_import"]["enabled"] = False
    before = preprocess_session(path, preprocess_config=cfg, include_events=False, include_metrics=False)["session"]["df"]
    changed = bytearray(data)
    for i in range(600, 1200):
        changed[72 + 48 * i + 4:72 + 48 * i + 6] = (3500).to_bytes(2, "little")
    path.write_bytes(changed)
    after = preprocess_session(path, preprocess_config=cfg, include_events=False, include_metrics=False)["session"]["df"]
    pd.testing.assert_frame_equal(before[before.segment_id == 0], after[after.segment_id == 0])


def test_manager_smoke_entry_point_and_pending_status_without_window(tmp_path, monkeypatch):
    from bodaqs_import_manager import import_agent_setup as manager
    runner, _ = make_source(tmp_path)

    def no_window(*args, **kwargs):
        raise AssertionError("Headless validation must not open a desktop window")

    monkeypatch.setattr(manager.SingleInstanceLock, "for_app_config", no_window)
    assert manager.main(["--smoke-test-byb-source", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "byb_smoke_result.json").read_text())
    assert len(report["imported"]) == 1
    window = manager.ImportAgentManagerWindow.__new__(manager.ImportAgentManagerWindow)
    progress = {"event": "archive_deferred", "reason": "needs_configuration", "error": "Missing geometry", "source_id": "byb_test", "archive_name": "ride.byb"}
    assert window._source_status_from_progress(progress) == "BYB needs configuration"
    assert "Missing geometry" in window._format_import_progress_log(progress, origin="import_now")


def test_discovery_patterns_and_configuration_not_claimed(tmp_path):
    runner, _ = make_source(tmp_path)
    native_config = json.loads((tmp_path / "import_source.json").read_text())
    native_config["inbox_dir"] = "."
    native_config["archive_patterns"] = ["*.json", "*.byb"]
    (tmp_path / "import_source.json").write_text(json.dumps(native_config))
    runner = ImportSourceRunner(load_import_source_config(tmp_path))
    # Compatibility/control/geometry files are never recordings, even under a broad glob.
    assert not any(path.suffix == ".json" for path in runner._discover_archives())


def test_recording_estimator_cannot_use_window_across_gap(tmp_path):
    _, path = setup_files(tmp_path, fixed=False)
    path.write_bytes(recording_bytes(np.r_[np.arange(250), np.arange(1000, 1250)].astype(np.uint32)))
    session, _, _ = load_byb_session(path, preprocess_config={"zero_window_s": .4})
    assert session["meta"]["byb"]["zero_references"]["front"]["method"] == "fallback_first_value"


def test_public_pipeline_honors_explicit_zero_window(tmp_path):
    _, path = setup_files(tmp_path, fixed=False)
    result = preprocess_session(path, zero_window_s=.05, include_events=False, include_metrics=False)
    assert result["session"]["meta"]["byb"]["zero_references"]["front"]["window_s"] == .05


def test_imported_session_is_ready_in_library_api_and_exposes_gps(tmp_path):
    from bodaqs_analysis.library_api import LibraryAdapter
    runner, _ = make_source(tmp_path)
    result = runner.scan_once()["imported"][0]
    root = runner.source.artifacts_dir
    (root / "library_definition.json").write_text(json.dumps({"schema": "bodaqs.import_agent_library", "version": 1, "library_id": "byb_test", "display_name": "BYB test", "artifacts_dir": str(root)}))
    adapter = LibraryAdapter(root.parent)
    row = adapter.get_catalog("byb_test")["rows"][0]
    ref = {key: row[key] for key in ("library_id", "run_id", "session_id", "session_key")}
    gps = adapter.get_session_gps_points("byb_test", ref)
    assert gps["present"] and len(gps["points"]) == 17
    adequacy = adapter.get_analysis_view_adequacy("simple-suspension", {"sessions": [ref]})
    assert adequacy["status"] == "ready"
