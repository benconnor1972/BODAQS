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


def recording_bytes(counters=None, n=1601, travel=(170, 65, 150), trailer_extra=()):
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
    fields = {0: "Example rider", 1: "75 Kg", 7: "Example bike", 8: "L", 9: "29"}
    fields.update({10 + index: str(value) for index, value in enumerate((*travel, *trailer_extra))})
    for index, value in fields.items():
        payload = value.encode("ascii")
        trailer[2 + 30 * index:2 + 30 * index + len(payload)] = payload
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


@pytest.mark.parametrize("extra", [(), (0, 0, 0, 0), (15, 25, 35, 45)])
def test_fixed_trailer_travel_is_independent_of_later_fields(tmp_path, extra):
    path = tmp_path / "fixed_fields.byb"
    path.write_bytes(recording_bytes(travel=(200, 75, 200), trailer_extra=extra))
    result = read_byb(path)
    assert result.travel == {"front_suspension_mm": 200, "rear_suspension_mm": 75, "rear_wheel_mm": 200}
    assert result.qc["trailer"]["layout"] == "fixed_30_byte_fields"
    assert result.qc["trailer"]["bike"] == "Example bike"


def test_compact_trailer_remains_supported(tmp_path):
    data = bytearray(recording_bytes())
    trailer = bytearray(2012)
    trailer[:2] = b"\xf0\xf0"
    payload = b"Example\0Bike\0" + b"29\0" + b"170\0" + b"65\0" + b"150\0"
    trailer[2:2 + len(payload)] = payload
    data[-2012:] = trailer
    path = tmp_path / "compact.byb"
    path.write_bytes(data)
    result = read_byb(path)
    assert result.travel == {"front_suspension_mm": 170, "rear_suspension_mm": 65, "rear_wheel_mm": 150}
    assert result.qc["trailer"]["layout"] == "compact_trailing_travel"


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


@pytest.mark.parametrize("existing_settings", [False, True])
def test_manager_byb_editor_loads_namespace_template_or_existing_settings(tmp_path, monkeypatch, existing_settings):
    from importlib.resources.readers import MultiplexedPath
    from types import SimpleNamespace
    from bodaqs_import_manager import import_agent_setup as manager

    assets = ROOT / "import-manager/bodaqs_import_manager/import_agent_assets"
    expected = (assets / "byb/template.json").read_text(encoding="utf-8")
    if existing_settings:
        expected = '{"existing": "source-specific settings"}\n'
        (tmp_path / "byb.json").write_text(expected, encoding="utf-8")

    def resource_files(package):
        assert package == "bodaqs_import_manager.import_agent_assets"
        assert not existing_settings, "Existing source settings must take precedence"
        # Namespace-package resources have a single-component joinpath on Python 3.11.
        return MultiplexedPath(str(assets))

    class Widget:
        def __init__(self, *args, **kwargs):
            self.text = None

        def insert(self, index, text):
            self.text = text

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    editor = Widget()
    monkeypatch.setattr(manager, "files", resource_files)
    monkeypatch.setattr(manager, "tk", SimpleNamespace(Toplevel=Widget, Text=lambda *a, **kw: editor, StringVar=Widget))
    monkeypatch.setattr(manager, "ttk", SimpleNamespace(Label=Widget, Frame=Widget, Button=Widget))

    def unexpected_error(*args, **kwargs):
        pytest.fail(f"BYB editor failed to open: {args}")

    monkeypatch.setattr(manager.messagebox, "showerror", unexpected_error)
    window = manager.ImportAgentManagerWindow.__new__(manager.ImportAgentManagerWindow)
    window.root = object()
    window._selected_source_config = lambda: SimpleNamespace(source_root=tmp_path, source_id="byb_test")
    opened = []
    window._wait_for_manager_dialog = opened.append
    window._edit_selected_byb_settings()
    assert len(opened) == 1
    assert editor.text == expected
    assert (tmp_path / "byb.json").exists() == existing_settings


@pytest.fixture
def byb_editor_ui(monkeypatch):
    from types import SimpleNamespace
    from bodaqs_import_manager import import_agent_setup as manager

    ui = SimpleNamespace(buttons={}, editors=[], statuses=[], dialogs=[], errors=[], logs=[])

    class Widget:
        def __init__(self, *args, **kwargs):
            self.value = kwargs.get("value", "")
            self.destroyed = False

        def insert(self, index, text):
            self.value = text

        def get(self, *args):
            return self.value

        def set(self, value):
            self.value = value

        def destroy(self):
            self.destroyed = True

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    def capture(collection):
        def create(*args, **kwargs):
            widget = Widget(*args, **kwargs)
            collection.append(widget)
            return widget
        return create

    def button(*args, **kwargs):
        ui.buttons[kwargs["text"]] = kwargs["command"]
        return Widget()

    monkeypatch.setattr(manager, "tk", SimpleNamespace(Toplevel=capture(ui.dialogs), Text=capture(ui.editors), StringVar=capture(ui.statuses)))
    monkeypatch.setattr(manager, "ttk", SimpleNamespace(Label=Widget, Frame=Widget, Button=button))
    monkeypatch.setattr(manager.messagebox, "showerror", lambda *args, **kwargs: ui.errors.append(args))

    def open_editor(source_root):
        window = manager.ImportAgentManagerWindow.__new__(manager.ImportAgentManagerWindow)
        window.root = object()
        window._selected_source_config = lambda: SimpleNamespace(source_root=source_root, source_id="byb_test", logger_timezone="UTC")
        window._append_log = ui.logs.append
        window._wait_for_manager_dialog = lambda dialog: None
        window._edit_selected_byb_settings()
        return ui.editors[-1]

    ui.open = open_editor
    return ui


def test_manager_byb_template_defaults(tmp_path, byb_editor_ui):
    config = json.loads(byb_editor_ui.open(tmp_path).get())
    assert config["suspension"]["front"]["sensor_length_mm"] == 210
    assert config["suspension"]["rear"]["sensor_length_mm"] == 80
    assert config["front_projection"]["head_angle_deg"] == 65
    assert config["timezone"] == "GMT"
    validate_byb_config(config)
    from zoneinfo import ZoneInfo
    assert ZoneInfo(config["timezone"]).utcoffset(None).total_seconds() == 0


@pytest.mark.parametrize("existing_settings", [False, True])
@pytest.mark.parametrize("validate_first", [False, True])
def test_manager_byb_save_persists_edits_with_unresolved_geometry(tmp_path, byb_editor_ui, existing_settings, validate_first):
    path = tmp_path / "byb.json"
    if existing_settings:
        template = ROOT / "import-manager/bodaqs_import_manager/import_agent_assets/byb/template.json"
        original = json.loads(template.read_text())
        original["timezone"] = "Australia/Perth"
        path.write_text(json.dumps(original))
    editor = byb_editor_ui.open(tmp_path)
    config = json.loads(editor.get())
    assert config["timezone"] == ("Australia/Perth" if existing_settings else "GMT")
    config["display_name"] = "Edited setup — saved"
    config["suspension"]["front"]["sensor_length_mm"] = 215
    content = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    editor.set(content)
    if validate_first:
        byb_editor_ui.buttons["Validate"]()
        assert "geometry" in byb_editor_ui.statuses[-1].get()
        assert path.exists() == existing_settings
    byb_editor_ui.buttons["Save"]()
    assert not byb_editor_ui.errors
    assert path.read_bytes() == content.encode("utf-8")
    assert not path.with_suffix(".json.tmp").exists()
    assert byb_editor_ui.dialogs[-1].destroyed
    assert "Saved BYB settings" in byb_editor_ui.logs[-1]
    assert byb_editor_ui.open(tmp_path).get() == content


@pytest.mark.parametrize("invalid_text", ['{"broken":', '[]'])
def test_manager_byb_save_reports_invalid_json_without_overwriting(tmp_path, byb_editor_ui, invalid_text):
    path = tmp_path / "byb.json"
    original = '{"display_name": "Keep this draft"}'
    path.write_text(original)
    byb_editor_ui.open(tmp_path).set(invalid_text)
    byb_editor_ui.buttons["Save"]()
    assert byb_editor_ui.errors and "Could not save BYB settings" in byb_editor_ui.errors[-1][1]
    assert path.read_text() == original
    assert not byb_editor_ui.dialogs[-1].destroyed


def test_manager_byb_save_reports_write_failure(tmp_path, byb_editor_ui, monkeypatch):
    from bodaqs_import_manager import import_agent_setup as manager

    def fail_replace(*args):
        raise PermissionError("test write denied")

    path = tmp_path / "byb.json"
    byb_editor_ui.open(tmp_path)
    monkeypatch.setattr(manager.os, "replace", fail_replace)
    byb_editor_ui.buttons["Save"]()
    assert not path.exists()
    assert "test write denied" in byb_editor_ui.errors[-1][1]
    assert not byb_editor_ui.dialogs[-1].destroyed


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
