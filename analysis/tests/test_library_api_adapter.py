import json
import sys
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pandas.errors import MergeError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ANALYSIS_ROOT = _REPO_ROOT / "analysis"
if str(_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_ROOT))

from bodaqs_analysis.artifacts import ArtifactStore
from bodaqs_analysis.library_api import (
    InvalidRequestError,
    InvalidStudySetError,
    LibraryAdapter,
    LibraryNotFoundError,
    RevisionConflictError,
    SessionDeleteConflictError,
    SignalNotFoundError,
    StudySetNotFoundError,
    TimeseriesUnavailableError,
    derive_object_id,
    export_library_fixture,
    make_session_key,
    make_session_ref_id,
    make_study_set_selector_handle,
    make_unique_object_id,
    parse_session_key,
)
from bodaqs_analysis.library_api.catalog import discover_libraries
from bodaqs_analysis.library_api_service import create_app
from bodaqs_analysis.widgets.contracts import EntitySelectionSnapshot, ScopeEntity, SelectionSnapshot
from bodaqs_analysis.widgets.entity_scope import build_entity_selection_snapshot
from bodaqs_analysis.widgets.metric_widget_data import build_metric_viz_df
from bodaqs_analysis.widgets.session_selector import attach_refresh, make_session_selector
from bodaqs_analysis.library.aggregations import make_default_aggregation_store


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _make_library_definition(
    library_root: Path,
    *,
    library_id: str,
    display_name: str,
) -> None:
    _write_json(
        library_root / "library_definition.json",
        {
            "schema": "bodaqs.import_agent_library",
            "version": 1,
            "library_id": library_id,
            "display_name": display_name,
            "artifacts_dir": str(library_root),
        },
    )


def _make_session(
    library_root: Path,
    run_id: str,
    session_id: str,
    *,
    library_id: str = "default-library",
) -> dict:
    (library_root / "runs" / run_id / "sessions" / session_id).mkdir(parents=True)
    session_key = make_session_key(run_id, session_id)
    return {
        "library_id": library_id,
        "run_id": run_id,
        "session_id": session_id,
        "session_key": session_key,
        "session_ref_id": make_session_ref_id(library_id, session_key),
    }


def _write_catalog_fixture_session(library_root: Path, *, library_id: str = "default-library") -> dict:
    run_id = "run_2026-05-25T13-57-10_LOCAL"
    session_id = "2026-05-18_13-27-14"
    session_ref = _make_session(library_root, run_id, session_id, library_id=library_id)
    session_root = library_root / "runs" / run_id / "sessions" / session_id

    _write_json(
        library_root / "runs" / run_id / "manifest.json",
        {
            "run_id": run_id,
            "created_at": "2026-05-25T13:57:10",
            "description": "Prototype F import",
            "pipeline_config": {
                "import_source": {
                    "source_id": "prototype-f",
                    "source_type": "logger_wifi",
                },
                "archive_import": {
                    "processing_key": "processing-key-1",
                },
            },
        },
    )
    _write_json(
        session_root / "manifest.json",
        {
            "session_id": session_id,
            "description": "Rough descent",
            "source": {
                "import_source_id": "prototype-f",
                "import_source_type": "logger_wifi",
                "original_archive_filename": "2026-02-19_09-43-31_3.zip",
                "processing_key": "processing-key-1",
                "remote_source": {"logger_id": "Prototype F"},
            },
            "summary": {"n_rows": 3, "t_start_s": 0.0, "t_end_s": 2.0},
        },
    )
    _write_json(
        session_root / "session" / "meta.json",
        {
            "t0_datetime": "2026-05-18T05:27:14Z",
            "qc": {"warnings": ["fit_import_failed"]},
            "signals": {
                "time_s": {
                    "quantity": "time",
                    "unit": "s",
                    "domain": "time",
                },
                "front_wheel_disp_dom_wheel [mm]": {
                    "end": "front",
                    "domain": "wheel",
                    "quantity": "disp",
                    "unit": "mm",
                    "processing_role": "primary_analysis",
                    "origin": "analysis",
                },
                "rear_wheel_disp_dom_wheel [mm]": {
                    "end": "rear",
                    "domain": "wheel",
                    "quantity": "disp",
                    "unit": "mm",
                    "processing_role": "primary_analysis",
                    "origin": "analysis",
                },
                "active_mask_qc": {
                    "kind": "qc",
                    "quantity": "mask",
                    "unit": None,
                },
            },
        },
    )
    (session_root / "session").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "time_s": [0.0, 1.0, 2.0],
            "front_wheel_disp_dom_wheel [mm]": [0.0, 10.0, 20.0],
            "rear_wheel_disp_dom_wheel [mm]": [0.0, 12.0, 24.0],
            "active_mask_qc": [True, True, True],
        }
    ).to_parquet(session_root / "session" / "df.parquet", index=False)
    _write_json(
        session_root / "annotations" / "session_notes.json",
        {
            "schema": "bodaqs.session_notes.document",
            "version": 1,
            "run_id": run_id,
            "session_id": session_id,
            "session_key": session_ref["session_key"],
            "template_id": "suspension_setup",
            "template_version": "1.0",
            "title": "Setup notes",
            "values": {"bike": "Prototype F", "rider": "Ben"},
            "custom_values": {},
            "free_text_notes": None,
            "created_at_utc": "2026-05-25T05:57:10Z",
            "updated_at_utc": "2026-05-25T05:57:10Z",
            "draft": True,
        },
    )
    events_root = session_root / "events"
    (events_root / "bottom_out").mkdir(parents=True)
    (events_root / "jump").mkdir(parents=True)
    pd.DataFrame(
        {
            "event_id": ["bottom_out:front:1"],
            "schema_id": ["bottom_out"],
            "event_name": ["Bottom out"],
            "start_time_s": [0.5],
            "end_time_s": [0.7],
        }
    ).to_parquet(events_root / "bottom_out" / "events.parquet", index=False)
    pd.DataFrame(
        {
            "event_id": ["jump:front:1", "jump:rear:1"],
            "schema_id": ["jump", "jump"],
            "event_name": ["Jump", "Jump"],
            "start_time_s": [1.0, 1.5],
            "end_time_s": [1.2, 1.7],
        }
    ).to_parquet(events_root / "jump" / "events.parquet", index=False)
    metrics_root = session_root / "metrics" / "bottom_out"
    metrics_root.mkdir(parents=True)
    pd.DataFrame(
        {
            "session_id": [session_id],
            "event_id": ["bottom_out:front:1"],
            "schema_id": ["bottom_out"],
            "peak_force": [123.0],
            "duration_s": [0.2],
        }
    ).to_parquet(metrics_root / "metrics.parquet", index=False)
    return session_ref


def test_session_selector_can_hide_legacy_aggregations(tmp_path: Path) -> None:
    library_root = tmp_path / "default-library"
    session_ref = _write_catalog_fixture_session(library_root)
    store = make_default_aggregation_store(artifact_store=ArtifactStore(library_root))
    store.create(
        title="Legacy aggregation",
        member_session_keys=[session_ref["session_key"]],
        aggregation_key="legacy-aggregation",
    )
    store.save()

    selector = make_session_selector(
        artifacts_dir=library_root,
        include_aggregations=False,
        autosave_default=False,
    )

    entities = selector["get_selected_entities"]()
    assert entities
    assert {entity.kind for entity in entities} == {"session"}
    assert all("aggregation" not in str(option).lower() for option in selector["entities_sel"].options)


def _write_gps_fit_stream(
    library_root: Path,
    session_ref: dict,
    *,
    times: list[float],
    coordinates: list[tuple[float, float]] | None = None,
) -> None:
    if coordinates is not None and len(coordinates) != len(times):
        raise ValueError("coordinates must contain one lon/lat pair for each time.")
    stream_root = (
        library_root
        / "runs"
        / session_ref["run_id"]
        / "sessions"
        / session_ref["session_id"]
        / "session"
        / "streams"
        / "gps_fit"
    )
    _write_json(
        stream_root / "meta.json",
        {
            "kind": "intermittent",
            "stream_name": "gps_fit",
            "time_col": "time_s",
            "channel_info": {
                "gps_fit_position_latitude_dom_world [deg]": {
                    "role": "position_latitude",
                    "quantity": "latitude",
                    "unit": "deg",
                },
                "gps_fit_position_longitude_dom_world [deg]": {
                    "role": "position_longitude",
                    "quantity": "longitude",
                    "unit": "deg",
                },
                "gps_fit_altitude_dom_world [m]": {
                    "role": "altitude",
                    "quantity": "altitude",
                    "unit": "m",
                },
            },
        },
    )
    pd.DataFrame(
        {
            "time_s": times,
            "gps_fit_position_latitude_dom_world [deg]": [
                coordinates[index][1] if coordinates is not None else -31.95 - (index * 0.0001)
                for index, _ in enumerate(times)
            ],
            "gps_fit_position_longitude_dom_world [deg]": [
                coordinates[index][0] if coordinates is not None else 115.86 + (index * 0.0001)
                for index, _ in enumerate(times)
            ],
            "gps_fit_altitude_dom_world [m]": [200.0 + index for index, _ in enumerate(times)],
        }
    ).to_parquet(stream_root / "df.parquet", index=False)


def test_derive_object_id_from_display_name() -> None:
    assert derive_object_id("Setup Comparison 1") == "setup-comparison-1"
    assert derive_object_id("Ben's Stévo / Prototype F!") == "ben-s-stevo-prototype-f"
    assert derive_object_id("!!!", fallback="Study Set") == "study-set"
    assert derive_object_id("A" * 100, max_length=12) == "a" * 12


def test_make_unique_object_id_adds_suffix() -> None:
    assert make_unique_object_id("Setup", {"setup", "setup-2"}) == "setup-3"
    assert make_unique_object_id("A" * 20, {"a" * 10}, max_length=10) == "aaaaaaaa-2"


def test_session_key_helpers() -> None:
    key = make_session_key("run_1", "session_2")
    assert key == "run_1::session_2"
    assert parse_session_key(key) == ("run_1", "session_2")
    with pytest.raises(ValueError):
        parse_session_key("not-a-session-key")


def test_discover_libraries_reads_library_definition(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )

    discovered = discover_libraries(libraries_root)

    assert len(discovered) == 1
    library = discovered[0]
    assert library["library_id"] == "default-library"
    assert library["display_name"] == "Default Library"
    assert library["root"] == str(library_root.resolve())
    assert library["definition_schema"] == "bodaqs.import_agent_library"
    assert library["capabilities"]["read_processed_library"] is True


def test_discover_libraries_reads_library_definition_under_libraries_child(tmp_path: Path) -> None:
    libraries_root = tmp_path / "workspace"
    library_root = libraries_root / "libraries" / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )

    discovered = discover_libraries(libraries_root)

    assert len(discovered) == 1
    assert discovered[0]["library_id"] == "default-library"
    assert discovered[0]["root"] == str(library_root.resolve())


def test_discover_libraries_falls_back_to_runs_directory(tmp_path: Path) -> None:
    library_root = tmp_path / "libraries" / "Loose Library"
    (library_root / "runs" / "run_1").mkdir(parents=True)
    (tmp_path / "libraries" / "not-a-library").mkdir(parents=True)

    discovered = discover_libraries(tmp_path / "libraries")

    assert [library["library_id"] for library in discovered] == ["loose-library"]
    assert discovered[0]["display_name"] == "Loose Library"


def test_discover_libraries_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(InvalidRequestError) as exc:
        discover_libraries(tmp_path / "missing")

    assert exc.value.code == "invalid_request"
    assert "libraries_root" in exc.value.details


def test_discover_libraries_rejects_duplicate_library_ids(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    _make_library_definition(
        libraries_root / "one",
        library_id="shared",
        display_name="One",
    )
    _make_library_definition(
        libraries_root / "two",
        library_id="shared",
        display_name="Two",
    )

    with pytest.raises(InvalidRequestError) as exc:
        discover_libraries(libraries_root)

    assert exc.value.details["library_id"] == "shared"


def test_library_adapter_capabilities_and_lookup(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    _make_library_definition(
        libraries_root / "default-library",
        library_id="default-library",
        display_name="Default Library",
    )

    adapter = LibraryAdapter(libraries_root)

    capabilities = adapter.capabilities()
    assert capabilities["schema"] == "bodaqs.library_api_capabilities"
    assert capabilities["required"]["read_parquet"] is True
    assert capabilities["features"]["run_processing_jobs"] is False

    libraries = adapter.list_libraries()
    assert [library["library_id"] for library in libraries] == ["default-library"]
    assert adapter.get_library("default-library")["display_name"] == "Default Library"

    with pytest.raises(LibraryNotFoundError) as exc:
        adapter.get_library("unknown")

    assert exc.value.code == "library_not_found"
    assert exc.value.details["library_id"] == "unknown"


def test_library_adapter_refresh_updates_library_cache(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    adapter = LibraryAdapter(libraries_root)

    (libraries_root).mkdir(parents=True)
    assert adapter.list_libraries() == []

    _make_library_definition(
        libraries_root / "new-library",
        library_id="new-library",
        display_name="New Library",
    )

    assert adapter.list_libraries() == []
    refreshed = adapter.list_libraries(refresh=True)
    assert [library["library_id"] for library in refreshed] == ["new-library"]


def test_library_adapter_loads_and_saves_session_note(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    loaded = adapter.load_session_note("default-library", {"session_ref": session_ref})
    assert loaded["schema"] == "bodaqs.library_api.session_note"
    assert loaded["present"] is True
    assert loaded["note"]["values"]["bike"] == "Prototype F"
    assert loaded["note"]["draft"] is True
    assert loaded["template"]["status"] == "ok"
    assert "bike" in {field["field_id"] for field in loaded["template"]["fields"]}

    note = dict(loaded["note"])
    note["values"] = {**note["values"], "bike": "Prototype G", "rider": "Ben"}
    note["free_text_notes"] = "Sag checked before the shuttle laps."
    note["draft"] = False

    saved = adapter.save_session_note(
        "default-library",
        {
            "session_ref": session_ref,
            "note": note,
        },
    )

    assert saved["present"] is True
    assert saved["note"]["values"]["bike"] == "Prototype G"
    assert saved["note"]["free_text_notes"] == "Sag checked before the shuttle laps."
    assert saved["note"]["draft"] is False

    saved_path = (
        library_root
        / "runs"
        / session_ref["run_id"]
        / "sessions"
        / session_ref["session_id"]
        / "annotations"
        / "session_notes.json"
    )
    persisted = _read_json(saved_path)
    assert persisted["values"]["bike"] == "Prototype G"
    assert persisted["draft"] is False

    catalog = adapter.get_catalog("default-library", refresh=True)
    row = catalog["rows"][0]
    assert row["note_status"]["status"] == "edited"
    assert row["note_fields"]["bike"] == "Prototype G"


def test_library_adapter_updates_session_descriptions_and_refreshes_catalog(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    original_catalog = adapter.get_catalog("default-library")
    assert original_catalog["rows"][0]["display"]["run_label"] == "Prototype F import"
    assert original_catalog["rows"][0]["display"]["session_label"] == "Rough descent"

    updated = adapter.update_session_descriptions(
        "default-library",
        {
            "session_ref": session_ref,
            "run_description": "Morning shuttle run",
            "session_description": "Lower chute lap",
        },
    )

    assert updated["schema"] == "bodaqs.library_api.session_descriptions"
    assert updated["updated_fields"] == ["run_description", "session_description"]
    assert updated["run_description"] == "Morning shuttle run"
    assert updated["session_description"] == "Lower chute lap"

    catalog = adapter.get_catalog("default-library")
    row = catalog["rows"][0]
    assert row["display"]["run_label"] == "Morning shuttle run"
    assert row["display"]["session_label"] == "Lower chute lap"

    run_manifest = _read_json(library_root / "runs" / session_ref["run_id"] / "manifest.json")
    session_manifest = _read_json(
        library_root
        / "runs"
        / session_ref["run_id"]
        / "sessions"
        / session_ref["session_id"]
        / "manifest.json"
    )
    assert run_manifest["description"] == "Morning shuttle run"
    assert session_manifest["description"] == "Lower chute lap"


def test_library_adapter_creates_loads_lists_and_deletes_study_set(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    adapter = LibraryAdapter(libraries_root)

    created = adapter.create_study_set(
        "default-library",
        {
            "display_name": "Setup Comparison",
            "sessions": [session_ref],
        },
    )

    study_set_path = libraries_root / "study_sets" / "setup-comparison.json"
    assert created["schema"] == "bodaqs.study_set"
    assert created["version"] == 1
    assert created["study_set_id"] == "setup-comparison"
    assert created["revision"] == 1
    assert created["sessions"] == [session_ref]
    assert study_set_path.exists()

    assert adapter.list_study_sets("default-library") == [
        {
            "study_set_id": "setup-comparison",
            "display_name": "Setup Comparison",
            "revision": 1,
            "updated_at": created["provenance"]["updated_at"],
            "session_count": 1,
            "library_count": 1,
            "grouping_count": 0,
            "track_count": 0,
            "path": str(study_set_path),
        }
    ]
    assert adapter.load_study_set("default-library", "setup-comparison") == created

    assert adapter.delete_study_set("default-library", "setup-comparison") == {
        "deleted": True,
        "study_set_id": "setup-comparison",
    }
    with pytest.raises(StudySetNotFoundError):
        adapter.load_study_set("default-library", "setup-comparison")


def test_library_adapter_reads_and_migrates_legacy_study_set_location(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    legacy_path = libraries_root / "library" / "study_sets" / "legacy-study-set.json"
    _write_json(
        legacy_path,
        {
            "schema": "bodaqs.study_set",
            "version": 1,
            "study_set_id": "legacy-study-set",
            "display_name": "Legacy Study Set",
            "revision": 1,
            "sessions": [session_ref],
            "groupings": [],
            "bookmarks": [],
            "tracks": [],
            "provenance": {
                "created_at": "2026-06-01T00:00:00Z",
                "created_by": "test",
                "created_from": {"kind": "manual_selection", "details": {}},
                "updated_at": "2026-06-01T00:00:00Z",
            },
            "display_state": {"bodaqs_web_v1": {}},
        },
    )
    adapter = LibraryAdapter(libraries_root)

    assert adapter.list_study_sets()[0]["path"] == str(legacy_path)
    loaded = adapter.load_study_set("legacy-study-set")
    assert loaded["display_name"] == "Legacy Study Set"

    loaded["display_name"] = "Migrated Study Set"
    updated = adapter.update_study_set(
        "legacy-study-set",
        expected_revision=1,
        payload=loaded,
    )

    canonical_path = libraries_root / "study_sets" / "legacy-study-set.json"
    assert updated["revision"] == 2
    assert canonical_path.exists()
    assert not legacy_path.exists()


def test_library_adapter_creates_unique_study_set_ids(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    adapter = LibraryAdapter(libraries_root)

    first = adapter.create_study_set(
        "default-library",
        {"display_name": "Setup Comparison", "sessions": [session_ref]},
    )
    second = adapter.create_study_set(
        "default-library",
        {"display_name": "Setup Comparison", "sessions": [session_ref]},
    )

    assert first["study_set_id"] == "setup-comparison"
    assert second["study_set_id"] == "setup-comparison-2"


def test_library_adapter_study_sets_can_span_libraries(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    first_library = libraries_root / "default-library"
    second_library = libraries_root / "second-library"
    _make_library_definition(
        first_library,
        library_id="default-library",
        display_name="Default Library",
    )
    _make_library_definition(
        second_library,
        library_id="second-library",
        display_name="Second Library",
    )
    first_ref = _make_session(first_library, "run_1", "session_1", library_id="default-library")
    second_ref = _make_session(second_library, "run_2", "session_2", library_id="second-library")
    adapter = LibraryAdapter(libraries_root)

    created = adapter.create_study_set(
        {
            "display_name": "Cross Library Comparison",
            "sessions": [first_ref, second_ref],
            "groupings": [
                {
                    "grouping_id": "comparison",
                    "display_name": "Comparison",
                    "session_refs": [first_ref["session_ref_id"], second_ref["session_ref_id"]],
                }
            ],
        },
    )

    assert created["study_set_id"] == "cross-library-comparison"
    assert {session["library_id"] for session in created["sessions"]} == {
        "default-library",
        "second-library",
    }
    assert created["groupings"][0]["session_refs"] == [
        first_ref["session_ref_id"],
        second_ref["session_ref_id"],
    ]
    assert adapter.list_study_sets()[0]["library_count"] == 2


def test_library_adapter_delete_session_blocks_then_cleans_study_set_memberships(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    kept_ref = _make_session(library_root, "run_1", "session_2")
    adapter = LibraryAdapter(libraries_root)
    created = adapter.create_study_set(
        {
            "display_name": "Delete Guard Study Set",
            "sessions": [session_ref, kept_ref],
            "groupings": [
                {
                    "grouping_id": "mixed",
                    "display_name": "Mixed",
                    "session_refs": [session_ref["session_ref_id"], kept_ref["session_ref_id"]],
                },
                {
                    "grouping_id": "deleted-only",
                    "display_name": "Deleted only",
                    "session_refs": [session_ref["session_ref_id"]],
                },
            ],
            "bookmarks": [
                {
                    "bookmark_id": "deleted-start",
                    "display_name": "Deleted start",
                    "session_ref": session_ref["session_ref_id"],
                    "time_s": 0.0,
                }
            ],
        },
    )

    with pytest.raises(SessionDeleteConflictError) as exc:
        adapter.delete_session("default-library", "run_1", "session_1")

    assert exc.value.details["session_ref_id"] == session_ref["session_ref_id"]
    assert exc.value.details["references"][0]["study_set_id"] == created["study_set_id"]
    assert (library_root / "runs" / "run_1" / "sessions" / "session_1").exists()

    deleted = adapter.delete_session(
        "default-library",
        "run_1",
        "session_1",
        cleanup_memberships=True,
    )

    assert deleted["deleted"] is True
    assert deleted["cleanup_memberships"] is True
    assert deleted["session_ref_id"] == session_ref["session_ref_id"]
    assert deleted["updated_study_sets"][0]["study_set_id"] == created["study_set_id"]
    assert deleted["updated_study_sets"][0]["removed_groupings"] == [
        {"grouping_id": "deleted-only", "display_name": "Deleted only"}
    ]
    assert deleted["updated_study_sets"][0]["removed_bookmark_count"] == 1
    assert not (library_root / "runs" / "run_1" / "sessions" / "session_1").exists()

    updated = adapter.load_study_set(created["study_set_id"])
    assert updated["revision"] == 2
    assert [session["session_ref_id"] for session in updated["sessions"]] == [kept_ref["session_ref_id"]]
    assert updated["groupings"] == [
        {
            "grouping_id": "mixed",
            "display_name": "Mixed",
            "session_refs": [kept_ref["session_ref_id"]],
        }
    ]
    assert updated["bookmarks"] == []


def test_library_adapter_updates_study_set_with_revision_check(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    adapter = LibraryAdapter(libraries_root)
    created = adapter.create_study_set(
        "default-library",
        {"display_name": "Setup Comparison", "sessions": [session_ref]},
    )

    updated = adapter.update_study_set(
        "default-library",
        "setup-comparison",
        expected_revision=1,
        payload={
            "display_name": "Setup Comparison Edited",
            "sessions": [session_ref],
            "groupings": [
                {
                    "grouping_id": "baseline",
                    "display_name": "Baseline",
                    "sessions": [session_ref],
                }
            ],
            "bookmarks": [
                {
                    "bookmark_id": "start",
                    "display_name": "Start",
                    "session": session_ref,
                    "time_s": 0.0,
                }
            ],
            "tracks": [
                {
                    "track_id": "test-track",
                    "from_point_id": "gate-a",
                    "to_point_id": "gate-b",
                }
            ],
        },
    )

    assert updated["revision"] == 2
    assert updated["display_name"] == "Setup Comparison Edited"
    assert updated["provenance"]["created_at"] == created["provenance"]["created_at"]
    assert updated["provenance"]["created_by"] == created["provenance"]["created_by"]

    with pytest.raises(RevisionConflictError) as exc:
        adapter.update_study_set(
            "default-library",
            "setup-comparison",
            expected_revision=1,
            payload={"display_name": "Stale Update", "sessions": [session_ref]},
        )

    assert exc.value.details["current_revision"] == 2


def test_library_adapter_session_filter_crud_and_revision_check(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    adapter = LibraryAdapter(libraries_root)

    created = adapter.create_session_filter(
        {
            "display_name": "Ben rides with GPS",
            "description": "Reusable GPS comparison helper.",
            "category": "gps",
            "predicate": {
                "op": "and",
                "children": [
                    {"field": "rider", "op": "contains", "value": "ben"},
                    {"field": "gps.quality", "op": "eq", "value": "usable"},
                ],
            },
        }
    )

    filter_path = libraries_root / "session_filters" / "ben-rides-with-gps.json"
    assert created["schema"] == "bodaqs.session_filter"
    assert created["version"] == 1
    assert created["filter_id"] == "ben-rides-with-gps"
    assert created["revision"] == 1
    assert filter_path.exists()
    assert adapter.list_session_filters()[0]["filter_id"] == "ben-rides-with-gps"
    assert adapter.load_session_filter("ben-rides-with-gps") == created

    updated_payload = dict(created)
    updated_payload["display_name"] = "Ben rides with usable GPS"
    updated_payload["category"] = ""
    updated = adapter.update_session_filter(
        "ben-rides-with-gps",
        expected_revision=1,
        payload=updated_payload,
    )
    assert updated["revision"] == 2
    assert updated["display_name"] == "Ben rides with usable GPS"
    assert updated["category"] == ""

    with pytest.raises(RevisionConflictError) as exc:
        adapter.update_session_filter(
            "ben-rides-with-gps",
            expected_revision=1,
            payload=updated,
        )
    assert exc.value.details["current_revision"] == 2

    assert adapter.delete_session_filter("ben-rides-with-gps") == {
        "deleted": True,
        "filter_id": "ben-rides-with-gps",
    }


def test_library_adapter_session_filter_accepts_trackpoint_crossing_predicate(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    adapter = LibraryAdapter(libraries_root)

    created = adapter.create_session_filter(
        {
            "display_name": "Ben rides through test points",
            "description": "Rider plus trackpoint crossing helper.",
            "category": "riders",
            "predicate": {
                "op": "and",
                "children": [
                    {"field": "rider", "op": "contains", "value": "Ben"},
                    {
                        "field": "trackpoint.crossing",
                        "op": "matches",
                        "value": {
                            "track_id": "ben-stevo-2026-02-19",
                            "trackpoint_ids": ["test", "in-tween", "test-2"],
                            "match_mode": "all",
                            "tolerance_m": 10,
                        },
                    },
                ],
            },
        }
    )

    trackpoint_predicate = created["predicate"]["children"][1]
    assert trackpoint_predicate == {
        "field": "trackpoint.crossing",
        "op": "matches",
        "value": {
            "track_id": "ben-stevo-2026-02-19",
            "trackpoint_ids": ["test", "in-tween", "test-2"],
            "match_mode": "all",
            "tolerance_m": 10.0,
        },
    }


def test_create_study_set_rejects_missing_session(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    adapter = LibraryAdapter(libraries_root)
    missing_session = {
        "library_id": "default-library",
        "run_id": "run_missing",
        "session_id": "session_missing",
        "session_key": make_session_key("run_missing", "session_missing"),
    }
    missing_session["session_ref_id"] = make_session_ref_id(
        missing_session["library_id"],
        missing_session["session_key"],
    )

    with pytest.raises(InvalidStudySetError) as exc:
        adapter.create_study_set(
            "default-library",
            {"display_name": "Broken", "sessions": [missing_session]},
        )

    assert exc.value.code == "invalid_study_set"
    assert exc.value.details["session_key"] == "run_missing::session_missing"
    assert exc.value.details["session_ref_id"] == "default-library|||run_missing::session_missing"


def test_create_study_set_rejects_grouping_outside_top_level_sessions(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    other_session_ref = _make_session(library_root, "run_1", "session_2")
    adapter = LibraryAdapter(libraries_root)

    with pytest.raises(InvalidStudySetError) as exc:
        adapter.create_study_set(
            "default-library",
            {
                "display_name": "Broken Grouping",
                "sessions": [session_ref],
                "groupings": [
                    {
                        "grouping_id": "outside",
                        "display_name": "Outside",
                        "sessions": [other_session_ref],
                    }
                ],
            },
        )

    assert exc.value.details["session_ref_id"] == other_session_ref["session_ref_id"]


def test_create_study_set_validates_bookmark_shape(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    adapter = LibraryAdapter(libraries_root)

    with pytest.raises(InvalidStudySetError):
        adapter.create_study_set(
            "default-library",
            {
                "display_name": "Broken Bookmark",
                "sessions": [session_ref],
                "bookmarks": [
                    {
                        "bookmark_id": "ambiguous",
                        "display_name": "Ambiguous",
                        "session": session_ref,
                        "time_s": 1.0,
                        "time_window": {"start_s": 0.0, "end_s": 2.0},
                    }
                ],
            },
        )

    valid = adapter.create_study_set(
        "default-library",
        {
            "display_name": "Valid Bookmark",
            "sessions": [session_ref],
            "bookmarks": [
                {
                    "bookmark_id": "window",
                    "display_name": "Window",
                    "session": session_ref,
                    "time_window": {"start_s": 0.0, "end_s": 2.0},
                }
            ],
        },
    )

    assert valid["bookmarks"][0]["bookmark_id"] == "window"


def test_library_adapter_builds_catalog_rows_from_artifacts(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    catalog = adapter.get_catalog("default-library")

    assert catalog["schema"] == "bodaqs.session_catalog"
    assert catalog["version"] == 1
    assert catalog["library_id"] == "default-library"
    assert catalog["row_count"] == 1
    row = catalog["rows"][0]
    assert row["schema"] == "bodaqs.session_catalog_row"
    assert row["library_id"] == "default-library"
    assert row["session_key"] == session_ref["session_key"]
    assert row["session_ref_id"] == session_ref["session_ref_id"]
    assert row["display"]["label"] == "Prototype F - Rough descent"
    assert row["timestamps"]["started_at_utc"] == "2026-05-18T05:27:14Z"
    assert row["timestamps"]["processed_at"] == "2026-05-25T13:57:10"
    assert row["note_status"]["status"] == "draft"
    assert row["note_status"]["template_id"] == "suspension_setup"
    assert row["note_fields"] == {"bike": "Prototype F", "rider": "Ben"}
    assert row["qc_summary"] == {
        "status": "warning",
        "warning_count": 1,
        "error_count": 0,
    }
    assert row["provenance"] == {
        "source_type": "logger_wifi",
        "source_id": "prototype-f",
        "logger_id": "Prototype F",
        "archive_name": "2026-02-19_09-43-31_3.zip",
        "processing_key": "processing-key-1",
    }
    assert row["event_schema"]["schema_id"] is None
    assert row["event_schema"]["schema_ids"] == ["bottom_out", "jump"]
    assert row["event_summary"]["total_count"] == 3
    assert row["event_summary"]["by_type"] == {"bottom_out": 1, "jump": 2}
    assert row["metric_summary"] == {
        "metric_count": 2,
        "event_count_with_metrics": 1,
        "schema_ids": ["bottom_out"],
    }

    signal_columns = {signal["column"] for signal in row["available_signals"]}
    assert signal_columns == {
        "front_wheel_disp_dom_wheel [mm]",
        "rear_wheel_disp_dom_wheel [mm]",
        "time_s",
    }
    front_signal = next(
        signal
        for signal in row["available_signals"]
        if signal["column"] == "front_wheel_disp_dom_wheel [mm]"
    )
    assert front_signal["signal_id"] == "front-wheel-disp-mm"
    assert front_signal["display_name"] == "Front Wheel Disp"
    assert front_signal["processing_role"] == "primary_analysis"


def test_library_adapter_catalog_reports_gps_summary_quality(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    _write_gps_fit_stream(library_root, session_ref, times=[-100.0, 0.0, 2.0, 100.0])
    adapter = LibraryAdapter(libraries_root)

    summary = adapter.get_catalog("default-library")["rows"][0]["gps_summary"]

    assert summary["schema"] == "bodaqs.session_gps_summary"
    assert summary["present"] is True
    assert summary["preferred_source"] == "gps_fit"
    assert summary["preferred_source_id"] == "gps_fit"
    assert summary["preferred_source_kind"] == "fit_enrichment"
    assert summary["position_point_count"] == 2
    assert summary["quality"] == "limited"
    assert "gps_low_point_count" in summary["warnings"]
    assert summary == adapter.get_session_gps_summary("default-library", session_ref)

    points = adapter.get_session_gps_points(
        "default-library",
        {
            **session_ref,
            "max_points": 2,
        },
    )
    assert points["schema"] == "bodaqs.session_gps_points"
    assert points["present"] is True
    assert points["source"]["kind"] == "fit_enrichment"
    assert points["sampling"]["source_points"] == 2
    assert points["sampling"]["returned_points"] == 2
    assert [point["time_s"] for point in points["points"]] == [0.0, 2.0]
    assert points["sampling"]["window"] == {"start_s": 0.0, "end_s": 2.0}


def test_library_api_geospatial_endpoints_create_tracks_and_compute_matches(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    _write_gps_fit_stream(
        library_root,
        session_ref,
        times=[0.0, 1.0, 2.0],
        coordinates=[
            (115.86, -31.95),
            (115.8605, -31.95),
            (115.861, -31.95),
        ],
    )
    client = TestClient(create_app(libraries_root))

    policy_response = client.get("/api/v1/geospatial-policies/default-geospatial-policy")
    assert policy_response.status_code == 200
    assert policy_response.json()["schema"] == "bodaqs.geospatial_policy"

    track_payload = {
        "track_id": "test-track",
        "display_name": "Test Track",
        "path": {
            "type": "LineString",
            "length_m": 100.0,
            "coordinates": [
                [115.86, -31.95, 200.0],
                [115.861, -31.95, 201.0],
            ],
        },
        "trackpoints": [
            {
                "trackpoint_id": "start-gate",
                "display_name": "Start gate",
                "station_m": 50.0,
                "position": {
                    "type": "Point",
                    "coordinates": [115.8605, -31.95, 200.0],
                },
            }
        ],
    }
    create_response = client.post("/api/v1/tracks", json=track_payload)
    assert create_response.status_code == 200
    assert create_response.json()["track_id"] == "test-track"
    assert client.get("/api/v1/tracks").json()[0]["track_id"] == "test-track"

    gps_response = client.post(
        "/api/v1/libraries/default-library/sessions/gps-summary",
        json=session_ref,
    )
    assert gps_response.status_code == 200
    assert gps_response.json()["quality"] == "usable"

    points_response = client.post(
        "/api/v1/libraries/default-library/sessions/gps/points",
        json={**session_ref, "max_points": 2},
    )
    assert points_response.status_code == 200
    points = points_response.json()
    assert points["schema"] == "bodaqs.session_gps_points"
    assert points["sampling"]["source_points"] == 3
    assert points["sampling"]["returned_points"] == 2
    assert points["points"][0]["time_s"] == 0.0
    assert points["points"][-1]["time_s"] == 2.0

    match_response = client.post(
        "/api/v1/track-matches/compute",
        json={"track_id": "test-track", "session_ref": session_ref},
    )
    assert match_response.status_code == 200
    match = match_response.json()
    assert match["schema"] == "bodaqs.session_track_match"
    assert match["status"] == "matched"
    assert match["trackpoint_results"][0]["trackpoint_id"] == "start-gate"
    assert match["trackpoint_results"][0]["crossed"] is True
    assert match["trackpoint_results"][0]["crossing_time_s"] == pytest.approx(1.0)


def test_library_adapter_track_match_requires_cutline_crossing(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    _write_gps_fit_stream(
        library_root,
        session_ref,
        times=[0.0, 1.0],
        coordinates=[
            (115.86, -31.95),
            (115.8604, -31.95),
        ],
    )
    adapter = LibraryAdapter(libraries_root)
    adapter.create_track(
        {
            "track_id": "test-track",
            "display_name": "Test Track",
            "path": {
                "type": "LineString",
                "length_m": 100.0,
                "coordinates": [
                    [115.86, -31.95],
                    [115.861, -31.95],
                ],
            },
            "trackpoints": [
                {
                    "trackpoint_id": "late-gate",
                    "display_name": "Late gate",
                    "station_m": 90.0,
                    "position": {"type": "Point", "coordinates": [115.8609, -31.95]},
                }
            ],
        }
    )

    match = adapter.compute_track_match({"track_id": "test-track", "session_ref": session_ref})
    result = match["trackpoint_results"][0]

    assert match["status"] == "partial"
    assert result["trackpoint_id"] == "late-gate"
    assert result["crossed"] is False
    assert result["min_distance_m"] > 5.0


def test_library_adapter_trackpoint_match_query_can_be_cancelled(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)
    adapter.create_track(
        {
            "track_id": "test-track",
            "display_name": "Test Track",
            "path": {
                "type": "LineString",
                "coordinates": [[115.86, -31.95], [115.861, -31.951]],
            },
            "trackpoints": [
                {
                    "trackpoint_id": "start-gate",
                    "display_name": "Start gate",
                    "station_m": 0.0,
                    "position": {"type": "Point", "coordinates": [115.86, -31.95]},
                }
            ],
        }
    )

    query = adapter.create_trackpoint_match_query(
        {
            "scope": {"library_ids": ["default-library"]},
            "track_id": "test-track",
            "trackpoint_ids": ["start-gate"],
            "match_mode": "all",
            "tolerance_m": 5.0,
        }
    )
    assert query["status"] == "queued"
    cancelled = adapter.cancel_trackpoint_match_query(query["query_id"])
    assert cancelled["status"] == "cancelled"

    after_run = adapter.run_trackpoint_match_query(query["query_id"])
    assert after_run["status"] == "cancelled"
    results = adapter.load_trackpoint_match_query_results(query["query_id"])
    assert results["result_count"] == 0


def test_library_api_service_trackpoint_match_query_lifecycle(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    _write_gps_fit_stream(
        library_root,
        session_ref,
        times=[0.0, 1.0, 2.0],
        coordinates=[
            (115.86, -31.95),
            (115.8605, -31.95),
            (115.861, -31.95),
        ],
    )
    client = TestClient(create_app(libraries_root))
    track_payload = {
        "track_id": "test-track",
        "display_name": "Test Track",
        "path": {
            "type": "LineString",
            "length_m": 100.0,
            "coordinates": [
                [115.86, -31.95, 200.0],
                [115.861, -31.95, 201.0],
            ],
        },
        "trackpoints": [
            {
                "trackpoint_id": "start-gate",
                "display_name": "Start gate",
                "station_m": 50.0,
                "position": {
                    "type": "Point",
                    "coordinates": [115.8605, -31.95, 200.0],
                },
            }
        ],
    }
    assert client.post("/api/v1/tracks", json=track_payload).status_code == 200

    create_response = client.post(
        "/api/v1/trackpoint-match-queries",
        json={
            "scope": {"library_ids": ["default-library"]},
            "track_id": "test-track",
            "trackpoint_ids": ["start-gate"],
            "match_mode": "all",
            "tolerance_m": 5.0,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["schema"] == "bodaqs.trackpoint_match_query"
    assert created["candidate_session_count"] == 1

    query_id = created["query_id"]
    status = created
    for _ in range(50):
        status_response = client.get(f"/api/v1/trackpoint-match-queries/{query_id}")
        assert status_response.status_code == 200
        status = status_response.json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert status["processed_session_count"] == 1
    assert status["matched_session_count"] == 1

    results_response = client.get(f"/api/v1/trackpoint-match-queries/{query_id}/results", params={"limit": 1})
    assert results_response.status_code == 200
    results = results_response.json()
    assert results["schema"] == "bodaqs.trackpoint_match_query_results"
    assert results["result_count"] == 1
    assert results["results"][0]["session_ref"]["session_ref_id"] == session_ref["session_ref_id"]
    assert results["results"][0]["matched_trackpoint_ids"] == ["start-gate"]

    repeated = client.post(
        "/api/v1/trackpoint-match-queries",
        json={
            "scope": {"library_ids": ["default-library"]},
            "track_id": "test-track",
            "trackpoint_ids": ["start-gate"],
            "match_mode": "all",
            "tolerance_m": 5.0,
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["query_id"] == query_id


def test_library_adapter_catalog_cache_refreshes_explicitly(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    assert adapter.get_catalog("default-library")["row_count"] == 1

    _make_session(library_root, "run_2", "session_2")
    assert adapter.get_catalog("default-library")["row_count"] == 1
    assert adapter.get_catalog("default-library", refresh=True)["row_count"] == 2


def test_library_adapter_returns_timeseries_window_for_semantic_signals(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    payload = adapter.get_timeseries_window(
        "default-library",
        {
            "session": session_ref,
            "signals": [
                {
                    "selector": {
                        "end": "front",
                        "domain": "wheel",
                        "quantity": "disp",
                        "unit": "mm",
                        "processing_role": "primary_analysis",
                    }
                },
                {
                    "selector": {
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp",
                        "unit": "mm",
                        "processing_role": "primary_analysis",
                    }
                },
            ],
            "window": {"start_s": 0.0, "end_s": 2.0},
            "resolution": {"target_points": 10},
            "include_events": True,
        },
    )

    assert payload["schema"] == "bodaqs.timeseries_window"
    assert payload["version"] == 1
    assert payload["session"] == session_ref
    assert payload["window"] == {
        "requested_start_s": 0.0,
        "requested_end_s": 2.0,
        "returned_start_s": 0.0,
        "returned_end_s": 2.0,
    }
    assert payload["sampling"] == {
        "mode": "raw",
        "source_points": 3,
        "returned_points": 3,
        "target_points": 10,
    }
    assert payload["time"]["column"] == "time_s"
    assert payload["time"]["values"] == [0.0, 1.0, 2.0]
    assert [signal["column"] for signal in payload["signals"]] == [
        "front_wheel_disp_dom_wheel [mm]",
        "rear_wheel_disp_dom_wheel [mm]",
    ]
    assert payload["signals"][0]["values"] == [0.0, 10.0, 20.0]
    assert payload["signals"][1]["values"] == [0.0, 12.0, 24.0]
    assert [event["event_type"] for event in payload["events"]] == [
        "bottom_out",
        "jump",
        "jump",
    ]
    assert payload["events"][0]["display_name"] == "Bottom out"
    assert payload["warnings"] == []


def test_library_adapter_queries_raw_signals_events_and_metrics(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    signals = adapter.query_signals(
        "default-library",
        {
            "sessions": [session_ref],
            "signals": [
                {
                    "role": "front_displacement",
                    "column": "front_wheel_disp_dom_wheel [mm]",
                },
                {
                    "role": "missing",
                    "column": "not_a_real_signal",
                },
            ],
        },
    )

    assert signals["schema"] == "bodaqs.signal_query"
    assert signals["sessions"][0]["sampling"]["mode"] == "raw"
    assert signals["sessions"][0]["sampling"]["distribution_correct"] is True
    assert signals["sessions"][0]["signals"][0]["role"] == "front_displacement"
    assert signals["sessions"][0]["signals"][0]["values"] == [0.0, 10.0, 20.0]
    assert signals["warnings"][0]["role"] == "missing"
    assert signals["warnings"][0]["code"] == "signal_not_found"

    events = adapter.query_events("default-library", {"sessions": [session_ref]})
    assert events["schema"] == "bodaqs.events_query"
    assert events["row_count"] == 3
    assert {row["event_type"] for row in events["rows"]} == {"bottom_out", "jump"}

    metrics = adapter.query_metrics("default-library", {"sessions": [session_ref], "event_types": ["bottom_out"]})
    assert metrics["schema"] == "bodaqs.metrics_query"
    assert metrics["row_count"] == 1
    assert metrics["rows"][0]["fields"]["peak_force"] == 123.0


def test_library_adapter_timeseries_window_downsamples_concrete_columns(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    session_root = (
        library_root
        / "runs"
        / session_ref["run_id"]
        / "sessions"
        / session_ref["session_id"]
    )
    pd.DataFrame(
        {
            "time_s": [float(i) for i in range(20)],
            "front_wheel_disp_dom_wheel [mm]": [float(i) for i in range(20)],
            "rear_wheel_disp_dom_wheel [mm]": [float(20 - i) for i in range(20)],
            "active_mask_qc": [True] * 20,
        }
    ).to_parquet(session_root / "session" / "df.parquet", index=False)
    adapter = LibraryAdapter(libraries_root)

    payload = adapter.get_timeseries_window(
        "default-library",
        {
            "session": session_ref,
            "signals": [{"column": "front_wheel_disp_dom_wheel [mm]"}],
            "resolution": {"target_points": 6},
        },
    )

    assert payload["sampling"]["mode"] == "min_max_bucket"
    assert payload["sampling"]["source_points"] == 20
    assert payload["sampling"]["returned_points"] <= 8
    assert payload["time"]["values"][0] == 0.0
    assert payload["time"]["values"][-1] == 19.0
    assert payload["signals"][0]["values"][0] == 0.0
    assert payload["signals"][0]["values"][-1] == 19.0


def test_library_adapter_timeseries_window_rejects_missing_signal(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    with pytest.raises(SignalNotFoundError):
        adapter.get_timeseries_window(
            "default-library",
            {
                "session": session_ref,
                "signals": [{"column": "not_a_real_signal"}],
            },
        )


def test_library_adapter_timeseries_window_rejects_empty_window(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    with pytest.raises(TimeseriesUnavailableError):
        adapter.get_timeseries_window(
            "default-library",
            {
                "session": session_ref,
                "signals": [{"column": "front_wheel_disp_dom_wheel [mm]"}],
                "window": {"start_s": 99.0, "end_s": 100.0},
            },
        )


def test_export_library_fixture_writes_static_payloads(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    fixture_dir = tmp_path / "fixture"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)

    manifest = export_library_fixture(libraries_root, "default-library", fixture_dir)

    assert manifest["schema"] == "bodaqs.library_api_fixture"
    assert manifest["library_id"] == "default-library"
    assert (fixture_dir / "capabilities.json").exists()
    assert (fixture_dir / "libraries.json").exists()
    assert (fixture_dir / "libraries" / "default-library" / "library.json").exists()
    assert (fixture_dir / "libraries" / "default-library" / "catalog.json").exists()

    study_set_path = (
        fixture_dir
        / "study_sets"
        / "fixture-study-set.json"
    )
    study_set = _read_json(study_set_path)
    assert study_set["study_set_id"] == "fixture-study-set"
    assert study_set["sessions"][0]["session_key"] == session_ref["session_key"]

    study_set_index = _read_json(
        fixture_dir / "study_sets" / "index.json"
    )
    assert study_set_index[0]["path"].endswith("fixture-study-set.json")

    window_index = _read_json(
        fixture_dir / "libraries" / "default-library" / "timeseries_windows" / "index.json"
    )
    window = _read_json(fixture_dir / window_index[0]["path"])
    assert window["schema"] == "bodaqs.timeseries_window"
    assert window["session"] == session_ref
    assert [signal["column"] for signal in window["signals"]] == [
        "front_wheel_disp_dom_wheel [mm]",
        "rear_wheel_disp_dom_wheel [mm]",
    ]
    assert [event["event_type"] for event in window["events"]] == [
        "bottom_out",
        "jump",
        "jump",
    ]


def test_export_library_fixture_uses_existing_study_set(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    fixture_dir = tmp_path / "fixture"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)
    adapter.create_study_set(
        "default-library",
        {
            "study_set_id": "existing-study-set",
            "display_name": "Existing Study Set",
            "sessions": [session_ref],
        },
    )

    export_library_fixture(libraries_root, "default-library", fixture_dir)

    study_set_path = (
        fixture_dir
        / "study_sets"
        / "existing-study-set.json"
    )
    assert _read_json(study_set_path)["display_name"] == "Existing Study Set"


def test_export_library_fixture_rejects_nonempty_output_dir(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    fixture_dir = tmp_path / "fixture"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    _write_catalog_fixture_session(library_root)
    _write_json(fixture_dir / "existing.json", {"already": "here"})

    with pytest.raises(InvalidRequestError):
        export_library_fixture(libraries_root, "default-library", fixture_dir)


def test_study_set_selection_snapshot_bridge_for_plain_sessions(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)
    adapter.create_study_set(
        "default-library",
        {
            "study_set_id": "plain-study-set",
            "display_name": "Plain Study Set",
            "sessions": [session_ref],
        },
    )

    bridge = adapter.study_set_to_selection_snapshot(
        "default-library",
        "plain-study-set",
    )

    assert bridge["schema"] == "bodaqs.study_set_selection_snapshot"
    assert bridge["study_set_id"] == "plain-study-set"
    assert bridge["key_to_ref"] == {
        session_ref["session_key"]: (session_ref["run_id"], session_ref["session_id"])
    }
    assert isinstance(bridge["selection_snapshot"], SelectionSnapshot)
    assert isinstance(bridge["entity_snapshot"], EntitySelectionSnapshot)
    assert bridge["selection_snapshot"].session_keys() == [session_ref["session_key"]]
    assert bridge["events_index_df"].to_dict("records") == [
        {
            "session_key": session_ref["session_key"],
            "run_id": session_ref["run_id"],
            "session_id": session_ref["session_id"],
        }
    ]

    selector_handle = bridge["selector_handle"]
    assert selector_handle["store"].root == library_root
    assert selector_handle["get_selected"]() == [
        {"run_id": session_ref["run_id"], "session_id": session_ref["session_id"]}
    ]
    assert selector_handle["get_selected_entities"]()[0].kind == "session"
    assert selector_handle["get_key_to_ref"]() == bridge["key_to_ref"]
    assert selector_handle["get_events_index_df"]().equals(bridge["events_index_df"])
    entity_snapshot = selector_handle["get_entity_snapshot"]()
    assert entity_snapshot.expanded_session_keys == [session_ref["session_key"]]
    assert entity_snapshot.selected_entities[0].kind == "session"


def test_study_set_selection_snapshot_bridge_resolves_display_name_input(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)
    adapter.create_study_set(
        "default-library",
        {
            "study_set_id": "archie-evedon-26-v2",
            "display_name": "Archie-Evedon-26_v2",
            "sessions": [session_ref],
        },
    )

    assert adapter.resolve_study_set_id("Archie-Evedon-26_v2", library_id="default-library") == (
        "archie-evedon-26-v2"
    )
    assert adapter.resolve_study_set_id("archie-evedon-26_v2", library_id="default-library") == (
        "archie-evedon-26-v2"
    )
    assert adapter.resolve_study_set_id("Archie Evedon 26 v2", library_id="default-library") == (
        "archie-evedon-26-v2"
    )

    bridge = adapter.study_set_to_selection_snapshot(
        "default-library",
        "Archie-Evedon-26_v2",
    )

    assert bridge["study_set_id"] == "archie-evedon-26-v2"
    assert bridge["key_to_ref"] == {
        session_ref["session_key"]: (session_ref["run_id"], session_ref["session_id"])
    }


def test_static_study_set_selector_handle_accepts_refresh_attachment(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)
    adapter.create_study_set(
        "default-library",
        {
            "study_set_id": "plain-study-set",
            "display_name": "Plain Study Set",
            "sessions": [session_ref],
        },
    )
    bridge = adapter.study_set_to_selection_snapshot("default-library", "plain-study-set")

    calls: list[str] = []
    refresh_handle = attach_refresh(
        bridge["selector_handle"],
        rebuild_fns=[lambda: calls.append("rebuilt")],
    )

    refresh_handle["trigger"]()
    refresh_handle["detach"]()
    assert calls == ["rebuilt"]


def test_study_set_chart_scope_selector_defaults_to_first_entity(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    first_ref = _write_catalog_fixture_session(library_root)
    second_ref = _make_session(library_root, "run_2", "session_2")
    adapter = LibraryAdapter(libraries_root)
    adapter.create_study_set(
        "default-library",
        {
            "study_set_id": "grouped-study-set",
            "display_name": "Grouped Study Set",
            "sessions": [first_ref, second_ref],
            "groupings": [
                {
                    "grouping_id": "baseline",
                    "display_name": "Baseline",
                    "sessions": [first_ref],
                }
            ],
        },
    )
    bridge = adapter.study_set_to_selection_snapshot("default-library", "grouped-study-set")

    selector = make_study_set_selector_handle(bridge)

    assert selector["get_key_to_ref"]() == {
        first_ref["session_key"]: (first_ref["run_id"], first_ref["session_id"])
    }
    assert [entity.kind for entity in selector["get_selected_entities"]()] == [
        "study_set_grouping"
    ]

    entities_sel = selector["entities_sel"]
    entities_sel.value = tuple(value for _, value in entities_sel.options)
    assert selector["get_key_to_ref"]() == {
        first_ref["session_key"]: (first_ref["run_id"], first_ref["session_id"]),
        second_ref["session_key"]: (second_ref["run_id"], second_ref["session_id"]),
    }


def test_study_set_selection_snapshot_bridge_maps_groupings_to_entities(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    first_ref = _write_catalog_fixture_session(library_root)
    second_ref = _make_session(library_root, "run_2", "session_2")
    adapter = LibraryAdapter(libraries_root)
    adapter.create_study_set(
        "default-library",
        {
            "study_set_id": "grouped-study-set",
            "display_name": "Grouped Study Set",
            "sessions": [first_ref, second_ref],
            "groupings": [
                {
                    "grouping_id": "baseline",
                    "display_name": "Baseline",
                    "sessions": [first_ref],
                }
            ],
        },
    )

    bridge = adapter.study_set_to_selection_snapshot(
        "default-library",
        "grouped-study-set",
    )

    entity_snapshot = bridge["entity_snapshot"]
    assert [entity.kind for entity in entity_snapshot.selected_entities] == [
        "study_set_grouping",
        "session",
        "session",
    ]
    assert entity_snapshot.selected_entities[0].entity_key == (
        "study_set:grouped-study-set:grouping:baseline"
    )
    assert entity_snapshot.selected_entities[0].member_session_keys == (
        first_ref["session_key"],
    )
    assert entity_snapshot.selected_entities[1].entity_key == first_ref["session_key"]
    assert entity_snapshot.selected_entities[2].entity_key == second_ref["session_key"]
    assert entity_snapshot.entity_to_effective_members == {
        "study_set:grouped-study-set:grouping:baseline": [first_ref["session_key"]],
        first_ref["session_key"]: [first_ref["session_key"]],
        second_ref["session_key"]: [second_ref["session_key"]],
    }
    assert entity_snapshot.expanded_session_keys == [
        first_ref["session_key"],
        second_ref["session_key"],
    ]
    assert entity_snapshot.key_to_ref == {
        first_ref["session_key"]: (first_ref["run_id"], first_ref["session_id"]),
        second_ref["session_key"]: (second_ref["run_id"], second_ref["session_id"]),
    }

    bridge_without_groups = adapter.study_set_to_selection_snapshot(
        "default-library",
        "grouped-study-set",
        include_groupings=False,
    )
    assert [entity.kind for entity in bridge_without_groups["entity_snapshot"].selected_entities] == [
        "session",
        "session",
    ]


def test_entity_selection_snapshot_deduplicates_study_set_grouping_members() -> None:
    key_to_ref = {
        "run_1::session_1": ("run_1", "session_1"),
        "run_1::session_2": ("run_1", "session_2"),
    }
    events_index_df = pd.DataFrame(
        [
            {"session_key": "run_1::session_1", "run_id": "run_1", "session_id": "session_1"},
            {"session_key": "run_1::session_2", "run_id": "run_1", "session_id": "session_2"},
        ]
    )
    snapshot = build_entity_selection_snapshot(
        selected_entities=[
            ScopeEntity(
                entity_key="study_set:demo:grouping:baseline",
                kind="study_set_grouping",
                label="Baseline",
                member_session_keys=("run_1::session_1", "run_1::session_2"),
            ),
            ScopeEntity(
                entity_key="run_1::session_1",
                kind="session",
                label="Session 1",
                member_session_keys=("run_1::session_1",),
            ),
        ],
        key_to_ref=key_to_ref,
        events_index_df=events_index_df,
    )

    assert snapshot.entity_to_effective_members == {
        "study_set:demo:grouping:baseline": ["run_1::session_2"],
        "run_1::session_1": ["run_1::session_1"],
    }
    assert snapshot.expanded_session_keys == ["run_1::session_2", "run_1::session_1"]
    assert snapshot.key_to_ref == key_to_ref

    unreduced_snapshot = build_entity_selection_snapshot(
        selected_entities=snapshot.selected_entities,
        key_to_ref=key_to_ref,
        events_index_df=events_index_df,
        reduce_grouped_overlaps=False,
    )
    assert unreduced_snapshot.entity_to_effective_members[
        "study_set:demo:grouping:baseline"
    ] == ["run_1::session_1", "run_1::session_2"]


def test_metric_viz_join_keeps_overlapping_entity_rows_distinct() -> None:
    events_df = pd.DataFrame(
        [
            {
                "session_key": "run_1::session_1",
                "schema_id": "suspension",
                "event_id": "event_1",
                "signal_col": "front_travel_mm",
                "entity_key": "study_set:demo:grouping:baseline",
                "entity_kind": "study_set_grouping",
                "source_session_key": "run_1::session_1",
            },
            {
                "session_key": "run_1::session_1",
                "schema_id": "suspension",
                "event_id": "event_1",
                "signal_col": "front_travel_mm",
                "entity_key": "run_1::session_1",
                "entity_kind": "session",
                "source_session_key": "run_1::session_1",
            },
        ]
    )
    metrics_df = pd.DataFrame(
        [
            {
                "session_key": "run_1::session_1",
                "schema_id": "suspension",
                "event_id": "event_1",
                "entity_key": "study_set:demo:grouping:baseline",
                "entity_kind": "study_set_grouping",
                "source_session_key": "run_1::session_1",
                "m_peak": 42.0,
            },
            {
                "session_key": "run_1::session_1",
                "schema_id": "suspension",
                "event_id": "event_1",
                "entity_key": "run_1::session_1",
                "entity_kind": "session",
                "source_session_key": "run_1::session_1",
                "m_peak": 42.0,
            },
        ]
    )

    viz_df, metric_cols = build_metric_viz_df(
        events_df=events_df,
        metrics_df=metrics_df,
        session_key_col="session_key",
        event_id_col="event_id",
        schema_id_col="schema_id",
        event_type_col="schema_id",
        signal_col="signal_col",
        include_optional_event_cols=("entity_key", "entity_kind", "source_session_key"),
    )

    assert metric_cols == ["m_peak"]
    assert viz_df["entity_key"].tolist() == [
        "study_set:demo:grouping:baseline",
        "run_1::session_1",
    ]
    assert viz_df["m_peak"].tolist() == [42.0, 42.0]


def test_metric_viz_join_still_rejects_true_duplicate_event_metric_rows() -> None:
    events_df = pd.DataFrame(
        [
            {
                "session_key": "run_1::session_1",
                "schema_id": "suspension",
                "event_id": "event_1",
                "signal_col": "front_travel_mm",
            }
        ]
    )
    metrics_df = pd.DataFrame(
        [
            {
                "session_key": "run_1::session_1",
                "schema_id": "suspension",
                "event_id": "event_1",
                "m_peak": 42.0,
            },
            {
                "session_key": "run_1::session_1",
                "schema_id": "suspension",
                "event_id": "event_1",
                "m_peak": 43.0,
            },
        ]
    )

    with pytest.raises(MergeError):
        build_metric_viz_df(
            events_df=events_df,
            metrics_df=metrics_df,
            session_key_col="session_key",
            event_id_col="event_id",
            schema_id_col="schema_id",
            event_type_col="schema_id",
            signal_col="signal_col",
        )


def test_library_api_service_exposes_core_routes(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    client = TestClient(create_app(libraries_root))

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["features"]["write_study_sets"] is True

    libraries = client.get("/api/v1/libraries")
    assert libraries.status_code == 200
    assert libraries.json()[0]["library_id"] == "default-library"

    library = client.get("/api/v1/libraries/default-library")
    assert library.status_code == 200
    assert library.json()["display_name"] == "Default Library"

    catalog = client.get("/api/v1/libraries/default-library/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["rows"][0]["session_key"] == session_ref["session_key"]

    refresh = client.post("/api/v1/libraries/default-library/refresh")
    assert refresh.status_code == 200
    assert refresh.json()["refreshed"] is True

    note_response = client.post(
        "/api/v1/libraries/default-library/sessions/note",
        json={"session_ref": session_ref},
    )
    assert note_response.status_code == 200
    note_payload = note_response.json()
    assert note_payload["present"] is True
    assert note_payload["note"]["values"]["rider"] == "Ben"

    edited_note = note_payload["note"]
    edited_note["values"] = {**edited_note["values"], "rider": "Alex"}
    edited_note["draft"] = False
    save_note_response = client.put(
        "/api/v1/libraries/default-library/sessions/note",
        json={"session_ref": session_ref, "note": edited_note},
    )
    assert save_note_response.status_code == 200
    assert save_note_response.json()["note"]["values"]["rider"] == "Alex"
    assert save_note_response.json()["note"]["draft"] is False

    description_response = client.put(
        "/api/v1/libraries/default-library/sessions/descriptions",
        json={
            "session_ref": session_ref,
            "run_description": "Service run description",
            "session_description": "Service session description",
        },
    )
    assert description_response.status_code == 200
    assert description_response.json()["schema"] == "bodaqs.library_api.session_descriptions"
    assert description_response.json()["run_description"] == "Service run description"
    assert description_response.json()["session_description"] == "Service session description"

    updated_catalog = client.get("/api/v1/libraries/default-library/catalog")
    assert updated_catalog.status_code == 200
    assert updated_catalog.json()["rows"][0]["display"]["run_label"] == "Service run description"
    assert updated_catalog.json()["rows"][0]["display"]["session_label"] == "Service session description"

    other_libraries_root = tmp_path / "other-libraries"
    other_library_root = other_libraries_root / "field-library"
    _make_library_definition(
        other_library_root,
        library_id="field-library",
        display_name="Field Library",
    )
    other_session_ref = _write_catalog_fixture_session(other_library_root, library_id="field-library")

    switch_root = client.post(
        "/api/v1/config/libraries-root",
        json={"libraries_root": str(other_libraries_root)},
    )
    assert switch_root.status_code == 200
    assert switch_root.json()["updated"] is True
    assert switch_root.json()["library_count"] == 1
    assert switch_root.json()["libraries_root"] == str(other_libraries_root)

    switched_health = client.get("/api/v1/health")
    assert switched_health.status_code == 200
    assert switched_health.json()["libraries_root"] == str(other_libraries_root)

    switched_libraries = client.get("/api/v1/libraries")
    assert switched_libraries.status_code == 200
    assert switched_libraries.json()[0]["library_id"] == "field-library"

    switched_catalog = client.get("/api/v1/libraries/field-library/catalog")
    assert switched_catalog.status_code == 200
    assert switched_catalog.json()["rows"][0]["session_key"] == other_session_ref["session_key"]


def test_library_api_service_study_set_crud_and_revision_conflict(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    client = TestClient(create_app(libraries_root))

    create_response = client.post(
        "/api/v1/study-sets",
        json={
            "display_name": "Service Study Set",
            "sessions": [session_ref],
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["study_set_id"] == "service-study-set"
    assert created["revision"] == 1

    list_response = client.get("/api/v1/study-sets")
    assert list_response.status_code == 200
    assert list_response.json()[0]["study_set_id"] == "service-study-set"

    load_response = client.get("/api/v1/study-sets/service-study-set")
    assert load_response.status_code == 200
    assert load_response.json()["display_name"] == "Service Study Set"

    updated_payload = dict(created)
    updated_payload["display_name"] = "Service Study Set Edited"
    update_response = client.put(
        "/api/v1/study-sets/service-study-set",
        json={"expected_revision": 1, "study_set": updated_payload},
    )
    assert update_response.status_code == 200
    assert update_response.json()["revision"] == 2

    conflict_response = client.put(
        "/api/v1/study-sets/service-study-set",
        json={"expected_revision": 1, "study_set": updated_payload},
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["error"]["code"] == "revision_conflict"

    delete_response = client.delete("/api/v1/study-sets/service-study-set")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "study_set_id": "service-study-set"}


def test_library_api_service_delete_session_conflict_and_cleanup(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    client = TestClient(create_app(libraries_root))

    create_response = client.post(
        "/api/v1/study-sets",
        json={
            "display_name": "Delete Service Study Set",
            "sessions": [session_ref],
            "groupings": [
                {
                    "grouping_id": "only-session",
                    "display_name": "Only session",
                    "session_refs": [session_ref["session_ref_id"]],
                }
            ],
        },
    )
    assert create_response.status_code == 200

    conflict_response = client.delete("/api/v1/libraries/default-library/runs/run_1/sessions/session_1")
    assert conflict_response.status_code == 409
    assert conflict_response.json()["error"]["code"] == "session_delete_conflict"
    assert conflict_response.json()["error"]["details"]["references"][0]["study_set_id"] == "delete-service-study-set"

    cleanup_response = client.delete(
        "/api/v1/libraries/default-library/runs/run_1/sessions/session_1?cleanup_memberships=true"
    )
    assert cleanup_response.status_code == 200
    cleanup_payload = cleanup_response.json()
    assert cleanup_payload["deleted"] is True
    assert cleanup_payload["updated_study_sets"][0]["removed_groupings"] == [
        {"grouping_id": "only-session", "display_name": "Only session"}
    ]
    assert not (library_root / "runs" / "run_1" / "sessions" / "session_1").exists()

    updated_response = client.get("/api/v1/study-sets/delete-service-study-set")
    assert updated_response.status_code == 200
    assert updated_response.json()["sessions"] == []
    assert updated_response.json()["groupings"] == []


def test_library_api_service_session_filter_crud_and_revision_conflict(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    client = TestClient(create_app(libraries_root))

    create_response = client.post(
        "/api/v1/session-filters",
        json={
            "display_name": "Service GPS Filter",
            "description": "Reusable filter from service test.",
            "category": "gps",
            "predicate": {"field": "gps.quality", "op": "eq", "value": "usable"},
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["schema"] == "bodaqs.session_filter"
    assert created["filter_id"] == "service-gps-filter"
    assert created["revision"] == 1

    list_response = client.get("/api/v1/session-filters")
    assert list_response.status_code == 200
    assert list_response.json()[0]["filter_id"] == "service-gps-filter"

    load_response = client.get("/api/v1/session-filters/service-gps-filter")
    assert load_response.status_code == 200
    assert load_response.json()["display_name"] == "Service GPS Filter"

    updated_payload = dict(created)
    updated_payload["display_name"] = "Service Usable GPS Filter"
    updated_payload["category"] = ""
    update_response = client.put(
        "/api/v1/session-filters/service-gps-filter",
        json={"expected_revision": 1, "session_filter": updated_payload},
    )
    assert update_response.status_code == 200
    assert update_response.json()["revision"] == 2
    assert update_response.json()["category"] == ""

    conflict_response = client.put(
        "/api/v1/session-filters/service-gps-filter",
        json={"expected_revision": 1, "session_filter": updated_payload},
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["error"]["code"] == "revision_conflict"

    delete_response = client.delete("/api/v1/session-filters/service-gps-filter")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "filter_id": "service-gps-filter"}


def test_library_api_service_session_filter_accepts_trackpoint_crossing_predicate(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    client = TestClient(create_app(libraries_root))

    create_response = client.post(
        "/api/v1/session-filters",
        json={
            "display_name": "Service Trackpoint Filter",
            "description": "Reusable geospatial filter from service test.",
            "category": "gps",
            "predicate": {
                "op": "and",
                "children": [
                    {"field": "rider", "op": "contains", "value": "Ben"},
                    {
                        "field": "trackpoint.crossing",
                        "op": "matches",
                        "value": {
                            "track_id": "service-track",
                            "trackpoint_ids": ["gate-a"],
                            "match_mode": "all",
                            "tolerance_m": 5,
                        },
                    },
                ],
            },
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["schema"] == "bodaqs.session_filter"
    assert created["predicate"]["children"][1]["op"] == "matches"
    assert created["predicate"]["children"][1]["value"]["track_id"] == "service-track"


def test_library_api_service_timeseries_window_and_error_envelope(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    client = TestClient(create_app(libraries_root))

    window_response = client.post(
        "/api/v1/libraries/default-library/timeseries/window",
        json={
            "session": session_ref,
            "signals": [{"column": "front_wheel_disp_dom_wheel [mm]"}],
            "include_events": True,
        },
    )
    assert window_response.status_code == 200
    window = window_response.json()
    assert window["schema"] == "bodaqs.timeseries_window"
    assert window["signals"][0]["values"] == [0.0, 10.0, 20.0]
    assert [event["event_type"] for event in window["events"]] == [
        "bottom_out",
        "jump",
        "jump",
    ]

    signal_response = client.post(
        "/api/v1/libraries/default-library/signals/query",
        json={
            "sessions": [session_ref],
            "signals": [{"role": "front_displacement", "column": "front_wheel_disp_dom_wheel [mm]"}],
        },
    )
    assert signal_response.status_code == 200
    signal_payload = signal_response.json()
    assert signal_payload["schema"] == "bodaqs.signal_query"
    assert signal_payload["sessions"][0]["signals"][0]["values"] == [0.0, 10.0, 20.0]

    event_response = client.post(
        "/api/v1/libraries/default-library/events/query",
        json={"sessions": [session_ref]},
    )
    assert event_response.status_code == 200
    assert event_response.json()["row_count"] == 3

    metric_response = client.post(
        "/api/v1/libraries/default-library/metrics/query",
        json={"sessions": [session_ref], "event_types": ["bottom_out"]},
    )
    assert metric_response.status_code == 200
    assert metric_response.json()["rows"][0]["fields"]["peak_force"] == 123.0

    missing_response = client.get("/api/v1/libraries/missing-library")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "library_not_found"
